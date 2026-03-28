"""Tests for Issue #259: Proxy review session — interactive calibration.

Verifies:
1. Memory introspection: enumerate patterns with activation levels and percepts
2. Correction recording: corrections stored as high-activation review_correction chunks
3. Reinforcement: review reinforcements boost trace on existing chunks
4. Review session lifecycle: open, interact, close via message bus
5. Introspection shows confidence and prediction history
6. Corrections are state-agnostic (empty state) so they surface in all gate contexts
"""
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.proxy_memory import (
    MemoryChunk,
    base_level_activation,
    get_interaction_counter,
    increment_interaction_counter,
    open_proxy_db,
    query_chunks,
    store_chunk,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_temp_db():
    """Create a temporary proxy memory DB. Returns (conn, path)."""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    conn = open_proxy_db(path)
    return conn, path


def _make_gate_chunk(
    conn, *,
    chunk_id='chunk-1',
    state='TASK_ASSERT',
    task_type='my-project',
    outcome='approve',
    content='Approved the migration plan.',
    prior_prediction='approve',
    prior_confidence=0.8,
    posterior_prediction='approve',
    posterior_confidence=0.9,
    salient_percepts=None,
    interaction=None,
):
    """Store a gate_outcome chunk and advance the interaction counter."""
    if interaction is None:
        interaction = increment_interaction_counter(conn)
    chunk = MemoryChunk(
        id=chunk_id,
        type='gate_outcome',
        state=state,
        task_type=task_type,
        outcome=outcome,
        content=content,
        prior_prediction=prior_prediction,
        prior_confidence=prior_confidence,
        posterior_prediction=posterior_prediction,
        posterior_confidence=posterior_confidence,
        salient_percepts=salient_percepts or ['test coverage', 'rollback strategy'],
        traces=[interaction],
    )
    store_chunk(conn, chunk)
    return chunk


def _make_bus(db_path=None):
    """Create a SqliteMessageBus backed by a temp DB."""
    from projects.POC.orchestrator.messaging import SqliteMessageBus
    if db_path is None:
        fd, db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
    return SqliteMessageBus(db_path)


# ── 1. Memory introspection ────────────────────────────────────────────────

class TestMemoryIntrospection(unittest.TestCase):
    """The proxy can introspect its own ACT-R memory for review sessions."""

    def test_introspect_chunks_returns_activation_levels(self):
        """introspect_chunks returns chunks with computed activation."""
        from projects.POC.orchestrator.proxy_review import introspect_chunks

        conn, path = _make_temp_db()
        try:
            _make_gate_chunk(conn, chunk_id='c1')
            _make_gate_chunk(conn, chunk_id='c2', state='WORK_ASSERT',
                             outcome='correct', content='Corrected missing tests.')
            current = get_interaction_counter(conn)

            result = introspect_chunks(conn, current_interaction=current)

            self.assertGreater(len(result), 0)
            for entry in result:
                self.assertIn('chunk', entry)
                self.assertIn('activation', entry)
                self.assertIsInstance(entry['activation'], float)
                self.assertIn('age', entry)
        finally:
            conn.close()
            os.unlink(path)

    def test_introspect_chunks_shows_prediction_history(self):
        """Each introspected chunk includes prior/posterior predictions and confidence."""
        from projects.POC.orchestrator.proxy_review import introspect_chunks

        conn, path = _make_temp_db()
        try:
            _make_gate_chunk(conn, chunk_id='c1',
                             prior_prediction='approve', prior_confidence=0.7,
                             posterior_prediction='correct', posterior_confidence=0.85)
            current = get_interaction_counter(conn)

            result = introspect_chunks(conn, current_interaction=current)

            self.assertEqual(len(result), 1)
            entry = result[0]
            self.assertEqual(entry['chunk'].prior_prediction, 'approve')
            self.assertAlmostEqual(entry['chunk'].prior_confidence, 0.7)
            self.assertEqual(entry['chunk'].posterior_prediction, 'correct')
            self.assertAlmostEqual(entry['chunk'].posterior_confidence, 0.85)
        finally:
            conn.close()
            os.unlink(path)

    def test_introspect_chunks_shows_salient_percepts(self):
        """Introspected chunks include salient percepts."""
        from projects.POC.orchestrator.proxy_review import introspect_chunks

        conn, path = _make_temp_db()
        try:
            _make_gate_chunk(conn, chunk_id='c1',
                             salient_percepts=['test coverage', 'error handling'])
            current = get_interaction_counter(conn)

            result = introspect_chunks(conn, current_interaction=current)

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]['chunk'].salient_percepts,
                             ['test coverage', 'error handling'])
        finally:
            conn.close()
            os.unlink(path)

    def test_introspect_sorted_by_activation_descending(self):
        """Chunks are sorted by activation level, highest first."""
        from projects.POC.orchestrator.proxy_review import introspect_chunks

        conn, path = _make_temp_db()
        try:
            # Create chunks at different interaction times — older chunk has lower activation
            i1 = increment_interaction_counter(conn)
            c1 = MemoryChunk(id='old', type='gate_outcome', state='s', task_type='t',
                             outcome='approve', content='old', traces=[i1])
            store_chunk(conn, c1)

            # Advance counter several times to create age gap
            for _ in range(10):
                increment_interaction_counter(conn)

            i2 = increment_interaction_counter(conn)
            c2 = MemoryChunk(id='new', type='gate_outcome', state='s', task_type='t',
                             outcome='approve', content='new', traces=[i2])
            store_chunk(conn, c2)

            current = get_interaction_counter(conn)
            result = introspect_chunks(conn, current_interaction=current)

            self.assertGreaterEqual(len(result), 2)
            # Newer chunk should have higher activation
            self.assertGreaterEqual(result[0]['activation'], result[1]['activation'])
        finally:
            conn.close()
            os.unlink(path)

    def test_format_introspection_for_display(self):
        """format_introspection produces human-readable markdown."""
        from projects.POC.orchestrator.proxy_review import (
            format_introspection,
            introspect_chunks,
        )

        conn, path = _make_temp_db()
        try:
            _make_gate_chunk(conn, chunk_id='c1', outcome='approve',
                             salient_percepts=['test coverage'])
            current = get_interaction_counter(conn)
            entries = introspect_chunks(conn, current_interaction=current)

            text = format_introspection(entries)

            self.assertIn('approve', text)
            self.assertIn('test coverage', text)
            self.assertIn('activation', text.lower())
        finally:
            conn.close()
            os.unlink(path)


