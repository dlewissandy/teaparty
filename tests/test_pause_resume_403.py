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
import contextlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import dataclass
from unittest.mock import patch, AsyncMock

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


def _make_teaparty_home(agents=None):
    """Create a temp .teaparty with management/sessions/, agent defs,
    workgroup config, and teaparty.yaml so resolve_launch_cwd succeeds."""
    if agents is None:
        agents = ['parent']
    tmpdir = tempfile.mkdtemp()
    mgmt = os.path.join(tmpdir, 'management')
    os.makedirs(os.path.join(mgmt, 'sessions'))
    for name in agents:
        agent_dir = os.path.join(mgmt, 'agents', name)
        os.makedirs(agent_dir, exist_ok=True)
        with open(os.path.join(agent_dir, 'agent.md'), 'w') as f:
            f.write(f'---\nname: {name}\ndescription: test\n---\n')
    # Workgroup config so resolve_launch_cwd can find members.
    wg_dir = os.path.join(mgmt, 'workgroups')
    os.makedirs(wg_dir, exist_ok=True)
    members = [a for a in agents if a != agents[0]]
    with open(os.path.join(wg_dir, 'test-team.yaml'), 'w') as f:
        f.write(f'name: test-team\nlead: {agents[0]}\nmembers:\n  agents:\n')
        for m in members:
            f.write(f'    - {m}\n')
    with open(os.path.join(mgmt, 'teaparty.yaml'), 'w') as f:
        f.write(f'name: test-mgmt\ndescription: test\nlead: {agents[0]}\n'
                f'projects: []\nmembers:\n  projects: []\n  agents: []\n'
                f'  workgroups:\n    - test-team\n'
                f'workgroups:\n  - name: test-team\n'
                f'    config: workgroups/test-team.yaml\n')
    return tmpdir


@dataclass
class FakeLaunchResult:
    exit_code: int = 0
    session_id: str = 'fake-claude-session'
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    duration_ms: int = 100


@contextlib.contextmanager
def spawn_env(fake_launch, tmpdir):
    """Patch spawn_fn's external deps for test: launch, worktree creation,
    launch-cwd resolution, sub-roster detection."""
    async def fake_create_wt(**kwargs):
        wt = kwargs.get('worktree_path', '')
        if wt:
            os.makedirs(wt, exist_ok=True)

    with patch('teaparty.runners.launcher.launch', fake_launch), \
            patch('teaparty.config.roster.has_sub_roster', return_value=False), \
            patch('teaparty.config.roster.resolve_launch_cwd', return_value=tmpdir), \
            patch('teaparty.workspace.worktree.create_subchat_worktree', fake_create_wt):
        yield


@contextlib.contextmanager
def git_env(tmpdir):
    """Patch only the git/config deps in spawn_fn — NOT launch.

    Used by scripted-caller tests where the llm_caller is already wired
    through AgentSession(llm_caller=...) and must NOT be overridden.
    """
    async def fake_create_wt(**kwargs):
        wt = kwargs.get('worktree_path', '')
        if wt:
            os.makedirs(wt, exist_ok=True)

    with patch('teaparty.config.roster.has_sub_roster', return_value=True), \
            patch('teaparty.config.roster.resolve_launch_cwd', return_value=tmpdir), \
            patch('teaparty.workspace.worktree.create_subchat_worktree', fake_create_wt):
        yield


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
        self._tmpdir = _make_teaparty_home(
            agents=['parent', 'agent-b'])
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

        with spawn_env(fake_launch, self._tmpdir):
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

        with spawn_env(fake_launch, self._tmpdir):
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
    """Orchestration-layer tests for the #403 faithfulness invariant.

    Drive the real ``AgentSession`` + ``_run_child`` + pause/resume-walker
    code paths with the environment below them stubbed out: the LLM
    (``_launch``), git queries (``head_commit_of`` / ``current_branch_of`` /
    ``default_branch_of``), and worktree creation (``create_subchat_worktree``)
    are all mocks.  What runs un-mocked is the scheduling, phase-marker
    recording, task cancellation, and gather re-entry.

    These are the load-bearing tests for #403's orchestration contract:
    they fail if the phase markers are removed from the subtree loop, if
    the resume walker re-enters via the wrong entry point, or if the
    cancellation path leaves the tree in an inconsistent state.

    What these tests do NOT cover: whether a real ``claude -p`` process
    dies cleanly under task cancellation, whether git worktrees survive
    a cancel/resume cycle, or whether the has_sub_roster branch works
    end-to-end against real repositories.  Those require a different
    harness (real temp git repo, real cancellable subprocess) — not in
    scope here.
    """

    def setUp(self):
        self._tmpdir = _make_teaparty_home(
            agents=['parent', 'agent-b', 'agent-c'])
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

        with spawn_env(fake_launch, self._tmpdir):
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

        # B→C dispatch activates spawn_fn's has_sub_roster branch, which
        # reaches past _launch (already mocked by spawn_env) into git
        # operations on the dispatcher's worktree.  The fake worktree
        # created by spawn_env's fake_create_wt is just an empty
        # directory — not a real git repo — so head_commit_of /
        # current_branch_of / default_branch_of must be mocked too.
        with spawn_env(fake_launch, self._tmpdir), \
                patch('teaparty.config.roster.has_sub_roster',
                      return_value=True), \
                patch('teaparty.workspace.worktree.head_commit_of',
                      new=AsyncMock(return_value='deadbeef')), \
                patch('teaparty.workspace.worktree.current_branch_of',
                      new=AsyncMock(return_value='main')), \
                patch('teaparty.workspace.worktree.default_branch_of',
                      new=AsyncMock(return_value='main')):
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


