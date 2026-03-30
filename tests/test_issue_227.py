"""Tests for Issue #227: Separate salience index from memory chunk embeddings.

The design change separates salience into an independent retrieval path rather
than a fifth embedding dimension in the composite score.  Experience retrieval
uses 4 dimensions (situation, artifact, stimulus, response).  Salience
retrieval is a dedicated query over chunks with non-null salience embeddings.

Verified behaviors:
  1. composite_score() uses 4 experience dimensions, not 5.
  2. Chunks without salience are NOT penalized in experience retrieval.
  3. retrieve_salience() returns only chunks with populated salience.
  4. serialize_chunks_for_prompt() renders experience and salience sections
     separately.
  5. EXPERIENCE_DIMS and EXPERIENCE_EMBEDDING_DIMENSIONS constants exist
     and exclude salience.
"""
from __future__ import annotations

import unittest

from orchestrator.proxy_memory import (
    MemoryChunk,
    composite_score,
    cosine_similarity,
    serialize_chunks_for_prompt,
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


class TestIssue227CompositeScoreExcludesSalience(unittest.TestCase):
    """composite_score() must use 4 experience dimensions, not 5."""

    def test_salience_embedding_not_included_in_composite(self):
        """Passing a salience context embedding should NOT change the
        composite score — salience is no longer part of composite scoring."""
        vec = [1.0, 0.0, 0.0]

        chunk = _make_chunk(
            traces=[1],
            embedding_situation=vec,
            embedding_artifact=vec,
            embedding_stimulus=vec,
            embedding_response=vec,
            embedding_salience=vec,
        )

        # Score WITHOUT salience in context
        ctx_no_salience = {
            'situation': vec, 'artifact': vec,
            'stimulus': vec, 'response': vec,
        }
        score_without = composite_score(
            chunk, ctx_no_salience, current_interaction=2,
            b_min=0.0, b_max=0.0,
            activation_weight=0.0, semantic_weight=1.0,
            s=0.0,
        )

        # Score WITH salience in context — should be IDENTICAL
        ctx_with_salience = {
            'situation': vec, 'artifact': vec,
            'stimulus': vec, 'response': vec,
            'salience': vec,
        }
        score_with = composite_score(
            chunk, ctx_with_salience, current_interaction=2,
            b_min=0.0, b_max=0.0,
            activation_weight=0.0, semantic_weight=1.0,
            s=0.0,
        )

        self.assertAlmostEqual(
            score_without, score_with, places=5,
            msg="Salience should not contribute to composite score",
        )

    def test_four_dim_perfect_match_gives_semantic_one(self):
        """When all 4 experience dimensions have cosine=1.0, semantic = 1.0."""
        vec = [1.0, 0.0, 0.0]
        chunk = _make_chunk(
            traces=[1],
            embedding_situation=vec,
            embedding_artifact=vec,
            embedding_stimulus=vec,
            embedding_response=vec,
        )
        context = {
            'situation': vec, 'artifact': vec,
            'stimulus': vec, 'response': vec,
        }
        score = composite_score(
            chunk, context, current_interaction=2,
            b_min=0.0, b_max=0.0,
            activation_weight=0.0, semantic_weight=1.0,
            s=0.0,
        )
        self.assertAlmostEqual(
            score, 1.0, places=5,
            msg="4/4 perfect experience matches should give semantic = 1.0",
        )

    def test_chunk_without_salience_not_penalized(self):
        """A chunk with no salience embedding should score the same as one
        with salience when both have identical experience embeddings.
        This is the core bug: the old 5-dimension divisor penalized
        chunks without salience."""
        vec = [1.0, 0.0, 0.0]

        chunk_with_salience = _make_chunk(
            chunk_id='with-salience', traces=[1],
            embedding_situation=vec,
            embedding_artifact=vec,
            embedding_stimulus=vec,
            embedding_response=vec,
            embedding_salience=vec,
        )
        chunk_without_salience = _make_chunk(
            chunk_id='without-salience', traces=[1],
            embedding_situation=vec,
            embedding_artifact=vec,
            embedding_stimulus=vec,
            embedding_response=vec,
            embedding_salience=None,
        )

        ctx = {
            'situation': vec, 'artifact': vec,
            'stimulus': vec, 'response': vec,
        }
        score_with = composite_score(
            chunk_with_salience, ctx, current_interaction=2,
            b_min=0.0, b_max=0.0,
            activation_weight=0.0, semantic_weight=1.0,
            s=0.0,
        )
        score_without = composite_score(
            chunk_without_salience, ctx, current_interaction=2,
            b_min=0.0, b_max=0.0,
            activation_weight=0.0, semantic_weight=1.0,
            s=0.0,
        )
        self.assertAlmostEqual(
            score_with, score_without, places=5,
            msg="Salience should not affect experience retrieval score",
        )


class TestIssue227ExperienceDimsConstant(unittest.TestCase):
    """EXPERIENCE_DIMS and EXPERIENCE_EMBEDDING_DIMENSIONS must exist."""

    def test_experience_dims_excludes_salience(self):
        from orchestrator.proxy_memory import EXPERIENCE_DIMS
        self.assertNotIn('salience', EXPERIENCE_DIMS)
        self.assertEqual(len(EXPERIENCE_DIMS), 4)
        self.assertIn('situation', EXPERIENCE_DIMS)
        self.assertIn('artifact', EXPERIENCE_DIMS)
        self.assertIn('stimulus', EXPERIENCE_DIMS)
        self.assertIn('response', EXPERIENCE_DIMS)

    def test_experience_embedding_dimensions_is_four(self):
        from orchestrator.proxy_memory import EXPERIENCE_EMBEDDING_DIMENSIONS
        self.assertEqual(EXPERIENCE_EMBEDDING_DIMENSIONS, 4)


class TestIssue227RetrieveSalience(unittest.TestCase):
    """retrieve_salience() is a dedicated retrieval path for salience chunks."""

    def test_retrieve_salience_exists(self):
        """The function must be importable."""
        from orchestrator.proxy_memory import retrieve_salience
        self.assertTrue(callable(retrieve_salience))

    def test_retrieve_salience_returns_only_salience_chunks(self):
        """retrieve_salience() should return only chunks with non-null
        salience embeddings, ranked by cosine similarity."""
        from orchestrator.proxy_memory import (
            open_proxy_db,
            store_chunk,
            retrieve_salience,
            get_interaction_counter,
        )

        conn = open_proxy_db(':memory:')
        vec = [1.0, 0.0, 0.0]
        other_vec = [0.0, 1.0, 0.0]

        # Chunk WITH salience — should be returned
        chunk_salient = _make_chunk(
            chunk_id='salient', traces=[1],
            embedding_situation=vec,
            embedding_salience=vec,
            prediction_delta='Missing rollback strategy',
        )
        store_chunk(conn, chunk_salient)

        # Chunk WITHOUT salience — should NOT be returned
        chunk_routine = _make_chunk(
            chunk_id='routine', traces=[1],
            embedding_situation=vec,
            embedding_salience=None,
        )
        store_chunk(conn, chunk_routine)

        results = retrieve_salience(
            conn,
            context_embedding=vec,
            current_interaction=2,
        )
        result_ids = [c.id for c in results]
        self.assertIn('salient', result_ids)
        self.assertNotIn('routine', result_ids)
        conn.close()

    def test_retrieve_salience_ranks_by_cosine_similarity(self):
        """Chunks with salience closer to the query should rank higher."""
        from orchestrator.proxy_memory import (
            open_proxy_db,
            store_chunk,
            retrieve_salience,
        )

        conn = open_proxy_db(':memory:')
        query_vec = [1.0, 0.0, 0.0]
        close_vec = [0.9, 0.1, 0.0]  # high similarity
        far_vec = [0.0, 1.0, 0.0]    # low similarity

        chunk_close = _make_chunk(
            chunk_id='close', traces=[1],
            embedding_salience=close_vec,
            prediction_delta='Close match',
        )
        chunk_far = _make_chunk(
            chunk_id='far', traces=[1],
            embedding_salience=far_vec,
            prediction_delta='Far match',
        )
        store_chunk(conn, chunk_close)
        store_chunk(conn, chunk_far)

        results = retrieve_salience(
            conn, context_embedding=query_vec, current_interaction=2,
        )
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].id, 'close',
                         "Higher cosine similarity should rank first")
        conn.close()


