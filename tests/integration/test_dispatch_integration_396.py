"""Integration tests for issue #396: async dispatch with real LLM calls.

These tests exercise the entire code path — real claude -p processes,
real MCP server, real bus writes. No mocks.

Requires: claude binary on PATH, Max subscription active.

Architecture: one TeaPartyBridge starts for the entire module on a
test-only port. All tests share the same bridge, the same .teaparty
config tree, and the same event loop. This is the real bridge code
on a different port — not a test-specific reimplementation.
"""
import asyncio
import json
import os
import shutil
import tempfile
import time
import unittest

HAVE_CLAUDE = shutil.which('claude') is not None
BRIDGE_PORT = 19876

# Module-level state — shared across all tests
_module_env = None    # (teaparty_home, repo_root, static_dir)
_module_loop = None
_module_runner = None


def _make_test_environment():
    """Create a complete .teaparty config tree for testing."""
    repo_root = tempfile.mkdtemp()
    teaparty_home = os.path.join(repo_root, '.teaparty')
    sessions_dir = os.path.join(teaparty_home, 'management', 'sessions')
    agents_dir = os.path.join(teaparty_home, 'management', 'agents')
    os.makedirs(sessions_dir)

    _write_agent(agents_dir, 'leaf-agent', """---
name: leaf-agent
description: A simple agent that responds to messages.
model: sonnet
---
You are a test agent. When you receive a message, respond with a single
short sentence acknowledging the message. Do not use any tools. Just respond
with text.
""")

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

    _write_agent(agents_dir, 'slow-agent', """---
name: slow-agent
description: A slow agent for testing timeouts.
model: haiku
---
You are a test agent. Respond with "Slow agent done." Do not use any tools.
""")

    # Workgroup: dispatcher-agent leads, leaf-agent is member
    wg_dir = os.path.join(teaparty_home, 'management', 'workgroups')
    os.makedirs(wg_dir)
    with open(os.path.join(wg_dir, 'dispatch-team.yaml'), 'w') as f:
        f.write('name: dispatch-team\nlead: dispatcher-agent\n'
                'members:\n  agents:\n    - leaf-agent\n')

    # Management team config — workgroup registered and active
    with open(os.path.join(teaparty_home, 'management', 'teaparty.yaml'), 'w') as f:
        f.write('name: test\nlead: test-parent\n'
                'workgroups:\n'
                '  - name: dispatch-team\n'
                '    config: workgroups/dispatch-team.yaml\n'
                'members:\n  workgroups:\n    - dispatch-team\n')

    # Parent dispatch session
    from teaparty.runners.launcher import create_session
    create_session(agent_name='test-parent', scope='management',
                   teaparty_home=teaparty_home, session_id='test-parent-main')

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
    """Start one bridge for all integration tests."""
    global _module_env, _module_loop, _module_runner

    if not HAVE_CLAUDE:
        return

    _module_env = _make_test_environment()
    teaparty_home, repo_root, static_dir = _module_env

    os.environ['TEAPARTY_BRIDGE_PORT'] = str(BRIDGE_PORT)

    _module_loop = asyncio.new_event_loop()

    from aiohttp import web
    from teaparty.bridge.server import TeaPartyBridge

    bridge = TeaPartyBridge(
        teaparty_home=teaparty_home,
        static_dir=static_dir,
    )
    app = bridge._build_app()
    _module_runner = web.AppRunner(app)

    async def start():
        await _module_runner.setup()
        site = web.TCPSite(_module_runner, 'localhost', BRIDGE_PORT)
        await site.start()

    _module_loop.run_until_complete(start())


def tearDownModule():
    """Stop the bridge, clean up."""
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


def _run(coro, timeout=120):
    """Run a coroutine on the module's event loop."""
    return _module_loop.run_until_complete(
        asyncio.wait_for(coro, timeout=timeout))


def _make_session():
    """Create an AgentSession connected to the shared bridge."""
    from teaparty.teams.session import AgentSession
    from teaparty.messaging.conversations import ConversationType

    return AgentSession(
        _module_env[0],  # teaparty_home
        agent_name='test-parent',
        scope='management',
        qualifier='main',
        conversation_type=ConversationType.OFFICE_MANAGER,
        dispatches=True,
    )


