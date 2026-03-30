#!/usr/bin/env python3
"""Tests for issue #92: Replace bespoke state management with python-statemachine.

Verifies:
 1. CfAMachine exists as a StateMachine subclass with states matching the JSON definition
 2. CfAMachine accepts every valid transition from the JSON and rejects invalid ones
 3. The transition() function delegates to the machine (not just dict lookup)
 4. RunnerSM exists as a declared state machine for ClaudeRunner lifecycle
 5. RunnerSM enforces valid lifecycle transitions
 6. Backward compatibility: CfaState, TRANSITIONS, and all public API preserved
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Helpers ─────────────────────────────────────────────────────────────────

def _load_json_machine() -> dict:
    """Load the canonical JSON state machine definition."""
    json_path = os.path.join(
        os.path.dirname(__file__), '..', 'cfa-state-machine.json',
    )
    with open(json_path) as f:
        return json.load(f)


def _all_transitions_from_json(machine: dict) -> list[tuple[str, str, str, str]]:
    """Extract all (from_state, action, to_state, actor) tuples from JSON."""
    result = []
    for from_state, edges in machine['transitions'].items():
        for edge in edges:
            result.append((from_state, edge['action'], edge['to'], edge['actor']))
    return result


# ── Test: CfAMachine exists and matches JSON ───────────────────────────────

class TestCfAMachineExists(unittest.TestCase):
    """The CfA state machine is declared as a python-statemachine StateMachine."""

    def test_cfa_machine_class_exists(self):
        """CfAMachine is importable from cfa_machine module."""
        from scripts.cfa_machine import CfAMachine
        from statemachine import StateMachine
        self.assertTrue(
            issubclass(CfAMachine, StateMachine),
            'CfAMachine must be a StateMachine subclass',
        )

    def test_machine_has_correct_state_count(self):
        """CfAMachine has exactly the number of states defined in JSON."""
        from scripts.cfa_machine import CfAMachine
        machine_json = _load_json_machine()
        expected_states = set()
        for phase_info in machine_json['phases'].values():
            expected_states.update(phase_info['states'])
        machine_states = {s.value for s in CfAMachine.states}
        self.assertEqual(machine_states, expected_states)

    def test_machine_initial_state_is_idea(self):
        """CfAMachine starts at IDEA."""
        from scripts.cfa_machine import CfAMachine
        sm = CfAMachine()
        self.assertEqual(sm.current_state_value, 'IDEA')

    def test_machine_terminal_states(self):
        """COMPLETED_WORK and WITHDRAWN are final states."""
        from scripts.cfa_machine import CfAMachine
        final_values = {s.value for s in CfAMachine.states if s.final}
        self.assertIn('COMPLETED_WORK', final_values)
        self.assertIn('WITHDRAWN', final_values)


class TestCfAMachineTransitions(unittest.TestCase):
    """CfAMachine accepts every valid transition from JSON and rejects invalid ones."""

    def test_every_json_transition_is_valid(self):
        """Every transition in the JSON is accepted by the machine."""
        from scripts.cfa_machine import CfAMachine
        machine_json = _load_json_machine()
        failures = []
        for from_state, action, to_state, _actor in _all_transitions_from_json(machine_json):
            try:
                sm = CfAMachine(start_value=from_state)
                event_name = action.replace('-', '_')
                sm.send(event_name)
                actual_to = sm.current_state_value
                if actual_to != to_state:
                    failures.append(
                        f'{from_state} --{action}--> expected {to_state}, got {actual_to}'
                    )
            except Exception as exc:
                failures.append(f'{from_state} --{action}--> raised {exc}')
        self.assertEqual(failures, [], '\n'.join(failures))

    def test_invalid_transition_rejected(self):
        """An action not valid from the current state is rejected."""
        from scripts.cfa_machine import CfAMachine
        sm = CfAMachine()  # starts at IDEA
        with self.assertRaises(Exception):
            sm.send('approve')  # not valid from IDEA

    def test_machine_start_value_resume(self):
        """Machine can be instantiated at any valid state via start_value."""
        from scripts.cfa_machine import CfAMachine
        machine_json = _load_json_machine()
        all_states = set()
        for phase_info in machine_json['phases'].values():
            all_states.update(phase_info['states'])
        for state in all_states:
            sm = CfAMachine(start_value=state)
            self.assertEqual(sm.current_state_value, state)


# ── Test: transition() uses the machine ────────────────────────────────────

class TestTransitionUsesMachine(unittest.TestCase):
    """The transition() function delegates to the state machine for validation."""

    def test_transition_still_works(self):
        """Existing transition() API continues to work correctly."""
        from scripts.cfa_state import make_initial_state, transition
        cfa = make_initial_state()
        cfa = transition(cfa, 'propose')
        self.assertEqual(cfa.state, 'PROPOSAL')

    def test_transition_raises_invalid_transition(self):
        """Invalid actions still raise InvalidTransition."""
        from scripts.cfa_state import (
            InvalidTransition, make_initial_state, transition,
        )
        cfa = make_initial_state()
        with self.assertRaises(InvalidTransition):
            transition(cfa, 'approve')

    def test_transition_immutability(self):
        """transition() returns a new CfaState, never mutates the original."""
        from scripts.cfa_state import make_initial_state, transition
        cfa = make_initial_state()
        new_cfa = transition(cfa, 'propose')
        self.assertEqual(cfa.state, 'IDEA')
        self.assertEqual(new_cfa.state, 'PROPOSAL')

    def test_transition_updates_history(self):
        """transition() appends to history list."""
        from scripts.cfa_state import make_initial_state, transition
        cfa = make_initial_state()
        cfa = transition(cfa, 'propose')
        self.assertEqual(len(cfa.history), 1)
        self.assertEqual(cfa.history[0]['action'], 'propose')

    def test_transition_tracks_backtracks(self):
        """Cross-phase backtracks increment backtrack_count."""
        from scripts.cfa_state import make_initial_state, transition
        cfa = make_initial_state()
        cfa = transition(cfa, 'propose')
        cfa = transition(cfa, 'auto-approve')  # INTENT
        cfa = transition(cfa, 'plan')  # DRAFT
        cfa = transition(cfa, 'refine-intent')  # backtrack
        self.assertEqual(cfa.backtrack_count, 1)

    def test_available_actions_returns_hyphenated_names(self):
        """available_actions() returns hyphenated action names, not underscored."""
        from scripts.cfa_state import available_actions
        actions = dict(available_actions('PROPOSAL'))
        self.assertIn('auto-approve', actions)
        self.assertNotIn('auto_approve', actions)


# ── Test: TRANSITIONS dict backward compatibility ──────────────────────────

class TestTransitionsDictCompat(unittest.TestCase):
    """TRANSITIONS dict preserves the (action, target, actor) tuple interface."""

    def test_transitions_is_dict(self):
        from scripts.cfa_state import TRANSITIONS
        self.assertIsInstance(TRANSITIONS, dict)

    def test_transitions_get_returns_tuples(self):
        """TRANSITIONS.get(state) returns list of (action, target, actor) tuples."""
        from scripts.cfa_state import TRANSITIONS
        edges = TRANSITIONS.get('PROPOSAL', [])
        self.assertTrue(len(edges) > 0)
        for edge in edges:
            self.assertEqual(len(edge), 3, f'Expected 3-tuple, got {edge}')
            action, target, actor = edge
            self.assertIsInstance(action, str)
            self.assertIsInstance(target, str)
            self.assertIsInstance(actor, str)

    def test_transitions_action_names_are_hyphenated(self):
        """TRANSITIONS dict uses hyphenated action names (matching JSON)."""
        from scripts.cfa_state import TRANSITIONS
        edges = TRANSITIONS.get('PROPOSAL', [])
        action_names = {a for a, _, _ in edges}
        self.assertIn('auto-approve', action_names)


# ── Test: Machine hooks (history, backtrack counting) ──────────────────────

class TestMachineHooks(unittest.TestCase):
    """after_transition hook records history and counts backtracks."""

    def test_history_recorded_by_hook(self):
        """Machine's after_transition hook records history entries."""
        from scripts.cfa_machine import (
            CfAMachine, CfATransitionModel, PHASE_SETS,
        )
        model = CfATransitionModel(
            phase_sets=PHASE_SETS,
            last_action='propose',
            last_actor='human',
        )
        sm = CfAMachine(start_value='IDEA', cfa_model=model)
        sm.send('propose')
        self.assertEqual(len(model.history), 1)
        self.assertEqual(model.history[0]['state'], 'IDEA')
        self.assertEqual(model.history[0]['action'], 'propose')
        self.assertEqual(model.history[0]['actor'], 'human')
        self.assertIn('timestamp', model.history[0])

    def test_backtrack_counted_by_hook(self):
        """Machine's after_transition hook increments backtrack_count on cross-phase."""
        from scripts.cfa_machine import (
            CfAMachine, CfATransitionModel, PHASE_SETS,
        )
        # Start at DRAFT (planning), do refine-intent -> INTENT_RESPONSE (intent)
        model = CfATransitionModel(
            phase_sets=PHASE_SETS,
            last_action='refine-intent',
            last_actor='human',
        )
        sm = CfAMachine(start_value='DRAFT', cfa_model=model)
        sm.send('refine_intent')
        self.assertEqual(model.backtrack_count, 1)

    def test_non_backtrack_not_counted(self):
        """Forward transitions don't increment backtrack_count."""
        from scripts.cfa_machine import (
            CfAMachine, CfATransitionModel, PHASE_SETS,
        )
        model = CfATransitionModel(
            phase_sets=PHASE_SETS,
            last_action='propose',
            last_actor='human',
        )
        sm = CfAMachine(start_value='IDEA', cfa_model=model)
        sm.send('propose')
        self.assertEqual(model.backtrack_count, 0)

    def test_history_via_transition_function(self):
        """transition() history comes from the machine hook, not manual code."""
        from scripts.cfa_state import make_initial_state, transition
        cfa = make_initial_state()
        cfa = transition(cfa, 'propose')
        cfa = transition(cfa, 'auto-approve')
        self.assertEqual(len(cfa.history), 2)
        self.assertEqual(cfa.history[0]['action'], 'propose')
        self.assertEqual(cfa.history[1]['action'], 'auto-approve')


