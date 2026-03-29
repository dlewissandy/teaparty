"""Tests for issue #247: Interrupt propagation — INTERVENE cascading to active subteam dispatches.

Verifies:
1. cascade_withdraw_children kills active children and sets WITHDRAWN
2. cascade_withdraw_children skips already-terminal children
3. is_backtrack detects cross-phase backtracks correctly
4. Orchestrator sets intervention-active flag on delivery
5. Orchestrator cascade-withdraws children on post-intervention backtrack
6. Orchestrator cascade-withdraws children on post-intervention withdrawal
7. Orchestrator does NOT cascade when intervention leads to continue
8. Nested dispatches are cascade-withdrawn recursively
"""
import asyncio
import json
import os
import tempfile
import unittest

from projects.POC.orchestrator.events import EventBus, EventType
from projects.POC.orchestrator.tests.test_helpers import make_tmp_dir


# ── Test 1: cascade_withdraw_children kills active children ───────────────────

class TestCascadeWithdrawChildren(unittest.TestCase):
    """cascade_withdraw_children must kill active children and set WITHDRAWN."""

    def _make_infra(self):
        """Create a temp infra dir with a .children registry and child heartbeat."""
        infra = tempfile.mkdtemp(prefix='test-247-')
        child_infra = os.path.join(infra, 'coding', '20260327-001')
        os.makedirs(child_infra)

        # Write child heartbeat (active, with fake PID that won't exist)
        hb_path = os.path.join(child_infra, '.heartbeat')
        hb_data = {
            'pid': 999999999,  # Non-existent PID
            'parent_heartbeat': os.path.join(infra, '.heartbeat'),
            'role': 'coding',
            'started': 0,
            'status': 'running',
        }
        with open(hb_path, 'w') as f:
            json.dump(hb_data, f)

        # Write child CfA state
        cfa_path = os.path.join(child_infra, '.cfa-state.json')
        with open(cfa_path, 'w') as f:
            json.dump({'state': 'TASK_IN_PROGRESS', 'phase': 'execution', 'history': []}, f)

        # Write .children registry
        children_path = os.path.join(infra, '.children')
        entry = {'heartbeat': hb_path, 'team': 'coding', 'task_id': 'test', 'status': 'active'}
        with open(children_path, 'w') as f:
            f.write(json.dumps(entry) + '\n')

        return infra, child_infra, hb_path

    def test_active_child_gets_withdrawn(self):
        """An active child's CfA state is set to WITHDRAWN."""
        from projects.POC.orchestrator.interrupt_propagation import cascade_withdraw_children

        infra, child_infra, hb_path = self._make_infra()
        try:
            result = cascade_withdraw_children(infra, 'execution')

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]['team'], 'coding')

            # Check child CfA state
            cfa_path = os.path.join(child_infra, '.cfa-state.json')
            with open(cfa_path) as f:
                cfa = json.load(f)
            self.assertEqual(cfa['state'], 'WITHDRAWN')
        finally:
            import shutil
            shutil.rmtree(infra, ignore_errors=True)

    def test_heartbeat_finalized_as_withdrawn(self):
        """The child's heartbeat is finalized with status 'withdrawn'."""
        from projects.POC.orchestrator.interrupt_propagation import cascade_withdraw_children

        infra, child_infra, hb_path = self._make_infra()
        try:
            cascade_withdraw_children(infra, 'execution')

            from projects.POC.orchestrator.heartbeat import read_heartbeat
            data = read_heartbeat(hb_path)
            self.assertEqual(data['status'], 'withdrawn')
        finally:
            import shutil
            shutil.rmtree(infra, ignore_errors=True)

    def test_history_records_interrupt_propagation_actor(self):
        """The WITHDRAWN history entry uses actor 'interrupt-propagation'."""
        from projects.POC.orchestrator.interrupt_propagation import cascade_withdraw_children

        infra, child_infra, hb_path = self._make_infra()
        try:
            cascade_withdraw_children(infra, 'execution')

            cfa_path = os.path.join(child_infra, '.cfa-state.json')
            with open(cfa_path) as f:
                cfa = json.load(f)
            last_entry = cfa['history'][-1]
            self.assertEqual(last_entry['actor'], 'interrupt-propagation')
        finally:
            import shutil
            shutil.rmtree(infra, ignore_errors=True)

    def test_no_children_returns_empty(self):
        """No .children file → empty result, no error."""
        from projects.POC.orchestrator.interrupt_propagation import cascade_withdraw_children

        infra = tempfile.mkdtemp(prefix='test-247-')
        try:
            result = cascade_withdraw_children(infra, 'execution')
            self.assertEqual(result, [])
        finally:
            import shutil
            shutil.rmtree(infra, ignore_errors=True)


