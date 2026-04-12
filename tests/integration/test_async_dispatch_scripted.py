"""CI-runnable integration tests for issue #396.

Exercises the FULL dispatch codepath (spawn_fn, async tasks, resume
chain, CloseConversation, background task lifecycle) using a scripted
LLM caller instead of real claude. Tests run in any environment — no
claude binary, no Max subscription, no non-determinism.

Architecture:
- TeaPartyBridge starts on a test-only port (real code, test scope)
- AgentSession created with llm_caller=make_scripted_caller(scripts)
- Scripts are stateful per-agent — the coordinator tracks which replies
  it has seen to handle parallel dispatch race conditions

Coverage: linear, parallel, rate limit, parallel instance, diamond,
close mid-flight, recursive close.
"""
import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import unittest

from teaparty.runners.scripted import (
    make_scripted_caller,
    text_event,
    tool_use_event,
    cost_event,
    thinking_event,
)

BRIDGE_PORT = 19877
_FIRST_COORD_IS_HUMAN = True

_module_env = None
_module_loop = None
_module_runner = None


def _make_test_environment():
    repo_root = tempfile.mkdtemp()
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

    for name in ['coordinator', 'mid-agent', 'leaf-agent']:
        agent_dir = os.path.join(agents_dir, name)
        os.makedirs(agent_dir, exist_ok=True)
        with open(os.path.join(agent_dir, 'agent.md'), 'w') as f:
            f.write(f'---\nname: {name}\ndescription: test\n---\n')

    wg_dir = os.path.join(teaparty_home, 'management', 'workgroups')
    os.makedirs(wg_dir)
    with open(os.path.join(wg_dir, 'test-team.yaml'), 'w') as f:
        f.write('name: test-team\nlead: coordinator\n'
                'members:\n  agents:\n    - mid-agent\n    - leaf-agent\n')
    with open(os.path.join(wg_dir, 'mid-team.yaml'), 'w') as f:
        f.write('name: mid-team\nlead: mid-agent\n'
                'members:\n  agents:\n    - leaf-agent\n')
    with open(os.path.join(teaparty_home, 'management', 'teaparty.yaml'), 'w') as f:
        f.write('name: test\nlead: coordinator\n'
                'workgroups:\n'
                '  - name: test-team\n'
                '    config: workgroups/test-team.yaml\n'
                '  - name: mid-team\n'
                '    config: workgroups/mid-team.yaml\n'
                'members:\n  workgroups:\n    - test-team\n    - mid-team\n')

    static_dir = os.path.join(repo_root, 'static')
    os.makedirs(static_dir)
    with open(os.path.join(static_dir, 'index.html'), 'w') as f:
        f.write('<html></html>')

    return teaparty_home, repo_root, static_dir


def setUpModule():
    global _module_env, _module_loop, _module_runner
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
        if _module_runner:
            try:
                await asyncio.wait_for(_module_runner.cleanup(), timeout=5.0)
            except asyncio.TimeoutError:
                pass

    if _module_loop:
        try:
            _module_loop.run_until_complete(_shutdown())
        except Exception:
            pass
        _module_loop.close()
    if _module_env:
        shutil.rmtree(_module_env[1], ignore_errors=True)
    os.environ.pop('TEAPARTY_BRIDGE_PORT', None)


def _run(coro, timeout=30):
    return _module_loop.run_until_complete(
        asyncio.wait_for(coro, timeout=timeout))


def _make_coordinator(qualifier, llm_caller, on_dispatch=None):
    from teaparty.teams.session import AgentSession
    from teaparty.messaging.conversations import ConversationType
    return AgentSession(
        _module_env[0],
        agent_name='coordinator',
        scope='management',
        qualifier=qualifier,
        conversation_type=ConversationType.OFFICE_MANAGER,
        dispatches=True,
        llm_caller=llm_caller,
        on_dispatch=on_dispatch,
    )


def _send_human(session, message):
    session._bus.send(session.conversation_id, 'human', message)


async def _wait_for_result(session, timeout=10):
    conv_id = session.conversation_id
    for _ in range(timeout * 10):
        await asyncio.sleep(0.1)
        msgs = session._bus.receive(conv_id)
        for m in reversed(msgs):
            if m.sender == 'coordinator' and 'RESULT:' in m.content:
                return m.content
    return None


def _get_handles(session):
    cmap = session._dispatch_session.conversation_map
    return [f'dispatch:{sid}' for sid in cmap.values()]


def _close_all(session):
    from teaparty.workspace.close_conversation import close_conversation
    for conv_id in _get_handles(session):
        close_conversation(
            session._dispatch_session, conv_id,
            teaparty_home=_module_env[0], scope='management')


# ── Script builders ────────────────────────────────────────────────────────

