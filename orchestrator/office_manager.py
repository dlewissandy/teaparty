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
import re
import sqlite3
import time
import uuid
from enum import Enum

from orchestrator.messaging import (
    ConversationType,
    SqliteMessageBus,
    make_conversation_id,
)


# ── Path helpers ────────────────────────────────────────────────────────────

def om_bus_path(teaparty_home: str) -> str:
    """Return the canonical path to the office manager's message database.

    The OM database is persistent and not session-scoped. It lives at
    {teaparty_home}/om/om-messages.db, separate from per-session messages.db
    files. Both the orchestrator and the bridge use this function to locate
    the same database. Issue #290.
    """
    return os.path.join(teaparty_home, 'om', 'om-messages.db')


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


# ── Liaison agent construction ──────────────────────────────────────────────

def _project_slug(name: str) -> str:
    """Convert a project name to a liaison agent slug.

    'TeaParty'  → 'teaparty'
    'My Project' → 'my-project'
    'foo_bar'   → 'foo-bar'
    """
    slug = name.lower()
    slug = re.sub(r'[^a-z0-9]+', '-', slug)
    return slug.strip('-')


def _make_project_liaison_def(name: str, path: str) -> dict:
    """Build an agent definition dict for a project liaison."""
    return {
        'description': (
            f'Liaison for the {name} project. Answers status queries by reading '
            'project state, git log, session state, and config files.'
        ),
        'prompt': (
            f'You are the {name} project liaison on the management team. '
            f'Your project is at: {path}\n\n'
            'Your role:\n'
            '1. Answer the office manager\'s status queries about your project by reading:\n'
            f'   - {path}/.teaparty/ — project configuration\n'
            f'   - {path}/.sessions/ — session state (if it exists)\n'
            f'   - git log in {path} — recent activity\n'
            f'   - Any CfA state JSON files under {path}\n'
            '2. Report your findings to the office manager: '
            'SendMessage(to="office-manager", content="<your answer>")\n\n'
            'You do NOT dispatch execution or spawn sessions. '
            'Execution dispatch requires session context that does not exist here. '
            'Your job is answering questions.\n\n'
            'POINT-NOT-PASTE: Reference files by path, not by pasting their contents.'
        ),
        'model': 'haiku',
        'maxTurns': 10,
        'disallowedTools': [
            'Edit', 'Write', 'MultiEdit', 'WebSearch', 'WebFetch',
            'Task', 'TaskOutput', 'TaskStop', 'TeamCreate', 'TeamDelete',
            'NotebookEdit',
        ],
    }


def _make_configuration_liaison_def() -> dict:
    """Build an agent definition dict for the configuration workgroup liaison."""
    return {
        'description': (
            'Liaison for the Configuration workgroup. Answers questions about '
            'current Claude Code configuration and routes change requests.'
        ),
        'prompt': (
            'You are the configuration workgroup liaison on the management team. '
            'You represent the Configuration Team — the workgroup that creates and '
            'modifies agents, skills, hooks, MCP servers, and other Claude Code artifacts.\n\n'
            'Your role:\n'
            '1. Answer the office manager\'s questions about current configuration:\n'
            '   - What agents exist: .claude/agents/\n'
            '   - What skills are defined: .claude/skills/\n'
            '   - What hooks are active: .claude/settings.json\n'
            '2. Dispatch configuration requests to the Configuration Team when asked:\n'
            '   Send(member="configuration-lead", message="<specific configuration request>")\n'
            '3. Report results to the office manager: '
            'SendMessage(to="office-manager", content="<your answer>")\n\n'
            'POINT-NOT-PASTE: Reference files by path, not by pasting their contents.'
        ),
        'model': 'haiku',
        'maxTurns': 10,
        'disallowedTools': [
            'Edit', 'Write', 'MultiEdit', 'WebSearch', 'WebFetch',
            'Task', 'TaskOutput', 'TaskStop', 'TeamCreate', 'TeamDelete',
            'NotebookEdit',
        ],
    }


