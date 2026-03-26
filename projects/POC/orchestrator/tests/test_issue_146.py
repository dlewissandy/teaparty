#!/usr/bin/env python3
"""Tests for issue #146: Assert gates as reward signal for online skill learning.

Covers:
 1. Gate outcome JSONL entries include skill_name when a skill-based plan is active
 2. Engine persists active skill info to sidecar file for post-session use
 3. Reflect pass reads gate outcomes, applies correction deltas to skill template
 4. Reflect pass updates skill frontmatter with approval stats
 5. Reflect pass is wired into extract_learnings pipeline
 6. Skills with low approval rates are flagged for review in frontmatter
 7. Reflect pass is a no-op when no skill was used in the session
"""
import asyncio
import json
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


def _make_skill(skills_dir, name='research-paper', description='Write a research paper',
                body='', approval_rate='', uses=''):
    """Write a skill file to the skills directory and return its path."""
    if not body:
        body = (
            '## Decomposition\n\n'
            '1. Survey literature on {topic}\n'
            '2. Construct argument\n'
            '3. Draft sections\n'
            '4. Edit for coherence\n'
        )
    fm_lines = [
        '---',
        f'name: {name}',
        f'description: {description}',
        'category: writing',
    ]
    if approval_rate:
        fm_lines.append(f'approval_rate: {approval_rate}')
    if uses:
        fm_lines.append(f'uses: {uses}')
    fm_lines.append('---')
    fm_lines.append('')
    content = '\n'.join(fm_lines) + body
    os.makedirs(skills_dir, exist_ok=True)
    path = os.path.join(skills_dir, f'{name}.md')
    Path(path).write_text(content)
    return path


def _make_interaction_log(log_path, entries):
    """Write a .proxy-interactions.jsonl file from a list of dicts."""
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, 'w') as f:
        for entry in entries:
            f.write(json.dumps(entry) + '\n')


def _make_engine(tmpdir):
    """Create a minimal Orchestrator wired to temp dirs."""
    from projects.POC.orchestrator.engine import Orchestrator
    from projects.POC.orchestrator.events import EventBus
    from projects.POC.scripts.cfa_state import CfaState

    infra_dir = os.path.join(tmpdir, 'infra')
    project_dir = os.path.join(tmpdir, 'project')
    worktree = os.path.join(tmpdir, 'worktree')
    for d in (infra_dir, project_dir, worktree):
        os.makedirs(d, exist_ok=True)

    cfa = CfaState(phase='planning', state='DRAFT', actor='agent', backtrack_count=0)
    config = MagicMock()
    config.stall_timeout = 1800
    event_bus = EventBus()

    orch = Orchestrator(
        cfa_state=cfa,
        phase_config=config,
        event_bus=event_bus,
        input_provider=AsyncMock(),
        infra_dir=infra_dir,
        project_workdir=project_dir,
        session_worktree=worktree,
        proxy_model_path=os.path.join(tmpdir, 'proxy-model.json'),
        project_slug='test-project',
        poc_root='/tmp/poc',
        task='Write a research paper on distributed systems',
        session_id='test-session',
    )
    return orch, infra_dir, project_dir, worktree


def _read_frontmatter(path):
    """Parse YAML frontmatter from a file, return (meta_dict, body)."""
    from projects.POC.orchestrator.procedural_learning import _parse_candidate_frontmatter
    return _parse_candidate_frontmatter(Path(path).read_text())


# ── Tests: gate outcomes tagged with skill_name ──────────────────────────────

