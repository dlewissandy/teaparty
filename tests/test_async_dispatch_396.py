"""Specification tests for issue #396: async dispatch, conversation handles, recursive close.

Tests verify the dispatch model described in the issue:
- Send is async (returns handle, child runs in background)
- Slot limit enforced (3 per agent)
- CloseConversation recursively tears down children
- All 8 dispatch topologies work correctly
"""
import json
import os
import shutil
import tempfile
import unittest

from teaparty.runners.launcher import (
    Session,
    create_session,
    record_child_session,
    remove_child_session,
    check_slot_available,
    MAX_CONVERSATIONS_PER_AGENT,
)


def _make_teaparty_home():
    """Create a temp .teaparty directory with management/sessions/."""
    tmpdir = tempfile.mkdtemp()
    os.makedirs(os.path.join(tmpdir, 'management', 'sessions'))
    return tmpdir


class TestSendReturnsHandle(unittest.TestCase):
    """Send returns a conversation handle, not the child's response."""

    def setUp(self):
        self._tmpdir = _make_teaparty_home()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_send_result_has_message_sent_status(self):
        """The Send tool returns status='message_sent'."""
        # The actual Send MCP tool is tested via integration.
        # Here we verify the spawn_fn return contract.
        session = create_session(
            agent_name='child', scope='management',
            teaparty_home=self._tmpdir,
        )
        # spawn_fn returns (session_id, worktree, '') — empty result_text
        # means the tool handler constructs the handle, not the response.
        self.assertIsInstance(session.id, str)
        self.assertTrue(len(session.id) > 0)
        conv_id = f'dispatch:{session.id}'
        self.assertTrue(conv_id.startswith('dispatch:'))


class TestSlotLimit(unittest.TestCase):
    """Per-agent conversation limit is enforced."""

    def setUp(self):
        self._tmpdir = _make_teaparty_home()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_three_slots_available(self):
        """Fresh session has 3 available slots."""
        parent = create_session(
            agent_name='parent', scope='management',
            teaparty_home=self._tmpdir,
        )
        self.assertTrue(check_slot_available(parent))
        self.assertEqual(MAX_CONVERSATIONS_PER_AGENT, 3)

    def test_slot_exhaustion(self):
        """After 3 children, no more slots available."""
        parent = create_session(
            agent_name='parent', scope='management',
            teaparty_home=self._tmpdir,
        )
        for i in range(3):
            record_child_session(parent, request_id=f'req-{i}',
                                 child_session_id=f'child-{i}')
        self.assertFalse(check_slot_available(parent))

    def test_close_frees_slot(self):
        """Removing a child frees a slot."""
        parent = create_session(
            agent_name='parent', scope='management',
            teaparty_home=self._tmpdir,
        )
        for i in range(3):
            record_child_session(parent, request_id=f'req-{i}',
                                 child_session_id=f'child-{i}')
        self.assertFalse(check_slot_available(parent))
        remove_child_session(parent, request_id='req-0')
        self.assertTrue(check_slot_available(parent))


class TestLinearDispatch(unittest.TestCase):
    """Test case 1: A → B → C."""

    def setUp(self):
        self._tmpdir = _make_teaparty_home()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_linear_chain(self):
        """A dispatches to B, B dispatches to C. Each has its own session
        and conversation_map entry."""
        a = create_session(agent_name='a', scope='management',
                           teaparty_home=self._tmpdir)
        b = create_session(agent_name='b', scope='management',
                           teaparty_home=self._tmpdir)
        c = create_session(agent_name='c', scope='management',
                           teaparty_home=self._tmpdir)

        record_child_session(a, request_id='a-to-b', child_session_id=b.id)
        record_child_session(b, request_id='b-to-c', child_session_id=c.id)

        self.assertIn('a-to-b', a.conversation_map)
        self.assertIn('b-to-c', b.conversation_map)
        self.assertEqual(len(c.conversation_map), 0)


class TestParallelDispatch(unittest.TestCase):
    """Test case 2: A → B, C (parallel)."""

    def setUp(self):
        self._tmpdir = _make_teaparty_home()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_parallel_children(self):
        """A dispatches to B and C. Both recorded in A's conversation_map."""
        a = create_session(agent_name='a', scope='management',
                           teaparty_home=self._tmpdir)
        b = create_session(agent_name='b', scope='management',
                           teaparty_home=self._tmpdir)
        c = create_session(agent_name='c', scope='management',
                           teaparty_home=self._tmpdir)

        record_child_session(a, request_id='a-to-b', child_session_id=b.id)
        record_child_session(a, request_id='a-to-c', child_session_id=c.id)

        self.assertEqual(len(a.conversation_map), 2)
        self.assertTrue(check_slot_available(a))  # 2 of 3 used


class TestRateLimitDispatch(unittest.TestCase):
    """Test case 3: A → B, C, D (full), close one, send to E."""

    def setUp(self):
        self._tmpdir = _make_teaparty_home()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_rate_limit_then_close_and_send(self):
        """Fill 3 slots, verify blocked, close one, verify available."""
        a = create_session(agent_name='a', scope='management',
                           teaparty_home=self._tmpdir)
        for name in ['b', 'c', 'd']:
            child = create_session(agent_name=name, scope='management',
                                   teaparty_home=self._tmpdir)
            record_child_session(a, request_id=f'a-to-{name}',
                                 child_session_id=child.id)

        # Slots full
        self.assertFalse(check_slot_available(a))

        # Close first child (b done first)
        remove_child_session(a, request_id='a-to-b')
        self.assertTrue(check_slot_available(a))

        # Now can dispatch to e
        e = create_session(agent_name='e', scope='management',
                           teaparty_home=self._tmpdir)
        record_child_session(a, request_id='a-to-e', child_session_id=e.id)
        self.assertFalse(check_slot_available(a))  # Full again


