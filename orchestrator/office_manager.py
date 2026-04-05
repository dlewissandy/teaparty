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

from orchestrator.messaging import (
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
        from orchestrator.proxy_memory import (
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
        from orchestrator.proxy_memory import (
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


def _iter_stream_events(stream_path: str, agent_role: str):
    """Yield (sender, content) pairs for every event in a stream-json JSONL file.

    Maps stream event types to bus sender labels:
    - thinking block   → ('thinking', text)
    - text block       → (agent_role, text)
    - tool_use block   → ('tool_use', JSON of name+input)
    - tool_result event → ('tool_result', content text or JSON)
    - system event     → ('system', JSON of event)
    - unknown block    → ('unknown:<type>', JSON of block)

    Yields events in stream order. Unknown event types are skipped; unknown
    block types within assistant events are written rather than dropped.
    """
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
                            yield 'tool_use', json.dumps({
                                'name': block.get('name', ''),
                                'input': block.get('input', {}),
                            })
                        else:
                            yield f'unknown:{block_type}', json.dumps(block)

                elif ev_type == 'tool_result':
                    raw = ev.get('content', '')
                    yield 'tool_result', raw if isinstance(raw, str) else json.dumps(raw)

                elif ev_type == 'user':
                    # Tool results arrive as content blocks inside user events.
                    content = ev.get('message', {}).get('content', [])
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get('type') == 'tool_result':
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

    except OSError:
        pass


# Senders that carry internal stream trace — not conversational history.
# Shared with proxy_review.py for consistent dialog history filtering.
NON_CONVERSATIONAL_SENDERS: frozenset[str] = frozenset({
    'thinking', 'tool_use', 'tool_result', 'system', 'orchestrator',
    'state', 'cost', 'log',
})


# ── Roster agent construction ──────────────────────────────────────────────

def _build_roster_agents_json(
    teaparty_home: str,
) -> tuple[dict, list[str]]:
    """Build the OM's --agents roster from the management team config.

    Team membership is derived from three sources only:
    1. Proxy agents — implied by ``humans:`` entries
    2. Project leads — implied by ``members.projects``
    3. Workgroup leads — implied by ``members.workgroups``

    Returns:
        (agents_dict, warnings) where agents_dict maps agent name → definition
        and warnings is a list of human-readable messages about degraded state.
    """
    from orchestrator.config_reader import (
        load_management_team,
        load_management_workgroups,
        read_agent_frontmatter,
    )
    from orchestrator.roster import derive_om_roster

    agents: dict = {}
    warnings: list[str] = []

    try:
        team = load_management_team(teaparty_home)
    except FileNotFoundError:
        return agents, warnings
    except Exception as exc:  # noqa: BLE001
        warnings.append(
            f'Could not load team registry ({exc}) — roster unavailable.'
        )
        return agents, warnings

    repo_root = os.path.dirname(teaparty_home)
    mgmt_agents_dir = os.path.join(
        teaparty_home, 'management', 'agents',
    )

    # Project leads (from members.projects)
    try:
        roster = derive_om_roster(teaparty_home, agents_dir=mgmt_agents_dir)
        for name, info in roster.items():
            agents[name] = {'description': info.get('description', name)}
    except Exception as exc:  # noqa: BLE001
        warnings.append(f'Roster derivation failed ({exc}).')

    # Workgroup leads (from members.workgroups)
    try:
        workgroups = load_management_workgroups(team, teaparty_home=teaparty_home)
        for wg in workgroups:
            if wg.lead and wg.lead not in agents:
                desc = ''
                lead_path = os.path.join(
                    mgmt_agents_dir, wg.lead, 'agent.md',
                )
                if os.path.isfile(lead_path):
                    fm = read_agent_frontmatter(lead_path)
                    desc = fm.get('description', '')
                agents[wg.lead] = {
                    'description': desc or f'{wg.name} workgroup lead',
                }
    except Exception as exc:  # noqa: BLE001
        warnings.append(f'Workgroup loading failed ({exc}).')

    # Proxy agents (implied by humans: entries)
    for human in team.humans:
        proxy_name = 'proxy-review'
        if proxy_name not in agents:
            desc = ''
            proxy_path = os.path.join(
                mgmt_agents_dir, proxy_name, 'agent.md',
            )
            if os.path.isfile(proxy_path):
                fm = read_agent_frontmatter(proxy_path)
                desc = fm.get('description', '')
            agents[proxy_name] = {
                'description': desc or f'Human proxy for {human.name}',
            }

    return agents, warnings


# ── MCP config ──────────────────────────────────────────────────────────────

def _build_mcp_config(project_root: str, mcp_env: dict | None = None) -> dict:
    """Build the mcp_config dict for the office manager's ClaudeRunner.

    Points at orchestrator.mcp_server (the config + escalation tool server).
    When mcp_env is provided, socket paths (SEND_SOCKET, REPLY_SOCKET, etc.)
    are passed to the MCP server subprocess so dispatch tools work.
    """
    venv_python = os.path.join(project_root, '.venv', 'bin', 'python3')
    if not os.path.isfile(venv_python):
        venv_python = 'python3'
    config: dict = {
        'command': venv_python,
        'args': ['-m', 'orchestrator.mcp_server'],
    }
    if mcp_env:
        config['env'] = mcp_env
    return {'teaparty-config': config}


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

    def _state_path(self) -> str:
        """Return the state file path, keyed by user_id so concurrent OM threads don't collide."""
        safe_id = self.user_id.replace('/', '-').replace(':', '-').replace(' ', '-')
        return os.path.join(self._infra_dir, f'.om-session-{safe_id}.json')

    def save_state(self) -> None:
        """Persist session state (Claude session ID and conversation title) to disk."""
        state = {
            'claude_session_id': self.claude_session_id,
            'user_id': self.user_id,
            'conversation_id': self.conversation_id,
            'conversation_title': self.conversation_title,
        }
        state_path = self._state_path()
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
        from orchestrator.bus_event_listener import BusEventListener
        from orchestrator.agent_spawner import AgentSpawner

        log = logging.getLogger('orchestrator.office_manager')
        bus_db_path = os.path.join(self._infra_dir, 'messages.db')
        spawner = AgentSpawner(teaparty_home=self.teaparty_home)
        repo_root = os.path.dirname(self.teaparty_home)

        def _child_mcp_config(member: str, context_id: str) -> dict:
            """Build MCP config with listener socket paths for a spawned agent.

            Uses mcp_server_dispatch entry point which hardcodes the dispatch
            tool scope (~20 tools instead of 41), staying below the deferral
            threshold to eliminate the ToolSearch round-trip.
            """
            sockets = self._bus_listener_sockets
            mcp_env = {
                'SEND_SOCKET': sockets[0],
                'REPLY_SOCKET': sockets[1],
                'CLOSE_CONV_SOCKET': sockets[2],
                'AGENT_ID': member,
                'CONTEXT_ID': context_id,
            } if sockets else {}
            venv_python = os.path.join(repo_root, '.venv', 'bin', 'python3')
            if not os.path.isfile(venv_python):
                venv_python = 'python3'
            return {
                'teaparty-config': {
                    'command': venv_python,
                    'args': ['-m', 'orchestrator.mcp_server_dispatch'],
                    'env': mcp_env,
                },
            }

        async def spawn_fn(member, composite, context_id):
            import subprocess as _sp
            import time as _time
            t0 = _time.monotonic()

            safe_id = context_id.replace(':', '_').replace('/', '_')
            agent_dir = os.path.join(self._infra_dir, 'agents', safe_id)
            wt_result = _sp.run(
                ['git', 'worktree', 'add', '--detach', agent_dir],
                cwd=repo_root, capture_output=True, text=True,
            )
            if wt_result.returncode != 0:
                os.makedirs(agent_dir, exist_ok=True)
            t_worktree = _time.monotonic()

            # Pass socket paths in extra_env so the claude -p process has
            # them, and the MCP server child inherits them.  SEND_SOCKET
            # also signals _agent_tool_scope() to use the dispatch scope.
            sockets = self._bus_listener_sockets
            child_extra_env = {
                'CONTEXT_ID': context_id,
                'AGENT_ID': member,
            }
            if sockets:
                child_extra_env['SEND_SOCKET'] = sockets[0]
                child_extra_env['REPLY_SOCKET'] = sockets[1]
                child_extra_env['CLOSE_CONV_SOCKET'] = sockets[2]

            session_id, result_text = await spawner.spawn(
                composite, worktree=agent_dir, role=member,
                project_dir=repo_root, is_management=True,
                extra_env=child_extra_env,
                mcp_config=_child_mcp_config(member, context_id),
            )
            t_done = _time.monotonic()

            log.info(
                'spawn_fn_timing: member=%r git_worktree=%.2fs spawner=%.2fs total=%.2fs',
                member, t_worktree - t0, t_done - t_worktree, t_done - t0,
            )
            return (session_id, agent_dir, result_text)

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

            return await spawner.spawn(
                composite, worktree=agent_dir, role=member,
                project_dir=repo_root, resume_session=session_id,
                is_management=True,
                mcp_config=_child_mcp_config(member, context_id),
            )

        async def reply_fn(context_id, session_id, message):
            """Deliver a worker reply to the OM's conversation bus.

            Called for EVERY Reply from a dispatched worker.  Writes the
            reply to the OM's message bus so it appears in the chat blade.
            The OM will see it on its next turn.
            """
            log.info('OM reply_fn: delivering reply for context %s', context_id)
            self._bus.send(
                self.conversation_id,
                'configuration-lead',  # TODO: derive sender from context
                message,
            )

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
        """Invoke the office manager agent to respond to the current conversation.

        Loads session state (for --resume), runs claude -p as the office-manager
        sub-agent, extracts the response text from the stream, writes it to the
        OM bus, and saves the updated session ID for the next --resume.

        Returns the agent's response text, or '' if invocation fails or produces
        no text.
        """
        import asyncio
        import tempfile
        import time as _time
        from orchestrator.claude_runner import create_runner
        from orchestrator.worktree import ensure_agent_worktree

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

        # For resuming sessions, pass only the latest human message; the prior
        # context lives in the Claude session. For fresh sessions, pass the full
        # conversation history so the agent understands what it's responding to.
        if self.claude_session_id:
            prompt = self._latest_human_message()
        else:
            prompt = self.build_context()

        if not prompt:
            return ''

        # Agent isolation: run in a worktree with a scoped .claude/.
        effective_cwd = await ensure_agent_worktree(
            'office-manager', cwd, self._infra_dir,
        )
        self._effective_cwd = effective_cwd

        stream_fd, stream_path = tempfile.mkstemp(suffix='.jsonl', prefix='om-stream-')
        os.close(stream_fd)

        # Build liaison team from registry. Degrade gracefully if registry is
        # missing or malformed rather than failing the entire invocation.
        agents_dict, registry_warnings = _build_roster_agents_json(self.teaparty_home)
        for warning in registry_warnings:
            self.send_agent_message(
                f'[Team configuration warning: {warning}]'
            )

        # Write agents JSON to a named path in the infra dir (not a temp file)
        # so existing tests that mock tempfile.mkstemp for stream_path are unaffected.
        safe_id = self.user_id.replace('/', '-').replace(':', '-').replace(' ', '-')
        agents_path: str | None = os.path.join(
            self._infra_dir, f'.om-agents-{safe_id}.json',
        )
        try:
            with open(agents_path, 'w') as f:
                json.dump(agents_dict, f)
        except OSError:
            agents_path = None

        # Start (or reuse) the bus event listener so the OM can Send/Reply.
        mcp_env = await self._ensure_bus_listener(cwd)

        try:
            runner = create_runner(
                prompt,
                cwd=effective_cwd,
                stream_file=stream_path,
                backend=self._llm_backend,
                agents_file=agents_path,
                lead='office-manager',
                permission_mode='default',
                settings={
                    'permissions': {
                        'allow': [
                            # Dispatch and escalation
                            'mcp__teaparty-config__Send',
                            'mcp__teaparty-config__Reply',
                            'mcp__teaparty-config__AskQuestion',
                            'mcp__teaparty-config__CloseConversation',
                            # Intervention
                            'mcp__teaparty-config__WithdrawSession',
                            'mcp__teaparty-config__PauseDispatch',
                            'mcp__teaparty-config__ResumeDispatch',
                            'mcp__teaparty-config__ReprioritizeDispatch',
                            # Config read tools
                            'mcp__teaparty-config__PinArtifact',
                            'mcp__teaparty-config__UnpinArtifact',
                            'mcp__teaparty-config__ListProjects',
                            'mcp__teaparty-config__GetProject',
                            'mcp__teaparty-config__ListAgents',
                            'mcp__teaparty-config__GetAgent',
                            'mcp__teaparty-config__ListSkills',
                            'mcp__teaparty-config__GetSkill',
                            'mcp__teaparty-config__ListWorkgroups',
                            'mcp__teaparty-config__GetWorkgroup',
                            'mcp__teaparty-config__ListHooks',
                            'mcp__teaparty-config__ListScheduledTasks',
                            'mcp__teaparty-config__ListPins',
                            'mcp__teaparty-config__ListTeamMembers',
                        ],
                    },
                },
                resume_session=self.claude_session_id,
                mcp_config=_build_mcp_config(cwd, mcp_env=mcp_env),
            )
            result = await runner.run()

            events = list(_iter_stream_events(stream_path, 'office-manager'))
            response_text = '\n'.join(c for s, c in events if s == 'office-manager')

            for sender, content in events:
                self._bus.send(self.conversation_id, sender, content)

            if not response_text:
                # Runner completed but produced no assistant text. Clear the
                # saved session so the next invocation starts fresh rather than
                # silently producing nothing again on --resume.
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
                # Update the OM's bus context with the latest session_id so
                # reinvoke_fn can find it when workers reply.
                if self._bus_context_id:
                    bus_db_path = os.path.join(self._infra_dir, 'messages.db')
                    _bus_ctx = SqliteMessageBus(bus_db_path)
                    try:
                        _bus_ctx.set_agent_context_session_id(
                            self._bus_context_id, result.session_id,
                        )
                    finally:
                        _bus_ctx.close()
                # On the first turn, capture the slug Claude auto-generates for
                # this conversation so the UI can show a descriptive nav label.
                if is_fresh_session and not self.conversation_title:
                    slug = _extract_slug(stream_path, result.session_id, cwd)
                    if slug:
                        self.conversation_title = slug
                self.save_state()

            _log_om = logging.getLogger('orchestrator.office_manager')
            _log_om.info(
                'invoke_timing: total=%.2fs response_len=%d',
                _time.monotonic() - t_invoke_start, len(response_text),
            )
            return response_text
        finally:
            try:
                os.unlink(stream_path)
            except OSError:
                pass
            if agents_path:
                try:
                    os.unlink(agents_path)
                except OSError:
                    pass


def read_om_session_title(teaparty_home: str, qualifier: str) -> str | None:
    """Read the conversation title from a saved OM session state file.

    Returns None if no title is stored or the file doesn't exist.
    """
    safe_id = qualifier.replace('/', '-').replace(':', '-').replace(' ', '-')
    state_path = os.path.join(teaparty_home, 'management', 'agents', 'office-manager', f'.om-session-{safe_id}.json')
    try:
        with open(state_path) as f:
            state = json.load(f)
        return state.get('conversation_title') or None
    except (FileNotFoundError, json.JSONDecodeError):
        return None
