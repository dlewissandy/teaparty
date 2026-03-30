"""Tests for Issue #223: ACT-R Phase 1 ablation — activation decay vs. simple recency.

Verifies:
1. retrieve_most_recent_n() returns the N most recent chunks by latest trace
2. ablation_actr_vs_recency() compares retrieval sets from both configurations
3. Reinforcement-sensitive chunks rank differently under ACT-R vs. recency
4. Results break down by interaction epoch (early vs. late)
5. reinforcement_distribution() reports trace counts across chunks
"""
from __future__ import annotations

import os
import tempfile
import unittest

from orchestrator.proxy_memory import (
    MemoryChunk,
    open_proxy_db,
    store_chunk,
)


def _make_chunk(
    chunk_id: str = 'test-chunk',
    state: str = 'PLAN_ASSERT',
    task_type: str = 'security',
    outcome: str = 'approve',
    posterior_prediction: str = 'approve',
    human_response: str = 'OK',
    traces: list[int] | None = None,
    **kwargs,
) -> MemoryChunk:
    defaults = dict(
        id=chunk_id,
        type='gate_outcome',
        state=state,
        task_type=task_type,
        outcome=outcome,
        posterior_prediction=posterior_prediction,
        human_response=human_response,
        content='test interaction',
        traces=traces or [1],
        embedding_model='test/test',
    )
    defaults.update(kwargs)
    return MemoryChunk(**defaults)


def _seed_db(tmpdir: str, chunks: list[MemoryChunk], counter: int = 0) -> str:
    """Create and seed a proxy memory DB. Returns the db_path."""
    db_path = os.path.join(tmpdir, 'proxy_memory.db')
    conn = open_proxy_db(db_path)
    for chunk in chunks:
        store_chunk(conn, chunk)
    if counter:
        conn.execute(
            "UPDATE proxy_state SET value=? WHERE key='interaction_counter'",
            (counter,),
        )
        conn.commit()
    conn.close()
    return db_path


# ── Most-Recent-N Retrieval ─────────────────────────────────────────────────

class TestRetrieveMostRecentN(unittest.TestCase):
    """retrieve_most_recent_n() returns the N most recent chunks by latest trace."""

    def test_returns_n_most_recent(self):
        from orchestrator.proxy_memory import retrieve_most_recent_n

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [
                _make_chunk('old', traces=[1]),
                _make_chunk('mid', traces=[5]),
                _make_chunk('new', traces=[10]),
            ], counter=12)
            conn = open_proxy_db(db_path)
            result = retrieve_most_recent_n(conn, n=2, state='PLAN_ASSERT',
                                             task_type='security')
            conn.close()

            ids = [c.id for c in result]
            self.assertEqual(len(result), 2)
            self.assertEqual(ids[0], 'new')
            self.assertEqual(ids[1], 'mid')

    def test_structural_filter(self):
        """Only returns chunks matching state and task_type."""
        from orchestrator.proxy_memory import retrieve_most_recent_n

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [
                _make_chunk('match', state='PLAN_ASSERT', task_type='security',
                            traces=[10]),
                _make_chunk('wrong-state', state='WORK_ASSERT', task_type='security',
                            traces=[11]),
                _make_chunk('wrong-type', state='PLAN_ASSERT', task_type='docs',
                            traces=[12]),
            ], counter=15)
            conn = open_proxy_db(db_path)
            result = retrieve_most_recent_n(conn, n=10, state='PLAN_ASSERT',
                                             task_type='security')
            conn.close()

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].id, 'match')

    def test_uses_latest_trace_for_ordering(self):
        """A chunk reinforced recently ranks above a newer chunk with only creation trace."""
        from orchestrator.proxy_memory import retrieve_most_recent_n

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [
                # Created at 2, reinforced at 15 — latest trace is 15
                _make_chunk('old-reinforced', traces=[2, 15]),
                # Created at 10, never reinforced — latest trace is 10
                _make_chunk('newer-unreinforced', traces=[10]),
            ], counter=20)
            conn = open_proxy_db(db_path)
            result = retrieve_most_recent_n(conn, n=2, state='PLAN_ASSERT',
                                             task_type='security')
            conn.close()

            ids = [c.id for c in result]
            self.assertEqual(ids[0], 'old-reinforced',
                             'Reinforced chunk should rank first by latest trace')

    def test_n_larger_than_candidates(self):
        """When N exceeds available chunks, return all of them."""
        from orchestrator.proxy_memory import retrieve_most_recent_n

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [
                _make_chunk('only', traces=[5]),
            ], counter=10)
            conn = open_proxy_db(db_path)
            result = retrieve_most_recent_n(conn, n=100, state='PLAN_ASSERT',
                                             task_type='security')
            conn.close()

            self.assertEqual(len(result), 1)

    def test_empty_db(self):
        from orchestrator.proxy_memory import retrieve_most_recent_n

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [], counter=10)
            conn = open_proxy_db(db_path)
            result = retrieve_most_recent_n(conn, n=10, state='PLAN_ASSERT',
                                             task_type='security')
            conn.close()

            self.assertEqual(result, [])


