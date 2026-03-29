"""Tests for issue #276: INTERVENE events recorded as learning-system memory chunks.

Verifies:
1. write_intervention_chunk() writes a JSONL entry to .interventions.jsonl
2. The chunk captures content, senders, CfA state, phase, and timestamp
3. write_intervention_outcome() appends an outcome record to .interventions.jsonl
4. _deliver_intervention() calls write_intervention_chunk()
5. _check_interrupt_propagation() calls write_intervention_outcome()
6. _promote_interventions() reads .interventions.jsonl for post-session extraction
7. extract_learnings() includes the interventions scope
8. summarize_session.promote() handles the interventions scope
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))


# ── Test 1: write_intervention_chunk writes a JSONL entry ─────────────────────

class TestWriteInterventionChunk(unittest.TestCase):
    """write_intervention_chunk() must write a structured entry to .interventions.jsonl."""

    def _call(self, infra_dir, **kwargs):
        from projects.POC.orchestrator.learnings import write_intervention_chunk
        write_intervention_chunk(infra_dir=infra_dir, **kwargs)

    def test_creates_interventions_jsonl(self):
        """write_intervention_chunk creates .interventions.jsonl in infra_dir."""
        with tempfile.TemporaryDirectory() as tmp:
            self._call(
                tmp,
                content='please stop and reconsider',
                senders=['human'],
                cfa_state='PLANNING_REVIEW',
                phase='planning',
            )
            path = os.path.join(tmp, '.interventions.jsonl')
            self.assertTrue(os.path.isfile(path), '.interventions.jsonl must exist')

    def test_chunk_contains_content(self):
        """The written chunk must include the intervention content."""
        with tempfile.TemporaryDirectory() as tmp:
            self._call(
                tmp,
                content='the requirements changed',
                senders=['human'],
                cfa_state='TASK_EXECUTE',
                phase='execution',
            )
            path = os.path.join(tmp, '.interventions.jsonl')
            entry = json.loads(Path(path).read_text().strip())
            self.assertEqual(entry['content'], 'the requirements changed')

    def test_chunk_contains_cfa_state(self):
        """The written chunk must include the CfA state at intervention time."""
        with tempfile.TemporaryDirectory() as tmp:
            self._call(
                tmp,
                content='stop',
                senders=['human'],
                cfa_state='PLANNING_REVIEW',
                phase='planning',
            )
            entry = json.loads(
                Path(os.path.join(tmp, '.interventions.jsonl')).read_text().strip()
            )
            self.assertEqual(entry['cfa_state'], 'PLANNING_REVIEW')

    def test_chunk_contains_phase(self):
        """The written chunk must include the phase name."""
        with tempfile.TemporaryDirectory() as tmp:
            self._call(
                tmp,
                content='stop',
                senders=['human'],
                cfa_state='TASK_EXECUTE',
                phase='execution',
            )
            entry = json.loads(
                Path(os.path.join(tmp, '.interventions.jsonl')).read_text().strip()
            )
            self.assertEqual(entry['phase'], 'execution')

    def test_chunk_contains_senders(self):
        """The written chunk must include the sender list."""
        with tempfile.TemporaryDirectory() as tmp:
            self._call(
                tmp,
                content='advice from alice',
                senders=['advisor:alice'],
                cfa_state='TASK_EXECUTE',
                phase='execution',
            )
            entry = json.loads(
                Path(os.path.join(tmp, '.interventions.jsonl')).read_text().strip()
            )
            self.assertIn('advisor:alice', entry['senders'])

    def test_chunk_has_timestamp(self):
        """The written chunk must include a timestamp."""
        with tempfile.TemporaryDirectory() as tmp:
            self._call(
                tmp,
                content='stop',
                senders=['human'],
                cfa_state='TASK_EXECUTE',
                phase='execution',
            )
            entry = json.loads(
                Path(os.path.join(tmp, '.interventions.jsonl')).read_text().strip()
            )
            self.assertIn('timestamp', entry)
            self.assertTrue(entry['timestamp'])

    def test_chunk_type_is_intervention(self):
        """The written chunk must have type='intervention'."""
        with tempfile.TemporaryDirectory() as tmp:
            self._call(
                tmp,
                content='stop',
                senders=['human'],
                cfa_state='TASK_EXECUTE',
                phase='execution',
            )
            entry = json.loads(
                Path(os.path.join(tmp, '.interventions.jsonl')).read_text().strip()
            )
            self.assertEqual(entry['type'], 'intervention')

    def test_multiple_chunks_appended(self):
        """Multiple calls append multiple entries (one per line)."""
        with tempfile.TemporaryDirectory() as tmp:
            self._call(tmp, content='first', senders=['human'],
                       cfa_state='TASK_EXECUTE', phase='execution')
            self._call(tmp, content='second', senders=['human'],
                       cfa_state='TASK_EXECUTE', phase='execution')
            lines = Path(os.path.join(tmp, '.interventions.jsonl')).read_text().strip().splitlines()
            self.assertEqual(len(lines), 2)


# ── Test 2: write_intervention_outcome appends an outcome record ───────────────

class TestWriteInterventionOutcome(unittest.TestCase):
    """write_intervention_outcome() must append an outcome record."""

    def _write_chunk(self, infra_dir):
        from projects.POC.orchestrator.learnings import write_intervention_chunk
        write_intervention_chunk(
            infra_dir=infra_dir,
            content='stop',
            senders=['human'],
            cfa_state='TASK_EXECUTE',
            phase='execution',
        )

    def _write_outcome(self, infra_dir, outcome, backtrack_phase=''):
        from projects.POC.orchestrator.learnings import write_intervention_outcome
        write_intervention_outcome(
            infra_dir=infra_dir,
            outcome=outcome,
            backtrack_phase=backtrack_phase,
        )

    def test_outcome_appended_as_new_line(self):
        """write_intervention_outcome appends a second JSONL line."""
        with tempfile.TemporaryDirectory() as tmp:
            self._write_chunk(tmp)
            self._write_outcome(tmp, 'continue')
            lines = Path(os.path.join(tmp, '.interventions.jsonl')).read_text().strip().splitlines()
            self.assertEqual(len(lines), 2)

    def test_outcome_record_type(self):
        """Outcome record has type='intervention_outcome'."""
        with tempfile.TemporaryDirectory() as tmp:
            self._write_chunk(tmp)
            self._write_outcome(tmp, 'backtrack', backtrack_phase='planning')
            lines = Path(os.path.join(tmp, '.interventions.jsonl')).read_text().strip().splitlines()
            outcome_entry = json.loads(lines[-1])
            self.assertEqual(outcome_entry['type'], 'intervention_outcome')

    def test_outcome_continue(self):
        """Outcome record captures 'continue' outcome."""
        with tempfile.TemporaryDirectory() as tmp:
            self._write_chunk(tmp)
            self._write_outcome(tmp, 'continue')
            lines = Path(os.path.join(tmp, '.interventions.jsonl')).read_text().strip().splitlines()
            entry = json.loads(lines[-1])
            self.assertEqual(entry['outcome'], 'continue')

    def test_outcome_backtrack_with_phase(self):
        """Backtrack outcome includes backtrack_phase."""
        with tempfile.TemporaryDirectory() as tmp:
            self._write_chunk(tmp)
            self._write_outcome(tmp, 'backtrack', backtrack_phase='intent')
            lines = Path(os.path.join(tmp, '.interventions.jsonl')).read_text().strip().splitlines()
            entry = json.loads(lines[-1])
            self.assertEqual(entry['outcome'], 'backtrack')
            self.assertEqual(entry['backtrack_phase'], 'intent')

    def test_outcome_withdraw(self):
        """Withdraw outcome is recorded correctly."""
        with tempfile.TemporaryDirectory() as tmp:
            self._write_chunk(tmp)
            self._write_outcome(tmp, 'withdraw')
            lines = Path(os.path.join(tmp, '.interventions.jsonl')).read_text().strip().splitlines()
            entry = json.loads(lines[-1])
            self.assertEqual(entry['outcome'], 'withdraw')

    def test_outcome_without_prior_chunk_is_safe(self):
        """write_intervention_outcome is safe even without a prior chunk."""
        with tempfile.TemporaryDirectory() as tmp:
            # No prior chunk — should not raise
            self._write_outcome(tmp, 'continue')
            path = os.path.join(tmp, '.interventions.jsonl')
            self.assertTrue(os.path.isfile(path))


# ── Test 3: _deliver_intervention calls write_intervention_chunk ───────────────

class TestDeliverInterventionWritesChunk(unittest.TestCase):
    """_deliver_intervention must write a chunk to .interventions.jsonl."""

    def _make_orchestrator(self, infra_dir, queue=None):
        from projects.POC.orchestrator.intervention import InterventionQueue
        from projects.POC.orchestrator.engine import Orchestrator
        from projects.POC.orchestrator.events import EventBus
        from projects.POC.scripts.cfa_state import make_initial_state

        q = queue or InterventionQueue()
        return Orchestrator(
            cfa_state=make_initial_state(task_id='test'),
            phase_config=_make_stub_phase_config(),
            event_bus=EventBus(),
            input_provider=None,
            infra_dir=infra_dir,
            project_workdir=infra_dir,
            session_worktree=infra_dir,
            proxy_model_path=infra_dir,
            project_slug='test',
            poc_root=infra_dir,
            intervention_queue=q,
            session_id='test-session',
        )

    def test_deliver_intervention_writes_interventions_jsonl(self):
        """_deliver_intervention writes .interventions.jsonl in infra_dir."""
        from projects.POC.orchestrator.intervention import InterventionQueue

        with tempfile.TemporaryDirectory() as tmp:
            q = InterventionQueue()
            q.enqueue('change direction', sender='human')
            orch = self._make_orchestrator(tmp, q)
            asyncio.run(orch._deliver_intervention())

            path = os.path.join(tmp, '.interventions.jsonl')
            self.assertTrue(os.path.isfile(path), '.interventions.jsonl must be written')

    def test_deliver_intervention_chunk_has_content(self):
        """The written chunk captures the intervention message content."""
        from projects.POC.orchestrator.intervention import InterventionQueue

        with tempfile.TemporaryDirectory() as tmp:
            q = InterventionQueue()
            q.enqueue('stop and reconsider', sender='human')
            orch = self._make_orchestrator(tmp, q)
            asyncio.run(orch._deliver_intervention())

            entry = json.loads(
                Path(os.path.join(tmp, '.interventions.jsonl')).read_text().strip()
            )
            self.assertIn('stop and reconsider', entry['content'])

    def test_deliver_intervention_chunk_has_cfa_state(self):
        """The written chunk captures the CfA state at delivery time."""
        from projects.POC.orchestrator.intervention import InterventionQueue

        with tempfile.TemporaryDirectory() as tmp:
            q = InterventionQueue()
            q.enqueue('redirect', sender='human')
            orch = self._make_orchestrator(tmp, q)
            asyncio.run(orch._deliver_intervention())

            entry = json.loads(
                Path(os.path.join(tmp, '.interventions.jsonl')).read_text().strip()
            )
            self.assertIn('cfa_state', entry)
            self.assertTrue(entry['cfa_state'])

    def test_no_queue_does_not_write_chunk(self):
        """Without an intervention queue, no chunk is written."""
        with tempfile.TemporaryDirectory() as tmp:
            from projects.POC.orchestrator.engine import Orchestrator
            from projects.POC.orchestrator.events import EventBus
            from projects.POC.scripts.cfa_state import make_initial_state

            orch = Orchestrator(
                cfa_state=make_initial_state(task_id='test'),
                phase_config=_make_stub_phase_config(),
                event_bus=EventBus(),
                input_provider=None,
                infra_dir=tmp,
                project_workdir=tmp,
                session_worktree=tmp,
                proxy_model_path=tmp,
                project_slug='test',
                poc_root=tmp,
            )
            asyncio.run(orch._deliver_intervention())
            self.assertFalse(
                os.path.isfile(os.path.join(tmp, '.interventions.jsonl'))
            )


# ── Test 4: _check_interrupt_propagation writes outcome ────────────────────────

class TestInterruptPropagationWritesOutcome(unittest.TestCase):
    """_check_interrupt_propagation must write an outcome record after resolving."""

    def test_check_interrupt_propagation_writes_outcome_source(self):
        """_check_interrupt_propagation source must call write_intervention_outcome."""
        import inspect
        from projects.POC.orchestrator.engine import Orchestrator
        source = inspect.getsource(Orchestrator._check_interrupt_propagation)
        self.assertIn(
            'write_intervention_outcome', source,
            '_check_interrupt_propagation must call write_intervention_outcome',
        )


# ── Test 5: _promote_interventions exists and reads .interventions.jsonl ────────

class TestPromoteInterventions(unittest.TestCase):
    """_promote_interventions must read .interventions.jsonl and pass it to promote."""

    def test_promote_interventions_exists(self):
        """_promote_interventions must be importable from learnings."""
        from projects.POC.orchestrator.learnings import _promote_interventions
        self.assertTrue(callable(_promote_interventions))

    def test_promote_interventions_skips_missing_file(self):
        """_promote_interventions is a no-op when .interventions.jsonl is absent."""
        with tempfile.TemporaryDirectory() as tmp:
            proj = tempfile.mkdtemp()
            try:
                # Should not raise even with no file
                from projects.POC.orchestrator.learnings import _promote_interventions
                _promote_interventions(
                    infra_dir=tmp,
                    project_dir=proj,
                    scripts_dir='',
                )
            finally:
                import shutil
                shutil.rmtree(proj, ignore_errors=True)

    def test_promote_interventions_skips_empty_file(self):
        """_promote_interventions is a no-op when .interventions.jsonl is empty."""
        with tempfile.TemporaryDirectory() as tmp:
            proj = tempfile.mkdtemp()
            try:
                Path(os.path.join(tmp, '.interventions.jsonl')).touch()
                from projects.POC.orchestrator.learnings import _promote_interventions
                _promote_interventions(
                    infra_dir=tmp,
                    project_dir=proj,
                    scripts_dir='',
                )
            finally:
                import shutil
                shutil.rmtree(proj, ignore_errors=True)


# ── Test 6: extract_learnings includes interventions scope ──────────────────────

class TestExtractLearningsInterventionsScope(unittest.TestCase):
    """extract_learnings must include an interventions scope."""

    def test_extract_learnings_calls_promote_interventions(self):
        """extract_learnings source must reference _promote_interventions."""
        import inspect
        from projects.POC.orchestrator.learnings import extract_learnings
        source = inspect.getsource(extract_learnings)
        self.assertIn(
            '_promote_interventions', source,
            'extract_learnings must call _promote_interventions',
        )

    def test_extract_learnings_runs_without_interventions_file(self):
        """extract_learnings completes successfully even with no .interventions.jsonl."""
        with tempfile.TemporaryDirectory() as tmp_infra:
            with tempfile.TemporaryDirectory() as tmp_proj:
                from projects.POC.orchestrator.learnings import extract_learnings
                from unittest.mock import patch

                async def run():
                    with patch(
                        'projects.POC.orchestrator.learnings._promote_interventions',
                    ) as mock_pi:
                        mock_pi.return_value = None
                        await extract_learnings(
                            infra_dir=tmp_infra,
                            project_dir=tmp_proj,
                            session_worktree=tmp_infra,
                            task='test task',
                            poc_root=tmp_infra,
                        )
                        return mock_pi.call_count

                count = asyncio.run(run())
                self.assertGreater(count, 0, '_promote_interventions must be called')


# ── Test 7: summarize_session.promote handles interventions scope ──────────────

class TestSummarizeSessionInterventionsScope(unittest.TestCase):
    """summarize_session.promote() must handle the interventions scope."""

    def test_promote_interventions_scope_exists(self):
        """promote() must not return 'Unknown scope' for interventions."""
        from projects.POC.scripts.summarize_session import promote

        with tempfile.TemporaryDirectory() as tmp_infra:
            with tempfile.TemporaryDirectory() as tmp_proj:
                # No .interventions.jsonl file — should return 0 (skip), not 1 (unknown)
                result = promote(
                    'interventions',
                    session_dir=tmp_infra,
                    project_dir=tmp_proj,
                    output_dir='',
                )
                # Should return 0 (no-op skip) not 1 (unknown scope error)
                self.assertEqual(result, 0, 'interventions scope must be recognized (return 0 for skip)')

    def test_promote_interventions_scope_has_prompt(self):
        """PROMPTS dict must contain an 'interventions' key."""
        from projects.POC.scripts.summarize_session import PROMPTS
        self.assertIn('interventions', PROMPTS, "PROMPTS must have an 'interventions' key")

    def test_promote_interventions_writes_to_proxy_tasks(self):
        """promote(interventions) writes output to proxy-tasks/ directory."""
        from projects.POC.scripts.summarize_session import promote

        with tempfile.TemporaryDirectory() as tmp_infra:
            with tempfile.TemporaryDirectory() as tmp_proj:
                # Write a non-empty .interventions.jsonl
                chunk = json.dumps({
                    'type': 'intervention',
                    'timestamp': '2026-01-01T00:00:00',
                    'content': 'please reconsider the approach',
                    'senders': ['human'],
                    'cfa_state': 'PLANNING_REVIEW',
                    'phase': 'planning',
                    'outcome': 'pending',
                })
                outcome = json.dumps({
                    'type': 'intervention_outcome',
                    'timestamp': '2026-01-01T00:01:00',
                    'outcome': 'backtrack',
                    'backtrack_phase': 'intent',
                })
                Path(os.path.join(tmp_infra, '.interventions.jsonl')).write_text(
                    chunk + '\n' + outcome + '\n'
                )

                from unittest.mock import patch
                with patch('projects.POC.scripts.summarize_session.summarize') as mock_summarize:
                    promote(
                        'interventions',
                        session_dir=tmp_infra,
                        project_dir=tmp_proj,
                        output_dir='',
                    )
                    self.assertTrue(
                        mock_summarize.called,
                        'summarize() must be called for non-empty .interventions.jsonl',
                    )
                    output_arg = mock_summarize.call_args[0][1]
                    self.assertIn(
                        'proxy-tasks', output_arg,
                        'interventions scope must write to proxy-tasks/',
                    )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_stub_phase_config():
    class _StubPhaseConfig:
        stall_timeout = 1800
        human_actor_states = frozenset()

        def phase_spec(self, phase_name):
            return None

    return _StubPhaseConfig()


if __name__ == '__main__':
    unittest.main()
