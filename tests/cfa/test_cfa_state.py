#!/usr/bin/env python3
"""Tests for cfa_state.py — Conversation for Action state machine.

Five-state model: INTENT, PLAN, EXECUTE, DONE, WITHDRAWN.
Three working phases (intent, planning, execution) plus 'terminal'.
"""
import sys
import tempfile
import os
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from teaparty.cfa.statemachine.cfa_state import (
    CfaState,
    InvalidTransition,
    TRANSITIONS,
    ALL_STATES,
    INTENT_STATES,
    PLANNING_STATES,
    EXECUTION_STATES,
    TERMINAL_STATES,
    make_initial_state,
    set_state_direct,
    transition,
    available_actions,
    phase_for_state,
    is_globally_terminal,
    is_backtrack,
    save_state,
    load_state,
)


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _make_cfa(**kwargs) -> CfaState:
    """Create a CfaState at a given position for testing.

    Defaults to the initial INTENT state. Callers can override any field.
    """
    defaults = dict(
        phase='intent',
        state='INTENT',
        history=[],
        backtrack_count=0,
        task_id='',
    )
    defaults.update(kwargs)
    return CfaState(**defaults)


def _advance(cfa: CfaState, *actions: str) -> CfaState:
    """Apply a sequence of actions, returning the final state."""
    for action in actions:
        cfa = transition(cfa, action)
    return cfa


def _make_at_state(state: str, **kwargs) -> CfaState:
    """Create a CfaState positioned at a specific state node, with correct phase."""
    return _make_cfa(
        phase=phase_for_state(state),
        state=state,
        **kwargs,
    )


# ── make_initial_state ──────────────────────────────────────────────────────────

class TestMakeInitialState(unittest.TestCase):

    def test_initial_state_is_intent(self):
        cfa = make_initial_state()
        self.assertEqual(cfa.state, 'INTENT')

    def test_initial_phase_is_intent(self):
        cfa = make_initial_state()
        self.assertEqual(cfa.phase, 'intent')

    def test_initial_history_is_empty(self):
        cfa = make_initial_state()
        self.assertEqual(cfa.history, [])

    def test_initial_backtrack_count_is_zero(self):
        cfa = make_initial_state()
        self.assertEqual(cfa.backtrack_count, 0)

    def test_initial_task_id_is_empty(self):
        cfa = make_initial_state()
        self.assertEqual(cfa.task_id, '')

    def test_initial_with_task_id(self):
        cfa = make_initial_state(task_id='uber-001')
        self.assertEqual(cfa.task_id, 'uber-001')


# ── State set shape ─────────────────────────────────────────────────────────────

class TestStateSets(unittest.TestCase):
    """EXECUTION_STATES holds only working execution states, not terminals."""

    def test_execution_states_is_only_execute(self):
        self.assertEqual(EXECUTION_STATES, frozenset({'EXECUTE'}))

    def test_terminal_states_is_done_withdrawn(self):
        self.assertEqual(TERMINAL_STATES, frozenset({'DONE', 'WITHDRAWN'}))

    def test_terminal_states_disjoint_from_working(self):
        working = INTENT_STATES | PLANNING_STATES | EXECUTION_STATES
        self.assertEqual(working & TERMINAL_STATES, frozenset())

    def test_all_states_is_union(self):
        self.assertEqual(
            ALL_STATES,
            INTENT_STATES | PLANNING_STATES | EXECUTION_STATES | TERMINAL_STATES,
        )


# ── phase_for_state ─────────────────────────────────────────────────────────────

class TestPhaseForState(unittest.TestCase):

    def test_intent_states(self):
        for state in INTENT_STATES:
            with self.subTest(state=state):
                self.assertEqual(phase_for_state(state), 'intent')

    def test_planning_states(self):
        for state in PLANNING_STATES:
            with self.subTest(state=state):
                self.assertEqual(phase_for_state(state), 'planning')

    def test_execution_states(self):
        for state in EXECUTION_STATES:
            with self.subTest(state=state):
                self.assertEqual(phase_for_state(state), 'execution')

    def test_terminal_states_are_terminal_phase(self):
        for state in TERMINAL_STATES:
            with self.subTest(state=state):
                self.assertEqual(phase_for_state(state), 'terminal')

    def test_unknown_state_raises(self):
        with self.assertRaises(ValueError):
            phase_for_state('BOGUS_STATE')

    def test_specific_samples(self):
        self.assertEqual(phase_for_state('INTENT'), 'intent')
        self.assertEqual(phase_for_state('PLAN'), 'planning')
        self.assertEqual(phase_for_state('EXECUTE'), 'execution')
        self.assertEqual(phase_for_state('DONE'), 'terminal')
        self.assertEqual(phase_for_state('WITHDRAWN'), 'terminal')


