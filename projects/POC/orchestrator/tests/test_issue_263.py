"""Tests for issue #263: Conversation identity and persistence across chat patterns.

Verifies:
1. ConversationType covers all 5 patterns from the reference table
2. Conversation dataclass with id, type, state, created_at metadata
3. SqliteMessageBus tracks conversation metadata in a conversations table
4. Conversation lifecycle: active → closed (with read-only history)
5. Persistent conversations (office_manager, proxy_review) resumable by qualifier
6. Multiple active conversations listed and filtered by type
7. make_conversation_id supports all 5 patterns with correct identity schemes
"""
import os
import tempfile
import time
import unittest

from projects.POC.orchestrator.messaging import (
    Conversation,
    ConversationState,
    ConversationType,
    Message,
    SqliteMessageBus,
    make_conversation_id,
)


class TestConversationTypeCompleteness(unittest.TestCase):
    """ConversationType covers all 5 patterns from conversation-identity.md."""

    def test_office_manager_type_exists(self):
        self.assertIsNotNone(ConversationType.OFFICE_MANAGER)

    def test_job_type_exists(self):
        """Job chat: one per project+job, lives with the job."""
        self.assertIsNotNone(ConversationType.JOB)

    def test_task_type_exists(self):
        """Task chat: one per project+job+task, lives with the task."""
        self.assertIsNotNone(ConversationType.TASK)

    def test_proxy_review_type_exists(self):
        """Proxy review: one per decider, indefinite persistence."""
        self.assertIsNotNone(ConversationType.PROXY_REVIEW)

    def test_liaison_type_exists(self):
        """Liaison chat: session-scoped, requester+target."""
        self.assertIsNotNone(ConversationType.LIAISON)

    def test_backward_compat_project_session(self):
        """PROJECT_SESSION still exists for backward compatibility."""
        self.assertIsNotNone(ConversationType.PROJECT_SESSION)

    def test_backward_compat_subteam(self):
        """SUBTEAM still exists for backward compatibility."""
        self.assertIsNotNone(ConversationType.SUBTEAM)


class TestConversationIdentitySchemes(unittest.TestCase):
    """make_conversation_id produces correct IDs for all 5 patterns."""

    def test_office_manager_id(self):
        """Office manager: om:{human}."""
        cid = make_conversation_id(ConversationType.OFFICE_MANAGER, 'darrell')
        self.assertEqual(cid, 'om:darrell')

    def test_job_id(self):
        """Job chat: job:{project}:{job_id}."""
        cid = make_conversation_id(ConversationType.JOB, 'myproject:job-001')
        self.assertEqual(cid, 'job:myproject:job-001')

    def test_task_id(self):
        """Task chat: task:{project}:{job_id}:{task_id}."""
        cid = make_conversation_id(ConversationType.TASK, 'myproject:job-001:task-a')
        self.assertEqual(cid, 'task:myproject:job-001:task-a')

    def test_proxy_review_id(self):
        """Proxy review: proxy:{decider_id}."""
        cid = make_conversation_id(ConversationType.PROXY_REVIEW, 'darrell')
        self.assertEqual(cid, 'proxy:darrell')

    def test_liaison_id(self):
        """Liaison chat: liaison:{requester}:{target}."""
        cid = make_conversation_id(ConversationType.LIAISON, 'alice:bob')
        self.assertEqual(cid, 'liaison:alice:bob')

    def test_no_collisions_across_types(self):
        """Same qualifier in different types produces different IDs."""
        ids = set()
        for ct in ConversationType:
            ids.add(make_conversation_id(ct, 'test'))
        self.assertEqual(len(ids), len(ConversationType))


class TestConversationDataclass(unittest.TestCase):
    """Conversation entity with metadata."""

    def test_conversation_has_required_fields(self):
        conv = Conversation(
            id='om:darrell',
            type=ConversationType.OFFICE_MANAGER,
            state=ConversationState.ACTIVE,
            created_at=time.time(),
        )
        self.assertEqual(conv.id, 'om:darrell')
        self.assertEqual(conv.type, ConversationType.OFFICE_MANAGER)
        self.assertEqual(conv.state, ConversationState.ACTIVE)
        self.assertIsInstance(conv.created_at, float)

    def test_conversation_state_enum(self):
        """ConversationState has ACTIVE and CLOSED members."""
        self.assertIsNotNone(ConversationState.ACTIVE)
        self.assertIsNotNone(ConversationState.CLOSED)


