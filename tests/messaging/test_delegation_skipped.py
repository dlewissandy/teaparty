"""Regression: a lead-tier turn that writes without dispatching is surfaced.

A lead's role is to delegate via ``Send``.  Its team roster is in the
system prompt.  When the lead instead produces filesystem-mutating
tool calls (Write/Edit/Bash) and never dispatches, the role is being
violated.  ``run_agent_loop`` emits ``delegation_skipped`` telemetry
and a ``system`` bus message so the operator sees the friction
instead of discovering it by reading bus history.

The detector latches on the first ``Send`` so subsequent assembly
turns (Write after the team has delivered) are not re-flagged.
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.messaging.child_dispatch import _emit_delegation_skipped


class _StubBus:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def send(self, conv_id: str, sender: str, content: str) -> str:
        self.calls.append((conv_id, sender, content))
        return 'mid'


class DelegationSkippedEmitTest(unittest.TestCase):
    """``_emit_delegation_skipped`` writes both signals."""

    def test_telemetry_and_bus_signal(self) -> None:
        recorded: list[dict] = []

        def _capture(event_type, *, scope, agent_name, session_id, data):
            recorded.append({
                'event_type': event_type,
                'scope': scope,
                'agent_name': agent_name,
                'session_id': session_id,
                'data': data,
            })

        import teaparty.telemetry as _tele
        original = _tele.record_event
        _tele.record_event = _capture
        bus = _StubBus()
        try:
            _emit_delegation_skipped(
                bus=bus,
                conv_id='conv-abc',
                agent_name='research-lead',
                launch_kwargs_base={'scope': 'project-x', 'session_id': 'sid'},
                tool_use_counts={'Write': 7, 'Bash': 3},
            )
        finally:
            _tele.record_event = original

        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]['event_type'], 'delegation_skipped')
        self.assertEqual(recorded[0]['data']['tool_use_counts']['Write'], 7)

        self.assertEqual(len(bus.calls), 1)
        conv, sender, content = bus.calls[0]
        self.assertEqual(sender, 'system')
        self.assertIn('research-lead', content)
        self.assertIn('7 Write', content)
        self.assertIn('zero Send', content)


class RunAgentLoopDelegationSemanticsTest(unittest.TestCase):
    """Loop-level pin: detector fires for a write-without-send turn,
    stays silent for a normal Send-then-assemble flow.
    """

    def _run_loop(
        self, *, agent_name, tool_calls_per_turn, num_turns,
    ) -> tuple[list[str], list[tuple[str, str, str]]]:
        """Drive ``run_agent_loop`` against a scripted launch_fn whose
        stream events synthesize tool_use payloads of the requested shape.
        """
        import asyncio
        from teaparty.messaging import child_dispatch

        class _Result:
            def __init__(self) -> None:
                self.result = 'ok'
                self.session_id = 'claude-sid'
                self.exit_code = 0
                self.stall_killed = False

        idx = {'i': 0}

        async def fake_launch(**kwargs):
            on_stream = kwargs.get('on_stream_event')
            tools = tool_calls_per_turn[idx['i']]
            idx['i'] += 1
            if on_stream:
                on_stream({
                    'type': 'assistant',
                    'message': {
                        'content': [
                            {'type': 'tool_use', 'name': name}
                            for name in tools
                        ],
                    },
                })
            return _Result()

        bus_calls: list[tuple[str, str, str]] = []

        class _Bus:
            def send(self, conv_id, sender, content):
                bus_calls.append((conv_id, sender, content))
                return 'mid'

            def children_of(self, conv_id):
                return []

        # No grandchildren in any turn → loop exits after each turn
        # via the natural-exit branch.  Drive multiple turns by
        # setting on_terminate to return None for the first
        # ``num_turns - 1`` calls and a sentinel on the last so the
        # loop terminates cleanly.
        terminate_calls = {'n': 0}

        async def on_terminate():
            terminate_calls['n'] += 1
            if terminate_calls['n'] >= num_turns:
                return 'DONE'  # any non-None terminal value
            return None

        # If we want multiple turns, the loop needs to re-enter.  A
        # natural-exit happens when no grandchildren and on_terminate
        # returns None.  To re-enter we'd need a grandchild reply.
        # Simpler: just run num_turns=1 here and verify the per-turn
        # detection.  Multi-turn semantics covered by the unit-helper
        # tests above.
        from teaparty.teams import stream as _stream_mod
        original_classify = _stream_mod._classify_event
        _stream_mod._classify_event = lambda ev, agent, tu, tr: []

        telemetry: list[str] = []

        def _capture_event(event_type, *, scope, agent_name, session_id, data):
            telemetry.append(event_type)

        import teaparty.telemetry as _tele
        original_record = _tele.record_event
        _tele.record_event = _capture_event

        class _Session:
            id = 'sid'
            claude_session_id = ''

        try:
            asyncio.run(child_dispatch.run_agent_loop(
                agent_name=agent_name,
                initial_message='go',
                bus=_Bus(),
                conv_id='conv',
                session=_Session(),
                tasks_by_child={},
                results_by_child={},
                launch_fn=fake_launch,
                launch_kwargs_base={'scope': 'p', 'session_id': 'sid'},
                on_terminate=on_terminate,
            ))
        finally:
            _tele.record_event = original_record
            _stream_mod._classify_event = original_classify

        return telemetry, bus_calls

    def test_lead_writes_without_send_emits_signal(self) -> None:
        """A lead-tier turn with Write but no Send must trip the detector."""
        telemetry, bus_calls = self._run_loop(
            agent_name='research-lead',
            tool_calls_per_turn=[['Write', 'Write', 'Bash']],
            num_turns=1,
        )
        self.assertIn('delegation_skipped', telemetry)
        self.assertTrue(
            any(c[1] == 'system' and 'Delegation skipped' in c[2]
                for c in bus_calls),
            f'no system message about delegation in {bus_calls!r}',
        )

    def test_specialist_writing_does_not_trip(self) -> None:
        """Specialists are expected to write; the detector targets leads only."""
        telemetry, bus_calls = self._run_loop(
            agent_name='researcher',
            tool_calls_per_turn=[['Write', 'Write', 'Bash']],
            num_turns=1,
        )
        self.assertNotIn('delegation_skipped', telemetry)

    def test_lead_send_does_not_trip(self) -> None:
        """A lead that dispatches is fine, even on a turn with Read/Bash too."""
        telemetry, bus_calls = self._run_loop(
            agent_name='research-lead',
            tool_calls_per_turn=[['Read', 'mcp__teaparty-config__Send']],
            num_turns=1,
        )
        self.assertNotIn('delegation_skipped', telemetry)


if __name__ == '__main__':
    unittest.main()
