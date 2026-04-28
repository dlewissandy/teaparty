"""Regression: a permission stall produces an operator-visible signal.

Detection alone is not enough — without surfacing, a stalled worker
costs the operator a log dive to discover.  ``run_agent_loop`` must
write two artifacts when ``_looks_like_permission_stall`` matches a
clean-exit reply:

1. A ``stall_detected`` telemetry event on the agent's scope, so the
   dashboard friction view records the friction and the audit trail
   keeps the diagnostic.
2. A ``system`` sender message on the agent's conversation, so the
   chat panel renders the stall inline next to the agent's output.

A recovery decision (anything other than ``abort``) emits the matching
``stall_recovered`` event and a ``Permission stall recovery: …``
system message, closing the friction-signal pair.

The detector unit-tests in ``test_permission_stall_recovery.py`` pin
the regex; this file pins the surfacing behaviour.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.messaging.child_dispatch import (
    _emit_stall_signals,
    _emit_stall_recovery_signal,
)


class _StubBus:
    """Captures ``send`` calls without touching SQLite."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def send(self, conv_id: str, sender: str, content: str) -> str:
        self.calls.append((conv_id, sender, content))
        return 'msg-' + str(len(self.calls))


class StallSignalsEmitTest(unittest.TestCase):
    """``_emit_stall_signals`` writes a bus system message and (when scope is
    non-empty) a telemetry event."""

    def test_bus_system_message_is_sent(self) -> None:
        bus = _StubBus()
        _emit_stall_signals(
            bus=bus,
            conv_id='conv-abc',
            agent_name='writing-lead',
            launch_kwargs_base={'scope': 'project-x', 'session_id': 'sid-1'},
            reply_head="I'm blocked on permission for VOICE-SWATCH.md",
        )
        self.assertEqual(len(bus.calls), 1)
        conv_id, sender, content = bus.calls[0]
        self.assertEqual(conv_id, 'conv-abc')
        self.assertEqual(sender, 'system')
        self.assertIn('Permission stall', content)
        self.assertIn("blocked on permission", content)

    def test_bus_failure_does_not_raise(self) -> None:
        """A closed conversation must not abort the recovery path."""

        class _BoomBus:
            def send(self, *a, **kw):  # noqa: ANN001, ARG002
                raise ValueError('conversation closed')

        # Must not raise.
        _emit_stall_signals(
            bus=_BoomBus(),
            conv_id='conv-x',
            agent_name='writing-lead',
            launch_kwargs_base={'scope': 'project-x', 'session_id': 'sid-1'},
            reply_head='blocked',
        )

    def test_telemetry_scope_takes_precedence_over_scope(self) -> None:
        """``telemetry_scope`` is the project slug for cross-repo dispatch.

        When set, it overrides ``scope`` (the management bucket).  This
        keeps the stall event in the friction view of the project the
        operator is actually watching.
        """
        recorded: list[dict] = []

        def _capture(event_type, *, scope, agent_name, session_id, data):
            recorded.append({
                'event_type': event_type,
                'scope': scope,
                'agent_name': agent_name,
                'session_id': session_id,
                'data': data,
            })

        # Patch the lazy import inside the helper.
        import teaparty.telemetry as _tele
        original = _tele.record_event
        _tele.record_event = _capture
        try:
            _emit_stall_signals(
                bus=_StubBus(),
                conv_id='conv-abc',
                agent_name='writing-lead',
                launch_kwargs_base={
                    'scope': 'management',
                    'telemetry_scope': 'joke-book',
                    'session_id': 'sid-9',
                },
                reply_head='blocked on permission',
            )
        finally:
            _tele.record_event = original

        self.assertEqual(len(recorded), 1)
        ev = recorded[0]
        self.assertEqual(ev['event_type'], 'stall_detected')
        self.assertEqual(ev['scope'], 'joke-book')
        self.assertEqual(ev['agent_name'], 'writing-lead')
        self.assertEqual(ev['session_id'], 'sid-9')
        self.assertEqual(ev['data'].get('kind'), 'permission_stall')
        self.assertIn('reply_head', ev['data'])

    def test_no_scope_skips_telemetry_keeps_bus(self) -> None:
        """An empty scope must not synthesize a fake one — drop the event."""
        recorded: list[dict] = []

        def _capture(event_type, *, scope, agent_name, session_id, data):
            recorded.append({'scope': scope})

        import teaparty.telemetry as _tele
        original = _tele.record_event
        _tele.record_event = _capture
        bus = _StubBus()
        try:
            _emit_stall_signals(
                bus=bus,
                conv_id='conv',
                agent_name='ag',
                launch_kwargs_base={'session_id': 'sid'},
                reply_head='',
            )
        finally:
            _tele.record_event = original

        # No telemetry written, but bus message still goes out.
        self.assertEqual(recorded, [])
        self.assertEqual(len(bus.calls), 1)


class StallRecoverySignalsEmitTest(unittest.TestCase):
    """``_emit_stall_recovery_signal`` closes the friction-signal pair."""

    def test_recovery_emits_recovered_event(self) -> None:
        recorded: list[dict] = []

        def _capture(event_type, *, scope, agent_name, session_id, data):
            recorded.append({'event_type': event_type, 'data': data})

        import teaparty.telemetry as _tele
        original = _tele.record_event
        _tele.record_event = _capture
        bus = _StubBus()
        try:
            _emit_stall_recovery_signal(
                bus=bus,
                conv_id='conv-abc',
                agent_name='writing-lead',
                launch_kwargs_base={'scope': 'project-x', 'session_id': 'sid'},
                decision='retry',
            )
        finally:
            _tele.record_event = original

        self.assertEqual(len(recorded), 1)
        self.assertEqual(recorded[0]['event_type'], 'stall_recovered')
        self.assertEqual(recorded[0]['data'].get('decision'), 'retry')
        self.assertEqual(len(bus.calls), 1)
        self.assertEqual(bus.calls[0][1], 'system')
        self.assertIn('recovery', bus.calls[0][2].lower())


if __name__ == '__main__':
    unittest.main()
