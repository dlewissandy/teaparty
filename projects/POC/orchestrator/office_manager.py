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

from projects.POC.orchestrator.messaging import (
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
        from projects.POC.orchestrator.proxy_memory import (
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
        from projects.POC.orchestrator.proxy_memory import (
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

    def __init__(self, infra_dir: str, user_id: str):
        self.infra_dir = infra_dir
        self.user_id = user_id
        self.conversation_id = make_conversation_id(
            ConversationType.OFFICE_MANAGER, user_id,
        )
        self.claude_session_id: str | None = None

        # Create message bus in infra directory
        bus_path = os.path.join(infra_dir, 'om-messages.db')
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

    def save_state(self) -> None:
        """Persist session state (Claude session ID) to disk."""
        state = {
            'claude_session_id': self.claude_session_id,
            'user_id': self.user_id,
            'conversation_id': self.conversation_id,
        }
        state_path = os.path.join(self.infra_dir, '.om-session-state.json')
        tmp = state_path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(state, f)
        os.replace(tmp, state_path)

    def load_state(self) -> None:
        """Load session state from disk."""
        state_path = os.path.join(self.infra_dir, '.om-session-state.json')
        try:
            with open(state_path) as f:
                state = json.load(f)
            self.claude_session_id = state.get('claude_session_id')
        except (FileNotFoundError, json.JSONDecodeError):
            pass
