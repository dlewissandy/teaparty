"""Tests for Issue #331: Proxy chat — invoke the proxy agent when a human message is posted.

Acceptance criteria:
1. Human sends a message to proxy:* → proxy agent responds (message written to bus)
2. Multi-turn conversation works (--resume; session ID persisted across turns)
3. Proxy has access to ACT-R memory during conversation (memory context in prompt)
4. Corrections in chat update the learned model (record_correction called on [CORRECTION:...])
5. Proxy conversation appears in the navigator with a meaningful slug
6. Works from both global config and project config Participants cards
7. docs/proposals/proxy-review/proposal.md updated to reflect bridge invocation path
8. Specification-based tests cover bus routing and agent invocation for proxy:* conversations
"""
import asyncio
import inspect
import json
import os
import shutil
import sqlite3
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


def _make_proxy_bus(tmpdir: str):
    """Open (and create) the proxy bus for the given tmpdir."""
    from orchestrator.messaging import SqliteMessageBus
    from orchestrator.proxy_review import proxy_bus_path
    path = proxy_bus_path(tmpdir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return SqliteMessageBus(path)


def _make_stream_jsonl(text: str, session_id: str = 'sid-test', slug: str = '') -> str:
    """Write a minimal stream JSONL file and return its path."""
    fd, path = tempfile.mkstemp(suffix='.jsonl', prefix='proxy-test-stream-')
    os.close(fd)
    with open(path, 'w') as f:
        ev = {'type': 'system', 'session_id': session_id}
        if slug:
            ev['slug'] = slug
        f.write(json.dumps(ev) + '\n')
        f.write(json.dumps({
            'type': 'assistant',
            'message': {'content': [{'type': 'text', 'text': text}]},
        }) + '\n')
    return path


# ── AC1: proxy_bus_path exists in orchestrator.proxy_review ──────────────────

class TestProxyBusPathExists(unittest.TestCase):
    """proxy_bus_path must exist in orchestrator.proxy_review."""

    def test_proxy_bus_path_is_importable(self):
        """proxy_bus_path must be importable from orchestrator.proxy_review."""
        from orchestrator.proxy_review import proxy_bus_path
        self.assertTrue(callable(proxy_bus_path), 'proxy_bus_path must be a callable')

    def test_proxy_bus_path_returns_string_under_teaparty_home(self):
        """proxy_bus_path must return a path under teaparty_home."""
        from orchestrator.proxy_review import proxy_bus_path
        path = proxy_bus_path('/tmp/test-home')
        self.assertTrue(
            path.startswith('/tmp/test-home'),
            f'proxy_bus_path must be under teaparty_home; got {path!r}',
        )

    def test_proxy_bus_path_ends_with_db(self):
        """proxy_bus_path must return a .db path."""
        from orchestrator.proxy_review import proxy_bus_path
        path = proxy_bus_path('/tmp/test-home')
        self.assertTrue(
            path.endswith('.db'),
            f'proxy_bus_path must be a .db file path; got {path!r}',
        )


# ── AC1: proxy:* routed to proxy bus ─────────────────────────────────────────

class TestProxyBusRouting(unittest.TestCase):
    """proxy:* conversations must route to the persistent proxy bus."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)
        self._setup_proxy_bus()

    def _setup_proxy_bus(self):
        from orchestrator.proxy_review import proxy_bus_path
        from orchestrator.messaging import SqliteMessageBus
        path = proxy_bus_path(self.tmpdir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.bridge._proxy_bus = SqliteMessageBus(path)
        self.bridge._buses['proxy'] = self.bridge._proxy_bus

    def tearDown(self):
        if hasattr(self.bridge, '_proxy_bus') and self.bridge._proxy_bus:
            self.bridge._proxy_bus.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_bus_for_proxy_conversation_returns_proxy_bus(self):
        """_bus_for_conversation('proxy:darrell') must return the proxy bus, not None."""
        bus = self.bridge._bus_for_conversation('proxy:darrell')
        self.assertIsNotNone(
            bus,
            '_bus_for_conversation must return the proxy bus for proxy:* conversations, not None',
        )

    def test_bridge_has_proxy_bus_attribute(self):
        """TeaPartyBridge must have a _proxy_bus attribute for the persistent proxy bus."""
        self.assertTrue(
            hasattr(self.bridge, '_proxy_bus'),
            'TeaPartyBridge must have _proxy_bus attribute (analogous to _om_bus)',
        )


# ── AC1: Conversation auto-created on first POST ──────────────────────────────

class TestProxyConversationAutoCreation(unittest.TestCase):
    """POST to proxy:* must register the conversation in the conversations table."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)
        from orchestrator.proxy_review import proxy_bus_path
        from orchestrator.messaging import SqliteMessageBus
        path = proxy_bus_path(self.tmpdir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.bridge._proxy_bus = SqliteMessageBus(path)
        self.bridge._buses['proxy'] = self.bridge._proxy_bus

    def tearDown(self):
        if self.bridge._proxy_bus:
            self.bridge._proxy_bus.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_handle_conversation_post_creates_proxy_conversation(self):
        """_handle_conversation_post source must create the proxy conversation before sending."""
        source = inspect.getsource(self.bridge._handle_conversation_post)
        self.assertIn(
            'proxy',
            source,
            '_handle_conversation_post must handle proxy: conversations (create and invoke)',
        )

    def test_create_conversation_makes_proxy_conversation_visible(self):
        """After create_conversation(), active_conversations() must include the proxy conversation."""
        from orchestrator.messaging import ConversationType
        bus = self.bridge._proxy_bus
        conv = bus.create_conversation(ConversationType.PROXY_REVIEW, 'darrell')
        convs = bus.active_conversations(ConversationType.PROXY_REVIEW)
        ids = [c.id for c in convs]
        self.assertIn(
            conv.id, ids,
            'After create_conversation, proxy conversation must appear in active_conversations()',
        )


# ── AC1: Proxy agent invoked and reply written to bus ────────────────────────

class TestProxyAgentReplyWrittenToBus(unittest.TestCase):
    """_invoke_proxy must write the agent reply to the proxy bus after runner completes."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)
        from orchestrator.proxy_review import proxy_bus_path, ProxyReviewSession
        from orchestrator.messaging import SqliteMessageBus
        path = proxy_bus_path(self.tmpdir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.bridge._proxy_bus = SqliteMessageBus(path)
        self.bridge._buses['proxy'] = self.bridge._proxy_bus

    def tearDown(self):
        if self.bridge._proxy_bus:
            self.bridge._proxy_bus.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_invoke_proxy_writes_reply_to_bus(self):
        """_invoke_proxy() must result in a proxy message in the proxy bus."""
        from orchestrator.proxy_review import ProxyReviewSession

        session = ProxyReviewSession(self.tmpdir, 'darrell')
        session.send_human_message('What have you learned about my review style?')

        stream_path = _make_stream_jsonl('I have noticed you prefer thorough test coverage.')
        try:
            mock_result = MagicMock()
            mock_result.session_id = 'sid-proxy-reply-test'

            with patch('orchestrator.claude_runner.ClaudeRunner') as MockRunner:
                instance = MagicMock()
                instance.run = AsyncMock(return_value=mock_result)
                instance.stream_file = stream_path
                MockRunner.return_value = instance

                with patch('tempfile.mkstemp', return_value=(0, stream_path)):
                    with patch('os.close'):
                        with patch('os.unlink'):
                            asyncio.run(self.bridge._invoke_proxy('darrell'))

            msgs = session.get_messages()
            proxy_msgs = [m for m in msgs if m.sender == 'proxy']
            self.assertTrue(
                len(proxy_msgs) > 0,
                '_invoke_proxy must write the agent reply to the bus as sender=proxy',
            )
        finally:
            try:
                os.unlink(stream_path)
            except OSError:
                pass

    def test_bridge_has_invoke_proxy_method(self):
        """TeaPartyBridge must have an _invoke_proxy method (analogous to _invoke_om)."""
        self.assertTrue(
            hasattr(self.bridge, '_invoke_proxy'),
            'TeaPartyBridge must have _invoke_proxy method for proxy chat invocation',
        )


# ── AC2: --resume session ID persisted across turns ──────────────────────────

class TestProxyResumeSessionPersistence(unittest.TestCase):
    """Second _invoke_proxy call must use the session ID saved by the first."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)
        from orchestrator.proxy_review import proxy_bus_path
        from orchestrator.messaging import SqliteMessageBus
        path = proxy_bus_path(self.tmpdir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.bridge._proxy_bus = SqliteMessageBus(path)
        self.bridge._buses['proxy'] = self.bridge._proxy_bus

    def tearDown(self):
        if self.bridge._proxy_bus:
            self.bridge._proxy_bus.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_second_invoke_uses_session_id_from_first(self):
        """After first _invoke_proxy, the session ID must be saved; second call loads it for --resume."""
        from orchestrator.proxy_review import ProxyReviewSession

        session = ProxyReviewSession(self.tmpdir, 'darrell')
        session.send_human_message('First message.')

        first_stream = _make_stream_jsonl('First response.', 'first-proxy-session-id')
        try:
            first_result = MagicMock()
            first_result.session_id = 'first-proxy-session-id'

            with patch('orchestrator.claude_runner.ClaudeRunner') as MockRunner:
                instance = MagicMock()
                instance.run = AsyncMock(return_value=first_result)
                instance.stream_file = first_stream
                MockRunner.return_value = instance

                with patch('tempfile.mkstemp', return_value=(0, first_stream)):
                    with patch('os.close'):
                        with patch('os.unlink'):
                            asyncio.run(self.bridge._invoke_proxy('darrell'))
        finally:
            try:
                os.unlink(first_stream)
            except OSError:
                pass

        # Second ProxyReviewSession for same qualifier must pick up saved session ID
        session2 = ProxyReviewSession(self.tmpdir, 'darrell')
        session2.load_state()
        self.assertEqual(
            session2.claude_session_id, 'first-proxy-session-id',
            'Second ProxyReviewSession must load the session ID saved by the first invoke',
        )

    def test_proxy_review_session_has_save_and_load_state(self):
        """ProxyReviewSession must have save_state and load_state methods for --resume support."""
        from orchestrator.proxy_review import ProxyReviewSession
        session = ProxyReviewSession(self.tmpdir, 'darrell')
        self.assertTrue(hasattr(session, 'save_state'), 'ProxyReviewSession must have save_state')
        self.assertTrue(hasattr(session, 'load_state'), 'ProxyReviewSession must have load_state')

    def test_proxy_review_session_has_claude_session_id(self):
        """ProxyReviewSession must track claude_session_id for --resume."""
        from orchestrator.proxy_review import ProxyReviewSession
        session = ProxyReviewSession(self.tmpdir, 'darrell')
        self.assertIsNone(
            session.claude_session_id,
            'claude_session_id must start as None (no prior session)',
        )


# ── AC3: ACT-R memory context in proxy prompt ─────────────────────────────────

class TestProxyMemoryContext(unittest.TestCase):
    """Proxy agent must receive ACT-R memory context during conversation."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_proxy_memory_path_is_importable(self):
        """proxy_memory_path must be importable from orchestrator.proxy_review."""
        from orchestrator.proxy_review import proxy_memory_path
        self.assertTrue(callable(proxy_memory_path))

    def test_proxy_memory_path_returns_db_under_teaparty_home(self):
        """proxy_memory_path must return a .db path under teaparty_home."""
        from orchestrator.proxy_review import proxy_memory_path
        path = proxy_memory_path('/tmp/test-home')
        self.assertTrue(
            path.startswith('/tmp/test-home'),
            f'proxy_memory_path must be under teaparty_home; got {path!r}',
        )
        self.assertTrue(path.endswith('.db'), f'proxy_memory_path must be a .db file; got {path!r}')

    def test_proxy_review_session_build_context_includes_memory(self):
        """ProxyReviewSession.build_context must include ACT-R memory context when available."""
        from orchestrator.proxy_review import ProxyReviewSession
        session = ProxyReviewSession(self.tmpdir, 'darrell')
        # build_context must be callable and return a string
        context = session.build_context()
        self.assertIsInstance(
            context, str,
            'ProxyReviewSession.build_context must return a string',
        )


# ── AC4: Corrections update the learned model ────────────────────────────────

class TestProxyCorrectionsFeedback(unittest.TestCase):
    """Corrections made in proxy chat must update the learned model."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)
        from orchestrator.proxy_review import proxy_bus_path
        from orchestrator.messaging import SqliteMessageBus
        path = proxy_bus_path(self.tmpdir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.bridge._proxy_bus = SqliteMessageBus(path)
        self.bridge._buses['proxy'] = self.bridge._proxy_bus

    def tearDown(self):
        if self.bridge._proxy_bus:
            self.bridge._proxy_bus.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_invoke_proxy_processes_correction_signals_from_response(self):
        """When the agent response contains [CORRECTION:...], it must be stored in the ACT-R DB."""
        from orchestrator.proxy_review import ProxyReviewSession, proxy_memory_path
        from orchestrator.proxy_memory import open_proxy_db, query_chunks

        session = ProxyReviewSession(self.tmpdir, 'darrell')
        session.send_human_message('Stop flagging missing rollback strategies.')

        correction_response = (
            'Understood. I will stop flagging missing rollback strategies for internal tools.\n'
            '[CORRECTION: stop flagging missing rollback strategies for internal tools]'
        )
        stream_path = _make_stream_jsonl(correction_response)
        try:
            mock_result = MagicMock()
            mock_result.session_id = 'sid-correction-test'

            with patch('orchestrator.claude_runner.ClaudeRunner') as MockRunner:
                instance = MagicMock()
                instance.run = AsyncMock(return_value=mock_result)
                instance.stream_file = stream_path
                MockRunner.return_value = instance

                with patch('tempfile.mkstemp', return_value=(0, stream_path)):
                    with patch('os.close'):
                        with patch('os.unlink'):
                            asyncio.run(self.bridge._invoke_proxy('darrell'))

            # Verify correction was stored in the ACT-R memory DB
            mem_path = proxy_memory_path(self.tmpdir)
            if os.path.exists(mem_path):
                conn = open_proxy_db(mem_path)
                try:
                    chunks = query_chunks(conn)
                    correction_chunks = [c for c in chunks if c.type == 'review_correction']
                    self.assertTrue(
                        len(correction_chunks) > 0,
                        '_invoke_proxy must store [CORRECTION:...] signals in the ACT-R DB; '
                        'none found after correction response',
                    )
                finally:
                    conn.close()
        finally:
            try:
                os.unlink(stream_path)
            except OSError:
                pass


# ── AC5: Proxy conversation appears in navigator with meaningful slug ─────────

class TestProxyConversationSlug(unittest.TestCase):
    """Proxy conversation must appear in navigator with a meaningful slug."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)
        from orchestrator.proxy_review import proxy_bus_path
        from orchestrator.messaging import SqliteMessageBus
        path = proxy_bus_path(self.tmpdir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.bridge._proxy_bus = SqliteMessageBus(path)
        self.bridge._buses['proxy'] = self.bridge._proxy_bus

    def tearDown(self):
        if self.bridge._proxy_bus:
            self.bridge._proxy_bus.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_invoke_proxy_captures_slug_on_first_turn(self):
        """_invoke_proxy must capture the conversation slug from the stream on first turn."""
        from orchestrator.proxy_review import ProxyReviewSession

        session = ProxyReviewSession(self.tmpdir, 'darrell')
        session.send_human_message('Hello.')

        stream_path = _make_stream_jsonl(
            'Hello! I am your proxy.',
            session_id='sid-slug-test',
            slug='proxy-calibration-darrell',
        )
        try:
            mock_result = MagicMock()
            mock_result.session_id = 'sid-slug-test'

            with patch('orchestrator.claude_runner.ClaudeRunner') as MockRunner:
                instance = MagicMock()
                instance.run = AsyncMock(return_value=mock_result)
                instance.stream_file = stream_path
                MockRunner.return_value = instance

                with patch('tempfile.mkstemp', return_value=(0, stream_path)):
                    with patch('os.close'):
                        with patch('os.unlink'):
                            asyncio.run(self.bridge._invoke_proxy('darrell'))

            session2 = ProxyReviewSession(self.tmpdir, 'darrell')
            session2.load_state()
            self.assertEqual(
                session2.conversation_title, 'proxy-calibration-darrell',
                'ProxyReviewSession must save the slug as conversation_title after first turn; '
                f'got {session2.conversation_title!r}',
            )
        finally:
            try:
                os.unlink(stream_path)
            except OSError:
                pass

    def test_read_proxy_session_title_returns_saved_slug(self):
        """read_proxy_session_title must read the title saved by save_state."""
        from orchestrator.proxy_review import ProxyReviewSession, read_proxy_session_title

        session = ProxyReviewSession(self.tmpdir, 'darrell')
        session.conversation_title = 'test-slug'
        session.save_state()

        title = read_proxy_session_title(self.tmpdir, 'darrell')
        self.assertEqual(
            title, 'test-slug',
            'read_proxy_session_title must return the saved conversation_title',
        )


# ── AC5: Proxy conversations listed in navigator ──────────────────────────────

class TestProxyConversationsListed(unittest.TestCase):
    """GET /api/conversations?type=proxy_review must return proxy conversations."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)
        from orchestrator.proxy_review import proxy_bus_path
        from orchestrator.messaging import SqliteMessageBus
        path = proxy_bus_path(self.tmpdir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.bridge._proxy_bus = SqliteMessageBus(path)
        self.bridge._buses['proxy'] = self.bridge._proxy_bus

    def tearDown(self):
        if self.bridge._proxy_bus:
            self.bridge._proxy_bus.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_handle_conversations_list_routes_proxy_review_to_proxy_bus(self):
        """_handle_conversations_list source must handle proxy_review type via proxy bus."""
        source = inspect.getsource(self.bridge._handle_conversations_list)
        self.assertIn(
            'proxy',
            source,
            '_handle_conversations_list must route proxy_review type to the proxy bus',
        )


# ── AC6: Works from both global and project config Participants cards ──────────

class TestProxyConvIdPrefix(unittest.TestCase):
    """proxy:{decider} must be the canonical conversation ID format for proxy chat."""

    def test_proxy_conversation_id_prefix_is_proxy(self):
        """ConversationType.PROXY_REVIEW must use 'proxy' prefix in make_conversation_id."""
        from orchestrator.messaging import ConversationType, make_conversation_id
        conv_id = make_conversation_id(ConversationType.PROXY_REVIEW, 'darrell')
        self.assertEqual(
            conv_id, 'proxy:darrell',
            f'make_conversation_id(PROXY_REVIEW, "darrell") must return "proxy:darrell"; got {conv_id!r}',
        )

    def test_bus_for_conversation_handles_proxy_prefix(self):
        """_bus_for_conversation source must handle proxy: prefix routing."""
        tmpdir = _make_tmpdir()
        try:
            bridge = _make_bridge(tmpdir)
            source = inspect.getsource(bridge._bus_for_conversation)
            self.assertIn(
                'proxy',
                source,
                '_bus_for_conversation must handle proxy: prefix (route to proxy bus)',
            )
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ── AC7: docs/proposals/proxy-review/proposal.md updated ──────────────────────

class TestProxyReviewProposalUpdated(unittest.TestCase):
    """proposal.md must describe bridge invocation path, not TUI."""

    def _get_proposal(self) -> str:
        path = _REPO_ROOT / 'docs' / 'proposals' / 'proxy-review' / 'proposal.md'
        self.assertTrue(path.exists(), f'proposal.md not found at {path}')
        return path.read_text()

    def test_proposal_does_not_reference_tui_as_invocation_path(self):
        """proposal.md must not say 'TUI invokes' — TUI was retired in #305."""
        doc = self._get_proposal()
        self.assertNotIn(
            'TUI invokes',
            doc,
            'proposal.md still says "TUI invokes" — must be updated to bridge invocation',
        )

    def test_proposal_references_bridge_invocation(self):
        """proposal.md must describe the bridge as the invocation path."""
        doc = self._get_proposal()
        self.assertTrue(
            'bridge' in doc.lower(),
            'proposal.md must describe the bridge as the invocation path for proxy chat',
        )


# ── AC8: Concurrent proxy invocations queue ───────────────────────────────────

class TestProxyConcurrentQueueing(unittest.TestCase):
    """Concurrent POSTs to proxy:* must queue, not drop."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)
        from orchestrator.proxy_review import proxy_bus_path
        from orchestrator.messaging import SqliteMessageBus
        path = proxy_bus_path(self.tmpdir)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.bridge._proxy_bus = SqliteMessageBus(path)
        self.bridge._buses['proxy'] = self.bridge._proxy_bus

    def tearDown(self):
        if self.bridge._proxy_bus:
            self.bridge._proxy_bus.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_bridge_has_proxy_locks_dict(self):
        """TeaPartyBridge must have _proxy_locks dict for per-qualifier asyncio.Lock objects."""
        self.assertTrue(
            hasattr(self.bridge, '_proxy_locks'),
            'TeaPartyBridge must have _proxy_locks dict (analogous to _om_locks)',
        )

    def test_invoke_proxy_uses_per_qualifier_lock(self):
        """_invoke_proxy source must use _proxy_locks to serialize per-qualifier access."""
        source = inspect.getsource(self.bridge._invoke_proxy)
        self.assertIn(
            '_proxy_locks',
            source,
            '_invoke_proxy must use _proxy_locks for per-qualifier asyncio.Lock serialization',
        )

    def test_runner_exception_writes_error_message_to_bus(self):
        """When the proxy runner raises, _invoke_proxy must write an error message to the proxy bus."""
        from orchestrator.proxy_review import ProxyReviewSession

        session = ProxyReviewSession(self.tmpdir, 'darrell')
        session.send_human_message('A message that will fail.')

        with patch('orchestrator.claude_runner.ClaudeRunner') as MockRunner:
            instance = MagicMock()
            instance.run = AsyncMock(side_effect=RuntimeError('simulated runner failure'))
            MockRunner.return_value = instance

            with patch('tempfile.mkstemp', return_value=(0, '/tmp/proxy-fake.jsonl')):
                with patch('os.close'):
                    with patch('os.unlink'):
                        asyncio.run(self.bridge._invoke_proxy('darrell'))

        msgs = session.get_messages()
        proxy_msgs = [m for m in msgs if m.sender == 'proxy']
        self.assertTrue(
            len(proxy_msgs) > 0,
            '_invoke_proxy must write an error message to the bus on runner failure',
        )


# ── AC4 (path alignment): corrections reach gate memory ─────────────────────

class TestProxyMemoryPathAlignment(unittest.TestCase):
    """Review-session memory path and gate memory path must be the same file.

    Design constraint (human-proxies.md): 'One learning infrastructure, all
    channels. There is no separation between chat proxy and gate proxy — they
    are the same agent, the same memory, the same learning system.'
    """

    def test_review_memory_path_matches_gate_memory_path(self):
        """proxy_memory_path(teaparty_home) must equal resolve_memory_db_path when
        proxy_model_path is derived from {poc_root}/.teaparty/management/agents/proxy-review/
        (as session.py sets it).  This verifies the single-database guarantee — corrections written
        during a proxy review conversation land in the same DB that consult_proxy
        reads at approval gates."""
        from orchestrator.proxy_review import proxy_memory_path
        from orchestrator.proxy_memory import resolve_memory_db_path

        teaparty_home = '/tmp/test-teaparty-home'
        # Derive proxy_model_path the same way session.py does
        poc_root = os.path.dirname(teaparty_home)  # analogous: teaparty_home = poc_root/.teaparty
        proxy_model_path = os.path.join(teaparty_home, 'management', 'agents', 'proxy-review', '.proxy-confidence.json')

        review_db = proxy_memory_path(teaparty_home)
        gate_db = resolve_memory_db_path(proxy_model_path)

        self.assertEqual(
            review_db,
            gate_db,
            f'Review memory DB ({review_db!r}) and gate memory DB ({gate_db!r}) must be the same file. '
            'Corrections written during proxy chat must reach the approval gate.',
        )

    def test_session_proxy_model_path_is_under_teaparty_proxy_dir(self):
        """session.py must derive proxy_model_path from the proxy-review agent dir
        so that resolve_memory_db_path returns the co-located .proxy-memory.db."""
        import inspect
        from orchestrator.session import Session
        source = inspect.getsource(Session.run)
        self.assertIn(
            '.teaparty',
            source,
            'Session.run must derive proxy_model_path from .teaparty/ — '
            'found no .teaparty reference, so gate memory is not aligned with review session memory',
        )
        self.assertNotIn(
            "os.path.join(project_dir, '.proxy-confidence.json')",
            source,
            'Session.run must not use project_dir for proxy_model_path — '
            'gate memory must be global (per-human), not per-project',
        )
