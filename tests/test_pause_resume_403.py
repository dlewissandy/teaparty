"""Specification tests for issue #403: project pause / resume with phase-based faithful resume.

These tests exercise the real dispatch machinery with a mocked _launch,
the same pattern used by #395/#396 regression tests. They verify:

1. ``_run_child`` writes an accurate ``phase`` field on every transition.
2. ``mark_complete`` records the final ``response_text``.
3. ``pause_project_subtree`` cancels only the targeted project's tasks
   and leaves the recorded phase on disk.
4. ``resume_project_subtree`` skips LLM re-invocation for sessions that
   were in ``complete`` or ``awaiting`` at pause time, and only re-runs
   a claude turn for sessions in ``launching``.
5. ``spawn_fn`` refuses new dispatches while the project is paused.
6. Cross-project isolation: pausing project A does not touch project B.
7. The Pause All / Resume All buttons no longer emit the seedBlade
   strings (grep-based CI check).
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from unittest.mock import patch

from teaparty.messaging.conversations import ConversationType
from teaparty.runners.launcher import (
    Session,
    create_session,
    load_session,
    mark_launching,
    mark_awaiting,
    mark_complete,
    _save_session_metadata,
)
from teaparty.workspace.pause_resume import (
    collect_project_subtree,
    pause_project_subtree,
    resume_project_subtree,
)


def _make_teaparty_home():
    tmpdir = tempfile.mkdtemp()
    os.makedirs(os.path.join(tmpdir, 'management', 'sessions'))
    os.makedirs(os.path.join(tmpdir, 'management', 'agents', 'parent'))
    return tmpdir


@dataclass
class FakeLaunchResult:
    exit_code: int = 0
    session_id: str = 'fake-claude-session'
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 100


class TestPhaseFieldPersistence(unittest.TestCase):
    """mark_launching/mark_awaiting/mark_complete update metadata.json.

    Read-modify-write must preserve every other field so a concurrent
    update to conversation_map is not clobbered.
    """

    def setUp(self):
        self._tmpdir = _make_teaparty_home()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_mark_launching_persists(self):
        s = create_session(
            agent_name='a', scope='management', teaparty_home=self._tmpdir)
        s.conversation_map = {'r1': 'child-sid'}
        _save_session_metadata(s)

        mark_launching(s, 'hello there')

        loaded = load_session(
            agent_name='a', scope='management',
            teaparty_home=self._tmpdir, session_id=s.id)
        self.assertEqual(loaded.phase, 'launching')
        self.assertEqual(loaded.current_message, 'hello there')
        # Unrelated fields preserved.
        self.assertEqual(loaded.conversation_map, {'r1': 'child-sid'})

    def test_mark_awaiting_stores_gc_ids(self):
        s = create_session(
            agent_name='a', scope='management', teaparty_home=self._tmpdir)
        mark_awaiting(s, ['gc1', 'gc2'])
        loaded = load_session(
            agent_name='a', scope='management',
            teaparty_home=self._tmpdir, session_id=s.id)
        self.assertEqual(loaded.phase, 'awaiting')
        self.assertEqual(loaded.in_flight_gc_ids, ['gc1', 'gc2'])

    def test_mark_complete_records_response_text(self):
        s = create_session(
            agent_name='a', scope='management', teaparty_home=self._tmpdir)
        mark_complete(s, 'the final integrated reply')
        loaded = load_session(
            agent_name='a', scope='management',
            teaparty_home=self._tmpdir, session_id=s.id)
        self.assertEqual(loaded.phase, 'complete')
        self.assertEqual(loaded.response_text, 'the final integrated reply')


class TestCollectProjectSubtree(unittest.TestCase):
    """The walker finds every in-project session rooted at top-level jobs."""

    def setUp(self):
        self._tmpdir = _make_teaparty_home()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _mk(self, sid, slug, parent=''):
        path = os.path.join(self._tmpdir, 'management', 'sessions', sid)
        os.makedirs(path, exist_ok=True)
        meta = {
            'session_id': sid,
            'agent_name': 'x',
            'scope': 'management',
            'claude_session_id': '',
            'conversation_map': {},
            'phase': 'launching',
            'response_text': '',
            'project_slug': slug,
            'parent_session_id': parent,
        }
        with open(os.path.join(path, 'metadata.json'), 'w') as f:
            json.dump(meta, f)
        return sid

    def _link(self, parent_sid, request_id, child_sid):
        path = os.path.join(
            self._tmpdir, 'management', 'sessions', parent_sid, 'metadata.json')
        with open(path) as f:
            meta = json.load(f)
        meta['conversation_map'][request_id] = child_sid
        with open(path, 'w') as f:
            json.dump(meta, f)

    def test_cross_project_isolation(self):
        """Walker on project A returns only A's sessions."""
        self._mk('a-root', 'alpha')
        self._mk('a-child', 'alpha', parent='a-root')
        self._link('a-root', 'r1', 'a-child')
        self._mk('b-root', 'beta')
        self._mk('b-child', 'beta', parent='b-root')
        self._link('b-root', 'r1', 'b-child')

        sessions_dir = os.path.join(self._tmpdir, 'management', 'sessions')
        alpha = {sid for sid, _ in collect_project_subtree(sessions_dir, 'alpha')}
        beta = {sid for sid, _ in collect_project_subtree(sessions_dir, 'beta')}

        self.assertEqual(alpha, {'a-root', 'a-child'})
        self.assertEqual(beta, {'b-root', 'b-child'})


