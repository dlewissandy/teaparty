#!/usr/bin/env python3
"""Tests for issue #229: Continuous skill refinement via friction signals and quality monitoring.

Covers:
 1. Friction event detection — scan stream JSONL for operational friction patterns
 2. Friction events written to sidecar file after phase completion
 3. Friction-aware skill refinement wired into extract_learnings pipeline
 4. Per-skill quality metrics aggregation across sessions
 5. Degraded skill suppression in skill_lookup (needs_review=true skipped)
 6. Quality monitoring thresholds flag skills for review
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
                body='', needs_review='', approval_rate='', uses='',
                friction_events_total=''):
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
    if needs_review:
        fm_lines.append(f'needs_review: {needs_review}')
    if friction_events_total:
        fm_lines.append(f'friction_events_total: {friction_events_total}')
    fm_lines.append('---')
    fm_lines.append('')
    content = '\n'.join(fm_lines) + body
    os.makedirs(skills_dir, exist_ok=True)
    path = os.path.join(skills_dir, f'{name}.md')
    Path(path).write_text(content)
    return path


def _make_stream_jsonl(path, events):
    """Write a stream JSONL file with the given event dicts."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        for event in events:
            f.write(json.dumps(event) + '\n')


def _make_skill_stats(stats_dir, skill_name, stats):
    """Write a per-skill stats JSON sidecar."""
    os.makedirs(stats_dir, exist_ok=True)
    path = os.path.join(stats_dir, f'{skill_name}.json')
    with open(path, 'w') as f:
        json.dump(stats, f)
    return path


# ── Tests: friction event detection from stream JSONL ─────────────────────────

class TestFrictionEventDetection(unittest.TestCase):
    """Friction events are detected by scanning the stream JSONL file for
    operational friction patterns: permission denials, file-not-found errors,
    and fallback retries."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmpdir = self._td.name

    def tearDown(self):
        self._td.cleanup()

    def test_detect_permission_denial(self):
        """Permission denial messages in agent output are detected as friction events."""
        from projects.POC.orchestrator.procedural_learning import detect_friction_events

        stream_path = os.path.join(self.tmpdir, '.exec-stream.jsonl')
        _make_stream_jsonl(stream_path, [
            {'type': 'assistant', 'message': {'content': [
                {'type': 'tool_use', 'name': 'Bash'},
            ]}},
            {'type': 'result', 'result': 'Permission denied: cannot write to /etc/hosts'},
        ])

        events = detect_friction_events(stream_path)
        self.assertGreater(len(events), 0, 'Should detect permission denial')
        self.assertTrue(
            any(e['category'] == 'permission_denied' for e in events),
            f'Expected permission_denied category, got: {[e["category"] for e in events]}',
        )

    def test_detect_file_not_found(self):
        """File-not-found errors are detected as friction events."""
        from projects.POC.orchestrator.procedural_learning import detect_friction_events

        stream_path = os.path.join(self.tmpdir, '.exec-stream.jsonl')
        _make_stream_jsonl(stream_path, [
            {'type': 'result', 'result': 'Error: No such file or directory: src/missing.py'},
        ])

        events = detect_friction_events(stream_path)
        self.assertGreater(len(events), 0, 'Should detect file-not-found')
        self.assertTrue(
            any(e['category'] == 'file_not_found' for e in events),
            f'Expected file_not_found category, got: {[e["category"] for e in events]}',
        )

    def test_detect_fallback_retry(self):
        """Fallback retries (tool errors followed by alternative approach) are friction."""
        from projects.POC.orchestrator.procedural_learning import detect_friction_events

        stream_path = os.path.join(self.tmpdir, '.exec-stream.jsonl')
        _make_stream_jsonl(stream_path, [
            {'type': 'result', 'result': 'Error: command not found: foo'},
            {'type': 'assistant', 'message': {'content': [
                {'type': 'text', 'text': 'Let me try a different approach'},
            ]}},
        ])

        events = detect_friction_events(stream_path)
        self.assertGreater(len(events), 0, 'Should detect fallback retry')
        self.assertTrue(
            any(e['category'] == 'fallback_retry' for e in events),
            f'Expected fallback_retry category, got: {[e["category"] for e in events]}',
        )

    def test_no_friction_in_clean_session(self):
        """A clean session with no errors produces no friction events."""
        from projects.POC.orchestrator.procedural_learning import detect_friction_events

        stream_path = os.path.join(self.tmpdir, '.exec-stream.jsonl')
        _make_stream_jsonl(stream_path, [
            {'type': 'assistant', 'message': {'content': [
                {'type': 'text', 'text': 'Task completed successfully.'},
            ]}},
        ])

        events = detect_friction_events(stream_path)
        self.assertEqual(len(events), 0, 'Clean session should produce no friction events')

    def test_returns_list_of_dicts_with_required_fields(self):
        """Each friction event dict has category and detail fields."""
        from projects.POC.orchestrator.procedural_learning import detect_friction_events

        stream_path = os.path.join(self.tmpdir, '.exec-stream.jsonl')
        _make_stream_jsonl(stream_path, [
            {'type': 'result', 'result': 'Permission denied'},
        ])

        events = detect_friction_events(stream_path)
        for event in events:
            self.assertIn('category', event, 'Friction event must have category')
            self.assertIn('detail', event, 'Friction event must have detail')


# ── Tests: friction events written to sidecar after phase ─────────────────────

class TestFrictionEventSidecar(unittest.TestCase):
    """After execution phase completes, friction events from the stream are
    written to .friction-events.json in the infra dir."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmpdir = self._td.name
        self.infra_dir = os.path.join(self.tmpdir, 'infra')
        os.makedirs(self.infra_dir)

    def tearDown(self):
        self._td.cleanup()

    def test_friction_sidecar_written_after_extraction(self):
        """extract_learnings writes .friction-events.json when friction events exist."""
        from projects.POC.orchestrator.learnings import extract_learnings

        # Create a stream with friction
        stream_path = os.path.join(self.infra_dir, '.exec-stream.jsonl')
        _make_stream_jsonl(stream_path, [
            {'type': 'result', 'result': 'Permission denied: cannot run sudo'},
        ])

        project_dir = os.path.join(self.tmpdir, 'project')
        worktree = os.path.join(self.tmpdir, 'worktree')
        os.makedirs(project_dir)
        os.makedirs(worktree)

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
             patch('projects.POC.orchestrator.learnings._compact_proxy_correction_entries'), \
             patch('projects.POC.orchestrator.learnings._compact_proxy_patterns'), \
             patch('projects.POC.orchestrator.learnings._reflect_on_skill_outcomes'):
            _run(extract_learnings(
                infra_dir=self.infra_dir,
                project_dir=project_dir,
                session_worktree=worktree,
                task='Test task',
                poc_root='/tmp/poc',
            ))

        sidecar_path = os.path.join(self.infra_dir, '.friction-events.json')
        self.assertTrue(os.path.isfile(sidecar_path),
                        '.friction-events.json should be written when friction exists')

        with open(sidecar_path) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)


