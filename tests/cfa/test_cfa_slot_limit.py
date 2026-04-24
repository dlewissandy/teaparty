"""Regression: CfA ``_bus_spawn_agent`` enforces the 3-dispatch slot limit.

The chat-tier ``spawn_fn`` in ``teaparty/teams/session.py`` has always
called ``check_slot_available`` and returned ``('', '', 'slot_limit')``
when a caller already has ``MAX_CONVERSATIONS_PER_AGENT`` live
children on the bus.  The CfA engine's ``_bus_spawn_agent`` never did
— it just created sessions.  A CfA job lead (e.g. joke-book-lead)
could open a 4th concurrent dispatch to the same member and nothing
stopped it.

One policy, two spawn_fns that had diverged.  This test pins that
CfA enforces the same limit the chat tier does.
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
from teaparty.runners.launcher import (
    MAX_CONVERSATIONS_PER_AGENT,
    create_session,
)


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
    def __init__(self, session_id='stub'):
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


class TestCfaSpawnEnforcesSlotLimit(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._project = tempfile.mkdtemp(prefix='tp-slot-')
        _init_repo(self._project)
        self._tp = os.path.join(self._project, '.teaparty')
        self._infra = tempfile.mkdtemp(prefix='tp-slot-infra-')
        os.makedirs(os.path.join(self._tp, 'management', 'sessions'),
                    exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._project, ignore_errors=True)
        shutil.rmtree(self._infra, ignore_errors=True)

    async def test_fourth_concurrent_dispatch_is_refused(self) -> None:
        """With ``MAX=3`` already open, the 4th Send returns slot_limit."""
        self.assertEqual(
            MAX_CONVERSATIONS_PER_AGENT, 3,
            'Constant changed; update this test if the policy changed.',
        )

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
        from teaparty.cfa.statemachine.cfa_state import CfaState
        o.cfa = CfaState(phase='execution', state='EXECUTE')

        async def fake_launch(**kwargs):
            return _StubLLMResult()

        orig_launch = launcher_mod.launch
        launcher_mod.launch = fake_launch
        orig_resolve = roster_mod.resolve_launch_placement
        roster_mod.resolve_launch_placement = (
            lambda m, th: (th, 'management')
        )
        from teaparty.mcp.registry import current_conversation_id
        caller_conv = 'job:test:orch-session-1'
        current_conversation_id.set(caller_conv)

        # Seed the bus with a JOB conv (what the lead owns) so the
        # slot check has a valid parent to query children of.
        _seed = SqliteMessageBus(bus_db)
        try:
            _seed.create_conversation(
                ConversationType.JOB, 'test:orch-session-1',
                agent_name='lead', project_slug='test',
            )
        finally:
            _seed.close()

        sids: list[str] = []
        try:
            # Three dispatches to distinct members should all succeed —
            # the limit is per-caller-conv, not per-recipient.
            for i in range(MAX_CONVERSATIONS_PER_AGENT):
                sid, _, refusal = await o._bus_spawn_agent(
                    member=f'worker-{i}',
                    composite=f'task {i}',
                    context_id=f'req-{i}',
                )
                self.assertEqual(
                    refusal, '',
                    f'Dispatch {i + 1} of {MAX_CONVERSATIONS_PER_AGENT} '
                    f'unexpectedly refused: {refusal!r}',
                )
                self.assertTrue(sid, f'Dispatch {i + 1} returned empty sid')
                sids.append(sid)

            # The fourth dispatch is over the limit — MUST refuse.
            fourth_sid, _, fourth_refusal = await o._bus_spawn_agent(
                member='worker-4',
                composite='one too many',
                context_id='req-4',
            )
            self.assertEqual(
                fourth_sid, '',
                "4th dispatch must not return a session id — "
                'spawn_fn did not honor MAX_CONVERSATIONS_PER_AGENT',
            )
            self.assertEqual(
                fourth_refusal, 'slot_limit',
                f'4th dispatch must be refused with reason '
                f'``slot_limit``; got {fourth_refusal!r}.  '
                f'If this fails, CfA has drifted from the chat-tier '
                f'spawn_fn again.',
            )
        finally:
            launcher_mod.launch = orig_launch
            roster_mod.resolve_launch_placement = orig_resolve

    async def test_resume_does_not_count_against_slot_limit(self) -> None:
        """Resuming an existing open dispatch reuses a slot, not adds one.

        If the slot check counted resumes as new dispatches, a caller
        with 3 open threads could never continue any of them — every
        follow-up Send would be refused.  The handle-is-durable work
        depends on resume being free.
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
        from teaparty.cfa.statemachine.cfa_state import CfaState
        o.cfa = CfaState(phase='execution', state='EXECUTE')

        async def fake_launch(**kwargs):
            return _StubLLMResult(session_id=f'claude-resume')

        orig_launch = launcher_mod.launch
        launcher_mod.launch = fake_launch
        orig_resolve = roster_mod.resolve_launch_placement
        roster_mod.resolve_launch_placement = (
            lambda m, th: (th, 'management')
        )
        from teaparty.mcp.registry import current_conversation_id
        caller_conv = 'job:test:orch-session-2'
        current_conversation_id.set(caller_conv)

        _seed = SqliteMessageBus(bus_db)
        try:
            _seed.create_conversation(
                ConversationType.JOB, 'test:orch-session-2',
                agent_name='lead', project_slug='test',
            )
        finally:
            _seed.close()

        try:
            # Open 3 distinct dispatches (fill the slots).
            opened: list[str] = []
            for i in range(MAX_CONVERSATIONS_PER_AGENT):
                sid, _, refusal = await o._bus_spawn_agent(
                    member=f'worker-{i}',
                    composite=f'task {i}',
                    context_id=f'req-{i}',
                )
                self.assertEqual(refusal, '')
                opened.append(sid)
                task = o._tasks_by_child.get(sid)
                if task is not None:
                    await task

            # Resume the first one — same member, handle passed as
            # context_id.  Should NOT be refused (existing slot reused)
            # and should return the same sid.
            resume_sid, _, resume_refusal = await o._bus_spawn_agent(
                member='worker-0',
                composite='follow-up in thread',
                context_id=f'dispatch:{opened[0]}',
            )
            self.assertEqual(
                resume_refusal, '',
                'Resuming an existing dispatch must not trip the slot '
                'check — resume reuses a slot.  Got: '
                f'{resume_refusal!r}',
            )
            self.assertEqual(
                resume_sid, opened[0],
                'Resume must return the SAME sid (we re-used the '
                'existing child session), not a new one.',
            )
        finally:
            launcher_mod.launch = orig_launch
            roster_mod.resolve_launch_placement = orig_resolve


if __name__ == '__main__':
    unittest.main()
