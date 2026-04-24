"""Regression: a dispatch handle stays valid until the lead closes it.

When the CfA lead calls Send, it receives
``conversation_id='dispatch:{sid}'``.  The handle is durable: a
subsequent Send passing ``context_id=<handle>`` must re-enter the
SAME child (re-launch with ``--resume``), NOT spawn a new session.

The previous implementation had a ``SessionRegistry`` layer in
``teaparty/mcp/tools/messaging.py`` that was supposed to track
open threads, but nothing populated it.  Every Send unconditionally
called ``spawn_fn`` and ``spawn_fn`` unconditionally created a new
session.  The handle was dead the moment it was returned — the
"continue a thread" contract of the Send tool was aspirational.

Single source of truth for open threads: the bus ``conversations``
table.  ``_bus_spawn_agent`` now reads it: if the passed context_id
names an ACTIVE DISPATCH conv whose agent_name matches the target
member, the existing child session is loaded and re-used; otherwise
a new session is created.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import unittest

from teaparty.messaging.conversations import (
    ConversationState,
    ConversationType,
    SqliteMessageBus,
)
from teaparty.messaging.listener import BusEventListener
from teaparty.runners.launcher import create_session


def _git(cwd, *args):
    subprocess.run(
        ['git', *args], cwd=cwd, capture_output=True, check=True,
    )


def _init_repo(path):
    os.makedirs(path, exist_ok=True)
    _git(path, 'init', '-b', 'main')
    _git(path, 'config', 'user.email', 't@e.com')
    _git(path, 'config', 'user.name', 't')
    with open(os.path.join(path, 'README'), 'w') as f:
        f.write('x\n')
    _git(path, 'add', '.')
    _git(path, 'commit', '-m', 'init')


class _StubLLMResult:
    def __init__(self, session_id='stub-claude'):
        self.session_id = session_id
        self.exit_code = 0
        self.duration_ms = 1
        self.cost_usd = 0.0
        self.cost_per_model = {}
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_tokens = 0
        self.cache_create_tokens = 0
        self.response_text = 'done'
        self.stderr_lines = []
        self.stall_killed = False
        self.api_overloaded = False
        self.tools_called = {}
        self.start_time = 0.0


class TestDispatchHandleResume(unittest.IsolatedAsyncioTestCase):
    """Second Send with the prior handle reuses the same child session."""

    def setUp(self) -> None:
        self._project = tempfile.mkdtemp(prefix='tp-resume-')
        _init_repo(self._project)
        self._tp = os.path.join(self._project, '.teaparty')
        self._infra = tempfile.mkdtemp(prefix='tp-resume-infra-')
        os.makedirs(os.path.join(self._tp, 'management', 'sessions'),
                    exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._project, ignore_errors=True)
        shutil.rmtree(self._infra, ignore_errors=True)

    async def test_second_send_with_handle_resumes_same_child(self) -> None:
        """Passing the prior dispatch handle re-uses its session record.

        First Send creates child session X.  The child's reply arrives,
        conversation remains ACTIVE (no close).  Second Send passes
        ``context_id='dispatch:X'`` → ``_bus_spawn_agent`` must load
        session X and re-launch it with ``resume_session``, not create
        a new session.  If this test fails, the "prior dispatch handle
        goes stale" bug is back.
        """
        from teaparty.cfa.engine import Orchestrator
        import teaparty.runners.launcher as launcher_mod
        import teaparty.config.roster as roster_mod

        dispatcher = create_session(
            agent_name='lead', scope='management', teaparty_home=self._tp,
        )
        bus_db = os.path.join(self._infra, 'messages.db')
        listener = BusEventListener(bus_db_path=bus_db)

        o = Orchestrator.__new__(Orchestrator)
        o.poc_root = self._project
        o.teaparty_home = self._tp
        o.project_workdir = self._project
        o.session_worktree = self._project
        o.infra_dir = self._infra
        o.project_slug = 'test'
        o._dispatcher_session = dispatcher
        o._on_dispatch = None
        o._mcp_routes = None
        o._tasks_by_child = {}
        o._bus_event_listener = listener
        listener.tasks_by_child = o._tasks_by_child
        o._phase_session_ids = {}
        o._fan_in_event = None
        # Minimal cfa state so _run_child's inject path doesn't AttributeError.
        from teaparty.cfa.statemachine.cfa_state import CfaState
        o.cfa = CfaState(phase='execution', state='EXECUTE', actor='project_lead')

        # Capture every ``resume_session`` passed to launch so we can
        # verify the second call resumes instead of spawning fresh.
        launch_calls = []

        async def fake_launch(**kwargs):
            launch_calls.append({
                'session_id': kwargs.get('session_id', ''),
                'resume_session': kwargs.get('resume_session', ''),
            })
            return _StubLLMResult(session_id=f'claude-{len(launch_calls)}')

        orig_launch = launcher_mod.launch
        launcher_mod.launch = fake_launch

        # Stub member resolution + the contextvar the spawn_fn reads.
        orig_resolve = roster_mod.resolve_launch_placement
        roster_mod.resolve_launch_placement = (
            lambda m, th: (th, 'management')
        )
        from teaparty.mcp.registry import current_conversation_id
        current_conversation_id.set(f'dispatch:{dispatcher.id}')

        try:
            # First Send — no handle; spawns a new child.
            first_sid, first_wt, first_refusal = await o._bus_spawn_agent(
                member='coding-lead', composite='do the thing',
                context_id='',
            )
            self.assertEqual(first_refusal, '')
            self.assertTrue(first_sid)

            # Wait for the scheduled _run_child task to complete so
            # ``claude_session_id`` is persisted to the child metadata.
            task = o._tasks_by_child.get(first_sid)
            if task is not None:
                await task

            # Second Send with the prior handle — must reuse.
            first_handle = f'dispatch:{first_sid}'
            second_sid, second_wt, second_refusal = await o._bus_spawn_agent(
                member='coding-lead', composite='also do this',
                context_id=first_handle,
            )
            self.assertEqual(second_refusal, '')
            self.assertEqual(
                second_sid, first_sid,
                'Second Send with the prior handle must return the '
                'SAME session id — the handle stays valid until the '
                "caller closes.  Got a new id, which means spawn_fn "
                'created a parallel session the child has no memory '
                "of.  That's the 'prior dispatch handle goes stale' "
                'bug the resume path is supposed to eliminate.',
            )

            # Wait for the second task to complete.
            task2 = o._tasks_by_child.get(second_sid)
            if task2 is not None:
                await task2

            # And the second launch must pass resume_session (the
            # claude session id from the first launch).
            self.assertEqual(len(launch_calls), 2)
            self.assertEqual(
                launch_calls[1]['resume_session'], 'claude-1',
                'Second launch must --resume the first claude session '
                "so the child has the first turn's context.",
            )

        finally:
            launcher_mod.launch = orig_launch
            roster_mod.resolve_launch_placement = orig_resolve

    async def test_second_send_after_close_spawns_new(self) -> None:
        """After CloseConversation, the handle is no longer valid."""
        from teaparty.cfa.engine import Orchestrator
        import teaparty.runners.launcher as launcher_mod
        import teaparty.config.roster as roster_mod

        dispatcher = create_session(
            agent_name='lead', scope='management', teaparty_home=self._tp,
        )
        bus_db = os.path.join(self._infra, 'messages.db')
        listener = BusEventListener(bus_db_path=bus_db)

        o = Orchestrator.__new__(Orchestrator)
        o.poc_root = self._project
        o.teaparty_home = self._tp
        o.project_workdir = self._project
        o.session_worktree = self._project
        o.infra_dir = self._infra
        o.project_slug = 'test'
        o._dispatcher_session = dispatcher
        o._on_dispatch = None
        o._mcp_routes = None
        o._tasks_by_child = {}
        o._bus_event_listener = listener
        listener.tasks_by_child = o._tasks_by_child
        o._phase_session_ids = {}
        o._fan_in_event = None
        # Minimal cfa state so _run_child's inject path doesn't AttributeError.
        from teaparty.cfa.statemachine.cfa_state import CfaState
        o.cfa = CfaState(phase='execution', state='EXECUTE', actor='project_lead')

        async def fake_launch(**kwargs):
            return _StubLLMResult()

        orig_launch = launcher_mod.launch
        launcher_mod.launch = fake_launch
        orig_resolve = roster_mod.resolve_launch_placement
        roster_mod.resolve_launch_placement = (
            lambda m, th: (th, 'management')
        )
        from teaparty.mcp.registry import current_conversation_id
        current_conversation_id.set(f'dispatch:{dispatcher.id}')

        try:
            first_sid, _, _ = await o._bus_spawn_agent(
                member='coding-lead', composite='first',
                context_id='',
            )
            task = o._tasks_by_child.get(first_sid)
            if task is not None:
                await task

            # Close the conversation in the bus (simulates
            # CloseConversation being called).
            bus = SqliteMessageBus(bus_db)
            try:
                bus.update_conversation_state(
                    f'dispatch:{first_sid}', ConversationState.CLOSED,
                )
            finally:
                bus.close()

            # Send with the closed handle — must spawn a NEW session
            # because the prior thread is closed.
            second_sid, _, _ = await o._bus_spawn_agent(
                member='coding-lead', composite='second',
                context_id=f'dispatch:{first_sid}',
            )
            self.assertNotEqual(
                second_sid, first_sid,
                'After a conversation is CLOSED, its handle must no '
                'longer route to resume — a follow-up Send must spawn '
                'a new session.  Otherwise the agent can silently '
                "reopen a merged-and-gone worktree.",
            )
        finally:
            launcher_mod.launch = orig_launch
            roster_mod.resolve_launch_placement = orig_resolve


if __name__ == '__main__':
    unittest.main()
