"""End-to-end behavioural test for CfA CloseConversation (#422).

The ticket's definition of done says:

    A CfA-launched lead agent can call CloseConversation('dispatch:...')
    and see the subchat's worktree merged into the parent worktree,
    the session directory removed, and the accordion updated —
    identical to OM chat.

This test file exercises that sentence literally, end-to-end:

  1. Call Orchestrator._bus_spawn_agent (with a stubbed llm_caller)
     to dispatch a CfA child — a real git worktree is created on a
     session branch, real metadata is written to disk.
  2. Simulate the child writing work in its worktree and committing.
  3. Call the shared close_fn (built via build_close_fn, the same
     factory the engine installs in MCPRoutes).
  4. Assert the committed work is now present on the parent's branch,
     the child's session directory is gone, the worktree branch is
     deleted, and exactly one dispatch_completed event fired.

No source-level regex checks.  The test reaches into the actual
objects the production code produces and verifies the DoD's own
sentence, merge and all.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import unittest

from teaparty.cfa.engine import Orchestrator
from teaparty.mcp.registry import MCPRoutes
from teaparty.messaging.listener import BusEventListener
from teaparty.runners.launcher import (
    create_session, load_session, _save_session_metadata as _save_meta,
)
from teaparty.workspace.close_conversation import build_close_fn


def _git(cwd: str, *args: str) -> str:
    """Run git with the given args in *cwd*, returning stdout (stripped)."""
    r = subprocess.run(
        ['git', *args], cwd=cwd, capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


def _init_repo() -> str:
    """Init a git repo with one commit on 'main'; return the path."""
    path = tempfile.mkdtemp(prefix='tp422-e2e-')
    _git(path, 'init', '-b', 'main')
    _git(path, 'config', 'user.email', 't@e.com')
    _git(path, 'config', 'user.name', 't')
    with open(os.path.join(path, 'README'), 'w') as f:
        f.write('initial\n')
    _git(path, 'add', '.')
    _git(path, 'commit', '-m', 'init')
    return path


class _StubLLMResult:
    """Minimal stand-in for ClaudeResult so _launch's telemetry path runs."""
    def __init__(self):
        self.session_id = 'fake-claude-session-id'
        self.exit_code = 0
        self.duration_ms = 1
        self.cost_usd = 0.0
        self.cost_per_model = {}
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_tokens = 0
        self.cache_create_tokens = 0
        self.response_text = ''
        self.stderr_lines = []
        self.stall_killed = False
        self.api_overloaded = False
        self.tools_called = {}
        self.start_time = 0.0


async def _stub_llm_caller(**kwargs):
    """A scripted llm_caller that never actually runs claude."""
    return _StubLLMResult()