class TestConversationLifecycle(unittest.TestCase):
    """SqliteMessageBus tracks conversation metadata and lifecycle."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmp, 'messages.db')
        self.bus = SqliteMessageBus(self.db_path)

    def tearDown(self):
        self.bus.close()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_create_conversation(self):
        """create_conversation stores metadata and returns a Conversation."""
        conv = self.bus.create_conversation(
            ConversationType.OFFICE_MANAGER, 'darrell',
        )
        self.assertEqual(conv.id, 'om:darrell')
        self.assertEqual(conv.type, ConversationType.OFFICE_MANAGER)
        self.assertEqual(conv.state, ConversationState.ACTIVE)
        self.assertIsInstance(conv.created_at, float)

    def test_get_conversation(self):
        """get_conversation retrieves stored metadata."""
        self.bus.create_conversation(ConversationType.JOB, 'proj:job-1')
        conv = self.bus.get_conversation('job:proj:job-1')
        self.assertIsNotNone(conv)
        self.assertEqual(conv.type, ConversationType.JOB)
        self.assertEqual(conv.state, ConversationState.ACTIVE)

    def test_get_nonexistent_conversation_returns_none(self):
        conv = self.bus.get_conversation('om:nobody')
        self.assertIsNone(conv)

    def test_close_conversation(self):
        """close_conversation transitions state to CLOSED."""
        self.bus.create_conversation(ConversationType.JOB, 'proj:job-1')
        self.bus.close_conversation('job:proj:job-1')
        conv = self.bus.get_conversation('job:proj:job-1')
        self.assertEqual(conv.state, ConversationState.CLOSED)

    def test_closed_conversation_history_still_readable(self):
        """Messages in a closed conversation are still retrievable."""
        self.bus.create_conversation(ConversationType.JOB, 'proj:job-1')
        cid = 'job:proj:job-1'
        self.bus.send(cid, 'orchestrator', 'task started')
        self.bus.close_conversation(cid)
        msgs = self.bus.receive(cid)
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].content, 'task started')

    def test_send_to_closed_conversation_raises(self):
        """Cannot send new messages to a closed conversation."""
        self.bus.create_conversation(ConversationType.JOB, 'proj:job-1')
        cid = 'job:proj:job-1'
        self.bus.close_conversation(cid)
        with self.assertRaises(ValueError):
            self.bus.send(cid, 'orchestrator', 'should fail')


class TestMultipleActiveConversations(unittest.TestCase):
    """Multiple simultaneous active conversations."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmp, 'messages.db')
        self.bus = SqliteMessageBus(self.db_path)

    def tearDown(self):
        self.bus.close()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_list_active_conversations(self):
        """active_conversations returns all conversations in ACTIVE state."""
        self.bus.create_conversation(ConversationType.OFFICE_MANAGER, 'darrell')
        self.bus.create_conversation(ConversationType.JOB, 'proj:job-1')
        self.bus.create_conversation(ConversationType.JOB, 'proj:job-2')
        active = self.bus.active_conversations()
        self.assertEqual(len(active), 3)

    def test_list_active_filtered_by_type(self):
        """active_conversations(type=...) filters by conversation type."""
        self.bus.create_conversation(ConversationType.OFFICE_MANAGER, 'darrell')
        self.bus.create_conversation(ConversationType.JOB, 'proj:job-1')
        self.bus.create_conversation(ConversationType.TASK, 'proj:job-1:task-a')
        jobs = self.bus.active_conversations(conv_type=ConversationType.JOB)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].type, ConversationType.JOB)

    def test_closed_not_in_active_list(self):
        """Closed conversations don't appear in active_conversations."""
        self.bus.create_conversation(ConversationType.JOB, 'proj:job-1')
        self.bus.create_conversation(ConversationType.JOB, 'proj:job-2')
        self.bus.close_conversation('job:proj:job-1')
        active = self.bus.active_conversations()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].id, 'job:proj:job-2')

    def test_multiple_types_simultaneously(self):
        """Multiple conversation types can be active at once."""
        self.bus.create_conversation(ConversationType.OFFICE_MANAGER, 'darrell')
        self.bus.create_conversation(ConversationType.JOB, 'proj:job-1')
        self.bus.create_conversation(ConversationType.TASK, 'proj:job-1:task-a')
        self.bus.create_conversation(ConversationType.PROXY_REVIEW, 'darrell')
        active = self.bus.active_conversations()
        types = {c.type for c in active}
        self.assertEqual(types, {
            ConversationType.OFFICE_MANAGER,
            ConversationType.JOB,
            ConversationType.TASK,
            ConversationType.PROXY_REVIEW,
        })