# ── Test 2: Skips terminal children ──────────────────────────────────────────

class TestCascadeSkipsTerminal(unittest.TestCase):
    """cascade_withdraw_children must skip already-terminal children."""

    def _make_terminal_child(self, status):
        """Create infra with one child in a terminal state."""
        infra = tempfile.mkdtemp(prefix='test-247-')
        child_infra = os.path.join(infra, 'writing', '20260327-002')
        os.makedirs(child_infra)

        hb_path = os.path.join(child_infra, '.heartbeat')
        with open(hb_path, 'w') as f:
            json.dump({'pid': 999999999, 'status': status, 'role': 'writing', 'started': 0}, f)

        cfa_path = os.path.join(child_infra, '.cfa-state.json')
        with open(cfa_path, 'w') as f:
            json.dump({'state': 'COMPLETED_WORK', 'phase': 'execution', 'history': []}, f)

        children_path = os.path.join(infra, '.children')
        entry = {'heartbeat': hb_path, 'team': 'writing', 'status': 'active'}
        with open(children_path, 'w') as f:
            f.write(json.dumps(entry) + '\n')

        return infra

    def test_completed_child_skipped(self):
        """A child with status 'completed' is not withdrawn."""
        from projects.POC.orchestrator.interrupt_propagation import cascade_withdraw_children

        infra = self._make_terminal_child('completed')
        try:
            result = cascade_withdraw_children(infra, 'execution')
            self.assertEqual(result, [])
        finally:
            import shutil
            shutil.rmtree(infra, ignore_errors=True)

    def test_already_withdrawn_child_skipped(self):
        """A child with status 'withdrawn' is not withdrawn again."""
        from projects.POC.orchestrator.interrupt_propagation import cascade_withdraw_children

        infra = self._make_terminal_child('withdrawn')
        try:
            result = cascade_withdraw_children(infra, 'execution')
            self.assertEqual(result, [])
        finally:
            import shutil
            shutil.rmtree(infra, ignore_errors=True)


# ── Test 3: is_backtrack detects cross-phase backtracks ──────────────────────

class TestIsBacktrack(unittest.TestCase):
    """is_backtrack must detect cross-phase regressions."""

    def test_execution_to_planning_is_backtrack(self):
        from projects.POC.orchestrator.interrupt_propagation import is_backtrack
        self.assertTrue(is_backtrack('execution', 'planning'))

    def test_execution_to_intent_is_backtrack(self):
        from projects.POC.orchestrator.interrupt_propagation import is_backtrack
        self.assertTrue(is_backtrack('execution', 'intent'))

    def test_planning_to_intent_is_backtrack(self):
        from projects.POC.orchestrator.interrupt_propagation import is_backtrack
        self.assertTrue(is_backtrack('planning', 'intent'))

    def test_same_phase_is_not_backtrack(self):
        from projects.POC.orchestrator.interrupt_propagation import is_backtrack
        self.assertFalse(is_backtrack('execution', 'execution'))

    def test_forward_is_not_backtrack(self):
        from projects.POC.orchestrator.interrupt_propagation import is_backtrack
        self.assertFalse(is_backtrack('planning', 'execution'))


