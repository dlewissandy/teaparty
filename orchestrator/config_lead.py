"""Config lead session — multi-turn human-agent conversation for configuration.

The config lead is a direct chat channel between the human and the configuration-lead
agent, scoped to the entity being configured (workgroup, agent, project, or management
level). Each entity has its own persistent conversation.

Conversation ID scheme:
  config:{qualifier}

where qualifier encodes level and entity, e.g.:
  config:management                      → management-level config
  config:project:{slug}                  → project config
  config:wg:{slug}:{name}               → workgroup within project (or empty slug for org)
  config:agent:{slug}:{name}            → agent within project (or empty slug for org)
  config:artifact:{slug}:{encoded-path}  → artifact viewer

The lead agent is 'configuration-lead' in all cases. Project-scoped entities run
with the project directory as cwd.

Issue #371.
"""
from __future__ import annotations

import json
import os
import tempfile

from orchestrator.messaging import (
    ConversationType,
    SqliteMessageBus,
    agent_bus_path,
    make_conversation_id,
)
from orchestrator.office_manager import (
    NON_CONVERSATIONAL_SENDERS,
    _build_mcp_config,
    _extract_slug,
    _iter_stream_events,
)


def config_lead_bus_path(teaparty_home: str) -> str:
    """Return the canonical path to the config lead message database."""
    return agent_bus_path(teaparty_home, 'configuration-lead')


class ConfigLeadSession:
    """Multi-turn conversation session with the configuration-lead agent.

    Scoped to a specific entity (workgroup, agent, project, or management level).
    The qualifier encodes the entity scope; two different qualifiers produce two
    separate conversations, even if they route to the same underlying agent.

    State (Claude session ID, conversation title) is persisted to disk keyed by
    qualifier so --resume works across invocations.
    """

    LEAD = 'configuration-lead'

    def __init__(self, teaparty_home: str, qualifier: str, llm_backend: str = 'claude'):
        self.teaparty_home = os.path.expanduser(teaparty_home)
        self._infra_dir = os.path.join(self.teaparty_home, 'management', 'agents', 'configuration-lead')
        self.qualifier = qualifier
        self._llm_backend = llm_backend
        self.conversation_id = make_conversation_id(ConversationType.CONFIG_LEAD, qualifier)
        self.claude_session_id: str | None = None
        self.conversation_title: str | None = None

        bus_path = config_lead_bus_path(self.teaparty_home)
        os.makedirs(os.path.dirname(bus_path), exist_ok=True)
        self._bus = SqliteMessageBus(bus_path)

    def send_human_message(self, content: str) -> str:
        """Record a human message in the conversation. Returns message ID."""
        return self._bus.send(self.conversation_id, 'human', content)

    def send_agent_message(self, content: str) -> str:
        """Record a config lead message in the conversation. Returns message ID."""
        return self._bus.send(self.conversation_id, self.LEAD, content)

    def get_messages(self, since_timestamp: float = 0.0):
        """Retrieve conversation messages, optionally since a timestamp."""
        return self._bus.receive(self.conversation_id, since_timestamp=since_timestamp)

    def build_context(self) -> str:
        """Build conversation history formatted for the agent prompt."""
        messages = self.get_messages()
        if not messages:
            return ''
        lines = []
        for msg in messages:
            if (msg.sender in NON_CONVERSATIONAL_SENDERS
                    or msg.sender.startswith('unknown:')):
                continue
            role = 'Human' if msg.sender == 'human' else 'Config Lead'
            lines.append(f'{role}: {msg.content}')
        return '\n\n'.join(lines)

    def _state_path(self) -> str:
        safe_id = self.qualifier.replace('/', '-').replace(':', '-').replace(' ', '-')
        return os.path.join(self._infra_dir, f'.config-session-{safe_id}.json')

    def save_state(self) -> None:
        """Persist session state to disk."""
        state = {
            'claude_session_id': self.claude_session_id,
            'qualifier': self.qualifier,
            'conversation_id': self.conversation_id,
            'conversation_title': self.conversation_title,
        }
        state_path = self._state_path()
        os.makedirs(os.path.dirname(state_path), exist_ok=True)
        tmp = state_path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(state, f)
        os.replace(tmp, state_path)

    def load_state(self) -> None:
        """Load session state from disk."""
        state_path = self._state_path()
        try:
            with open(state_path) as f:
                state = json.load(f)
            self.claude_session_id = state.get('claude_session_id')
            self.conversation_title = state.get('conversation_title') or None
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    def _latest_human_message(self) -> str:
        messages = self.get_messages()
        for msg in reversed(messages):
            if msg.sender == 'human':
                return msg.content
        return ''

    async def invoke(self, *, cwd: str) -> str:
        """Invoke the configuration-lead agent to respond to the current conversation.

        Fresh session: sends full conversation history.
        Resumed session: sends only the latest human message via --resume.

        Returns the agent's response text, or '' if invocation fails.
        """
        import asyncio
        from orchestrator.claude_runner import create_runner
        from orchestrator.worktree import ensure_agent_worktree

        self.load_state()
        is_fresh_session = self.claude_session_id is None

        if self.claude_session_id:
            prompt = self._latest_human_message()
        else:
            prompt = self.build_context()

        if not prompt:
            return ''

        # Agent isolation: run in a worktree with a scoped .claude/.
        effective_cwd = await ensure_agent_worktree(
            self.LEAD, cwd, self._infra_dir,
        )

        stream_fd, stream_path = tempfile.mkstemp(suffix='.jsonl', prefix='config-stream-')
        os.close(stream_fd)

        try:
            runner = create_runner(
                prompt,
                cwd=effective_cwd,
                stream_file=stream_path,
                backend=self._llm_backend,
                lead=self.LEAD,
                permission_mode='default',
                settings={
                    'permissions': {
                        'allow': [
                            'mcp__teaparty-config__PinArtifact',
                            'mcp__teaparty-config__UnpinArtifact',
                        ],
                    },
                },
                resume_session=self.claude_session_id,
                mcp_config=_build_mcp_config(cwd),
            )
            result = await runner.run()

            events = list(_iter_stream_events(stream_path, self.LEAD))
            response_text = '\n'.join(c for s, c in events if s == self.LEAD)

            for sender, content in events:
                self._bus.send(self.conversation_id, sender, content)

            if not response_text:
                self.claude_session_id = None
                self.save_state()
                self._bus.send(
                    self.conversation_id,
                    self.LEAD,
                    'I was unable to produce a response (the session may have '
                    'expired). Please send your message again to start a fresh '
                    'session.',
                )

            if response_text and result.session_id:
                self.claude_session_id = result.session_id
                if is_fresh_session and not self.conversation_title:
                    slug = _extract_slug(stream_path, result.session_id, cwd)
                    if slug:
                        self.conversation_title = slug
                self.save_state()

            return response_text
        finally:
            try:
                os.unlink(stream_path)
            except OSError:
                pass