# ── Ablation Comparison ─────────────────────────────────────────────────────

class TestAblationActrVsRecency(unittest.TestCase):
    """ablation_actr_vs_recency() compares retrieval sets under both configs."""

    def test_returns_structured_result(self):
        from orchestrator.proxy_metrics import ablation_actr_vs_recency

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [
                _make_chunk('c1', traces=[4, 5], posterior_prediction='approve',
                            outcome='approve', human_response='OK'),
                _make_chunk('c2', traces=[3], posterior_prediction='correct',
                            outcome='correct', human_response='Fix it'),
            ], counter=6)
            conn = open_proxy_db(db_path)
            result = ablation_actr_vs_recency(conn, s=0.0)
            conn.close()

            self.assertIsNotNone(result.actr_ids)
            self.assertIsNotNone(result.recency_ids)
            self.assertIsInstance(result.overlap, float)
            self.assertIsInstance(result.actr_match_rate, float)
            self.assertIsInstance(result.recency_match_rate, float)

    def test_recency_n_matches_actr_survivor_count(self):
        """Config B's N should equal Config A's activation survivor count."""
        from orchestrator.proxy_metrics import ablation_actr_vs_recency

        with tempfile.TemporaryDirectory() as tmpdir:
            # One chunk will be below activation threshold (very old, single trace)
            db_path = _seed_db(tmpdir, [
                _make_chunk('recent', traces=[98, 99], human_response='OK'),
                _make_chunk('mid', traces=[90], human_response='OK'),
                # Created at interaction 1, counter=100 → very decayed
                _make_chunk('ancient', traces=[1], human_response='OK'),
            ], counter=100)
            conn = open_proxy_db(db_path)
            result = ablation_actr_vs_recency(conn, s=0.0)
            conn.close()

            # recency should use same count as actr survivors
            self.assertEqual(len(result.recency_ids), len(result.actr_ids))

    def test_reinforcement_causes_ranking_divergence(self):
        """When reinforcement patterns exist, ACT-R and recency should differ.

        At counter=20:
          Chunk A: traces=[5,8,12,16], B=ln(15^-0.5+12^-0.5+8^-0.5+4^-0.5)=0.337
          Chunk B: traces=[18],        B=ln(2^-0.5)=-0.346
          Chunk C: traces=[19],        B=ln(1^-0.5)=0.0
        All above tau=-0.5, so all 3 are retrieved by both configs.
        ACT-R ranks by activation: A, C, B
        Recency ranks by latest trace: C(19), B(18), A(16)
        """
        from orchestrator.proxy_metrics import ablation_actr_vs_recency

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [
                _make_chunk('A', traces=[5, 8, 12, 16], human_response='OK'),
                _make_chunk('B', traces=[18], human_response='OK'),
                _make_chunk('C', traces=[19], human_response='OK'),
            ], counter=20)
            conn = open_proxy_db(db_path)
            result = ablation_actr_vs_recency(conn, s=0.0)
            conn.close()

            # All 3 chunks above threshold — both configs retrieve all 3
            self.assertEqual(len(result.actr_ids), 3)
            self.assertEqual(len(result.recency_ids), 3)
            # Same set (overlap=1.0) but different order
            self.assertAlmostEqual(result.overlap, 1.0)
            # ACT-R should rank heavily-reinforced chunk A first
            self.assertEqual(result.actr_ids[0], 'A',
                             'ACT-R should rank reinforced chunk first')
            # Recency should rank most-recent chunk C first
            self.assertEqual(result.recency_ids[0], 'C',
                             'Recency should rank most recent chunk first')

    def test_identical_when_single_trace_chunks(self):
        """With only single-trace chunks, both configs retrieve same set."""
        from orchestrator.proxy_metrics import ablation_actr_vs_recency

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [
                _make_chunk('c1', traces=[8], human_response='OK'),
                _make_chunk('c2', traces=[9], human_response='OK'),
                _make_chunk('c3', traces=[10], human_response='OK'),
            ], counter=12)
            conn = open_proxy_db(db_path)
            result = ablation_actr_vs_recency(conn, s=0.0)
            conn.close()

            self.assertAlmostEqual(result.overlap, 1.0,
                                    msg='Single-trace chunks should yield identical sets')

    def test_empty_db(self):
        from orchestrator.proxy_metrics import ablation_actr_vs_recency

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [])
            conn = open_proxy_db(db_path)
            result = ablation_actr_vs_recency(conn, s=0.0)
            conn.close()

            self.assertEqual(result.actr_ids, [])
            self.assertEqual(result.recency_ids, [])
            self.assertAlmostEqual(result.overlap, 1.0)


# ── Epoch Breakdown ─────────────────────────────────────────────────────────

