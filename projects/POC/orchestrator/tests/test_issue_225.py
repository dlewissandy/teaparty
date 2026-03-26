"""Tests for Issue #225: Composite scoring vs. activation-only and similarity-only retrieval.

The ablation compares retrieval quality under three weight configurations:
  A (composite):        activation_weight=0.5, semantic_weight=0.5
  B (activation-only):  activation_weight=1.0, semantic_weight=0.0
  C (similarity-only):  activation_weight=0.0, semantic_weight=1.0

Tests verify that:
1. retrieve_chunks() accepts and respects activation_weight / semantic_weight
2. Activation-only retrieval ranks purely by activation (ignores embeddings)
3. Similarity-only retrieval ranks purely by similarity (ignores activation)
4. The ablation harness runs all three configs and returns structured results
5. Results are deterministic when noise is disabled (s=0.0)
"""
from __future__ import annotations

import os
import tempfile
import unittest

from projects.POC.orchestrator.proxy_memory import (
    MemoryChunk,
    open_proxy_db,
    store_chunk,
    retrieve_chunks,
    composite_score,
    base_level_activation,
    normalize_activation,
    RETRIEVAL_THRESHOLD,
)


def _make_chunk(
    chunk_id: str = 'test-chunk',
    state: str = 'PLAN_ASSERT',
    task_type: str = 'security',
    outcome: str = 'approve',
    traces: list[int] | None = None,
    **kwargs,
) -> MemoryChunk:
    defaults = dict(
        id=chunk_id,
        type='gate_outcome',
        state=state,
        task_type=task_type,
        outcome=outcome,
        content='test interaction content',
        traces=traces or [1],
        embedding_model='test/test',
    )
    defaults.update(kwargs)
    return MemoryChunk(**defaults)


def _make_db(tmpdir: str, chunks: list[MemoryChunk], counter: int = 20):
    """Seed a proxy memory DB with chunks and return the connection."""
    db_path = os.path.join(tmpdir, '.proxy-memory.db')
    conn = open_proxy_db(db_path)
    for chunk in chunks:
        store_chunk(conn, chunk)
    conn.execute(
        "UPDATE proxy_state SET value=? WHERE key='interaction_counter'",
        (counter,),
    )
    conn.commit()
    return conn, db_path


