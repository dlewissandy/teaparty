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
        artifact = _PHASES['execution'].artifact
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


# ── SC7: _interpret_output finds artifact in session_worktree ─────────────────

class TestInterpretOutputFindsArtifactInWorktree(unittest.TestCase):
    """AgentRunner._interpret_output must find artifacts in session_worktree, not infra_dir."""

    def setUp(self):
        self.worktree = tempfile.mkdtemp()
        self.infra_dir = tempfile.mkdtemp()  # separate from worktree

    def tearDown(self):
        import shutil
        shutil.rmtree(self.worktree, ignore_errors=True)
        shutil.rmtree(self.infra_dir, ignore_errors=True)

    def _make_ctx(self, artifact: str) -> object:
        from teaparty.cfa.actors import ActorContext
        from teaparty.cfa.phase_config import PhaseSpec
        from teaparty.messaging.bus import EventBus
        from unittest.mock import AsyncMock, MagicMock
        bus = MagicMock(spec=EventBus)
        bus.publish = AsyncMock()
        spec = PhaseSpec(
            name='execution',
            agent_file='agents/uber-team.json',
            lead='project-lead',
            permission_mode='acceptEdits',
            stream_file='.exec-stream.jsonl',
            artifact=artifact,
            approval_state='WORK_ASSERT',
        )
        return ActorContext(
            state='WORK_IN_PROGRESS',
            phase='execution',
            task='Do the work',
            infra_dir=self.infra_dir,    # separate from worktree
            project_workdir='/tmp/proj',
            session_worktree=self.worktree,
            stream_file='.exec-stream.jsonl',
            phase_spec=spec,
            poc_root='/tmp/poc',
            event_bus=bus,
        )

    def test_work_summary_in_worktree_routes_to_assert(self):
        """WORK_SUMMARY.md in session_worktree (not infra_dir) must trigger assert action."""
        from teaparty.cfa.actors import AgentRunner
        from teaparty.runners.claude import ClaudeResult

        ctx = self._make_ctx('WORK_SUMMARY.md')
        # Write to worktree only — infra_dir does NOT have the file
        Path(os.path.join(self.worktree, 'WORK_SUMMARY.md')).write_text('# Work Summary\n')
        # Confirm infra_dir does NOT have it (test is only meaningful if they differ)
        self.assertFalse(os.path.isfile(os.path.join(self.infra_dir, 'WORK_SUMMARY.md')))

        runner = AgentRunner()
        result = runner._interpret_output(ctx, ClaudeResult(exit_code=0, session_id='s1'))

        self.assertEqual(
            result.action, 'assert',
            f'WORK_SUMMARY.md in session_worktree must trigger assert (got {result.action!r}). '
            'If this fails, _interpret_output is still looking in infra_dir.',
        )
        self.assertNotIn(
            'artifact_missing', result.data,
            'artifact_missing must not appear in result.data when artifact is found',
        )
        self.assertIn(
            'WORK_SUMMARY.md', result.data.get('artifact_path', ''),
            'artifact_path must reference WORK_SUMMARY.md in session_worktree',
        )

    def test_work_summary_in_infra_dir_only_not_found(self):
        """WORK_SUMMARY.md in infra_dir only (not session_worktree) must NOT be found.
        Artifacts belong in the worktree; infra_dir is not the artifact home anymore."""
        from teaparty.cfa.actors import AgentRunner
        from teaparty.runners.claude import ClaudeResult

        ctx = self._make_ctx('WORK_SUMMARY.md')
        # Write to infra_dir only — worktree does NOT have the file
        Path(os.path.join(self.infra_dir, 'WORK_SUMMARY.md')).write_text('# Old location\n')

        runner = AgentRunner()
        result = runner._interpret_output(ctx, ClaudeResult(exit_code=0, session_id='s1'))

        self.assertNotEqual(
            result.action, 'assert',
            'action must NOT be assert when WORK_SUMMARY.md is in infra_dir (wrong location) '
            'but not in session_worktree. If this fails, _interpret_output is still checking infra_dir.',
        )

    def test_intent_md_in_worktree_routes_to_assert(self):
        """INTENT.md in session_worktree (not infra_dir) must trigger assert action."""
        from teaparty.cfa.actors import AgentRunner, ActorContext
        from teaparty.cfa.phase_config import PhaseSpec
        from teaparty.messaging.bus import EventBus
        from teaparty.runners.claude import ClaudeResult
        from unittest.mock import AsyncMock, MagicMock

        bus = MagicMock(spec=EventBus)
        bus.publish = AsyncMock()
        spec = PhaseSpec(
            name='intent', agent_file='agents/intent.json',
            lead='intent-lead', permission_mode='acceptEdits',
            stream_file='.intent-stream.jsonl', artifact='INTENT.md',
            approval_state='INTENT_ASSERT',
        )
        ctx = ActorContext(
            state='PROPOSAL', phase='intent', task='Build the feature',
            infra_dir=self.infra_dir, project_workdir='/tmp/proj',
            session_worktree=self.worktree, stream_file='.intent-stream.jsonl',
            phase_spec=spec, poc_root='/tmp/poc', event_bus=bus,
        )
        # Write to worktree only
        Path(os.path.join(self.worktree, 'INTENT.md')).write_text('# INTENT: Test\n')
        self.assertFalse(os.path.isfile(os.path.join(self.infra_dir, 'INTENT.md')))

        runner = AgentRunner()
        result = runner._interpret_output(ctx, ClaudeResult(exit_code=0, session_id='s1'))

        self.assertEqual(
            result.action, 'assert',
            f'INTENT.md in session_worktree must trigger assert (got {result.action!r}). '
            'If this fails, _interpret_output is still looking in infra_dir.',
        )
        self.assertFalse(result.data.get('artifact_missing'),
                         'artifact_missing must be False when INTENT.md is in session_worktree')