class TestCfACloseE2E(unittest.IsolatedAsyncioTestCase):
    """CfA spawn → close → merge lands the child's commit on main."""

    def setUp(self) -> None:
        # The "project" repo is where the CfA job runs.  The lead's
        # session_worktree would normally live under .teaparty/jobs/ but
        # for this test we let the lead's worktree == the project repo
        # itself so merges go straight to main.
        self._project = _init_repo()
        # .teaparty/ lives inside the project repo, mirroring real layout.
        self._tp = os.path.join(self._project, '.teaparty')
        os.makedirs(os.path.join(self._project, 'management', 'sessions'),
                    exist_ok=True)
        # Minimal workgroups dir so has_sub_roster() never explodes.
        os.makedirs(os.path.join(self._tp, 'management', 'workgroups'),
                    exist_ok=True)
        os.makedirs(os.path.join(self._tp, 'management', 'agents'),
                    exist_ok=True)
        # A bare project.yaml so project-config lookups don't fail.
        os.makedirs(os.path.join(self._tp, 'project'), exist_ok=True)
        with open(os.path.join(self._tp, 'project', 'project.yaml'), 'w') as f:
            f.write('name: test\ndescription: test\nlead: lead\n')

    def tearDown(self) -> None:
        shutil.rmtree(self._project, ignore_errors=True)

    def _make_orchestrator(self, dispatcher) -> Orchestrator:
        """Build an Orchestrator stub exposing only the attributes
        _bus_spawn_agent reads.  Full __init__ wants an EventBus, CfaState,
        PhaseConfig, etc. — none of which this test exercises.  A real
        BusEventListener is attached because _bus_spawn_agent delegates
        to its schedule_child_task (the shared helper with chat tier).
        """
        o = Orchestrator.__new__(Orchestrator)
        o.poc_root = self._project
        o.project_workdir = self._project
        # Lead's session worktree == the project repo root for this test.
        # Child worktrees are forked from here and merge back to this.
        o.session_worktree = self._project
        o.infra_dir = tempfile.mkdtemp(prefix='tp422-infra-')
        o.project_slug = 'test'
        o._dispatcher_session = dispatcher
        o._on_dispatch = None  # set per-test
        o._mcp_routes = None   # not used by _bus_spawn_agent itself
        o._tasks_by_child = {}
        o._bus_event_listener = BusEventListener(bus_db_path='')
        o._bus_event_listener.tasks_by_child = o._tasks_by_child
        return o

    async def test_close_merges_child_commit_into_parent_branch(self):
        """The critical DoD sentence: close merges the subchat back."""
        # ── Dispatcher session on disk so record_child_session works ──
        dispatcher = create_session(
            agent_name='lead', scope='management', teaparty_home=self._project,
        )
        o = self._make_orchestrator(dispatcher)

        # ── Monkeypatch launch so _bus_spawn_agent doesn't run claude ─
        import teaparty.cfa.engine as engine_mod
        real_launch = engine_mod
        # Patch the symbol used inside _bus_spawn_agent's local import.
        import teaparty.runners.launcher as launcher_mod
        orig = launcher_mod.launch

        async def fake_launch(**kwargs):
            return _StubLLMResult()

        launcher_mod.launch = fake_launch
        try:
            session_id, wt_path, refusal = await o._bus_spawn_agent(
                member='worker', composite='do the thing',
                context_id='req-1',
            )
        finally:
            launcher_mod.launch = orig

        self.assertEqual(refusal, '',
                         f'spawn must not refuse: {refusal!r}')
        self.assertTrue(session_id,
                        'spawn must return a non-empty session id')

        # ── The returned id must be the session RECORD id, not the
        # claude session id.  That means a directory named {session_id}
        # exists under management/sessions/ with real metadata.
        sess_dir = os.path.join(
            self._project, 'management', 'sessions', session_id)
        self.assertTrue(os.path.isdir(sess_dir),
                        f'session dir must exist at {sess_dir}')

        loaded = load_session(
            agent_name='worker', scope='management',
            teaparty_home=self._project, session_id=session_id,
        )
        self.assertIsNotNone(loaded,
                             'metadata.json must be loadable for close_fn')
        # All the fields close_conversation will read:
        self.assertEqual(loaded.worktree_path, wt_path)
        self.assertTrue(loaded.worktree_branch.startswith('session/'))
        self.assertEqual(loaded.merge_target_repo, self._project)
        self.assertEqual(loaded.merge_target_worktree, self._project)
        self.assertTrue(loaded.merge_target_branch,
                        'merge_target_branch must be set (not empty)')
        self.assertEqual(loaded.parent_session_id, dispatcher.id)

        # ── Child does work and commits ──
        child_file = os.path.join(wt_path, 'CHILD_WORK')
        with open(child_file, 'w') as f:
            f.write('delivered by the worker\n')
        _git(wt_path, 'add', '.')
        _git(wt_path, 'commit', '-m', 'worker output')

        # ── Close via the shared close_fn (same factory the engine uses) ──
        events: list[dict] = []
        close_fn = build_close_fn(
            dispatch_session=dispatcher,
            teaparty_home=self._project,
            scope='management',
            tasks_by_child=o._tasks_by_child,
            on_dispatch=events.append,
            agent_name='lead',
        )
        result = await close_fn(f'dispatch:{session_id}')

        # ── The DoD sentence, verified ──
        self.assertEqual(result.get('status'), 'ok',
                         f'close must succeed: {result}')
        # Child's content is now on the parent's branch (main).
        self.assertTrue(
            os.path.isfile(os.path.join(self._project, 'CHILD_WORK')),
            "child's committed file must appear on the parent's branch "
            'after close — this is the DoD sentence',
        )
        self.assertEqual(
            open(os.path.join(self._project, 'CHILD_WORK')).read(),
            'delivered by the worker\n',
            "child's committed content must be on main verbatim",
        )
        # Session directory is gone.
        self.assertFalse(
            os.path.isdir(sess_dir),
            f'session dir must be removed after close: {sess_dir}',
        )
        # Session branch is deleted.
        branches = _git(self._project, 'branch', '--list', loaded.worktree_branch)
        self.assertEqual(
            branches, '',
            f'session branch {loaded.worktree_branch!r} must be deleted',
        )
        # Dispatcher's conversation_map no longer holds the child.
        dispatcher_fresh = load_session(
            agent_name='lead', scope='management',
            teaparty_home=self._project, session_id=dispatcher.id,
        )
        self.assertNotIn(
            session_id,
            list(dispatcher_fresh.conversation_map.values()),
            "closed child must be removed from dispatcher's conversation_map",
        )
        # Exactly one dispatch_completed event for the child.
        completed = [e for e in events if e.get('type') == 'dispatch_completed']
        self.assertEqual(len(completed), 1,
                         f'expected 1 dispatch_completed, got {events}')
        self.assertEqual(completed[0]['child_session_id'], session_id)
        self.assertEqual(completed[0]['parent_session_id'], dispatcher.id)
        self.assertEqual(completed[0]['agent_name'], 'worker')


