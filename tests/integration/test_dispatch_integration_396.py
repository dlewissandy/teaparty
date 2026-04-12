"""Integration tests for issue #396: async dispatch, full end-to-end.

Every test invokes a real coordinator agent with a real message, lets
it make real decisions via the Send tool, and verifies its real output.
No stubs. No direct spawn_fn calls from the test.

Flow:
1. Test writes a human message to the coordinator's bus conversation
2. Test calls coordinator.invoke() — same path the bridge uses
3. Coordinator reads the message, uses Send to dispatch
4. Children run, respond via bus
5. Coordinator is resumed, integrates replies, produces final output
6. Test reads the coordinator's final output from its bus
7. Test calls CloseConversation for every handle, verifies cleanup

Architecture: one TeaPartyBridge on a test port, real git repo,
real claude calls, real MCP. Tests share the bridge but each test
gets a fresh coordinator conversation (cleared at setUp).

Requires: claude binary on PATH, Max subscription active.
"""
import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest

HAVE_CLAUDE = shutil.which('claude') is not None
BRIDGE_PORT = 19876

_module_env = None
_module_loop = None
_module_runner = None


def _make_test_environment():
    repo_root = tempfile.mkdtemp()

    # Real git repo — worktree operations require it
    subprocess.run(['git', 'init', '-q'], cwd=repo_root, check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@example.com'],
                   cwd=repo_root, check=True)
    subprocess.run(['git', 'config', 'user.name', 'test'],
                   cwd=repo_root, check=True)
    with open(os.path.join(repo_root, 'README.md'), 'w') as f:
        f.write('test\n')
    subprocess.run(['git', 'add', 'README.md'], cwd=repo_root, check=True)
    subprocess.run(['git', 'commit', '-q', '-m', 'init'],
                   cwd=repo_root, check=True)

    teaparty_home = os.path.join(repo_root, '.teaparty')
    sessions_dir = os.path.join(teaparty_home, 'management', 'sessions')
    agents_dir = os.path.join(teaparty_home, 'management', 'agents')
    os.makedirs(sessions_dir)

    # ── Agents ───────────────────────────────────────────────────────────

    # Leaf agent — responds to messages, no tools
    _write_agent(agents_dir, 'leaf-agent', """---
name: leaf-agent
description: A simple test agent that responds with a one-word acknowledgment.
model: haiku
---
You are a test agent. Respond with a single word that echoes the key
word from the message you receive. For example, if asked to "say alpha",
respond with "alpha". If asked to "say hello", respond with "hello".
Do not use any tools. Just respond with the one word.
""")

    # Coordinator — the parent agent for tests. Has Send + CloseConversation.
    _write_agent(agents_dir, 'coordinator', """---
name: coordinator
description: Test coordinator that dispatches work via Send and integrates replies.
model: sonnet
tools: mcp__teaparty-config__Send, mcp__teaparty-config__CloseConversation
---
You are a test coordinator. You receive a task from the human and use
the Send tool to dispatch work to member agents. You MUST use the Send
tool to dispatch — do not answer directly.

When Send returns with status="message_sent" and a conversation_id,
that means the child is running. The child's reply will arrive as a
subsequent message in this conversation (prefixed with "Reply from").

After all dispatches and replies complete, respond with a single
summary line that begins with "RESULT:" followed by the replies you
received, in the order they arrived. Example:
  "RESULT: alpha, beta"

Do not call CloseConversation — the test framework handles cleanup.
""")

    # Workgroup: coordinator leads, leaf-agent is member
    wg_dir = os.path.join(teaparty_home, 'management', 'workgroups')
    os.makedirs(wg_dir)
    with open(os.path.join(wg_dir, 'test-team.yaml'), 'w') as f:
        f.write('name: test-team\nlead: coordinator\n'
                'members:\n  agents:\n    - leaf-agent\n')

    # Management team
    with open(os.path.join(teaparty_home, 'management', 'teaparty.yaml'), 'w') as f:
        f.write('name: test\nlead: coordinator\n'
                'workgroups:\n'
                '  - name: test-team\n'
                '    config: workgroups/test-team.yaml\n'
                'members:\n  workgroups:\n    - test-team\n')

    # Static dir for the bridge
    static_dir = os.path.join(repo_root, 'static')
    os.makedirs(static_dir)
    with open(os.path.join(static_dir, 'index.html'), 'w') as f:
        f.write('<html></html>')

    return teaparty_home, repo_root, static_dir


