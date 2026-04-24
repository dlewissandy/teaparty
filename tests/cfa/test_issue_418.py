#!/usr/bin/env python3
"""Issue #418: Task-level CfA states are gone; the execution phase is
flattened into a single working state.

In the five-state model (INTENT, PLAN, EXECUTE, DONE, WITHDRAWN) the
execution phase has one non-terminal state (EXECUTE) plus the two
globally terminal states (DONE, WITHDRAWN). All TASK_* states,
FAILED_TASK, COMPLETED_TASK, AWAITING_REPLIES, and the actors
execution_worker/execution_lead are removed. The probe-loop / retry
machinery in ApprovalGate (_MAX_DIALOG_TURNS, _MAX_FALLBACK_RETRIES,
_NEVER_ESCALATE_STATES, __fallback__) is deleted.

These tests encode the new invariants. Each would fail if the
corresponding removal were reverted.
"""
from __future__ import annotations

import inspect
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.cfa.statemachine.cfa_state import (
    ALL_STATES,
    EXECUTION_STATES,
    INTENT_STATES,
    PLANNING_STATES,
    TERMINAL_STATES,
    TRANSITIONS,
    CfaState,
    is_globally_terminal,
    make_initial_state,
    transition,
)


REMOVED_TASK_STATES = frozenset({
    'TASK',
    'TASK_IN_PROGRESS',
    'TASK_QUESTION',
    'TASK_ESCALATE',
    'TASK_RESPONSE',
    'TASK_ASSERT',
    'COMPLETED_TASK',
    'FAILED_TASK',
    'AWAITING_REPLIES',
    # Also removed in the five-state collapse:
    'WORK_IN_PROGRESS',
    'WORK_ASSERT',
    'COMPLETED_WORK',
    'IDEA',
    'PLANNING',
    'INTENT_ASSERT',
    'PLAN_ASSERT',
    'PLANNING_QUESTION',
    'PLANNING_RESPONSE',
    'INTENT_RESPONSE',
})

REMOVED_ACTIONS = frozenset({
    'send-and-wait', 'resume',
    # Also removed in the five-state collapse:
    'assert', 'auto-approve', 'correct', 'refine-intent', 'revise-plan',
    'plan',
})


# ── State machine structural invariants ────────────────────────────────────

class TestExecutionPhaseShape(unittest.TestCase):
    """The execution phase reduces to {EXECUTE}; terminals are their own phase."""

    def test_execution_phase_has_exactly_one_state(self):
        self.assertEqual(
            set(EXECUTION_STATES),
            {'EXECUTE'},
            f'execution phase must contain only EXECUTE, got {sorted(EXECUTION_STATES)}',
        )

    def test_terminals_are_their_own_phase(self):
        self.assertEqual(
            set(TERMINAL_STATES),
            {'DONE', 'WITHDRAWN'},
            f'terminal states must be exactly DONE and WITHDRAWN, got {sorted(TERMINAL_STATES)}',
        )

    def test_no_task_level_states_in_any_phase(self):
        for state in REMOVED_TASK_STATES:
            self.assertNotIn(
                state, ALL_STATES,
                f'state {state!r} was supposed to be removed but is still defined',
            )

    def test_no_transition_targets_a_removed_task_state(self):
        for source, edges in TRANSITIONS.items():
            for action, target in edges:
                self.assertNotIn(
                    target, REMOVED_TASK_STATES,
                    f'transition {source} --{action}--> {target} targets a removed task-level state',
                )

    def test_no_transition_originates_from_a_removed_task_state(self):
        for state in REMOVED_TASK_STATES:
            self.assertNotIn(
                state, TRANSITIONS,
                f'state {state!r} still has outgoing transitions defined',
            )


