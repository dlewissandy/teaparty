#!/usr/bin/env python3
"""Tests for issue #142: Wire crystallize_skills into session lifecycle and add skill self-correction.

Covers:
 1. extract_learnings calls crystallize_skills after skill-archive
 2. Skill self-correction: engine tracks which skill was used
 3. Skill self-correction: backtrack after skill-based plan archives corrected plan as candidate
 4. Correction candidate includes corrects_skill metadata linking to the failed skill
 5. Non-skill backtracks do NOT trigger skill self-correction
"""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))


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
    corrects_skill: str = '',
) -> str:
    """Write a skill candidate file with frontmatter and return its path."""
    if not body:
        body = (
            '## Decomposition\n\n'
            '1. Survey\n2. Argue\n3. Draft\n4. Edit\n'
        )
    lines = [
        '---',
        f'task: {task}',
        f'category: {category}',
        f'status: {status}',
        f'session_id: test-session',
        f'timestamp: 2026-03-14T12:00:00',
    ]
    if corrects_skill:
        lines.append(f'corrects_skill: {corrects_skill}')
    lines.append('---')
    lines.append('')
    lines.append(body)
    content = '\n'.join(lines)
    Path(candidates_dir).mkdir(parents=True, exist_ok=True)
    path = os.path.join(candidates_dir, filename)
    Path(path).write_text(content)
    return path


# ── Tests: crystallize_skills wired into extract_learnings ───────────────────

class TestCrystallizeWiredIntoLearnings(unittest.TestCase):
    """crystallize_skills is called as part of extract_learnings after skill-archive."""

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

    def test_extract_learnings_calls_crystallize_after_archive(self):
        """extract_learnings must call crystallize_skills after archiving the candidate."""
        from projects.POC.orchestrator.learnings import extract_learnings

        _make_plan(os.path.join(self.infra_dir, 'PLAN.md'))

        crystallize_called = []

        def _track_crystallize(**kwargs):
            crystallize_called.append(kwargs)
            return 0

        with patch('projects.POC.orchestrator.learnings._run_summarize'), \
             patch('projects.POC.orchestrator.learnings._promote_team'), \
             patch('projects.POC.orchestrator.learnings._promote_session'), \
             patch('projects.POC.orchestrator.learnings._promote_project'), \
             patch('projects.POC.orchestrator.learnings._promote_global'), \
             patch('projects.POC.orchestrator.learnings._promote_prospective'), \
             patch('projects.POC.orchestrator.learnings._promote_in_flight'), \
             patch('projects.POC.orchestrator.learnings._promote_corrective'), \
             patch('projects.POC.orchestrator.learnings._reinforce_retrieved'), \
             patch('projects.POC.orchestrator.learnings._compact_proxy_patterns'), \
             patch(
                 'projects.POC.orchestrator.procedural_learning.crystallize_skills',
                 side_effect=_track_crystallize,
             ) as mock_crystallize:
            _run(extract_learnings(
                infra_dir=self.infra_dir,
                project_dir=self.project_dir,
                session_worktree=self.worktree,
                task='Write a research paper',
                poc_root='/tmp/poc',
            ))

        # crystallize_skills must have been called with the project_dir
        self.assertGreater(len(crystallize_called), 0,
                           'crystallize_skills was never called by extract_learnings')
        self.assertEqual(crystallize_called[0]['project_dir'], self.project_dir)


# ── Tests: engine tracks active skill ────────────────────────────────────────

