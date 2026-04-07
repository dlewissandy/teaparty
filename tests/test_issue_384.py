"""Issue #384: Job worktrees — hierarchical, project-scoped worktree layout.

Tests that the job store creates jobs and tasks under
{project_root}/.teaparty/jobs/ with the correct directory structure,
state files, and lifecycle operations.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
import unittest


def _make_git_repo(path: str) -> str:
    """Initialize a bare git repo with an initial commit. Returns repo root."""
    os.makedirs(path, exist_ok=True)
    subprocess.run(['git', 'init', path], check=True, capture_output=True)
    subprocess.run(['git', 'config', 'user.email', 'test@test.com'],
                   cwd=path, check=True, capture_output=True)
    subprocess.run(['git', 'config', 'user.name', 'Test'],
                   cwd=path, check=True, capture_output=True)
    # Need an initial commit for worktrees to work
    dummy = os.path.join(path, '.gitkeep')
    with open(dummy, 'w') as f:
        f.write('')
    subprocess.run(['git', 'add', '.'], cwd=path, check=True, capture_output=True)
    subprocess.run(['git', 'commit', '-m', 'init'], cwd=path,
                   check=True, capture_output=True)
    return path


def _run(coro):
    """Run an async function synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


class TestJobCreation(unittest.TestCase):
    """SC1: Jobs are created under {project_root}/.teaparty/jobs/ with their own git worktree."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.repo_root = _make_git_repo(os.path.join(self._tmpdir, 'repo'))

    def tearDown(self):
        # Clean up git worktrees before removing tmpdir
        subprocess.run(['git', 'worktree', 'prune'], cwd=self.repo_root,
                       capture_output=True)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_create_job_produces_worktree_under_teaparty_jobs(self):
        """A new job creates a directory under .teaparty/jobs/ containing a
        git worktree checkout and a job.json state file."""
        from orchestrator.job_store import create_job

        result = _run(create_job(
            project_root=self.repo_root,
            task='Fix the session write-scope bug',
            issue=355,
        ))

        # Job directory exists under .teaparty/jobs/
        jobs_dir = os.path.join(self.repo_root, '.teaparty', 'jobs')
        self.assertTrue(os.path.isdir(jobs_dir))

        # The job directory matches the expected pattern
        job_dir = result['job_dir']
        self.assertTrue(job_dir.startswith(jobs_dir))
        self.assertTrue(os.path.isdir(job_dir))

        # Contains a worktree/ that is a git checkout
        worktree = os.path.join(job_dir, 'worktree')
        self.assertTrue(os.path.isdir(worktree))
        self.assertTrue(os.path.isdir(os.path.join(worktree, '.git')) or
                        os.path.isfile(os.path.join(worktree, '.git')))

        # Contains a job.json with expected fields
        job_json_path = os.path.join(job_dir, 'job.json')
        self.assertTrue(os.path.isfile(job_json_path))
        with open(job_json_path) as f:
            job_state = json.load(f)
        self.assertEqual(job_state['issue'], 355)
        self.assertEqual(job_state['status'], 'active')
        self.assertIn('job_id', job_state)
        self.assertIn('created_at', job_state)

    def test_create_job_updates_jobs_index(self):
        """Creating a job adds an entry to jobs.json."""
        from orchestrator.job_store import create_job

        result = _run(create_job(
            project_root=self.repo_root,
            task='First job',
            issue=100,
        ))

        index_path = os.path.join(self.repo_root, '.teaparty', 'jobs', 'jobs.json')
        self.assertTrue(os.path.isfile(index_path))
        with open(index_path) as f:
            index = json.load(f)
        self.assertEqual(len(index['jobs']), 1)
        self.assertEqual(index['jobs'][0]['job_id'], result['job_id'])


class TestTaskCreation(unittest.TestCase):
    """SC2: Tasks are created under their parent job with their own git worktree."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.repo_root = _make_git_repo(os.path.join(self._tmpdir, 'repo'))

    def tearDown(self):
        subprocess.run(['git', 'worktree', 'prune'], cwd=self.repo_root,
                       capture_output=True)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_create_task_produces_worktree_under_parent_job(self):
        """A task is created under its parent job's tasks/ directory with
        its own git worktree and task.json state file."""
        from orchestrator.job_store import create_job, create_task

        job = _run(create_job(
            project_root=self.repo_root,
            task='Fix the bug',
            issue=355,
        ))

        task = _run(create_task(
            job_dir=job['job_dir'],
            task='Implement the fix',
            team='coding',
            agent='developer',
        ))

        # Task directory is under the job's tasks/ directory
        tasks_dir = os.path.join(job['job_dir'], 'tasks')
        self.assertTrue(task['task_dir'].startswith(tasks_dir))
        self.assertTrue(os.path.isdir(task['task_dir']))

        # Contains a worktree/ that is a git checkout
        worktree = os.path.join(task['task_dir'], 'worktree')
        self.assertTrue(os.path.isdir(worktree))
        self.assertTrue(os.path.isdir(os.path.join(worktree, '.git')) or
                        os.path.isfile(os.path.join(worktree, '.git')))

        # Contains a task.json with expected fields
        task_json_path = os.path.join(task['task_dir'], 'task.json')
        self.assertTrue(os.path.isfile(task_json_path))
        with open(task_json_path) as f:
            task_state = json.load(f)
        self.assertEqual(task_state['team'], 'coding')
        self.assertEqual(task_state['agent'], 'developer')
        self.assertEqual(task_state['status'], 'active')

    def test_create_task_updates_tasks_index(self):
        """Creating a task adds an entry to the job's tasks/tasks.json."""
        from orchestrator.job_store import create_job, create_task

        job = _run(create_job(
            project_root=self.repo_root,
            task='Fix the bug',
            issue=355,
        ))

        task = _run(create_task(
            job_dir=job['job_dir'],
            task='Implement the fix',
            team='coding',
            agent='developer',
        ))

        index_path = os.path.join(job['job_dir'], 'tasks', 'tasks.json')
        self.assertTrue(os.path.isfile(index_path))
        with open(index_path) as f:
            index = json.load(f)
        self.assertEqual(len(index['tasks']), 1)
        self.assertEqual(index['tasks'][0]['task_id'], task['task_id'])