# ── Test: Machine guards (backtrack suppression) ──────────────────────────

class TestMachineGuards(unittest.TestCase):
    """Backtrack transitions are gated by the backtrack_allowed guard."""

    def test_backtrack_allowed_by_default(self):
        """Backtrack transitions work when suppress_backtracks=False (default)."""
        from scripts.cfa_machine import CfAMachine
        sm = CfAMachine(start_value='DRAFT')
        sm.send('refine_intent')  # backtrack: DRAFT -> INTENT_RESPONSE
        self.assertEqual(sm.current_state_value, 'INTENT_RESPONSE')

    def test_backtrack_suppressed(self):
        """Backtrack transitions are blocked when suppress_backtracks=True."""
        from scripts.cfa_machine import CfAMachine
        sm = CfAMachine(start_value='DRAFT', suppress_backtracks=True)
        with self.assertRaises(Exception):
            sm.send('refine_intent')

    def test_non_backtrack_unaffected_by_suppression(self):
        """Non-backtrack transitions work even with suppress_backtracks=True."""
        from scripts.cfa_machine import CfAMachine
        sm = CfAMachine(start_value='DRAFT', suppress_backtracks=True)
        sm.send('auto_approve')  # not a backtrack
        self.assertEqual(sm.current_state_value, 'PLAN')

    def test_backtrack_edges_match_json(self):
        """BACKTRACK_EDGES matches every edge with backtrack:true in JSON."""
        from scripts.cfa_machine import BACKTRACK_EDGES
        machine_json = _load_json_machine()
        expected = set()
        for from_state, edges in machine_json['transitions'].items():
            for edge in edges:
                if edge.get('backtrack'):
                    expected.add((from_state, edge['action']))
        self.assertEqual(set(BACKTRACK_EDGES), expected)


