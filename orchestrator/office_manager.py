"""Office manager session — multi-turn human-agent conversation.

The office manager is a team lead one level above projects. It coordinates
across projects via AskTeam dispatch, synthesizes status, records durable
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

def _extract_assistant_text(stream_path: str) -> str:
    """Extract concatenated assistant text blocks from a stream-json JSONL file."""
    parts = []
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
                if ev.get('type') != 'assistant':
                    continue
                for block in ev.get('message', {}).get('content', []):
                    if isinstance(block, dict) and block.get('type') == 'text':
                        text = block.get('text', '').strip()
                        if text:
                            parts.append(text)
    except OSError:
        pass
    return '\n'.join(parts)


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

        Returns the message history as a string the office manager agent
        can read to understand the conversation so far.
        """
        messages = self.get_messages()
        if not messages:
            return ''
        lines = []
        for msg in messages:
            role = 'Human' if msg.sender == 'human' else 'Office Manager'
            lines.append(f'{role}: {msg.content}')
        return '\n\n'.join(lines)

    def _state_path(self) -> str:
        """Return the state file path, keyed by user_id so concurrent OM threads don't collide."""
        safe_id = self.user_id.replace('/', '-').replace(':', '-').replace(' ', '-')
        return os.path.join(self._infra_dir, f'.om-session-{safe_id}.json')

    def save_state(self) -> None:
        """Persist session state (Claude session ID) to disk."""
        state = {
            'claude_session_id': self.claude_session_id,
            'user_id': self.user_id,
            'conversation_id': self.conversation_id,
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

        try:
            runner = ClaudeRunner(
                prompt=prompt,
                cwd=cwd,
                stream_file=stream_path,
                lead='office-manager',
                permission_mode='default',
                resume_session=self.claude_session_id,
            )
            result = await runner.run()

            response_text = _extract_assistant_text(stream_path)

            if response_text:
                self.send_agent_message(response_text)

            if result.session_id:
                self.claude_session_id = result.session_id
                self.save_state()

            return response_text
        finally:
            try:
                os.unlink(stream_path)
            except OSError:
                pass