class TestGateOutcomeSkillTagging(unittest.TestCase):
    """When a skill-based plan is active, gate outcome log entries must include
    the skill_name so the post-session reflect pass can scope signal to skills."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmpdir = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def test_log_interaction_includes_skill_name_when_active(self):
        """_log_interaction entries include skill_name when _active_skill is set."""
        orch, infra_dir, project_dir, _ = _make_engine(self.tmpdir)

        # Simulate skill lookup having set _active_skill
        orch._active_skill = {
            'name': 'research-paper',
            'path': '/tmp/skills/research-paper.md',
            'score': '0.85',
            'template': '## Decomposition\n1. Survey\n',
        }

        # Create the ApprovalGate and call _log_interaction
        from projects.POC.orchestrator.actors import ApprovalGate
        from projects.POC.orchestrator.events import EventBus

        gate = ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, 'proxy-model.json'),
            input_provider=AsyncMock(),
            poc_root='/tmp/poc',
        )
        # Attach the active_skill to gate so it can tag entries
        gate._active_skill = orch._active_skill

        ctx = MagicMock()
        ctx.state = 'PLAN_ASSERT'
        ctx.session_id = 'test-session'

        gate._log_interaction(
            ctx, 'test-project',
            prediction='approve', outcome='correct',
            delta='Add a rollback step',
        )

        # Read the log file and verify skill_name is present
        log_path = os.path.join(self.tmpdir, '.proxy-interactions.jsonl')
        self.assertTrue(os.path.isfile(log_path),
                        'No .proxy-interactions.jsonl written')
        with open(log_path) as f:
            entries = [json.loads(line) for line in f if line.strip()]

        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].get('skill_name'), 'research-paper',
                         'Log entry missing skill_name when _active_skill is set')

    def test_log_interaction_omits_skill_name_when_no_active_skill(self):
        """_log_interaction entries do NOT include skill_name when no skill is active."""
        from projects.POC.orchestrator.actors import ApprovalGate

        gate = ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, 'proxy-model.json'),
            input_provider=AsyncMock(),
            poc_root='/tmp/poc',
        )

        ctx = MagicMock()
        ctx.state = 'PLAN_ASSERT'
        ctx.session_id = 'test-session'

        gate._log_interaction(
            ctx, 'test-project',
            prediction='approve', outcome='approve',
            delta='',
        )

        log_path = os.path.join(self.tmpdir, '.proxy-interactions.jsonl')
        self.assertTrue(os.path.isfile(log_path))
        with open(log_path) as f:
            entries = [json.loads(line) for line in f if line.strip()]

        self.assertEqual(len(entries), 1)
        self.assertNotIn('skill_name', entries[0],
                         'Log entry should not have skill_name when no skill is active')


# ── Tests: engine persists active skill for post-session use ─────────────────

class TestEngineSkillPersistence(unittest.TestCase):
    """The engine must persist which skill was used to a sidecar file so
    extract_learnings can find it post-session."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmpdir = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def test_persist_active_skill_writes_sidecar(self):
        """After _try_skill_lookup succeeds, a .active-skill.json sidecar is written."""
        orch, infra_dir, project_dir, _ = _make_engine(self.tmpdir)
        skills_dir = os.path.join(project_dir, 'skills')
        _make_skill(skills_dir)

        Path(os.path.join(infra_dir, 'INTENT.md')).write_text(
            'Research and write a paper surveying distributed consensus algorithms'
        )

        result = _run(orch._try_skill_lookup())
        self.assertTrue(result)

        sidecar_path = os.path.join(infra_dir, '.active-skill.json')
        self.assertTrue(os.path.isfile(sidecar_path),
                        'No .active-skill.json sidecar written after skill lookup')

        with open(sidecar_path) as f:
            data = json.load(f)
        self.assertEqual(data['name'], 'research-paper')
        self.assertIn('path', data)
        self.assertEqual(data['session_id'], 'test-session',
                         'Sidecar must include session_id for JSONL filtering')


# ── Tests: reflect pass applies corrections to skill template ────────────────

