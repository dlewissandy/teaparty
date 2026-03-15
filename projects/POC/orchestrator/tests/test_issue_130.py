"""Tests for issue #130: CfA SVG diagram must match state machine spec.

Verifies the SVG at docs/images/cfa-backtrack-overview.svg against
cfa-state-machine.json for:
1. All states from each phase appear in the SVG
2. All backtrack transitions appear as arrows
3. Backtrack arrows use marker-end (not marker-start) for correct direction
"""
import json
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent.parent
SVG_PATH = PROJECT_ROOT / 'docs' / 'images' / 'cfa-backtrack-overview.svg'
STATE_MACHINE_PATH = PROJECT_ROOT / 'projects' / 'POC' / 'cfa-state-machine.json'


def _load_state_machine():
    with open(STATE_MACHINE_PATH) as f:
        return json.load(f)


def _load_svg():
    with open(SVG_PATH) as f:
        return f.read()


def _all_states(sm):
    """Return all states from all phases."""
    states = set()
    for phase_info in sm['phases'].values():
        states.update(phase_info['states'])
    return states


def _all_backtracks(sm):
    """Return all backtrack transitions as (from_state, to_state, action) tuples."""
    backtracks = []
    for state, edges in sm['transitions'].items():
        for edge in edges:
            if edge.get('backtrack'):
                backtracks.append((state, edge['to'], edge['action']))
    return backtracks


class TestSvgStatesMatchSpec(unittest.TestCase):
    """All states from the state machine must appear in the SVG."""

    def setUp(self):
        self.sm = _load_state_machine()
        self.svg = _load_svg()

    def test_all_intent_states_present(self):
        for state in self.sm['phases']['intent']['states']:
            self.assertIn(state, self.svg,
                          f"Intent state {state} missing from SVG")

    def test_all_planning_states_present(self):
        for state in self.sm['phases']['planning']['states']:
            self.assertIn(state, self.svg,
                          f"Planning state {state} missing from SVG")

    def test_all_execution_states_present(self):
        for state in self.sm['phases']['execution']['states']:
            # WITHDRAWN is a terminal state that may appear as a small
            # node or label — just check it's mentioned somewhere
            self.assertIn(state, self.svg,
                          f"Execution state {state} missing from SVG")


class TestSvgBacktracksMatchSpec(unittest.TestCase):
    """All backtrack transitions must appear in the SVG."""

    def setUp(self):
        self.sm = _load_state_machine()
        self.svg = _load_svg()
        self.backtracks = _all_backtracks(self.sm)

    def test_all_backtrack_sources_present(self):
        """Every backtrack source state appears in the SVG."""
        sources = {bt[0] for bt in self.backtracks}
        for source in sources:
            self.assertIn(source, self.svg,
                          f"Backtrack source {source} missing from SVG")

    def test_all_backtrack_targets_present(self):
        """Every backtrack target state appears in the SVG."""
        targets = {bt[1] for bt in self.backtracks}
        for target in targets:
            self.assertIn(target, self.svg,
                          f"Backtrack target {target} missing from SVG")

    def test_all_backtrack_action_labels_present(self):
        """Every backtrack action label appears in the SVG."""
        actions = {bt[2] for bt in self.backtracks}
        for action in actions:
            self.assertIn(action, self.svg,
                          f"Backtrack action label '{action}' missing from SVG")

    def test_backtrack_count_matches(self):
        """SVG has the same number of backtrack comments/labels as the spec."""
        # Count backtrack path elements in the SVG.
        # Each backtrack should have a comment or text label.
        # We look for action labels in the backtrack section.
        backtrack_section = self.svg[self.svg.find('BACKTRACK'):]
        action_labels = re.findall(
            r'>(refine-intent|backtrack|revise-plan)<',
            backtrack_section,
        )
        expected = len(self.backtracks)
        self.assertEqual(
            len(action_labels), expected,
            f"Expected {expected} backtrack labels, found {len(action_labels)}: {action_labels}",
        )


class TestSvgArrowDirection(unittest.TestCase):
    """Backtrack arrows must use marker-end, not marker-start."""

    def setUp(self):
        self.svg = _load_svg()

    def test_no_marker_start_on_backtrack_group(self):
        """The backtrack arrow group must not use marker-start for arrowheads."""
        # Find the backtrack group (contains the backtrack arrows)
        backtrack_section = self.svg[self.svg.find('BACKTRACK'):]
        # marker-start on the <g> tag means arrowheads point wrong direction
        g_match = re.search(r'<g[^>]*marker-start', backtrack_section)
        self.assertIsNone(
            g_match,
            "Backtrack arrows use marker-start (arrowheads point toward source). "
            "Should use marker-end (arrowheads point toward target).",
        )


if __name__ == '__main__':
    unittest.main()