class TestConversationPersistenceAndResume(unittest.TestCase):
    """Persistent conversations survive across bus instances (TUI restarts)."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmp, 'messages.db')

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_office_manager_persists_across_restarts(self):
        """Office manager conversation and its messages survive a bus reconnect."""
        bus1 = SqliteMessageBus(self.db_path)
        bus1.create_conversation(ConversationType.OFFICE_MANAGER, 'darrell')
        bus1.send('om:darrell', 'human', 'Hello office manager')
        bus1.send('om:darrell', 'office-manager', 'Hello! How can I help?')
        bus1.close()

        # Reconnect — simulates TUI restart
        bus2 = SqliteMessageBus(self.db_path)
        conv = bus2.get_conversation('om:darrell')
        self.assertIsNotNone(conv)
        self.assertEqual(conv.state, ConversationState.ACTIVE)
        msgs = bus2.receive('om:darrell')
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].content, 'Hello office manager')
        bus2.close()

    def test_proxy_review_persists_across_restarts(self):
        """Proxy review conversation persists indefinitely."""
        bus1 = SqliteMessageBus(self.db_path)
        bus1.create_conversation(ConversationType.PROXY_REVIEW, 'darrell')
        bus1.send('proxy:darrell', 'human', 'Show me your confidence levels')
        bus1.close()

        bus2 = SqliteMessageBus(self.db_path)
        conv = bus2.get_conversation('proxy:darrell')
        self.assertIsNotNone(conv)
        self.assertEqual(conv.state, ConversationState.ACTIVE)
        msgs = bus2.receive('proxy:darrell')
        self.assertEqual(len(msgs), 1)
        bus2.close()

    def test_find_conversation_by_qualifier(self):
        """find_conversation locates a persistent conversation by type+qualifier."""
        bus = SqliteMessageBus(self.db_path)
        bus.create_conversation(ConversationType.OFFICE_MANAGER, 'darrell')
        bus.create_conversation(ConversationType.OFFICE_MANAGER, 'alice')
        conv = bus.find_conversation(ConversationType.OFFICE_MANAGER, 'darrell')
        self.assertIsNotNone(conv)
        self.assertEqual(conv.id, 'om:darrell')
        bus.close()

    def test_resume_adds_to_existing_history(self):
        """Resuming a conversation appends to existing message history."""
        bus1 = SqliteMessageBus(self.db_path)
        bus1.create_conversation(ConversationType.OFFICE_MANAGER, 'darrell')
        bus1.send('om:darrell', 'human', 'Day 1 message')
        bus1.close()

        bus2 = SqliteMessageBus(self.db_path)
        bus2.send('om:darrell', 'human', 'Day 2 message')
        msgs = bus2.receive('om:darrell')
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].content, 'Day 1 message')
        self.assertEqual(msgs[1].content, 'Day 2 message')
        bus2.close()

    def test_create_existing_conversation_returns_existing(self):
        """Creating a conversation that already exists returns the existing one."""
        bus = SqliteMessageBus(self.db_path)
        conv1 = bus.create_conversation(ConversationType.OFFICE_MANAGER, 'darrell')
        conv2 = bus.create_conversation(ConversationType.OFFICE_MANAGER, 'darrell')
        self.assertEqual(conv1.id, conv2.id)
        # Should not duplicate
        active = bus.active_conversations(conv_type=ConversationType.OFFICE_MANAGER)
        self.assertEqual(len(active), 1)
        bus.close()


class TestImplicitConversationCreation(unittest.TestCase):
    """Sending to an unknown conversation creates it implicitly for backward compat."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmp, 'messages.db')
        self.bus = SqliteMessageBus(self.db_path)

    def tearDown(self):
        self.bus.close()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_send_to_unknown_conversation_still_works(self):
        """Sending to a conversation that wasn't explicitly created still stores the message."""
        self.bus.send('session:legacy-123', 'orchestrator', 'hello')
        msgs = self.bus.receive('session:legacy-123')
        self.assertEqual(len(msgs), 1)


if __name__ == '__main__':
    unittest.main()
