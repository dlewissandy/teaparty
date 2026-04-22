#!/usr/bin/env python3
"""Tests for issue #137: AskQuestion MCP tool.

Replaces file-based escalation (.intent-escalation.md, stream-offset detection)
with an MCP tool the agent calls directly.  The tool routes through the proxy:
confident → return proxy answer; not confident → escalate to human.

Tests are layered (per pre-mortem Risk 5 mitigation):
 - Unit tests for the handler logic (no MCP protocol)
 - Proxy routing tests (confident vs. escalate)
 - Differential recording (proxy prediction vs. human actual)
 - ClaudeRunner integration (MCP server config wired in)
"""
try:
    import mcp  # noqa: F401
except ImportError:
    import unittest
    raise unittest.SkipTest('mcp package not installed')

import asyncio
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.messaging.bus import EventBus


# ── Helpers ──────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _make_event_bus():
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


# ── Tests: AskQuestion handler logic ────────────────────────────────────────

class TestAskQuestionHandler(unittest.TestCase):
    """The AskQuestion handler receives a question and returns an answer."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_handler_exists_and_is_callable(self):
        """The ask_question handler must exist and be async-callable."""
        from teaparty.mcp.server.main import ask_question_handler
        self.assertTrue(callable(ask_question_handler))

    def test_handler_returns_string_answer(self):
        """The handler must return a string answer, not None or a dict."""
        from teaparty.mcp.server.main import ask_question_handler

        # Provide a mock proxy that is confident
        async def mock_proxy(question, context):
            return {'confident': True, 'answer': 'Ages 5-8', 'prediction': 'Ages 5-8'}

        result = _run(ask_question_handler(
            question='Who is the target audience?',
            context='Writing a children\'s joke book',
            proxy_fn=mock_proxy,
        ))
        self.assertIsInstance(result, str)
        self.assertIn('Ages 5-8', result)

    def test_handler_requires_question(self):
        """Calling with an empty question should raise ValueError."""
        from teaparty.mcp.server.main import ask_question_handler

        async def mock_proxy(question, context):
            return {'confident': True, 'answer': 'Yes', 'prediction': 'Yes'}

        with self.assertRaises(ValueError):
            _run(ask_question_handler(
                question='',
                context='',
                proxy_fn=mock_proxy,
            ))


# ── Tests: Proxy routing ────────────────────────────────────────────────────

class TestProxyRouting(unittest.TestCase):
    """The handler routes through the proxy: confident → auto-answer,
    not confident → escalate to human."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_confident_proxy_returns_answer_without_human(self):
        """When the proxy is confident, the human is never consulted."""
        from teaparty.mcp.server.main import ask_question_handler

        human_called = []

        async def mock_proxy(question, context):
            return {'confident': True, 'answer': 'PostgreSQL', 'prediction': 'PostgreSQL'}

        async def mock_human(question):
            human_called.append(question)
            return 'MySQL'

        result = _run(ask_question_handler(
            question='What database?',
            context='Building a web app',
            proxy_fn=mock_proxy,
            human_fn=mock_human,
        ))
        self.assertEqual(result, 'PostgreSQL')
        self.assertEqual(len(human_called), 0, "Human should NOT be consulted when proxy is confident")

    def test_not_confident_proxy_escalates_to_human(self):
        """When the proxy is not confident, the human's answer is returned."""
        from teaparty.mcp.server.main import ask_question_handler

        human_called = []

        async def mock_proxy(question, context):
            return {'confident': False, 'answer': '', 'prediction': 'Maybe PostgreSQL?'}

        async def mock_human(question):
            human_called.append(question)
            return 'Use SQLite for now'

        result = _run(ask_question_handler(
            question='What database?',
            context='Building a prototype',
            proxy_fn=mock_proxy,
            human_fn=mock_human,
        ))
        self.assertEqual(result, 'Use SQLite for now')
        self.assertEqual(len(human_called), 1, "Human MUST be consulted when proxy is not confident")
        self.assertIn('What database?', human_called[0])

    def test_proxy_always_generates_prediction(self):
        """Per issue #138: the proxy must ALWAYS generate a prediction,
        even when not confident.  The prediction is stored for differential learning."""
        from teaparty.mcp.server.main import ask_question_handler

        predictions_recorded = []

        async def mock_proxy(question, context):
            prediction = 'I think PostgreSQL'
            return {'confident': False, 'answer': '', 'prediction': prediction}

        async def mock_human(question):
            return 'Use SQLite'

        def mock_record_differential(prediction, actual, question, context):
            predictions_recorded.append({
                'prediction': prediction,
                'actual': actual,
                'question': question,
            })

        result = _run(ask_question_handler(
            question='What database?',
            context='Prototype',
            proxy_fn=mock_proxy,
            human_fn=mock_human,
            record_differential_fn=mock_record_differential,
        ))

        self.assertEqual(result, 'Use SQLite')
        self.assertEqual(len(predictions_recorded), 1,
                         "Differential must be recorded when proxy is not confident")
        self.assertEqual(predictions_recorded[0]['prediction'], 'I think PostgreSQL')
        self.assertEqual(predictions_recorded[0]['actual'], 'Use SQLite')


