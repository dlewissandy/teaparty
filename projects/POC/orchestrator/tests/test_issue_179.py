"""Tests for Issue #179: ACT-R proxy memory system.

Covers the core memory module (proxy_memory.py): activation math,
chunk storage, retrieval, and serialization.
"""
from __future__ import annotations

import asyncio
import math
import sqlite3
import unittest
from unittest.mock import patch, MagicMock

from projects.POC.orchestrator.proxy_memory import (
    MemoryChunk,
    base_level_activation,
    normalize_activation,
    logistic_noise,
    cosine_similarity,
    composite_score,
    open_proxy_db,
    get_interaction_counter,
    increment_interaction_counter,
    store_chunk,
    get_chunk,
    add_trace,
    query_chunks,
    reinforce_retrieved,
    retrieve_chunks,
    record_interaction,
    serialize_chunks_for_prompt,
    DECAY,
    RETRIEVAL_THRESHOLD,
    EXPERIENCE_EMBEDDING_DIMENSIONS,
)


def _make_db() -> sqlite3.Connection:
    """Create an in-memory proxy memory database."""
    return open_proxy_db(':memory:')


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


class TestBaseActivation(unittest.TestCase):
    """Tests for base_level_activation() — B = ln(Σ t_i^(-d))."""

    def test_single_trace_at_distance_1(self):
        # t=1: B = ln(1^(-0.5)) = ln(1.0) = 0.0
        b = base_level_activation([9], current_interaction=10)
        self.assertAlmostEqual(b, 0.0, places=5)

    def test_worked_example_from_docs(self):
        # From act-r.md: traces at 2, 10, 50 interactions ago
        # B = ln(2^(-0.5) + 10^(-0.5) + 50^(-0.5))
        #   = ln(0.707 + 0.316 + 0.141) = ln(1.164) ≈ 0.152
        current = 100
        traces = [current - 2, current - 10, current - 50]
        b = base_level_activation(traces, current)
        self.assertAlmostEqual(b, 0.152, places=2)

    def test_fresh_access_boosts_activation(self):
        # From act-r.md: after re-access at t=1, B jumps to ~0.703
        current = 101
        traces = [100, 100 - 2, 100 - 10, 100 - 50]
        b = base_level_activation(traces, current)
        self.assertAlmostEqual(b, 0.703, places=2)

    def test_empty_traces(self):
        b = base_level_activation([], current_interaction=10)
        self.assertEqual(b, -float('inf'))

    def test_minimum_age_is_1(self):
        # Trace at current interaction: age clamped to 1
        b = base_level_activation([10], current_interaction=10)
        self.assertAlmostEqual(b, 0.0, places=5)


class TestNormalization(unittest.TestCase):

    def test_midpoint(self):
        self.assertAlmostEqual(normalize_activation(0.5, 0.0, 1.0), 0.5)

    def test_at_min(self):
        self.assertAlmostEqual(normalize_activation(0.0, 0.0, 1.0), 0.0)

    def test_at_max(self):
        self.assertAlmostEqual(normalize_activation(1.0, 0.0, 1.0), 1.0)

    def test_equal_min_max(self):
        self.assertAlmostEqual(normalize_activation(5.0, 5.0, 5.0), 0.5)

    def test_clamps_below(self):
        self.assertAlmostEqual(normalize_activation(-1.0, 0.0, 1.0), 0.0)

    def test_clamps_above(self):
        self.assertAlmostEqual(normalize_activation(2.0, 0.0, 1.0), 1.0)


class TestLogisticNoise(unittest.TestCase):

    def test_distribution_centered_near_zero(self):
        samples = [logistic_noise(0.25) for _ in range(10000)]
        mean = sum(samples) / len(samples)
        self.assertAlmostEqual(mean, 0.0, places=1)

    def test_zero_scale_returns_zero(self):
        self.assertEqual(logistic_noise(0.0), 0.0)


class TestCosineSimilarity(unittest.TestCase):

    def test_identical_vectors(self):
        self.assertAlmostEqual(cosine_similarity([1, 0, 0], [1, 0, 0]), 1.0)

    def test_orthogonal_vectors(self):
        self.assertAlmostEqual(cosine_similarity([1, 0, 0], [0, 1, 0]), 0.0)

    def test_opposite_vectors(self):
        self.assertAlmostEqual(cosine_similarity([1, 0], [-1, 0]), -1.0)

    def test_zero_vector(self):
        self.assertAlmostEqual(cosine_similarity([0, 0], [1, 1]), 0.0)


