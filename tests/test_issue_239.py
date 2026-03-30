"""Issue #239: archive_skill_candidate should write category to candidate frontmatter.

Tests:
 1. archive_skill_candidate writes category to frontmatter when provided
 2. archive_skill_candidate omits category line when not provided (backward compat)
 3. _cluster_candidates groups candidates with category metadata by category
 4. learnings wrapper reads category from skill file and passes it through
 5. engine correction path passes skill category to archive_skill_candidate
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


def _make_plan(path: str, content: str = '') -> None:
    """Write a minimal PLAN.md for testing."""
    Path(path).write_text(content or '## Plan\n\n1. Survey the literature\n2. Write the paper\n')


def _make_skill_file(path: str, *, name: str = 'test-skill',
                     category: str = 'debugging', description: str = 'A test skill') -> None:
    """Write a minimal skill file with frontmatter."""
    Path(path).write_text(
        f'---\nname: {name}\ndescription: {description}\ncategory: {category}\n---\n\n'
        f'## Workflow\n\n1. Do the thing\n'
    )


class TestArchiveCategoryInFrontmatter(unittest.TestCase):
    """archive_skill_candidate writes category to candidate frontmatter."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmpdir = self._td.name
        self.worktree = os.path.join(self.tmpdir, 'worktree')
        self.project_dir = os.path.join(self.tmpdir, 'project')
        os.makedirs(self.worktree)
        os.makedirs(self.project_dir)

    def tearDown(self):
        self._td.cleanup()

    def test_category_written_when_provided(self):
        """When category is provided, it appears in candidate frontmatter."""
        from orchestrator.procedural_learning import archive_skill_candidate

        _make_plan(os.path.join(self.worktree, 'PLAN.md'))

        result = archive_skill_candidate(
            session_worktree=self.worktree,
            project_dir=self.project_dir,
            task='Fix the auth bug',
            session_id='20260326-100000',
            category='debugging',
        )

        self.assertTrue(result)
        candidates_dir = os.path.join(self.project_dir, 'skill-candidates')
        content = Path(os.path.join(candidates_dir, '20260326-100000.md')).read_text()
        self.assertIn('category: debugging', content)

    def test_category_omitted_when_empty(self):
        """When category is not provided, no category line appears (backward compat)."""
        from orchestrator.procedural_learning import archive_skill_candidate

        _make_plan(os.path.join(self.worktree, 'PLAN.md'))

        archive_skill_candidate(
            session_worktree=self.worktree,
            project_dir=self.project_dir,
            task='Write a paper',
            session_id='20260326-100001',
        )

        candidates_dir = os.path.join(self.project_dir, 'skill-candidates')
        content = Path(os.path.join(candidates_dir, '20260326-100001.md')).read_text()
        self.assertNotIn('category:', content)


class TestClusterCandidatesWithCategory(unittest.TestCase):
    """_cluster_candidates groups candidates that have category metadata."""

    def test_candidates_with_same_category_cluster_together(self):
        """Candidates sharing a category field are grouped into one cluster."""
        from orchestrator.procedural_learning import _cluster_candidates

        candidates = [
            {'meta': {'task': 'fix login', 'category': 'debugging'}, 'body': ''},
            {'meta': {'task': 'fix signup', 'category': 'debugging'}, 'body': ''},
            {'meta': {'task': 'write docs', 'category': 'documentation'}, 'body': ''},
        ]

        clusters = _cluster_candidates(candidates)

        # Should get exactly 2 clusters: debugging (2 items) and documentation (1 item)
        self.assertEqual(len(clusters), 2)
        sizes = sorted(len(c) for c in clusters)
        self.assertEqual(sizes, [1, 2])

    def test_uncategorized_candidates_use_similarity_fallback(self):
        """Candidates without category still cluster by task similarity."""
        from orchestrator.procedural_learning import _cluster_candidates

        candidates = [
            {'meta': {'task': 'fix the login bug in auth'}, 'body': ''},
            {'meta': {'task': 'fix the signup bug in auth'}, 'body': ''},
        ]

        clusters = _cluster_candidates(candidates)
        # These share enough tokens to cluster together
        self.assertEqual(len(clusters), 1)


class TestLearningsWrapperPassesCategory(unittest.TestCase):
    """The learnings.py wrapper reads category from the skill file."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmpdir = self._td.name
        self.infra_dir = os.path.join(self.tmpdir, 'infra')
        self.worktree = os.path.join(self.tmpdir, 'worktree')
        self.project_dir = os.path.join(self.tmpdir, 'project')
        self.skills_dir = os.path.join(self.project_dir, 'skills')
        os.makedirs(self.infra_dir)
        os.makedirs(self.worktree)
        os.makedirs(self.project_dir)
        os.makedirs(self.skills_dir)

    def tearDown(self):
        self._td.cleanup()

    def test_category_from_active_skill(self):
        """When .active-skill.json exists, category is read from the skill file."""
        from orchestrator.learnings import _archive_skill_candidate

        # Create the skill file with a category
        skill_path = os.path.join(self.skills_dir, 'test-skill.md')
        _make_skill_file(skill_path, category='debugging')

        # Create the sidecar that points to the skill
        sidecar = {'name': 'test-skill', 'path': skill_path, 'score': '0.5', 'session_id': 'sess-1'}
        Path(os.path.join(self.infra_dir, '.active-skill.json')).write_text(json.dumps(sidecar))

        # Create PLAN.md
        _make_plan(os.path.join(self.infra_dir, 'PLAN.md'))

        with patch('orchestrator.procedural_learning.archive_skill_candidate') as mock_archive:
            mock_archive.return_value = True
            _archive_skill_candidate(
                infra_dir=self.infra_dir,
                session_worktree=self.worktree,
                project_dir=self.project_dir,
                task='Fix the bug',
                session_id='sess-1',
            )

            mock_archive.assert_called_once()
            call_kwargs = mock_archive.call_args[1]
            self.assertEqual(call_kwargs['category'], 'debugging')

    def test_no_category_without_active_skill(self):
        """When no .active-skill.json exists, category is empty."""
        from orchestrator.learnings import _archive_skill_candidate

        _make_plan(os.path.join(self.infra_dir, 'PLAN.md'))

        with patch('orchestrator.procedural_learning.archive_skill_candidate') as mock_archive:
            mock_archive.return_value = True
            _archive_skill_candidate(
                infra_dir=self.infra_dir,
                session_worktree=self.worktree,
                project_dir=self.project_dir,
                task='Write a paper',
                session_id='sess-2',
            )

            mock_archive.assert_called_once()
            call_kwargs = mock_archive.call_args[1]
            # Should not pass category, or pass empty string
            self.assertIn(call_kwargs.get('category', ''), ('', None))
