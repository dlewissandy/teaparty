"""Issue #398 — Fetch-and-subscribe atomicity for chat message delivery.

These tests encode the spec from the ticket: every message is delivered to
every client exactly once, across the join between the initial HTTP load and
the live WebSocket stream. No client-side dedup. Cursor owned by the client,
scoped per (client, conversation).

Covered dimensions:
  - Bus cursor semantics: empty, non-empty, past-end, equal-timestamp tiebreak
  - Subscribe handshake: catch-up replay + live delivery = exactly once
  - Reconnect: stale cursor delivers only the gap, nothing before
  - Multi-client: two subscribers at different cursors on the same conversation
  - Race window: messages written concurrently with subscribe are delivered once
  - escalation_cleared event: emitted when awaiting_input flips True → False

Each test is load-bearing: if the cursor-aware bus method or the per-
subscription relay dispatch is reverted, the test fails with an invariant-
naming diagnostic.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import unittest

from teaparty.bridge.message_relay import MessageRelay
from teaparty.messaging.conversations import SqliteMessageBus


def _make_bus(tc: unittest.TestCase) -> SqliteMessageBus:
    tmp = tempfile.mkdtemp(prefix='teaparty-398-')
    tc.addCleanup(shutil.rmtree, tmp, True)
    return SqliteMessageBus(os.path.join(tmp, 'messages.db'))


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) \
        if False else asyncio.new_event_loop().run_until_complete(coro)


def _send_many(bus: SqliteMessageBus, cid: str, senders_contents: list[tuple[str, str]]) -> list[str]:
    """Send a batch of messages and return their ids in send order."""
    ids = []
    for sender, content in senders_contents:
        ids.append(bus.send(cid, sender, content))
    return ids


class _FakeWS:
    """Captures messages that would be sent over a real aiohttp WebSocket.

    The subscription dispatcher only needs ``send_json`` (or an equivalent
    ``send_event``) — we record every call so tests can assert exact counts
    and ordering.
    """
    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False

    async def send_json(self, payload: dict) -> None:
        if self.closed:
            raise RuntimeError('send_json on closed FakeWS')
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True

    def messages_for(self, conv_id: str) -> list[dict]:
        return [p for p in self.sent if p.get('type') == 'message' and p.get('conversation_id') == conv_id]


# ── Layer 1: Bus cursor semantics ───────────────────────────────────────────

class TestBusCursor(unittest.TestCase):
    """SqliteMessageBus.receive_since_cursor must define a stable total order
    over (timestamp, id) and return a watermark cursor captured in the same
    read as the returned rows.
    """

    def test_empty_cursor_returns_all_and_watermark(self):
        bus = _make_bus(self)
        _send_many(bus, 'c:1', [('a', 'm0'), ('a', 'm1'), ('a', 'm2')])
        msgs, cursor = bus.receive_since_cursor('c:1', '')
        self.assertEqual(
            [m.content for m in msgs], ['m0', 'm1', 'm2'],
            'receive_since_cursor("") must return every message in send order',
        )
        self.assertNotEqual(cursor, '', 'watermark cursor must be non-empty when rows were returned')

    def test_cursor_at_tail_returns_nothing(self):
        bus = _make_bus(self)
        _send_many(bus, 'c:1', [('a', 'm0'), ('a', 'm1')])
        _, tail = bus.receive_since_cursor('c:1', '')
        msgs, cursor = bus.receive_since_cursor('c:1', tail)
        self.assertEqual(msgs, [], 'reading from the tail cursor must return zero rows')
        self.assertEqual(cursor, tail, 'empty read must not advance the cursor past the tail')

    def test_cursor_delivers_only_gap(self):
        bus = _make_bus(self)
        _send_many(bus, 'c:1', [('a', 'm0'), ('a', 'm1')])
        _, mid = bus.receive_since_cursor('c:1', '')
        _send_many(bus, 'c:1', [('a', 'm2'), ('a', 'm3')])
        msgs, cursor = bus.receive_since_cursor('c:1', mid)
        self.assertEqual(
            [m.content for m in msgs], ['m2', 'm3'],
            'cursor-based read must return exactly the rows added after the cursor',
        )
        self.assertNotEqual(cursor, mid, 'cursor must advance when new rows are read')

    def test_equal_timestamp_stable_tiebreak_by_id(self):
        bus = _make_bus(self)
        # Force several rows with identical timestamp by writing directly.
        # The bus returns stable order via (timestamp ASC, id ASC).
        import sqlite3
        import uuid
        ts = 1234567.5
        ids = sorted(uuid.uuid4().hex for _ in range(5))
        for mid in ids:
            bus._conn.execute(
                'INSERT INTO messages (id, conversation, sender, content, timestamp) '
                'VALUES (?, ?, ?, ?, ?)',
                (mid, 'c:1', 'a', mid, ts),
            )
        bus._conn.commit()

        msgs, _ = bus.receive_since_cursor('c:1', '')
        returned_ids = [m.id for m in msgs]
        self.assertEqual(
            returned_ids, ids,
            'equal-timestamp rows must be returned in id-ascending order (stable tiebreak)',
        )

        # Mid-batch cursor: after the 2nd row, the next read must return the last 3
        # in the same order and must not re-emit the first 2.
        mid_cursor = f'{ts:.9f}:{ids[1]}'
        rest, _ = bus.receive_since_cursor('c:1', mid_cursor)
        self.assertEqual(
            [m.id for m in rest], ids[2:],
            'equal-timestamp cursor tiebreak must resume strictly after the given id',
        )

    def test_cursor_is_opaque_watermark_of_last_row(self):
        bus = _make_bus(self)
        ids = _send_many(bus, 'c:1', [('a', 'm0'), ('a', 'm1'), ('a', 'm2')])
        msgs, cursor = bus.receive_since_cursor('c:1', '')
        # The cursor must reference the last row returned, so that the
        # immediate next read at that cursor yields nothing.
        again, _ = bus.receive_since_cursor('c:1', cursor)
        self.assertEqual(
            again, [],
            f'cursor returned with {len(msgs)} rows must be the strict watermark; '
            f'got {len(again)} extra rows on re-read',
        )
        self.assertEqual(msgs[-1].id, ids[-1])


# ── Layer 2: Subscription-dispatching MessageRelay ──────────────────────────

class TestSubscriptionRelay(unittest.IsolatedAsyncioTestCase):
    """MessageRelay, after #398, must hold per-(ws, conversation) cursors
    and never double-deliver across the join between subscribe catch-up and
    live polling.
    """

    def _make_relay(self, buses: dict) -> MessageRelay:
        # Legacy broadcast callback is retained for input_requested fan-out;
        # the dispatcher per-client path must not depend on it for messages.
        async def _noop_broadcast(event: dict) -> None:
            pass
        return MessageRelay(buses, _noop_broadcast)

    async def test_subscribe_catchup_plus_live_is_exactly_once(self):
        bus = _make_bus(self)
        buses = {'session': bus}
        relay = self._make_relay(buses)

        # Write a burst that straddles the subscribe boundary.
        _send_many(bus, 'om:alice', [('agent', f'pre-{i}') for i in range(3)])

        ws = _FakeWS()
        await relay.subscribe(ws, 'om:alice', since_cursor='')

        # Now write more messages; the relay's poll must pick them up.
        _send_many(bus, 'om:alice', [('agent', f'post-{i}') for i in range(3)])
        await relay.poll_once()

        contents = [p['content'] for p in ws.messages_for('om:alice')]
        self.assertEqual(
            contents, ['pre-0', 'pre-1', 'pre-2', 'post-0', 'post-1', 'post-2'],
            f'subscribe must deliver every message exactly once in order; got {contents}',
        )

        # Negative space: a second poll with no writes delivers nothing new.
        await relay.poll_once()
        self.assertEqual(
            [p['content'] for p in ws.messages_for('om:alice')], contents,
            'poll_once must not re-deliver messages the subscription already received',
        )

    async def test_race_window_message_delivered_exactly_once(self):
        """The exact bug from the ticket: a message whose timestamp is inside
        the window between the client's fetch and the relay's next poll.
        Under the old fetch-and-poll model, both the fetch and the relay
        would return this row. Under #398, the cursor-owning subscribe
        handshake must deliver it exactly once.
        """
        bus = _make_bus(self)
        relay = self._make_relay({'session': bus})

        # Write a message that will be captured by the "initial fetch".
        _send_many(bus, 'om:alice', [('agent', 'race-row')])

        # Client issues the equivalent of GET /api/conversations/om:alice:
        # (messages, cursor) captured atomically, just like the handler.
        msgs0, cursor0 = bus.receive_since_cursor('om:alice', '')
        self.assertEqual([m.content for m in msgs0], ['race-row'])

        # Client opens the WS and subscribes with the cursor it just got.
        ws = _FakeWS()
        await relay.subscribe(ws, 'om:alice', since_cursor=cursor0)

        # The relay polls — under the old model, this is where the duplicate
        # appeared. Under #398 the cursor excludes it.
        await relay.poll_once()

        dupes = [p for p in ws.messages_for('om:alice') if p['content'] == 'race-row']
        self.assertEqual(
            len(dupes), 0,
            f'race-row was delivered via subscribe catch-up but reappeared via '
            f'the live stream {len(dupes)} time(s); cursor did not gate it out',
        )

    async def test_reconnect_with_stale_cursor_delivers_only_gap(self):
        bus = _make_bus(self)
        relay = self._make_relay({'session': bus})

        _send_many(bus, 'om:alice', [('agent', f'm{i}') for i in range(3)])

        ws1 = _FakeWS()
        await relay.subscribe(ws1, 'om:alice', since_cursor='')
        await relay.unsubscribe(ws1, 'om:alice')

        # Capture the cursor the client would have saved: the watermark of
        # the messages it already displayed.
        seen_contents = [p['content'] for p in ws1.messages_for('om:alice')]
        self.assertEqual(seen_contents, ['m0', 'm1', 'm2'])
        _, client_cursor = bus.receive_since_cursor('om:alice', '')

        # More messages arrive while the client is disconnected.
        _send_many(bus, 'om:alice', [('agent', f'm{i}') for i in range(3, 6)])

        # Client reconnects with its last known cursor.
        ws2 = _FakeWS()
        await relay.subscribe(ws2, 'om:alice', since_cursor=client_cursor)

        gap = [p['content'] for p in ws2.messages_for('om:alice')]
        self.assertEqual(
            gap, ['m3', 'm4', 'm5'],
            f'reconnect must deliver exactly the gap, got {gap}',
        )

        # Negative space: none of the pre-disconnect messages were replayed.
        for old in ('m0', 'm1', 'm2'):
            self.assertNotIn(
                old, gap,
                f'reconnect delivered message {old!r} that the client had already seen',
            )

    async def test_two_clients_at_different_cursors_are_independent(self):
        bus = _make_bus(self)
        relay = self._make_relay({'session': bus})

        # Three messages before either client subscribes.
        _send_many(bus, 'om:alice', [('agent', f'm{i}') for i in range(3)])

        ws_full = _FakeWS()
        await relay.subscribe(ws_full, 'om:alice', since_cursor='')

        # Now advance to a mid-point cursor and subscribe a second client there.
        _, mid_cursor = bus.receive_since_cursor('om:alice', '')

        _send_many(bus, 'om:alice', [('agent', 'm3')])

        ws_tail = _FakeWS()
        await relay.subscribe(ws_tail, 'om:alice', since_cursor=mid_cursor)

        # Both clients should see the new m3 via the next poll. ws_full should
        # have received all 4; ws_tail should have received only m3.
        await relay.poll_once()

        full_contents = [p['content'] for p in ws_full.messages_for('om:alice')]
        tail_contents = [p['content'] for p in ws_tail.messages_for('om:alice')]

        self.assertEqual(
            full_contents, ['m0', 'm1', 'm2', 'm3'],
            f'full subscriber expected all 4 messages, got {full_contents}',
        )
        self.assertEqual(
            tail_contents, ['m3'],
            f'mid-cursor subscriber expected exactly [m3], got {tail_contents}',
        )

    async def test_unsubscribe_stops_further_delivery(self):
        bus = _make_bus(self)
        relay = self._make_relay({'session': bus})

        ws = _FakeWS()
        await relay.subscribe(ws, 'om:alice', since_cursor='')
        _send_many(bus, 'om:alice', [('agent', 'm0')])
        await relay.poll_once()

        await relay.unsubscribe(ws, 'om:alice')
        _send_many(bus, 'om:alice', [('agent', 'm1')])
        await relay.poll_once()

        contents = [p['content'] for p in ws.messages_for('om:alice')]
        self.assertEqual(
            contents, ['m0'],
            f'unsubscribed client received {contents} after unsubscribe; expected only [m0]',
        )

    async def test_no_broadcast_leakage_before_subscribe(self):
        """A WS connection that has never sent a subscribe frame must not
        receive any 'message' events, even if the relay polls. This is the
        server-side corollary to the client handshake rule.
        """
        bus = _make_bus(self)
        relay = self._make_relay({'session': bus})

        ws = _FakeWS()
        relay.register_connection(ws)  # connect, but do not subscribe
        _send_many(bus, 'om:alice', [('agent', 'm0'), ('agent', 'm1')])
        await relay.poll_once()

        msg_events = [p for p in ws.sent if p.get('type') == 'message']
        self.assertEqual(
            msg_events, [],
            f'unsubscribed connection received {len(msg_events)} message events; '
            f'relay must not push to connections without an active subscription',
        )


# ── Layer 3: escalation_cleared event ───────────────────────────────────────

class TestEscalationClearedEvent(unittest.IsolatedAsyncioTestCase):
    """Criterion 10: the relay must emit a dedicated escalation_cleared event
    when a conversation's awaiting_input flag transitions True → False. The
    index.html page must not need to inspect 'message' event contents to
    infer escalation state.
    """

    async def test_escalation_cleared_emitted_on_transition(self):
        from teaparty.messaging.conversations import ConversationType
        bus = _make_bus(self)
        # Create the conversation so set_awaiting_input has a row to update.
        bus.create_conversation(ConversationType.OFFICE_MANAGER, 'alice')
        cid = 'om:alice'

        events: list[dict] = []

        async def capture(event: dict) -> None:
            events.append(event)

        relay = MessageRelay({'session': bus}, capture)

        # Transition 1: off → on. Must emit input_requested.
        bus.set_awaiting_input(cid, True)
        await relay.poll_once()
        types = [e['type'] for e in events]
        self.assertIn(
            'input_requested', types,
            f'expected input_requested on awaiting_input True transition; got {types}',
        )

        # Transition 2: on → off. Must emit escalation_cleared exactly once.
        events.clear()
        bus.set_awaiting_input(cid, False)
        await relay.poll_once()

        cleared = [e for e in events if e.get('type') == 'escalation_cleared']
        self.assertEqual(
            len(cleared), 1,
            f'expected exactly 1 escalation_cleared event on True→False transition; '
            f'got {len(cleared)} (all events: {events})',
        )
        self.assertEqual(cleared[0].get('conversation_id'), cid)

        # Negative space: a subsequent poll with no further transitions must
        # NOT emit another escalation_cleared.
        events.clear()
        await relay.poll_once()
        self.assertEqual(
            [e for e in events if e.get('type') == 'escalation_cleared'], [],
            'escalation_cleared must fire once per transition, not on every poll',
        )


if __name__ == '__main__':
    unittest.main()
