"""Tests for issue #206: TUI chat panel for human-agent conversations.

Verifies:
1. ConversationIndex discovers conversations across sessions
2. Unread tracking: last-read timestamps, unread counts
3. Conversation switching: selecting a conversation loads its messages
4. Gate messages rendered with context in conversation flow
5. Notification: conversations with unread messages flagged
6. Human messages sent through the bus via ChatModel
7. Sender attribution and timestamps on messages
"""
import os
import tempfile
import time
import unittest

from projects.POC.orchestrator.messaging import (
    ConversationType,
    SqliteMessageBus,
    make_conversation_id,
)


def _make_bus(tmp_dir, name='messages.db'):
    """Create a SqliteMessageBus in a temp directory."""
    path = os.path.join(tmp_dir, name)
    return SqliteMessageBus(path), path


class TestConversationIndex(unittest.TestCase):
    """ConversationIndex discovers and lists conversations from the bus."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.bus, self.bus_path = _make_bus(self._tmp)

    def tearDown(self):
        self.bus.close()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_empty_bus_returns_no_conversations(self):
        """No conversations when bus has no messages or conversation records."""
        from projects.POC.tui.chat_model import ConversationIndex
        index = ConversationIndex(self.bus)
        self.assertEqual(index.list_conversations(), [])

    def test_discovers_active_conversations(self):
        """Lists conversations that have been created in the bus."""
        self.bus.create_conversation(ConversationType.OFFICE_MANAGER, 'darrell')
        self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'sess-1')
        from projects.POC.tui.chat_model import ConversationIndex
        index = ConversationIndex(self.bus)
        convos = index.list_conversations()
        ids = [c.id for c in convos]
        self.assertIn('om:darrell', ids)
        self.assertIn('session:sess-1', ids)

    def test_excludes_closed_conversations(self):
        """Closed conversations are not listed."""
        self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'active')
        c = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'done')
        self.bus.close_conversation(c.id)
        from projects.POC.tui.chat_model import ConversationIndex
        index = ConversationIndex(self.bus)
        convos = index.list_conversations()
        ids = [c.id for c in convos]
        self.assertIn('session:active', ids)
        self.assertNotIn('session:done', ids)

    def test_conversation_types_included(self):
        """All three conversation types (office_manager, project_session, subteam) are listed."""
        self.bus.create_conversation(ConversationType.OFFICE_MANAGER, 'user')
        self.bus.create_conversation(ConversationType.PROJECT_SESSION, 's1')
        self.bus.create_conversation(ConversationType.SUBTEAM, 'writing-abc')
        from projects.POC.tui.chat_model import ConversationIndex
        index = ConversationIndex(self.bus)
        convos = index.list_conversations()
        types = {c.type for c in convos}
        self.assertIn(ConversationType.OFFICE_MANAGER, types)
        self.assertIn(ConversationType.PROJECT_SESSION, types)
        self.assertIn(ConversationType.SUBTEAM, types)


class TestUnreadTracking(unittest.TestCase):
    """Unread counts and last-read timestamp tracking."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.bus, self.bus_path = _make_bus(self._tmp)

    def tearDown(self):
        self.bus.close()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_new_conversation_messages_are_unread(self):
        """Messages in a conversation the human hasn't viewed are counted as unread."""
        conv = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'test')
        self.bus.send(conv.id, 'orchestrator', 'Hello')
        self.bus.send(conv.id, 'orchestrator', 'Approve?')
        from projects.POC.tui.chat_model import UnreadTracker
        tracker = UnreadTracker()
        count = tracker.unread_count(self.bus, conv.id)
        self.assertEqual(count, 2)

    def test_marking_read_clears_unread(self):
        """After mark_read(), unread count drops to zero."""
        conv = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'test')
        self.bus.send(conv.id, 'orchestrator', 'msg1')
        self.bus.send(conv.id, 'orchestrator', 'msg2')
        from projects.POC.tui.chat_model import UnreadTracker
        tracker = UnreadTracker()
        tracker.mark_read(conv.id)
        count = tracker.unread_count(self.bus, conv.id)
        self.assertEqual(count, 0)

    def test_new_messages_after_mark_read_are_unread(self):
        """Messages arriving after mark_read() are counted as unread."""
        conv = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'test')
        self.bus.send(conv.id, 'orchestrator', 'old')
        from projects.POC.tui.chat_model import UnreadTracker
        tracker = UnreadTracker()
        tracker.mark_read(conv.id)
        time.sleep(0.01)
        self.bus.send(conv.id, 'orchestrator', 'new')
        count = tracker.unread_count(self.bus, conv.id)
        self.assertEqual(count, 1)

    def test_has_unread_returns_bool(self):
        """has_unread() returns True when there are unread messages."""
        conv = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'test')
        from projects.POC.tui.chat_model import UnreadTracker
        tracker = UnreadTracker()
        self.assertFalse(tracker.has_unread(self.bus, conv.id))
        self.bus.send(conv.id, 'orchestrator', 'ping')
        self.assertTrue(tracker.has_unread(self.bus, conv.id))


