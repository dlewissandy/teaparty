"""Tests for Issue #184: Non-atomic interaction counter + chunk store.

Verifies that record_interaction wraps counter increment and chunk
storage in a single transaction, so a failure in store_chunk rolls
back the counter increment.
"""
from __future__ import annotations

import sqlite3
import unittest
from unittest.mock import patch

from projects.POC.orchestrator.proxy_memory import (
    get_interaction_counter,
    get_chunk,
    open_proxy_db,
    record_interaction,
    store_chunk,
)


def _make_db() -> sqlite3.Connection:
    """Create an in-memory proxy memory database."""
    return open_proxy_db(':memory:')


class TestRecordInteractionAtomicity(unittest.TestCase):
    """A-010: increment_interaction_counter and store_chunk must be atomic."""

    def test_counter_rolls_back_when_store_chunk_fails(self):
        """If store_chunk raises, the interaction counter must not be incremented."""
        conn = _make_db()
        self.assertEqual(get_interaction_counter(conn), 0)

        with patch(
            'projects.POC.orchestrator.proxy_memory._store_chunk_no_commit',
            side_effect=sqlite3.OperationalError('simulated disk error'),
        ):
            with self.assertRaises(sqlite3.OperationalError):
                record_interaction(
                    conn,
                    interaction_type='gate_outcome',
                    state='PLAN_ASSERT',
                    task_type='security',
                    outcome='approve',
                    content='This should fail atomically',
                    embed_fn=lambda text: [1.0, 0.0],
                )

        # Counter must still be 0 — the increment should have been rolled back
        self.assertEqual(
            get_interaction_counter(conn), 0,
            'Interaction counter was incremented despite store_chunk failure — '
            'operations are not atomic',
        )

    def test_counter_rolls_back_when_add_trace_fails(self):
        """If add_trace raises on the existing-chunk path, counter rolls back."""
        from projects.POC.orchestrator.proxy_memory import MemoryChunk

        conn = _make_db()
        # Pre-populate a chunk and set counter to 1
        chunk = MemoryChunk(
            id='existing',
            type='gate_outcome',
            state='PLAN_ASSERT',
            task_type='security',
            outcome='approve',
            content='test',
            traces=[1],
        )
        store_chunk(conn, chunk)
        conn.execute(
            "UPDATE proxy_state SET value=1 WHERE key='interaction_counter'"
        )
        conn.commit()
        self.assertEqual(get_interaction_counter(conn), 1)

        with patch(
            'projects.POC.orchestrator.proxy_memory._add_trace_no_commit',
            side_effect=sqlite3.OperationalError('simulated disk error'),
        ):
            with self.assertRaises(sqlite3.OperationalError):
                record_interaction(
                    conn,
                    chunk_id='existing',
                    interaction_type='gate_outcome',
                    state='PLAN_ASSERT',
                    task_type='security',
                    outcome='approve',
                    content='re-access should fail atomically',
                )

        # Counter must still be 1 — the increment should have been rolled back
        self.assertEqual(
            get_interaction_counter(conn), 1,
            'Interaction counter was incremented despite add_trace failure — '
            'operations are not atomic',
        )

    def test_embed_fn_runs_outside_transaction(self):
        """Embedding calls must happen before BEGIN IMMEDIATE, not inside it.

        _default_embed routes to try_embed which calls conn.commit() on the
        embedding_cache table. If _embed runs inside the transaction, that
        commit would prematurely commit the counter increment, destroying
        atomicity. This test verifies embeddings are computed before the
        transaction by checking that an embed_fn that commits doesn't
        interfere with rollback.
        """
        conn = _make_db()
        self.assertEqual(get_interaction_counter(conn), 0)

        def committing_embed(text):
            """Simulates try_embed writing to embedding_cache and committing."""
            conn.execute(
                "INSERT OR REPLACE INTO embedding_cache "
                "(hash, provider, model, embedding, updated_at) "
                "VALUES (?, ?, ?, ?, 0)",
                (text, 'test', 'test', '[1.0]'),
            )
            conn.commit()
            return [1.0, 0.0]

        with patch(
            'projects.POC.orchestrator.proxy_memory._store_chunk_no_commit',
            side_effect=sqlite3.OperationalError('simulated failure after embed'),
        ):
            with self.assertRaises(sqlite3.OperationalError):
                record_interaction(
                    conn,
                    interaction_type='gate_outcome',
                    state='PLAN_ASSERT',
                    task_type='security',
                    outcome='approve',
                    content='test',
                    embed_fn=committing_embed,
                )

        # If embed ran inside the transaction, its conn.commit() would have
        # committed the counter increment, making rollback impossible.
        self.assertEqual(
            get_interaction_counter(conn), 0,
            'embed_fn commit leaked the counter increment — '
            'embeddings are being computed inside the transaction',
        )

    def test_successful_record_still_works(self):
        """Sanity check: record_interaction still works end-to-end after refactor."""
        conn = _make_db()
        chunk = record_interaction(
            conn,
            interaction_type='gate_outcome',
            state='PLAN_ASSERT',
            task_type='security',
            outcome='approve',
            content='Normal operation',
            embed_fn=lambda text: [1.0, 0.0],
        )
        self.assertEqual(get_interaction_counter(conn), 1)
        self.assertIsNotNone(get_chunk(conn, chunk.id))
        self.assertEqual(chunk.traces, [1])

    def test_successful_reinforce_still_works(self):
        """Sanity check: existing-chunk reinforcement path still works."""
        from projects.POC.orchestrator.proxy_memory import MemoryChunk

        conn = _make_db()
        chunk = MemoryChunk(
            id='existing',
            type='gate_outcome',
            state='PLAN_ASSERT',
            task_type='security',
            outcome='approve',
            content='test',
            traces=[1],
        )
        store_chunk(conn, chunk)
        conn.execute(
            "UPDATE proxy_state SET value=1 WHERE key='interaction_counter'"
        )
        conn.commit()

        result = record_interaction(
            conn,
            chunk_id='existing',
            interaction_type='gate_outcome',
            state='PLAN_ASSERT',
            task_type='security',
            outcome='approve',
            content='re-access',
        )
        self.assertEqual(result.id, 'existing')
        self.assertEqual(result.traces, [1, 2])
        self.assertEqual(get_interaction_counter(conn), 2)


if __name__ == '__main__':
    unittest.main()