class TestNewDelegatePath(unittest.TestCase):
    """PLAN --approve--> EXECUTE (planning phase terminates via the skill outcome)."""

    def test_plan_approves_to_execute(self):
        plan_edges = TRANSITIONS.get('PLAN', [])
        approve_targets = [
            target for action, target in plan_edges
            if action == 'approve'
        ]
        self.assertEqual(
            approve_targets, ['EXECUTE'],
            'PLAN must approve directly to EXECUTE — got '
            f'{approve_targets}',
        )

    def test_execute_outgoing_edges_are_exact(self):
        """EXECUTE has exactly four outgoing actions:
        approve (→DONE), replan (→PLAN), realign (→INTENT), withdraw (→WITHDRAWN)."""
        edges = TRANSITIONS.get('EXECUTE', [])
        action_to_target = {action: target for action, target in edges}

        self.assertEqual(
            set(action_to_target.keys()),
            {'approve', 'replan', 'realign', 'withdraw'},
            f'EXECUTE must have exactly these four actions; '
            f'got {sorted(action_to_target.keys())}',
        )
        self.assertEqual(
            action_to_target['approve'], 'DONE',
            f'EXECUTE --approve--> must go to DONE, got '
            f'{action_to_target["approve"]}',
        )
        self.assertEqual(
            action_to_target['replan'], 'PLAN',
            f'EXECUTE --replan--> must go to PLAN '
            f'(project-level backtrack to planning phase), got '
            f'{action_to_target["replan"]}',
        )
        self.assertEqual(
            action_to_target['realign'], 'INTENT',
            f'EXECUTE --realign--> must go to INTENT (deep backtrack), got '
            f'{action_to_target["realign"]}',
        )
        self.assertEqual(
            action_to_target['withdraw'], 'WITHDRAWN',
            f'EXECUTE --withdraw--> must go to WITHDRAWN, got '
            f'{action_to_target["withdraw"]}',
        )


class TestActionsRemoved(unittest.TestCase):
    """send-and-wait and resume were state-machine-only mechanics for
    TASK_IN_PROGRESS ↔ AWAITING_REPLIES. Both must be gone. Likewise for
    the assert/auto-approve/correct/refine-intent/revise-plan/plan actions
    that belonged to the removed WORK_ASSERT/IDEA/PLANNING states."""

    def test_send_and_wait_action_not_present(self):
        for source, edges in TRANSITIONS.items():
            for action, _target in edges:
                self.assertNotEqual(
                    action, 'send-and-wait',
                    f'action {action!r} still present from {source}; '
                    'fan-in must happen at the turn boundary, not as a '
                    'state transition',
                )

    def test_resume_action_not_present(self):
        for source, edges in TRANSITIONS.items():
            for action, _target in edges:
                self.assertNotEqual(
                    action, 'resume',
                    f'action {action!r} still present from {source}; '
                    'it was only used to leave AWAITING_REPLIES, which is gone',
                )

    def test_removed_actions_not_present(self):
        """assert, auto-approve, correct, refine-intent, revise-plan, plan
        were part of the old multi-state execution/intent/planning paths."""
        for source, edges in TRANSITIONS.items():
            for action, _target in edges:
                self.assertNotIn(
                    action, REMOVED_ACTIONS,
                    f'action {action!r} still present from {source}; '
                    'all task-level and multi-state actions are removed',
                )


class TestProjectLevelBacktracksPreserved(unittest.TestCase):
    """EXECUTE keeps project-level backtracks; PLAN keeps its own backtrack
    to intent. These are project-level decisions and stay — renamed as
    replan (EXECUTE→PLAN) and realign (EXECUTE→INTENT, PLAN→INTENT)."""

    def test_execute_can_replan(self):
        edges = TRANSITIONS.get('EXECUTE', [])
        replan = [(a, t) for a, t in edges if a == 'replan']
        self.assertEqual(
            replan, [('replan', 'PLAN')],
            f'EXECUTE --replan--> PLAN must be preserved '
            f'at project-level scope; got {replan}',
        )

    def test_execute_can_realign(self):
        edges = TRANSITIONS.get('EXECUTE', [])
        realign = [(a, t) for a, t in edges if a == 'realign']
        self.assertEqual(
            realign, [('realign', 'INTENT')],
            f'EXECUTE --realign--> INTENT must be preserved '
            f'at project-level scope (intent skill re-runs on backtrack); got {realign}',
        )

    def test_plan_can_realign_to_intent(self):
        edges = TRANSITIONS.get('PLAN', [])
        back = [(a, t) for a, t in edges if a == 'realign']
        self.assertEqual(
            back, [('realign', 'INTENT')],
            f'PLAN --realign--> INTENT must be preserved; got {back}',
        )


