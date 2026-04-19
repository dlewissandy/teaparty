#!/usr/bin/env python3
"""Issue #418: Remove task-level CfA state machine.

The execution phase keeps exactly one non-gate non-terminal state
(WORK_IN_PROGRESS). All TASK_* states, FAILED_TASK, COMPLETED_TASK,
AWAITING_REPLIES, and the actors execution_worker/execution_lead are
removed from the state machine. Five scope-violating edges that allowed
task-level decisions to change project-level state are gone. The probe-
loop / retry machinery in ApprovalGate (_MAX_DIALOG_TURNS,
_MAX_FALLBACK_RETRIES, _NEVER_ESCALATE_STATES, __fallback__) is deleted.

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
})

REMOVED_EXECUTION_ACTORS = frozenset({'execution_worker', 'execution_lead'})

REMOVED_ACTIONS = frozenset({'send-and-wait', 'resume'})


# ── State machine structural invariants ────────────────────────────────────

class TestExecutionPhaseShape(unittest.TestCase):
    """The execution phase reduces to {WORK_IN_PROGRESS, WORK_ASSERT,
    COMPLETED_WORK, WITHDRAWN}."""

    def test_execution_phase_has_exactly_four_states(self):
        self.assertEqual(
            set(EXECUTION_STATES),
            {'WORK_IN_PROGRESS', 'WORK_ASSERT', 'COMPLETED_WORK', 'WITHDRAWN'},
            f'execution phase must contain only four states, got {sorted(EXECUTION_STATES)}',
        )

    def test_no_task_level_states_in_any_phase(self):
        for state in REMOVED_TASK_STATES:
            self.assertNotIn(
                state, ALL_STATES,
                f'state {state!r} was supposed to be removed but is still defined',
            )

    def test_no_transition_targets_a_removed_task_state(self):
        for source, edges in TRANSITIONS.items():
            for action, target, _actor in edges:
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
    """PLAN --delegate--> WORK_IN_PROGRESS (replacing PLAN --delegate--> TASK)."""

    def test_plan_delegates_to_work_in_progress(self):
        plan_edges = TRANSITIONS.get('PLAN', [])
        delegate_targets = [
            target for action, target, _actor in plan_edges
            if action == 'delegate'
        ]
        self.assertEqual(
            delegate_targets, ['WORK_IN_PROGRESS'],
            'PLAN must delegate directly to WORK_IN_PROGRESS — got '
            f'{delegate_targets}',
        )

    def test_work_in_progress_outgoing_edges_are_exact(self):
        """WORK_IN_PROGRESS retains only: assert, auto-approve, backtrack, withdraw."""
        edges = TRANSITIONS.get('WORK_IN_PROGRESS', [])
        action_to_target = {action: target for action, target, _actor in edges}

        self.assertEqual(
            action_to_target.get('assert'), 'WORK_ASSERT',
            f'WORK_IN_PROGRESS --assert--> must go to WORK_ASSERT, got '
            f'{action_to_target.get("assert")}',
        )
        self.assertEqual(
            action_to_target.get('auto-approve'), 'COMPLETED_WORK',
            f'WORK_IN_PROGRESS --auto-approve--> must go to COMPLETED_WORK, '
            f'got {action_to_target.get("auto-approve")}',
        )
        self.assertEqual(
            action_to_target.get('withdraw'), 'WITHDRAWN',
            f'WORK_IN_PROGRESS --withdraw--> must go to WITHDRAWN, got '
            f'{action_to_target.get("withdraw")}',
        )

        self.assertNotIn(
            'delegate', action_to_target,
            'WORK_IN_PROGRESS --delegate--> edge (to removed TASK state) '
            'must be gone',
        )
        self.assertNotIn(
            'send-and-wait', action_to_target,
            'WORK_IN_PROGRESS --send-and-wait--> edge must be gone; '
            'fan-in happens at the turn boundary, not via state transitions',
        )


class TestExecutionActorsRemoved(unittest.TestCase):
    """Actors execution_worker / execution_lead must not appear in any edge."""

    def test_no_transition_names_a_removed_actor(self):
        for source, edges in TRANSITIONS.items():
            for action, target, actor in edges:
                self.assertNotIn(
                    actor, REMOVED_EXECUTION_ACTORS,
                    f'transition {source} --{action}--> {target} actor={actor!r} '
                    'uses a removed execution actor',
                )


class TestActionsRemoved(unittest.TestCase):
    """send-and-wait and resume were state-machine-only mechanics for
    TASK_IN_PROGRESS ↔ AWAITING_REPLIES. Both must be gone."""

    def test_send_and_wait_action_not_present(self):
        for source, edges in TRANSITIONS.items():
            for action, _target, _actor in edges:
                self.assertNotEqual(
                    action, 'send-and-wait',
                    f'action {action!r} still present from {source}; '
                    'fan-in must happen at the turn boundary, not as a '
                    'state transition',
                )

    def test_resume_action_not_present(self):
        for source, edges in TRANSITIONS.items():
            for action, _target, _actor in edges:
                self.assertNotEqual(
                    action, 'resume',
                    f'action {action!r} still present from {source}; '
                    'it was only used to leave AWAITING_REPLIES, which is gone',
                )


class TestScopeViolatingEdgesRemoved(unittest.TestCase):
    """The five edges that let task-level decisions change project-level
    state, enumerated in issue #418, must all be absent."""

    # (from_state, action, to_state) — these were the scope-violating edges.
    SCOPE_VIOLATORS = [
        ('TASK_ESCALATE', 'complete', 'COMPLETED_WORK'),
        ('TASK_ASSERT', 'revise-plan', 'PLANNING_RESPONSE'),
        ('TASK_ASSERT', 'refine-intent', 'INTENT_RESPONSE'),
        ('TASK_QUESTION', 'backtrack', 'PLANNING_QUESTION'),
        ('FAILED_TASK', 'backtrack', 'PLANNING_QUESTION'),
    ]

    def test_no_scope_violating_edge_survives(self):
        for source, action, target in self.SCOPE_VIOLATORS:
            if source not in TRANSITIONS:
                continue  # source state was removed entirely — edge is gone
            edges = TRANSITIONS[source]
            matches = [
                (a, t) for a, t, _actor in edges
                if a == action and t == target
            ]
            self.assertFalse(
                matches,
                f'scope-violating edge {source} --{action}--> {target} '
                'must be removed',
            )