class TestConversationSwitching(unittest.TestCase):
    """Selecting a conversation loads its messages."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.bus, self.bus_path = _make_bus(self._tmp)

    def tearDown(self):
        self.bus.close()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_load_messages_for_selected_conversation(self):
        """ChatModel.messages() returns messages for the specified conversation."""
        c1 = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'sess-a')
        c2 = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'sess-b')
        self.bus.send(c1.id, 'orchestrator', 'msg for a')
        self.bus.send(c2.id, 'orchestrator', 'msg for b')
        from projects.POC.tui.chat_model import ChatModel
        model = ChatModel(self.bus)
        msgs_a = model.messages(c1.id)
        msgs_b = model.messages(c2.id)
        self.assertEqual(len(msgs_a), 1)
        self.assertEqual(msgs_a[0].content, 'msg for a')
        self.assertEqual(len(msgs_b), 1)
        self.assertEqual(msgs_b[0].content, 'msg for b')

    def test_switching_marks_previous_as_read(self):
        """Selecting a conversation marks it as read in the unread tracker."""
        c1 = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'sess-a')
        self.bus.send(c1.id, 'orchestrator', 'unread msg')
        from projects.POC.tui.chat_model import ChatModel
        model = ChatModel(self.bus)
        model.select_conversation(c1.id)
        self.assertEqual(model.unread_tracker.unread_count(self.bus, c1.id), 0)


class TestGateMessagesInChat(unittest.TestCase):
    """Gate interactions appear as chat messages with context."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.bus, self.bus_path = _make_bus(self._tmp)

    def tearDown(self):
        self.bus.close()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_gate_question_appears_in_conversation(self):
        """When orchestrator sends a gate question, it appears in messages."""
        conv = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'gate-test')
        self.bus.send(conv.id, 'orchestrator', 'Review intent: The project will...')
        from projects.POC.tui.chat_model import ChatModel
        model = ChatModel(self.bus)
        msgs = model.messages(conv.id)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].sender, 'orchestrator')
        self.assertIn('Review intent', msgs[0].content)

    def test_human_gate_response_sent_through_bus(self):
        """Human's gate response goes through the bus as a chat message."""
        conv = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'gate-test')
        self.bus.send(conv.id, 'orchestrator', 'Approve plan?')
        from projects.POC.tui.chat_model import ChatModel
        model = ChatModel(self.bus)
        model.send_message(conv.id, 'Approved, looks good')
        msgs = model.messages(conv.id)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[1].sender, 'human')
        self.assertEqual(msgs[1].content, 'Approved, looks good')