# ── available_actions ───────────────────────────────────────────────────────────

class TestAvailableActions(unittest.TestCase):

    def test_intent_actions(self):
        actions = available_actions('INTENT')
        self.assertIn('approve', actions)
        self.assertIn('withdraw', actions)

    def test_done_has_no_actions(self):
        self.assertEqual(available_actions('DONE'), [])

    def test_withdrawn_has_no_actions(self):
        self.assertEqual(available_actions('WITHDRAWN'), [])

    def test_unknown_state_raises(self):
        with self.assertRaises(ValueError):
            available_actions('NOT_A_STATE')

    def test_all_states_have_known_actions(self):
        """Every state in ALL_STATES should be queryable."""
        for state in ALL_STATES:
            with self.subTest(state=state):
                result = available_actions(state)
                self.assertIsInstance(result, list)


# ── is_globally_terminal ────────────────────────────────────────────────────────

class TestIsGloballyTerminal(unittest.TestCase):

    def test_done_is_globally_terminal(self):
        self.assertTrue(is_globally_terminal('DONE'))

    def test_withdrawn_is_globally_terminal(self):
        self.assertTrue(is_globally_terminal('WITHDRAWN'))

    def test_working_states_are_not_globally_terminal(self):
        for state in ('INTENT', 'PLAN', 'EXECUTE'):
            with self.subTest(state=state):
                self.assertFalse(is_globally_terminal(state))


# ── is_backtrack ────────────────────────────────────────────────────────────────

class TestIsBacktrack(unittest.TestCase):

    def test_plan_realign_is_backtrack(self):
        self.assertTrue(is_backtrack('PLAN', 'realign'))

    def test_execute_replan_is_backtrack(self):
        self.assertTrue(is_backtrack('EXECUTE', 'replan'))

    def test_execute_realign_is_backtrack(self):
        self.assertTrue(is_backtrack('EXECUTE', 'realign'))

    def test_forward_transitions_are_not_backtracks(self):
        forward_cases = [
            ('INTENT', 'approve'),
            ('PLAN', 'approve'),
            ('EXECUTE', 'approve'),
        ]
        for from_state, action in forward_cases:
            with self.subTest(from_state=from_state, action=action):
                self.assertFalse(is_backtrack(from_state, action))

    def test_unknown_action_returns_false(self):
        self.assertFalse(is_backtrack('PLAN', 'nonexistent-action'))

    def test_withdraw_is_not_a_backtrack(self):
        """Transitions into terminal states are ends, not backtracks."""
        for from_state in ('INTENT', 'PLAN', 'EXECUTE'):
            with self.subTest(from_state=from_state):
                self.assertFalse(is_backtrack(from_state, 'withdraw'))


# ── transition — Phase 1: Intent Alignment ──────────────────────────────────────

class TestTransitionPhase1(unittest.TestCase):

    def test_intent_approve_to_plan(self):
        cfa = _make_cfa()
        new_cfa = transition(cfa, 'approve')
        self.assertEqual(new_cfa.state, 'PLAN')
        self.assertEqual(new_cfa.phase, 'planning')

    def test_intent_withdraw_to_withdrawn(self):
        cfa = _make_cfa()
        new_cfa = transition(cfa, 'withdraw')
        self.assertEqual(new_cfa.state, 'WITHDRAWN')
        self.assertEqual(new_cfa.phase, 'terminal')


# ── transition — Phase 2: Planning ──────────────────────────────────────────────

class TestTransitionPhase2(unittest.TestCase):

    def test_plan_approve_to_execute(self):
        cfa = _make_at_state('PLAN')
        new_cfa = transition(cfa, 'approve')
        self.assertEqual(new_cfa.state, 'EXECUTE')
        self.assertEqual(new_cfa.phase, 'execution')

    def test_plan_realign_to_intent(self):
        cfa = _make_at_state('PLAN')
        new_cfa = transition(cfa, 'realign')
        self.assertEqual(new_cfa.state, 'INTENT')
        self.assertEqual(new_cfa.phase, 'intent')

    def test_plan_withdraw_to_withdrawn(self):
        cfa = _make_at_state('PLAN')
        new_cfa = transition(cfa, 'withdraw')
        self.assertEqual(new_cfa.state, 'WITHDRAWN')
        self.assertEqual(new_cfa.phase, 'terminal')