def _stateful_coordinator_script(expected_replies, dispatch_events):
    """Build a stateful coordinator script that accumulates seen replies.

    expected_replies: set of substrings to look for in resume prompts
    dispatch_events: list of stream events to fire on the initial call

    The coordinator fires the dispatch events on first call. On every
    subsequent call it scans the resume prompt (`message`) for any
    expected substrings and unions them into its seen set. The set
    persists across invokes, so replies integrate even when they
    arrive across multiple resume turns.

    When seen == expected, it emits ``RESULT: ...``.
    """
    seen: set = set()
    first_call = [True]

    def respond(message):
        if first_call[0]:
            first_call[0] = False
            return dispatch_events
        for item in expected_replies:
            if item in message:
                seen.add(item)
        if seen == expected_replies:
            result = ', '.join(sorted(seen))
            return [text_event(f'RESULT: {result}'), cost_event()]
        return [text_event(f'Got {len(seen)} of {len(expected_replies)}'),
                cost_event()]

    return respond


# ── Tests ──────────────────────────────────────────────────────────────────


class TestParallelDispatchScripted(unittest.TestCase):
    """Coordinator dispatches to leaf-agent twice in parallel.
    Both children reply with scripted responses.
    Coordinator is resumed twice, integrates both replies, produces RESULT."""

    def test_coordinator_integrates_both_parallel_replies(self):
        scripts = {
            'coordinator': _stateful_coordinator_script(
                expected_replies={'alpha', 'beta'},
                dispatch_events=[
                    thinking_event('Dispatching two tasks.'),
                    tool_use_event('mcp__teaparty-config__Send',
                                   {'member': 'leaf-agent', 'message': 'say alpha'}),
                    tool_use_event('mcp__teaparty-config__Send',
                                   {'member': 'leaf-agent', 'message': 'say beta'}),
                    text_event('Both dispatched. Waiting for replies.'),
                    cost_event(),
                ]),
            'leaf-agent': {
                'say alpha': [text_event('alpha'), cost_event()],
                'say beta':  [text_event('beta'), cost_event()],
            },
        }
        session = _make_coordinator('parallel-scripted',
                                    make_scripted_caller(scripts))

        async def run():
            _send_human(session, 'Dispatch alpha and beta tasks')
            await session.invoke(cwd=_module_env[1])
            return await _wait_for_result(session, timeout=10)

        result = _run(run(), timeout=30)
        self.assertIsNotNone(result, 'Coordinator must produce RESULT')
        self.assertIn('alpha', result)
        self.assertIn('beta', result)

        # Accordion invariant: child replies must NOT be flattened onto
        # the parent conversation. They live on the nested
        # dispatch:{child} conversations, which is what the UI
        # accordion reads. If a future change dual-writes, this fails.
        parent_msgs = session._bus.receive(session.conversation_id)
        parent_senders = [m.sender for m in parent_msgs]
        self.assertNotIn(
            'leaf-agent', parent_senders,
            'child reply must not appear on the parent conversation '
            '— it belongs on the nested dispatch:{child} bus')

        # And each child's reply IS present on its own dispatch bus.
        for child_sid in session._dispatch_session.conversation_map.values():
            child_msgs = session._bus.receive(f'dispatch:{child_sid}')
            senders = {m.sender for m in child_msgs}
            self.assertIn(
                'leaf-agent', senders,
                'child reply must be present on its nested dispatch bus')

        _close_all(session)
        self.assertEqual(len(session._dispatch_session.conversation_map), 0)


class TestParallelInstanceScripted(unittest.TestCase):
    """Coordinator dispatches same agent twice with different payloads.
    Two separate instances run, two separate replies arrive."""

    def test_two_instances_of_same_agent_reply_independently(self):
        scripts = {
            'coordinator': _stateful_coordinator_script(
                expected_replies={'red', 'blue'},
                dispatch_events=[
                    tool_use_event('mcp__teaparty-config__Send',
                                   {'member': 'leaf-agent', 'message': 'say red'}),
                    tool_use_event('mcp__teaparty-config__Send',
                                   {'member': 'leaf-agent', 'message': 'say blue'}),
                    text_event('Both sent.'),
                    cost_event(),
                ]),
            'leaf-agent': {
                'say red':  [text_event('red'), cost_event()],
                'say blue': [text_event('blue'), cost_event()],
            },
        }
        session = _make_coordinator('instance-scripted',
                                    make_scripted_caller(scripts))

        async def run():
            _send_human(session, 'Dispatch red and blue')
            await session.invoke(cwd=_module_env[1])
            return await _wait_for_result(session, timeout=10)

        result = _run(run(), timeout=30)
        self.assertIsNotNone(result, 'Coordinator must produce RESULT')
        self.assertIn('red', result)
        self.assertIn('blue', result)

        _close_all(session)
        self.assertEqual(len(session._dispatch_session.conversation_map), 0)