class TestNotifications(unittest.TestCase):
    """Conversations needing attention are flagged."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.bus, self.bus_path = _make_bus(self._tmp)

    def tearDown(self):
        self.bus.close()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_pending_gate_flagged_as_needs_attention(self):
        """A conversation with an unanswered orchestrator message needs attention."""
        conv = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'attn-test')
        self.bus.send(conv.id, 'orchestrator', 'Approve?')
        from projects.POC.tui.chat_model import ChatModel
        model = ChatModel(self.bus)
        self.assertTrue(model.needs_attention(conv.id))

    def test_answered_gate_not_flagged(self):
        """A conversation where the human has responded does not need attention."""
        conv = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'attn-test')
        self.bus.send(conv.id, 'orchestrator', 'Approve?')
        self.bus.send(conv.id, 'human', 'Yes')
        from projects.POC.tui.chat_model import ChatModel
        model = ChatModel(self.bus)
        self.assertFalse(model.needs_attention(conv.id))

    def test_conversations_needing_attention_listed(self):
        """attention_conversations() returns only conversations needing attention."""
        c1 = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'needs')
        c2 = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'ok')
        self.bus.send(c1.id, 'orchestrator', 'Question?')
        self.bus.send(c2.id, 'orchestrator', 'Question?')
        self.bus.send(c2.id, 'human', 'Answer')
        from projects.POC.tui.chat_model import ChatModel
        model = ChatModel(self.bus)
        attention = model.attention_conversations()
        ids = [c.id for c in attention]
        self.assertIn(c1.id, ids)
        self.assertNotIn(c2.id, ids)


class TestSenderAttributionAndTimestamps(unittest.TestCase):
    """Messages have sender attribution and timestamps."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.bus, self.bus_path = _make_bus(self._tmp)

    def tearDown(self):
        self.bus.close()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_messages_have_sender(self):
        """Each message has sender attribution."""
        conv = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'test')
        self.bus.send(conv.id, 'orchestrator', 'Hello')
        self.bus.send(conv.id, 'human', 'Hi')
        from projects.POC.tui.chat_model import ChatModel
        model = ChatModel(self.bus)
        msgs = model.messages(conv.id)
        self.assertEqual(msgs[0].sender, 'orchestrator')
        self.assertEqual(msgs[1].sender, 'human')

    def test_messages_have_timestamps(self):
        """Each message has a float timestamp."""
        conv = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'test')
        self.bus.send(conv.id, 'orchestrator', 'Hello')
        from projects.POC.tui.chat_model import ChatModel
        model = ChatModel(self.bus)
        msgs = model.messages(conv.id)
        self.assertIsInstance(msgs[0].timestamp, float)
        self.assertGreater(msgs[0].timestamp, 0)

    def test_format_message_includes_sender_and_time(self):
        """format_message() produces a string with sender label and timestamp."""
        conv = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'test')
        self.bus.send(conv.id, 'orchestrator', 'Review this')
        from projects.POC.tui.chat_model import ChatModel, format_message
        model = ChatModel(self.bus)
        msgs = model.messages(conv.id)
        formatted = format_message(msgs[0])
        self.assertIn('orchestrator', formatted)
        # Should include some time representation
        self.assertIn(':', formatted)  # HH:MM format


class TestChatModelSendMessage(unittest.TestCase):
    """ChatModel.send_message() sends human messages through the bus."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.bus, self.bus_path = _make_bus(self._tmp)

    def tearDown(self):
        self.bus.close()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_send_message_persists_to_bus(self):
        """Messages sent via ChatModel are persisted in the bus."""
        conv = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'test')
        from projects.POC.tui.chat_model import ChatModel
        model = ChatModel(self.bus)
        model.send_message(conv.id, 'Hello from human')
        msgs = self.bus.receive(conv.id)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].sender, 'human')
        self.assertEqual(msgs[0].content, 'Hello from human')

    def test_send_message_returns_message_id(self):
        """send_message() returns the message ID."""
        conv = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'test')
        from projects.POC.tui.chat_model import ChatModel
        model = ChatModel(self.bus)
        msg_id = model.send_message(conv.id, 'test')
        self.assertIsInstance(msg_id, str)
        self.assertTrue(len(msg_id) > 0)


class TestMultiBusAggregation(unittest.TestCase):
    """ChatModel aggregates conversations across multiple session buses."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        # Two separate session buses (like two different sessions)
        self.bus1, self.bus1_path = _make_bus(self._tmp, 'session1.db')
        self.bus2, self.bus2_path = _make_bus(self._tmp, 'session2.db')

    def tearDown(self):
        self.bus1.close()
        self.bus2.close()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_aggregates_conversations_across_buses(self):
        """Conversations from multiple buses appear in a single listing."""
        self.bus1.create_conversation(ConversationType.PROJECT_SESSION, 'sess-1')
        self.bus2.create_conversation(ConversationType.PROJECT_SESSION, 'sess-2')
        from projects.POC.tui.chat_model import ChatModel
        model = ChatModel.from_bus_paths([self.bus1_path, self.bus2_path])
        convos = model.conversations()
        ids = [c.id for c in convos]
        self.assertIn('session:sess-1', ids)
        self.assertIn('session:sess-2', ids)

    def test_messages_from_correct_bus(self):
        """Messages are read from the bus that owns the conversation."""
        c1 = self.bus1.create_conversation(ConversationType.PROJECT_SESSION, 'sess-1')
        self.bus1.send(c1.id, 'orchestrator', 'msg from bus1')
        c2 = self.bus2.create_conversation(ConversationType.PROJECT_SESSION, 'sess-2')
        self.bus2.send(c2.id, 'orchestrator', 'msg from bus2')
        from projects.POC.tui.chat_model import ChatModel
        model = ChatModel.from_bus_paths([self.bus1_path, self.bus2_path])
        msgs1 = model.messages(c1.id)
        msgs2 = model.messages(c2.id)
        self.assertEqual(len(msgs1), 1)
        self.assertEqual(msgs1[0].content, 'msg from bus1')
        self.assertEqual(len(msgs2), 1)
        self.assertEqual(msgs2[0].content, 'msg from bus2')

    def test_send_to_correct_bus(self):
        """send_message routes to the bus that owns the conversation."""
        c1 = self.bus1.create_conversation(ConversationType.PROJECT_SESSION, 'sess-1')
        from projects.POC.tui.chat_model import ChatModel
        model = ChatModel.from_bus_paths([self.bus1_path, self.bus2_path])
        model.send_message(c1.id, 'human reply')
        # Verify it went to bus1, not bus2
        msgs = self.bus1.receive(c1.id)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].sender, 'human')
        msgs2 = self.bus2.receive(c1.id)
        self.assertEqual(len(msgs2), 0)

    def test_attention_across_buses(self):
        """attention_conversations() spans all buses."""
        c1 = self.bus1.create_conversation(ConversationType.PROJECT_SESSION, 'sess-1')
        self.bus1.send(c1.id, 'orchestrator', 'Question?')
        c2 = self.bus2.create_conversation(ConversationType.PROJECT_SESSION, 'sess-2')
        self.bus2.send(c2.id, 'orchestrator', 'Another?')
        self.bus2.send(c2.id, 'human', 'Answer')
        from projects.POC.tui.chat_model import ChatModel
        model = ChatModel.from_bus_paths([self.bus1_path, self.bus2_path])
        attention = model.attention_conversations()
        ids = [c.id for c in attention]
        self.assertIn(c1.id, ids)
        self.assertNotIn(c2.id, ids)


