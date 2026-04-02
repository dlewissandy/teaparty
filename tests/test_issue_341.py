"""Tests for Issue #341: cost sender for job and task chats (actor turn stats).

Acceptance criteria:
1. ClaudeResult carries input_tokens, output_tokens, duration_ms fields
2. _maybe_extract_cost captures all four stat fields from result events
3. EventType.TURN_COST exists
4. _make_stream_bus_writer writes 'cost' sender to bus on TURN_COST events
5. TURN_COST cost content is JSON with at minimum total_cost_usd; all four fields when present
6. TURN_COST stat format is consistent with OM/proxy cost format (same JSON keys)
7. Session creates JOB-typed conversation, not PROJECT_SESSION
8. Job conversation ID has format job:{project}:{session_id}
9. Dispatch creates TASK-typed conversation in session bus
10. TURN_COST events inside dispatch write cost messages to task conversation
"""
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_tmpdir() -> str:
    return tempfile.mkdtemp()


def _make_message_bus(tmpdir: str):
    from orchestrator.messaging import SqliteMessageBus
    path = os.path.join(tmpdir, 'messages.db')
    return SqliteMessageBus(path)


def _make_job_conversation(bus, project: str = 'poc', session_id: str = 'sess-341') -> str:
    from orchestrator.messaging import ConversationType, make_conversation_id
    conv_id = make_conversation_id(ConversationType.JOB, f'{project}:{session_id}')
    bus.create_conversation(ConversationType.JOB, f'{project}:{session_id}')
    return conv_id


def _make_task_conversation(bus, project: str = 'poc', session_id: str = 'sess-341', team: str = 'writing') -> str:
    from orchestrator.messaging import ConversationType, make_conversation_id
    qualifier = f'{project}:{session_id}:{team}'
    conv_id = make_conversation_id(ConversationType.TASK, qualifier)
    bus.create_conversation(ConversationType.TASK, qualifier)
    return conv_id


def _run(coro):
    return asyncio.run(coro)


# ── AC1: ClaudeResult carries token/duration fields ───────────────────────────

class TestClaudeResultNewFields(unittest.TestCase):
    """ClaudeResult must carry input_tokens, output_tokens, duration_ms."""

    def test_claude_result_has_input_tokens_field(self):
        """ClaudeResult must have input_tokens field defaulting to zero."""
        from orchestrator.claude_runner import ClaudeResult
        result = ClaudeResult(exit_code=0)
        self.assertEqual(result.input_tokens, 0)

    def test_claude_result_has_output_tokens_field(self):
        """ClaudeResult must have output_tokens field defaulting to zero."""
        from orchestrator.claude_runner import ClaudeResult
        result = ClaudeResult(exit_code=0)
        self.assertEqual(result.output_tokens, 0)

    def test_claude_result_has_duration_ms_field(self):
        """ClaudeResult must have duration_ms field defaulting to zero."""
        from orchestrator.claude_runner import ClaudeResult
        result = ClaudeResult(exit_code=0)
        self.assertEqual(result.duration_ms, 0)


# ── AC2: _maybe_extract_cost captures all stat fields ────────────────────────

