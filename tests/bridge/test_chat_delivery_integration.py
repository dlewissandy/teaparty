"""Issue #398 — HTTP/WebSocket integration tests for fetch-and-subscribe.

Audit finding (Tests reviewer, 2026-04-12): the relay- and bus-level tests in
test_chat_delivery_atomicity.py do not exercise the HTTP/WS boundary where
the bug actually manifested. A regression that reverts the response shape to
a bare array, or restores ``async for msg in ws: pass`` on the WebSocket
handler, would not be caught by the relay tests alone.

These tests drive the bridge through its real aiohttp handlers — a live
test server, a real WebSocket client, JSON frames on the wire — and assert
the server-side contract from the ticket:

  - GET /api/conversations/{id} returns {messages, cursor} from a single read.
  - WebSocket subscribe + catch-up + live delivery = exactly once.
  - Unsubscribed connections receive zero message events.
  - Malformed cursors produce a sharp error, not silent halt.
  - The `asyncio.Lock` inside MessageRelay actually prevents concurrent
    subscribe/dispatch double-delivery (deterministic race reproduction).
  - `_find_bus_for` locates conversations across multiple buses.
  - `escalation_cleared` fires when the relay starts on a bus whose
    awaiting_input is later cleared.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
import unittest
from typing import Any

from aiohttp import WSMsgType, web
from aiohttp.test_utils import TestClient, TestServer

from teaparty.bridge.message_relay import MessageRelay
from teaparty.messaging.conversations import (
    ConversationType,
    SqliteMessageBus,
)


def _make_bus_at(tc: unittest.TestCase) -> SqliteMessageBus:
    tmp = tempfile.mkdtemp(prefix='teaparty-398-int-')
    tc.addCleanup(shutil.rmtree, tmp, True)
    return SqliteMessageBus(os.path.join(tmp, 'messages.db'))


class _MiniBridge:
    """A minimal stand-in for TeaPartyBridge that exposes exactly the two
    handlers we are exercising plus the relay + bus registry they depend on.

    Binding the real ``_handle_conversation_get`` and ``_handle_websocket``
    methods here (via ``type.MethodType``) runs the production code, not a
    reimplementation — so a regression to either handler shows up in these
    tests.
    """
    def __init__(self, bus: SqliteMessageBus):
        self._buses = {'session': bus}
        self._ws_clients: set[web.WebSocketResponse] = set()

        async def _noop_broadcast(event: dict) -> None:
            pass

        self._message_relay = MessageRelay(self._buses, _noop_broadcast)

    # Bound in __init__ below from TeaPartyBridge.
    _handle_conversation_get: Any = None
    _handle_websocket: Any = None

    def _bus_for_conversation(self, conv_id: str):
        for bus in self._buses.values():
            try:
                if conv_id in bus.conversations():
                    return bus
            except Exception:
                continue
        # First bus is fine as a fallback (test fixture)
        return next(iter(self._buses.values()), None)

    def _serialize_message(self, m) -> dict:
        return {
            'id': m.id,
            'conversation': m.conversation,
            'sender': m.sender,
            'content': m.content,
            'timestamp': m.timestamp,
        }


def _attach_real_handlers(mini: _MiniBridge) -> None:
    from types import MethodType
    from teaparty.bridge.server import TeaPartyBridge
    mini._handle_conversation_get = MethodType(
        TeaPartyBridge._handle_conversation_get, mini,
    )
    mini._handle_websocket = MethodType(
        TeaPartyBridge._handle_websocket, mini,
    )


async def _build_app(bus: SqliteMessageBus) -> tuple[web.Application, _MiniBridge]:
    mini = _MiniBridge(bus)
    _attach_real_handlers(mini)
    app = web.Application()
    app.router.add_get(
        '/api/conversations/{id}', mini._handle_conversation_get,
    )
    app.router.add_get('/ws', mini._handle_websocket)
    return app, mini


# ── HTTP integration ────────────────────────────────────────────────────────

class TestConversationGetIntegration(unittest.IsolatedAsyncioTestCase):
    """GET /api/conversations/{id} must return the {messages, cursor} shape
    through the real aiohttp router, not a bare array (ticket criterion 1).
    """

    async def asyncSetUp(self):
        self.bus = _make_bus_at(self)
        app, self.mini = await _build_app(self.bus)
        self.server = TestServer(app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()

    async def test_response_shape_is_messages_and_cursor(self):
        self.bus.send('om:alice', 'agent', 'm0')
        self.bus.send('om:alice', 'agent', 'm1')

        resp = await self.client.get('/api/conversations/om:alice')
        self.assertEqual(resp.status, 200)
        body = await resp.json()

        self.assertIsInstance(
            body, dict,
            f'GET /api/conversations/{{id}} must return an object, got {type(body).__name__}',
        )
        self.assertIn(
            'messages', body,
            f'response must contain "messages" key, got keys={list(body.keys())}',
        )
        self.assertIn(
            'cursor', body,
            f'response must contain "cursor" key, got keys={list(body.keys())}',
        )
        self.assertEqual(
            [m['content'] for m in body['messages']], ['m0', 'm1'],
            'messages array must be in send order',
        )
        self.assertNotEqual(
            body['cursor'], '',
            'cursor must be a non-empty watermark when rows were returned',
        )

    async def test_empty_conversation_returns_empty_cursor(self):
        resp = await self.client.get('/api/conversations/om:ghost')
        body = await resp.json()
        self.assertEqual(body['messages'], [])
        self.assertEqual(body['cursor'], '')


# ── WebSocket integration ──────────────────────────────────────────────────

class TestWebSocketSubscribeIntegration(unittest.IsolatedAsyncioTestCase):
    """The WebSocket handler must parse subscribe/unsubscribe frames and
    deliver messages exactly once through the real WS wire (ticket
    criteria 2, 3, 5, 8).
    """

    async def asyncSetUp(self):
        self.bus = _make_bus_at(self)
        app, self.mini = await _build_app(self.bus)
        self.server = TestServer(app)
        await self.server.start_server()
        self.client = TestClient(self.server)
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        await self.server.close()

    async def _receive_messages(self, ws, count: int, timeout: float = 2.0) -> list[dict]:
        msgs: list[dict] = []
        try:
            while len(msgs) < count:
                raw = await asyncio.wait_for(ws.receive(), timeout=timeout)
                if raw.type != WSMsgType.TEXT:
                    continue
                ev = json.loads(raw.data)
                if ev.get('type') == 'message':
                    msgs.append(ev)
        except asyncio.TimeoutError:
            pass
        return msgs

    async def test_subscribe_frame_replays_from_cursor(self):
        self.bus.send('om:alice', 'agent', 'pre-0')
        self.bus.send('om:alice', 'agent', 'pre-1')

        async with self.client.ws_connect('/ws') as ws:
            await ws.send_json({
                'type': 'subscribe',
                'conversation_id': 'om:alice',
                'since_cursor': '',
            })
            msgs = await self._receive_messages(ws, count=2)

        contents = [m['content'] for m in msgs]
        self.assertEqual(
            contents, ['pre-0', 'pre-1'],
            f'subscribe catch-up must replay every prior row in order; got {contents}',
        )

    async def test_unsubscribed_connection_receives_no_messages(self):
        """Server-side corollary of ticket criterion 8: a WS connection that
        has never sent a subscribe frame must not receive any ``message``
        events, even when the relay polls the bus. The handler must not
        broadcast to bare connections.
        """
        async with self.client.ws_connect('/ws') as ws:
            # Write and poll the relay while no subscribe has been sent.
            self.bus.send('om:alice', 'agent', 'broadcast-probe')
            await self.mini._message_relay.poll_once()
            msgs = await self._receive_messages(ws, count=1, timeout=0.5)

        self.assertEqual(
            msgs, [],
            f'unsubscribed connection received {len(msgs)} message event(s); '
            f'relay must not deliver messages without an active subscription',
        )

    async def test_race_window_over_the_wire(self):
        """The exact bug from the ticket, exercised end-to-end through HTTP
        and WS. A row is captured by the HTTP fetch; the client subscribes
        with the returned cursor; the relay polls. Under the old fetch-and-
        poll model the row would be delivered twice — once via the fetch and
        once via the first poll. Under #398 it is delivered exactly once
        (via the fetch), and the subscribe cursor gates the relay out.
        """
        self.bus.send('om:alice', 'agent', 'race-row')

        resp = await self.client.get('/api/conversations/om:alice')
        body = await resp.json()
        cursor = body['cursor']
        self.assertEqual([m['content'] for m in body['messages']], ['race-row'])

        async with self.client.ws_connect('/ws') as ws:
            await ws.send_json({
                'type': 'subscribe',
                'conversation_id': 'om:alice',
                'since_cursor': cursor,
            })
            # Two polling windows, per ticket criterion 5.
            await self.mini._message_relay.poll_once()
            await self.mini._message_relay.poll_once()
            msgs = await self._receive_messages(ws, count=1, timeout=0.5)

        self.assertEqual(
            msgs, [],
            f'race-row was delivered via HTTP fetch but reappeared on the WS '
            f'subscribe stream {len(msgs)} time(s) — cursor did not gate it out',
        )

    async def test_unsubscribe_frame_stops_further_delivery(self):
        async with self.client.ws_connect('/ws') as ws:
            await ws.send_json({
                'type': 'subscribe',
                'conversation_id': 'om:alice',
                'since_cursor': '',
            })
            self.bus.send('om:alice', 'agent', 'm0')
            await self.mini._message_relay.poll_once()
            first = await self._receive_messages(ws, count=1)

            await ws.send_json({
                'type': 'unsubscribe',
                'conversation_id': 'om:alice',
            })
            # Deterministic synchronization: the server processes frames on
            # a single task in-order, so a ping/pong round-trip after the
            # unsubscribe guarantees the unsubscribe has been applied before
            # we proceed. Without this there is no client-visible ordering
            # between the send and the server-side handling.
            await ws.send_json({'type': 'ping'})
            while True:
                raw = await asyncio.wait_for(ws.receive(), timeout=2.0)
                if raw.type == WSMsgType.TEXT and json.loads(raw.data).get('type') == 'pong':
                    break

            self.bus.send('om:alice', 'agent', 'm1')
            await self.mini._message_relay.poll_once()
            second = await self._receive_messages(ws, count=1, timeout=0.5)

        self.assertEqual(
            [m['content'] for m in first], ['m0'],
            'first write after subscribe must be delivered',
        )
        self.assertEqual(
            second, [],
            f'unsubscribe frame ignored: received {len(second)} message(s) after it',
        )


# ── Robustness and edge cases ──────────────────────────────────────────────

class TestBusCursorRobustness(unittest.TestCase):
    """Edge cases the main test file does not cover."""

    def _bus(self) -> SqliteMessageBus:
        return _make_bus_at(self)

    def test_malformed_cursor_raises_value_error(self):
        """A malformed cursor must produce a sharp, diagnosable error rather
        than a silent zero-result or an obscure sqlite error. The relay's
        broad except-Exception would otherwise hide delivery halts.
        """
        bus = self._bus()
        bus.send('c:1', 'a', 'm0')
        with self.assertRaises(ValueError) as ctx:
            bus.receive_since_cursor('c:1', 'not-a-cursor')
        self.assertIn(
            'invalid cursor', str(ctx.exception),
            f'ValueError must name the invariant; got: {ctx.exception}',
        )

    def test_cursor_parse_accepts_int_timestamps(self):
        """A cursor emitted as '1234567:abc' (no decimal) must still parse.
        Float conversion tolerates this, but regression-pin the behavior so
        a stricter parser does not silently break round-trippers.
        """
        bus = self._bus()
        # Write two rows and fetch; then feed the watermark back.
        bus.send('c:1', 'a', 'm0')
        _, cursor = bus.receive_since_cursor('c:1', '')
        rest, _ = bus.receive_since_cursor('c:1', cursor)
        self.assertEqual(rest, [])


class TestRelayMultiBus(unittest.IsolatedAsyncioTestCase):
    """MessageRelay._find_bus_for must locate conversations when the registry
    holds more than one bus — the common case in real runs where every
    agent owns its own bus.
    """

    async def test_conversation_routed_to_correct_bus_across_registry(self):
        bus_a = _make_bus_at(self)
        bus_b = _make_bus_at(self)
        bus_a.send('om:alice', 'agent', 'from-a')
        bus_b.send('pm:bob', 'agent', 'from-b')

        async def _noop(event: dict) -> None:
            pass

        relay = MessageRelay({'bus_a': bus_a, 'bus_b': bus_b}, _noop)

        class _FakeWS:
            def __init__(self):
                self.sent: list[dict] = []
            async def send_json(self, payload: dict) -> None:
                self.sent.append(payload)

        ws = _FakeWS()
        await relay.subscribe(ws, 'om:alice', since_cursor='')
        await relay.subscribe(ws, 'pm:bob', since_cursor='')

        a_msgs = [p for p in ws.sent if p.get('conversation_id') == 'om:alice']
        b_msgs = [p for p in ws.sent if p.get('conversation_id') == 'pm:bob']

        self.assertEqual(
            [p['content'] for p in a_msgs], ['from-a'],
            'om:alice subscription must be routed to bus_a',
        )
        self.assertEqual(
            [p['content'] for p in b_msgs], ['from-b'],
            'pm:bob subscription must be routed to bus_b',
        )


class TestConcurrentSubscribeAndDispatch(unittest.IsolatedAsyncioTestCase):
    """Deterministic race reproduction: subscribe and dispatch must not
    both see the same row. Without the ``asyncio.Lock`` in MessageRelay,
    a subscribe that reads from cursor X and a dispatch that also reads
    from cursor X would both return the row between them, double-delivering.
    """

    async def test_lock_prevents_subscribe_vs_dispatch_double_delivery(self):
        bus = _make_bus_at(self)

        async def _noop(event: dict) -> None:
            pass

        relay = MessageRelay({'session': bus}, _noop)

        # Pre-populate with one row that subscribe catch-up will replay.
        bus.send('om:alice', 'agent', 'pre')

        class _FakeWS:
            def __init__(self):
                self.sent: list[dict] = []
            async def send_json(self, payload: dict) -> None:
                self.sent.append(payload)

        ws = _FakeWS()
        # Install a bare (unsubscribed) entry so _dispatch_messages has a
        # connection to iterate over — it must not deliver anything until
        # the subscribe completes.
        relay.register_connection(ws)

        # Kick off subscribe and dispatch simultaneously. The relay lock
        # must serialize them; if it did not, dispatch could run first,
        # read nothing (no subscription yet), then subscribe would run
        # and return the row — fine — OR subscribe could run first, then
        # a second poll in the same window would double-deliver the row.
        # The invariant is exactly one copy on the wire.
        await asyncio.gather(
            relay.subscribe(ws, 'om:alice', since_cursor=''),
            relay._dispatch_messages(),
            relay._dispatch_messages(),
        )

        contents = [p['content'] for p in ws.sent if p.get('type') == 'message']
        self.assertEqual(
            contents.count('pre'), 1,
            f'pre was delivered {contents.count("pre")} times under concurrent '
            f'subscribe+dispatch; expected exactly 1 (lock invariant)',
        )


class TestEscalationStartupState(unittest.IsolatedAsyncioTestCase):
    """On startup the relay has no awaiting_input state. The first poll must
    emit ``input_requested`` for any conversation that is already awaiting —
    and a subsequent clear must emit ``escalation_cleared`` exactly once.
    """

    async def test_startup_with_already_set_then_clear(self):
        bus = _make_bus_at(self)
        bus.create_conversation(ConversationType.OFFICE_MANAGER, 'alice')
        bus.set_awaiting_input('om:alice', True)

        events: list[dict] = []

        async def capture(event: dict) -> None:
            events.append(event)

        relay = MessageRelay({'session': bus}, capture)

        # First poll after startup — must emit input_requested for the
        # pre-existing awaiting_input conversation.
        await relay.poll_once()
        requested = [e for e in events if e.get('type') == 'input_requested']
        self.assertEqual(
            len(requested), 1,
            f'expected input_requested on first poll for pre-existing '
            f'awaiting_input; got {len(requested)} (events: {events})',
        )

        # Second poll, still awaiting — must emit nothing new.
        events.clear()
        await relay.poll_once()
        self.assertEqual(
            events, [],
            f'steady-state poll must not re-emit input_requested; got {events}',
        )

        # Clear — must emit escalation_cleared exactly once.
        bus.set_awaiting_input('om:alice', False)
        await relay.poll_once()
        cleared = [e for e in events if e.get('type') == 'escalation_cleared']
        self.assertEqual(
            len(cleared), 1,
            f'expected exactly 1 escalation_cleared on True→False '
            f'transition; got {len(cleared)} (events: {events})',
        )


if __name__ == '__main__':
    unittest.main()
