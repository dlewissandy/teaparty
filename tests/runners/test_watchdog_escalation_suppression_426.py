"""Issue #426: stall watchdog must suppress kill while AskQuestion is in flight.

Specification (per the issue's laser-focused refinement comment):

  When ``AskQuestionRunner`` enters its wait-for-reply loop, the lead
  session is marked with an "awaiting-escalation" sentinel.  The
  watchdog reads this sentinel; while set, the kill timer pauses (the
  threshold is treated as infinity).  When the reply arrives — five
  seconds in or five days in — the runner clears the sentinel and the
  watchdog resumes normal behaviour for the next turn.

  Out of scope: deleting the watchdog, broader policy changes.  Only
  the AskQuestion-wait interaction is addressed.

These tests pin the decision-level behaviour: given a state that would
otherwise indicate a stall, the watchdog MUST decline to kill if the
caller's session is in an in-flight escalation.  Reverting just the
sentinel check flips the decision and these tests fail with a specific
diagnostic.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.mcp.registry import (
    clear as _clear_registry,
    mark_escalation_active,
    mark_escalation_done,
)
from teaparty.runners.claude import ClaudeRunner


def _make_runner(session_id: str) -> ClaudeRunner:
    """Build a minimal ClaudeRunner instance for the decision helper.

    The helper reads ``self.session_id``, ``self.stall_timeout``, and
    ``self.STALE_THRESHOLD`` only.  We don't spawn a subprocess.
    """
    return ClaudeRunner(
        prompt='unused',
        cwd='/tmp',
        stream_file='/tmp/stream-426.jsonl',
        stall_timeout=1800,
        session_id=session_id,
    )


def _stalled_state() -> dict:
    """Return a state dict that, in the absence of escalation suppression,
    would unambiguously trigger a stall kill.

    All four "alive" signals fail:
      - no active (non-stale) tool call
      - lead's last event is older than STALE_THRESHOLD
      - child's last event is older than STALE_THRESHOLD (or zero)
      - no fresh child heartbeats (children_file empty)
    AND ``last_output_time`` is older than ``stall_timeout``.
    """
    now = 100_000.0
    far_past = now - 10_000.0  # well beyond any threshold
    return dict(
        now=now,
        last_output_time=far_past,
        last_lead_event_time=far_past,
        last_child_event_time=0.0,
        open_tool_calls={},
        children_file='',
        running_agent_count=0,
    )


class TestStallDecisionSuppressedDuringEscalation(unittest.TestCase):
    """Pin the suppression invariant: an active escalation means
    ``_should_kill_for_stall`` returns False even when every other
    signal would indicate a stall.
    """

    def setUp(self) -> None:
        _clear_registry()

    def tearDown(self) -> None:
        _clear_registry()

    def test_stall_state_kills_when_no_escalation_active(self) -> None:
        """Sanity check: in the absence of an escalation, the same
        state DOES trigger a kill.  This is the calibration baseline —
        without it the suppression test could pass for the wrong
        reason (e.g. the helper always returns False)."""
        runner = _make_runner(session_id='lead-sid-A')
        self.assertTrue(
            runner._should_kill_for_stall(**_stalled_state()),
            'control: a state with all alive-signals failing AND '
            'last_output_time beyond stall_timeout MUST be classified '
            'as a stall when no escalation is in flight; otherwise the '
            'suppression test below would pass vacuously',
        )

    def test_stall_state_suppressed_when_session_has_active_escalation(self) -> None:
        runner = _make_runner(session_id='lead-sid-A')
        mark_escalation_active('lead-sid-A:esc-1')
        try:
            self.assertFalse(
                runner._should_kill_for_stall(**_stalled_state()),
                'while the caller is in a legitimate AskQuestion wait, '
                'the watchdog MUST NOT declare a stall — the wait can '
                'legitimately span hours or days and the caller should '
                'not be killed.  Reverting the sentinel check flips '
                'this assertion (the lead would be killed, the '
                'AskQuestion would re-fire on resume, the original '
                'proxy reply would be orphaned).',
            )
        finally:
            mark_escalation_done('lead-sid-A:esc-1')

    def test_unrelated_session_escalation_does_not_suppress(self) -> None:
        """Negative space: marking an escalation for a *different*
        session must NOT spare this lead.  The suppression is keyed by
        ``session_id`` — a global flag would be wrong here.
        """
        runner = _make_runner(session_id='lead-sid-A')
        mark_escalation_active('different-session:esc-1')
        try:
            self.assertTrue(
                runner._should_kill_for_stall(**_stalled_state()),
                'the suppression must be per-caller; an active '
                'escalation in some other session must not spare this '
                'lead from a legitimate stall kill',
            )
        finally:
            mark_escalation_done('different-session:esc-1')

    def test_stall_resumes_after_escalation_done(self) -> None:
        """Cleanup verification: once the escalation is marked done,
        the watchdog regains its normal kill behaviour for the next
        legitimate stall.
        """
        runner = _make_runner(session_id='lead-sid-A')
        mark_escalation_active('lead-sid-A:esc-1')
        # Mid-escalation: suppressed.
        self.assertFalse(runner._should_kill_for_stall(**_stalled_state()))
        # Done: not suppressed any more.
        mark_escalation_done('lead-sid-A:esc-1')
        self.assertTrue(
            runner._should_kill_for_stall(**_stalled_state()),
            'after mark_escalation_done, suppression must lift — '
            'otherwise a hung session that left the marker behind '
            'would be permanently exempt from stall detection',
        )


class TestStallDecisionNormalChecks(unittest.TestCase):
    """Pin the existing watchdog logic: alive-signals override the
    stall decision.  These tests are calibration coverage so a future
    refactor of the helper can't accidentally regress the unrelated
    checks while the suppression test still passes.
    """

    def setUp(self) -> None:
        _clear_registry()

    def tearDown(self) -> None:
        _clear_registry()

    def test_active_tool_call_overrides_stall(self) -> None:
        runner = _make_runner(session_id='lead-sid-X')
        state = _stalled_state()
        # Tool call started 60s ago — well below STALE_THRESHOLD (120s).
        state['open_tool_calls'] = {'tool-1': state['now'] - 60.0}
        self.assertFalse(
            runner._should_kill_for_stall(**state),
            'an active (non-stale) open tool call must override the '
            'stall decision; the lead is mid-tool, not stalled',
        )

    def test_recent_lead_event_overrides_stall(self) -> None:
        runner = _make_runner(session_id='lead-sid-Y')
        state = _stalled_state()
        # Lead emitted within STALE_THRESHOLD.
        state['last_lead_event_time'] = state['now'] - 30.0
        self.assertFalse(
            runner._should_kill_for_stall(**state),
            'a recent lead stream-json event must override the stall '
            'decision; the lead is actively producing output',
        )


if __name__ == '__main__':
    unittest.main()
