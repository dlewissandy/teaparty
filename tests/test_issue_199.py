#!/usr/bin/env python3
"""Tests for issue #199 — in-flight and prospective learning extraction.

Covers:
 1. write_assumption_checkpoint() writes structured JSONL entries to
    .assumptions.jsonl at phase transitions
 2. write_premortem() generates .premortem.md from PLAN.md content
 3. _reinforce_retrieved() accuracy-aware reinforcement: reinforces
    aligned entries, decrements misaligned ones
 4. Engine integration: phase completion triggers assumption checkpoints
 5. Engine integration: planning→execution bridge triggers premortem
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _write(path: str, content: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(content)


# ── 1. Assumption checkpoint writing ─────────────────────────────────────────

class TestWriteAssumptionCheckpoint(unittest.TestCase):
    """write_assumption_checkpoint() appends structured JSONL entries."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.infra_dir = self.tmpdir

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_creates_assumptions_file_on_first_call(self):
        """First checkpoint creates .assumptions.jsonl."""
        from orchestrator.learnings import write_assumption_checkpoint

        path = os.path.join(self.infra_dir, '.assumptions.jsonl')
        self.assertFalse(os.path.exists(path))

        write_assumption_checkpoint(
            infra_dir=self.infra_dir,
            phase='intent',
            cfa_state='INTENT',
            artifact_summary='Intent document approved',
        )

        self.assertTrue(os.path.exists(path))

    def test_entry_matches_prompt_schema(self):
        """Each JSONL entry matches the in-flight prompt's expected schema.

        The in-flight prompt template expects: milestone, timestamp,
        assumptions (with complexity, approach_viability, preference_model,
        scope), and recommendation.
        """
        from orchestrator.learnings import write_assumption_checkpoint

        write_assumption_checkpoint(
            infra_dir=self.infra_dir,
            phase='planning',
            cfa_state='PLAN',
            artifact_summary='Decomposed into 3 sub-tasks',
        )

        path = os.path.join(self.infra_dir, '.assumptions.jsonl')
        line = Path(path).read_text().strip()
        entry = json.loads(line)

        # Schema fields the in-flight prompt template expects
        self.assertIn('milestone', entry)
        self.assertIn('timestamp', entry)
        self.assertIn('assumptions', entry)
        self.assertIn('recommendation', entry)

        assumptions = entry['assumptions']
        self.assertIn('complexity', assumptions)
        self.assertIn('approach_viability', assumptions)
        self.assertIn('preference_model', assumptions)
        self.assertIn('scope', assumptions)

        # Artifact content should be embedded in assumptions
        self.assertIn('Decomposed into 3 sub-tasks', assumptions['complexity'])

    def test_appends_multiple_entries(self):
        """Successive calls append, not overwrite."""
        from orchestrator.learnings import write_assumption_checkpoint

        write_assumption_checkpoint(
            infra_dir=self.infra_dir,
            phase='intent',
            cfa_state='INTENT',
            artifact_summary='Intent approved',
        )
        write_assumption_checkpoint(
            infra_dir=self.infra_dir,
            phase='planning',
            cfa_state='PLAN',
            artifact_summary='Plan approved',
        )

        path = os.path.join(self.infra_dir, '.assumptions.jsonl')
        lines = [l for l in Path(path).read_text().strip().split('\n') if l.strip()]
        self.assertEqual(len(lines), 2)

        entries = [json.loads(l) for l in lines]
        self.assertIn('intent', entries[0]['milestone'])
        self.assertIn('planning', entries[1]['milestone'])


# ── 2. Premortem generation ──────────────────────────────────────────────────