class TestDashboardAttentionCount(unittest.TestCase):
    """Dashboard can query total attention count across all conversations."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.bus, self.bus_path = _make_bus(self._tmp)

    def tearDown(self):
        self.bus.close()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_attention_count_for_dashboard(self):
        """attention_count() returns total number of conversations needing attention."""
        c1 = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'a')
        c2 = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'b')
        c3 = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'c')
        self.bus.send(c1.id, 'orchestrator', 'Q1?')
        self.bus.send(c2.id, 'orchestrator', 'Q2?')
        self.bus.send(c3.id, 'orchestrator', 'Q3?')
        self.bus.send(c3.id, 'human', 'A3')
        from projects.POC.tui.chat_model import ChatModel
        model = ChatModel(self.bus)
        self.assertEqual(model.attention_count(), 2)


class TestGateContextInMessages(unittest.TestCase):
    """Gate messages include CfA state and artifact references."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.bus, self.bus_path = _make_bus(self._tmp)

    def tearDown(self):
        self.bus.close()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_format_gate_message_includes_state_label(self):
        """format_gate_message() includes a human-readable CfA state label."""
        from projects.POC.tui.chat_model import format_gate_context
        context = format_gate_context(
            cfa_state='INTENT_ASSERT',
            artifact_path='/tmp/session/INTENT.md',
        )
        self.assertIn('review intent', context.lower())
        self.assertIn('INTENT.md', context)

    def test_format_gate_message_plan_assert(self):
        """format_gate_context for PLAN_ASSERT references the plan."""
        from projects.POC.tui.chat_model import format_gate_context
        context = format_gate_context(
            cfa_state='PLAN_ASSERT',
            artifact_path='/tmp/session/plan.md',
        )
        self.assertIn('plan', context.lower())
        self.assertIn('plan.md', context)

    def test_format_gate_message_work_assert(self):
        """format_gate_context for WORK_ASSERT references the work."""
        from projects.POC.tui.chat_model import format_gate_context
        context = format_gate_context(
            cfa_state='WORK_ASSERT',
            artifact_path='',
        )
        self.assertIn('work', context.lower())

    def test_format_gate_message_escalation(self):
        """format_gate_context for escalation states."""
        from projects.POC.tui.chat_model import format_gate_context
        context = format_gate_context(
            cfa_state='INTENT_ESCALATE',
            artifact_path='',
        )
        self.assertIn('question', context.lower())


if __name__ == '__main__':
    unittest.main()
