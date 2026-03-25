#!/usr/bin/env python3
"""Tests for issue #40: Git commits as version tracking for session artifacts.

Covers:
 1. commit_artifact() stages and commits specified files.
 2. artifact_version() returns the correct version number from git history.
 3. Engine._commit_artifacts() does NOT commit INTENT.md (Issue #148).
 4. Engine._commit_artifacts() does NOT commit PLAN.md (Issue #148).
 5. Engine._commit_artifacts() commits all files on TASK_ASSERT transition.
 6. Commit failures are non-fatal (logged, not raised).
"""
import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.worktree import artifact_version, commit_artifact
from projects.POC.orchestrator.engine import Orchestrator
from projects.POC.orchestrator.events import EventBus
from projects.POC.scripts.cfa_state import make_initial_state, transition


def _run(coro):
    return asyncio.run(coro)


def _init_git_repo(path: str) -> None:
    """Initialize a git repo with an initial commit."""
    subprocess.run(['git', 'init'], cwd=path, capture_output=True, check=True)
    subprocess.run(
        ['git', 'commit', '--allow-empty', '-m', 'init'],
        cwd=path, capture_output=True, check=True,
    )


def _git_log_oneline(path: str, filename: str = '') -> list[str]:
    """Return git log --oneline entries, optionally filtered by filename."""
    cmd = ['git', 'log', '--oneline']
    if filename:
        cmd += ['--', filename]
    result = subprocess.run(cmd, cwd=path, capture_output=True, text=True)
    return [l for l in result.stdout.strip().split('\n') if l]


# ── worktree.commit_artifact tests ─────────────────────────────────────────


class TestCommitArtifact(unittest.TestCase):
    """commit_artifact() stages and commits files in a worktree."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        _init_git_repo(self.tmpdir)

    def test_commits_single_file(self):
        """A single artifact file is committed with the given message."""
        Path(self.tmpdir, 'INTENT.md').write_text('# Intent\n')
        _run(commit_artifact(self.tmpdir, ['INTENT.md'], 'Intent v1: assert'))

        log = _git_log_oneline(self.tmpdir, 'INTENT.md')
        self.assertEqual(len(log), 1)
        self.assertIn('Intent v1: assert', log[0])

    def test_commits_multiple_files(self):
        """Multiple paths are staged and committed together."""
        Path(self.tmpdir, 'INTENT.md').write_text('# Intent\n')
        Path(self.tmpdir, 'PLAN.md').write_text('# Plan\n')
        _run(commit_artifact(self.tmpdir, ['INTENT.md', 'PLAN.md'], 'batch'))

        log = _git_log_oneline(self.tmpdir)
        # Should have 2 commits: init + batch
        self.assertEqual(len(log), 2)
        self.assertIn('batch', log[0])

    def test_noop_when_nothing_changed(self):
        """No new commit is created if the file hasn't changed."""
        Path(self.tmpdir, 'INTENT.md').write_text('# Intent\n')
        _run(commit_artifact(self.tmpdir, ['INTENT.md'], 'v1'))

        # Commit again without changes
        _run(commit_artifact(self.tmpdir, ['INTENT.md'], 'v2'))

        log = _git_log_oneline(self.tmpdir, 'INTENT.md')
        self.assertEqual(len(log), 1, 'Should not create empty commit')

    def test_commits_all_via_dot(self):
        """Using '.' as path commits all changes (execution deliverables)."""
        Path(self.tmpdir, 'output.txt').write_text('result\n')
        Path(self.tmpdir, 'report.md').write_text('# Report\n')
        _run(commit_artifact(self.tmpdir, ['.'], 'Execution: assert'))

        log = _git_log_oneline(self.tmpdir)
        self.assertEqual(len(log), 2)
        self.assertIn('Execution: assert', log[0])


