"""Tests for orchestrator/messaging.py — message bus and conversation lifecycle.

Layered:
  1. Conversation identity — make_conversation_id determinism
  2. Message CRUD — send, receive, ordering, timestamps
  3. Conversation lifecycle — create, close, state transitions
  4. Awaiting input — signaling and polling
  5. Agent context — fan-out/fan-in dispatch tracking
"""
import os
import shutil
import tempfile
import time
import unittest

from teaparty.messaging.conversations import (
    ConversationState,
    ConversationType,
    Message,
    SqliteMessageBus,
    make_conversation_id,
)


def _make_bus(tc: unittest.TestCase) -> SqliteMessageBus:
    tmp = tempfile.mkdtemp(prefix='teaparty-test-')
    tc.addCleanup(shutil.rmtree, tmp, True)
    db = os.path.join(tmp, 'messages.db')
    return SqliteMessageBus(db)


# ── Layer 1: Conversation identity ──────────────────────────────────────────

class TestConversationId(unittest.TestCase):
    """make_conversation_id must produce deterministic namespaced IDs."""

    def test_om_format(self):
        cid = make_conversation_id(ConversationType.OFFICE_MANAGER, 'darrell')
        self.assertEqual(cid, 'om:darrell')

    def test_pm_format(self):
        cid = make_conversation_id(ConversationType.PROJECT_MANAGER, 'proj:alice')
        self.assertEqual(cid, 'pm:proj:alice')

    def test_proxy_format(self):
        cid = make_conversation_id(ConversationType.PROXY_REVIEW, 'darrell')
        self.assertEqual(cid, 'proxy:darrell')

    def test_config_lead_format(self):
        cid = make_conversation_id(ConversationType.CONFIG_LEAD, 'global')
        self.assertEqual(cid, 'config:global')

    def test_same_inputs_same_output(self):
        a = make_conversation_id(ConversationType.OFFICE_MANAGER, 'x')
        b = make_conversation_id(ConversationType.OFFICE_MANAGER, 'x')
        self.assertEqual(a, b)

    def test_different_types_different_output(self):
        a = make_conversation_id(ConversationType.OFFICE_MANAGER, 'x')
        b = make_conversation_id(ConversationType.PROJECT_MANAGER, 'x')
        self.assertNotEqual(a, b)


# ── Layer 2: Message CRUD ────────────────────────────────────────────────────

class TestMessageCRUD(unittest.TestCase):
    """Messages must round-trip through send/receive."""

    def test_send_returns_message_id(self):
        bus = _make_bus(self)
        mid = bus.send('conv:1', 'human', 'hello')
        self.assertIsInstance(mid, str)
        self.assertTrue(len(mid) > 0)

    def test_receive_returns_sent_messages(self):
        bus = _make_bus(self)
        bus.send('conv:1', 'human', 'hello')
        bus.send('conv:1', 'agent', 'hi back')
        msgs = bus.receive('conv:1')
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].sender, 'human')
        self.assertEqual(msgs[0].content, 'hello')
        self.assertEqual(msgs[1].sender, 'agent')

    def test_messages_are_message_objects(self):
        bus = _make_bus(self)
        bus.send('conv:1', 'human', 'test')
        msgs = bus.receive('conv:1')
        self.assertIsInstance(msgs[0], Message)
        self.assertIsInstance(msgs[0].timestamp, float)

    def test_receive_empty_conversation(self):
        bus = _make_bus(self)
        msgs = bus.receive('nonexistent')
        self.assertEqual(msgs, [])

    def test_messages_ordered_by_timestamp(self):
        bus = _make_bus(self)
        bus.send('conv:1', 'a', 'first')
        bus.send('conv:1', 'b', 'second')
        bus.send('conv:1', 'c', 'third')
        msgs = bus.receive('conv:1')
        timestamps = [m.timestamp for m in msgs]
        self.assertEqual(timestamps, sorted(timestamps))

    def test_receive_since_timestamp(self):
        bus = _make_bus(self)
        bus.send('conv:1', 'a', 'first')
        time.sleep(0.01)
        cutoff = time.time()
        time.sleep(0.01)
        bus.send('conv:1', 'b', 'second')
        msgs = bus.receive('conv:1', since_timestamp=cutoff)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].content, 'second')

    def test_conversations_list(self):
        bus = _make_bus(self)
        bus.send('conv:a', 'human', 'x')
        bus.send('conv:b', 'human', 'y')
        convs = bus.conversations()
        self.assertIn('conv:a', convs)
        self.assertIn('conv:b', convs)

    def test_conversations_isolated(self):
        bus = _make_bus(self)
        bus.send('conv:a', 'human', 'for a')
        bus.send('conv:b', 'human', 'for b')
        msgs_a = bus.receive('conv:a')
        msgs_b = bus.receive('conv:b')
        self.assertEqual(len(msgs_a), 1)
        self.assertEqual(msgs_a[0].content, 'for a')
        self.assertEqual(len(msgs_b), 1)
        self.assertEqual(msgs_b[0].content, 'for b')


# ── Layer 3: Conversation lifecycle ──────────────────────────────────────────

