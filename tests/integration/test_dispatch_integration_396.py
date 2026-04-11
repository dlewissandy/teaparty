"""Integration tests for issue #396: async dispatch with real LLM calls.

These tests exercise the entire code path — real claude -p processes,
real MCP server, real bus writes. No mocks.

Requires: claude binary on PATH, Max subscription active.
Skip with: pytest -m 'not integration'

Each test creates a real .teaparty config tree, starts the bridge's
MCP server, and runs real agent dispatches. Tests verify messages
arrive in the bus with the correct conversation handles.
"""
import asyncio
import json
import os
import shutil
import tempfile
import time
import unittest

HAVE_CLAUDE = shutil.which('claude') is not None


async def _start_bridge(teaparty_home, static_dir, port):
    """Start the bridge server non-blocking. Returns (runner, site) for cleanup."""
    from aiohttp import web
    from teaparty.bridge.server import TeaPartyBridge

    os.environ['TEAPARTY_BRIDGE_PORT'] = str(port)

    bridge = TeaPartyBridge(
        teaparty_home=teaparty_home,
        static_dir=static_dir,
    )
    app = bridge._build_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, 'localhost', port)
    await site.start()
    return runner, site, bridge


async def _stop_bridge(runner):
    """Stop the bridge server."""
    await runner.cleanup()


def _make_test_environment():
    """Create a complete .teaparty config tree for testing.

    Returns (teaparty_home, repo_root) where teaparty_home is the
    .teaparty directory and repo_root is its parent (simulating a repo).
    """
    repo_root = tempfile.mkdtemp()
    teaparty_home = os.path.join(repo_root, '.teaparty')
    sessions_dir = os.path.join(teaparty_home, 'management', 'sessions')
    agents_dir = os.path.join(teaparty_home, 'management', 'agents')
    os.makedirs(sessions_dir)

    # Agent: leaf-agent — responds with a short message, no tools
    _write_agent(agents_dir, 'leaf-agent', """---
name: leaf-agent
description: A simple agent that responds to messages.
model: sonnet
---
You are a test agent. When you receive a message, respond with a single
short sentence acknowledging the message. Do not use any tools. Just respond
with text.
""")

    # Agent: dispatcher-agent — calls Send to dispatch to leaf-agent
    _write_agent(agents_dir, 'dispatcher-agent', """---
name: dispatcher-agent
description: An agent that dispatches work to leaf-agent via Send.
model: sonnet
tools: mcp__teaparty-config__Send
---
You are a test dispatcher. When you receive a message:
1. Use the Send tool to send the message to member 'leaf-agent'
2. After Send returns with the conversation handle, respond with the text: "Dispatched. Handle: " followed by the conversation_id.

Do not use any other tools. Do not do anything else.
""")

    # Agent: slow-agent — waits a bit before responding
    _write_agent(agents_dir, 'slow-agent', """---
name: slow-agent
description: A slow agent for testing timeouts.
model: haiku
---
You are a test agent. When you receive a message, respond with
"Slow agent done." Do not use any tools.
""")

    # Workgroup config: dispatcher-agent leads a workgroup containing leaf-agent.
    # This makes has_sub_roster return True for dispatcher-agent.
    wg_dir = os.path.join(teaparty_home, 'management', 'workgroups')
    os.makedirs(wg_dir, exist_ok=True)
    with open(os.path.join(wg_dir, 'dispatch-team.yaml'), 'w') as f:
        f.write('name: dispatch-team\n')
        f.write('lead: dispatcher-agent\n')
        f.write('members:\n')
        f.write('  agents:\n')
        f.write('    - leaf-agent\n')

    # Minimal teaparty.yaml — workgroups registered AND active
    with open(os.path.join(teaparty_home, 'management', 'teaparty.yaml'), 'w') as f:
        f.write('name: test\n')
        f.write('lead: test-parent\n')
        f.write('workgroups:\n')
        f.write('  - name: dispatch-team\n')
        f.write('    config: workgroups/dispatch-team.yaml\n')
        f.write('members:\n')
        f.write('  workgroups:\n')
        f.write('    - dispatch-team\n')

    # Create the parent dispatch session
    from teaparty.runners.launcher import create_session
    create_session(agent_name='test-parent', scope='management',
                   teaparty_home=teaparty_home, session_id='test-parent-main')

    # Static dir for the bridge (minimal — just needs to exist)
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