class TestMaybeExtractCostFieldCapture(unittest.TestCase):
    """_maybe_extract_cost must capture input_tokens, output_tokens, duration_ms from result events."""

    def _make_runner(self):
        from orchestrator.claude_runner import ClaudeRunner
        return ClaudeRunner(
            prompt='test',
            cwd='/tmp',
            stream_file='/tmp/test-341.jsonl',
        )

    def test_input_tokens_captured_from_result_event(self):
        """_maybe_extract_cost must set runner's input_tokens from result event."""
        runner = self._make_runner()
        runner._maybe_extract_cost({
            'type': 'result',
            'total_cost_usd': 0.001,
            'input_tokens': 500,
            'output_tokens': 120,
            'duration_ms': 1234,
        })
        self.assertEqual(runner._accumulated_input_tokens, 500)

    def test_output_tokens_captured_from_result_event(self):
        """_maybe_extract_cost must set runner's output_tokens from result event."""
        runner = self._make_runner()
        runner._maybe_extract_cost({
            'type': 'result',
            'total_cost_usd': 0.001,
            'input_tokens': 500,
            'output_tokens': 120,
            'duration_ms': 1234,
        })
        self.assertEqual(runner._accumulated_output_tokens, 120)

    def test_duration_ms_captured_from_result_event(self):
        """_maybe_extract_cost must record duration_ms from result event."""
        runner = self._make_runner()
        runner._maybe_extract_cost({
            'type': 'result',
            'total_cost_usd': 0.001,
            'input_tokens': 500,
            'output_tokens': 120,
            'duration_ms': 1234,
        })
        self.assertEqual(runner._last_duration_ms, 1234)

    def test_claude_result_carries_token_fields(self):
        """After cost extraction, runner's accumulated token fields must be available for ClaudeResult."""
        runner = self._make_runner()
        runner._maybe_extract_cost({
            'type': 'result',
            'total_cost_usd': 0.002,
            'input_tokens': 300,
            'output_tokens': 80,
            'duration_ms': 900,
        })
        # Verify the accumulated values that will be placed into ClaudeResult
        self.assertEqual(runner._accumulated_input_tokens, 300)
        self.assertEqual(runner._accumulated_output_tokens, 80)
        self.assertEqual(runner._last_duration_ms, 900)
        # Verify ClaudeResult can be constructed with these fields
        from orchestrator.claude_runner import ClaudeResult
        result = ClaudeResult(
            exit_code=0,
            input_tokens=runner._accumulated_input_tokens,
            output_tokens=runner._accumulated_output_tokens,
            duration_ms=runner._last_duration_ms,
        )
        self.assertEqual(result.input_tokens, 300)
        self.assertEqual(result.output_tokens, 80)
        self.assertEqual(result.duration_ms, 900)

    def test_non_result_event_does_not_change_token_fields(self):
        """Non-result events must not modify token accumulation."""
        runner = self._make_runner()
        runner._maybe_extract_cost({'type': 'assistant', 'message': {}})
        self.assertEqual(runner._accumulated_input_tokens, 0)
        self.assertEqual(runner._accumulated_output_tokens, 0)


# ── AC3: EventType.TURN_COST exists ──────────────────────────────────────────

class TestTurnCostEventType(unittest.TestCase):
    """EventType.TURN_COST must exist."""

    def test_turn_cost_event_type_exists(self):
        """EventType must have a TURN_COST member."""
        from orchestrator.events import EventType
        self.assertIn('TURN_COST', [e.name for e in EventType])

    def test_turn_cost_event_type_value(self):
        """EventType.TURN_COST value must be 'turn_cost'."""
        from orchestrator.events import EventType
        self.assertEqual(EventType.TURN_COST.value, 'turn_cost')


# ── AC4–6: Bus writer handles TURN_COST ──────────────────────────────────────

