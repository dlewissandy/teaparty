"""Routing scope is set by the dispatcher, carried into the dispatch.

The bug class this pins: when a parent dispatches a child, what
routing table enforces the CHILD's Send calls?

Pre-fix: launcher inherited the parent's ``mcp_routes`` and
registered the parent's dispatcher under the child's name.  The
child then authorized against the *parent's* roster — wrong scope,
every cross-team Send refused.

Half-fix: the launcher rebuilt a per-agent dispatcher from
``derive_team_roster(agent_name, teaparty_home)``.  That worked for
same-repo dispatch but broke for cross-repo dispatch (the agent's
local tp had no management config and the lookup returned ``None``,
falling back to the parent's dispatcher again).  An ``org_home or
teaparty_home`` fallback was a smell — two sources of truth.

Final fix: routing scope is a property of the *dispatch*.  The
dispatcher knows its own identity (parent_lead) and its own
config tree, computes the child's dispatcher once at the dispatch
site, and slots it into the child's ``mcp_routes``.  The launcher
just registers what was passed — no re-derivation, no
``which-tp?`` ambiguity.

This test pins the contract: ``build_session_dispatcher`` accepts
``parent_lead`` (a property of the dispatch, not the team) and
yields a routing table whose gateway pair reflects that conversation
context.  Same workgroup loaned to two different parents must
produce two different gateway pairs.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest

import yaml


def _make_org_with_workgroup() -> str:
    """Create a minimal teaparty home with a Configuration workgroup."""
    home = tempfile.mkdtemp(prefix='dispatch-scope-')
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

    for agent in ('office-manager', 'configuration-lead', 'project-specialist'):
        with open(
            os.path.join(mgmt, 'agents', agent, 'agent.md'), 'w',
        ) as f:
            f.write(f'---\nname: {agent}\n---\nplaceholder\n')

    return tp


class TestDispatcherBuildsAtDispatchSite(unittest.TestCase):
    """The dispatcher's tp + identity determine the child's routing."""

    def setUp(self) -> None:
        self._tp = _make_org_with_workgroup()
        self.addCleanup(shutil.rmtree, os.path.dirname(self._tp), True)
        from teaparty.mcp import registry
        registry.clear()
        self.addCleanup(registry.clear)

    def test_workgroup_lead_dispatch_authorizes_workgroup_mesh(self) -> None:
        """When OM dispatches configuration-lead, the child's dispatcher
        authorizes configuration-lead → project-specialist (workgroup
        mesh) and configuration-lead → office-manager (parent gateway).
        OM's roster does NOT include the workgroup mesh; the dispatcher
        built at the dispatch site does.
        """
        from teaparty.messaging.child_dispatch import (
            build_session_dispatcher,
        )
        from teaparty.messaging.dispatcher import RoutingError

        # Mirror schedule_child_dispatch: build child's dispatcher with
        # parent_lead=dispatcher's identity.
        child_d = build_session_dispatcher(
            teaparty_home=self._tp,
            lead_name='configuration-lead',
            parent_lead='office-manager',
        )
        self.assertIsNotNone(child_d)
        child_d.authorize('configuration-lead', 'project-specialist')
        child_d.authorize('configuration-lead', 'office-manager')
        with self.assertRaises(RoutingError):
            # Cross-team: configuration-lead does NOT directly route to
            # the OM's other members.
            child_d.authorize('configuration-lead', 'random-other-lead')

    def test_om_dispatcher_alone_would_have_refused(self) -> None:
        """Sanity: OM's own dispatcher does not include the workgroup
        mesh — the dispatch-site rebuild is what makes the child
        correctly authorized.
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

    def test_parent_lead_is_a_dispatch_property_not_team_property(
        self,
    ) -> None:
        """Same team, different parent_lead → different gateway pair.

        Pins the matrix-loan invariant: a workgroup's parent_lead is
        determined by the conversation that initiated the dispatch,
        not by the workgroup itself.  The team is one team; the gateway
        pair is conversation-scoped.
        """
        from teaparty.messaging.child_dispatch import (
            build_session_dispatcher,
        )
        from teaparty.messaging.dispatcher import RoutingError

        d_via_om = build_session_dispatcher(
            teaparty_home=self._tp,
            lead_name='configuration-lead',
            parent_lead='office-manager',
        )
        d_via_other = build_session_dispatcher(
            teaparty_home=self._tp,
            lead_name='configuration-lead',
            parent_lead='hypothetical-other-parent',
        )

        # Each dispatch context has the matching gateway pair, and only
        # that one.
        d_via_om.authorize('configuration-lead', 'office-manager')
        with self.assertRaises(RoutingError):
            d_via_om.authorize(
                'configuration-lead', 'hypothetical-other-parent',
            )

        d_via_other.authorize(
            'configuration-lead', 'hypothetical-other-parent',
        )
        with self.assertRaises(RoutingError):
            d_via_other.authorize('configuration-lead', 'office-manager')


if __name__ == '__main__':
    unittest.main()