class TestProjectLevelBacktracksPreserved(unittest.TestCase):
    """WORK_ASSERT keeps the project-level backtracks; PLAN_ASSERT keeps
    refine-intent. These are project-level decisions and stay."""

    def test_work_assert_can_revise_plan(self):
        edges = TRANSITIONS.get('WORK_ASSERT', [])
        revise = [(a, t) for a, t, _ in edges if a == 'revise-plan']
        self.assertEqual(
            revise, [('revise-plan', 'PLANNING_RESPONSE')],
            f'WORK_ASSERT --revise-plan--> PLANNING_RESPONSE must be preserved '
            f'at project-level scope; got {revise}',
        )

    def test_work_assert_can_refine_intent(self):
        edges = TRANSITIONS.get('WORK_ASSERT', [])
        refine = [(a, t) for a, t, _ in edges if a == 'refine-intent']
        self.assertEqual(
            refine, [('refine-intent', 'INTENT_RESPONSE')],
            f'WORK_ASSERT --refine-intent--> INTENT_RESPONSE must be preserved '
            f'at project-level scope; got {refine}',
        )

    def test_plan_assert_can_refine_intent(self):
        edges = TRANSITIONS.get('PLAN_ASSERT', [])
        refine = [(a, t) for a, t, _ in edges if a == 'refine-intent']
        self.assertEqual(
            refine, [('refine-intent', 'INTENT_RESPONSE')],
            f'PLAN_ASSERT --refine-intent--> INTENT_RESPONSE must be preserved; '
            f'got {refine}',
        )


class TestHappyPathThroughNewMachine(unittest.TestCase):
    """End-to-end: IDEA → PROPOSAL → INTENT → DRAFT → PLAN →
    WORK_IN_PROGRESS → WORK_ASSERT → COMPLETED_WORK."""

    def test_happy_path_reaches_completed_work_without_any_task_state(self):
        cfa = make_initial_state()
        path = [(cfa.state, '')]

        for action in [
            'propose', 'auto-approve',  # → INTENT
            'plan', 'auto-approve',     # → PLAN
            'delegate',                 # → WORK_IN_PROGRESS (was TASK)
            'assert',                   # → WORK_ASSERT
            'approve',                  # → COMPLETED_WORK
        ]:
            cfa = transition(cfa, action)
            path.append((cfa.state, action))

        self.assertTrue(
            is_globally_terminal(cfa.state),
            f'happy path must reach a terminal state; ended at {cfa.state}',
        )
        self.assertEqual(
            cfa.state, 'COMPLETED_WORK',
            f'expected COMPLETED_WORK; got {cfa.state}',
        )

        visited = {state for state, _ in path}
        for banned in REMOVED_TASK_STATES:
            self.assertNotIn(
                banned, visited,
                f'happy path must not visit removed state {banned}; '
                f'full path: {path}',
            )


# ── ApprovalGate machinery removal ─────────────────────────────────────────

