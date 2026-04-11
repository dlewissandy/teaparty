#!/usr/bin/env python3
"""Tests for issue #393 — /clear must fully reset, build_context must not duplicate.

Acceptance criteria:
1. /clear clears all messages from the conversation's bus database
2. /clear stops the bus event listener
3. /clear closes open agent context records
4. /clear resets bus listener state (_bus_listener, _bus_listener_sockets, etc.)
5. build_context returns empty string after clear (no stale history)
6. Resume path sends only the latest human message (not full history)
"""
import asyncio
import os
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from teaparty.messaging.conversations import ConversationType, SqliteMessageBus
from teaparty.teams.session import AgentSession


def _make_session(tmpdir):
    """Create an AgentSession backed by a temp directory."""
    session = AgentSession(
        tmpdir,
        agent_name='office-manager',
        qualifier='test-user',
        conversation_type=ConversationType.OFFICE_MANAGER,
        dispatches=True,
    )
    return session


class TestClearDeletesBusMessages(unittest.TestCase):
    """/clear must delete all messages for the conversation from the bus."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._session = _make_session(self._tmpdir)

    def tearDown(self):
        self._session._bus.close()

    def test_clear_removes_all_messages_from_bus(self):
        """After /clear, no messages remain in the conversation's bus."""
        bus = self._session._bus
        conv_id = self._session.conversation_id

        # Populate history
        bus.send(conv_id, 'human', 'Hello')
        bus.send(conv_id, 'office-manager', 'Hi there')
        bus.send(conv_id, 'human', 'How are you?')
        self.assertEqual(len(bus.receive(conv_id)), 3)

        # Send /clear and invoke
        bus.send(conv_id, 'human', '/clear')

        with patch.object(self._session, 'load_state'), \
             patch.object(self._session, 'save_state'):
            asyncio.run(self._session.invoke(cwd=self._tmpdir))

        # All prior messages should be gone
        messages = bus.receive(conv_id)
        # Only the "Session cleared." response should remain
        human_msgs = [m for m in messages if m.sender == 'human']
        self.assertEqual(len(human_msgs), 0,
                         'All human messages should be cleared after /clear')


class TestClearStopsBusListener(unittest.TestCase):
    """/clear must stop the bus event listener."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._session = _make_session(self._tmpdir)

    def tearDown(self):
        self._session._bus.close()

    def test_clear_stops_active_bus_listener(self):
        """If a bus listener is running, /clear stops it."""
        bus = self._session._bus
        conv_id = self._session.conversation_id

        # Simulate an active listener
        mock_listener = AsyncMock()
        self._session._bus_listener = mock_listener
        self._session._bus_listener_sockets = ('/tmp/s', '/tmp/r', '/tmp/c')

        bus.send(conv_id, 'human', '/clear')

        with patch.object(self._session, 'load_state'), \
             patch.object(self._session, 'save_state'):
            asyncio.run(self._session.invoke(cwd=self._tmpdir))

        mock_listener.stop.assert_awaited_once()
        self.assertIsNone(self._session._bus_listener,
                          'Bus listener should be None after /clear')


class TestClearResetsListenerState(unittest.TestCase):
    """/clear must reset all bus listener state fields."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._session = _make_session(self._tmpdir)

    def tearDown(self):
        self._session._bus.close()

    def test_clear_resets_bus_context_id_and_dispatch_session(self):
        """After /clear, _bus_context_id and _dispatch_session are reset."""
        bus = self._session._bus
        conv_id = self._session.conversation_id

        # Set up state that should be reset
        self._session._bus_context_id = 'agent:office-manager:lead:fake-uuid'
        self._session._dispatch_session = MagicMock()
        self._session._bus_listener = AsyncMock()
        self._session._bus_listener_sockets = ('/tmp/s', '/tmp/r', '/tmp/c')

        bus.send(conv_id, 'human', '/clear')

        with patch.object(self._session, 'load_state'), \
             patch.object(self._session, 'save_state'):
            asyncio.run(self._session.invoke(cwd=self._tmpdir))

        self.assertIsNone(self._session._bus_context_id,
                          '_bus_context_id should be None after /clear')
        self.assertIsNone(self._session._dispatch_session,
                          '_dispatch_session should be None after /clear')
        self.assertIsNone(self._session._bus_listener_sockets,
                          '_bus_listener_sockets should be None after /clear')


