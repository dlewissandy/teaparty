"""Tests for Issue #335: chat.html — add state, cost, and log filter buttons per chat-windows.md spec.

Acceptance criteria:
1. _iter_stream_events yields ('cost', stats_json) for stream-json result events
2. cost stats JSON encodes total_cost_usd, duration_ms, input_tokens, output_tokens
3. result events with no recognized cost/token fields yield no cost event
4. Session bus writer writes STATE_CHANGED events to message bus with sender='state'
5. Session bus writer writes LOG events to message bus with sender='log'
6. Session bus writer ignores events from a different session_id
7. FILTER_TESTS in chat.html includes predicates for state, cost, and log senders
8. Filter row in chat.html renders state, cost, and log buttons (off by default)
9. state, cost, and log are in NON_CONVERSATIONAL_SENDERS
10. state, cost, log senders are excluded from OM dialog history
11. cost sender appears in proxy path: result events in proxy stream files yield cost messages
"""
import asyncio
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_tmpdir() -> str:
    return tempfile.mkdtemp()


def _make_stream_path(events: list) -> str:
    fd, path = tempfile.mkstemp(suffix='.jsonl', prefix='test-335-')
    os.close(fd)
    with open(path, 'w') as f:
        for ev in events:
            f.write(json.dumps(ev) + '\n')
    return path


def _make_result_event(**kwargs) -> dict:
    ev = {'type': 'result', 'subtype': 'success'}
    ev.update(kwargs)
    return ev


def _make_message_bus(tmpdir: str):
    from orchestrator.messaging import SqliteMessageBus, ConversationType
    path = os.path.join(tmpdir, 'messages.db')
    bus = SqliteMessageBus(path)
    return bus


def _make_conversation(bus, session_id: str = 'sess-test') -> str:
    from orchestrator.messaging import ConversationType, make_conversation_id
    conv_id = make_conversation_id(ConversationType.PROJECT_SESSION, session_id)
    bus.create_conversation(ConversationType.PROJECT_SESSION, session_id)
    return conv_id


# ── AC1–3: _iter_stream_events result → cost ──────────────────────────────────

class TestCostSenderFromResultEvent(unittest.TestCase):
    """_iter_stream_events must yield sender='cost' for stream-json result events."""

    def test_result_event_yields_cost_sender(self):
        """A result event with cost/token fields must produce sender='cost'."""
        from orchestrator.office_manager import _iter_stream_events

        path = _make_stream_path([
            _make_result_event(
                total_cost_usd=0.0042,
                duration_ms=1234,
                input_tokens=500,
                output_tokens=120,
            ),
        ])
        try:
            events = list(_iter_stream_events(path, 'om'))
        finally:
            os.unlink(path)

        cost_events = [(s, c) for s, c in events if s == 'cost']
        self.assertEqual(len(cost_events), 1, 'Expected exactly one cost event from a result event')

    def test_cost_event_content_encodes_stats(self):
        """cost event content must be JSON encoding total_cost_usd, duration_ms, input_tokens, output_tokens."""
        from orchestrator.office_manager import _iter_stream_events

        path = _make_stream_path([
            _make_result_event(
                total_cost_usd=0.0042,
                duration_ms=1234,
                input_tokens=500,
                output_tokens=120,
            ),
        ])
        try:
            events = list(_iter_stream_events(path, 'om'))
        finally:
            os.unlink(path)

        cost_events = [(s, c) for s, c in events if s == 'cost']
        self.assertEqual(len(cost_events), 1)
        stats = json.loads(cost_events[0][1])
        self.assertAlmostEqual(stats['total_cost_usd'], 0.0042)
        self.assertEqual(stats['duration_ms'], 1234)
        self.assertEqual(stats['input_tokens'], 500)
        self.assertEqual(stats['output_tokens'], 120)

    def test_result_event_partial_fields_yields_cost(self):
        """A result event with only total_cost_usd must still yield a cost event."""
        from orchestrator.office_manager import _iter_stream_events

        path = _make_stream_path([
            _make_result_event(total_cost_usd=0.001),
        ])
        try:
            events = list(_iter_stream_events(path, 'om'))
        finally:
            os.unlink(path)

        cost_events = [(s, c) for s, c in events if s == 'cost']
        self.assertEqual(len(cost_events), 1)
        stats = json.loads(cost_events[0][1])
        self.assertIn('total_cost_usd', stats)
        self.assertNotIn('duration_ms', stats)

    def test_result_event_no_cost_fields_yields_no_cost_event(self):
        """A result event with no cost or token fields must not yield a cost event."""
        from orchestrator.office_manager import _iter_stream_events

        path = _make_stream_path([
            {'type': 'result', 'subtype': 'error', 'error': 'something failed'},
        ])
        try:
            events = list(_iter_stream_events(path, 'om'))
        finally:
            os.unlink(path)

        cost_events = [(s, c) for s, c in events if s == 'cost']
        self.assertEqual(len(cost_events), 0, 'result event without cost data must not yield cost sender')

    def test_cost_event_does_not_suppress_other_senders(self):
        """A stream file with result + assistant events must yield both cost and agent senders."""
        from orchestrator.office_manager import _iter_stream_events

        path = _make_stream_path([
            {
                'type': 'assistant',
                'message': {'content': [{'type': 'text', 'text': 'Hello!'}]},
            },
            _make_result_event(total_cost_usd=0.001, duration_ms=500, input_tokens=10, output_tokens=5),
        ])
        try:
            events = list(_iter_stream_events(path, 'om'))
        finally:
            os.unlink(path)

        senders = [s for s, _ in events]
        self.assertIn('om', senders, 'agent text sender must still appear')
        self.assertIn('cost', senders, 'cost sender must appear alongside agent sender')