def _build_liaison_agents_json(
    teaparty_home: str,
) -> tuple[dict, list[str]]:
    """Build liaison agent definitions from the registry at teaparty_home.

    Reads teaparty.yaml, discovers valid projects, and constructs one liaison
    agent per valid project plus a configuration workgroup liaison. Called by
    OfficeManagerSession.invoke() to populate the --agents flag on each
    ClaudeRunner invocation.

    Returns:
        (agents_dict, warnings) where agents_dict maps agent name → definition
        and warnings is a list of human-readable messages about degraded state.
        The agents_dict always contains at least 'configuration-liaison'.
    """
    from orchestrator.config_reader import discover_projects, load_management_team

    agents: dict = {}
    warnings: list[str] = []

    try:
        team = load_management_team(teaparty_home)
    except FileNotFoundError:
        # Registry absent — new or unconfigured deployment. Proceed silently
        # with configuration-liaison only; no warning (nothing misconfigured).
        agents['configuration-liaison'] = _make_configuration_liaison_def()
        return agents, warnings
    except Exception as exc:  # noqa: BLE001
        warnings.append(
            f'Could not load team registry ({exc}) — project liaisons unavailable.'
        )
        agents['configuration-liaison'] = _make_configuration_liaison_def()
        return agents, warnings

    projects = discover_projects(team)
    skipped: list[str] = []
    for project in projects:
        if not project['valid']:
            skipped.append(project['name'])
            continue
        slug = _project_slug(project['name'])
        agent_name = f'{slug}-liaison'
        agents[agent_name] = _make_project_liaison_def(
            name=project['name'],
            path=project['path'],
        )

    if skipped:
        warnings.append(
            f'Projects skipped (missing required markers: .git, .claude, .teaparty): '
            + ', '.join(skipped)
        )

    agents['configuration-liaison'] = _make_configuration_liaison_def()
    return agents, warnings


# ── MCP config ──────────────────────────────────────────────────────────────

def _build_mcp_config(project_root: str) -> dict:
    """Build the mcp_config dict for the office manager's ClaudeRunner.

    Points at orchestrator.mcp_server (the config + escalation tool server).
    Inherits the project_root via cwd so config tools resolve paths correctly.
    """
    venv_python = os.path.join(project_root, '.venv', 'bin', 'python3')
    if not os.path.isfile(venv_python):
        venv_python = 'python3'
    return {
        'teaparty-config': {
            'command': venv_python,
            'args': ['-m', 'orchestrator.mcp_server'],
        },
    }


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

    def __init__(self, teaparty_home: str, user_id: str):
        self.teaparty_home = teaparty_home
        self._infra_dir = os.path.join(teaparty_home, 'om')
        self.user_id = user_id
        self.conversation_id = make_conversation_id(
            ConversationType.OFFICE_MANAGER, user_id,
        )
        self.claude_session_id: str | None = None
        self.conversation_title: str | None = None

        # Message bus at the canonical OM path — same location the bridge reads.
        bus_path = om_bus_path(teaparty_home)
        os.makedirs(os.path.dirname(bus_path), exist_ok=True)
        self._bus = SqliteMessageBus(bus_path)

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
        from orchestrator.claude_runner import ClaudeRunner

        self.load_state()
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

        stream_fd, stream_path = tempfile.mkstemp(suffix='.jsonl', prefix='om-stream-')
        os.close(stream_fd)

        # Build liaison team from registry. Degrade gracefully if registry is
        # missing or malformed rather than failing the entire invocation.
        agents_dict, registry_warnings = _build_liaison_agents_json(self.teaparty_home)
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

        try:
            runner = ClaudeRunner(
                prompt=prompt,
                cwd=cwd,
                stream_file=stream_path,
                agents_file=agents_path,
                lead='office-manager',
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
                # On the first turn, capture the slug Claude auto-generates for
                # this conversation so the UI can show a descriptive nav label.
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
    state_path = os.path.join(teaparty_home, 'om', f'.om-session-{safe_id}.json')
    try:
        with open(state_path) as f:
            state = json.load(f)
        return state.get('conversation_title') or None
    except (FileNotFoundError, json.JSONDecodeError):
        return None
