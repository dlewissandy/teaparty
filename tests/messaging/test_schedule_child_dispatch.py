"""Tests for ``teaparty.messaging.child_dispatch.schedule_child_dispatch``.

Cut 24 unified the spawn-fn prelude across both tiers.  Both CfA's
``Orchestrator`` and chat-tier's ``AgentSession`` now build a
``ChildDispatchContext`` at boot and register the ``make_spawn_fn(ctx)``
result via ``MCPRoutes.spawn_fn``.  ~500 lines of duplicated prelude
collapsed into one function with two tier-specific knobs (``fixed_scope``
for CfA's hard-coded scope, ``cross_repo_supported`` for chat-tier's
multi-project dispatch) and one tier-specific hook
(``on_child_complete`` for fan-in).

These tests pin the unified contract — refusal codes, bus row writes,
parent_conv_id propagation, the cross-repo branch — independent of
either tier.

Background-task discipline: schedule_child_dispatch spawns a child
asyncio.Task that calls run_child_lifecycle → launch().  Tests stub
``teaparty.runners.launcher.launch`` to return a benign ClaudeResult so
the background task drains immediately rather than hanging on a real
subprocess.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from teaparty.messaging.conversations import (
    ConversationState,
    ConversationType,
    SqliteMessageBus,
)
from teaparty.messaging.listener import BusEventListener
from teaparty.messaging.child_dispatch import (
    ChildDispatchContext,
    schedule_child_dispatch,
    make_spawn_fn,
)
from teaparty.runners.claude import ClaudeResult
from teaparty.runners.launcher import create_session
from teaparty.mcp.registry import current_conversation_id


def _git(cwd, *args):
    subprocess.run(['git', *args], cwd=cwd, capture_output=True, check=True)


def _init_repo(path: str) -> None:
    os.makedirs(path, exist_ok=True)
    _git(path, 'init', '-b', 'main')
    _git(path, 'config', 'user.email', 't@e.com')
    _git(path, 'config', 'user.name', 't')
    with open(os.path.join(path, 'README'), 'w') as f:
        f.write('x\n')
    _git(path, 'add', '.')
    _git(path, 'commit', '-m', 'init')


async def _stub_launch(**kwargs):
    """Drop-in replacement for launcher.launch — returns immediately.

    Without this, schedule_child_dispatch's background _run_child task
    would hang on a real subprocess spawn forever (or until pytest's
    timeout).
    """
    return ClaudeResult(exit_code=0, session_id='stub-claude')


class _DispatchTest(unittest.IsolatedAsyncioTestCase):
    """Common setup: a real git repo, a bus, a stubbed launch."""

    def setUp(self):
        self._project = tempfile.mkdtemp(prefix='tp-spawn-')
        _init_repo(self._project)
        self._tp = os.path.join(self._project, '.teaparty')
        os.makedirs(os.path.join(self._tp, 'management', 'sessions'),
                    exist_ok=True)
        self._infra = tempfile.mkdtemp(prefix='tp-spawn-infra-')
        bus_db = os.path.join(self._infra, 'messages.db')
        SqliteMessageBus(bus_db).close()
        self._bus_db = bus_db
        self._bus = SqliteMessageBus(bus_db)
        self._listener = BusEventListener(bus_db_path=bus_db)
        self._dispatcher = create_session(
            agent_name='lead', scope='management', teaparty_home=self._tp,
        )
        self._dispatcher.worktree_path = self._project
        self._dispatcher.merge_target_repo = self._project
        self._dispatcher.merge_target_worktree = self._project
        self._dispatcher.launch_cwd = self._project

        # Stub launch globally — applied in every test method.
        self._launch_patch = patch(
            'teaparty.runners.launcher.launch', _stub_launch,
        )
        self._launch_patch.start()
        # Stub member resolver: any name → (teaparty_home, 'management').
        self._resolver_patch = patch(
            'teaparty.config.roster.resolve_launch_placement',
            lambda m, th: (th, 'management'),
        )
        self._resolver_patch.start()

    def tearDown(self):
        self._launch_patch.stop()
        self._resolver_patch.stop()
        try:
            self._bus.close()
        except Exception:
            pass
        shutil.rmtree(self._project, ignore_errors=True)
        shutil.rmtree(self._infra, ignore_errors=True)

    async def asyncTearDown(self):
        # Drain any pending background tasks the spawn function created.
        # Without this, IsolatedAsyncioTestCase logs warnings about
        # unawaited tasks at process shutdown.
        for task in list(self._listener.tasks_by_child.values()):
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    def _make_ctx(self, **overrides) -> ChildDispatchContext:
        kw = dict(
            dispatcher_session=self._dispatcher,
            bus=self._bus,
            bus_listener=self._listener,
            session_registry={},
            tasks_by_child=self._listener.tasks_by_child,
            teaparty_home=self._tp,
            project_slug='proj',
            repo_root=self._project,
            telemetry_scope='proj',
            fixed_scope='management',
            cross_repo_supported=False,
            log_tag='test.spawn',
        )
        kw.update(overrides)
        return ChildDispatchContext(**kw)


class TestRefusalCodes(_DispatchTest):
    """Cases where the prelude refuses before scheduling anything."""

    async def test_paused_check_refuses_with_paused_code(self):
        ctx = self._make_ctx(paused_check=lambda: True)
        current_conversation_id.set('parent-conv')
        sid, wt, refusal = await schedule_child_dispatch(
            'coding-lead', 'do work', '', ctx=ctx,
        )
        self.assertEqual(sid, '')
        self.assertEqual(refusal, 'paused')

    async def test_unresolved_member_refuses_with_unresolved_code(self):
        # Override the global stub: this test wants an unresolved member.
        self._resolver_patch.stop()
        from teaparty.config.roster import LaunchCwdNotResolved
        with patch(
            'teaparty.config.roster.resolve_launch_placement',
            side_effect=LaunchCwdNotResolved('not registered'),
        ):
            ctx = self._make_ctx()
            current_conversation_id.set('parent-conv')
            sid, _, refusal = await schedule_child_dispatch(
                'no-such-agent', 'work', '', ctx=ctx,
            )
        # Restart the suite-level resolver patch so tearDown's stop() works.
        self._resolver_patch.start()
        self.assertEqual(sid, '')
        self.assertTrue(refusal.startswith('unresolved_member:'))

    async def test_empty_parent_conv_id_raises(self):
        """No fallback derivation: empty contextvar → RuntimeError."""
        ctx = self._make_ctx()
        current_conversation_id.set('')
        with self.assertRaises(RuntimeError) as exc_ctx:
            await schedule_child_dispatch(
                'coding-lead', 'work', '', ctx=ctx,
            )
        self.assertIn(
            'current_conversation_id is empty',
            str(exc_ctx.exception),
        )


class TestBusRowWrites(_DispatchTest):
    """The DISPATCH row is the single source of truth for the dispatch."""

    async def test_writes_dispatch_row_with_correct_parent(self):
        ctx = self._make_ctx()
        current_conversation_id.set('job:proj:sess-1')
        sid, _, refusal = await schedule_child_dispatch(
            'coding-lead', 'work', '', ctx=ctx,
        )
        self.assertEqual(refusal, '')

        rows = self._bus._conn.execute(
            'SELECT id, parent_conversation_id, agent_name, '
            'project_slug, worktree_path '
            'FROM conversations WHERE id LIKE ?',
            ('dispatch:%',),
        ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], 'job:proj:sess-1')
        self.assertEqual(rows[0][2], 'coding-lead')
        self.assertEqual(rows[0][3], 'proj')
        self.assertTrue(rows[0][4],
                        'worktree_path must be stamped on the DISPATCH row')

    async def test_bus_row_written_even_when_worktree_creation_fails(self):
        """The dispatch record is intent — must persist even if the worktree
        can't be created.  Recovery later closes the orphaned ACTIVE row."""
        ctx = self._make_ctx()
        # Point dispatcher at a non-git dir so create_subchat_worktree fails.
        ctx.repo_root = self._infra
        ctx.dispatcher_session.worktree_path = self._infra
        ctx.dispatcher_session.merge_target_repo = self._infra
        current_conversation_id.set('job:proj:sess-1')

        sid, _, refusal = await schedule_child_dispatch(
            'coding-lead', 'work', '', ctx=ctx,
        )

        self.assertEqual(refusal, 'worktree_failed')
        rows = self._bus._conn.execute(
            'SELECT id FROM conversations WHERE id LIKE ?',
            ('dispatch:%',),
        ).fetchall()
        self.assertEqual(
            len(rows), 1,
            'DISPATCH row must be written BEFORE worktree creation '
            'so a failed worktree leaves a row recovery can find.',
        )


