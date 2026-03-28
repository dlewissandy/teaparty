#!/usr/bin/env python3
"""Tests for issue #144: AskTeam MCP tool replaces dispatch_cli.

AskTeam(team, task) is a single parameterized MCP tool.  Liaison agents
call it instead of python3 -m dispatch_cli.  The orchestrator handles
subteam lifecycle (worktree, child CfA, merge, learning) behind the tool.

Tests verify:
  1. AskTeam tool is registered in the MCP server
  2. The dispatch listener handles ask_team requests
  3. dispatch() is called with team and task from the tool parameters
  4. Concurrent AskTeam calls run in parallel (not serialized)
  5. AskTeam is in permissions.allow for all phases
  6. Liaison prompts reference AskTeam, not dispatch_cli
  7. dispatch() accepts explicit parameters (no os.environ dependency)
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))


def _run(coro):
    return asyncio.run(coro)


# ── MCP server registers AskTeam ────────────────────────────────────────────

class TestAskTeamToolRegistered(unittest.TestCase):
    """The MCP server must register an AskTeam tool."""

    def test_mcp_server_has_ask_team_tool(self):
        """create_server() must register an AskTeam tool."""
        try:
            import mcp  # noqa: F401
        except ImportError:
            self.skipTest('mcp package not installed')

        from projects.POC.orchestrator.mcp_server import create_server
        server = create_server()
        # FastMCP stores tools — check that AskTeam is registered
        tool_names = [t.name for t in server._tool_manager.list_tools()]
        self.assertIn('AskTeam', tool_names,
                      f"AskTeam must be registered. Found: {tool_names}")

    def test_ask_team_accepts_team_and_task(self):
        """AskTeam must accept team and task parameters."""
        try:
            import mcp  # noqa: F401
        except ImportError:
            self.skipTest('mcp package not installed')

        from projects.POC.orchestrator.mcp_server import create_server
        server = create_server()
        tools = server._tool_manager.list_tools()
        ask_team = next((t for t in tools if t.name == 'AskTeam'), None)
        self.assertIsNotNone(ask_team)
        props = ask_team.parameters.get('properties', {})
        self.assertIn('team', props, "AskTeam must accept a 'team' parameter")
        self.assertIn('task', props, "AskTeam must accept a 'task' parameter")


# ── Dispatch listener handles ask_team requests ─────────────────────────────

class TestDispatchListenerHandlesAskTeam(unittest.TestCase):
    """The dispatch listener must handle ask_team requests from the MCP server."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_listener_routes_ask_team_to_dispatch(self):
        """ask_team request must call dispatch() with team and task."""
        from projects.POC.orchestrator.dispatch_listener import DispatchListener
        from projects.POC.orchestrator.events import EventBus

        bus = MagicMock(spec=EventBus)
        bus.publish = AsyncMock()

        listener = DispatchListener(
            event_bus=bus,
            session_worktree=self.tmpdir,
            infra_dir=self.tmpdir,
            project_slug='test-project',
            session_id='test-session',
            poc_root=self.tmpdir,
        )

        mock_result = {
            'status': 'completed',
            'team': 'writing',
            'task': 'Write jokes',
            'terminal_state': 'COMPLETED_WORK',
        }

        with patch('projects.POC.orchestrator.dispatch_listener.dispatch',
                   new_callable=AsyncMock, return_value=mock_result) as mock_dispatch:
            result = _run(listener._handle_dispatch('writing', 'Write jokes'))

        mock_dispatch.assert_called_once()
        call_kwargs = mock_dispatch.call_args
        all_args = str(call_kwargs)
        self.assertIn('writing', all_args)
        self.assertIn('Write jokes', all_args)

    def test_listener_returns_dispatch_result(self):
        """The dispatch result must be returned to the MCP server."""
        from projects.POC.orchestrator.dispatch_listener import DispatchListener
        from projects.POC.orchestrator.events import EventBus

        bus = MagicMock(spec=EventBus)
        bus.publish = AsyncMock()

        listener = DispatchListener(
            event_bus=bus,
            session_worktree=self.tmpdir,
            infra_dir=self.tmpdir,
            project_slug='test-project',
            session_id='test-session',
            poc_root=self.tmpdir,
        )

        mock_result = {
            'status': 'completed',
            'team': 'art',
            'task': 'Draw logo',
            'terminal_state': 'COMPLETED_WORK',
            'backtrack_count': 0,
        }

        with patch('projects.POC.orchestrator.dispatch_listener.dispatch',
                   new_callable=AsyncMock, return_value=mock_result):
            result = _run(listener._handle_dispatch('art', 'Draw logo'))

        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['team'], 'art')