class TestClearClosesAgentContexts(unittest.TestCase):
    """/clear must close open agent context records in the bus DB."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._session = _make_session(self._tmpdir)

    def tearDown(self):
        self._session._bus.close()

    def test_clear_closes_open_agent_contexts(self):
        """Open agent context records are closed after /clear."""
        bus = self._session._bus
        conv_id = self._session.conversation_id

        # The agent's infra DB (where contexts live) is separate from the
        # conversation bus. Create contexts in the infra DB.
        infra_dir = os.path.join(
            self._tmpdir, 'management', 'agents', 'office-manager',
        )
        os.makedirs(infra_dir, exist_ok=True)
        infra_db_path = os.path.join(infra_dir, 'messages.db')
        infra_bus = SqliteMessageBus(infra_db_path)
        infra_bus.create_agent_context(
            'agent:office-manager:lead:ctx-1',
            initiator_agent_id='office-manager',
            recipient_agent_id='office-manager',
        )
        infra_bus.create_agent_context(
            'agent:office-manager:teaparty-lead:ctx-2',
            initiator_agent_id='office-manager',
            recipient_agent_id='teaparty-lead',
        )
        # Verify they start open
        open_contexts = infra_bus.open_agent_contexts()
        self.assertEqual(len(open_contexts), 2)

        bus.send(conv_id, 'human', '/clear')

        with patch.object(self._session, 'load_state'), \
             patch.object(self._session, 'save_state'):
            asyncio.run(self._session.invoke(cwd=self._tmpdir))

        # All contexts should now be closed
        open_contexts = infra_bus.open_agent_contexts()
        self.assertEqual(len(open_contexts), 0,
                         'All agent contexts should be closed after /clear')
        infra_bus.close()


class TestClearReleasesChildWorktrees(unittest.TestCase):
    """/clear must release child worktrees stored in agent context records."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._session = _make_session(self._tmpdir)

    def tearDown(self):
        self._session._bus.close()

    def test_clear_calls_git_worktree_remove_for_each_child(self):
        """Worktree paths from open contexts are removed via git worktree remove."""
        bus = self._session._bus
        conv_id = self._session.conversation_id

        infra_dir = os.path.join(
            self._tmpdir, 'management', 'agents', 'office-manager',
        )
        os.makedirs(infra_dir, exist_ok=True)
        infra_db_path = os.path.join(infra_dir, 'messages.db')
        infra_bus = SqliteMessageBus(infra_db_path)

        # Create contexts with worktree paths
        infra_bus.create_agent_context(
            'agent:om:lead:ctx-1',
            initiator_agent_id='office-manager',
            recipient_agent_id='teaparty-lead',
        )
        wt_path_1 = os.path.join(self._tmpdir, 'wt1')
        os.makedirs(wt_path_1, exist_ok=True)
        infra_bus.set_agent_context_worktree_path('agent:om:lead:ctx-1', wt_path_1)

        infra_bus.create_agent_context(
            'agent:om:lead:ctx-2',
            initiator_agent_id='office-manager',
            recipient_agent_id='config-lead',
        )
        wt_path_2 = os.path.join(self._tmpdir, 'wt2')
        os.makedirs(wt_path_2, exist_ok=True)
        infra_bus.set_agent_context_worktree_path('agent:om:lead:ctx-2', wt_path_2)
        infra_bus.close()

        bus.send(conv_id, 'human', '/clear')

        removed_paths = []
        original_run = __import__('subprocess').run

        def capture_worktree_remove(*args, **kwargs):
            cmd = args[0] if args else kwargs.get('args', [])
            if isinstance(cmd, list) and 'worktree' in cmd and 'remove' in cmd:
                removed_paths.append(cmd[-1])  # last arg is the path
            return original_run(*args, **kwargs)

        with patch.object(self._session, 'load_state'), \
             patch.object(self._session, 'save_state'), \
             patch('subprocess.run', side_effect=capture_worktree_remove):
            asyncio.run(self._session.invoke(cwd=self._tmpdir))

        self.assertIn(wt_path_1, removed_paths,
                       'First child worktree should be removed')
        self.assertIn(wt_path_2, removed_paths,
                       'Second child worktree should be removed')