def _write_agent(agents_dir, name, content):
    agent_dir = os.path.join(agents_dir, name)
    os.makedirs(agent_dir, exist_ok=True)
    with open(os.path.join(agent_dir, 'agent.md'), 'w') as f:
        f.write(content)


def setUpModule():
    global _module_env, _module_loop, _module_runner
    if not HAVE_CLAUDE:
        return
    _module_env = _make_test_environment()
    teaparty_home, repo_root, static_dir = _module_env
    os.environ['TEAPARTY_BRIDGE_PORT'] = str(BRIDGE_PORT)
    _module_loop = asyncio.new_event_loop()
    from aiohttp import web
    from teaparty.bridge.server import TeaPartyBridge
    bridge = TeaPartyBridge(teaparty_home=teaparty_home, static_dir=static_dir)
    app = bridge._build_app()
    _module_runner = web.AppRunner(app)

    async def start():
        await _module_runner.setup()
        await web.TCPSite(_module_runner, 'localhost', BRIDGE_PORT).start()
    _module_loop.run_until_complete(start())


def tearDownModule():
    global _module_env, _module_loop, _module_runner
    if _module_runner:
        _module_loop.run_until_complete(_module_runner.cleanup())
    if _module_loop:
        pending = asyncio.all_tasks(_module_loop)
        if pending:
            _module_loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True))
        _module_loop.close()
    if _module_env:
        shutil.rmtree(_module_env[1], ignore_errors=True)
    os.environ.pop('TEAPARTY_BRIDGE_PORT', None)


def _run(coro, timeout=180):
    return _module_loop.run_until_complete(
        asyncio.wait_for(coro, timeout=timeout))


def _make_coordinator(qualifier):
    """Create a fresh coordinator session with a unique qualifier.

    Each test uses a different qualifier so bus conversations are isolated.
    """
    from teaparty.teams.session import AgentSession
    from teaparty.messaging.conversations import ConversationType
    return AgentSession(
        _module_env[0],
        agent_name='coordinator',
        scope='management',
        qualifier=qualifier,
        conversation_type=ConversationType.OFFICE_MANAGER,
        dispatches=True,
    )


def _send_human_message(session, message):
    """Write a human message to the coordinator's conversation bus."""
    session._bus.send(session.conversation_id, 'human', message)


def _get_coordinator_result(session):
    """Extract the coordinator's 'RESULT:' response from its conversation."""
    msgs = session._bus.receive(session.conversation_id)
    for m in reversed(msgs):
        if m.sender == 'coordinator' and 'RESULT:' in m.content:
            return m.content
    return None


async def _wait_for_result(session, timeout=120):
    """Poll the bus until the coordinator produces a RESULT: line.

    The coordinator's first turn dispatches and ends. Child replies
    trigger resumes (serialized by the invoke lock). Eventually one
    resume produces the RESULT: line.
    """
    for _ in range(timeout):
        await asyncio.sleep(1.0)
        result = _get_coordinator_result(session)
        if result:
            return result
    return None


def _print_conversation(label, messages):
    print(f'\n--- {label} ---')
    for m in messages:
        content = m.content if len(m.content) < 200 else m.content[:200] + '...'
        print(f'  [{m.sender}] {content}')


