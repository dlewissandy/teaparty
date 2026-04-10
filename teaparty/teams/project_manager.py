"""Project manager session — multi-turn human-agent conversation scoped to a project.

Each registered project has its own project manager. The project manager is the
same underlying agent definition as the office manager, but runs with the project's
directory as cwd, carries the project's identity as its lead name, and coordinates
the project's own team rather than org-level liaisons.

Conversation ID scheme: pm:{project_slug}:{user_id}  e.g. pm:jainai:darrell
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import uuid

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


def pm_bus_path(teaparty_home: str) -> str:
    """Return the canonical path to the project manager message database."""
    return agent_bus_path(teaparty_home, 'project-manager')


def read_pm_session_title(teaparty_home: str, project_slug: str, user_id: str) -> str | None:
    """Read the conversation title from a saved PM session state file."""
    qualifier = f'{project_slug}:{user_id}'
    safe_id = qualifier.replace('/', '-').replace(':', '-').replace(' ', '-')
    sessions_dir = os.path.join(teaparty_home, 'management', 'sessions')
    state_path = os.path.join(sessions_dir, f'pm-{safe_id}', 'metadata.json')
    try:
        with open(state_path) as f:
            state = json.load(f)
        return state.get('conversation_title') or None
    except (FileNotFoundError, json.JSONDecodeError):
        return None


class ProjectManagerSession:
    """Multi-turn conversation session with a project manager agent.

    The project manager is the management agent running in a project's context:
    - cwd is the project directory
    - lead name is '{slug}-project-manager'
    - conversation ID is 'pm:{slug}:{user_id}'

    One session per project per user. State (Claude session ID, title) is
    persisted to disk keyed by project slug and user so --resume works across
    invocations.
    """

    def __init__(self, teaparty_home: str, project_slug: str, user_id: str,
                 llm_backend: str = 'claude'):
        self.teaparty_home = teaparty_home
        self.project_slug = project_slug
        self.user_id = user_id
        self._llm_backend = llm_backend
        self._infra_dir = os.path.join(teaparty_home, 'management', 'agents', 'project-manager')
        self.lead = f'{project_slug}-project-manager'
        self.conversation_id = make_conversation_id(
            ConversationType.PROJECT_MANAGER, f'{project_slug}:{user_id}',
        )
        self.claude_session_id: str | None = None
        self.conversation_title: str | None = None

        bus_path = pm_bus_path(teaparty_home)
        os.makedirs(os.path.dirname(bus_path), exist_ok=True)
        self._bus = SqliteMessageBus(bus_path)

    def send_human_message(self, content: str) -> str:
        return self._bus.send(self.conversation_id, 'human', content)

    def send_agent_message(self, content: str) -> str:
        return self._bus.send(self.conversation_id, self.lead, content)

    def get_messages(self, since_timestamp: float = 0.0):
        return self._bus.receive(self.conversation_id, since_timestamp=since_timestamp)

    def build_context(self) -> str:
        messages = self.get_messages()
        if not messages:
            return ''
        lines = []
        for msg in messages:
            if (msg.sender in NON_CONVERSATIONAL_SENDERS
                    or msg.sender.startswith('unknown:')):
                continue
            role = 'Human' if msg.sender == 'human' else 'Project Manager'
            lines.append(f'{role}: {msg.content}')
        return '\n\n'.join(lines)

    def _session_key(self) -> str:
        qualifier = f'{self.project_slug}:{self.user_id}'
        safe_id = qualifier.replace('/', '-').replace(':', '-').replace(' ', '-')
        return f'pm-{safe_id}'

    def save_state(self) -> None:
        from teaparty.runners.launcher import create_session, load_session
        key = self._session_key()
        session = load_session(
            agent_name=self.lead, scope='management',
            teaparty_home=self.teaparty_home, session_id=key,
        )
        if session is None:
            session = create_session(
                agent_name=self.lead, scope='management',
                teaparty_home=self.teaparty_home, session_id=key,
            )
        meta_path = os.path.join(session.path, 'metadata.json')
        meta = {
            'session_id': session.id, 'agent_name': session.agent_name,
            'scope': session.scope,
            'claude_session_id': self.claude_session_id or '',
            'conversation_map': session.conversation_map,
            'conversation_title': self.conversation_title or '',
        }
        tmp = meta_path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(meta, f, indent=2)
        os.replace(tmp, meta_path)

    def load_state(self) -> None:
        from teaparty.runners.launcher import load_session
        session = load_session(
            agent_name=self.lead, scope='management',
            teaparty_home=self.teaparty_home, session_id=self._session_key(),
        )
        if session is not None:
            self.claude_session_id = session.claude_session_id or None
            meta_path = os.path.join(session.path, 'metadata.json')
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                self.conversation_title = meta.get('conversation_title') or None
            except (FileNotFoundError, json.JSONDecodeError):
                pass

    def _latest_human_message(self) -> str:
        messages = self.get_messages()
        for msg in reversed(messages):
            if msg.sender == 'human':
                return msg.content
        return ''

    async def invoke(self, *, cwd: str) -> str:
        """Invoke the project manager agent via the unified launcher."""
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
            self.lead, cwd, self._infra_dir,
        )

        stream_fd, stream_path = tempfile.mkstemp(suffix='.jsonl', prefix='pm-stream-')
        os.close(stream_fd)

        stream_callback, events = _make_live_stream_relay(
            self._bus, self.conversation_id, self.lead,
        )

        mcp_port = int(os.environ.get('TEAPARTY_BRIDGE_PORT', '9000'))

        try:
            result = await launch(
                agent_name=self.lead,
                message=prompt,
                scope='management',
                teaparty_home=self.teaparty_home,
                worktree=effective_cwd,
                resume_session=self.claude_session_id or '',
                mcp_port=mcp_port,
                on_stream_event=stream_callback,
            )

            response_text = '\n'.join(c for s, c in events if s == self.lead)

            if not response_text:
                self.claude_session_id = None
                self.save_state()
                self._bus.send(
                    self.conversation_id,
                    self.lead,
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