# ── transition — Phase 3: Execution ─────────────────────────────────────────────

class TestTransitionPhase3(unittest.TestCase):

    def test_execute_approve_to_done(self):
        cfa = _make_at_state('EXECUTE')
        new_cfa = transition(cfa, 'approve')
        self.assertEqual(new_cfa.state, 'DONE')
        self.assertEqual(new_cfa.phase, 'terminal')

    def test_execute_replan_to_plan(self):
        cfa = _make_at_state('EXECUTE')
        new_cfa = transition(cfa, 'replan')
        self.assertEqual(new_cfa.state, 'PLAN')
        self.assertEqual(new_cfa.phase, 'planning')

    def test_execute_realign_to_intent(self):
        cfa = _make_at_state('EXECUTE')
        new_cfa = transition(cfa, 'realign')
        self.assertEqual(new_cfa.state, 'INTENT')
        self.assertEqual(new_cfa.phase, 'intent')

    def test_execute_withdraw_to_withdrawn(self):
        cfa = _make_at_state('EXECUTE')
        new_cfa = transition(cfa, 'withdraw')
        self.assertEqual(new_cfa.state, 'WITHDRAWN')
        self.assertEqual(new_cfa.phase, 'terminal')


# ── Invalid transitions ──────────────────────────────────────────────────────────

class TestInvalidTransitions(unittest.TestCase):

    def test_invalid_action_raises_invalid_transition(self):
        cfa = _make_cfa()
        with self.assertRaises(InvalidTransition):
            transition(cfa, 'replan')  # not valid from INTENT

    def test_wrong_action_for_state_raises(self):
        cfa = _make_at_state('INTENT')
        with self.assertRaises(InvalidTransition):
            transition(cfa, 'accept')

    def test_terminal_state_raises_on_any_action(self):
        for terminal in ('DONE', 'WITHDRAWN'):
            cfa = _make_at_state(terminal)
            with self.subTest(terminal=terminal):
                with self.assertRaises(InvalidTransition):
                    transition(cfa, 'approve')

    def test_error_message_lists_valid_actions(self):
        cfa = _make_at_state('INTENT')
        try:
            transition(cfa, 'bogus-action')
            self.fail("Expected InvalidTransition")
        except InvalidTransition as e:
            # Error message should mention the invalid action
            self.assertIn('bogus-action', str(e))

    def test_skipping_phases_raises(self):
        """Cannot jump from INTENT straight to EXECUTE."""
        cfa = _make_cfa()
        with self.assertRaises(InvalidTransition):
            transition(cfa, 'replan')

    def test_every_state_rejects_random_action(self):
        """Every state should reject a nonsense action."""
        for state in ALL_STATES:
            with self.subTest(state=state):
                cfa = _make_at_state(state)
                with self.assertRaises(InvalidTransition):
                    transition(cfa, '__nonexistent__')


# ── History accumulation ────────────────────────────────────────────────────────

class TestHistory(unittest.TestCase):

    def test_history_grows_on_each_transition(self):
        cfa = make_initial_state()
        self.assertEqual(len(cfa.history), 0)
        cfa = transition(cfa, 'approve')
        self.assertEqual(len(cfa.history), 1)
        cfa = transition(cfa, 'approve')
        self.assertEqual(len(cfa.history), 2)

    def test_history_entry_has_required_keys(self):
        cfa = make_initial_state()
        cfa = transition(cfa, 'approve')
        entry = cfa.history[0]
        self.assertIn('state', entry)
        self.assertIn('action', entry)
        self.assertIn('timestamp', entry)

    def test_history_records_correct_from_state(self):
        cfa = make_initial_state()
        cfa = transition(cfa, 'approve')
        self.assertEqual(cfa.history[0]['state'], 'INTENT')
        self.assertEqual(cfa.history[0]['action'], 'approve')

    def test_history_is_not_mutated_between_instances(self):
        """Original CfaState is not mutated when transitioning."""
        original = make_initial_state()
        new_cfa = transition(original, 'approve')
        self.assertEqual(len(original.history), 0)
        self.assertEqual(len(new_cfa.history), 1)

    def test_history_timestamp_is_iso_format(self):
        from datetime import datetime
        cfa = transition(make_initial_state(), 'approve')
        ts = cfa.history[0]['timestamp']
        # Should parse without error
        parsed = datetime.fromisoformat(ts)
        self.assertIsNotNone(parsed)