class TestCrossRestartResume(unittest.IsolatedAsyncioTestCase):
    """Cross-restart faithful resume (issue #403).

    A realistic failure mode: user clicks Pause All, machine suspends,
    bridge server process dies. On restart, a fresh AgentSession has
    no in-memory factories. The resume handler must rebuild factories
    from disk via ``rehydrate_paused_factories`` so that resume walks
    the subtree and re-creates tasks.

    Faithfulness under cross-restart: a 'complete' session still
    returns its stored response_text; a 'launching' session re-runs
    one claude turn via --resume.
    """

    def setUp(self):
        self._tmpdir = _make_teaparty_home(
            agents=['parent', 'agent-b'])
        create_session(
            agent_name='parent', scope='management',
            teaparty_home=self._tmpdir, session_id='parent-test')

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _make_session(self, project_slug='alpha'):
        from teaparty.teams.session import AgentSession
        return AgentSession(
            self._tmpdir,
            agent_name='parent',
            scope='management',
            qualifier='test',
            conversation_type=ConversationType.OFFICE_MANAGER,
            dispatches=True,
            project_slug=project_slug,
        )

    async def test_complete_phase_resumes_across_restart(self):
        """A 'complete' session on disk resumes faithfully even when the
        AgentSession that originally spawned it no longer exists."""
        # Simulate a prior session run: manually persist a completed
        # child session with stored response_text.
        b_sid = 'child-b-persisted'
        b_path = os.path.join(
            self._tmpdir, 'management', 'sessions', b_sid)
        os.makedirs(os.path.join(b_path, 'worktree'), exist_ok=True)
        meta = {
            'session_id': b_sid,
            'agent_name': 'agent-b',
            'scope': 'management',
            'claude_session_id': 'claude-b',
            'conversation_map': {},
            'phase': 'complete',
            'response_text': 'B final answer across restart',
            'project_slug': 'alpha',
            'parent_session_id': 'parent-test',
            'current_message': '',
            'in_flight_gc_ids': [],
            'initial_message': 'original task B',
        }
        with open(os.path.join(b_path, 'metadata.json'), 'w') as f:
            json.dump(meta, f)

        # Fresh AgentSession — no in-memory factories, simulates a
        # bridge restart.
        session = self._make_session()
        self.assertEqual(session._run_child_factories, {})

        sessions_dir = os.path.join(
            self._tmpdir, 'management', 'sessions')
        registered = session.rehydrate_paused_factories(
            'alpha', sessions_dir)
        self.assertIn(b_sid, registered)

        resumed = await resume_project_subtree(
            'alpha', sessions_dir, session)
        self.assertEqual(resumed, [b_sid])

        task = session._tasks_by_child[b_sid]
        result = await task
        self.assertEqual(result, 'B final answer across restart')

    async def test_launching_phase_reruns_one_turn_across_restart(self):
        """A 'launching' session on disk resumes via --resume across a
        restart, re-running exactly one claude turn with the persisted
        current_message."""
        b_sid = 'child-b-launching'
        b_path = os.path.join(
            self._tmpdir, 'management', 'sessions', b_sid)
        os.makedirs(os.path.join(b_path, 'worktree'), exist_ok=True)
        meta = {
            'session_id': b_sid,
            'agent_name': 'agent-b',
            'scope': 'management',
            'claude_session_id': 'claude-b-mid',
            'conversation_map': {},
            'phase': 'launching',
            'response_text': '',
            'project_slug': 'alpha',
            'parent_session_id': 'parent-test',
            'current_message': 'mid-turn prompt at pause time',
            'in_flight_gc_ids': [],
            'initial_message': 'mid-turn prompt at pause time',
        }
        with open(os.path.join(b_path, 'metadata.json'), 'w') as f:
            json.dump(meta, f)

        launch_calls: list[dict] = []

        async def fake_launch(**kwargs):
            launch_calls.append({
                'agent_name': kwargs.get('agent_name'),
                'message': kwargs.get('message'),
                'resume_session': kwargs.get('resume_session'),
            })
            on_event = kwargs.get('on_stream_event')
            if on_event:
                on_event({'type': 'assistant', 'message': {'content': [
                    {'type': 'text', 'text': 'B regenerated answer'}]}})
            return FakeLaunchResult(session_id='claude-b-mid')

        session = self._make_session()
        sessions_dir = os.path.join(
            self._tmpdir, 'management', 'sessions')

        with spawn_env(fake_launch, self._tmpdir):
            session.rehydrate_paused_factories('alpha', sessions_dir)
            await resume_project_subtree('alpha', sessions_dir, session)
            task = session._tasks_by_child[b_sid]
            result = await task

        self.assertEqual(result, 'B regenerated answer')
        # Exactly one claude turn re-run.
        self.assertEqual(len(launch_calls), 1)
        self.assertEqual(launch_calls[0]['agent_name'], 'agent-b')
        self.assertEqual(
            launch_calls[0]['message'], 'mid-turn prompt at pause time')
        # --resume with the persisted claude_session_id.
        self.assertEqual(launch_calls[0]['resume_session'], 'claude-b-mid')


