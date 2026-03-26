"""Tests for Issue #219: reinforce_retrieved() wired into retrieval path.

ACT-R Rule 2 says chunks retrieved for a task should receive a new trace.
reinforce_retrieved() exists but nothing calls it. These tests verify that
_retrieve_actr_memories() reinforces chunks after retrieval.
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from projects.POC.orchestrator.proxy_memory import (
    MemoryChunk,
    open_proxy_db,
    store_chunk,
    get_chunk,
    get_interaction_counter,
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


def _make_db_file(tmpdir: str, team: str = '') -> tuple[str, str]:
    """Create a proxy memory DB file and return (db_path, proxy_model_path).

    The proxy_model_path is what the code uses to derive the DB path via
    resolve_memory_db_path().
    """
    proxy_model_path = os.path.join(tmpdir, '.proxy-confidence.json')
    if team:
        db_path = os.path.join(tmpdir, f'.proxy-memory-{team}.db')
    else:
        db_path = os.path.join(tmpdir, '.proxy-memory.db')
    return db_path, proxy_model_path


class TestRetrievalReinforcementWiring(unittest.TestCase):
    """_retrieve_actr_memories() must reinforce retrieved chunks (ACT-R Rule 2)."""

    def test_retrieve_actr_memories_reinforces_chunks(self):
        """After _retrieve_actr_memories retrieves chunks, their traces grow."""
        from projects.POC.orchestrator.proxy_agent import _retrieve_actr_memories

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, proxy_model_path = _make_db_file(tmpdir)

            # Seed the DB with a chunk (recent trace so it survives tau filter)
            conn = open_proxy_db(db_path)
            chunk = _make_chunk(chunk_id='c1', traces=[4])
            store_chunk(conn, chunk)
            conn.execute(
                "UPDATE proxy_state SET value=5 WHERE key='interaction_counter'"
            )
            conn.commit()
            conn.close()

            # Mock embedding to avoid real API calls
            mock_embed = lambda text, conn=None, provider=None, model=None: [1.0, 0.0]

            with patch('projects.POC.scripts.memory_indexer.detect_provider', return_value=('test', 'test')), \
                 patch('projects.POC.scripts.memory_indexer.try_embed', side_effect=mock_embed):
                result = _retrieve_actr_memories(
                    proxy_model_path=proxy_model_path,
                    team='',
                    state='PLAN_ASSERT',
                    task_type='security',
                    question='Review the security plan',
                )

            # The retrieval should have returned serialized chunks
            self.assertIn('Memory', result, 'Should have retrieved the chunk')

            # Re-open DB and check that the chunk was reinforced with a new trace
            conn = open_proxy_db(db_path)
            loaded = get_chunk(conn, 'c1')
            conn.close()

            self.assertIsNotNone(loaded)
            self.assertGreater(
                len(loaded.traces), 1,
                f'Expected chunk to be reinforced (traces > 1), got traces={loaded.traces}',
            )
            # Trace value should be the current interaction counter
            self.assertEqual(loaded.traces[0], 4, 'Original trace preserved')
            self.assertIn(5, loaded.traces,
                          'Reinforcement trace should use the current interaction counter')

    def test_retrieve_actr_memories_does_not_increment_counter(self):
        """Reinforcement should NOT advance the interaction counter.

        The counter is only incremented by record_interaction() (Rule 1).
        Retrieval reinforcement (Rule 2) adds a trace at the current counter
        value without incrementing it.
        """
        from projects.POC.orchestrator.proxy_agent import _retrieve_actr_memories

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, proxy_model_path = _make_db_file(tmpdir)

            conn = open_proxy_db(db_path)
            store_chunk(conn, _make_chunk(chunk_id='c1', traces=[4]))
            conn.execute(
                "UPDATE proxy_state SET value=5 WHERE key='interaction_counter'"
            )
            conn.commit()
            conn.close()

            mock_embed = lambda text, conn=None, provider=None, model=None: [1.0, 0.0]

            with patch('projects.POC.scripts.memory_indexer.detect_provider', return_value=('test', 'test')), \
                 patch('projects.POC.scripts.memory_indexer.try_embed', side_effect=mock_embed):
                _retrieve_actr_memories(
                    proxy_model_path=proxy_model_path,
                    team='',
                    state='PLAN_ASSERT',
                    task_type='security',
                    question='Review the plan',
                )

            conn = open_proxy_db(db_path)
            counter = get_interaction_counter(conn)
            conn.close()

            self.assertEqual(counter, 5,
                             'Retrieval reinforcement must not increment the interaction counter')

    def test_retrieve_actr_memories_reinforces_all_retrieved(self):
        """All retrieved chunks get reinforced, not just the first."""
        from projects.POC.orchestrator.proxy_agent import _retrieve_actr_memories

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, proxy_model_path = _make_db_file(tmpdir)

            conn = open_proxy_db(db_path)
            for i in range(3):
                store_chunk(conn, _make_chunk(
                    chunk_id=f'c{i}', traces=[4],  # recent enough to survive tau
                ))
            conn.execute(
                "UPDATE proxy_state SET value=5 WHERE key='interaction_counter'"
            )
            conn.commit()
            conn.close()

            mock_embed = lambda text, conn=None, provider=None, model=None: [1.0, 0.0]

            with patch('projects.POC.scripts.memory_indexer.detect_provider', return_value=('test', 'test')), \
                 patch('projects.POC.scripts.memory_indexer.try_embed', side_effect=mock_embed):
                _retrieve_actr_memories(
                    proxy_model_path=proxy_model_path,
                    team='',
                    state='PLAN_ASSERT',
                    task_type='security',
                    question='test',
                )

            conn = open_proxy_db(db_path)
            for i in range(3):
                loaded = get_chunk(conn, f'c{i}')
                self.assertGreater(
                    len(loaded.traces), 1,
                    f'Chunk c{i} should be reinforced, got traces={loaded.traces}',
                )
            conn.close()

    def test_empty_retrieval_does_not_error(self):
        """When no chunks are retrieved, reinforcement is a no-op."""
        from projects.POC.orchestrator.proxy_agent import _retrieve_actr_memories

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, proxy_model_path = _make_db_file(tmpdir)

            # Create DB with counter but no chunks
            conn = open_proxy_db(db_path)
            conn.execute(
                "UPDATE proxy_state SET value=5 WHERE key='interaction_counter'"
            )
            conn.commit()
            conn.close()

            mock_embed = lambda text, conn=None, provider=None, model=None: [1.0, 0.0]

            with patch('projects.POC.scripts.memory_indexer.detect_provider', return_value=('test', 'test')), \
                 patch('projects.POC.scripts.memory_indexer.try_embed', side_effect=mock_embed):
                result = _retrieve_actr_memories(
                    proxy_model_path=proxy_model_path,
                    team='',
                    state='PLAN_ASSERT',
                    task_type='security',
                    question='test',
                )

            self.assertEqual(result, '')


if __name__ == '__main__':
    unittest.main()
