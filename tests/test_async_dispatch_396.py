"""Specification tests for issue #396: async dispatch, conversation handles, recursive close.

These tests exercise the real dispatch machinery with a scripted LLM caller.
The scripted caller replaces only the claude -p subprocess — everything else
is real: session creation, git worktree management, conversation_map management,
bus writes, background tasks, and recursive close.

TestCloseConversation: unit tests for close_conversation using hand-built
    session directories (no launch, no event loop).

TestAsyncSpawnFn / TestAsyncTopologies: use make_scripted_caller +
    AgentSession(llm_caller=...) to drive the full dispatch pipeline on
    a shared module-level event loop, the same pattern as the integration
    tests in test_async_dispatch_scripted.py.
"""
import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from teaparty.runners.launcher import (
    Session,
    create_session,
    record_child_session,
    remove_child_session,
    check_slot_available,
    MAX_CONVERSATIONS_PER_AGENT,
    _save_session_metadata,
)
from teaparty.runners.scripted import (
    make_scripted_caller,
    text_event,
    tool_use_event,
    cost_event,
)
from teaparty.workspace.close_conversation import (
    close_conversation_sync as close_conversation,
)


# ── Shared test environment ──────────────────────────────────────────────────
# Module-level git repo and event loop, reused across TestAsyncSpawnFn and
# TestAsyncTopologies.  Each test class gets its own .teaparty home inside
# the shared repo (via setUp) so tests don't interfere.

_module_loop = None
_module_repo_root = None


def _init_git_repo():
    """Create a temp git repo with one commit."""
    root = tempfile.mkdtemp()
    subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
    subprocess.run(['git', 'config', 'user.email', 't@x'],
                   cwd=root, check=True)
    subprocess.run(['git', 'config', 'user.name', 't'],
                   cwd=root, check=True)
    with open(os.path.join(root, 'README.md'), 'w') as f:
        f.write('x\n')
    subprocess.run(['git', 'add', 'README.md'], cwd=root, check=True)
    subprocess.run(['git', 'commit', '-q', '-m', 'init'],
                   cwd=root, check=True)
    return root


def setUpModule():
    global _module_loop, _module_repo_root
    _module_repo_root = _init_git_repo()
    _module_loop = asyncio.new_event_loop()


def tearDownModule():
    global _module_loop, _module_repo_root

    async def _shutdown():
        pending = [t for t in asyncio.all_tasks(_module_loop)
                   if t is not asyncio.current_task()]
        for t in pending:
            t.cancel()
        if pending:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*pending, return_exceptions=True),
                    timeout=5.0)
            except asyncio.TimeoutError:
                pass

    if _module_loop:
        try:
            _module_loop.run_until_complete(_shutdown())
        except Exception:
            pass
        _module_loop.close()
    if _module_repo_root:
        shutil.rmtree(_module_repo_root, ignore_errors=True)
    from teaparty.mcp import registry as _registry
    _registry.clear()


def _run(coro, timeout=30):
    """Run a coroutine on the module loop with a timeout."""
    return _module_loop.run_until_complete(
        asyncio.wait_for(coro, timeout=timeout))


def _make_teaparty_home(repo_root=None, agents=None, workgroups=None):
    """Create a .teaparty dir with a management registry inside *repo_root*.

    Returns the .teaparty path.  If *repo_root* is None, creates a fresh
    temp dir with ``git init`` (used by TestCloseConversation which doesn't
    need the module-level repo).

    *agents* is the list of agent names to register.  Defaults to
    ['parent', 'child-a', 'child-b', 'child-c'].

    *workgroups* is an optional list of dicts, each with 'name', 'lead',
    and 'members' keys, defining the workgroup hierarchy.  When omitted a
    single flat workgroup is created with agents[0] as lead.
    """
    if repo_root is None:
        repo_root = _init_git_repo()
    if agents is None:
        agents = ['parent', 'child-a', 'child-b', 'child-c']

    tp = os.path.join(repo_root, '.teaparty')
    mgmt = os.path.join(tp, 'management')
    os.makedirs(os.path.join(mgmt, 'sessions'), exist_ok=True)

    for name in agents:
        d = os.path.join(mgmt, 'agents', name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, 'agent.md'), 'w') as f:
            f.write(f'---\ndescription: {name}\n---\n\n{name}\n')

    wg_dir = os.path.join(mgmt, 'workgroups')
    os.makedirs(wg_dir, exist_ok=True)

    if workgroups is None:
        lead = agents[0]
        members = agents[1:]
        workgroups = [{'name': 'test-team', 'lead': lead, 'members': members}]

    for wg in workgroups:
        with open(os.path.join(wg_dir, f'{wg["name"]}.yaml'), 'w') as f:
            f.write(f'name: {wg["name"]}\nlead: {wg["lead"]}\n'
                    f'members:\n  agents:\n')
            for m in wg['members']:
                f.write(f'    - {m}\n')

    with open(os.path.join(mgmt, 'teaparty.yaml'), 'w') as f:
        f.write(f'name: test-mgmt\ndescription: test\nlead: {workgroups[0]["lead"]}\n'
                f'projects: []\n'
                f'members:\n  projects: []\n  agents: []\n'
                f'  workgroups:\n')
        for wg in workgroups:
            f.write(f'    - {wg["name"]}\n')
        f.write(f'workgroups:\n')
        for wg in workgroups:
            f.write(f'  - name: {wg["name"]}\n'
                    f'    config: workgroups/{wg["name"]}.yaml\n')

    return tp