class TestCfASpawnReturnsSessionRecordId(unittest.IsolatedAsyncioTestCase):
    """Regression: _bus_spawn_agent must return the session RECORD id.

    Before #422's fix the method returned result.session_id (the claude
    session UUID).  That broke CloseConversation because
    ``dispatch:{claude_uuid}`` doesn't map to any directory under
    ``{scope}/sessions/`` — the session dir is named by
    ``child_session.id``.  This test pins that contract.
    """

    def setUp(self) -> None:
        self._project = _init_repo()
        self._tp = os.path.join(self._project, '.teaparty')
        os.makedirs(os.path.join(self._project, 'management', 'sessions'),
                    exist_ok=True)
        os.makedirs(os.path.join(self._tp, 'management', 'workgroups'),
                    exist_ok=True)
        os.makedirs(os.path.join(self._tp, 'management', 'agents'),
                    exist_ok=True)
        os.makedirs(os.path.join(self._tp, 'project'), exist_ok=True)
        with open(os.path.join(self._tp, 'project', 'project.yaml'), 'w') as f:
            f.write('name: test\ndescription: test\nlead: lead\n')

    def tearDown(self) -> None:
        shutil.rmtree(self._project, ignore_errors=True)

    async def test_returned_id_names_an_on_disk_session_dir(self) -> None:
        dispatcher = create_session(
            agent_name='lead', scope='management', teaparty_home=self._project,
        )
        o = Orchestrator.__new__(Orchestrator)
        o.poc_root = self._project
        o.project_workdir = self._project
        o.session_worktree = self._project
        o.infra_dir = tempfile.mkdtemp(prefix='tp422-infra-')
        o.project_slug = 'test'
        o._dispatcher_session = dispatcher
        o._on_dispatch = None
        o._mcp_routes = None
        o._tasks_by_child = {}
        o._bus_event_listener = BusEventListener(bus_db_path='')
        o._bus_event_listener.tasks_by_child = o._tasks_by_child

        import teaparty.runners.launcher as launcher_mod
        orig = launcher_mod.launch

        async def fake_launch(**kwargs):
            return _StubLLMResult()

        launcher_mod.launch = fake_launch
        try:
            session_id, _, _ = await o._bus_spawn_agent(
                member='worker', composite='do',
                context_id='req-1',
            )
        finally:
            launcher_mod.launch = orig

        # It MUST NOT be the claude session id the stub returned.
        self.assertNotEqual(
            session_id, 'fake-claude-session-id',
            'spawn must return the session-record id, NOT the claude '
            'session id — otherwise close_conversation cannot find the '
            'session metadata.  Regression guard for #422.',
        )
        # It MUST name a real session directory on disk.
        sess_dir = os.path.join(
            self._project, 'management', 'sessions', session_id)
        self.assertTrue(
            os.path.isdir(sess_dir),
            f'returned session id must name a directory under '
            f'sessions/, got {session_id!r}',
        )


if __name__ == '__main__':
    unittest.main()