# ── 2. Correction recording ────────────────────────────────────────────────

class TestCorrectionRecording(unittest.TestCase):
    """Corrections from review sessions are recorded as high-activation chunks."""

    def test_record_correction_creates_review_correction_chunk(self):
        """record_correction stores a chunk with type='review_correction'."""
        from projects.POC.orchestrator.proxy_review import record_correction

        conn, path = _make_temp_db()
        try:
            chunk_id = record_correction(
                conn,
                correction='Stop flagging missing rollback strategies for internal tools.',
                source='darrell',
            )

            chunk = conn.execute(
                'SELECT * FROM proxy_chunks WHERE id = ?', (chunk_id,),
            ).fetchone()
            self.assertIsNotNone(chunk)
            self.assertEqual(chunk['type'], 'review_correction')
            self.assertIn('rollback', chunk['content'])
        finally:
            conn.close()
            os.unlink(path)

    def test_correction_has_high_activation_traces(self):
        """Corrections get multiple initial traces for elevated activation."""
        from projects.POC.orchestrator.proxy_review import (
            CORRECTION_ACTIVATION_BOOST,
            record_correction,
        )

        conn, path = _make_temp_db()
        try:
            chunk_id = record_correction(
                conn,
                correction='Care more about test coverage.',
                source='darrell',
            )

            chunks = query_chunks(conn, type='review_correction')
            self.assertEqual(len(chunks), 1)
            # Correction should have boosted traces
            self.assertGreaterEqual(len(chunks[0].traces), CORRECTION_ACTIVATION_BOOST)
        finally:
            conn.close()
            os.unlink(path)

    def test_correction_has_empty_state(self):
        """Corrections are state-agnostic so they surface in all gate contexts."""
        from projects.POC.orchestrator.proxy_review import record_correction

        conn, path = _make_temp_db()
        try:
            record_correction(conn, correction='Test.', source='darrell')

            chunks = query_chunks(conn, type='review_correction')
            self.assertEqual(len(chunks), 1)
            self.assertEqual(chunks[0].state, '')
        finally:
            conn.close()
            os.unlink(path)

    def test_correction_surfaces_in_state_scoped_query(self):
        """Corrections with empty state surface when querying any CfA state."""
        from projects.POC.orchestrator.proxy_review import record_correction

        conn, path = _make_temp_db()
        try:
            record_correction(
                conn, correction='Always check for rollback.', source='darrell',
            )

            # Query with a specific state — correction should still surface
            # because query_chunks includes type='steering' OR-logic
            # and review_correction needs the same treatment
            chunks = query_chunks(conn, state='TASK_ASSERT')
            found = [c for c in chunks if c.type == 'review_correction']
            self.assertEqual(len(found), 1)
        finally:
            conn.close()
            os.unlink(path)

    def test_correction_stores_source_attribution(self):
        """The human who made the correction is recorded for attribution."""
        from projects.POC.orchestrator.proxy_review import record_correction

        conn, path = _make_temp_db()
        try:
            record_correction(conn, correction='Test.', source='darrell')

            chunks = query_chunks(conn, type='review_correction')
            self.assertEqual(chunks[0].task_type, 'darrell')
        finally:
            conn.close()
            os.unlink(path)