class TestHappyPathThroughNewMachine(unittest.TestCase):
    """End-to-end: INTENT → PLAN → EXECUTE → DONE."""

    def test_happy_path_reaches_done_without_any_task_state(self):
        cfa = make_initial_state()
        path = [(cfa.state, '')]

        for action in [
            'approve',  # → PLAN
            'approve',  # → EXECUTE
            'approve',  # → DONE
        ]:
            cfa = transition(cfa, action)
            path.append((cfa.state, action))

        self.assertTrue(
            is_globally_terminal(cfa.state),
            f'happy path must reach a terminal state; ended at {cfa.state}',
        )
        self.assertEqual(
            cfa.state, 'DONE',
            f'expected DONE; got {cfa.state}',
        )

        visited = {state for state, _ in path}
        for banned in REMOVED_TASK_STATES:
            self.assertNotIn(
                banned, visited,
                f'happy path must not visit removed state {banned}; '
                f'full path: {path}',
            )


# ── ApprovalGate removed ───────────────────────────────────────────────────
# The former ``TestApprovalGateMachineryRemoved`` test class proved that
# the task-level gate constants (``_MAX_DIALOG_TURNS``, ``_GATE_TEMPLATES``,
# ``_CFA_STATE_TO_PHASE``, etc.) and the ``__fallback__`` retry branch
# were dead.  ``ApprovalGate`` itself is now deleted, along with every
# one of those constants — the tests it held are redundant.


# ── Engine machinery removal ───────────────────────────────────────────────

class TestEngineFanInNoLongerUsesStateMachine(unittest.TestCase):
    """Fan-in wait is a framework-level turn-boundary concern, not a
    state-machine round-trip. Verify the engine no longer transitions
    through AWAITING_REPLIES."""

    def test_await_fan_in_does_not_call_send_and_wait_transition(self):
        from teaparty.cfa.engine import Orchestrator
        # _await_fan_in_and_reinvoke may have been removed entirely; if so,
        # the invariant is satisfied vacuously.
        func = getattr(Orchestrator, '_await_fan_in_and_reinvoke', None)
        if func is None:
            return
        src = inspect.getsource(func)
        self.assertNotIn(
            "'send-and-wait'", src,
            'fan-in must not drive state-machine transitions; '
            '"send-and-wait" action is gone',
        )
        self.assertNotIn(
            "'resume'", src,
            'fan-in must not drive state-machine transitions; '
            '"resume" action is gone',
        )
        self.assertNotIn(
            'AWAITING_REPLIES', src,
            'fan-in must not reference the removed AWAITING_REPLIES state',
        )



# ── Classifier surface ─────────────────────────────────────────────────────

class TestClassifierSurface(unittest.TestCase):
    """classify_review derives state→actions from the JSON machine, so
    removing TASK states from the JSON automatically removes them from
    the classifier. Verify the derived table carries no task-level keys."""

    def test_derived_state_actions_has_no_task_entries(self):
        from teaparty.scripts.classify_review import STATE_ACTIONS
        for banned in REMOVED_TASK_STATES:
            self.assertNotIn(
                banned, STATE_ACTIONS,
                f'STATE_ACTIONS must not carry entry for removed state {banned}; '
                'classifier derives from the JSON machine',
            )


if __name__ == '__main__':
    unittest.main()