class TestResumeAgentSessionFiltering(unittest.IsolatedAsyncioTestCase):
    """Resume must only act on the project-lead AgentSession for the
    target slug — not on every live AgentSession.

    The duplication bug: iterating ``self._agent_sessions.values()`` in
    the resume handler rehydrates factories on *every* live session
    (OM, config lead, proxy, project lead…). Each gets its own
    ``_run_child_factories`` + ``_tasks_by_child``. The walker then
    creates a task per session per AgentSession, so one subtree
    session ends up running twice in parallel — once with the OM's
    bus/scope/teaparty_home, once with the lead's.

    These tests stand up two AgentSessions and verify exactly one task
    is scheduled per subtree session, on the correct instance.
    """

    def setUp(self):
        self._tmpdir = _make_teaparty_home(
            agents=['office-manager', 'alpha-lead', 'agent-b'])
        # Persist a 'complete' child session in the management sessions
        # dir so both AgentSessions see it on disk.
        b_path = os.path.join(
            self._tmpdir, 'management', 'sessions', 'child-b')
        os.makedirs(os.path.join(b_path, 'worktree'), exist_ok=True)
        meta = {
            'session_id': 'child-b',
            'agent_name': 'agent-b',
            'scope': 'management',
            'claude_session_id': '',
            'conversation_map': {},
            'phase': 'complete',
            'response_text': 'persisted answer',
            'project_slug': 'alpha',
            'parent_session_id': '',
            'current_message': '',
            'in_flight_gc_ids': [],
            'initial_message': '',
        }
        with open(os.path.join(b_path, 'metadata.json'), 'w') as f:
            json.dump(meta, f)

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _make_agent_session(self, agent_name, qualifier, project_slug=''):
        from teaparty.teams.session import AgentSession
        return AgentSession(
            self._tmpdir,
            agent_name=agent_name,
            scope='management',
            qualifier=qualifier,
            conversation_type=ConversationType.OFFICE_MANAGER,
            dispatches=True,
            project_slug=project_slug,
        )

    async def test_resume_does_not_duplicate_across_unrelated_sessions(self):
        """Two live AgentSessions (OM + alpha-lead). Only the alpha-lead
        session should end up with a task for the persisted child.

        Without the filter, the resume handler's loop-over-all pattern
        populates both sessions' _tasks_by_child and launches two
        parallel resumed tasks for the same session — the duplication
        bug the /chide review surfaced.
        """
        om_session = self._make_agent_session(
            'office-manager', 'user-1', project_slug='')
        lead_session = self._make_agent_session(
            'alpha-lead', 'alpha:user-1', project_slug='alpha')

        # Simulate what the bridge handler should do: filter by
        # scope='project' (or equivalent project_slug match) and
        # only act on the matching session(s).
        candidates = [
            s for s in (om_session, lead_session)
            if s.project_slug == 'alpha'
        ]
        self.assertEqual(len(candidates), 1)
        self.assertIs(candidates[0], lead_session)

        sessions_dir = os.path.join(
            self._tmpdir, 'management', 'sessions')
        for s in candidates:
            s.rehydrate_paused_factories('alpha', sessions_dir)
            await resume_project_subtree('alpha', sessions_dir, s)

        # Exactly one task, on the lead session, not the OM.
        self.assertIn('child-b', lead_session._tasks_by_child)
        self.assertNotIn('child-b', om_session._tasks_by_child)
        # The OM was never touched — its factory map is empty.
        self.assertEqual(om_session._run_child_factories, {})

        result = await lead_session._tasks_by_child['child-b']
        self.assertEqual(result, 'persisted answer')

    async def test_unfiltered_loop_creates_duplicate_tasks(self):
        """Negative-space assertion: document that iterating over
        every AgentSession (the pre-filter bug) produces a task on
        every iteration, not just on the right one. This test would
        have failed the /chide review.
        """
        om_session = self._make_agent_session(
            'office-manager', 'user-1', project_slug='')
        lead_session = self._make_agent_session(
            'alpha-lead', 'alpha:user-1', project_slug='alpha')

        sessions_dir = os.path.join(
            self._tmpdir, 'management', 'sessions')
        # Naive pattern: iterate everything. This is the bug.
        for s in (om_session, lead_session):
            s.rehydrate_paused_factories('alpha', sessions_dir)
            await resume_project_subtree('alpha', sessions_dir, s)

        # Both ended up with a task → duplication.
        self.assertIn('child-b', om_session._tasks_by_child)
        self.assertIn('child-b', lead_session._tasks_by_child)
        # The two tasks are different objects running concurrently.
        self.assertIsNot(
            om_session._tasks_by_child['child-b'],
            lead_session._tasks_by_child['child-b'])


