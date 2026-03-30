"""Message bus with adapter interface for human-agent communication.

Replaces the blocking FIFO IPC with a persistent, conversation-based
message bus.  The adapter interface allows swapping storage backends
(SQLite for POC, external adapters like Slack/Teams later).

Conversation types (see docs/proposals/chat-experience/references/conversation-identity.md):
  - office_manager: one per human, persistent across days/weeks
  - job: one per project+job, lives with the job
  - task: one per project+job+task, lives with the task
  - proxy_review: one per decider, indefinite persistence
  - liaison: session-scoped, requester+target
  - project_session: one per active session (legacy, from issue #200)
  - subteam: one per dispatch (legacy, from issue #200)

Issues #200, #263, #288.
"""
from __future__ import annotations

import asyncio
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from orchestrator.events import InputRequest

if TYPE_CHECKING:
    from orchestrator.role_enforcer import RoleEnforcer

_log = logging.getLogger('orchestrator.messaging')


class ConversationType(Enum):
    OFFICE_MANAGER = 'office_manager'    # One per human, persistent across days/weeks
    PROJECT_SESSION = 'project_session'  # One per session, closes when session ends
    SUBTEAM = 'subteam'                  # One per dispatch, proxy participates
    JOB = 'job'                          # One per project+job, lives with the job
    TASK = 'task'                        # One per project+job+task, lives with the task
    PROXY_REVIEW = 'proxy_review'        # One per decider, indefinite persistence
    LIAISON = 'liaison'                  # Session-scoped, requester+target


class ConversationState(Enum):
    ACTIVE = 'active'
    CLOSED = 'closed'


@dataclass
class Message:
    """A single message in a conversation."""
    id: str
    conversation: str
    sender: str
    content: str
    timestamp: float


@dataclass
class Conversation:
    """A conversation with stable identity and lifecycle state."""
    id: str
    type: ConversationType
    state: ConversationState
    created_at: float
    awaiting_input: bool = False