# ── Backtrack count ──────────────────────────────────────────────────────────────

class TestBacktrackCount(unittest.TestCase):

    def test_forward_transitions_do_not_increment(self):
        cfa = _advance(make_initial_state(), 'approve', 'approve', 'approve')
        self.assertEqual(cfa.backtrack_count, 0)
        self.assertEqual(cfa.state, 'DONE')

    def test_plan_realign_increments(self):
        cfa = _advance(make_initial_state(), 'approve', 'realign')
        self.assertEqual(cfa.state, 'INTENT')
        self.assertEqual(cfa.backtrack_count, 1)

    def test_multiple_backtracks_accumulate(self):
        # INTENT → PLAN → realign → INTENT (backtrack #1)
        # → approve → PLAN → realign (backtrack #2)
        cfa = make_initial_state()
        cfa = _advance(cfa, 'approve', 'realign')
        self.assertEqual(cfa.backtrack_count, 1)
        cfa = _advance(cfa, 'approve', 'realign')
        self.assertEqual(cfa.backtrack_count, 2)

    def test_execute_replan_increments(self):
        cfa = _make_at_state('EXECUTE')
        new_cfa = transition(cfa, 'replan')
        self.assertEqual(new_cfa.backtrack_count, 1)

    def test_execute_realign_increments(self):
        cfa = _make_at_state('EXECUTE')
        new_cfa = transition(cfa, 'realign')
        self.assertEqual(new_cfa.backtrack_count, 1)

    def test_withdraw_is_not_a_backtrack(self):
        """Transitions into terminal states never increment backtrack_count."""
        for state in ('INTENT', 'PLAN', 'EXECUTE'):
            cfa = _make_at_state(state)
            with self.subTest(state=state):
                new_cfa = transition(cfa, 'withdraw')
                self.assertEqual(new_cfa.backtrack_count, 0)


# ── Persistence ──────────────────────────────────────────────────────────────────

class TestPersistence(unittest.TestCase):

    def _make_temp_path(self) -> str:
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        return path

    def test_save_and_load_initial_state(self):
        cfa = make_initial_state()
        path = self._make_temp_path()
        try:
            save_state(cfa, path)
            loaded = load_state(path)
            self.assertEqual(loaded.state, cfa.state)
            self.assertEqual(loaded.phase, cfa.phase)
            self.assertEqual(loaded.backtrack_count, cfa.backtrack_count)
            self.assertEqual(loaded.history, cfa.history)
            self.assertEqual(loaded.task_id, cfa.task_id)
        finally:
            os.unlink(path)

    def test_round_trip_with_history(self):
        cfa = _advance(make_initial_state(), 'approve', 'approve')
        path = self._make_temp_path()
        try:
            save_state(cfa, path)
            loaded = load_state(path)
            self.assertEqual(loaded.state, 'EXECUTE')
            self.assertEqual(loaded.phase, 'execution')
            self.assertEqual(len(loaded.history), 2)
        finally:
            os.unlink(path)

    def test_round_trip_with_backtrack_count(self):
        cfa = _advance(make_initial_state(), 'approve', 'realign')
        path = self._make_temp_path()
        try:
            save_state(cfa, path)
            loaded = load_state(path)
            self.assertEqual(loaded.backtrack_count, 1)
        finally:
            os.unlink(path)

    def test_round_trip_with_task_id(self):
        cfa = _make_at_state('EXECUTE', task_id='task-abc-123')
        path = self._make_temp_path()
        try:
            save_state(cfa, path)
            loaded = load_state(path)
            self.assertEqual(loaded.task_id, 'task-abc-123')
        finally:
            os.unlink(path)

    def test_round_trip_terminal_state(self):
        """Terminal states have phase='terminal' and round-trip cleanly."""
        cfa = _advance(make_initial_state(task_id='t1'), 'approve', 'approve', 'approve')
        self.assertEqual(cfa.state, 'DONE')
        self.assertEqual(cfa.phase, 'terminal')
        path = self._make_temp_path()
        try:
            save_state(cfa, path)
            loaded = load_state(path)
            self.assertEqual(loaded.state, 'DONE')
            self.assertEqual(loaded.phase, 'terminal')
        finally:
            os.unlink(path)

    def test_saved_file_is_valid_json(self):
        import json
        cfa = make_initial_state()
        path = self._make_temp_path()
        try:
            save_state(cfa, path)
            with open(path) as f:
                data = json.load(f)
            self.assertIn('state', data)
            self.assertIn('phase', data)
            self.assertIn('history', data)
            self.assertIn('backtrack_count', data)
        finally:
            os.unlink(path)


