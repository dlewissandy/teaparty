#!/usr/bin/env python3
"""Tests for issue #393 — /clear must fully reset, build_context must not duplicate.

Acceptance criteria:
1. /clear clears all messages from the conversation's bus database
2. /clear stops the bus event listener
3. /clear closes open agent context records
4. /clear resets bus listener state (_bus_listener, etc.)
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

        bus.send(conv_id, 'human', '/clear')

        with patch.object(self._session, 'load_state'), \
             patch.object(self._session, 'save_state'):
            asyncio.run(self._session.invoke(cwd=self._tmpdir))

        self.assertIsNone(self._session._bus_context_id,
                          '_bus_context_id should be None after /clear')
        self.assertIsNone(self._session._dispatch_session,
                          '_dispatch_session should be None after /clear')


class TestClearClosesAgentContexts(unittest.TestCase):
    """/clear must close open agent context records in the bus DB."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._session = _make_session(self._tmpdir)

    def tearDown(self):
        self._session._bus.close()

    def test_clear_closes_only_this_sessions_agent_contexts(self):
        """Only contexts in this session's tree are closed; other sessions' survive."""
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

        # This session's context tree
        lead_ctx = 'agent:office-manager:lead:session-A'
        self._session._bus_context_id = lead_ctx
        infra_bus.create_agent_context(
            lead_ctx,
            initiator_agent_id='office-manager',
            recipient_agent_id='office-manager',
        )
        infra_bus.create_agent_context_and_increment_parent(
            'agent:office-manager:teaparty-lead:child-1',
            initiator_agent_id='office-manager',
            recipient_agent_id='teaparty-lead',
            parent_context_id=lead_ctx,
        )

        # A DIFFERENT session's context (must survive /clear)
        other_lead = 'agent:office-manager:lead:session-B'
        infra_bus.create_agent_context(
            other_lead,
            initiator_agent_id='office-manager',
            recipient_agent_id='office-manager',
        )
        infra_bus.create_agent_context_and_increment_parent(
            'agent:office-manager:config-lead:other-child',
            initiator_agent_id='office-manager',
            recipient_agent_id='config-lead',
            parent_context_id=other_lead,
        )

        # 4 total open contexts
        self.assertEqual(len(infra_bus.open_agent_contexts()), 4)

        bus.send(conv_id, 'human', '/clear')

        with patch.object(self._session, 'load_state'), \
             patch.object(self._session, 'save_state'):
            asyncio.run(self._session.invoke(cwd=self._tmpdir))

        # Session A's contexts (lead + child) should be closed
        # Session B's contexts (lead + child) should still be open
        open_contexts = infra_bus.open_agent_contexts()
        self.assertEqual(len(open_contexts), 2,
                         'Only this session\'s contexts should be closed')
        open_ids = {c['context_id'] for c in open_contexts}
        self.assertIn(other_lead, open_ids,
                       'Other session\'s lead context must survive')
        self.assertIn('agent:office-manager:config-lead:other-child', open_ids,
                       'Other session\'s child context must survive')
        infra_bus.close()