class TestReflectPassAppliesCorrections(unittest.TestCase):
    """Post-session reflect pass reads gate correction deltas and applies them
    to the skill template via an LLM call."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmpdir = self._td.name
        self.project_dir = os.path.join(self.tmpdir, 'project')
        self.infra_dir = os.path.join(self.tmpdir, 'infra')
        self.skills_dir = os.path.join(self.project_dir, 'skills')
        for d in (self.project_dir, self.infra_dir, self.skills_dir):
            os.makedirs(d)

    def tearDown(self):
        self._td.cleanup()

    def test_reflect_applies_correction_to_skill(self):
        """When gate outcomes for a skill include corrections, the reflect pass
        updates the skill template with the correction incorporated."""
        from projects.POC.orchestrator.procedural_learning import reflect_on_skill

        skill_path = _make_skill(self.skills_dir)
        original_content = Path(skill_path).read_text()

        # Correction deltas from gate outcomes
        corrections = [
            {'state': 'PLAN_ASSERT', 'outcome': 'correct',
             'delta': 'Add a rollback step after each major section'},
        ]

        # The LLM should return an updated skill incorporating the correction
        updated_skill = (
            '---\n'
            'name: research-paper\n'
            'description: Write a research paper\n'
            'category: writing\n'
            '---\n\n'
            '## Decomposition\n\n'
            '1. Survey literature on {topic}\n'
            '2. Construct argument\n'
            '3. Draft sections\n'
            '4. Add rollback step\n'
            '5. Edit for coherence\n'
        )

        with patch(
            'projects.POC.orchestrator.procedural_learning._apply_signals_to_skill',
            return_value=updated_skill,
        ) as mock_apply:
            result = reflect_on_skill(
                skill_path=skill_path,
                corrections=corrections,
            )

        self.assertTrue(result, 'reflect_on_skill should return True on success')

        # Verify the LLM was called with the skill template and corrections
        mock_apply.assert_called_once()
        call_args = mock_apply.call_args
        self.assertIn('Add a rollback step', str(call_args))

        # Verify the skill file was updated
        new_content = Path(skill_path).read_text()
        self.assertIn('rollback', new_content)
        self.assertNotEqual(new_content, original_content)

    def test_reflect_noop_when_all_approved(self):
        """When all gate outcomes are approvals (no corrections), reflect is a no-op."""
        from projects.POC.orchestrator.procedural_learning import reflect_on_skill

        skill_path = _make_skill(self.skills_dir)
        original_content = Path(skill_path).read_text()

        # No corrections — all approvals
        corrections = []

        result = reflect_on_skill(
            skill_path=skill_path,
            corrections=corrections,
        )

        self.assertFalse(result, 'reflect_on_skill should return False when no corrections')
        self.assertEqual(Path(skill_path).read_text(), original_content,
                         'Skill file should be unchanged when no corrections')

    def test_reflect_preserves_skill_on_llm_failure(self):
        """If the LLM call fails, the original skill file is preserved."""
        from projects.POC.orchestrator.procedural_learning import reflect_on_skill

        skill_path = _make_skill(self.skills_dir)
        original_content = Path(skill_path).read_text()

        corrections = [
            {'state': 'PLAN_ASSERT', 'outcome': 'correct',
             'delta': 'Add error handling'},
        ]

        with patch(
            'projects.POC.orchestrator.procedural_learning._apply_signals_to_skill',
            return_value='',  # LLM returned empty
        ):
            result = reflect_on_skill(
                skill_path=skill_path,
                corrections=corrections,
            )

        self.assertFalse(result, 'reflect_on_skill should return False on LLM failure')
        self.assertEqual(Path(skill_path).read_text(), original_content,
                         'Skill file must be preserved when LLM fails')


# ── Tests: skill approval stats in frontmatter ───────────────────────────────

class TestSkillApprovalStats(unittest.TestCase):
    """The reflect pass updates skill frontmatter with approval stats
    computed from gate outcomes."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmpdir = self._td.name
        self.project_dir = os.path.join(self.tmpdir, 'project')
        self.skills_dir = os.path.join(self.project_dir, 'skills')
        os.makedirs(self.skills_dir)

    def tearDown(self):
        self._td.cleanup()

    def test_update_skill_stats_records_outcomes(self):
        """update_skill_stats writes approval_rate, uses, corrections to frontmatter."""
        from projects.POC.orchestrator.procedural_learning import update_skill_stats

        skill_path = _make_skill(self.skills_dir)

        outcomes = ['approve', 'approve', 'correct', 'approve']
        update_skill_stats(skill_path=skill_path, outcomes=outcomes)

        meta, _ = _read_frontmatter(skill_path)
        self.assertEqual(meta.get('uses'), '4')
        self.assertEqual(meta.get('approval_rate'), '0.75')
        self.assertEqual(meta.get('corrections'), '1')

    def test_stats_accumulate_across_calls(self):
        """Calling update_skill_stats multiple times accumulates counts."""
        from projects.POC.orchestrator.procedural_learning import update_skill_stats

        skill_path = _make_skill(self.skills_dir, approval_rate='1.0', uses='2')

        # New session: 1 correct out of 1
        update_skill_stats(skill_path=skill_path, outcomes=['correct'])

        meta, _ = _read_frontmatter(skill_path)
        # 2 prior approvals + 0 new approvals = 2 approvals out of 3 total
        self.assertEqual(meta.get('uses'), '3')

    def test_low_approval_rate_flagged(self):
        """Skills with approval_rate below threshold get needs_review flag."""
        from projects.POC.orchestrator.procedural_learning import update_skill_stats

        skill_path = _make_skill(self.skills_dir)

        # 4 corrections, 1 approval = 0.2 approval rate
        outcomes = ['correct', 'correct', 'correct', 'correct', 'approve']
        update_skill_stats(skill_path=skill_path, outcomes=outcomes)

        meta, _ = _read_frontmatter(skill_path)
        self.assertEqual(meta.get('needs_review'), 'true',
                         'Skill with low approval rate should be flagged needs_review')


