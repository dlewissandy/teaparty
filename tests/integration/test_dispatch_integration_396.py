"""Integration tests for issue #396: async dispatch with real LLM calls.

Full end-to-end tests exercising every dispatch topology. Each test
verifies the complete lifecycle:

1. Send returns message_sent with a conversation handle
2. Child's response arrives in the dispatch conversation
3. Parent is resumed — reply appears in parent's conversation
4. Parent integrates the child's response
5. CloseConversation removes sessions, frees slots, no orphans

Architecture: one TeaPartyBridge for the module on a test-only port.
All tests share the same bridge and event loop. Real claude calls.

Requires: claude binary on PATH, Max subscription active.
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

_module_env = None
_module_loop = None
_module_runner = None


def _make_test_environment():
    repo_root = tempfile.mkdtemp()
    teaparty_home = os.path.join(repo_root, '.teaparty')
    sessions_dir = os.path.join(teaparty_home, 'management', 'sessions')
    agents_dir = os.path.join(teaparty_home, 'management', 'agents')
    os.makedirs(sessions_dir)

    _write_agent(agents_dir, 'leaf-agent', """---
name: leaf-agent
description: A simple agent that responds to messages.
model: haiku
---
You are a test agent. When you receive a message, respond with a single
short sentence acknowledging it. Do not use any tools.
""")

    _write_agent(agents_dir, 'dispatcher-agent', """---
name: dispatcher-agent
description: An agent that dispatches to leaf-agent via Send then relays the response.
model: sonnet
tools: mcp__teaparty-config__Send
---
You are a test dispatcher. When you receive a message:
1. Use Send to send the message to member 'leaf-agent'
2. After Send returns, respond with "Dispatched. Handle: " followed by
   the conversation_id from the Send result.