# ── 3. Reinforcement ───────────────────────────────────────────────────────

class TestReviewReinforcement(unittest.TestCase):
    """Review reinforcements boost activation on existing chunks."""

    def test_reinforce_chunk_adds_trace(self):
        """reinforce_chunk adds a trace to the target chunk."""
        from projects.POC.orchestrator.proxy_review import reinforce_chunk

        conn, path = _make_temp_db()
        try:
            chunk = _make_gate_chunk(conn, chunk_id='c1')
            original_traces = len(chunk.traces)

            reinforce_chunk(conn, chunk_id='c1')

            updated = query_chunks(conn)
            target = [c for c in updated if c.id == 'c1'][0]
            self.assertGreater(len(target.traces), original_traces)
        finally:
            conn.close()
            os.unlink(path)

    def test_reinforce_increases_activation(self):
        """Reinforcement increases the chunk's base-level activation."""
        from projects.POC.orchestrator.proxy_review import reinforce_chunk

        conn, path = _make_temp_db()
        try:
            chunk = _make_gate_chunk(conn, chunk_id='c1')
            current = get_interaction_counter(conn)
            activation_before = base_level_activation(chunk.traces, current)

            reinforce_chunk(conn, chunk_id='c1')

            updated = query_chunks(conn)
            target = [c for c in updated if c.id == 'c1'][0]
            current_after = get_interaction_counter(conn)
            activation_after = base_level_activation(target.traces, current_after)

            self.assertGreater(activation_after, activation_before)
        finally:
            conn.close()
            os.unlink(path)

    def test_reinforce_nonexistent_chunk_raises(self):
        """Reinforcing a nonexistent chunk raises ValueError."""
        from projects.POC.orchestrator.proxy_review import reinforce_chunk

        conn, path = _make_temp_db()
        try:
            with self.assertRaises(ValueError):
                reinforce_chunk(conn, chunk_id='nonexistent')
        finally:
            conn.close()
            os.unlink(path)