class TestClearDoesNotTouchNonWorktreeDirs(unittest.TestCase):
    """Chat-tier /clear must NOT call ``git worktree remove`` on cwd
    paths stored in child contexts.

    Under issue #397 chat-tier children launch at the real repo and do
    not have their own worktree. The stored ``agent_worktree_path`` is
    just an opaque cwd handle — removing it would delete real repo state.
    """

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._session = _make_session(self._tmpdir)

    def tearDown(self):
        self._session._bus.close()

    def test_clear_skips_non_worktree_paths(self):
        """Plain directories (no .git file) stored on child contexts
        must not be passed to ``git worktree remove``."""
        bus = self._session._bus
        conv_id = self._session.conversation_id

        lead_ctx = 'agent:office-manager:lead:wt-session'
        self._session._bus_context_id = lead_ctx

        infra_dir = os.path.join(
            self._tmpdir, 'management', 'agents', 'office-manager',
        )
        os.makedirs(infra_dir, exist_ok=True)
        infra_db_path = os.path.join(infra_dir, 'messages.db')
        infra_bus = SqliteMessageBus(infra_db_path)

        infra_bus.create_agent_context(
            lead_ctx,
            initiator_agent_id='office-manager',
            recipient_agent_id='office-manager',
        )
        infra_bus.create_agent_context_and_increment_parent(
            'agent:om:teaparty-lead:ctx-1',
            initiator_agent_id='office-manager',
            recipient_agent_id='teaparty-lead',
            parent_context_id=lead_ctx,
        )
        plain_dir = os.path.join(self._tmpdir, 'not-a-worktree')
        os.makedirs(plain_dir, exist_ok=True)
        infra_bus.set_agent_context_worktree_path(
            'agent:om:teaparty-lead:ctx-1', plain_dir,
        )
        infra_bus.close()

        bus.send(conv_id, 'human', '/clear')

        removed_paths = []
        original_run = __import__('subprocess').run

        def capture_worktree_remove(*args, **kwargs):
            cmd = args[0] if args else kwargs.get('args', [])
            if isinstance(cmd, list) and 'worktree' in cmd and 'remove' in cmd:
                removed_paths.append(cmd[-1])
            return original_run(*args, **kwargs)

        with patch.object(self._session, 'load_state'), \
             patch.object(self._session, 'save_state'), \
             patch('subprocess.run', side_effect=capture_worktree_remove):
            asyncio.run(self._session.invoke(cwd=self._tmpdir))

        self.assertNotIn(plain_dir, removed_paths,
                         'Chat-tier cwd paths must not be removed as worktrees')
        self.assertTrue(os.path.isdir(plain_dir),
                        'The non-worktree dir must still exist after /clear')


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

    def test_close_agent_context_tree_scopes_to_parent(self):
        """close_agent_context_tree only closes the parent and its children."""
        # Tree A: parent + child
        self._bus.create_agent_context(
            'parent-A', initiator_agent_id='a', recipient_agent_id='a',
        )
        self._bus.create_agent_context_and_increment_parent(
            'child-A1', initiator_agent_id='a', recipient_agent_id='b',
            parent_context_id='parent-A',
        )

        # Tree B: parent + child (should survive)
        self._bus.create_agent_context(
            'parent-B', initiator_agent_id='a', recipient_agent_id='a',
        )
        self._bus.create_agent_context_and_increment_parent(
            'child-B1', initiator_agent_id='a', recipient_agent_id='c',
            parent_context_id='parent-B',
        )

        self.assertEqual(len(self._bus.open_agent_contexts()), 4)

        self._bus.close_agent_context_tree('parent-A')

        open_ctx = self._bus.open_agent_contexts()
        self.assertEqual(len(open_ctx), 2)
        open_ids = {c['context_id'] for c in open_ctx}
        self.assertEqual(open_ids, {'parent-B', 'child-B1'})

    def test_open_agent_contexts_for_parent(self):
        """open_agent_contexts_for_parent returns only children of the given parent."""
        self._bus.create_agent_context(
            'parent-X', initiator_agent_id='a', recipient_agent_id='a',
        )
        self._bus.create_agent_context_and_increment_parent(
            'child-X1', initiator_agent_id='a', recipient_agent_id='b',
            parent_context_id='parent-X',
        )
        self._bus.create_agent_context(
            'parent-Y', initiator_agent_id='a', recipient_agent_id='a',
        )

        children = self._bus.open_agent_contexts_for_parent('parent-X')
        self.assertEqual(len(children), 1)
        self.assertEqual(children[0]['context_id'], 'child-X1')


