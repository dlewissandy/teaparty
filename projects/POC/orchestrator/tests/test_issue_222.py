"""Tests for Issue #222: Multi-dimensional embeddings (5 vectors) vs single blended embedding ablation.

The ablation compares retrieval quality under two scoring configurations:
- Configuration A (current): 5 independent embeddings, composite_score averages across all dims
- Configuration B (ablation): 1 blended embedding from concatenated text, single cosine similarity

Tests verify:
1. blended_text() produces correct concatenation from chunk fields
2. single_composite_score() computes valid scores using one embedding
3. run_embedding_ablation() produces per-context retrieval comparison
4. The 95% threshold criterion from act-r-proxy-memory.md
5. Results are broken down by CfA state and task type
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
    human_response: str = 'Looks good',
    content: str = 'Review of security plan at PLAN_ASSERT gate',
    traces: list[int] | None = None,
    embedding_situation: list[float] | None = None,
    embedding_artifact: list[float] | None = None,
    embedding_stimulus: list[float] | None = None,
    embedding_response: list[float] | None = None,
    embedding_salience: list[float] | None = None,
    embedding_blended: list[float] | None = None,
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
        human_response=human_response,
        content=content,
        traces=traces or [1],
        embedding_model='test/test',
        embedding_situation=embedding_situation,
        embedding_artifact=embedding_artifact,
        embedding_stimulus=embedding_stimulus,
        embedding_response=embedding_response,
        embedding_salience=embedding_salience,
        embedding_blended=embedding_blended,
    )
    defaults.update(kwargs)
    return MemoryChunk(**defaults)


def _seed_db(tmpdir: str, chunks: list[MemoryChunk], counter: int = 10) -> str:
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


# ── blended_text ────────────────────────────────────────────────────────────

class TestBlendedText(unittest.TestCase):
    """blended_text() concatenates available chunk fields into a single string."""

    def test_concatenates_all_available_fields(self):
        from projects.POC.orchestrator.proxy_ablation import blended_text

        chunk = _make_chunk(
            state='PLAN_ASSERT',
            task_type='security',
            content='Full interaction text here',
            human_response='Add rollback strategy',
            prediction_delta='Missing safety mechanism changed prediction',
        )
        result = blended_text(chunk)

        self.assertIn('PLAN_ASSERT', result)
        self.assertIn('security', result)
        self.assertIn('Full interaction text here', result)
        self.assertIn('Add rollback strategy', result)
        self.assertIn('Missing safety mechanism', result)

    def test_handles_empty_fields(self):
        from projects.POC.orchestrator.proxy_ablation import blended_text

        chunk = _make_chunk(
            state='WORK_ASSERT',
            task_type='docs',
            content='Some content',
            human_response='',
            prediction_delta='',
        )
        result = blended_text(chunk)

        self.assertIn('WORK_ASSERT', result)
        self.assertIn('docs', result)
        self.assertIn('Some content', result)
        # Should not have empty sections cluttering the text
        self.assertTrue(len(result.strip()) > 0)

    def test_returns_nonempty_for_minimal_chunk(self):
        from projects.POC.orchestrator.proxy_ablation import blended_text

        chunk = _make_chunk(
            state='PLAN_ASSERT',
            task_type='',
            content='minimal',
            human_response='',
            prediction_delta='',
        )
        result = blended_text(chunk)
        self.assertTrue(len(result.strip()) > 0)


# ── single_composite_score ──────────────────────────────────────────────────

class TestSingleCompositeScore(unittest.TestCase):
    """single_composite_score uses one blended embedding instead of 5."""

    def test_produces_valid_score(self):
        from projects.POC.orchestrator.proxy_ablation import single_composite_score

        chunk = _make_chunk(
            traces=[8, 9],
            embedding_blended=[1.0, 0.0, 0.0],
        )
        context_blended = [1.0, 0.0, 0.0]

        score = single_composite_score(
            chunk, context_blended,
            current_interaction=10,
            b_min=-1.0, b_max=1.0,
            s=0.0,  # disable noise for determinism
        )
        self.assertIsInstance(score, float)

    def test_identical_embeddings_score_high(self):
        from projects.POC.orchestrator.proxy_ablation import single_composite_score

        vec = [1.0, 0.0, 0.5, 0.3]
        chunk = _make_chunk(traces=[9], embedding_blended=vec)

        score = single_composite_score(
            chunk, vec,
            current_interaction=10,
            b_min=0.0, b_max=0.0,  # single chunk → normalize to 0.5
            s=0.0,
        )
        # With identical embeddings, cosine similarity = 1.0
        # semantic component = 0.5 * 1.0 = 0.5
        # activation component = 0.5 * 0.5 = 0.25 (normalized to 0.5 when b_min==b_max)
        self.assertGreater(score, 0.5)

    def test_orthogonal_embeddings_score_lower(self):
        from projects.POC.orchestrator.proxy_ablation import single_composite_score

        chunk = _make_chunk(
            traces=[9],
            embedding_blended=[1.0, 0.0, 0.0],
        )
        context = [0.0, 1.0, 0.0]  # orthogonal

        score = single_composite_score(
            chunk, context,
            current_interaction=10,
            b_min=0.0, b_max=0.0,
            s=0.0,
        )
        # cosine similarity = 0, so semantic component = 0
        # Only activation contributes
        self.assertLess(score, 0.5)

    def test_none_blended_embedding_returns_activation_only(self):
        from projects.POC.orchestrator.proxy_ablation import single_composite_score

        chunk = _make_chunk(traces=[9], embedding_blended=None)

        score = single_composite_score(
            chunk, [1.0, 0.0],
            current_interaction=10,
            b_min=0.0, b_max=0.0,
            s=0.0,
        )
        # With no blended embedding, semantic component is 0
        # Score is purely from activation
        self.assertIsInstance(score, float)


# ── Ablation runner ─────────────────────────────────────────────────────────

class TestEmbeddingAblation(unittest.TestCase):
    """run_embedding_ablation() compares retrieval under both configurations."""

    def _make_ablation_chunks(self) -> list[MemoryChunk]:
        """Create chunks with both multi-dim and blended embeddings."""
        # Use simple orthogonal vectors so retrieval ranking is deterministic
        chunks = []
        states = ['PLAN_ASSERT', 'WORK_ASSERT']
        task_types = ['security', 'docs']

        i = 0
        for state in states:
            for tt in task_types:
                for rep in range(3):
                    i += 1
                    # Create embedding vectors with some variation
                    base = [float(i % 3), float(i % 5), float(i % 7)]
                    chunks.append(_make_chunk(
                        chunk_id=f'c{i}',
                        state=state,
                        task_type=tt,
                        outcome='approve' if rep < 2 else 'correct',
                        posterior_prediction='approve',
                        human_response=f'Response {i}',
                        traces=[i],
                        embedding_situation=base,
                        embedding_artifact=[x * 0.5 for x in base],
                        embedding_stimulus=[x * 0.3 for x in base],
                        embedding_response=[x * 0.7 for x in base],
                        embedding_salience=None,
                        embedding_blended=base,
                    ))
        return chunks

    def test_returns_result_with_required_fields(self):
        from projects.POC.orchestrator.proxy_ablation import (
            EmbeddingAblationResult,
            run_embedding_ablation,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            chunks = self._make_ablation_chunks()
            db_path = _seed_db(tmpdir, chunks, counter=20)
            conn = open_proxy_db(db_path)
            result = run_embedding_ablation(conn)
            conn.close()

            self.assertIsInstance(result, EmbeddingAblationResult)
            self.assertIsInstance(result.overall_retrieval_overlap, float)
            self.assertIsInstance(result.per_context, list)
            self.assertIsInstance(result.threshold_met, bool)
            self.assertIn(result.recommendation, ('SIMPLIFY', 'KEEP_MULTI_DIM'))

    def test_per_context_breakdown_by_state_and_task_type(self):
        from projects.POC.orchestrator.proxy_ablation import run_embedding_ablation

        with tempfile.TemporaryDirectory() as tmpdir:
            chunks = self._make_ablation_chunks()
            db_path = _seed_db(tmpdir, chunks, counter=20)
            conn = open_proxy_db(db_path)
            result = run_embedding_ablation(conn)
            conn.close()

            # Should have breakdown entries
            self.assertGreater(len(result.per_context), 0)

            # Each entry should have state and task_type
            for ctx in result.per_context:
                self.assertTrue(hasattr(ctx, 'state'))
                self.assertTrue(hasattr(ctx, 'task_type'))
                self.assertTrue(hasattr(ctx, 'n_interactions'))

    def test_threshold_95_percent(self):
        """When retrieval overlap >= 95%, recommendation is SIMPLIFY."""
        from projects.POC.orchestrator.proxy_ablation import (
            EmbeddingAblationResult,
            apply_threshold,
        )

        # Simulate a result with high overlap
        result = apply_threshold(overall_overlap=0.96)
        self.assertTrue(result.threshold_met)
        self.assertEqual(result.recommendation, 'SIMPLIFY')

    def test_threshold_below_95_percent(self):
        """When retrieval overlap < 95%, recommendation is KEEP_MULTI_DIM."""
        from projects.POC.orchestrator.proxy_ablation import apply_threshold

        result = apply_threshold(overall_overlap=0.80)
        self.assertFalse(result.threshold_met)
        self.assertEqual(result.recommendation, 'KEEP_MULTI_DIM')

    def test_empty_db_returns_insufficient(self):
        from projects.POC.orchestrator.proxy_ablation import run_embedding_ablation

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = _seed_db(tmpdir, [], counter=0)
            conn = open_proxy_db(db_path)
            result = run_embedding_ablation(conn)
            conn.close()

            self.assertEqual(result.recommendation, 'INSUFFICIENT')
            self.assertEqual(len(result.per_context), 0)


# ── DB schema support ───────────────────────────────────────────────────────

class TestBlendedEmbeddingStorage(unittest.TestCase):
    """The embedding_blended column is stored and retrieved correctly."""

    def test_store_and_retrieve_blended_embedding(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, 'test.db')
            conn = open_proxy_db(db_path)

            vec = [0.1, 0.2, 0.3, 0.4]
            chunk = _make_chunk(chunk_id='bl1', embedding_blended=vec)
            store_chunk(conn, chunk)

            from projects.POC.orchestrator.proxy_memory import get_chunk
            loaded = get_chunk(conn, 'bl1')
            conn.close()

            self.assertEqual(loaded.embedding_blended, vec)

    def test_blended_embedding_none_when_absent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, 'test.db')
            conn = open_proxy_db(db_path)

            chunk = _make_chunk(chunk_id='bl2', embedding_blended=None)
            store_chunk(conn, chunk)

            from projects.POC.orchestrator.proxy_memory import get_chunk
            loaded = get_chunk(conn, 'bl2')
            conn.close()

            self.assertIsNone(loaded.embedding_blended)


# ── Populate blended embeddings ─────────────────────────────────────────────

class TestPopulateBlendedEmbeddings(unittest.TestCase):
    """populate_blended_embeddings() backfills chunks that lack blended vectors."""

    def test_populates_missing_blended_embeddings(self):
        from unittest.mock import patch
        from projects.POC.orchestrator.proxy_ablation import populate_blended_embeddings

        with tempfile.TemporaryDirectory() as tmpdir:
            # Chunks without blended embeddings
            chunks = [
                _make_chunk(chunk_id='p1', embedding_blended=None),
                _make_chunk(chunk_id='p2', embedding_blended=None),
            ]
            db_path = _seed_db(tmpdir, chunks)
            conn = open_proxy_db(db_path)

            mock_embed = lambda text, conn=None, provider=None, model=None: [0.1, 0.2, 0.3]
            with patch('projects.POC.scripts.memory_indexer.detect_provider', return_value=('test', 'test')), \
                 patch('projects.POC.scripts.memory_indexer.try_embed', side_effect=mock_embed):
                updated = populate_blended_embeddings(conn)

            self.assertEqual(updated, 2)

            from projects.POC.orchestrator.proxy_memory import get_chunk
            loaded = get_chunk(conn, 'p1')
            self.assertIsNotNone(loaded.embedding_blended)
            self.assertEqual(loaded.embedding_blended, [0.1, 0.2, 0.3])
            conn.close()

    def test_skips_chunks_that_already_have_blended(self):
        from unittest.mock import patch
        from projects.POC.orchestrator.proxy_ablation import populate_blended_embeddings

        with tempfile.TemporaryDirectory() as tmpdir:
            chunks = [
                _make_chunk(chunk_id='p3', embedding_blended=[0.5, 0.5]),
            ]
            db_path = _seed_db(tmpdir, chunks)
            conn = open_proxy_db(db_path)

            # Should not be called since all chunks already have blended
            updated = populate_blended_embeddings(conn)

            self.assertEqual(updated, 0)
            conn.close()


# ── Report generation ───────────────────────────────────────────────────────

class TestAblationReport(unittest.TestCase):
    """generate_ablation_report() produces readable text output."""

    def test_report_contains_key_sections(self):
        from projects.POC.orchestrator.proxy_ablation import (
            AblationContextResult,
            EmbeddingAblationResult,
            generate_ablation_report,
        )

        result = EmbeddingAblationResult(
            overall_retrieval_overlap=0.85,
            per_context=[
                AblationContextResult(
                    state='PLAN_ASSERT', task_type='security',
                    n_interactions=5, mean_overlap=0.90,
                ),
                AblationContextResult(
                    state='WORK_ASSERT', task_type='docs',
                    n_interactions=3, mean_overlap=0.80,
                ),
            ],
            threshold_met=False,
            recommendation='KEEP_MULTI_DIM',
        )
        text = generate_ablation_report(result)

        self.assertIn('Multi-Dimensional vs Single Blended', text)
        self.assertIn('85.0%', text)
        self.assertIn('KEEP_MULTI_DIM', text)
        self.assertIn('PLAN_ASSERT', text)
        self.assertIn('WORK_ASSERT', text)


# ── record_interaction computes blended embedding ───────────────────────────

class TestRecordInteractionBlended(unittest.TestCase):
    """record_interaction() automatically computes embedding_blended."""

    def test_new_chunk_gets_blended_embedding(self):
        from unittest.mock import patch
        from projects.POC.orchestrator.proxy_memory import record_interaction, get_chunk

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, 'test.db')
            conn = open_proxy_db(db_path)

            call_count = [0]

            def mock_embed(text, conn=None, provider=None, model=None):
                call_count[0] += 1
                return [float(call_count[0])] * 3

            with patch('projects.POC.scripts.memory_indexer.detect_provider', return_value=('test', 'test')), \
                 patch('projects.POC.scripts.memory_indexer.try_embed', side_effect=mock_embed):
                chunk = record_interaction(
                    conn,
                    interaction_type='gate_outcome',
                    state='PLAN_ASSERT',
                    task_type='security',
                    outcome='approve',
                    content='Test interaction content',
                    human_response='Looks good',
                    situation_text='PLAN_ASSERT security',
                )

            loaded = get_chunk(conn, chunk.id)
            conn.close()

            # The blended embedding should be non-None
            self.assertIsNotNone(loaded.embedding_blended)
            self.assertEqual(len(loaded.embedding_blended), 3)


if __name__ == '__main__':
    unittest.main()
