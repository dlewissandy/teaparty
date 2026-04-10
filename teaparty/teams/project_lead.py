"""Project lead session — multi-turn human-agent conversation with a project lead.

Each registered project has a lead agent. The human talks directly to the lead
to create and manage jobs. The lead runs with the project's directory as cwd
and carries the project's identity.

Conversation ID scheme: lead:{lead_name}:{qualifier}  e.g. lead:pybayes-lead:pybayes-m1abc
"""
from __future__ import annotations

import json
import os
import tempfile

from teaparty.messaging.conversations import (
    ConversationType,
    SqliteMessageBus,
    agent_bus_path,
    make_conversation_id,
)
from teaparty.teams.office_manager import (
    NON_CONVERSATIONAL_SENDERS,
    _extract_slug,
    _make_live_stream_relay,
)


def pl_bus_path(teaparty_home: str, lead_name: str) -> str:
    """Return the canonical path to a project lead's message database."""
    return agent_bus_path(teaparty_home, lead_name)


class ProjectLeadSession:
    """Multi-turn conversation session with a project lead agent.

    The human talks directly to the project lead to propose jobs, check
    status, and manage work within a single project.

    One session per lead per qualifier. State (Claude session ID, title)
    is persisted to disk so --resume works across invocations.
    """

    def __init__(
        self,
        teaparty_home: str,
        lead_name: str,
        qualifier: str,
        llm_backend: str = 'claude',
    ):
        self.teaparty_home = teaparty_home
        self.lead_name = lead_name
        self.qualifier = qualifier
        self._llm_backend = llm_backend
        self._infra_dir = os.path.join(
            teaparty_home, 'management', 'agents', lead_name,
        )
        self.conversation_id = make_conversation_id(
            ConversationType.PROJECT_LEAD, f'{lead_name}:{qualifier}',
        )
        self.claude_session_id: str | None = None
        self.conversation_title: str | None = None

        bus_path = pl_bus_path(teaparty_home, lead_name)
        os.makedirs(os.path.dirname(bus_path), exist_ok=True)
        self._bus = SqliteMessageBus(bus_path)

    def send_human_message(self, content: str) -> str:
        return self._bus.send(self.conversation_id, 'human', content)

    def send_agent_message(self, content: str) -> str:
        return self._bus.send(self.conversation_id, self.lead_name, content)

    def get_messages(self, since_timestamp: float = 0.0):
        return self._bus.receive(
            self.conversation_id, since_timestamp=since_timestamp,
        )

    def build_context(self) -> str:
        messages = self.get_messages()
        if not messages:
            return ''
        lines = []
        for msg in messages:
            if (msg.sender in NON_CONVERSATIONAL_SENDERS
                    or msg.sender.startswith('unknown:')):
                continue
            role = 'Human' if msg.sender == 'human' else self.lead_name
            lines.append(f'{role}: {msg.content}')
        return '\n\n'.join(lines)

    def _state_path(self) -> str:
        safe_id = self.qualifier.replace('/', '-').replace(':', '-').replace(' ', '-')
        return os.path.join(
            self._infra_dir, f'.pl-session-{safe_id}.json',
        )

    def save_state(self) -> None:
        state = {
            'claude_session_id': self.claude_session_id,
            'lead_name': self.lead_name,
            'qualifier': self.qualifier,
            'conversation_id': self.conversation_id,
            'conversation_title': self.conversation_title,
        }
        os.makedirs(os.path.dirname(self._state_path()), exist_ok=True)
        state_path = self._state_path()
        tmp = state_path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(state, f)
        os.replace(tmp, state_path)

    def load_state(self) -> None:
        try:
            with open(self._state_path()) as f:
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
        """Invoke the project lead agent via the unified launcher."""
        from teaparty.runners.launcher import launch
        from teaparty.workspace.worktree import ensure_agent_worktree

        self.load_state()
        is_fresh_session = self.claude_session_id is None

        if self.claude_session_id:
            prompt = self._latest_human_message()
        else:
            prompt = self.build_context()

        if not prompt:
            return ''

        effective_cwd = await ensure_agent_worktree(
            self.lead_name, cwd, self._infra_dir,
        )

        stream_fd, stream_path = tempfile.mkstemp(
            suffix='.jsonl', prefix='pl-stream-',
        )
        os.close(stream_fd)

        stream_callback, events = _make_live_stream_relay(
            self._bus, self.conversation_id, self.lead_name,
        )

        mcp_port = int(os.environ.get('TEAPARTY_BRIDGE_PORT', '9000'))

        try:
            result = await launch(
                agent_name=self.lead_name,
                message=prompt,
                scope='management',
                teaparty_home=self.teaparty_home,
                worktree=effective_cwd,
                resume_session=self.claude_session_id or '',
                mcp_port=mcp_port,
                on_stream_event=stream_callback,
            )

            response_text = '\n'.join(
                c for s, c in events if s == self.lead_name
            )

            if not response_text:
                self.claude_session_id = None
                self.save_state()
                self._bus.send(
                    self.conversation_id,
                    self.lead_name,
                    'I was unable to produce a response (the session may have '
                    'expired). Please send your message again to start a fresh '
                    'session.',
                )

            if response_text and result.session_id:
                self.claude_session_id = result.session_id
                if is_fresh_session and not self.conversation_title:
                    slug = _extract_slug(
                        stream_path, result.session_id, cwd,
                    )
                    if slug:
                        self.conversation_title = slug
                self.save_state()

            return response_text
        finally:
            try:
                os.unlink(stream_path)
            except OSError:
                pass
