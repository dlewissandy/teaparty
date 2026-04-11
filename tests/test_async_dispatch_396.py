"""Specification tests for issue #396: async dispatch, conversation handles, recursive close.

These tests exercise the real dispatch machinery with a mocked launcher.
The mock replaces only the claude -p subprocess — everything else is real:
session creation, conversation_map management, bus writes, background tasks,
and recursive close.
"""
import asyncio
import json
import os
import shutil
import tempfile
import unittest
from dataclasses import dataclass, field
from unittest.mock import patch, AsyncMock

from teaparty.messaging.conversations import SqliteMessageBus, agent_bus_path
from teaparty.runners.launcher import (
    Session,
    create_session,
    record_child_session,
    remove_child_session,
    check_slot_available,
    MAX_CONVERSATIONS_PER_AGENT,
    _save_session_metadata,
)
from teaparty.workspace.close_conversation import close_conversation


def _make_teaparty_home():
    """Create a temp .teaparty with management/sessions/ and agent bus dir."""
    tmpdir = tempfile.mkdtemp()
    os.makedirs(os.path.join(tmpdir, 'management', 'sessions'))
    os.makedirs(os.path.join(tmpdir, 'management', 'agents', 'office-manager'))
    return tmpdir


@dataclass
class FakeLaunchResult:
    """Mimics ClaudeResult from the real launcher."""
    exit_code: int = 0
    session_id: str = 'fake-claude-session'
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 100