# ── Test: RunnerSM exists and works ────────────────────────────────────────

class TestRunnerSMExists(unittest.TestCase):
    """ClaudeRunner lifecycle is declared as a python-statemachine StateMachine."""

    def test_runner_sm_class_exists(self):
        """RunnerSM is importable from runner_machine module."""
        from orchestrator.runner_machine import RunnerSM
        from statemachine import StateMachine
        self.assertTrue(
            issubclass(RunnerSM, StateMachine),
            'RunnerSM must be a StateMachine subclass',
        )

    def test_runner_sm_initial_state(self):
        """RunnerSM starts at idle."""
        from orchestrator.runner_machine import RunnerSM
        sm = RunnerSM()
        self.assertEqual(sm.current_state_value, 'idle')

    def test_runner_sm_happy_path(self):
        """RunnerSM: idle -> launching -> streaming -> done."""
        from orchestrator.runner_machine import RunnerSM
        sm = RunnerSM()
        sm.send('launch')
        self.assertEqual(sm.current_state_value, 'launching')
        sm.send('stream')
        self.assertEqual(sm.current_state_value, 'streaming')
        sm.send('finish')
        self.assertEqual(sm.current_state_value, 'done')

    def test_runner_sm_stall_kill_path(self):
        """RunnerSM: idle -> launching -> streaming -> stalled -> killed."""
        from orchestrator.runner_machine import RunnerSM
        sm = RunnerSM()
        sm.send('launch')
        sm.send('stream')
        sm.send('stall')
        self.assertEqual(sm.current_state_value, 'stalled')
        sm.send('kill')
        self.assertEqual(sm.current_state_value, 'killed')

    def test_runner_sm_error_path(self):
        """RunnerSM: launching -> failed on error."""
        from orchestrator.runner_machine import RunnerSM
        sm = RunnerSM()
        sm.send('launch')
        sm.send('error')
        self.assertEqual(sm.current_state_value, 'failed')

    def test_runner_sm_invalid_transition(self):
        """RunnerSM rejects invalid transitions."""
        from orchestrator.runner_machine import RunnerSM
        sm = RunnerSM()
        with self.assertRaises(Exception):
            sm.send('stream')  # can't stream from idle


# ── Test: ClaudeRunner integrates RunnerSM ─────────────────────────────────

class TestClaudeRunnerHasSM(unittest.TestCase):
    """ClaudeRunner uses RunnerSM for lifecycle tracking."""

    def test_claude_runner_has_sm_attribute(self):
        """ClaudeRunner instances have a _sm attribute that is a RunnerSM."""
        from orchestrator.claude_runner import ClaudeRunner
        from orchestrator.runner_machine import RunnerSM
        runner = ClaudeRunner(
            prompt='test',
            cwd='/tmp',
            stream_file='/tmp/stream.jsonl',
        )
        self.assertIsInstance(runner._sm, RunnerSM)


if __name__ == '__main__':
    unittest.main()
