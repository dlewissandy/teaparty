#!/usr/bin/env python3
"""Tests for issue #388 — chat filter buttons for all stream event types.

The chat filter bar has 9 buttons: agent, human, thinking, tools, results,
system, state, cost, log.  The _on_stream_event handler in engine.py must
relay stream events with sender values that match the chat.html filter
predicates.

These tests verify that each stream event type produces messages with the
correct sender value in the message bus.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from orchestrator.messaging import SqliteMessageBus


class TestStreamEventRelay(unittest.TestCase):
    """_on_stream_event relays stream events with correct sender values."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._tmpdir, 'messages.db')
        self._bus = SqliteMessageBus(self._db_path)
        self._conv_id = 'job:test-project:test-session'

    def tearDown(self):
        self._bus.close()

    def _get_handler(self):
        """Return the stream event relay function under test."""
        from orchestrator.engine import _make_stream_event_handler
        return _make_stream_event_handler(self._bus, self._conv_id)

    def _messages(self):
        return self._bus.receive(self._conv_id)

    # ── assistant text → sender='agent' ──────────────────────────────────

    def test_assistant_text_string_content_sent_as_agent(self):
        """Assistant event with string content produces sender='agent'."""
        handler = self._get_handler()
        handler({'type': 'assistant', 'message': {'content': 'Hello world'}})
        msgs = self._messages()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].sender, 'agent')
        self.assertEqual(msgs[0].content, 'Hello world')

    def test_assistant_text_block_content_sent_as_agent(self):
        """Assistant event with content block array (text type) produces sender='agent'."""
        handler = self._get_handler()
        handler({'type': 'assistant', 'message': {
            'content': [{'type': 'text', 'text': 'Block text'}],
        }})
        msgs = self._messages()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].sender, 'agent')
        self.assertEqual(msgs[0].content, 'Block text')

    # ── thinking → sender='thinking' ─────────────────────────────────────

    def test_thinking_block_sent_as_thinking(self):
        """Assistant event with thinking content block produces sender='thinking'."""
        handler = self._get_handler()
        handler({'type': 'assistant', 'message': {
            'content': [{'type': 'thinking', 'thinking': 'Let me consider...'}],
        }})
        msgs = self._messages()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].sender, 'thinking')
        self.assertEqual(msgs[0].content, 'Let me consider...')

    def test_mixed_text_and_thinking_blocks_produce_separate_messages(self):
        """Assistant with both text and thinking blocks produces two messages."""
        handler = self._get_handler()
        handler({'type': 'assistant', 'message': {
            'content': [
                {'type': 'thinking', 'thinking': 'Hmm...'},
                {'type': 'text', 'text': 'Here is my answer'},
            ],
        }})
        msgs = self._messages()
        self.assertEqual(len(msgs), 2)
        senders = {m.sender for m in msgs}
        self.assertEqual(senders, {'agent', 'thinking'})

    # ── tool_use → sender='tool_use' ─────────────────────────────────────

    def test_tool_use_event_sent_as_tool_use(self):
        """tool_use stream event produces sender='tool_use'."""
        handler = self._get_handler()
        handler({
            'type': 'tool_use',
            'tool_use_id': 'abc123',
            'name': 'Read',
            'input': {'file_path': '/tmp/test.py'},
        })
        msgs = self._messages()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].sender, 'tool_use')
        self.assertIn('Read', msgs[0].content)

    # ── tool_result → sender='tool_result' ───────────────────────────────

    def test_tool_result_event_sent_as_tool_result(self):
        """tool_result stream event produces sender='tool_result'."""
        handler = self._get_handler()
        handler({
            'type': 'tool_result',
            'tool_use_id': 'abc123',
            'content': 'file contents here',
        })
        msgs = self._messages()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].sender, 'tool_result')
        self.assertEqual(msgs[0].content, 'file contents here')

    # ── system → sender='system' ─────────────────────────────────────────

    def test_system_init_event_sent_as_system(self):
        """system/init stream event produces sender='system'."""
        handler = self._get_handler()
        handler({
            'type': 'system',
            'subtype': 'init',
            'session_id': 'sess-123',
        })
        msgs = self._messages()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].sender, 'system')

    # ── result → sender='agent' (existing behavior) ─────────────────────

    def test_result_event_sent_as_agent(self):
        """result stream event produces sender='agent' (unchanged)."""
        handler = self._get_handler()
        handler({'type': 'result', 'result': 'Final output'})
        msgs = self._messages()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].sender, 'agent')
        self.assertEqual(msgs[0].content, 'Final output')

    # ── Edge cases ───────────────────────────────────────────────────────

    def test_empty_assistant_content_not_sent(self):
        """Assistant event with empty content produces no message."""
        handler = self._get_handler()
        handler({'type': 'assistant', 'message': {'content': ''}})
        self.assertEqual(len(self._messages()), 0)

    def test_empty_tool_result_not_sent(self):
        """tool_result with empty content produces no message."""
        handler = self._get_handler()
        handler({'type': 'tool_result', 'tool_use_id': 'x', 'content': ''})
        self.assertEqual(len(self._messages()), 0)


if __name__ == '__main__':
    unittest.main()