class TestClearForcesTeardownOnMergeFailure(unittest.TestCase):
    """/clear must purge on-disk state even when close_conversation
    cannot merge the child's worktree.

    Specification: /clear is operator-initiated "throw it away." A
    child whose worktree has drifted or whose branch has vanished would
    make close_conversation return {'status': 'conflict'} or 'error' —
    in that case the child stays in the parent's on-disk
    ``conversation_map`` and the blade resurrects on page reload.
    /clear must fall back to force-teardown: strip the conversation_map
    entry and rmtree the session dir regardless of merge status.
    """

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._session = _make_session(self._tmpdir)

    def tearDown(self):
        self._session._bus.close()

    def _seed_stale_child(self, parent_session_id=None,
                          child_session_id='stale-child',
                          request_id='dispatch:stale-conv'):
        # Default to the session's actual _session_key so load_session
        # finds it. _make_session uses qualifier='test-user' → the key
        # is 'office-manager-test-user'.
        if parent_session_id is None:
            parent_session_id = self._session._session_key()
        """Write parent + child metadata.json AND register in the bus so
        /clear walks them (#422 — bus is authoritative)."""
        import json as _json
        sessions_dir = os.path.join(
            self._tmpdir, 'management', 'sessions')
        os.makedirs(os.path.join(
            sessions_dir, parent_session_id), exist_ok=True)
        os.makedirs(os.path.join(
            sessions_dir, child_session_id), exist_ok=True)

        with open(os.path.join(
                sessions_dir, parent_session_id, 'metadata.json'), 'w') as f:
            _json.dump({
                'session_id': parent_session_id,
                'agent_name': 'office-manager',
                'scope': 'management',
                'conversation_map': {request_id: child_session_id},
            }, f)
        with open(os.path.join(
                sessions_dir, child_session_id, 'metadata.json'), 'w') as f:
            _json.dump({
                'session_id': child_session_id,
                'agent_name': 'teaparty-lead',
                'scope': 'management',
                'conversation_map': {},
                # No worktree_path — nothing to merge, but simulate
                # close_conversation returning a non-ok status.
            }, f)

        # Register the stale child in the bus so /clear's bus-first
        # walker finds it (#422).  This is how the real spawn_fn would
        # have left things before the crash/restart scenario that
        # "stale child" represents.
        from teaparty.messaging.conversations import (
            ConversationState, ConversationType,
        )
        self._session._bus.create_conversation(
            ConversationType.DISPATCH, child_session_id,
            agent_name='teaparty-lead',
            parent_conversation_id=self._session.conversation_id,
            request_id=request_id,
            state=ConversationState.ACTIVE,
        )
        return sessions_dir

    def test_clear_purges_child_when_close_returns_conflict(self):
        """If close_conversation returns status='conflict', /clear must
        still remove the child from conversation_map and rmtree its dir."""
        sessions_dir = self._seed_stale_child()
        bus = self._session._bus
        conv_id = self._session.conversation_id

        bus.send(conv_id, 'human', '/clear')

        async def failing_close(parent_session, conversation_id, **kwargs):
            return {'status': 'conflict',
                    'message': 'simulated merge conflict',
                    'conflicts': ['file.txt']}

        with patch.object(self._session, 'load_state'), \
             patch.object(self._session, 'save_state'), \
             patch('teaparty.workspace.close_conversation.close_conversation',
                   side_effect=failing_close):
            asyncio.run(self._session.invoke(cwd=self._tmpdir))

        # Child session dir must be gone
        self.assertFalse(
            os.path.isdir(os.path.join(sessions_dir, 'stale-child')),
            'Force-teardown must rmtree the child session dir '
            'when close_conversation fails to merge')

        # Parent's conversation_map on disk must no longer reference it
        parent_meta_path = os.path.join(
            sessions_dir, self._session._session_key(), 'metadata.json')
        import json as _json
        with open(parent_meta_path) as f:
            parent_meta = _json.load(f)
        self.assertEqual(parent_meta.get('conversation_map', {}), {},
                         'Force-teardown must strip the entry from the '
                         'parent conversation_map on disk so the blade '
                         'does not resurrect on page reload')

    def test_clear_purges_child_when_close_raises(self):
        """If close_conversation raises, /clear must still force-teardown."""
        sessions_dir = self._seed_stale_child(
            child_session_id='raising-child',
            request_id='dispatch:raising')
        bus = self._session._bus
        conv_id = self._session.conversation_id

        bus.send(conv_id, 'human', '/clear')

        async def raising_close(*args, **kwargs):
            raise RuntimeError('simulated close_conversation blowup')

        with patch.object(self._session, 'load_state'), \
             patch.object(self._session, 'save_state'), \
             patch('teaparty.workspace.close_conversation.close_conversation',
                   side_effect=raising_close):
            asyncio.run(self._session.invoke(cwd=self._tmpdir))

        self.assertFalse(
            os.path.isdir(os.path.join(sessions_dir, 'raising-child')),
            'Force-teardown must rmtree the child even when '
            'close_conversation raises')


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
        self.assertEqual(prompt, 'Human: Second message',
                         'Resume should send the latest incoming message '
                         'prefixed with its sender role')
        self.assertNotIn('First message', prompt,
                         'Resume must not include earlier messages')


if __name__ == '__main__':
    unittest.main()