class TestArtifactVersion(unittest.TestCase):
    """artifact_version() derives version from git history."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        _init_git_repo(self.tmpdir)

    def test_version_starts_at_1(self):
        """First version of a new artifact is 1."""
        v = _run(artifact_version(self.tmpdir, 'INTENT.md'))
        self.assertEqual(v, 1)

    def test_version_increments(self):
        """Version increments with each commit that touches the file."""
        Path(self.tmpdir, 'INTENT.md').write_text('v1\n')
        _run(commit_artifact(self.tmpdir, ['INTENT.md'], 'v1'))

        v = _run(artifact_version(self.tmpdir, 'INTENT.md'))
        self.assertEqual(v, 2)

    def test_version_ignores_other_files(self):
        """Commits to other files don't affect the version count."""
        Path(self.tmpdir, 'INTENT.md').write_text('intent\n')
        _run(commit_artifact(self.tmpdir, ['INTENT.md'], 'intent'))

        Path(self.tmpdir, 'PLAN.md').write_text('plan\n')
        _run(commit_artifact(self.tmpdir, ['PLAN.md'], 'plan'))

        v = _run(artifact_version(self.tmpdir, 'INTENT.md'))
        self.assertEqual(v, 2, 'PLAN.md commit should not affect INTENT.md version')


# ── Engine._commit_artifacts integration ───────────────────────────────────


def _make_orchestrator(tmpdir: str, cfa_state=None) -> Orchestrator:
    """Create a minimal Orchestrator with a real git worktree."""
    infra_dir = os.path.join(tmpdir, '.session')
    worktree = os.path.join(tmpdir, 'worktree')
    project_dir = os.path.join(tmpdir, 'project')
    os.makedirs(infra_dir, exist_ok=True)
    os.makedirs(worktree, exist_ok=True)
    os.makedirs(project_dir, exist_ok=True)

    _init_git_repo(worktree)

    if cfa_state is None:
        cfa = make_initial_state(task_id='test')
        cfa = transition(cfa, 'propose')   # → PROPOSAL
        cfa = transition(cfa, 'assert')    # → INTENT_ASSERT
    else:
        cfa = cfa_state

    config = MagicMock()
    bus = EventBus()

    return Orchestrator(
        cfa_state=cfa,
        phase_config=config,
        event_bus=bus,
        input_provider=AsyncMock(),
        infra_dir=infra_dir,
        project_workdir=project_dir,
        session_worktree=worktree,
        proxy_model_path=os.path.join(tmpdir, '.proxy.json'),
        project_slug='test-project',
        poc_root=tmpdir,
        task='test task',
        session_id='20260314-160000',
    )


def _make_actor_result(action='approve'):
    from projects.POC.orchestrator.actors import ActorResult
    return ActorResult(action=action, data={})


class TestEngineCommitOnIntentAssert(unittest.TestCase):
    """Engine must NOT commit INTENT.md — it lives only in infra_dir.  Issue #148."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_intent_committed_on_assert(self):
        """INTENT.md must not appear in git history after INTENT_ASSERT.
        Artifacts live only in infra_dir, not the worktree.  Issue #148."""
        cfa = make_initial_state(task_id='test')
        cfa = transition(cfa, 'propose')  # → PROPOSAL

        orch = _make_orchestrator(self.tmpdir, cfa_state=cfa)
        Path(orch.session_worktree, 'INTENT.md').write_text('# Intent\nDo a thing.\n')

        _run(orch._transition('assert', _make_actor_result(action='assert')))

        self.assertEqual(orch.cfa.state, 'INTENT_ASSERT')
        log = _git_log_oneline(orch.session_worktree, 'INTENT.md')
        self.assertEqual(len(log), 0)


class TestEngineCommitOnPlanAssert(unittest.TestCase):
    """Engine must NOT commit PLAN.md — it lives only in infra_dir.  Issue #148."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_plan_committed_on_assert(self):
        """PLAN.md must not appear in git history after PLAN_ASSERT.
        Artifacts live only in infra_dir, not the worktree.  Issue #148."""
        cfa = make_initial_state(task_id='test')
        cfa = transition(cfa, 'propose')       # → PROPOSAL
        cfa = transition(cfa, 'auto-approve')   # → INTENT
        cfa = transition(cfa, 'plan')           # → DRAFT

        orch = _make_orchestrator(self.tmpdir, cfa_state=cfa)
        Path(orch.session_worktree, 'PLAN.md').write_text('# Plan\nStep 1.\n')

        _run(orch._transition('assert', _make_actor_result(action='assert')))

        self.assertEqual(orch.cfa.state, 'PLAN_ASSERT')
        log = _git_log_oneline(orch.session_worktree, 'PLAN.md')
        self.assertEqual(len(log), 0)