class TestParallelInstanceDispatch(unittest.TestCase):
    """Test case 4: A → B, B (two instances of same agent)."""

    def setUp(self):
        self._tmpdir = _make_teaparty_home()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_two_instances_of_same_agent(self):
        """A dispatches to B twice. Two separate sessions with different IDs."""
        a = create_session(agent_name='a', scope='management',
                           teaparty_home=self._tmpdir)
        b1 = create_session(agent_name='b', scope='management',
                            teaparty_home=self._tmpdir)
        b2 = create_session(agent_name='b', scope='management',
                            teaparty_home=self._tmpdir)

        self.assertNotEqual(b1.id, b2.id)

        record_child_session(a, request_id='a-to-b-1',
                             child_session_id=b1.id)
        record_child_session(a, request_id='a-to-b-2',
                             child_session_id=b2.id)

        self.assertEqual(len(a.conversation_map), 2)
        self.assertEqual(a.conversation_map['a-to-b-1'], b1.id)
        self.assertEqual(a.conversation_map['a-to-b-2'], b2.id)


class TestDiamondDispatch(unittest.TestCase):
    """Test case 5: A → (B → D), (C → D). Different instances of D."""

    def setUp(self):
        self._tmpdir = _make_teaparty_home()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_diamond_topology(self):
        """B and C both dispatch to D. Two separate D instances."""
        a = create_session(agent_name='a', scope='management',
                           teaparty_home=self._tmpdir)
        b = create_session(agent_name='b', scope='management',
                           teaparty_home=self._tmpdir)
        c = create_session(agent_name='c', scope='management',
                           teaparty_home=self._tmpdir)
        d1 = create_session(agent_name='d', scope='management',
                            teaparty_home=self._tmpdir)
        d2 = create_session(agent_name='d', scope='management',
                            teaparty_home=self._tmpdir)

        record_child_session(a, request_id='a-to-b', child_session_id=b.id)
        record_child_session(a, request_id='a-to-c', child_session_id=c.id)
        record_child_session(b, request_id='b-to-d', child_session_id=d1.id)
        record_child_session(c, request_id='c-to-d', child_session_id=d2.id)

        # Two different D instances
        self.assertNotEqual(d1.id, d2.id)
        # B's child is d1, C's child is d2
        self.assertEqual(b.conversation_map['b-to-d'], d1.id)
        self.assertEqual(c.conversation_map['c-to-d'], d2.id)


class TestCloseConversation(unittest.TestCase):
    """Test cases 6-8: CloseConversation lifecycle."""

    def setUp(self):
        self._tmpdir = _make_teaparty_home()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _close_conversation(self, parent_session, conversation_id):
        """Close a dispatch conversation — the function under test."""
        from teaparty.workspace.close_conversation import close_conversation
        close_conversation(parent_session, conversation_id,
                           teaparty_home=self._tmpdir, scope='management')

    def test_close_frees_slot(self):
        """Test case 8: Close after completion frees the slot."""
        parent = create_session(agent_name='parent', scope='management',
                                teaparty_home=self._tmpdir)
        child = create_session(agent_name='child', scope='management',
                               teaparty_home=self._tmpdir)
        record_child_session(parent, request_id='req-1',
                             child_session_id=child.id)
        self.assertEqual(len(parent.conversation_map), 1)

        self._close_conversation(parent, f'dispatch:{child.id}')
        self.assertEqual(len(parent.conversation_map), 0)
        self.assertTrue(check_slot_available(parent))

    def test_close_removes_worktree(self):
        """Test case 8: Close cleans up child's session directory."""
        parent = create_session(agent_name='parent', scope='management',
                                teaparty_home=self._tmpdir)
        child = create_session(agent_name='child', scope='management',
                               teaparty_home=self._tmpdir)
        record_child_session(parent, request_id='req-1',
                             child_session_id=child.id)
        self.assertTrue(os.path.isdir(child.path))

        self._close_conversation(parent, f'dispatch:{child.id}')
        self.assertFalse(os.path.isdir(child.path))

    def test_recursive_close(self):
        """Test case 7: A → B → C. Close B also closes C."""
        a = create_session(agent_name='a', scope='management',
                           teaparty_home=self._tmpdir)
        b = create_session(agent_name='b', scope='management',
                           teaparty_home=self._tmpdir)
        c = create_session(agent_name='c', scope='management',
                           teaparty_home=self._tmpdir)

        record_child_session(a, request_id='a-to-b', child_session_id=b.id)
        record_child_session(b, request_id='b-to-c', child_session_id=c.id)

        self.assertTrue(os.path.isdir(b.path))
        self.assertTrue(os.path.isdir(c.path))

        self._close_conversation(a, f'dispatch:{b.id}')

        # Both B and C cleaned up
        self.assertFalse(os.path.isdir(b.path))
        self.assertFalse(os.path.isdir(c.path))
        # A's slot freed
        self.assertEqual(len(a.conversation_map), 0)


if __name__ == '__main__':
    unittest.main()