class TestLinearDispatchScripted(unittest.TestCase):
    """A→B→C chain. Coordinator dispatches mid-agent, which dispatches
    leaf-agent, which replies. Reply bubbles up through mid-agent to
    coordinator, producing RESULT."""

    def test_leaf_reply_bubbles_up_through_mid_agent(self):
        # mid-agent: first call dispatches leaf; resume call (after leaf
        # replies) echoes 'done' upward. Only one child, no race.
        first_mid = [True]
        mid_calls = [0]
        mid_messages: list = []
        coord_resumes = [0]
        coord_resume_messages: list = []

        def mid_script(message):
            mid_calls[0] += 1
            mid_messages.append(message)
            if first_mid[0]:
                first_mid[0] = False
                return [
                    tool_use_event('mcp__teaparty-config__Send',
                                   {'member': 'leaf-agent', 'message': 'do work'}),
                    text_event('Dispatched leaf.'),
                    cost_event(),
                ]
            return [text_event('done'), cost_event()]

        # Wrap the stateful coord script so we can count resume turns
        # and capture what the coordinator sees on each one. The fix
        # for the "interim reply" bug is: coord must be resumed
        # EXACTLY ONCE (with mid's final 'done'), never with mid's
        # interim 'Dispatched leaf.' text.
        inner_coord = _stateful_coordinator_script(
            expected_replies={'done'},
            dispatch_events=[
                tool_use_event('mcp__teaparty-config__Send',
                               {'member': 'mid-agent', 'message': 'run pipeline'}),
                text_event('Dispatched.'),
                cost_event(),
            ])

        def coord_script(message):
            # The first call is the initial human dispatch. Every
            # subsequent call is a resume with a child reply.
            if coord_resumes[0] > 0 or not _FIRST_COORD_IS_HUMAN:
                coord_resume_messages.append(message)
            coord_resumes[0] += 1
            return inner_coord(message)

        scripts = {
            'coordinator': coord_script,
            'mid-agent': mid_script,
            'leaf-agent': {
                'do work': [text_event('leaf-done'), cost_event()],
            },
        }
        session = _make_coordinator('linear-scripted',
                                    make_scripted_caller(scripts))

        async def run():
            _send_human(session, 'Run the pipeline')
            await session.invoke(cwd=_module_env[1])
            return await _wait_for_result(session, timeout=10)

        result = _run(run(), timeout=30)
        self.assertIsNotNone(result, 'Coordinator must produce RESULT')
        self.assertIn('done', result)

        # Reload invariant: rebuilding the dispatch tree from disk
        # MUST still show completed children, because they aren't
        # closed. Slots are only freed by explicit CloseConversation
        # (ticket #396). Natural completion leaves the conversation
        # open — the parent owns its lifecycle and decides when to
        # close it. The accordion should therefore show the nested
        # blades with a 'completed' status until the caller cleans up.
        from teaparty.bridge.state.dispatch_tree import build_dispatch_tree
        sessions_dir = os.path.join(
            _module_env[0], 'management', 'sessions')
        tree = build_dispatch_tree(
            sessions_dir, session._dispatch_session.id)
        children = tree.get('children', [])
        self.assertEqual(
            len(children), 1,
            'mid-agent is completed but NOT closed — must still be in '
            'the dispatch tree until the caller explicitly closes it. '
            'tree=%r' % tree)
        self.assertEqual(children[0]['agent_name'], 'mid-agent')
        self.assertEqual(
            len(children[0].get('children', [])), 1,
            'leaf-agent is also completed-but-not-closed and must '
            'stay nested under mid-agent in the tree.')
        self.assertEqual(
            children[0]['children'][0]['agent_name'], 'leaf-agent')

        # Regression: coordinator must be resumed EXACTLY ONCE — with
        # mid's final 'done'. Before the subtree-loop fix, mid's first
        # turn ('Dispatched leaf.') was delivered as an interim reply
        # BEFORE leaf had even run, so the coord was resumed twice:
        # once with the stale interim text and once with the real
        # answer. Two resumes here = regression.
        self.assertEqual(
            coord_resumes[0], 2,
            'coord should be invoked exactly twice (initial + one '
            'resume with the final reply), got %d; messages=%r' % (
                coord_resumes[0], coord_resume_messages))
        # And the resume must not contain the interim 'Dispatched leaf.'
        # text that mid emits on its first turn.
        self.assertTrue(
            all('Dispatched leaf' not in m for m in coord_resume_messages),
            'coord resume must not contain mid\'s interim text; '
            'messages=%r' % (coord_resume_messages,))

        # mid must have been launched twice: once to dispatch leaf,
        # once (via --resume) with leaf's reply so mid could integrate.
        self.assertEqual(mid_calls[0], 2,
                         'mid should be launched twice (first turn + '
                         'resume with leaf reply), got %d' % mid_calls[0])
        self.assertIn('leaf-done', mid_messages[1],
                      'mid\'s second launch message must contain '
                      'leaf\'s reply; got %r' % mid_messages[1])

        _close_all(session)
        self.assertEqual(len(session._dispatch_session.conversation_map), 0)