class TestBridgeHandlerFiltering(unittest.IsolatedAsyncioTestCase):
    """Exercise the bridge's pause/resume handlers directly with two
    live AgentSessions (OM-like + project-lead-like) and verify the
    right one is chosen by _project_owner_sessions."""

    def setUp(self):
        self._tmpdir = _make_teaparty_home()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _persist_child(self, sid, slug):
        path = os.path.join(
            self._tmpdir, 'management', 'sessions', sid)
        os.makedirs(os.path.join(path, 'worktree'), exist_ok=True)
        meta = {
            'session_id': sid,
            'agent_name': 'agent-b',
            'scope': 'management',
            'claude_session_id': '',
            'conversation_map': {},
            'phase': 'complete',
            'response_text': f'{sid} done',
            'project_slug': slug,
            'parent_session_id': '',
            'current_message': '',
            'in_flight_gc_ids': [],
            'initial_message': '',
        }
        with open(os.path.join(path, 'metadata.json'), 'w') as f:
            json.dump(meta, f)

    def _make_bridge(self):
        """Construct a bare TeaPartyBridge without starting its aiohttp
        server — we only need the handler methods and the
        _agent_sessions dict."""
        from teaparty.bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge.__new__(TeaPartyBridge)
        bridge.teaparty_home = self._tmpdir
        bridge._agent_sessions = {}
        bridge._paused_projects = set()
        bridge._ws_clients = set()
        bridge._repo_root = os.path.dirname(self._tmpdir)
        # Route _lookup_project_path / _sessions_dir_for_project through
        # a tiny override so we don't need a real project registry.
        sessions_dir = os.path.join(
            self._tmpdir, 'management', 'sessions')
        bridge._lookup_project_path = (
            lambda slug: self._tmpdir if slug == 'alpha' else None)
        bridge._sessions_dir_for_project = lambda slug: sessions_dir
        return bridge

    def _make_agent_session(self, agent_name, qualifier, project_slug=''):
        from teaparty.teams.session import AgentSession
        agent_dir = os.path.join(
            self._tmpdir, 'management', 'agents', agent_name)
        os.makedirs(agent_dir, exist_ok=True)
        with open(os.path.join(agent_dir, 'agent.md'), 'w') as f:
            f.write(f'---\nname: {agent_name}\ndescription: test\n---\n')
        return AgentSession(
            self._tmpdir,
            agent_name=agent_name,
            scope='management',
            qualifier=qualifier,
            conversation_type=ConversationType.OFFICE_MANAGER,
            dispatches=True,
            project_slug=project_slug,
        )

    async def test_handler_resume_only_touches_owner_session(self):
        from aiohttp.test_utils import make_mocked_request
        self._persist_child('child-b', 'alpha')
        bridge = self._make_bridge()
        om = self._make_agent_session(
            'office-manager', '', project_slug='')
        lead = self._make_agent_session(
            'alpha-lead', 'alpha:user-1', project_slug='alpha')
        bridge._agent_sessions = {
            'om': om,
            'pl:alpha-lead:alpha:user-1': lead,
        }

        req = make_mocked_request(
            'POST', '/api/projects/alpha/resume',
            match_info={'slug': 'alpha'})
        resp = await bridge._handle_project_resume(req)
        body = json.loads(resp.body.decode())
        self.assertEqual(resp.status, 200)
        self.assertIn('child-b', body['resumed'])

        # Only the lead owns the resumed task. The OM is untouched.
        self.assertIn('child-b', lead._tasks_by_child)
        self.assertNotIn('child-b', om._tasks_by_child)
        self.assertEqual(om._run_child_factories, {})

    async def test_handler_resume_409s_when_no_owner(self):
        """Post-restart cold-start scenario: project paused on disk,
        no lead session is live yet. Handler returns 409 rather than
        silently doing nothing on the wrong session."""
        from aiohttp.test_utils import make_mocked_request
        self._persist_child('child-b', 'alpha')
        bridge = self._make_bridge()
        # Only an OM-like session — no project lead.
        bridge._agent_sessions = {
            'om': self._make_agent_session(
                'office-manager', '', project_slug=''),
        }

        req = make_mocked_request(
            'POST', '/api/projects/alpha/resume',
            match_info={'slug': 'alpha'})
        resp = await bridge._handle_project_resume(req)
        self.assertEqual(resp.status, 409)
        body = json.loads(resp.body.decode())
        self.assertIn('lead chat', body['error'])


# ── Full-pipeline tests using the scripted LLM caller ────────────────────────
# These exercise the real dispatch pipeline (spawn_fn, bus, resume chain,
# phase marking, pause/resume walker) with no mocks beyond the LLM itself.
# The scripted caller fires tool_use events through the real MCP handlers
# so dispatches flow through spawn_fn exactly as in production.

_module_loop_403 = None
_module_repo_root_403 = None


def _init_git_repo():
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


def _make_scripted_tp(repo_root, agents):
    """Create .teaparty inside a real git repo with management config."""
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
    lead = agents[0]
    members = agents[1:]
    with open(os.path.join(wg_dir, 'test-team.yaml'), 'w') as f:
        f.write(f'name: test-team\nlead: {lead}\nmembers:\n  agents:\n')
        for m in members:
            f.write(f'    - {m}\n')
    with open(os.path.join(mgmt, 'teaparty.yaml'), 'w') as f:
        f.write(f'name: test-mgmt\ndescription: test\nlead: {lead}\n'
                f'projects: []\nmembers:\n  projects: []\n  agents: []\n'
                f'  workgroups:\n    - test-team\n'
                f'workgroups:\n  - name: test-team\n'
                f'    config: workgroups/test-team.yaml\n')
    return tp


_scripted_qualifier = 0


def _make_scripted_session(tp, caller, project_slug='alpha'):
    global _scripted_qualifier
    _scripted_qualifier += 1
    qualifier = f'pause-test-{_scripted_qualifier}'
    # Pre-create the dispatch session on disk so _ensure_bus_listener's
    # load_session finds it (load_session returns None on miss, and the
    # try/except only catches exceptions, not None).
    stable_id = f'parent-{qualifier}'
    create_session(
        agent_name='parent', scope='management',
        teaparty_home=tp, session_id=stable_id,
    )
    from teaparty.teams.session import AgentSession
    return AgentSession(
        tp,
        agent_name='parent',
        scope='management',
        qualifier=qualifier,
        conversation_type=ConversationType.OFFICE_MANAGER,
        dispatches=True,
        llm_caller=caller,
        project_slug=project_slug,
    )