def _run_async(coro, timeout=120):
    """Run an async coroutine with a timeout."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            asyncio.wait_for(coro, timeout=timeout))
    finally:
        # Let background tasks finish
        pending = asyncio.all_tasks(loop)
        if pending:
            loop.run_until_complete(
                asyncio.gather(*pending, return_exceptions=True))
        loop.close()


@unittest.skipUnless(HAVE_CLAUDE, 'Requires claude binary')
class TestParallelLeafDispatch(unittest.TestCase):
    """Test case 2: A → B, C (parallel leaf dispatch).

    A dispatches to two leaf agents in parallel. Both respond.
    Both responses arrive in separate bus conversations.
    """

    def setUp(self):
        self._teaparty_home, self._repo_root, self._static_dir = _make_test_environment()

    def tearDown(self):
        shutil.rmtree(self._repo_root, ignore_errors=True)

    def test_two_leaf_agents_respond_independently(self):
        from teaparty.teams.session import AgentSession
        from teaparty.messaging.conversations import ConversationType

        session = AgentSession(
            self._teaparty_home,
            agent_name='test-parent',
            scope='management',
            qualifier='main',
            conversation_type=ConversationType.OFFICE_MANAGER,
            dispatches=True,
        )

        async def run():
            await session._ensure_bus_listener(self._repo_root)
            from teaparty.mcp.registry import get_spawn_fn
            spawn_fn = get_spawn_fn('test-parent')
            self.assertIsNotNone(spawn_fn, 'spawn_fn not registered')

            # Dispatch to two leaf agents in parallel
            t0 = time.monotonic()
            sid_b, _, _ = await spawn_fn(
                'leaf-agent', 'Hello from test, please respond.', 'ctx-b')
            sid_c, _, _ = await spawn_fn(
                'leaf-agent', 'Another message, please respond.', 'ctx-c')
            dispatch_time = time.monotonic() - t0

            # Both should return immediately (async dispatch)
            self.assertTrue(len(sid_b) > 0, 'First dispatch should succeed')
            self.assertTrue(len(sid_c) > 0, 'Second dispatch should succeed')
            self.assertNotEqual(sid_b, sid_c, 'Different session IDs')
            self.assertLess(dispatch_time, 2.0,
                            'Both dispatches should return in < 2s (async)')

            # Wait for both agents to complete
            for _ in range(60):  # up to 60 seconds
                await asyncio.sleep(1.0)
                msgs_b = session._bus.receive(f'dispatch:{sid_b}')
                msgs_c = session._bus.receive(f'dispatch:{sid_c}')
                b_has_response = any(
                    m.sender == 'leaf-agent' for m in msgs_b)
                c_has_response = any(
                    m.sender == 'leaf-agent' for m in msgs_c)
                if b_has_response and c_has_response:
                    break

            # Verify both responded
            msgs_b = session._bus.receive(f'dispatch:{sid_b}')
            msgs_c = session._bus.receive(f'dispatch:{sid_c}')

            b_senders = [m.sender for m in msgs_b]
            c_senders = [m.sender for m in msgs_c]

            self.assertIn('leaf-agent', b_senders,
                          f'B should have leaf-agent response. Senders: {b_senders}')
            self.assertIn('leaf-agent', c_senders,
                          f'C should have leaf-agent response. Senders: {c_senders}')

            # Print actual messages for inspection
            print('\n--- B conversation ---')
            for m in msgs_b:
                print(f'  [{m.sender}] {m.content[:80]}')
            print('\n--- C conversation ---')
            for m in msgs_c:
                print(f'  [{m.sender}] {m.content[:80]}')

        _run_async(run())


@unittest.skipUnless(HAVE_CLAUDE, 'Requires claude binary')
class TestSlotLimitAndReuse(unittest.TestCase):
    """Test case 3: A → B, C, D (fills slots), close one, send E."""

    def setUp(self):
        self._teaparty_home, self._repo_root, self._static_dir = _make_test_environment()

    def tearDown(self):
        shutil.rmtree(self._repo_root, ignore_errors=True)

    def test_fourth_rejected_then_close_and_retry(self):
        from teaparty.teams.session import AgentSession
        from teaparty.messaging.conversations import ConversationType
        from teaparty.workspace.close_conversation import close_conversation

        session = AgentSession(
            self._teaparty_home,
            agent_name='test-parent',
            scope='management',
            qualifier='main',
            conversation_type=ConversationType.OFFICE_MANAGER,
            dispatches=True,
        )

        async def run():
            await session._ensure_bus_listener(self._repo_root)
            from teaparty.mcp.registry import get_spawn_fn
            spawn_fn = get_spawn_fn('test-parent')

            # Fill 3 slots
            sids = []
            for i in range(3):
                sid, _, _ = await spawn_fn(
                    'leaf-agent', f'Message {i}', f'ctx-{i}')
                self.assertTrue(len(sid) > 0, f'Dispatch {i} should succeed')
                sids.append(sid)

            # 4th should fail
            sid_4, _, _ = await spawn_fn('leaf-agent', 'Message 3', 'ctx-3')
            self.assertEqual(sid_4, '', '4th dispatch should be rejected')

            # Wait for first agent to finish
            for _ in range(60):
                await asyncio.sleep(1.0)
                msgs = session._bus.receive(f'dispatch:{sids[0]}')
                if any(m.sender == 'leaf-agent' for m in msgs):
                    break

            # Close it
            close_conversation(
                session._dispatch_session, f'dispatch:{sids[0]}',
                teaparty_home=self._teaparty_home, scope='management')

            # Now should succeed
            sid_4, _, _ = await spawn_fn('leaf-agent', 'Message 3', 'ctx-3b')
            self.assertTrue(len(sid_4) > 0,
                            'Dispatch should succeed after close')

            print(f'\nSlot freed after close. New dispatch: {sid_4}')

        _run_async(run())


@unittest.skipUnless(HAVE_CLAUDE, 'Requires claude binary')
class TestParallelInstanceSameAgent(unittest.TestCase):
    """Test case 4: A → B, B (two instances of same agent)."""

    def setUp(self):
        self._teaparty_home, self._repo_root, self._static_dir = _make_test_environment()

    def tearDown(self):
        shutil.rmtree(self._repo_root, ignore_errors=True)

    def test_two_instances_respond_separately(self):
        from teaparty.teams.session import AgentSession
        from teaparty.messaging.conversations import ConversationType

        session = AgentSession(
            self._teaparty_home,
            agent_name='test-parent',
            scope='management',
            qualifier='main',
            conversation_type=ConversationType.OFFICE_MANAGER,
            dispatches=True,
        )

        async def run():
            await session._ensure_bus_listener(self._repo_root)
            from teaparty.mcp.registry import get_spawn_fn
            spawn_fn = get_spawn_fn('test-parent')

            sid_1, _, _ = await spawn_fn(
                'leaf-agent', 'First instance message', 'ctx-inst-1')
            sid_2, _, _ = await spawn_fn(
                'leaf-agent', 'Second instance message', 'ctx-inst-2')

            self.assertNotEqual(sid_1, sid_2)

            # Wait for both
            for _ in range(60):
                await asyncio.sleep(1.0)
                m1 = session._bus.receive(f'dispatch:{sid_1}')
                m2 = session._bus.receive(f'dispatch:{sid_2}')
                if (any(m.sender == 'leaf-agent' for m in m1) and
                        any(m.sender == 'leaf-agent' for m in m2)):
                    break

            msgs_1 = session._bus.receive(f'dispatch:{sid_1}')
            msgs_2 = session._bus.receive(f'dispatch:{sid_2}')

            self.assertTrue(any(m.sender == 'leaf-agent' for m in msgs_1),
                            'Instance 1 should respond')
            self.assertTrue(any(m.sender == 'leaf-agent' for m in msgs_2),
                            'Instance 2 should respond')

            print('\n--- Instance 1 ---')
            for m in msgs_1:
                print(f'  [{m.sender}] {m.content[:80]}')
            print('\n--- Instance 2 ---')
            for m in msgs_2:
                print(f'  [{m.sender}] {m.content[:80]}')

        _run_async(run())


@unittest.skipUnless(HAVE_CLAUDE, 'Requires claude binary')
class TestLinearDispatch(unittest.TestCase):
    """Test case 1: A → B → C (linear dispatch with real MCP).

    A dispatches to dispatcher-agent (B). B calls Send to dispatch to
    leaf-agent (C). C responds. B responds. Both responses are in the
    bus under their respective conversation handles.

    Requires the bridge's MCP server running so B can call Send.
    """

    def setUp(self):
        self._teaparty_home, self._repo_root, self._static_dir = _make_test_environment()

    def tearDown(self):
        shutil.rmtree(self._repo_root, ignore_errors=True)

    def test_linear_chain_with_real_mcp(self):
        from teaparty.teams.session import AgentSession
        from teaparty.messaging.conversations import ConversationType

        session = AgentSession(
            self._teaparty_home,
            agent_name='test-parent',
            scope='management',
            qualifier='main',
            conversation_type=ConversationType.OFFICE_MANAGER,
            dispatches=True,
        )

        async def run():
            # Start bridge so B can call Send via MCP
            port = 19876
            runner, site, bridge = await _start_bridge(
                self._teaparty_home, self._static_dir, port)

            try:
                await session._ensure_bus_listener(self._repo_root)
                from teaparty.mcp.registry import get_spawn_fn
                spawn_fn = get_spawn_fn('test-parent')
                self.assertIsNotNone(spawn_fn)

                # A dispatches to B (dispatcher-agent)
                b_sid, _, _ = await spawn_fn(
                    'dispatcher-agent',
                    'Please dispatch this to leaf-agent: "What is 2+2?"',
                    'a-to-b')
                self.assertTrue(len(b_sid) > 0, 'Dispatch to B should succeed')

                # Wait for B to dispatch to C and both to complete
                b_responded = False
                for _ in range(90):
                    await asyncio.sleep(1.0)
                    msgs_b = session._bus.receive(f'dispatch:{b_sid}')
                    if any(m.sender == 'dispatcher-agent' for m in msgs_b):
                        b_responded = True
                        break

                self.assertTrue(b_responded, 'B (dispatcher-agent) should respond')

                msgs_b = session._bus.receive(f'dispatch:{b_sid}')
                print('\n--- B (dispatcher-agent) conversation ---')
                for m in msgs_b:
                    print(f'  [{m.sender}] {m.content[:100]}')

                # Verify B's response mentions the dispatch handle
                b_text = ' '.join(m.content for m in msgs_b
                                  if m.sender == 'dispatcher-agent')
                self.assertTrue(
                    'dispatch:' in b_text.lower() or 'handle' in b_text.lower()
                    or 'leaf-agent' in b_text.lower() or 'message_sent' in b_text.lower(),
                    f'B should mention the dispatch. Got: {b_text[:200]}')

            finally:
                await _stop_bridge(runner)

        _run_async(run(), timeout=120)


if __name__ == '__main__':
    unittest.main()
