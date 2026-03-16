#!/usr/bin/env python3
"""Tests for Issue #159: TUI crashes on session withdraw.

Root cause: _kill_pid() in withdraw.py uses os.killpg() on the PID from
.running. For in-process sessions, that PID is the TUI's own PID, so
os.killpg() kills the TUI's process group.

Covers:
 1. _kill_pid() must not kill the current process (self-kill guard)
 2. _kill_pid() must not kill the current process's group via killpg
 3. withdraw_session() must skip self-PID in .running but still clean up state
 4. withdraw_session() must skip self-PID in dispatch .running files
 5. ClaudeRunner.run() must kill its subprocess in its finally block
 6. Drilldown _do_withdraw must pop the screen (return to dashboard)
"""
import asyncio
import json
import os
import signal
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.tui.state_reader import SessionState, DispatchState


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
    worktree_path: str = '/tmp/fake-worktree',
) -> SessionState:
    """Build a minimal SessionState for testing."""
    return SessionState(
        project='test-project',
        session_id='20260316-120000',
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
        worktree_path='/tmp/fake-dispatch-wt',
        task='dispatch task',
        status=status,
        cfa_state='TASK_IN_PROGRESS',
        cfa_phase='execution',
        is_running=True,
        infra_dir=infra_dir,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestSelfKillGuard(unittest.TestCase):
    """_kill_pid must not kill the current process or its process group."""

    def test_kill_pid_skips_own_pid(self):
        """_kill_pid() must not send signals when pid == os.getpid()."""
        from projects.POC.tui.withdraw import _kill_pid

        own_pid = os.getpid()
        with patch('os.killpg') as mock_killpg, \
             patch('os.kill') as mock_kill:
            _kill_pid(own_pid)
            mock_killpg.assert_not_called()
            mock_kill.assert_not_called()

    def test_kill_pid_skips_own_process_group(self):
        """_kill_pid() must not killpg our own pgid even if PID differs.

        When a child process shares our process group, killpg on its pgid
        would still kill us.
        """
        from projects.POC.tui.withdraw import _kill_pid

        own_pgid = os.getpgid(os.getpid())
        fake_child_pid = 99999

        with patch('os.getpgid', return_value=own_pgid) as mock_getpgid, \
             patch('os.killpg') as mock_killpg, \
             patch('os.kill') as mock_kill:
            _kill_pid(fake_child_pid)
            # Should not use killpg with our own pgid
            mock_killpg.assert_not_called()
            # Should fall back to direct os.kill on the PID
            mock_kill.assert_called_once_with(fake_child_pid, signal.SIGTERM)


class TestWithdrawSelfKillPrevention(unittest.TestCase):
    """withdraw_session() must not kill the TUI when .running has its own PID."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.infra_dir = os.path.join(self.tmpdir, 'session-infra')
        os.makedirs(self.infra_dir)

        # Write CfA state
        self.cfa_path = os.path.join(self.infra_dir, '.cfa-state.json')
        with open(self.cfa_path, 'w') as f:
            json.dump({
                'phase': 'intent', 'state': 'PROPOSAL',
                'actor': 'intent_team', 'history': [],
            }, f)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_withdraw_with_own_pid_in_running(self):
        """When .running contains our own PID, withdraw must not kill it but
        must still set WITHDRAWN state and clean up sentinels."""
        from projects.POC.tui.withdraw import withdraw_session

        # Write our own PID to .running (simulates in-process session)
        running_path = os.path.join(self.infra_dir, '.running')
        with open(running_path, 'w') as f:
            f.write(str(os.getpid()))

        session = _make_session_state(self.infra_dir)

        with patch('os.killpg') as mock_killpg, \
             patch('os.kill') as mock_kill:
            result = _run(withdraw_session(session))

        # Must return True (session was withdrawn)
        self.assertTrue(result)

        # Must NOT have sent any kill signals
        mock_killpg.assert_not_called()
        mock_kill.assert_not_called()

        # State must be WITHDRAWN
        with open(self.cfa_path) as f:
            cfa = json.load(f)
        self.assertEqual(cfa['state'], 'WITHDRAWN')

        # .running sentinel must be cleaned up
        self.assertFalse(os.path.exists(running_path))

    def test_withdraw_with_own_pid_in_dispatch_running(self):
        """When dispatch .running contains our own PID, withdraw must skip it."""
        from projects.POC.tui.withdraw import withdraw_session

        # Session .running with our PID
        running_path = os.path.join(self.infra_dir, '.running')
        with open(running_path, 'w') as f:
            f.write(str(os.getpid()))

        # Dispatch .running also with our PID (in-process dispatch)
        dispatch_infra = os.path.join(self.tmpdir, 'dispatch-infra')
        os.makedirs(dispatch_infra)
        with open(os.path.join(dispatch_infra, '.running'), 'w') as f:
            f.write(str(os.getpid()))

        dispatch = _make_dispatch_state(dispatch_infra)
        session = _make_session_state(self.infra_dir, dispatches=[dispatch])

        with patch('os.killpg') as mock_killpg, \
             patch('os.kill') as mock_kill:
            result = _run(withdraw_session(session))

        self.assertTrue(result)
        mock_killpg.assert_not_called()
        mock_kill.assert_not_called()


class TestClaudeRunnerSubprocessCleanup(unittest.TestCase):
    """ClaudeRunner.run() must kill its subprocess in its finally block."""

    def test_kill_subprocess_terminates_running_process(self):
        """_kill_subprocess should call _kill_process_tree when proc is running."""
        from projects.POC.orchestrator.claude_runner import ClaudeRunner

        runner = ClaudeRunner(
            prompt='test',
            cwd='/tmp',
            stream_file='/tmp/test-stream.jsonl',
        )

        mock_proc = MagicMock()
        mock_proc.returncode = None  # Still running
        mock_proc.pid = 12345
        runner._process = mock_proc

        with patch('projects.POC.orchestrator.claude_runner._kill_process_tree') as mock_kill:
            runner._kill_subprocess()
            mock_kill.assert_called_once_with(12345)

    def test_run_finally_calls_kill_subprocess(self):
        """ClaudeRunner.run() must call _kill_subprocess in its finally block."""
        import inspect
        from projects.POC.orchestrator.claude_runner import ClaudeRunner

        source = inspect.getsource(ClaudeRunner.run)
        self.assertIn('_kill_subprocess', source,
                       'ClaudeRunner.run() must call _kill_subprocess in finally block')


class TestDrilldownWithdrawNavigation(unittest.TestCase):
    """Drilldown _do_withdraw must pop the screen to return to dashboard."""

    def test_do_withdraw_pops_screen(self):
        """_do_withdraw must call app.pop_screen() to return to dashboard."""
        import inspect
        from projects.POC.tui.screens.drilldown import DrilldownScreen

        source = inspect.getsource(DrilldownScreen._do_withdraw)
        self.assertIn('pop_screen', source,
                       '_do_withdraw must call pop_screen to return to dashboard')

    def test_do_withdraw_does_not_log_to_activity(self):
        """_do_withdraw must NOT write to activity log (screen is being popped)."""
        import inspect
        from projects.POC.tui.screens.drilldown import DrilldownScreen

        source = inspect.getsource(DrilldownScreen._do_withdraw)
        self.assertNotIn('activity-log', source,
                         '_do_withdraw must not write to activity log when popping screen')


if __name__ == '__main__':
    unittest.main()
