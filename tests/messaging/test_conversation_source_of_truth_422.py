"""Conversations are the single source of truth for tree/name/parent (#422).

The bus's ``conversations`` table is the one place every reader consults
to answer:

  - "who leads this conversation?" → ``agent_name``
  - "who is this conversation under?" → ``parent_conversation_id``
  - "what Send request created this?" → ``request_id``
  - "what are the children of this conversation?" → ``children_of(id)``

This test file pins the contract at the data layer, before any of the
callers that use it are migrated.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from teaparty.messaging.conversations import (
    ConversationState,
    ConversationType,
    SqliteMessageBus,
)


class TestConversationRecordHoldsAgentName(unittest.TestCase):
    """The bus record carries agent_name; no disk walk needed to get it."""

    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp(prefix='tp422-conv-')
        self._bus = SqliteMessageBus(os.path.join(self._dir, 'bus.db'))

    def test_create_then_read_roundtrips_all_new_fields(self) -> None:
        conv = self._bus.create_conversation(
            ConversationType.SUBTEAM, 'q1',
            agent_name='coding-team',
            parent_conversation_id='job:p1',
            request_id='req-abc',
        )
        self.assertEqual(conv.agent_name, 'coding-team')
        self.assertEqual(conv.parent_conversation_id, 'job:p1')
        self.assertEqual(conv.request_id, 'req-abc')

        loaded = self._bus.get_conversation(conv.id)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.agent_name, 'coding-team')
        self.assertEqual(loaded.parent_conversation_id, 'job:p1')
        self.assertEqual(loaded.request_id, 'req-abc')

    def test_omitted_fields_default_to_empty_string(self) -> None:
        """Roots and legacy callers that don't supply the new fields still work."""
        conv = self._bus.create_conversation(ConversationType.JOB, 'root')
        self.assertEqual(conv.agent_name, '')
        self.assertEqual(conv.parent_conversation_id, '')
        self.assertEqual(conv.request_id, '')


class TestChildrenOfIsTheOneTreeQuery(unittest.TestCase):
    """``children_of`` replaces every disk-walk that resolved the tree."""

    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp(prefix='tp422-tree-')
        self._bus = SqliteMessageBus(os.path.join(self._dir, 'bus.db'))

    def test_children_ordered_by_creation_time(self) -> None:
        parent = self._bus.create_conversation(
            ConversationType.JOB, 'p', agent_name='lead',
        )
        c1 = self._bus.create_conversation(
            ConversationType.SUBTEAM, 'c1',
            agent_name='team-a',
            parent_conversation_id=parent.id,
        )
        c2 = self._bus.create_conversation(
            ConversationType.SUBTEAM, 'c2',
            agent_name='team-b',
            parent_conversation_id=parent.id,
        )
        kids = self._bus.children_of(parent.id)
        self.assertEqual([k.id for k in kids], [c1.id, c2.id])
        self.assertEqual([k.agent_name for k in kids], ['team-a', 'team-b'])

    def test_unrelated_conversations_are_not_children(self) -> None:
        p1 = self._bus.create_conversation(
            ConversationType.JOB, 'p1', agent_name='l1',
        )
        p2 = self._bus.create_conversation(
            ConversationType.JOB, 'p2', agent_name='l2',
        )
        self._bus.create_conversation(
            ConversationType.SUBTEAM, 'a',
            agent_name='team-a',
            parent_conversation_id=p1.id,
        )
        self._bus.create_conversation(
            ConversationType.SUBTEAM, 'b',
            agent_name='team-b',
            parent_conversation_id=p2.id,
        )
        self.assertEqual([k.agent_name for k in self._bus.children_of(p1.id)],
                         ['team-a'])
        self.assertEqual([k.agent_name for k in self._bus.children_of(p2.id)],
                         ['team-b'])

    def test_root_with_no_children_returns_empty(self) -> None:
        root = self._bus.create_conversation(
            ConversationType.JOB, 'root', agent_name='lead',
        )
        self.assertEqual(self._bus.children_of(root.id), [])


class TestPauseLiveConversationsIsTheRecoverySweep(unittest.TestCase):
    """On bridge startup, every pending/active becomes paused (#422)."""

    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp(prefix='tp422-recovery-')
        self._bus = SqliteMessageBus(os.path.join(self._dir, 'bus.db'))

    def test_pending_and_active_are_paused_terminal_states_untouched(self) -> None:
        pending = self._bus.create_conversation(
            ConversationType.SUBTEAM, 'pending',
            agent_name='a',
            state=ConversationState.PENDING,
        )
        active = self._bus.create_conversation(
            ConversationType.SUBTEAM, 'active',
            agent_name='b',
            state=ConversationState.ACTIVE,
        )
        closed = self._bus.create_conversation(
            ConversationType.SUBTEAM, 'closed',
            agent_name='c',
            state=ConversationState.CLOSED,
        )
        withdrawn = self._bus.create_conversation(
            ConversationType.SUBTEAM, 'withdrawn',
            agent_name='d',
            state=ConversationState.WITHDRAWN,
        )

        count = self._bus.pause_live_conversations()
        self.assertEqual(count, 2,
                         'only pending+active transition; terminals untouched')

        self.assertEqual(
            self._bus.get_conversation(pending.id).state,
            ConversationState.PAUSED)
        self.assertEqual(
            self._bus.get_conversation(active.id).state,
            ConversationState.PAUSED)
        self.assertEqual(
            self._bus.get_conversation(closed.id).state,
            ConversationState.CLOSED)
        self.assertEqual(
            self._bus.get_conversation(withdrawn.id).state,
            ConversationState.WITHDRAWN)

    def test_running_sweep_twice_is_a_noop(self) -> None:
        self._bus.create_conversation(
            ConversationType.SUBTEAM, 'a',
            agent_name='x',
            state=ConversationState.ACTIVE,
        )
        first = self._bus.pause_live_conversations()
        second = self._bus.pause_live_conversations()
        self.assertEqual(first, 1)
        self.assertEqual(second, 0, 'sweep is idempotent')


if __name__ == '__main__':
    unittest.main()