# ── Helpers for scripted tests ───────────────────────────────────────────────

_qualifier_counter = 0


def _make_session(teaparty_home, llm_caller, agent_name='parent',
                  qualifier=None):
    """Create an AgentSession wired to the scripted caller.

    Each call gets a unique qualifier so tests never share on-disk
    session state (conversation_map, slots).
    """
    global _qualifier_counter
    if qualifier is None:
        _qualifier_counter += 1
        qualifier = f'test-{_qualifier_counter}'

    from teaparty.teams.session import AgentSession
    from teaparty.messaging.conversations import ConversationType
    return AgentSession(
        teaparty_home,
        agent_name=agent_name,
        scope='management',
        qualifier=qualifier,
        conversation_type=ConversationType.OFFICE_MANAGER,
        dispatches=True,
        llm_caller=llm_caller,
    )


def _send_human(session, message):
    session._bus.send(session.conversation_id, 'human', message)


async def _wait_for_result(session, keyword='RESULT:', timeout=10):
    """Poll the bus for a coordinator message containing *keyword*."""
    conv_id = session.conversation_id
    for _ in range(timeout * 10):
        await asyncio.sleep(0.1)
        msgs = session._bus.receive(conv_id)
        for m in reversed(msgs):
            if m.sender == session.agent_name and keyword in m.content:
                return m.content
    return None


async def _wait_for_child_response(session, child_sid, keyword, timeout=10):
    """Poll a child's bus conversation for *keyword*."""
    conv_id = f'dispatch:{child_sid}'
    for _ in range(timeout * 10):
        await asyncio.sleep(0.1)
        msgs = session._bus.receive(conv_id)
        for m in msgs:
            if keyword in m.content:
                return m.content
    return None


def _dispatch_once(*dispatch_events):
    """Build a stateful parent script that dispatches on the first call only.

    On the first invocation, fires *dispatch_events* (tool_use + text +
    cost_event). On every subsequent call (resumes from completed children),
    returns an acknowledgement without re-dispatching.
    """
    first = [True]
    def script(msg):
        if first[0]:
            first[0] = False
            return list(dispatch_events)
        return [text_event('RESULT: done'), cost_event()]
    return script


def _get_handles(session):
    cmap = session._dispatch_session.conversation_map
    return [f'dispatch:{sid}' for sid in cmap.values()]


def _close_all(session, teaparty_home):
    from teaparty.workspace.close_conversation import close_conversation as _async_close
    for conv_id in _get_handles(session):
        _module_loop.run_until_complete(_async_close(
            session._dispatch_session, conv_id,
            teaparty_home=teaparty_home, scope='management'))


# ── TestCloseConversation ────────────────────────────────────────────────────
# These are pure session-directory tests — no event loop, no launch.

class TestCloseConversation(unittest.TestCase):
    """CloseConversation recursively tears down children and frees slots.

    These tests create real session directories on disk, populate
    conversation_maps, and verify that close_conversation removes
    the correct directories and frees the correct slots.
    """

    def setUp(self):
        self._tmpdir = _make_teaparty_home()

    def tearDown(self):
        # Clean up the entire repo root (parent of .teaparty)
        shutil.rmtree(os.path.dirname(self._tmpdir), ignore_errors=True)

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


# ── TestAsyncSpawnFn ─────────────────────────────────────────────────────────
# Uses the scripted caller to exercise spawn_fn through the full
# AgentSession machinery — no patches, no scope issues.

