#!/usr/bin/env python3
"""Tests for the AskQuestion MCP tool (issue #137, Cut 10 consolidation).

The tool handler delegates to a per-caller ``AskQuestionRunner``
registered in ``teaparty.mcp.registry``.  The runner spawns a proxy
child via the ``/escalation`` skill, loops on DIALOG/RESPONSE/WITHDRAW,
and returns the answer — same-process direct call, no bus ping-pong.

Tests:
  - The handler's thin lookup-and-delegate contract.
  - The runner's skill loop (RESPONSE / WITHDRAW / DIALOG).
  - The ``_parse_skill_output`` parser.
  - MCP tool registration at the server layer.
"""
try:
    import mcp  # noqa: F401
except ImportError:
    import unittest
    raise unittest.SkipTest('mcp package not installed')

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# ── Helpers ──────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


# ── Tests: AskQuestion handler contract ─────────────────────────────────────

class TestAskQuestionHandler(unittest.TestCase):
    """The handler looks up the caller's runner and delegates to it."""

    def setUp(self):
        from teaparty.mcp.registry import clear
        clear()

    def tearDown(self):
        from teaparty.mcp.registry import clear
        clear()

    def test_handler_exists_and_is_callable(self):
        from teaparty.mcp.server.main import ask_question_handler
        self.assertTrue(callable(ask_question_handler))

    def test_handler_rejects_empty_question(self):
        from teaparty.mcp.tools.escalation import ask_question_handler
        with self.assertRaises(ValueError):
            _run(ask_question_handler(question=''))

    def test_handler_raises_when_no_runner_registered(self):
        """The handler must surface the missing-runner condition — no
        silent fallback.  Returning empty would hide a caller bug where
        the agent session forgot to register."""
        from teaparty.mcp.tools.escalation import ask_question_handler
        with self.assertRaises(RuntimeError) as ctx:
            _run(ask_question_handler(question='Anything?'))
        self.assertIn('AskQuestionRunner', str(ctx.exception))

    def test_handler_delegates_to_registered_runner(self):
        """The handler calls ``runner.run(question, context)`` and
        returns its value verbatim."""
        from teaparty.mcp.tools.escalation import ask_question_handler
        from teaparty.mcp.registry import (
            register_ask_question_runner, current_agent_name,
        )

        captured = []

        class _StubRunner:
            async def run(self, question, context='', *, attachments=None):
                captured.append((question, context, list(attachments or [])))
                return 'Ages 5-8'

        register_ask_question_runner('test-agent', _StubRunner())
        token = current_agent_name.set('test-agent')
        try:
            result = _run(ask_question_handler(
                question='Who is the audience?',
                context='Joke book',
            ))
        finally:
            current_agent_name.reset(token)

        self.assertEqual(result, 'Ages 5-8')
        self.assertEqual(captured, [('Who is the audience?', 'Joke book', [])])


# ── Tests: AskQuestionRunner skill loop (issue #420) ───────────────────────

