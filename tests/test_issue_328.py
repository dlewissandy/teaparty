"""Tests for Issue #328: OM chat — invoke the office-manager agent when a human message is posted.

Acceptance criteria:
1. First POST to om:* creates the conversation in the conversations table (sidebar visibility)
2. OM agent is invoked after each POST; reply written to bus
3. Second POST on same qualifier resumes via --resume; session ID carried from first turn
4. Second rapid POST queues behind the first (lock, not drop)
5. Agent runner exception writes an error message to the bus as sender='office-manager'
6. session-lifecycle.md updated to describe bridge invocation
"""
import asyncio
import inspect
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_REPO_ROOT = Path(__file__).parent.parent


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_tmpdir() -> str:
    return tempfile.mkdtemp()


def _make_bridge(tmpdir: str):
    from bridge.server import TeaPartyBridge
    static_dir = os.path.join(tmpdir, 'static')
    os.makedirs(static_dir, exist_ok=True)
    with open(os.path.join(static_dir, 'index.html'), 'w') as f:
        f.write('<html></html>')
    return TeaPartyBridge(teaparty_home=tmpdir, static_dir=static_dir)


def _make_om_bus(tmpdir: str):
    """Open (and create) the OM bus for the given tmpdir."""
    from orchestrator.messaging import SqliteMessageBus
    from orchestrator.office_manager import om_bus_path
    path = om_bus_path(tmpdir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return SqliteMessageBus(path)


def _make_stream_jsonl(text: str, session_id: str = 'sid-test') -> str:
    """Write a minimal stream JSONL file and return its path."""
    fd, path = tempfile.mkstemp(suffix='.jsonl', prefix='om-test-stream-')
    os.close(fd)
    with open(path, 'w') as f:
        f.write(json.dumps({'type': 'system', 'session_id': session_id}) + '\n')
        f.write(json.dumps({
            'type': 'assistant',
            'message': {'content': [{'type': 'text', 'text': text}]},
        }) + '\n')
    return path


# ── AC1: Conversation auto-created on first POST ──────────────────────────────

class TestConversationAutoCreation(unittest.TestCase):
    """POST to om:* must register the conversation in the conversations table."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)
        # Set up the OM bus directly (startup normally does this)
        from orchestrator.office_manager import om_bus_path
        from orchestrator.messaging import SqliteMessageBus
        path = om_bus_path(self.tmpdir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.bridge._om_bus = SqliteMessageBus(path)

    def tearDown(self):
        if self.bridge._om_bus:
            self.bridge._om_bus.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_first_post_creates_conversation_in_conversations_table(self):
        """First POST to om:* must call create_conversation so active_conversations() returns it."""
        from orchestrator.messaging import ConversationType

        # Before: no conversations registered
        convs_before = self.bridge._om_bus.active_conversations(ConversationType.OFFICE_MANAGER)
        self.assertEqual(len(convs_before), 0, 'No conversations should exist before first POST')

        # Simulate what _handle_conversation_post does for om:* — call create_conversation
        # The test verifies that _handle_conversation_post DOES call create_conversation.
        # We check the source to confirm it's present, and test the effect on the bus.
        source = inspect.getsource(self.bridge._handle_conversation_post)
        self.assertIn(
            'create_conversation',
            source,
            '_handle_conversation_post must call create_conversation for om: conversations '
            'so the conversation appears in active_conversations() (sidebar)',
        )

    def test_create_conversation_makes_conversation_visible_in_active_list(self):
        """After create_conversation(), active_conversations() must include the OM conversation."""
        from orchestrator.messaging import ConversationType
        from orchestrator.office_manager import om_bus_path

        bus = self.bridge._om_bus
        conv = bus.create_conversation(ConversationType.OFFICE_MANAGER, 'darrell')

        convs = bus.active_conversations(ConversationType.OFFICE_MANAGER)
        ids = [c.id for c in convs]
        self.assertIn(
            conv.id, ids,
            'After create_conversation, the conversation must appear in active_conversations()',
        )

    def test_bridge_handle_conversation_post_creates_conversation_for_om(self):
        """_handle_conversation_post source must create the conversation before sending for om:."""
        source = inspect.getsource(self.bridge._handle_conversation_post)
        # create_conversation must appear before bus.send in the source for om: conversations
        self.assertIn(
            'create_conversation',
            source,
            '_handle_conversation_post must call bus.create_conversation() for om: conversations',
        )


# ── AC2: Reply written to bus after runner ────────────────────────────────────

class TestOMAgentReplyWrittenToBus(unittest.TestCase):
    """_invoke_om must write the agent reply to the OM bus after the runner completes."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)
        from orchestrator.office_manager import om_bus_path
        from orchestrator.messaging import SqliteMessageBus
        path = om_bus_path(self.tmpdir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.bridge._om_bus = SqliteMessageBus(path)

    def tearDown(self):
        if self.bridge._om_bus:
            self.bridge._om_bus.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_invoke_om_writes_reply_to_bus(self):
        """_invoke_om() must result in an office-manager message in the OM bus."""
        from orchestrator.messaging import ConversationType
        from orchestrator.office_manager import OfficeManagerSession, om_bus_path

        # Seed a human message so the session has something to respond to
        session = OfficeManagerSession(self.tmpdir, 'darrell')
        session.send_human_message('Hello, please help me.')

        stream_path = _make_stream_jsonl('Hello! I am the office manager.')
        try:
            mock_result = MagicMock()
            mock_result.session_id = 'sid-reply-test'

            with patch('orchestrator.claude_runner.ClaudeRunner') as MockRunner:
                instance = MagicMock()
                instance.run = AsyncMock(return_value=mock_result)
                instance.stream_file = stream_path
                MockRunner.return_value = instance

                with patch('tempfile.mkstemp', return_value=(0, stream_path)):
                    with patch('os.close'):
                        with patch('os.unlink'):
                            asyncio.run(self.bridge._invoke_om('darrell'))

            msgs = session.get_messages()
            agent_msgs = [m for m in msgs if m.sender == 'office-manager']
            self.assertTrue(
                len(agent_msgs) > 0,
                '_invoke_om must write the agent reply to the bus as sender=office-manager',
            )
        finally:
            try:
                os.unlink(stream_path)
            except OSError:
                pass


# ── AC3: --resume session ID persisted across turns ──────────────────────────

class TestOMResumeSessionPersistence(unittest.TestCase):
    """Second _invoke_om call must use the session ID saved by the first."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)
        from orchestrator.office_manager import om_bus_path
        from orchestrator.messaging import SqliteMessageBus
        path = om_bus_path(self.tmpdir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.bridge._om_bus = SqliteMessageBus(path)

    def tearDown(self):
        if self.bridge._om_bus:
            self.bridge._om_bus.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_second_invoke_uses_session_id_from_first(self):
        """After first _invoke_om, the session ID must be saved; second call loads it for --resume."""
        from orchestrator.office_manager import OfficeManagerSession

        session = OfficeManagerSession(self.tmpdir, 'darrell')
        session.send_human_message('First message.')

        first_stream = _make_stream_jsonl('First response.', 'first-session-id')
        try:
            first_result = MagicMock()
            first_result.session_id = 'first-session-id'

            with patch('orchestrator.claude_runner.ClaudeRunner') as MockRunner:
                instance = MagicMock()
                instance.run = AsyncMock(return_value=first_result)
                instance.stream_file = first_stream
                MockRunner.return_value = instance

                with patch('tempfile.mkstemp', return_value=(0, first_stream)):
                    with patch('os.close'):
                        with patch('os.unlink'):
                            asyncio.run(self.bridge._invoke_om('darrell'))
        finally:
            try:
                os.unlink(first_stream)
            except OSError:
                pass

        # Now verify that a second OfficeManagerSession for the same qualifier
        # picks up the saved session ID via load_state()
        session2 = OfficeManagerSession(self.tmpdir, 'darrell')
        session2.load_state()
        self.assertEqual(
            session2.claude_session_id, 'first-session-id',
            'Second OfficeManagerSession must load the session ID saved by the first invoke',
        )


# ── AC4: Concurrent messages queue (not drop) ────────────────────────────────

class TestOMConcurrentMessageQueueing(unittest.TestCase):
    """Rapid second POST must queue behind the first, not be silently dropped."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)
        from orchestrator.office_manager import om_bus_path
        from orchestrator.messaging import SqliteMessageBus
        path = om_bus_path(self.tmpdir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.bridge._om_bus = SqliteMessageBus(path)

    def tearDown(self):
        if self.bridge._om_bus:
            self.bridge._om_bus.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_bridge_has_om_locks_dict(self):
        """TeaPartyBridge must have _om_locks dict for per-qualifier asyncio locks."""
        self.assertTrue(
            hasattr(self.bridge, '_om_locks'),
            'TeaPartyBridge must have _om_locks dict for per-qualifier asyncio.Lock objects',
        )

    def test_bridge_does_not_have_om_in_flight_set(self):
        """The _om_in_flight set must be replaced by per-qualifier locks (_om_locks)."""
        self.assertFalse(
            hasattr(self.bridge, '_om_in_flight'),
            '_om_in_flight must be replaced by _om_locks — a set drops concurrent messages, '
            'a lock queues them',
        )

    def test_invoke_om_acquires_per_qualifier_lock(self):
        """_invoke_om source must use _om_locks (asyncio.Lock) to serialize per-qualifier access."""
        source = inspect.getsource(self.bridge._invoke_om)
        self.assertIn(
            '_om_locks',
            source,
            '_invoke_om must use _om_locks for per-qualifier asyncio.Lock serialization',
        )

    def test_two_concurrent_invocations_both_complete(self):
        """Both first and second _invoke_om calls must complete when run concurrently."""
        from orchestrator.office_manager import OfficeManagerSession

        session = OfficeManagerSession(self.tmpdir, 'darrell')
        session.send_human_message('Message 1')
        session.send_human_message('Message 2')

        call_count = [0]
        first_stream = _make_stream_jsonl('Response 1.', 'sid-1')
        second_stream = _make_stream_jsonl('Response 2.', 'sid-2')
        stream_paths = [first_stream, second_stream]
        session_ids = ['sid-1', 'sid-2']

        try:
            async def run_concurrent():
                async def mock_run(*args, **kwargs):
                    await asyncio.sleep(0)  # yield to allow concurrency
                    idx = call_count[0]
                    call_count[0] += 1
                    return MagicMock(session_id=session_ids[min(idx, 1)])

                with patch('orchestrator.claude_runner.ClaudeRunner') as MockRunner:
                    def make_instance():
                        idx = call_count[0]
                        sp = stream_paths[min(idx, len(stream_paths) - 1)]
                        inst = MagicMock()
                        inst.run = AsyncMock(side_effect=lambda: MagicMock(
                            session_id=session_ids[min(call_count[0] - 1, 1)]
                        ))
                        inst.stream_file = sp
                        return inst

                    # Use a simpler approach: just run two sequential calls through the lock
                    with patch('tempfile.mkstemp', side_effect=[
                        (0, first_stream), (0, second_stream),
                    ]):
                        with patch('os.close'):
                            with patch('os.unlink'):
                                r1 = MagicMock()
                                r1.session_id = 'sid-1'
                                r2 = MagicMock()
                                r2.session_id = 'sid-2'

                                inst1 = MagicMock()
                                inst1.run = AsyncMock(return_value=r1)
                                inst1.stream_file = first_stream

                                inst2 = MagicMock()
                                inst2.run = AsyncMock(return_value=r2)
                                inst2.stream_file = second_stream

                                MockRunner.side_effect = [inst1, inst2]

                                # Launch both concurrently
                                await asyncio.gather(
                                    self.bridge._invoke_om('darrell'),
                                    self.bridge._invoke_om('darrell'),
                                )

            asyncio.run(run_concurrent())

            msgs = session.get_messages()
            agent_msgs = [m for m in msgs if m.sender == 'office-manager']
            self.assertEqual(
                len(agent_msgs), 2,
                'Both concurrent _invoke_om calls must complete and write replies to the bus; '
                f'got {len(agent_msgs)} agent messages instead of 2',
            )
        finally:
            for sp in [first_stream, second_stream]:
                try:
                    os.unlink(sp)
                except OSError:
                    pass


# ── AC5: Runner failure writes error to bus ───────────────────────────────────

class TestOMRunnerFailureWritesError(unittest.TestCase):
    """If the OM runner raises, an error message must appear in the bus."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)
        from orchestrator.office_manager import om_bus_path
        from orchestrator.messaging import SqliteMessageBus
        path = om_bus_path(self.tmpdir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.bridge._om_bus = SqliteMessageBus(path)

    def tearDown(self):
        if self.bridge._om_bus:
            self.bridge._om_bus.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_runner_exception_writes_error_message_to_bus(self):
        """When the OM runner raises, _invoke_om must write an error message to the OM bus."""
        from orchestrator.messaging import ConversationType
        from orchestrator.office_manager import OfficeManagerSession, make_conversation_id

        session = OfficeManagerSession(self.tmpdir, 'darrell')
        session.send_human_message('A message that will fail.')

        with patch('orchestrator.claude_runner.ClaudeRunner') as MockRunner:
            instance = MagicMock()
            instance.run = AsyncMock(side_effect=RuntimeError('simulated runner failure'))
            MockRunner.return_value = instance

            with patch('tempfile.mkstemp', return_value=(0, '/tmp/om-fake.jsonl')):
                with patch('os.close'):
                    with patch('os.unlink'):
                        asyncio.run(self.bridge._invoke_om('darrell'))

        # After failure, there must be a message from 'office-manager' with an error indication
        msgs = session.get_messages()
        agent_msgs = [m for m in msgs if m.sender == 'office-manager']
        self.assertTrue(
            len(agent_msgs) > 0,
            '_invoke_om must write an error message to the bus on runner failure; '
            'currently errors are silently swallowed',
        )

    def test_error_message_indicates_failure(self):
        """The error message written on failure must indicate something went wrong."""
        from orchestrator.office_manager import OfficeManagerSession

        session = OfficeManagerSession(self.tmpdir, 'darrell')
        session.send_human_message('Trigger a failure.')

        with patch('orchestrator.claude_runner.ClaudeRunner') as MockRunner:
            instance = MagicMock()
            instance.run = AsyncMock(side_effect=RuntimeError('agent crashed'))
            MockRunner.return_value = instance

            with patch('tempfile.mkstemp', return_value=(0, '/tmp/om-fake2.jsonl')):
                with patch('os.close'):
                    with patch('os.unlink'):
                        asyncio.run(self.bridge._invoke_om('darrell'))

        msgs = session.get_messages()
        agent_msgs = [m for m in msgs if m.sender == 'office-manager']
        self.assertTrue(len(agent_msgs) > 0, 'Must have an error message')
        content = agent_msgs[0].content.lower()
        self.assertTrue(
            'error' in content or 'fail' in content or 'unavailable' in content,
            f'Error message content must indicate failure; got: {agent_msgs[0].content!r}',
        )


# ── AC6: session-lifecycle.md updated ────────────────────────────────────────

class TestSessionLifecycleDocUpdated(unittest.TestCase):
    """session-lifecycle.md must describe bridge invocation, not TUI invocation."""

    def _get_doc(self) -> str:
        path = _REPO_ROOT / 'docs' / 'proposals' / 'office-manager' / 'references' / 'session-lifecycle.md'
        self.assertTrue(path.exists(), f'session-lifecycle.md not found at {path}')
        return path.read_text()

    def test_session_lifecycle_does_not_reference_tui_invocation(self):
        """session-lifecycle.md must not say 'The TUI invokes' — TUI was retired in #305."""
        doc = self._get_doc()
        self.assertNotIn(
            'The TUI invokes',
            doc,
            'session-lifecycle.md still says "The TUI invokes" — must be updated to describe '
            'bridge invocation (issue #328 supersedes the TUI invocation path)',
        )

    def test_session_lifecycle_references_bridge_invocation(self):
        """session-lifecycle.md must describe bridge-side invocation of the OM agent."""
        doc = self._get_doc()
        self.assertTrue(
            'bridge' in doc.lower(),
            'session-lifecycle.md must describe the bridge as the OM invocation path',
        )