# ── AC11: cost sender in proxy path ──────────────────────────────────────────

class TestCostSenderInProxyPath(unittest.TestCase):
    """_iter_stream_events with agent_role='proxy' must also yield cost from result events."""

    def test_proxy_path_result_event_yields_cost_sender(self):
        """result events in proxy stream files must yield sender='cost'."""
        from orchestrator.office_manager import _iter_stream_events

        path = _make_stream_path([
            _make_result_event(total_cost_usd=0.002, duration_ms=800, input_tokens=80, output_tokens=30),
        ])
        try:
            events = list(_iter_stream_events(path, 'proxy'))
        finally:
            os.unlink(path)

        cost_events = [(s, c) for s, c in events if s == 'cost']
        self.assertEqual(len(cost_events), 1)


# ── AC4–6: Session bus writer for state and log ───────────────────────────────

class TestSessionBusWriterStateSender(unittest.TestCase):
    """_make_stream_bus_writer must write STATE_CHANGED events to bus with sender='state'."""

    def _run(self, coro):
        return asyncio.run(coro)

    def test_state_changed_event_writes_state_sender_to_bus(self):
        """A STATE_CHANGED event must produce a message with sender='state' in the bus."""
        from orchestrator.session import _make_stream_bus_writer
        from orchestrator.events import Event, EventBus, EventType

        tmpdir = _make_tmpdir()
        bus = _make_message_bus(tmpdir)
        conv_id = _make_conversation(bus, 'sess-335')

        writer = _make_stream_bus_writer(bus, conv_id, 'sess-335')

        event = Event(
            type=EventType.STATE_CHANGED,
            data={'previous_state': 'PROPOSAL', 'state': 'INTENT', 'action': 'propose'},
            session_id='sess-335',
        )
        self._run(writer(event))

        messages = bus.receive(conv_id, since_timestamp=0.0)
        state_msgs = [m for m in messages if m.sender == 'state']
        self.assertEqual(len(state_msgs), 1, 'Expected one state sender message')
        self.assertIn('PROPOSAL', state_msgs[0].content)
        self.assertIn('INTENT', state_msgs[0].content)

    def test_state_transition_content_format(self):
        """State message content must encode prev_state → new_state [action]."""
        from orchestrator.session import _make_stream_bus_writer
        from orchestrator.events import Event, EventBus, EventType

        tmpdir = _make_tmpdir()
        bus = _make_message_bus(tmpdir)
        conv_id = _make_conversation(bus, 'sess-fmt')

        writer = _make_stream_bus_writer(bus, conv_id, 'sess-fmt')

        event = Event(
            type=EventType.STATE_CHANGED,
            data={'previous_state': 'DRAFT', 'state': 'PLAN', 'action': 'draft'},
            session_id='sess-fmt',
        )
        self._run(writer(event))

        messages = bus.receive(conv_id, since_timestamp=0.0)
        state_msgs = [m for m in messages if m.sender == 'state']
        self.assertEqual(len(state_msgs), 1)
        content = state_msgs[0].content
        self.assertIn('DRAFT', content)
        self.assertIn('PLAN', content)
        self.assertIn('draft', content)