class TestRunnerSkillLoop(unittest.TestCase):
    """``AskQuestionRunner.run()`` drives the proxy + ``/escalation`` skill.

    The mock proxy invoker stands in for the bridge's ``_invoke_proxy``.
    It writes a canned response to the per-escalation proxy conversation
    and (for DIALOG turns) waits for the human before returning, so the
    runner observes the same message ordering it would in production.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.teaparty_home = os.path.join(self.tmpdir, '.teaparty')
        self.infra_dir = os.path.join(
            self.teaparty_home, 'management', 'agents', 'proxy',
        )
        os.makedirs(self.infra_dir, exist_ok=True)
        proxy_dir = os.path.join(self.teaparty_home, 'proxy')
        os.makedirs(proxy_dir, exist_ok=True)
        self.proxy_bus_path = os.path.join(proxy_dir, 'proxy-messages.db')
        self.bus_db = os.path.join(self.infra_dir, 'messages.db')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_runner(self, proxy_invoker, on_dispatch=None):
        from teaparty.cfa.gates.escalation import AskQuestionRunner
        from teaparty.runners.launcher import create_session

        dispatcher = create_session(
            agent_name='office-manager',
            scope='management',
            teaparty_home=self.teaparty_home,
            session_id='test-dispatcher',
        )

        return AskQuestionRunner(
            bus_db_path=self.bus_db,
            session_id=dispatcher.id,
            infra_dir=self.infra_dir,
            proxy_invoker_fn=proxy_invoker,
            on_dispatch=on_dispatch,
            dispatcher_session=dispatcher,
            # Dispatcher is a dispatched agent here, so its conv_id
            # follows the ``dispatch:{sid}`` form.
            dispatcher_conv_id=f'dispatch:{dispatcher.id}',
            teaparty_home=self.teaparty_home,
            scope='management',
        )

    def test_response_terminates_loop_with_message(self):
        """RESPONSE from the skill → runner returns the message.  The
        proxy invoker is called exactly once.  Mid-loop, the dispatch
        tree rooted at the dispatcher shows the escalation as a child."""
        from teaparty.messaging.conversations import (
            SqliteMessageBus,
            ConversationType,
            make_conversation_id,
        )

        invocations = []
        dispatch_events = []
        mid_loop_trees = []

        async def mock_invoker(qualifier: str, cwd: str, **_: object) -> None:
            invocations.append((qualifier, cwd))
            # The cwd is the materialized worktree clone (#425);
            # the question itself reaches the proxy via the bus.
            assert os.path.isdir(cwd), f'cwd {cwd!r} must exist'
            # Accordion invariant: mid-loop, build_dispatch_tree rooted
            # at the dispatcher sees the escalation as a child node with
            # agent_name='proxy'.
            from teaparty.bridge.state.dispatch_tree import build_dispatch_tree
            mid_loop_trees.append(
                build_dispatch_tree(
                    SqliteMessageBus(self.bus_db),
                    'dispatch:test-dispatcher',
                    root_session_id='test-dispatcher',
                ),
            )
            proxy_bus = SqliteMessageBus(self.proxy_bus_path)
            conv_id = make_conversation_id(ConversationType.PROXY, qualifier)
            proxy_bus.send(conv_id, 'proxy', json.dumps({
                'status': 'RESPONSE', 'message': 'Use Postgres',
            }))

        def on_dispatch(evt):
            dispatch_events.append(evt)

        runner = self._make_runner(mock_invoker, on_dispatch=on_dispatch)

        answer = _run(runner.run('What database?'))

        self.assertEqual(answer, 'Use Postgres')
        self.assertEqual(len(invocations), 1)
        types = [e['type'] for e in dispatch_events]
        self.assertIn('dispatch_started', types)
        self.assertIn('dispatch_completed', types)
        # The escalation dir is torn down after termination.
        _qual, cwd = invocations[0]
        self.assertFalse(os.path.exists(cwd))
        # Mid-loop tree: dispatcher sees the escalation as its child.
        self.assertEqual(len(mid_loop_trees), 1)
        tree = mid_loop_trees[0]
        self.assertEqual(tree['session_id'], 'test-dispatcher')
        self.assertEqual(len(tree['children']), 1,
                         'dispatcher must see exactly one escalation child')
        child = tree['children'][0]
        self.assertEqual(child['agent_name'], 'proxy')
        # One-identity invariant: the tree's conversation_id MUST equal
        # the proxy bus conv_id where messages live.
        self.assertTrue(
            child['conversation_id'].startswith('proxy:'),
            "escalation's bus row id must be the proxy conv_id",
        )

    def test_withdraw_prefixes_answer_with_marker(self):
        """WITHDRAW from the skill → answer is ``[WITHDRAW]\\n<reason>``."""
        from teaparty.messaging.conversations import (
            SqliteMessageBus,
            ConversationType,
            make_conversation_id,
        )

        async def mock_invoker(qualifier: str, cwd: str, **_: object) -> None:
            proxy_bus = SqliteMessageBus(self.proxy_bus_path)
            conv_id = make_conversation_id(ConversationType.PROXY, qualifier)
            proxy_bus.send(conv_id, 'proxy', json.dumps({
                'status': 'WITHDRAW', 'message': 'abandoned',
            }))

        runner = self._make_runner(mock_invoker)
        answer = _run(runner.run('Still doing this?'))
        self.assertEqual(answer, '[WITHDRAW]\nabandoned')

    def test_dialog_loop_waits_for_human_then_resumes(self):
        """DIALOG from the skill → runner waits for a sender='human'
        message on the proxy conversation, then re-invokes the proxy.
        On the second turn the skill emits RESPONSE and the runner
        terminates with the final answer."""
        from teaparty.messaging.conversations import (
            SqliteMessageBus,
            ConversationType,
            make_conversation_id,
        )

        invocations = []

        async def mock_invoker(qualifier: str, cwd: str, **_: object) -> None:
            invocations.append(qualifier)
            proxy_bus = SqliteMessageBus(self.proxy_bus_path)
            conv_id = make_conversation_id(ConversationType.PROXY, qualifier)
            if len(invocations) == 1:
                # First turn: DIALOG — ask a clarifying question.
                proxy_bus.send(conv_id, 'proxy', json.dumps({
                    'status': 'DIALOG',
                    'message': 'Do you mean production or staging?',
                }))
            else:
                # Second turn: RESPONSE — reply to teammate.
                proxy_bus.send(conv_id, 'proxy', json.dumps({
                    'status': 'RESPONSE',
                    'message': 'Use Postgres on production',
                }))

        runner = self._make_runner(mock_invoker)

        async def _human_replies_after(delay: float):
            """Simulate the accordion writing a human reply to the
            proxy conversation after the first invocation."""
            await asyncio.sleep(delay)
            deadline = time.time() + 5
            while time.time() < deadline and not invocations:
                await asyncio.sleep(0.05)
            qualifier = invocations[0]
            proxy_bus = SqliteMessageBus(self.proxy_bus_path)
            conv_id = make_conversation_id(ConversationType.PROXY, qualifier)
            proxy_bus.send(conv_id, 'human', 'production please')

        async def _test():
            human_task = asyncio.create_task(_human_replies_after(0.2))
            answer = await runner.run('What database?')
            await human_task
            self.assertEqual(answer, 'Use Postgres on production')
            self.assertEqual(
                len(invocations), 2,
                'proxy must be invoked twice (DIALOG then RESPONSE)',
            )

        _run(_test())


# ── Tests: MCP server tool registration ─────────────────────────────────────

class TestMCPServerRegistration(unittest.TestCase):
    """The MCP server must register AskQuestion as an available tool."""

    def test_server_has_ask_question_tool(self):
        from teaparty.mcp.server.main import create_server
        server = create_server()
        tools = _run(server.list_tools())
        tool_names = [t.name for t in tools]
        self.assertIn('AskQuestion', tool_names)


# ── Tests: ClaudeRunner MCP integration ─────────────────────────────────────

class TestClaudeRunnerMCPIntegration(unittest.TestCase):
    """ClaudeRunner must wire the MCP server into Claude Code's args."""

    def test_no_mcp_config_when_not_provided(self):
        from teaparty.runners.claude import ClaudeRunner

        runner = ClaudeRunner(
            prompt='test',
            cwd='/tmp',
            stream_file='/tmp/stream.jsonl',
        )
        args = runner._build_args(None)
        self.assertNotIn('--mcp-config', args)


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

    def test_last_matching_object_wins(self):
        """When the proxy emits intermediate thinking that contains
        JSON-looking fragments, the terminal turn is the one that
        matters — the last recognised status object wins."""
        from teaparty.cfa.gates.escalation import _parse_skill_output
        text = (
            '{"status": "DIALOG", "message": "thinking out loud"}\n'
            '... revising ...\n'
            '{"status": "RESPONSE", "message": "final answer"}'
        )
        status, message = _parse_skill_output(text)
        self.assertEqual(status, 'RESPONSE')
        self.assertEqual(message, 'final answer')


if __name__ == '__main__':
    unittest.main()
