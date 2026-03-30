"""Tests for Issue #219: reinforce_retrieved() wired into consultation path.

ACT-R Rule 2 says chunks retrieved for a task should receive a new trace
after the proxy agent has consumed them and produced a response.
reinforce_retrieved() exists but nothing calls it. These tests verify that:

1. _retrieve_actr_memories() returns chunk IDs for deferred reinforcement
2. _reinforce_actr_memories() writes traces to the DB using those IDs
3. consult_proxy() calls reinforcement after the agent produces a response
4. Reinforcement does not happen when the agent fails to produce output
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch, AsyncMock, MagicMock

from orchestrator.proxy_memory import (
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
    """Create a proxy memory DB file and return (db_path, proxy_model_path)."""
    proxy_model_path = os.path.join(tmpdir, '.proxy-confidence.json')
    if team:
        db_path = os.path.join(tmpdir, f'.proxy-memory-{team}.db')
    else:
        db_path = os.path.join(tmpdir, '.proxy-memory.db')
    return db_path, proxy_model_path


def _seed_db(db_path: str, chunks: list[MemoryChunk], counter: int = 5):
    """Seed a proxy memory DB with chunks and set the interaction counter."""
    conn = open_proxy_db(db_path)
    for chunk in chunks:
        store_chunk(conn, chunk)
    conn.execute(
        "UPDATE proxy_state SET value=? WHERE key='interaction_counter'",
        (counter,),
    )
    conn.commit()
    conn.close()


class TestRetrievalReturnsChunkIds(unittest.TestCase):
    """_retrieve_actr_memories() returns chunk IDs for deferred reinforcement."""

    def test_returns_chunk_ids(self):
        from orchestrator.proxy_agent import _retrieve_actr_memories

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, proxy_model_path = _make_db_file(tmpdir)
            _seed_db(db_path, [_make_chunk(chunk_id='c1', traces=[4])])

            mock_embed = lambda text, conn=None, provider=None, model=None: [1.0, 0.0]

            with patch('scripts.memory_indexer.detect_provider', return_value=('test', 'test')), \
                 patch('scripts.memory_indexer.try_embed', side_effect=mock_embed):
                result = _retrieve_actr_memories(
                    proxy_model_path=proxy_model_path,
                    team='',
                    state='PLAN_ASSERT',
                    task_type='security',
                    question='Review the security plan',
                )

            self.assertIn('c1', result.chunk_ids)
            self.assertIn('Memory', result.serialized)
            self.assertEqual(result.db_path, db_path)
            self.assertEqual(result.interaction_counter, 5)

    def test_retrieval_does_not_reinforce(self):
        """Retrieval alone must NOT add traces — that happens post-consumption."""
        from orchestrator.proxy_agent import _retrieve_actr_memories

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, proxy_model_path = _make_db_file(tmpdir)
            _seed_db(db_path, [_make_chunk(chunk_id='c1', traces=[4])])

            mock_embed = lambda text, conn=None, provider=None, model=None: [1.0, 0.0]

            with patch('scripts.memory_indexer.detect_provider', return_value=('test', 'test')), \
                 patch('scripts.memory_indexer.try_embed', side_effect=mock_embed):
                _retrieve_actr_memories(
                    proxy_model_path=proxy_model_path,
                    team='',
                    state='PLAN_ASSERT',
                    task_type='security',
                    question='test',
                )

            conn = open_proxy_db(db_path)
            loaded = get_chunk(conn, 'c1')
            conn.close()
            self.assertEqual(loaded.traces, [4],
                             'Retrieval must not add traces — reinforcement is post-consumption')

    def test_empty_retrieval(self):
        from orchestrator.proxy_agent import _retrieve_actr_memories, _EMPTY_RETRIEVAL

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, proxy_model_path = _make_db_file(tmpdir)
            _seed_db(db_path, [], counter=5)

            mock_embed = lambda text, conn=None, provider=None, model=None: [1.0, 0.0]

            with patch('scripts.memory_indexer.detect_provider', return_value=('test', 'test')), \
                 patch('scripts.memory_indexer.try_embed', side_effect=mock_embed):
                result = _retrieve_actr_memories(
                    proxy_model_path=proxy_model_path,
                    team='',
                    state='PLAN_ASSERT',
                    task_type='security',
                    question='test',
                )

            self.assertEqual(result.serialized, '')
            self.assertEqual(result.chunk_ids, [])


class TestReinforceActrMemories(unittest.TestCase):
    """_reinforce_actr_memories() writes traces to the DB."""

    def test_reinforces_all_chunks(self):
        from orchestrator.proxy_agent import (
            _reinforce_actr_memories,
            _ActrRetrievalResult,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, _ = _make_db_file(tmpdir)
            _seed_db(db_path, [
                _make_chunk(chunk_id='c0', traces=[4]),
                _make_chunk(chunk_id='c1', traces=[4]),
                _make_chunk(chunk_id='c2', traces=[4]),
            ])

            retrieval = _ActrRetrievalResult(
                serialized='(unused)',
                chunk_ids=['c0', 'c1', 'c2'],
                db_path=db_path,
                interaction_counter=5,
            )
            _reinforce_actr_memories(retrieval)

            conn = open_proxy_db(db_path)
            for i in range(3):
                loaded = get_chunk(conn, f'c{i}')
                self.assertEqual(
                    loaded.traces, [4, 5],
                    f'Chunk c{i} should have reinforcement trace at 5',
                )
            conn.close()

    def test_does_not_increment_counter(self):
        from orchestrator.proxy_agent import (
            _reinforce_actr_memories,
            _ActrRetrievalResult,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, _ = _make_db_file(tmpdir)
            _seed_db(db_path, [_make_chunk(chunk_id='c1', traces=[4])])

            retrieval = _ActrRetrievalResult(
                serialized='(unused)',
                chunk_ids=['c1'],
                db_path=db_path,
                interaction_counter=5,
            )
            _reinforce_actr_memories(retrieval)

            conn = open_proxy_db(db_path)
            counter = get_interaction_counter(conn)
            conn.close()
            self.assertEqual(counter, 5,
                             'Reinforcement must not increment the interaction counter')

    def test_empty_retrieval_is_noop(self):
        from orchestrator.proxy_agent import (
            _reinforce_actr_memories,
            _EMPTY_RETRIEVAL,
        )
        # Should not raise
        _reinforce_actr_memories(_EMPTY_RETRIEVAL)


class TestConsultProxyReinforcement(unittest.TestCase):
    """consult_proxy() reinforces after agent runs, not before."""

    def test_reinforcement_called_after_agent_produces_response(self):
        """When the proxy agent produces a response, reinforcement fires."""
        import asyncio
        from orchestrator.proxy_agent import consult_proxy

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, proxy_model_path = _make_db_file(tmpdir)
            _seed_db(db_path, [_make_chunk(chunk_id='c1', traces=[4])])

            mock_embed = lambda text, conn=None, provider=None, model=None: [1.0, 0.0]

            # Mock the agent to return a successful response
            mock_two_pass = MagicMock()
            mock_two_pass.text = 'Approved — the plan looks good.'
            mock_two_pass.confidence = 0.9
            mock_two_pass.prior_action = 'approve'
            mock_two_pass.prior_confidence = 0.85
            mock_two_pass.prior_text = 'Likely approve'
            mock_two_pass.posterior_action = 'approve'
            mock_two_pass.posterior_confidence = 0.9
            mock_two_pass.prediction_delta = ''
            mock_two_pass.salient_percepts = []

            with patch('scripts.memory_indexer.detect_provider', return_value=('test', 'test')), \
                 patch('scripts.memory_indexer.try_embed', side_effect=mock_embed), \
                 patch('scripts.approval_gate.resolve_team_model_path', return_value=proxy_model_path), \
                 patch('scripts.approval_gate.retrieve_similar_interactions', return_value=[]), \
                 patch('orchestrator.proxy_agent.run_proxy_agent', new_callable=AsyncMock, return_value=mock_two_pass), \
                 patch('orchestrator.proxy_agent._calibrate_confidence', return_value=0.9):
                result = asyncio.run(consult_proxy(
                    'Review the security plan',
                    state='PLAN_ASSERT',
                    project_slug='security',
                    proxy_model_path=proxy_model_path,
                    proxy_enabled=True,
                ))

            self.assertTrue(result.from_agent)
            self.assertGreater(result.confidence, 0)

            # The chunk should now be reinforced
            conn = open_proxy_db(db_path)
            loaded = get_chunk(conn, 'c1')
            conn.close()

            self.assertEqual(
                loaded.traces, [4, 5],
                f'Chunk should be reinforced after agent response, got traces={loaded.traces}',
            )

    def test_no_reinforcement_when_agent_fails(self):
        """When the agent produces no text, reinforcement does NOT fire."""
        import asyncio
        from orchestrator.proxy_agent import consult_proxy

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path, proxy_model_path = _make_db_file(tmpdir)
            _seed_db(db_path, [_make_chunk(chunk_id='c1', traces=[4])])

            mock_embed = lambda text, conn=None, provider=None, model=None: [1.0, 0.0]

            # Mock the agent to return empty (failure)
            mock_two_pass = MagicMock()
            mock_two_pass.text = ''
            mock_two_pass.confidence = 0.0

            with patch('scripts.memory_indexer.detect_provider', return_value=('test', 'test')), \
                 patch('scripts.memory_indexer.try_embed', side_effect=mock_embed), \
                 patch('scripts.approval_gate.resolve_team_model_path', return_value=proxy_model_path), \
                 patch('scripts.approval_gate.retrieve_similar_interactions', return_value=[]), \
                 patch('orchestrator.proxy_agent.run_proxy_agent', new_callable=AsyncMock, return_value=mock_two_pass):
                result = asyncio.run(consult_proxy(
                    'Review the security plan',
                    state='PLAN_ASSERT',
                    project_slug='security',
                    proxy_model_path=proxy_model_path,
                    proxy_enabled=True,
                ))

            self.assertEqual(result.text, '')

            # The chunk should NOT be reinforced — agent produced no response
            conn = open_proxy_db(db_path)
            loaded = get_chunk(conn, 'c1')
            conn.close()

            self.assertEqual(
                loaded.traces, [4],
                f'Chunk should NOT be reinforced when agent fails, got traces={loaded.traces}',
            )


if __name__ == '__main__':
    unittest.main()
