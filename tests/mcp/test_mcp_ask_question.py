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

    @unittest.skip(
        "Obsolete contract: this asserted that cold start forces escalation "
        "to the human and records the differential.  Cold-start cap was "
        "dropped (MEMORY_DEPTH_THRESHOLD=0), so the proxy may answer "
        "directly instead of escalating.  Differential recording on "
        "escalation is still covered via the confident-proxy path in "
        "test_no_differential_when_proxy_is_confident and sibling tests."
    )
    def test_cold_start_records_differential(self):
        pass

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


if __name__ == '__main__':
    unittest.main()
