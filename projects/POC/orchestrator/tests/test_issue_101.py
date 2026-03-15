#!/usr/bin/env python3
"""Tests for issue #101: procedural learning — successful plans become reusable skills.

Covers:
 1. archive_skill_candidate writes a PLAN.md copy with metadata to skill-candidates/
 2. archive_skill_candidate is a no-op when PLAN.md is missing
 3. archive_skill_candidate includes task, session_id, and timestamp in frontmatter
 4. crystallize_skills identifies recurring patterns across candidates and writes a skill
 5. crystallize_skills skips candidates already marked as processed
 6. crystallize_skills requires a minimum number of candidates before extraction
 7. extract_learnings runs skill archival as part of the pipeline
 8. Full lifecycle: archive → crystallize → lookup finds the skill
"""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.skill_lookup import lookup_skill


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _make_plan(path: str, content: str = '') -> str:
    """Write a PLAN.md file and return its path."""
    if not content:
        content = (
            '## Decomposition\n\n'
            '1. Survey the literature\n'
            '2. Construct the argument\n'
            '3. Draft sections in parallel\n'
            '4. Edit for coherence\n'
        )
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(content)
    return path


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


# ── Tests: archive_skill_candidate ───────────────────────────────────────────

class TestArchiveSkillCandidate(unittest.TestCase):
    """archive_skill_candidate saves a successful plan as a skill candidate."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmpdir = self._td.name
        self.worktree = os.path.join(self.tmpdir, 'worktree')
        self.project_dir = os.path.join(self.tmpdir, 'project')
        os.makedirs(self.worktree)
        os.makedirs(self.project_dir)

    def tearDown(self):
        self._td.cleanup()

    def test_archives_plan_as_candidate(self):
        """When PLAN.md exists, it is copied to skill-candidates/ with frontmatter."""
        from projects.POC.orchestrator.procedural_learning import archive_skill_candidate

        _make_plan(os.path.join(self.worktree, 'PLAN.md'))

        archive_skill_candidate(
            session_worktree=self.worktree,
            project_dir=self.project_dir,
            task='Write a research paper on distributed systems',
            session_id='20260314-120000',
        )

        candidates_dir = os.path.join(self.project_dir, 'skill-candidates')
        self.assertTrue(os.path.isdir(candidates_dir))

        candidates = [f for f in os.listdir(candidates_dir) if f.endswith('.md')]
        self.assertEqual(len(candidates), 1)

        content = Path(os.path.join(candidates_dir, candidates[0])).read_text()
        self.assertIn('task:', content)
        self.assertIn('session_id:', content)
        self.assertIn('status: pending', content)
        self.assertIn('Survey the literature', content)

    def test_noop_when_plan_missing(self):
        """When PLAN.md does not exist, no candidate is written."""
        from projects.POC.orchestrator.procedural_learning import archive_skill_candidate

        archive_skill_candidate(
            session_worktree=self.worktree,
            project_dir=self.project_dir,
            task='Some task',
            session_id='20260314-120000',
        )

        candidates_dir = os.path.join(self.project_dir, 'skill-candidates')
        if os.path.isdir(candidates_dir):
            self.assertEqual(len(os.listdir(candidates_dir)), 0)

    def test_frontmatter_includes_metadata(self):
        """Candidate frontmatter includes task, session_id, timestamp, and status."""
        from projects.POC.orchestrator.procedural_learning import archive_skill_candidate

        _make_plan(os.path.join(self.worktree, 'PLAN.md'))

        archive_skill_candidate(
            session_worktree=self.worktree,
            project_dir=self.project_dir,
            task='Fix the login bug in the auth module',
            session_id='20260314-153000',
        )

        candidates_dir = os.path.join(self.project_dir, 'skill-candidates')
        candidates = [f for f in os.listdir(candidates_dir) if f.endswith('.md')]
        content = Path(os.path.join(candidates_dir, candidates[0])).read_text()

        self.assertIn('task: Fix the login bug in the auth module', content)
        self.assertIn('session_id: 20260314-153000', content)
        self.assertIn('status: pending', content)
        self.assertIn('timestamp:', content)

    def test_multiple_archives_create_separate_files(self):
        """Each session creates a distinct candidate file."""
        from projects.POC.orchestrator.procedural_learning import archive_skill_candidate

        _make_plan(os.path.join(self.worktree, 'PLAN.md'))

        archive_skill_candidate(
            session_worktree=self.worktree,
            project_dir=self.project_dir,
            task='Task one',
            session_id='session-001',
        )
        archive_skill_candidate(
            session_worktree=self.worktree,
            project_dir=self.project_dir,
            task='Task two',
            session_id='session-002',
        )

        candidates_dir = os.path.join(self.project_dir, 'skill-candidates')
        candidates = [f for f in os.listdir(candidates_dir) if f.endswith('.md')]
        self.assertEqual(len(candidates), 2)


# ── Tests: crystallize_skills ────────────────────────────────────────────────

class TestCrystallizeSkills(unittest.TestCase):
    """crystallize_skills generalizes recurring plan patterns into skill templates."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmpdir = self._td.name
        self.project_dir = os.path.join(self.tmpdir, 'project')
        os.makedirs(self.project_dir)
        self.candidates_dir = os.path.join(self.project_dir, 'skill-candidates')
        self.skills_dir = os.path.join(self.project_dir, 'skills')

    def tearDown(self):
        self._td.cleanup()

    def test_crystallize_produces_skill_from_similar_candidates(self):
        """Given 3+ similar candidates, crystallization produces a skill file."""
        from projects.POC.orchestrator.procedural_learning import crystallize_skills

        # Create 3 similar candidates (same category, similar structure)
        for i in range(3):
            _make_candidate(
                self.candidates_dir,
                f'candidate-{i}.md',
                task=f'Write a research paper on topic {i}',
                category='writing',
            )

        # Mock the LLM call that generalizes plans
        def fake_generalize(candidates_text):
            return (
                '---\n'
                'name: research-paper\n'
                'description: Write a research paper with survey and argument\n'
                'category: writing\n'
                '---\n\n'
                '## Decomposition\n\n'
                '1. Survey literature on {topic}\n'
                '2. Construct argument\n'
                '3. Draft sections\n'
                '4. Edit for coherence\n'
            )

        with patch(
            'projects.POC.orchestrator.procedural_learning._generalize_candidates',
            side_effect=fake_generalize,
        ):
            result = crystallize_skills(project_dir=self.project_dir)

        self.assertGreater(result, 0)
        self.assertTrue(os.path.isdir(self.skills_dir))
        skills = [f for f in os.listdir(self.skills_dir) if f.endswith('.md')]
        self.assertGreater(len(skills), 0)

    def test_crystallize_skips_processed_candidates(self):
        """Candidates with status=processed are not included in crystallization."""
        from projects.POC.orchestrator.procedural_learning import crystallize_skills

        _make_candidate(self.candidates_dir, 'old.md', status='processed')
        _make_candidate(self.candidates_dir, 'new-1.md', status='pending')
        _make_candidate(self.candidates_dir, 'new-2.md', status='pending')

        # Only 2 pending candidates — below threshold of 3
        result = crystallize_skills(project_dir=self.project_dir, min_candidates=3)
        self.assertEqual(result, 0)

    def test_crystallize_requires_minimum_candidates(self):
        """Crystallization does not run with fewer than min_candidates pending."""
        from projects.POC.orchestrator.procedural_learning import crystallize_skills

        _make_candidate(self.candidates_dir, 'only-one.md')

        result = crystallize_skills(project_dir=self.project_dir, min_candidates=3)
        self.assertEqual(result, 0)
        self.assertFalse(os.path.isdir(self.skills_dir))

    def test_crystallize_marks_candidates_as_processed(self):
        """After crystallization, source candidates are marked status=processed."""
        from projects.POC.orchestrator.procedural_learning import crystallize_skills

        for i in range(3):
            _make_candidate(self.candidates_dir, f'c-{i}.md')

        def fake_generalize(candidates_text):
            return (
                '---\nname: test-skill\ndescription: A test\ncategory: testing\n---\n\n'
                '## Steps\n1. Do thing\n'
            )

        with patch(
            'projects.POC.orchestrator.procedural_learning._generalize_candidates',
            side_effect=fake_generalize,
        ):
            crystallize_skills(project_dir=self.project_dir)

        for f in os.listdir(self.candidates_dir):
            if f.endswith('.md'):
                content = Path(os.path.join(self.candidates_dir, f)).read_text()
                self.assertIn('status: processed', content)

    def test_crystallize_noop_when_no_candidates_dir(self):
        """Returns 0 when skill-candidates/ does not exist."""
        from projects.POC.orchestrator.procedural_learning import crystallize_skills

        result = crystallize_skills(project_dir=self.project_dir)
        self.assertEqual(result, 0)