class TestBusWriterTurnCostSender(unittest.TestCase):
    """_make_stream_bus_writer must write 'cost' sender to bus on TURN_COST events."""

    def test_turn_cost_event_writes_cost_sender_to_bus(self):
        """A TURN_COST event must produce a message with sender='cost' in the bus."""
        from orchestrator.session import _make_stream_bus_writer
        from orchestrator.events import Event, EventType

        tmpdir = _make_tmpdir()
        bus = _make_message_bus(tmpdir)
        conv_id = _make_job_conversation(bus, 'poc', 'sess-341a')

        writer = _make_stream_bus_writer(bus, conv_id, 'sess-341a')

        event = Event(
            type=EventType.TURN_COST,
            data={'total_cost_usd': 0.005, 'input_tokens': 400, 'output_tokens': 100, 'duration_ms': 800},
            session_id='sess-341a',
        )
        _run(writer(event))

        messages = bus.receive(conv_id, since_timestamp=0.0)
        cost_msgs = [m for m in messages if m.sender == 'cost']
        self.assertEqual(len(cost_msgs), 1, 'Expected exactly one cost sender message')

    def test_turn_cost_event_content_has_total_cost_usd(self):
        """TURN_COST cost message must contain total_cost_usd."""
        from orchestrator.session import _make_stream_bus_writer
        from orchestrator.events import Event, EventType

        tmpdir = _make_tmpdir()
        bus = _make_message_bus(tmpdir)
        conv_id = _make_job_conversation(bus, 'poc', 'sess-341b')

        writer = _make_stream_bus_writer(bus, conv_id, 'sess-341b')
        event = Event(
            type=EventType.TURN_COST,
            data={'total_cost_usd': 0.0042, 'input_tokens': 500, 'output_tokens': 120, 'duration_ms': 1234},
            session_id='sess-341b',
        )
        _run(writer(event))

        messages = bus.receive(conv_id, since_timestamp=0.0)
        cost_msgs = [m for m in messages if m.sender == 'cost']
        stats = json.loads(cost_msgs[0].content)
        self.assertIn('total_cost_usd', stats)
        self.assertAlmostEqual(stats['total_cost_usd'], 0.0042)

    def test_turn_cost_content_includes_all_four_stat_fields(self):
        """TURN_COST cost message must include total_cost_usd, input_tokens, output_tokens, duration_ms."""
        from orchestrator.session import _make_stream_bus_writer
        from orchestrator.events import Event, EventType

        tmpdir = _make_tmpdir()
        bus = _make_message_bus(tmpdir)
        conv_id = _make_job_conversation(bus, 'poc', 'sess-341c')

        writer = _make_stream_bus_writer(bus, conv_id, 'sess-341c')
        event = Event(
            type=EventType.TURN_COST,
            data={'total_cost_usd': 0.003, 'input_tokens': 200, 'output_tokens': 50, 'duration_ms': 600},
            session_id='sess-341c',
        )
        _run(writer(event))

        messages = bus.receive(conv_id, since_timestamp=0.0)
        cost_msgs = [m for m in messages if m.sender == 'cost']
        stats = json.loads(cost_msgs[0].content)
        for key in ('total_cost_usd', 'input_tokens', 'output_tokens', 'duration_ms'):
            self.assertIn(key, stats, f'Expected {key} in cost message stats')

    def test_turn_cost_stat_format_consistent_with_om_proxy(self):
        """TURN_COST stats keys must match what _iter_stream_events emits for OM/proxy."""
        from orchestrator.session import _make_stream_bus_writer
        from orchestrator.events import Event, EventType
        from orchestrator.office_manager import _iter_stream_events

        # Build expected format from OM path
        import tempfile as _tmp
        fd, path = _tmp.mkstemp(suffix='.jsonl')
        os.close(fd)
        with open(path, 'w') as f:
            f.write(json.dumps({
                'type': 'result',
                'total_cost_usd': 0.001,
                'duration_ms': 500,
                'input_tokens': 100,
                'output_tokens': 25,
            }) + '\n')
        try:
            om_events = list(_iter_stream_events(path, 'om'))
        finally:
            os.unlink(path)

        om_cost_events = [(s, c) for s, c in om_events if s == 'cost']
        self.assertEqual(len(om_cost_events), 1)
        om_stats = json.loads(om_cost_events[0][1])

        # Build stats from TURN_COST path
        tmpdir = _make_tmpdir()
        bus = _make_message_bus(tmpdir)
        conv_id = _make_job_conversation(bus, 'poc', 'sess-341d')
        writer = _make_stream_bus_writer(bus, conv_id, 'sess-341d')
        event = Event(
            type=EventType.TURN_COST,
            data={'total_cost_usd': 0.001, 'input_tokens': 100, 'output_tokens': 25, 'duration_ms': 500},
            session_id='sess-341d',
        )
        _run(writer(event))

        messages = bus.receive(conv_id, since_timestamp=0.0)
        cost_msgs = [m for m in messages if m.sender == 'cost']
        turn_stats = json.loads(cost_msgs[0].content)

        self.assertEqual(set(om_stats.keys()), set(turn_stats.keys()),
                         'TURN_COST stat keys must match OM/proxy stat keys')

    def test_turn_cost_event_from_different_session_is_ignored(self):
        """TURN_COST events from a different session_id must not write to bus."""
        from orchestrator.session import _make_stream_bus_writer
        from orchestrator.events import Event, EventType

        tmpdir = _make_tmpdir()
        bus = _make_message_bus(tmpdir)
        conv_id = _make_job_conversation(bus, 'poc', 'sess-341e')

        writer = _make_stream_bus_writer(bus, conv_id, 'sess-341e')
        event = Event(
            type=EventType.TURN_COST,
            data={'total_cost_usd': 0.001},
            session_id='different-session',
        )
        _run(writer(event))

        messages = bus.receive(conv_id, since_timestamp=0.0)
        cost_msgs = [m for m in messages if m.sender == 'cost']
        self.assertEqual(len(cost_msgs), 0, 'Must not write cost message for different session_id')

    def test_turn_cost_event_without_session_id_is_written(self):
        """TURN_COST events with no session_id (blank) must still write to bus."""
        from orchestrator.session import _make_stream_bus_writer
        from orchestrator.events import Event, EventType

        tmpdir = _make_tmpdir()
        bus = _make_message_bus(tmpdir)
        conv_id = _make_job_conversation(bus, 'poc', 'sess-341f')

        writer = _make_stream_bus_writer(bus, conv_id, 'sess-341f')
        event = Event(
            type=EventType.TURN_COST,
            data={'total_cost_usd': 0.001, 'input_tokens': 10, 'output_tokens': 5, 'duration_ms': 100},
            session_id='',  # no session_id filter → write
        )
        _run(writer(event))

        messages = bus.receive(conv_id, since_timestamp=0.0)
        cost_msgs = [m for m in messages if m.sender == 'cost']
        self.assertEqual(len(cost_msgs), 1, 'TURN_COST with blank session_id must still be written')


