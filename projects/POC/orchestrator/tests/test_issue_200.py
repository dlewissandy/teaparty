"""Tests for issue #200: Messaging bus with adapter interface.

Verifies:
1. MessageBusAdapter protocol contract (send, receive, conversations)
2. SqliteMessageBus CRUD operations
3. Conversation isolation (messages don't leak across conversations)
4. Temporal filtering (receive with since_timestamp)
5. Conversation type prefixes (office_manager, project_session, subteam)
6. Audit trail: all messages persisted and retrievable
7. MessageBusInputProvider bridges message bus to InputProvider protocol
"""
import asyncio
import os
import tempfile
import time
import unittest

from projects.POC.orchestrator.messaging import (
    ConversationType,
    Message,
    MessageBusAdapter,
    MessageBusInputProvider,
    SqliteMessageBus,
    make_conversation_id,
)


class TestSqliteMessageBus(unittest.TestCase):
    """Core message bus CRUD and contract tests."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmp, 'messages.db')
        self.bus = SqliteMessageBus(self.db_path)

    def tearDown(self):
        self.bus.close()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_send_returns_message_id(self):
        """send() returns a non-empty string message ID."""
        msg_id = self.bus.send('conv1', 'alice', 'hello')
        self.assertIsInstance(msg_id, str)
        self.assertTrue(len(msg_id) > 0)

    def test_receive_returns_sent_messages(self):
        """Messages sent to a conversation are returned by receive()."""
        self.bus.send('conv1', 'alice', 'hello')
        self.bus.send('conv1', 'bob', 'hi there')
        messages = self.bus.receive('conv1')
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].sender, 'alice')
        self.assertEqual(messages[0].content, 'hello')
        self.assertEqual(messages[1].sender, 'bob')
        self.assertEqual(messages[1].content, 'hi there')

    def test_receive_respects_conversation_isolation(self):
        """Messages in one conversation don't appear in another."""
        self.bus.send('conv1', 'alice', 'for conv1')
        self.bus.send('conv2', 'bob', 'for conv2')
        msgs1 = self.bus.receive('conv1')
        msgs2 = self.bus.receive('conv2')
        self.assertEqual(len(msgs1), 1)
        self.assertEqual(msgs1[0].content, 'for conv1')
        self.assertEqual(len(msgs2), 1)
        self.assertEqual(msgs2[0].content, 'for conv2')

    def test_receive_since_timestamp_filters(self):
        """receive(since_timestamp) only returns messages after that time."""
        self.bus.send('conv1', 'alice', 'old message')
        cutoff = time.time()
        time.sleep(0.01)  # ensure timestamp separation
        self.bus.send('conv1', 'bob', 'new message')
        messages = self.bus.receive('conv1', since_timestamp=cutoff)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0].content, 'new message')

    def test_conversations_lists_active(self):
        """conversations() returns all conversation IDs with messages."""
        self.bus.send('conv-a', 'alice', 'msg')
        self.bus.send('conv-b', 'bob', 'msg')
        self.bus.send('conv-a', 'alice', 'another')
        convos = self.bus.conversations()
        self.assertEqual(sorted(convos), ['conv-a', 'conv-b'])

    def test_conversations_empty_when_no_messages(self):
        """conversations() returns empty list when no messages exist."""
        self.assertEqual(self.bus.conversations(), [])

    def test_message_has_timestamp(self):
        """Each message has a float timestamp."""
        self.bus.send('conv1', 'alice', 'hello')
        msgs = self.bus.receive('conv1')
        self.assertIsInstance(msgs[0].timestamp, float)
        self.assertGreater(msgs[0].timestamp, 0)

    def test_message_has_id(self):
        """Each received message has the ID returned by send()."""
        msg_id = self.bus.send('conv1', 'alice', 'hello')
        msgs = self.bus.receive('conv1')
        self.assertEqual(msgs[0].id, msg_id)

    def test_receive_empty_conversation(self):
        """receive() on a non-existent conversation returns empty list."""
        self.assertEqual(self.bus.receive('nonexistent'), [])

    def test_messages_ordered_by_timestamp(self):
        """Messages are returned in chronological order."""
        for i in range(5):
            self.bus.send('conv1', 'sender', f'msg-{i}')
        msgs = self.bus.receive('conv1')
        for i, msg in enumerate(msgs):
            self.assertEqual(msg.content, f'msg-{i}')


