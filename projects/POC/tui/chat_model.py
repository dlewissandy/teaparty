"""Data model for the TUI chat panel — conversation listing, unread tracking, messaging.

Sits between the Textual chat screen and the SqliteMessageBus. All business
logic for conversation discovery, unread counts, attention detection, and
message formatting lives here so it can be tested without Textual.

Issue #206.
"""
from __future__ import annotations

import os
import time
from datetime import datetime

from projects.POC.orchestrator.messaging import (
    Conversation,
    ConversationState,
    Message,
    SqliteMessageBus,
)


# ── CfA state labels for gate context ─────────────────────────────────────

_GATE_LABELS: dict[str, str] = {
    'INTENT_ASSERT': 'Review intent',
    'PLAN_ASSERT': 'Review plan',
    'WORK_ASSERT': 'Review completed work',
    'INTENT_ESCALATE': 'Agent has a question about intent',
    'PLANNING_ESCALATE': 'Agent has a question about the plan',
    'TASK_ESCALATE': 'Agent has a question about the task',
}


class ConversationIndex:
    """Discovers and lists active conversations from the message bus."""

    def __init__(self, bus: SqliteMessageBus):
        self._bus = bus

    def list_conversations(self) -> list[Conversation]:
        """Return all active conversations, ordered by creation time."""
        return self._bus.active_conversations()


class UnreadTracker:
    """Tracks last-read timestamps per conversation for unread counts."""

    def __init__(self):
        self._last_read: dict[str, float] = {}

    def mark_read(self, conversation_id: str) -> None:
        """Mark a conversation as read at the current time."""
        self._last_read[conversation_id] = time.time()

    def unread_count(self, bus: SqliteMessageBus, conversation_id: str) -> int:
        """Count messages in a conversation since the last mark_read."""
        since = self._last_read.get(conversation_id, 0.0)
        messages = bus.receive(conversation_id, since_timestamp=since)
        return len(messages)

    def has_unread(self, bus: SqliteMessageBus, conversation_id: str) -> bool:
        """True if there are unread messages in the conversation."""
        return self.unread_count(bus, conversation_id) > 0


class ChatModel:
    """Facade for the chat panel's data needs.

    Wraps ConversationIndex, UnreadTracker, and message bus operations
    into a single interface the chat screen can call.

    Supports single-bus mode (ChatModel(bus)) or multi-bus aggregation
    (ChatModel.from_bus_paths([path1, path2])) for spanning conversations
    across session databases.
    """

    def __init__(self, bus: SqliteMessageBus):
        self.bus = bus
        self.index = ConversationIndex(bus)
        self.unread_tracker = UnreadTracker()
        self._selected: str = ''
        # Multi-bus support: maps conversation_id → bus
        self._buses: list[SqliteMessageBus] = [bus]
        self._conv_bus: dict[str, SqliteMessageBus] = {}

    @classmethod
    def from_bus_paths(cls, paths: list[str]) -> 'ChatModel':
        """Create a ChatModel aggregating conversations across multiple buses."""
        buses = [SqliteMessageBus(p) for p in paths if os.path.exists(p)]
        if not buses:
            raise ValueError('No valid bus paths provided')
        model = cls(buses[0])
        model._buses = buses
        return model

    def conversations(self) -> list[Conversation]:
        """List all active conversations across all buses."""
        all_convos: list[Conversation] = []
        self._conv_bus.clear()
        for bus in self._buses:
            for conv in bus.active_conversations():
                if conv.id not in self._conv_bus:
                    self._conv_bus[conv.id] = bus
                    all_convos.append(conv)
        all_convos.sort(key=lambda c: c.created_at)
        return all_convos

    def _bus_for(self, conversation_id: str) -> SqliteMessageBus:
        """Return the bus that owns a conversation."""
        if conversation_id in self._conv_bus:
            return self._conv_bus[conversation_id]
        # Refresh mapping
        self.conversations()
        return self._conv_bus.get(conversation_id, self.bus)

    def messages(self, conversation_id: str) -> list[Message]:
        """Return all messages in a conversation."""
        return self._bus_for(conversation_id).receive(conversation_id)

    def select_conversation(self, conversation_id: str) -> None:
        """Switch to a conversation, marking it as read."""
        self._selected = conversation_id
        self.unread_tracker.mark_read(conversation_id)

    def send_message(self, conversation_id: str, content: str) -> str:
        """Send a human message to a conversation. Returns message ID."""
        return self._bus_for(conversation_id).send(conversation_id, 'human', content)

    def needs_attention(self, conversation_id: str) -> bool:
        """True if the conversation has a pending orchestrator question.

        A conversation needs attention when the last message is from
        the orchestrator (unanswered question / gate).
        """
        messages = self._bus_for(conversation_id).receive(conversation_id)
        if not messages:
            return False
        return messages[-1].sender == 'orchestrator'

    def attention_conversations(self) -> list[Conversation]:
        """Return conversations that need human attention."""
        result = []
        for conv in self.conversations():
            if self.needs_attention(conv.id):
                result.append(conv)
        return result

    def attention_count(self) -> int:
        """Total number of conversations needing human attention.

        Used by the dashboard to show a notification badge without
        opening the chat screen.
        """
        return len(self.attention_conversations())

    def close(self) -> None:
        """Close all bus connections."""
        for bus in self._buses:
            try:
                bus.close()
            except Exception:
                pass


def format_message(msg: Message) -> str:
    """Format a message for display with sender label and timestamp.

    Returns a plain-text string like '[orchestrator] 14:30 — Review this'.
    """
    dt = datetime.fromtimestamp(msg.timestamp)
    time_str = dt.strftime('%H:%M')
    return f'[{msg.sender}] {time_str} — {msg.content}'


def format_gate_context(cfa_state: str, artifact_path: str) -> str:
    """Format CfA gate context for display in a chat message.

    Provides a human-readable label for the gate and references
    the artifact under review (if any).
    """
    label = _GATE_LABELS.get(cfa_state, cfa_state)
    if artifact_path:
        filename = os.path.basename(artifact_path)
        return f'{label} — see {filename}'
    return label
