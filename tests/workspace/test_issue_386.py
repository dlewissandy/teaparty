"""Issue #386: Withdraw button in chat window does not cancel the job.

Tests that withdrawal:
1. Works without a running engine (no socket dependency)
2. Kills all processes for the job and its tasks
3. Removes all git worktrees (job + tasks)
4. Removes job/task entries from indexes
5. Preserves CfA state history for the stats pipeline
6. Sets job status to 'withdrawn' in job.json
"""
from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import tempfile
import unittest


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_git_repo(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    subprocess.run(['git', 'init', path], check=True, capture_output=True)
    subprocess.run(['git', 'config', 'user.email', 'test@test.com'],
                   cwd=path, check=True, capture_output=True)
    subprocess.run(['git', 'config', 'user.name', 'Test'],
                   cwd=path, check=True, capture_output=True)
    dummy = os.path.join(path, '.gitkeep')
    with open(dummy, 'w') as f:
        f.write('')
    subprocess.run(['git', 'add', '.'], cwd=path, check=True, capture_output=True)
    subprocess.run(['git', 'commit', '-m', 'init'], cwd=path,
                   check=True, capture_output=True)
    return path


def _make_job_with_worktree(repo_root: str, session_id: str, *,
                            cfa_state: str = 'WORK_IN_PROGRESS') -> dict:
    """Create a job with a real git worktree and CfA state."""
    from teaparty.workspace.job_store import create_job
    result = _run(create_job(
        project_root=repo_root,
        task=f'Test task for {session_id}',
        session_id=session_id,
    ))
    job_dir = result['job_dir']

    # Write CfA state
    cfa = {
        'phase': 'execution', 'state': cfa_state, 'actor': 'agent',
        'backtrack_count': 0,
        'history': [
            {'state': 'IDEA', 'action': 'propose', 'actor': 'human',
             'timestamp': '2026-04-01T12:00:00+00:00'},
            {'state': 'PROPOSAL', 'action': 'assert', 'actor': 'intent_team',
             'timestamp': '2026-04-01T12:01:00+00:00'},
        ],
    }
    with open(os.path.join(job_dir, '.cfa-state.json'), 'w') as f:
        json.dump(cfa, f)

    # Write heartbeat (no real PID — tests don't spawn real processes)
    with open(os.path.join(job_dir, '.heartbeat'), 'w') as f:
        json.dump({'status': 'alive', 'pid': -1, 'ts': 0}, f)

    return result


class TestWithdrawJob(unittest.TestCase):
    """Withdrawal removes worktrees and indexes but preserves CfA state."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.repo_root = _make_git_repo(os.path.join(self._tmpdir, 'repo'))

    def tearDown(self):
        subprocess.run(['git', 'worktree', 'prune'], cwd=self.repo_root,
                       capture_output=True)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_withdraw_removes_worktree(self):
        """Withdrawn job's git worktree is deleted."""
        result = _make_job_with_worktree(self.repo_root, 'test-001')
        worktree = result['worktree_path']
        self.assertTrue(os.path.isdir(worktree))

        from teaparty.workspace.job_store import withdraw_job
        _run(withdraw_job(project_root=self.repo_root,
                          job_dir=result['job_dir']))

        self.assertFalse(os.path.isdir(worktree))

    def test_withdraw_removes_index_entry(self):
        """Withdrawn job is removed from jobs.json."""
        result = _make_job_with_worktree(self.repo_root, 'test-001')

        from teaparty.workspace.job_store import withdraw_job, _jobs_dir, _load_index
        jobs_index = os.path.join(_jobs_dir(self.repo_root), 'jobs.json')
        before = _load_index(jobs_index, 'jobs')
        self.assertEqual(len(before['jobs']), 1)

        _run(withdraw_job(project_root=self.repo_root,
                          job_dir=result['job_dir']))

        after = _load_index(jobs_index, 'jobs')
        self.assertEqual(len(after['jobs']), 0)

    def test_withdraw_preserves_cfa_state(self):
        """CfA state history survives withdrawal for the stats pipeline."""
        result = _make_job_with_worktree(self.repo_root, 'test-001')
        job_dir = result['job_dir']

        from teaparty.workspace.job_store import withdraw_job
        _run(withdraw_job(project_root=self.repo_root, job_dir=job_dir))

        # job.json still exists with withdrawn status
        with open(os.path.join(job_dir, 'job.json')) as f:
            state = json.load(f)
        self.assertEqual(state['status'], 'withdrawn')

        # .cfa-state.json still exists with WITHDRAWN state and history
        cfa_path = os.path.join(job_dir, '.cfa-state.json')
        self.assertTrue(os.path.isfile(cfa_path))
        with open(cfa_path) as f:
            cfa = json.load(f)
        self.assertEqual(cfa['state'], 'WITHDRAWN')
        self.assertGreater(len(cfa['history']), 0,
                           'CfA history must survive for stats')

    def test_withdraw_sets_cfa_to_withdrawn(self):
        """CfA state is set to WITHDRAWN with history entry."""
        result = _make_job_with_worktree(self.repo_root, 'test-001',
                                         cfa_state='WORK_IN_PROGRESS')

        from teaparty.workspace.job_store import withdraw_job
        _run(withdraw_job(project_root=self.repo_root,
                          job_dir=result['job_dir']))

        with open(os.path.join(result['job_dir'], '.cfa-state.json')) as f:
            cfa = json.load(f)
        self.assertEqual(cfa['state'], 'WITHDRAWN')
        # History should have the withdrawal entry appended
        last = cfa['history'][-1]
        self.assertEqual(last['state'], 'WITHDRAWN')

    def test_withdraw_removes_task_worktrees(self):
        """Task worktrees under the job are also removed."""
        job_result = _make_job_with_worktree(self.repo_root, 'test-001')

        from teaparty.workspace.job_store import create_task, withdraw_job
        task_result = _run(create_task(
            job_dir=job_result['job_dir'],
            task='Subtask',
            team='coding',
        ))
        self.assertTrue(os.path.isdir(task_result['worktree_path']))

        _run(withdraw_job(project_root=self.repo_root,
                          job_dir=job_result['job_dir']))

        self.assertFalse(os.path.isdir(task_result['worktree_path']))

    def test_withdraw_already_terminal_is_noop(self):
        """Withdrawing an already-withdrawn job doesn't fail."""
        result = _make_job_with_worktree(self.repo_root, 'test-001',
                                         cfa_state='COMPLETED_WORK')

        from teaparty.workspace.job_store import withdraw_job
        # Should not raise
        _run(withdraw_job(project_root=self.repo_root,
                          job_dir=result['job_dir']))


class TestWithdrawKillsProcesses(unittest.TestCase):
    """Withdrawal kills running processes."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.repo_root = _make_git_repo(os.path.join(self._tmpdir, 'repo'))

    def tearDown(self):
        subprocess.run(['git', 'worktree', 'prune'], cwd=self.repo_root,
                       capture_output=True)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_withdraw_kills_job_process(self):
        """A running process recorded in .heartbeat is killed on withdrawal."""
        result = _make_job_with_worktree(self.repo_root, 'test-001')
        job_dir = result['job_dir']

        # Start a real sleep process to kill
        proc = subprocess.Popen(['sleep', '300'])
        with open(os.path.join(job_dir, '.heartbeat'), 'w') as f:
            json.dump({'status': 'alive', 'pid': proc.pid, 'ts': 0}, f)

        from teaparty.workspace.job_store import withdraw_job
        _run(withdraw_job(project_root=self.repo_root, job_dir=job_dir))

        # Process should be dead — wait with timeout to reap
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            self.fail('Process should have been killed by withdrawal')
        self.assertNotEqual(proc.returncode, None)


class TestBridgeWithdrawEndpoint(unittest.TestCase):
    """Bridge withdraw endpoint works without engine socket."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.repo_root = _make_git_repo(os.path.join(self._tmpdir, 'repo'))

    def tearDown(self):
        subprocess.run(['git', 'worktree', 'prune'], cwd=self.repo_root,
                       capture_output=True)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_withdraw_without_socket(self):
        """Withdrawal succeeds even when no intervention socket exists."""
        result = _make_job_with_worktree(self.repo_root, 'test-001')

        # No socket exists — the old code would return 503
        from teaparty.workspace.job_store import withdraw_job
        _run(withdraw_job(project_root=self.repo_root,
                          job_dir=result['job_dir']))

        with open(os.path.join(result['job_dir'], '.cfa-state.json')) as f:
            cfa = json.load(f)
        self.assertEqual(cfa['state'], 'WITHDRAWN')
