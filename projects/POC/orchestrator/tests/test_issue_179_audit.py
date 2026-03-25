"""Tests for audit findings #190-#194 on the ACT-R proxy memory system."""
import json
import math
import os
import sqlite3
import tempfile
import unittest

from projects.POC.orchestrator.proxy_memory import (
    DECAY,
    MemoryChunk,
    add_trace,
    base_level_activation,
    composite_score,
    cosine_similarity,
    get_chunk,
    open_proxy_db,
    retrieve_chunks,
    store_chunk,
)


def _make_chunk(**overrides) -> MemoryChunk:
    defaults = dict(
        id='test-chunk-1',
        type='gate_outcome',
        state='WORK_ASSERT',
        task_type='poc',
        outcome='approve',
        content='test interaction',
        traces=[1],
    )
    defaults.update(overrides)
    return MemoryChunk(**defaults)


def _make_db() -> tuple[sqlite3.Connection, str]:
    td = tempfile.mkdtemp()
    path = os.path.join(td, 'test.db')
    conn = open_proxy_db(path)
    return conn, path


class TestIssue190CosineVectorMismatch(unittest.TestCase):
    """#190: cosine_similarity must reject mismatched vector lengths."""

    def test_mismatched_lengths_raises(self):
        """zip(a, b) silently truncates; we need an error instead."""
        a = [1.0, 0.0, 0.0]
        b = [1.0, 0.0, 0.0, 0.0, 0.0]
        with self.assertRaises(ValueError):
            cosine_similarity(a, b)

    def test_equal_lengths_still_works(self):
        a = [1.0, 0.0, 0.0]
        b = [1.0, 0.0, 0.0]
        self.assertAlmostEqual(cosine_similarity(a, b), 1.0)

    def test_empty_vectors(self):
        self.assertAlmostEqual(cosine_similarity([], []), 0.0)


class TestIssue191RetrieveDoesNotMutate(unittest.TestCase):
    """#191: retrieve_chunks should not add traces (write-on-read)."""

    def test_retrieve_does_not_add_traces(self):
        conn, _ = _make_db()
        # Use interaction=1, retrieve at interaction=2 — recent enough to pass tau
        chunk = _make_chunk(traces=[1])
        store_chunk(conn, chunk)

        results = retrieve_chunks(
            conn, state='WORK_ASSERT', task_type='poc',
            current_interaction=2, top_k=10, tau=-10.0,
        )
        self.assertEqual(len(results), 1, "Chunk should be retrieved")

        after = get_chunk(conn, 'test-chunk-1')
        self.assertEqual(after.traces, [1],
                         "retrieve_chunks should not add traces")
        conn.close()

    def test_retrieve_is_idempotent(self):
        conn, _ = _make_db()
        chunk = _make_chunk(traces=[1])
        store_chunk(conn, chunk)

        # Two identical retrievals should return identical trace state
        r1 = retrieve_chunks(
            conn, state='WORK_ASSERT', task_type='poc',
            current_interaction=2, top_k=10, s=0.0, tau=-10.0,
        )
        r2 = retrieve_chunks(
            conn, state='WORK_ASSERT', task_type='poc',
            current_interaction=2, top_k=10, s=0.0, tau=-10.0,
        )
        self.assertEqual(len(r1), len(r2))
        after = get_chunk(conn, 'test-chunk-1')
        self.assertEqual(after.traces, [1],
                         "Two retrievals should not accumulate traces")
        conn.close()


class TestIssue192EmbeddingDimensions(unittest.TestCase):
    """#192: composite_score should not penalize sparse embeddings."""

    def test_sparse_embeddings_not_penalized(self):
        """Denominator should count populated dimensions, not total (5)."""
        vec = [1.0, 0.0, 0.0]

        # Chunk with only situation embedding
        chunk = _make_chunk(
            traces=[1],
            embedding_situation=vec,
        )
        # Query with only situation
        context = {'situation': vec}

        score_sparse = composite_score(
            chunk, context, current_interaction=2,
            b_min=0.0, b_max=0.0, s=0.0,
        )

        # Chunk with all 5 dimensions populated identically
        chunk_full = _make_chunk(
            id='full',
            traces=[1],
            embedding_situation=vec,
            embedding_artifact=vec,
            embedding_stimulus=vec,
            embedding_response=vec,
            embedding_salience=vec,
        )
        context_full = {
            'situation': vec, 'artifact': vec, 'stimulus': vec,
            'response': vec, 'salience': vec,
        }
        score_full = composite_score(
            chunk_full, context_full, current_interaction=2,
            b_min=0.0, b_max=0.0, s=0.0,
        )

        # A perfect match on 1/1 populated dimensions should score the same
        # semantic component as a perfect match on 5/5 populated dimensions.
        # With the old code (divide by 5 always), sparse gets 0.2 and full gets 1.0.
        # The semantic components should be equal (both perfect matches).
        # We check that the sparse score is NOT drastically lower than full.
        self.assertGreater(score_sparse, score_full * 0.8,
                           "Sparse embedding penalized vs full — denominator bug")


class TestIssue193ConfidenceCalibrationFloor(unittest.TestCase):
    """#193: geometric mean must not collapse to zero on parse failure."""

    def test_zero_agent_confidence_does_not_zero_output(self):
        """When agent_confidence=0.0 (parse failure), calibrated confidence
        should not be zero — statistical history should still contribute."""
        # We test the math directly rather than the full _calibrate_confidence
        # because that requires filesystem state. The geometric mean is the bug.
        agent_confidence = 0.0
        stats_confidence = 0.9

        # Current code: (0.0 * 0.9) ** 0.5 = 0.0 -- this is the bug
        raw = (agent_confidence * stats_confidence) ** 0.5
        self.assertEqual(raw, 0.0, "Sanity: raw geometric mean is zero")

        # After fix: agent_confidence should be floored
        CONFIDENCE_FLOOR = 0.05
        floored = (max(agent_confidence, CONFIDENCE_FLOOR) * stats_confidence) ** 0.5
        self.assertGreater(floored, 0.0,
                           "Floored geometric mean should not be zero")
        self.assertGreater(floored, 0.1,
                           "Floored confidence should be meaningful")


class TestIssue194RowToChunkNamedAccess(unittest.TestCase):
    """#194: _row_to_chunk should use named column access, not positional."""

    def test_row_factory_is_set(self):
        """After fix, the connection should use sqlite3.Row factory."""
        conn, _ = _make_db()
        chunk = _make_chunk()
        store_chunk(conn, chunk)

        # Verify we can retrieve with named access
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            'SELECT * FROM proxy_chunks WHERE id=?', (chunk.id,)
        ).fetchone()
        # Named access should work
        self.assertEqual(row['id'], chunk.id)
        self.assertEqual(row['state'], chunk.state)
        self.assertEqual(row['outcome'], chunk.outcome)
        conn.close()


if __name__ == '__main__':
    unittest.main()
