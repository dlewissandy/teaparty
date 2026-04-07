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

    def test_tool_result_array_content_joined(self):
        """tool_result with content block array is joined into a string."""
        handler = self._get_handler()
        handler({
            'type': 'tool_result',
            'tool_use_id': 'abc123',
            'content': [
                {'type': 'text', 'text': 'line one'},
                {'type': 'text', 'text': 'line two'},
            ],
        })
        msgs = self._messages()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].sender, 'tool_result')
        self.assertIn('line one', msgs[0].content)
        self.assertIn('line two', msgs[0].content)

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

    # ── tool_use as content block within assistant ─────────────────────

    def test_tool_use_content_block_sent_as_tool_use(self):
        """tool_use block within assistant content produces sender='tool_use'."""
        handler = self._get_handler()
        handler({'type': 'assistant', 'message': {
            'content': [
                {'type': 'text', 'text': 'I will read the file'},
                {'type': 'tool_use', 'id': 'tu_001', 'name': 'Read',
                 'input': {'file_path': '/tmp/x.py'}},
            ],
        }})
        msgs = self._messages()
        senders = [(m.sender, m.content) for m in msgs]
        self.assertEqual(len(msgs), 2)
        self.assertEqual(senders[0], ('agent', 'I will read the file'))
        self.assertEqual(senders[1][0], 'tool_use')
        self.assertIn('Read', senders[1][1])

    def test_duplicate_tool_use_deduplicated(self):
        """Same tool_use_id from content block and top-level event produces one message."""
        handler = self._get_handler()
        # First: assistant event with tool_use content block
        handler({'type': 'assistant', 'message': {
            'content': [
                {'type': 'tool_use', 'id': 'tu_dup', 'name': 'Grep',
                 'input': {'pattern': 'foo'}},
            ],
        }})
        # Then: top-level tool_use event with the same ID
        handler({
            'type': 'tool_use',
            'tool_use_id': 'tu_dup',
            'name': 'Grep',
            'input': {'pattern': 'foo'},
        })
        msgs = [m for m in self._messages() if m.sender == 'tool_use']
        self.assertEqual(len(msgs), 1)

    # ── tool_result inside user event ────────────────────────────────────

    def test_tool_result_in_user_event_sent_as_tool_result(self):
        """tool_result block within a user event produces sender='tool_result'."""
        handler = self._get_handler()
        handler({'type': 'user', 'message': {
            'content': [
                {'type': 'tool_result', 'tool_use_id': 'tr_001',
                 'content': 'result from tool'},
            ],
        }})
        msgs = self._messages()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].sender, 'tool_result')
        self.assertEqual(msgs[0].content, 'result from tool')

    def test_duplicate_tool_result_deduplicated(self):
        """Same tool_use_id from user event and top-level event produces one message."""
        handler = self._get_handler()
        # First: top-level tool_result
        handler({
            'type': 'tool_result',
            'tool_use_id': 'tr_dup',
            'content': 'first occurrence',
        })
        # Then: user event with same tool_result
        handler({'type': 'user', 'message': {
            'content': [
                {'type': 'tool_result', 'tool_use_id': 'tr_dup',
                 'content': 'first occurrence'},
            ],
        }})
        msgs = [m for m in self._messages() if m.sender == 'tool_result']
        self.assertEqual(len(msgs), 1)

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


class TestIterStreamEvents(unittest.TestCase):
    """_iter_stream_events handles all event representations with deduplication."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._stream_path = os.path.join(self._tmpdir, 'stream.jsonl')

    def _write_events(self, events):
        import json
        with open(self._stream_path, 'w') as f:
            for ev in events:
                f.write(json.dumps(ev) + '\n')

    def _iter(self, agent_role='test-agent'):
        from orchestrator.office_manager import _iter_stream_events
        return list(_iter_stream_events(self._stream_path, agent_role))

    # ── top-level tool_use ───────────────────────────────────────────────

    def test_top_level_tool_use_yielded(self):
        """Top-level tool_use event produces ('tool_use', ...)."""
        self._write_events([{
            'type': 'tool_use',
            'tool_use_id': 'tu_top',
            'name': 'Read',
            'input': {'file_path': '/tmp/x.py'},
        }])
        results = self._iter()
        tool_uses = [(s, c) for s, c in results if s == 'tool_use']
        self.assertEqual(len(tool_uses), 1)
        self.assertIn('Read', tool_uses[0][1])

    def test_duplicate_tool_use_from_block_and_top_level_deduplicated(self):
        """Same tool_use_id from content block and top-level yields once."""
        self._write_events([
            {'type': 'assistant', 'message': {'content': [
                {'type': 'tool_use', 'id': 'tu_dup', 'name': 'Grep',
                 'input': {'pattern': 'foo'}},
            ]}},
            {'type': 'tool_use', 'tool_use_id': 'tu_dup', 'name': 'Grep',
             'input': {'pattern': 'foo'}},
        ])
        results = self._iter()
        tool_uses = [(s, c) for s, c in results if s == 'tool_use']
        self.assertEqual(len(tool_uses), 1)

    def test_different_tool_use_ids_both_yielded(self):
        """Different tool_use_ids from content block and top-level both yield."""
        self._write_events([
            {'type': 'assistant', 'message': {'content': [
                {'type': 'tool_use', 'id': 'tu_1', 'name': 'Read',
                 'input': {}},
            ]}},
            {'type': 'tool_use', 'tool_use_id': 'tu_2', 'name': 'Write',
             'input': {}},
        ])
        results = self._iter()
        tool_uses = [(s, c) for s, c in results if s == 'tool_use']
        self.assertEqual(len(tool_uses), 2)

    # ── tool_result deduplication ────────────────────────────────────────

    def test_duplicate_tool_result_from_top_level_and_user_deduplicated(self):
        """Same tool_use_id from top-level tool_result and user event yields once."""
        self._write_events([
            {'type': 'tool_result', 'tool_use_id': 'tr_dup',
             'content': 'result text'},
            {'type': 'user', 'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 'tr_dup',
                 'content': 'result text'},
            ]}},
        ])
        results = self._iter()
        tool_results = [(s, c) for s, c in results if s == 'tool_result']
        self.assertEqual(len(tool_results), 1)

    # ── existing behavior preserved ──────────────────────────────────────

    def test_thinking_block_yielded(self):
        """Thinking content block produces ('thinking', text)."""
        self._write_events([{'type': 'assistant', 'message': {'content': [
            {'type': 'thinking', 'thinking': 'Let me think...'},
        ]}}])
        results = self._iter()
        self.assertEqual(results, [('thinking', 'Let me think...')])

    def test_text_block_yielded_with_agent_role(self):
        """Text content block produces (agent_role, text)."""
        self._write_events([{'type': 'assistant', 'message': {'content': [
            {'type': 'text', 'text': 'Hello'},
        ]}}])
        results = self._iter(agent_role='office-manager')
        self.assertEqual(results, [('office-manager', 'Hello')])

    def test_system_event_yielded(self):
        """System event produces ('system', json)."""
        self._write_events([{
            'type': 'system', 'subtype': 'init', 'session_id': 's1',
        }])
        results = self._iter()
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], 'system')


if __name__ == '__main__':
    unittest.main()
