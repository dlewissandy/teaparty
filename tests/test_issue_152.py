#!/usr/bin/env python3
"""Tests for issue #152: Orphan recovery at approval gates bypasses human review.

Verifies:
 1. handle_orphan_response() at *_ASSERT states rejects 'approve' and forces 'resume'
 2. _reconstruct_last_actor_data() finds artifacts in infra_dir (not just worktree)
 3. Non-gate states still accept resume/abandon (no regression)
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from projects.POC.tui.orphan_recovery import (
    APPROVAL_GATE_SUCCESSORS,
    handle_orphan_response,
)
from projects.POC.orchestrator.session import _reconstruct_last_actor_data
from projects.POC.scripts.cfa_state import CfaState
from projects.POC.orchestrator.phase_config import PhaseConfig


# ── Helpers ─────────────────────────────────────────────────────────────────

def _make_session(cfa_state: str, infra_dir: str, cfa_phase: str = '') -> MagicMock:
    """Build a minimal session mock for orphan_recovery."""
    session = MagicMock()
    session.cfa_state = cfa_state
    session.cfa_phase = cfa_phase or _phase_for(cfa_state)
    session.infra_dir = infra_dir
    return session


def _phase_for(state: str) -> str:
    if 'INTENT' in state or state in ('IDEA', 'PROPOSAL'):
        return 'intent'
    if 'PLAN' in state or state == 'DRAFT':
        return 'planning'
    return 'execution'


def _make_cfa_state(state: str, phase: str = '') -> CfaState:
    if not phase:
        phase = _phase_for(state)
    return CfaState(
        phase=phase,
        state=state,
        actor='human',
        history=[],
        backtrack_count=0,
    )


def _make_config() -> PhaseConfig:
    poc_root = str(Path(__file__).parent.parent / 'projects' / 'POC')
    return PhaseConfig(poc_root)


# ── Test: Orphan recovery rejects 'approve' at approval gates ──────────────

class TestOrphanRecoveryRejectsApproveAtGates(unittest.TestCase):
    """At *_ASSERT states, 'approve' must NOT bypass the CfA state machine.

    The only valid actions at an orphaned approval gate should be 'resume'
    (which re-launches the orchestrator with the full ApprovalGate) or
    'abandon' (which withdraws).
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        cfa_data = {
            'phase': 'intent', 'state': 'INTENT_ASSERT',
            'actor': 'human', 'history': [], 'backtrack_count': 0,
        }
        with open(os.path.join(self.tmpdir, '.cfa-state.json'), 'w') as f:
            json.dump(cfa_data, f)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_approve_rejected_at_intent_assert(self):
        session = _make_session('INTENT_ASSERT', self.tmpdir)
        result = handle_orphan_response(session, 'approve')
        self.assertIsInstance(result, str)
        self.assertNotIn('Advanced', result)
        self.assertIn('resume', result.lower())

    def test_approve_rejected_at_plan_assert(self):
        session = _make_session('PLAN_ASSERT', self.tmpdir)
        result = handle_orphan_response(session, 'approve')
        self.assertIsInstance(result, str)
        self.assertNotIn('Advanced', result)
        self.assertIn('resume', result.lower())

    def test_approve_rejected_at_work_assert(self):
        session = _make_session('WORK_ASSERT', self.tmpdir)
        result = handle_orphan_response(session, 'approve')
        self.assertIsInstance(result, str)
        self.assertNotIn('Advanced', result)
        self.assertIn('resume', result.lower())

    def test_resume_still_works_at_gates(self):
        session = _make_session('INTENT_ASSERT', self.tmpdir)
        result = handle_orphan_response(session, 'resume')
        self.assertIsInstance(result, tuple)
        self.assertEqual(result[0], 'resume')

    def test_abandon_still_works_at_gates(self):
        session = _make_session('INTENT_ASSERT', self.tmpdir)
        result = handle_orphan_response(session, 'abandon')
        self.assertIsInstance(result, str)
        self.assertIn('withdrawn', result.lower())


# ── Test: _reconstruct_last_actor_data finds artifacts in infra_dir ────────

class TestReconstructLastActorDataInfraDir(unittest.TestCase):
    """_reconstruct_last_actor_data must find artifacts in infra_dir.

    Issue #147 moved session artifacts to infra_dir.  The reconstruction
    function must check infra_dir, not just worktree_path.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.worktree = os.path.join(self.tmpdir, 'worktree')
        self.infra_dir = os.path.join(self.tmpdir, 'infra')
        os.makedirs(self.worktree)
        os.makedirs(self.infra_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_finds_intent_in_infra_dir(self):
        Path(self.infra_dir, 'INTENT.md').write_text('# Intent\nTest')
        cfa = _make_cfa_state('INTENT_ASSERT', 'intent')
        config = _make_config()
        data = _reconstruct_last_actor_data(
            cfa, config, self.worktree, self.infra_dir,
        )
        self.assertIn('artifact_path', data)
        self.assertTrue(os.path.exists(data['artifact_path']))

    def test_finds_plan_in_infra_dir(self):
        Path(self.infra_dir, 'PLAN.md').write_text('# Plan\nTest')
        cfa = _make_cfa_state('PLAN_ASSERT', 'planning')
        config = _make_config()
        data = _reconstruct_last_actor_data(
            cfa, config, self.worktree, self.infra_dir,
        )
        self.assertIn('artifact_path', data)
        self.assertTrue(os.path.exists(data['artifact_path']))


# ── Test: Non-gate orphan states unaffected ────────────────────────────────

class TestOrphanRecoveryNonGateStatesUnchanged(unittest.TestCase):
    """Mid-execution states should still offer resume/abandon."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_mid_execution_resume(self):
        session = _make_session('TASK_IN_PROGRESS', self.tmpdir)
        result = handle_orphan_response(session, 'resume')
        self.assertIsInstance(result, tuple)
        self.assertEqual(result[0], 'resume')

    def test_mid_execution_abandon(self):
        session = _make_session('TASK_IN_PROGRESS', self.tmpdir)
        result = handle_orphan_response(session, 'abandon')
        self.assertIsInstance(result, str)
        self.assertIn('withdrawn', result.lower())


if __name__ == '__main__':
    unittest.main()