# ── Tests: reflect wired into extract_learnings pipeline ─────────────────────

class TestReflectWiredIntoLearnings(unittest.TestCase):
    """The reflect-on-skill step is called as part of extract_learnings
    when a skill was used in the session."""

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

    def test_extract_learnings_calls_reflect_when_skill_was_used(self):
        """extract_learnings calls the skill-refine scope when .active-skill.json exists."""
        from projects.POC.orchestrator.learnings import extract_learnings

        # Write the sidecar that indicates a skill was used
        sidecar = {'name': 'research-paper', 'path': '/tmp/skills/research-paper.md'}
        Path(os.path.join(self.infra_dir, '.active-skill.json')).write_text(
            json.dumps(sidecar)
        )

        refine_called = []

        def _track_refine(**kwargs):
            refine_called.append(kwargs)

        with patch('projects.POC.orchestrator.learnings._run_summarize'), \
             patch('projects.POC.orchestrator.learnings._promote_team'), \
             patch('projects.POC.orchestrator.learnings._promote_session'), \
             patch('projects.POC.orchestrator.learnings._promote_project'), \
             patch('projects.POC.orchestrator.learnings._promote_global'), \
             patch('projects.POC.orchestrator.learnings._promote_prospective'), \
             patch('projects.POC.orchestrator.learnings._promote_in_flight'), \
             patch('projects.POC.orchestrator.learnings._promote_corrective'), \
             patch('projects.POC.orchestrator.learnings._reinforce_retrieved'), \
             patch('projects.POC.orchestrator.learnings._archive_skill_candidate'), \
             patch('projects.POC.orchestrator.learnings._crystallize_skills'), \
             patch('projects.POC.orchestrator.learnings._detect_and_write_friction'), \
             patch('projects.POC.orchestrator.learnings._compact_proxy_correction_entries'), \
             patch('projects.POC.orchestrator.learnings._compact_proxy_patterns'), \
             patch(
                 'projects.POC.orchestrator.learnings._refine_skill_unified',
                 side_effect=_track_refine,
             ):
            _run(extract_learnings(
                infra_dir=self.infra_dir,
                project_dir=self.project_dir,
                session_worktree=self.worktree,
                task='Write a research paper',
                poc_root='/tmp/poc',
            ))

        self.assertGreater(len(refine_called), 0,
                           '_refine_skill_unified was never called')

    def test_extract_learnings_skips_reflect_when_no_skill(self):
        """extract_learnings does NOT call skill-refine when no .active-skill.json."""
        from projects.POC.orchestrator.learnings import extract_learnings

        refine_called = []

        def _track_refine(**kwargs):
            refine_called.append(kwargs)

        with patch('projects.POC.orchestrator.learnings._run_summarize'), \
             patch('projects.POC.orchestrator.learnings._promote_team'), \
             patch('projects.POC.orchestrator.learnings._promote_session'), \
             patch('projects.POC.orchestrator.learnings._promote_project'), \
             patch('projects.POC.orchestrator.learnings._promote_global'), \
             patch('projects.POC.orchestrator.learnings._promote_prospective'), \
             patch('projects.POC.orchestrator.learnings._promote_in_flight'), \
             patch('projects.POC.orchestrator.learnings._promote_corrective'), \
             patch('projects.POC.orchestrator.learnings._reinforce_retrieved'), \
             patch('projects.POC.orchestrator.learnings._archive_skill_candidate'), \
             patch('projects.POC.orchestrator.learnings._crystallize_skills'), \
             patch('projects.POC.orchestrator.learnings._detect_and_write_friction'), \
             patch('projects.POC.orchestrator.learnings._compact_proxy_correction_entries'), \
             patch('projects.POC.orchestrator.learnings._compact_proxy_patterns'), \
             patch(
                 'projects.POC.orchestrator.learnings._refine_skill_unified',
                 side_effect=_track_refine,
             ):
            _run(extract_learnings(
                infra_dir=self.infra_dir,
                project_dir=self.project_dir,
                session_worktree=self.worktree,
                task='Write a research paper',
                poc_root='/tmp/poc',
            ))

        self.assertEqual(len(refine_called), 0,
                         '_refine_skill_unified should not be called without .active-skill.json')


# ── Tests: session-scoped filtering in reflect pass ──────────────────────────