# ── Full happy path ──────────────────────────────────────────────────────────────

class TestHappyPath(unittest.TestCase):
    """Test the complete direct path from INTENT to DONE."""

    def test_full_happy_path(self):
        """INTENT → PLAN → EXECUTE → DONE"""
        cfa = make_initial_state()
        self.assertEqual(cfa.state, 'INTENT')

        cfa = transition(cfa, 'approve')
        self.assertEqual(cfa.state, 'PLAN')
        self.assertFalse(is_globally_terminal('PLAN'))

        cfa = transition(cfa, 'approve')
        self.assertEqual(cfa.state, 'EXECUTE')

        cfa = transition(cfa, 'approve')
        self.assertEqual(cfa.state, 'DONE')

        self.assertTrue(is_globally_terminal('DONE'))
        self.assertEqual(cfa.backtrack_count, 0)
        # 3 transitions = 3 history entries
        self.assertEqual(len(cfa.history), 3)

    def test_full_happy_path_phases_correct(self):
        """Verify phase transitions at each phase boundary."""
        cfa = make_initial_state()
        self.assertEqual(cfa.phase, 'intent')

        cfa = _advance(cfa, 'approve')
        self.assertEqual(cfa.phase, 'planning')  # PLAN

        cfa = _advance(cfa, 'approve')
        self.assertEqual(cfa.phase, 'execution')  # EXECUTE

        cfa = _advance(cfa, 'approve')
        self.assertEqual(cfa.phase, 'terminal')  # DONE

    def test_withdrawn_path(self):
        """Withdrawal at any point leads to WITHDRAWN terminal state."""
        cfa = _advance(make_initial_state(), 'withdraw')
        self.assertEqual(cfa.state, 'WITHDRAWN')
        self.assertTrue(is_globally_terminal('WITHDRAWN'))
        # Cannot continue after withdrawal
        with self.assertRaises(InvalidTransition):
            transition(cfa, 'approve')


# ── Backtracking path ────────────────────────────────────────────────────────────

class TestBacktrackingPath(unittest.TestCase):
    """Test a full path that includes cross-phase backtracking."""

    def test_realign_from_plan_to_intent_and_complete(self):
        """INTENT → PLAN → realign → INTENT → approve → PLAN → approve
           → EXECUTE → approve → DONE"""
        cfa = make_initial_state()

        # Reach PLAN
        cfa = _advance(cfa, 'approve')
        self.assertEqual(cfa.state, 'PLAN')
        self.assertEqual(cfa.backtrack_count, 0)

        # Realign back to INTENT
        cfa = transition(cfa, 'realign')
        self.assertEqual(cfa.state, 'INTENT')
        self.assertEqual(cfa.phase, 'intent')
        self.assertEqual(cfa.backtrack_count, 1)

        # Re-approve intent
        cfa = transition(cfa, 'approve')
        self.assertEqual(cfa.state, 'PLAN')
        self.assertEqual(cfa.phase, 'planning')

        # Complete execution
        cfa = _advance(cfa, 'approve', 'approve')
        self.assertEqual(cfa.state, 'DONE')
        self.assertTrue(is_globally_terminal(cfa.state))
        self.assertEqual(cfa.backtrack_count, 1)

    def test_execute_replan_to_plan(self):
        """EXECUTE → replan → PLAN."""
        cfa = _make_at_state('EXECUTE')
        cfa = transition(cfa, 'replan')
        self.assertEqual(cfa.state, 'PLAN')
        self.assertEqual(cfa.phase, 'planning')
        self.assertEqual(cfa.backtrack_count, 1)

    def test_execute_realign_to_intent(self):
        """Deep backtrack: EXECUTE → realign → INTENT."""
        cfa = _make_at_state('EXECUTE')
        cfa = transition(cfa, 'realign')
        self.assertEqual(cfa.state, 'INTENT')
        self.assertEqual(cfa.phase, 'intent')
        self.assertEqual(cfa.backtrack_count, 1)


# ── Complete transition table coverage ──────────────────────────────────────────

