#!/usr/bin/env python3
"""Tests for cfa_state.py — Conversation for Action state machine."""
import sys
import tempfile
import os
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from cfa_state import (
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

    def test_initial_actor_is_human(self):
        cfa = make_initial_state()
        self.assertEqual(cfa.actor, 'human')

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
        self.assertEqual(phase_for_state('DRAFT'), 'planning')
        self.assertEqual(phase_for_state('PLAN'), 'planning')
        self.assertEqual(phase_for_state('TASK'), 'execution')
        self.assertEqual(phase_for_state('COMPLETED_WORK'), 'execution')
        self.assertEqual(phase_for_state('WITHDRAWN'), 'execution')


# ── available_actions ───────────────────────────────────────────────────────────

class TestAvailableActions(unittest.TestCase):

    def test_idea_has_propose(self):
        actions = dict(available_actions('IDEA'))
        self.assertIn('propose', actions)
        self.assertEqual(actions['propose'], 'human')

    def test_proposal_actions(self):
        actions = dict(available_actions('PROPOSAL'))
        self.assertIn('question', actions)
        self.assertIn('escalate', actions)
        self.assertIn('assert', actions)
        self.assertIn('auto-approve', actions)
        self.assertIn('withdraw', actions)
        self.assertEqual(actions['withdraw'], 'human')

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

    def test_plan_is_phase_terminal(self):
        self.assertTrue(is_phase_terminal('PLAN'))

    def test_completed_work_is_phase_terminal(self):
        self.assertTrue(is_phase_terminal('COMPLETED_WORK'))

    def test_withdrawn_is_phase_terminal(self):
        self.assertTrue(is_phase_terminal('WITHDRAWN'))

    def test_mid_states_are_not_phase_terminal(self):
        non_terminal = ['IDEA', 'PROPOSAL', 'DRAFT', 'TASK', 'TASK_IN_PROGRESS',
                        'INTENT_QUESTION', 'PLANNING_QUESTION', 'WORK_IN_PROGRESS']
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

    def test_plan_is_not_globally_terminal(self):
        self.assertFalse(is_globally_terminal('PLAN'))

    def test_mid_states_are_not_globally_terminal(self):
        for state in ['IDEA', 'PROPOSAL', 'DRAFT', 'TASK', 'TASK_IN_PROGRESS']:
            with self.subTest(state=state):
                self.assertFalse(is_globally_terminal(state))


# ── is_backtrack ────────────────────────────────────────────────────────────────

class TestIsBacktrack(unittest.TestCase):

    def test_draft_refine_intent_is_backtrack(self):
        self.assertTrue(is_backtrack('DRAFT', 'refine-intent'))

    def test_planning_question_backtrack_is_backtrack(self):
        self.assertTrue(is_backtrack('PLANNING_QUESTION', 'backtrack'))

    def test_task_question_backtrack_is_backtrack(self):
        self.assertTrue(is_backtrack('TASK_QUESTION', 'backtrack'))

    def test_failed_task_backtrack_is_backtrack(self):
        self.assertTrue(is_backtrack('FAILED_TASK', 'backtrack'))

    def test_work_in_progress_backtrack_is_backtrack(self):
        self.assertTrue(is_backtrack('WORK_IN_PROGRESS', 'backtrack'))

    def test_work_assert_revise_plan_is_backtrack(self):
        self.assertTrue(is_backtrack('WORK_ASSERT', 'revise-plan'))

    def test_work_assert_refine_intent_is_backtrack(self):
        self.assertTrue(is_backtrack('WORK_ASSERT', 'refine-intent'))

    def test_forward_transitions_are_not_backtracks(self):
        forward_cases = [
            ('IDEA', 'propose'),
            ('PROPOSAL', 'auto-approve'),
            ('INTENT', 'plan'),
            ('DRAFT', 'auto-approve'),
            ('PLAN', 'delegate'),
            ('TASK', 'accept'),
        ]
        for from_state, action in forward_cases:
            with self.subTest(from_state=from_state, action=action):
                self.assertFalse(is_backtrack(from_state, action))

    def test_same_phase_transitions_are_not_backtracks(self):
        # PROPOSAL → withdraw → WITHDRAWN is execution-owned, but PROPOSAL is intent;
        # WITHDRAWN is execution. However this goes forward in the phase order.
        # Within-phase transitions:
        self.assertFalse(is_backtrack('INTENT_QUESTION', 'answer'))
        self.assertFalse(is_backtrack('PLANNING_QUESTION', 'answer'))
        self.assertFalse(is_backtrack('TASK_QUESTION', 'answer'))

    def test_unknown_action_returns_false(self):
        self.assertFalse(is_backtrack('DRAFT', 'nonexistent-action'))


# ── transition — Phase 1: Intent Alignment ──────────────────────────────────────

class TestTransitionPhase1(unittest.TestCase):

    def test_idea_propose_to_proposal(self):
        cfa = _make_cfa()
        new_cfa = transition(cfa, 'propose')
        self.assertEqual(new_cfa.state, 'PROPOSAL')
        self.assertEqual(new_cfa.phase, 'intent')
        # actor is set from the transition entry: propose is performed by 'human'
        self.assertEqual(new_cfa.actor, 'human')

    def test_proposal_question_to_intent_question(self):
        cfa = _make_at_state('PROPOSAL')
        new_cfa = transition(cfa, 'question')
        self.assertEqual(new_cfa.state, 'INTENT_QUESTION')
        self.assertEqual(new_cfa.actor, 'intent_team')

    def test_proposal_escalate_to_intent_escalate(self):
        cfa = _make_at_state('PROPOSAL')
        new_cfa = transition(cfa, 'escalate')
        self.assertEqual(new_cfa.state, 'INTENT_ESCALATE')

    def test_proposal_assert_to_intent_assert(self):
        cfa = _make_at_state('PROPOSAL')
        new_cfa = transition(cfa, 'assert')
        self.assertEqual(new_cfa.state, 'INTENT_ASSERT')

    def test_proposal_auto_approve_to_intent(self):
        cfa = _make_at_state('PROPOSAL')
        new_cfa = transition(cfa, 'auto-approve')
        self.assertEqual(new_cfa.state, 'INTENT')
        self.assertEqual(new_cfa.phase, 'intent')

    def test_proposal_withdraw_to_withdrawn(self):
        cfa = _make_at_state('PROPOSAL')
        new_cfa = transition(cfa, 'withdraw')
        self.assertEqual(new_cfa.state, 'WITHDRAWN')
        self.assertEqual(new_cfa.phase, 'execution')

    def test_intent_question_answer_to_intent_response(self):
        cfa = _make_at_state('INTENT_QUESTION')
        new_cfa = transition(cfa, 'answer')
        self.assertEqual(new_cfa.state, 'INTENT_RESPONSE')
        self.assertEqual(new_cfa.actor, 'research_team')

    def test_intent_escalate_clarify_to_intent_response(self):
        cfa = _make_at_state('INTENT_ESCALATE')
        new_cfa = transition(cfa, 'clarify')
        self.assertEqual(new_cfa.state, 'INTENT_RESPONSE')
        self.assertEqual(new_cfa.actor, 'human')

    def test_intent_escalate_withdraw_to_withdrawn(self):
        cfa = _make_at_state('INTENT_ESCALATE')
        new_cfa = transition(cfa, 'withdraw')
        self.assertEqual(new_cfa.state, 'WITHDRAWN')

    def test_intent_assert_approve_to_intent(self):
        cfa = _make_at_state('INTENT_ASSERT')
        new_cfa = transition(cfa, 'approve')
        self.assertEqual(new_cfa.state, 'INTENT')
        self.assertEqual(new_cfa.actor, 'human')

    def test_intent_assert_correct_to_intent_response(self):
        cfa = _make_at_state('INTENT_ASSERT')
        new_cfa = transition(cfa, 'correct')
        self.assertEqual(new_cfa.state, 'INTENT_RESPONSE')
        self.assertEqual(new_cfa.actor, 'human')

    def test_intent_assert_withdraw_to_withdrawn(self):
        cfa = _make_at_state('INTENT_ASSERT')
        new_cfa = transition(cfa, 'withdraw')
        self.assertEqual(new_cfa.state, 'WITHDRAWN')

    def test_intent_response_synthesize_to_proposal(self):
        cfa = _make_at_state('INTENT_RESPONSE')
        new_cfa = transition(cfa, 'synthesize')
        self.assertEqual(new_cfa.state, 'PROPOSAL')
        self.assertEqual(new_cfa.actor, 'intent_team')


# ── transition — Phase 2: Planning ──────────────────────────────────────────────

class TestTransitionPhase2(unittest.TestCase):

    def test_intent_plan_to_draft(self):
        cfa = _make_at_state('INTENT')
        new_cfa = transition(cfa, 'plan')
        self.assertEqual(new_cfa.state, 'DRAFT')
        self.assertEqual(new_cfa.phase, 'planning')
        self.assertEqual(new_cfa.actor, 'planning_team')

    def test_draft_question_to_planning_question(self):
        cfa = _make_at_state('DRAFT')
        new_cfa = transition(cfa, 'question')
        self.assertEqual(new_cfa.state, 'PLANNING_QUESTION')

    def test_draft_escalate_to_planning_escalate(self):
        cfa = _make_at_state('DRAFT')
        new_cfa = transition(cfa, 'escalate')
        self.assertEqual(new_cfa.state, 'PLANNING_ESCALATE')

    def test_draft_assert_to_plan_assert(self):
        cfa = _make_at_state('DRAFT')
        new_cfa = transition(cfa, 'assert')
        self.assertEqual(new_cfa.state, 'PLAN_ASSERT')

    def test_draft_auto_approve_to_plan(self):
        cfa = _make_at_state('DRAFT')
        new_cfa = transition(cfa, 'auto-approve')
        self.assertEqual(new_cfa.state, 'PLAN')
        self.assertEqual(new_cfa.phase, 'planning')

    def test_draft_withdraw_to_withdrawn(self):
        cfa = _make_at_state('DRAFT')
        new_cfa = transition(cfa, 'withdraw')
        self.assertEqual(new_cfa.state, 'WITHDRAWN')

    def test_draft_refine_intent_to_intent_response(self):
        cfa = _make_at_state('DRAFT')
        new_cfa = transition(cfa, 'refine-intent')
        self.assertEqual(new_cfa.state, 'INTENT_RESPONSE')
        self.assertEqual(new_cfa.phase, 'intent')
        self.assertEqual(new_cfa.actor, 'human')

    def test_planning_question_answer_to_planning_response(self):
        cfa = _make_at_state('PLANNING_QUESTION')
        new_cfa = transition(cfa, 'answer')
        self.assertEqual(new_cfa.state, 'PLANNING_RESPONSE')
        self.assertEqual(new_cfa.actor, 'research_team')

    def test_planning_question_backtrack_to_intent_question(self):
        cfa = _make_at_state('PLANNING_QUESTION')
        new_cfa = transition(cfa, 'backtrack')
        self.assertEqual(new_cfa.state, 'INTENT_QUESTION')
        self.assertEqual(new_cfa.phase, 'intent')
        self.assertEqual(new_cfa.actor, 'research_team')

    def test_planning_escalate_clarify_to_planning_response(self):
        cfa = _make_at_state('PLANNING_ESCALATE')
        new_cfa = transition(cfa, 'clarify')
        self.assertEqual(new_cfa.state, 'PLANNING_RESPONSE')
        self.assertEqual(new_cfa.actor, 'human')

    def test_planning_escalate_withdraw_to_withdrawn(self):
        cfa = _make_at_state('PLANNING_ESCALATE')
        new_cfa = transition(cfa, 'withdraw')
        self.assertEqual(new_cfa.state, 'WITHDRAWN')

    def test_plan_assert_approve_to_plan(self):
        cfa = _make_at_state('PLAN_ASSERT')
        new_cfa = transition(cfa, 'approve')
        self.assertEqual(new_cfa.state, 'PLAN')
        self.assertEqual(new_cfa.actor, 'human')

    def test_plan_assert_correct_to_planning_response(self):
        cfa = _make_at_state('PLAN_ASSERT')
        new_cfa = transition(cfa, 'correct')
        self.assertEqual(new_cfa.state, 'PLANNING_RESPONSE')

    def test_plan_assert_withdraw_to_withdrawn(self):
        cfa = _make_at_state('PLAN_ASSERT')
        new_cfa = transition(cfa, 'withdraw')
        self.assertEqual(new_cfa.state, 'WITHDRAWN')

    def test_planning_response_synthesize_to_draft(self):
        cfa = _make_at_state('PLANNING_RESPONSE')
        new_cfa = transition(cfa, 'synthesize')
        self.assertEqual(new_cfa.state, 'DRAFT')
        self.assertEqual(new_cfa.actor, 'planning_team')


# ── transition — Phase 3: Execution ─────────────────────────────────────────────

class TestTransitionPhase3(unittest.TestCase):

    def test_plan_delegate_to_task(self):
        cfa = _make_at_state('PLAN')
        new_cfa = transition(cfa, 'delegate')
        self.assertEqual(new_cfa.state, 'TASK')
        self.assertEqual(new_cfa.phase, 'execution')
        # delegate is performed by 'execution_lead'
        self.assertEqual(new_cfa.actor, 'execution_lead')

    def test_task_accept_to_task_in_progress(self):
        cfa = _make_at_state('TASK')
        new_cfa = transition(cfa, 'accept')
        self.assertEqual(new_cfa.state, 'TASK_IN_PROGRESS')

    def test_task_escalate_to_task_escalate(self):
        cfa = _make_at_state('TASK')
        new_cfa = transition(cfa, 'escalate')
        self.assertEqual(new_cfa.state, 'TASK_ESCALATE')
        self.assertEqual(new_cfa.actor, 'execution_worker')

    def test_task_failed_to_failed_task(self):
        cfa = _make_at_state('TASK')
        new_cfa = transition(cfa, 'failed')
        self.assertEqual(new_cfa.state, 'FAILED_TASK')

    def test_task_in_progress_assert_to_task_assert(self):
        cfa = _make_at_state('TASK_IN_PROGRESS')
        new_cfa = transition(cfa, 'assert')
        self.assertEqual(new_cfa.state, 'TASK_ASSERT')

    def test_task_in_progress_question_to_task_question(self):
        cfa = _make_at_state('TASK_IN_PROGRESS')
        new_cfa = transition(cfa, 'question')
        self.assertEqual(new_cfa.state, 'TASK_QUESTION')

    def test_task_in_progress_escalate_to_task_escalate(self):
        cfa = _make_at_state('TASK_IN_PROGRESS')
        new_cfa = transition(cfa, 'escalate')
        self.assertEqual(new_cfa.state, 'TASK_ESCALATE')

    def test_task_in_progress_failed_to_failed_task(self):
        cfa = _make_at_state('TASK_IN_PROGRESS')
        new_cfa = transition(cfa, 'failed')
        self.assertEqual(new_cfa.state, 'FAILED_TASK')

    def test_task_question_answer_to_task_response(self):
        cfa = _make_at_state('TASK_QUESTION')
        new_cfa = transition(cfa, 'answer')
        self.assertEqual(new_cfa.state, 'TASK_RESPONSE')
        self.assertEqual(new_cfa.actor, 'research_team')

    def test_task_question_backtrack_to_planning_question(self):
        cfa = _make_at_state('TASK_QUESTION')
        new_cfa = transition(cfa, 'backtrack')
        self.assertEqual(new_cfa.state, 'PLANNING_QUESTION')
        self.assertEqual(new_cfa.phase, 'planning')
        self.assertEqual(new_cfa.actor, 'research_team')

    def test_task_escalate_clarify_to_task_response(self):
        cfa = _make_at_state('TASK_ESCALATE')
        new_cfa = transition(cfa, 'clarify')
        self.assertEqual(new_cfa.state, 'TASK_RESPONSE')
        self.assertEqual(new_cfa.actor, 'approval_gate')

    def test_task_escalate_withdraw_to_withdrawn(self):
        cfa = _make_at_state('TASK_ESCALATE')
        new_cfa = transition(cfa, 'withdraw')
        self.assertEqual(new_cfa.state, 'WITHDRAWN')
        self.assertEqual(new_cfa.actor, 'approval_gate')

    def test_task_assert_approve_to_completed_task(self):
        cfa = _make_at_state('TASK_ASSERT')
        new_cfa = transition(cfa, 'approve')
        self.assertEqual(new_cfa.state, 'COMPLETED_TASK')
        self.assertEqual(new_cfa.actor, 'execution_lead')

    def test_task_assert_correct_to_task_response(self):
        cfa = _make_at_state('TASK_ASSERT')
        new_cfa = transition(cfa, 'correct')
        self.assertEqual(new_cfa.state, 'TASK_RESPONSE')

    def test_task_assert_reject_to_failed_task(self):
        cfa = _make_at_state('TASK_ASSERT')
        new_cfa = transition(cfa, 'reject')
        self.assertEqual(new_cfa.state, 'FAILED_TASK')
        self.assertEqual(new_cfa.actor, 'execution_lead')

    def test_task_response_synthesize_to_task_in_progress(self):
        cfa = _make_at_state('TASK_RESPONSE')
        new_cfa = transition(cfa, 'synthesize')
        self.assertEqual(new_cfa.state, 'TASK_IN_PROGRESS')
        self.assertEqual(new_cfa.actor, 'execution_worker')

    def test_failed_task_retry_to_task(self):
        cfa = _make_at_state('FAILED_TASK')
        new_cfa = transition(cfa, 'retry')
        self.assertEqual(new_cfa.state, 'TASK')
        self.assertEqual(new_cfa.actor, 'execution_worker')

    def test_failed_task_escalate_to_task_escalate(self):
        cfa = _make_at_state('FAILED_TASK')
        new_cfa = transition(cfa, 'escalate')
        self.assertEqual(new_cfa.state, 'TASK_ESCALATE')

    def test_failed_task_backtrack_to_planning_question(self):
        cfa = _make_at_state('FAILED_TASK')
        new_cfa = transition(cfa, 'backtrack')
        self.assertEqual(new_cfa.state, 'PLANNING_QUESTION')
        self.assertEqual(new_cfa.phase, 'planning')
        self.assertEqual(new_cfa.actor, 'execution_lead')

    def test_completed_task_synthesize_to_work_in_progress(self):
        cfa = _make_at_state('COMPLETED_TASK')
        new_cfa = transition(cfa, 'synthesize')
        self.assertEqual(new_cfa.state, 'WORK_IN_PROGRESS')
        self.assertEqual(new_cfa.actor, 'execution_lead')

    def test_work_in_progress_delegate_to_task(self):
        cfa = _make_at_state('WORK_IN_PROGRESS')
        new_cfa = transition(cfa, 'delegate')
        self.assertEqual(new_cfa.state, 'TASK')

    def test_work_in_progress_assert_to_work_assert(self):
        cfa = _make_at_state('WORK_IN_PROGRESS')
        new_cfa = transition(cfa, 'assert')
        self.assertEqual(new_cfa.state, 'WORK_ASSERT')

    def test_work_in_progress_auto_approve_to_completed_work(self):
        cfa = _make_at_state('WORK_IN_PROGRESS')
        new_cfa = transition(cfa, 'auto-approve')
        self.assertEqual(new_cfa.state, 'COMPLETED_WORK')

    def test_work_in_progress_backtrack_to_planning_question(self):
        cfa = _make_at_state('WORK_IN_PROGRESS')
        new_cfa = transition(cfa, 'backtrack')
        self.assertEqual(new_cfa.state, 'PLANNING_QUESTION')
        self.assertEqual(new_cfa.phase, 'planning')

    def test_work_assert_approve_to_completed_work(self):
        cfa = _make_at_state('WORK_ASSERT')
        new_cfa = transition(cfa, 'approve')
        self.assertEqual(new_cfa.state, 'COMPLETED_WORK')
        self.assertEqual(new_cfa.actor, 'approval_gate')

    def test_work_assert_correct_to_task_response(self):
        cfa = _make_at_state('WORK_ASSERT')
        new_cfa = transition(cfa, 'correct')
        self.assertEqual(new_cfa.state, 'TASK_RESPONSE')

    def test_work_assert_revise_plan_to_planning_response(self):
        cfa = _make_at_state('WORK_ASSERT')
        new_cfa = transition(cfa, 'revise-plan')
        self.assertEqual(new_cfa.state, 'PLANNING_RESPONSE')
        self.assertEqual(new_cfa.phase, 'planning')

    def test_work_assert_refine_intent_to_intent_response(self):
        cfa = _make_at_state('WORK_ASSERT')
        new_cfa = transition(cfa, 'refine-intent')
        self.assertEqual(new_cfa.state, 'INTENT_RESPONSE')
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
            transition(cfa, 'approve')

    def test_wrong_action_for_state_raises(self):
        cfa = _make_at_state('PROPOSAL')
        with self.assertRaises(InvalidTransition):
            transition(cfa, 'accept')

    def test_terminal_state_raises_on_any_action(self):
        for terminal in ('COMPLETED_WORK', 'WITHDRAWN'):
            cfa = _make_at_state(terminal)
            with self.subTest(terminal=terminal):
                with self.assertRaises(InvalidTransition):
                    transition(cfa, 'propose')

    def test_error_message_lists_valid_actions(self):
        cfa = _make_at_state('PROPOSAL')
        try:
            transition(cfa, 'bogus-action')
            self.fail("Expected InvalidTransition")
        except InvalidTransition as e:
            # Error message should mention the invalid action
            self.assertIn('bogus-action', str(e))

    def test_skipping_phases_raises(self):
        """Cannot jump from IDEA straight to DRAFT."""
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
        cfa = transition(cfa, 'propose')
        self.assertEqual(len(cfa.history), 1)
        cfa = transition(cfa, 'auto-approve')
        self.assertEqual(len(cfa.history), 2)

    def test_history_entry_has_required_keys(self):
        cfa = make_initial_state()
        cfa = transition(cfa, 'propose')
        entry = cfa.history[0]
        self.assertIn('state', entry)
        self.assertIn('action', entry)
        self.assertIn('actor', entry)
        self.assertIn('timestamp', entry)

    def test_history_records_correct_from_state(self):
        cfa = make_initial_state()
        cfa = transition(cfa, 'propose')
        self.assertEqual(cfa.history[0]['state'], 'IDEA')
        self.assertEqual(cfa.history[0]['action'], 'propose')

    def test_history_is_not_mutated_between_instances(self):
        """Original CfaState is not mutated when transitioning."""
        original = make_initial_state()
        new_cfa = transition(original, 'propose')
        self.assertEqual(len(original.history), 0)
        self.assertEqual(len(new_cfa.history), 1)

    def test_history_timestamp_is_iso_format(self):
        from datetime import datetime
        cfa = transition(make_initial_state(), 'propose')
        ts = cfa.history[0]['timestamp']
        # Should parse without error
        parsed = datetime.fromisoformat(ts)
        self.assertIsNotNone(parsed)


# ── Backtrack count ──────────────────────────────────────────────────────────────

class TestBacktrackCount(unittest.TestCase):

    def test_forward_transitions_do_not_increment(self):
        cfa = _advance(make_initial_state(), 'propose', 'auto-approve', 'plan', 'auto-approve')
        self.assertEqual(cfa.backtrack_count, 0)

    def test_draft_refine_intent_increments(self):
        cfa = _advance(make_initial_state(), 'propose', 'auto-approve', 'plan', 'refine-intent')
        self.assertEqual(cfa.backtrack_count, 1)

    def test_multiple_backtracks_accumulate(self):
        # IDEA → PROPOSAL → INTENT → DRAFT → refine-intent → INTENT_RESPONSE
        # → synthesize → PROPOSAL → auto-approve → INTENT → plan → DRAFT
        # → refine-intent (2nd backtrack) → ...
        cfa = make_initial_state()
        cfa = _advance(cfa, 'propose', 'auto-approve')  # INTENT
        cfa = _advance(cfa, 'plan', 'refine-intent')    # INTENT_RESPONSE; backtrack #1
        self.assertEqual(cfa.backtrack_count, 1)
        cfa = _advance(cfa, 'synthesize', 'auto-approve')  # INTENT again
        cfa = _advance(cfa, 'plan', 'refine-intent')        # backtrack #2
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
        cfa = _advance(make_initial_state(), 'propose', 'auto-approve', 'plan')
        path = self._make_temp_path()
        try:
            save_state(cfa, path)
            loaded = load_state(path)
            self.assertEqual(loaded.state, 'DRAFT')
            self.assertEqual(loaded.phase, 'planning')
            self.assertEqual(len(loaded.history), 3)
        finally:
            os.unlink(path)

    def test_round_trip_with_backtrack_count(self):
        cfa = _advance(make_initial_state(), 'propose', 'auto-approve', 'plan', 'refine-intent')
        path = self._make_temp_path()
        try:
            save_state(cfa, path)
            loaded = load_state(path)
            self.assertEqual(loaded.backtrack_count, 1)
        finally:
            os.unlink(path)

    def test_round_trip_with_task_id(self):
        cfa = _make_at_state('TASK', task_id='task-abc-123')
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
        """IDEA → PROPOSAL → INTENT → DRAFT → PLAN → TASK → TASK_IN_PROGRESS
           → TASK_ASSERT → COMPLETED_TASK → WORK_IN_PROGRESS → COMPLETED_WORK"""
        cfa = make_initial_state()
        self.assertEqual(cfa.state, 'IDEA')

        cfa = transition(cfa, 'propose')
        self.assertEqual(cfa.state, 'PROPOSAL')

        cfa = transition(cfa, 'auto-approve')
        self.assertEqual(cfa.state, 'INTENT')
        self.assertTrue(is_phase_terminal('INTENT'))
        self.assertFalse(is_globally_terminal('INTENT'))

        cfa = transition(cfa, 'plan')
        self.assertEqual(cfa.state, 'DRAFT')

        cfa = transition(cfa, 'auto-approve')
        self.assertEqual(cfa.state, 'PLAN')
        self.assertTrue(is_phase_terminal('PLAN'))
        self.assertFalse(is_globally_terminal('PLAN'))

        cfa = transition(cfa, 'delegate')
        self.assertEqual(cfa.state, 'TASK')

        cfa = transition(cfa, 'accept')
        self.assertEqual(cfa.state, 'TASK_IN_PROGRESS')

        cfa = transition(cfa, 'assert')
        self.assertEqual(cfa.state, 'TASK_ASSERT')

        cfa = transition(cfa, 'approve')
        self.assertEqual(cfa.state, 'COMPLETED_TASK')

        cfa = transition(cfa, 'synthesize')
        self.assertEqual(cfa.state, 'WORK_IN_PROGRESS')

        cfa = transition(cfa, 'auto-approve')
        self.assertEqual(cfa.state, 'COMPLETED_WORK')

        self.assertTrue(is_globally_terminal('COMPLETED_WORK'))
        self.assertEqual(cfa.backtrack_count, 0)
        # 10 transitions = 10 history entries
        self.assertEqual(len(cfa.history), 10)

    def test_full_happy_path_phases_correct(self):
        """Verify phase transitions at each phase boundary."""
        cfa = make_initial_state()
        self.assertEqual(cfa.phase, 'intent')

        cfa = _advance(cfa, 'propose', 'auto-approve')
        self.assertEqual(cfa.phase, 'intent')  # INTENT is still intent phase

        cfa = _advance(cfa, 'plan')
        self.assertEqual(cfa.phase, 'planning')  # DRAFT enters planning

        cfa = _advance(cfa, 'auto-approve')
        self.assertEqual(cfa.phase, 'planning')  # PLAN is still planning phase

        cfa = _advance(cfa, 'delegate')
        self.assertEqual(cfa.phase, 'execution')  # TASK enters execution

    def test_withdrawn_path(self):
        """Withdrawal at any point leads to WITHDRAWN terminal state."""
        cfa = _advance(make_initial_state(), 'propose')
        cfa = transition(cfa, 'withdraw')
        self.assertEqual(cfa.state, 'WITHDRAWN')
        self.assertTrue(is_globally_terminal('WITHDRAWN'))
        # Cannot continue after withdrawal
        with self.assertRaises(InvalidTransition):
            transition(cfa, 'propose')


# ── Backtracking path ────────────────────────────────────────────────────────────

class TestBacktrackingPath(unittest.TestCase):
    """Test a full path that includes cross-phase backtracking."""

    def test_backtrack_from_draft_to_intent_and_complete(self):
        """IDEA → ... → DRAFT → refine-intent → INTENT_RESPONSE → synthesize
           → PROPOSAL → auto-approve → INTENT → plan → DRAFT → auto-approve
           → PLAN → ... → COMPLETED_WORK"""
        cfa = make_initial_state()

        # Reach DRAFT
        cfa = _advance(cfa, 'propose', 'auto-approve', 'plan')
        self.assertEqual(cfa.state, 'DRAFT')
        self.assertEqual(cfa.backtrack_count, 0)

        # Backtrack to intent phase
        cfa = transition(cfa, 'refine-intent')
        self.assertEqual(cfa.state, 'INTENT_RESPONSE')
        self.assertEqual(cfa.phase, 'intent')
        self.assertEqual(cfa.backtrack_count, 1)

        # Re-synthesize intent
        cfa = transition(cfa, 'synthesize')
        self.assertEqual(cfa.state, 'PROPOSAL')

        cfa = transition(cfa, 'auto-approve')
        self.assertEqual(cfa.state, 'INTENT')

        # Re-enter planning
        cfa = transition(cfa, 'plan')
        self.assertEqual(cfa.state, 'DRAFT')
        self.assertEqual(cfa.phase, 'planning')

        cfa = transition(cfa, 'auto-approve')
        self.assertEqual(cfa.state, 'PLAN')

        # Complete execution
        cfa = _advance(cfa, 'delegate', 'accept', 'assert', 'approve', 'synthesize', 'auto-approve')
        self.assertEqual(cfa.state, 'COMPLETED_WORK')
        self.assertTrue(is_globally_terminal(cfa.state))
        self.assertEqual(cfa.backtrack_count, 1)

    def test_backtrack_from_work_assert_revise_plan(self):
        """Backtrack from WORK_ASSERT → revise-plan → PLANNING_RESPONSE."""
        cfa = _make_at_state('WORK_ASSERT')
        cfa = transition(cfa, 'revise-plan')
        self.assertEqual(cfa.state, 'PLANNING_RESPONSE')
        self.assertEqual(cfa.phase, 'planning')
        self.assertEqual(cfa.backtrack_count, 1)

        # Can synthesize back to DRAFT
        cfa = transition(cfa, 'synthesize')
        self.assertEqual(cfa.state, 'DRAFT')

    def test_backtrack_from_work_assert_refine_intent(self):
        """Deep backtrack: WORK_ASSERT → refine-intent → INTENT_RESPONSE."""
        cfa = _make_at_state('WORK_ASSERT')
        cfa = transition(cfa, 'refine-intent')
        self.assertEqual(cfa.state, 'INTENT_RESPONSE')
        self.assertEqual(cfa.phase, 'intent')
        self.assertEqual(cfa.backtrack_count, 1)

    def test_backtrack_from_planning_question_to_intent(self):
        """PLANNING_QUESTION → backtrack → INTENT_QUESTION (in intent phase)."""
        cfa = _make_at_state('PLANNING_QUESTION')
        cfa = transition(cfa, 'backtrack')
        self.assertEqual(cfa.state, 'INTENT_QUESTION')
        self.assertEqual(cfa.phase, 'intent')
        self.assertEqual(cfa.backtrack_count, 1)

        # Can answer and continue forward
        cfa = transition(cfa, 'answer')
        self.assertEqual(cfa.state, 'INTENT_RESPONSE')

    def test_backtrack_from_task_question_to_planning(self):
        """TASK_QUESTION → backtrack → PLANNING_QUESTION (in planning phase)."""
        cfa = _make_at_state('TASK_QUESTION')
        cfa = transition(cfa, 'backtrack')
        self.assertEqual(cfa.state, 'PLANNING_QUESTION')
        self.assertEqual(cfa.phase, 'planning')
        self.assertEqual(cfa.backtrack_count, 1)

    def test_failed_task_backtrack_to_planning(self):
        """FAILED_TASK → backtrack → PLANNING_QUESTION."""
        cfa = _make_at_state('FAILED_TASK')
        cfa = transition(cfa, 'backtrack')
        self.assertEqual(cfa.state, 'PLANNING_QUESTION')
        self.assertEqual(cfa.phase, 'planning')
        self.assertEqual(cfa.actor, 'execution_lead')
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
        parent = _make_at_state('TASK', task_id='uber-001')
        child = make_child_state(parent, 'coding')
        self.assertEqual(child.parent_id, 'uber-001')
        self.assertEqual(child.team_id, 'coding')
        self.assertEqual(child.depth, 1)
        self.assertEqual(child.state, 'INTENT')
        self.assertEqual(child.phase, 'planning')
        self.assertTrue(child.task_id.startswith('coding-'))

    def test_make_child_state_custom_task_id(self):
        parent = _make_at_state('TASK', task_id='uber-001')
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
        parent = _make_at_state('TASK', task_id='uber-001')
        child = make_child_state(parent, 'coding')
        self.assertFalse(is_root(child))

    def test_hierarchy_preserved_through_transitions(self):
        parent = _make_at_state('TASK', task_id='uber-001')
        child = make_child_state(parent, 'coding')
        # Child starts at INTENT (skips intent phase per spec Section 7)
        child = transition(child, 'plan')
        self.assertEqual(child.parent_id, 'uber-001')
        self.assertEqual(child.team_id, 'coding')
        self.assertEqual(child.depth, 1)
        child = transition(child, 'auto-approve')
        self.assertEqual(child.parent_id, 'uber-001')
        self.assertEqual(child.team_id, 'coding')
        self.assertEqual(child.depth, 1)

    def test_hierarchy_preserved_through_backtrack(self):
        parent = _make_at_state('TASK', task_id='uber-001')
        child = make_child_state(parent, 'coding')
        # Child starts at INTENT, plan → DRAFT, refine-intent → INTENT_RESPONSE (backtrack)
        child = _advance(child, 'plan', 'refine-intent')
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
            'state': 'DRAFT',
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
            self.assertEqual(loaded.state, 'DRAFT')
            self.assertEqual(loaded.parent_id, '')
            self.assertEqual(loaded.team_id, '')
            self.assertEqual(loaded.depth, 0)
        finally:
            os.unlink(path)

    def test_child_state_round_trip(self):
        parent = _make_at_state('TASK', task_id='uber-001')
        child = make_child_state(parent, 'art', task_id='art-001')
        # Child starts at INTENT; advance to DRAFT via plan
        child = _advance(child, 'plan')  # INTENT → DRAFT
        path = self._make_temp_path()
        try:
            save_state(child, path)
            loaded = load_state(path)
            self.assertEqual(loaded.parent_id, 'uber-001')
            self.assertEqual(loaded.team_id, 'art')
            self.assertEqual(loaded.depth, 1)
            self.assertEqual(loaded.task_id, 'art-001')
            self.assertEqual(loaded.state, 'DRAFT')
        finally:
            os.unlink(path)


# ── set_state_direct ──────────────────────────────────────────────────────────

class TestSetStateDirect(unittest.TestCase):

    def test_set_to_plan(self):
        cfa = make_initial_state()
        cfa = set_state_direct(cfa, 'PLAN')
        self.assertEqual(cfa.state, 'PLAN')
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
        cfa = set_state_direct(cfa, 'PLAN')
        self.assertEqual(cfa.parent_id, 'p1')
        self.assertEqual(cfa.team_id, 'art')
        self.assertEqual(cfa.depth, 1)

    def test_set_state_preserves_backtrack_count(self):
        cfa = _make_cfa(backtrack_count=3)
        cfa = set_state_direct(cfa, 'TASK')
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
        # Parent: IDEA → ... → PLAN → delegate → TASK
        parent = make_initial_state(task_id='uber-001')
        parent = _advance(parent, 'propose', 'auto-approve', 'plan', 'auto-approve', 'delegate')
        self.assertEqual(parent.state, 'TASK')

        # Create child for coding team — starts at INTENT (skips intent phase per spec Section 7)
        child = make_child_state(parent, 'coding', task_id='coding-001')
        self.assertEqual(child.depth, 1)
        self.assertEqual(child.parent_id, 'uber-001')
        self.assertEqual(child.state, 'INTENT')

        # Child runs planning+execution (no intent phase needed)
        child = _advance(child, 'plan', 'auto-approve',
                        'delegate', 'accept', 'assert', 'approve', 'synthesize', 'auto-approve')
        self.assertEqual(child.state, 'COMPLETED_WORK')
        self.assertTrue(is_globally_terminal(child.state))

        # Parent continues: TASK → accept → ... → COMPLETED_WORK
        parent = _advance(parent, 'accept', 'assert', 'approve', 'synthesize', 'auto-approve')
        self.assertEqual(parent.state, 'COMPLETED_WORK')

    def test_multiple_dispatches_sequential(self):
        """Parent dispatches to multiple teams sequentially."""
        parent = make_initial_state(task_id='uber-001')
        parent = _advance(parent, 'propose', 'auto-approve', 'plan', 'auto-approve', 'delegate')

        # First dispatch: art team — child starts at INTENT (skips intent phase)
        art_child = make_child_state(parent, 'art', task_id='art-001')
        art_child = _advance(art_child, 'plan', 'auto-approve',
                            'delegate', 'accept', 'assert', 'approve', 'synthesize', 'auto-approve')
        self.assertEqual(art_child.state, 'COMPLETED_WORK')

        # Parent: accept first task, then delegate again
        parent = _advance(parent, 'accept', 'assert', 'approve', 'synthesize')
        self.assertEqual(parent.state, 'WORK_IN_PROGRESS')
        parent = transition(parent, 'delegate')  # Second dispatch
        self.assertEqual(parent.state, 'TASK')

        # Second dispatch: coding team — child starts at INTENT
        coding_child = make_child_state(parent, 'coding', task_id='coding-001')
        self.assertEqual(coding_child.parent_id, 'uber-001')
        coding_child = _advance(coding_child, 'plan', 'auto-approve',
                               'delegate', 'accept', 'assert', 'approve', 'synthesize', 'auto-approve')
        self.assertEqual(coding_child.state, 'COMPLETED_WORK')

        # Parent finishes
        parent = _advance(parent, 'accept', 'assert', 'approve', 'synthesize', 'auto-approve')
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

            # Apply 'propose' transition: IDEA → PROPOSAL
            loaded = load_state(state_file)
            result = transition(loaded, 'propose')
            save_state(result, state_file)

            reloaded = load_state(state_file)
            self.assertEqual(reloaded.state, 'PROPOSAL')
        finally:
            os.unlink(state_file)

    def test_invalid_transition_raises(self):
        """Applying an invalid action from a given state raises InvalidTransition."""
        cfa = _make_cfa(state='IDEA')
        with self.assertRaises(InvalidTransition):
            transition(cfa, 'approve')  # 'approve' is not valid from IDEA

    def test_transition_round_trip_through_planning(self):
        """Walk through a valid transition sequence through intent and planning."""
        cfa = _make_cfa(state='IDEA')
        cfa = transition(cfa, 'propose')
        self.assertEqual(cfa.state, 'PROPOSAL')
        cfa = transition(cfa, 'assert')
        self.assertEqual(cfa.state, 'INTENT_ASSERT')
        cfa = transition(cfa, 'approve')
        self.assertEqual(cfa.state, 'INTENT')
        cfa = transition(cfa, 'plan')
        self.assertEqual(cfa.state, 'DRAFT')
        cfa = transition(cfa, 'assert')
        self.assertEqual(cfa.state, 'PLAN_ASSERT')
        cfa = transition(cfa, 'approve')
        self.assertEqual(cfa.state, 'PLAN')

    def test_work_assert_correct_goes_to_task_response(self):
        """Per CfA spec: WORK_ASSERT correct → TASK_RESPONSE (not PLANNING_RESPONSE)."""
        cfa = _make_cfa(state='WORK_ASSERT', phase='execution')
        cfa = transition(cfa, 'correct')
        self.assertEqual(cfa.state, 'TASK_RESPONSE')

    def test_withdraw_from_work_in_progress(self):
        """WORK_IN_PROGRESS withdraw → WITHDRAWN (newly added transition)."""
        cfa = _make_cfa(state='WORK_IN_PROGRESS', phase='execution')
        cfa = transition(cfa, 'withdraw')
        self.assertEqual(cfa.state, 'WITHDRAWN')

    def test_withdraw_from_task_in_progress(self):
        """TASK_IN_PROGRESS withdraw → WITHDRAWN (newly added transition)."""
        cfa = _make_cfa(state='TASK_IN_PROGRESS', phase='execution')
        cfa = transition(cfa, 'withdraw')
        self.assertEqual(cfa.state, 'WITHDRAWN')

    def test_withdraw_from_failed_task(self):
        """FAILED_TASK withdraw → WITHDRAWN (newly added transition)."""
        cfa = _make_cfa(state='FAILED_TASK', phase='execution')
        cfa = transition(cfa, 'withdraw')
        self.assertEqual(cfa.state, 'WITHDRAWN')


# ── Escalation path tests ─────────────────────────────────────────────────────

class TestEscalationPaths(unittest.TestCase):
    """Verify the full escalation paths through the CfA state machine.

    These are the paths that the new shell orchestration code drives:
      PROPOSAL → escalate → INTENT_ESCALATE → clarify → INTENT_RESPONSE → synthesize → PROPOSAL
      DRAFT → escalate → PLANNING_ESCALATE → clarify → PLANNING_RESPONSE → synthesize → DRAFT
      TASK_IN_PROGRESS → escalate → TASK_ESCALATE → clarify → TASK_RESPONSE → synthesize → TASK_IN_PROGRESS
    """

    def test_intent_escalation_full_path(self):
        """PROPOSAL → escalate → INTENT_ESCALATE → clarify → INTENT_RESPONSE → synthesize → PROPOSAL."""
        cfa = _make_cfa(state='PROPOSAL', phase='intent')
        cfa = transition(cfa, 'escalate')
        self.assertEqual(cfa.state, 'INTENT_ESCALATE')
        cfa = transition(cfa, 'clarify')
        self.assertEqual(cfa.state, 'INTENT_RESPONSE')
        cfa = transition(cfa, 'synthesize')
        self.assertEqual(cfa.state, 'PROPOSAL')

    def test_planning_escalation_full_path(self):
        """DRAFT → escalate → PLANNING_ESCALATE → clarify → PLANNING_RESPONSE → synthesize → DRAFT."""
        cfa = _make_cfa(state='DRAFT', phase='planning')
        cfa = transition(cfa, 'escalate')
        self.assertEqual(cfa.state, 'PLANNING_ESCALATE')
        cfa = transition(cfa, 'clarify')
        self.assertEqual(cfa.state, 'PLANNING_RESPONSE')
        cfa = transition(cfa, 'synthesize')
        self.assertEqual(cfa.state, 'DRAFT')

    def test_execution_escalation_full_path(self):
        """TASK_IN_PROGRESS → escalate → TASK_ESCALATE → clarify → TASK_RESPONSE → synthesize → TASK_IN_PROGRESS."""
        cfa = _make_cfa(state='TASK_IN_PROGRESS', phase='execution')
        cfa = transition(cfa, 'escalate')
        self.assertEqual(cfa.state, 'TASK_ESCALATE')
        cfa = transition(cfa, 'clarify')
        self.assertEqual(cfa.state, 'TASK_RESPONSE')
        cfa = transition(cfa, 'synthesize')
        self.assertEqual(cfa.state, 'TASK_IN_PROGRESS')

    def test_intent_escalation_withdraw(self):
        """Withdraw from INTENT_ESCALATE → WITHDRAWN."""
        cfa = _make_cfa(state='INTENT_ESCALATE', phase='intent')
        cfa = transition(cfa, 'withdraw')
        self.assertEqual(cfa.state, 'WITHDRAWN')

    def test_planning_escalation_withdraw(self):
        """Withdraw from PLANNING_ESCALATE → WITHDRAWN."""
        cfa = _make_cfa(state='PLANNING_ESCALATE', phase='planning')
        cfa = transition(cfa, 'withdraw')
        self.assertEqual(cfa.state, 'WITHDRAWN')

    def test_task_escalation_withdraw(self):
        """Withdraw from TASK_ESCALATE → WITHDRAWN."""
        cfa = _make_cfa(state='TASK_ESCALATE', phase='execution')
        cfa = transition(cfa, 'withdraw')
        self.assertEqual(cfa.state, 'WITHDRAWN')

    def test_multiple_escalation_rounds(self):
        """Agent can escalate multiple times before writing INTENT.md."""
        cfa = _make_cfa(state='PROPOSAL', phase='intent')
        # Round 1: escalate → clarify → back to PROPOSAL
        cfa = transition(cfa, 'escalate')
        self.assertEqual(cfa.state, 'INTENT_ESCALATE')
        cfa = transition(cfa, 'clarify')
        cfa = transition(cfa, 'synthesize')
        self.assertEqual(cfa.state, 'PROPOSAL')
        # Round 2: escalate again
        cfa = transition(cfa, 'escalate')
        self.assertEqual(cfa.state, 'INTENT_ESCALATE')
        cfa = transition(cfa, 'clarify')
        cfa = transition(cfa, 'synthesize')
        self.assertEqual(cfa.state, 'PROPOSAL')
        # Finally: assert (write INTENT.md)
        cfa = transition(cfa, 'assert')
        self.assertEqual(cfa.state, 'INTENT_ASSERT')

    def test_escalation_then_assert_path(self):
        """Planning escalation followed by normal assert path."""
        cfa = _make_cfa(state='DRAFT', phase='planning')
        # Escalate first
        cfa = transition(cfa, 'escalate')
        self.assertEqual(cfa.state, 'PLANNING_ESCALATE')
        cfa = transition(cfa, 'clarify')
        cfa = transition(cfa, 'synthesize')
        self.assertEqual(cfa.state, 'DRAFT')
        # Then assert normally
        cfa = transition(cfa, 'assert')
        self.assertEqual(cfa.state, 'PLAN_ASSERT')
        cfa = transition(cfa, 'approve')
        self.assertEqual(cfa.state, 'PLAN')


if __name__ == '__main__':
    unittest.main()
