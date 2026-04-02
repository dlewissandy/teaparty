#!/usr/bin/env python3
"""Tests for issue #144: AskTeam MCP tool replaces dispatch_cli.

AskTeam(team, task) replaced dispatch_cli as the dispatch tool in issue #144.
Issue #359 retired AskTeam in favour of Send/Reply bus dispatch.  These tests
verify the state of affairs after that migration:

  1. AskTeam is NOT registered in the MCP server (retired in #359)
  2. Send is registered — the replacement dispatch tool
  3. Reply is registered — the Send counterpart
  4. dispatch() still accepts explicit session parameters (used by other paths)
  5. dispatch() is the correct dispatch mechanism (not AskTeam)
"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

_PHASE_CONFIG = Path(__file__).parent.parent / 'orchestrator' / 'phase-config.json'


# ── AskTeam is retired ──────────────────────────────────────────────────────

class TestAskTeamRetired(unittest.TestCase):
    """AskTeam must not be registered — it was retired in issue #359."""

    def test_mcp_server_does_not_have_ask_team_tool(self):
        """create_server() must not register an AskTeam tool after retirement."""
        try:
            import mcp  # noqa: F401
        except ImportError:
            self.skipTest('mcp package not installed')

        from orchestrator.mcp_server import create_server
        server = create_server()
        tool_names = [t.name for t in server._tool_manager.list_tools()]
        self.assertNotIn('AskTeam', tool_names,
                         f"AskTeam must not be registered after retirement. Found: {tool_names}")

    def test_dispatch_listener_module_does_not_exist(self):
        """dispatch_listener.py must not exist — it was deleted in issue #359."""
        dispatch_listener_path = Path(__file__).parent.parent / 'orchestrator' / 'dispatch_listener.py'
        self.assertFalse(
            dispatch_listener_path.exists(),
            'dispatch_listener.py must be deleted — it served only the AskTeam blocking RPC',
        )


# ── Send and Reply are the replacement dispatch tools ───────────────────────

class TestSendReplyRegistered(unittest.TestCase):
    """Send and Reply must be registered — they are the replacement for AskTeam."""

    def test_mcp_server_has_send_tool(self):
        """create_server() must register a Send tool."""
        try:
            import mcp  # noqa: F401
        except ImportError:
            self.skipTest('mcp package not installed')

        from orchestrator.mcp_server import create_server
        server = create_server()
        tool_names = [t.name for t in server._tool_manager.list_tools()]
        self.assertIn('Send', tool_names,
                      f"Send must be registered as the dispatch tool. Found: {tool_names}")

    def test_mcp_server_has_reply_tool(self):
        """create_server() must register a Reply tool."""
        try:
            import mcp  # noqa: F401
        except ImportError:
            self.skipTest('mcp package not installed')

        from orchestrator.mcp_server import create_server
        server = create_server()
        tool_names = [t.name for t in server._tool_manager.list_tools()]
        self.assertIn('Reply', tool_names,
                      f"Reply must be registered as the Send counterpart. Found: {tool_names}")

    def test_send_accepts_member_and_message(self):
        """Send must accept member and message parameters."""
        try:
            import mcp  # noqa: F401
        except ImportError:
            self.skipTest('mcp package not installed')

        from orchestrator.mcp_server import create_server
        server = create_server()
        tools = server._tool_manager.list_tools()
        send = next((t for t in tools if t.name == 'Send'), None)
        self.assertIsNotNone(send)
        props = send.parameters.get('properties', {})
        self.assertIn('member', props, "Send must accept a 'member' parameter")
        self.assertIn('message', props, "Send must accept a 'message' parameter")


# ── AskTeam not in phase permissions ────────────────────────────────────────

class TestAskTeamNotInPhasePermissions(unittest.TestCase):
    """AskTeam must not appear in any phase's permissions.allow after retirement."""

    def _load_config(self) -> dict:
        with open(_PHASE_CONFIG) as f:
            return json.load(f)

    def test_intent_phase_does_not_allow_ask_team(self):
        config = self._load_config()
        allowed = config['phases']['intent']['settings_overlay']['permissions']['allow']
        ask_team_entries = [t for t in allowed if 'AskTeam' in t]
        self.assertEqual(ask_team_entries, [],
                         f"AskTeam must not be in intent phase permissions.allow after retirement. Got: {ask_team_entries}")

    def test_planning_phase_does_not_allow_ask_team(self):
        config = self._load_config()
        allowed = config['phases']['planning']['settings_overlay']['permissions']['allow']
        ask_team_entries = [t for t in allowed if 'AskTeam' in t]
        self.assertEqual(ask_team_entries, [],
                         f"AskTeam must not be in planning phase permissions.allow after retirement. Got: {ask_team_entries}")

    def test_execution_phase_does_not_allow_ask_team(self):
        config = self._load_config()
        allowed = config['phases']['execution']['settings_overlay']['permissions']['allow']
        ask_team_entries = [t for t in allowed if 'AskTeam' in t]
        self.assertEqual(ask_team_entries, [],
                         f"AskTeam must not be in execution phase permissions.allow after retirement. Got: {ask_team_entries}")


# ── dispatch() still accepts explicit parameters ────────────────────────────

class TestDispatchAcceptsParameters(unittest.TestCase):
    """dispatch() must accept session context as parameters, not os.environ."""

    def test_dispatch_signature_has_session_params(self):
        """dispatch() must accept session_worktree, infra_dir, project_slug."""
        import inspect
        from orchestrator.dispatch_cli import dispatch
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