# ── SC8: _check_skill_correction reads PLAN.md from session_worktree ─────────


class TestCheckSkillCorrectionReadsFromWorktree(unittest.TestCase):
    """``archive_skill_correction`` must read PLAN.md from session_worktree (issue #407).

    Before this fix, plan_path used infra_dir. After the artifact migration,
    PLAN.md is in session_worktree, so the old path always returned early (file
    not found), silently breaking skill self-correction (Issue #142).

    The hook moved out of Orchestrator in Cut 21; the regression guard
    is preserved against ``teaparty.learning.phase_hooks.archive_skill_correction``
    directly.
    """

    def test_plan_in_worktree_is_read_for_correction(self):
        """PLAN.md in session_worktree triggers skill correction comparison.

        If plan_path still uses infra_dir, the file is not found and the
        function returns early — active_skill would never produce a
        correction candidate regardless of whether the plan was modified.
        """
        from teaparty.learning.phase_hooks import archive_skill_correction

        with tempfile.TemporaryDirectory() as worktree, \
             tempfile.TemporaryDirectory() as infra_dir, \
             tempfile.TemporaryDirectory() as project_dir:

            # Write PLAN.md to worktree (correct location per #407)
            plan_content = '# Plan\n\nDo it differently than the original.\n'
            Path(os.path.join(worktree, 'PLAN.md')).write_text(plan_content)
            # Confirm infra_dir does NOT have it
            self.assertFalse(os.path.isfile(os.path.join(infra_dir, 'PLAN.md')))

            called = []
            try:
                import teaparty.learning.procedural.learning as _learning_mod
                original_archive = _learning_mod.archive_skill_candidate

                def _mock_archive(**kwargs):
                    called.append(kwargs)
                    return None

                _learning_mod.archive_skill_candidate = _mock_archive
                archive_skill_correction(
                    active_skill={
                        'name': 'test-skill',
                        'path': '',
                        'template': '# Plan\n\nOriginal template.\n',
                    },
                    session_worktree=worktree,
                    infra_dir=infra_dir,
                    project_workdir=project_dir,
                    task='Build the feature',
                    session_id='test-session',
                )
            finally:
                _learning_mod.archive_skill_candidate = original_archive

            self.assertTrue(
                called,
                'archive_skill_correction must detect plan modification and '
                'call archive_skill_candidate.  If this fails, plan_path is '
                'still using infra_dir — PLAN.md was not found (returns '
                'early before archive).',
            )

    def test_plan_in_infra_dir_only_not_found(self):
        """PLAN.md in infra_dir only must NOT trigger correction — wrong location.

        Load-bearing negative test: with the old code (infra_dir), the
        file WOULD be found.  With the fix (session_worktree), it is not
        found and the function returns early — no correction is attempted.
        """
        from teaparty.learning.phase_hooks import archive_skill_correction

        with tempfile.TemporaryDirectory() as worktree, \
             tempfile.TemporaryDirectory() as infra_dir, \
             tempfile.TemporaryDirectory() as project_dir:

            # Write PLAN.md to infra_dir ONLY (old/wrong location)
            plan_content = '# Plan\n\nModified version.\n'
            Path(os.path.join(infra_dir, 'PLAN.md')).write_text(plan_content)
            self.assertFalse(os.path.isfile(os.path.join(worktree, 'PLAN.md')))

            called = []
            try:
                import teaparty.learning.procedural.learning as _learning_mod
                original_archive = _learning_mod.archive_skill_candidate

                def _mock_archive(**kwargs):
                    called.append(kwargs)
                    return None

                _learning_mod.archive_skill_candidate = _mock_archive
                archive_skill_correction(
                    active_skill={
                        'name': 'test-skill',
                        'path': '',
                        'template': '# Plan\n\nOriginal template.\n',
                    },
                    session_worktree=worktree,
                    infra_dir=infra_dir,
                    project_workdir=project_dir,
                    task='Build the feature',
                    session_id='test-session',
                )
            finally:
                _learning_mod.archive_skill_candidate = original_archive

            self.assertFalse(
                called,
                'archive_skill_correction must NOT find PLAN.md in '
                'infra_dir (only session_worktree is checked after #407).  '
                'If this fails, plan_path is still using infra_dir.',
            )