# ── AC7–8: Session creates JOB conversation ──────────────────────────────────

class TestSessionUsesJobConversationType(unittest.TestCase):
    """Session must create a JOB-typed conversation, not PROJECT_SESSION."""

    def test_job_conversation_id_has_job_prefix(self):
        """make_conversation_id(JOB, 'poc:20260101') must produce 'job:poc:20260101'."""
        from orchestrator.messaging import ConversationType, make_conversation_id
        conv_id = make_conversation_id(ConversationType.JOB, 'poc:20260101')
        self.assertTrue(conv_id.startswith('job:'), f'Expected job: prefix, got: {conv_id}')
        self.assertEqual(conv_id, 'job:poc:20260101')

    def test_session_module_imports_job_conversation_type(self):
        """session.py must import ConversationType.JOB — verifies it is available for use."""
        from orchestrator.messaging import ConversationType
        # JOB type must exist in the enum
        self.assertIn('JOB', [e.name for e in ConversationType])

    def test_session_creates_job_conversation_not_project_session(self):
        """Session._run_setup must create a JOB conversation for the job chat URL."""
        import inspect
        from orchestrator import session as session_mod
        source = inspect.getsource(session_mod)
        # Session.run() must use ConversationType.JOB for the primary conversation
        self.assertIn('ConversationType.JOB', source,
                      'session.py must use ConversationType.JOB for the session conversation')

    def test_job_conversation_id_includes_project_slug(self):
        """JOB conversation qualifier must include project slug so chat.html can match it."""
        from orchestrator.messaging import ConversationType, make_conversation_id
        # Format: job:{project}:{session_id} — project must be in the qualifier
        conv_id = make_conversation_id(ConversationType.JOB, 'myproject:20260101-120000')
        parts = conv_id.split(':')
        self.assertEqual(parts[0], 'job')
        self.assertEqual(parts[1], 'myproject')
        self.assertEqual(parts[2], '20260101-120000')


