"""Tests for Issue #212: composite_score divides by TOTAL_EMBEDDING_DIMENSIONS.

The design spec requires division by TOTAL_EMBEDDING_DIMENSIONS (not
matched_dims) so that breadth of matching is rewarded: a chunk matching
moderately across all dimensions ranks higher than one matching strongly
on only a few.
"""
from __future__ import annotations

import unittest

from projects.POC.orchestrator.proxy_memory import (
    MemoryChunk,
    composite_score,
    TOTAL_EMBEDDING_DIMENSIONS,
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


class TestIssue212BreadthOverDepth(unittest.TestCase):
    """composite_score must divide cosine sum by TOTAL_EMBEDDING_DIMENSIONS."""

    def test_broad_match_ranks_above_narrow_match(self):
        """A chunk matching moderately on all 5 dims should outscore one
        matching perfectly on only 2 dims, when both have equal activation."""
        # cosine similarity of identical unit vectors = 1.0
        vec = [1.0, 0.0, 0.0]

        # Broad: moderate (0.5) match on all 5 dims → sem = 5*0.5/5 = 0.5
        half_vec = [0.5, 0.5, 0.0]  # cosine with vec ≈ 0.707

        chunk_broad = _make_chunk(
            chunk_id='broad', traces=[9],
            embedding_situation=half_vec,
            embedding_artifact=half_vec,
            embedding_stimulus=half_vec,
            embedding_response=half_vec,
            embedding_salience=half_vec,
        )
        # Narrow: perfect match on 2 dims only → sem = 2*1.0/5 = 0.4
        chunk_narrow = _make_chunk(
            chunk_id='narrow', traces=[9],
            embedding_situation=vec,
            embedding_artifact=vec,
        )

        ctx = {
            'situation': vec, 'artifact': vec, 'stimulus': vec,
            'response': vec, 'salience': vec,
        }
        score_broad = composite_score(
            chunk_broad, ctx, 10, 0.0, 1.0, s=0.0,
        )
        score_narrow = composite_score(
            chunk_narrow, ctx, 10, 0.0, 1.0, s=0.0,
        )
        # Broad should beat narrow because breadth is rewarded
        self.assertGreater(score_broad, score_narrow,
                           "Broad match should outscore narrow match")

    def test_semantic_component_divides_by_total_dims(self):
        """With activation zeroed out, semantic component should be
        sim_sum / TOTAL_EMBEDDING_DIMENSIONS, not sim_sum / matched_dims."""
        vec = [1.0, 0.0, 0.0]

        # 1 perfect match out of 5 dims → sem = 1.0 / 5 = 0.2
        chunk = _make_chunk(
            traces=[1],
            embedding_situation=vec,
        )
        context = {'situation': vec}

        score = composite_score(
            chunk, context, current_interaction=2,
            b_min=0.0, b_max=0.0,
            activation_weight=0.0, semantic_weight=1.0,
            s=0.0,
        )
        expected = 1.0 / TOTAL_EMBEDDING_DIMENSIONS  # 0.2
        self.assertAlmostEqual(score, expected, places=5,
                               msg="Semantic score should be cosine_sum / TOTAL_EMBEDDING_DIMENSIONS")

    def test_all_dims_perfect_match_gives_semantic_one(self):
        """When all dimensions have cosine=1.0, semantic component = 1.0."""
        vec = [1.0, 0.0, 0.0]
        chunk = _make_chunk(
            traces=[1],
            embedding_situation=vec,
            embedding_artifact=vec,
            embedding_stimulus=vec,
            embedding_response=vec,
            embedding_salience=vec,
        )
        context = {
            'situation': vec, 'artifact': vec, 'stimulus': vec,
            'response': vec, 'salience': vec,
        }
        score = composite_score(
            chunk, context, current_interaction=2,
            b_min=0.0, b_max=0.0,
            activation_weight=0.0, semantic_weight=1.0,
            s=0.0,
        )
        self.assertAlmostEqual(score, 1.0, places=5,
                               msg="5/5 perfect matches should give semantic = 1.0")