class TestEngineCommitOnTaskAssert(unittest.TestCase):
    """Engine auto-commits all deliverables when transitioning to TASK_ASSERT."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_deliverables_committed_on_assert(self):
        """When agent asserts execution (TASK_IN_PROGRESS → TASK_ASSERT),
        all deliverables are committed to the session worktree."""
        cfa = make_initial_state(task_id='test')
        cfa = transition(cfa, 'propose')       # → PROPOSAL
        cfa = transition(cfa, 'auto-approve')   # → INTENT
        cfa = transition(cfa, 'plan')           # → DRAFT
        cfa = transition(cfa, 'auto-approve')   # → PLAN
        cfa = transition(cfa, 'delegate')       # → TASK
        cfa = transition(cfa, 'accept')         # → TASK_IN_PROGRESS

        orch = _make_orchestrator(self.tmpdir, cfa_state=cfa)
        Path(orch.session_worktree, 'output.py').write_text('print("hello")\n')
        Path(orch.session_worktree, 'tests.py').write_text('assert True\n')

        _run(orch._transition('assert', _make_actor_result(action='assert')))

        self.assertEqual(orch.cfa.state, 'TASK_ASSERT')
        log = _git_log_oneline(orch.session_worktree)
        # init + execution commit = 2
        self.assertEqual(len(log), 2)
        self.assertIn('Execution: assert', log[0])


class TestEngineCommitFailureNonFatal(unittest.TestCase):
    """Commit failures must not crash the orchestrator."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_commit_failure_is_logged_not_raised(self):
        """If git commit fails, _transition still completes normally."""
        cfa = make_initial_state(task_id='test')
        cfa = transition(cfa, 'propose')  # → PROPOSAL

        orch = _make_orchestrator(self.tmpdir, cfa_state=cfa)
        # Don't create INTENT.md — commit will fail (nothing to commit)
        # But worktree is a real git repo, so artifact_version should work

        # This should complete without raising
        _run(orch._transition('assert', _make_actor_result(action='assert')))
        self.assertEqual(orch.cfa.state, 'INTENT_ASSERT')


class TestEngineVersionIncrementsOnCorrection(unittest.TestCase):
    """INTENT.md must not be committed even after correction cycles.  Issue #148."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def test_intent_not_committed_after_correction(self):
        """After correction cycles, INTENT.md must still not be in git history.
        Artifacts live only in infra_dir.  Issue #148."""
        # First assertion: PROPOSAL → INTENT_ASSERT
        cfa = make_initial_state(task_id='test')
        cfa = transition(cfa, 'propose')  # → PROPOSAL

        orch = _make_orchestrator(self.tmpdir, cfa_state=cfa)
        Path(orch.session_worktree, 'INTENT.md').write_text('v1 intent\n')
        _run(orch._transition('assert', _make_actor_result(action='assert')))

        # Correction cycle: INTENT_ASSERT → correct → INTENT_RESPONSE
        _run(orch._transition('correct', _make_actor_result(action='correct')))
        # INTENT_RESPONSE → synthesize → PROPOSAL
        _run(orch._transition('synthesize', _make_actor_result(action='synthesize')))

        # Re-assertion: PROPOSAL → assert → INTENT_ASSERT
        Path(orch.session_worktree, 'INTENT.md').write_text('v2 intent (corrected)\n')
        _run(orch._transition('assert', _make_actor_result(action='assert')))

        self.assertEqual(orch.cfa.state, 'INTENT_ASSERT')
        log = _git_log_oneline(orch.session_worktree, 'INTENT.md')
        self.assertEqual(len(log), 0)


if __name__ == '__main__':
    unittest.main()