class TestCloseConversation(unittest.TestCase):
    """CloseConversation recursively tears down children and frees slots.

    These tests create real session directories on disk, populate
    conversation_maps, and verify that close_conversation removes
    the correct directories and frees the correct slots.
    """

    def setUp(self):
        self._tmpdir = _make_teaparty_home()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _create(self, name, conversation_map=None):
        """Create a session with optional pre-populated conversation_map."""
        s = create_session(agent_name=name, scope='management',
                           teaparty_home=self._tmpdir)
        if conversation_map:
            s.conversation_map = conversation_map
            _save_session_metadata(s)
        return s

    def test_close_frees_slot_and_removes_directory(self):
        """Close after completion: slot freed, session directory removed."""
        parent = self._create('parent')
        child = self._create('child')
        record_child_session(parent, request_id='r1',
                             child_session_id=child.id)

        # Verify preconditions
        self.assertEqual(len(parent.conversation_map), 1)
        self.assertTrue(os.path.isdir(child.path))

        close_conversation(parent, f'dispatch:{child.id}',
                           teaparty_home=self._tmpdir, scope='management')

        # Slot freed
        self.assertEqual(len(parent.conversation_map), 0)
        # Directory gone
        self.assertFalse(os.path.isdir(child.path))
        # conversation_map persisted to disk
        with open(os.path.join(parent.path, 'metadata.json')) as f:
            meta = json.load(f)
        self.assertEqual(meta['conversation_map'], {})

    def test_recursive_close_A_B_C(self):
        """A → B → C. Closing B removes both B and C."""
        a = self._create('a')
        b = self._create('b')
        c = self._create('c')

        record_child_session(a, request_id='a-to-b', child_session_id=b.id)
        # B's conversation_map must be on disk for recursive walk
        record_child_session(b, request_id='b-to-c', child_session_id=c.id)

        # All three exist
        self.assertTrue(os.path.isdir(a.path))
        self.assertTrue(os.path.isdir(b.path))
        self.assertTrue(os.path.isdir(c.path))

        close_conversation(a, f'dispatch:{b.id}',
                           teaparty_home=self._tmpdir, scope='management')

        # A still exists, B and C are gone
        self.assertTrue(os.path.isdir(a.path))
        self.assertFalse(os.path.isdir(b.path))
        self.assertFalse(os.path.isdir(c.path))
        # A's slot freed
        self.assertEqual(len(a.conversation_map), 0)

    def test_recursive_close_deep_chain(self):
        """A → B → C → D. Closing B removes B, C, and D."""
        a = self._create('a')
        b = self._create('b')
        c = self._create('c')
        d = self._create('d')

        record_child_session(a, request_id='a-b', child_session_id=b.id)
        record_child_session(b, request_id='b-c', child_session_id=c.id)
        record_child_session(c, request_id='c-d', child_session_id=d.id)

        close_conversation(a, f'dispatch:{b.id}',
                           teaparty_home=self._tmpdir, scope='management')

        self.assertTrue(os.path.isdir(a.path))
        self.assertFalse(os.path.isdir(b.path))
        self.assertFalse(os.path.isdir(c.path))
        self.assertFalse(os.path.isdir(d.path))

    def test_close_one_of_parallel_children(self):
        """A → B, C. Close B only. C remains, A has one slot freed."""
        a = self._create('a')
        b = self._create('b')
        c = self._create('c')

        record_child_session(a, request_id='a-b', child_session_id=b.id)
        record_child_session(a, request_id='a-c', child_session_id=c.id)
        self.assertEqual(len(a.conversation_map), 2)

        close_conversation(a, f'dispatch:{b.id}',
                           teaparty_home=self._tmpdir, scope='management')

        # B gone, C remains
        self.assertFalse(os.path.isdir(b.path))
        self.assertTrue(os.path.isdir(c.path))
        # One slot freed, one still occupied
        self.assertEqual(len(a.conversation_map), 1)
        self.assertIn('a-c', a.conversation_map)

    def test_diamond_close(self):
        """A → (B → D1), (C → D2). Close B removes B and D1, C and D2 remain."""
        a = self._create('a')
        b = self._create('b')
        c = self._create('c')
        d1 = self._create('d')
        d2 = self._create('d')

        record_child_session(a, request_id='a-b', child_session_id=b.id)
        record_child_session(a, request_id='a-c', child_session_id=c.id)
        record_child_session(b, request_id='b-d', child_session_id=d1.id)
        record_child_session(c, request_id='c-d', child_session_id=d2.id)

        close_conversation(a, f'dispatch:{b.id}',
                           teaparty_home=self._tmpdir, scope='management')

        # B and D1 gone
        self.assertFalse(os.path.isdir(b.path))
        self.assertFalse(os.path.isdir(d1.path))
        # C and D2 remain
        self.assertTrue(os.path.isdir(c.path))
        self.assertTrue(os.path.isdir(d2.path))
        # A's slot for B freed, slot for C remains
        self.assertEqual(len(a.conversation_map), 1)
        self.assertIn('a-c', a.conversation_map)

    def test_rate_limit_close_and_reuse(self):
        """Fill 3 slots, close one, verify can dispatch again."""
        a = self._create('a')
        children = []
        for i in range(3):
            child = self._create(f'child-{i}')
            record_child_session(a, request_id=f'r-{i}',
                                 child_session_id=child.id)
            children.append(child)

        self.assertFalse(check_slot_available(a))

        # Close child-0
        close_conversation(a, f'dispatch:{children[0].id}',
                           teaparty_home=self._tmpdir, scope='management')

        self.assertTrue(check_slot_available(a))

        # Can dispatch again
        e = self._create('e')
        record_child_session(a, request_id='r-e', child_session_id=e.id)
        self.assertFalse(check_slot_available(a))  # Full again

    def test_parallel_instance_same_agent(self):
        """A dispatches to B twice. Separate sessions, separate handles."""
        a = self._create('a')
        b1 = self._create('b')
        b2 = self._create('b')

        self.assertNotEqual(b1.id, b2.id)
        self.assertNotEqual(b1.path, b2.path)

        record_child_session(a, request_id='r-b1', child_session_id=b1.id)
        record_child_session(a, request_id='r-b2', child_session_id=b2.id)

        # Close first instance — second remains
        close_conversation(a, f'dispatch:{b1.id}',
                           teaparty_home=self._tmpdir, scope='management')

        self.assertFalse(os.path.isdir(b1.path))
        self.assertTrue(os.path.isdir(b2.path))
        self.assertEqual(len(a.conversation_map), 1)


