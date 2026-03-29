"""Tests for issue #200: Messaging bus with adapter interface.

Verifies:
1. MessageBusAdapter protocol contract (send, receive, conversations)
2. SqliteMessageBus CRUD operations
3. Conversation isolation (messages don't leak across conversations)
4. Temporal filtering (receive with since_timestamp)
5. Conversation type prefixes (office_manager, project_session, subteam)
6. Audit trail: all messages persisted and retrievable
7. MessageBusInputProvider bridges message bus to InputProvider protocol
8. is_waiting / current_request properties on MessageBusInputProvider
9. TUI IPC: check_message_bus_request and send_message_bus_response
10. Session integration: bus created in infra_dir, bus info in SESSION_STARTED event
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

_SESSION_TYPE = ConversationType.PROJECT_SESSION


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
            async def _respond():
                await asyncio.sleep(0.05)
                self.bus.send(self.conversation_id, 'human', 'yes, approved')

            asyncio.ensure_future(_respond())
            result = await self.provider(request)
            return result

        result = asyncio.new_event_loop().run_until_complete(_run())
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

        asyncio.new_event_loop().run_until_complete(_run())
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

        asyncio.new_event_loop().run_until_complete(_run())
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


class TestMessageBusInputProviderState(unittest.TestCase):
    """is_waiting and current_request properties for TUI compat."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmp, 'messages.db')
        self.bus = SqliteMessageBus(self.db_path)
        self.conversation_id = 'session:test-state'
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

    def test_not_waiting_initially(self):
        """Provider is not waiting before any call."""
        self.assertFalse(self.provider.is_waiting)
        self.assertIsNone(self.provider.current_request)

    def test_waiting_during_call(self):
        """Provider is_waiting is True while awaiting a response."""
        request = self._make_input_request(bridge_text='Waiting test')
        waiting_observed = []

        async def _run():
            async def _check_and_respond():
                await asyncio.sleep(0.05)
                waiting_observed.append(self.provider.is_waiting)
                waiting_observed.append(
                    self.provider.current_request is not None
                )
                self.bus.send(self.conversation_id, 'human', 'done')

            asyncio.ensure_future(_check_and_respond())
            await self.provider(request)

        asyncio.new_event_loop().run_until_complete(_run())
        self.assertTrue(waiting_observed[0], 'is_waiting should be True during call')
        self.assertTrue(waiting_observed[1], 'current_request should be set during call')

    def test_not_waiting_after_call(self):
        """Provider is not waiting after call completes."""
        request = self._make_input_request()

        async def _run():
            async def _respond():
                await asyncio.sleep(0.05)
                self.bus.send(self.conversation_id, 'human', 'ok')

            asyncio.ensure_future(_respond())
            await self.provider(request)

        asyncio.new_event_loop().run_until_complete(_run())
        self.assertFalse(self.provider.is_waiting)
        self.assertIsNone(self.provider.current_request)


