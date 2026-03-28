"""Message bus with adapter interface for human-agent communication.

Replaces the blocking FIFO IPC with a persistent, conversation-based
message bus.  The adapter interface allows swapping storage backends
(SQLite for POC, external adapters like Slack/Teams later).

Three conversation types:
  - office_manager: one per human, persistent across sessions
  - project_session: one per active session, closed on completion
  - subteam: one per dispatch, proxy participates

Issue #200.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from projects.POC.orchestrator.events import InputRequest

_log = logging.getLogger('orchestrator.messaging')


@dataclass
class Message:
    """A single message in a conversation."""
    id: str
    conversation: str
    sender: str
    content: str
    timestamp: float


class ConversationType(Enum):
    OFFICE_MANAGER = 'office_manager'   # Deferred: depends on office manager feature
    PROJECT_SESSION = 'project_session'  # Active: created by Session.run()
    SUBTEAM = 'subteam'                  # Active: created by DispatchListener


_PREFIXES = {
    ConversationType.OFFICE_MANAGER: 'om',
    ConversationType.PROJECT_SESSION: 'session',
    ConversationType.SUBTEAM: 'team',
}


def make_conversation_id(conv_type: ConversationType, qualifier: str) -> str:
    """Create a namespaced conversation ID.

    Examples:
        make_conversation_id(ConversationType.OFFICE_MANAGER, 'darrell')
        → 'om:darrell'

        make_conversation_id(ConversationType.PROJECT_SESSION, '20260327-143000')
        → 'session:20260327-143000'
    """
    prefix = _PREFIXES[conv_type]
    return f'{prefix}:{qualifier}'


@runtime_checkable
class MessageBusAdapter(Protocol):
    """Adapter interface for message storage backends."""

    def send(self, conversation_id: str, sender: str, content: str) -> str:
        """Send a message. Returns the message ID."""
        ...

    def receive(
        self, conversation_id: str, since_timestamp: float = 0.0,
    ) -> list[Message]:
        """Receive messages from a conversation, optionally since a timestamp."""
        ...

    def conversations(self) -> list[str]:
        """List all conversation IDs with messages."""
        ...


class SqliteMessageBus:
    """SQLite-backed message bus.

    Single table schema: id, conversation, sender, content, timestamp.
    Uses WAL mode for concurrent read safety.
    """

    def __init__(self, db_path: str):
        self._conn = sqlite3.connect(db_path)
        self._conn.execute('PRAGMA journal_mode=WAL')
        self._conn.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                conversation TEXT NOT NULL,
                sender TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
        ''')
        self._conn.execute(
            'CREATE INDEX IF NOT EXISTS idx_messages_conv_ts '
            'ON messages (conversation, timestamp)'
        )
        self._conn.commit()

    def send(self, conversation_id: str, sender: str, content: str) -> str:
        msg_id = uuid.uuid4().hex
        ts = time.time()
        self._conn.execute(
            'INSERT INTO messages (id, conversation, sender, content, timestamp) '
            'VALUES (?, ?, ?, ?, ?)',
            (msg_id, conversation_id, sender, content, ts),
        )
        self._conn.commit()
        return msg_id

    def receive(
        self, conversation_id: str, since_timestamp: float = 0.0,
    ) -> list[Message]:
        cursor = self._conn.execute(
            'SELECT id, conversation, sender, content, timestamp '
            'FROM messages '
            'WHERE conversation = ? AND timestamp > ? '
            'ORDER BY timestamp ASC',
            (conversation_id, since_timestamp),
        )
        return [
            Message(id=row[0], conversation=row[1], sender=row[2],
                    content=row[3], timestamp=row[4])
            for row in cursor.fetchall()
        ]

    def conversations(self) -> list[str]:
        cursor = self._conn.execute(
            'SELECT DISTINCT conversation FROM messages ORDER BY conversation'
        )
        return [row[0] for row in cursor.fetchall()]

    def close(self) -> None:
        self._conn.close()


class MessageBusInputProvider:
    """InputProvider backed by a message bus conversation.

    When called, sends the agent's question to the conversation as an
    'orchestrator' message, then polls for a 'human' response.  This
    preserves the full exchange as an audit trail in the message bus.

    Exposes ``is_waiting`` and ``current_request`` for TUI compatibility
    with the older TUIInputProvider interface.
    """

    def __init__(
        self,
        bus: MessageBusAdapter,
        conversation_id: str,
        poll_interval: float = 0.1,
    ):
        self.bus = bus
        self.conversation_id = conversation_id
        self.poll_interval = poll_interval
        self._waiting = False
        self._current_request: InputRequest | None = None

    @property
    def is_waiting(self) -> bool:
        """True when the orchestrator is blocked waiting for input."""
        return self._waiting

    @property
    def current_request(self) -> InputRequest | None:
        """The InputRequest the orchestrator is waiting on, or None."""
        return self._current_request if self._waiting else None

    async def __call__(self, request: InputRequest) -> str:
        """Send the question and poll for a human response."""
        self._current_request = request
        self._waiting = True
        try:
            # Record the question
            self.bus.send(
                self.conversation_id,
                'orchestrator',
                request.bridge_text,
            )

            # Poll for human response
            since = time.time()
            while True:
                messages = self.bus.receive(self.conversation_id, since_timestamp=since)
                for msg in messages:
                    if msg.sender == 'human':
                        return msg.content
                await asyncio.sleep(self.poll_interval)
        finally:
            self._waiting = False
            self._current_request = None
