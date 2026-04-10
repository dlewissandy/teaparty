"""Unified agent session — one codepath for all agent conversations.

Every agent conversation in TeaParty — OM, project leads, config lead,
project manager, proxy — runs through this single session class. The
session manages the conversation lifecycle: message bus, state persistence
via the launcher's session system, worktree creation, and delegation to
the unified launcher for subprocess execution.

Variable behavior is handled through configuration and hooks, not
subclasses:
- dispatch: agents with rosters get a BusEventListener for Send/Reply
- post_invoke: optional callback after launch (e.g. proxy ACT-R processing)
- build_prompt: optional override for prompt construction (e.g. proxy memory)

Issue #394.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any, Awaitable, Callable

from teaparty.messaging.conversations import (
    ConversationType,
    SqliteMessageBus,
    agent_bus_path,
    make_conversation_id,
)
from teaparty.teams.stream import (
    NON_CONVERSATIONAL_SENDERS,
    _extract_slug,
    _make_live_stream_relay,
)

_log = logging.getLogger('teaparty.teams.session')

# Type for optional hooks
PostInvokeHook = Callable[[str, 'AgentSession'], None]  # (response_text, session)
BuildPromptHook = Callable[['AgentSession', str], str]   # (session, latest_human) -> prompt


class AgentSession:
    """Unified session for any agent conversation.

    One class handles all agent types. Differences are configuration:

    - agent_name: which agent definition to use
    - scope: 'management' or 'project'
    - conversation_type: how the conversation_id is keyed
    - agent_role: the sender label on bus messages
    - dispatches: whether to start a BusEventListener for Send/Reply
    - post_invoke_hook: called after launch with the response text
    - build_prompt_hook: called to build the prompt (overrides default)
    """

    def __init__(
        self,
        teaparty_home: str,
        *,
        agent_name: str,
        scope: str = 'management',
        qualifier: str,
        conversation_type: ConversationType,
        agent_role: str = '',
        llm_backend: str = 'claude',
        dispatches: bool = False,
        post_invoke_hook: PostInvokeHook | None = None,
        build_prompt_hook: BuildPromptHook | None = None,
    ):
        self.teaparty_home = os.path.expanduser(teaparty_home)
        self.agent_name = agent_name
        self.scope = scope
        self.qualifier = qualifier
        self.agent_role = agent_role or agent_name
        self._llm_backend = llm_backend
        self._dispatches = dispatches
        self._post_invoke_hook = post_invoke_hook
        self._build_prompt_hook = build_prompt_hook

        self.conversation_id = make_conversation_id(conversation_type, qualifier)
        self.claude_session_id: str | None = None
        self.conversation_title: str | None = None

        # Message bus
        bus_path = agent_bus_path(self.teaparty_home, agent_name)
        os.makedirs(os.path.dirname(bus_path), exist_ok=True)
        self._bus = SqliteMessageBus(bus_path)

        # Dispatch infrastructure (lazy init)
        self._bus_listener = None
        self._bus_listener_sockets: tuple[str, str, str] | None = None
        self._bus_context_id: str | None = None
        self._dispatch_session = None

    # ── Message bus ──────────────────────────────────────────────────────

    def send_human_message(self, content: str) -> str:
        return self._bus.send(self.conversation_id, 'human', content)

    def send_agent_message(self, content: str) -> str:
        return self._bus.send(self.conversation_id, self.agent_role, content)

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
            role = 'Human' if msg.sender == 'human' else self.agent_role
            lines.append(f'{role}: {msg.content}')
        return '\n\n'.join(lines)

    # ── Session lifecycle (via launcher) ─────────────────────────────────

    def _session_key(self) -> str:
        safe_id = self.qualifier.replace('/', '-').replace(':', '-').replace(' ', '-')
        return f'{self.agent_name}-{safe_id}'

    def save_state(self) -> None:
        from teaparty.runners.launcher import create_session, load_session
        key = self._session_key()
        session = load_session(
            agent_name=self.agent_name, scope=self.scope,
            teaparty_home=self.teaparty_home, session_id=key,
        )
        if session is None:
            session = create_session(
                agent_name=self.agent_name, scope=self.scope,
                teaparty_home=self.teaparty_home, session_id=key,
            )
        meta_path = os.path.join(session.path, 'metadata.json')
        meta = {
            'session_id': session.id,
            'agent_name': session.agent_name,
            'scope': session.scope,
            'claude_session_id': self.claude_session_id or '',
            'conversation_map': session.conversation_map,
            'conversation_title': self.conversation_title or '',
            'qualifier': self.qualifier,
            'conversation_id': self.conversation_id,
        }
        tmp = meta_path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(meta, f, indent=2)
        os.replace(tmp, meta_path)

    def load_state(self) -> None:
        from teaparty.runners.launcher import load_session
        session = load_session(
            agent_name=self.agent_name, scope=self.scope,
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

    # ── Dispatch (Send/Reply) ────────────────────────────────────────────

    async def _ensure_bus_listener(self, cwd: str) -> dict:
        """Start the BusEventListener for agents that dispatch via Send."""
        if self._bus_listener is not None:
            send, reply, close = self._bus_listener_sockets
            return {
                'SEND_SOCKET': send,
                'REPLY_SOCKET': reply,
                'CLOSE_CONV_SOCKET': close,
                'AGENT_ID': self.agent_name,
                'PYTHONPATH': cwd,
            }

        from teaparty.messaging.listener import BusEventListener
        from teaparty.runners.launcher import (
            launch as _launch,
            create_session as _create_session,
            record_child_session as _record_child,
            remove_child_session as _remove_child,
            check_slot_available as _check_slot,
        )

        infra_dir = os.path.join(
            self.teaparty_home, self.scope, 'agents', self.agent_name,
        )
        bus_db_path = os.path.join(infra_dir, 'messages.db')
        repo_root = os.path.dirname(self.teaparty_home)

        if self._dispatch_session is None:
            self._dispatch_session = _create_session(
                agent_name=self.agent_name, scope=self.scope,
                teaparty_home=self.teaparty_home,
            )
        dispatch_session = self._dispatch_session

        async def spawn_fn(member, composite, context_id):
            import subprocess as _sp
            import time as _time
            t0 = _time.monotonic()

            if not _check_slot(dispatch_session):
                _log.warning(
                    '%s spawn_fn: at conversation limit, blocking dispatch to %s',
                    self.agent_name, member,
                )
                return ('', '', 'Dispatch blocked: per-agent conversation limit reached.')

            # Session = worktree (1:1). Create session, worktree inside it.
            child_session = _create_session(
                agent_name=member, scope=self.scope,
                teaparty_home=self.teaparty_home,
            )
            worktree_path = os.path.join(child_session.path, 'worktree')
            wt_result = _sp.run(
                ['git', 'worktree', 'add', '--detach', worktree_path],
                cwd=repo_root, capture_output=True, text=True,
            )
            if wt_result.returncode != 0:
                os.makedirs(worktree_path, exist_ok=True)

            mcp_port = int(os.environ.get('TEAPARTY_BRIDGE_PORT', '9000'))
            result = await _launch(
                agent_name=member, message=composite,
                scope=self.scope, teaparty_home=self.teaparty_home,
                worktree=worktree_path, mcp_port=mcp_port,
            )

            if result.session_id:
                _record_child(dispatch_session,
                              request_id=context_id,
                              child_session_id=result.session_id)

            _log.info('%s spawn_fn: dispatched to %s in %.2fs',
                      self.agent_name, member, _time.monotonic() - t0)
            return (result.session_id, worktree_path, '')

        async def resume_fn(member, composite, session_id, context_id):
            agent_dir = ''
            if os.path.exists(bus_db_path) and context_id:
                bus = SqliteMessageBus(bus_db_path)
                try:
                    ctx = bus.get_agent_context(context_id)
                    if ctx:
                        agent_dir = ctx.get('agent_worktree_path', '')
                finally:
                    bus.close()
            if not agent_dir:
                agent_dir = repo_root

            mcp_port = int(os.environ.get('TEAPARTY_BRIDGE_PORT', '9000'))
            result = await _launch(
                agent_name=member, message=composite,
                scope=self.scope, teaparty_home=self.teaparty_home,
                worktree=agent_dir, resume_session=session_id,
                mcp_port=mcp_port,
            )
            return result.session_id

        async def reply_fn(context_id, session_id, message):
            _log.info('%s reply_fn: delivering reply for context %s',
                      self.agent_name, context_id)
            self._bus.send(self.conversation_id, self.agent_role, message)
            _remove_child(dispatch_session, request_id=context_id)

        async def reinvoke_fn(context_id, session_id, message):
            _log.info('%s reinvoke_fn: fan-in complete for context %s',
                      self.agent_name, context_id)

        async def cleanup_fn(worktree_path):
            import subprocess as _sp
            if worktree_path and os.path.isdir(worktree_path):
                _sp.run(
                    ['git', 'worktree', 'remove', '--force', worktree_path],
                    cwd=repo_root, capture_output=True,
                )

        if not self._bus_context_id:
            self._bus_context_id = f'agent:{self.agent_name}:lead:{uuid.uuid4()}'
            bus = SqliteMessageBus(bus_db_path)
            try:
                bus.create_agent_context(
                    self._bus_context_id,
                    initiator_agent_id=self.agent_name,
                    recipient_agent_id=self.agent_name,
                )
            finally:
                bus.close()

        self._bus_listener = BusEventListener(
            bus_db_path=bus_db_path,
            initiator_agent_id=self.agent_name,
            current_context_id=self._bus_context_id,
            spawn_fn=spawn_fn,
            resume_fn=resume_fn,
            reply_fn=reply_fn,
            reinvoke_fn=reinvoke_fn,
            cleanup_fn=cleanup_fn,
        )
        sockets = await self._bus_listener.start()
        self._bus_listener_sockets = sockets

        from teaparty.mcp.registry import register_spawn_fn
        register_spawn_fn(self.agent_name, spawn_fn)

        send, reply, close = sockets
        return {
            'SEND_SOCKET': send,
            'REPLY_SOCKET': reply,
            'CLOSE_CONV_SOCKET': close,
            'AGENT_ID': self.agent_name,
            'PYTHONPATH': cwd,
        }

    async def stop(self):
        """Stop the bus event listener. Call on session teardown."""
        if self._bus_listener is not None:
            await self._bus_listener.stop()
            self._bus_listener = None
            self._bus_listener_sockets = None

    # ── Invoke ───────────────────────────────────────────────────────────

    async def invoke(self, *, cwd: str) -> str:
        """Invoke the agent via the unified launcher.

        The one invoke path for all agents:
        1. Load state
        2. Build prompt (fresh or resume)
        3. Create/load session, create worktree inside it
        4. Start bus listener if agent dispatches
        5. Launch via unified launcher
        6. Detect poisoned session / empty response
        7. Run post_invoke_hook if provided
        8. Save state
        """
        import time as _time
        from teaparty.runners.launcher import (
            launch, detect_poisoned_session,
            create_session as _create_session, load_session as _load_session,
        )
        from teaparty.workspace.worktree import ensure_agent_worktree

        t_start = _time.monotonic()
        self.load_state()

        # Handle /clear
        latest = self._latest_human_message()
        if latest.strip() == '/clear':
            self.claude_session_id = None
            self.save_state()
            msg = 'Session cleared.'
            self._bus.send(self.conversation_id, self.agent_role, msg)
            return msg

        is_fresh_session = self.claude_session_id is None

        # Build prompt — use hook if provided, else standard pattern
        if self._build_prompt_hook:
            prompt = self._build_prompt_hook(self, latest)
        elif self.claude_session_id:
            prompt = self._latest_human_message()
        else:
            prompt = self.build_context()

        if not prompt:
            return ''

        # Session = worktree (1:1). Create session dir, worktree inside it.
        session_key = self._session_key()
        session = _load_session(
            agent_name=self.agent_name, scope=self.scope,
            teaparty_home=self.teaparty_home, session_id=session_key,
        )
        if session is None:
            session = _create_session(
                agent_name=self.agent_name, scope=self.scope,
                teaparty_home=self.teaparty_home, session_id=session_key,
            )

        infra_dir = os.path.join(
            self.teaparty_home, self.scope, 'agents', self.agent_name,
        )
        effective_cwd = await ensure_agent_worktree(
            self.agent_name, cwd, infra_dir,
            session_path=session.path,
        )

        # Start bus listener for agents that dispatch
        if self._dispatches:
            await self._ensure_bus_listener(cwd)

        # Stream events to bus in real-time
        stream_callback, events = _make_live_stream_relay(
            self._bus, self.conversation_id, self.agent_role,
        )

        # The launcher writes stream events to {worktree}/.stream.jsonl.
        # We read the slug from that same file after launch completes.
        stream_path = os.path.join(effective_cwd, '.stream.jsonl')

        mcp_port = int(os.environ.get('TEAPARTY_BRIDGE_PORT', '9000'))

        result = await launch(
            agent_name=self.agent_name,
            message=prompt,
            scope=self.scope,
            teaparty_home=self.teaparty_home,
            worktree=effective_cwd,
            resume_session=self.claude_session_id or '',
            mcp_port=mcp_port,
            on_stream_event=stream_callback,
        )

        response_text = '\n'.join(
            c for s, c in events if s == self.agent_role
        )

        # Poisoned session detection (all agents, not just OM)
        system_events = []
        for sender, content in events:
            if sender == 'system':
                try:
                    system_events.append(json.loads(content))
                except (ValueError, json.JSONDecodeError):
                    pass
        if detect_poisoned_session(system_events):
            _log.warning(
                '%s: MCP server failed — clearing session', self.agent_name,
            )
            self.claude_session_id = None
            self.save_state()

        if not response_text:
            self.claude_session_id = None
            self.save_state()
            self._bus.send(
                self.conversation_id,
                self.agent_role,
                'I was unable to produce a response (the session may have '
                'expired). Please send your message again to start a fresh '
                'session.',
            )

        # Post-invoke hook (e.g. proxy ACT-R correction processing)
        if response_text and self._post_invoke_hook:
            self._post_invoke_hook(response_text, self)

        if response_text and result.session_id:
            self.claude_session_id = result.session_id
            if is_fresh_session and not self.conversation_title:
                slug = _extract_slug(stream_path, result.session_id, cwd)
                if slug:
                    self.conversation_title = slug
            self.save_state()

        _log.info(
            '%s invoke: %.2fs response_len=%d',
            self.agent_name, _time.monotonic() - t_start, len(response_text),
        )
        return response_text


# ── Session title reader ─────────────────────────────────────────────────────

def read_session_title(
    teaparty_home: str,
    agent_name: str,
    qualifier: str,
    scope: str = 'management',
) -> str | None:
    """Read the conversation title from a saved session's metadata.json."""
    safe_id = qualifier.replace('/', '-').replace(':', '-').replace(' ', '-')
    session_key = f'{agent_name}-{safe_id}'
    sessions_dir = os.path.join(teaparty_home, scope, 'sessions')
    meta_path = os.path.join(sessions_dir, session_key, 'metadata.json')
    try:
        with open(meta_path) as f:
            state = json.load(f)
        return state.get('conversation_title') or None
    except (FileNotFoundError, json.JSONDecodeError):
        return None