class TestRetrieveChunksWeightParams(unittest.TestCase):
    """retrieve_chunks() must accept and pass through weight parameters."""

    def test_activation_weight_and_semantic_weight_accepted(self):
        """retrieve_chunks() accepts activation_weight and semantic_weight kwargs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            conn, _ = _make_db(tmpdir, [_make_chunk(traces=[18])])
            # Should not raise TypeError for unexpected keyword arguments
            results = retrieve_chunks(
                conn,
                current_interaction=20,
                activation_weight=1.0,
                semantic_weight=0.0,
                s=0.0,
            )
            conn.close()
            self.assertEqual(len(results), 1)

    def test_activation_only_ignores_embeddings(self):
        """With activation_weight=1.0, semantic_weight=0.0, embeddings do not
        affect ranking. A chunk with high activation but no embedding match
        should rank above a chunk with low activation but perfect embedding match."""
        # Chunk A: high activation (recent, multiple traces), no embeddings
        chunk_a = _make_chunk(
            chunk_id='high-activation',
            traces=[15, 17, 19],
            embedding_situation=None,
        )
        # Chunk B: lower activation (fewer recent traces), strong embeddings
        chunk_b = _make_chunk(
            chunk_id='high-similarity',
            traces=[19],
            embedding_situation=[1.0, 0.0, 0.0],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            conn, _ = _make_db(tmpdir, [chunk_a, chunk_b])

            context_embeddings = {'situation': [1.0, 0.0, 0.0]}

            results = retrieve_chunks(
                conn,
                current_interaction=20,
                context_embeddings=context_embeddings,
                activation_weight=1.0,
                semantic_weight=0.0,
                s=0.0,
            )
            conn.close()

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].id, 'high-activation',
                             'Activation-only should rank high-activation chunk first')

    def test_similarity_only_ignores_activation(self):
        """With activation_weight=0.0, semantic_weight=1.0, activation does not
        affect ranking. A chunk with strong embedding match but low activation
        should rank above a chunk with high activation but no embedding match."""
        # Chunk A: high activation, no embeddings
        chunk_a = _make_chunk(
            chunk_id='high-activation',
            traces=[15, 17, 19],
            embedding_situation=None,
        )
        # Chunk B: lower activation, strong embeddings
        chunk_b = _make_chunk(
            chunk_id='high-similarity',
            traces=[19],
            embedding_situation=[1.0, 0.0, 0.0],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            conn, _ = _make_db(tmpdir, [chunk_a, chunk_b])

            context_embeddings = {'situation': [1.0, 0.0, 0.0]}

            results = retrieve_chunks(
                conn,
                current_interaction=20,
                context_embeddings=context_embeddings,
                activation_weight=0.0,
                semantic_weight=1.0,
                s=0.0,
            )
            conn.close()

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].id, 'high-similarity',
                             'Similarity-only should rank high-similarity chunk first')

    def test_composite_blends_both_signals(self):
        """With composite scoring, semantic similarity breaks an activation tie.
        Two chunks with identical activation — one has embeddings, one doesn't.
        The one with embeddings should rank higher under composite scoring."""
        # Both chunks have identical activation
        chunk_a = _make_chunk(
            chunk_id='no-embedding',
            traces=[18, 19],
            embedding_situation=None,
        )
        chunk_b = _make_chunk(
            chunk_id='has-embedding',
            traces=[18, 19],
            embedding_situation=[1.0, 0.0, 0.0],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            conn, _ = _make_db(tmpdir, [chunk_a, chunk_b])

            context_embeddings = {'situation': [1.0, 0.0, 0.0]}

            results = retrieve_chunks(
                conn,
                current_interaction=20,
                context_embeddings=context_embeddings,
                activation_weight=0.5,
                semantic_weight=0.5,
                s=0.0,
            )
            conn.close()

            self.assertEqual(len(results), 2)
            self.assertEqual(results[0].id, 'has-embedding',
                             'Composite scoring: semantic similarity breaks activation tie')


class TestAblationHarness(unittest.TestCase):
    """The ablation harness runs all three configurations on the same data."""

    def test_harness_returns_three_configs(self):
        """run_scoring_ablation() returns results for all three configurations."""
        from projects.POC.orchestrator.proxy_memory import run_scoring_ablation

        chunks = [
            _make_chunk(chunk_id=f'c{i}', traces=[i * 2 + 1], outcome='approve',
                        embedding_situation=[float(i % 2), float((i + 1) % 2), 0.0])
            for i in range(5)
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            conn, _ = _make_db(tmpdir, chunks, counter=20)

            results = run_scoring_ablation(
                conn,
                state='PLAN_ASSERT',
                task_type='security',
                context_embeddings={'situation': [1.0, 0.0, 0.0]},
                current_interaction=20,
            )
            conn.close()

        self.assertIn('composite', results)
        self.assertIn('activation_only', results)
        self.assertIn('similarity_only', results)

    def test_harness_configs_produce_different_rankings(self):
        """Different weight configs should (generally) produce different rankings
        when activation and similarity signals diverge."""
        from projects.POC.orchestrator.proxy_memory import run_scoring_ablation

        # Chunk with high activation, low similarity
        high_act = _make_chunk(
            chunk_id='high-act', traces=[15, 17, 19],
            embedding_situation=[0.0, 0.0, 1.0],
        )
        # Chunk with lower activation, high similarity
        high_sim = _make_chunk(
            chunk_id='high-sim', traces=[19],
            embedding_situation=[1.0, 0.0, 0.0],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            conn, _ = _make_db(tmpdir, [high_act, high_sim])

            results = run_scoring_ablation(
                conn,
                state='PLAN_ASSERT',
                task_type='security',
                context_embeddings={'situation': [1.0, 0.0, 0.0]},
                current_interaction=20,
            )
            conn.close()

        act_order = [c.id for c in results['activation_only']]
        sim_order = [c.id for c in results['similarity_only']]

        self.assertEqual(act_order[0], 'high-act',
                         'Activation-only should rank high-act first')
        self.assertEqual(sim_order[0], 'high-sim',
                         'Similarity-only should rank high-sim first')
        self.assertNotEqual(act_order, sim_order,
                            'Activation-only and similarity-only should differ')

    def test_harness_deterministic_with_no_noise(self):
        """Results should be identical across runs when noise is disabled."""
        from projects.POC.orchestrator.proxy_memory import run_scoring_ablation

        chunks = [
            _make_chunk(chunk_id=f'c{i}', traces=[i + 1],
                        embedding_situation=[float(i) / 5, 1.0 - float(i) / 5, 0.0])
            for i in range(5)
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            conn, _ = _make_db(tmpdir, chunks, counter=20)

            r1 = run_scoring_ablation(
                conn, state='PLAN_ASSERT', task_type='security',
                context_embeddings={'situation': [1.0, 0.0, 0.0]},
                current_interaction=20,
            )
            r2 = run_scoring_ablation(
                conn, state='PLAN_ASSERT', task_type='security',
                context_embeddings={'situation': [1.0, 0.0, 0.0]},
                current_interaction=20,
            )
            conn.close()

        for config in ('composite', 'activation_only', 'similarity_only'):
            ids_1 = [c.id for c in r1[config]]
            ids_2 = [c.id for c in r2[config]]
            self.assertEqual(ids_1, ids_2,
                             f'{config} rankings should be deterministic with s=0.0')

    def test_harness_at_multiple_checkpoints(self):
        """run_scoring_ablation() supports checkpoint parameter to evaluate
        at a specific interaction count (for multi-checkpoint comparison)."""
        from projects.POC.orchestrator.proxy_memory import run_scoring_ablation

        # Chunk visible at interaction 10 (trace=5, activation at N=10 is fine)
        early = _make_chunk(chunk_id='early', traces=[5],
                            embedding_situation=[1.0, 0.0, 0.0])
        # Chunk only created at interaction 18 — not visible at checkpoint 10
        # if we filter by creation time, but visible at checkpoint 20
        late = _make_chunk(chunk_id='late', traces=[18],
                           embedding_situation=[1.0, 0.0, 0.0])

        with tempfile.TemporaryDirectory() as tmpdir:
            conn, _ = _make_db(tmpdir, [early, late], counter=20)

            # At checkpoint 10, the 'late' chunk's trace (18) is in the future
            # relative to current_interaction=10, so age = max(10-18, 1) = 1
            # Both chunks pass activation filter, but activation values differ
            results_10 = run_scoring_ablation(
                conn, state='PLAN_ASSERT', task_type='security',
                context_embeddings={'situation': [1.0, 0.0, 0.0]},
                current_interaction=10,
            )
            results_20 = run_scoring_ablation(
                conn, state='PLAN_ASSERT', task_type='security',
                context_embeddings={'situation': [1.0, 0.0, 0.0]},
                current_interaction=20,
            )
            conn.close()

        # Both checkpoints should return results (the harness works at any N)
        self.assertGreater(len(results_10['composite']), 0)
        self.assertGreater(len(results_20['composite']), 0)


if __name__ == '__main__':
    unittest.main()
