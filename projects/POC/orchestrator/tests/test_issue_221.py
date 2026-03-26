"""Tests for Issue #221: ACT-R Phase 1 evaluation harness.

Four evaluation metrics computed from proxy_memory.db chunks:
1. Action match rate — posterior_prediction vs outcome for escalated gates
2. Prior calibration — prior_prediction vs posterior_prediction agreement
3. Surprise calibration — when surprise detected, did the human respond?
4. Go/no-go assessment — sample coverage and threshold checks

Plus a reporting function that aggregates everything.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from projects.POC.orchestrator.proxy_memory import (
    MemoryChunk,
    open_proxy_db,
    store_chunk,
)


def _make_chunk(
    chunk_id: str = 'test-chunk',
    state: str = 'PLAN_ASSERT',
    task_type: str = 'security',
    outcome: str = 'approve',
    prior_prediction: str = 'approve',
    posterior_prediction: str = 'approve',
    prior_confidence: float = 0.8,
    posterior_confidence: float = 0.9,
    prediction_delta: str = '',
    salient_percepts: list[str] | None = None,
    human_response: str = '',
    traces: list[int] | None = None,
    **kwargs,
) -> MemoryChunk:
    defaults = dict(
        id=chunk_id,
        type='gate_outcome',
        state=state,
        task_type=task_type,
        outcome=outcome,
        prior_prediction=prior_prediction,
        posterior_prediction=posterior_prediction,
        prior_confidence=prior_confidence,
        posterior_confidence=posterior_confidence,
        prediction_delta=prediction_delta,
        salient_percepts=salient_percepts or [],
        human_response=human_response,
        content='test interaction',
        traces=traces or [1],
        embedding_model='test/test',
    )
    defaults.update(kwargs)
    return MemoryChunk(**defaults)


def _seed_db(tmpdir: str, chunks: list[MemoryChunk]) -> str:
    """Create and seed a proxy memory DB. Returns the db_path."""
    db_path = os.path.join(tmpdir, 'proxy_memory.db')
    conn = open_proxy_db(db_path)
    for chunk in chunks:
        store_chunk(conn, chunk)
    conn.close()
    return db_path


# ── Action Match Rate ────────────────────────────────────────────────────────

class TestActionMatchRate(unittest.TestCase):
    """posterior_prediction vs outcome, only for gates where human responded."""

    def test_perfect_match(self):
        from projects.POC.orchestrator.proxy_metrics import action_match_rate

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [
                _make_chunk('c1', outcome='approve', posterior_prediction='approve',
                            human_response='Looks good'),
                _make_chunk('c2', outcome='correct', posterior_prediction='correct',
                            human_response='Needs changes'),
            ])
            conn = open_proxy_db(db_path)
            result = action_match_rate(conn)
            conn.close()

            self.assertAlmostEqual(result.rate, 1.0)
            self.assertEqual(result.eligible, 2)
            self.assertEqual(result.matched, 2)

    def test_partial_match(self):
        from projects.POC.orchestrator.proxy_metrics import action_match_rate

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [
                _make_chunk('c1', outcome='approve', posterior_prediction='approve',
                            human_response='OK'),
                _make_chunk('c2', outcome='correct', posterior_prediction='approve',
                            human_response='Wrong'),
                _make_chunk('c3', outcome='approve', posterior_prediction='correct',
                            human_response='Actually fine'),
            ])
            conn = open_proxy_db(db_path)
            result = action_match_rate(conn)
            conn.close()

            self.assertAlmostEqual(result.rate, 1 / 3)
            self.assertEqual(result.eligible, 3)
            self.assertEqual(result.matched, 1)

    def test_excludes_chunks_without_human_response(self):
        """Gates where no human responded are excluded from action match."""
        from projects.POC.orchestrator.proxy_metrics import action_match_rate

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [
                _make_chunk('c1', outcome='approve', posterior_prediction='approve',
                            human_response='OK'),
                # No human_response — auto-approved, should be excluded
                _make_chunk('c2', outcome='approve', posterior_prediction='approve',
                            human_response=''),
            ])
            conn = open_proxy_db(db_path)
            result = action_match_rate(conn)
            conn.close()

            self.assertEqual(result.eligible, 1)
            self.assertAlmostEqual(result.rate, 1.0)

    def test_empty_db_returns_zero(self):
        from projects.POC.orchestrator.proxy_metrics import action_match_rate

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [])
            conn = open_proxy_db(db_path)
            result = action_match_rate(conn)
            conn.close()

            self.assertEqual(result.eligible, 0)
            self.assertAlmostEqual(result.rate, 0.0)

    def test_excludes_chunks_without_posterior(self):
        """Pre-two-pass chunks with empty posterior_prediction are excluded."""
        from projects.POC.orchestrator.proxy_metrics import action_match_rate

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [
                _make_chunk('c1', outcome='approve', posterior_prediction='',
                            human_response='OK'),
            ])
            conn = open_proxy_db(db_path)
            result = action_match_rate(conn)
            conn.close()

            self.assertEqual(result.eligible, 0)


# ── Prior Calibration ────────────────────────────────────────────────────────

class TestPriorCalibration(unittest.TestCase):
    """prior_prediction vs posterior_prediction agreement rate."""

    def test_perfect_calibration(self):
        from projects.POC.orchestrator.proxy_metrics import prior_calibration

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [
                _make_chunk('c1', prior_prediction='approve',
                            posterior_prediction='approve'),
                _make_chunk('c2', prior_prediction='correct',
                            posterior_prediction='correct'),
            ])
            conn = open_proxy_db(db_path)
            result = prior_calibration(conn)
            conn.close()

            self.assertAlmostEqual(result.rate, 1.0)
            self.assertEqual(result.eligible, 2)

    def test_partial_calibration(self):
        from projects.POC.orchestrator.proxy_metrics import prior_calibration

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [
                _make_chunk('c1', prior_prediction='approve',
                            posterior_prediction='approve'),
                _make_chunk('c2', prior_prediction='approve',
                            posterior_prediction='correct'),
            ])
            conn = open_proxy_db(db_path)
            result = prior_calibration(conn)
            conn.close()

            self.assertAlmostEqual(result.rate, 0.5)
            self.assertEqual(result.agreed, 1)

    def test_excludes_chunks_without_both_predictions(self):
        from projects.POC.orchestrator.proxy_metrics import prior_calibration

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [
                _make_chunk('c1', prior_prediction='', posterior_prediction='approve'),
                _make_chunk('c2', prior_prediction='approve', posterior_prediction=''),
                _make_chunk('c3', prior_prediction='approve',
                            posterior_prediction='approve'),
            ])
            conn = open_proxy_db(db_path)
            result = prior_calibration(conn)
            conn.close()

            self.assertEqual(result.eligible, 1)
            self.assertAlmostEqual(result.rate, 1.0)


# ── Surprise Calibration ─────────────────────────────────────────────────────

class TestSurpriseCalibration(unittest.TestCase):
    """When surprise was detected, did the human respond?"""

    def test_surprise_with_human_response(self):
        from projects.POC.orchestrator.proxy_metrics import surprise_calibration

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [
                _make_chunk('c1', prediction_delta='action changed from approve to correct',
                            salient_percepts=['missing rollback'],
                            human_response='Yes the rollback plan is missing'),
            ])
            conn = open_proxy_db(db_path)
            result = surprise_calibration(conn)
            conn.close()

            self.assertEqual(result.surprises, 1)
            self.assertEqual(result.confirmed, 1)
            self.assertAlmostEqual(result.rate, 1.0)

    def test_surprise_without_human_response(self):
        from projects.POC.orchestrator.proxy_metrics import surprise_calibration

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [
                _make_chunk('c1', prediction_delta='confidence shifted',
                            salient_percepts=['unusual pattern'],
                            human_response=''),
            ])
            conn = open_proxy_db(db_path)
            result = surprise_calibration(conn)
            conn.close()

            self.assertEqual(result.surprises, 1)
            self.assertEqual(result.confirmed, 0)
            self.assertAlmostEqual(result.rate, 0.0)

    def test_no_surprise_chunks_excluded(self):
        from projects.POC.orchestrator.proxy_metrics import surprise_calibration

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [
                _make_chunk('c1', prediction_delta='', salient_percepts=[],
                            human_response='OK'),
            ])
            conn = open_proxy_db(db_path)
            result = surprise_calibration(conn)
            conn.close()

            self.assertEqual(result.surprises, 0)

    def test_mixed_surprise_population(self):
        from projects.POC.orchestrator.proxy_metrics import surprise_calibration

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [
                # Surprise + confirmed
                _make_chunk('c1', prediction_delta='action changed',
                            salient_percepts=['missing tests'],
                            human_response='Agreed, add tests'),
                # Surprise + not confirmed
                _make_chunk('c2', prediction_delta='confidence shifted',
                            salient_percepts=['odd naming'],
                            human_response=''),
                # No surprise — excluded
                _make_chunk('c3', prediction_delta='', salient_percepts=[]),
            ])
            conn = open_proxy_db(db_path)
            result = surprise_calibration(conn)
            conn.close()

            self.assertEqual(result.surprises, 2)
            self.assertEqual(result.confirmed, 1)
            self.assertAlmostEqual(result.rate, 0.5)


# ── Go/No-Go Assessment ─────────────────────────────────────────────────────

class TestGoNoGo(unittest.TestCase):
    """Sample coverage and threshold checks for Phase 2 transition."""

    def _make_diverse_chunks(self) -> list[MemoryChunk]:
        """Create 12 chunks spanning 3 task types and 4 states, all matching."""
        chunks = []
        states = ['PLAN_ASSERT', 'WORK_ASSERT', 'ACCEPT_ASSERT', 'COUNTER_ASSERT']
        task_types = ['security', 'docs', 'migration']
        i = 0
        for state in states:
            for tt in task_types:
                i += 1
                chunks.append(_make_chunk(
                    f'c{i}', state=state, task_type=tt,
                    outcome='approve', posterior_prediction='approve',
                    human_response=f'Response {i}',
                ))
        return chunks

    def test_sufficient_coverage(self):
        from projects.POC.orchestrator.proxy_metrics import go_no_go_assessment

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, self._make_diverse_chunks())
            conn = open_proxy_db(db_path)
            result = go_no_go_assessment(conn)
            conn.close()

            self.assertGreaterEqual(result.distinct_task_types, 3)
            self.assertGreaterEqual(result.distinct_states, 4)

    def test_insufficient_task_types(self):
        from projects.POC.orchestrator.proxy_metrics import go_no_go_assessment

        with tempfile.TemporaryDirectory() as tmpdir:
            # Only 2 task types
            chunks = [
                _make_chunk('c1', state='PLAN_ASSERT', task_type='security',
                            outcome='approve', posterior_prediction='approve',
                            human_response='OK'),
                _make_chunk('c2', state='WORK_ASSERT', task_type='docs',
                            outcome='approve', posterior_prediction='approve',
                            human_response='OK'),
            ]
            db_path = _seed_db(tmpdir, chunks)
            conn = open_proxy_db(db_path)
            result = go_no_go_assessment(conn)
            conn.close()

            self.assertEqual(result.distinct_task_types, 2)
            self.assertFalse(result.coverage_met)

    def test_insufficient_total_below_50(self):
        from projects.POC.orchestrator.proxy_metrics import go_no_go_assessment

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, self._make_diverse_chunks())  # only 12
            conn = open_proxy_db(db_path)
            result = go_no_go_assessment(conn)
            conn.close()

            self.assertEqual(result.total_eligible, 12)
            self.assertFalse(result.sample_sufficient)

    def test_coverage_matrix_shape(self):
        """The coverage matrix has entries for each (state, task_type) pair."""
        from projects.POC.orchestrator.proxy_metrics import go_no_go_assessment

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, self._make_diverse_chunks())
            conn = open_proxy_db(db_path)
            result = go_no_go_assessment(conn)
            conn.close()

            # 4 states × 3 task types = 12 cells, each with count 1
            self.assertEqual(len(result.coverage_matrix), 12)
            for (state, tt), count in result.coverage_matrix.items():
                self.assertEqual(count, 1)

    def test_verdict_go(self):
        """When action match >= 70% and coverage met and sample >= 50, verdict is GO."""
        from projects.POC.orchestrator.proxy_metrics import go_no_go_assessment

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create 60 chunks: 4 states × 3 task types × 5 each = 60
            # All matching (100% action match rate)
            chunks = []
            states = ['PLAN_ASSERT', 'WORK_ASSERT', 'ACCEPT_ASSERT', 'COUNTER_ASSERT']
            task_types = ['security', 'docs', 'migration']
            i = 0
            for state in states:
                for tt in task_types:
                    for rep in range(5):
                        i += 1
                        chunks.append(_make_chunk(
                            f'c{i}', state=state, task_type=tt,
                            outcome='approve', posterior_prediction='approve',
                            human_response=f'Response {i}',
                        ))

            db_path = _seed_db(tmpdir, chunks)
            conn = open_proxy_db(db_path)
            result = go_no_go_assessment(conn)
            conn.close()

            self.assertTrue(result.sample_sufficient)
            self.assertTrue(result.coverage_met)
            self.assertEqual(result.verdict, 'GO')

    def test_verdict_no_go(self):
        """When action match < 60%, verdict is NO_GO."""
        from projects.POC.orchestrator.proxy_metrics import go_no_go_assessment

        with tempfile.TemporaryDirectory() as tmpdir:
            chunks = []
            states = ['PLAN_ASSERT', 'WORK_ASSERT', 'ACCEPT_ASSERT', 'COUNTER_ASSERT']
            task_types = ['security', 'docs', 'migration']
            i = 0
            for state in states:
                for tt in task_types:
                    for rep in range(5):
                        i += 1
                        # Only ~33% match (1 of 3 task types matches)
                        match = (tt == 'security')
                        chunks.append(_make_chunk(
                            f'c{i}', state=state, task_type=tt,
                            outcome='approve' if match else 'correct',
                            posterior_prediction='approve',
                            human_response=f'Response {i}',
                        ))

            db_path = _seed_db(tmpdir, chunks)
            conn = open_proxy_db(db_path)
            result = go_no_go_assessment(conn)
            conn.close()

            self.assertLess(result.action_match_rate, 0.6)
            self.assertEqual(result.verdict, 'NO_GO')

    def test_verdict_investigate(self):
        """When action match between 60-70%, verdict is INVESTIGATE."""
        from projects.POC.orchestrator.proxy_metrics import go_no_go_assessment

        with tempfile.TemporaryDirectory() as tmpdir:
            chunks = []
            states = ['PLAN_ASSERT', 'WORK_ASSERT', 'ACCEPT_ASSERT', 'COUNTER_ASSERT']
            task_types = ['security', 'docs', 'migration']
            i = 0
            for state in states:
                for tt in task_types:
                    for rep in range(5):
                        i += 1
                        # ~65% match rate: match 2 of 3 task types, miss 1/3
                        if tt == 'migration' and rep < 4:
                            outcome = 'correct'  # mismatch
                        else:
                            outcome = 'approve'  # match
                        chunks.append(_make_chunk(
                            f'c{i}', state=state, task_type=tt,
                            outcome=outcome,
                            posterior_prediction='approve',
                            human_response=f'Response {i}',
                        ))

            db_path = _seed_db(tmpdir, chunks)
            conn = open_proxy_db(db_path)
            result = go_no_go_assessment(conn)
            conn.close()

            self.assertGreaterEqual(result.action_match_rate, 0.6)
            self.assertLess(result.action_match_rate, 0.7)
            self.assertEqual(result.verdict, 'INVESTIGATE')

    def test_verdict_insufficient_when_not_enough_data(self):
        """When sample < 50, verdict is INSUFFICIENT regardless of match rate."""
        from projects.POC.orchestrator.proxy_metrics import go_no_go_assessment

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, self._make_diverse_chunks())  # 12 chunks
            conn = open_proxy_db(db_path)
            result = go_no_go_assessment(conn)
            conn.close()

            self.assertEqual(result.verdict, 'INSUFFICIENT')


# ── Report Generation ────────────────────────────────────────────────────────

class TestEvaluationReport(unittest.TestCase):
    """generate_report() aggregates all metrics into a structured report."""

    def test_report_contains_all_metrics(self):
        from projects.POC.orchestrator.proxy_metrics import generate_report

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [
                _make_chunk('c1', outcome='approve', posterior_prediction='approve',
                            prior_prediction='approve', human_response='OK'),
            ])
            conn = open_proxy_db(db_path)
            report = generate_report(conn)
            conn.close()

            self.assertIn('action_match', report)
            self.assertIn('prior_calibration', report)
            self.assertIn('surprise_calibration', report)
            self.assertIn('go_no_go', report)

    def test_report_as_text(self):
        from projects.POC.orchestrator.proxy_metrics import generate_report

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [
                _make_chunk('c1', outcome='approve', posterior_prediction='approve',
                            prior_prediction='approve', human_response='OK'),
            ])
            conn = open_proxy_db(db_path)
            report = generate_report(conn)
            conn.close()

            text = report['text']
            self.assertIn('Action Match Rate', text)
            self.assertIn('Prior Calibration', text)
            self.assertIn('Surprise Calibration', text)
            self.assertIn('Go/No-Go', text)


if __name__ == '__main__':
    unittest.main()
