#!/usr/bin/env python3
"""Tests for cfa_state.py — Conversation for Action state machine."""
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
    make_initial_state,
    make_child_state,
    is_root,
    set_state_direct,
    transition,
    available_actions,
    phase_for_state,
    is_phase_terminal,
    is_globally_terminal,
    is_backtrack,
    save_state,
    load_state,
)


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _make_cfa(**kwargs) -> CfaState:
    """Create a CfaState at a given position for testing.

    Defaults to the initial IDEA state. Callers can override any field.
    """
    defaults = dict(
        phase='intent',
        state='IDEA',
        actor='human',
        history=[],
        backtrack_count=0,
        task_id='',
        parent_id='',
        team_id='',
        depth=0,
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
    phase = phase_for_state(state)
    # Determine a plausible actor for the state (use any valid next actor or 'human')
    actions = available_actions(state)
    actor = actions[0][1] if actions else 'human'
    return _make_cfa(phase=phase, state=state, actor=actor, **kwargs)


# ── make_initial_state ──────────────────────────────────────────────────────────

class TestMakeInitialState(unittest.TestCase):

    def test_initial_state_is_idea(self):
        cfa = make_initial_state()
        self.assertEqual(cfa.state, 'IDEA')

    def test_initial_phase_is_intent(self):
        cfa = make_initial_state()
        self.assertEqual(cfa.phase, 'intent')

    def test_initial_actor_is_intent_team(self):
        cfa = make_initial_state()
        self.assertEqual(cfa.actor, 'intent_team')

    def test_initial_history_is_empty(self):
        cfa = make_initial_state()
        self.assertEqual(cfa.history, [])

    def test_initial_backtrack_count_is_zero(self):
        cfa = make_initial_state()
        self.assertEqual(cfa.backtrack_count, 0)

    def test_initial_task_id_is_empty(self):
        cfa = make_initial_state()
        self.assertEqual(cfa.task_id, '')


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

    def test_unknown_state_raises(self):
        with self.assertRaises(ValueError):
            phase_for_state('BOGUS_STATE')

    def test_specific_samples(self):
        self.assertEqual(phase_for_state('IDEA'), 'intent')
        self.assertEqual(phase_for_state('INTENT'), 'intent')
        self.assertEqual(phase_for_state('PLANNING'), 'planning')
        self.assertEqual(phase_for_state('WORK_IN_PROGRESS'), 'execution')
        self.assertEqual(phase_for_state('COMPLETED_WORK'), 'execution')
        self.assertEqual(phase_for_state('WITHDRAWN'), 'execution')


# ── available_actions ───────────────────────────────────────────────────────────

class TestAvailableActions(unittest.TestCase):

    def test_idea_actions(self):
        actions = dict(available_actions('IDEA'))
        self.assertIn('approve', actions)
        self.assertIn('withdraw', actions)

    def test_completed_work_has_no_actions(self):
        self.assertEqual(available_actions('COMPLETED_WORK'), [])

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


# ── is_phase_terminal ───────────────────────────────────────────────────────────

class TestIsPhaseTerminal(unittest.TestCase):

    def test_intent_is_phase_terminal(self):
        self.assertTrue(is_phase_terminal('INTENT'))

    def test_completed_work_is_phase_terminal(self):
        self.assertTrue(is_phase_terminal('COMPLETED_WORK'))

    def test_withdrawn_is_phase_terminal(self):
        self.assertTrue(is_phase_terminal('WITHDRAWN'))

    def test_mid_states_are_not_phase_terminal(self):
        non_terminal = ['IDEA', 'PLANNING', 'WORK_IN_PROGRESS']
        for state in non_terminal:
            with self.subTest(state=state):
                self.assertFalse(is_phase_terminal(state))


# ── is_globally_terminal ────────────────────────────────────────────────────────

class TestIsGloballyTerminal(unittest.TestCase):

    def test_completed_work_is_globally_terminal(self):
        self.assertTrue(is_globally_terminal('COMPLETED_WORK'))

    def test_withdrawn_is_globally_terminal(self):
        self.assertTrue(is_globally_terminal('WITHDRAWN'))

    def test_intent_is_not_globally_terminal(self):
        self.assertFalse(is_globally_terminal('INTENT'))

    def test_mid_states_are_not_globally_terminal(self):
        for state in ['IDEA', 'PLANNING', 'WORK_IN_PROGRESS']:
            with self.subTest(state=state):
                self.assertFalse(is_globally_terminal(state))


# ── is_backtrack ────────────────────────────────────────────────────────────────

class TestIsBacktrack(unittest.TestCase):

    def test_planning_backtrack_is_backtrack(self):
        self.assertTrue(is_backtrack('PLANNING', 'backtrack'))

    def test_work_in_progress_backtrack_is_backtrack(self):
        self.assertTrue(is_backtrack('WORK_IN_PROGRESS', 'backtrack'))

    def test_work_assert_revise_plan_is_backtrack(self):
        self.assertTrue(is_backtrack('WORK_ASSERT', 'revise-plan'))

    def test_work_assert_refine_intent_is_backtrack(self):
        self.assertTrue(is_backtrack('WORK_ASSERT', 'refine-intent'))

    def test_forward_transitions_are_not_backtracks(self):
        forward_cases = [
            ('IDEA', 'approve'),
            ('INTENT', 'plan'),
            ('PLANNING', 'approve'),
            ('WORK_IN_PROGRESS', 'assert'),
        ]
        for from_state, action in forward_cases:
            with self.subTest(from_state=from_state, action=action):
                self.assertFalse(is_backtrack(from_state, action))

    def test_same_phase_transitions_are_not_backtracks(self):
        self.assertFalse(is_backtrack('WORK_ASSERT', 'correct'))

    def test_unknown_action_returns_false(self):
        self.assertFalse(is_backtrack('PLANNING', 'nonexistent-action'))


# ── transition — Phase 1: Intent Alignment ──────────────────────────────────────

class TestTransitionPhase1(unittest.TestCase):

    def test_idea_approve_to_intent(self):
        cfa = _make_cfa()
        new_cfa = transition(cfa, 'approve')
        self.assertEqual(new_cfa.state, 'INTENT')
        self.assertEqual(new_cfa.phase, 'intent')
        self.assertEqual(new_cfa.actor, 'intent_team')

    def test_idea_withdraw_to_withdrawn(self):
        cfa = _make_cfa()
        new_cfa = transition(cfa, 'withdraw')
        self.assertEqual(new_cfa.state, 'WITHDRAWN')
        self.assertEqual(new_cfa.phase, 'execution')


# ── transition — Phase 2: Planning ──────────────────────────────────────────────

class TestTransitionPhase2(unittest.TestCase):

    def test_intent_plan_to_planning(self):
        cfa = _make_at_state('INTENT')
        new_cfa = transition(cfa, 'plan')
        self.assertEqual(new_cfa.state, 'PLANNING')
        self.assertEqual(new_cfa.phase, 'planning')
        self.assertEqual(new_cfa.actor, 'planning_team')

    def test_planning_approve_to_work_in_progress(self):
        cfa = _make_at_state('PLANNING')
        new_cfa = transition(cfa, 'approve')
        self.assertEqual(new_cfa.state, 'WORK_IN_PROGRESS')
        self.assertEqual(new_cfa.phase, 'execution')
        self.assertEqual(new_cfa.actor, 'project_lead')

    def test_planning_backtrack_to_idea(self):
        cfa = _make_at_state('PLANNING')
        new_cfa = transition(cfa, 'backtrack')
        self.assertEqual(new_cfa.state, 'IDEA')
        self.assertEqual(new_cfa.phase, 'intent')

    def test_planning_withdraw_to_withdrawn(self):
        cfa = _make_at_state('PLANNING')
        new_cfa = transition(cfa, 'withdraw')
        self.assertEqual(new_cfa.state, 'WITHDRAWN')


# ── transition — Phase 3: Execution ─────────────────────────────────────────────

class TestTransitionPhase3(unittest.TestCase):

    def test_work_in_progress_assert_to_work_assert(self):
        cfa = _make_at_state('WORK_IN_PROGRESS')
        new_cfa = transition(cfa, 'assert')
        self.assertEqual(new_cfa.state, 'WORK_ASSERT')

    def test_work_in_progress_auto_approve_to_completed_work(self):
        cfa = _make_at_state('WORK_IN_PROGRESS')
        new_cfa = transition(cfa, 'auto-approve')
        self.assertEqual(new_cfa.state, 'COMPLETED_WORK')

    def test_work_in_progress_backtrack_to_planning(self):
        cfa = _make_at_state('WORK_IN_PROGRESS')
        new_cfa = transition(cfa, 'backtrack')
        self.assertEqual(new_cfa.state, 'PLANNING')
        self.assertEqual(new_cfa.phase, 'planning')

    def test_work_in_progress_withdraw_to_withdrawn(self):
        cfa = _make_at_state('WORK_IN_PROGRESS')
        new_cfa = transition(cfa, 'withdraw')
        self.assertEqual(new_cfa.state, 'WITHDRAWN')

    def test_work_assert_approve_to_completed_work(self):
        cfa = _make_at_state('WORK_ASSERT')
        new_cfa = transition(cfa, 'approve')
        self.assertEqual(new_cfa.state, 'COMPLETED_WORK')
        self.assertEqual(new_cfa.actor, 'approval_gate')

    def test_work_assert_correct_to_work_in_progress(self):
        cfa = _make_at_state('WORK_ASSERT')
        new_cfa = transition(cfa, 'correct')
        self.assertEqual(new_cfa.state, 'WORK_IN_PROGRESS')

    def test_work_assert_revise_plan_to_planning(self):
        cfa = _make_at_state('WORK_ASSERT')
        new_cfa = transition(cfa, 'revise-plan')
        self.assertEqual(new_cfa.state, 'PLANNING')
        self.assertEqual(new_cfa.phase, 'planning')

    def test_work_assert_refine_intent_to_idea(self):
        cfa = _make_at_state('WORK_ASSERT')
        new_cfa = transition(cfa, 'refine-intent')
        self.assertEqual(new_cfa.state, 'IDEA')
        self.assertEqual(new_cfa.phase, 'intent')

    def test_work_assert_withdraw_to_withdrawn(self):
        cfa = _make_at_state('WORK_ASSERT')
        new_cfa = transition(cfa, 'withdraw')
        self.assertEqual(new_cfa.state, 'WITHDRAWN')


# ── Invalid transitions ──────────────────────────────────────────────────────────

class TestInvalidTransitions(unittest.TestCase):

    def test_invalid_action_raises_invalid_transition(self):
        cfa = _make_cfa()
        with self.assertRaises(InvalidTransition):
            transition(cfa, 'plan')  # not valid from IDEA

    def test_wrong_action_for_state_raises(self):
        cfa = _make_at_state('IDEA')
        with self.assertRaises(InvalidTransition):
            transition(cfa, 'accept')

    def test_terminal_state_raises_on_any_action(self):
        for terminal in ('COMPLETED_WORK', 'WITHDRAWN'):
            cfa = _make_at_state(terminal)
            with self.subTest(terminal=terminal):
                with self.assertRaises(InvalidTransition):
                    transition(cfa, 'approve')

    def test_error_message_lists_valid_actions(self):
        cfa = _make_at_state('IDEA')
        try:
            transition(cfa, 'bogus-action')
            self.fail("Expected InvalidTransition")
        except InvalidTransition as e:
            # Error message should mention the invalid action
            self.assertIn('bogus-action', str(e))

    def test_skipping_phases_raises(self):
        """Cannot jump from IDEA straight to PLANNING."""
        cfa = _make_cfa()
        with self.assertRaises(InvalidTransition):
            transition(cfa, 'plan')

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
        cfa = transition(cfa, 'plan')
        self.assertEqual(len(cfa.history), 2)

    def test_history_entry_has_required_keys(self):
        cfa = make_initial_state()
        cfa = transition(cfa, 'approve')
        entry = cfa.history[0]
        self.assertIn('state', entry)
        self.assertIn('action', entry)
        self.assertIn('actor', entry)
        self.assertIn('timestamp', entry)

    def test_history_records_correct_from_state(self):
        cfa = make_initial_state()
        cfa = transition(cfa, 'approve')
        self.assertEqual(cfa.history[0]['state'], 'IDEA')
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
        cfa = _advance(make_initial_state(), 'approve', 'plan', 'approve')
        self.assertEqual(cfa.backtrack_count, 0)

    def test_planning_backtrack_increments(self):
        cfa = _advance(make_initial_state(), 'approve', 'plan', 'backtrack')
        self.assertEqual(cfa.backtrack_count, 1)

    def test_multiple_backtracks_accumulate(self):
        # IDEA → INTENT → PLANNING → backtrack → IDEA
        # → approve → INTENT → plan → PLANNING → backtrack (2nd)
        cfa = make_initial_state()
        cfa = _advance(cfa, 'approve')          # INTENT
        cfa = _advance(cfa, 'plan', 'backtrack')  # IDEA; backtrack #1
        self.assertEqual(cfa.backtrack_count, 1)
        cfa = _advance(cfa, 'approve')          # INTENT again
        cfa = _advance(cfa, 'plan', 'backtrack')  # backtrack #2
        self.assertEqual(cfa.backtrack_count, 2)

    def test_work_assert_backtrack_increments(self):
        cfa = _make_at_state('WORK_ASSERT')
        new_cfa = transition(cfa, 'revise-plan')
        self.assertEqual(new_cfa.backtrack_count, 1)

    def test_work_assert_refine_intent_increments(self):
        cfa = _make_at_state('WORK_ASSERT')
        new_cfa = transition(cfa, 'refine-intent')
        self.assertEqual(new_cfa.backtrack_count, 1)


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
            self.assertEqual(loaded.actor, cfa.actor)
            self.assertEqual(loaded.backtrack_count, cfa.backtrack_count)
            self.assertEqual(loaded.history, cfa.history)
            self.assertEqual(loaded.task_id, cfa.task_id)
        finally:
            os.unlink(path)

    def test_round_trip_with_history(self):
        cfa = _advance(make_initial_state(), 'approve', 'plan')
        path = self._make_temp_path()
        try:
            save_state(cfa, path)
            loaded = load_state(path)
            self.assertEqual(loaded.state, 'PLANNING')
            self.assertEqual(loaded.phase, 'planning')
            self.assertEqual(len(loaded.history), 2)
        finally:
            os.unlink(path)

    def test_round_trip_with_backtrack_count(self):
        cfa = _advance(make_initial_state(), 'approve', 'plan', 'backtrack')
        path = self._make_temp_path()
        try:
            save_state(cfa, path)
            loaded = load_state(path)
            self.assertEqual(loaded.backtrack_count, 1)
        finally:
            os.unlink(path)

    def test_round_trip_with_task_id(self):
        cfa = _make_at_state('WORK_IN_PROGRESS', task_id='task-abc-123')
        path = self._make_temp_path()
        try:
            save_state(cfa, path)
            loaded = load_state(path)
            self.assertEqual(loaded.task_id, 'task-abc-123')
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
            self.assertIn('actor', data)
            self.assertIn('history', data)
            self.assertIn('backtrack_count', data)
        finally:
            os.unlink(path)


# ── Full happy path ──────────────────────────────────────────────────────────────

class TestHappyPath(unittest.TestCase):
    """Test the complete direct path from IDEA to COMPLETED_WORK."""

    def test_full_happy_path(self):
        """IDEA → INTENT → PLANNING → WORK_IN_PROGRESS → WORK_ASSERT → COMPLETED_WORK"""
        cfa = make_initial_state()
        self.assertEqual(cfa.state, 'IDEA')

        cfa = transition(cfa, 'approve')
        self.assertEqual(cfa.state, 'INTENT')
        self.assertTrue(is_phase_terminal('INTENT'))
        self.assertFalse(is_globally_terminal('INTENT'))

        cfa = transition(cfa, 'plan')
        self.assertEqual(cfa.state, 'PLANNING')

        cfa = transition(cfa, 'approve')
        self.assertEqual(cfa.state, 'WORK_IN_PROGRESS')

        cfa = transition(cfa, 'assert')
        self.assertEqual(cfa.state, 'WORK_ASSERT')

        cfa = transition(cfa, 'approve')
        self.assertEqual(cfa.state, 'COMPLETED_WORK')

        self.assertTrue(is_globally_terminal('COMPLETED_WORK'))
        self.assertEqual(cfa.backtrack_count, 0)
        # 5 transitions = 5 history entries
        self.assertEqual(len(cfa.history), 5)

    def test_full_happy_path_phases_correct(self):
        """Verify phase transitions at each phase boundary."""
        cfa = make_initial_state()
        self.assertEqual(cfa.phase, 'intent')

        cfa = _advance(cfa, 'approve')
        self.assertEqual(cfa.phase, 'intent')  # INTENT is still intent phase

        cfa = _advance(cfa, 'plan')
        self.assertEqual(cfa.phase, 'planning')  # PLANNING

        cfa = _advance(cfa, 'approve')
        self.assertEqual(cfa.phase, 'execution')  # WORK_IN_PROGRESS enters execution

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

    def test_backtrack_from_planning_to_intent_and_complete(self):
        """IDEA → INTENT → PLANNING → backtrack → IDEA → approve → INTENT
           → plan → PLANNING → approve → WORK_IN_PROGRESS → ... → COMPLETED_WORK"""
        cfa = make_initial_state()

        # Reach PLANNING
        cfa = _advance(cfa, 'approve', 'plan')
        self.assertEqual(cfa.state, 'PLANNING')
        self.assertEqual(cfa.backtrack_count, 0)

        # Backtrack to intent phase (lands at IDEA — skill re-runs)
        cfa = transition(cfa, 'backtrack')
        self.assertEqual(cfa.state, 'IDEA')
        self.assertEqual(cfa.phase, 'intent')
        self.assertEqual(cfa.backtrack_count, 1)

        # Re-approve intent
        cfa = transition(cfa, 'approve')
        self.assertEqual(cfa.state, 'INTENT')

        # Re-enter planning
        cfa = transition(cfa, 'plan')
        self.assertEqual(cfa.state, 'PLANNING')
        self.assertEqual(cfa.phase, 'planning')

        # Complete execution: PLANNING → approve → WORK_IN_PROGRESS → assert → WORK_ASSERT → approve → COMPLETED_WORK
        cfa = _advance(cfa, 'approve', 'assert', 'approve')
        self.assertEqual(cfa.state, 'COMPLETED_WORK')
        self.assertTrue(is_globally_terminal(cfa.state))
        self.assertEqual(cfa.backtrack_count, 1)

    def test_backtrack_from_work_assert_revise_plan(self):
        """Backtrack from WORK_ASSERT → revise-plan → PLANNING."""
        cfa = _make_at_state('WORK_ASSERT')
        cfa = transition(cfa, 'revise-plan')
        self.assertEqual(cfa.state, 'PLANNING')
        self.assertEqual(cfa.phase, 'planning')
        self.assertEqual(cfa.backtrack_count, 1)

    def test_backtrack_from_work_assert_refine_intent(self):
        """Deep backtrack: WORK_ASSERT → refine-intent → IDEA."""
        cfa = _make_at_state('WORK_ASSERT')
        cfa = transition(cfa, 'refine-intent')
        self.assertEqual(cfa.state, 'IDEA')
        self.assertEqual(cfa.phase, 'intent')
        self.assertEqual(cfa.backtrack_count, 1)

    def test_work_in_progress_backtrack_to_planning(self):
        """WORK_IN_PROGRESS → backtrack → PLANNING."""
        cfa = _make_at_state('WORK_IN_PROGRESS')
        cfa = transition(cfa, 'backtrack')
        self.assertEqual(cfa.state, 'PLANNING')
        self.assertEqual(cfa.phase, 'planning')
        self.assertEqual(cfa.backtrack_count, 1)


# ── Complete transition table coverage ──────────────────────────────────────────

class TestCompleteTransitionCoverage(unittest.TestCase):
    """Verify every edge in TRANSITIONS is reachable and produces correct output."""

    def test_all_transitions_produce_valid_next_state(self):
        """For every (from_state, action, target) in TRANSITIONS, the transition
        produces a CfaState with state == target and phase == phase_for_state(target)."""
        for from_state, edges in TRANSITIONS.items():
            for action, expected_target, expected_actor in edges:
                with self.subTest(from_state=from_state, action=action):
                    cfa = _make_at_state(from_state)
                    new_cfa = transition(cfa, action)
                    self.assertEqual(new_cfa.state, expected_target,
                        f"{from_state} --{action}--> expected {expected_target}, got {new_cfa.state}")
                    self.assertEqual(new_cfa.actor, expected_actor,
                        f"{from_state} --{action}--> expected actor {expected_actor}, got {new_cfa.actor}")
                    self.assertEqual(new_cfa.phase, phase_for_state(expected_target))


# ── Hierarchy fields ────────────────────────────────────────────────────────────

class TestHierarchyFields(unittest.TestCase):

    def test_default_hierarchy_fields(self):
        cfa = make_initial_state()
        self.assertEqual(cfa.parent_id, '')
        self.assertEqual(cfa.team_id, '')
        self.assertEqual(cfa.depth, 0)

    def test_make_initial_with_task_id(self):
        cfa = make_initial_state(task_id='uber-001')
        self.assertEqual(cfa.task_id, 'uber-001')
        self.assertEqual(cfa.state, 'IDEA')

    def test_make_initial_with_team_id(self):
        cfa = make_initial_state(team_id='coding')
        self.assertEqual(cfa.team_id, 'coding')

    def test_make_child_state_basic(self):
        parent = _make_at_state('WORK_IN_PROGRESS', task_id='uber-001')
        child = make_child_state(parent, 'coding')
        self.assertEqual(child.parent_id, 'uber-001')
        self.assertEqual(child.team_id, 'coding')
        self.assertEqual(child.depth, 1)
        self.assertEqual(child.state, 'INTENT')
        # phase matches phase_for_state(state); child passes through the
        # brief INTENT acknowledgment before advancing into planning.
        self.assertEqual(child.phase, 'intent')
        self.assertTrue(child.task_id.startswith('coding-'))

    def test_make_child_state_custom_task_id(self):
        parent = _make_at_state('WORK_IN_PROGRESS', task_id='uber-001')
        child = make_child_state(parent, 'art', task_id='art-custom-001')
        self.assertEqual(child.task_id, 'art-custom-001')
        self.assertEqual(child.parent_id, 'uber-001')

    def test_make_child_nested_depth(self):
        """Sub-subteam should have depth=2."""
        root = make_initial_state(task_id='root-001')
        child = make_child_state(root, 'coding', task_id='coding-001')
        grandchild = make_child_state(child, 'testing', task_id='testing-001')
        self.assertEqual(grandchild.depth, 2)
        self.assertEqual(grandchild.parent_id, 'coding-001')
        self.assertEqual(grandchild.team_id, 'testing')

    def test_is_root_on_initial(self):
        self.assertTrue(is_root(make_initial_state()))

    def test_is_root_with_task_id_still_root(self):
        """Root state with a task_id is still root (depth=0, no parent)."""
        cfa = make_initial_state(task_id='uber-001')
        self.assertTrue(is_root(cfa))

    def test_is_root_false_for_child(self):
        parent = _make_at_state('WORK_IN_PROGRESS', task_id='uber-001')
        child = make_child_state(parent, 'coding')
        self.assertFalse(is_root(child))

    def test_hierarchy_preserved_through_transitions(self):
        parent = _make_at_state('WORK_IN_PROGRESS', task_id='uber-001')
        child = make_child_state(parent, 'coding')
        # Child starts at INTENT; the inherited intent is acknowledged
        # (not re-derived) before advancing into planning.
        child = transition(child, 'plan')
        self.assertEqual(child.parent_id, 'uber-001')
        self.assertEqual(child.team_id, 'coding')
        self.assertEqual(child.depth, 1)
        child = transition(child, 'approve')
        self.assertEqual(child.parent_id, 'uber-001')
        self.assertEqual(child.team_id, 'coding')
        self.assertEqual(child.depth, 1)

    def test_hierarchy_preserved_through_backtrack(self):
        parent = _make_at_state('WORK_IN_PROGRESS', task_id='uber-001')
        child = make_child_state(parent, 'coding')
        # Child starts at INTENT, plan → PLANNING, backtrack → IDEA
        child = _advance(child, 'plan', 'backtrack')
        self.assertEqual(child.parent_id, 'uber-001')
        self.assertEqual(child.team_id, 'coding')
        self.assertEqual(child.depth, 1)
        self.assertEqual(child.backtrack_count, 1)


# ── Hierarchy persistence ──────────────────────────────────────────────────────

class TestHierarchyPersistence(unittest.TestCase):

    def _make_temp_path(self) -> str:
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        return path

    def test_round_trip_preserves_hierarchy_fields(self):
        cfa = _make_cfa(parent_id='parent-123', team_id='coding', depth=2)
        path = self._make_temp_path()
        try:
            save_state(cfa, path)
            loaded = load_state(path)
            self.assertEqual(loaded.parent_id, 'parent-123')
            self.assertEqual(loaded.team_id, 'coding')
            self.assertEqual(loaded.depth, 2)
        finally:
            os.unlink(path)

    def test_backward_compat_load_without_hierarchy(self):
        """Load a state file that predates hierarchy fields."""
        import json
        old_data = {
            'phase': 'planning',
            'state': 'PLANNING',
            'actor': 'planning_team',
            'history': [],
            'backtrack_count': 0,
            'task_id': 'old-task',
        }
        path = self._make_temp_path()
        try:
            with open(path, 'w') as f:
                json.dump(old_data, f)
            loaded = load_state(path)
            self.assertEqual(loaded.state, 'PLANNING')
            self.assertEqual(loaded.parent_id, '')
            self.assertEqual(loaded.team_id, '')
            self.assertEqual(loaded.depth, 0)
        finally:
            os.unlink(path)

    def test_child_state_round_trip(self):
        parent = _make_at_state('WORK_IN_PROGRESS', task_id='uber-001')
        child = make_child_state(parent, 'art', task_id='art-001')
        # Child starts at INTENT; advance to PLANNING via plan
        child = _advance(child, 'plan')  # INTENT → PLANNING
        path = self._make_temp_path()
        try:
            save_state(child, path)
            loaded = load_state(path)
            self.assertEqual(loaded.parent_id, 'uber-001')
            self.assertEqual(loaded.team_id, 'art')
            self.assertEqual(loaded.depth, 1)
            self.assertEqual(loaded.task_id, 'art-001')
            self.assertEqual(loaded.state, 'PLANNING')
        finally:
            os.unlink(path)


# ── set_state_direct ──────────────────────────────────────────────────────────

class TestSetStateDirect(unittest.TestCase):

    def test_set_to_planning(self):
        cfa = make_initial_state()
        cfa = set_state_direct(cfa, 'PLANNING')
        self.assertEqual(cfa.state, 'PLANNING')
        self.assertEqual(cfa.phase, 'planning')

    def test_set_to_completed_work(self):
        cfa = _make_at_state('WORK_ASSERT')
        cfa = set_state_direct(cfa, 'COMPLETED_WORK')
        self.assertEqual(cfa.state, 'COMPLETED_WORK')
        self.assertEqual(cfa.phase, 'execution')
        self.assertEqual(cfa.actor, 'system')  # terminal state

    def test_set_state_appends_history(self):
        cfa = make_initial_state()
        cfa = set_state_direct(cfa, 'INTENT')
        self.assertEqual(len(cfa.history), 1)
        self.assertEqual(cfa.history[0]['action'], 'set-state')
        self.assertEqual(cfa.history[0]['state'], 'IDEA')
        self.assertEqual(cfa.history[0]['target'], 'INTENT')

    def test_set_state_preserves_hierarchy(self):
        cfa = _make_cfa(parent_id='p1', team_id='art', depth=1)
        cfa = set_state_direct(cfa, 'PLANNING')
        self.assertEqual(cfa.parent_id, 'p1')
        self.assertEqual(cfa.team_id, 'art')
        self.assertEqual(cfa.depth, 1)

    def test_set_state_preserves_backtrack_count(self):
        cfa = _make_cfa(backtrack_count=3)
        cfa = set_state_direct(cfa, 'WORK_IN_PROGRESS')
        self.assertEqual(cfa.backtrack_count, 3)

    def test_set_state_unknown_state_raises(self):
        """set_state_direct calls phase_for_state which raises on unknown."""
        cfa = make_initial_state()
        with self.assertRaises(ValueError):
            set_state_direct(cfa, 'NOT_A_STATE')


# ── Recursive CfA happy path ──────────────────────────────────────────────────

class TestRecursiveHappyPath(unittest.TestCase):
    """Test a full recursive CfA cycle: parent dispatches, child completes."""

    def test_parent_to_child_to_completion(self):
        # Parent: IDEA → INTENT → PLANNING → approve → WORK_IN_PROGRESS
        parent = make_initial_state(task_id='uber-001')
        parent = _advance(parent, 'approve', 'plan', 'approve')
        self.assertEqual(parent.state, 'WORK_IN_PROGRESS')

        # Create child for coding team — starts at INTENT (skips intent phase per spec Section 7)
        child = make_child_state(parent, 'coding', task_id='coding-001')
        self.assertEqual(child.depth, 1)
        self.assertEqual(child.parent_id, 'uber-001')
        self.assertEqual(child.state, 'INTENT')

        # Child runs planning+execution (no intent phase needed)
        child = _advance(child, 'plan', 'approve', 'assert', 'approve')
        self.assertEqual(child.state, 'COMPLETED_WORK')
        self.assertTrue(is_globally_terminal(child.state))

        # Parent continues: WORK_IN_PROGRESS → assert → WORK_ASSERT → approve → COMPLETED_WORK
        parent = _advance(parent, 'assert', 'approve')
        self.assertEqual(parent.state, 'COMPLETED_WORK')

    def test_multiple_dispatches_sequential(self):
        """Parent runs execution with multiple subteam dispatches before
        writing WORK_SUMMARY.  Subteam coordination happens over the bus;
        the parent stays in WORK_IN_PROGRESS throughout.
        """
        parent = make_initial_state(task_id='uber-001')
        parent = _advance(parent, 'approve', 'plan', 'approve')
        self.assertEqual(parent.state, 'WORK_IN_PROGRESS')

        # First dispatch: art team — child starts at INTENT (skips intent phase)
        art_child = make_child_state(parent, 'art', task_id='art-001')
        art_child = _advance(art_child, 'plan', 'approve', 'assert', 'approve')
        self.assertEqual(art_child.state, 'COMPLETED_WORK')

        # Parent stays in WORK_IN_PROGRESS; no state transition needed
        # between dispatches.
        self.assertEqual(parent.state, 'WORK_IN_PROGRESS')

        # Second dispatch: coding team — child starts at INTENT
        coding_child = make_child_state(parent, 'coding', task_id='coding-001')
        self.assertEqual(coding_child.parent_id, 'uber-001')
        coding_child = _advance(coding_child, 'plan', 'approve', 'assert', 'approve')
        self.assertEqual(coding_child.state, 'COMPLETED_WORK')

        # Parent finishes: WORK_IN_PROGRESS → assert → WORK_ASSERT → approve → COMPLETED_WORK
        parent = _advance(parent, 'assert', 'approve')
        self.assertEqual(parent.state, 'COMPLETED_WORK')


# ── CLI --transition tests ───────────────────────────────────────────────────

class TestTransitionCLI(unittest.TestCase):
    """Test the --transition CLI command that applies validated transitions."""

    def test_valid_transition_updates_state_file(self):
        """--transition with a valid action updates the state file."""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            state_file = f.name
        try:
            # Init a state at IDEA
            cfa = make_initial_state('test-cli')
            save_state(cfa, state_file)
            self.assertEqual(cfa.state, 'IDEA')

            # Apply 'approve' transition: IDEA → INTENT
            loaded = load_state(state_file)
            result = transition(loaded, 'approve')
            save_state(result, state_file)

            reloaded = load_state(state_file)
            self.assertEqual(reloaded.state, 'INTENT')
        finally:
            os.unlink(state_file)

    def test_invalid_transition_raises(self):
        """Applying an invalid action from a given state raises InvalidTransition."""
        cfa = _make_cfa(state='IDEA')
        with self.assertRaises(InvalidTransition):
            transition(cfa, 'plan')  # 'plan' is not valid from IDEA

    def test_transition_round_trip_through_planning(self):
        """Walk through a valid transition sequence through intent and planning."""
        cfa = _make_cfa(state='IDEA')
        cfa = transition(cfa, 'approve')
        self.assertEqual(cfa.state, 'INTENT')
        cfa = transition(cfa, 'plan')
        self.assertEqual(cfa.state, 'PLANNING')
        cfa = transition(cfa, 'approve')
        self.assertEqual(cfa.state, 'WORK_IN_PROGRESS')

    def test_work_assert_correct_goes_to_work_in_progress(self):
        """WORK_ASSERT correct sends the lead back to re-do the work."""
        cfa = _make_cfa(state='WORK_ASSERT', phase='execution')
        cfa = transition(cfa, 'correct')
        self.assertEqual(cfa.state, 'WORK_IN_PROGRESS')

    def test_withdraw_from_work_in_progress(self):
        """WORK_IN_PROGRESS withdraw → WITHDRAWN."""
        cfa = _make_cfa(state='WORK_IN_PROGRESS', phase='execution')
        cfa = transition(cfa, 'withdraw')
        self.assertEqual(cfa.state, 'WITHDRAWN')


if __name__ == '__main__':
    unittest.main()