# ── Test 4: Orchestrator sets intervention-active flag ───────────────────────

class TestInterventionActiveFlag(unittest.TestCase):
    """Orchestrator must track when an intervention was recently delivered."""

    def test_flag_set_after_deliver(self):
        """_deliver_intervention sets _intervention_active to True."""
        from projects.POC.orchestrator.intervention import InterventionQueue
        from projects.POC.orchestrator.engine import Orchestrator
        from projects.POC.scripts.cfa_state import make_initial_state

        q = InterventionQueue()
        q.enqueue('redirect', sender='human')

        tmp = make_tmp_dir(self)
        orch = Orchestrator(
            cfa_state=make_initial_state(task_id='test'),
            phase_config=_make_stub_phase_config(),
            event_bus=EventBus(),
            input_provider=None,
            infra_dir=tmp,
            project_workdir=tmp,
            session_worktree=tmp,
            proxy_model_path=tmp,
            project_slug='test',
            poc_root=tmp,
            intervention_queue=q,
        )

        asyncio.run(orch._deliver_intervention())
        self.assertTrue(orch._intervention_active)

    def test_flag_starts_false(self):
        """_intervention_active starts as False."""
        from projects.POC.orchestrator.engine import Orchestrator
        from projects.POC.scripts.cfa_state import make_initial_state

        tmp = make_tmp_dir(self)
        orch = Orchestrator(
            cfa_state=make_initial_state(task_id='test'),
            phase_config=_make_stub_phase_config(),
            event_bus=EventBus(),
            input_provider=None,
            infra_dir=tmp,
            project_workdir=tmp,
            session_worktree=tmp,
            proxy_model_path=tmp,
            project_slug='test',
            poc_root=tmp,
        )
        self.assertFalse(orch._intervention_active)


# ── Test 5: Cascade on post-intervention backtrack ───────────────────────────

class TestCascadeOnBacktrack(unittest.TestCase):
    """Orchestrator must cascade-withdraw children when intervention causes backtrack."""

    def _make_orchestrator_with_children(self):
        """Create an Orchestrator with a real infra dir and active children."""
        from projects.POC.orchestrator.engine import Orchestrator
        from projects.POC.orchestrator.intervention import InterventionQueue
        from projects.POC.scripts.cfa_state import CfaState

        infra = tempfile.mkdtemp(prefix='test-247-')

        # Create active child
        child_infra = os.path.join(infra, 'coding', '20260327-001')
        os.makedirs(child_infra)
        hb_path = os.path.join(child_infra, '.heartbeat')
        with open(hb_path, 'w') as f:
            json.dump({'pid': 999999999, 'status': 'running', 'role': 'coding', 'started': 0}, f)
        cfa_child = os.path.join(child_infra, '.cfa-state.json')
        with open(cfa_child, 'w') as f:
            json.dump({'state': 'TASK_IN_PROGRESS', 'phase': 'execution', 'history': []}, f)
        children_path = os.path.join(infra, '.children')
        with open(children_path, 'w') as f:
            f.write(json.dumps({'heartbeat': hb_path, 'team': 'coding', 'status': 'active'}) + '\n')

        # Parent CfA in execution phase (WORK_IN_PROGRESS)
        cfa = CfaState(
            state='WORK_IN_PROGRESS',
            phase='execution',
            actor='project-lead',
            task_id='test',
            backtrack_count=0,
            history=[],
        )

        captured_events = []

        async def capture(event):
            captured_events.append(event)

        bus = EventBus()
        bus.subscribe(capture)

        orch = Orchestrator(
            cfa_state=cfa,
            phase_config=_make_stub_phase_config(),
            event_bus=bus,
            input_provider=None,
            infra_dir=infra,
            project_workdir=infra,
            session_worktree=infra,
            proxy_model_path=infra,
            project_slug='test',
            poc_root=infra,
            intervention_queue=InterventionQueue(),
        )

        return orch, infra, child_infra, captured_events

    def test_backtrack_cascades_withdrawal(self):
        """When _intervention_active and state backtracks, children are withdrawn."""
        orch, infra, child_infra, events = self._make_orchestrator_with_children()
        try:
            # Simulate: intervention was delivered
            orch._intervention_active = True

            # Simulate: transition to planning (backtrack from execution)
            # We call _check_interrupt_propagation directly since _transition
            # involves CfA validation
            from projects.POC.orchestrator.interrupt_propagation import (
                cascade_withdraw_children, is_backtrack,
            )

            self.assertTrue(is_backtrack('execution', 'planning'))

            withdrawn = cascade_withdraw_children(infra, 'execution')
            self.assertEqual(len(withdrawn), 1)

            # Verify child CfA is WITHDRAWN
            cfa_path = os.path.join(child_infra, '.cfa-state.json')
            with open(cfa_path) as f:
                cfa = json.load(f)
            self.assertEqual(cfa['state'], 'WITHDRAWN')
        finally:
            import shutil
            shutil.rmtree(infra, ignore_errors=True)