class _FakeAgentSession:
    """Minimal stand-in for AgentSession used by pause/resume_project_subtree."""
    def __init__(self):
        self._tasks_by_child: dict = {}
        self._background_tasks: set = set()
        self._run_child_factories: dict = {}


class TestPauseResumeMechanics(unittest.IsolatedAsyncioTestCase):
    """End-to-end pause/resume on a fake AgentSession."""

    def setUp(self):
        self._tmpdir = _make_teaparty_home()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _mk_session(self, sid, slug, phase, *,
                    parent='', response_text='', gc_ids=None,
                    current_message='', claude_sid=''):
        path = os.path.join(self._tmpdir, 'management', 'sessions', sid)
        os.makedirs(path, exist_ok=True)
        meta = {
            'session_id': sid,
            'agent_name': 'x',
            'scope': 'management',
            'claude_session_id': claude_sid,
            'conversation_map': {},
            'phase': phase,
            'response_text': response_text,
            'project_slug': slug,
            'parent_session_id': parent,
            'current_message': current_message,
            'in_flight_gc_ids': list(gc_ids or []),
            'initial_message': '',
        }
        with open(os.path.join(path, 'metadata.json'), 'w') as f:
            json.dump(meta, f)

    async def test_pause_cancels_only_target_project_tasks(self):
        self._mk_session('a-root', 'alpha', 'launching')
        self._mk_session('b-root', 'beta', 'launching')

        agent_session = _FakeAgentSession()

        # Long-running tasks representing in-flight _run_child runs.
        async def never_ending():
            await asyncio.sleep(60)
            return 'x'

        a_task = asyncio.create_task(never_ending())
        b_task = asyncio.create_task(never_ending())
        agent_session._tasks_by_child['a-root'] = a_task
        agent_session._tasks_by_child['b-root'] = b_task

        sessions_dir = os.path.join(
            self._tmpdir, 'management', 'sessions')
        paused = await pause_project_subtree(
            'alpha', sessions_dir, agent_session)

        self.assertEqual(set(paused), {'a-root'})
        self.assertTrue(a_task.cancelled() or a_task.done())
        self.assertFalse(b_task.done())
        b_task.cancel()
        try:
            await b_task
        except asyncio.CancelledError:
            pass

    async def test_resume_complete_phase_uses_stored_response(self):
        """A session in 'complete' phase resumes instantly via stored text,
        with no LLM re-invocation."""
        self._mk_session(
            'root', 'alpha', 'complete',
            response_text='the final answer')
        agent_session = _FakeAgentSession()
        sessions_dir = os.path.join(
            self._tmpdir, 'management', 'sessions')

        resumed = await resume_project_subtree(
            'alpha', sessions_dir, agent_session)

        self.assertEqual(resumed, ['root'])
        task = agent_session._tasks_by_child['root']
        result = await task
        self.assertEqual(result, 'the final answer')

    async def test_resume_without_factory_logs_and_skips(self):
        """Cross-restart case (no factory registered) is not fatal."""
        self._mk_session('root', 'alpha', 'launching')
        agent_session = _FakeAgentSession()
        sessions_dir = os.path.join(
            self._tmpdir, 'management', 'sessions')
        resumed = await resume_project_subtree(
            'alpha', sessions_dir, agent_session)
        # root has no factory → skipped (the warning path).
        self.assertEqual(resumed, [])

    async def test_resume_launching_phase_invokes_factory(self):
        """A 'launching' phase resume calls the factory with resume_session
        set to the persisted claude_session_id."""
        self._mk_session(
            'root', 'alpha', 'launching',
            claude_sid='claude-abc',
            current_message='original prompt')

        calls: list[dict] = []

        def factory(**kwargs):
            calls.append(kwargs)
            async def _c():
                return 're-ran answer'
            return _c()

        agent_session = _FakeAgentSession()
        agent_session._run_child_factories['root'] = factory
        sessions_dir = os.path.join(
            self._tmpdir, 'management', 'sessions')

        resumed = await resume_project_subtree(
            'alpha', sessions_dir, agent_session)
        self.assertEqual(resumed, ['root'])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['start_at_phase'], 'launching')
        self.assertEqual(calls[0]['resume_claude_session'], 'claude-abc')
        task = agent_session._tasks_by_child['root']
        self.assertEqual(await task, 're-ran answer')

    async def test_resume_awaiting_phase_invokes_factory_with_gc_ids(self):
        """An 'awaiting' phase resume calls the factory with the stored
        in_flight_gc_ids so gather can be re-entered without relaunching
        claude for the current turn."""
        self._mk_session(
            'root', 'alpha', 'awaiting',
            gc_ids=['g1', 'g2'],
            claude_sid='claude-xyz')

        calls: list[dict] = []

        def factory(**kwargs):
            calls.append(kwargs)
            async def _c():
                return 'gather-reentry result'
            return _c()

        agent_session = _FakeAgentSession()
        agent_session._run_child_factories['root'] = factory
        sessions_dir = os.path.join(
            self._tmpdir, 'management', 'sessions')

        await resume_project_subtree('alpha', sessions_dir, agent_session)

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['start_at_phase'], 'awaiting')
        self.assertEqual(calls[0]['initial_gc_task_ids'], ['g1', 'g2'])
        self.assertEqual(calls[0]['resume_claude_session'], 'claude-xyz')