class TestConversationTypes(unittest.TestCase):
    """Conversation ID generation for the three conversation types."""

    def test_office_manager_conversation_id(self):
        """Office manager conversations have 'om:' prefix."""
        cid = make_conversation_id(ConversationType.OFFICE_MANAGER, 'darrell')
        self.assertTrue(cid.startswith('om:'))
        self.assertIn('darrell', cid)

    def test_project_session_conversation_id(self):
        """Project session conversations have 'session:' prefix."""
        cid = make_conversation_id(ConversationType.PROJECT_SESSION, '20260327-143000')
        self.assertTrue(cid.startswith('session:'))
        self.assertIn('20260327-143000', cid)

    def test_subteam_conversation_id(self):
        """Subteam conversations have 'team:' prefix."""
        cid = make_conversation_id(ConversationType.SUBTEAM, 'writing-abc123')
        self.assertTrue(cid.startswith('team:'))
        self.assertIn('writing-abc123', cid)

    def test_no_namespace_collisions(self):
        """Different types with same qualifier produce different IDs."""
        om = make_conversation_id(ConversationType.OFFICE_MANAGER, 'test')
        sess = make_conversation_id(ConversationType.PROJECT_SESSION, 'test')
        team = make_conversation_id(ConversationType.SUBTEAM, 'test')
        self.assertEqual(len({om, sess, team}), 3)


class TestMessageBusInputProvider(unittest.TestCase):
    """MessageBusInputProvider bridges message bus → InputProvider protocol."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmp, 'messages.db')
        self.bus = SqliteMessageBus(self.db_path)
        self.conversation_id = 'session:test-session'
        self.provider = MessageBusInputProvider(
            bus=self.bus,
            conversation_id=self.conversation_id,
        )

    def tearDown(self):
        self.bus.close()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_input_request(self, **kwargs):
        from projects.POC.orchestrator.events import InputRequest
        defaults = {
            'type': 'approval',
            'state': 'INTENT_ASSERT',
            'artifact': '',
            'bridge_text': 'Do you approve?',
        }
        defaults.update(kwargs)
        return InputRequest(**defaults)

    def test_call_sends_question_and_receives_answer(self):
        """Calling the provider sends the question to the bus and returns the human's response."""
        request = self._make_input_request(bridge_text='Approve this?')

        async def _run():
            # Simulate human responding after a short delay
            async def _respond():
                await asyncio.sleep(0.05)
                self.bus.send(self.conversation_id, 'human', 'yes, approved')

            asyncio.ensure_future(_respond())
            result = await self.provider(request)
            return result

        result = asyncio.get_event_loop().run_until_complete(_run())
        self.assertEqual(result, 'yes, approved')

    def test_question_persisted_to_bus(self):
        """The agent's question is persisted as a message in the bus."""
        request = self._make_input_request(bridge_text='What color?')

        async def _run():
            async def _respond():
                await asyncio.sleep(0.05)
                self.bus.send(self.conversation_id, 'human', 'blue')

            asyncio.ensure_future(_respond())
            await self.provider(request)

        asyncio.get_event_loop().run_until_complete(_run())
        msgs = self.bus.receive(self.conversation_id)
        # Should have both the question and the answer
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].sender, 'orchestrator')
        self.assertIn('What color?', msgs[0].content)

    def test_audit_trail_preserved(self):
        """All exchanges are in the bus for audit purposes."""
        async def _run():
            for i in range(3):
                req = self._make_input_request(bridge_text=f'Question {i}')

                async def _respond(n=i):
                    await asyncio.sleep(0.05)
                    self.bus.send(self.conversation_id, 'human', f'Answer {n}')

                asyncio.ensure_future(_respond())
                await self.provider(req)

        asyncio.get_event_loop().run_until_complete(_run())
        msgs = self.bus.receive(self.conversation_id)
        # 3 questions + 3 answers = 6 messages
        self.assertEqual(len(msgs), 6)


class TestAdapterProtocol(unittest.TestCase):
    """MessageBusAdapter protocol compliance."""

    def test_sqlite_bus_satisfies_protocol(self):
        """SqliteMessageBus is a valid MessageBusAdapter."""
        tmp = tempfile.mkdtemp()
        try:
            bus = SqliteMessageBus(os.path.join(tmp, 'test.db'))
            self.assertIsInstance(bus, MessageBusAdapter)
            bus.close()
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