class TestCompositeScore(unittest.TestCase):

    def test_broad_match_outscores_narrow_match(self):
        """A perfect match on 4/4 experience dims outscores a perfect match
        on 2/4, because composite_score divides by EXPERIENCE_EMBEDDING_DIMENSIONS.
        (Updated by #227: salience excluded from composite scoring.)"""
        vec_a = [1.0, 0.0, 0.0]

        chunk_broad = _make_chunk(
            chunk_id='broad', traces=[9],
            embedding_situation=vec_a,
            embedding_artifact=vec_a,
            embedding_stimulus=vec_a,
            embedding_response=vec_a,
        )
        chunk_narrow = _make_chunk(
            chunk_id='narrow', traces=[9],
            embedding_situation=vec_a,
            embedding_artifact=vec_a,
            embedding_stimulus=None,
            embedding_response=None,
        )

        ctx = {
            'situation': vec_a,
            'artifact': vec_a,
            'stimulus': vec_a,
            'response': vec_a,
        }
        score_broad = composite_score(
            chunk_broad, ctx, 10, 0.0, 1.0, s=0.0,
        )
        score_narrow = composite_score(
            chunk_narrow, ctx, 10, 0.0, 1.0, s=0.0,
        )
        # Broad match covers all 4 experience dims → sem = 4/4 = 1.0
        # Narrow match covers 2 dims → sem = 2/4 = 0.5
        # Breadth is rewarded per design spec.
        self.assertGreater(score_broad, score_narrow)


class TestChunkCRUD(unittest.TestCase):

    def test_store_and_retrieve(self):
        conn = _make_db()
        chunk = _make_chunk(embedding_situation=[1.0, 2.0, 3.0])
        store_chunk(conn, chunk)

        loaded = get_chunk(conn, 'test-chunk')
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.id, 'test-chunk')
        self.assertEqual(loaded.state, 'PLAN_ASSERT')
        self.assertEqual(loaded.traces, [1])
        self.assertEqual(loaded.embedding_situation, [1.0, 2.0, 3.0])

    def test_get_nonexistent_returns_none(self):
        conn = _make_db()
        self.assertIsNone(get_chunk(conn, 'nope'))

    def test_add_trace(self):
        conn = _make_db()
        store_chunk(conn, _make_chunk(traces=[1]))
        add_trace(conn, 'test-chunk', 5)
        loaded = get_chunk(conn, 'test-chunk')
        self.assertEqual(loaded.traces, [1, 5])

    def test_query_by_state(self):
        conn = _make_db()
        store_chunk(conn, _make_chunk(chunk_id='a', state='PLAN_ASSERT'))
        store_chunk(conn, _make_chunk(chunk_id='b', state='WORK_ASSERT'))
        results = query_chunks(conn, state='PLAN_ASSERT')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, 'a')

    def test_query_by_task_type(self):
        conn = _make_db()
        store_chunk(conn, _make_chunk(chunk_id='a', task_type='security'))
        store_chunk(conn, _make_chunk(chunk_id='b', task_type='docs'))
        results = query_chunks(conn, task_type='docs')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, 'b')

    def test_query_no_filter(self):
        conn = _make_db()
        store_chunk(conn, _make_chunk(chunk_id='a'))
        store_chunk(conn, _make_chunk(chunk_id='b'))
        results = query_chunks(conn)
        self.assertEqual(len(results), 2)


class TestInteractionCounter(unittest.TestCase):

    def test_starts_at_zero(self):
        conn = _make_db()
        self.assertEqual(get_interaction_counter(conn), 0)

    def test_increments(self):
        conn = _make_db()
        v1 = increment_interaction_counter(conn)
        v2 = increment_interaction_counter(conn)
        self.assertEqual(v1, 1)
        self.assertEqual(v2, 2)

    def test_get_after_increment(self):
        conn = _make_db()
        increment_interaction_counter(conn)
        increment_interaction_counter(conn)
        self.assertEqual(get_interaction_counter(conn), 2)


