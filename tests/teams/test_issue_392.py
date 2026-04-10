#!/usr/bin/env python3
"""Tests for issue #392 — stream agent events to chat blade in real-time.

Team agents (OM, project_manager, project_lead, config_lead) must stream
events to the message bus as they arrive, not batch them after the runner
completes.  The _make_live_stream_relay function creates a synchronous
callback that writes (sender, content) pairs to the bus immediately and
accumulates them for post-processing.
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from teaparty.messaging.conversations import SqliteMessageBus


def _make_bus(tmpdir: str):
    db_path = os.path.join(tmpdir, 'messages.db')
    bus = SqliteMessageBus(db_path)
    conv_id = 'om:test-user'
    return bus, conv_id


class TestLiveStreamRelay(unittest.TestCase):
    """_make_live_stream_relay writes events to the bus as they arrive."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._bus, self._conv_id = _make_bus(self._tmpdir)

    def tearDown(self):
        self._bus.close()

    def _get_relay(self, agent_role='office-manager'):
        from teaparty.teams.office_manager import _make_live_stream_relay
        return _make_live_stream_relay(self._bus, self._conv_id, agent_role)

    def _messages(self):
        return self._bus.receive(self._conv_id)

    # ── Assistant text events stream immediately ─────────────────────────

    def test_assistant_text_block_written_to_bus_immediately(self):
        """An assistant text block is written to the bus when the callback fires,
        not deferred until later."""
        callback, events = self._get_relay()
        callback({
            'type': 'assistant',
            'message': {'content': [
                {'type': 'text', 'text': 'Hello world'},
            ]},
        })
        msgs = self._messages()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].sender, 'office-manager')
        self.assertEqual(msgs[0].content, 'Hello world')

    # ── Thinking events stream immediately ───────────────────────────────

    def test_thinking_block_written_to_bus_immediately(self):
        """A thinking block is written to the bus when the callback fires."""
        callback, events = self._get_relay()
        callback({
            'type': 'assistant',
            'message': {'content': [
                {'type': 'thinking', 'thinking': 'Let me consider...'},
            ]},
        })
        msgs = self._messages()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].sender, 'thinking')
        self.assertEqual(msgs[0].content, 'Let me consider...')

    # ── Tool use events stream immediately ───────────────────────────────

    def test_tool_use_block_written_to_bus_immediately(self):
        """A tool_use block is written to the bus when the callback fires."""
        callback, events = self._get_relay()
        callback({
            'type': 'assistant',
            'message': {'content': [
                {'type': 'tool_use', 'id': 'tu_1', 'name': 'Read',
                 'input': {'path': '/foo'}},
            ]},
        })
        msgs = self._messages()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].sender, 'tool_use')
        payload = json.loads(msgs[0].content)
        self.assertEqual(payload['name'], 'Read')

    # ── Tool result events stream immediately ────────────────────────────

    def test_tool_result_event_written_to_bus_immediately(self):
        """A top-level tool_result event is written to the bus immediately."""
        callback, events = self._get_relay()
        callback({
            'type': 'tool_result',
            'tool_use_id': 'tr_1',
            'content': 'file contents here',
        })
        msgs = self._messages()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].sender, 'tool_result')

    # ── Cost/result events stream immediately ────────────────────────────

    def test_result_event_produces_cost_message(self):
        """A result event with cost data produces a cost message."""
        callback, events = self._get_relay()
        callback({
            'type': 'result',
            'total_cost_usd': 0.05,
            'duration_ms': 1234,
            'input_tokens': 100,
            'output_tokens': 200,
        })
        msgs = self._messages()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].sender, 'cost')

    # ── System events stream immediately ─────────────────────────────────

    def test_system_event_written_to_bus_immediately(self):
        """A system event is written to the bus when the callback fires."""
        callback, events = self._get_relay()
        callback({'type': 'system', 'subtype': 'init', 'mcp_servers': []})
        msgs = self._messages()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].sender, 'system')

    # ── Events accumulate for post-processing ────────────────────────────

    def test_events_list_accumulates_sender_content_pairs(self):
        """The returned events list collects (sender, content) for each event."""
        callback, events = self._get_relay()
        callback({
            'type': 'assistant',
            'message': {'content': [
                {'type': 'thinking', 'thinking': 'hmm'},
                {'type': 'text', 'text': 'answer'},
            ]},
        })
        callback({'type': 'result', 'total_cost_usd': 0.01})
        self.assertEqual(len(events), 3)
        self.assertEqual(events[0], ('thinking', 'hmm'))
        self.assertEqual(events[1], ('office-manager', 'answer'))
        self.assertEqual(events[2][0], 'cost')

    # ── Deduplication ────────────────────────────────────────────────────

    def test_duplicate_tool_use_ids_are_deduplicated(self):
        """Same tool_use_id appearing in assistant block and top-level event
        should produce only one bus message."""
        callback, events = self._get_relay()
        callback({
            'type': 'assistant',
            'message': {'content': [
                {'type': 'tool_use', 'id': 'tu_dup', 'name': 'Bash',
                 'input': {'cmd': 'ls'}},
            ]},
        })
        callback({
            'type': 'tool_use',
            'tool_use_id': 'tu_dup',
            'name': 'Bash',
            'input': {'cmd': 'ls'},
        })
        msgs = self._messages()
        self.assertEqual(len(msgs), 1)

    def test_duplicate_tool_result_ids_are_deduplicated(self):
        """Same tool_use_id for tool_result should produce only one message."""
        callback, events = self._get_relay()
        callback({
            'type': 'tool_result',
            'tool_use_id': 'tr_dup',
            'content': 'result A',
        })
        callback({
            'type': 'user',
            'message': {'content': [
                {'type': 'tool_result', 'tool_use_id': 'tr_dup',
                 'content': 'result A'},
            ]},
        })
        msgs = self._messages()
        self.assertEqual(len(msgs), 1)