# ── Tests: integration with extract_learnings ────────────────────────────────

class TestProceduralLearningIntegration(unittest.TestCase):
    """Skill archival is wired into the post-session learning pipeline."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmpdir = self._td.name
        self.infra_dir = os.path.join(self.tmpdir, 'infra')
        self.project_dir = os.path.join(self.tmpdir, 'project')
        self.worktree = os.path.join(self.tmpdir, 'worktree')
        for d in (self.infra_dir, self.project_dir, self.worktree):
            os.makedirs(d)

    def tearDown(self):
        self._td.cleanup()

    def test_extract_learnings_runs_skill_archival(self):
        """extract_learnings includes skill archival in its pipeline."""
        from projects.POC.orchestrator.learnings import extract_learnings

        _make_plan(os.path.join(self.worktree, 'PLAN.md'))

        # Mock all the existing scopes so they don't fail
        with patch('projects.POC.orchestrator.learnings._run_summarize'), \
             patch('projects.POC.orchestrator.learnings._promote_team'), \
             patch('projects.POC.orchestrator.learnings._promote_session'), \
             patch('projects.POC.orchestrator.learnings._promote_project'), \
             patch('projects.POC.orchestrator.learnings._promote_global'), \
             patch('projects.POC.orchestrator.learnings._promote_prospective'), \
             patch('projects.POC.orchestrator.learnings._promote_in_flight'), \
             patch('projects.POC.orchestrator.learnings._promote_corrective'), \
             patch('projects.POC.orchestrator.learnings._reinforce_retrieved'):
            _run(extract_learnings(
                infra_dir=self.infra_dir,
                project_dir=self.project_dir,
                session_worktree=self.worktree,
                task='Write a research paper',
                poc_root='/tmp/poc',
            ))

        # A skill candidate should have been archived
        candidates_dir = os.path.join(self.project_dir, 'skill-candidates')
        self.assertTrue(os.path.isdir(candidates_dir))
        candidates = [f for f in os.listdir(candidates_dir) if f.endswith('.md')]
        self.assertGreater(len(candidates), 0)


# ── Tests: full lifecycle ────────────────────────────────────────────────────

class TestProceduralLearningLifecycle(unittest.TestCase):
    """End-to-end: archive plans → crystallize → lookup finds the skill."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmpdir = self._td.name
        self.project_dir = os.path.join(self.tmpdir, 'project')
        os.makedirs(self.project_dir)

    def tearDown(self):
        self._td.cleanup()

    def test_full_lifecycle(self):
        """Plans archived over 3 sessions → crystallize → lookup finds the skill."""
        from projects.POC.orchestrator.procedural_learning import (
            archive_skill_candidate,
            crystallize_skills,
        )

        # Simulate 3 sessions that each produce a similar plan
        for i in range(3):
            worktree = os.path.join(self.tmpdir, f'worktree-{i}')
            os.makedirs(worktree)
            _make_plan(
                os.path.join(worktree, 'PLAN.md'),
                content=(
                    '## Decomposition\n\n'
                    f'1. Survey the literature on topic {i}\n'
                    '2. Construct the argument\n'
                    '3. Draft sections in parallel\n'
                    '4. Edit for coherence\n'
                ),
            )
            archive_skill_candidate(
                session_worktree=worktree,
                project_dir=self.project_dir,
                task=f'Write a research paper on topic {i}',
                session_id=f'session-{i:03d}',
            )

        # Verify 3 candidates exist
        candidates_dir = os.path.join(self.project_dir, 'skill-candidates')
        pending = [
            f for f in os.listdir(candidates_dir)
            if f.endswith('.md')
        ]
        self.assertEqual(len(pending), 3)

        # Crystallize with mocked LLM
        def fake_generalize(candidates_text):
            return (
                '---\n'
                'name: research-paper\n'
                'description: Write a research paper with literature survey and argument construction\n'
                'category: writing\n'
                '---\n\n'
                '## Decomposition\n\n'
                '1. Survey literature on {topic}\n'
                '2. Construct argument\n'
                '3. Draft sections in parallel\n'
                '4. Edit for coherence\n'
            )

        with patch(
            'projects.POC.orchestrator.procedural_learning._generalize_candidates',
            side_effect=fake_generalize,
        ):
            crystallize_skills(project_dir=self.project_dir)

        # Lookup should find the crystallized skill
        skills_dir = os.path.join(self.project_dir, 'skills')
        result = lookup_skill(
            task='Write a research paper on distributed systems',
            intent='Research and write a paper surveying distributed consensus algorithms',
            skills_dir=skills_dir,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.name, 'research-paper')
        self.assertIn('Survey literature', result.template)


if __name__ == '__main__':
    unittest.main()
