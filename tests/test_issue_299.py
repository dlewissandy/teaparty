"""Tests for issue #299: message_relay.py — per-session message bus polling, message event push.

Acceptance criteria:
1. Maintains conversation_id → last_polled_timestamp across polls
2. Calls bus.receive(id, since_timestamp=last_ts) for each tracked conversation
3. Pushes `message` events for new messages
4. Detects input_requested via conversations_awaiting_input() flag
5. Handles office manager's separate om-messages.db
"""
import asyncio
import os
import shutil
import tempfile
import unittest


# ── Stubs ─────────────────────────────────────────────────────────────────────

class _FakeMsg:
    def __init__(self, sender, content, timestamp=1.0, msg_id='msg-test'):
        self.sender = sender
        self.content = content
        self.timestamp = timestamp
        self.id = msg_id


class _FakeConv:
    def __init__(self, cid):
        self.id = cid


class _SpyBus:
    """Bus stub that records receive() calls for inspection."""

    def __init__(self, conv_ids=None, messages=None, awaiting=None):
        self._conv_ids = conv_ids or []
        self._messages = messages or {}   # {cid: [_FakeMsg]}
        self._awaiting = awaiting or []
        self.receive_calls = []           # [(cid, since_timestamp), ...]

    def conversations(self):
        return list(self._conv_ids)

    def receive(self, cid, since_timestamp=0.0):
        self.receive_calls.append((cid, since_timestamp))
        return [m for m in self._messages.get(cid, [])
                if m.timestamp > since_timestamp]

    def conversations_awaiting_input(self):
        return list(self._awaiting)


# ── 1. last_polled_timestamp tracking ─────────────────────────────────────────

class TestSinceTimestampTracking(unittest.TestCase):
    """Relay must track last-seen timestamp per conversation_id."""

    def test_last_ts_advances_after_messages_received(self):
        """After a poll returns a message, the next poll uses its timestamp."""
        from bridge.message_relay import MessageRelay

        events = []

        async def broadcast(event):
            events.append(event)

        cid = 'task:proj:job1:t1'
        bus = _SpyBus(
            conv_ids=[cid],
            messages={cid: [_FakeMsg('agent', 'first', 1.0)]},
        )
        relay = MessageRelay({'s1': bus}, broadcast)

        asyncio.run(relay.poll_once())
        first_call_ts = bus.receive_calls[-1][1]
        self.assertEqual(first_call_ts, 0.0,
                         'First poll must start at since_timestamp=0.0')

        asyncio.run(relay.poll_once())
        second_call_ts = bus.receive_calls[-1][1]
        self.assertEqual(second_call_ts, 1.0,
                         'Second poll must use the timestamp of the last seen message')

    def test_last_ts_unchanged_when_no_new_messages(self):
        """If no messages arrive, since_timestamp stays at 0.0."""
        from bridge.message_relay import MessageRelay

        events = []

        async def broadcast(event):
            events.append(event)

        cid = 'task:proj:job1:t2'
        bus = _SpyBus(conv_ids=[cid], messages={})
        relay = MessageRelay({'s1': bus}, broadcast)

        asyncio.run(relay.poll_once())
        asyncio.run(relay.poll_once())
        for _, ts in bus.receive_calls:
            self.assertEqual(ts, 0.0,
                             'Without messages, since_timestamp stays at 0.0')

    def test_timestamps_tracked_independently_per_conversation(self):
        """Each conversation_id has its own last-seen timestamp."""
        from bridge.message_relay import MessageRelay

        events = []

        async def broadcast(event):
            events.append(event)

        cid_a = 'task:proj:job1:t1'
        cid_b = 'task:proj:job1:t2'
        bus = _SpyBus(
            conv_ids=[cid_a, cid_b],
            messages={
                cid_a: [_FakeMsg('agent', 'msg-a', 5.0)],
                cid_b: [_FakeMsg('agent', 'msg-b', 9.0)],
            },
        )
        relay = MessageRelay({'s1': bus}, broadcast)

        asyncio.run(relay.poll_once())
        asyncio.run(relay.poll_once())

        # Second poll must use each conversation's own timestamp
        second_calls = {cid: ts for cid, ts in bus.receive_calls[-2:]}
        self.assertEqual(second_calls[cid_a], 5.0)
        self.assertEqual(second_calls[cid_b], 9.0)