class _AsyncTestCase(unittest.TestCase):
    """Base class for async tests on the shared module loop.

    Cancels all background tasks spawned during the test before tearDown
    removes the .teaparty directory.  Without this, _run_child tasks
    from a just-completed test can race with tearDown and hit
    FileNotFoundError on deleted session dirs.
    """

    _session = None  # Subclasses set this to the AgentSession under test

    def tearDown(self):
        # Cancel any background tasks the session spawned
        if self._session is not None:
            for task in list(self._session._background_tasks):
                task.cancel()
            if self._session._background_tasks:
                try:
                    _module_loop.run_until_complete(asyncio.wait_for(
                        asyncio.gather(*self._session._background_tasks,
                                       return_exceptions=True),
                        timeout=2.0))
                except (asyncio.TimeoutError, Exception):
                    pass
        # Now safe to remove .teaparty
        if hasattr(self, '_tmpdir') and self._tmpdir:
            shutil.rmtree(self._tmpdir, ignore_errors=True)


class TestAsyncSpawnFn(_AsyncTestCase):
    """Test spawn_fn with a scripted caller.

    These tests exercise the real spawn_fn closure from AgentSession
    using a scripted caller. Everything is real: session creation,
    git worktree management, conversation_map, bus writes, background
    task lifecycle.
    """

    def setUp(self):
        self._tmpdir = _make_teaparty_home(
            repo_root=_module_repo_root,
            agents=['parent', 'child-a', 'child-b', 'child-c'],
        )

    def test_spawn_returns_immediately(self):
        """spawn_fn returns a session_id and empty result_text without
        waiting for the child to complete."""
        import time

        # Child script: takes 2 seconds to respond
        scripts = {
            'parent': _dispatch_once(
                tool_use_event('mcp__teaparty-config__Send',
                               {'member': 'child-a',
                                'message': 'Do something'}),
                text_event('Dispatched.'),
                cost_event(),
            ),
            'child-a': lambda msg: [text_event('Hello from child'),
                                    cost_event()],
        }
        self._session = _make_session(self._tmpdir, make_scripted_caller(scripts))

        async def run():
            _send_human(self._session, 'Dispatch a child')
            t0 = time.monotonic()
            await self._session.invoke(cwd=_module_repo_root)
            elapsed = time.monotonic() - t0

            # invoke returns after the parent's first turn, not after
            # the child completes. The child runs as a background task.
            self.assertLess(elapsed, 5.0)

            # Parent dispatched at least one child
            cmap = self._session._dispatch_session.conversation_map
            self.assertGreaterEqual(len(cmap), 1)

        _run(run())

    def test_child_response_arrives_in_bus(self):
        """After invoke, the child's response is written to the parent's
        bus under the dispatch conversation_id."""
        scripts = {
            'parent': _dispatch_once(
                tool_use_event('mcp__teaparty-config__Send',
                               {'member': 'child-a',
                                'message': 'What is the answer?'}),
                text_event('Dispatched.'),
                cost_event(),
            ),
            'child-a': {
                'What is the answer': [text_event('The answer is 42'),
                                       cost_event()],
            },
        }
        self._session = _make_session(self._tmpdir, make_scripted_caller(scripts))

        async def run():
            _send_human(self._session, 'Ask child-a')
            await self._session.invoke(cwd=_module_repo_root)

            # Wait for the child to complete
            cmap = self._session._dispatch_session.conversation_map
            self.assertEqual(len(cmap), 1)
            child_sid = list(cmap.values())[0]

            result = await _wait_for_child_response(
                self._session, child_sid, 'The answer is 42')
            self.assertIsNotNone(
                result, 'Child response must arrive on dispatch bus')

        _run(run())

    def test_parallel_dispatch_two_children(self):
        """Two Send calls in quick succession both succeed and both children
        produce responses in the bus."""
        scripts = {
            'parent': _dispatch_once(
                tool_use_event('mcp__teaparty-config__Send',
                               {'member': 'child-a',
                                'message': 'say alpha'}),
                tool_use_event('mcp__teaparty-config__Send',
                               {'member': 'child-b',
                                'message': 'say beta'}),
                text_event('Both dispatched.'),
                cost_event(),
            ),
            'child-a': {'say alpha': [text_event('alpha'), cost_event()]},
            'child-b': {'say beta': [text_event('beta'), cost_event()]},
        }
        self._session = _make_session(self._tmpdir, make_scripted_caller(scripts))

        async def run():
            _send_human(self._session, 'Dispatch two')
            await self._session.invoke(cwd=_module_repo_root)

            cmap = self._session._dispatch_session.conversation_map
            self.assertEqual(len(cmap), 2, 'Both children must be dispatched')

            sids = list(cmap.values())
            r_a = await _wait_for_child_response(self._session, sids[0], 'alpha')
            r_b = await _wait_for_child_response(self._session, sids[1], 'beta')

            # At least one of each — order depends on which sid maps to which child
            combined = (r_a or '') + (r_b or '')
            self.assertIn('alpha', combined)
            self.assertIn('beta', combined)

        _run(run())

    def test_slot_limit_rejects_fourth(self):
        """After 3 dispatches, the 4th returns empty session_id (rejected)."""
        scripts = {
            'parent': _dispatch_once(
                tool_use_event('mcp__teaparty-config__Send',
                               {'member': 'child-a',
                                'message': 'task 1'}),
                tool_use_event('mcp__teaparty-config__Send',
                               {'member': 'child-b',
                                'message': 'task 2'}),
                tool_use_event('mcp__teaparty-config__Send',
                               {'member': 'child-c',
                                'message': 'task 3'}),
                # 4th dispatch — should be rejected by slot limit
                tool_use_event('mcp__teaparty-config__Send',
                               {'member': 'child-a',
                                'message': 'task 4'}),
                text_event('All dispatched.'),
                cost_event(),
            ),
            'child-a': lambda msg: [text_event(f'done: {msg[:20]}'),
                                    cost_event()],
            'child-b': lambda msg: [text_event('done b'), cost_event()],
            'child-c': lambda msg: [text_event('done c'), cost_event()],
        }
        self._session = _make_session(self._tmpdir, make_scripted_caller(scripts))

        async def run():
            _send_human(self._session, 'Fill all slots')
            await self._session.invoke(cwd=_module_repo_root)

            # At most MAX_CONVERSATIONS_PER_AGENT children
            cmap = self._session._dispatch_session.conversation_map
            self.assertLessEqual(len(cmap), MAX_CONVERSATIONS_PER_AGENT)

        _run(run())