class TestPausedSpawnRefusal(unittest.IsolatedAsyncioTestCase):
    """spawn_fn refuses to create new child tasks while the project is
    paused (the flag is checked via the paused_check callable)."""

    def setUp(self):
        self._tmpdir = _make_teaparty_home()
        for name in ['parent', 'agent-b']:
            agent_dir = os.path.join(
                self._tmpdir, 'management', 'agents', name)
            os.makedirs(agent_dir, exist_ok=True)
            with open(os.path.join(agent_dir, 'agent.md'), 'w') as f:
                f.write(f'---\nname: {name}\ndescription: test\n---\n')
        create_session(
            agent_name='parent', scope='management',
            teaparty_home=self._tmpdir, session_id='parent-test')

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _make_session(self, paused_check=None):
        from teaparty.teams.session import AgentSession
        return AgentSession(
            self._tmpdir,
            agent_name='parent',
            scope='management',
            qualifier='test',
            conversation_type=ConversationType.OFFICE_MANAGER,
            dispatches=True,
            project_slug='alpha',
            paused_check=paused_check,
        )

    async def test_spawn_blocked_when_paused(self):
        paused = {'flag': True}
        session = self._make_session(
            paused_check=lambda: paused['flag'])

        async def fake_launch(**kwargs):
            return FakeLaunchResult(session_id='x')

        with patch('teaparty.runners.launcher.launch', fake_launch), \
                patch('teaparty.config.roster.has_sub_roster', return_value=False), \
                patch('subprocess.run'):
            await session._ensure_bus_listener(self._tmpdir)
            from teaparty.mcp.registry import get_spawn_fn
            spawn_fn = get_spawn_fn('parent')
            sid, wt, ctx = await spawn_fn('agent-b', 'task', 'r1')

        # Empty tuple → dispatch refused.
        self.assertEqual(sid, '')
        await session.stop()

    async def test_spawn_allowed_when_not_paused(self):
        session = self._make_session(paused_check=lambda: False)

        async def fake_launch(**kwargs):
            return FakeLaunchResult(session_id='x')

        with patch('teaparty.runners.launcher.launch', fake_launch), \
                patch('teaparty.config.roster.has_sub_roster', return_value=False), \
                patch('subprocess.run'):
            await session._ensure_bus_listener(self._tmpdir)
            from teaparty.mcp.registry import get_spawn_fn
            spawn_fn = get_spawn_fn('parent')
            sid, wt, ctx = await spawn_fn('agent-b', 'task', 'r1')

        self.assertNotEqual(sid, '')
        await session.stop()