class TestProjectScoping(unittest.TestCase):
    """SC3: Each project's jobs live in that project's .teaparty/jobs/."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.project_a = _make_git_repo(os.path.join(self._tmpdir, 'project-a'))
        self.project_b = _make_git_repo(os.path.join(self._tmpdir, 'project-b'))

    def tearDown(self):
        for repo in (self.project_a, self.project_b):
            subprocess.run(['git', 'worktree', 'prune'], cwd=repo,
                           capture_output=True)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_jobs_are_isolated_per_project(self):
        """Jobs created for different projects live in their respective
        .teaparty/jobs/ directories, not in a shared pool."""
        from orchestrator.job_store import create_job

        job_a = _run(create_job(
            project_root=self.project_a,
            task='Project A work',
            issue=1,
        ))
        job_b = _run(create_job(
            project_root=self.project_b,
            task='Project B work',
            issue=2,
        ))

        # Each job lives under its own project
        self.assertTrue(job_a['job_dir'].startswith(
            os.path.join(self.project_a, '.teaparty', 'jobs')))
        self.assertTrue(job_b['job_dir'].startswith(
            os.path.join(self.project_b, '.teaparty', 'jobs')))

        # Project A's jobs dir has no knowledge of project B's jobs
        a_index = os.path.join(self.project_a, '.teaparty', 'jobs', 'jobs.json')
        with open(a_index) as f:
            a_jobs = json.load(f)
        self.assertEqual(len(a_jobs['jobs']), 1)
        self.assertEqual(a_jobs['jobs'][0]['job_id'], job_a['job_id'])


class TestParallelTaskIsolation(unittest.TestCase):
    """SC4: Parallel tasks operate on independent checkouts."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.repo_root = _make_git_repo(os.path.join(self._tmpdir, 'repo'))

    def tearDown(self):
        subprocess.run(['git', 'worktree', 'prune'], cwd=self.repo_root,
                       capture_output=True)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_parallel_tasks_have_distinct_worktrees(self):
        """Two tasks under the same job have different worktree paths and
        independent git checkouts (different .git references)."""
        from orchestrator.job_store import create_job, create_task

        job = _run(create_job(
            project_root=self.repo_root,
            task='Fix the bug',
            issue=355,
        ))

        task_1 = _run(create_task(
            job_dir=job['job_dir'],
            task='Implement the fix',
            team='coding',
            agent='developer',
        ))
        task_2 = _run(create_task(
            job_dir=job['job_dir'],
            task='Write the tests',
            team='coding',
            agent='test-engineer',
        ))

        wt1 = os.path.join(task_1['task_dir'], 'worktree')
        wt2 = os.path.join(task_2['task_dir'], 'worktree')

        # Different paths
        self.assertNotEqual(wt1, wt2)

        # Both are valid git checkouts
        for wt in (wt1, wt2):
            result = subprocess.run(
                ['git', 'rev-parse', '--git-dir'],
                cwd=wt, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0)


