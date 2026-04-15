"""Message bus with adapter interface for human-agent communication.

Replaces the blocking FIFO IPC with a persistent, conversation-based
message bus.  The adapter interface allows swapping storage backends
(SQLite for POC, external adapters like Slack/Teams later).

Conversation types (see docs/proposals/chat-experience/references/conversation-identity.md):
  - office_manager: one per system, persistent
  - job: one per project+job, lives with the job
  - task: one per project+job+task, lives with the task
  - proxy: one per decider, indefinite persistence
  - liaison: session-scoped, requester+target
  - project_session: one per active session (legacy, from issue #200)
  - subteam: one per dispatch (legacy, from issue #200)

Issues #200, #263, #288.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from teaparty.messaging.bus import InputRequest

if TYPE_CHECKING:
    from teaparty.util.role_enforcer import RoleEnforcer

_log = logging.getLogger('teaparty.messaging.conversations')


def agent_bus_path(teaparty_home: str, agent_name: str) -> str:
    """Return the canonical path to an agent's persistent message database.

    Convention: {teaparty_home}/management/agents/{agent-name}/{agent-name}-messages.db

    Every agent has a persistent bus at this path.  The bridge and orchestrator
    both use this function to locate the same database.  Agent name is the
    kebab-case directory name under management/agents/ (e.g. 'office-manager',
    'teaparty-lead', 'proxy').
    """
    return os.path.join(
        teaparty_home, 'management', 'agents', agent_name,
        f'{agent_name}-messages.db',
    )


class ConversationType(Enum):
    OFFICE_MANAGER = 'office_manager'    # One per system, persistent
    PROJECT_MANAGER = 'project_manager'  # One per project+human, persistent
    PROJECT_SESSION = 'project_session'  # One per session, closes when session ends
    SUBTEAM = 'subteam'                  # One per dispatch, proxy participates
    JOB = 'job'                          # One per project+job, lives with the job
    TASK = 'task'                        # One per project+job+task, lives with the task
    PROXY = 'proxy'                       # One per decider, indefinite persistence
    LIAISON = 'liaison'                  # Session-scoped, requester+target
    CONFIG_LEAD = 'config_lead'          # One per entity-scope, persistent config lead chat
    PROJECT_LEAD = 'project_lead'        # One per project lead, persistent


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
    ConversationType.PROJECT_MANAGER: 'pm',
    ConversationType.PROJECT_SESSION: 'session',
    ConversationType.SUBTEAM: 'team',
    ConversationType.JOB: 'job',
    ConversationType.TASK: 'task',
    ConversationType.PROXY: 'proxy',
    ConversationType.LIAISON: 'liaison',
    ConversationType.CONFIG_LEAD: 'config',
    ConversationType.PROJECT_LEAD: 'lead',
}


def make_conversation_id(conv_type: ConversationType, qualifier: str = '') -> str:
    """Create a namespaced conversation ID.

    When *qualifier* is empty the prefix alone is returned (no colon).

    Examples:
        make_conversation_id(ConversationType.OFFICE_MANAGER)
        → 'om'

        make_conversation_id(ConversationType.PROJECT_SESSION, '20260327-143000')
        → 'session:20260327-143000'
    """
    prefix = _PREFIXES[conv_type]
    return f'{prefix}:{qualifier}' if qualifier else prefix


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

        # Agent context records for bus-mediated agent-to-agent dispatch (issue #351)
        self._conn.execute('''
            CREATE TABLE IF NOT EXISTS agent_contexts (
                context_id TEXT PRIMARY KEY,
                initiator_agent_id TEXT NOT NULL,
                recipient_agent_id TEXT NOT NULL,
                parent_context_id TEXT NOT NULL DEFAULT '',
                session_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open',
                pending_count INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                conversation_status TEXT NOT NULL DEFAULT 'open',
                agent_worktree_path TEXT NOT NULL DEFAULT ''
            )
        ''')
        # Migrate existing DBs that predate the conversation_status column (issue #383)
        try:
            self._conn.execute(
                "ALTER TABLE agent_contexts "
                "ADD COLUMN conversation_status TEXT NOT NULL DEFAULT 'open'"
            )
        except sqlite3.OperationalError:
            pass  # Column already exists
        # Migrate existing DBs that predate the agent_worktree_path column (issue #379)
        try:
            self._conn.execute(
                "ALTER TABLE agent_contexts "
                "ADD COLUMN agent_worktree_path TEXT NOT NULL DEFAULT ''"
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
            'ORDER BY timestamp ASC, id ASC',
            (conversation_id, since_timestamp),
        )
        return [
            Message(id=row[0], conversation=row[1], sender=row[2],
                    content=row[3], timestamp=row[4])
            for row in cursor.fetchall()
        ]

    def receive_since_cursor(
        self, conversation_id: str, cursor: str = '',
    ) -> tuple[list[Message], str]:
        """Return (messages, new_cursor) for a cursor-based read.

        ``cursor`` is an opaque string of the form ``"{timestamp:.9f}:{id}"``
        or the empty string for a read from the beginning of the conversation.
        The total order over rows is ``(timestamp ASC, id ASC)``, which is
        stable under equal timestamps and across restarts.

        The returned cursor is the watermark of the last row returned, or the
        input cursor if no rows were returned. Both the rows and the cursor
        are captured in the same SQLite read, so there is no skew between
        "rows from time T" and "cursor from time T + delta".

        This is the read path for the fetch-and-subscribe atomicity contract
        (issue #398). Callers that want timestamp-based polling should keep
        using ``receive()``.
        """
        if cursor:
            try:
                ts_part, id_part = cursor.split(':', 1)
                ts = float(ts_part)
            except ValueError as exc:
                raise ValueError(f'invalid cursor: {cursor!r}') from exc
            rows = self._conn.execute(
                'SELECT id, conversation, sender, content, timestamp '
                'FROM messages '
                'WHERE conversation = ? '
                '  AND (timestamp > ? OR (timestamp = ? AND id > ?)) '
                'ORDER BY timestamp ASC, id ASC',
                (conversation_id, ts, ts, id_part),
            ).fetchall()
        else:
            rows = self._conn.execute(
                'SELECT id, conversation, sender, content, timestamp '
                'FROM messages '
                'WHERE conversation = ? '
                'ORDER BY timestamp ASC, id ASC',
                (conversation_id,),
            ).fetchall()

        messages = [
            Message(id=row[0], conversation=row[1], sender=row[2],
                    content=row[3], timestamp=row[4])
            for row in rows
        ]
        if messages:
            last = messages[-1]
            new_cursor = f'{last.timestamp:.9f}:{last.id}'
        else:
            new_cursor = cursor
        return messages, new_cursor

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

    def clear_messages(self, conversation_id: str) -> None:
        """Delete all messages for a conversation."""
        self._conn.execute(
            'DELETE FROM messages WHERE conversation = ?',
            (conversation_id,),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ── Agent context records (issue #351) ───────────────────────────────────

    def create_agent_context(
        self,
        context_id: str,
        initiator_agent_id: str,
        recipient_agent_id: str,
    ) -> None:
        """Create a new agent-to-agent conversation context record.

        Status begins as 'open'; pending_count begins at 0.
        parent_context_id is stored for fan-in tracking (empty string if no parent).
        """
        ts = time.time()
        self._conn.execute(
            'INSERT INTO agent_contexts '
            '(context_id, initiator_agent_id, recipient_agent_id, created_at) '
            'VALUES (?, ?, ?, ?)',
            (context_id, initiator_agent_id, recipient_agent_id, ts),
        )
        self._conn.commit()

    def create_agent_context_and_increment_parent(
        self,
        context_id: str,
        initiator_agent_id: str,
        recipient_agent_id: str,
        parent_context_id: str,
    ) -> None:
        """Atomically create a sub-context and increment the parent's pending_count.

        Both writes succeed or both fail (SQLite transaction).  A crash between
        them would leave the fan-in counter permanently wrong; the transaction
        prevents that.

        Raises ValueError if parent_context_id does not exist.
        """
        # Verify parent exists before starting the transaction
        row = self._conn.execute(
            'SELECT context_id FROM agent_contexts WHERE context_id = ?',
            (parent_context_id,),
        ).fetchone()
        if row is None:
            raise ValueError(
                f'Parent context {parent_context_id!r} does not exist; '
                'cannot create child context'
            )

        ts = time.time()
        with self._conn:
            self._conn.execute(
                'INSERT INTO agent_contexts '
                '(context_id, initiator_agent_id, recipient_agent_id, '
                'parent_context_id, created_at) '
                'VALUES (?, ?, ?, ?, ?)',
                (context_id, initiator_agent_id, recipient_agent_id,
                 parent_context_id, ts),
            )
            self._conn.execute(
                'UPDATE agent_contexts SET pending_count = pending_count + 1 '
                'WHERE context_id = ?',
                (parent_context_id,),
            )

    def get_agent_context(self, context_id: str) -> dict | None:
        """Return the agent context record as a dict, or None if not found."""
        row = self._conn.execute(
            'SELECT context_id, initiator_agent_id, recipient_agent_id, '
            'parent_context_id, session_id, status, pending_count, created_at, '
            'conversation_status, agent_worktree_path '
            'FROM agent_contexts WHERE context_id = ?',
            (context_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            'context_id': row[0],
            'initiator_agent_id': row[1],
            'recipient_agent_id': row[2],
            'parent_context_id': row[3],
            'session_id': row[4],
            'status': row[5],
            'pending_count': row[6],
            'created_at': row[7],
            'conversation_status': row[8],
            'agent_worktree_path': row[9],
        }

    def close_agent_conversation(self, context_id: str) -> None:
        """Transition the conversation to conversation_status='closed'.

        Only the originator should call this.  Subsequent follow-up Sends
        to a closed conversation are rejected at the routing layer (issue #383).
        """
        self._conn.execute(
            "UPDATE agent_contexts SET conversation_status = 'closed' "
            'WHERE context_id = ?',
            (context_id,),
        )
        self._conn.commit()

    def set_agent_context_session_id(self, context_id: str, session_id: str) -> None:
        """Record the Claude session ID captured from the first invocation."""
        self._conn.execute(
            'UPDATE agent_contexts SET session_id = ? WHERE context_id = ?',
            (session_id, context_id),
        )
        self._conn.commit()

    def set_agent_context_worktree_path(self, context_id: str, worktree_path: str) -> None:
        """Record the agent's worktree path for cleanup on conversation close."""
        self._conn.execute(
            'UPDATE agent_contexts SET agent_worktree_path = ? WHERE context_id = ?',
            (worktree_path, context_id),
        )
        self._conn.commit()

    def increment_pending_count(self, context_id: str) -> None:
        """Increment pending_count by 1 (fan-out: one more worker in flight)."""
        self._conn.execute(
            'UPDATE agent_contexts SET pending_count = pending_count + 1 '
            'WHERE context_id = ?',
            (context_id,),
        )
        self._conn.commit()

    def decrement_pending_count(self, context_id: str) -> int:
        """Decrement pending_count by 1 and return the new count.

        When the count reaches 0, the fan-in is complete and the caller
        should be re-invoked.
        """
        self._conn.execute(
            'UPDATE agent_contexts SET pending_count = pending_count - 1 '
            'WHERE context_id = ?',
            (context_id,),
        )
        self._conn.commit()
        row = self._conn.execute(
            'SELECT pending_count FROM agent_contexts WHERE context_id = ?',
            (context_id,),
        ).fetchone()
        return row[0] if row else 0

    def close_agent_context(self, context_id: str) -> None:
        """Transition the context to status='closed'."""
        self._conn.execute(
            "UPDATE agent_contexts SET status = 'closed' WHERE context_id = ?",
            (context_id,),
        )
        self._conn.commit()

    def close_all_agent_contexts(self) -> None:
        """Close all open agent context records."""
        self._conn.execute(
            "UPDATE agent_contexts SET status = 'closed' WHERE status = 'open'"
        )
        self._conn.commit()

    def close_agent_context_tree(self, parent_context_id: str) -> None:
        """Close the parent context and all its direct children.

        Scoped to one conversation's context tree — other conversations'
        contexts are not affected.
        """
        self._conn.execute(
            "UPDATE agent_contexts SET status = 'closed' "
            "WHERE status = 'open' AND "
            "(context_id = ? OR parent_context_id = ?)",
            (parent_context_id, parent_context_id),
        )
        self._conn.commit()

    def open_agent_contexts_for_parent(self, parent_context_id: str) -> list[dict]:
        """Return open agent context records that are children of the given parent."""
        cursor = self._conn.execute(
            'SELECT context_id, initiator_agent_id, recipient_agent_id, '
            'parent_context_id, session_id, status, pending_count, created_at, '
            'conversation_status, agent_worktree_path '
            "FROM agent_contexts WHERE status = 'open' "
            "AND parent_context_id = ? ORDER BY created_at",
            (parent_context_id,),
        )
        return [
            {
                'context_id': row[0],
                'initiator_agent_id': row[1],
                'recipient_agent_id': row[2],
                'parent_context_id': row[3],
                'session_id': row[4],
                'status': row[5],
                'pending_count': row[6],
                'created_at': row[7],
                'conversation_status': row[8],
                'agent_worktree_path': row[9],
            }
            for row in cursor.fetchall()
        ]

    def open_agent_contexts(self) -> list[dict]:
        """Return all agent context records with status='open'."""
        cursor = self._conn.execute(
            'SELECT context_id, initiator_agent_id, recipient_agent_id, '
            'parent_context_id, session_id, status, pending_count, created_at, '
            'conversation_status, agent_worktree_path '
            "FROM agent_contexts WHERE status = 'open' ORDER BY created_at"
        )
        return [
            {
                'context_id': row[0],
                'initiator_agent_id': row[1],
                'recipient_agent_id': row[2],
                'parent_context_id': row[3],
                'session_id': row[4],
                'status': row[5],
                'pending_count': row[6],
                'created_at': row[7],
                'conversation_status': row[8],
                'agent_worktree_path': row[9],
            }
            for row in cursor.fetchall()
        ]


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
        sender: str = 'orchestrator',
    ):
        self.bus = bus
        self.conversation_id = conversation_id
        self.poll_interval = poll_interval
        self.sender = sender
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
            # Record the question attributed to the project lead (or 'orchestrator' fallback).
            # Skip if empty — the agent's output is already visible in the conversation
            # (Socratic querying: INTENT_ASSERT with no artifact yet).
            if request.bridge_text:
                self.bus.send(
                    self.conversation_id,
                    self.sender,
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
                # Accept any non-human sender: the gate question may come from the
                # project lead (e.g. 'comics-lead') or the legacy 'orchestrator' (Issue #408).
                if msg.sender != 'human':
                    return {'bridge_text': msg.content}
            return None
        finally:
            bus.close()
    except Exception:
        return None


class SessionRegistry:
    """Maps (member, context_id) to session file information for --resume injection.

    The registry is populated by the bus listener after it first spawns an agent
    (capturing session_id from ``--output-format json`` output and the JSONL path
    from the file system).  The MCP server's ``send_handler`` consults it when
    continuing an existing thread: it looks up the session file, injects the
    composite, then posts.  For first sends (no context_id), no session exists
    yet and injection is skipped — the composite is delivered as ``$TASK`` by
    the listener.

    File-backed (JSON) so the registry survives across MCP server restarts
    within a session.  The registry path is stored in ``SESSION_REGISTRY_PATH``.
    """

    def __init__(self, registry_path: str) -> None:
        self._path = registry_path

    def _load(self) -> dict:
        if not os.path.exists(self._path):
            return {}
        with open(self._path) as f:
            return json.load(f)

    def _save(self, data: dict) -> None:
        directory = os.path.dirname(self._path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self._path, 'w') as f:
            json.dump(data, f)

    def register(
        self,
        member: str,
        context_id: str,
        session_id: str,
        session_file: str,
        cwd: str,
    ) -> None:
        """Record session info for a (member, context_id) pair."""
        data = self._load()
        data[f'{member}:{context_id}'] = {
            'session_id': session_id,
            'session_file': session_file,
            'cwd': cwd,
        }
        self._save(data)

    def lookup(
        self, member: str, context_id: str,
    ) -> tuple[str, str, str] | None:
        """Return (session_id, session_file, cwd) for the pair, or None."""
        data = self._load()
        entry = data.get(f'{member}:{context_id}')
        if entry is None:
            return None
        return entry['session_id'], entry['session_file'], entry['cwd']


def inject_composite_into_history(
    session_file: str,
    composite: str,
    session_id: str,
    cwd: str,
    *,
    version: str = '',
) -> None:
    """Inject a composite message into an agent's conversation history.

    Appends a JSONL entry to the session file so the recipient's next
    ``--resume`` invocation sees the composite as an incoming user message.

    The entry follows the observed Claude Code JSONL schema (invocation-model.md,
    Worktree Reuse section):
    - ``type``: ``"user"``
    - ``message.role``: ``"user"``
    - ``message.content``: the composite message
    - ``isSidechain``: ``True``
    - ``userType``: ``"external"``
    - ``parentUuid``: UUID of the last existing entry (``None`` for empty file)

    The session file path follows the observed layout:
    ``~/.claude/projects/{cwd.replace('/', '-')}/{session_id}.jsonl``.
    Callers supply the fully-resolved path; this function does not derive it.

    Args:
        session_file: Absolute path to the recipient's ``.jsonl`` session file.
        composite: The composite message (Task/Context envelope) to inject.
        session_id: Claude Code session UUID for this conversation thread.
        cwd: Working directory of the recipient's invocation.
        version: Claude Code version string. Defaults to CLAUDE_VERSION env var,
            then empty string if unset.
    """
    import json as _json
    import uuid as _uuid
    from datetime import datetime, timezone

    last_uuid = None
    if os.path.exists(session_file):
        with open(session_file) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entry = _json.loads(line)
                        last_uuid = entry.get('uuid')
                    except _json.JSONDecodeError:
                        pass

    if not version:
        version = os.environ.get('CLAUDE_VERSION', '')

    now = datetime.now(timezone.utc)
    ms = now.microsecond // 1000
    timestamp = now.strftime('%Y-%m-%dT%H:%M:%S.') + f'{ms:03d}Z'

    entry = {
        'parentUuid': last_uuid,
        'isSidechain': True,
        'userType': 'external',
        'cwd': cwd,
        'sessionId': session_id,
        'version': version,
        'type': 'user',
        'message': {
            'role': 'user',
            'content': composite,
        },
        'uuid': str(_uuid.uuid4()),
        'timestamp': timestamp,
    }

    os.makedirs(os.path.dirname(session_file), exist_ok=True)
    with open(session_file, 'a') as f:
        f.write(_json.dumps(entry) + '\n')


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
