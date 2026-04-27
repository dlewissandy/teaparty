"""Issue #407: Artifacts (INTENT.md, PLAN.md, WORK_SUMMARY.md) belong in the worktree.

Tests that:
1. create_job() writes a .gitignore that excludes INTENT.md, PLAN.md, WORK_SUMMARY.md
2. create_task() writes same .gitignore entries
3. create_task() copies INTENT.md and PLAN.md from parent job worktree
4. _generate_work_summary has been deleted (agent writes WORK_SUMMARY.md)
5. phase-config.json execution artifact is WORK_SUMMARY.md (not .work-summary.md)
6. _MERGE_EXCLUDE tracks WORK_SUMMARY.md (not .work-summary.md)
7. _interpret_output finds execution artifact in session_worktree, not infra_dir
8. _check_skill_correction reads PLAN.md from session_worktree, not infra_dir
9. _build_artifact_context searches worktree first, then infra_dir; uses WORK_SUMMARY.md name
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


def _make_git_repo(path: str) -> str:
    """Initialize a git repo with an initial commit. Returns repo root."""
    os.makedirs(path, exist_ok=True)
    subprocess.run(['git', 'init', path], check=True, capture_output=True)
    subprocess.run(['git', 'config', 'user.email', 'test@test.com'],
                   cwd=path, check=True, capture_output=True)
    subprocess.run(['git', 'config', 'user.name', 'Test'],
                   cwd=path, check=True, capture_output=True)
    dummy = os.path.join(path, '.gitkeep')
    Path(dummy).write_text('')
    subprocess.run(['git', 'add', '.'], cwd=path, check=True, capture_output=True)
    subprocess.run(['git', 'commit', '-m', 'init'], cwd=path,
                   check=True, capture_output=True)
    return path


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── SC1: create_job() gitignore ───────────────────────────────────────────────

class TestJobWorktreeGitignore(unittest.TestCase):
    """create_job() must write a .gitignore that excludes process artifacts."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.repo_root = _make_git_repo(os.path.join(self._tmpdir, 'repo'))

    def tearDown(self):
        subprocess.run(['git', 'worktree', 'prune'], cwd=self.repo_root,
                       capture_output=True)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_create_job_gitignore_excludes_intent_md(self):
        """Job worktree .gitignore must contain INTENT.md so agents cannot commit it."""
        from teaparty.workspace.job_store import create_job
        result = _run(create_job(project_root=self.repo_root, task='Test task'))
        gitignore = os.path.join(result['worktree_path'], '.gitignore')
        self.assertTrue(os.path.isfile(gitignore),
                        'create_job must write .gitignore to the worktree')
        content = Path(gitignore).read_text()
        self.assertIn('INTENT.md', content,
                      '.gitignore must exclude INTENT.md (process artifact, must not reach main)')

    def test_create_job_gitignore_excludes_plan_md(self):
        """Job worktree .gitignore must contain PLAN.md so agents cannot commit it."""
        from teaparty.workspace.job_store import create_job
        result = _run(create_job(project_root=self.repo_root, task='Test task'))
        gitignore = os.path.join(result['worktree_path'], '.gitignore')
        content = Path(gitignore).read_text()
        self.assertIn('PLAN.md', content,
                      '.gitignore must exclude PLAN.md (process artifact, must not reach main)')

    def test_create_job_gitignore_excludes_work_summary_md(self):
        """Job worktree .gitignore must contain WORK_SUMMARY.md so agents cannot commit it."""
        from teaparty.workspace.job_store import create_job
        result = _run(create_job(project_root=self.repo_root, task='Test task'))
        gitignore = os.path.join(result['worktree_path'], '.gitignore')
        content = Path(gitignore).read_text()
        self.assertIn('WORK_SUMMARY.md', content,
                      '.gitignore must exclude WORK_SUMMARY.md (process artifact, must not reach main)')

    def test_create_job_gitignore_does_not_exclude_old_hidden_filename(self):
        """.work-summary.md is the old name — it must NOT be used in the gitignore."""
        from teaparty.workspace.job_store import create_job
        result = _run(create_job(project_root=self.repo_root, task='Test task'))
        gitignore = os.path.join(result['worktree_path'], '.gitignore')
        content = Path(gitignore).read_text()
        self.assertNotIn('.work-summary.md', content,
                         '.gitignore must not reference old .work-summary.md name')

    def test_create_job_gitignore_is_committed(self):
        """The .gitignore must be committed so it is present for agent sessions."""
        from teaparty.workspace.job_store import create_job
        result = _run(create_job(project_root=self.repo_root, task='Test task'))
        # git ls-files returns the filename only if it is tracked (committed)
        proc = subprocess.run(
            ['git', 'ls-files', '.gitignore'],
            cwd=result['worktree_path'],
            capture_output=True, text=True,
        )
        self.assertIn('.gitignore', proc.stdout,
                      '.gitignore must be committed (tracked by git), not left as untracked')


# ── SC2: create_task() gitignore ─────────────────────────────────────────────

