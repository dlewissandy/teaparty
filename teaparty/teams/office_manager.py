"""Office manager session — multi-turn human-agent conversation.

The office manager is a team lead one level above projects. It coordinates
across projects via Send/Reply dispatch, synthesizes status, records durable
preferences via memory-based steering, and takes direct intervention actions.

Runtime: a `claude -p` agent invoked via CLI. Multi-turn via `--resume`.
Not persistent between conversations — fresh agent with persistent memory
each time.

Issue #201.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from enum import Enum

from teaparty.messaging.conversations import (
    ConversationType,
    SqliteMessageBus,
    agent_bus_path,
    make_conversation_id,
)


# ── Path helpers ────────────────────────────────────────────────────────────

def om_bus_path(teaparty_home: str) -> str:
    """Return the canonical path to the office manager's message database."""
    return agent_bus_path(teaparty_home, 'office-manager')


# ── Memory chunk types ──────────────────────────────────────────────────────

class MemoryChunkType(Enum):
    """ACT-R memory chunk types for the office manager.

    These are recorded to the shared .proxy-memory.db alongside the proxy's
    gate_outcome chunks. Type discriminates reads — the proxy queries for
    gate_outcome, the office manager queries for inquiry and steering.
    """
    INQUIRY = 'inquiry'
    STEERING = 'steering'
    ACTION_REQUEST = 'action_request'
    CONTEXT_INJECTION = 'context_injection'


# ── Memory store ────────────────────────────────────────────────────────────

class MemoryStore:
    """SQLite-backed memory chunk store for the office manager and proxy.

    Same database as the proxy's .proxy-memory.db. Chunk type discriminates
    reads. SQLite WAL mode handles concurrent access.

    This is a transitional implementation. When the ACT-R memory engine
    lands (issue #198), this store will be replaced by ACT-R's activation-
    based retrieval. The schema is designed to be forward-compatible.
    """

    def __init__(self, db_path: str):
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.execute('PRAGMA journal_mode=WAL')
        self._conn.execute('''
            CREATE TABLE IF NOT EXISTS memory_chunks (
                id TEXT PRIMARY KEY,
                chunk_type TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
        ''')
        self._conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_chunks_type '
            'ON memory_chunks (chunk_type)'
        )
        self._conn.commit()

    def record(self, chunk_type: str, content: str, source: str) -> str:
        """Record a memory chunk. Returns the chunk ID."""
        chunk_id = uuid.uuid4().hex
        ts = time.time()
        self._conn.execute(
            'INSERT INTO memory_chunks (id, chunk_type, content, source, timestamp) '
            'VALUES (?, ?, ?, ?, ?)',
            (chunk_id, chunk_type, content, source, ts),
        )
        self._conn.commit()
        return chunk_id

    def retrieve(self, chunk_type: str | None = None) -> list[dict]:
        """Retrieve memory chunks, optionally filtered by type."""
        if chunk_type:
            cursor = self._conn.execute(
                'SELECT id, chunk_type, content, source, timestamp '
                'FROM memory_chunks WHERE chunk_type = ? '
                'ORDER BY timestamp ASC',
                (chunk_type,),
            )
        else:
            cursor = self._conn.execute(
                'SELECT id, chunk_type, content, source, timestamp '
                'FROM memory_chunks ORDER BY timestamp ASC'
            )
        return [
            {
                'id': row[0],
                'chunk_type': row[1],
                'content': row[2],
                'source': row[3],
                'timestamp': row[4],
            }
            for row in cursor.fetchall()
        ]

    def record_steering(
        self, *, content: str, source: str, current_interaction: int,
    ) -> str:
        """Record a steering chunk into proxy_chunks for cross-conversation learning.

        Steering chunks are stored as MemoryChunk objects in the proxy's
        proxy_chunks table so that activation-based retrieval surfaces them
        at gates when context matches.
        """
        from teaparty.proxy.memory import (
            open_proxy_db,
            record_steering_chunk,
        )
        proxy_conn = open_proxy_db(self._db_path)
        try:
            chunk_id = record_steering_chunk(
                proxy_conn,
                content=content,
                source=source,
                current_interaction=current_interaction,
            )
            return chunk_id
        finally:
            proxy_conn.close()

    def get_gate_outcomes(self, *, task_type: str = ''):
        """Read gate_outcome chunks from proxy_chunks for status reporting."""
        from teaparty.proxy.memory import (
            open_proxy_db,
            query_gate_outcomes,
        )
        proxy_conn = open_proxy_db(self._db_path)
        try:
            return query_gate_outcomes(proxy_conn, task_type=task_type)
        finally:
            proxy_conn.close()

    def close(self) -> None:
        self._conn.close()