class TestApprovalGateMachineryRemoved(unittest.TestCase):
    """`_MAX_DIALOG_TURNS`, `_MAX_FALLBACK_RETRIES`, `_NEVER_ESCALATE_STATES`,
    and the `__fallback__` retry branch are all dead with task-level gates
    gone. Verify the module no longer carries them."""

    def test_max_dialog_turns_constant_absent(self):
        from teaparty.cfa import actors
        self.assertFalse(
            hasattr(actors, '_MAX_DIALOG_TURNS'),
            '_MAX_DIALOG_TURNS module constant must be removed; '
            'probe-loop cap was only needed for task-level retry loops',
        )

    def test_max_fallback_retries_constant_absent(self):
        from teaparty.cfa import actors
        self.assertFalse(
            hasattr(actors, '_MAX_FALLBACK_RETRIES'),
            '_MAX_FALLBACK_RETRIES module constant must be removed',
        )

    def test_never_escalate_states_absent_or_empty(self):
        from teaparty.cfa import actors
        states = getattr(actors, '_NEVER_ESCALATE_STATES', None)
        if states is None:
            return  # preferred: constant deleted entirely
        self.assertEqual(
            set(states), set(),
            f'_NEVER_ESCALATE_STATES must be empty or removed; '
            f'got {sorted(states)}. No task-level gates remain to mark.',
        )

    def test_approval_gate_run_source_has_no_fallback_branch(self):
        from teaparty.cfa import actors
        src = inspect.getsource(actors.ApprovalGate.run)
        self.assertNotIn(
            '__fallback__', src,
            'ApprovalGate.run must not branch on __fallback__; the retry '
            'machinery was part of the task-level loop and is removed',
        )
        self.assertNotIn(
            '_MAX_DIALOG_TURNS', src,
            'ApprovalGate.run must not cap dialog turns; probe-loop cap removed',
        )

    def test_gate_templates_have_no_task_level_entries(self):
        from teaparty.cfa import actors
        templates = getattr(actors, '_GATE_TEMPLATES', {})
        for banned in ('TASK_ASSERT', 'TASK_ESCALATE'):
            self.assertNotIn(
                banned, templates,
                f'_GATE_TEMPLATES entry for {banned} must be removed; '
                'no task-level gates remain',
            )

    def test_cfa_state_to_phase_has_no_task_level_entries(self):
        from teaparty.cfa import actors
        mapping = getattr(actors, '_CFA_STATE_TO_PHASE', {})
        for banned in ('TASK_ASSERT', 'TASK_ESCALATE'):
            self.assertNotIn(
                banned, mapping,
                f'_CFA_STATE_TO_PHASE entry for {banned} must be removed',
            )


# ── Engine machinery removal ───────────────────────────────────────────────

class TestEngineFanInNoLongerUsesStateMachine(unittest.TestCase):
    """Fan-in wait is a framework-level turn-boundary concern, not a
    state-machine round-trip. Verify the engine no longer transitions
    through AWAITING_REPLIES."""

    def test_await_fan_in_does_not_call_send_and_wait_transition(self):
        from teaparty.cfa.engine import Orchestrator
        src = inspect.getsource(Orchestrator._await_fan_in_and_reinvoke)
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

    def test_work_escalation_states_empty_or_absent(self):
        from teaparty.cfa import engine
        states = getattr(engine, 'WORK_ESCALATION_STATES', None)
        if states is None:
            return
        self.assertEqual(
            set(states), set(),
            f'WORK_ESCALATION_STATES must be empty or removed; got '
            f'{sorted(states)}. TASK_ESCALATE is gone; work-level '
            'escalations are no longer a category.',
        )


class TestEngineCommitsArtifactsDuringExecution(unittest.TestCase):
    """_commit_artifacts was keyed on TASK_ASSERT — with that state gone
    the commit must fire during the execution phase some other way
    (per-turn commit while in WORK_IN_PROGRESS is the plan)."""

    def test_commit_artifacts_does_not_key_on_removed_state(self):
        from teaparty.cfa.engine import Orchestrator
        src = inspect.getsource(Orchestrator._commit_artifacts)
        self.assertNotIn(
            "'TASK_ASSERT'", src,
            '_commit_artifacts must not key on the removed TASK_ASSERT state; '
            'commits must fire while the CfA is in WORK_IN_PROGRESS or upon '
            'entering WORK_ASSERT',
        )


class TestSessionExecuteOnlyUsesNewStartState(unittest.TestCase):
    """Session.execute_only jumped directly to the old 'TASK' state;
    post-change it must land in 'WORK_IN_PROGRESS' instead."""

    def test_execute_only_jumps_to_work_in_progress(self):
        from teaparty.cfa import session
        src = inspect.getsource(session.Session.run)
        self.assertNotIn(
            "set_state_direct(cfa, 'TASK')", src,
            "execute_only path must not jump to the removed 'TASK' state",
        )
        self.assertIn(
            "set_state_direct(cfa, 'WORK_IN_PROGRESS')", src,
            "execute_only path must jump to 'WORK_IN_PROGRESS'",
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