class TestCompleteTransitionCoverage(unittest.TestCase):
    """Verify every edge in TRANSITIONS is reachable and produces correct output."""

    def test_all_transitions_produce_valid_next_state(self):
        """For every (from_state, action, target) in TRANSITIONS, the transition
        produces a CfaState with state == target and phase == phase_for_state(target)."""
        for from_state, edges in TRANSITIONS.items():
            for action, expected_target in edges:
                with self.subTest(from_state=from_state, action=action):
                    cfa = _make_at_state(from_state)
                    new_cfa = transition(cfa, action)
                    self.assertEqual(new_cfa.state, expected_target,
                        f"{from_state} --{action}--> expected {expected_target}, got {new_cfa.state}")
                    self.assertEqual(new_cfa.phase, phase_for_state(expected_target))


# ── set_state_direct ──────────────────────────────────────────────────────────

class TestSetStateDirect(unittest.TestCase):

    def test_set_to_plan(self):
        cfa = make_initial_state()
        cfa = set_state_direct(cfa, 'PLAN')
        self.assertEqual(cfa.state, 'PLAN')
        self.assertEqual(cfa.phase, 'planning')

    def test_set_to_done(self):
        cfa = _make_at_state('EXECUTE')
        cfa = set_state_direct(cfa, 'DONE')
        self.assertEqual(cfa.state, 'DONE')
        self.assertEqual(cfa.phase, 'terminal')

    def test_set_state_appends_history(self):
        cfa = make_initial_state()
        cfa = set_state_direct(cfa, 'PLAN')
        self.assertEqual(len(cfa.history), 1)
        self.assertEqual(cfa.history[0]['action'], 'set-state')
        self.assertEqual(cfa.history[0]['state'], 'INTENT')
        self.assertEqual(cfa.history[0]['target'], 'PLAN')

    def test_set_state_preserves_backtrack_count(self):
        cfa = _make_cfa(backtrack_count=3)
        cfa = set_state_direct(cfa, 'EXECUTE')
        self.assertEqual(cfa.backtrack_count, 3)

    def test_set_state_preserves_task_id(self):
        cfa = _make_cfa(task_id='t-42')
        cfa = set_state_direct(cfa, 'EXECUTE')
        self.assertEqual(cfa.task_id, 't-42')

    def test_set_state_unknown_state_raises(self):
        """set_state_direct calls phase_for_state which raises on unknown."""
        cfa = make_initial_state()
        with self.assertRaises(ValueError):
            set_state_direct(cfa, 'NOT_A_STATE')


# ── CLI --transition tests ───────────────────────────────────────────────────

class TestTransitionCLI(unittest.TestCase):
    """Test the --transition CLI command that applies validated transitions."""

    def test_valid_transition_updates_state_file(self):
        """--transition with a valid action updates the state file."""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            state_file = f.name
        try:
            # Init a state at INTENT
            cfa = make_initial_state('test-cli')
            save_state(cfa, state_file)
            self.assertEqual(cfa.state, 'INTENT')

            # Apply 'approve' transition: INTENT → PLAN
            loaded = load_state(state_file)
            result = transition(loaded, 'approve')
            save_state(result, state_file)

            reloaded = load_state(state_file)
            self.assertEqual(reloaded.state, 'PLAN')
        finally:
            os.unlink(state_file)

    def test_invalid_transition_raises(self):
        """Applying an invalid action from a given state raises InvalidTransition."""
        cfa = _make_cfa(state='INTENT')
        with self.assertRaises(InvalidTransition):
            transition(cfa, 'replan')  # 'replan' is not valid from INTENT

    def test_transition_round_trip_through_planning(self):
        """Walk through a valid transition sequence through intent and planning."""
        cfa = _make_cfa(state='INTENT')
        cfa = transition(cfa, 'approve')
        self.assertEqual(cfa.state, 'PLAN')
        cfa = transition(cfa, 'approve')
        self.assertEqual(cfa.state, 'EXECUTE')
        cfa = transition(cfa, 'approve')
        self.assertEqual(cfa.state, 'DONE')

    def test_withdraw_from_execute(self):
        """EXECUTE withdraw → WITHDRAWN."""
        cfa = _make_cfa(state='EXECUTE', phase='execution')
        cfa = transition(cfa, 'withdraw')
        self.assertEqual(cfa.state, 'WITHDRAWN')


if __name__ == '__main__':
    unittest.main()