class TestIssue227SerializeSeparateSections(unittest.TestCase):
    """serialize_chunks_for_prompt() renders experience and salience separately."""

    def test_separate_sections_in_output(self):
        """When salience_chunks are provided, output should have two
        distinct sections."""
        exp_chunk = _make_chunk(chunk_id='exp-1', human_response='approved it')
        sal_chunk = _make_chunk(
            chunk_id='sal-1',
            prediction_delta='Missing rollback changed prediction',
        )

        result = serialize_chunks_for_prompt(
            chunks=[exp_chunk],
            salience_chunks=[sal_chunk],
        )
        self.assertIn('Your relevant experience with this human', result)
        self.assertIn('What has surprised you in similar situations', result)
        self.assertIn('sal-1'[:8], result)
        self.assertIn('exp-1'[:8], result)

    def test_no_salience_section_when_empty(self):
        """When no salience_chunks, output should not contain salience section."""
        exp_chunk = _make_chunk(chunk_id='exp-1')

        result = serialize_chunks_for_prompt(chunks=[exp_chunk])
        self.assertIn('Your relevant experience with this human', result)
        self.assertNotIn('surprised', result)

    def test_backward_compatible_without_salience_arg(self):
        """Calling without salience_chunks should work (backward compat)."""
        exp_chunk = _make_chunk(chunk_id='exp-1')
        # Should not raise
        result = serialize_chunks_for_prompt(chunks=[exp_chunk])
        self.assertIn('exp-1'[:8], result)