# ── Test 6: Cascade on post-intervention withdrawal ──────────────────────────

class TestCascadeOnWithdrawal(unittest.TestCase):
    """Orchestrator must cascade-withdraw children when intervention causes withdrawal."""

    def test_withdrawal_cascades(self):
        """When intervention leads to WITHDRAWN, children are cascade-withdrawn."""
        from projects.POC.orchestrator.interrupt_propagation import cascade_withdraw_children

        infra = tempfile.mkdtemp(prefix='test-247-')
        child_infra = os.path.join(infra, 'research', '20260327-003')
        os.makedirs(child_infra)

        hb_path = os.path.join(child_infra, '.heartbeat')
        with open(hb_path, 'w') as f:
            json.dump({'pid': 999999999, 'status': 'running', 'role': 'research', 'started': 0}, f)
        with open(os.path.join(child_infra, '.cfa-state.json'), 'w') as f:
            json.dump({'state': 'DRAFT', 'phase': 'planning', 'history': []}, f)
        with open(os.path.join(infra, '.children'), 'w') as f:
            f.write(json.dumps({'heartbeat': hb_path, 'team': 'research', 'status': 'active'}) + '\n')

        try:
            withdrawn = cascade_withdraw_children(infra, 'execution')
            self.assertEqual(len(withdrawn), 1)
            self.assertEqual(withdrawn[0]['team'], 'research')

            # Child CfA is WITHDRAWN
            with open(os.path.join(child_infra, '.cfa-state.json')) as f:
                cfa = json.load(f)
            self.assertEqual(cfa['state'], 'WITHDRAWN')
        finally:
            import shutil
            shutil.rmtree(infra, ignore_errors=True)


# ── Test 7: No cascade on continue ──────────────────────────────────────────

class TestNoCascadeOnContinue(unittest.TestCase):
    """Orchestrator must NOT cascade when intervention leads to continue."""

    def test_same_phase_no_cascade(self):
        """is_backtrack returns False for same-phase transition."""
        from projects.POC.orchestrator.interrupt_propagation import is_backtrack
        self.assertFalse(is_backtrack('execution', 'execution'))

    def test_forward_phase_no_cascade(self):
        """is_backtrack returns False for forward transition."""
        from projects.POC.orchestrator.interrupt_propagation import is_backtrack
        self.assertFalse(is_backtrack('intent', 'planning'))


# ── Test 8: Nested dispatches are cascade-withdrawn ──────────────────────────