@unittest.skipUnless(HAVE_CLAUDE, 'Requires claude binary')
class TestParallelLeafDispatch(unittest.TestCase):
    """Test case 2: A → B, C (parallel leaf dispatch)."""

    def test_two_leaf_agents_respond_and_parent_resumes(self):
        session = _make_session()

        async def run():
            await session._ensure_bus_listener(_module_env[1])
            from teaparty.mcp.registry import get_spawn_fn
            spawn_fn = get_spawn_fn('test-parent')
            self.assertIsNotNone(spawn_fn)

            t0 = time.monotonic()
            sid_b, _, _ = await spawn_fn(
                'leaf-agent', 'Hello, please respond.', 'ctx-b')
            sid_c, _, _ = await spawn_fn(
                'leaf-agent', 'Another message, please respond.', 'ctx-c')
            dispatch_time = time.monotonic() - t0

            self.assertTrue(len(sid_b) > 0)
            self.assertTrue(len(sid_c) > 0)
            self.assertNotEqual(sid_b, sid_c)
            self.assertLess(dispatch_time, 2.0, 'Both dispatches should be async')

            # Wait for BOTH child responses to arrive in the parent's
            # conversation (written by the resume mechanism).
            parent_conv = session.conversation_id
            for _ in range(90):
                await asyncio.sleep(1.0)
                parent_msgs = session._bus.receive(parent_conv)
                replies = [m for m in parent_msgs if m.sender == 'leaf-agent']
                if len(replies) >= 2:
                    break

            # Child dispatch conversations should have responses
            msgs_b = session._bus.receive(f'dispatch:{sid_b}')
            msgs_c = session._bus.receive(f'dispatch:{sid_c}')

            self.assertTrue(any(m.sender == 'leaf-agent' for m in msgs_b),
                            f'B missing response: {[(m.sender, m.content[:50]) for m in msgs_b]}')
            self.assertTrue(any(m.sender == 'leaf-agent' for m in msgs_c),
                            f'C missing response: {[(m.sender, m.content[:50]) for m in msgs_c]}')

            # Parent's conversation should have the replies
            parent_msgs = session._bus.receive(parent_conv)
            replies = [m for m in parent_msgs if m.sender == 'leaf-agent']
            self.assertGreaterEqual(len(replies), 2,
                                    f'Parent should have 2 replies. Got: '
                                    f'{[(m.sender, m.content[:50]) for m in parent_msgs]}')

            print('\n--- Parent conversation (full exchange) ---')
            for m in parent_msgs:
                print(f'  [{m.sender}] {m.content[:100]}')
            print('\n--- B dispatch conversation ---')
            for m in msgs_b:
                print(f'  [{m.sender}] {m.content[:80]}')
            print('\n--- C dispatch conversation ---')
            for m in msgs_c:
                print(f'  [{m.sender}] {m.content[:80]}')

            # Clean up
            from teaparty.workspace.close_conversation import close_conversation
            close_conversation(session._dispatch_session, f'dispatch:{sid_b}',
                               teaparty_home=_module_env[0], scope='management')
            close_conversation(session._dispatch_session, f'dispatch:{sid_c}',
                               teaparty_home=_module_env[0], scope='management')

        _run(run())


@unittest.skipUnless(HAVE_CLAUDE, 'Requires claude binary')
class TestSlotLimitAndReuse(unittest.TestCase):
    """Test case 3: A → B, C, D (fills slots), close one, send E."""

    def test_fourth_rejected_then_close_and_retry(self):
        session = _make_session()

        async def run():
            await session._ensure_bus_listener(_module_env[1])
            from teaparty.mcp.registry import get_spawn_fn
            from teaparty.workspace.close_conversation import close_conversation
            spawn_fn = get_spawn_fn('test-parent')

            sids = []
            for i in range(3):
                sid, _, _ = await spawn_fn(
                    'leaf-agent', f'Message {i}', f'ctx-{i}')
                self.assertTrue(len(sid) > 0, f'Dispatch {i} should succeed')
                sids.append(sid)

            # 4th should fail
            sid_4, _, _ = await spawn_fn('leaf-agent', 'Message 3', 'ctx-3')
            self.assertEqual(sid_4, '', '4th dispatch should be rejected')
            print(f'\n4th dispatch correctly rejected (3 slots full)')

            # Wait for first to finish
            for _ in range(60):
                await asyncio.sleep(1.0)
                msgs = session._bus.receive(f'dispatch:{sids[0]}')
                if any(m.sender == 'leaf-agent' for m in msgs):
                    break

            # Close it
            close_conversation(session._dispatch_session, f'dispatch:{sids[0]}',
                               teaparty_home=_module_env[0], scope='management')

            # Now should succeed
            sid_e, _, _ = await spawn_fn('leaf-agent', 'Message E', 'ctx-e')
            self.assertTrue(len(sid_e) > 0, 'E should succeed after close')
            print(f'Dispatch E succeeded after close: {sid_e}')

            # Clean up remaining slots
            for sid in sids[1:] + [sid_e]:
                close_conversation(session._dispatch_session, f'dispatch:{sid}',
                                   teaparty_home=_module_env[0], scope='management')

        _run(run())