class TestTasksByChildRetention(unittest.TestCase):
    """Regression for the linear-chain race: in real claude a
    grandchild subprocess often finishes WHILE its parent's first
    _launch is still in flight (they run concurrently on the event
    loop). The parent's _run_child loop then checks _tasks_by_child
    for the grandchild's task to await it — if the dict entry was
    eagerly popped by the task's done_callback, the loop finds
    nothing, breaks, and finalizes the parent with stale first-turn
    text. OM ends up resumed with 'I'll forward…' instead of the
    actual child reply.

    Invariant: tasks must stay in _tasks_by_child after completion
    so a lagging parent loop can still find them. Cleanup happens
    on close_fn / /clear / _cancel_background_tasks, not on done.
    """

    def test_completed_task_stays_in_tasks_by_child(self):
        scripts = {
            'coordinator': _stateful_coordinator_script(
                expected_replies={'hello'},
                dispatch_events=[
                    tool_use_event('mcp__teaparty-config__Send',
                                   {'member': 'leaf-agent', 'message': 'say hello'}),
                    text_event('Dispatched.'),
                    cost_event(),
                ]),
            'leaf-agent': {
                'say hello': [text_event('hello'), cost_event()],
            },
        }
        session = _make_coordinator('retention-scripted',
                                    make_scripted_caller(scripts))

        async def run():
            _send_human(session, 'start')
            await session.invoke(cwd=_module_env[1])
            return await _wait_for_result(session, timeout=10)

        result = _run(run(), timeout=30)
        self.assertIsNotNone(result)

        # Child finished. Its conversation_map entry is still present
        # (slot not yet freed — the ticket says slots persist until
        # explicit CloseConversation). The in-flight task reference
        # must ALSO still be present in _tasks_by_child, otherwise a
        # lagging grandparent loop that tries to collect the task's
        # result on the next yield will find nothing and break.
        child_ids = list(session._dispatch_session.conversation_map.values())
        self.assertEqual(len(child_ids), 1)
        csid = child_ids[0]
        self.assertIn(
            csid, session._tasks_by_child,
            'Completed grandchild task was removed from _tasks_by_child '
            '— a lagging parent _run_child loop awaiting this task '
            'will break and finalize with stale first-turn text. '
            'Tasks must stay in the dict until close_fn / /clear.')
        self.assertTrue(session._tasks_by_child[csid].done(),
                        'task should be in the dict AND be done')

        _close_all(session)


class TestRateLimitScripted(unittest.TestCase):
    """Coordinator tries to dispatch 4 children — 4th is denied by the
    slot limit (3). After closing one, a retry succeeds."""

    def test_fourth_concurrent_send_is_denied_by_slot_limit(self):
        dispatch_calls = [0]

        def coord_script(message):
            dispatch_calls[0] += 1
            if dispatch_calls[0] == 1:
                return [
                    tool_use_event('mcp__teaparty-config__Send',
                                   {'member': 'leaf-agent', 'message': 'task 1'}),
                    tool_use_event('mcp__teaparty-config__Send',
                                   {'member': 'leaf-agent', 'message': 'task 2'}),
                    tool_use_event('mcp__teaparty-config__Send',
                                   {'member': 'leaf-agent', 'message': 'task 3'}),
                    tool_use_event('mcp__teaparty-config__Send',
                                   {'member': 'leaf-agent', 'message': 'task 4'}),
                    text_event('Four sent.'),
                    cost_event(),
                ]
            return [text_event('ack'), cost_event()]

        scripts = {
            'coordinator': coord_script,
            'leaf-agent': {
                'task': [text_event('ok'), cost_event()],
            },
        }
        session = _make_coordinator('ratelimit-scripted',
                                    make_scripted_caller(scripts))

        async def run():
            _send_human(session, 'Dispatch four tasks')
            await session.invoke(cwd=_module_env[1])
            await asyncio.sleep(0.3)

        _run(run(), timeout=30)

        # Exactly 3 children were recorded — the 4th was slot-denied.
        # (Children may have already completed and been cleaned up by
        # resume; what matters is that at no point did the map exceed 3.)
        self.assertLessEqual(len(session._dispatch_session.conversation_map), 3)

        _close_all(session)
        self.assertEqual(len(session._dispatch_session.conversation_map), 0)