class TestJobCleanup(unittest.TestCase):
    """SC5: Removing a job directory removes all child task worktrees, state, and indexes."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.repo_root = _make_git_repo(os.path.join(self._tmpdir, 'repo'))

    def tearDown(self):
        subprocess.run(['git', 'worktree', 'prune'], cwd=self.repo_root,
                       capture_output=True)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_cleanup_job_removes_job_and_all_tasks(self):
        """Cleaning up a job removes its directory, worktree, all child task
        worktrees, and deregisters from the jobs index."""
        from orchestrator.job_store import create_job, create_task, cleanup_job

        job = _run(create_job(
            project_root=self.repo_root,
            task='Fix the bug',
            issue=355,
        ))
        _run(create_task(
            job_dir=job['job_dir'],
            task='Implement fix',
            team='coding',
            agent='developer',
        ))
        _run(create_task(
            job_dir=job['job_dir'],
            task='Write tests',
            team='coding',
            agent='test-engineer',
        ))

        job_dir = job['job_dir']
        self.assertTrue(os.path.isdir(job_dir))

        _run(cleanup_job(
            project_root=self.repo_root,
            job_dir=job_dir,
        ))

        # Job directory is gone
        self.assertFalse(os.path.isdir(job_dir))

        # Jobs index is updated
        index_path = os.path.join(self.repo_root, '.teaparty', 'jobs', 'jobs.json')
        with open(index_path) as f:
            index = json.load(f)
        self.assertEqual(len(index['jobs']), 0)

        # Git worktrees are cleaned up (no dangling references)
        result = subprocess.run(
            ['git', 'worktree', 'list', '--porcelain'],
            cwd=self.repo_root, capture_output=True, text=True,
        )
        # Only the main worktree should remain
        worktree_lines = [l for l in result.stdout.splitlines()
                          if l.startswith('worktree ')]
        self.assertEqual(len(worktree_lines), 1,
                         f'Expected only main worktree, got: {worktree_lines}')


class TestJobTaskFullPath(unittest.TestCase):
    """Integration: job creation → task creation → task worktree exists under the job."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.repo_root = _make_git_repo(os.path.join(self._tmpdir, 'repo'))

    def tearDown(self):
        subprocess.run(['git', 'worktree', 'prune'], cwd=self.repo_root,
                       capture_output=True)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_full_path_job_to_task_worktree(self):
        """The full directory path from project root to task worktree matches
        the proposal layout: .teaparty/jobs/job-{id}/tasks/task-{id}/worktree/"""
        from orchestrator.job_store import create_job, create_task

        job = _run(create_job(
            project_root=self.repo_root,
            task='Fix the bug',
            issue=355,
        ))
        task = _run(create_task(
            job_dir=job['job_dir'],
            task='Implement fix',
            team='coding',
            agent='developer',
        ))

        # Verify the structural nesting
        task_worktree = os.path.join(task['task_dir'], 'worktree')
        rel = os.path.relpath(task_worktree, self.repo_root)
        parts = rel.split(os.sep)

        # .teaparty / jobs / job-XXX / tasks / task-XXX / worktree
        self.assertEqual(parts[0], '.teaparty')
        self.assertEqual(parts[1], 'jobs')
        self.assertTrue(parts[2].startswith('job-'))
        self.assertEqual(parts[3], 'tasks')
        self.assertTrue(parts[4].startswith('task-'))
        self.assertEqual(parts[5], 'worktree')