class TestBuildContextEmptyAfterClear(unittest.TestCase):
    """build_context must return empty string after /clear."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._session = _make_session(self._tmpdir)

    def tearDown(self):
        self._session._bus.close()

    def test_build_context_returns_empty_after_clear(self):
        """After /clear deletes bus messages, build_context returns ''."""
        bus = self._session._bus
        conv_id = self._session.conversation_id

        # Populate history
        bus.send(conv_id, 'human', 'Tell me about X')
        bus.send(conv_id, 'office-manager', 'X is...')
        self.assertNotEqual(self._session.build_context(), '')

        # /clear
        bus.send(conv_id, 'human', '/clear')
        with patch.object(self._session, 'load_state'), \
             patch.object(self._session, 'save_state'):
            asyncio.run(self._session.invoke(cwd=self._tmpdir))

        # build_context should now return empty or only the post-clear message
        context = self._session.build_context()
        self.assertNotIn('Tell me about X', context,
                         'Pre-clear messages must not appear in build_context')
        self.assertNotIn('X is...', context,
                         'Pre-clear agent responses must not appear in build_context')


class TestClearMessagesBusMethod(unittest.TestCase):
    """SqliteMessageBus must support clearing messages for a conversation."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._tmpdir, 'messages.db')
        self._bus = SqliteMessageBus(self._db_path)

    def tearDown(self):
        self._bus.close()

    def test_clear_messages_removes_all_for_conversation(self):
        """clear_messages(conversation_id) removes all messages for that conversation."""
        self._bus.send('conv-1', 'human', 'msg 1')
        self._bus.send('conv-1', 'agent', 'msg 2')
        self._bus.send('conv-2', 'human', 'other conv')

        self._bus.clear_messages('conv-1')

        self.assertEqual(len(self._bus.receive('conv-1')), 0)
        self.assertEqual(len(self._bus.receive('conv-2')), 1,
                         'Messages in other conversations must not be affected')

    def test_close_all_agent_contexts_closes_open_records(self):
        """close_all_agent_contexts() closes all open context records."""
        self._bus.create_agent_context(
            'ctx-1', initiator_agent_id='a', recipient_agent_id='b',
        )
        self._bus.create_agent_context(
            'ctx-2', initiator_agent_id='a', recipient_agent_id='c',
        )
        self.assertEqual(len(self._bus.open_agent_contexts()), 2)

        self._bus.close_all_agent_contexts()

        self.assertEqual(len(self._bus.open_agent_contexts()), 0)


class TestResumePathSendsOnlyLatestMessage(unittest.TestCase):
    """On resume, invoke sends only the latest human message, not full history."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._session = _make_session(self._tmpdir)

    def tearDown(self):
        self._session._bus.close()

    def test_resume_sends_only_latest_human_message(self):
        """When claude_session_id is set (resume), prompt is just the latest human message."""
        bus = self._session._bus
        conv_id = self._session.conversation_id

        bus.send(conv_id, 'human', 'First message')
        bus.send(conv_id, 'office-manager', 'Response 1')
        bus.send(conv_id, 'human', 'Second message')

        # Simulate existing session (resume path)
        self._session.claude_session_id = 'existing-session-id'

        captured_kwargs = {}

        async def fake_launch(**kwargs):
            captured_kwargs.update(kwargs)
            mock_result = MagicMock()
            mock_result.session_id = 'existing-session-id'
            return mock_result

        with patch('teaparty.runners.launcher.launch', side_effect=fake_launch), \
             patch.object(self._session, 'load_state'), \
             patch.object(self._session, 'save_state'), \
             patch('teaparty.workspace.worktree.ensure_agent_worktree',
                   new_callable=AsyncMock, return_value=self._tmpdir):
            asyncio.run(self._session.invoke(cwd=self._tmpdir))

        prompt = captured_kwargs.get('message', '')
        self.assertEqual(prompt, 'Second message',
                         'Resume should send only the latest human message')
        self.assertNotIn('First message', prompt,
                         'Resume must not include earlier messages')


if __name__ == '__main__':
    unittest.main()