class TestAsyncSpawnFn(unittest.TestCase):
    """Test the actual spawn_fn with a mocked launcher.

    These tests exercise the real spawn_fn closure from AgentSession,
    mocking only the claude -p subprocess. Everything else is real:
    session creation, worktree creation (as directories, not git),
    conversation_map management, bus writes, background task lifecycle.
    """

    def setUp(self):
        self._tmpdir = _make_teaparty_home()
        # Create a minimal .teaparty config structure
        agents_dir = os.path.join(self._tmpdir, 'management', 'agents')
        for name in ['parent', 'child-a', 'child-b', 'child-c']:
            agent_dir = os.path.join(agents_dir, name)
            os.makedirs(agent_dir, exist_ok=True)
            with open(os.path.join(agent_dir, 'agent.md'), 'w') as f:
                f.write(f'---\nname: {name}\ndescription: test agent\n---\n')
        # Create the parent's named dispatch session so _ensure_bus_listener
        # can load it (stable_id = 'parent-test')
        create_session(agent_name='parent', scope='management',
                       teaparty_home=self._tmpdir, session_id='parent-test')

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _make_fake_launch(self, response_text='Hello from child',
                          delay=0.1):
        """Create a mock _launch that simulates agent execution.

        Fires on_stream_event with a text response, waits `delay` seconds,
        returns a FakeLaunchResult.
        """
        async def fake_launch(**kwargs):
            on_event = kwargs.get('on_stream_event')
            agent_name = kwargs.get('agent_name', 'child')
            if on_event:
                # Simulate agent producing a text response
                on_event({
                    'type': 'assistant',
                    'message': {'content': [
                        {'type': 'text', 'text': response_text},
                    ]},
                })
            await asyncio.sleep(delay)
            return FakeLaunchResult(session_id=f'claude-{agent_name}')
        return fake_launch

    def _run(self, coro):
        """Run an async coroutine in a new event loop."""
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            # Let pending tasks complete
            pending = asyncio.all_tasks(loop)
            if pending:
                loop.run_until_complete(asyncio.gather(*pending,
                                                       return_exceptions=True))
            loop.close()

    @patch('teaparty.teams.session.os.path.dirname',
           side_effect=os.path.dirname)
    def test_spawn_returns_immediately(self, _):
        """spawn_fn returns a session_id and empty result_text without
        waiting for the child to complete."""
        import time

        from teaparty.teams.session import AgentSession
        from teaparty.messaging.conversations import ConversationType

        session = AgentSession(
            self._tmpdir,
            agent_name='parent',
            scope='management',
            qualifier='test',
            conversation_type=ConversationType.OFFICE_MANAGER,
            dispatches=True,
        )

        fake_launch = self._make_fake_launch(delay=2.0)  # 2 seconds

        async def run():
            with patch('teaparty.runners.launcher.launch', fake_launch), \
                 patch('teaparty.config.roster.has_sub_roster', return_value=False), \
                 patch('subprocess.run'):  # skip git worktree add
                env = await session._ensure_bus_listener(self._tmpdir)

                # Get the registered spawn_fn
                from teaparty.mcp.registry import get_spawn_fn
                spawn_fn = get_spawn_fn('parent')
                self.assertIsNotNone(spawn_fn)

                t0 = time.monotonic()
                session_id, worktree, result_text = await spawn_fn(
                    'child-a', '## Task\nDo something', 'ctx-1')
                elapsed = time.monotonic() - t0

                # Returns immediately — much less than the 2s delay
                self.assertLess(elapsed, 1.0)
                # Has a session_id (the handle)
                self.assertTrue(len(session_id) > 0)
                # result_text is empty (response comes via bus, not here)
                self.assertEqual(result_text, '')

        self._run(run())

    def test_child_response_arrives_in_bus(self):
        """After spawn_fn returns, the child's response is written to the
        parent's bus under the dispatch conversation_id."""
        from teaparty.teams.session import AgentSession
        from teaparty.messaging.conversations import ConversationType

        session = AgentSession(
            self._tmpdir,
            agent_name='parent',
            scope='management',
            qualifier='test',
            conversation_type=ConversationType.OFFICE_MANAGER,
            dispatches=True,
        )

        fake_launch = self._make_fake_launch(
            response_text='The answer is 42', delay=0.1)

        async def run():
            with patch('teaparty.runners.launcher.launch', fake_launch), \
                 patch('teaparty.config.roster.has_sub_roster', return_value=False), \
                 patch('subprocess.run'):
                await session._ensure_bus_listener(self._tmpdir)
                from teaparty.mcp.registry import get_spawn_fn
                spawn_fn = get_spawn_fn('parent')

                child_sid, _, _ = await spawn_fn(
                    'child-a', '## Task\nWhat is the answer?', 'ctx-2')

                # Wait for background task to complete
                await asyncio.sleep(0.3)

                # Check the bus for the child's response
                conv_id = f'dispatch:{child_sid}'
                messages = session._bus.receive(conv_id)

                # Should have: parent's request + child's text response
                senders = [m.sender for m in messages]
                contents = [m.content for m in messages]

                self.assertIn('parent', senders)
                self.assertIn('child-a', senders)
                self.assertTrue(
                    any('The answer is 42' in c for c in contents),
                    f'Child response not found in bus. Messages: {list(zip(senders, contents))}')

        self._run(run())

    def test_parallel_dispatch_two_children(self):
        """Two Send calls in quick succession both succeed and both children
        produce responses in the bus."""
        from teaparty.teams.session import AgentSession
        from teaparty.messaging.conversations import ConversationType

        session = AgentSession(
            self._tmpdir,
            agent_name='parent',
            scope='management',
            qualifier='test',
            conversation_type=ConversationType.OFFICE_MANAGER,
            dispatches=True,
        )

        call_count = {'value': 0}
        async def counting_launch(**kwargs):
            call_count['value'] += 1
            agent = kwargs.get('agent_name', 'child')
            on_event = kwargs.get('on_stream_event')
            if on_event:
                on_event({
                    'type': 'assistant',
                    'message': {'content': [
                        {'type': 'text', 'text': f'Response from {agent}'},
                    ]},
                })
            await asyncio.sleep(0.1)
            return FakeLaunchResult(session_id=f'claude-{agent}')

        async def run():
            with patch('teaparty.runners.launcher.launch', counting_launch), \
                 patch('teaparty.config.roster.has_sub_roster', return_value=False), \
                 patch('subprocess.run'):
                await session._ensure_bus_listener(self._tmpdir)
                from teaparty.mcp.registry import get_spawn_fn
                spawn_fn = get_spawn_fn('parent')

                # Dispatch to two children without waiting
                sid_a, _, _ = await spawn_fn('child-a', 'task a', 'ctx-a')
                sid_b, _, _ = await spawn_fn('child-b', 'task b', 'ctx-b')

                self.assertTrue(len(sid_a) > 0)
                self.assertTrue(len(sid_b) > 0)
                self.assertNotEqual(sid_a, sid_b)

                # Wait for both to complete
                await asyncio.sleep(0.3)

                # Both launched
                self.assertEqual(call_count['value'], 2)

                # Both responses in bus
                msgs_a = session._bus.receive(f'dispatch:{sid_a}')
                msgs_b = session._bus.receive(f'dispatch:{sid_b}')

                a_content = ' '.join(m.content for m in msgs_a)
                b_content = ' '.join(m.content for m in msgs_b)

                self.assertIn('Response from child-a', a_content)
                self.assertIn('Response from child-b', b_content)

        self._run(run())

    def test_slot_limit_rejects_fourth(self):
        """After 3 dispatches, the 4th returns empty session_id (rejected)."""
        from teaparty.teams.session import AgentSession
        from teaparty.messaging.conversations import ConversationType

        session = AgentSession(
            self._tmpdir,
            agent_name='parent',
            scope='management',
            qualifier='test',
            conversation_type=ConversationType.OFFICE_MANAGER,
            dispatches=True,
        )

        fake_launch = self._make_fake_launch(delay=5.0)  # Long-running

        async def run():
            with patch('teaparty.runners.launcher.launch', fake_launch), \
                 patch('teaparty.config.roster.has_sub_roster', return_value=False), \
                 patch('subprocess.run'):
                await session._ensure_bus_listener(self._tmpdir)
                from teaparty.mcp.registry import get_spawn_fn
                spawn_fn = get_spawn_fn('parent')

                # Fill 3 slots
                for i in range(3):
                    sid, _, _ = await spawn_fn(f'child-{chr(97+i)}', f'task {i}', f'ctx-{i}')
                    self.assertTrue(len(sid) > 0, f'Dispatch {i} should succeed')

                # 4th should fail
                sid, _, _ = await spawn_fn('child-c', 'task 3', 'ctx-3')
                self.assertEqual(sid, '', '4th dispatch should be rejected')

        self._run(run())


