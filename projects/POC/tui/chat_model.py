"""Data model for the TUI chat panel — conversation listing, unread tracking, messaging.

Sits between the Textual chat screen and the SqliteMessageBus. All business
logic for conversation discovery, unread counts, attention detection, and
message formatting lives here so it can be tested without Textual.

Issue #206.
"""
from __future__ import annotations

import time
from datetime import datetime

from projects.POC.orchestrator.messaging import (
    Conversation,
    ConversationState,
    Message,
    SqliteMessageBus,
)


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
    """

    def __init__(self, bus: SqliteMessageBus):
        self.bus = bus
        self.index = ConversationIndex(bus)
        self.unread_tracker = UnreadTracker()
        self._selected: str = ''

    def conversations(self) -> list[Conversation]:
        """List all active conversations."""
        return self.index.list_conversations()

    def messages(self, conversation_id: str) -> list[Message]:
        """Return all messages in a conversation."""
        return self.bus.receive(conversation_id)

    def select_conversation(self, conversation_id: str) -> None:
        """Switch to a conversation, marking it as read."""
        self._selected = conversation_id
        self.unread_tracker.mark_read(conversation_id)

    def send_message(self, conversation_id: str, content: str) -> str:
        """Send a human message to a conversation. Returns message ID."""
        return self.bus.send(conversation_id, 'human', content)

    def needs_attention(self, conversation_id: str) -> bool:
        """True if the conversation has a pending orchestrator question.

        A conversation needs attention when the last message is from
        the orchestrator (unanswered question / gate).
        """
        messages = self.bus.receive(conversation_id)
        if not messages:
            return False
        return messages[-1].sender == 'orchestrator'

    def attention_conversations(self) -> list[Conversation]:
        """Return conversations that need human attention."""
        result = []
        for conv in self.index.list_conversations():
            if self.needs_attention(conv.id):
                result.append(conv)
        return result


def format_message(msg: Message) -> str:
    """Format a message for display with sender label and timestamp.

    Returns a plain-text string like '[orchestrator] 14:30 — Review this'.
    """
    dt = datetime.fromtimestamp(msg.timestamp)
    time_str = dt.strftime('%H:%M')
    return f'[{msg.sender}] {time_str} — {msg.content}'