class TestSessionBusWriterLogSender(unittest.TestCase):
    """_make_stream_bus_writer must write LOG events to bus with sender='log'."""

    def _run(self, coro):
        return asyncio.run(coro)

    def test_log_event_writes_log_sender_to_bus(self):
        """A LOG event must produce a message with sender='log' in the bus."""
        from orchestrator.session import _make_stream_bus_writer
        from orchestrator.events import Event, EventBus, EventType

        tmpdir = _make_tmpdir()
        bus = _make_message_bus(tmpdir)
        conv_id = _make_conversation(bus, 'sess-log')

        writer = _make_stream_bus_writer(bus, conv_id, 'sess-log')

        event = Event(
            type=EventType.LOG,
            data={'category': 'INFO', 'message': 'Skill lookup succeeded'},
            session_id='sess-log',
        )
        self._run(writer(event))

        messages = bus.receive(conv_id, since_timestamp=0.0)
        log_msgs = [m for m in messages if m.sender == 'log']
        self.assertEqual(len(log_msgs), 1)
        self.assertIn('Skill lookup succeeded', log_msgs[0].content)

    def test_log_event_empty_message_not_written(self):
        """A LOG event with empty message must not produce a bus message."""
        from orchestrator.session import _make_stream_bus_writer
        from orchestrator.events import Event, EventBus, EventType

        tmpdir = _make_tmpdir()
        bus = _make_message_bus(tmpdir)
        conv_id = _make_conversation(bus, 'sess-emptylog')

        writer = _make_stream_bus_writer(bus, conv_id, 'sess-emptylog')

        event = Event(
            type=EventType.LOG,
            data={'category': 'INFO', 'message': ''},
            session_id='sess-emptylog',
        )
        self._run(writer(event))

        messages = bus.receive(conv_id, since_timestamp=0.0)
        log_msgs = [m for m in messages if m.sender == 'log']
        self.assertEqual(len(log_msgs), 0, 'Empty log message must not be written to bus')


class TestSessionBusWriterSessionFilter(unittest.TestCase):
    """_make_stream_bus_writer must ignore events from a different session_id."""

    def _run(self, coro):
        return asyncio.run(coro)

    def test_event_from_different_session_is_ignored(self):
        """Events from a different session_id must not write to the bus."""
        from orchestrator.session import _make_stream_bus_writer
        from orchestrator.events import Event, EventBus, EventType

        tmpdir = _make_tmpdir()
        bus = _make_message_bus(tmpdir)
        conv_id = _make_conversation(bus, 'sess-mine')

        writer = _make_stream_bus_writer(bus, conv_id, 'sess-mine')

        event = Event(
            type=EventType.STATE_CHANGED,
            data={'previous_state': 'PROPOSAL', 'state': 'INTENT', 'action': 'propose'},
            session_id='sess-other',  # different session
        )
        self._run(writer(event))

        messages = bus.receive(conv_id, since_timestamp=0.0)
        self.assertEqual(len(messages), 0, 'Event from a different session must not write to bus')

    def test_event_with_no_session_id_is_written(self):
        """Events with no session_id (empty string) are not filtered out."""
        from orchestrator.session import _make_stream_bus_writer
        from orchestrator.events import Event, EventBus, EventType

        tmpdir = _make_tmpdir()
        bus = _make_message_bus(tmpdir)
        conv_id = _make_conversation(bus, 'sess-noid')

        writer = _make_stream_bus_writer(bus, conv_id, 'sess-noid')

        event = Event(
            type=EventType.LOG,
            data={'category': 'INFO', 'message': 'Global diagnostic'},
            session_id='',  # no session ID
        )
        self._run(writer(event))

        messages = bus.receive(conv_id, since_timestamp=0.0)
        log_msgs = [m for m in messages if m.sender == 'log']
        self.assertEqual(len(log_msgs), 1)