class TestTaskWorktreeGitignore(unittest.TestCase):
    """create_task() must write a .gitignore that excludes process artifacts."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.repo_root = _make_git_repo(os.path.join(self._tmpdir, 'repo'))

    def tearDown(self):
        subprocess.run(['git', 'worktree', 'prune'], cwd=self.repo_root,
                       capture_output=True)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _make_job(self):
        from teaparty.workspace.job_store import create_job
        return _run(create_job(project_root=self.repo_root, task='Parent job'))

    def test_create_task_gitignore_excludes_intent_md(self):
        """Task worktree .gitignore must contain INTENT.md."""
        from teaparty.workspace.job_store import create_task
        job = self._make_job()
        task = _run(create_task(job_dir=job['job_dir'], task='Subtask', team='coding', agent='dev'))
        gitignore = os.path.join(task['worktree_path'], '.gitignore')
        self.assertTrue(os.path.isfile(gitignore),
                        'create_task must write .gitignore to the task worktree')
        content = Path(gitignore).read_text()
        self.assertIn('INTENT.md', content,
                      'task .gitignore must exclude INTENT.md')

    def test_create_task_gitignore_excludes_plan_md(self):
        """Task worktree .gitignore must contain PLAN.md."""
        from teaparty.workspace.job_store import create_task
        job = self._make_job()
        task = _run(create_task(job_dir=job['job_dir'], task='Subtask', team='coding', agent='dev'))
        gitignore = os.path.join(task['worktree_path'], '.gitignore')
        content = Path(gitignore).read_text()
        self.assertIn('PLAN.md', content,
                      'task .gitignore must exclude PLAN.md')

    def test_create_task_gitignore_excludes_work_summary_md(self):
        """Task worktree .gitignore must contain WORK_SUMMARY.md."""
        from teaparty.workspace.job_store import create_task
        job = self._make_job()
        task = _run(create_task(job_dir=job['job_dir'], task='Subtask', team='coding', agent='dev'))
        gitignore = os.path.join(task['worktree_path'], '.gitignore')
        content = Path(gitignore).read_text()
        self.assertIn('WORK_SUMMARY.md', content,
                      'task .gitignore must exclude WORK_SUMMARY.md')


# ── SC3: create_task() copies INTENT.md and PLAN.md from parent ─────────────

class TestTaskWorktreeInheritsArtifacts(unittest.TestCase):
    """create_task() must copy INTENT.md and PLAN.md from the parent job worktree."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self.repo_root = _make_git_repo(os.path.join(self._tmpdir, 'repo'))

    def tearDown(self):
        subprocess.run(['git', 'worktree', 'prune'], cwd=self.repo_root,
                       capture_output=True)
        import shutil
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _make_job(self):
        from teaparty.workspace.job_store import create_job
        return _run(create_job(project_root=self.repo_root, task='Parent job'))

    def test_create_task_copies_intent_md_from_parent_worktree(self):
        """When INTENT.md exists in the parent job worktree, it is copied to the task worktree."""
        from teaparty.workspace.job_store import create_task
        job = self._make_job()
        # Write INTENT.md to the parent job worktree
        intent_content = '# INTENT: Build the feature\nObjective: test subagent context'
        Path(os.path.join(job['worktree_path'], 'INTENT.md')).write_text(intent_content)

        task = _run(create_task(job_dir=job['job_dir'], task='Subtask', team='coding', agent='dev'))

        task_intent = os.path.join(task['worktree_path'], 'INTENT.md')
        self.assertTrue(os.path.isfile(task_intent),
                        'INTENT.md must be copied from parent job worktree to task worktree')
        self.assertEqual(Path(task_intent).read_text(), intent_content,
                         'copied INTENT.md must have the same content as the parent copy')

    def test_create_task_copies_plan_md_from_parent_worktree(self):
        """When PLAN.md exists in the parent job worktree, it is copied to the task worktree."""
        from teaparty.workspace.job_store import create_task
        job = self._make_job()
        plan_content = '# PLAN\n## Steps\n1. Write tests\n2. Implement\n'
        Path(os.path.join(job['worktree_path'], 'PLAN.md')).write_text(plan_content)

        task = _run(create_task(job_dir=job['job_dir'], task='Subtask', team='coding', agent='dev'))

        task_plan = os.path.join(task['worktree_path'], 'PLAN.md')
        self.assertTrue(os.path.isfile(task_plan),
                        'PLAN.md must be copied from parent job worktree to task worktree')
        self.assertEqual(Path(task_plan).read_text(), plan_content,
                         'copied PLAN.md must have the same content as the parent copy')

    def test_create_task_succeeds_when_parent_has_no_artifacts(self):
        """If parent has no INTENT.md or PLAN.md, create_task succeeds without error."""
        from teaparty.workspace.job_store import create_task
        job = self._make_job()
        # No INTENT.md or PLAN.md in parent worktree
        task = _run(create_task(job_dir=job['job_dir'], task='Subtask', team='coding', agent='dev'))
        self.assertIn('worktree_path', task,
                      'create_task must succeed even when parent has no artifacts')
        # Files must NOT exist in task worktree (nothing to copy)
        self.assertFalse(os.path.isfile(os.path.join(task['worktree_path'], 'INTENT.md')),
                         'INTENT.md must not appear in task worktree if parent had none')
        self.assertFalse(os.path.isfile(os.path.join(task['worktree_path'], 'PLAN.md')),
                         'PLAN.md must not appear in task worktree if parent had none')

    def test_create_task_copies_both_artifacts_independently(self):
        """Only the artifacts that exist in the parent are copied (partial inheritance)."""
        from teaparty.workspace.job_store import create_task
        job = self._make_job()
        # Write only INTENT.md, not PLAN.md
        Path(os.path.join(job['worktree_path'], 'INTENT.md')).write_text('# INTENT: Only intent')

        task = _run(create_task(job_dir=job['job_dir'], task='Subtask', team='coding', agent='dev'))

        self.assertTrue(os.path.isfile(os.path.join(task['worktree_path'], 'INTENT.md')),
                        'INTENT.md must be copied when present in parent')
        self.assertFalse(os.path.isfile(os.path.join(task['worktree_path'], 'PLAN.md')),
                         'PLAN.md must not appear when absent from parent')