# ── 2. since_timestamp keyword argument ───────────────────────────────────────

class TestReceiveUsesKeywordArgument(unittest.TestCase):
    """bus.receive() must be called with since_timestamp as a keyword arg (issue #283)."""

    def test_receive_called_with_since_timestamp_keyword(self):
        """receive() must be invoked as receive(id, since_timestamp=ts), not positionally."""
        from bridge.message_relay import MessageRelay

        receive_kwargs = []

        class _CaptureBus:
            def conversations(self):
                return ['conv-1']

            def receive(self, cid, **kwargs):
                receive_kwargs.append(kwargs)
                return []

            def conversations_awaiting_input(self):
                return []

        relay = MessageRelay({'s1': _CaptureBus()}, lambda e: asyncio.sleep(0))
        asyncio.run(relay.poll_once())

        self.assertEqual(len(receive_kwargs), 1)
        self.assertIn('since_timestamp', receive_kwargs[0],
                      'receive() must use since_timestamp as a keyword argument')


# ── 3. message events ─────────────────────────────────────────────────────────

class TestMessageEventEmission(unittest.TestCase):
    """New messages must be pushed as `message` WebSocket events."""

    def test_message_event_emitted_for_each_new_message(self):
        from bridge.message_relay import MessageRelay

        events = []

        async def broadcast(event):
            events.append(event)

        cid = 'task:proj:job1:t1'
        bus = _SpyBus(
            conv_ids=[cid],
            messages={cid: [
                _FakeMsg('agent', 'hello', 1.0),
                _FakeMsg('human', 'reply', 2.0),
            ]},
        )
        relay = MessageRelay({'s1': bus}, broadcast)
        asyncio.run(relay.poll_once())

        msg_events = [e for e in events if e['type'] == 'message']
        self.assertEqual(len(msg_events), 2)

    def test_message_event_fields_match_spec(self):
        """Each `message` event must have conversation_id, sender, content, timestamp."""
        from bridge.message_relay import MessageRelay

        events = []

        async def broadcast(event):
            events.append(event)

        cid = 'task:proj:job1:t1'
        bus = _SpyBus(
            conv_ids=[cid],
            messages={cid: [_FakeMsg('orchestrator', 'What next?', 3.0)]},
        )
        relay = MessageRelay({'s1': bus}, broadcast)
        asyncio.run(relay.poll_once())

        msg_events = [e for e in events if e['type'] == 'message']
        self.assertEqual(len(msg_events), 1)
        ev = msg_events[0]
        self.assertEqual(ev['conversation_id'], cid)
        self.assertEqual(ev['sender'], 'orchestrator')
        self.assertEqual(ev['content'], 'What next?')
        self.assertEqual(ev['timestamp'], 3.0)

    def test_already_seen_messages_not_re_emitted(self):
        """Messages with timestamp ≤ last-seen must not be emitted again."""
        from bridge.message_relay import MessageRelay

        events = []

        async def broadcast(event):
            events.append(event)

        cid = 'task:proj:job1:t1'
        bus = _SpyBus(
            conv_ids=[cid],
            messages={cid: [_FakeMsg('agent', 'first', 1.0)]},
        )
        relay = MessageRelay({'s1': bus}, broadcast)

        asyncio.run(relay.poll_once())
        asyncio.run(relay.poll_once())  # second poll: timestamp filter excludes ts=1.0

        msg_events = [e for e in events if e['type'] == 'message']
        self.assertEqual(len(msg_events), 1,
                         'Already-seen messages must not be emitted a second time')


# ── 4. input_requested detection ──────────────────────────────────────────────