class TestRetrieveChunks(unittest.TestCase):

    def test_activation_threshold_filters(self):
        """Chunks below tau are excluded from results."""
        conn = _make_db()
        # Chunk with very old trace — low activation
        store_chunk(conn, _make_chunk(chunk_id='old', traces=[1]))
        # Chunk with recent trace — high activation
        store_chunk(conn, _make_chunk(chunk_id='recent', traces=[99]))

        results = retrieve_chunks(
            conn, current_interaction=100, tau=-0.5, s=0.0,
        )
        ids = [c.id for c in results]
        self.assertIn('recent', ids)
        # 'old' has B = ln(100^(-0.5)) = ln(0.1) = -2.3, well below tau
        self.assertNotIn('old', ids)

    def test_structural_filter(self):
        conn = _make_db()
        store_chunk(conn, _make_chunk(chunk_id='a', state='PLAN_ASSERT', traces=[99]))
        store_chunk(conn, _make_chunk(chunk_id='b', state='WORK_ASSERT', traces=[99]))

        results = retrieve_chunks(
            conn, state='PLAN_ASSERT', current_interaction=100, s=0.0,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, 'a')

    def test_ranks_by_composite(self):
        """More recent chunk ranks higher when embeddings are equal."""
        conn = _make_db()
        vec = [1.0, 0.0]
        store_chunk(conn, _make_chunk(
            chunk_id='older', traces=[90], embedding_situation=vec,
        ))
        store_chunk(conn, _make_chunk(
            chunk_id='newer', traces=[99], embedding_situation=vec,
        ))

        results = retrieve_chunks(
            conn,
            context_embeddings={'situation': vec},
            current_interaction=100,
            s=0.0,
        )
        self.assertEqual(results[0].id, 'newer')

    def test_top_k_limits(self):
        conn = _make_db()
        for i in range(20):
            # All chunks have recent traces so none fall below tau
            store_chunk(conn, _make_chunk(
                chunk_id=f'c{i}', traces=[118 + (i % 2)],
            ))
        results = retrieve_chunks(
            conn, current_interaction=120, top_k=5, s=0.0,
        )
        self.assertEqual(len(results), 5)

    def test_empty_db(self):
        conn = _make_db()
        results = retrieve_chunks(conn, current_interaction=10)
        self.assertEqual(results, [])


class TestRetrievalReinforcement(unittest.TestCase):
    """Retrieval is a pure read; reinforcement is a separate explicit step."""

    def test_retrieve_does_not_add_trace(self):
        conn = _make_db()
        store_chunk(conn, _make_chunk(chunk_id='r1', traces=[1]))

        results = retrieve_chunks(
            conn, current_interaction=5, tau=-999, s=0.0,
        )
        self.assertEqual(len(results), 1)
        loaded = get_chunk(conn, 'r1')
        self.assertEqual(loaded.traces, [1],
                         "retrieve_chunks should not mutate traces")

    def test_reinforce_retrieved_adds_trace(self):
        """Explicit reinforce_retrieved adds traces for used chunks."""
        conn = _make_db()
        store_chunk(conn, _make_chunk(chunk_id='r1', traces=[1]))

        results = retrieve_chunks(
            conn, current_interaction=5, tau=-999, s=0.0,
        )
        # Caller explicitly reinforces after using the chunks
        reinforce_retrieved(conn, results, current_interaction=5)

        loaded = get_chunk(conn, 'r1')
        self.assertIn(5, loaded.traces)
        self.assertEqual(loaded.traces, [1, 5])

    def test_reinforcement_boosts_activation(self):
        """Reinforced chunks have higher activation than unreinforced."""
        bx = base_level_activation([1, 5], current_interaction=10)
        by = base_level_activation([1], current_interaction=10)
        self.assertGreater(bx, by)