class TestCloseAfterCompletionScripted(unittest.TestCase):
    """After a child completes and replies, explicit CloseConversation
    removes it from the parent's conversation_map and tears down the
    child's session directory."""

    def test_close_frees_slot_and_removes_session_dir(self):
        scripts = {
            'coordinator': _stateful_coordinator_script(
                expected_replies={'hello'},
                dispatch_events=[
                    tool_use_event('mcp__teaparty-config__Send',
                                   {'member': 'leaf-agent', 'message': 'say hello'}),
                    text_event('Dispatched.'),
                    cost_event(),
                ]),
            'leaf-agent': {
                'say hello': [text_event('hello'), cost_event()],
            },
        }
        session = _make_coordinator('close-scripted',
                                    make_scripted_caller(scripts))

        async def run():
            _send_human(session, 'Say hello')
            await session.invoke(cwd=_module_env[1])
            return await _wait_for_result(session, timeout=10)

        result = _run(run(), timeout=30)
        self.assertIsNotNone(result)

        # A child is recorded in the map.
        self.assertEqual(len(session._dispatch_session.conversation_map), 1)
        child_session_id = next(
            iter(session._dispatch_session.conversation_map.values()))
        sessions_dir = os.path.join(
            _module_env[0], 'management', 'sessions')
        child_path = os.path.join(sessions_dir, child_session_id)
        self.assertTrue(os.path.isdir(child_path))

        _close_all(session)

        # Slot freed and child session directory removed.
        self.assertEqual(len(session._dispatch_session.conversation_map), 0)
        self.assertFalse(os.path.isdir(child_path))


class TestClearFiresDispatchCompleted(unittest.TestCase):
    """/clear is the operator-initiated equivalent of 'close everything
    you own'. It must close every open top-level dispatch the same way
    CloseConversation would: fire dispatch_completed per removed
    descendant so the UI accordion tears down, rmtree the child session
    dirs, free the slots.

    Two regression scenarios:
      A) Live session — user types /clear on an active session that
         has in-memory _dispatch_session and registered close_fn.
      B) Fresh server — server restart, stale on-disk state from prior
         run, user types /clear before any other invoke. _dispatch_session
         is None and close_fn isn't even registered yet. _clear must
         still walk the on-disk state and tear it down."""

    def test_clear_closes_every_open_dispatch(self):
        dispatch_events_seen: list = []

        scripts = {
            'coordinator': _stateful_coordinator_script(
                expected_replies={'hello'},
                dispatch_events=[
                    tool_use_event('mcp__teaparty-config__Send',
                                   {'member': 'leaf-agent', 'message': 'say hello'}),
                    text_event('Dispatched.'),
                    cost_event(),
                ]),
            'leaf-agent': {
                'say hello': [text_event('hello'), cost_event()],
            },
        }
        session = _make_coordinator(
            'clear-scripted',
            make_scripted_caller(scripts),
            on_dispatch=lambda ev: dispatch_events_seen.append(ev))

        async def run():
            _send_human(session, 'Say hello')
            await session.invoke(cwd=_module_env[1])
            return await _wait_for_result(session, timeout=10)

        result = _run(run(), timeout=30)
        self.assertIsNotNone(result)

        # Confirm the dispatched child is present on disk before /clear.
        self.assertEqual(len(session._dispatch_session.conversation_map), 1)
        child_sid = next(
            iter(session._dispatch_session.conversation_map.values()))
        sessions_dir = os.path.join(
            _module_env[0], 'management', 'sessions')
        child_path = os.path.join(sessions_dir, child_sid)
        self.assertTrue(os.path.isdir(child_path))

        # Snapshot dispatch_started events up to this point so we can
        # isolate the close events from /clear.
        events_before_clear = len(dispatch_events_seen)

        # Run /clear via the invoke path (the human types '/clear').
        async def do_clear():
            _send_human(session, '/clear')
            return await session.invoke(cwd=_module_env[1])

        _run(do_clear(), timeout=30)

        # 1. dispatch_completed must have fired for the child so the UI
        # accordion removes its blade.
        new_events = dispatch_events_seen[events_before_clear:]
        completed = [e for e in new_events
                     if e.get('type') == 'dispatch_completed']
        self.assertTrue(
            any(e['child_session_id'] == child_sid for e in completed),
            '/clear must fire dispatch_completed for every open '
            'dispatch so the UI accordion tears down; saw only %r' % new_events)

        # 2. Child session directory must be gone.
        self.assertFalse(
            os.path.isdir(child_path),
            '/clear must rmtree child session dirs — otherwise a page '
            'reload would resurrect the accordion blades from stale '
            'on-disk state.')

        # 3. In-memory state fully reset.
        self.assertIsNone(session._dispatch_session)

    def test_clear_on_fresh_session_walks_disk_state(self):
        """Scenario B: server restart, stale on-disk dispatch from a
        prior run, user types /clear before anything else. In this
        state _dispatch_session is None (lazy-initialized later in
        invoke) and close_fn is not registered yet. _clear must still
        load the dispatch session from disk and tear down the
        descendants so the UI accordion and session dirs clean up."""
        dispatch_events_seen: list = []

        # --- Phase 1: create a stale dispatch on disk ------------------
        scripts1 = {
            'coordinator': _stateful_coordinator_script(
                expected_replies={'hello'},
                dispatch_events=[
                    tool_use_event('mcp__teaparty-config__Send',
                                   {'member': 'leaf-agent', 'message': 'say hello'}),
                    text_event('Dispatched.'),
                    cost_event(),
                ]),
            'leaf-agent': {
                'say hello': [text_event('hello'), cost_event()],
            },
        }
        session1 = _make_coordinator(
            'clear-fresh-scripted',
            make_scripted_caller(scripts1))

        async def run1():
            _send_human(session1, 'Say hello')
            await session1.invoke(cwd=_module_env[1])
            return await _wait_for_result(session1, timeout=10)

        _run(run1(), timeout=30)
        self.assertEqual(len(session1._dispatch_session.conversation_map), 1)
        child_sid = next(
            iter(session1._dispatch_session.conversation_map.values()))
        sessions_dir = os.path.join(
            _module_env[0], 'management', 'sessions')
        child_path = os.path.join(sessions_dir, child_sid)
        self.assertTrue(os.path.isdir(child_path))

        # Simulate server shutdown: stop the bus listener and drop the
        # AgentSession entirely. The on-disk session dirs remain.
        async def stop1():
            await session1.stop()
        _run(stop1(), timeout=10)
        del session1

        # --- Phase 2: new AgentSession (fresh server) ------------------
        # Same qualifier → same session_key → loads the same on-disk
        # dispatch_session metadata. But _dispatch_session in memory
        # is None until _ensure_bus_listener runs, and close_fn isn't
        # in the registry yet.
        scripts2 = {
            'coordinator': lambda m: [text_event('ack'), cost_event()],
            'leaf-agent': {
                'say hello': [text_event('hello'), cost_event()],
            },
        }
        session2 = _make_coordinator(
            'clear-fresh-scripted',
            make_scripted_caller(scripts2),
            on_dispatch=lambda ev: dispatch_events_seen.append(ev))

        # Sanity: at this point session2 has not been invoked, so
        # _dispatch_session is None — the fresh-server state.
        self.assertIsNone(session2._dispatch_session)

        # But the stale child is still on disk.
        self.assertTrue(os.path.isdir(child_path))

        # Run /clear. This must walk the on-disk state and tear it down.
        async def do_clear():
            _send_human(session2, '/clear')
            return await session2.invoke(cwd=_module_env[1])

        _run(do_clear(), timeout=30)

        # 1. dispatch_completed fired for the stale child.
        completed = [e for e in dispatch_events_seen
                     if e.get('type') == 'dispatch_completed']
        self.assertTrue(
            any(e['child_session_id'] == child_sid for e in completed),
            '/clear on a fresh server must load stale dispatch state '
            'from disk and fire dispatch_completed for every child; '
            'saw only %r' % dispatch_events_seen)

        # 2. Stale session directory is gone.
        self.assertFalse(
            os.path.isdir(child_path),
            '/clear on a fresh server must rmtree stale child session '
            'dirs — otherwise the accordion comes back on next reload.')