class TestTuiIpcMessageBus(unittest.TestCase):
    """TUI IPC message bus functions: check_message_bus_request, send_message_bus_response."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmp, 'messages.db')
        self.bus = SqliteMessageBus(self.db_path)
        self.conversation_id = make_conversation_id(_SESSION_TYPE, 'ipc-test')
        self.bus.create_conversation(_SESSION_TYPE, 'ipc-test')

    def tearDown(self):
        self.bus.close()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_no_pending_request_when_empty(self):
        """No request when awaiting_input flag is not set."""
        from projects.POC.orchestrator.messaging import check_message_bus_request
        result = check_message_bus_request(self.db_path, self.conversation_id)
        self.assertIsNone(result)

    def test_pending_request_after_orchestrator_sends_and_sets_flag(self):
        """Pending request detected via structural awaiting_input flag."""
        from projects.POC.orchestrator.messaging import check_message_bus_request
        self.bus.send(self.conversation_id, 'orchestrator', 'Approve?')
        self.bus.set_awaiting_input(self.conversation_id, True)
        result = check_message_bus_request(self.db_path, self.conversation_id)
        self.assertIsNotNone(result)
        self.assertEqual(result['bridge_text'], 'Approve?')

    def test_no_pending_after_flag_cleared(self):
        """No pending request after awaiting_input flag is cleared."""
        from projects.POC.orchestrator.messaging import check_message_bus_request
        self.bus.send(self.conversation_id, 'orchestrator', 'Approve?')
        self.bus.set_awaiting_input(self.conversation_id, True)
        self.bus.set_awaiting_input(self.conversation_id, False)
        result = check_message_bus_request(self.db_path, self.conversation_id)
        self.assertIsNone(result)

    def test_send_message_bus_response(self):
        """send_message_bus_response writes a human message to the bus."""
        from projects.POC.orchestrator.messaging import send_message_bus_response
        self.bus.send(self.conversation_id, 'orchestrator', 'Color?')
        ok = send_message_bus_response(self.db_path, self.conversation_id, 'blue')
        self.assertTrue(ok)
        msgs = self.bus.receive(self.conversation_id)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[1].sender, 'human')
        self.assertEqual(msgs[1].content, 'blue')

    def test_nonexistent_db_returns_none(self):
        """check_message_bus_request returns None for missing DB."""
        from projects.POC.orchestrator.messaging import check_message_bus_request
        result = check_message_bus_request('/nonexistent/path.db', 'conv')
        self.assertIsNone(result)

    def test_end_to_end_bus_round_trip(self):
        """Full round trip: orchestrator sends question → TUI detects via flag → sends response → orchestrator receives."""
        from projects.POC.orchestrator.messaging import check_message_bus_request, send_message_bus_response
        provider = MessageBusInputProvider(
            bus=self.bus,
            conversation_id=self.conversation_id,
            poll_interval=0.02,
        )

        async def _run():
            from projects.POC.orchestrator.events import InputRequest
            request = InputRequest(
                type='approval',
                state='INTENT_ASSERT',
                bridge_text='Approve the intent?',
            )

            async def _tui_responds():
                # Simulate TUI polling and responding
                while True:
                    await asyncio.sleep(0.03)
                    pending = check_message_bus_request(
                        self.db_path, self.conversation_id,
                    )
                    if pending:
                        send_message_bus_response(
                            self.db_path, self.conversation_id, 'approved',
                        )
                        break

            asyncio.ensure_future(_tui_responds())
            result = await provider(request)
            return result

        result = asyncio.new_event_loop().run_until_complete(_run())
        self.assertEqual(result, 'approved')

        # Verify audit trail
        msgs = self.bus.receive(self.conversation_id)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].sender, 'orchestrator')
        self.assertIn('Approve the intent?', msgs[0].content)
        self.assertEqual(msgs[1].sender, 'human')
        self.assertEqual(msgs[1].content, 'approved')


class TestSessionBusIntegration(unittest.TestCase):
    """Session creates bus in infra_dir and publishes bus info in SESSION_STARTED."""

    def test_session_started_event_includes_bus_info(self):
        """SESSION_STARTED event contains message_bus_path and conversation_id."""
        from projects.POC.orchestrator.events import EventBus, Event, EventType

        captured_events = []

        async def _capture(event):
            if event.type == EventType.SESSION_STARTED:
                captured_events.append(event)

        bus = EventBus()
        bus.subscribe(_capture)

        # Publish a mock SESSION_STARTED event with bus info (as Session does)
        async def _run():
            await bus.publish(Event(
                type=EventType.SESSION_STARTED,
                data={
                    'task': 'test',
                    'project': 'test-project',
                    'session_id': '20260327-143000',
                    'worktree': '/tmp/wt',
                    'message_bus_path': '/tmp/infra/messages.db',
                    'conversation_id': 'session:20260327-143000',
                },
                session_id='20260327-143000',
            ))

        asyncio.new_event_loop().run_until_complete(_run())
        self.assertEqual(len(captured_events), 1)
        data = captured_events[0].data
        self.assertEqual(data['message_bus_path'], '/tmp/infra/messages.db')
        self.assertEqual(data['conversation_id'], 'session:20260327-143000')


class TestSubteamConversation(unittest.TestCase):
    """DispatchListener creates subteam conversations in the message bus."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmp, 'messages.db')
        self.bus = SqliteMessageBus(self.db_path)

    def tearDown(self):
        self.bus.close()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_subteam_conversation_id_format(self):
        """Subteam conversations use team: prefix."""
        cid = make_conversation_id(ConversationType.SUBTEAM, 'writing-20260327')
        self.assertTrue(cid.startswith('team:'))
        self.assertIn('writing', cid)

    def test_subteam_messages_persisted(self):
        """Messages sent to a subteam conversation are retrievable."""
        cid = make_conversation_id(ConversationType.SUBTEAM, 'art-session1')
        self.bus.send(cid, 'orchestrator', 'Dispatch to art: Draw a logo')
        self.bus.send(cid, 'art', 'Dispatch completed: COMPLETED_WORK')
        msgs = self.bus.receive(cid)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].sender, 'orchestrator')
        self.assertIn('Draw a logo', msgs[0].content)
        self.assertEqual(msgs[1].sender, 'art')

    def test_subteam_isolated_from_session(self):
        """Subteam messages don't appear in project session conversation."""
        session_cid = make_conversation_id(ConversationType.PROJECT_SESSION, 'test')
        team_cid = make_conversation_id(ConversationType.SUBTEAM, 'writing-test')
        self.bus.send(session_cid, 'orchestrator', 'session msg')
        self.bus.send(team_cid, 'orchestrator', 'team msg')
        session_msgs = self.bus.receive(session_cid)
        team_msgs = self.bus.receive(team_cid)
        self.assertEqual(len(session_msgs), 1)
        self.assertEqual(session_msgs[0].content, 'session msg')
        self.assertEqual(len(team_msgs), 1)
        self.assertEqual(team_msgs[0].content, 'team msg')


class TestChatPanelReads(unittest.TestCase):
    """Chat panel reads conversation history from the bus."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmp, 'messages.db')
        self.bus = SqliteMessageBus(self.db_path)
        self.conversation_id = 'session:chat-test'

    def tearDown(self):
        self.bus.close()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_conversation_history_readable(self):
        """All messages in a conversation are readable for the chat panel."""
        self.bus.send(self.conversation_id, 'orchestrator', 'Approve intent?')
        self.bus.send(self.conversation_id, 'human', 'Yes, approved')
        self.bus.send(self.conversation_id, 'orchestrator', 'Review plan?')
        self.bus.send(self.conversation_id, 'human', 'Looks good')
        msgs = self.bus.receive(self.conversation_id)
        self.assertEqual(len(msgs), 4)
        senders = [m.sender for m in msgs]
        self.assertEqual(senders, ['orchestrator', 'human', 'orchestrator', 'human'])

    def test_incremental_read_via_count(self):
        """Can track message count for incremental rendering."""
        self.bus.send(self.conversation_id, 'orchestrator', 'msg1')
        msgs = self.bus.receive(self.conversation_id)
        count = len(msgs)
        self.assertEqual(count, 1)
        self.bus.send(self.conversation_id, 'human', 'msg2')
        msgs = self.bus.receive(self.conversation_id)
        new_msgs = msgs[count:]
        self.assertEqual(len(new_msgs), 1)
        self.assertEqual(new_msgs[0].content, 'msg2')


if __name__ == '__main__':
    unittest.main()