class TestInputRequestedDetection(unittest.TestCase):
    """Relay must emit input_requested when conversations_awaiting_input() fires."""

    def test_input_requested_event_emitted_when_awaiting(self):
        from bridge.message_relay import MessageRelay

        events = []

        async def broadcast(event):
            events.append(event)

        cid = 'task:proj:job1:t1'
        bus = _SpyBus(
            conv_ids=[cid],
            messages={cid: [_FakeMsg('orchestrator', 'Ready?', 1.0)]},
            awaiting=[_FakeConv(cid)],
        )
        relay = MessageRelay({'s1': bus}, broadcast)
        asyncio.run(relay.poll_once())

        ir_events = [e for e in events if e['type'] == 'input_requested']
        self.assertEqual(len(ir_events), 1)

    def test_input_requested_not_re_emitted_on_subsequent_polls(self):
        """input_requested must be emitted once per waiting transition, not every poll."""
        from bridge.message_relay import MessageRelay

        events = []

        async def broadcast(event):
            events.append(event)

        cid = 'task:proj:job1:t1'
        bus = _SpyBus(
            conv_ids=[cid],
            messages={cid: [_FakeMsg('orchestrator', 'Ready?', 1.0)]},
            awaiting=[_FakeConv(cid)],
        )
        relay = MessageRelay({'s1': bus}, broadcast)
        asyncio.run(relay.poll_once())
        asyncio.run(relay.poll_once())
        asyncio.run(relay.poll_once())

        ir_events = [e for e in events if e['type'] == 'input_requested']
        self.assertEqual(len(ir_events), 1,
                         'input_requested must not be re-emitted while still waiting')

    def test_input_requested_uses_structural_flag_not_heuristic(self):
        """Detection must use conversations_awaiting_input(), not message content inspection."""
        from bridge.message_relay import MessageRelay
        import inspect

        source = inspect.getsource(MessageRelay._poll_bus)
        self.assertIn('conversations_awaiting_input',
                      source,
                      'Must use conversations_awaiting_input() for detection')


# ── 5. Office manager bus handling ────────────────────────────────────────────

class TestOmBusPolling(unittest.TestCase):
    """Relay must poll the OM bus when it is present in the bus registry."""

    def test_om_bus_conversations_are_polled(self):
        """When bus_registry contains 'om' key, relay polls that bus too."""
        from bridge.message_relay import MessageRelay

        events = []

        async def broadcast(event):
            events.append(event)

        om_cid = 'om:alice'
        om_bus = _SpyBus(
            conv_ids=[om_cid],
            messages={om_cid: [_FakeMsg('human', 'escalation', 2.0)]},
        )

        relay = MessageRelay({'om': om_bus}, broadcast)
        asyncio.run(relay.poll_once())

        self.assertTrue(om_bus.receive_calls,
                        'relay must poll the OM bus when it is in the registry')

    def test_om_message_emitted_as_message_event(self):
        """Messages from OM conversations must be pushed as `message` events."""
        from bridge.message_relay import MessageRelay

        events = []

        async def broadcast(event):
            events.append(event)

        om_cid = 'om:alice'
        om_bus = _SpyBus(
            conv_ids=[om_cid],
            messages={om_cid: [_FakeMsg('human', 'escalation', 2.0)]},
        )

        relay = MessageRelay({'om': om_bus}, broadcast)
        asyncio.run(relay.poll_once())

        msg_events = [e for e in events if e['type'] == 'message']
        self.assertEqual(len(msg_events), 1)
        self.assertEqual(msg_events[0]['conversation_id'], om_cid)

    def test_om_input_requested_uses_om_session_id(self):
        """input_requested events from OM conversations must have session_id='om'."""
        from bridge.message_relay import MessageRelay

        events = []

        async def broadcast(event):
            events.append(event)

        om_cid = 'om:alice'
        om_bus = _SpyBus(
            conv_ids=[om_cid],
            messages={om_cid: [_FakeMsg('orchestrator', 'Approve?', 1.0)]},
            awaiting=[_FakeConv(om_cid)],
        )

        relay = MessageRelay({'om': om_bus}, broadcast)
        asyncio.run(relay.poll_once())

        ir_events = [e for e in events if e['type'] == 'input_requested']
        self.assertEqual(len(ir_events), 1)
        self.assertEqual(ir_events[0]['session_id'], 'om',
                         'OM input_requested events must carry session_id="om"')

    def test_om_and_session_buses_polled_independently(self):
        """Both session buses and the OM bus must be polled in the same poll cycle."""
        from bridge.message_relay import MessageRelay

        events = []

        async def broadcast(event):
            events.append(event)

        sess_cid = 'task:proj:job1:t1'
        om_cid = 'om:bob'
        sess_bus = _SpyBus(
            conv_ids=[sess_cid],
            messages={sess_cid: [_FakeMsg('agent', 'work', 1.0)]},
        )
        om_bus = _SpyBus(
            conv_ids=[om_cid],
            messages={om_cid: [_FakeMsg('human', 'escalate', 2.0)]},
        )

        relay = MessageRelay({'session-20260101-120000': sess_bus, 'om': om_bus}, broadcast)
        asyncio.run(relay.poll_once())

        msg_events = [e for e in events if e['type'] == 'message']
        conv_ids = {e['conversation_id'] for e in msg_events}
        self.assertIn(sess_cid, conv_ids, 'Session bus messages must be emitted')
        self.assertIn(om_cid, conv_ids, 'OM bus messages must be emitted')


