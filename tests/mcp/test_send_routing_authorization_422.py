#!/usr/bin/env python3
"""Send authorizes through the session BusDispatcher before invoking spawn_fn.

Cut 18 wires routing enforcement uniformly across both tiers (CfA engine
+ chat-tier AgentSession): both build a ``BusDispatcher`` from the
session's roster at boot, both attach it to ``MCPRoutes``, both register
the same bundle for every agent they launch in their subtree.  The Send
MCP handler consults the dispatcher before invoking ``spawn_fn`` —
authorization is the single transport-level enforcement point that makes
routing correctness independent of agent-definition trust.

These tests pin down two invariants the new wiring must preserve:

1. **Refusal short-circuits the spawn.**  When the dispatcher refuses
   ``(sender_id, recipient_id)``, Send returns ``status: failed`` with a
   routing reason and never invokes ``spawn_fn``.  An agent with a
   broken or hostile prompt cannot reach a peer outside its permitted
   set, no matter what its prompt says.

2. **The map mediates name → id translation.**  Send sees roster
   *names* (``coding-lead``, ``om``); the routing table keys on scoped
   *agent IDs* (``proj/coding/lead``, ``om``).  The handler resolves
   both through ``agent_id_map`` registered on ``MCPRoutes`` before
   authorizing.  This is what makes one routing table work for an
   arbitrarily nested team — every tier's session populates its own
   ``(dispatcher, agent_id_map)`` pair, every agent in that subtree
   authorizes against it.
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


def _build_routes(*, allows: list[tuple[str, str]],
                  agent_id_map: dict[str, str]) -> mcp_registry.MCPRoutes:
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
        agent_id_map=agent_id_map,
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
        # Allow project-lead → coding-lead but NOT specialist → coding-lead.
        routes = _build_routes(
            allows=[('proj/lead', 'proj/coding/lead')],
            agent_id_map={
                'specialist': 'proj/coding/specialist',
                'coding-lead': 'proj/coding/lead',
            },
        )
        mcp_registry.register_agent_mcp_routes('specialist', routes)
        mcp_registry.current_agent_name.set('specialist')

        result = _run(_default_send_post('coding-lead', 'msg', ''))
        payload = json.loads(result)

        self.assertEqual(payload['status'], 'failed')
        self.assertIn('Routing refused', payload['reason'])
        self.assertIn('proj/coding/specialist', payload['reason'])
        self.assertIn('proj/coding/lead', payload['reason'])
        self.assertEqual(
            routes.invocations, [],
            'spawn_fn must NOT be called when routing is refused — '
            'authorization is the transport-level enforcement point '
            'and any spawn that escapes it bypasses the whole table.',
        )

    def test_authorized_routing_invokes_spawn(self):
        """Dispatcher allows → spawn_fn runs; the agent_id_map mediates."""
        routes = _build_routes(
            allows=[('proj/coding/specialist', 'proj/coding/lead')],
            agent_id_map={
                'specialist': 'proj/coding/specialist',
                'coding-lead': 'proj/coding/lead',
            },
        )
        mcp_registry.register_agent_mcp_routes('specialist', routes)
        mcp_registry.current_agent_name.set('specialist')

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

    def test_unmapped_names_fall_through_as_their_own_ids(self):
        """An agent name absent from the id_map authorizes as itself.

        This is the edge case where a session's roster does not include
        the caller or recipient (e.g. an old session map, a
        misconfigured workgroup).  The dispatcher is still consulted —
        it just sees the raw name as the id.  No silent allow-through.
        """
        routes = _build_routes(
            allows=[],  # nothing allowed
            agent_id_map={'coding-lead': 'proj/coding/lead'},
        )
        mcp_registry.register_agent_mcp_routes('unknown-caller', routes)
        mcp_registry.current_agent_name.set('unknown-caller')

        result = _run(_default_send_post('also-unknown', 'msg', ''))
        payload = json.loads(result)
        self.assertEqual(payload['status'], 'failed')
        self.assertIn('Routing refused', payload['reason'])
        # Both ends fall through unmapped:
        self.assertIn('unknown-caller', payload['reason'])
        self.assertIn('also-unknown', payload['reason'])


class TestMCPRoutesCarriesDispatcher(unittest.TestCase):
    """Structural: register_agent_mcp_routes installs both fields."""

    def setUp(self):
        mcp_registry.clear()

    def tearDown(self):
        mcp_registry.clear()

    def test_register_installs_dispatcher_in_lookup(self):
        table = RoutingTable()
        table.add_pair('a', 'b')
        dispatcher = BusDispatcher(table)
        id_map = {'name': 'a'}
        routes = mcp_registry.MCPRoutes(
            spawn_fn=lambda *a, **kw: None,
            dispatcher=dispatcher,
            agent_id_map=id_map,
        )
        mcp_registry.register_agent_mcp_routes('caller', routes)

        self.assertIs(mcp_registry.get_dispatcher('caller'), dispatcher)
        self.assertEqual(
            mcp_registry.get_agent_id_map('caller'), id_map,
        )

    def test_clear_removes_dispatcher_and_map(self):
        table = RoutingTable()
        table.add_pair('a', 'b')
        routes = mcp_registry.MCPRoutes(
            dispatcher=BusDispatcher(table),
            agent_id_map={'x': 'y'},
        )
        mcp_registry.register_agent_mcp_routes('caller', routes)
        mcp_registry.clear()

        self.assertIsNone(mcp_registry.get_dispatcher('caller'))
        self.assertEqual(mcp_registry.get_agent_id_map('caller'), {})


if __name__ == '__main__':
    unittest.main()