# ── TestAsyncTopologies ──────────────────────────────────────────────────────

class TestAsyncTopologies(_AsyncTestCase):
    """End-to-end async dispatch tests for each topology.

    These exercise the real spawn_fn with scripted callers. Each test
    verifies that responses arrive in the correct bus conversations
    under the correct conversation_id.
    """

    def setUp(self):
        self._agents = ['parent', 'agent-b', 'agent-c', 'agent-d', 'agent-e']
        # Hierarchical workgroups: parent leads the top team; agent-b and
        # agent-c each lead sub-teams containing agent-d (and agent-e).
        # This lets B and C dispatch to D in the diamond/linear tests.
        self._tmpdir = _make_teaparty_home(
            repo_root=_module_repo_root,
            agents=self._agents,
            workgroups=[
                {'name': 'top-team', 'lead': 'parent',
                 'members': ['agent-b', 'agent-c', 'agent-d', 'agent-e']},
                {'name': 'b-team', 'lead': 'agent-b',
                 'members': ['agent-c', 'agent-d']},
                {'name': 'c-team', 'lead': 'agent-c',
                 'members': ['agent-d', 'agent-e']},
            ],
        )

    def test_linear_A_B_C(self):
        """A dispatches to B. B dispatches to C. C responds. B integrates
        C's reply and responds. Both responses arrive in the correct bus."""

        b_dispatched = [False]
        def _b_script(msg):
            if not b_dispatched[0] and 'task for B' in msg:
                b_dispatched[0] = True
                return [
                    tool_use_event('mcp__teaparty-config__Send',
                                   {'member': 'agent-c',
                                    'message': 'task for C'}),
                    text_event('B dispatched to C.'),
                    cost_event(),
                ]
            # Resume with C's reply
            return [text_event('B says: C told me the answer'),
                    cost_event()]

        parent_dispatched = [False]
        def _parent_script(msg):
            if not parent_dispatched[0]:
                parent_dispatched[0] = True
                return [
                    tool_use_event('mcp__teaparty-config__Send',
                                   {'member': 'agent-b',
                                    'message': 'task for B'}),
                    text_event('Dispatched to B.'),
                    cost_event(),
                ]
            return [text_event('RESULT: B says: C told me the answer'),
                    cost_event()]

        scripts = {
            'parent': _parent_script,
            'agent-b': _b_script,
            'agent-c': {'task for C': [text_event('C says: the answer is 42'),
                                       cost_event()]},
        }
        self._session = _make_session(self._tmpdir, make_scripted_caller(scripts))

        async def run():
            _send_human(self._session, 'Start linear chain')
            await self._session.invoke(cwd=_module_repo_root)

            # Wait for the chain to complete — parent gets resumed with B's reply
            result = await _wait_for_result(
                self._session, keyword='RESULT:', timeout=15)
            self.assertIsNotNone(result, 'Parent must produce RESULT')

            # Check B's bus for the expected content.
            cmap = self._session._dispatch_session.conversation_map
            self.assertGreaterEqual(len(cmap), 1)
            b_sid = list(cmap.values())[0]
            b_reply = await _wait_for_child_response(
                self._session, b_sid, 'B says: C told me the answer', timeout=15)
            self.assertIsNotNone(
                b_reply, 'B must integrate C reply before responding')

        _run(run(), timeout=30)

    def test_parallel_A_B_C(self):
        """A dispatches to B and C in parallel. Both respond independently."""
        scripts = {
            'parent': _dispatch_once(
                tool_use_event('mcp__teaparty-config__Send',
                               {'member': 'agent-b',
                                'message': 'task B'}),
                tool_use_event('mcp__teaparty-config__Send',
                               {'member': 'agent-c',
                                'message': 'task C'}),
                text_event('Both dispatched.'),
                cost_event(),
            ),
            'agent-b': {'task B': [text_event('Response from agent-b'),
                                   cost_event()]},
            'agent-c': {'task C': [text_event('Response from agent-c'),
                                   cost_event()]},
        }
        self._session = _make_session(self._tmpdir, make_scripted_caller(scripts))

        async def run():
            _send_human(self._session, 'Dispatch parallel')
            await self._session.invoke(cwd=_module_repo_root)

            cmap = self._session._dispatch_session.conversation_map
            self.assertEqual(len(cmap), 2)

            sids = list(cmap.values())
            r0 = await _wait_for_child_response(
                self._session, sids[0], 'Response from agent-', timeout=10)
            r1 = await _wait_for_child_response(
                self._session, sids[1], 'Response from agent-', timeout=10)
            combined = (r0 or '') + (r1 or '')
            self.assertIn('agent-b', combined)
            self.assertIn('agent-c', combined)

        _run(run())

    def test_rate_limit_close_and_reuse(self):
        """A sends to B, C, D (fills slots). Close B. A sends to E."""

        def _parent_script(msg):
            if 'Fill all slots' in msg:
                return [
                    tool_use_event('mcp__teaparty-config__Send',
                                   {'member': 'agent-b',
                                    'message': 'task B'}),
                    tool_use_event('mcp__teaparty-config__Send',
                                   {'member': 'agent-c',
                                    'message': 'task C'}),
                    tool_use_event('mcp__teaparty-config__Send',
                                   {'member': 'agent-d',
                                    'message': 'task D'}),
                    text_event('Three dispatched.'),
                    cost_event(),
                ]
            # Resume after child replies
            return [text_event('RESULT: integrated'), cost_event()]

        scripts = {
            'parent': _parent_script,
            'agent-b': {'task B': [text_event('Done B'), cost_event()]},
            'agent-c': {'task C': [text_event('Done C'), cost_event()]},
            'agent-d': {'task D': [text_event('Done D'), cost_event()]},
            'agent-e': lambda msg: [text_event('Done E'), cost_event()],
        }
        self._session = _make_session(self._tmpdir, make_scripted_caller(scripts))

        async def run():
            from teaparty.workspace.close_conversation import (
                close_conversation as _async_close,
            )
            _send_human(self._session, 'Fill all slots')
            await self._session.invoke(cwd=_module_repo_root)

            # Wait for children to complete
            await asyncio.sleep(1.0)

            cmap = self._session._dispatch_session.conversation_map
            self.assertEqual(len(cmap), 3, 'All 3 slots filled')

            # Close one child to free a slot
            first_sid = list(cmap.values())[0]
            await _async_close(
                self._session._dispatch_session, f'dispatch:{first_sid}',
                teaparty_home=self._tmpdir, scope='management')

            self.assertTrue(check_slot_available(self._session._dispatch_session))

        _run(run(), timeout=30)

    def test_parallel_instance_A_B_B(self):
        """A sends to B twice. Two instances respond with different content."""
        instance_count = {'value': 0}

        def _b_script(msg):
            instance_count['value'] += 1
            n = instance_count['value']
            return [text_event(f'agent-b instance {n}'), cost_event()]

        scripts = {
            'parent': _dispatch_once(
                tool_use_event('mcp__teaparty-config__Send',
                               {'member': 'agent-b',
                                'message': 'task 1'}),
                tool_use_event('mcp__teaparty-config__Send',
                               {'member': 'agent-b',
                                'message': 'task 2'}),
                text_event('Both dispatched.'),
                cost_event(),
            ),
            'agent-b': _b_script,
        }
        self._session = _make_session(self._tmpdir, make_scripted_caller(scripts))

        async def run():
            _send_human(self._session, 'Dispatch B twice')
            await self._session.invoke(cwd=_module_repo_root)

            cmap = self._session._dispatch_session.conversation_map
            self.assertEqual(len(cmap), 2, 'Two B instances dispatched')

            sids = list(cmap.values())
            self.assertNotEqual(sids[0], sids[1])

            r0 = await _wait_for_child_response(
                self._session, sids[0], 'instance', timeout=10)
            r1 = await _wait_for_child_response(
                self._session, sids[1], 'instance', timeout=10)
            self.assertIsNotNone(r0, 'First B instance must respond')
            self.assertIsNotNone(r1, 'Second B instance must respond')

        _run(run())

    def test_diamond_A_BD_CD(self):
        """A → B and C. Both B and C dispatch to D (separate instances).
        All four responses arrive under correct conversation handles."""
        d_instance = {'count': 0}

        def _make_bc_script():
            dispatched = [False]
            def _script(msg):
                if not dispatched[0] and 'task' in msg:
                    dispatched[0] = True
                    agent = 'agent-b' if 'B' in msg else 'agent-c'
                    return [
                        tool_use_event('mcp__teaparty-config__Send',
                                       {'member': 'agent-d',
                                        'message': f'task from {agent}'}),
                        text_event(f'{agent} dispatched to D.'),
                        cost_event(),
                    ]
                return [text_event('done after dispatching D'), cost_event()]
            return _script

        def _d_script(msg):
            d_instance['count'] += 1
            return [text_event(f'D instance {d_instance["count"]}'),
                    cost_event()]

        parent_dispatched = [False]
        def _parent_script(msg):
            if not parent_dispatched[0]:
                parent_dispatched[0] = True
                return [
                    tool_use_event('mcp__teaparty-config__Send',
                                   {'member': 'agent-b',
                                    'message': 'task B'}),
                    tool_use_event('mcp__teaparty-config__Send',
                                   {'member': 'agent-c',
                                    'message': 'task C'}),
                    text_event('Both dispatched.'),
                    cost_event(),
                ]
            return [text_event('RESULT: diamond complete'), cost_event()]

        scripts = {
            'parent': _parent_script,
            'agent-b': _make_bc_script(),
            'agent-c': _make_bc_script(),
            'agent-d': _d_script,
        }
        self._session = _make_session(self._tmpdir, make_scripted_caller(scripts))

        async def run():
            _send_human(self._session, 'Start diamond')
            await self._session.invoke(cwd=_module_repo_root)

            # Wait for the diamond to complete — both B and C must finish.
            # B or C completing first triggers 'RESULT:' on the parent; the
            # other sibling may still be in flight.  Poll until both B and C
            # have 'done' in their conversation buses (timeout=15s total).
            cmap = self._session._dispatch_session.conversation_map
            deadline = asyncio.get_event_loop().time() + 15
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(0.1)
                sids = list(cmap.values())
                found_b = any(
                    'agent-b' in ' '.join(m.content for m in
                        self._session._bus.receive(f'dispatch:{s}'))
                    and 'done' in ' '.join(m.content for m in
                        self._session._bus.receive(f'dispatch:{s}'))
                    for s in sids
                )
                found_c = any(
                    'agent-c' in ' '.join(m.content for m in
                        self._session._bus.receive(f'dispatch:{s}'))
                    and 'done' in ' '.join(m.content for m in
                        self._session._bus.receive(f'dispatch:{s}'))
                    for s in sids
                )
                if found_b and found_c:
                    break

            # Two D instances were launched
            self.assertEqual(d_instance['count'], 2)

            self.assertGreaterEqual(len(cmap), 2)
            self.assertTrue(found_b, 'B response must be in bus')
            self.assertTrue(found_c, 'C response must be in bus')

        _run(run(), timeout=30)


if __name__ == '__main__':
    unittest.main()