class TestSessionScopedFiltering(unittest.TestCase):
    """The reflect pass must only process gate outcomes from the current session,
    not historical outcomes from prior sessions using the same skill."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmpdir = self._td.name
        self.project_dir = os.path.join(self.tmpdir, 'project')
        self.infra_dir = os.path.join(self.tmpdir, 'infra')
        self.skills_dir = os.path.join(self.project_dir, 'skills')
        for d in (self.project_dir, self.infra_dir, self.skills_dir):
            os.makedirs(d)

    def tearDown(self):
        self._td.cleanup()

    def test_reflect_only_processes_current_session_outcomes(self):
        """_reflect_on_skill_outcomes filters JSONL entries by session_id."""
        from projects.POC.orchestrator.learnings import _reflect_on_skill_outcomes

        skill_path = _make_skill(self.skills_dir)

        # Write sidecar with session_id
        sidecar = {
            'name': 'research-paper',
            'path': skill_path,
            'session_id': 'session-2',
        }
        Path(os.path.join(self.infra_dir, '.active-skill.json')).write_text(
            json.dumps(sidecar)
        )

        # JSONL log has entries from TWO sessions
        _make_interaction_log(
            os.path.join(self.project_dir, '.proxy-interactions.jsonl'),
            [
                # Session 1 (prior) — should be IGNORED
                {'session_id': 'session-1', 'skill_name': 'research-paper',
                 'state': 'PLAN_ASSERT', 'outcome': 'correct',
                 'delta': 'Old correction from prior session'},
                {'session_id': 'session-1', 'skill_name': 'research-paper',
                 'state': 'PLAN_ASSERT', 'outcome': 'approve', 'delta': ''},
                # Session 2 (current) — should be PROCESSED
                {'session_id': 'session-2', 'skill_name': 'research-paper',
                 'state': 'PLAN_ASSERT', 'outcome': 'correct',
                 'delta': 'Add error handling'},
            ],
        )

        corrections_seen = []

        def _mock_apply(skill_content, corrections, friction_events):
            corrections_seen.extend(corrections)
            return ''  # return empty to avoid writing

        with patch(
            'projects.POC.orchestrator.procedural_learning._apply_signals_to_skill',
            side_effect=_mock_apply,
        ):
            _reflect_on_skill_outcomes(
                infra_dir=self.infra_dir,
                project_dir=self.project_dir,
            )

        # Only session-2's correction should have been passed to reflect
        self.assertEqual(len(corrections_seen), 1,
                         f'Expected 1 correction from session-2, got {len(corrections_seen)}')
        self.assertIn('error handling', corrections_seen[0]['delta'])
        self.assertNotIn('Old correction', str(corrections_seen))

    def test_stats_only_count_current_session(self):
        """update_skill_stats via _reflect_on_skill_outcomes only counts current session outcomes."""
        from projects.POC.orchestrator.learnings import _reflect_on_skill_outcomes

        # Pre-seed skill with stats from 2 prior uses (both approved)
        skill_path = _make_skill(self.skills_dir, approval_rate='1.0', uses='2')

        sidecar = {
            'name': 'research-paper',
            'path': skill_path,
            'session_id': 'session-3',
        }
        Path(os.path.join(self.infra_dir, '.active-skill.json')).write_text(
            json.dumps(sidecar)
        )

        # JSONL has outcomes from session-1 (old) and session-3 (current)
        _make_interaction_log(
            os.path.join(self.project_dir, '.proxy-interactions.jsonl'),
            [
                {'session_id': 'session-1', 'skill_name': 'research-paper',
                 'state': 'PLAN_ASSERT', 'outcome': 'approve', 'delta': ''},
                {'session_id': 'session-3', 'skill_name': 'research-paper',
                 'state': 'PLAN_ASSERT', 'outcome': 'correct',
                 'delta': 'Add rollback'},
            ],
        )

        with patch(
            'projects.POC.orchestrator.procedural_learning._apply_signals_to_skill',
            return_value='',
        ):
            _reflect_on_skill_outcomes(
                infra_dir=self.infra_dir,
                project_dir=self.project_dir,
            )

        meta, _ = _read_frontmatter(skill_path)
        # Prior: 2 uses, 2 approvals. Current session: 1 use (correct).
        # Total: 3 uses, 2 approvals = 0.67 rate
        self.assertEqual(meta.get('uses'), '3',
                         'Should count only current session outcomes, not re-count historical')


if __name__ == '__main__':
    unittest.main()