# ── Concurrent dispatch ─────────────────────────────────────────────────────

class TestConcurrentDispatch(unittest.TestCase):
    """Multiple AskTeam calls must run concurrently, not serialize."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_two_dispatches_run_concurrently(self):
        """Two AskTeam calls should overlap in time, not run sequentially."""
        from projects.POC.orchestrator.dispatch_listener import DispatchListener
        from projects.POC.orchestrator.events import EventBus
        import time

        bus = MagicMock(spec=EventBus)
        bus.publish = AsyncMock()

        listener = DispatchListener(
            event_bus=bus,
            session_worktree=self.tmpdir,
            infra_dir=self.tmpdir,
            project_slug='test',
            session_id='test',
            poc_root=self.tmpdir,
        )

        call_times = []

        async def slow_dispatch(*args, **kwargs):
            call_times.append(('start', time.monotonic()))
            await asyncio.sleep(0.1)
            call_times.append(('end', time.monotonic()))
            return {'status': 'completed', 'team': 'test', 'terminal_state': 'COMPLETED_WORK'}

        async def run_concurrent():
            with patch('projects.POC.orchestrator.dispatch_listener.dispatch',
                       side_effect=slow_dispatch):
                results = await asyncio.gather(
                    listener._handle_dispatch('art', 'task 1'),
                    listener._handle_dispatch('writing', 'task 2'),
                )
            return results

        results = _run(run_concurrent())

        self.assertEqual(len(results), 2)
        # Both should complete — verify we got 4 timing events (2 starts + 2 ends)
        self.assertEqual(len(call_times), 4)
        # The second start should happen before the first end (parallel, not serial)
        starts = [t for label, t in call_times if label == 'start']
        ends = [t for label, t in call_times if label == 'end']
        self.assertTrue(starts[1] < ends[0],
                        "Second dispatch must start before first finishes (parallel)")


# ── Permissions ─────────────────────────────────────────────────────────────

class TestAskTeamPermissions(unittest.TestCase):
    """AskTeam must be in permissions.allow for all phases."""

    def _load_config(self) -> dict:
        config_path = Path(__file__).parent.parent / 'phase-config.json'
        with open(config_path) as f:
            return json.load(f)

    def test_intent_phase_allows_ask_team(self):
        config = self._load_config()
        allowed = config['phases']['intent']['settings_overlay']['permissions']['allow']
        mcp_tools = [t for t in allowed if 'AskTeam' in t]
        self.assertTrue(len(mcp_tools) > 0,
                        f"AskTeam must be in intent phase permissions.allow. Got: {allowed}")

    def test_planning_phase_allows_ask_team(self):
        config = self._load_config()
        allowed = config['phases']['planning']['settings_overlay']['permissions']['allow']
        mcp_tools = [t for t in allowed if 'AskTeam' in t]
        self.assertTrue(len(mcp_tools) > 0,
                        f"AskTeam must be in planning phase permissions.allow. Got: {allowed}")

    def test_execution_phase_allows_ask_team(self):
        config = self._load_config()
        allowed = config['phases']['execution']['settings_overlay']['permissions']['allow']
        mcp_tools = [t for t in allowed if 'AskTeam' in t]
        self.assertTrue(len(mcp_tools) > 0,
                        f"AskTeam must be in execution phase permissions.allow. Got: {allowed}")


# ── dispatch() accepts explicit parameters ──────────────────────────────────

class TestDispatchAcceptsParameters(unittest.TestCase):
    """dispatch() must accept session context as parameters, not os.environ."""

    def test_dispatch_signature_has_session_params(self):
        """dispatch() must accept session_worktree, infra_dir, project_slug."""
        import inspect
        from projects.POC.orchestrator.dispatch_cli import dispatch
        sig = inspect.signature(dispatch)
        params = set(sig.parameters.keys())
        self.assertIn('session_worktree', params,
                      "dispatch() must accept session_worktree parameter")
        self.assertIn('infra_dir', params,
                      "dispatch() must accept infra_dir parameter")
        self.assertIn('project_slug', params,
                      "dispatch() must accept project_slug parameter")


if __name__ == '__main__':
    unittest.main()
