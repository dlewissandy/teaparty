"""Per-session SqliteMessageBus polling and WebSocket message/input_requested event push.

Polls each active session's message bus for new messages and conversations
with awaiting_input=1. Emits events via the broadcast callback.

Events emitted:
  message         — new message in a conversation
  input_requested — conversation has awaiting_input=1

Issue #297.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Awaitable

_log = logging.getLogger('bridge.message_relay')

BroadcastFn = Callable[[dict], Awaitable[None]]


class MessageRelay:
    """Polls per-session message buses and emits message/input_requested events.

    Args:
        bus_registry: Mutable dict ``{session_id: SqliteMessageBus}``. Shared
                      with the StatePoller, which manages bus lifecycle.
        broadcast: Async callable ``(event: dict) -> None``.
    """

    def __init__(self, bus_registry: dict, broadcast: BroadcastFn):
        self._buses = bus_registry
        self._broadcast = broadcast
        # Last-seen timestamp per conversation_id
        self._last_ts: dict[str, float] = {}
        # Conversations we've already surfaced as awaiting_input
        self._awaiting: set[str] = set()

    async def poll_once(self) -> None:
        """Poll all active buses for new messages and awaiting_input flags."""
        for session_id, bus in list(self._buses.items()):
            try:
                await self._poll_bus(session_id, bus)
            except Exception:
                _log.exception('Error polling bus for session %s', session_id)

    async def _poll_bus(self, session_id: str, bus) -> None:
        # Poll for new messages in all conversations
        try:
            conv_ids = bus.conversations()
        except Exception:
            return

        for cid in conv_ids:
            last = self._last_ts.get(cid, 0.0)
            try:
                messages = bus.receive(cid, since_timestamp=last)
            except Exception:
                continue
            for msg in messages:
                await self._broadcast({
                    'type': 'message',
                    'id': msg.id,
                    'conversation_id': cid,
                    'sender': msg.sender,
                    'content': msg.content,
                    'timestamp': msg.timestamp,
                })
                if msg.timestamp > last:
                    last = msg.timestamp
            self._last_ts[cid] = last

        # Poll for input_requested flag changes
        try:
            waiting = bus.conversations_awaiting_input()
        except Exception:
            return

        waiting_ids = {c.id for c in waiting}
        for cid in waiting_ids - self._awaiting:
            # Fetch the question — the latest orchestrator message in this conversation.
            question = ''
            try:
                all_msgs = bus.receive(cid, since_timestamp=0.0)
                for msg in reversed(all_msgs):
                    if msg.sender == 'orchestrator':
                        question = msg.content
                        break
            except Exception:
                pass
            await self._broadcast({
                'type': 'input_requested',
                'session_id': session_id,
                'conversation_id': cid,
                'question': question,
            })
        self._awaiting = (self._awaiting - set(conv_ids)) | waiting_ids

    async def run(self, interval: float = 1.0) -> None:
        """Poll continuously at the given interval (seconds)."""
        while True:
            try:
                await self.poll_once()
            except Exception:
                _log.exception('Error in MessageRelay.poll_once')
            await asyncio.sleep(interval)