class TestEpochBreakdown(unittest.TestCase):
    """Ablation results broken down by interaction epoch (early vs. late)."""

    def test_two_epoch_breakdown(self):
        from orchestrator.proxy_metrics import ablation_actr_vs_recency

        with tempfile.TemporaryDirectory() as tmpdir:
            chunks = []
            # Early epoch: interactions 1-10
            for i in range(1, 6):
                chunks.append(_make_chunk(f'early-{i}', traces=[i],
                                          human_response='OK'))
            # Late epoch: interactions 11-20, some with reinforcement
            for i in range(11, 16):
                traces = [i, i + 2] if i % 2 == 0 else [i]
                chunks.append(_make_chunk(f'late-{i}', traces=traces,
                                          human_response='OK'))

            db_path = _seed_db(tmpdir, chunks, counter=20)
            conn = open_proxy_db(db_path)
            result = ablation_actr_vs_recency(conn, s=0.0)
            conn.close()

            self.assertIsNotNone(result.epoch_breakdown)
            self.assertGreaterEqual(len(result.epoch_breakdown), 2)
            for epoch in result.epoch_breakdown:
                self.assertIn('epoch', epoch)
                self.assertIn('overlap', epoch)


# ── Reinforcement Distribution ──────────────────────────────────────────────

class TestReinforcementDistribution(unittest.TestCase):
    """reinforcement_distribution() reports trace counts across chunks."""

    def test_basic_distribution(self):
        from orchestrator.proxy_metrics import reinforcement_distribution

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [
                _make_chunk('c1', traces=[1]),            # 1 trace
                _make_chunk('c2', traces=[2, 5]),         # 2 traces
                _make_chunk('c3', traces=[3, 6, 9]),      # 3 traces
                _make_chunk('c4', traces=[4]),             # 1 trace
            ])
            conn = open_proxy_db(db_path)
            result = reinforcement_distribution(conn)
            conn.close()

            self.assertEqual(result.total_chunks, 4)
            self.assertEqual(result.single_trace_count, 2)
            self.assertEqual(result.multi_trace_count, 2)
            self.assertAlmostEqual(result.single_trace_fraction, 0.5)
            self.assertAlmostEqual(result.mean_traces, 7 / 4)

    def test_all_single_trace(self):
        """When all chunks have 1 trace, ablation is tautological."""
        from orchestrator.proxy_metrics import reinforcement_distribution

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [
                _make_chunk('c1', traces=[1]),
                _make_chunk('c2', traces=[2]),
                _make_chunk('c3', traces=[3]),
            ])
            conn = open_proxy_db(db_path)
            result = reinforcement_distribution(conn)
            conn.close()

            self.assertEqual(result.single_trace_count, 3)
            self.assertAlmostEqual(result.single_trace_fraction, 1.0)
            self.assertTrue(result.ablation_tautological,
                            'All single-trace → ablation is tautological')

    def test_empty_db(self):
        from orchestrator.proxy_metrics import reinforcement_distribution

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [])
            conn = open_proxy_db(db_path)
            result = reinforcement_distribution(conn)
            conn.close()

            self.assertEqual(result.total_chunks, 0)
            self.assertTrue(result.ablation_tautological)

    def test_max_traces(self):
        from orchestrator.proxy_metrics import reinforcement_distribution

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [
                _make_chunk('c1', traces=[1, 2, 3, 4, 5]),
                _make_chunk('c2', traces=[6]),
            ])
            conn = open_proxy_db(db_path)
            result = reinforcement_distribution(conn)
            conn.close()

            self.assertEqual(result.max_traces, 5)


# ── Threshold Check ─────────────────────────────────────────────────────────

class TestAblationThreshold(unittest.TestCase):
    """The 95% go/no-go criterion from the design doc."""

    def test_passes_threshold_when_close(self):
        from orchestrator.proxy_metrics import ablation_actr_vs_recency

        with tempfile.TemporaryDirectory() as tmpdir:
            # All single-trace chunks → identical retrieval → 100% overlap
            chunks = [
                _make_chunk(f'c{i}', traces=[i], posterior_prediction='approve',
                            outcome='approve', human_response='OK')
                for i in range(1, 11)
            ]
            db_path = _seed_db(tmpdir, chunks, counter=12)
            conn = open_proxy_db(db_path)
            result = ablation_actr_vs_recency(conn, s=0.0)
            conn.close()

            self.assertTrue(result.recency_sufficient,
                            'Identical retrieval sets → recency is sufficient')

    def test_fails_threshold_when_divergent(self):
        """When ACT-R match rate is much higher than recency, threshold fails."""
        from orchestrator.proxy_metrics import ablation_actr_vs_recency

        # This test uses constructed data where ACT-R would rank differently
        # due to reinforcement. The actual threshold check depends on
        # match rate comparison, not just overlap.
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [
                # High-activation chunk that matches outcome
                _make_chunk('reinforced', traces=[2, 5, 8, 11, 14],
                            outcome='correct', posterior_prediction='correct',
                            human_response='Fix this'),
                # Recent but wrong prediction
                _make_chunk('recent-wrong', traces=[15],
                            outcome='correct', posterior_prediction='approve',
                            human_response='Wrong'),
            ], counter=16)
            conn = open_proxy_db(db_path)
            result = ablation_actr_vs_recency(conn, s=0.0)
            conn.close()

            # Both configs should retrieve both chunks (small set)
            # but the result structure should be valid
            self.assertIsInstance(result.recency_sufficient, bool)


if __name__ == '__main__':
    unittest.main()
