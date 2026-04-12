"""Per-subscription chat-message dispatcher and escalation event emitter.

Implements the server side of the fetch-and-subscribe atomicity contract
(issue #398):

  - ``message`` events are delivered per-(connection, conversation) using
    a client-owned cursor. The relay never broadcasts message events to
    connections without an active subscription for the conversation.
  - ``input_requested`` and ``escalation_cleared`` events track conversation
    ``awaiting_input`` transitions and are broadcast to every connected
    client via the bridge's broadcast callback (they are not scoped to a
    subscription).

Every message is delivered to every subscribed client exactly once,
across the join between subscribe-time catch-up and live polling. Clients
do not filter or dedup.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

_log = logging.getLogger('teaparty.bridge.message_relay')

BroadcastFn = Callable[[dict], Awaitable[None]]


class MessageRelay:
    """Subscription-scoped chat dispatcher + global escalation broadcaster.

    Args:
        bus_registry: Mutable dict ``{session_id: SqliteMessageBus}``.
                      Shared with the StatePoller, which manages bus
                      lifecycle.
        broadcast:    Async callable ``(event: dict) -> None`` used for
                      non-subscription events (``input_requested``,
                      ``escalation_cleared``, any future connection-agnostic
                      events). Message events are NOT sent via this path.
    """

    def __init__(self, bus_registry: dict, broadcast: BroadcastFn):
        self._buses = bus_registry
        self._broadcast = broadcast

        # Per-connection subscriptions: connection -> {conversation_id: cursor}.
        # The connection object must expose ``async send_json(payload)``.
        self._subscriptions: dict[Any, dict[str, str]] = {}

        # Lock serializing subscription mutations with per-connection dispatch.
        # A subscribe must atomically: read from the cursor, push each row,
        # advance the cursor, and install the subscription — with no gap in
        # which the dispatcher could also dispatch the same rows.
        self._lock = asyncio.Lock()

        # awaiting_input tracking for escalation events. Keyed by
        # conversation_id (which is globally unique across buses).
        self._awaiting: dict[str, str] = {}  # cid -> session_id

    # ── Connection lifecycle ────────────────────────────────────────────────

    def register_connection(self, connection: Any) -> None:
        """Register a new WebSocket connection.

        A registered connection with no subscriptions receives no ``message``
        events. It only starts receiving messages after calling
        :meth:`subscribe` for a conversation.
        """
        self._subscriptions.setdefault(connection, {})

    def unregister_connection(self, connection: Any) -> None:
        """Remove a connection and all of its subscriptions."""
        self._subscriptions.pop(connection, None)

    # ── Subscription management ─────────────────────────────────────────────

    async def subscribe(
        self, connection: Any, conversation_id: str, since_cursor: str = '',
    ) -> None:
        """Subscribe *connection* to *conversation_id* starting at *since_cursor*.

        Atomically: replays every message strictly after ``since_cursor``
        (the catch-up phase), advances the cursor to the watermark of the
        replayed rows, and installs the subscription. Subsequent polls will
        deliver only newer rows, so there is no handoff gap.
        """
        async with self._lock:
            bus = self._find_bus_for(conversation_id)
            if bus is None:
                # No bus yet — still install the subscription so future
                # writes get delivered once a bus appears.
                conns = self._subscriptions.setdefault(connection, {})
                conns[conversation_id] = since_cursor
                return

            messages, new_cursor = bus.receive_since_cursor(
                conversation_id, since_cursor,
            )
            for msg in messages:
                await self._send_message(connection, conversation_id, msg)

            conns = self._subscriptions.setdefault(connection, {})
            conns[conversation_id] = new_cursor

    async def unsubscribe(self, connection: Any, conversation_id: str) -> None:
        """Stop delivering messages on *conversation_id* to *connection*."""
        async with self._lock:
            conns = self._subscriptions.get(connection)
            if conns is not None:
                conns.pop(conversation_id, None)

    # ── Polling ─────────────────────────────────────────────────────────────

    async def poll_once(self) -> None:
        """Poll every subscription and every bus's awaiting_input flag.

        Message dispatch is per-subscription: each ``(connection, cid)``
        owns its own cursor and receives rows independently. Escalation
        events are global and broadcast via the bridge broadcast callback.
        """
        await self._dispatch_messages()
        await self._poll_escalations()

    async def _dispatch_messages(self) -> None:
        async with self._lock:
            # Snapshot connection/subscription pairs so mutations during
            # dispatch (unsubscribe from another task) don't blow up the loop.
            pairs: list[tuple[Any, str, str]] = [
                (conn, cid, cursor)
                for conn, subs in self._subscriptions.items()
                for cid, cursor in subs.items()
            ]
            for connection, cid, cursor in pairs:
                bus = self._find_bus_for(cid)
                if bus is None:
                    continue
                try:
                    messages, new_cursor = bus.receive_since_cursor(cid, cursor)
                except Exception:
                    _log.exception('Error reading cursor for %s', cid)
                    continue
                if not messages:
                    continue
                for msg in messages:
                    await self._send_message(connection, cid, msg)
                # Advance the stored cursor. Check the subscription still
                # exists — it could have been removed between snapshot and
                # dispatch (under the lock it can't, but be defensive).
                subs = self._subscriptions.get(connection)
                if subs is not None and cid in subs:
                    subs[cid] = new_cursor

    async def _poll_escalations(self) -> None:
        """Scan every bus for awaiting_input transitions.

        Emits ``input_requested`` on False→True transitions and
        ``escalation_cleared`` on True→False transitions. Events are sent
        via the broadcast callback (not per-subscription) because the
        dashboard's escalation UI is global.
        """
        current: dict[str, tuple[str, str]] = {}  # cid -> (session_id, question)
        for session_id, bus in list(self._buses.items()):
            try:
                waiting = bus.conversations_awaiting_input()
            except Exception:
                _log.exception('Error reading awaiting_input for %s', session_id)
                continue
            for conv in waiting:
                question = ''
                try:
                    all_msgs = bus.receive(conv.id, since_timestamp=0.0)
                    for msg in reversed(all_msgs):
                        if msg.sender == 'orchestrator':
                            question = msg.content
                            break
                except Exception:
                    pass
                current[conv.id] = (session_id, question)

        # False → True transitions
        for cid, (session_id, question) in current.items():
            if cid in self._awaiting:
                continue
            await self._broadcast({
                'type': 'input_requested',
                'session_id': session_id,
                'conversation_id': cid,
                'question': question,
            })
            self._awaiting[cid] = session_id

        # True → False transitions
        cleared = [cid for cid in self._awaiting if cid not in current]
        for cid in cleared:
            session_id = self._awaiting.pop(cid)
            await self._broadcast({
                'type': 'escalation_cleared',
                'session_id': session_id,
                'conversation_id': cid,
            })

    async def run(self, interval: float = 1.0) -> None:
        """Poll continuously at the given interval (seconds)."""
        while True:
            try:
                await self.poll_once()
            except Exception:
                _log.exception('Error in MessageRelay.poll_once')
            await asyncio.sleep(interval)

    # ── Internal helpers ────────────────────────────────────────────────────

    def _find_bus_for(self, conversation_id: str):
        """Return the first bus in the registry that knows this conversation.

        Conversations are globally unique across buses (prefix-namespaced),
        so the first match is the correct one.
        """
        for bus in self._buses.values():
            try:
                if conversation_id in bus.conversations():
                    return bus
            except Exception:
                continue
        return None

    async def _send_message(self, connection: Any, cid: str, msg) -> None:
        payload = {
            'type': 'message',
            'id': msg.id,
            'conversation_id': cid,
            'sender': msg.sender,
            'content': msg.content,
            'timestamp': msg.timestamp,
        }
        try:
            await connection.send_json(payload)
        except Exception:
            _log.debug('Failed to send message to connection; dropping', exc_info=True)