class TestRecordInteraction(unittest.TestCase):

    def test_creates_chunk(self):
        conn = _make_db()
        chunk = record_interaction(
            conn,
            interaction_type='gate_outcome',
            state='PLAN_ASSERT',
            task_type='security',
            outcome='approve',
            content='Approved the security plan',
            embed_fn=lambda text: [1.0, 0.0, 0.0],
        )
        self.assertIsNotNone(chunk.id)
        self.assertEqual(chunk.state, 'PLAN_ASSERT')
        self.assertEqual(chunk.traces, [1])
        self.assertEqual(get_interaction_counter(conn), 1)

    def test_reinforces_existing(self):
        conn = _make_db()
        store_chunk(conn, _make_chunk(chunk_id='existing', traces=[1]))
        # Set counter to 1 so next increment gives 2
        conn.execute(
            "UPDATE proxy_state SET value=1 WHERE key='interaction_counter'"
        )
        conn.commit()

        chunk = record_interaction(
            conn,
            chunk_id='existing',
            interaction_type='gate_outcome',
            state='PLAN_ASSERT',
            task_type='security',
            outcome='approve',
            content='re-accessed',
        )
        self.assertEqual(chunk.id, 'existing')
        self.assertEqual(chunk.traces, [1, 2])

    def test_situation_text_used_for_embedding(self):
        """A-020: situation_text should be used for embedding when provided."""
        conn = _make_db()
        embedded_texts = []

        def track_embed(text):
            embedded_texts.append(text)
            return [1.0, 0.0]

        record_interaction(
            conn,
            interaction_type='gate_outcome',
            state='PLAN_ASSERT',
            task_type='security',
            outcome='approve',
            content='test',
            situation_text='custom situation description',
            embed_fn=track_embed,
        )
        # The situation embedding should use the provided text, not f'{state} {task_type}'
        self.assertIn('custom situation description', embedded_texts)
        self.assertNotIn('PLAN_ASSERT security', embedded_texts)

    def test_situation_fallback_without_text(self):
        """When situation_text is empty, falls back to state + task_type."""
        conn = _make_db()
        embedded_texts = []

        def track_embed(text):
            embedded_texts.append(text)
            return [1.0, 0.0]

        record_interaction(
            conn,
            interaction_type='gate_outcome',
            state='PLAN_ASSERT',
            task_type='security',
            outcome='approve',
            content='test',
            embed_fn=track_embed,
        )
        self.assertIn('PLAN_ASSERT security', embedded_texts)

    def test_embed_fn_called_per_dimension(self):
        conn = _make_db()
        calls = []

        def track_embed(text):
            calls.append(text)
            return [1.0, 0.0]

        record_interaction(
            conn,
            interaction_type='gate_outcome',
            state='PLAN_ASSERT',
            task_type='security',
            outcome='correct',
            content='test',
            human_response='Add rollback',
            stimulus_text='Review the plan',
            artifact_text='The plan content',
            prediction_delta='Missing rollback changed prediction',
            embed_fn=track_embed,
        )
        # Should embed: situation, artifact, stimulus, response, salience, blended
        self.assertEqual(len(calls), 6)


class TestSerializeChunks(unittest.TestCase):

    def test_empty_list(self):
        self.assertEqual(serialize_chunks_for_prompt([]), '')

    def test_basic_serialization(self):
        chunk = _make_chunk(
            prior_prediction='approve',
            prior_confidence=0.8,
            posterior_prediction='correct',
            posterior_confidence=0.85,
            prediction_delta='Missing rollback section',
            human_response='Add a rollback strategy',
        )
        result = serialize_chunks_for_prompt([chunk])
        self.assertIn('PLAN_ASSERT', result)
        self.assertIn('approve', result)
        self.assertIn('correct', result)
        self.assertIn('Missing rollback', result)
        self.assertIn('Add a rollback', result)

    def test_respects_token_budget(self):
        chunks = [
            _make_chunk(
                chunk_id=f'c{i}',
                content='x' * 2000,
                human_response='y' * 500,
            )
            for i in range(20)
        ]
        result = serialize_chunks_for_prompt(chunks, token_budget=500)
        # With ~500 token budget (2000 chars), should include far fewer than 20
        self.assertLess(result.count('### Memory'), 20)


class TestCalibrateConfidence(unittest.TestCase):
    """Issue #220: calibration uses agent confidence directly, not geometric mean.

    EMA is a system health monitor only.  The cold-start guard is based
    on ACT-R memory depth, not EMA sample count.
    """

    def _calibrate(self, agent_conf, memory_depth=10):
        """Call _calibrate_confidence with mocked memory depth."""
        from projects.POC.orchestrator.proxy_agent import _calibrate_confidence

        with patch('projects.POC.orchestrator.proxy_agent._get_memory_depth',
                   return_value=memory_depth):
            return _calibrate_confidence(
                agent_conf, 'PLAN_ASSERT', 'test', '/tmp/test.json', '',
                _random=1.0,  # bypass exploration rate guard
            )

    def test_agent_confidence_passes_through(self):
        """Agent confidence is the decision signal when memory is deep."""
        result = self._calibrate(0.85)
        self.assertAlmostEqual(result, 0.85, places=2)

    def test_low_confidence_passes_through(self):
        """Low agent confidence is not lifted by historical data."""
        result = self._calibrate(0.3)
        self.assertAlmostEqual(result, 0.3, places=2)

    def test_cold_start_caps_at_half(self):
        """Shallow memory caps confidence at 0.5."""
        result = self._calibrate(0.9, memory_depth=1)
        self.assertLessEqual(result, 0.5)


if __name__ == '__main__':
    unittest.main()