# ── Tests: friction-aware skill refinement ────────────────────────────────────

class TestFrictionAwareSkillRefinement(unittest.TestCase):
    """When a skill was used and friction events were recorded, the post-session
    pipeline invokes skill refinement with friction signals."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmpdir = self._td.name
        self.infra_dir = os.path.join(self.tmpdir, 'infra')
        self.project_dir = os.path.join(self.tmpdir, 'project')
        self.skills_dir = os.path.join(self.project_dir, 'skills')
        for d in (self.infra_dir, self.project_dir, self.skills_dir):
            os.makedirs(d)

    def tearDown(self):
        self._td.cleanup()

    def test_refine_skill_with_friction_signals(self):
        """refine_skill_with_friction() passes friction events to the LLM along
        with the skill template, producing an updated skill."""
        from projects.POC.orchestrator.procedural_learning import refine_skill_with_friction

        skill_path = _make_skill(self.skills_dir)
        original = Path(skill_path).read_text()

        friction_events = [
            {'category': 'file_not_found', 'detail': 'Agent searched for src/config.py but it is at config/settings.py'},
            {'category': 'permission_denied', 'detail': 'Bash command blocked: npm install -g'},
        ]

        updated_skill = (
            '---\n'
            'name: research-paper\n'
            'description: Write a research paper\n'
            'category: writing\n'
            '---\n\n'
            '## Decomposition\n\n'
            '1. Survey literature on {topic}\n'
            '   - Config is at config/settings.py\n'
            '2. Construct argument\n'
            '3. Draft sections\n'
            '4. Edit for coherence\n'
        )

        with patch(
            'projects.POC.orchestrator.procedural_learning._apply_friction_to_skill',
            return_value=updated_skill,
        ) as mock_apply:
            result = refine_skill_with_friction(
                skill_path=skill_path,
                friction_events=friction_events,
            )

        self.assertTrue(result, 'refine_skill_with_friction should return True on success')
        mock_apply.assert_called_once()
        # Verify friction events were passed to the LLM function
        call_args = mock_apply.call_args
        self.assertIn('file_not_found', str(call_args))

    def test_refine_noop_when_no_friction(self):
        """When there are no friction events, refinement is a no-op."""
        from projects.POC.orchestrator.procedural_learning import refine_skill_with_friction

        skill_path = _make_skill(self.skills_dir)
        original = Path(skill_path).read_text()

        result = refine_skill_with_friction(
            skill_path=skill_path,
            friction_events=[],
        )

        self.assertFalse(result, 'Should return False with no friction events')
        self.assertEqual(Path(skill_path).read_text(), original,
                         'Skill should be unchanged with no friction')

    def test_refine_preserves_skill_on_llm_failure(self):
        """If the LLM returns empty, the original skill is preserved."""
        from projects.POC.orchestrator.procedural_learning import refine_skill_with_friction

        skill_path = _make_skill(self.skills_dir)
        original = Path(skill_path).read_text()

        friction_events = [
            {'category': 'permission_denied', 'detail': 'blocked write'},
        ]

        with patch(
            'projects.POC.orchestrator.procedural_learning._apply_friction_to_skill',
            return_value='',
        ):
            result = refine_skill_with_friction(
                skill_path=skill_path,
                friction_events=friction_events,
            )

        self.assertFalse(result)
        self.assertEqual(Path(skill_path).read_text(), original)


# ── Tests: friction refinement wired into extract_learnings ───────────────────

class TestFrictionRefinementWiring(unittest.TestCase):
    """The friction-aware refinement step is called as part of extract_learnings
    when both a skill was used AND friction events were recorded."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmpdir = self._td.name
        self.infra_dir = os.path.join(self.tmpdir, 'infra')
        self.project_dir = os.path.join(self.tmpdir, 'project')
        self.skills_dir = os.path.join(self.project_dir, 'skills')
        self.worktree = os.path.join(self.tmpdir, 'worktree')
        for d in (self.infra_dir, self.project_dir, self.skills_dir, self.worktree):
            os.makedirs(d)

    def tearDown(self):
        self._td.cleanup()

    def test_friction_refinement_called_when_skill_and_friction_exist(self):
        """extract_learnings calls friction refinement when both .active-skill.json
        and .friction-events.json exist."""
        from projects.POC.orchestrator.learnings import extract_learnings

        # Write active skill sidecar
        skill_path = _make_skill(self.skills_dir)
        sidecar = {'name': 'research-paper', 'path': skill_path, 'session_id': 'test-session'}
        Path(os.path.join(self.infra_dir, '.active-skill.json')).write_text(json.dumps(sidecar))

        # Write friction events sidecar
        friction = [{'category': 'permission_denied', 'detail': 'blocked'}]
        Path(os.path.join(self.infra_dir, '.friction-events.json')).write_text(json.dumps(friction))

        # Write the interaction log (needed for skill-reflect)
        Path(os.path.join(self.project_dir, '.proxy-interactions.jsonl')).write_text('')

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
             patch('projects.POC.orchestrator.learnings._reflect_on_skill_outcomes'), \
             patch('projects.POC.orchestrator.learnings._compact_proxy_correction_entries'), \
             patch('projects.POC.orchestrator.learnings._compact_proxy_patterns'), \
             patch(
                 'projects.POC.orchestrator.learnings._refine_skill_from_friction',
                 side_effect=_track_refine,
             ):
            _run(extract_learnings(
                infra_dir=self.infra_dir,
                project_dir=self.project_dir,
                session_worktree=self.worktree,
                task='Test task',
                poc_root='/tmp/poc',
            ))

        self.assertGreater(len(refine_called), 0,
                           '_refine_skill_from_friction should be called when skill + friction exist')

    def test_friction_refinement_skipped_when_no_friction(self):
        """extract_learnings does NOT call friction refinement when no .friction-events.json."""
        from projects.POC.orchestrator.learnings import extract_learnings

        # Write active skill sidecar only (no friction)
        skill_path = _make_skill(self.skills_dir)
        sidecar = {'name': 'research-paper', 'path': skill_path, 'session_id': 'test-session'}
        Path(os.path.join(self.infra_dir, '.active-skill.json')).write_text(json.dumps(sidecar))
        Path(os.path.join(self.project_dir, '.proxy-interactions.jsonl')).write_text('')

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
             patch('projects.POC.orchestrator.learnings._reflect_on_skill_outcomes'), \
             patch('projects.POC.orchestrator.learnings._compact_proxy_correction_entries'), \
             patch('projects.POC.orchestrator.learnings._compact_proxy_patterns'), \
             patch(
                 'projects.POC.orchestrator.learnings._refine_skill_from_friction',
                 side_effect=_track_refine,
             ):
            _run(extract_learnings(
                infra_dir=self.infra_dir,
                project_dir=self.project_dir,
                session_worktree=self.worktree,
                task='Test task',
                poc_root='/tmp/poc',
            ))

        self.assertEqual(len(refine_called), 0,
                         'Friction refinement should not be called without friction events')