class TestConversationLifecycle(unittest.TestCase):
    """Conversations transition ACTIVE → CLOSED; closed rejects writes."""

    def test_create_conversation(self):
        bus = _make_bus(self)
        conv = bus.create_conversation(ConversationType.OFFICE_MANAGER, 'alice')
        self.assertEqual(conv.id, 'om:alice')
        self.assertEqual(conv.type, ConversationType.OFFICE_MANAGER)
        self.assertEqual(conv.state, ConversationState.ACTIVE)

    def test_create_idempotent(self):
        bus = _make_bus(self)
        c1 = bus.create_conversation(ConversationType.OFFICE_MANAGER, 'alice')
        c2 = bus.create_conversation(ConversationType.OFFICE_MANAGER, 'alice')
        self.assertEqual(c1.id, c2.id)

    def test_get_conversation(self):
        bus = _make_bus(self)
        bus.create_conversation(ConversationType.OFFICE_MANAGER, 'alice')
        conv = bus.get_conversation('om:alice')
        self.assertIsNotNone(conv)
        self.assertEqual(conv.state, ConversationState.ACTIVE)

    def test_get_nonexistent_returns_none(self):
        bus = _make_bus(self)
        self.assertIsNone(bus.get_conversation('om:nobody'))

    def test_close_conversation(self):
        bus = _make_bus(self)
        bus.create_conversation(ConversationType.OFFICE_MANAGER, 'alice')
        bus.close_conversation('om:alice')
        conv = bus.get_conversation('om:alice')
        self.assertEqual(conv.state, ConversationState.CLOSED)

    def test_active_conversations_filter(self):
        bus = _make_bus(self)
        bus.create_conversation(ConversationType.OFFICE_MANAGER, 'alice')
        bus.create_conversation(ConversationType.OFFICE_MANAGER, 'bob')
        bus.close_conversation('om:bob')
        active = bus.active_conversations(ConversationType.OFFICE_MANAGER)
        ids = [c.id for c in active]
        self.assertIn('om:alice', ids)
        self.assertNotIn('om:bob', ids)

    def test_find_conversation(self):
        bus = _make_bus(self)
        bus.create_conversation(ConversationType.PROXY_REVIEW, 'darrell')
        found = bus.find_conversation(ConversationType.PROXY_REVIEW, 'darrell')
        self.assertIsNotNone(found)
        self.assertEqual(found.id, 'proxy:darrell')


# ── Layer 4: Awaiting input ──────────────────────────────────────────────────

class TestAwaitingInput(unittest.TestCase):
    """awaiting_input flag signals orchestrator is blocked on human."""

    def test_default_not_awaiting(self):
        bus = _make_bus(self)
        bus.create_conversation(ConversationType.OFFICE_MANAGER, 'alice')
        conv = bus.get_conversation('om:alice')
        self.assertFalse(conv.awaiting_input)

    def test_set_and_clear_awaiting(self):
        bus = _make_bus(self)
        bus.create_conversation(ConversationType.OFFICE_MANAGER, 'alice')
        bus.set_awaiting_input('om:alice', True)
        conv = bus.get_conversation('om:alice')
        self.assertTrue(conv.awaiting_input)

        bus.set_awaiting_input('om:alice', False)
        conv = bus.get_conversation('om:alice')
        self.assertFalse(conv.awaiting_input)

    def test_conversations_awaiting_input(self):
        bus = _make_bus(self)
        bus.create_conversation(ConversationType.OFFICE_MANAGER, 'alice')
        bus.create_conversation(ConversationType.OFFICE_MANAGER, 'bob')
        bus.set_awaiting_input('om:alice', True)
        waiting = bus.conversations_awaiting_input()
        ids = [c.id for c in waiting]
        self.assertIn('om:alice', ids)
        self.assertNotIn('om:bob', ids)


# ── Layer 5: Agent context fan-out/fan-in ────────────────────────────────────

class TestAgentContext(unittest.TestCase):
    """Agent context tracks dispatch fan-out and fan-in."""

    def test_create_and_get(self):
        bus = _make_bus(self)
        bus.create_agent_context('ctx-1', 'lead', 'worker')
        ctx = bus.get_agent_context('ctx-1')
        self.assertIsNotNone(ctx)
        self.assertEqual(ctx['initiator_agent_id'], 'lead')
        self.assertEqual(ctx['recipient_agent_id'], 'worker')

    def test_get_nonexistent_returns_none(self):
        bus = _make_bus(self)
        self.assertIsNone(bus.get_agent_context('nope'))

    def test_pending_count_fan_out_fan_in(self):
        bus = _make_bus(self)
        bus.create_agent_context('parent', 'lead', 'coord')
        bus.increment_pending_count('parent')
        bus.increment_pending_count('parent')
        ctx = bus.get_agent_context('parent')
        self.assertEqual(ctx['pending_count'], 2)

        remaining = bus.decrement_pending_count('parent')
        self.assertEqual(remaining, 1)
        remaining = bus.decrement_pending_count('parent')
        self.assertEqual(remaining, 0)

    def test_close_agent_context(self):
        bus = _make_bus(self)
        bus.create_agent_context('ctx-close', 'a', 'b')
        bus.close_agent_context('ctx-close')
        ctx = bus.get_agent_context('ctx-close')
        self.assertEqual(ctx['status'], 'closed')

    def test_open_agent_contexts(self):
        bus = _make_bus(self)
        bus.create_agent_context('open-1', 'a', 'b')
        bus.create_agent_context('open-2', 'a', 'c')
        bus.close_agent_context('open-2')
        open_ctxs = bus.open_agent_contexts()
        ids = [c['context_id'] for c in open_ctxs]
        self.assertIn('open-1', ids)
        self.assertNotIn('open-2', ids)


if __name__ == '__main__':
    unittest.main()