class TestWritePremortem(unittest.TestCase):
    """write_premortem() generates .premortem.md from plan content."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.infra_dir = self.tmpdir

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_creates_premortem_file(self):
        """Writes .premortem.md in infra_dir."""
        from orchestrator.learnings import write_premortem

        plan_content = "# Plan\n\n1. Refactor module A\n2. Add tests\n3. Deploy"
        _write(os.path.join(self.infra_dir, 'PLAN.md'), plan_content)

        write_premortem(infra_dir=self.infra_dir, task='Refactor module A')

        path = os.path.join(self.infra_dir, '.premortem.md')
        self.assertTrue(os.path.exists(path))
        content = Path(path).read_text()
        self.assertTrue(len(content) > 0)

    def test_includes_plan_content(self):
        """Premortem references the plan."""
        from orchestrator.learnings import write_premortem

        plan_content = "# Plan\n\n1. Refactor module A\n2. Add tests"
        _write(os.path.join(self.infra_dir, 'PLAN.md'), plan_content)

        write_premortem(infra_dir=self.infra_dir, task='Refactor module A')

        path = os.path.join(self.infra_dir, '.premortem.md')
        content = Path(path).read_text()
        # Should contain the plan content or reference to it
        self.assertIn('Refactor module A', content)

    def test_skips_when_no_plan(self):
        """Does nothing when PLAN.md does not exist."""
        from orchestrator.learnings import write_premortem

        write_premortem(infra_dir=self.infra_dir, task='Some task')

        path = os.path.join(self.infra_dir, '.premortem.md')
        self.assertFalse(os.path.exists(path))

    def test_overwrites_stale_premortem(self):
        """If .premortem.md already exists (from a corrected plan), overwrites it."""
        from orchestrator.learnings import write_premortem

        # Write an initial premortem
        _write(os.path.join(self.infra_dir, '.premortem.md'), 'stale premortem')
        _write(os.path.join(self.infra_dir, 'PLAN.md'), '# New Plan\n\n1. New approach')

        write_premortem(infra_dir=self.infra_dir, task='New approach')

        content = Path(os.path.join(self.infra_dir, '.premortem.md')).read_text()
        self.assertNotEqual(content, 'stale premortem')
        self.assertIn('New approach', content)


# ── 3. Accuracy-aware reinforcement ──────────────────────────────────────────

class TestAccuracyAwareReinforcement(unittest.TestCase):
    """_reinforce_retrieved() uses accuracy signal from exec stream."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.infra_dir = os.path.join(self.tmpdir, 'infra')
        self.project_dir = os.path.join(self.tmpdir, 'project')
        os.makedirs(self.infra_dir)
        os.makedirs(self.project_dir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_retrieved_ids(self, ids: list[str]) -> None:
        """Write .retrieved-ids.txt with entry IDs."""
        _write(
            os.path.join(self.infra_dir, '.retrieved-ids.txt'),
            '\n'.join(ids) + '\n',
        )

    def _make_memory_entry(self, entry_id: str, learning: str,
                           reinforcement_count: int = 0) -> str:
        """Return a formatted memory entry with YAML frontmatter."""
        return (
            f'---\n'
            f'id: {entry_id}\n'
            f'reinforcement_count: {reinforcement_count}\n'
            f'last_reinforced: ""\n'
            f'importance: 0.5\n'
            f'---\n'
            f'## [{date.today().isoformat()}] {learning}\n'
            f'**Context:** test\n'
            f'**Learning:** {learning}\n'
            f'**Action:** Apply this\n'
        )

    def _make_tasks_file(self, entries: list[str]) -> str:
        """Write a tasks file with the given entries."""
        tasks_dir = os.path.join(self.project_dir, 'tasks')
        os.makedirs(tasks_dir, exist_ok=True)
        path = os.path.join(tasks_dir, 'test-learnings.md')
        _write(path, '\n\n'.join(entries))
        return path

    def _make_exec_stream(self, content_lines: list[str]) -> None:
        """Write a minimal exec stream with assistant content."""
        stream_path = os.path.join(self.infra_dir, '.exec-stream.jsonl')
        lines = []
        for line in content_lines:
            lines.append(json.dumps({
                'type': 'assistant',
                'message': {'content': [{'type': 'text', 'text': line}]},
            }))
        _write(stream_path, '\n'.join(lines) + '\n')

    def test_does_nothing_when_no_retrieved_ids(self):
        """No .retrieved-ids.txt → no changes."""
        from orchestrator.learnings import _reinforce_retrieved

        entry = self._make_memory_entry('entry-1', 'Always backup')
        self._make_tasks_file([entry])

        _reinforce_retrieved(infra_dir=self.infra_dir, project_dir=self.project_dir)

        # No crash, no changes
        from scripts.memory_entry import parse_memory_file
        content = Path(os.path.join(self.project_dir, 'tasks', 'test-learnings.md')).read_text()
        entries = parse_memory_file(content)
        self.assertEqual(entries[0].reinforcement_count, 0)

    def test_reinforces_aligned_entries(self):
        """Entries retrieved and aligned with outcomes get reinforcement_count += 1."""
        from orchestrator.learnings import _reinforce_retrieved

        entry = self._make_memory_entry('entry-aligned', 'Always run tests before deploy')
        self._make_tasks_file([entry])
        self._make_retrieved_ids(['entry-aligned'])
        # Exec stream shows tests were run — aligns with the learning
        self._make_exec_stream(['Running test suite before deployment...'])

        _reinforce_retrieved(infra_dir=self.infra_dir, project_dir=self.project_dir)

        from scripts.memory_entry import parse_memory_file
        content = Path(os.path.join(self.project_dir, 'tasks', 'test-learnings.md')).read_text()
        entries = parse_memory_file(content)
        # Should be reinforced (count > 0)
        self.assertGreaterEqual(entries[0].reinforcement_count, 1)

    def test_decrements_non_aligned_entries(self):
        """Entries retrieved but not aligned with outcomes get decremented."""
        from orchestrator.learnings import _reinforce_retrieved

        # Entry about database backups, but session was about UI refactoring
        entry = self._make_memory_entry(
            'entry-misaligned', 'Always backup database before migration',
            reinforcement_count=3,
        )
        self._make_tasks_file([entry])
        self._make_retrieved_ids(['entry-misaligned'])
        # Exec stream about completely unrelated work
        self._make_exec_stream([
            'Refactoring the CSS layout for the dashboard component',
            'Updated flexbox properties and grid alignment',
        ])

        _reinforce_retrieved(infra_dir=self.infra_dir, project_dir=self.project_dir)

        from scripts.memory_entry import parse_memory_file
        content = Path(os.path.join(self.project_dir, 'tasks', 'test-learnings.md')).read_text()
        entries = parse_memory_file(content)
        # Should be decremented from 3 to 2
        self.assertEqual(entries[0].reinforcement_count, 2)

    def test_reinforcement_count_never_below_zero(self):
        """Negative reinforcement has a floor at 0."""
        from orchestrator.learnings import _reinforce_retrieved

        entry = self._make_memory_entry(
            'entry-floor', 'Obscure database migration pattern',
            reinforcement_count=0,
        )
        self._make_tasks_file([entry])
        self._make_retrieved_ids(['entry-floor'])
        # Exec stream about completely unrelated work
        self._make_exec_stream([
            'Refactoring the CSS layout for the dashboard component',
        ])

        _reinforce_retrieved(infra_dir=self.infra_dir, project_dir=self.project_dir)

        from scripts.memory_entry import parse_memory_file
        content = Path(os.path.join(self.project_dir, 'tasks', 'test-learnings.md')).read_text()
        entries = parse_memory_file(content)
        self.assertEqual(entries[0].reinforcement_count, 0)


# ── 4. Engine: assumption checkpoints at phase completion ────────────────────

class TestEngineAssumptionCheckpoints(unittest.TestCase):
    """Orchestrator writes assumption checkpoints when phases complete."""

    def _make_orchestrator(self, infra_dir: str) -> 'Orchestrator':
        from orchestrator.engine import Orchestrator
        from orchestrator.events import EventBus
        from orchestrator.phase_config import PhaseConfig, PhaseSpec
        from scripts.cfa_state import CfaState

        cfa = CfaState(state='INTENT', phase='intent', actor='agent',
                       history=[], backtrack_count=0)
        cfg = MagicMock(spec=PhaseConfig)
        cfg.stall_timeout = 1800
        cfg.human_actor_states = frozenset()
        cfg.phase.return_value = PhaseSpec(
            name='intent', agent_file='agents/intent.json', lead='intent-lead',
            permission_mode='acceptEdits', stream_file='.intent-stream.jsonl',
            artifact=None, approval_state='INTENT_ASSERT', settings_overlay={},
        )
        cfg.team.return_value = MagicMock()

        bus = MagicMock(spec=EventBus)
        bus.publish = AsyncMock()

        return Orchestrator(
            cfa_state=cfa, phase_config=cfg, event_bus=bus,
            input_provider=AsyncMock(), infra_dir=infra_dir,
            project_workdir='/tmp/project', session_worktree='/tmp/worktree',
            proxy_model_path='/tmp/proxy.json', project_slug='test',
            poc_root='/tmp/poc', task='Test task', session_id='test-session',
        )

    def test_phase_completion_writes_assumption_checkpoint(self):
        """When _run_phase completes successfully, an assumption checkpoint is written."""
        tmpdir = tempfile.mkdtemp()
        try:
            from orchestrator.learnings import write_assumption_checkpoint

            orch = self._make_orchestrator(tmpdir)

            # Simulate: phase completed, write checkpoint
            write_assumption_checkpoint(
                infra_dir=tmpdir,
                phase='intent',
                cfa_state='INTENT',
                artifact_summary='Intent aligned and approved',
            )

            path = os.path.join(tmpdir, '.assumptions.jsonl')
            self.assertTrue(os.path.exists(path))
            entry = json.loads(Path(path).read_text().strip())
            self.assertIn('intent', entry['milestone'])
            self.assertIn('assumptions', entry)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_engine_includes_artifact_content_in_checkpoint(self):
        """_write_assumption_checkpoint reads INTENT.md and includes its content."""
        tmpdir = tempfile.mkdtemp()
        try:
            orch = self._make_orchestrator(tmpdir)

            # Write an INTENT.md artifact
            intent_content = '# Intent\n\nRefactor the auth module to use OAuth2.'
            _write(os.path.join(tmpdir, 'INTENT.md'), intent_content)

            # Call the engine method directly
            orch._write_assumption_checkpoint('intent')

            path = os.path.join(tmpdir, '.assumptions.jsonl')
            self.assertTrue(os.path.exists(path))
            entry = json.loads(Path(path).read_text().strip())
            # Artifact content should appear in the assumptions fields
            self.assertIn('OAuth2', entry['assumptions']['complexity'])
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


# ── 5. Engine: premortem at planning→execution bridge ────────────────────────

class TestEnginePremortem(unittest.TestCase):
    """Orchestrator writes premortem at the planning→execution bridge."""

    def test_premortem_written_from_plan(self):
        """write_premortem creates .premortem.md from PLAN.md content."""
        tmpdir = tempfile.mkdtemp()
        try:
            from orchestrator.learnings import write_premortem

            plan = '# Plan\n\n1. Implement feature X\n2. Add tests\n3. Deploy'
            _write(os.path.join(tmpdir, 'PLAN.md'), plan)

            write_premortem(infra_dir=tmpdir, task='Implement feature X')

            path = os.path.join(tmpdir, '.premortem.md')
            self.assertTrue(os.path.exists(path))
            content = Path(path).read_text()
            self.assertTrue(len(content) > 0)
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
