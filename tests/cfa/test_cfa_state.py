#!/usr/bin/env python3
"""Tests for cfa_state.py — flat 5-state CfA.

States: INTENT, PLAN, EXECUTE, DONE, WITHDRAWN.  No phase concept;
state IS the unit of dispatch.  Routing is response-driven via the
``Action`` enum + ``ACTION_TO_STATE`` map.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from teaparty.cfa.statemachine.cfa_state import (
    ACTION_TO_STATE,
    Action,
    CfaState,
    State,
    TERMINAL_STATES,
    apply_response,
    is_globally_terminal,
    load_state,
    make_initial_state,
    save_state,
    set_state_direct,
)


class TestEnumsAreStrings(unittest.TestCase):
    """StrEnum members compare equal to their literal string values."""

    def test_state_is_string(self):
        self.assertEqual(State.INTENT, 'INTENT')
        self.assertEqual(State.WITHDRAWN, 'WITHDRAWN')

    def test_action_is_string(self):
        self.assertEqual(Action.APPROVED_INTENT, 'APPROVED_INTENT')
        self.assertEqual(Action.WITHDRAW, 'WITHDRAW')


class TestMakeInitialState(unittest.TestCase):

    def test_initial_state_is_intent(self):
        cfa = make_initial_state()
        self.assertEqual(cfa.state, State.INTENT)

    def test_initial_history_is_empty(self):
        cfa = make_initial_state()
        self.assertEqual(cfa.history, [])

    def test_initial_backtrack_count_is_zero(self):
        cfa = make_initial_state()
        self.assertEqual(cfa.backtrack_count, 0)

    def test_task_id_passed_through(self):
        cfa = make_initial_state(task_id='job-42')
        self.assertEqual(cfa.task_id, 'job-42')


class TestSetStateDirect(unittest.TestCase):

    def test_lands_in_target_state(self):
        cfa = set_state_direct(make_initial_state(), State.PLAN)
        self.assertEqual(cfa.state, State.PLAN)

    def test_does_not_increment_backtrack(self):
        cfa = make_initial_state()
        cfa = set_state_direct(cfa, State.PLAN)
        cfa = set_state_direct(cfa, State.INTENT)
        self.assertEqual(cfa.backtrack_count, 0)

    def test_history_records_set_state(self):
        cfa = set_state_direct(make_initial_state(), State.PLAN)
        self.assertEqual(cfa.history[-1]['action'], 'set-state')
        self.assertEqual(cfa.history[-1]['target'], State.PLAN)


class TestApplyResponse(unittest.TestCase):
    """``apply_response`` is the only state-machine update path the
    engine uses — forward moves don't touch backtrack_count, backward
    moves to earlier working states do."""

    def test_forward_move_does_not_increment_backtrack(self):
        cfa = apply_response(make_initial_state(), State.PLAN)
        self.assertEqual(cfa.state, State.PLAN)
        self.assertEqual(cfa.backtrack_count, 0)

    def test_backward_move_increments_backtrack(self):
        cfa = make_initial_state()
        cfa = apply_response(cfa, State.PLAN)
        cfa = apply_response(cfa, State.EXECUTE)
        cfa = apply_response(cfa, State.INTENT)  # backtrack
        self.assertEqual(cfa.backtrack_count, 1)

    def test_terminal_move_does_not_increment_backtrack(self):
        cfa = apply_response(make_initial_state(), State.PLAN)
        cfa = apply_response(cfa, State.WITHDRAWN)
        self.assertEqual(cfa.backtrack_count, 0)


class TestActionToState(unittest.TestCase):
    """Every action except PENDING maps to a state.
    PENDING is the no-outcome sentinel and intentionally has no
    target state."""

    def test_every_action_maps_except_pending(self):
        for action in Action:
            if action == Action.PENDING:
                continue
            self.assertIn(action, ACTION_TO_STATE)

    def test_pending_does_not_map(self):
        self.assertNotIn(Action.PENDING, ACTION_TO_STATE)

    def test_failure_maps_to_failure_state(self):
        self.assertEqual(ACTION_TO_STATE[Action.FAILURE], State.FAILURE)


class TestIsGloballyTerminal(unittest.TestCase):

    def test_done_is_terminal(self):
        self.assertTrue(is_globally_terminal(State.DONE))

    def test_withdrawn_is_terminal(self):
        self.assertTrue(is_globally_terminal(State.WITHDRAWN))

    def test_failure_is_terminal(self):
        self.assertTrue(is_globally_terminal(State.FAILURE))

    def test_working_states_are_not_terminal(self):
        for s in (State.INTENT, State.PLAN, State.EXECUTE):
            self.assertFalse(is_globally_terminal(s))

    def test_terminal_states_set(self):
        self.assertEqual(
            TERMINAL_STATES,
            frozenset({State.DONE, State.WITHDRAWN, State.FAILURE}),
        )


class TestPersistence(unittest.TestCase):

    def test_save_load_roundtrip(self):
        cfa = apply_response(make_initial_state(task_id='t'), State.PLAN)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, '.cfa-state.json')
            save_state(cfa, path)
            loaded = load_state(path)
        self.assertEqual(loaded.state, cfa.state)
        self.assertEqual(loaded.task_id, cfa.task_id)
        self.assertEqual(loaded.history, cfa.history)


if __name__ == '__main__':
    unittest.main()