# ── SC9: _build_artifact_context proxy search order ──────────────────────────


class TestProxyArtifactSearchOrder(unittest.TestCase):
    """_build_artifact_context must search worktree first, then infra_dir (issue #407).

    Before this fix, search order was (infra_dir, session_worktree).
    The correct order after #407 is (session_worktree, infra_dir) so the
    worktree copy is always preferred. WORK_SUMMARY.md replaces .work-summary.md.
    """

    def setUp(self):
        self.worktree_td = tempfile.TemporaryDirectory()
        self.infra_td = tempfile.TemporaryDirectory()
        self.worktree = self.worktree_td.name
        self.infra_dir = self.infra_td.name

    def tearDown(self):
        self.worktree_td.cleanup()
        self.infra_td.cleanup()

    def _call(self, state: str, artifact_path: str = '') -> list:
        from teaparty.proxy.agent import _build_artifact_context
        return _build_artifact_context(
            artifact_path=artifact_path,
            session_worktree=self.worktree,
            infra_dir=self.infra_dir,
            state=state,
        )

    def test_intent_md_found_in_worktree_preferred_over_infra(self):
        """When INTENT.md exists in both worktree and infra_dir, worktree path is used."""
        wt_intent = os.path.join(self.worktree, 'INTENT.md')
        infra_intent = os.path.join(self.infra_dir, 'INTENT.md')
        Path(wt_intent).write_text('# INTENT: Worktree version\n')
        Path(infra_intent).write_text('# INTENT: Infra version\n')

        parts = self._call('EXECUTE')

        intent_parts = [p for p in parts if 'INTENT.md' in p]
        self.assertEqual(len(intent_parts), 1,
                         f'Expected exactly 1 INTENT.md context entry, got {intent_parts}')
        self.assertIn(self.worktree, intent_parts[0],
                      'INTENT.md context must reference the worktree path, not infra_dir. '
                      'If this fails, search order is still (infra_dir, worktree).')
        self.assertNotIn(self.infra_dir, intent_parts[0],
                         'infra_dir INTENT.md must NOT be used when worktree copy exists')

    def test_intent_md_fallback_to_infra_when_worktree_missing(self):
        """When INTENT.md is only in infra_dir (old session), it is used as fallback."""
        infra_intent = os.path.join(self.infra_dir, 'INTENT.md')
        Path(infra_intent).write_text('# INTENT: Legacy session\n')
        self.assertFalse(os.path.isfile(os.path.join(self.worktree, 'INTENT.md')))

        parts = self._call('EXECUTE')

        intent_parts = [p for p in parts if 'INTENT.md' in p]
        self.assertEqual(len(intent_parts), 1)
        self.assertIn(self.infra_dir, intent_parts[0],
                      'infra_dir fallback must be used when INTENT.md is absent from worktree')

    def test_work_summary_md_name_used_not_dot_work_summary(self):
        """WORK_SUMMARY.md (not .work-summary.md) is the artifact name searched."""
        # Write WORK_SUMMARY.md (new name)
        Path(os.path.join(self.worktree, 'WORK_SUMMARY.md')).write_text('# Work Summary\n')
        # Also write the old name — it must NOT appear
        Path(os.path.join(self.worktree, '.work-summary.md')).write_text('# Old hidden file\n')

        parts = self._call('EXECUTE')

        summary_parts = [p for p in parts if 'WORK_SUMMARY.md' in p]
        old_parts = [p for p in parts if '.work-summary.md' in p]

        self.assertEqual(len(summary_parts), 1,
                         'WORK_SUMMARY.md must appear in context for EXECUTE state. '
                         'If this fails, the artifact name was not updated from .work-summary.md.')
        self.assertEqual(len(old_parts), 0,
                         '.work-summary.md must NOT appear — it is the old hidden artifact name')

    def test_plan_md_found_in_worktree_for_execute(self):
        """PLAN.md in worktree is included in EXECUTE context (worktree-first)."""
        wt_plan = os.path.join(self.worktree, 'PLAN.md')
        infra_plan = os.path.join(self.infra_dir, 'PLAN.md')
        Path(wt_plan).write_text('# Plan: worktree\n')
        Path(infra_plan).write_text('# Plan: infra\n')

        parts = self._call('EXECUTE')

        plan_parts = [p for p in parts if 'PLAN.md' in p]
        self.assertEqual(len(plan_parts), 1)
        self.assertIn(self.worktree, plan_parts[0],
                      'PLAN.md context must reference worktree path for EXECUTE. '
                      'If this fails, search order is still (infra_dir, worktree).')


if __name__ == '__main__':
    unittest.main()
