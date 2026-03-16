#!/usr/bin/env python3
"""Tests for issue #153: Orphan recovery should be a restart modal, not a text dialog.

The text-based orphan recovery dialog (approve/resume/abandon) is dangerous:
  - "approve" calls _set_state_direct() which bypasses the approval gate
  - The user's corrections are lost because the state jumps past the gate
  - There is no clear signal that the session died

The fix replaces this with a simple restart modal (Resume? OK/Cancel):
  - OK → resumes via _launch_resume(), orchestrator re-presents the gate naturally
  - Cancel → returns to dashboard, session stays orphaned for later

These tests verify:
  1. handle_orphan_response no longer offers "approve" as a state-advancing action
  2. The orphan UI in _update_input_area no longer shows approve/resume/abandon text
  3. _set_state_direct is removed (no direct state manipulation from the TUI)
  4. Resume is the only recovery action that changes session state
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))


def _make_cfa_state_file(infra_dir, state='INTENT_ASSERT', phase='intent'):
    """Create a .cfa-state.json file in the given infra directory."""
    cfa = {
        'state': state,
        'phase': phase,
        'actor': 'human',
        'history': [],
    }
    path = os.path.join(infra_dir, '.cfa-state.json')
    with open(path, 'w') as f:
        json.dump(cfa, f)
    return path


def _make_running_file(infra_dir, pid=99999):
    """Create a .running sentinel file."""
    path = os.path.join(infra_dir, '.running')
    with open(path, 'w') as f:
        f.write(str(pid))
    return path


@dataclass
class _FakeSession:
    """Minimal stand-in for state_reader.SessionState."""
    cfa_state: str = 'INTENT_ASSERT'
    cfa_phase: str = 'intent'
    is_orphaned: bool = True
    needs_input: bool = False
    infra_dir: str = ''
    session_id: str = 'test-session'
    project: str = 'POC'
    task: str = 'test task'
    status: str = 'active'
    worktree_path: str = ''
    dispatches: list = field(default_factory=list)


# ── Test 1: "approve" must NOT directly advance state ──────────────────────


class TestApproveDoesNotAdvanceState(unittest.TestCase):
    """Typing 'approve' in orphan recovery must not call _set_state_direct.

    Before the fix: handle_orphan_response('approve') at INTENT_ASSERT
    called _set_state_direct to jump to INTENT (phase-terminal), causing
    resume_from_disk to auto-bridge past the gate.

    After the fix: 'approve' is not a recognized recovery command. The only
    recovery actions are resume (relaunch orchestrator) or cancel/abandon.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.infra_dir = os.path.join(self.tmpdir, 'infra')
        os.makedirs(self.infra_dir)
        _make_cfa_state_file(self.infra_dir, 'INTENT_ASSERT', 'intent')
        _make_running_file(self.infra_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_approve_does_not_change_cfa_state(self):
        """'approve' must not modify .cfa-state.json — gate bypass is the bug."""
        from projects.POC.tui.orphan_recovery import handle_orphan_response

        session = _FakeSession(
            cfa_state='INTENT_ASSERT',
            cfa_phase='intent',
            infra_dir=self.infra_dir,
        )

        result = handle_orphan_response(session, 'approve')

        # After fix: 'approve' should NOT be recognized as a valid command.
        # It must not return a success message about advancing state.
        # The CfA state file must be unchanged.
        with open(os.path.join(self.infra_dir, '.cfa-state.json')) as f:
            cfa = json.load(f)

        self.assertEqual(cfa['state'], 'INTENT_ASSERT',
                         'approve must NOT advance CfA state — that bypasses the gate')

    def test_approve_not_recognized_at_plan_assert(self):
        """'approve' at PLAN_ASSERT must also not advance state."""
        from projects.POC.tui.orphan_recovery import handle_orphan_response

        _make_cfa_state_file(self.infra_dir, 'PLAN_ASSERT', 'planning')
        session = _FakeSession(
            cfa_state='PLAN_ASSERT',
            cfa_phase='planning',
            infra_dir=self.infra_dir,
        )

        handle_orphan_response(session, 'approve')

        with open(os.path.join(self.infra_dir, '.cfa-state.json')) as f:
            cfa = json.load(f)

        self.assertEqual(cfa['state'], 'PLAN_ASSERT',
                         'approve must NOT advance CfA state at PLAN_ASSERT')

    def test_approve_not_recognized_at_work_assert(self):
        """'approve' at WORK_ASSERT must also not advance state."""
        from projects.POC.tui.orphan_recovery import handle_orphan_response

        _make_cfa_state_file(self.infra_dir, 'WORK_ASSERT', 'execution')
        session = _FakeSession(
            cfa_state='WORK_ASSERT',
            cfa_phase='execution',
            infra_dir=self.infra_dir,
        )

        handle_orphan_response(session, 'approve')

        with open(os.path.join(self.infra_dir, '.cfa-state.json')) as f:
            cfa = json.load(f)

        self.assertEqual(cfa['state'], 'WORK_ASSERT',
                         'approve must NOT advance CfA state at WORK_ASSERT')


# ── Test 2: _set_state_direct must not exist ───────────────────────────────


class TestSetStateDirectRemoved(unittest.TestCase):
    """_set_state_direct must be removed from orphan_recovery.py.

    Direct CfA state manipulation from the TUI is the root cause of the
    gate-bypass bug. The TUI should never write to .cfa-state.json — only
    the orchestrator should advance CfA state.
    """

    def test_no_set_state_direct_function(self):
        """orphan_recovery module must not export _set_state_direct."""
        from projects.POC.tui import orphan_recovery
        self.assertFalse(
            hasattr(orphan_recovery, '_set_state_direct'),
            '_set_state_direct must be removed — TUI must not manipulate CfA state directly',
        )

    def test_no_approval_gate_successors(self):
        """APPROVAL_GATE_SUCCESSORS constant must be removed."""
        from projects.POC.tui import orphan_recovery
        self.assertFalse(
            hasattr(orphan_recovery, 'APPROVAL_GATE_SUCCESSORS'),
            'APPROVAL_GATE_SUCCESSORS must be removed — no gate-bypass logic should exist',
        )


# ── Test 3: Recovery only offers resume or abandon ─────────────────────────


class TestRecoveryOnlyOffersResumeOrAbandon(unittest.TestCase):
    """Orphan recovery must only offer 'resume' (relaunch orchestrator)
    or 'abandon/withdraw' (mark withdrawn). No 'approve' option.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.infra_dir = os.path.join(self.tmpdir, 'infra')
        os.makedirs(self.infra_dir)
        _make_cfa_state_file(self.infra_dir, 'INTENT_ASSERT', 'intent')
        _make_running_file(self.infra_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_resume_returns_resume_signal(self):
        """'resume' must return a ('resume', infra_dir) tuple to trigger relaunch."""
        from projects.POC.tui.orphan_recovery import handle_orphan_response

        session = _FakeSession(
            cfa_state='INTENT_ASSERT',
            infra_dir=self.infra_dir,
        )

        result = handle_orphan_response(session, 'resume')

        self.assertIsInstance(result, tuple)
        self.assertEqual(result[0], 'resume')
        self.assertEqual(result[1], self.infra_dir)

    def test_resume_does_not_modify_cfa_state(self):
        """'resume' must not change .cfa-state.json — the orchestrator handles it."""
        from projects.POC.tui.orphan_recovery import handle_orphan_response

        session = _FakeSession(
            cfa_state='INTENT_ASSERT',
            infra_dir=self.infra_dir,
        )

        handle_orphan_response(session, 'resume')

        with open(os.path.join(self.infra_dir, '.cfa-state.json')) as f:
            cfa = json.load(f)

        self.assertEqual(cfa['state'], 'INTENT_ASSERT',
                         'resume must not modify CfA state')


# ── Test 4: No text-based prompt keywords in UI ────────────────────────────


class TestNoTextBasedOrphanPrompt(unittest.TestCase):
    """The drilldown's orphan recovery UI must not show a text-based
    'approve/resume/abandon' prompt. It should show a modal instead.
    """

    def test_update_input_area_no_approve_text(self):
        """_update_input_area must not render 'approve' in orphan prompt text."""
        import inspect
        from projects.POC.tui.screens.drilldown import DrilldownScreen

        source = inspect.getsource(DrilldownScreen._update_input_area)
        self.assertNotIn("'approve'", source,
                         '_update_input_area must not mention approve — '
                         'orphan recovery uses a modal, not text commands')

    def test_submit_input_no_orphan_keyword_parsing(self):
        """_submit_input must not parse orphan recovery keywords."""
        import inspect
        from projects.POC.tui.screens.drilldown import DrilldownScreen

        source = inspect.getsource(DrilldownScreen._submit_input)
        self.assertNotIn('handle_orphan_response', source,
                         '_submit_input must not call handle_orphan_response — '
                         'orphan recovery is handled by a modal, not input parsing')


if __name__ == '__main__':
    unittest.main()
