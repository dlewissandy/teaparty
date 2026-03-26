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
    """The ablation harness performs leave-one-out evaluation and reports
    action match rate at specified checkpoints."""

    def _make_history(self, n: int = 10):
        """Create a chronological sequence of chunks with divergent signals.

        Odd-indexed chunks: outcome='approve', embeddings point toward [1,0,0]
        Even-indexed chunks: outcome='correct', embeddings point toward [0,1,0]

        This creates a scenario where embedding similarity can predict outcome
        (similar embeddings → same outcome) while activation alone cannot
        (most recent chunk may have either outcome).
        """
        chunks = []
        for i in range(n):
            outcome = 'approve' if i % 2 == 1 else 'correct'
            emb = [1.0, 0.0, 0.0] if i % 2 == 1 else [0.0, 1.0, 0.0]
            chunks.append(_make_chunk(
                chunk_id=f'c{i}',
                traces=[i + 1],
                outcome=outcome,
                embedding_situation=emb,
            ))
        return chunks

    def test_returns_three_configs_with_match_rates(self):
        """run_scoring_ablation() returns AblationResult with all three configs
        and numeric match rates."""
        from projects.POC.orchestrator.proxy_memory import run_scoring_ablation

        chunks = self._make_history(6)

        with tempfile.TemporaryDirectory() as tmpdir:
            conn, _ = _make_db(tmpdir, chunks, counter=10)
            result = run_scoring_ablation(conn, checkpoints=[6])
            conn.close()

        self.assertIn(6, result.checkpoints)
        cp = result.checkpoints[6]
        self.assertIn('composite', cp)
        self.assertIn('activation_only', cp)
        self.assertIn('similarity_only', cp)

        for config_name in ('composite', 'activation_only', 'similarity_only'):
            r = cp[config_name]
            self.assertEqual(r.config, config_name)
            self.assertEqual(r.checkpoint, 6)
            self.assertGreaterEqual(r.match_rate, 0.0)
            self.assertLessEqual(r.match_rate, 1.0)
            self.assertGreater(r.total, 0, f'{config_name} should evaluate at least one chunk')

    def test_multiple_checkpoints(self):
        """Ablation evaluates at multiple interaction counts."""
        from projects.POC.orchestrator.proxy_memory import run_scoring_ablation

        chunks = self._make_history(10)

        with tempfile.TemporaryDirectory() as tmpdir:
            conn, _ = _make_db(tmpdir, chunks, counter=15)
            result = run_scoring_ablation(conn, checkpoints=[4, 7, 10])
            conn.close()

        self.assertIn(4, result.checkpoints)
        self.assertIn(7, result.checkpoints)
        self.assertIn(10, result.checkpoints)

        # More data should mean more evaluations
        self.assertGreater(
            result.checkpoints[10]['composite'].total,
            result.checkpoints[4]['composite'].total,
            'More chunks should yield more evaluations',
        )

    def test_deterministic_results(self):
        """Ablation produces identical results across runs (noise disabled)."""
        from projects.POC.orchestrator.proxy_memory import run_scoring_ablation

        chunks = self._make_history(8)

        with tempfile.TemporaryDirectory() as tmpdir:
            conn, _ = _make_db(tmpdir, chunks, counter=12)
            r1 = run_scoring_ablation(conn, checkpoints=[8])
            r2 = run_scoring_ablation(conn, checkpoints=[8])
            conn.close()

        for config in ('composite', 'activation_only', 'similarity_only'):
            self.assertEqual(
                r1.checkpoints[8][config].match_rate,
                r2.checkpoints[8][config].match_rate,
                f'{config} match rate should be deterministic',
            )

    def test_similarity_only_leverages_embedding_signal(self):
        """When outcomes correlate with embedding similarity, similarity-only
        should achieve a non-zero match rate."""
        from projects.POC.orchestrator.proxy_memory import run_scoring_ablation

        chunks = self._make_history(10)

        with tempfile.TemporaryDirectory() as tmpdir:
            conn, _ = _make_db(tmpdir, chunks, counter=15)
            result = run_scoring_ablation(conn, checkpoints=[10])
            conn.close()

        sim = result.checkpoints[10]['similarity_only']
        self.assertGreater(sim.match_rate, 0.0,
                           'Similarity-only should leverage embedding signal')

    def test_summary_output(self):
        """summary() produces human-readable Markdown table."""
        from projects.POC.orchestrator.proxy_memory import run_scoring_ablation

        chunks = self._make_history(6)

        with tempfile.TemporaryDirectory() as tmpdir:
            conn, _ = _make_db(tmpdir, chunks, counter=10)
            result = run_scoring_ablation(conn, checkpoints=[6])
            conn.close()

        summary = result.summary()
        self.assertIn('Scoring Ablation Results', summary)
        self.assertIn('composite', summary)
        self.assertIn('activation_only', summary)
        self.assertIn('similarity_only', summary)
        self.assertIn('Match Rate', summary)

    def test_empty_db_returns_empty_result(self):
        """Ablation on empty DB returns empty checkpoints."""
        from projects.POC.orchestrator.proxy_memory import run_scoring_ablation

        with tempfile.TemporaryDirectory() as tmpdir:
            conn, _ = _make_db(tmpdir, [], counter=0)
            result = run_scoring_ablation(conn, checkpoints=[10])
            conn.close()

        self.assertEqual(result.checkpoints, {})

    def test_survivors_avg_reported(self):
        """Each checkpoint reports average survivor count from activation filter."""
        from projects.POC.orchestrator.proxy_memory import run_scoring_ablation

        chunks = self._make_history(6)

        with tempfile.TemporaryDirectory() as tmpdir:
            conn, _ = _make_db(tmpdir, chunks, counter=10)
            result = run_scoring_ablation(conn, checkpoints=[6])
            conn.close()

        for config in ('composite', 'activation_only', 'similarity_only'):
            r = result.checkpoints[6][config]
            self.assertGreaterEqual(r.survivors_avg, 0.0,
                                    f'{config} should report survivor count')


if __name__ == '__main__':
    unittest.main()
