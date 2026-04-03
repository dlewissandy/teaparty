"""Tests for Issue #359: Bus dispatch — retire AskTeam.

AskTeam was a blocking RPC: agent calls AskTeam → DispatchListener → dispatch().
Send/Reply are validated (Issue #358).  AskTeam must be removed and Send/Reply
must be the only dispatch path.

Acceptance criteria:
AC1. AskTeam tool not registered in the MCP server
AC2. DispatchListener not imported or referenced in engine.py
AC3. phase-config.json does not list AskTeam in any phase's permissions.allow
AC4. routing.md does not describe AskTeam as "the current implementation"
AC5. All dispatching agent definitions (configuration-lead, teaparty-lead, pybayes-lead,
     comics-lead, jainai-lead) list Send, not AskTeam, in their tools
AC6. Send and Reply remain registered in the MCP server
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent
_PHASE_CONFIG = _REPO_ROOT / 'orchestrator' / 'phase-config.json'
_ROUTING_MD = _REPO_ROOT / 'docs' / 'proposals' / 'agent-dispatch' / 'references' / 'routing.md'
_AGENTS_DIR = _REPO_ROOT / '.teaparty' / 'management' / 'agents'
_DISPATCH_LISTENER = _REPO_ROOT / 'orchestrator' / 'dispatch_listener.py'
_ENGINE_PY = _REPO_ROOT / 'orchestrator' / 'engine.py'
_MCP_SERVER_PY = _REPO_ROOT / 'orchestrator' / 'mcp_server.py'


def _load_phase_config() -> dict:
    with open(_PHASE_CONFIG) as f:
        return json.load(f)


def _frontmatter_tools(agent_name: str) -> list[str]:
    path = _AGENTS_DIR / agent_name / 'agent.md'
    content = path.read_text()
    for line in content.splitlines():
        line = line.strip()
        if line.startswith('tools:'):
            raw = line[len('tools:'):].strip()
            return [t.strip() for t in raw.split(',') if t.strip()]
    return []


# ── AC1: AskTeam not registered in MCP server ────────────────────────────────

class TestAskTeamNotRegisteredInMCPServer(unittest.TestCase):
    """AC1: AskTeam must not be registered as an MCP tool."""

    def test_ask_team_not_in_mcp_server(self):
        """create_server() must not register an AskTeam tool."""
        try:
            import mcp  # noqa: F401
        except ImportError:
            self.skipTest('mcp package not installed')

        from orchestrator.mcp_server import create_server
        server = create_server()
        tool_names = [t.name for t in server._tool_manager.list_tools()]
        self.assertNotIn(
            'AskTeam', tool_names,
            f'AskTeam must not be registered — it has been retired. Found: {tool_names}',
        )

    def test_ask_team_handler_not_in_mcp_server_module(self):
        """mcp_server.py must not contain ask_team_handler."""
        source = _MCP_SERVER_PY.read_text()
        self.assertNotIn(
            'ask_team_handler',
            source,
            'mcp_server.py must not contain ask_team_handler — AskTeam is retired',
        )

    def test_ask_team_socket_not_in_mcp_server_module(self):
        """mcp_server.py must not reference ASK_TEAM_SOCKET."""
        source = _MCP_SERVER_PY.read_text()
        self.assertNotIn(
            'ASK_TEAM_SOCKET',
            source,
            'mcp_server.py must not reference ASK_TEAM_SOCKET — AskTeam is retired',
        )


# ── AC2: DispatchListener not in engine.py ───────────────────────────────────

class TestDispatchListenerRemovedFromEngine(unittest.TestCase):
    """AC2: engine.py must not import or start a DispatchListener."""

    def test_dispatch_listener_not_imported_in_engine(self):
        """engine.py must not import DispatchListener."""
        source = _ENGINE_PY.read_text()
        self.assertNotIn(
            'DispatchListener',
            source,
            'engine.py must not reference DispatchListener — it has been retired',
        )

    def test_ask_team_socket_not_in_engine(self):
        """engine.py must not set ASK_TEAM_SOCKET in mcp_env."""
        source = _ENGINE_PY.read_text()
        self.assertNotIn(
            'ASK_TEAM_SOCKET',
            source,
            'engine.py must not set ASK_TEAM_SOCKET — AskTeam is retired',
        )

    def test_dispatch_listener_file_does_not_exist(self):
        """dispatch_listener.py must not exist — it served only AskTeam."""
        self.assertFalse(
            _DISPATCH_LISTENER.exists(),
            'dispatch_listener.py must be deleted — it served only the AskTeam blocking RPC',
        )


# ── AC3: AskTeam not in phase-config.json permissions ────────────────────────

class TestAskTeamNotInPhasePermissions(unittest.TestCase):
    """AC3: No phase must list AskTeam in permissions.allow."""

    def _allowed_tools(self, phase: str) -> list[str]:
        config = _load_phase_config()
        return config['phases'][phase]['settings_overlay']['permissions']['allow']

    def test_intent_phase_does_not_allow_ask_team(self):
        allowed = self._allowed_tools('intent')
        ask_team_entries = [t for t in allowed if 'AskTeam' in t]
        self.assertEqual(
            ask_team_entries, [],
            f'intent phase must not allow AskTeam — it is retired. Got: {ask_team_entries}',
        )

    def test_planning_phase_does_not_allow_ask_team(self):
        allowed = self._allowed_tools('planning')
        ask_team_entries = [t for t in allowed if 'AskTeam' in t]
        self.assertEqual(
            ask_team_entries, [],
            f'planning phase must not allow AskTeam — it is retired. Got: {ask_team_entries}',
        )

    def test_execution_phase_does_not_allow_ask_team(self):
        allowed = self._allowed_tools('execution')
        ask_team_entries = [t for t in allowed if 'AskTeam' in t]
        self.assertEqual(
            ask_team_entries, [],
            f'execution phase must not allow AskTeam — it is retired. Got: {ask_team_entries}',
        )


# ── AC4: routing.md updated ───────────────────────────────────────────────────

class TestRoutingMdReflectsSendAsCurrent(unittest.TestCase):
    """AC4: routing.md must not describe AskTeam as the current implementation."""

    def test_routing_md_does_not_call_ask_team_current_implementation(self):
        """routing.md must not say 'AskTeam, the current implementation'."""
        text = _ROUTING_MD.read_text()
        self.assertNotIn(
            "AskTeam, the current implementation",
            text,
            'routing.md must not describe AskTeam as the current implementation — '
            'AskTeam is retired; Send is the current dispatch tool',
        )

    def test_routing_md_still_describes_two_layer_enforcement(self):
        """routing.md must still describe Send's client-side pre-check and bus dispatcher check."""
        text = _ROUTING_MD.read_text()
        self.assertIn(
            'Send',
            text,
            'routing.md must describe Send as the client-side pre-check tool',
        )
        self.assertIn(
            'independent enforcement point',
            text,
            'routing.md must still describe the dispatcher as an independent enforcement point',
        )