class TestUIGrepCheck(unittest.TestCase):
    """The old seedBlade-based Pause/Restart buttons must be gone from
    the frontend (issue #403, success criterion 12)."""

    def test_seedBlade_pause_restart_not_present(self):
        static_dir = os.path.join(
            os.path.dirname(__file__), '..',
            'teaparty', 'bridge', 'static')
        static_dir = os.path.normpath(static_dir)
        self.assertTrue(os.path.isdir(static_dir), static_dir)
        bad = [
            "seedBlade('Please pause",
            "seedBlade('Please restart",
            "Restart All",
        ]
        for root, _, files in os.walk(static_dir):
            for f in files:
                if not f.endswith('.html'):
                    continue
                p = os.path.join(root, f)
                with open(p) as fh:
                    content = fh.read()
                for needle in bad:
                    self.assertNotIn(
                        needle, content,
                        f'forbidden string {needle!r} still present in {p}')


class TestPauseResumeIntegration(unittest.IsolatedAsyncioTestCase):
    """End-to-end integration tests: dispatch a real tree through the real
    ``AgentSession`` + ``_run_child`` loop, count claude invocations via a
    scripted ``_launch``, pause mid-flight, resume, and verify the
    phase-based faithfulness invariant.

    These are the load-bearing tests for issue #403: they fail if the
    phase markers are removed from the subtree loop, if the resume walker
    re-enters via the wrong entry point, or if the cancellation path
    leaves the tree in an inconsistent state.
    """

    def setUp(self):
        self._tmpdir = _make_teaparty_home()
        for name in ['parent', 'agent-b', 'agent-c']:
            agent_dir = os.path.join(
                self._tmpdir, 'management', 'agents', name)
            os.makedirs(agent_dir, exist_ok=True)
            with open(os.path.join(agent_dir, 'agent.md'), 'w') as f:
                f.write(f'---\nname: {name}\ndescription: test\n---\n')
        create_session(
            agent_name='parent', scope='management',
            teaparty_home=self._tmpdir, session_id='parent-test')

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _make_session(self, project_slug='alpha', paused_check=None):
        from teaparty.teams.session import AgentSession
        return AgentSession(
            self._tmpdir,
            agent_name='parent',
            scope='management',
            qualifier='test',
            conversation_type=ConversationType.OFFICE_MANAGER,
            dispatches=True,
            project_slug=project_slug,
            paused_check=paused_check,
        )

    async def test_pause_captures_correct_phases_on_disk(self):
        """Dispatch a single-level job, pause while claude is running,
        verify phase='launching' is recorded on disk and the task is gone
        from _tasks_by_child."""
        b_launched = asyncio.Event()
        b_release = asyncio.Event()
        launch_calls: list[str] = []

        async def fake_launch(**kwargs):
            agent = kwargs.get('agent_name', '')
            launch_calls.append(agent)
            if agent == 'agent-b':
                b_launched.set()
                await b_release.wait()  # block until pause cancels us
                if kwargs.get('on_stream_event'):
                    kwargs['on_stream_event']({
                        'type': 'assistant',
                        'message': {'content': [
                            {'type': 'text', 'text': 'B says done'}]},
                    })
            return FakeLaunchResult(session_id=f'claude-{agent}')

        session = self._make_session()

        with patch('teaparty.runners.launcher.launch', fake_launch), \
                patch('teaparty.config.roster.has_sub_roster', return_value=False), \
                patch('subprocess.run'):
            await session._ensure_bus_listener(self._tmpdir)
            from teaparty.mcp.registry import get_spawn_fn
            spawn_fn = get_spawn_fn('parent')

            b_sid, _, _ = await spawn_fn('agent-b', 'task B', 'a-b')
            self.assertTrue(b_sid)

            # Wait until _run_child has entered _launch (phase=launching)
            await asyncio.wait_for(b_launched.wait(), timeout=2.0)

            # Now pause alpha. This cancels the task while it's awaiting
            # in _launch; mark_launching was called before the await so
            # phase='launching' is on disk.
            sessions_dir = os.path.join(
                self._tmpdir, 'management', 'sessions')
            await pause_project_subtree('alpha', sessions_dir, session)

            # Phase on disk is 'launching'.
            loaded = load_session(
                agent_name='agent-b', scope='management',
                teaparty_home=self._tmpdir, session_id=b_sid)
            self.assertEqual(loaded.phase, 'launching')
            self.assertEqual(loaded.current_message, 'task B')

            # Task is gone from _tasks_by_child.
            self.assertNotIn(b_sid, session._tasks_by_child)

            # No claude process for agent-b finished (cancelled mid-await).
            self.assertEqual(launch_calls, ['agent-b'])

            b_release.set()  # release any lingering wait
            await session.stop()

    async def test_resume_awaiting_phase_does_not_relaunch_parent(self):
        """B dispatches to C, pause while B is awaiting C's gather,
        resume, assert B's claude is NOT relaunched for the already-
        completed turn (faithfulness invariant for awaiting sessions)."""

        c_launched = asyncio.Event()
        c_release = asyncio.Event()
        launch_counts: dict[str, int] = {}

        async def fake_launch(**kwargs):
            agent = kwargs.get('agent_name', '')
            launch_counts[agent] = launch_counts.get(agent, 0) + 1
            on_event = kwargs.get('on_stream_event')
            session_id = kwargs.get('session_id', '')

            if agent == 'agent-b' and launch_counts[agent] == 1:
                # First turn: dispatch to C, then return.
                from teaparty.mcp.registry import (
                    get_spawn_fn, current_session_id,
                )
                token = current_session_id.set(session_id)
                try:
                    spawn = get_spawn_fn('parent')
                    if spawn:
                        await spawn('agent-c', 'task for C', 'b-to-c')
                finally:
                    current_session_id.reset(token)
                if on_event:
                    on_event({
                        'type': 'assistant',
                        'message': {'content': [
                            {'type': 'text',
                             'text': 'B turn-1 text'}]},
                    })
                return FakeLaunchResult(session_id='claude-b')

            if agent == 'agent-c':
                c_launched.set()
                await c_release.wait()
                if on_event:
                    on_event({
                        'type': 'assistant',
                        'message': {'content': [
                            {'type': 'text', 'text': 'C reply'}]},
                    })
                return FakeLaunchResult(session_id='claude-c')

            # B's second turn (after gather returns with C's reply)
            if on_event:
                on_event({
                    'type': 'assistant',
                    'message': {'content': [
                        {'type': 'text',
                         'text': 'B turn-2 integrated'}]},
                })
            return FakeLaunchResult(session_id='claude-b')

        session = self._make_session()

        with patch('teaparty.runners.launcher.launch', fake_launch), \
                patch('teaparty.config.roster.has_sub_roster', return_value=True), \
                patch('subprocess.run'):
            await session._ensure_bus_listener(self._tmpdir)
            from teaparty.mcp.registry import get_spawn_fn
            spawn_fn = get_spawn_fn('parent')

            b_sid, _, _ = await spawn_fn('agent-b', 'task B', 'a-b')

            # Wait until C is running — at this point B has finished its
            # first _launch and is awaiting gather on C.
            await asyncio.wait_for(c_launched.wait(), timeout=2.0)
            # Give the event loop a tick to record B's awaiting phase.
            await asyncio.sleep(0.05)

            sessions_dir = os.path.join(
                self._tmpdir, 'management', 'sessions')
            await pause_project_subtree('alpha', sessions_dir, session)

            # B on disk must be 'awaiting'; C must be 'launching'.
            b_meta = load_session(
                agent_name='agent-b', scope='management',
                teaparty_home=self._tmpdir, session_id=b_sid)
            self.assertEqual(b_meta.phase, 'awaiting')
            self.assertEqual(len(b_meta.in_flight_gc_ids), 1)

            b_first_turn_count = launch_counts.get('agent-b', 0)
            self.assertEqual(b_first_turn_count, 1)

            # Resume. B should NOT be re-launched for its already-
            # completed turn; C will be re-launched (its turn was killed
            # mid-_launch, phase='launching').
            c_release.set()
            await resume_project_subtree('alpha', sessions_dir, session)

            # Let the resumed tree make progress. The resumed C-task
            # re-enters _launch (count += 1). B's re-entered task starts
            # at gather, collects C's reply, then does ONE more _launch
            # for turn-2. So agent-b ends at exactly 2 launches — the
            # initial turn-1 and the post-gather turn-2.
            await asyncio.sleep(0.4)

            # Faithfulness invariant: B was in 'awaiting' at pause time.
            # Its first-turn _launch must NOT have been re-run — otherwise
            # B would be at 3 launches total.
            self.assertLessEqual(
                launch_counts.get('agent-b', 0), 2,
                f'B was re-launched unnecessarily: {launch_counts}')

            await session.stop()


if __name__ == '__main__':
    unittest.main()
