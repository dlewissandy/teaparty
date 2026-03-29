"""Tests for issue #288: input_requested event needs structural signal.

Verifies that MessageBusInputProvider sets a structural awaiting_input flag
on the conversations table rather than requiring content heuristics.

Acceptance criteria:
1. conversations table has awaiting_input column (schema)
2. SqliteMessageBus provides set_awaiting_input() and conversations_awaiting_input()
3. MessageBusInputProvider sets flag when posting question
4. MessageBusInputProvider clears flag when human responds (and on error)
5. check_message_bus_request() uses structural column, not message scan
6. conversations_awaiting_input() returns only conversations with flag set
"""
import asyncio
import os
import sqlite3
import tempfile
import unittest

from projects.POC.orchestrator.messaging import (
    ConversationType,
    MessageBusInputProvider,
    SqliteMessageBus,
    make_conversation_id,
)


class TestAwaitingInputSchema(unittest.TestCase):
    """conversations table has awaiting_input column."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmp, 'messages.db')
        self.bus = SqliteMessageBus(self.db_path)

    def tearDown(self):
        self.bus.close()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_awaiting_input_column_exists_in_conversations_table(self):
        """conversations table has an awaiting_input column."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute('PRAGMA table_info(conversations)')
        columns = {row[1] for row in cursor.fetchall()}
        conn.close()
        self.assertIn('awaiting_input', columns)

    def test_awaiting_input_defaults_to_zero(self):
        """New conversations have awaiting_input=0 by default."""
        cid = make_conversation_id(ConversationType.PROJECT_SESSION, 'test')
        self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'test')
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            'SELECT awaiting_input FROM conversations WHERE id = ?', (cid,)
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], 0)

    def test_awaiting_input_column_present_on_existing_db_after_reinit(self):
        """Re-opening an existing DB adds awaiting_input column if missing."""
        self.bus.close()
        # Create a DB without the column to simulate an older schema
        conn = sqlite3.connect(self.db_path)
        conn.execute('DROP TABLE IF EXISTS conversations')
        conn.execute('''
            CREATE TABLE conversations (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'active',
                created_at REAL NOT NULL
            )
        ''')
        conn.commit()
        conn.close()
        # Re-open — should migrate the schema
        bus2 = SqliteMessageBus(self.db_path)
        bus2.create_conversation(ConversationType.PROJECT_SESSION, 'migrated')
        cid = make_conversation_id(ConversationType.PROJECT_SESSION, 'migrated')
        conn2 = sqlite3.connect(self.db_path)
        row = conn2.execute(
            'SELECT awaiting_input FROM conversations WHERE id = ?', (cid,)
        ).fetchone()
        conn2.close()
        bus2.close()
        self.assertEqual(row[0], 0)


class TestSetAwaitingInput(unittest.TestCase):
    """SqliteMessageBus.set_awaiting_input() sets and clears the flag."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmp, 'messages.db')
        self.bus = SqliteMessageBus(self.db_path)
        self.conv = self.bus.create_conversation(
            ConversationType.PROJECT_SESSION, 'test-set'
        )

    def tearDown(self):
        self.bus.close()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_set_awaiting_input_true_marks_conversation(self):
        """set_awaiting_input(True) marks the conversation as awaiting input."""
        self.bus.set_awaiting_input(self.conv.id, True)
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            'SELECT awaiting_input FROM conversations WHERE id = ?',
            (self.conv.id,),
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], 1)

    def test_set_awaiting_input_false_clears_conversation(self):
        """set_awaiting_input(False) clears the awaiting_input flag."""
        self.bus.set_awaiting_input(self.conv.id, True)
        self.bus.set_awaiting_input(self.conv.id, False)
        conn = sqlite3.connect(self.db_path)
        row = conn.execute(
            'SELECT awaiting_input FROM conversations WHERE id = ?',
            (self.conv.id,),
        ).fetchone()
        conn.close()
        self.assertEqual(row[0], 0)

    def test_conversations_awaiting_input_returns_flagged_conversations(self):
        """conversations_awaiting_input() returns only conversations with flag set."""
        c1 = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'w1')
        c2 = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'w2')
        c3 = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'w3')
        self.bus.set_awaiting_input(c1.id, True)
        self.bus.set_awaiting_input(c3.id, True)

        waiting = self.bus.conversations_awaiting_input()
        waiting_ids = {c.id for c in waiting}
        self.assertIn(c1.id, waiting_ids)
        self.assertIn(c3.id, waiting_ids)
        self.assertNotIn(c2.id, waiting_ids)

    def test_conversations_awaiting_input_excludes_closed_conversations(self):
        """conversations_awaiting_input() excludes closed conversations."""
        c = self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'closed-w')
        self.bus.set_awaiting_input(c.id, True)
        self.bus.close_conversation(c.id)

        waiting = self.bus.conversations_awaiting_input()
        waiting_ids = {conv.id for conv in waiting}
        self.assertNotIn(c.id, waiting_ids)

    def test_conversations_awaiting_input_empty_when_none_flagged(self):
        """conversations_awaiting_input() returns empty list when no flag is set."""
        self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'no-flag')
        self.assertEqual(self.bus.conversations_awaiting_input(), [])


class TestMessageBusInputProviderSetsFlag(unittest.TestCase):
    """MessageBusInputProvider sets and clears awaiting_input via the bus."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmp, 'messages.db')
        self.bus = SqliteMessageBus(self.db_path)
        self.conv_id = make_conversation_id(ConversationType.PROJECT_SESSION, 'flag-test')
        self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'flag-test')
        self.provider = MessageBusInputProvider(
            bus=self.bus,
            conversation_id=self.conv_id,
            poll_interval=0.02,
        )

    def tearDown(self):
        self.bus.close()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_input_request(self, bridge_text='Approve?'):
        from projects.POC.orchestrator.events import InputRequest
        return InputRequest(
            type='approval',
            state='INTENT_ASSERT',
            artifact='',
            bridge_text=bridge_text,
        )

    def test_awaiting_input_set_after_question_posted(self):
        """Flag is set in the DB after the provider posts its question."""
        request = self._make_input_request('Approve the intent?')
        flag_observed = []

        async def _run():
            async def _check_and_respond():
                await asyncio.sleep(0.05)
                waiting = self.bus.conversations_awaiting_input()
                flag_observed.append(any(c.id == self.conv_id for c in waiting))
                self.bus.send(self.conv_id, 'human', 'yes')

            asyncio.ensure_future(_check_and_respond())
            await self.provider(request)

        asyncio.new_event_loop().run_until_complete(_run())
        self.assertTrue(flag_observed[0], 'awaiting_input should be set while waiting')

    def test_awaiting_input_cleared_after_human_responds(self):
        """Flag is cleared in the DB after the human response is received."""
        request = self._make_input_request('Approve the plan?')

        async def _run():
            async def _respond():
                await asyncio.sleep(0.05)
                self.bus.send(self.conv_id, 'human', 'approved')

            asyncio.ensure_future(_respond())
            await self.provider(request)

        asyncio.new_event_loop().run_until_complete(_run())
        waiting = self.bus.conversations_awaiting_input()
        waiting_ids = {c.id for c in waiting}
        self.assertNotIn(self.conv_id, waiting_ids)

    def test_awaiting_input_not_set_before_call(self):
        """Flag is not set before provider is called."""
        waiting = self.bus.conversations_awaiting_input()
        self.assertEqual(waiting, [])

    def test_bridge_can_detect_awaiting_input_without_content_inspection(self):
        """Bridge detects input-needed state via structural query, not message content."""
        request = self._make_input_request('Is this correct?')
        detected_structurally = []

        async def _run():
            async def _bridge_poll_and_respond():
                await asyncio.sleep(0.05)
                # Bridge queries structural column — no message content inspection
                waiting = self.bus.conversations_awaiting_input()
                conv_ids = [c.id for c in waiting]
                detected_structurally.append(self.conv_id in conv_ids)
                self.bus.send(self.conv_id, 'human', 'yes')

            asyncio.ensure_future(_bridge_poll_and_respond())
            await self.provider(request)

        asyncio.new_event_loop().run_until_complete(_run())
        self.assertTrue(
            detected_structurally[0],
            'Bridge structural query must detect awaiting_input without inspecting message content',
        )