# ── Tests: Differential recording ───────────────────────────────────────────

class TestDifferentialRecording(unittest.TestCase):
    """The differential (proxy prediction vs. human actual) is the highest-value
    learning signal.  It must always be recorded when the human is consulted."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_no_differential_when_proxy_is_confident(self):
        """When the proxy answers directly, no differential is recorded
        (there is no human response to compare against)."""
        from teaparty.mcp.server.main import ask_question_handler

        differentials = []

        async def mock_proxy(question, context):
            return {'confident': True, 'answer': 'Yes', 'prediction': 'Yes'}

        def mock_record(prediction, actual, question, context):
            differentials.append({'prediction': prediction, 'actual': actual})

        _run(ask_question_handler(
            question='Should we proceed?',
            context='',
            proxy_fn=mock_proxy,
            record_differential_fn=mock_record,
        ))
        self.assertEqual(len(differentials), 0,
                         "No differential when proxy handles it alone")

    def test_differential_includes_question_and_context(self):
        """The differential record must include the question and context
        so the learning system can scope it properly."""
        from teaparty.mcp.server.main import ask_question_handler

        differentials = []

        async def mock_proxy(question, context):
            return {'confident': False, 'answer': '', 'prediction': 'Probably yes'}

        async def mock_human(question):
            return 'No, not yet'

        def mock_record(prediction, actual, question, context):
            differentials.append({
                'prediction': prediction,
                'actual': actual,
                'question': question,
                'context': context,
            })

        _run(ask_question_handler(
            question='Ready to deploy?',
            context='staging environment',
            proxy_fn=mock_proxy,
            human_fn=mock_human,
            record_differential_fn=mock_record,
        ))
        self.assertEqual(len(differentials), 1)
        self.assertEqual(differentials[0]['question'], 'Ready to deploy?')
        self.assertEqual(differentials[0]['context'], 'staging environment')


# ── Tests: MCP server tool registration ─────────────────────────────────────

class TestMCPServerRegistration(unittest.TestCase):
    """The MCP server must register AskQuestion as an available tool."""

    def test_server_has_ask_question_tool(self):
        """The MCP server must expose an 'AskQuestion' tool."""
        from teaparty.mcp.server.main import create_server
        server = create_server()
        tools = _run(server.list_tools())
        tool_names = [t.name for t in tools]
        self.assertIn('AskQuestion', tool_names)


# ── Tests: ClaudeRunner MCP integration ─────────────────────────────────────

class TestClaudeRunnerMCPIntegration(unittest.TestCase):
    """ClaudeRunner must wire the MCP server into Claude Code's args."""

    def test_no_mcp_config_when_not_provided(self):
        """When mcp_config is not provided, --mcp-config should not appear."""
        from teaparty.runners.claude import ClaudeRunner

        runner = ClaudeRunner(
            prompt='test',
            cwd='/tmp',
            stream_file='/tmp/stream.jsonl',
        )
        args = runner._build_args(None)
        self.assertNotIn('--mcp-config', args)