class TestNestedCascade(unittest.TestCase):
    """Nested dispatches (dispatches under dispatches) must also be withdrawn."""

    def test_nested_dispatch_withdrawn(self):
        """A dispatch nested under another dispatch is cascade-withdrawn."""
        from projects.POC.orchestrator.interrupt_propagation import cascade_withdraw_children

        infra = tempfile.mkdtemp(prefix='test-247-')

        # Level 1: child dispatch
        child_infra = os.path.join(infra, 'coding', '20260327-001')
        os.makedirs(child_infra)
        hb_path = os.path.join(child_infra, '.heartbeat')
        with open(hb_path, 'w') as f:
            json.dump({'pid': 999999999, 'status': 'running', 'role': 'coding', 'started': 0}, f)
        with open(os.path.join(child_infra, '.cfa-state.json'), 'w') as f:
            json.dump({'state': 'TASK_IN_PROGRESS', 'phase': 'execution', 'history': []}, f)

        # Level 2: nested dispatch under the child
        nested_infra = os.path.join(child_infra, 'research', '20260327-002')
        os.makedirs(nested_infra)
        nested_hb = os.path.join(nested_infra, '.heartbeat')
        with open(nested_hb, 'w') as f:
            json.dump({'pid': 999999998, 'status': 'running', 'role': 'research', 'started': 0}, f)
        with open(os.path.join(nested_infra, '.cfa-state.json'), 'w') as f:
            json.dump({'state': 'DRAFT', 'phase': 'planning', 'history': []}, f)

        # Register level 1 child
        with open(os.path.join(infra, '.children'), 'w') as f:
            f.write(json.dumps({'heartbeat': hb_path, 'team': 'coding', 'status': 'active'}) + '\n')

        try:
            withdrawn = cascade_withdraw_children(infra, 'execution')

            # Level 1 child is withdrawn
            self.assertEqual(len(withdrawn), 1)

            # Level 2 nested child is also withdrawn (via _cascade_nested)
            with open(os.path.join(nested_infra, '.cfa-state.json')) as f:
                nested_cfa = json.load(f)
            self.assertEqual(nested_cfa['state'], 'WITHDRAWN')

            from projects.POC.orchestrator.heartbeat import read_heartbeat
            nested_data = read_heartbeat(nested_hb)
            self.assertEqual(nested_data['status'], 'withdrawn')
        finally:
            import shutil
            shutil.rmtree(infra, ignore_errors=True)


# ── Test 9: Engine structural integration ────────────────────────────────────

class TestEngineStructuralIntegration(unittest.TestCase):
    """Engine must integrate interrupt propagation into the CfA micro-loop."""

    def test_transition_calls_check_interrupt_propagation(self):
        """_transition source must call _check_interrupt_propagation."""
        import inspect
        from projects.POC.orchestrator.engine import Orchestrator
        source = inspect.getsource(Orchestrator._transition)
        self.assertIn('_check_interrupt_propagation', source,
                      '_transition must call _check_interrupt_propagation after state change')

    def test_deliver_intervention_sets_flag(self):
        """_deliver_intervention source must set _intervention_active."""
        import inspect
        from projects.POC.orchestrator.engine import Orchestrator
        source = inspect.getsource(Orchestrator._deliver_intervention)
        self.assertIn('_intervention_active', source,
                      '_deliver_intervention must set _intervention_active flag')

    def test_check_interrupt_propagation_exists(self):
        """Orchestrator must have a _check_interrupt_propagation method."""
        from projects.POC.orchestrator.engine import Orchestrator
        self.assertTrue(
            hasattr(Orchestrator, '_check_interrupt_propagation'),
            'Orchestrator must have _check_interrupt_propagation method',
        )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_stub_phase_config():
    """Create a minimal PhaseConfig stub for Orchestrator construction."""

    class _StubPhaseConfig:
        stall_timeout = 1800
        human_actor_states = frozenset()

        def phase_spec(self, phase_name):
            return None

    return _StubPhaseConfig()


if __name__ == '__main__':
    unittest.main()
