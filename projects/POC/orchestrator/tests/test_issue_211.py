#!/usr/bin/env python3
"""Failing tests for issue #211: WORK_ESCALATION_STATES references non-existent state.

WORK_ESCALATION_STATES contains 'TASK_REVIEW_ESCALATE' which does not exist in
the CfA state machine. The correct state is 'TASK_ESCALATE'. This means
_make_result() never sets escalation_type='work', so work-level escalations
are silently lost.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.engine import (
    WORK_ESCALATION_STATES,
    PLAN_ESCALATION_STATES,
)


def _load_state_machine_states():
    """Load all valid states from the CfA state machine JSON."""
    sm_path = Path(__file__).parent.parent.parent / 'cfa-state-machine.json'
    with open(sm_path) as f:
        sm = json.load(f)
    all_states = set()
    for phase in sm['phases'].values():
        all_states.update(phase['states'])
    return all_states


class TestWorkEscalationStates(unittest.TestCase):
    """WORK_ESCALATION_STATES must reference valid state machine states."""

    def test_all_members_exist_in_state_machine(self):
        """Every state in WORK_ESCALATION_STATES must exist in cfa-state-machine.json."""
        valid_states = _load_state_machine_states()
        for state in WORK_ESCALATION_STATES:
            self.assertIn(
                state, valid_states,
                f'{state!r} is in WORK_ESCALATION_STATES but does not exist '
                f'in the CfA state machine',
            )

    def test_task_escalate_detected_as_work_escalation(self):
        """TASK_ESCALATE must be recognized as a work-level escalation."""
        self.assertIn(
            'TASK_ESCALATE', WORK_ESCALATION_STATES,
            'TASK_ESCALATE should be in WORK_ESCALATION_STATES so that '
            'work-level escalations are detected by _make_result()',
        )

    def test_no_overlap_with_plan_escalation(self):
        """WORK_ESCALATION_STATES and PLAN_ESCALATION_STATES must be disjoint."""
        overlap = WORK_ESCALATION_STATES & PLAN_ESCALATION_STATES
        self.assertEqual(
            overlap, set(),
            f'Overlap between work and plan escalation states: {overlap}',
        )


class TestTuiStateLabelsCoverage(unittest.TestCase):
    """TUI state labels should only reference valid states."""

    def test_no_stale_state_labels(self):
        """Every key in _STATE_LABELS must exist in the CfA state machine."""
        from projects.POC.tui.screens.drilldown import _STATE_LABELS
        valid_states = _load_state_machine_states()
        for state in _STATE_LABELS:
            self.assertIn(
                state, valid_states,
                f'{state!r} is in _STATE_LABELS but does not exist '
                f'in the CfA state machine',
            )


if __name__ == '__main__':
    unittest.main()
