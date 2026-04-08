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

sys.path.insert(0, str(Path(__file__).parent.parent))

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

    def test_mcp_server_config_in_build_args(self):
        """When mcp_config is provided, ClaudeRunner must include
        --mcp-config in the CLI args pointing to a temp file."""
        from teaparty.runners.claude import ClaudeRunner

        runner = ClaudeRunner(
            prompt='test',
            cwd='/tmp',
            stream_file='/tmp/stream.jsonl',
            mcp_config={'ask-question': {
                'command': 'python',
                'args': ['-m', 'teaparty.mcp.server.main'],
            }},
        )
        args = runner._build_args(None)
        self.assertIn('--mcp-config', args)
        # Clean up the temp file created by _build_args
        if runner._mcp_config_file:
            try:
                os.unlink(runner._mcp_config_file)
            except OSError:
                pass

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

    def test_listener_starts_and_creates_socket(self):
        """After start(), the socket path exists."""
        from teaparty.cfa.gates.escalation import EscalationListener

        bus = _make_event_bus()
        listener = EscalationListener(
            bus, AsyncMock(return_value='answer'), session_id='test',
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            project_slug='test', cfa_state='PROPOSAL',
        )

        async def _test():
            socket_path = await listener.start()
            self.assertTrue(os.path.exists(socket_path))
            await listener.stop()

        _run(_test())

    def test_cold_start_escalates_to_human(self):
        """With no proxy model (cold start), questions go to the human."""
        import json as _json
        from teaparty.cfa.gates.escalation import EscalationListener

        bus = _make_event_bus()
        human_called = []

        async def mock_input(req):
            human_called.append(req.bridge_text)
            return 'Ages 5-8'

        listener = EscalationListener(
            bus, mock_input, session_id='test',
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            project_slug='test', cfa_state='PROPOSAL',
        )

        async def _test():
            socket_path = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(socket_path)
                request = _json.dumps({'type': 'ask_human', 'question': 'Who is the audience?'})
                writer.write(request.encode() + b'\n')
                await writer.drain()

                response_line = await reader.readline()
                response = _json.loads(response_line.decode())
                writer.close()
                await writer.wait_closed()

                self.assertEqual(response['answer'], 'Ages 5-8')
                self.assertEqual(len(human_called), 1)
                self.assertEqual(human_called[0], 'Who is the audience?')
            finally:
                await listener.stop()

        _run(_test())

    def test_cold_start_records_differential(self):
        """On cold start, the differential (empty prediction vs. human answer)
        is recorded in the proxy model for learning."""
        import json as _json
        from teaparty.cfa.gates.escalation import EscalationListener

        bus = _make_event_bus()
        proxy_path = os.path.join(self.tmpdir, '.proxy.json')

        async def mock_input(req):
            return 'Use PostgreSQL'

        listener = EscalationListener(
            bus, mock_input, session_id='test',
            proxy_model_path=proxy_path,
            project_slug='test', cfa_state='PROPOSAL',
        )

        async def _test():
            socket_path = await listener.start()
            try:
                reader, writer = await asyncio.open_unix_connection(socket_path)
                request = _json.dumps({'type': 'ask_human', 'question': 'What database?'})
                writer.write(request.encode() + b'\n')
                await writer.drain()

                response_line = await reader.readline()
                writer.close()
                await writer.wait_closed()
            finally:
                await listener.stop()

        _run(_test())

        # The proxy model should now exist with a recorded outcome
        self.assertTrue(os.path.exists(proxy_path),
                        "Proxy model must be created after recording differential")

    def test_confident_proxy_returns_without_human(self):
        """When the proxy is confident, the human is never consulted."""
        import json as _json
        from teaparty.cfa.gates.escalation import EscalationListener
        from teaparty.proxy.agent import ProxyResult

        bus = _make_event_bus()
        human_called = []

        async def mock_input(req):
            human_called.append(req)
            return 'should not reach here'

        listener = EscalationListener(
            bus, mock_input, session_id='test',
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            project_slug='test', cfa_state='PROPOSAL',
        )

        async def _test():
            with patch(
                'teaparty.proxy.agent.consult_proxy',
                new=AsyncMock(return_value=ProxyResult(
                    text='Use PostgreSQL', confidence=0.95, from_agent=True,
                )),
            ):
                socket_path = await listener.start()
                try:
                    reader, writer = await asyncio.open_unix_connection(socket_path)
                    request = _json.dumps({'type': 'ask_human', 'question': 'What database?'})
                    writer.write(request.encode() + b'\n')
                    await writer.drain()

                    response_line = await reader.readline()
                    response = _json.loads(response_line.decode())
                    writer.close()
                    await writer.wait_closed()

                    self.assertEqual(response['answer'], 'Use PostgreSQL')
                    self.assertEqual(len(human_called), 0,
                                     "Human must NOT be consulted when proxy is confident")
                finally:
                    await listener.stop()

        _run(_test())


if __name__ == '__main__':
    unittest.main()