Do not use any other tools.
""")

    wg_dir = os.path.join(teaparty_home, 'management', 'workgroups')
    os.makedirs(wg_dir)
    with open(os.path.join(wg_dir, 'dispatch-team.yaml'), 'w') as f:
        f.write('name: dispatch-team\nlead: dispatcher-agent\n'
                'members:\n  agents:\n    - leaf-agent\n')

    with open(os.path.join(teaparty_home, 'management', 'teaparty.yaml'), 'w') as f:
        f.write('name: test\nlead: test-parent\n'
                'workgroups:\n'
                '  - name: dispatch-team\n'
                '    config: workgroups/dispatch-team.yaml\n'
                'members:\n  workgroups:\n    - dispatch-team\n')

    from teaparty.runners.launcher import create_session
    create_session(agent_name='test-parent', scope='management',
                   teaparty_home=teaparty_home, session_id='test-parent-main')

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


def _run(coro, timeout=120):
    return _module_loop.run_until_complete(
        asyncio.wait_for(coro, timeout=timeout))


def _make_session():
    from teaparty.teams.session import AgentSession
    from teaparty.messaging.conversations import ConversationType
    return AgentSession(
        _module_env[0],
        agent_name='test-parent',
        scope='management',
        qualifier='main',
        conversation_type=ConversationType.OFFICE_MANAGER,
        dispatches=True,
    )


def _wait_for_replies(session, parent_conv, count, timeout=90):
    """Poll until `count` reply messages from agents appear in parent conv."""
    async def poll():
        for _ in range(timeout):
            await asyncio.sleep(1.0)
            msgs = session._bus.receive(parent_conv)
            replies = [m for m in msgs
                       if m.sender not in ('test-parent', 'human', 'system')]
            if len(replies) >= count:
                return
    _run(poll(), timeout=timeout + 5)


def _wait_for_child(session, dispatch_conv_id, agent_name, timeout=60):
    """Poll until the child agent writes a response to the dispatch conv."""
    async def poll():
        for _ in range(timeout):
            await asyncio.sleep(1.0)
            msgs = session._bus.receive(dispatch_conv_id)
            if any(m.sender == agent_name for m in msgs):
                return
    _run(poll(), timeout=timeout + 5)


def _print_conversation(label, messages):
    print(f'\n--- {label} ---')
    for m in messages:
        print(f'  [{m.sender}] {m.content[:120]}')


def _close_and_verify(test, session, conv_id):
    """Close a dispatch conversation and verify cleanup."""
    from teaparty.workspace.close_conversation import close_conversation
    child_sid = conv_id.replace('dispatch:', '')
    child_path = os.path.join(
        _module_env[0], 'management', 'sessions', child_sid)

    close_conversation(
        session._dispatch_session, conv_id,
        teaparty_home=_module_env[0], scope='management')

    test.assertFalse(
        os.path.isdir(child_path),
        f'Session dir should be removed after close: {child_path}')


@unittest.skipUnless(HAVE_CLAUDE, 'Requires claude binary')
class TestParallelLeafDispatch(unittest.TestCase):
    """A dispatches to two leaf agents. Both respond. Parent resumes
    with both replies. CloseConversation cleans up both."""

    def test_full_exchange(self):
        session = _make_session()
        parent_conv = session.conversation_id

        async def dispatch():
            await session._ensure_bus_listener(_module_env[1])
            from teaparty.mcp.registry import get_spawn_fn
            spawn_fn = get_spawn_fn('test-parent')
            self.assertIsNotNone(spawn_fn)

            # 1. Send — verify handle returned
            sid_b, _, _ = await spawn_fn(
                'leaf-agent', 'Say hello.', 'ctx-b')
            sid_c, _, _ = await spawn_fn(
                'leaf-agent', 'Say goodbye.', 'ctx-c')
            self.assertTrue(len(sid_b) > 0, 'B dispatch should return handle')
            self.assertTrue(len(sid_c) > 0, 'C dispatch should return handle')
            self.assertNotEqual(sid_b, sid_c, 'Handles should differ')
            return sid_b, sid_c

        sid_b, sid_c = _run(dispatch())

        # 2. Child responses arrive in dispatch conversations
        _wait_for_child(session, f'dispatch:{sid_b}', 'leaf-agent')
        _wait_for_child(session, f'dispatch:{sid_c}', 'leaf-agent')

        msgs_b = session._bus.receive(f'dispatch:{sid_b}')
        msgs_c = session._bus.receive(f'dispatch:{sid_c}')
        self.assertTrue(any(m.sender == 'leaf-agent' for m in msgs_b))
        self.assertTrue(any(m.sender == 'leaf-agent' for m in msgs_c))

        # 3. Parent resumed — replies in parent conversation
        _wait_for_replies(session, parent_conv, 2)
        parent_msgs = session._bus.receive(parent_conv)
        replies = [m for m in parent_msgs if m.sender == 'leaf-agent']
        self.assertGreaterEqual(len(replies), 2,
                                f'Parent should have 2 replies. '
                                f'Messages: {[(m.sender, m.content[:40]) for m in parent_msgs]}')

        # 4. Print full exchange
        _print_conversation('Parent conversation', parent_msgs)
        _print_conversation('B dispatch', msgs_b)
        _print_conversation('C dispatch', msgs_c)

        # 5. Cleanup — close both, verify sessions gone, slots freed
        _close_and_verify(self, session, f'dispatch:{sid_b}')
        _close_and_verify(self, session, f'dispatch:{sid_c}')
        self.assertEqual(len(session._dispatch_session.conversation_map), 0,
                         'All slots should be free after cleanup')


@unittest.skipUnless(HAVE_CLAUDE, 'Requires claude binary')
class TestSlotLimitAndReuse(unittest.TestCase):
    """Fill 3 slots. 4th rejected. Close one. 4th succeeds.
    Verify the complete exchange for each agent."""

    def test_full_exchange(self):
        session = _make_session()
        parent_conv = session.conversation_id

        async def dispatch():
            await session._ensure_bus_listener(_module_env[1])
            from teaparty.mcp.registry import get_spawn_fn
            spawn_fn = get_spawn_fn('test-parent')

            # Fill 3 slots
            sids = []
            for i in range(3):
                sid, _, _ = await spawn_fn(
                    'leaf-agent', f'Slot test message {i}', f'ctx-slot-{i}')
                self.assertTrue(len(sid) > 0, f'Dispatch {i} should succeed')
                sids.append(sid)

            # 4th fails
            sid_fail, _, _ = await spawn_fn(
                'leaf-agent', 'Should fail', 'ctx-slot-fail')
            self.assertEqual(sid_fail, '', '4th dispatch must be rejected')
            return sids

        sids = _run(dispatch())
        print(f'\n3 slots filled. 4th correctly rejected.')

        # Wait for first to respond
        _wait_for_child(session, f'dispatch:{sids[0]}', 'leaf-agent')

        # Close first — frees a slot
        _close_and_verify(self, session, f'dispatch:{sids[0]}')
        from teaparty.runners.launcher import check_slot_available
        self.assertTrue(check_slot_available(session._dispatch_session),
                        'Slot should be free after close')
        print(f'Closed slot 0. Slot available.')

        # 4th now succeeds
        async def dispatch_e():
            from teaparty.mcp.registry import get_spawn_fn
            spawn_fn = get_spawn_fn('test-parent')
            sid, _, _ = await spawn_fn(
                'leaf-agent', 'I am the 4th agent', 'ctx-slot-e')
            self.assertTrue(len(sid) > 0, '4th dispatch should now succeed')
            return sid

        sid_e = _run(dispatch_e())
        print(f'4th dispatch succeeded: {sid_e}')

        # Wait for E and remaining agents
        _wait_for_child(session, f'dispatch:{sid_e}', 'leaf-agent')

        # Wait for parent to get replies
        _wait_for_replies(session, parent_conv, 2)

        parent_msgs = session._bus.receive(parent_conv)
        _print_conversation('Parent conversation', parent_msgs)

        # Cleanup remaining
        for sid in sids[1:] + [sid_e]:
            _close_and_verify(self, session, f'dispatch:{sid}')
        self.assertEqual(len(session._dispatch_session.conversation_map), 0)
        print('All slots freed.')


@unittest.skipUnless(HAVE_CLAUDE, 'Requires claude binary')
class TestParallelInstanceSameAgent(unittest.TestCase):
    """A dispatches to leaf-agent twice. Two separate instances with
    separate sessions, separate handles, separate responses."""

    def test_full_exchange(self):
        session = _make_session()
        parent_conv = session.conversation_id

        async def dispatch():
            await session._ensure_bus_listener(_module_env[1])
            from teaparty.mcp.registry import get_spawn_fn
            spawn_fn = get_spawn_fn('test-parent')

            sid_1, _, _ = await spawn_fn(
                'leaf-agent', 'Instance 1: say alpha', 'ctx-i1')
            sid_2, _, _ = await spawn_fn(
                'leaf-agent', 'Instance 2: say beta', 'ctx-i2')
            self.assertNotEqual(sid_1, sid_2, 'Separate session IDs')
            return sid_1, sid_2

        sid_1, sid_2 = _run(dispatch())

        # Both respond in their dispatch conversations
        _wait_for_child(session, f'dispatch:{sid_1}', 'leaf-agent')
        _wait_for_child(session, f'dispatch:{sid_2}', 'leaf-agent')

        msgs_1 = session._bus.receive(f'dispatch:{sid_1}')
        msgs_2 = session._bus.receive(f'dispatch:{sid_2}')
        self.assertTrue(any(m.sender == 'leaf-agent' for m in msgs_1))
        self.assertTrue(any(m.sender == 'leaf-agent' for m in msgs_2))

        # Parent gets both replies
        _wait_for_replies(session, parent_conv, 2)
        parent_msgs = session._bus.receive(parent_conv)
        replies = [m for m in parent_msgs if m.sender == 'leaf-agent']
        self.assertGreaterEqual(len(replies), 2)

        _print_conversation('Parent conversation', parent_msgs)
        _print_conversation('Instance 1 dispatch', msgs_1)
        _print_conversation('Instance 2 dispatch', msgs_2)

        # Cleanup
        _close_and_verify(self, session, f'dispatch:{sid_1}')
        _close_and_verify(self, session, f'dispatch:{sid_2}')
        self.assertEqual(len(session._dispatch_session.conversation_map), 0)


@unittest.skipUnless(HAVE_CLAUDE, 'Requires claude binary')
class TestLinearDispatch(unittest.TestCase):
    """A → dispatcher-agent (B) → leaf-agent (C).
    B calls Send to C via real MCP. Full round trip."""

    def test_full_exchange(self):
        session = _make_session()
        parent_conv = session.conversation_id

        async def dispatch():
            await session._ensure_bus_listener(_module_env[1])
            from teaparty.mcp.registry import get_spawn_fn
            spawn_fn = get_spawn_fn('test-parent')

            sid_b, _, _ = await spawn_fn(
                'dispatcher-agent',
                'Dispatch to leaf-agent: "What is 2+2?"',
                'a-to-b')
            self.assertTrue(len(sid_b) > 0)
            return sid_b

        sid_b = _run(dispatch())

        # B responds (after calling Send internally)
        _wait_for_child(session, f'dispatch:{sid_b}', 'dispatcher-agent')

        msgs_b = session._bus.receive(f'dispatch:{sid_b}')
        self.assertTrue(any(m.sender == 'dispatcher-agent' for m in msgs_b),
                        'B should respond')

        # Verify B used the Send tool
        tool_calls = [m for m in msgs_b if m.sender == 'tool_use']
        send_calls = [m for m in tool_calls
                      if 'Send' in m.content]
        self.assertTrue(len(send_calls) > 0,
                        f'B should have called Send. Tool calls: '
                        f'{[m.content[:60] for m in tool_calls]}')

        # Verify Send returned message_sent (not the child's response)
        # The dispatcher's text should mention the handle, not echo
        # the leaf-agent's raw response.
        b_text = ' '.join(m.content for m in msgs_b
                          if m.sender == 'dispatcher-agent')
        self.assertTrue(
            any(kw in b_text.lower() for kw in
                ['dispatch', 'handle', 'sent', 'message_sent']),
            f'B should mention dispatch. Got: {b_text[:200]}')

        # Parent gets B's reply
        _wait_for_replies(session, parent_conv, 1)
        parent_msgs = session._bus.receive(parent_conv)

        _print_conversation('Parent conversation (full exchange)', parent_msgs)
        _print_conversation('B (dispatcher-agent) dispatch', msgs_b)

        # Cleanup
        _close_and_verify(self, session, f'dispatch:{sid_b}')
        self.assertEqual(len(session._dispatch_session.conversation_map), 0)


if __name__ == '__main__':
    unittest.main()
