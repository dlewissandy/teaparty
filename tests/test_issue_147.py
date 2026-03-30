#!/usr/bin/env python3
"""Tests for issue #147: Session artifacts live in infra_dir, not the worktree.

Session infrastructure artifacts (INTENT.md, PLAN.md, .work-summary.md) should
be written to the session's infra directory, not the git worktree. The worktree
should only contain the project's real files and the session's actual deliverable.

These tests verify that:
  1. _generate_work_summary writes to infra_dir, not worktree
  2. archive_skill_candidate reads PLAN.md from infra_dir
  3. Merge exclusion includes INTENT.md and PLAN.md as safety net
  4. AgentRunner._interpret_output finds artifacts in infra_dir
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.merge import _is_excluded
from orchestrator.procedural_learning import archive_skill_candidate


def _run(coro):
    return asyncio.run(coro)


# ── _generate_work_summary targets infra_dir ───────────────────────────────


class TestWorkSummaryInInfraDir(unittest.TestCase):
    """.work-summary.md should be written to infra_dir, not worktree."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.worktree = os.path.join(self.tmpdir, 'worktree')
        self.infra_dir = os.path.join(self.tmpdir, 'infra')
        os.makedirs(self.worktree)
        os.makedirs(self.infra_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_work_summary_written_to_infra_dir(self):
        """_generate_work_summary accepts infra_dir and writes there."""
        from orchestrator.actors import _generate_work_summary
        import inspect

        # The function must accept an infra_dir parameter
        sig = inspect.signature(_generate_work_summary)
        params = list(sig.parameters.keys())
        self.assertIn('infra_dir', params,
                       '_generate_work_summary must accept infra_dir parameter')

    def test_work_summary_not_in_worktree(self):
        """After _generate_work_summary, .work-summary.md is in infra_dir, not worktree."""
        from orchestrator.actors import _generate_work_summary

        with patch('orchestrator.merge.git_output',
                   new_callable=AsyncMock) as mock_git:
            mock_git.return_value = ''
            _run(_generate_work_summary(self.worktree, infra_dir=self.infra_dir))

        self.assertTrue(
            os.path.isfile(os.path.join(self.infra_dir, '.work-summary.md')),
            '.work-summary.md should exist in infra_dir',
        )
        self.assertFalse(
            os.path.isfile(os.path.join(self.worktree, '.work-summary.md')),
            '.work-summary.md should NOT exist in worktree',
        )


# ── procedural_learning reads from infra_dir ───────────────────────────────


class TestProceduralLearningReadsInfraDir(unittest.TestCase):
    """archive_skill_candidate should read PLAN.md from infra_dir."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.infra_dir = os.path.join(self.tmpdir, 'infra')
        self.worktree = os.path.join(self.tmpdir, 'worktree')
        self.project_dir = os.path.join(self.tmpdir, 'project')
        os.makedirs(self.infra_dir)
        os.makedirs(self.worktree)
        os.makedirs(self.project_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_reads_plan_from_infra_dir(self):
        """archive_skill_candidate reads PLAN.md from infra_dir, not worktree."""
        # PLAN.md only in infra_dir
        Path(os.path.join(self.infra_dir, 'PLAN.md')).write_text('# Good Plan')

        result = archive_skill_candidate(
            infra_dir=self.infra_dir,
            project_dir=self.project_dir,
            task='test task',
            session_id='test-session',
        )

        self.assertTrue(result)
        candidate_path = os.path.join(
            self.project_dir, 'skill-candidates', 'test-session.md',
        )
        self.assertTrue(os.path.isfile(candidate_path))
        content = Path(candidate_path).read_text()
        self.assertIn('# Good Plan', content)

    def test_ignores_stale_plan_in_worktree(self):
        """archive_skill_candidate does NOT read a stale PLAN.md from worktree."""
        # Stale plan in worktree, nothing in infra_dir
        Path(os.path.join(self.worktree, 'PLAN.md')).write_text('# Stale')

        result = archive_skill_candidate(
            infra_dir=self.infra_dir,
            project_dir=self.project_dir,
            task='test task',
            session_id='test-session',
        )

        self.assertFalse(result)


# ── Merge exclusion safety net ─────────────────────────────────────────────


# ── Agent --add-dir includes infra_dir ──────────────────────────────────


class TestAddDirsEmpty(unittest.TestCase):
    """_build_add_dirs must return empty — superseded by issue #150.

    Issue #147 originally added infra_dir to --add-dir so agents could read
    artifacts. Issue #150 removed all --add-dir flags because absolute paths
    leak into agent context, causing writes to wrong locations. Artifacts
    are now accessed from within the worktree.
    """

    def test_build_add_dirs_returns_empty(self):
        """_build_add_dirs returns empty list (issue #150)."""
        from orchestrator.engine import Orchestrator

        orch = Orchestrator.__new__(Orchestrator)
        orch.session_worktree = '/tmp/worktree'
        orch.project_workdir = '/tmp/project'
        orch.infra_dir = '/tmp/infra'

        dirs = orch._build_add_dirs()
        self.assertEqual(dirs, [])


# ── Merge exclusion safety net ─────────────────────────────────────────────


class TestMergeExcludesSessionArtifacts(unittest.TestCase):
    """Merge exclusion list should include session artifacts as safety net.

    Even though artifacts should no longer be in the worktree, the exclusion
    list should catch them if they accidentally end up there.
    """

    def test_intent_excluded(self):
        self.assertTrue(_is_excluded('INTENT.md'))

    def test_plan_excluded(self):
        self.assertTrue(_is_excluded('PLAN.md'))

    def test_work_summary_excluded(self):
        self.assertTrue(_is_excluded('.work-summary.md'))

    def test_deliverable_not_excluded(self):
        """Actual deliverables must NOT be excluded."""
        self.assertFalse(_is_excluded('vegetable-joke-book.md'))
        self.assertFalse(_is_excluded('humor-research.md'))