# ── AC7: FILTER_TESTS in chat.html ────────────────────────────────────────────

class TestChatHtmlFilterTests(unittest.TestCase):
    """chat.html FILTER_TESTS must include state, cost, and log predicates."""

    def _read_chat_html(self) -> str:
        path = _REPO_ROOT / 'bridge' / 'static' / 'chat.html'
        return path.read_text()

    def test_filter_tests_includes_state_predicate(self):
        """FILTER_TESTS must have a 'state' key."""
        html = self._read_chat_html()
        # The FILTER_TESTS object must contain a 'state' entry
        self.assertRegex(html, r"FILTER_TESTS\s*=\s*\{[^}]*'state'", "FILTER_TESTS must include 'state' predicate")

    def test_filter_tests_includes_cost_predicate(self):
        """FILTER_TESTS must have a 'cost' key."""
        html = self._read_chat_html()
        self.assertRegex(html, r"FILTER_TESTS\s*=\s*\{[^}]*'cost'", "FILTER_TESTS must include 'cost' predicate")

    def test_filter_tests_includes_log_predicate(self):
        """FILTER_TESTS must have a 'log' key."""
        html = self._read_chat_html()
        self.assertRegex(html, r"FILTER_TESTS\s*=\s*\{[^}]*'log'", "FILTER_TESTS must include 'log' predicate")

    def test_state_predicate_matches_state_sender(self):
        """state predicate must return true for messages with sender='state'."""
        html = self._read_chat_html()
        # The state predicate must check for sender === 'state'
        # We verify the predicate body contains a reference to 'state'
        match = re.search(r"'state'\s*:\s*function\(m\)\s*\{([^}]+)\}", html)
        self.assertIsNotNone(match, "state predicate function must be present")
        body = match.group(1)
        self.assertIn('state', body)

    def test_cost_predicate_matches_cost_sender(self):
        """cost predicate must return true for messages with sender='cost'."""
        html = self._read_chat_html()
        match = re.search(r"'cost'\s*:\s*function\(m\)\s*\{([^}]+)\}", html)
        self.assertIsNotNone(match, "cost predicate function must be present")

    def test_log_predicate_matches_log_sender(self):
        """log predicate must return true for messages with sender='log'."""
        html = self._read_chat_html()
        match = re.search(r"'log'\s*:\s*function\(m\)\s*\{([^}]+)\}", html)
        self.assertIsNotNone(match, "log predicate function must be present")


# ── AC8: Filter buttons in chat.html ─────────────────────────────────────────

class TestChatHtmlFilterButtons(unittest.TestCase):
    """Filter row in chat.html must include state, cost, and log buttons."""

    def _read_chat_html(self) -> str:
        path = _REPO_ROOT / 'bridge' / 'static' / 'chat.html'
        return path.read_text()

    def test_filter_row_includes_state_button(self):
        """renderMainArea must include a filter button for 'state'."""
        html = self._read_chat_html()
        # The filter row is built from an array — it must include 'state'
        self.assertIn("'state'", html, "filter row array must include 'state'")

    def test_filter_row_includes_cost_button(self):
        """renderMainArea must include a filter button for 'cost'."""
        html = self._read_chat_html()
        self.assertIn("'cost'", html, "filter row array must include 'cost'")

    def test_filter_row_includes_log_button(self):
        """renderMainArea must include a filter button for 'log'."""
        html = self._read_chat_html()
        self.assertIn("'log'", html, "filter row array must include 'log'")

    def test_state_button_is_off_by_default(self):
        """state filter button must be off by default (not in the default-on list)."""
        html = self._read_chat_html()
        # The filter row construction: on = (f === 'agent' || f === 'human')
        # state must NOT appear in the default-on condition
        # We check that the on-by-default condition does not include 'state'
        on_match = re.search(r"var on = [^;]+;", html)
        self.assertIsNotNone(on_match, "Default-on condition must exist")
        on_expr = on_match.group(0)
        self.assertNotIn("'state'", on_expr, "state must be off by default")

    def test_cost_button_is_off_by_default(self):
        """cost filter button must be off by default."""
        html = self._read_chat_html()
        on_match = re.search(r"var on = [^;]+;", html)
        self.assertIsNotNone(on_match)
        on_expr = on_match.group(0)
        self.assertNotIn("'cost'", on_expr, "cost must be off by default")

    def test_log_button_is_off_by_default(self):
        """log filter button must be off by default."""
        html = self._read_chat_html()
        on_match = re.search(r"var on = [^;]+;", html)
        self.assertIsNotNone(on_match)
        on_expr = on_match.group(0)
        self.assertNotIn("'log'", on_expr, "log must be off by default")