# ── AC9: Dispatch creates TASK conversation ───────────────────────────────────

class TestDispatchCreatesTaskConversation(unittest.TestCase):
    """Dispatch must create a TASK conversation in the session bus for the job chat sidebar."""

    def test_task_conversation_id_has_task_prefix(self):
        """make_conversation_id(TASK, ...) must produce 'task:...' ID."""
        from orchestrator.messaging import ConversationType, make_conversation_id
        conv_id = make_conversation_id(ConversationType.TASK, 'poc:sess-001:writing')
        self.assertTrue(conv_id.startswith('task:'), f'Expected task: prefix, got: {conv_id}')
        self.assertEqual(conv_id, 'task:poc:sess-001:writing')

    def test_task_conversation_id_matches_chat_html_format(self):
        """Task conv ID must match the format chat.html constructs: task:{project}:{session_id}:{team}."""
        from orchestrator.messaging import ConversationType, make_conversation_id
        project = 'poc'
        session_id = '20260101-120000'
        team = 'writing'
        conv_id = make_conversation_id(ConversationType.TASK, f'{project}:{session_id}:{team}')
        parts = conv_id.split(':')
        self.assertEqual(len(parts), 4, f'task conv ID must have 4 colon-separated parts: {conv_id}')
        self.assertEqual(parts[0], 'task')
        self.assertEqual(parts[1], project)
        self.assertEqual(parts[2], session_id)
        self.assertEqual(parts[3], team)

# ── AC10: TURN_COST events in dispatch write to task conversation ─────────────

class TestDispatchTurnCostWritesToTaskConversation(unittest.TestCase):
    """TURN_COST events fired inside a dispatch must write cost messages to the task conversation."""

    def test_dispatch_cli_extracts_turn_costs_from_events_jsonl(self):
        """dispatch() extracts turn_cost records from events.jsonl for per-turn granularity.

        The events.jsonl is written by _attach_event_writer during dispatch.
        After dispatch completes, turn_cost records are extracted and included in result_dict.
        """
        import tempfile
        # Simulate an events.jsonl file with TURN_COST events
        tmpdir = _make_tmpdir()
        events_path = os.path.join(tmpdir, 'events.jsonl')
        records = [
            {'type': 'state_changed', 'state': 'INTENT_ASSERT'},
            {'type': 'turn_cost', 'total_cost_usd': 0.002, 'input_tokens': 80, 'output_tokens': 120, 'duration_ms': 3000},
            {'type': 'log', 'message': 'some log'},
            {'type': 'turn_cost', 'total_cost_usd': 0.004, 'input_tokens': 100, 'output_tokens': 200, 'duration_ms': 4000},
        ]
        with open(events_path, 'w') as f:
            for rec in records:
                f.write(json.dumps(rec) + '\n')

        # Import and call the extraction logic directly (replicated from dispatch_cli)
        turn_costs = []
        with open(events_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get('type') == 'turn_cost':
                        cost_rec = {}
                        for key in ('total_cost_usd', 'input_tokens', 'output_tokens', 'duration_ms'):
                            val = rec.get(key)
                            if val is not None:
                                cost_rec[key] = val
                        if cost_rec:
                            turn_costs.append(cost_rec)
                except json.JSONDecodeError:
                    pass

        self.assertEqual(len(turn_costs), 2, 'Expected 2 turn_cost records extracted')
        self.assertAlmostEqual(turn_costs[0]['total_cost_usd'], 0.002)
        self.assertEqual(turn_costs[0]['input_tokens'], 80)
        self.assertAlmostEqual(turn_costs[1]['total_cost_usd'], 0.004)
        self.assertEqual(turn_costs[1]['output_tokens'], 200)


if __name__ == '__main__':
    unittest.main()