class TestThreadContinuation(_DispatchTest):
    """A second spawn with the prior dispatch handle must reuse the row."""

    async def test_thread_continuation_reuses_existing_session(self):
        ctx = self._make_ctx()
        current_conversation_id.set('job:proj:sess-1')
        first_sid, _, first_refusal = await schedule_child_dispatch(
            'coding-lead', 'first', '', ctx=ctx,
        )
        self.assertEqual(first_refusal, '')

        # Wait for the background task so the first dispatch fully
        # records before we re-enter.
        first_task = self._listener.tasks_by_child.get(first_sid)
        if first_task is not None:
            try:
                await asyncio.wait_for(first_task, timeout=2)
            except (asyncio.TimeoutError, Exception):
                pass

        second_sid, _, second_refusal = await schedule_child_dispatch(
            'coding-lead', 'second', f'dispatch:{first_sid}',
            ctx=ctx,
        )
        self.assertEqual(second_refusal, '')
        self.assertEqual(
            second_sid, first_sid,
            'Second spawn with the prior dispatch handle must reuse '
            'the same session id — the unified prelude consults the bus '
            'for thread continuation.',
        )
        # Only one DISPATCH row in the bus.
        rows = self._bus._conn.execute(
            'SELECT id FROM conversations WHERE id LIKE ?', ('dispatch:%',),
        ).fetchall()
        self.assertEqual(len(rows), 1)


class TestMakeSpawnFn(unittest.TestCase):
    """``make_spawn_fn`` returns an awaitable matching Send's contract."""

    def test_returns_callable_with_three_args(self):
        ctx = ChildDispatchContext(
            dispatcher_session=None, bus=None, bus_listener=None,
            session_registry={}, tasks_by_child={},
        )
        spawn = make_spawn_fn(ctx)
        self.assertTrue(callable(spawn))
        coro = spawn('m', 'c', 'r')
        self.assertTrue(asyncio.iscoroutine(coro))
        coro.close()


if __name__ == '__main__':
    unittest.main()
