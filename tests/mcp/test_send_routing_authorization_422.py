#!/usr/bin/env python3
"""Send authorizes through the session BusDispatcher before invoking spawn_fn.

Both tiers (CfA engine + chat-tier AgentSession) build a
``BusDispatcher`` from the session's roster at boot, attach it to
``MCPRoutes``, register the same bundle for every agent they launch in
their subtree.  The Send MCP handler consults the dispatcher before
invoking ``spawn_fn`` — authorization is the single transport-level
enforcement point that makes routing correctness independent of
agent-definition trust.

Cut 30: routing tables key directly on agent names — no
``agent_id_map`` translation layer.  An agent's name is its identity,
with 1:1 correspondence between the string and the entity it
identifies.

These tests pin down the invariants the wiring must preserve:

1. **Refusal short-circuits the spawn.**  When the dispatcher refuses
   ``(sender, recipient)``, Send returns ``status: failed`` with a
   routing reason and never invokes ``spawn_fn``.  An agent with a
   broken or hostile prompt cannot reach a peer outside its permitted
   set, no matter what its prompt says.

2. **Names are the identifiers.**  Send passes the caller's
   ``current_agent_name`` and the ``member`` argument straight to the
   dispatcher; the routing table's keys are the same strings used
   everywhere else.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from teaparty.mcp import registry as mcp_registry
from teaparty.mcp.tools.messaging import _default_send_post
from teaparty.messaging.dispatcher import BusDispatcher, RoutingTable


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _build_routes(*, allows: list[tuple[str, str]]) -> mcp_registry.MCPRoutes:
    """Build an MCPRoutes bundle with a dispatcher allowing only ``allows``."""
    table = RoutingTable()
    for sender, recipient in allows:
        table.add_pair(sender, recipient)

    invocations: list[tuple[str, str, str]] = []

    async def spawn(member, composite, context_id):
        invocations.append((member, composite, context_id))
        return ('child-sid', '/tmp/wt', '')

    routes = mcp_registry.MCPRoutes(
        spawn_fn=spawn,
        dispatcher=BusDispatcher(table),
    )
    routes.invocations = invocations  # type: ignore[attr-defined]
    return routes


class TestSendRoutingAuthorization(unittest.TestCase):

    def setUp(self):
        mcp_registry.clear()

    def tearDown(self):
        mcp_registry.clear()

    def test_refused_routing_short_circuits_spawn(self):
        """Dispatcher refuses → Send returns failed, spawn_fn never runs."""
        # Allow coding-lead → developer but NOT specialist → coding-lead.
        routes = _build_routes(
            allows=[('coding-lead', 'developer')],
        )
        mcp_registry.register_agent_mcp_routes('specialist', routes)
        mcp_registry.current_agent_name.set('specialist')

        result = _run(_default_send_post('coding-lead', 'msg', ''))
        payload = json.loads(result)

        self.assertEqual(payload['status'], 'failed')
        self.assertIn('Routing refused', payload['reason'])
        self.assertIn('specialist', payload['reason'])
        self.assertIn('coding-lead', payload['reason'])
        self.assertEqual(
            routes.invocations, [],
            'spawn_fn must NOT be called when routing is refused — '
            'authorization is the transport-level enforcement point '
            'and any spawn that escapes it bypasses the whole table.',
        )

    def test_authorized_routing_invokes_spawn(self):
        """Dispatcher allows → spawn_fn runs; names are passed as-is."""
        routes = _build_routes(
            allows=[('developer', 'coding-lead')],
        )
        mcp_registry.register_agent_mcp_routes('developer', routes)
        mcp_registry.current_agent_name.set('developer')

        result = _run(_default_send_post('coding-lead', 'msg', ''))
        payload = json.loads(result)

        self.assertEqual(payload['status'], 'message_sent')
        self.assertEqual(len(routes.invocations), 1)
        self.assertEqual(routes.invocations[0][0], 'coding-lead')

    def test_no_dispatcher_means_no_enforcement(self):
        """Bootstrap / scripted-test path: missing dispatcher → no check."""
        async def spawn(member, composite, context_id):
            return ('child-sid', '/tmp/wt', '')

        routes = mcp_registry.MCPRoutes(spawn_fn=spawn)  # no dispatcher
        mcp_registry.register_agent_mcp_routes('caller', routes)
        mcp_registry.current_agent_name.set('caller')

        result = _run(_default_send_post('any-target', 'msg', ''))
        payload = json.loads(result)

        self.assertEqual(payload['status'], 'message_sent')

    def test_om_can_send_to_project_lead(self):
        """The bug Cut 30 fixes: OM with agent_name='office-manager'
        sending to a project lead with agent_name='teaparty-lead' must
        match the routing table's pairs — no alias, no translation."""
        routes = _build_routes(
            allows=[
                ('office-manager', 'teaparty-lead'),
                ('teaparty-lead', 'office-manager'),
            ],
        )
        mcp_registry.register_agent_mcp_routes('office-manager', routes)
        mcp_registry.current_agent_name.set('office-manager')

        result = _run(_default_send_post('teaparty-lead', 'msg', ''))
        payload = json.loads(result)

        self.assertEqual(
            payload['status'], 'message_sent',
            'OM must be able to dispatch to its project lead under its '
            'real agent_name, not under a fictional `om` alias.',
        )


class TestMCPRoutesCarriesDispatcher(unittest.TestCase):
    """Structural: register_agent_mcp_routes installs the dispatcher."""

    def setUp(self):
        mcp_registry.clear()

    def tearDown(self):
        mcp_registry.clear()

    def test_register_installs_dispatcher_in_lookup(self):
        table = RoutingTable()
        table.add_pair('a', 'b')
        dispatcher = BusDispatcher(table)
        routes = mcp_registry.MCPRoutes(
            spawn_fn=lambda *a, **kw: None,
            dispatcher=dispatcher,
        )
        mcp_registry.register_agent_mcp_routes('caller', routes)

        self.assertIs(mcp_registry.get_dispatcher('caller'), dispatcher)

    def test_clear_removes_dispatcher(self):
        table = RoutingTable()
        table.add_pair('a', 'b')
        routes = mcp_registry.MCPRoutes(
            dispatcher=BusDispatcher(table),
        )
        mcp_registry.register_agent_mcp_routes('caller', routes)
        mcp_registry.clear()

        self.assertIsNone(mcp_registry.get_dispatcher('caller'))


if __name__ == '__main__':
    unittest.main()