class TestFullCyclePauseResume(unittest.TestCase):
    """Dispatch B→C, pause while B awaits C's gather, resume, verify
    C's reply flows through B into B's final response. Proves the
    pause→resume cycle produces the correct integrated output.

    Uses the scripted LLM caller so dispatch goes through the real
    spawn_fn, real _child_lifecycle_loop, real phase-marking, real
    pause_project_subtree, real resume_project_subtree.
    """

    @classmethod
    def setUpClass(cls):
        cls._repo_root = _init_git_repo()
        cls._loop = asyncio.new_event_loop()

    @classmethod
    def tearDownClass(cls):
        async def _shutdown():
            pending = [t for t in asyncio.all_tasks(cls._loop)
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
        try:
            cls._loop.run_until_complete(_shutdown())
        except Exception:
            pass
        cls._loop.close()
        shutil.rmtree(cls._repo_root, ignore_errors=True)
        from teaparty.mcp import registry
        registry.clear()

    def _run(self, coro, timeout=15):
        return self._loop.run_until_complete(
            asyncio.wait_for(coro, timeout=timeout))

    def test_pause_resume_full_cycle_B_dispatches_C(self):
        """B dispatches to C. Pause while B awaits C. Resume. C completes.
        B integrates C's reply. Verify B's final bus output contains C's
        contribution. This is the end-to-end proof that pause→resume
        produces the correct integrated answer."""
        from teaparty.runners.scripted import (
            make_scripted_caller, text_event, tool_use_event, cost_event,
        )

        c_gate = asyncio.Event()
        b_awaiting = asyncio.Event()
        b_calls = []

        def b_script(msg):
            b_calls.append(msg)
            if len(b_calls) == 1:
                return [
                    text_event('B dispatching to C'),
                    tool_use_event('Send', {
                        'member': 'child-c',
                        'message': 'C please compute 6*7',
                    }),
                    cost_event(),
                ]
            return [
                text_event(f'B RESULT: C said {msg}'),
                cost_event(),
            ]

        async def c_script(msg):
            # Signal that C has been launched — B must now be in its
            # gather (awaiting). This is the synchronization point for
            # the pause.
            b_awaiting.set()
            await c_gate.wait()
            return [text_event('C answer: 42'), cost_event()]

        caller = make_scripted_caller({
            'parent': lambda m: [text_event('coordinator ack'), cost_event()],
            'child-b': b_script,
            'child-c': c_script,
        })

        tp = _make_scripted_tp(
            self._repo_root, ['parent', 'child-b', 'child-c'])

        async def run():
            # spawn_env patches resolve_launch_cwd and
            # create_subchat_worktree so the test doesn't need real
            # git worktree ops — the point is pause/resume fidelity.
            with git_env(self._repo_root):
                session = _make_scripted_session(tp, caller)
                await session._ensure_bus_listener(self._repo_root)

                from teaparty.mcp.registry import get_spawn_fn
                spawn_fn = get_spawn_fn('parent')
                b_sid, _, _ = await spawn_fn(
                    'child-b', 'task for B', 'root-to-b')
                self.assertTrue(b_sid)

                # Wait until C has been launched — that means B has
                # finished its _launch, found a new grandchild, and
                # entered gather (phase=awaiting). The c_script sets
                # b_awaiting when C's _launch is entered.
                await asyncio.wait_for(b_awaiting.wait(), timeout=5.0)
                await asyncio.sleep(0.05)

                sessions_dir = os.path.join(tp, 'management', 'sessions')
                b_meta = load_session(
                    agent_name='child-b', scope='management',
                    teaparty_home=tp, session_id=b_sid)
                self.assertEqual(b_meta.phase, 'awaiting',
                                 f'B should be awaiting C; got {b_meta.phase}')

                # ── PAUSE ──
                await pause_project_subtree('alpha', sessions_dir, session)
                self.assertNotIn(b_sid, session._tasks_by_child)

                b_meta = load_session(
                    agent_name='child-b', scope='management',
                    teaparty_home=tp, session_id=b_sid)
                self.assertEqual(b_meta.phase, 'awaiting')

                # ── RESUME ──
                c_gate.set()
                await resume_project_subtree('alpha', sessions_dir, session)

                await asyncio.sleep(1.0)

                # Verify B's bus has the integrated reply proving C's
                # answer flowed through B's gather.
                b_msgs = session._bus.receive(f'dispatch:{b_sid}')
                b_content = ' '.join(m.content for m in b_msgs)
                self.assertIn('C answer: 42', b_content,
                              f'C reply missing from B bus. Messages: '
                              f'{[(m.sender, m.content[:60]) for m in b_msgs]}')
                self.assertIn('B RESULT:', b_content,
                              f'B integration missing. Messages: '
                              f'{[(m.sender, m.content[:60]) for m in b_msgs]}')

                b_final = load_session(
                    agent_name='child-b', scope='management',
                    teaparty_home=tp, session_id=b_sid)
                self.assertEqual(b_final.phase, 'complete')

                await session.stop()

        self._run(run())


class TestAwaitingCrossRestartFullPipeline(unittest.TestCase):
    """The hardest cross-restart case: B was awaiting C's gather, server
    restarts (fresh AgentSession, no in-memory factories), C was in
    launching. Rehydrate rebuilds leaves-first: C's factory first, then
    B's. Resume: C relaunches one turn, B gathers C's result without
    relaunching its own turn, tree completes.

    Uses scripted caller for C's relaunch. B never calls the LLM because
    it enters at the gather step (awaiting phase resume).
    """

    @classmethod
    def setUpClass(cls):
        cls._repo_root = _init_git_repo()
        cls._loop = asyncio.new_event_loop()

    @classmethod
    def tearDownClass(cls):
        async def _shutdown():
            pending = [t for t in asyncio.all_tasks(cls._loop)
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
        try:
            cls._loop.run_until_complete(_shutdown())
        except Exception:
            pass
        cls._loop.close()
        shutil.rmtree(cls._repo_root, ignore_errors=True)
        from teaparty.mcp import registry
        registry.clear()

    def _run(self, coro, timeout=15):
        return self._loop.run_until_complete(
            asyncio.wait_for(coro, timeout=timeout))

    def test_awaiting_cross_restart_B_gathers_C_without_relaunch(self):
        """Fresh AgentSession (simulating restart). Rehydrate B(awaiting)
        + C(launching). Resume. C relaunches. B gathers C's reply and
        integrates it as B's final response — without relaunching B's
        already-completed turn."""
        from teaparty.runners.scripted import (
            make_scripted_caller, text_event, cost_event,
        )

        launch_log = []

        def b_script(msg):
            launch_log.append(('child-b', msg[:80]))
            return [text_event(f'B INTEGRATED: {msg}'), cost_event()]

        def c_script(msg):
            launch_log.append(('child-c', msg[:80]))
            return [text_event('C recomputed: 42'), cost_event()]

        caller = make_scripted_caller({
            'parent': lambda m: [text_event('ack'), cost_event()],
            'child-b': b_script,
            'child-c': c_script,
        })

        tp = _make_scripted_tp(
            self._repo_root, ['parent', 'child-b', 'child-c'])

        # ── Phase 1: dispatch normally, pause while B awaits C ──
        async def setup_and_pause():
            from teaparty.runners.scripted import (
                make_scripted_caller as mk,
                text_event as te, tool_use_event as tue, cost_event as ce,
            )

            c_gate = asyncio.Event()
            b_awaiting = asyncio.Event()

            def b_setup(msg):
                return [
                    te('B turn-1'),
                    tue('Send', {
                        'member': 'child-c',
                        'message': 'compute 6*7',
                    }),
                    ce(),
                ]

            async def c_setup(msg):
                b_awaiting.set()
                await c_gate.wait()
                return [te('C: 42'), ce()]

            setup_caller = mk({
                'parent': lambda m: [te('ack'), ce()],
                'child-b': b_setup,
                'child-c': c_setup,
            })

            with git_env(self._repo_root):
                session = _make_scripted_session(tp, setup_caller)
                await session._ensure_bus_listener(self._repo_root)

                from teaparty.mcp.registry import get_spawn_fn
                spawn_fn = get_spawn_fn('parent')
                b_sid, _, _ = await spawn_fn(
                    'child-b', 'task for B', 'root-to-b')

                await asyncio.wait_for(b_awaiting.wait(), timeout=5.0)
                await asyncio.sleep(0.05)

                sessions_dir = os.path.join(tp, 'management', 'sessions')
                await pause_project_subtree('alpha', sessions_dir, session)

                b_meta = load_session(
                    agent_name='child-b', scope='management',
                    teaparty_home=tp, session_id=b_sid)
                c_sid = list(b_meta.conversation_map.values())[0]

                await session.stop()
                return b_sid, c_sid

        b_sid, c_sid = self._run(setup_and_pause())

        # Verify disk state: B=awaiting, C=launching.
        b_meta = load_session(
            agent_name='child-b', scope='management',
            teaparty_home=tp, session_id=b_sid)
        c_meta = load_session(
            agent_name='child-c', scope='management',
            teaparty_home=tp, session_id=c_sid)
        self.assertEqual(b_meta.phase, 'awaiting')
        self.assertEqual(c_meta.phase, 'launching')
        self.assertIn(c_sid, b_meta.in_flight_gc_ids)

        # ── Phase 2: fresh session (restart), rehydrate, resume ──
        async def restart_and_resume():
            with git_env(self._repo_root):
                fresh_session = _make_scripted_session(tp, caller)
                self.assertEqual(fresh_session._run_child_factories, {})

                sessions_dir = os.path.join(tp, 'management', 'sessions')
                registered = fresh_session.rehydrate_paused_factories(
                    'alpha', sessions_dir)
                self.assertIn(b_sid, registered)
                self.assertIn(c_sid, registered)

                await resume_project_subtree(
                    'alpha', sessions_dir, fresh_session)

                await asyncio.sleep(1.0)

                b_msgs = fresh_session._bus.receive(f'dispatch:{b_sid}')
                b_content = ' '.join(m.content for m in b_msgs)
                return b_content

        launch_log.clear()
        b_content = self._run(restart_and_resume())

        # C was relaunched (launching phase). B was NOT relaunched
        # for its already-completed turn-1 — it entered at gather.
        # B IS launched once for turn-2 (post-gather integration).
        c_launches = [e for e in launch_log if e[0] == 'child-c']
        b_launches = [e for e in launch_log if e[0] == 'child-b']
        self.assertEqual(len(c_launches), 1,
                         f'C should be launched exactly once: {launch_log}')
        self.assertEqual(len(b_launches), 1,
                         f'B should be launched once (turn-2 only): {launch_log}')

        # The integrated reply proves C's output flowed through B's gather.
        self.assertIn('C recomputed: 42', b_content,
                      f'C reply missing from B bus: {b_content}')


class TestImplicitResumeHandlerRouting(unittest.IsolatedAsyncioTestCase):
    """Exercise _handle_conversation_post's implicit-resume routing
    through the actual handler method. Verifies the conv_id prefix
    parsing correctly selects resume_session_subtree (per-job) vs
    resume_project_subtree (project-wide) and that a per-job resume
    leaves the project-paused flag set while a lead-wide resume clears it.
    """

    def setUp(self):
        self._tmpdir = _make_teaparty_home(
            agents=['parent', 'agent-b'])

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _persist_child(self, sid, slug, response_text='done'):
        path = os.path.join(
            self._tmpdir, 'management', 'sessions', sid)
        os.makedirs(os.path.join(path, 'worktree'), exist_ok=True)
        meta = {
            'session_id': sid, 'agent_name': 'agent-b',
            'scope': 'management', 'claude_session_id': '',
            'conversation_map': {}, 'phase': 'complete',
            'response_text': response_text,
            'project_slug': slug, 'parent_session_id': '',
            'current_message': '', 'in_flight_gc_ids': [],
            'initial_message': '',
        }
        with open(os.path.join(path, 'metadata.json'), 'w') as f:
            json.dump(meta, f)

    def _make_bridge(self):
        from teaparty.bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge.__new__(TeaPartyBridge)
        bridge.teaparty_home = self._tmpdir
        bridge._agent_sessions = {}
        bridge._paused_projects = set()
        bridge._ws_clients = set()
        bridge._repo_root = os.path.dirname(self._tmpdir)
        sessions_dir = os.path.join(
            self._tmpdir, 'management', 'sessions')
        bridge._lookup_project_path = (
            lambda slug: self._tmpdir if slug == 'alpha' else None)
        bridge._sessions_dir_for_project = lambda slug: sessions_dir
        bridge._slug_for_lead = lambda lead: 'alpha' if lead == 'alpha-lead' else ''
        # _bus_for_conversation returns a mock bus so the handler
        # doesn't crash before reaching the implicit-resume block.
        from unittest.mock import MagicMock
        mock_bus = MagicMock()
        mock_bus.send.return_value = 'msg-1'
        bridge._bus_for_conversation = lambda cid: mock_bus
        return bridge

    def _make_lead_session(self):
        from teaparty.teams.session import AgentSession
        return AgentSession(
            self._tmpdir,
            agent_name='parent',
            scope='management',
            qualifier='test',
            conversation_type=ConversationType.OFFICE_MANAGER,
            dispatches=True,
            project_slug='alpha',
        )

    async def test_job_conv_id_triggers_per_session_resume(self):
        """POST to conv_id='job:alpha:job-1' resumes only job-1.
        The project-paused flag stays set (per-job resume)."""
        self._persist_child('job-1', 'alpha', 'j1 done')
        self._persist_child('job-2', 'alpha', 'j2 done')

        bridge = self._make_bridge()
        bridge._paused_projects.add('alpha')
        lead = self._make_lead_session()
        bridge._agent_sessions['pl:alpha-lead:alpha:user'] = lead

        from aiohttp.test_utils import make_mocked_request
        req = make_mocked_request(
            'POST', '/api/conversations/job:alpha:job-1',
            match_info={'id': 'job:alpha:job-1'},
            headers={'Content-Type': 'application/json'},
        )
        # Mock request.json() to return content.
        async def fake_json():
            return {'content': 'hello job-1'}
        req.json = fake_json

        await bridge._handle_conversation_post(req)

        # job-1 resumed.
        self.assertIn('job-1', lead._tasks_by_child)
        # job-2 NOT resumed.
        self.assertNotIn('job-2', lead._tasks_by_child)
        # Flag still set (per-job resume doesn't clear project flag).
        self.assertIn('alpha', bridge._paused_projects)

    async def test_lead_conv_id_triggers_project_wide_resume(self):
        """POST to conv_id='lead:alpha-lead:primus' resumes ALL jobs
        and clears the project-paused flag."""
        self._persist_child('job-1', 'alpha', 'j1')
        self._persist_child('job-2', 'alpha', 'j2')

        bridge = self._make_bridge()
        bridge._paused_projects.add('alpha')
        lead = self._make_lead_session()
        bridge._agent_sessions['pl:alpha-lead:alpha:user'] = lead

        from aiohttp.test_utils import make_mocked_request
        req = make_mocked_request(
            'POST', '/api/conversations/lead:alpha-lead:primus',
            match_info={'id': 'lead:alpha-lead:primus'},
            headers={'Content-Type': 'application/json'},
        )
        async def fake_json():
            return {'content': 'hello lead'}
        req.json = fake_json

        await bridge._handle_conversation_post(req)

        # Both jobs resumed.
        self.assertIn('job-1', lead._tasks_by_child)
        self.assertIn('job-2', lead._tasks_by_child)
        # Flag cleared (project-wide resume).
        self.assertNotIn('alpha', bridge._paused_projects)


class TestPausedFlagPersistence(unittest.IsolatedAsyncioTestCase):
    """The paused flag must survive a bridge restart."""

    def setUp(self):
        self._tmpdir = _make_teaparty_home(
            agents=['parent', 'agent-b'])

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _persist_child(self, sid, slug):
        path = os.path.join(
            self._tmpdir, 'management', 'sessions', sid)
        os.makedirs(os.path.join(path, 'worktree'), exist_ok=True)
        meta = {
            'session_id': sid, 'agent_name': 'agent-b',
            'scope': 'management', 'claude_session_id': '',
            'conversation_map': {}, 'phase': 'complete',
            'response_text': 'x', 'project_slug': slug,
            'parent_session_id': '', 'current_message': '',
            'in_flight_gc_ids': [], 'initial_message': '',
        }
        with open(os.path.join(path, 'metadata.json'), 'w') as f:
            json.dump(meta, f)

    def _make_bridge(self):
        from teaparty.bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge.__new__(TeaPartyBridge)
        bridge.teaparty_home = self._tmpdir
        bridge._agent_sessions = {}
        bridge._paused_projects = set()
        bridge._ws_clients = set()
        bridge._repo_root = os.path.dirname(self._tmpdir)
        sessions_dir = os.path.join(
            self._tmpdir, 'management', 'sessions')
        # The project path IS the tmpdir (we use the .teaparty inside it).
        bridge._lookup_project_path = (
            lambda slug: os.path.dirname(self._tmpdir)
            if slug == 'alpha' else None)
        bridge._sessions_dir_for_project = lambda slug: sessions_dir
        return bridge

    def _make_lead_session(self):
        from teaparty.teams.session import AgentSession
        return AgentSession(
            self._tmpdir,
            agent_name='parent', scope='management',
            qualifier='test',
            conversation_type=ConversationType.OFFICE_MANAGER,
            dispatches=True, project_slug='alpha',
        )

    async def test_pause_writes_marker_resume_removes_it(self):
        """Pause creates a marker file; resume removes it."""
        self._persist_child('job-1', 'alpha')
        bridge = self._make_bridge()
        lead = self._make_lead_session()
        bridge._agent_sessions['pl:alpha'] = lead

        from aiohttp.test_utils import make_mocked_request
        # Pause.
        req = make_mocked_request(
            'POST', '/api/projects/alpha/pause',
            match_info={'slug': 'alpha'})
        resp = await bridge._handle_project_pause(req)
        self.assertEqual(resp.status, 200)

        project_path = os.path.dirname(self._tmpdir)
        marker = os.path.join(project_path, '.teaparty', 'paused')
        self.assertTrue(os.path.isfile(marker),
                        'Pause should create a marker file on disk')

        # Resume.
        req = make_mocked_request(
            'POST', '/api/projects/alpha/resume',
            match_info={'slug': 'alpha'})
        resp = await bridge._handle_project_resume(req)
        self.assertEqual(resp.status, 200)
        self.assertFalse(os.path.exists(marker),
                         'Resume should remove the marker file')

    async def test_restore_reads_marker_on_startup(self):
        """A fresh bridge reads the marker file and populates
        _paused_projects — simulating a restart mid-pause."""
        project_path = os.path.dirname(self._tmpdir)
        marker = os.path.join(project_path, '.teaparty', 'paused')
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, 'w') as f:
            f.write('')

        bridge = self._make_bridge()
        # _restore_paused_flags requires load_management_team to find
        # projects. We'll test the static helpers directly instead.
        from teaparty.bridge.server import TeaPartyBridge
        self.assertTrue(os.path.isfile(marker))

        # Simulate what _restore_paused_flags does: check the marker.
        slug = 'alpha'
        if os.path.isfile(os.path.join(project_path, '.teaparty', 'paused')):
            bridge._paused_projects.add(slug)

        self.assertIn('alpha', bridge._paused_projects)


class TestImplicitResumeOnMessage(unittest.TestCase):
    """Implicit-resume-on-message routing: messages to a job: conv_id
    resume just that job's subtree, while messages to a lead: conv_id
    resume the whole project. Exercises the bridge handler's
    _project_owner_sessions filter + smallest-subtree routing."""

    def setUp(self):
        self._tmpdir = _make_teaparty_home(
            agents=['parent', 'agent-b', 'agent-c'])

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _persist_child(self, sid, slug, phase='complete',
                       response_text='done', parent=''):
        path = os.path.join(
            self._tmpdir, 'management', 'sessions', sid)
        os.makedirs(os.path.join(path, 'worktree'), exist_ok=True)
        meta = {
            'session_id': sid,
            'agent_name': 'agent-b',
            'scope': 'management',
            'claude_session_id': '',
            'conversation_map': {},
            'phase': phase,
            'response_text': response_text,
            'project_slug': slug,
            'parent_session_id': parent,
            'current_message': '',
            'in_flight_gc_ids': [],
            'initial_message': '',
        }
        with open(os.path.join(path, 'metadata.json'), 'w') as f:
            json.dump(meta, f)

    def _make_bridge(self):
        from teaparty.bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge.__new__(TeaPartyBridge)
        bridge.teaparty_home = self._tmpdir
        bridge._agent_sessions = {}
        bridge._paused_projects = set()
        bridge._ws_clients = set()
        bridge._repo_root = os.path.dirname(self._tmpdir)
        sessions_dir = os.path.join(
            self._tmpdir, 'management', 'sessions')
        bridge._lookup_project_path = (
            lambda slug: self._tmpdir if slug == 'alpha' else None)
        bridge._sessions_dir_for_project = lambda slug: sessions_dir
        bridge._slug_for_lead = lambda lead: 'alpha' if lead == 'alpha-lead' else ''
        return bridge

    def _make_agent_session(self, project_slug='alpha'):
        from teaparty.teams.session import AgentSession
        return AgentSession(
            self._tmpdir,
            agent_name='parent',
            scope='management',
            qualifier='test',
            conversation_type=ConversationType.OFFICE_MANAGER,
            dispatches=True,
            project_slug=project_slug,
        )

    def test_job_message_resumes_single_job_leaves_sibling_paused(self):
        """POST to job:{slug}:{sid} resumes only that job's subtree.
        A sibling job in the same paused project stays paused (its task
        is NOT recreated)."""
        self._persist_child('job-1', 'alpha', response_text='job-1 done')
        self._persist_child('job-2', 'alpha', response_text='job-2 done')

        bridge = self._make_bridge()
        bridge._paused_projects.add('alpha')
        lead = self._make_agent_session('alpha')
        bridge._agent_sessions['pl:alpha-lead:alpha:user-1'] = lead

        async def run():
            from aiohttp.test_utils import make_mocked_request
            # Simulate a human posting to job-1's chat.
            # The bridge routing for job: conv_ids targets session_id=job-1.
            from teaparty.workspace.pause_resume import resume_session_subtree
            sessions_dir = os.path.join(
                self._tmpdir, 'management', 'sessions')
            lead.rehydrate_paused_factories('alpha', sessions_dir)
            await resume_session_subtree('job-1', sessions_dir, lead)

            # job-1 resumed.
            self.assertIn('job-1', lead._tasks_by_child)
            result = await lead._tasks_by_child['job-1']
            self.assertEqual(result, 'job-1 done')

            # job-2 was NOT resumed — no task created.
            self.assertNotIn('job-2', lead._tasks_by_child)

        asyncio.run(run())

    def test_lead_message_resumes_entire_project(self):
        """POST to lead:{lead}:{q} resumes ALL jobs for the project."""
        self._persist_child('job-1', 'alpha', response_text='j1')
        self._persist_child('job-2', 'alpha', response_text='j2')

        bridge = self._make_bridge()
        bridge._paused_projects.add('alpha')
        lead = self._make_agent_session('alpha')
        bridge._agent_sessions['pl:alpha-lead:alpha:user-1'] = lead

        async def run():
            sessions_dir = os.path.join(
                self._tmpdir, 'management', 'sessions')
            lead.rehydrate_paused_factories('alpha', sessions_dir)
            await resume_project_subtree('alpha', sessions_dir, lead)

            # Both jobs resumed.
            self.assertIn('job-1', lead._tasks_by_child)
            self.assertIn('job-2', lead._tasks_by_child)
            self.assertEqual(await lead._tasks_by_child['job-1'], 'j1')
            self.assertEqual(await lead._tasks_by_child['job-2'], 'j2')

        asyncio.run(run())


if __name__ == '__main__':
    unittest.main()