class TestRateLimitRetryScripted(unittest.TestCase):
    """After the 4th Send is denied, the coordinator closes one child
    and the retry Send succeeds."""

    def test_close_one_then_retry_fourth_succeeds(self):
        # Drive the coordinator by replaying scripted turns manually.
        scripts = {
            'coordinator': lambda m: [text_event('ack'), cost_event()],
            'leaf-agent': {
                'task': [text_event('ok'), cost_event()],
            },
        }
        session = _make_coordinator('ratelimit-retry',
                                    make_scripted_caller(scripts))

        from teaparty.mcp.registry import (
            current_agent_name, current_session_id, get_spawn_fn,
        )
        from teaparty.workspace.close_conversation import close_conversation

        async def run():
            _send_human(session, 'start')
            await session.invoke(cwd=_module_env[1])
            # Manually invoke spawn_fn four times in the coordinator's
            # context — same entry point the MCP Send handler uses.
            a = current_agent_name.set('coordinator')
            s = current_session_id.set(session._dispatch_session.id)
            try:
                spawn_fn = get_spawn_fn('coordinator')
                r1 = await spawn_fn('leaf-agent', 'task 1', 'c1')
                r2 = await spawn_fn('leaf-agent', 'task 2', 'c2')
                r3 = await spawn_fn('leaf-agent', 'task 3', 'c3')
                r4 = await spawn_fn('leaf-agent', 'task 4', 'c4')
                # r4 should be denied — ('', '', '')
                self.assertEqual(r4[0], '', 'slot limit should deny 4th')
                # Close the first child to free a slot
                close_conversation(
                    session._dispatch_session,
                    f'dispatch:{r1[0]}',
                    teaparty_home=_module_env[0], scope='management')
                # Retry
                r4b = await spawn_fn('leaf-agent', 'task 4', 'c4')
                self.assertNotEqual(r4b[0], '', 'retry after close should succeed')
            finally:
                current_session_id.reset(s)
                current_agent_name.reset(a)
            await asyncio.sleep(0.3)

        _run(run(), timeout=30)
        _close_all(session)
        self.assertEqual(len(session._dispatch_session.conversation_map), 0)