class TestIpcUsesStructuralFlag(unittest.TestCase):
    """check_message_bus_request uses awaiting_input column, not content heuristic."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self._tmp, 'messages.db')
        self.bus = SqliteMessageBus(self.db_path)
        self.conv_id = make_conversation_id(ConversationType.PROJECT_SESSION, 'ipc-test')
        self.bus.create_conversation(ConversationType.PROJECT_SESSION, 'ipc-test')

    def tearDown(self):
        self.bus.close()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_no_pending_request_when_flag_not_set(self):
        """check_message_bus_request returns None when awaiting_input=0."""
        from projects.POC.tui.ipc import check_message_bus_request
        # Even with orchestrator message, no flag means not awaiting
        self.bus.send(self.conv_id, 'orchestrator', 'A question')
        result = check_message_bus_request(self.db_path, self.conv_id)
        self.assertIsNone(result)

    def test_pending_request_when_flag_is_set(self):
        """check_message_bus_request returns request when awaiting_input=1."""
        from projects.POC.tui.ipc import check_message_bus_request
        self.bus.send(self.conv_id, 'orchestrator', 'Approve?')
        self.bus.set_awaiting_input(self.conv_id, True)
        result = check_message_bus_request(self.db_path, self.conv_id)
        self.assertIsNotNone(result)
        self.assertIn('bridge_text', result)

    def test_no_pending_request_after_flag_cleared(self):
        """check_message_bus_request returns None after flag is cleared."""
        from projects.POC.tui.ipc import check_message_bus_request
        self.bus.send(self.conv_id, 'orchestrator', 'Approve?')
        self.bus.set_awaiting_input(self.conv_id, True)
        self.bus.set_awaiting_input(self.conv_id, False)
        result = check_message_bus_request(self.db_path, self.conv_id)
        self.assertIsNone(result)

    def test_structural_flag_not_content_heuristic(self):
        """An orchestrator message followed by a human reply, then another orchestrator
        message NOT flagged: check_message_bus_request returns None.

        This test fails under the old heuristic (which would detect the trailing
        orchestrator message as pending) but passes when the structural flag is used.
        """
        from projects.POC.tui.ipc import check_message_bus_request
        # Exchange where human already answered the pending question
        self.bus.send(self.conv_id, 'orchestrator', 'First question')
        self.bus.send(self.conv_id, 'human', 'My answer')
        # Another orchestrator message (informational, not a question)
        self.bus.send(self.conv_id, 'orchestrator', 'Got it, proceeding.')
        # Flag is NOT set — no input needed
        result = check_message_bus_request(self.db_path, self.conv_id)
        self.assertIsNone(
            result,
            'Trailing orchestrator message without flag must not be treated as pending',
        )


if __name__ == '__main__':
    unittest.main()
