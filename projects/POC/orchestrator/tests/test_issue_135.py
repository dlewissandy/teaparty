#!/usr/bin/env python3
"""Tests for Issue #135: Add withdraw button to TUI dashboard and drilldown views.

Covers:
 1. withdraw_session() sets CfA state to WITHDRAWN and persists it
 2. withdraw_session() kills running subprocess PIDs (session + dispatches)
 3. withdraw_session() cleans up sentinel files (.running, .input-request.json)
    but leaves worktree intact
 4. withdraw_session() emits SESSION_COMPLETED with terminal_state=WITHDRAWN
 5. Dashboard screen has a 'w' binding mapped to withdraw action
 6. Drilldown screen has an 'f6' binding (priority) mapped to withdraw action
 7. Withdraw on a terminal session (COMPLETED_WORK/WITHDRAWN) is a no-op
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.state_reader import SessionState, DispatchState
from projects.POC.orchestrator.tests.test_helpers import make_tmp_dir


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    """Run a coroutine synchronously for testing."""
    return asyncio.run(coro)


def _make_session_state(
    infra_dir: str,
    cfa_state: str = 'PROPOSAL',
    cfa_phase: str = 'intent',
    status: str = 'active',
    dispatches: list | None = None,
    worktree_path: str = '',
) -> SessionState:
    """Build a minimal SessionState for testing."""
    if not worktree_path:
        worktree_path = infra_dir
    return SessionState(
        project='test-project',
        session_id='20260314-120000',
        worktree_name='session-120000--test',
        worktree_path=worktree_path,
        task='test task',
        status=status,
        cfa_phase=cfa_phase,
        cfa_state=cfa_state,
        cfa_actor='intent_team',
        needs_input=False,
        is_orphaned=False,
        dispatches=dispatches or [],
        stream_age_seconds=10,
        duration_seconds=60,
        infra_dir=infra_dir,
    )


def _make_dispatch_state(infra_dir: str, status: str = 'active') -> DispatchState:
    """Build a minimal DispatchState for testing."""
    return DispatchState(
        team='coding',
        worktree_name='dispatch-test',
        worktree_path=infra_dir,
        task='dispatch task',
        status=status,
        cfa_state='TASK_IN_PROGRESS',
        cfa_phase='execution',
        is_running=True,
        infra_dir=infra_dir,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestWithdrawSession(unittest.TestCase):
    """Tests for the withdraw_session() function."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.infra_dir = os.path.join(self.tmpdir, 'session-infra')
        os.makedirs(self.infra_dir)

        # Write a CfA state file
        self.cfa_path = os.path.join(self.infra_dir, '.cfa-state.json')
        cfa_data = {
            'phase': 'intent',
            'state': 'PROPOSAL',
            'actor': 'intent_team',
            'history': [],
            'backtrack_count': 0,
        }
        with open(self.cfa_path, 'w') as f:
            json.dump(cfa_data, f)

        # Write a .running sentinel with a fake PID
        self.running_path = os.path.join(self.infra_dir, '.running')
        with open(self.running_path, 'w') as f:
            f.write('99999')

        # Create a fake worktree directory
        self.worktree_dir = os.path.join(self.tmpdir, 'worktree')
        os.makedirs(self.worktree_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_sets_state_to_withdrawn(self):
        """withdraw_session() must set CfA state to WITHDRAWN."""
        from projects.POC.orchestrator.withdraw import withdraw_session

        session = _make_session_state(
            self.infra_dir, worktree_path=self.worktree_dir,
        )
        _run(withdraw_session(session))

        with open(self.cfa_path) as f:
            cfa = json.load(f)
        self.assertEqual(cfa['state'], 'WITHDRAWN')

    def test_kills_session_subprocess(self):
        """withdraw_session() must kill the PID in .running."""
        from projects.POC.orchestrator.withdraw import withdraw_session

        session = _make_session_state(
            self.infra_dir, worktree_path=self.worktree_dir,
        )
        with patch('projects.POC.orchestrator.withdraw._kill_pid') as mock_kill:
            _run(withdraw_session(session))
            mock_kill.assert_any_call(99999)

    def test_kills_dispatch_subprocesses(self):
        """withdraw_session() must kill PIDs from dispatch .running files."""
        from projects.POC.orchestrator.withdraw import withdraw_session

        # Create a dispatch infra dir with its own .running
        dispatch_infra = os.path.join(self.tmpdir, 'dispatch-infra')
        os.makedirs(dispatch_infra)
        with open(os.path.join(dispatch_infra, '.running'), 'w') as f:
            f.write('88888')

        dispatch = _make_dispatch_state(dispatch_infra)
        session = _make_session_state(
            self.infra_dir,
            dispatches=[dispatch],
            worktree_path=self.worktree_dir,
        )
        with patch('projects.POC.orchestrator.withdraw._kill_pid') as mock_kill:
            _run(withdraw_session(session))
            # Should kill both session PID and dispatch PID
            killed_pids = [call.args[0] for call in mock_kill.call_args_list]
            self.assertIn(99999, killed_pids)
            self.assertIn(88888, killed_pids)

    def test_cleans_up_sentinel_files(self):
        """withdraw_session() must remove .running and .input-request.json."""
        from projects.POC.orchestrator.withdraw import withdraw_session

        # Create .input-request.json
        req_path = os.path.join(self.infra_dir, '.input-request.json')
        with open(req_path, 'w') as f:
            json.dump({'state': 'INTENT_ASSERT'}, f)

        session = _make_session_state(
            self.infra_dir, worktree_path=self.worktree_dir,
        )
        _run(withdraw_session(session))

        self.assertFalse(os.path.exists(self.running_path))
        self.assertFalse(os.path.exists(req_path))

    def test_leaves_worktree_intact(self):
        """withdraw_session() must NOT delete the worktree directory."""
        from projects.POC.orchestrator.withdraw import withdraw_session

        # Put a file in the worktree to verify it survives
        marker = os.path.join(self.worktree_dir, 'INTENT.md')
        with open(marker, 'w') as f:
            f.write('# test')

        session = _make_session_state(
            self.infra_dir, worktree_path=self.worktree_dir,
        )
        _run(withdraw_session(session))

        self.assertTrue(os.path.isdir(self.worktree_dir))
        self.assertTrue(os.path.exists(marker))

    def test_emits_session_completed_event(self):
        """withdraw_session() must emit SESSION_COMPLETED with terminal_state=WITHDRAWN."""
        from projects.POC.orchestrator.withdraw import withdraw_session
        from projects.POC.orchestrator.events import EventBus, EventType

        bus = MagicMock(spec=EventBus)
        bus.publish = AsyncMock()

        session = _make_session_state(
            self.infra_dir, worktree_path=self.worktree_dir,
        )
        _run(withdraw_session(session, event_bus=bus))

        # Find the SESSION_COMPLETED event among published events
        found = False
        for call in bus.publish.call_args_list:
            evt = call.args[0]
            if evt.type == EventType.SESSION_COMPLETED:
                self.assertEqual(evt.data['terminal_state'], 'WITHDRAWN')
                found = True
                break
        self.assertTrue(found, 'SESSION_COMPLETED event was not emitted')

    def test_noop_on_terminal_state(self):
        """withdraw_session() on an already-terminal session is a no-op."""
        from projects.POC.orchestrator.withdraw import withdraw_session

        # Set CfA to COMPLETED_WORK
        with open(self.cfa_path, 'w') as f:
            json.dump({
                'phase': 'execution', 'state': 'COMPLETED_WORK',
                'actor': 'system', 'history': [],
            }, f)

        session = _make_session_state(
            self.infra_dir,
            cfa_state='COMPLETED_WORK',
            cfa_phase='execution',
            status='complete',
            worktree_path=self.worktree_dir,
        )
        result = _run(withdraw_session(session))
        self.assertFalse(result, 'withdraw_session should return False for terminal sessions')

        # State should be unchanged
        with open(self.cfa_path) as f:
            cfa = json.load(f)
        self.assertEqual(cfa['state'], 'COMPLETED_WORK')

    def test_cancels_in_process_task(self):
        """withdraw_session() must cancel the in-process run_task if provided."""
        from projects.POC.orchestrator.withdraw import withdraw_session

        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_task.cancel.return_value = True

        session = _make_session_state(
            self.infra_dir, worktree_path=self.worktree_dir,
        )
        _run(withdraw_session(session, in_process_task=mock_task))

        mock_task.cancel.assert_called_once()


class TestWithdrawBindings(unittest.TestCase):
    """Tests that TUI screens have 'w' bindings for withdraw."""

    def test_dashboard_has_withdraw_binding(self):
        """DashboardScreen must have a 'w' binding."""
        from projects.POC.tui.screens.dashboard import DashboardScreen
        keys = [b.key for b in DashboardScreen.BINDINGS]
        self.assertIn('w', keys)

    def test_drilldown_has_withdraw_binding(self):
        """DrilldownScreen must have an 'f6' binding for withdraw (not 'w', which conflicts with Input)."""
        from projects.POC.tui.screens.drilldown import DrilldownScreen
        keys = [b.key for b in DrilldownScreen.BINDINGS]
        self.assertIn('f6', keys)

    def test_dashboard_withdraw_binding_label(self):
        """Dashboard 'w' binding must be labeled 'Withdraw'."""
        from projects.POC.tui.screens.dashboard import DashboardScreen
        for b in DashboardScreen.BINDINGS:
            if b.key == 'w':
                self.assertEqual(b.description, 'Withdraw')
                break
        else:
            self.fail("No 'w' binding found on DashboardScreen")

    def test_drilldown_withdraw_binding_label(self):
        """Drilldown 'f6' binding must be labeled 'Withdraw'."""
        from projects.POC.tui.screens.drilldown import DrilldownScreen
        for b in DrilldownScreen.BINDINGS:
            if b.key == 'f6':
                self.assertEqual(b.description, 'Withdraw')
                break
        else:
            self.fail("No 'f6' binding found on DrilldownScreen")

    def test_drilldown_withdraw_binding_has_priority(self):
        """Drilldown withdraw binding must have priority=True to show over Input widget."""
        from projects.POC.tui.screens.drilldown import DrilldownScreen
        for b in DrilldownScreen.BINDINGS:
            if b.key == 'f6' and b.action == 'withdraw':
                self.assertTrue(b.priority, "Withdraw binding must have priority=True")
                break
        else:
            self.fail("No 'f6' withdraw binding found on DrilldownScreen")


if __name__ == '__main__':
    unittest.main()