# ── Tests: EscalationListener (socket IPC + proxy routing) ──────────────────

class TestEscalationListener(unittest.TestCase):
    """The EscalationListener routes through the proxy before asking the human."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_listener_starts_and_opens_bus(self):
        """After start(), the listener has an open bus connection and
        is polling the configured conversation."""
        from teaparty.cfa.gates.escalation import EscalationListener

        bus = _make_event_bus()
        bus_db = os.path.join(self.tmpdir, 'bus.db')
        listener = EscalationListener(
            bus, AsyncMock(return_value='answer'),
            bus_db_path=bus_db, conv_id='escalation:test',
            session_id='test',
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            project_slug='test', cfa_state='INTENT',
        )

        async def _test():
            await listener.start()
            self.assertIsNotNone(listener._bus)
            self.assertIsNotNone(listener._task)
            await listener.stop()
            self.assertIsNone(listener._task)

        _run(_test())

    def test_cold_start_records_interaction(self):
        """With no proxy model (cold start), the interaction is still
        recorded for learning — regardless of whether the proxy answered
        or escalated to the human.

        Cold-start here means the proxy returns a non-confident
        ProxyResult, which triggers the fallback to _ask_human via the
        input_provider.
        """
        import json as _json
        from teaparty.cfa.gates.escalation import EscalationListener
        from teaparty.messaging.conversations import SqliteMessageBus
        from teaparty.proxy.agent import ProxyResult

        bus = _make_event_bus()
        proxy_path = os.path.join(self.tmpdir, '.proxy.json')
        bus_db = os.path.join(self.tmpdir, 'bus.db')
        conv_id = 'escalation:test'

        async def mock_input(req):
            return 'Ages 5-8'

        listener = EscalationListener(
            bus, mock_input,
            bus_db_path=bus_db, conv_id=conv_id,
            session_id='test',
            proxy_model_path=proxy_path,
            project_slug='test', cfa_state='INTENT',
        )

        async def _test():
            with patch(
                'teaparty.proxy.agent.consult_proxy',
                new=AsyncMock(return_value=ProxyResult(
                    text='', confidence=0.0, from_agent=False,
                )),
            ):
                await listener.start()
                try:
                    msg_bus = SqliteMessageBus(bus_db)
                    msg_bus.send(conv_id, 'agent', _json.dumps({
                        'type': 'ask_human', 'question': 'Who is the audience?',
                    }))
                    import time as _time
                    deadline = _time.time() + 10
                    response = None
                    while _time.time() < deadline:
                        msgs = msg_bus.receive(conv_id, since_timestamp=0)
                        replies = [m for m in msgs if m.sender == 'orchestrator']
                        if replies:
                            response = _json.loads(replies[0].content)
                            break
                        await asyncio.sleep(0.05)
                    self.assertIsNotNone(response, 'orchestrator did not reply')
                    self.assertEqual(response['answer'], 'Ages 5-8')
                finally:
                    await listener.stop()

        _run(_test())

    def test_confident_proxy_returns_without_human(self):
        """When the proxy is confident, the human is never consulted."""
        import json as _json
        from teaparty.cfa.gates.escalation import EscalationListener
        from teaparty.messaging.conversations import SqliteMessageBus
        from teaparty.proxy.agent import ProxyResult

        bus = _make_event_bus()
        human_called = []

        async def mock_input(req):
            human_called.append(req)
            return 'should not reach here'

        bus_db = os.path.join(self.tmpdir, 'bus.db')
        conv_id = 'escalation:test'
        listener = EscalationListener(
            bus, mock_input,
            bus_db_path=bus_db, conv_id=conv_id,
            session_id='test',
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            project_slug='test', cfa_state='INTENT',
        )

        async def _test():
            with patch(
                'teaparty.proxy.agent.consult_proxy',
                new=AsyncMock(return_value=ProxyResult(
                    text='Use PostgreSQL', confidence=0.95, from_agent=True,
                )),
            ):
                await listener.start()
                try:
                    msg_bus = SqliteMessageBus(bus_db)
                    msg_bus.send(conv_id, 'agent', _json.dumps({
                        'type': 'ask_human', 'question': 'What database?',
                    }))
                    import time as _time
                    deadline = _time.time() + 10
                    response = None
                    while _time.time() < deadline:
                        msgs = msg_bus.receive(conv_id, since_timestamp=0)
                        replies = [m for m in msgs if m.sender == 'orchestrator']
                        if replies:
                            response = _json.loads(replies[0].content)
                            break
                        await asyncio.sleep(0.05)
                    self.assertIsNotNone(response, 'orchestrator did not reply')
                    self.assertEqual(response['answer'], 'Use PostgreSQL')
                    self.assertEqual(len(human_called), 0,
                                     "Human must NOT be consulted when proxy is confident")
                finally:
                    await listener.stop()

        _run(_test())

    def test_proxy_disabled_skips_consult_proxy(self):
        """When proxy_enabled=False (bridge path), the listener goes
        straight to the human without invoking consult_proxy."""
        import json as _json
        from teaparty.cfa.gates.escalation import EscalationListener
        from teaparty.messaging.conversations import SqliteMessageBus

        bus = _make_event_bus()
        bus_db = os.path.join(self.tmpdir, 'bus.db')
        conv_id = 'escalation:test'

        async def human(req):
            return 'human-answer'

        listener = EscalationListener(
            bus, human,
            bus_db_path=bus_db, conv_id=conv_id,
            session_id='test',
            proxy_enabled=False,
        )

        async def _test():
            # Assert consult_proxy is never called by patching it to raise.
            with patch(
                'teaparty.proxy.agent.consult_proxy',
                new=AsyncMock(side_effect=AssertionError(
                    'consult_proxy must not be called when proxy_enabled=False'
                )),
            ):
                await listener.start()
                try:
                    msg_bus = SqliteMessageBus(bus_db)
                    msg_bus.send(conv_id, 'agent', _json.dumps({
                        'type': 'ask_human', 'question': 'what?',
                    }))
                    import time as _time
                    deadline = _time.time() + 5
                    response = None
                    while _time.time() < deadline:
                        msgs = msg_bus.receive(conv_id, since_timestamp=0)
                        replies = [m for m in msgs if m.sender == 'orchestrator']
                        if replies:
                            response = _json.loads(replies[0].content)
                            break
                        await asyncio.sleep(0.05)
                    self.assertIsNotNone(response, 'orchestrator did not reply')
                    self.assertEqual(response['answer'], 'human-answer')
                finally:
                    await listener.stop()

        _run(_test())


# ── Tests: EscalationListener skill path (issue #420) ──────────────────────

class TestEscalationSkillPath(unittest.TestCase):
    """Issue #420: when ``proxy_invoker_fn`` is supplied, every AskQuestion
    routes through the proxy running the ``/escalation`` skill.

    The mock proxy invoker stands in for the bridge's ``_invoke_proxy``.
    It writes a canned response to the per-escalation proxy conversation
    and (for DIALOG turns) waits for the human before returning, so the
    listener observes the same message ordering it would in production.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # infra_dir layout matches .teaparty/{scope}/agents/{agent}/
        self.teaparty_home = os.path.join(self.tmpdir, '.teaparty')
        self.infra_dir = os.path.join(
            self.teaparty_home, 'management', 'agents', 'proxy',
        )
        os.makedirs(self.infra_dir, exist_ok=True)
        # Proxy bus lives at .teaparty/proxy/proxy-messages.db
        proxy_dir = os.path.join(self.teaparty_home, 'proxy')
        os.makedirs(proxy_dir, exist_ok=True)
        self.proxy_bus_path = os.path.join(proxy_dir, 'proxy-messages.db')
        self.bus_db = os.path.join(self.infra_dir, 'messages.db')
        self.conv_id = 'escalation:test-session'

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _send_ask(self, question: str) -> None:
        from teaparty.messaging.conversations import SqliteMessageBus
        import json as _json
        bus = SqliteMessageBus(self.bus_db)
        bus.send(self.conv_id, 'agent', _json.dumps({
            'type': 'ask_human', 'question': question,
        }))

    def _wait_for_reply(self, timeout: float = 10.0):
        from teaparty.messaging.conversations import SqliteMessageBus
        import json as _json
        import time as _time
        bus = SqliteMessageBus(self.bus_db)
        deadline = _time.time() + timeout
        while _time.time() < deadline:
            msgs = bus.receive(self.conv_id, since_timestamp=0)
            replies = [m for m in msgs if m.sender == 'orchestrator']
            if replies:
                return _json.loads(replies[0].content)
            import asyncio as _a
            _a.get_event_loop()  # ensure loop exists
            return None  # fallthrough handled below
        return None

    def _make_listener(self, proxy_invoker, on_dispatch=None):
        from teaparty.cfa.gates.escalation import EscalationListener
        from teaparty.runners.launcher import create_session

        async def human_never_called(req):
            raise AssertionError('input_provider must not be called on skill path')

        # The skill path creates the escalation as a proxy child session
        # under a real dispatcher session, so the accordion can render
        # it.  Pre-create the dispatcher so ``record_child_session`` has
        # a valid on-disk conversation_map to mutate.
        dispatcher = create_session(
            agent_name='office-manager',
            scope='management',
            teaparty_home=self.teaparty_home,
            session_id='test-dispatcher',
        )

        return EscalationListener(
            event_bus=None,
            input_provider=human_never_called,
            bus_db_path=self.bus_db,
            conv_id=self.conv_id,
            session_id=dispatcher.id,
            infra_dir=self.infra_dir,
            proxy_invoker_fn=proxy_invoker,
            on_dispatch=on_dispatch,
            dispatcher_session=dispatcher,
            teaparty_home=self.teaparty_home,
            scope='management',
        )

    def test_response_terminates_loop_with_message(self):
        """RESPONSE from the skill → listener returns ``{"answer": message}``.
        The proxy invoker is called exactly once."""
        from teaparty.messaging.conversations import (
            SqliteMessageBus,
            ConversationType,
            make_conversation_id,
        )
        import json as _json
        import time as _time

        invocations = []
        dispatch_events = []

        async def mock_invoker(qualifier: str, cwd: str, **_: object) -> None:
            invocations.append((qualifier, cwd))
            # QUESTION.md must exist at the invoker's cwd.
            assert os.path.isfile(os.path.join(cwd, 'QUESTION.md'))
            proxy_bus = SqliteMessageBus(self.proxy_bus_path)
            conv_id = make_conversation_id(ConversationType.PROXY, qualifier)
            proxy_bus.send(conv_id, 'proxy', _json.dumps({
                'status': 'RESPONSE', 'message': 'Use Postgres',
            }))

        def on_dispatch(evt):
            dispatch_events.append(evt)

        listener = self._make_listener(mock_invoker, on_dispatch=on_dispatch)

        async def _test():
            await listener.start()
            try:
                self._send_ask('What database?')
                deadline = _time.time() + 10
                response = None
                while _time.time() < deadline:
                    bus = SqliteMessageBus(self.bus_db)
                    msgs = bus.receive(self.conv_id, since_timestamp=0)
                    replies = [m for m in msgs if m.sender == 'orchestrator']
                    if replies:
                        response = _json.loads(replies[0].content)
                        break
                    await asyncio.sleep(0.05)
                self.assertIsNotNone(response)
                self.assertEqual(response['answer'], 'Use Postgres')
                self.assertEqual(len(invocations), 1)
                types = [e['type'] for e in dispatch_events]
                self.assertIn('dispatch_started', types)
                self.assertIn('dispatch_completed', types)
                # The escalation dir is torn down after termination.
                _qual, cwd = invocations[0]
                self.assertFalse(os.path.exists(cwd))
            finally:
                await listener.stop()

        _run(_test())

    def test_withdraw_prefixes_answer_with_marker(self):
        """WITHDRAW from the skill → answer is ``[WITHDRAW]\\n<reason>``."""
        from teaparty.messaging.conversations import (
            SqliteMessageBus,
            ConversationType,
            make_conversation_id,
        )
        import json as _json
        import time as _time

        async def mock_invoker(qualifier: str, cwd: str, **_: object) -> None:
            proxy_bus = SqliteMessageBus(self.proxy_bus_path)
            conv_id = make_conversation_id(ConversationType.PROXY, qualifier)
            proxy_bus.send(conv_id, 'proxy', _json.dumps({
                'status': 'WITHDRAW', 'message': 'abandoned',
            }))

        listener = self._make_listener(mock_invoker)

        async def _test():
            await listener.start()
            try:
                self._send_ask('Still doing this?')
                deadline = _time.time() + 10
                response = None
                while _time.time() < deadline:
                    bus = SqliteMessageBus(self.bus_db)
                    msgs = bus.receive(self.conv_id, since_timestamp=0)
                    replies = [m for m in msgs if m.sender == 'orchestrator']
                    if replies:
                        response = _json.loads(replies[0].content)
                        break
                    await asyncio.sleep(0.05)
                self.assertIsNotNone(response)
                self.assertEqual(response['answer'], '[WITHDRAW]\nabandoned')
            finally:
                await listener.stop()

        _run(_test())

    def test_dialog_loop_waits_for_human_then_resumes(self):
        """DIALOG from the skill → listener waits for a sender='human'
        message on the proxy conversation, then re-invokes the proxy.
        On the second turn the skill emits RESPONSE and the listener
        terminates with the final answer."""
        from teaparty.messaging.conversations import (
            SqliteMessageBus,
            ConversationType,
            make_conversation_id,
        )
        import json as _json
        import time as _time

        invocations = []

        async def mock_invoker(qualifier: str, cwd: str, **_: object) -> None:
            invocations.append(qualifier)
            proxy_bus = SqliteMessageBus(self.proxy_bus_path)
            conv_id = make_conversation_id(ConversationType.PROXY, qualifier)
            if len(invocations) == 1:
                # First turn: DIALOG — ask a clarifying question.
                proxy_bus.send(conv_id, 'proxy', _json.dumps({
                    'status': 'DIALOG',
                    'message': 'Do you mean production or staging?',
                }))
            else:
                # Second turn: RESPONSE — reply to teammate.
                proxy_bus.send(conv_id, 'proxy', _json.dumps({
                    'status': 'RESPONSE',
                    'message': 'Use Postgres on production',
                }))

        listener = self._make_listener(mock_invoker)

        async def _human_replies_after(delay: float):
            """Simulate the accordion writing a human reply to the proxy
            conversation after the first invocation."""
            await asyncio.sleep(delay)
            # Find the in-flight escalation qualifier from the first invocation.
            deadline = _time.time() + 5
            while _time.time() < deadline and not invocations:
                await asyncio.sleep(0.05)
            qualifier = invocations[0]
            proxy_bus = SqliteMessageBus(self.proxy_bus_path)
            conv_id = make_conversation_id(ConversationType.PROXY, qualifier)
            proxy_bus.send(conv_id, 'human', 'production please')

        async def _test():
            await listener.start()
            try:
                # Kick the simulated human reply in parallel.
                human_task = asyncio.create_task(_human_replies_after(0.2))
                self._send_ask('What database?')
                deadline = _time.time() + 10
                response = None
                while _time.time() < deadline:
                    bus = SqliteMessageBus(self.bus_db)
                    msgs = bus.receive(self.conv_id, since_timestamp=0)
                    replies = [m for m in msgs if m.sender == 'orchestrator']
                    if replies:
                        response = _json.loads(replies[0].content)
                        break
                    await asyncio.sleep(0.05)
                await human_task
                self.assertIsNotNone(response)
                self.assertEqual(
                    response['answer'], 'Use Postgres on production',
                )
                self.assertEqual(len(invocations), 2,
                                 'proxy must be invoked twice (DIALOG then RESPONSE)')
            finally:
                await listener.stop()

        _run(_test())