class TestServerOmBusWiring(unittest.TestCase):
    """Server must wire the OM bus into the shared relay bus registry (issue #290 + #299)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_om_bus_in_buses_after_startup(self):
        """After _on_startup, self._buses must contain 'om' key pointing to the OM bus."""
        from bridge.server import TeaPartyBridge

        static_dir = os.path.join(self.tmpdir, 'static')
        os.makedirs(static_dir)
        bridge = TeaPartyBridge(
            teaparty_home=self.tmpdir,
            static_dir=static_dir,
        )

        # Simulate startup with a fake app dict; cancel spawned tasks immediately
        class _FakeApp(dict):
            pass

        app = _FakeApp()

        async def run_startup():
            await bridge._on_startup(app)
            # Cancel background tasks
            for key in ('_poller_task', '_relay_task'):
                task = app.get(key)
                if task:
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass

        asyncio.run(run_startup())

        self.assertIn('om', bridge._buses,
                      "After _on_startup, bridge._buses must contain 'om' key for the OM bus")

    def test_om_bus_in_buses_is_the_same_as_om_bus_attribute(self):
        """bridge._buses['om'] must be the same object as bridge._om_bus."""
        from bridge.server import TeaPartyBridge

        static_dir = os.path.join(self.tmpdir, 'static')
        os.makedirs(static_dir)
        bridge = TeaPartyBridge(
            teaparty_home=self.tmpdir,
            static_dir=static_dir,
        )

        class _FakeApp(dict):
            pass

        app = _FakeApp()

        async def run_startup():
            await bridge._on_startup(app)
            for key in ('_poller_task', '_relay_task'):
                task = app.get(key)
                if task:
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass

        asyncio.run(run_startup())

        self.assertIs(bridge._buses.get('om'), bridge._om_bus,
                      "bridge._buses['om'] must be the same SqliteMessageBus as bridge._om_bus")

    def test_om_bus_not_double_closed_on_cleanup(self):
        """_on_cleanup must close the OM bus exactly once.

        When _buses['om'] is wired, the cleanup loop closes it. The explicit
        self._om_bus.close() must be removed to avoid a double-close.
        """
        from bridge.server import TeaPartyBridge

        static_dir = os.path.join(self.tmpdir, 'static')
        os.makedirs(static_dir)
        bridge = TeaPartyBridge(
            teaparty_home=self.tmpdir,
            static_dir=static_dir,
        )

        class _FakeApp(dict):
            pass

        app = _FakeApp()
        close_count = [0]

        async def run_lifecycle():
            await bridge._on_startup(app)
            for key in ('_poller_task', '_relay_task'):
                task = app.get(key)
                if task:
                    task.cancel()
                    try:
                        await task
                    except (asyncio.CancelledError, Exception):
                        pass

            # Patch the OM bus close method on the instance attribute to count calls.
            # bridge._om_bus and bridge._buses['om'] are the same object after the fix.
            original_close = bridge._om_bus.close

            def counting_close():
                close_count[0] += 1
                original_close()

            bridge._om_bus.close = counting_close

            await bridge._on_cleanup(app)

        asyncio.run(run_lifecycle())

        self.assertEqual(close_count[0], 1,
                         '_on_cleanup must close the OM bus exactly once')


if __name__ == '__main__':
    unittest.main()