# ── AC9–10: NON_CONVERSATIONAL_SENDERS ────────────────────────────────────────

class TestNonConversationalSenders(unittest.TestCase):
    """state, cost, and log must be in NON_CONVERSATIONAL_SENDERS."""

    def test_state_in_non_conversational_senders(self):
        """state sender must be in NON_CONVERSATIONAL_SENDERS."""
        from orchestrator.office_manager import NON_CONVERSATIONAL_SENDERS
        self.assertIn('state', NON_CONVERSATIONAL_SENDERS)

    def test_cost_in_non_conversational_senders(self):
        """cost sender must be in NON_CONVERSATIONAL_SENDERS."""
        from orchestrator.office_manager import NON_CONVERSATIONAL_SENDERS
        self.assertIn('cost', NON_CONVERSATIONAL_SENDERS)

    def test_log_in_non_conversational_senders(self):
        """log sender must be in NON_CONVERSATIONAL_SENDERS."""
        from orchestrator.office_manager import NON_CONVERSATIONAL_SENDERS
        self.assertIn('log', NON_CONVERSATIONAL_SENDERS)

    def test_state_sender_excluded_from_om_dialog_history(self):
        """Messages with sender='state' must be excluded from OM dialog history."""
        from orchestrator.proxy_review import build_dialog_history
        from orchestrator.messaging import SqliteMessageBus, ConversationType, make_conversation_id

        tmpdir = _make_tmpdir()
        bus = _make_message_bus(tmpdir)
        conv_id = _make_conversation(bus, 'sess-dialog')

        # Write a state message and an agent message
        bus.send(conv_id, 'state', 'PROPOSAL → INTENT [propose]')
        bus.send(conv_id, 'om', 'Task received.')

        history = build_dialog_history(bus, conv_id)

        self.assertNotIn('PROPOSAL → INTENT', history, 'state sender must be excluded from dialog history')
        self.assertIn('Task received.', history, 'agent text must appear in dialog history')

    def test_cost_sender_excluded_from_dialog_history(self):
        """Messages with sender='cost' must be excluded from dialog history."""
        from orchestrator.proxy_review import build_dialog_history
        from orchestrator.messaging import SqliteMessageBus, ConversationType, make_conversation_id

        tmpdir = _make_tmpdir()
        bus = _make_message_bus(tmpdir)
        conv_id = _make_conversation(bus, 'sess-cost-dialog')

        bus.send(conv_id, 'cost', json.dumps({'total_cost_usd': 0.001}))
        bus.send(conv_id, 'om', 'Analysis complete.')

        history = build_dialog_history(bus, conv_id)

        self.assertNotIn('total_cost_usd', history, 'cost sender must be excluded from dialog history')
        self.assertIn('Analysis complete.', history)

    def test_log_sender_excluded_from_dialog_history(self):
        """Messages with sender='log' must be excluded from dialog history."""
        from orchestrator.proxy_review import build_dialog_history
        from orchestrator.messaging import SqliteMessageBus, ConversationType, make_conversation_id

        tmpdir = _make_tmpdir()
        bus = _make_message_bus(tmpdir)
        conv_id = _make_conversation(bus, 'sess-log-dialog')

        bus.send(conv_id, 'log', 'Skill lookup failed')
        bus.send(conv_id, 'om', 'Proceeding without skill.')

        history = build_dialog_history(bus, conv_id)

        self.assertNotIn('Skill lookup failed', history, 'log sender must be excluded from dialog history')
        self.assertIn('Proceeding without skill.', history)


if __name__ == '__main__':
    unittest.main()