# ── AC5: All dispatching agent definitions use Send, not AskTeam ─────────────

_DISPATCHING_AGENTS = [
    'configuration-lead',
    'teaparty-lead',
    'pybayes-lead',
    'comics-lead',
    'jainai-lead',
]


class TestDispatchingAgentToolsUpdated(unittest.TestCase):
    """AC5: Every dispatching agent definition must list Send, not AskTeam."""

    def test_no_dispatching_agent_has_ask_team(self):
        """No dispatching agent must list AskTeam — it has been retired."""
        for agent in _DISPATCHING_AGENTS:
            with self.subTest(agent=agent):
                tools = _frontmatter_tools(agent)
                self.assertNotIn(
                    'AskTeam', tools,
                    f'{agent}/agent.md must not have AskTeam in tools — '
                    f'AskTeam is retired. Got: {tools}',
                )

    def test_all_dispatching_agents_have_send(self):
        """Every dispatching agent must list Send — it is the replacement for AskTeam."""
        for agent in _DISPATCHING_AGENTS:
            with self.subTest(agent=agent):
                tools = _frontmatter_tools(agent)
                self.assertIn(
                    'Send', tools,
                    f'{agent}/agent.md must have Send in tools — '
                    f'it is the replacement for AskTeam. Got: {tools}',
                )


# ── AC6: Send and Reply still registered ─────────────────────────────────────

class TestSendAndReplyStillRegistered(unittest.TestCase):
    """AC6: Send and Reply must remain registered — they are the replacement dispatch path."""

    def test_send_still_registered(self):
        """Send must still be registered in the MCP server."""
        try:
            import mcp  # noqa: F401
        except ImportError:
            self.skipTest('mcp package not installed')

        from orchestrator.mcp_server import create_server
        server = create_server()
        tool_names = [t.name for t in server._tool_manager.list_tools()]
        self.assertIn(
            'Send', tool_names,
            f'Send must remain registered as the replacement for AskTeam. Found: {tool_names}',
        )

    def test_reply_still_registered(self):
        """Reply must still be registered in the MCP server."""
        try:
            import mcp  # noqa: F401
        except ImportError:
            self.skipTest('mcp package not installed')

        from orchestrator.mcp_server import create_server
        server = create_server()
        tool_names = [t.name for t in server._tool_manager.list_tools()]
        self.assertIn(
            'Reply', tool_names,
            f'Reply must remain registered as part of the Send/Reply dispatch pair. Found: {tool_names}',
        )


if __name__ == '__main__':
    unittest.main()
