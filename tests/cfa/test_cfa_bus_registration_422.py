"""CfA _bus_spawn_agent registers each dispatch in the bus (#422).

The accordion-walker fix depends on the bus record existing at the
moment a Send returns.  This test exercises the real _bus_spawn_agent
against a real SQLite bus and a real git worktree, stubs only the
claude subprocess, and asserts the bus row reflects the dispatch.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import unittest

from teaparty.cfa.engine import Orchestrator
from teaparty.messaging.conversations import (
    ConversationState,
    ConversationType,
    SqliteMessageBus,
)
from teaparty.messaging.listener import BusEventListener
from teaparty.runners.launcher import create_session


def _git(cwd: str, *args: str) -> str:
    r = subprocess.run(
        ['git', *args], cwd=cwd, capture_output=True, text=True, check=True,
    )
    return r.stdout.strip()


def _init_repo() -> str:
    p = tempfile.mkdtemp(prefix='tp422-cfabus-')
    _git(p, 'init', '-b', 'main')
    _git(p, 'config', 'user.email', 't@e.com')
    _git(p, 'config', 'user.name', 't')
    with open(os.path.join(p, 'README'), 'w') as f:
        f.write('x\n')
    _git(p, 'add', '.')
    _git(p, 'commit', '-m', 'init')
    return p


class _StubLLMResult:
    def __init__(self):
        self.session_id = 'stub-claude'
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


class TestBusSpawnAgentRegistersDispatch(unittest.IsolatedAsyncioTestCase):
    """After _bus_spawn_agent returns, the bus has a row with agent_name."""

    def setUp(self) -> None:
        self._project = _init_repo()
        self._tp = os.path.join(self._project, '.teaparty')
        self._infra = tempfile.mkdtemp(prefix='tp422-infra-')
        os.makedirs(os.path.join(self._tp, 'management', 'sessions'),
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
        shutil.rmtree(self._infra, ignore_errors=True)

    async def test_dispatch_writes_bus_record_with_agent_name(self) -> None:
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

        import teaparty.runners.launcher as launcher_mod
        orig = launcher_mod.launch

        async def fake_launch(**kwargs):
            return _StubLLMResult()

        launcher_mod.launch = fake_launch
        # The production call site sets current_conversation_id via
        # the MCP middleware from the ``?conv=`` URL param that
        # ``launch()`` writes.  Tests that invoke _bus_spawn_agent
        # directly (bypassing MCP) MUST set the contextvar themselves
        # — no fallback derivation catches a miss.
        from teaparty.mcp.registry import current_conversation_id
        current_conversation_id.set(f'dispatch:{dispatcher.id}')
        try:
            session_id, _wt, refusal = await o._bus_spawn_agent(
                member='coding-team', composite='do',
                context_id='req-xyz',
            )
        finally:
            launcher_mod.launch = orig

        self.assertEqual(refusal, '')
        self.assertTrue(session_id)

        # The bus now holds the authoritative record for this dispatch.
        bus = SqliteMessageBus(bus_db)
        conv_id = f'dispatch:{session_id}'
        conv = bus.get_conversation(conv_id)
        self.assertIsNotNone(
            conv,
            f'_bus_spawn_agent must register the dispatch in the bus — '
            f'no row found for {conv_id}.  Without this row the accordion '
            'walker cannot resolve agent_name and the blade shows "unknown".',
        )
        self.assertEqual(conv.agent_name, 'coding-team',
                         'bus record must carry the member as the lead '
                         'agent_name (what the accordion blade displays)')
        self.assertEqual(conv.request_id, 'req-xyz')
        self.assertEqual(conv.state, ConversationState.ACTIVE)
        self.assertEqual(
            conv.parent_conversation_id,
            f'dispatch:{dispatcher.id}',
            'parent conv id must be derived from the dispatcher session '
            'so children_of(parent) returns this dispatch',
        )

        # And the parent sees this via children_of.
        kids = bus.children_of(f'dispatch:{dispatcher.id}')
        self.assertEqual(len(kids), 1)
        self.assertEqual(kids[0].agent_name, 'coding-team')


if __name__ == '__main__':
    unittest.main()
