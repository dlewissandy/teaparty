"""Tests for issue #250: Steering chunks in shared proxy memory for cross-conversation learning.

Verifies:
1. query_chunks supports a type filter parameter
2. retrieve_chunks supports a type filter parameter
3. Office manager can store steering chunks as MemoryChunk in proxy_chunks
4. Proxy retrieval naturally surfaces steering chunks at gates (activation-based)
5. Office manager can read gate_outcome chunks for status reporting
6. Cross-store visibility: OM writes steering, proxy sees it; proxy writes gate_outcome, OM reads it
"""
import os
import shutil
import tempfile
import unittest
import uuid

from projects.POC.orchestrator.proxy_memory import (
    MemoryChunk,
    open_proxy_db,
    query_chunks,
    retrieve_chunks,
    store_chunk,
)


def _make_chunk(
    *,
    chunk_type='gate_outcome',
    state='REVIEW',
    task_type='poc',
    outcome='approve',
    content='test chunk',
    traces=None,
    **kwargs,
):
    """Create a MemoryChunk with sensible defaults."""
    return MemoryChunk(
        id=uuid.uuid4().hex,
        type=chunk_type,
        state=state,
        task_type=task_type,
        outcome=outcome,
        content=content,
        traces=traces or [1],
        **kwargs,
    )


class TestQueryChunksTypeFilter(unittest.TestCase):
    """query_chunks supports filtering by chunk type."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmp, '.proxy-memory.db')
        self.conn = open_proxy_db(self.db_path)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_type_filter_returns_only_matching_type(self):
        """query_chunks(type='steering') returns only steering chunks."""
        store_chunk(self.conn, _make_chunk(chunk_type='gate_outcome'))
        store_chunk(self.conn, _make_chunk(chunk_type='steering', state='', outcome=''))
        store_chunk(self.conn, _make_chunk(chunk_type='gate_outcome'))

        results = query_chunks(self.conn, type='steering')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].type, 'steering')

    def test_type_filter_gate_outcome(self):
        """query_chunks(type='gate_outcome') excludes steering chunks."""
        store_chunk(self.conn, _make_chunk(chunk_type='gate_outcome'))
        store_chunk(self.conn, _make_chunk(chunk_type='steering', state='', outcome=''))

        results = query_chunks(self.conn, type='gate_outcome')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].type, 'gate_outcome')

    def test_no_type_filter_returns_all(self):
        """query_chunks with no type filter returns all chunk types."""
        store_chunk(self.conn, _make_chunk(chunk_type='gate_outcome'))
        store_chunk(self.conn, _make_chunk(chunk_type='steering', state='', outcome=''))

        results = query_chunks(self.conn)
        self.assertEqual(len(results), 2)


class TestRetrieveChunksTypeFilter(unittest.TestCase):
    """retrieve_chunks supports filtering by chunk type."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmp, '.proxy-memory.db')
        self.conn = open_proxy_db(self.db_path)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_retrieve_with_type_filter(self):
        """retrieve_chunks(type='steering') only considers steering chunks."""
        store_chunk(self.conn, _make_chunk(chunk_type='gate_outcome', traces=[1, 2, 3]))
        store_chunk(self.conn, _make_chunk(
            chunk_type='steering', state='', outcome='',
            content='Focus on security', traces=[1, 2],
        ))

        results = retrieve_chunks(
            self.conn, type='steering', current_interaction=5,
            tau=-10.0,  # low threshold to ensure retrieval
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].type, 'steering')
        self.assertIn('security', results[0].content)