class TestAsyncTopologies(unittest.TestCase):
    """End-to-end async dispatch tests for each topology in the issue.

    These exercise the real spawn_fn with mocked _launch. The mock
    simulates agent behavior: producing text, optionally dispatching
    to sub-agents (by calling spawn_fn again), and completing.

    Each test verifies that responses arrive in the correct bus
    conversation under the correct conversation_id.
    """

    def setUp(self):
        self._tmpdir = _make_teaparty_home()
        agents_dir = os.path.join(self._tmpdir, 'management', 'agents')
        for name in ['parent', 'agent-b', 'agent-c', 'agent-d', 'agent-e']:
            agent_dir = os.path.join(agents_dir, name)
            os.makedirs(agent_dir, exist_ok=True)
            with open(os.path.join(agent_dir, 'agent.md'), 'w') as f:
                f.write(f'---\nname: {name}\ndescription: test\n---\n')
        create_session(agent_name='parent', scope='management',
                       teaparty_home=self._tmpdir, session_id='parent-test')

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _run(self, coro):
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            pending = asyncio.all_tasks(loop)
            if pending:
                loop.run_until_complete(asyncio.gather(*pending,
                                                       return_exceptions=True))
            loop.close()

    def _make_session(self):
        from teaparty.teams.session import AgentSession
        from teaparty.messaging.conversations import ConversationType
        return AgentSession(
            self._tmpdir,
            agent_name='parent',
            scope='management',
            qualifier='test',
            conversation_type=ConversationType.OFFICE_MANAGER,
            dispatches=True,
        )

    def test_linear_A_B_C(self):
        """A dispatches to B. B dispatches to C. C responds. B responds.
        Both responses arrive in the correct bus conversations."""

        async def fake_launch(**kwargs):
            agent = kwargs.get('agent_name', '')
            on_event = kwargs.get('on_stream_event')
            session_id = kwargs.get('session_id', '')

            if agent == 'agent-b':
                # B dispatches to C before responding
                from teaparty.mcp.registry import get_spawn_fn, current_session_id
                # Set contextvar so C is recorded in B's map
                token = current_session_id.set(session_id)
                try:
                    spawn = get_spawn_fn('parent')
                    if spawn:
                        await spawn('agent-c', 'task for C', 'b-to-c')
                finally:
                    current_session_id.reset(token)
                # Wait for C to finish
                await asyncio.sleep(0.2)
                if on_event:
                    on_event({'type': 'assistant', 'message': {'content': [
                        {'type': 'text', 'text': 'B says: C told me the answer'},
                    ]}})
            elif agent == 'agent-c':
                if on_event:
                    on_event({'type': 'assistant', 'message': {'content': [
                        {'type': 'text', 'text': 'C says: the answer is 42'},
                    ]}})
                await asyncio.sleep(0.05)
            else:
                await asyncio.sleep(0.05)

            return FakeLaunchResult(session_id=f'claude-{agent}')

        session = self._make_session()

        async def run():
            with patch('teaparty.runners.launcher.launch', fake_launch), \
                 patch('teaparty.config.roster.has_sub_roster', return_value=True), \
                 patch('subprocess.run'):
                await session._ensure_bus_listener(self._tmpdir)
                from teaparty.mcp.registry import get_spawn_fn
                spawn_fn = get_spawn_fn('parent')

                b_sid, _, _ = await spawn_fn('agent-b', 'task for B', 'a-to-b')
                self.assertTrue(len(b_sid) > 0)

                # Wait for B and C to complete
                await asyncio.sleep(0.5)

                # B's response in A's bus
                b_msgs = session._bus.receive(f'dispatch:{b_sid}')
                b_content = ' '.join(m.content for m in b_msgs)
                self.assertIn('B says: C told me the answer', b_content,
                              f'B response missing. Messages: {[(m.sender, m.content[:50]) for m in b_msgs]}')

                # C's response in B's bus (under B's dispatch conversation)
                # Find C's session_id from B's conversation_map
                b_meta_path = os.path.join(
                    self._tmpdir, 'management', 'sessions', b_sid, 'metadata.json')
                if os.path.isfile(b_meta_path):
                    with open(b_meta_path) as f:
                        b_meta = json.load(f)
                    c_sid = b_meta.get('conversation_map', {}).get('b-to-c', '')
                    if c_sid:
                        c_msgs = session._bus.receive(f'dispatch:{c_sid}')
                        c_content = ' '.join(m.content for m in c_msgs)
                        self.assertIn('C says: the answer is 42', c_content,
                                      f'C response missing. Messages: {[(m.sender, m.content[:50]) for m in c_msgs]}')

        self._run(run())

    def test_parallel_A_B_C(self):
        """A dispatches to B and C in parallel. Both respond independently."""

        async def fake_launch(**kwargs):
            agent = kwargs.get('agent_name', '')
            on_event = kwargs.get('on_stream_event')
            if on_event:
                on_event({'type': 'assistant', 'message': {'content': [
                    {'type': 'text', 'text': f'Response from {agent}'},
                ]}})
            await asyncio.sleep(0.1)
            return FakeLaunchResult(session_id=f'claude-{agent}')

        session = self._make_session()

        async def run():
            with patch('teaparty.runners.launcher.launch', fake_launch), \
                 patch('teaparty.config.roster.has_sub_roster', return_value=False), \
                 patch('subprocess.run'):
                await session._ensure_bus_listener(self._tmpdir)
                from teaparty.mcp.registry import get_spawn_fn
                spawn_fn = get_spawn_fn('parent')

                b_sid, _, _ = await spawn_fn('agent-b', 'task B', 'a-b')
                c_sid, _, _ = await spawn_fn('agent-c', 'task C', 'a-c')

                # Both dispatched (non-blocking)
                self.assertNotEqual(b_sid, c_sid)

                await asyncio.sleep(0.3)

                b_msgs = session._bus.receive(f'dispatch:{b_sid}')
                c_msgs = session._bus.receive(f'dispatch:{c_sid}')

                self.assertTrue(any('Response from agent-b' in m.content for m in b_msgs),
                                f'B response missing: {[(m.sender, m.content[:50]) for m in b_msgs]}')
                self.assertTrue(any('Response from agent-c' in m.content for m in c_msgs),
                                f'C response missing: {[(m.sender, m.content[:50]) for m in c_msgs]}')

        self._run(run())

    def test_rate_limit_close_and_reuse(self):
        """A sends to B, C, D (fills slots). One finishes. A closes it.
        A sends to E successfully."""
        finish_events = {
            'agent-b': asyncio.Event(),
            'agent-c': asyncio.Event(),
            'agent-d': asyncio.Event(),
        }

        async def fake_launch(**kwargs):
            agent = kwargs.get('agent_name', '')
            on_event = kwargs.get('on_stream_event')
            if on_event:
                on_event({'type': 'assistant', 'message': {'content': [
                    {'type': 'text', 'text': f'Done from {agent}'},
                ]}})
            if agent == 'agent-b':
                await asyncio.sleep(0.05)  # B finishes fast
            else:
                await asyncio.sleep(5.0)  # C, D take long
            if agent in finish_events:
                finish_events[agent].set()
            return FakeLaunchResult(session_id=f'claude-{agent}')

        session = self._make_session()

        async def run():
            with patch('teaparty.runners.launcher.launch', fake_launch), \
                 patch('teaparty.config.roster.has_sub_roster', return_value=False), \
                 patch('subprocess.run'):
                await session._ensure_bus_listener(self._tmpdir)
                from teaparty.mcp.registry import get_spawn_fn
                spawn_fn = get_spawn_fn('parent')

                b_sid, _, _ = await spawn_fn('agent-b', 'task B', 'r-b')
                c_sid, _, _ = await spawn_fn('agent-c', 'task C', 'r-c')
                d_sid, _, _ = await spawn_fn('agent-d', 'task D', 'r-d')

                # 4th should fail
                e_sid, _, _ = await spawn_fn('agent-e', 'task E', 'r-e')
                self.assertEqual(e_sid, '', '4th dispatch should fail')

                # Wait for B to finish
                await asyncio.sleep(0.2)

                # Close B to free a slot
                close_conversation(session._dispatch_session, f'dispatch:{b_sid}',
                                   teaparty_home=self._tmpdir, scope='management')

                # Now E should succeed
                e_sid, _, _ = await spawn_fn('agent-e', 'task E', 'r-e')
                self.assertTrue(len(e_sid) > 0, 'E dispatch should succeed after close')

        self._run(run())

    def test_parallel_instance_A_B_B(self):
        """A sends to B twice. Two instances respond with different content."""
        call_count = {'value': 0}

        async def fake_launch(**kwargs):
            call_count['value'] += 1
            instance = call_count['value']
            agent = kwargs.get('agent_name', '')
            on_event = kwargs.get('on_stream_event')
            if on_event:
                on_event({'type': 'assistant', 'message': {'content': [
                    {'type': 'text', 'text': f'{agent} instance {instance}'},
                ]}})
            await asyncio.sleep(0.1)
            return FakeLaunchResult(session_id=f'claude-{agent}-{instance}')

        session = self._make_session()

        async def run():
            with patch('teaparty.runners.launcher.launch', fake_launch), \
                 patch('teaparty.config.roster.has_sub_roster', return_value=False), \
                 patch('subprocess.run'):
                await session._ensure_bus_listener(self._tmpdir)
                from teaparty.mcp.registry import get_spawn_fn
                spawn_fn = get_spawn_fn('parent')

                b1_sid, _, _ = await spawn_fn('agent-b', 'task 1', 'r-b1')
                b2_sid, _, _ = await spawn_fn('agent-b', 'task 2', 'r-b2')

                self.assertNotEqual(b1_sid, b2_sid)

                await asyncio.sleep(0.3)

                b1_msgs = session._bus.receive(f'dispatch:{b1_sid}')
                b2_msgs = session._bus.receive(f'dispatch:{b2_sid}')

                b1_content = ' '.join(m.content for m in b1_msgs)
                b2_content = ' '.join(m.content for m in b2_msgs)

                self.assertIn('instance 1', b1_content,
                              f'B1 wrong content: {b1_content}')
                self.assertIn('instance 2', b2_content,
                              f'B2 wrong content: {b2_content}')

        self._run(run())

    def test_diamond_A_BD_CD(self):
        """A → B and C. Both B and C dispatch to D (separate instances).
        All four responses arrive under correct conversation handles."""

        d_instance = {'count': 0}

        async def fake_launch(**kwargs):
            agent = kwargs.get('agent_name', '')
            session_id = kwargs.get('session_id', '')
            on_event = kwargs.get('on_stream_event')

            if agent in ('agent-b', 'agent-c'):
                # B and C each dispatch to D
                from teaparty.mcp.registry import get_spawn_fn, current_session_id
                token = current_session_id.set(session_id)
                try:
                    spawn = get_spawn_fn('parent')
                    if spawn:
                        await spawn('agent-d', f'task from {agent}', f'{agent}-to-d')
                finally:
                    current_session_id.reset(token)
                await asyncio.sleep(0.2)
                if on_event:
                    on_event({'type': 'assistant', 'message': {'content': [
                        {'type': 'text', 'text': f'{agent} done after dispatching D'},
                    ]}})
            elif agent == 'agent-d':
                d_instance['count'] += 1
                if on_event:
                    on_event({'type': 'assistant', 'message': {'content': [
                        {'type': 'text', 'text': f'D instance {d_instance["count"]}'},
                    ]}})
                await asyncio.sleep(0.05)
            else:
                await asyncio.sleep(0.05)

            return FakeLaunchResult(session_id=f'claude-{agent}-{session_id[:8]}')

        session = self._make_session()

        async def run():
            with patch('teaparty.runners.launcher.launch', fake_launch), \
                 patch('teaparty.config.roster.has_sub_roster', return_value=True), \
                 patch('subprocess.run'):
                await session._ensure_bus_listener(self._tmpdir)
                from teaparty.mcp.registry import get_spawn_fn
                spawn_fn = get_spawn_fn('parent')

                b_sid, _, _ = await spawn_fn('agent-b', 'task B', 'a-b')
                c_sid, _, _ = await spawn_fn('agent-c', 'task C', 'a-c')

                await asyncio.sleep(0.5)

                # Two D instances were launched
                self.assertEqual(d_instance['count'], 2)

                # B and C responses in A's bus
                b_msgs = session._bus.receive(f'dispatch:{b_sid}')
                c_msgs = session._bus.receive(f'dispatch:{c_sid}')

                self.assertTrue(any('agent-b done' in m.content for m in b_msgs),
                                f'B response missing: {[(m.sender, m.content[:50]) for m in b_msgs]}')
                self.assertTrue(any('agent-c done' in m.content for m in c_msgs),
                                f'C response missing: {[(m.sender, m.content[:50]) for m in c_msgs]}')

        self._run(run())


if __name__ == '__main__':
    unittest.main()