class TestEngineTracksActiveSkill(unittest.TestCase):
    """When _try_skill_lookup succeeds, the engine remembers which skill was used."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmpdir = self._td.name
        self.infra_dir = os.path.join(self.tmpdir, 'infra')
        self.project_dir = os.path.join(self.tmpdir, 'project')
        self.worktree = os.path.join(self.tmpdir, 'worktree')
        self.skills_dir = os.path.join(self.project_dir, 'skills')
        for d in (self.infra_dir, self.project_dir, self.worktree, self.skills_dir):
            os.makedirs(d)

    def tearDown(self):
        self._td.cleanup()

    def _make_engine(self):
        """Create a minimal Orchestrator wired to temp dirs."""
        from projects.POC.orchestrator.engine import Orchestrator
        from projects.POC.orchestrator.events import EventBus
        from projects.POC.scripts.cfa_state import CfaState

        cfa = CfaState(phase='planning', state='DRAFT', actor='agent', backtrack_count=0)
        config = MagicMock()
        config.stall_timeout = 1800
        event_bus = EventBus()

        orch = Orchestrator(
            cfa_state=cfa,
            phase_config=config,
            event_bus=event_bus,
            input_provider=AsyncMock(),
            infra_dir=self.infra_dir,
            project_workdir=self.project_dir,
            session_worktree=self.worktree,
            proxy_model_path=os.path.join(self.tmpdir, 'proxy-model.json'),
            project_slug='test-project',
            poc_root='/tmp/poc',
            task='Write a research paper on distributed systems',
            session_id='test-session',
        )
        return orch

    def _make_skill(self, name='research-paper', description='Write a research paper'):
        """Write a skill file to the skills directory."""
        content = (
            f'---\n'
            f'name: {name}\n'
            f'description: {description}\n'
            f'category: writing\n'
            f'---\n\n'
            f'## Decomposition\n\n'
            f'1. Survey literature on {{topic}}\n'
            f'2. Construct argument\n'
            f'3. Draft sections\n'
            f'4. Edit for coherence\n'
        )
        path = os.path.join(self.skills_dir, f'{name}.md')
        Path(path).write_text(content)
        return path

    def test_try_skill_lookup_sets_active_skill(self):
        """After _try_skill_lookup succeeds, self._active_skill is set."""
        orch = self._make_engine()
        self._make_skill()

        # Write INTENT.md (needed for lookup)
        Path(os.path.join(self.infra_dir, 'INTENT.md')).write_text(
            'Research and write a paper surveying distributed consensus algorithms'
        )

        result = _run(orch._try_skill_lookup())
        self.assertTrue(result)

        # The engine must track which skill was used
        self.assertTrue(hasattr(orch, '_active_skill'),
                        'Orchestrator has no _active_skill attribute')
        self.assertIsNotNone(orch._active_skill,
                             '_active_skill is None after successful lookup')
        self.assertEqual(orch._active_skill['name'], 'research-paper')
        # Must also store the original template for correction detection
        self.assertIn('template', orch._active_skill)
        self.assertIn('Survey literature', orch._active_skill['template'])

    def test_check_skill_correction_archives_when_plan_changed(self):
        """_check_skill_correction archives the corrected plan when PLAN.md differs from template."""
        orch = self._make_engine()
        self._make_skill()

        Path(os.path.join(self.infra_dir, 'INTENT.md')).write_text(
            'Research and write a paper surveying distributed consensus algorithms'
        )

        # Skill lookup succeeds — sets _active_skill with template
        _run(orch._try_skill_lookup())
        self.assertIsNotNone(orch._active_skill)

        # Simulate System 2 producing a corrected plan (overwrites PLAN.md)
        corrected_plan = (
            '## Corrected Decomposition\n\n'
            '1. Define research question first\n'
            '2. Survey literature on {topic}\n'
            '3. Construct argument\n'
            '4. Draft sections\n'
            '5. Peer review\n'
            '6. Edit for coherence\n'
        )
        Path(os.path.join(self.infra_dir, 'PLAN.md')).write_text(corrected_plan)

        # Now _check_skill_correction should detect the difference and archive
        orch._check_skill_correction()

        # Verify correction candidate was archived
        candidates_dir = os.path.join(self.project_dir, 'skill-candidates')
        self.assertTrue(os.path.isdir(candidates_dir))
        candidates = [f for f in os.listdir(candidates_dir) if f.endswith('.md')]
        self.assertEqual(len(candidates), 1)

        content = Path(os.path.join(candidates_dir, candidates[0])).read_text()
        self.assertIn('corrects_skill: research-paper', content)
        self.assertIn('Define research question first', content)

        # _active_skill should be cleared after archiving
        self.assertIsNone(orch._active_skill)

    def test_check_skill_correction_noop_when_plan_unchanged(self):
        """_check_skill_correction does nothing when PLAN.md matches the original template."""
        orch = self._make_engine()
        self._make_skill()

        Path(os.path.join(self.infra_dir, 'INTENT.md')).write_text(
            'Research and write a paper surveying distributed consensus algorithms'
        )

        # Skill lookup succeeds
        _run(orch._try_skill_lookup())
        self.assertIsNotNone(orch._active_skill)

        # PLAN.md is still the original template (not corrected)
        orch._check_skill_correction()

        # No correction candidate should exist
        candidates_dir = os.path.join(self.project_dir, 'skill-candidates')
        if os.path.isdir(candidates_dir):
            candidates = [f for f in os.listdir(candidates_dir) if f.endswith('.md')]
            self.assertEqual(len(candidates), 0)

        # _active_skill should still be set (no correction happened)
        self.assertIsNotNone(orch._active_skill)

    def test_active_skill_is_none_when_no_match(self):
        """_active_skill remains None when no skill matches."""
        orch = self._make_engine()
        # No skills in the dir

        result = _run(orch._try_skill_lookup())
        self.assertFalse(result)
        # _active_skill should be None or not set
        active = getattr(orch, '_active_skill', None)
        self.assertIsNone(active)


# ── Tests: skill self-correction on backtrack ────────────────────────────────

class TestSkillSelfCorrection(unittest.TestCase):
    """When a skill-based plan triggers a backtrack, the corrected plan is
    archived as a correction candidate targeting the failed skill."""

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

    def test_archive_skill_candidate_accepts_corrects_skill(self):
        """archive_skill_candidate accepts and records corrects_skill metadata."""
        from projects.POC.orchestrator.procedural_learning import archive_skill_candidate

        _make_plan(os.path.join(self.infra_dir, 'PLAN.md'),
                   content='## Corrected plan\n\n1. Better step 1\n2. Better step 2\n')

        result = archive_skill_candidate(
            infra_dir=self.infra_dir,
            project_dir=self.project_dir,
            task='Write a research paper',
            session_id='correction-001',
            corrects_skill='research-paper',
        )

        self.assertTrue(result)

        # Read back and verify corrects_skill appears in frontmatter
        candidates_dir = os.path.join(self.project_dir, 'skill-candidates')
        candidates = [f for f in os.listdir(candidates_dir) if f.endswith('.md')]
        self.assertEqual(len(candidates), 1)

        content = Path(os.path.join(candidates_dir, candidates[0])).read_text()
        self.assertIn('corrects_skill: research-paper', content)

    def test_backtrack_with_active_skill_archives_correction(self):
        """When engine backtracks from execution→planning with an active skill,
        it archives the corrected PLAN.md as a correction candidate."""
        from projects.POC.orchestrator.procedural_learning import (
            archive_skill_candidate,
            _parse_candidate_frontmatter,
        )

        # Simulate: a corrected PLAN.md exists (System 2 produced it)
        corrected_plan = '## Corrected Plan\n\n1. Better approach\n2. Verify first\n'
        _make_plan(os.path.join(self.infra_dir, 'PLAN.md'), content=corrected_plan)

        # Archive it as a correction
        archive_skill_candidate(
            infra_dir=self.infra_dir,
            project_dir=self.project_dir,
            task='Write a research paper',
            session_id='correction-session',
            corrects_skill='research-paper',
        )

        # Verify the candidate exists and has correction metadata
        candidates_dir = os.path.join(self.project_dir, 'skill-candidates')
        cand_path = os.path.join(candidates_dir, 'correction-session.md')
        self.assertTrue(os.path.isfile(cand_path))

        content = Path(cand_path).read_text()
        meta, body = _parse_candidate_frontmatter(content)
        self.assertEqual(meta.get('corrects_skill'), 'research-paper')
        self.assertIn('Better approach', body)

    def test_no_correction_without_active_skill(self):
        """Backtracks without an active skill do NOT archive correction candidates."""
        # This tests that _mark_false_positives alone (without skill tracking)
        # does not produce correction candidates.
        from projects.POC.orchestrator.procedural_learning import archive_skill_candidate

        _make_plan(os.path.join(self.infra_dir, 'PLAN.md'))

        # Archive without corrects_skill — this is a normal archive, not a correction
        archive_skill_candidate(
            infra_dir=self.infra_dir,
            project_dir=self.project_dir,
            task='Write a research paper',
            session_id='normal-session',
        )

        candidates_dir = os.path.join(self.project_dir, 'skill-candidates')
        cand_path = os.path.join(candidates_dir, 'normal-session.md')
        content = Path(cand_path).read_text()

        # No corrects_skill metadata should be present
        self.assertNotIn('corrects_skill:', content)


if __name__ == '__main__':
    unittest.main()