class TestIssue227SalienceQueryConstruction(unittest.TestCase):
    """The salience query should be constructed from artifact + situation,
    not just situation alone (per issue spec)."""

    def test_retrieve_salience_matches_artifact_context(self):
        """A salience chunk whose delta mentions an artifact feature should
        rank higher when the salience query incorporates that artifact."""
        from orchestrator.proxy_memory import (
            open_proxy_db,
            store_chunk,
            retrieve_salience,
        )

        conn = open_proxy_db(':memory:')

        # Salience chunk about missing rollback in a migration plan
        rollback_vec = [0.9, 0.1, 0.0]
        chunk = _make_chunk(
            chunk_id='rollback-surprise', traces=[1],
            embedding_salience=rollback_vec,
            prediction_delta='Missing rollback strategy for database migration',
        )
        store_chunk(conn, chunk)

        # Query with similar vector (as if constructed from artifact + situation)
        similar_query = [0.85, 0.15, 0.0]
        results = retrieve_salience(
            conn, context_embedding=similar_query, current_interaction=2,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, 'rollback-surprise')

        # Query with orthogonal vector should still return but with lower rank
        orthogonal_query = [0.0, 0.0, 1.0]
        results_orth = retrieve_salience(
            conn, context_embedding=orthogonal_query, current_interaction=2,
        )
        self.assertEqual(len(results_orth), 1)
        # Similarity should be much lower
        sim_similar = cosine_similarity(rollback_vec, similar_query)
        sim_orthogonal = cosine_similarity(rollback_vec, orthogonal_query)
        self.assertGreater(sim_similar, sim_orthogonal)
        conn.close()


if __name__ == '__main__':
    unittest.main()