# ── SC4: _generate_work_summary deleted ──────────────────────────────────────

class TestWorkSummaryGenerationDeleted(unittest.TestCase):
    """The programmatic work summary generator must be removed.
    WORK_SUMMARY.md is agent-written, not mechanically generated from git log.
    """

    def test_generate_work_summary_does_not_exist(self):
        """_generate_work_summary must not exist in actors — it is deleted in #407."""
        import teaparty.cfa.actors as actors_module
        self.assertFalse(
            hasattr(actors_module, '_generate_work_summary'),
            '_generate_work_summary must be deleted: WORK_SUMMARY.md is agent-written '
            '(not generated from git log). Its presence means the old behavior is intact.',
        )


# ── SC5: execution phase artifact ─────────────────────────────────────────────

class TestPhaseConfigArtifactName(unittest.TestCase):
    """The execution phase no longer has a mandatory artifact — in the
    five-state model, approval is the done-signal (not a summary file).
    The regression guard here is that the old ``.work-summary.md``
    name stays absent from the phase table.

    Source of truth is ``teaparty.cfa.phase_config._PHASES`` (literal
    Python constants); phase-config.json is gone.
    """

    def test_execution_artifact_is_null(self):
        """Execution phase artifact is None — approval is the done-signal."""
        from teaparty.cfa.phase_config import _PHASES
        from teaparty.cfa.statemachine.cfa_state import State
        artifact = _PHASES[State.EXECUTE].artifact
        self.assertIsNone(
            artifact,
            f'execution phase artifact must be None in the five-state '
            f'model (approval is the done-signal); got {artifact!r}.',
        )

    def test_execution_artifact_is_not_old_hidden_name(self):
        """No phase may reference the old .work-summary.md name."""
        from teaparty.cfa.phase_config import _PHASES
        for name, spec in _PHASES.items():
            self.assertNotEqual(
                spec.artifact, '.work-summary.md',
                f'{name} phase must not reference .work-summary.md',
            )


# ── SC6: _MERGE_EXCLUDE updated ───────────────────────────────────────────────

class TestMergeExcludeUpdated(unittest.TestCase):
    """_MERGE_EXCLUDE must track WORK_SUMMARY.md, not .work-summary.md."""

    def test_merge_exclude_contains_work_summary_md(self):
        """WORK_SUMMARY.md must be in _MERGE_EXCLUDE so it is never committed to main."""
        from teaparty.workspace.merge import _MERGE_EXCLUDE
        self.assertIn(
            'WORK_SUMMARY.md', _MERGE_EXCLUDE,
            'WORK_SUMMARY.md must be in _MERGE_EXCLUDE to prevent merging process artifacts to main',
        )

    def test_merge_exclude_does_not_contain_old_hidden_name(self):
        """_MERGE_EXCLUDE must not reference .work-summary.md (the old hidden name)."""
        from teaparty.workspace.merge import _MERGE_EXCLUDE
        self.assertNotIn(
            '.work-summary.md', _MERGE_EXCLUDE,
            '.work-summary.md must be removed from _MERGE_EXCLUDE (renamed to WORK_SUMMARY.md)',
        )

    def test_merge_exclude_still_contains_intent_and_plan(self):
        """INTENT.md and PLAN.md must remain in _MERGE_EXCLUDE (artifacts in worktree now)."""
        from teaparty.workspace.merge import _MERGE_EXCLUDE
        self.assertIn('INTENT.md', _MERGE_EXCLUDE,
                      'INTENT.md must remain in _MERGE_EXCLUDE')
        self.assertIn('PLAN.md', _MERGE_EXCLUDE,
                      'PLAN.md must remain in _MERGE_EXCLUDE')


if __name__ == '__main__':
    unittest.main()
