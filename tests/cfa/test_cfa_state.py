#!/usr/bin/env python3
"""Tests for cfa_state.py — Conversation for Action state machine.

Five-state model: INTENT, PLAN, EXECUTE, DONE, WITHDRAWN.
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

    Defaults to the initial INTENT state. Callers can override any field.
    """
    defaults = dict(
        phase='intent',
        state='INTENT',
        actor='intent_team',
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
    # Determine a plausible actor for the state (use any valid next actor or 'system')
    actions = available_actions(state)
    actor = actions[0][1] if actions else 'system'
    return _make_cfa(phase=phase, state=state, actor=actor, **kwargs)


# ── make_initial_state ──────────────────────────────────────────────────────────

class TestMakeInitialState(unittest.TestCase):

    def test_initial_state_is_intent(self):
        cfa = make_initial_state()
        self.assertEqual(cfa.state, 'INTENT')

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
        self.assertEqual(phase_for_state('INTENT'), 'intent')
        self.assertEqual(phase_for_state('PLAN'), 'planning')
        self.assertEqual(phase_for_state('EXECUTE'), 'execution')
        self.assertEqual(phase_for_state('DONE'), 'execution')
        self.assertEqual(phase_for_state('WITHDRAWN'), 'execution')


# ── available_actions ───────────────────────────────────────────────────────────

class TestAvailableActions(unittest.TestCase):

    def test_intent_actions(self):
        actions = dict(available_actions('INTENT'))
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


# ── is_phase_terminal ───────────────────────────────────────────────────────────

class TestIsPhaseTerminal(unittest.TestCase):

    def test_done_is_phase_terminal(self):
        self.assertTrue(is_phase_terminal('DONE'))

    def test_withdrawn_is_phase_terminal(self):
        self.assertTrue(is_phase_terminal('WITHDRAWN'))

    def test_working_states_are_not_phase_terminal(self):
        # In the five-state model, only globally terminal states are phase-terminal.
        for state in ('INTENT', 'PLAN', 'EXECUTE'):
            with self.subTest(state=state):
                self.assertFalse(is_phase_terminal(state))


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


# ── transition — Phase 1: Intent Alignment ──────────────────────────────────────

class TestTransitionPhase1(unittest.TestCase):

    def test_intent_approve_to_plan(self):
        cfa = _make_cfa()
        new_cfa = transition(cfa, 'approve')
        self.assertEqual(new_cfa.state, 'PLAN')
        self.assertEqual(new_cfa.phase, 'planning')
        # actor reflects who performed the INTENT→PLAN approve
        self.assertEqual(new_cfa.actor, 'intent_team')

    def test_intent_withdraw_to_withdrawn(self):
        cfa = _make_cfa()
        new_cfa = transition(cfa, 'withdraw')
        self.assertEqual(new_cfa.state, 'WITHDRAWN')
        self.assertEqual(new_cfa.phase, 'execution')


# ── transition — Phase 2: Planning ──────────────────────────────────────────────

class TestTransitionPhase2(unittest.TestCase):

    def test_plan_approve_to_execute(self):
        cfa = _make_at_state('PLAN')
        new_cfa = transition(cfa, 'approve')
        self.assertEqual(new_cfa.state, 'EXECUTE')
        self.assertEqual(new_cfa.phase, 'execution')
        # actor reflects who performed the PLAN→EXECUTE approve
        self.assertEqual(new_cfa.actor, 'planning_team')

    def test_plan_realign_to_intent(self):
        cfa = _make_at_state('PLAN')
        new_cfa = transition(cfa, 'realign')
        self.assertEqual(new_cfa.state, 'INTENT')
        self.assertEqual(new_cfa.phase, 'intent')

    def test_plan_withdraw_to_withdrawn(self):
        cfa = _make_at_state('PLAN')
        new_cfa = transition(cfa, 'withdraw')
        self.assertEqual(new_cfa.state, 'WITHDRAWN')


# ── transition — Phase 3: Execution ─────────────────────────────────────────────

class TestTransitionPhase3(unittest.TestCase):

    def test_execute_approve_to_done(self):
        cfa = _make_at_state('EXECUTE')
        new_cfa = transition(cfa, 'approve')
        self.assertEqual(new_cfa.state, 'DONE')
        self.assertEqual(new_cfa.phase, 'execution')

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
        self.assertIn('actor', entry)
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
        self.assertEqual(cfa.state, 'INTENT')

    def test_make_initial_with_team_id(self):
        cfa = make_initial_state(team_id='coding')
        self.assertEqual(cfa.team_id, 'coding')

    def test_make_child_state_basic(self):
        parent = _make_at_state('EXECUTE', task_id='uber-001')
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
        parent = _make_at_state('EXECUTE', task_id='uber-001')
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
        parent = _make_at_state('EXECUTE', task_id='uber-001')
        child = make_child_state(parent, 'coding')
        self.assertFalse(is_root(child))

    def test_hierarchy_preserved_through_transitions(self):
        parent = _make_at_state('EXECUTE', task_id='uber-001')
        child = make_child_state(parent, 'coding')
        # Child starts at INTENT; advance through approve → PLAN → EXECUTE.
        child = transition(child, 'approve')
        self.assertEqual(child.parent_id, 'uber-001')
        self.assertEqual(child.team_id, 'coding')
        self.assertEqual(child.depth, 1)
        child = transition(child, 'approve')
        self.assertEqual(child.parent_id, 'uber-001')
        self.assertEqual(child.team_id, 'coding')
        self.assertEqual(child.depth, 1)

    def test_hierarchy_preserved_through_backtrack(self):
        parent = _make_at_state('EXECUTE', task_id='uber-001')
        child = make_child_state(parent, 'coding')
        # Child starts at INTENT, approve → PLAN, realign → INTENT
        child = _advance(child, 'approve', 'realign')
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
            'state': 'PLAN',
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
            self.assertEqual(loaded.state, 'PLAN')
            self.assertEqual(loaded.parent_id, '')
            self.assertEqual(loaded.team_id, '')
            self.assertEqual(loaded.depth, 0)
        finally:
            os.unlink(path)

    def test_child_state_round_trip(self):
        parent = _make_at_state('EXECUTE', task_id='uber-001')
        child = make_child_state(parent, 'art', task_id='art-001')
        # Child starts at INTENT; advance to PLAN via approve
        child = _advance(child, 'approve')  # INTENT → PLAN
        path = self._make_temp_path()
        try:
            save_state(child, path)
            loaded = load_state(path)
            self.assertEqual(loaded.parent_id, 'uber-001')
            self.assertEqual(loaded.team_id, 'art')
            self.assertEqual(loaded.depth, 1)
            self.assertEqual(loaded.task_id, 'art-001')
            self.assertEqual(loaded.state, 'PLAN')
        finally:
            os.unlink(path)


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
        self.assertEqual(cfa.phase, 'execution')
        self.assertEqual(cfa.actor, 'system')  # terminal state

    def test_set_state_appends_history(self):
        cfa = make_initial_state()
        cfa = set_state_direct(cfa, 'PLAN')
        self.assertEqual(len(cfa.history), 1)
        self.assertEqual(cfa.history[0]['action'], 'set-state')
        self.assertEqual(cfa.history[0]['state'], 'INTENT')
        self.assertEqual(cfa.history[0]['target'], 'PLAN')

    def test_set_state_preserves_hierarchy(self):
        cfa = _make_cfa(parent_id='p1', team_id='art', depth=1)
        cfa = set_state_direct(cfa, 'PLAN')
        self.assertEqual(cfa.parent_id, 'p1')
        self.assertEqual(cfa.team_id, 'art')
        self.assertEqual(cfa.depth, 1)

    def test_set_state_preserves_backtrack_count(self):
        cfa = _make_cfa(backtrack_count=3)
        cfa = set_state_direct(cfa, 'EXECUTE')
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
        # Parent: INTENT → PLAN → EXECUTE
        parent = make_initial_state(task_id='uber-001')
        parent = _advance(parent, 'approve', 'approve')
        self.assertEqual(parent.state, 'EXECUTE')

        # Create child for coding team — starts at INTENT
        child = make_child_state(parent, 'coding', task_id='coding-001')
        self.assertEqual(child.depth, 1)
        self.assertEqual(child.parent_id, 'uber-001')
        self.assertEqual(child.state, 'INTENT')

        # Child runs the full cycle
        child = _advance(child, 'approve', 'approve', 'approve')
        self.assertEqual(child.state, 'DONE')
        self.assertTrue(is_globally_terminal(child.state))

        # Parent continues: EXECUTE → approve → DONE
        parent = _advance(parent, 'approve')
        self.assertEqual(parent.state, 'DONE')

    def test_multiple_dispatches_sequential(self):
        """Parent runs execution with multiple subteam dispatches.
        Subteam coordination happens over the bus; the parent stays in
        EXECUTE throughout.
        """
        parent = make_initial_state(task_id='uber-001')
        parent = _advance(parent, 'approve', 'approve')
        self.assertEqual(parent.state, 'EXECUTE')

        # First dispatch: art team
        art_child = make_child_state(parent, 'art', task_id='art-001')
        art_child = _advance(art_child, 'approve', 'approve', 'approve')
        self.assertEqual(art_child.state, 'DONE')

        # Parent stays in EXECUTE between dispatches
        self.assertEqual(parent.state, 'EXECUTE')

        # Second dispatch: coding team
        coding_child = make_child_state(parent, 'coding', task_id='coding-001')
        self.assertEqual(coding_child.parent_id, 'uber-001')
        coding_child = _advance(coding_child, 'approve', 'approve', 'approve')
        self.assertEqual(coding_child.state, 'DONE')

        # Parent finishes: EXECUTE → approve → DONE
        parent = _advance(parent, 'approve')
        self.assertEqual(parent.state, 'DONE')


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