# ── Stream parsing ──────────────────────────────────────────────────────────

def _extract_slug(stream_path: str, session_id: str, cwd: str) -> str:
    """Extract the conversation slug Claude auto-generates for this session.

    Tries the stream JSONL first (any event with a 'slug' field), then falls
    back to Claude's history file (~/.claude/projects/{hash}/{session_id}.jsonl).
    Returns '' if not found.
    """
    # Try stream file
    try:
        with open(stream_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except (ValueError, json.JSONDecodeError):
                    continue
                slug = ev.get('slug', '')
                if slug:
                    return slug
    except OSError:
        pass

    # Fall back to Claude's history JSONL
    if session_id and cwd:
        project_hash = cwd.replace('/', '-')
        history_path = os.path.join(
            os.path.expanduser('~'), '.claude', 'projects',
            project_hash, f'{session_id}.jsonl',
        )
        try:
            with open(history_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except (ValueError, json.JSONDecodeError):
                        continue
                    slug = ev.get('slug', '')
                    if slug:
                        return slug
        except OSError:
            pass

    return ''


def _classify_event(ev: dict, agent_role: str,
                    seen_tool_use: set[str],
                    seen_tool_result: set[str]):
    """Yield (sender, content) pairs for a single stream-json event dict.

    Maps stream event types to bus sender labels:
    - thinking block   → ('thinking', text)
    - text block       → (agent_role, text)
    - tool_use block   → ('tool_use', JSON of name+input)
    - tool_result event → ('tool_result', content text or JSON)
    - system event     → ('system', JSON of event)
    - unknown block    → ('unknown:<type>', JSON of block)

    Deduplicates tool_use and tool_result by their IDs.
    """
    ev_type = ev.get('type', '')

    if ev_type == 'assistant':
        for block in ev.get('message', {}).get('content', []):
            if not isinstance(block, dict):
                continue
            block_type = block.get('type', '')
            if block_type == 'thinking':
                text = block.get('thinking', '').strip()
                if text:
                    yield 'thinking', text
            elif block_type == 'text':
                text = block.get('text', '').strip()
                if text:
                    yield agent_role, text
            elif block_type == 'tool_use':
                tid = block.get('id', '')
                if tid and tid not in seen_tool_use:
                    seen_tool_use.add(tid)
                    yield 'tool_use', json.dumps({
                        'name': block.get('name', ''),
                        'input': block.get('input', {}),
                    })
            else:
                yield f'unknown:{block_type}', json.dumps(block)

    elif ev_type == 'tool_use':
        tid = ev.get('tool_use_id', '')
        if not tid or tid not in seen_tool_use:
            if tid:
                seen_tool_use.add(tid)
            yield 'tool_use', json.dumps({
                'name': ev.get('name', ''),
                'input': ev.get('input', {}),
            })

    elif ev_type == 'tool_result':
        tid = ev.get('tool_use_id', '')
        if not tid or tid not in seen_tool_result:
            if tid:
                seen_tool_result.add(tid)
            raw = ev.get('content', '')
            yield 'tool_result', raw if isinstance(raw, str) else json.dumps(raw)

    elif ev_type == 'user':
        content = ev.get('message', {}).get('content', [])
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get('type') == 'tool_result':
                    tid = block.get('tool_use_id', '')
                    if not tid or tid not in seen_tool_result:
                        if tid:
                            seen_tool_result.add(tid)
                        raw = block.get('content', '')
                        yield 'tool_result', raw if isinstance(raw, str) else json.dumps(raw)

    elif ev_type == 'system':
        yield 'system', json.dumps(ev)

    elif ev_type == 'result':
        stats = {k: ev[k] for k in (
            'total_cost_usd', 'duration_ms', 'input_tokens', 'output_tokens'
        ) if k in ev}
        if stats:
            yield 'cost', json.dumps(stats)


def _iter_stream_events(stream_path: str, agent_role: str):
    """Yield (sender, content) pairs for every event in a stream-json JSONL file."""
    seen_tool_use: set[str] = set()
    seen_tool_result: set[str] = set()
    try:
        with open(stream_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except (ValueError, json.JSONDecodeError):
                    continue
                yield from _classify_event(ev, agent_role, seen_tool_use, seen_tool_result)
    except OSError:
        pass


def _make_live_stream_relay(bus, conv_id: str, agent_role: str):
    """Return (callback, events) for real-time streaming to the message bus.

    The callback processes a single stream-json event dict: writes each
    (sender, content) pair to the bus immediately and appends it to the
    events list for post-processing.

    Returns:
        callback: Synchronous callable(event_dict) — pass as on_stream_event.
        events:   List of (sender, content) tuples accumulated during the run.
    """
    seen_tool_use: set[str] = set()
    seen_tool_result: set[str] = set()
    events: list[tuple[str, str]] = []

    def callback(event: dict) -> None:
        for sender, content in _classify_event(
            event, agent_role, seen_tool_use, seen_tool_result,
        ):
            bus.send(conv_id, sender, content)
            events.append((sender, content))

    return callback, events


# Senders that carry internal stream trace — not conversational history.
# Shared with proxy_review.py for consistent dialog history filtering.
NON_CONVERSATIONAL_SENDERS: frozenset[str] = frozenset({
    'thinking', 'tool_use', 'tool_result', 'system', 'orchestrator',
    'state', 'cost', 'log',
})




# ── Office manager session ──────────────────────────────────────────────────

class OfficeManagerSession:
    """Multi-turn conversation session with the office manager agent.

    Each invocation starts fresh from `claude -p` with an empty context
    window. ACT-R memory carries forward what the agent judged worth
    remembering. The message history persists indefinitely via the message
    bus, but the agent's working context is rebuilt from prompt, memory
    retrieval, and platform state on each invocation.

    The Claude CLI session ID is tracked for --resume support within a
    single conversation. Between conversations (fresh invocations), a new
    session ID is created.
    """

    def __init__(self, teaparty_home: str, user_id: str, llm_backend: str = 'claude'):
        self.teaparty_home = teaparty_home
        self._infra_dir = os.path.join(teaparty_home, 'management', 'agents', 'office-manager')
        self.user_id = user_id
        self._llm_backend = llm_backend
        self.conversation_id = make_conversation_id(
            ConversationType.OFFICE_MANAGER, user_id,
        )
        self.claude_session_id: str | None = None
        self.conversation_title: str | None = None

        # Message bus at the canonical OM path — same location the bridge reads.
        bus_path = om_bus_path(teaparty_home)
        os.makedirs(os.path.dirname(bus_path), exist_ok=True)
        self._bus = SqliteMessageBus(bus_path)

        # Bus event listener for Send/Reply dispatch — started lazily, kept
        # alive across --resume invocations within the same session.
        self._bus_listener = None
        self._bus_listener_sockets: tuple[str, str, str] | None = None
        # Parent context ID for the OM in the bus — children spawned via
        # Send have this as their parent_context_id so replies route back.
        self._bus_context_id: str = ''
        # Effective cwd (worktree) — set during invoke(), read by reply_fn
        # and reinvoke_fn to locate the OM's session file for injection.
        self._effective_cwd: str = ''

    def send_human_message(self, content: str) -> str:
        """Record a human message in the conversation. Returns message ID."""
        return self._bus.send(self.conversation_id, 'human', content)

    def send_agent_message(self, content: str) -> str:
        """Record an office manager message in the conversation. Returns message ID."""
        return self._bus.send(self.conversation_id, 'office-manager', content)

    def get_messages(self, since_timestamp: float = 0.0):
        """Retrieve conversation messages, optionally since a timestamp."""
        return self._bus.receive(self.conversation_id, since_timestamp=since_timestamp)

    def build_context(self) -> str:
        """Build conversation history formatted for the agent prompt.

        Returns human and agent-role messages only. Stream trace events
        (thinking, tool_use, tool_result, system) are excluded — they are
        internal diagnostics, not conversational history.
        """
        messages = self.get_messages()
        if not messages:
            return ''
        lines = []
        for msg in messages:
            if (msg.sender in NON_CONVERSATIONAL_SENDERS
                    or msg.sender.startswith('unknown:')):
                continue
            role = 'Human' if msg.sender == 'human' else 'Office Manager'
            lines.append(f'{role}: {msg.content}')
        return '\n\n'.join(lines)

    def _session_key(self) -> str:
        """Return a stable session key for this conversation."""
        safe_id = self.user_id.replace('/', '-').replace(':', '-').replace(' ', '-')
        return f'om-{safe_id}'

    def save_state(self) -> None:
        """Persist session state to {scope}/sessions/ via the launcher's session lifecycle."""
        from teaparty.runners.launcher import create_session, load_session, _save_session_metadata
        session_key = self._session_key()
        session = load_session(
            agent_name='office-manager', scope='management',
            teaparty_home=self.teaparty_home, session_id=session_key,
        )
        if session is None:
            session = create_session(
                agent_name='office-manager', scope='management',
                teaparty_home=self.teaparty_home, session_id=session_key,
            )
        session.claude_session_id = self.claude_session_id or ''
        # Store conversation title in metadata for read_om_session_title
        meta_path = os.path.join(session.path, 'metadata.json')
        meta = {
            'session_id': session.id,
            'agent_name': session.agent_name,
            'scope': session.scope,
            'claude_session_id': session.claude_session_id,
            'conversation_map': session.conversation_map,
            'conversation_title': self.conversation_title or '',
            'user_id': self.user_id,
            'conversation_id': self.conversation_id,
        }
        tmp = meta_path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(meta, f, indent=2)
        os.replace(tmp, meta_path)

    def load_state(self) -> None:
        """Load session state from {scope}/sessions/."""
        from teaparty.runners.launcher import load_session
        session = load_session(
            agent_name='office-manager', scope='management',
            teaparty_home=self.teaparty_home, session_id=self._session_key(),
        )
        if session is not None:
            self.claude_session_id = session.claude_session_id or None
            # Load conversation title from metadata
            meta_path = os.path.join(session.path, 'metadata.json')
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                self.conversation_title = meta.get('conversation_title') or None
            except (FileNotFoundError, json.JSONDecodeError):
                pass

    def _latest_human_message(self) -> str:
        """Return the content of the most recent human message in this conversation."""
        messages = self.get_messages()
        for msg in reversed(messages):
            if msg.sender == 'human':
                return msg.content
        return ''

    async def _ensure_bus_listener(self, cwd: str) -> dict:
        """Start the BusEventListener if not already running.

        Returns the mcp_env dict with socket paths for the MCP server.
        The listener stays alive across --resume invocations.
        """
        if self._bus_listener is not None:
            send, reply, close = self._bus_listener_sockets
            return {
                'SEND_SOCKET': send,
                'REPLY_SOCKET': reply,
                'CLOSE_CONV_SOCKET': close,
                'AGENT_ID': 'om',
                'PYTHONPATH': cwd,
            }

        import logging
        from teaparty.messaging.listener import BusEventListener

        log = logging.getLogger('teaparty.teams.office_manager')
        bus_db_path = os.path.join(self._infra_dir, 'messages.db')
        repo_root = os.path.dirname(self.teaparty_home)

        # Session object for conversation map tracking (per-agent limit of 3).
        from teaparty.runners.launcher import (
            create_session as _create_session,
            record_child_session as _record_child,
            check_slot_available as _check_slot,
        )
        if not hasattr(self, '_dispatch_session') or self._dispatch_session is None:
            self._dispatch_session = _create_session(
                agent_name='office-manager',
                scope='management',
                teaparty_home=self.teaparty_home,
            )

        dispatch_session = self._dispatch_session

        async def spawn_fn(member, composite, context_id):
            import subprocess as _sp
            import time as _time
            from teaparty.runners.launcher import launch as _launch
            t0 = _time.monotonic()

            # Enforce per-agent conversation limit (max 3 open dispatches).
            if not _check_slot(dispatch_session):
                log.warning(
                    'spawn_fn: agent %s at conversation limit (%d open), blocking dispatch to %s',
                    'office-manager', len(dispatch_session.conversation_map), member,
                )
                return ('', '', 'Dispatch blocked: per-agent conversation limit reached.')

            agent_dir = os.path.join(self._infra_dir, 'agents', f'pool_{member}')
            if not os.path.isdir(agent_dir):
                wt_result = _sp.run(
                    ['git', 'worktree', 'add', '--detach', agent_dir],
                    cwd=repo_root, capture_output=True, text=True,
                )
                if wt_result.returncode != 0:
                    os.makedirs(agent_dir, exist_ok=True)
            t_worktree = _time.monotonic()

            mcp_port = int(os.environ.get('TEAPARTY_BRIDGE_PORT', '9000'))
            result = await _launch(
                agent_name=member,
                message=composite,
                scope='management',
                teaparty_home=self.teaparty_home,
                worktree=agent_dir,
                mcp_port=mcp_port,
            )
            t_done = _time.monotonic()

            # Record the child session in the conversation map.
            if result.session_id:
                _record_child(dispatch_session,
                              request_id=context_id,
                              child_session_id=result.session_id)

            log.info(
                'spawn_fn_timing: member=%r worktree=%.2fs dispatch=%.2fs total=%.2fs',
                member, t_worktree - t0, t_done - t_worktree, t_done - t0,
            )
            return (result.session_id, agent_dir, '')

        async def resume_fn(member, composite, session_id, context_id):
            from teaparty.runners.launcher import launch as _launch
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
                agent_name=member,
                message=composite,
                scope='management',
                teaparty_home=self.teaparty_home,
                worktree=agent_dir,
                resume_session=session_id,
                mcp_port=mcp_port,
            )
            return (result.session_id, result.stream_file or '')

        async def reply_fn(context_id, session_id, message):
            """Deliver a worker reply to the OM's conversation bus.

            Called for EVERY Reply from a dispatched worker.  Writes the
            reply to the OM's message bus so it appears in the chat blade.
            Frees the dispatch slot in the conversation map.
            """
            from teaparty.runners.launcher import remove_child_session as _remove_child
            log.info('OM reply_fn: delivering reply for context %s', context_id)
            self._bus.send(
                self.conversation_id,
                'configuration-lead',  # TODO: derive sender from context
                message,
            )
            # Free the dispatch slot.
            _remove_child(dispatch_session, request_id=context_id)

        async def reinvoke_fn(context_id, session_id, message):
            """All workers have replied — no-op for now.

            The reply is already written to the bus by reply_fn and visible
            in the chat blade.  The OM's current turn may still be running
            (Send is non-blocking from the OM's perspective but the spawn
            completes synchronously).  A future iteration can --resume the
            OM here once the session lifecycle supports it.
            """
            log.info('OM reinvoke_fn: fan-in complete for context %s', context_id)

        async def cleanup_fn(worktree_path):
            import subprocess as _sp
            if worktree_path and os.path.isdir(worktree_path):
                _sp.run(
                    ['git', 'worktree', 'remove', '--force', worktree_path],
                    cwd=repo_root, capture_output=True,
                )

        # Create a parent context record for the OM so spawned children have
        # a valid parent_context_id.  Mirrors engine._bus_lead_context_id.
        if not self._bus_context_id:
            self._bus_context_id = f'agent:om:lead:{uuid.uuid4()}'
            bus = SqliteMessageBus(bus_db_path)
            try:
                bus.create_agent_context(
                    self._bus_context_id,
                    initiator_agent_id='om',
                    recipient_agent_id='om',
                )
            finally:
                bus.close()

        self._bus_listener = BusEventListener(
            bus_db_path=bus_db_path,
            initiator_agent_id='om',
            current_context_id=self._bus_context_id,
            spawn_fn=spawn_fn,
            resume_fn=resume_fn,
            reply_fn=reply_fn,
            reinvoke_fn=reinvoke_fn,
            cleanup_fn=cleanup_fn,
        )
        sockets = await self._bus_listener.start()
        self._bus_listener_sockets = sockets

        # Register spawn_fn in the MCP registry so the in-process
        # HTTP MCP server can route Send calls directly.
        from teaparty.mcp.registry import register_spawn_fn
        register_spawn_fn('office-manager', spawn_fn)

        send, reply, close = sockets
        return {
            'SEND_SOCKET': send,
            'REPLY_SOCKET': reply,
            'CLOSE_CONV_SOCKET': close,
            'AGENT_ID': 'om',
            'PYTHONPATH': cwd,
        }

    async def stop(self):
        """Stop the bus event listener. Call on session teardown."""
        if self._bus_listener is not None:
            await self._bus_listener.stop()
            self._bus_listener = None
            self._bus_listener_sockets = None

    async def invoke(self, *, cwd: str) -> str:
        """Invoke the office manager agent via the unified launcher.

        Loads session state (for --resume), launches the agent, extracts the
        response text from the stream, writes it to the OM bus, and saves the
        updated session ID for the next --resume.

        Returns the agent's response text, or '' if invocation fails or produces
        no text.
        """
        import tempfile
        import time as _time
        from teaparty.runners.launcher import (
            launch, detect_poisoned_session, create_session, load_session,
        )
        from teaparty.workspace.worktree import ensure_agent_worktree

        t_invoke_start = _time.monotonic()
        self.load_state()

        # Handle /clear: reset the Claude session so the next message starts fresh.
        latest = self._latest_human_message()
        if latest.strip() == '/clear':
            self.claude_session_id = None
            self.save_state()
            msg = 'Session cleared.'
            self._bus.send(self.conversation_id, 'office-manager', msg)
            return msg

        is_fresh_session = self.claude_session_id is None

        if self.claude_session_id:
            prompt = self._latest_human_message()
        else:
            prompt = self.build_context()

        if not prompt:
            return ''

        # Session = worktree (1:1). Create/load session first, then
        # create the worktree inside the session directory.
        session_key = self._session_key()
        session = load_session(
            agent_name='office-manager', scope='management',
            teaparty_home=self.teaparty_home, session_id=session_key,
        )
        if session is None:
            session = create_session(
                agent_name='office-manager', scope='management',
                teaparty_home=self.teaparty_home, session_id=session_key,
            )

        effective_cwd = await ensure_agent_worktree(
            'office-manager', cwd, self._infra_dir,
            session_path=session.path,
        )
        self._effective_cwd = effective_cwd

        # Start (or reuse) the bus event listener so the OM can Send/Reply.
        mcp_env = await self._ensure_bus_listener(cwd)

        # Stream events to the bus in real-time as the runner produces them.
        stream_callback, events = _make_live_stream_relay(
            self._bus, self.conversation_id, 'office-manager',
        )

        stream_fd, stream_path = tempfile.mkstemp(suffix='.jsonl', prefix='om-stream-')
        os.close(stream_fd)

        mcp_port = int(os.environ.get('TEAPARTY_BRIDGE_PORT', '9000'))

        try:
            result = await launch(
                agent_name='office-manager',
                message=prompt,
                scope='management',
                teaparty_home=self.teaparty_home,
                worktree=effective_cwd,
                resume_session=self.claude_session_id or '',
                mcp_port=mcp_port,
                on_stream_event=stream_callback,
            )

            if result.stderr_lines:
                _om_dbg.warning('OM stderr (%d lines): %s', len(result.stderr_lines),
                                '\n'.join(result.stderr_lines[-10:]))

            response_text = '\n'.join(c for s, c in events if s == 'office-manager')

            # Detect poisoned session via unified health check
            system_events = []
            for sender, content in events:
                if sender == 'system':
                    try:
                        system_events.append(json.loads(content))
                    except (ValueError, json.JSONDecodeError):
                        pass

            if detect_poisoned_session(system_events):
                import logging as _log_mod
                _log_mod.getLogger('teaparty.teams.office_manager').warning(
                    'MCP server failed to start — clearing session to prevent poisoned --resume'
                )
                self.claude_session_id = None
                self.save_state()

            if not response_text:
                self.claude_session_id = None
                self.save_state()
                self._bus.send(
                    self.conversation_id,
                    'office-manager',
                    'I was unable to produce a response (the session may have '
                    'expired). Please send your message again to start a fresh '
                    'session.',
                )

            if response_text and result.session_id:
                self.claude_session_id = result.session_id
                if self._bus_context_id:
                    bus_db_path = os.path.join(self._infra_dir, 'messages.db')
                    _bus_ctx = SqliteMessageBus(bus_db_path)
                    try:
                        _bus_ctx.set_agent_context_session_id(
                            self._bus_context_id, result.session_id,
                        )
                    finally:
                        _bus_ctx.close()
                if is_fresh_session and not self.conversation_title:
                    slug = _extract_slug(stream_path, result.session_id, cwd)
                    if slug:
                        self.conversation_title = slug
                self.save_state()

            import logging as _logging
            _logging.getLogger('teaparty.teams.office_manager').info(
                'invoke_timing: total=%.2fs response_len=%d',
                _time.monotonic() - t_invoke_start, len(response_text),
            )
            return response_text
        finally:
            try:
                os.unlink(stream_path)
            except OSError:
                pass


def read_om_session_title(teaparty_home: str, qualifier: str) -> str | None:
    """Read the conversation title from a saved OM session state file.

    Returns None if no title is stored or the file doesn't exist.
    """
    safe_id = qualifier.replace('/', '-').replace(':', '-').replace(' ', '-')
    sessions_dir = os.path.join(teaparty_home, 'management', 'sessions')
    state_path = os.path.join(sessions_dir, f'om-{safe_id}', 'metadata.json')
    try:
        with open(state_path) as f:
            state = json.load(f)
        return state.get('conversation_title') or None
    except (FileNotFoundError, json.JSONDecodeError):
        return None