_PREFIXES = {
    ConversationType.OFFICE_MANAGER: 'om',
    ConversationType.PROJECT_SESSION: 'session',
    ConversationType.SUBTEAM: 'team',
    ConversationType.JOB: 'job',
    ConversationType.TASK: 'task',
    ConversationType.PROXY_REVIEW: 'proxy',
    ConversationType.LIAISON: 'liaison',
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

    def set_awaiting_input(self, conversation_id: str, value: bool) -> None:
        """Set or clear the awaiting_input flag on a conversation."""
        ...

    def conversations_awaiting_input(self) -> list['Conversation']:
        """Return active conversations with awaiting_input=True."""
        ...


class SqliteMessageBus:
    """SQLite-backed message bus.

    Single table schema: id, conversation, sender, content, timestamp.
    Uses WAL mode for concurrent read safety.

    Optional ``role_enforcer`` attribute: when set to a ``RoleEnforcer``,
    ``send()`` checks the sender's D-A-I role before accepting input.
    """

    role_enforcer: 'RoleEnforcer | None'

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
        self._conn.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'active',
                created_at REAL NOT NULL,
                awaiting_input INTEGER NOT NULL DEFAULT 0
            )
        ''')
        # Migrate existing DBs that predate the awaiting_input column (issue #288)
        try:
            self._conn.execute(
                'ALTER TABLE conversations ADD COLUMN awaiting_input INTEGER NOT NULL DEFAULT 0'
            )
        except sqlite3.OperationalError:
            pass  # Column already exists
        self._conn.commit()
        self.role_enforcer = None

    def send(self, conversation_id: str, sender: str, content: str) -> str:
        # Check D-A-I role if enforcer is configured
        if self.role_enforcer is not None:
            self.role_enforcer.check_send(sender)

        # Reject writes to closed conversations
        row = self._conn.execute(
            'SELECT state FROM conversations WHERE id = ?',
            (conversation_id,),
        ).fetchone()
        if row and row[0] == ConversationState.CLOSED.value:
            raise ValueError(
                f'Cannot send to closed conversation: {conversation_id}'
            )

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

    # ── Conversation management ──

    def create_conversation(
        self, conv_type: ConversationType, qualifier: str,
    ) -> Conversation:
        """Create a conversation or return the existing one if it already exists."""
        cid = make_conversation_id(conv_type, qualifier)
        existing = self.get_conversation(cid)
        if existing is not None:
            return existing

        ts = time.time()
        self._conn.execute(
            'INSERT INTO conversations (id, type, state, created_at) '
            'VALUES (?, ?, ?, ?)',
            (cid, conv_type.value, ConversationState.ACTIVE.value, ts),
        )
        self._conn.commit()
        return Conversation(
            id=cid, type=conv_type,
            state=ConversationState.ACTIVE, created_at=ts,
        )

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        """Retrieve conversation metadata by ID, or None if not found."""
        row = self._conn.execute(
            'SELECT id, type, state, created_at, awaiting_input FROM conversations WHERE id = ?',
            (conversation_id,),
        ).fetchone()
        if row is None:
            return None
        return Conversation(
            id=row[0],
            type=ConversationType(row[1]),
            state=ConversationState(row[2]),
            created_at=row[3],
            awaiting_input=bool(row[4]),
        )

    def close_conversation(self, conversation_id: str) -> None:
        """Transition a conversation to CLOSED state."""
        self._conn.execute(
            'UPDATE conversations SET state = ? WHERE id = ?',
            (ConversationState.CLOSED.value, conversation_id),
        )
        self._conn.commit()

    def set_awaiting_input(self, conversation_id: str, value: bool) -> None:
        """Set or clear the awaiting_input flag on a conversation.

        When True, signals that the orchestrator is blocked waiting for human
        input in this conversation.  The bridge polls this flag to emit
        input_requested WebSocket events (issue #288).
        """
        self._conn.execute(
            'UPDATE conversations SET awaiting_input = ? WHERE id = ?',
            (1 if value else 0, conversation_id),
        )
        self._conn.commit()

    def conversations_awaiting_input(self) -> list[Conversation]:
        """Return active conversations with awaiting_input=1."""
        cursor = self._conn.execute(
            'SELECT id, type, state, created_at, awaiting_input FROM conversations '
            'WHERE state = ? AND awaiting_input = 1 ORDER BY created_at',
            (ConversationState.ACTIVE.value,),
        )
        return [
            Conversation(
                id=row[0], type=ConversationType(row[1]),
                state=ConversationState(row[2]), created_at=row[3],
                awaiting_input=bool(row[4]),
            )
            for row in cursor.fetchall()
        ]

    def active_conversations(
        self, conv_type: ConversationType | None = None,
    ) -> list[Conversation]:
        """List all active conversations, optionally filtered by type."""
        if conv_type is not None:
            cursor = self._conn.execute(
                'SELECT id, type, state, created_at, awaiting_input FROM conversations '
                'WHERE state = ? AND type = ? ORDER BY created_at',
                (ConversationState.ACTIVE.value, conv_type.value),
            )
        else:
            cursor = self._conn.execute(
                'SELECT id, type, state, created_at, awaiting_input FROM conversations '
                'WHERE state = ? ORDER BY created_at',
                (ConversationState.ACTIVE.value,),
            )
        return [
            Conversation(
                id=row[0], type=ConversationType(row[1]),
                state=ConversationState(row[2]), created_at=row[3],
                awaiting_input=bool(row[4]),
            )
            for row in cursor.fetchall()
        ]

    def find_conversation(
        self, conv_type: ConversationType, qualifier: str,
    ) -> Conversation | None:
        """Find a conversation by type and qualifier."""
        cid = make_conversation_id(conv_type, qualifier)
        return self.get_conversation(cid)

    def close(self) -> None:
        self._conn.close()


class MessageBusInputProvider:
    """InputProvider backed by a message bus conversation.

    When called, sends the agent's question to the conversation as an
    'orchestrator' message, then polls for a 'human' response.  This
    preserves the full exchange as an audit trail in the message bus.

    Exposes ``is_waiting`` and ``current_request`` for compatibility
    with the InputProvider interface.
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
            # Structural signal for the bridge (issue #288)
            self.bus.set_awaiting_input(self.conversation_id, True)

            # Poll for human response
            since = time.time()
            while True:
                messages = self.bus.receive(self.conversation_id, since_timestamp=since)
                for msg in messages:
                    if msg.sender == 'human':
                        return msg.content
                await asyncio.sleep(self.poll_interval)
        finally:
            self.bus.set_awaiting_input(self.conversation_id, False)
            self._waiting = False
            self._current_request = None


# ── IPC helpers for bridge / external clients ────────────────────────────────

def check_message_bus_request(
    bus_path: str, conversation_id: str,
) -> dict | None:
    """Check if the orchestrator is waiting for input via the message bus.

    Uses the structural awaiting_input flag set by MessageBusInputProvider
    (issue #288).  Returns a dict with 'bridge_text' (the most recent
    orchestrator message), or None if no input is pending.
    """
    import os
    if not os.path.exists(bus_path):
        return None
    try:
        bus = SqliteMessageBus(bus_path)
        try:
            conv = bus.get_conversation(conversation_id)
            if conv is None or not conv.awaiting_input:
                return None
            messages = bus.receive(conversation_id)
            for msg in reversed(messages):
                if msg.sender == 'orchestrator':
                    return {'bridge_text': msg.content}
            return None
        finally:
            bus.close()
    except Exception:
        return None


def send_message_bus_response(
    bus_path: str, conversation_id: str, response: str,
) -> bool:
    """Send a human response to the message bus.

    The orchestrator's MessageBusInputProvider polls for 'human' messages
    and will pick this up.

    Returns True on success, False on failure.
    """
    try:
        bus = SqliteMessageBus(bus_path)
        try:
            bus.send(conversation_id, 'human', response)
            return True
        finally:
            bus.close()
    except Exception:
        return False
