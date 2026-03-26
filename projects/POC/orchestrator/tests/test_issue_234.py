#!/usr/bin/env python3
"""Tests for issue #234: skill crystallization clusters candidates by similarity.

Covers:
 1. Candidates with different categories are clustered separately
 2. Each cluster produces an independent skill (not one merged skill)
 3. Candidates with same category but dissimilar tasks are split
 4. Mixed candidates: some cluster, some don't meet min_candidates
 5. Single-category candidates still work (backward compat)
 6. _cluster_candidates groups by category then by task similarity
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, call

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_candidate(
    candidates_dir: str,
    filename: str,
    *,
    task: str = 'Write a research paper',
    category: str = 'writing',
    status: str = 'pending',
    body: str = '',
) -> str:
    """Write a skill candidate file with frontmatter and return its path."""
    if not body:
        body = (
            '## Decomposition\n\n'
            '1. Survey\n2. Argue\n3. Draft\n4. Edit\n'
        )
    content = (
        f'---\n'
        f'task: {task}\n'
        f'category: {category}\n'
        f'status: {status}\n'
        f'session_id: test-session\n'
        f'timestamp: 2026-03-14T12:00:00\n'
        f'---\n\n'
        f'{body}'
    )
    Path(candidates_dir).mkdir(parents=True, exist_ok=True)
    path = os.path.join(candidates_dir, filename)
    Path(path).write_text(content)
    return path


def _fake_generalize(candidates_text):
    """Return a valid skill based on candidates_text content."""
    # Detect category from the candidates to produce distinguishable skills
    if 'debug' in candidates_text.lower():
        return (
            '---\n'
            'name: debug-workflow\n'
            'description: Debug a production issue\n'
            'category: debugging\n'
            '---\n\n'
            '## Steps\n1. Reproduce\n2. Isolate\n3. Fix\n'
        )
    if 'refactor' in candidates_text.lower():
        return (
            '---\n'
            'name: refactor-workflow\n'
            'description: Refactor a module\n'
            'category: refactoring\n'
            '---\n\n'
            '## Steps\n1. Identify\n2. Extract\n3. Verify\n'
        )
    return (
        '---\n'
        'name: research-paper\n'
        'description: Write a research paper\n'
        'category: writing\n'
        '---\n\n'
        '## Steps\n1. Survey\n2. Draft\n3. Edit\n'
    )


# ── Tests: clustering behavior ────────────────────────────────────────────────

class TestCrystallizeClustering(unittest.TestCase):
    """crystallize_skills clusters candidates by similarity before generalizing."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmpdir = self._td.name
        self.project_dir = os.path.join(self.tmpdir, 'project')
        os.makedirs(self.project_dir)
        self.candidates_dir = os.path.join(self.project_dir, 'skill-candidates')
        self.skills_dir = os.path.join(self.project_dir, 'skills')

    def tearDown(self):
        self._td.cleanup()

    def test_different_categories_produce_separate_skills(self):
        """Candidates with different categories are clustered separately,
        each cluster producing its own skill."""
        from projects.POC.orchestrator.procedural_learning import crystallize_skills

        # 3 writing candidates
        for i in range(3):
            _make_candidate(
                self.candidates_dir, f'write-{i}.md',
                task=f'Write a research paper on topic {i}',
                category='writing',
            )

        # 3 debugging candidates
        for i in range(3):
            _make_candidate(
                self.candidates_dir, f'debug-{i}.md',
                task=f'Debug production issue {i}',
                category='debugging',
                body='## Steps\n1. Reproduce\n2. Isolate\n3. Fix\n',
            )

        with patch(
            'projects.POC.orchestrator.procedural_learning._generalize_candidates',
            side_effect=_fake_generalize,
        ):
            result = crystallize_skills(project_dir=self.project_dir)

        # Two separate skills should be produced, not one merged skill
        self.assertEqual(result, 2)
        self.assertTrue(os.path.isdir(self.skills_dir))
        skills = sorted(f for f in os.listdir(self.skills_dir) if f.endswith('.md'))
        self.assertEqual(len(skills), 2)

    def test_generalize_called_once_per_cluster(self):
        """_generalize_candidates is called once per cluster, not once for all."""
        from projects.POC.orchestrator.procedural_learning import crystallize_skills

        for i in range(3):
            _make_candidate(
                self.candidates_dir, f'write-{i}.md',
                task=f'Write a research paper on topic {i}',
                category='writing',
            )
        for i in range(3):
            _make_candidate(
                self.candidates_dir, f'debug-{i}.md',
                task=f'Debug production issue {i}',
                category='debugging',
                body='## Steps\n1. Reproduce\n2. Isolate\n3. Fix\n',
            )

        with patch(
            'projects.POC.orchestrator.procedural_learning._generalize_candidates',
            side_effect=_fake_generalize,
        ) as mock_gen:
            crystallize_skills(project_dir=self.project_dir)

        # Called twice: once per category cluster
        self.assertEqual(mock_gen.call_count, 2)

    def test_mixed_candidates_only_crystallize_sufficient_clusters(self):
        """Clusters below min_candidates threshold are skipped."""
        from projects.POC.orchestrator.procedural_learning import crystallize_skills

        # 3 writing candidates — meets threshold
        for i in range(3):
            _make_candidate(
                self.candidates_dir, f'write-{i}.md',
                task=f'Write a research paper on topic {i}',
                category='writing',
            )

        # 1 debugging candidate — below threshold
        _make_candidate(
            self.candidates_dir, 'debug-0.md',
            task='Debug production issue',
            category='debugging',
            body='## Steps\n1. Reproduce\n2. Fix\n',
        )

        with patch(
            'projects.POC.orchestrator.procedural_learning._generalize_candidates',
            side_effect=_fake_generalize,
        ) as mock_gen:
            result = crystallize_skills(project_dir=self.project_dir)

        # Only writing cluster meets threshold
        self.assertEqual(result, 1)
        self.assertEqual(mock_gen.call_count, 1)

        # The debugging candidate should still be pending (not marked processed)
        debug_path = os.path.join(self.candidates_dir, 'debug-0.md')
        content = Path(debug_path).read_text()
        self.assertIn('status: pending', content)

    def test_single_category_backward_compat(self):
        """When all candidates share one category, behavior is the same as before."""
        from projects.POC.orchestrator.procedural_learning import crystallize_skills

        for i in range(3):
            _make_candidate(
                self.candidates_dir, f'candidate-{i}.md',
                task=f'Write a research paper on topic {i}',
                category='writing',
            )

        with patch(
            'projects.POC.orchestrator.procedural_learning._generalize_candidates',
            side_effect=_fake_generalize,
        ):
            result = crystallize_skills(project_dir=self.project_dir)

        self.assertEqual(result, 1)
        skills = [f for f in os.listdir(self.skills_dir) if f.endswith('.md')]
        self.assertEqual(len(skills), 1)

    def test_no_category_candidates_grouped_by_task_similarity(self):
        """Candidates without category metadata are grouped by task token similarity."""
        from projects.POC.orchestrator.procedural_learning import crystallize_skills

        # 3 similar tasks (no explicit category)
        for i in range(3):
            _make_candidate(
                self.candidates_dir, f'write-{i}.md',
                task=f'Write a research paper on topic {i}',
                category='',
            )

        # 3 different tasks (no explicit category)
        for i in range(3):
            _make_candidate(
                self.candidates_dir, f'debug-{i}.md',
                task=f'Debug and fix production crash number {i}',
                category='',
                body='## Steps\n1. Reproduce\n2. Isolate\n3. Fix\n',
            )

        with patch(
            'projects.POC.orchestrator.procedural_learning._generalize_candidates',
            side_effect=_fake_generalize,
        ):
            result = crystallize_skills(project_dir=self.project_dir)

        # Should produce 2 skills from similarity-based clusters, not 1 merged skill
        self.assertEqual(result, 2)


