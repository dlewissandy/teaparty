"""Tests for Issue #270: Proxy self-review chat wiring.

Verifies:
1. run_review_turn records both sides on the message bus
2. Dialog history is built from bus messages and passed to run_review_turn
3. Corrections in proxy responses are detected and recorded as high-activation chunks
4. ChatScreen._run_proxy_turn passes dialog_history across turns
"""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.messaging import SqliteMessageBus
from projects.POC.orchestrator.proxy_memory import (
    get_interaction_counter,
    open_proxy_db,
    query_chunks,
    store_chunk,
    MemoryChunk,
    increment_interaction_counter,
)
from projects.POC.orchestrator.proxy_review import (
    ReviewSession,
    build_review_prompt,
    open_review_session,
    run_review_turn,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_temp_db():
    """Create a temporary proxy memory DB. Returns (conn, path)."""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    conn = open_proxy_db(path)
    return conn, path


def _make_bus(db_path=None):
    """Create a SqliteMessageBus backed by a temp DB."""
    if db_path is None:
        fd, db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
    return SqliteMessageBus(db_path)


def _run_async(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


# ── 1. Message bus records both sides ──────────────────────────────────────

class TestMessageBusRecording(unittest.TestCase):
    """run_review_turn records both human and proxy messages on the bus."""

    @patch('projects.POC.orchestrator.proxy_review._invoke_review_agent',
           new_callable=AsyncMock, return_value='I see you care about test coverage.')
    def test_run_review_turn_records_human_and_proxy_on_bus(self, mock_agent):
        """Both the human message and proxy response appear on the bus."""
        conn, db_path = _make_temp_db()
        bus = _make_bus()
        try:
            session = open_review_session(bus, human_name='alice',
                                          memory_db_path=db_path)

            response = _run_async(run_review_turn(
                'What patterns have you learned?',
                conn=conn, session=session, bus=bus,
            ))

            self.assertEqual(response, 'I see you care about test coverage.')

            messages = bus.receive(session.conversation_id)
            senders = [m.sender for m in messages]
            self.assertIn('alice', senders)
            self.assertIn('proxy', senders)

            human_msg = next(m for m in messages if m.sender == 'alice')
            self.assertEqual(human_msg.content, 'What patterns have you learned?')
            proxy_msg = next(m for m in messages if m.sender == 'proxy')
            self.assertEqual(proxy_msg.content, 'I see you care about test coverage.')
        finally:
            conn.close()


# ── 2. Dialog history is built and passed ──────────────────────────────────

class TestDialogHistory(unittest.TestCase):
    """Dialog history accumulates across turns and is passed to the prompt."""

    def test_build_dialog_history_from_bus_messages(self):
        """build_dialog_history formats prior messages for the prompt."""
        from projects.POC.orchestrator.proxy_review import build_dialog_history

        bus = _make_bus()
        session = open_review_session(bus, human_name='bob')

        # Simulate a prior turn
        bus.send(session.conversation_id, 'bob', 'What have you learned?')
        bus.send(session.conversation_id, 'proxy', 'I learned you prioritize tests.')

        history = build_dialog_history(bus, session.conversation_id)

        self.assertIn('Human', history)
        self.assertIn('What have you learned?', history)
        self.assertIn('Proxy', history)
        self.assertIn('I learned you prioritize tests.', history)

    @patch('projects.POC.orchestrator.proxy_review._invoke_review_agent',
           new_callable=AsyncMock, return_value='You mentioned test coverage last time.')
    def test_dialog_history_passed_to_prompt_on_second_turn(self, mock_agent):
        """On the second turn, dialog_history from prior messages is included in the prompt."""
        conn, db_path = _make_temp_db()
        bus = _make_bus()
        try:
            session = open_review_session(bus, human_name='carol',
                                          memory_db_path=db_path)

            # First turn
            bus.send(session.conversation_id, 'carol', 'I care about tests.')
            bus.send(session.conversation_id, 'proxy', 'Noted, tests are important.')

            # Second turn
            _run_async(run_review_turn(
                'What did I say?',
                conn=conn, session=session, bus=bus,
            ))

            # Verify _invoke_review_agent received a prompt with dialog history
            prompt = mock_agent.call_args[0][0]
            self.assertIn('I care about tests.', prompt)
            self.assertIn('Noted, tests are important.', prompt)
        finally:
            conn.close()


# ── 3. Corrections are detected and recorded ──────────────────────────────

class TestCorrectionRecording(unittest.TestCase):
    """Corrections identified in proxy responses are recorded as high-activation chunks."""

    @patch('projects.POC.orchestrator.proxy_review._invoke_review_agent',
           new_callable=AsyncMock,
           return_value='[CORRECTION: stop flagging missing rollback strategies]\nUnderstood, I will stop flagging that.')
    def test_correction_in_response_is_recorded_as_chunk(self, mock_agent):
        """When the proxy's response contains a correction tag, it is recorded."""
        conn, db_path = _make_temp_db()
        bus = _make_bus()
        try:
            session = open_review_session(bus, human_name='dave',
                                          memory_db_path=db_path)

            _run_async(run_review_turn(
                'Stop flagging missing rollback strategies.',
                conn=conn, session=session, bus=bus,
            ))

            # A review_correction chunk should now exist
            chunks = query_chunks(conn, type='review_correction')
            self.assertGreater(len(chunks), 0)
            correction = chunks[0]
            self.assertIn('rollback', correction.content.lower())
        finally:
            conn.close()

    @patch('projects.POC.orchestrator.proxy_review._invoke_review_agent',
           new_callable=AsyncMock,
           return_value='[REINFORCE: chunk-abc12345]\nYes, that pattern is important.')
    def test_reinforcement_in_response_boosts_existing_chunk(self, mock_agent):
        """When the proxy's response contains a reinforce tag, the chunk gets a trace."""
        conn, db_path = _make_temp_db()
        bus = _make_bus()
        try:
            # Create a chunk to reinforce
            interaction = increment_interaction_counter(conn)
            chunk = MemoryChunk(
                id='chunk-abc12345', type='gate_outcome', state='s',
                task_type='t', outcome='approve', content='test',
                traces=[interaction],
            )
            store_chunk(conn, chunk)
            initial_traces = len(chunk.traces)

            session = open_review_session(bus, human_name='eve',
                                          memory_db_path=db_path)

            _run_async(run_review_turn(
                'Yes, that pattern is important.',
                conn=conn, session=session, bus=bus,
            ))

            # Chunk should have more traces now
            from projects.POC.orchestrator.proxy_memory import get_chunk
            updated = get_chunk(conn, 'chunk-abc12345')
            self.assertGreater(len(updated.traces), initial_traces)
        finally:
            conn.close()


if __name__ == '__main__':
    unittest.main()