class TestCloseMidFlightScripted(unittest.TestCase):
    """Child is still running when CloseConversation fires. The child's
    background task is cancelled, worktree/session removed, slot freed."""

    def test_running_child_is_killed_on_close(self):
        child_started = asyncio.Event()
        release = asyncio.Event()

        async def hang_script(message):
            child_started.set()
            await release.wait()  # cancelled by close_fn
            return [text_event('never'), cost_event()]

        scripts = {
            'coordinator': lambda m: [
                tool_use_event('mcp__teaparty-config__Send',
                               {'member': 'leaf-agent', 'message': 'hang'}),
                text_event('Dispatched.'),
                cost_event(),
            ],
            'leaf-agent': hang_script,
        }
        session = _make_coordinator('close-midflight',
                                    make_scripted_caller(scripts))

        async def run():
            _send_human(session, 'start')
            await session.invoke(cwd=_module_env[1])
            await asyncio.wait_for(child_started.wait(), timeout=5)

            conv_ids = _get_handles(session)
            self.assertEqual(len(conv_ids), 1)
            csid = conv_ids[0][len('dispatch:'):]
            child_path = os.path.join(
                _module_env[0], 'management', 'sessions', csid)
            self.assertTrue(os.path.isdir(child_path))

            # Task should currently be running (not done).
            task = session._tasks_by_child.get(csid)
            self.assertIsNotNone(task)
            self.assertFalse(task.done())

            from teaparty.mcp.registry import get_close_fn
            close_fn = get_close_fn('coordinator')
            await close_fn(conv_ids[0])

            # Post-conditions: slot freed, session dir gone, task cancelled.
            self.assertEqual(
                len(session._dispatch_session.conversation_map), 0)
            self.assertFalse(os.path.isdir(child_path))
            self.assertTrue(task.done())

        try:
            _run(run(), timeout=30)
        finally:
            release.set()


class TestRecursiveCloseScripted(unittest.TestCase):
    """A → B → C. Closing the A→B conversation must also tear down C's
    session (grandchild cleanup) and free slots at every level."""

    def test_close_parent_removes_grandchild(self):
        grandchild_started = asyncio.Event()
        release = asyncio.Event()
        dispatch_events_seen: list = []

        async def hang_leaf(message):
            grandchild_started.set()
            await release.wait()
            return [text_event('never'), cost_event()]

        scripts = {
            'coordinator': lambda m: [
                tool_use_event('mcp__teaparty-config__Send',
                               {'member': 'mid-agent', 'message': 'descend'}),
                text_event('Dispatched.'),
                cost_event(),
            ],
            'mid-agent': lambda m: [
                tool_use_event('mcp__teaparty-config__Send',
                               {'member': 'leaf-agent', 'message': 'hang'}),
                text_event('Dispatched leaf.'),
                cost_event(),
            ],
            'leaf-agent': hang_leaf,
        }
        session = _make_coordinator(
            'recursive-close',
            make_scripted_caller(scripts),
            on_dispatch=lambda ev: dispatch_events_seen.append(ev))

        async def run():
            _send_human(session, 'start')
            await session.invoke(cwd=_module_env[1])
            await asyncio.wait_for(grandchild_started.wait(), timeout=5)

            # Coordinator has one child (mid); mid has one child (leaf).
            mid_handles = _get_handles(session)
            self.assertEqual(len(mid_handles), 1)
            mid_csid = mid_handles[0][len('dispatch:'):]
            sessions_dir = os.path.join(
                _module_env[0], 'management', 'sessions')
            mid_path = os.path.join(sessions_dir, mid_csid)
            self.assertTrue(os.path.isdir(mid_path))

            # Read mid's metadata to find the grandchild
            with open(os.path.join(mid_path, 'metadata.json')) as f:
                mid_meta = json.load(f)
            grand_map = mid_meta.get('conversation_map', {})
            self.assertEqual(len(grand_map), 1,
                             'mid-agent should have dispatched one grandchild')
            grand_csid = next(iter(grand_map.values()))
            grand_path = os.path.join(sessions_dir, grand_csid)
            self.assertTrue(os.path.isdir(grand_path))

            # Capture the in-flight tasks BEFORE closing so we can
            # assert they were actually cancelled (not just orphaned).
            mid_task = session._tasks_by_child.get(mid_csid)
            grand_task = session._tasks_by_child.get(grand_csid)
            self.assertIsNotNone(grand_task, 'grandchild task must be tracked')
            self.assertFalse(grand_task.done(),
                             'grandchild must still be running before close')

            # Close the coordinator→mid conversation.
            from teaparty.mcp.registry import get_close_fn
            close_fn = get_close_fn('coordinator')
            await close_fn(mid_handles[0])

            # Both mid and grandchild must be gone from the filesystem,
            # AND their in-flight tasks must be cancelled. Without task
            # cancellation, a real claude subprocess would outlive the
            # close — the ticket explicitly requires the kill.
            self.assertEqual(
                len(session._dispatch_session.conversation_map), 0)
            self.assertFalse(os.path.isdir(mid_path))
            self.assertFalse(os.path.isdir(grand_path))
            if mid_task is not None:
                self.assertTrue(mid_task.done(), 'mid task must be cancelled')
            self.assertTrue(grand_task.done(),
                            'grandchild task must be cancelled recursively')

            # UI accordion auto-activation: close_fn must emit a
            # dispatch_completed event for every removed session, so
            # the frontend moves the user from whatever they were
            # viewing up to the parent. Previously this only happened
            # on normal completion, not explicit CloseConversation.
            completed = [e for e in dispatch_events_seen
                         if e.get('type') == 'dispatch_completed']
            closed_ids = {e['child_session_id'] for e in completed}
            self.assertIn(grand_csid, closed_ids,
                          'grandchild close must emit dispatch_completed')
            self.assertIn(mid_csid, closed_ids,
                          'mid close must emit dispatch_completed')
            # The grandchild event must point to mid as its parent;
            # the mid event must point to the coordinator session.
            for e in completed:
                if e['child_session_id'] == grand_csid:
                    self.assertEqual(e['parent_session_id'], mid_csid,
                                     'grandchild parent should be mid')
                if e['child_session_id'] == mid_csid:
                    self.assertEqual(
                        e['parent_session_id'],
                        session._dispatch_session.id,
                        'mid parent should be coordinator')

        try:
            _run(run(), timeout=30)
        finally:
            release.set()