# ── 4. Review session lifecycle ────────────────────────────────────────────

class TestReviewSessionLifecycle(unittest.TestCase):
    """Review session opens, interacts, and closes via message bus."""

    def test_open_review_session_creates_proxy_review_conversation(self):
        """open_review_session creates a PROXY_REVIEW conversation."""
        from projects.POC.orchestrator.messaging import ConversationType
        from projects.POC.orchestrator.proxy_review import open_review_session

        bus = _make_bus()
        try:
            session = open_review_session(bus, human_name='darrell')

            self.assertIsNotNone(session)
            self.assertEqual(session.conversation_id, 'proxy:darrell')

            conv = bus.get_conversation('proxy:darrell')
            self.assertIsNotNone(conv)
            self.assertEqual(conv.type, ConversationType.PROXY_REVIEW)
        finally:
            bus.close()

    def test_open_review_session_is_idempotent(self):
        """Opening a review session twice returns the same conversation."""
        from projects.POC.orchestrator.proxy_review import open_review_session

        bus = _make_bus()
        try:
            s1 = open_review_session(bus, human_name='darrell')
            s2 = open_review_session(bus, human_name='darrell')

            self.assertEqual(s1.conversation_id, s2.conversation_id)
        finally:
            bus.close()

    def test_review_session_records_messages(self):
        """Messages sent during review are recorded on the message bus."""
        from projects.POC.orchestrator.proxy_review import open_review_session

        bus = _make_bus()
        try:
            session = open_review_session(bus, human_name='darrell')

            bus.send(session.conversation_id, 'darrell',
                     'What patterns have you picked up?')
            bus.send(session.conversation_id, 'proxy',
                     'I have noticed you care about test coverage.')

            messages = bus.receive(session.conversation_id)
            self.assertEqual(len(messages), 2)
            self.assertEqual(messages[0].sender, 'darrell')
            self.assertEqual(messages[1].sender, 'proxy')
        finally:
            bus.close()

    def test_review_session_has_human_and_db_path(self):
        """ReviewSession carries the human name and memory DB path."""
        from projects.POC.orchestrator.proxy_review import open_review_session

        bus = _make_bus()
        try:
            session = open_review_session(
                bus, human_name='darrell', memory_db_path='/tmp/test.db',
            )

            self.assertEqual(session.human_name, 'darrell')
            self.assertEqual(session.memory_db_path, '/tmp/test.db')
        finally:
            bus.close()


# ── 5. Accuracy summary ───────────────────────────────────────────────────

class TestAccuracySummary(unittest.TestCase):
    """Review session can show proxy accuracy and confidence summary."""

    def test_summarize_accuracy_with_data(self):
        """summarize_accuracy returns formatted accuracy when data exists."""
        from projects.POC.orchestrator.proxy_review import summarize_accuracy

        conn, path = _make_temp_db()
        try:
            # Insert accuracy data
            conn.execute(
                """INSERT INTO proxy_accuracy
                   (state, task_type, prior_correct, prior_total,
                    posterior_correct, posterior_total, last_updated)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                ('TASK_ASSERT', 'my-project', 7, 10, 9, 10, '2026-03-27'),
            )
            conn.commit()

            text = summarize_accuracy(conn)

            self.assertIn('TASK_ASSERT', text)
            self.assertIn('90', text)  # 9/10 = 90%
        finally:
            conn.close()
            os.unlink(path)

    def test_summarize_accuracy_empty(self):
        """summarize_accuracy returns a message when no data exists."""
        from projects.POC.orchestrator.proxy_review import summarize_accuracy

        conn, path = _make_temp_db()
        try:
            text = summarize_accuracy(conn)
            self.assertIn('no', text.lower())
        finally:
            conn.close()
            os.unlink(path)


if __name__ == '__main__':
    unittest.main()