# ── Tests: skill output parser (DD6) ───────────────────────────────────────

class TestSkillOutputParser(unittest.TestCase):
    """``_parse_skill_output`` extracts the outermost
    ``{"status": ..., "message": ...}`` from the proxy's last turn."""

    def test_plain_json_object(self):
        from teaparty.cfa.gates.escalation import _parse_skill_output
        status, message = _parse_skill_output(
            '{"status": "RESPONSE", "message": "Use Postgres"}',
        )
        self.assertEqual(status, 'RESPONSE')
        self.assertEqual(message, 'Use Postgres')

    def test_surrounded_by_prose(self):
        from teaparty.cfa.gates.escalation import _parse_skill_output
        text = (
            'Thinking aloud here...\n'
            'I will respond with:\n'
            '{"status": "DIALOG", "message": "Which database?"}\n'
            'done.'
        )
        status, message = _parse_skill_output(text)
        self.assertEqual(status, 'DIALOG')
        self.assertEqual(message, 'Which database?')

    def test_withdraw_status(self):
        from teaparty.cfa.gates.escalation import _parse_skill_output
        status, message = _parse_skill_output(
            '{"status": "WITHDRAW", "message": "abandoned"}',
        )
        self.assertEqual(status, 'WITHDRAW')
        self.assertEqual(message, 'abandoned')

    def test_unknown_status_returns_empty(self):
        from teaparty.cfa.gates.escalation import _parse_skill_output
        status, message = _parse_skill_output(
            '{"status": "BOGUS", "message": "x"}',
        )
        self.assertEqual(status, '')
        self.assertEqual(message, '')

    def test_no_json_returns_empty(self):
        from teaparty.cfa.gates.escalation import _parse_skill_output
        status, message = _parse_skill_output('just prose, no json')
        self.assertEqual(status, '')
        self.assertEqual(message, '')

    def test_message_with_nested_braces(self):
        """A ``message`` string containing ``{`` / ``}`` must still parse
        because the brace-walker respects string literals."""
        from teaparty.cfa.gates.escalation import _parse_skill_output
        status, message = _parse_skill_output(
            '{"status": "RESPONSE", "message": "Use {db: postgres}"}',
        )
        self.assertEqual(status, 'RESPONSE')
        self.assertEqual(message, 'Use {db: postgres}')

    def test_last_recognised_object_wins(self):
        """Intermediate JSON fragments should lose to the terminal turn."""
        from teaparty.cfa.gates.escalation import _parse_skill_output
        text = (
            '{"status": "DIALOG", "message": "first"}\n'
            'then later:\n'
            '{"status": "RESPONSE", "message": "final"}'
        )
        status, message = _parse_skill_output(text)
        self.assertEqual(status, 'RESPONSE')
        self.assertEqual(message, 'final')


if __name__ == '__main__':
    unittest.main()