def _verify_cleanup(test, session, handles):
    """Close all handles, verify sessions removed from disk, slots freed."""
    from teaparty.workspace.close_conversation import close_conversation
    for conv_id in handles:
        child_sid = conv_id.replace('dispatch:', '')
        child_path = os.path.join(
            _module_env[0], 'management', 'sessions', child_sid)
        close_conversation(
            session._dispatch_session, conv_id,
            teaparty_home=_module_env[0], scope='management')
        test.assertFalse(
            os.path.isdir(child_path),
            f'Session dir should be removed: {child_path}')


def _get_dispatch_handles(session):
    """Return the list of dispatch:{id} conversation handles from parent's map."""
    cmap = session._dispatch_session.conversation_map
    return [f'dispatch:{child_sid}' for child_sid in cmap.values()]


@unittest.skipUnless(HAVE_CLAUDE, 'Requires claude binary')
class TestParallelDispatch(unittest.TestCase):
    """Coordinator dispatches to leaf-agent twice in parallel.
    Verifies the coordinator actually uses Send, both children run,
    both replies arrive, coordinator integrates them into RESULT:."""

    def test_full_e2e(self):
        session = _make_coordinator('parallel')

        async def run():
            _send_human_message(
                session,
                'Dispatch two messages in parallel: '
                'send "say alpha" to leaf-agent and "say beta" to leaf-agent. '
                'Wait for both replies, then respond with RESULT: '
                'followed by both words, separated by commas.')
            # First invoke runs the dispatch turn. Resumes happen in
            # background tasks when children reply.
            await session.invoke(cwd=_module_env[1])
            # Poll until the coordinator produces a RESULT line.
            return await _wait_for_result(session, timeout=120)

        result = _run(run(), timeout=180)

        msgs = session._bus.receive(session.conversation_id)
        _print_conversation('Coordinator conversation', msgs)

        self.assertIsNotNone(
            result, 'Coordinator must produce a RESULT: line')
        self.assertIn('alpha', result.lower(),
                      f'Result must mention alpha. Got: {result}')
        self.assertIn('beta', result.lower(),
                      f'Result must mention beta. Got: {result}')

        # Verify the coordinator used the Send tool at least twice
        tool_uses = [m for m in msgs if m.sender == 'tool_use'
                     and 'Send' in m.content]
        self.assertGreaterEqual(
            len(tool_uses), 2,
            f'Coordinator must call Send at least twice. '
            f'Tool uses: {[m.content[:60] for m in tool_uses]}')

        handles = _get_dispatch_handles(session)
        _verify_cleanup(self, session, handles)
        self.assertEqual(len(session._dispatch_session.conversation_map), 0)


@unittest.skipUnless(HAVE_CLAUDE, 'Requires claude binary')
class TestParallelInstance(unittest.TestCase):
    """Coordinator dispatches two tasks to the same leaf-agent.
    Both instances run independently, both replies arrive."""

    def test_full_e2e(self):
        session = _make_coordinator('instances')

        async def run():
            _send_human_message(
                session,
                'I need you to run two independent tasks on leaf-agent. '
                'Task 1: send "say red" to leaf-agent. '
                'Task 2: send "say blue" to leaf-agent. '
                'Wait for both replies, then respond with RESULT: '
                'followed by both colors, separated by commas.')
            await session.invoke(cwd=_module_env[1])
            return await _wait_for_result(session, timeout=120)

        result = _run(run(), timeout=180)

        msgs = session._bus.receive(session.conversation_id)
        _print_conversation('Coordinator conversation', msgs)

        self.assertIsNotNone(result)
        self.assertIn('red', result.lower())
        self.assertIn('blue', result.lower())

        tool_uses = [m for m in msgs if m.sender == 'tool_use'
                     and 'Send' in m.content]
        self.assertGreaterEqual(len(tool_uses), 2)

        handles = _get_dispatch_handles(session)
        _verify_cleanup(self, session, handles)


if __name__ == '__main__':
    unittest.main()