@unittest.skipUnless(HAVE_CLAUDE, 'Requires claude binary')
class TestParallelInstanceSameAgent(unittest.TestCase):
    """Test case 4: A → B, B (two instances of same agent)."""

    def test_two_instances_respond_separately(self):
        session = _make_session()

        async def run():
            await session._ensure_bus_listener(_module_env[1])
            from teaparty.mcp.registry import get_spawn_fn
            from teaparty.workspace.close_conversation import close_conversation
            spawn_fn = get_spawn_fn('test-parent')

            sid_1, _, _ = await spawn_fn(
                'leaf-agent', 'First instance message', 'ctx-inst-1')
            sid_2, _, _ = await spawn_fn(
                'leaf-agent', 'Second instance message', 'ctx-inst-2')

            self.assertNotEqual(sid_1, sid_2)

            for _ in range(60):
                await asyncio.sleep(1.0)
                m1 = session._bus.receive(f'dispatch:{sid_1}')
                m2 = session._bus.receive(f'dispatch:{sid_2}')
                if (any(m.sender == 'leaf-agent' for m in m1) and
                        any(m.sender == 'leaf-agent' for m in m2)):
                    break

            msgs_1 = session._bus.receive(f'dispatch:{sid_1}')
            msgs_2 = session._bus.receive(f'dispatch:{sid_2}')

            self.assertTrue(any(m.sender == 'leaf-agent' for m in msgs_1))
            self.assertTrue(any(m.sender == 'leaf-agent' for m in msgs_2))

            print('\n--- Instance 1 ---')
            for m in msgs_1:
                print(f'  [{m.sender}] {m.content[:80]}')
            print('\n--- Instance 2 ---')
            for m in msgs_2:
                print(f'  [{m.sender}] {m.content[:80]}')

            close_conversation(session._dispatch_session, f'dispatch:{sid_1}',
                               teaparty_home=_module_env[0], scope='management')
            close_conversation(session._dispatch_session, f'dispatch:{sid_2}',
                               teaparty_home=_module_env[0], scope='management')

        _run(run())


@unittest.skipUnless(HAVE_CLAUDE, 'Requires claude binary')
class TestLinearDispatch(unittest.TestCase):
    """Test case 1: A → B → C (linear dispatch with real MCP)."""

    def test_linear_chain_with_real_mcp(self):
        session = _make_session()

        async def run():
            await session._ensure_bus_listener(_module_env[1])
            from teaparty.mcp.registry import get_spawn_fn
            from teaparty.workspace.close_conversation import close_conversation
            spawn_fn = get_spawn_fn('test-parent')
            self.assertIsNotNone(spawn_fn)

            b_sid, _, _ = await spawn_fn(
                'dispatcher-agent',
                'Please dispatch this to leaf-agent: "What is 2+2?"',
                'a-to-b')
            self.assertTrue(len(b_sid) > 0)

            b_responded = False
            for _ in range(90):
                await asyncio.sleep(1.0)
                msgs_b = session._bus.receive(f'dispatch:{b_sid}')
                if any(m.sender == 'dispatcher-agent' for m in msgs_b):
                    b_responded = True
                    break

            self.assertTrue(b_responded, 'dispatcher-agent should respond')

            msgs_b = session._bus.receive(f'dispatch:{b_sid}')
            print('\n--- B (dispatcher-agent) conversation ---')
            for m in msgs_b:
                print(f'  [{m.sender}] {m.content[:100]}')

            b_text = ' '.join(m.content for m in msgs_b
                              if m.sender == 'dispatcher-agent')
            self.assertTrue(
                any(kw in b_text.lower() for kw in
                    ['dispatch', 'handle', 'leaf-agent', 'message_sent', 'sent']),
                f'B should mention dispatch. Got: {b_text[:200]}')

            close_conversation(session._dispatch_session, f'dispatch:{b_sid}',
                               teaparty_home=_module_env[0], scope='management')

        _run(run(), timeout=120)


if __name__ == '__main__':
    unittest.main()