class TestSteeringChunkStorage(unittest.TestCase):
    """Office manager stores steering chunks as MemoryChunk in proxy_chunks."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmp, '.proxy-memory.db')
        self.conn = open_proxy_db(self.db_path)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_store_steering_chunk(self):
        """A steering chunk stored via store_chunk is queryable."""
        from projects.POC.orchestrator.proxy_memory import record_steering_chunk
        chunk_id = record_steering_chunk(
            self.conn,
            content='Focus on security across all sessions',
            source='darrell',
            current_interaction=5,
        )
        results = query_chunks(self.conn, type='steering')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, 'Focus on security across all sessions')
        self.assertEqual(results[0].id, chunk_id)

    def test_steering_chunk_has_traces(self):
        """Steering chunks have traces for activation decay."""
        from projects.POC.orchestrator.proxy_memory import record_steering_chunk
        record_steering_chunk(
            self.conn,
            content='Worried about migration',
            source='darrell',
            current_interaction=10,
        )
        results = query_chunks(self.conn, type='steering')
        self.assertEqual(results[0].traces, [10])

    def test_steering_chunk_has_source_in_task_type(self):
        """Steering chunk source is stored in task_type for attribution."""
        from projects.POC.orchestrator.proxy_memory import record_steering_chunk
        record_steering_chunk(
            self.conn,
            content='test',
            source='darrell',
            current_interaction=1,
        )
        results = query_chunks(self.conn, type='steering')
        self.assertEqual(results[0].task_type, 'darrell')


class TestCrossConversationRetrieval(unittest.TestCase):
    """Cross-conversation learning: steering surfaces at gates, gate outcomes surface for OM."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmp, '.proxy-memory.db')
        self.conn = open_proxy_db(self.db_path)

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_steering_surfaces_in_proxy_retrieval(self):
        """A steering chunk surfaces in retrieve_chunks alongside gate_outcome chunks."""
        # Proxy stores gate outcome
        store_chunk(self.conn, _make_chunk(
            chunk_type='gate_outcome', state='REVIEW', outcome='approve',
            content='Approved migration plan', traces=[1, 2, 3],
        ))
        # Office manager stores steering
        from projects.POC.orchestrator.proxy_memory import record_steering_chunk
        record_steering_chunk(
            self.conn,
            content='Worried about the database migration',
            source='darrell',
            current_interaction=4,
        )

        # Proxy retrieves all chunks (no type filter) — steering should appear
        results = retrieve_chunks(
            self.conn, current_interaction=5,
            tau=-10.0,
        )
        types = {c.type for c in results}
        self.assertIn('steering', types)
        self.assertIn('gate_outcome', types)

    def test_steering_surfaces_with_state_filter(self):
        """Steering chunks surface even when proxy filters by CfA state.

        The proxy passes state='REVIEW' (or similar) to retrieve_chunks.
        Steering chunks have state='' because they are state-agnostic.
        They must still appear in results — this is the core cross-conversation
        learning path described in the proposal.
        """
        store_chunk(self.conn, _make_chunk(
            chunk_type='gate_outcome', state='REVIEW', outcome='approve',
            content='Approved plan', traces=[1, 2, 3],
        ))
        from projects.POC.orchestrator.proxy_memory import record_steering_chunk
        record_steering_chunk(
            self.conn,
            content='Worried about the database migration',
            source='darrell',
            current_interaction=4,
        )

        # Proxy retrieves with state filter — steering must still appear
        results = retrieve_chunks(
            self.conn, state='REVIEW', current_interaction=5,
            tau=-10.0,
        )
        types = {c.type for c in results}
        self.assertIn('steering', types,
                       'Steering chunks must surface even when proxy filters by CfA state')
        self.assertIn('gate_outcome', types)

    def test_steering_surfaces_with_task_type_filter(self):
        """Steering chunks surface even when proxy filters by task_type."""
        store_chunk(self.conn, _make_chunk(
            chunk_type='gate_outcome', state='REVIEW', task_type='poc',
            outcome='approve', traces=[1, 2, 3],
        ))
        from projects.POC.orchestrator.proxy_memory import record_steering_chunk
        record_steering_chunk(
            self.conn,
            content='Focus on security',
            source='darrell',
            current_interaction=4,
        )

        results = query_chunks(self.conn, task_type='poc')
        types = {c.type for c in results}
        self.assertIn('steering', types,
                       'Steering chunks must surface even when filtering by task_type')

    def test_om_reads_gate_outcomes(self):
        """Office manager can read gate_outcome chunks for status reporting."""
        from projects.POC.orchestrator.proxy_memory import query_gate_outcomes
        store_chunk(self.conn, _make_chunk(
            chunk_type='gate_outcome', state='REVIEW', outcome='correct',
            content='Corrected migration plan', task_type='poc',
        ))
        store_chunk(self.conn, _make_chunk(
            chunk_type='steering', state='', outcome='',
            content='Focus on security',
        ))

        outcomes = query_gate_outcomes(self.conn)
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].type, 'gate_outcome')
        self.assertEqual(outcomes[0].outcome, 'correct')

    def test_om_reads_gate_outcomes_by_task(self):
        """Office manager can filter gate outcomes by task_type."""
        from projects.POC.orchestrator.proxy_memory import query_gate_outcomes
        store_chunk(self.conn, _make_chunk(
            chunk_type='gate_outcome', task_type='poc', outcome='approve',
        ))
        store_chunk(self.conn, _make_chunk(
            chunk_type='gate_outcome', task_type='other', outcome='correct',
        ))

        results = query_gate_outcomes(self.conn, task_type='poc')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].task_type, 'poc')


class TestOfficeManagerMemoryStoreIntegration(unittest.TestCase):
    """MemoryStore in office_manager.py writes steering to proxy_chunks."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmp, '.proxy-memory.db')

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_memory_store_steering_writes_to_proxy_chunks(self):
        """MemoryStore.record_steering() writes to proxy_chunks, not memory_chunks."""
        from projects.POC.orchestrator.office_manager import MemoryStore
        store = MemoryStore(self.db_path)
        store.record_steering(
            content='Focus on security',
            source='darrell',
            current_interaction=5,
        )
        # Verify via proxy_memory's query_chunks
        conn = open_proxy_db(self.db_path)
        results = query_chunks(conn, type='steering')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].content, 'Focus on security')
        conn.close()

    def test_memory_store_reads_gate_outcomes(self):
        """MemoryStore.get_gate_outcomes() reads from proxy_chunks."""
        conn = open_proxy_db(self.db_path)
        store_chunk(conn, _make_chunk(
            chunk_type='gate_outcome', outcome='correct',
            content='Corrected plan',
        ))
        conn.close()

        from projects.POC.orchestrator.office_manager import MemoryStore
        store = MemoryStore(self.db_path)
        outcomes = store.get_gate_outcomes()
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(outcomes[0].outcome, 'correct')


if __name__ == '__main__':
    unittest.main()