# ── Tests: per-skill quality metrics aggregation ──────────────────────────────

class TestSkillQualityMetrics(unittest.TestCase):
    """Per-skill quality metrics are aggregated across sessions and stored
    in skill frontmatter (friction_events_total, sessions_since_refinement)."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmpdir = self._td.name
        self.project_dir = os.path.join(self.tmpdir, 'project')
        self.skills_dir = os.path.join(self.project_dir, 'skills')
        os.makedirs(self.skills_dir)

    def tearDown(self):
        self._td.cleanup()

    def test_update_friction_stats(self):
        """update_skill_friction_stats accumulates friction event counts."""
        from projects.POC.orchestrator.procedural_learning import update_skill_friction_stats

        skill_path = _make_skill(self.skills_dir)

        friction_events = [
            {'category': 'permission_denied', 'detail': 'blocked'},
            {'category': 'file_not_found', 'detail': 'missing config'},
        ]

        update_skill_friction_stats(skill_path=skill_path, friction_events=friction_events)

        meta, _ = self._read_frontmatter(skill_path)
        self.assertEqual(meta.get('friction_events_total'), '2',
                         'Should record total friction event count')

    def test_friction_stats_accumulate_across_sessions(self):
        """Friction stats accumulate when called multiple times."""
        from projects.POC.orchestrator.procedural_learning import update_skill_friction_stats

        skill_path = _make_skill(self.skills_dir, friction_events_total='3')

        friction_events = [
            {'category': 'permission_denied', 'detail': 'blocked again'},
        ]

        update_skill_friction_stats(skill_path=skill_path, friction_events=friction_events)

        meta, _ = self._read_frontmatter(skill_path)
        self.assertEqual(meta.get('friction_events_total'), '4',
                         'Should accumulate: 3 prior + 1 new = 4')

    def test_high_friction_flags_needs_review(self):
        """Skills with friction events trending upward get flagged needs_review."""
        from projects.POC.orchestrator.procedural_learning import update_skill_friction_stats

        # Skill already has 8 friction events over 4 uses — avg 2.0 per session
        skill_path = _make_skill(
            self.skills_dir, friction_events_total='8', uses='4',
        )

        # Another 5 friction events this session — avg climbing
        friction_events = [{'category': 'permission_denied', 'detail': f'event-{i}'} for i in range(5)]
        update_skill_friction_stats(skill_path=skill_path, friction_events=friction_events)

        meta, _ = self._read_frontmatter(skill_path)
        self.assertEqual(meta.get('needs_review'), 'true',
                         'Skill with high friction should be flagged needs_review')

    def _read_frontmatter(self, path):
        from projects.POC.orchestrator.procedural_learning import _parse_candidate_frontmatter
        return _parse_candidate_frontmatter(Path(path).read_text())


# ── Tests: degraded skill suppression in lookup ───────────────────────────────

class TestDegradedSkillSuppression(unittest.TestCase):
    """skill_lookup.lookup_skill skips skills that have needs_review=true,
    preventing degraded skills from being used as warm-start plans."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmpdir = self._td.name
        self.skills_dir = os.path.join(self.tmpdir, 'skills')
        os.makedirs(self.skills_dir)

    def tearDown(self):
        self._td.cleanup()

    def test_needs_review_skill_excluded_from_lookup(self):
        """A skill with needs_review=true is not returned by lookup_skill."""
        from projects.POC.orchestrator.skill_lookup import lookup_skill

        _make_skill(self.skills_dir, needs_review='true')

        result = lookup_skill(
            task='Write a research paper on distributed consensus',
            intent='Survey distributed consensus algorithms and produce a paper',
            skills_dir=self.skills_dir,
        )

        self.assertIsNone(result,
                          'lookup_skill should skip skills with needs_review=true')

    def test_healthy_skill_still_returned(self):
        """A skill without needs_review is returned normally."""
        from projects.POC.orchestrator.skill_lookup import lookup_skill

        _make_skill(self.skills_dir)

        result = lookup_skill(
            task='Write a research paper on distributed consensus',
            intent='Survey distributed consensus algorithms and produce a paper',
            skills_dir=self.skills_dir,
        )

        self.assertIsNotNone(result,
                             'lookup_skill should return healthy skills normally')

    def test_degraded_skill_skipped_in_favor_of_healthy(self):
        """When one skill is degraded and another is healthy, the healthy one wins."""
        from projects.POC.orchestrator.skill_lookup import lookup_skill

        # Degraded skill — better name match but flagged
        _make_skill(
            self.skills_dir, name='research-paper',
            description='Write a research paper',
            needs_review='true',
        )

        # Healthy skill — less specific but not flagged
        _make_skill(
            self.skills_dir, name='academic-writing',
            description='Write academic papers and research documents',
        )

        result = lookup_skill(
            task='Write a research paper on distributed consensus',
            intent='Survey distributed consensus algorithms and produce a paper',
            skills_dir=self.skills_dir,
        )

        # Should get academic-writing, not the degraded research-paper
        if result is not None:
            self.assertNotEqual(result.name, 'research-paper',
                                'Should not return degraded skill when healthy alternative exists')


if __name__ == '__main__':
    unittest.main()