class TestDiamondDispatchScripted(unittest.TestCase):
    """A → B, A → C; B → D, C → D. Two instances of D run concurrently
    under two different parents. Each D reply routes back to the right
    parent by its own conversation_id."""

    def test_two_d_instances_route_to_correct_parents(self):

        # mid-agent dispatches its leaf with a branch-specific payload so
        # the two leaf instances produce distinct labels.
        def mid_script(message):
            if 'branch b' in message:
                return [
                    tool_use_event('mcp__teaparty-config__Send',
                                   {'member': 'leaf-agent', 'message': 'd-from-b'}),
                    text_event('mid b dispatched leaf'),
                    cost_event(),
                ]
            if 'branch c' in message:
                return [
                    tool_use_event('mcp__teaparty-config__Send',
                                   {'member': 'leaf-agent', 'message': 'd-from-c'}),
                    text_event('mid c dispatched leaf'),
                    cost_event(),
                ]
            # Resume after leaf reply — echo it upward.
            label = 'd-from-b' if 'd-from-b' in message else 'd-from-c'
            return [text_event(label), cost_event()]

        scripts = {
            'coordinator': _stateful_coordinator_script(
                expected_replies={'d-from-b', 'd-from-c'},
                dispatch_events=[
                    tool_use_event('mcp__teaparty-config__Send',
                                   {'member': 'mid-agent', 'message': 'branch b'}),
                    tool_use_event('mcp__teaparty-config__Send',
                                   {'member': 'mid-agent', 'message': 'branch c'}),
                    text_event('Two branches dispatched.'),
                    cost_event(),
                ]),
            'mid-agent': mid_script,
            'leaf-agent': {
                'd-from-b': [text_event('d-from-b'), cost_event()],
                'd-from-c': [text_event('d-from-c'), cost_event()],
            },
        }
        session = _make_coordinator('diamond-scripted',
                                    make_scripted_caller(scripts))

        async def run():
            _send_human(session, 'Run diamond')
            await session.invoke(cwd=_module_env[1])
            return await _wait_for_result(session, timeout=10)

        result = _run(run(), timeout=30)
        self.assertIsNotNone(result, 'Coordinator must produce RESULT')
        self.assertIn('d-from-b', result)
        self.assertIn('d-from-c', result)

        # Both mid-agents dispatched a leaf — verify two independent
        # D instances existed by inspecting metadata on the two mid
        # session dirs.
        sessions_dir = os.path.join(_module_env[0], 'management', 'sessions')
        mid_ids = list(session._dispatch_session.conversation_map.values())
        self.assertEqual(len(mid_ids), 2, 'two mid-agents should be recorded')
        leaf_ids = set()
        for mid_id in mid_ids:
            meta_path = os.path.join(sessions_dir, mid_id, 'metadata.json')
            with open(meta_path) as f:
                meta = json.load(f)
            for leaf_id in meta.get('conversation_map', {}).values():
                leaf_ids.add(leaf_id)
        self.assertEqual(len(leaf_ids), 2,
                         'two independent leaf (D) instances should exist')

        _close_all(session)
        self.assertEqual(len(session._dispatch_session.conversation_map), 0)


if __name__ == '__main__':
    unittest.main()