# ── Tests: _cluster_candidates helper ─────────────────────────────────────────

class TestClusterCandidates(unittest.TestCase):
    """_cluster_candidates groups candidates by category + task similarity."""

    def test_groups_by_category(self):
        """Candidates with different categories land in different clusters."""
        from projects.POC.orchestrator.procedural_learning import _cluster_candidates

        candidates = [
            {'meta': {'category': 'writing', 'task': 'Write a paper'}, 'body': ''},
            {'meta': {'category': 'writing', 'task': 'Write an essay'}, 'body': ''},
            {'meta': {'category': 'debugging', 'task': 'Debug a crash'}, 'body': ''},
            {'meta': {'category': 'debugging', 'task': 'Debug an error'}, 'body': ''},
        ]

        clusters = _cluster_candidates(candidates)
        self.assertEqual(len(clusters), 2)

        categories = {c[0]['meta']['category'] for c in clusters}
        self.assertEqual(categories, {'writing', 'debugging'})

    def test_no_category_falls_back_to_similarity(self):
        """Candidates without category are grouped by task description similarity."""
        from projects.POC.orchestrator.procedural_learning import _cluster_candidates

        candidates = [
            {'meta': {'category': '', 'task': 'Write a research paper on AI'}, 'body': ''},
            {'meta': {'category': '', 'task': 'Write a research paper on ML'}, 'body': ''},
            {'meta': {'category': '', 'task': 'Debug the login crash'}, 'body': ''},
            {'meta': {'category': '', 'task': 'Debug the auth failure'}, 'body': ''},
        ]

        clusters = _cluster_candidates(candidates)
        # Should produce 2 clusters based on task similarity
        self.assertEqual(len(clusters), 2)


if __name__ == '__main__':
    unittest.main()
