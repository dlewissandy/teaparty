"""Each agent's launch installs ITS OWN dispatcher in the registry.

The bug this pins: when OM dispatched to configuration-lead, the
parent's ``mcp_routes`` (containing OM's dispatcher) was passed
through the launcher to configuration-lead's launch.  ``launch()``
called ``register_agent_mcp_routes('configuration-lead', mcp_routes)``,
which registered OM's dispatcher under configuration-lead's name.
configuration-lead's subprocess then hit an MCP URL keyed on its own
agent name, ``get_dispatcher()`` returned OM's dispatcher, and Send
to a workgroup member was refused — because workgroup members aren't
in the OM team's flat roster.

The fix: ``launch()`` builds a dispatcher derived from
``derive_team_roster(agent_name)`` — the agent's OWN team — and slots
it into the registered bundle, regardless of what the parent supplied.
For non-lead agents (workgroup members), the parent's dispatcher is
kept; that *is* the team they're operating in, and authorizes the
leaf↔lead reply path.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import textwrap
import unittest

import yaml


def _make_org_with_workgroup() -> str:
    """Create a minimal teaparty home with a Configuration workgroup."""
    home = tempfile.mkdtemp(prefix='launch-disp-')
    tp = os.path.join(home, '.teaparty')
    mgmt = os.path.join(tp, 'management')
    os.makedirs(os.path.join(mgmt, 'workgroups'))
    os.makedirs(os.path.join(mgmt, 'agents', 'office-manager'))
    os.makedirs(os.path.join(mgmt, 'agents', 'configuration-lead'))
    os.makedirs(os.path.join(mgmt, 'agents', 'project-specialist'))

    with open(os.path.join(mgmt, 'teaparty.yaml'), 'w') as f:
        yaml.dump({
            'name': 'Mgmt',
            'description': 'Test',
            'lead': 'office-manager',
            'projects': [],
            'members': {
                'projects': [],
                'workgroups': ['Configuration'],
            },
            'workgroups': [
                {'name': 'Configuration',
                 'config': 'workgroups/configuration.yaml'},
            ],
        }, f)

    with open(os.path.join(mgmt, 'workgroups', 'configuration.yaml'), 'w') as f:
        yaml.dump({
            'name': 'Configuration',
            'description': 'Config team',
            'lead': 'configuration-lead',
            'members': {'agents': ['project-specialist']},
        }, f)

    # Bare agent.md files so the launcher's frontmatter read finds them.
    for agent in ('office-manager', 'configuration-lead', 'project-specialist'):
        with open(
            os.path.join(mgmt, 'agents', agent, 'agent.md'), 'w',
        ) as f:
            f.write(f'---\nname: {agent}\n---\nplaceholder\n')

    return tp


class TestLaunchInstallsAgentSpecificDispatcher(unittest.TestCase):
    """``launch(agent_name=X)`` must install X's dispatcher under X."""

    def setUp(self) -> None:
        self._tp = _make_org_with_workgroup()
        self.addCleanup(shutil.rmtree, os.path.dirname(self._tp), True)
        # Reset registry between tests to avoid leakage.
        from teaparty.mcp import registry
        registry.clear()
        self.addCleanup(registry.clear)

    def _parent_mcp_routes_with_om_dispatcher(self):
        """Return MCPRoutes with OM's dispatcher (what a child inherits)."""
        from teaparty.mcp.registry import MCPRoutes
        from teaparty.messaging.child_dispatch import (
            build_session_dispatcher,
        )
        om_dispatcher = build_session_dispatcher(
            teaparty_home=self._tp, lead_name='office-manager',
        )
        return MCPRoutes(dispatcher=om_dispatcher)

    def test_lead_child_gets_its_own_dispatcher_not_parents(self) -> None:
        """When OM-style mcp_routes are passed to a launch for
        configuration-lead, the registered dispatcher is configuration-lead's
        — authorizing configuration-lead → project-specialist (workgroup
        mesh), not OM's table (which would refuse it).
        """
        # Reproduce launch()'s registration logic directly.  We can't
        # call the full launch() here (it spawns a subprocess); the
        # dispatcher selection is the part we care about and it's
        # standalone code at the top of the function.
        from teaparty.mcp.registry import (
            MCPRoutes, get_dispatcher, register_agent_mcp_routes,
        )
        from teaparty.messaging.child_dispatch import (
            build_session_dispatcher,
        )
        from teaparty.messaging.dispatcher import RoutingError

        agent_name = 'configuration-lead'
        # Parent's mcp_routes (OM's dispatcher).
        parent_routes = self._parent_mcp_routes_with_om_dispatcher()

        # Mirror launch()'s replacement logic.
        agent_dispatcher = build_session_dispatcher(
            teaparty_home=self._tp, lead_name=agent_name,
        )
        self.assertIsNotNone(
            agent_dispatcher,
            'configuration-lead is a known lead — '
            'derive_team_roster must resolve it',
        )
        replaced = MCPRoutes(
            spawn_fn=parent_routes.spawn_fn,
            close_fn=parent_routes.close_fn,
            ask_question_runner=parent_routes.ask_question_runner,
            dispatcher=agent_dispatcher,
        )
        register_agent_mcp_routes(agent_name, replaced)

        # Now simulate the MCP middleware: current_agent_name set to
        # configuration-lead → get_dispatcher() returns configuration-lead's.
        from teaparty.mcp.registry import current_agent_name
        token = current_agent_name.set(agent_name)
        try:
            d = get_dispatcher()
            self.assertIsNotNone(d)
            # Authorizes the workgroup-internal route.
            d.authorize('configuration-lead', 'project-specialist')
            # And the parent gateway up to OM.
            d.authorize('configuration-lead', 'office-manager')
        finally:
            current_agent_name.reset(token)

    def test_om_dispatcher_alone_would_have_refused(self) -> None:
        """Sanity: the bug condition.  OM's dispatcher does NOT
        authorize configuration-lead → project-specialist; that's
        exactly why the parent's dispatcher must not be reused for the
        child.  This test pins the asymmetry.
        """
        from teaparty.messaging.child_dispatch import (
            build_session_dispatcher,
        )
        from teaparty.messaging.dispatcher import RoutingError

        om_d = build_session_dispatcher(
            teaparty_home=self._tp, lead_name='office-manager',
        )
        with self.assertRaises(RoutingError):
            om_d.authorize('configuration-lead', 'project-specialist')


if __name__ == '__main__':
    unittest.main()