class TestRunnerReceivesOnStreamEvent(unittest.TestCase):
    """Team agent invoke methods must pass on_stream_event to the unified launcher."""

    def _make_fake_launch(self):
        """Return (fake_launch, captured_kwargs) for verifying on_stream_event."""
        from unittest.mock import MagicMock
        captured_kwargs = {}

        async def fake_launch(**kwargs):
            captured_kwargs.update(kwargs)
            mock_result = MagicMock()
            mock_result.session_id = 'sess-123'
            mock_result.stderr_lines = []
            return mock_result

        return fake_launch, captured_kwargs

    def test_office_manager_passes_on_stream_event_to_runner(self):
        """OfficeManagerSession.invoke() must pass on_stream_event so events
        stream to the bus in real-time, not batched after completion."""
        from unittest.mock import patch, AsyncMock
        import asyncio

        tmpdir = tempfile.mkdtemp()
        bus_path = os.path.join(tmpdir, 'messages.db')
        bus = SqliteMessageBus(bus_path)
        conv_id = 'om:test-user'

        from teaparty.teams.office_manager import OfficeManagerSession

        session = OfficeManagerSession.__new__(OfficeManagerSession)
        session.teaparty_home = tmpdir
        session.user_id = 'test-user'
        session._bus = bus
        session.conversation_id = conv_id
        session.claude_session_id = None
        session.conversation_title = ''
        session._llm_backend = 'deterministic'
        session._infra_dir = tmpdir
        session._bus_context_id = None
        session._om_locks = {}

        bus.send(conv_id, 'human', 'Hello')
        fake_launch, captured = self._make_fake_launch()

        with patch('teaparty.runners.launcher.launch', side_effect=fake_launch), \
             patch.object(session, 'load_state'), \
             patch.object(session, 'save_state'), \
             patch.object(session, '_ensure_bus_listener', new_callable=AsyncMock, return_value={}), \
             patch('teaparty.workspace.worktree.ensure_agent_worktree', new_callable=AsyncMock, return_value=tmpdir):

            asyncio.run(session.invoke(cwd=tmpdir))

        self.assertIn('on_stream_event', captured,
                       'launch must receive on_stream_event for real-time streaming')
        self.assertIsNotNone(captured['on_stream_event'],
                             'on_stream_event must not be None')

        bus.close()

    def test_project_manager_passes_on_stream_event_to_runner(self):
        """ProjectManagerSession.invoke() must pass on_stream_event."""
        from unittest.mock import patch, AsyncMock
        import asyncio

        tmpdir = tempfile.mkdtemp()
        bus = SqliteMessageBus(os.path.join(tmpdir, 'messages.db'))
        conv_id = 'pm:test-project:test-user'

        from teaparty.teams.project_manager import ProjectManagerSession
        session = ProjectManagerSession.__new__(ProjectManagerSession)
        session.teaparty_home = tmpdir
        session.lead = 'project-manager'
        session._bus = bus
        session.conversation_id = conv_id
        session.claude_session_id = None
        session.conversation_title = ''
        session._llm_backend = 'deterministic'
        session._infra_dir = tmpdir

        bus.send(conv_id, 'human', 'Hello')
        fake_launch, captured = self._make_fake_launch()

        with patch('teaparty.runners.launcher.launch', side_effect=fake_launch), \
             patch.object(session, 'load_state'), \
             patch.object(session, 'save_state'), \
             patch('teaparty.workspace.worktree.ensure_agent_worktree',
                   new_callable=AsyncMock, return_value=tmpdir):
            asyncio.run(session.invoke(cwd=tmpdir))

        self.assertIn('on_stream_event', captured)
        self.assertIsNotNone(captured['on_stream_event'])
        bus.close()

    def test_project_lead_passes_on_stream_event_to_runner(self):
        """ProjectLeadSession.invoke() must pass on_stream_event."""
        from unittest.mock import patch, AsyncMock
        import asyncio

        tmpdir = tempfile.mkdtemp()
        bus = SqliteMessageBus(os.path.join(tmpdir, 'messages.db'))
        conv_id = 'lead:test-lead:test-user'

        from teaparty.teams.project_lead import ProjectLeadSession
        session = ProjectLeadSession.__new__(ProjectLeadSession)
        session.teaparty_home = tmpdir
        session.lead_name = 'test-lead'
        session.qualifier = 'test-user'
        session._bus = bus
        session.conversation_id = conv_id
        session.claude_session_id = None
        session.conversation_title = ''
        session._llm_backend = 'deterministic'
        session._infra_dir = tmpdir

        bus.send(conv_id, 'human', 'Hello')
        fake_launch, captured = self._make_fake_launch()

        with patch('teaparty.runners.launcher.launch', side_effect=fake_launch), \
             patch.object(session, 'load_state'), \
             patch.object(session, 'save_state'), \
             patch('teaparty.workspace.worktree.ensure_agent_worktree',
                   new_callable=AsyncMock, return_value=tmpdir):
            asyncio.run(session.invoke(cwd=tmpdir))

        self.assertIn('on_stream_event', captured)
        self.assertIsNotNone(captured['on_stream_event'])
        bus.close()

    def test_config_lead_passes_on_stream_event_to_runner(self):
        """ConfigLeadSession.invoke() must pass on_stream_event."""
        from unittest.mock import patch, AsyncMock
        import asyncio

        tmpdir = tempfile.mkdtemp()
        bus = SqliteMessageBus(os.path.join(tmpdir, 'messages.db'))
        conv_id = 'config:test-user'

        from teaparty.teams.config_lead import ConfigLeadSession
        session = ConfigLeadSession.__new__(ConfigLeadSession)
        session.teaparty_home = tmpdir
        session.LEAD = 'configuration-lead'
        session._bus = bus
        session.conversation_id = conv_id
        session.claude_session_id = None
        session.conversation_title = ''
        session._llm_backend = 'deterministic'
        session._infra_dir = tmpdir

        bus.send(conv_id, 'human', 'Hello')
        fake_launch, captured = self._make_fake_launch()

        with patch('teaparty.runners.launcher.launch', side_effect=fake_launch), \
             patch.object(session, 'load_state'), \
             patch.object(session, 'save_state'), \
             patch.object(session, '_ensure_bus_listener',
                          new_callable=AsyncMock, return_value={}), \
             patch('teaparty.workspace.worktree.ensure_agent_worktree',
                   new_callable=AsyncMock, return_value=tmpdir):
            asyncio.run(session.invoke(cwd=tmpdir))

        self.assertIn('on_stream_event', captured)
        self.assertIsNotNone(captured['on_stream_event'])
        bus.close()

    def test_proxy_review_passes_on_stream_event_to_runner(self):
        """ProxyReviewSession.invoke() must pass on_stream_event."""
        from unittest.mock import patch, AsyncMock
        import asyncio

        tmpdir = tempfile.mkdtemp()
        bus = SqliteMessageBus(os.path.join(tmpdir, 'messages.db'))
        conv_id = 'proxy:test-user'

        from teaparty.proxy.review import ProxyReviewSession
        session = ProxyReviewSession.__new__(ProxyReviewSession)
        session.teaparty_home = tmpdir
        session.decider = 'test-user'
        session._bus = bus
        session.conversation_id = conv_id
        session.claude_session_id = 'existing-session'
        session.conversation_title = ''
        session._llm_backend = 'deterministic'
        session._infra_dir = tmpdir

        bus.send(conv_id, 'human', 'Hello')
        fake_launch, captured = self._make_fake_launch()

        with patch('teaparty.runners.launcher.launch', side_effect=fake_launch), \
             patch.object(session, 'load_state'), \
             patch.object(session, 'save_state'), \
             patch.object(session, '_build_memory_context_prompt',
                          return_value='memory context'), \
             patch('teaparty.workspace.worktree.ensure_agent_worktree',
                   new_callable=AsyncMock, return_value=tmpdir):
            asyncio.run(session.invoke(cwd=tmpdir))

        self.assertIn('on_stream_event', captured)
        self.assertIsNotNone(captured['on_stream_event'])
        bus.close()


if __name__ == '__main__':
    unittest.main()
