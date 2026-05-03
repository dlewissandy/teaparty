"""AgentSession uses the registry tp (org_home) for routing/placement,
not the per-project execution tp.

The bug this pins: an external project lead (e.g. joke-book-lead) has
two distinct tps:

  * Execution tp = project's local ``.teaparty/`` (joke-book/.teaparty)
    — where the agent's session data, message bus, etc. live.
  * Registry tp = bridge's own ``.teaparty/`` — where the project is
    registered as a member, and where ``derive_team_roster`` /
    ``resolve_launch_placement`` walk to find this agent's team.

Pre-fix, AgentSession used ``teaparty_home`` (the project's local tp)
for routing too.  Joke-book's local tp has no management config, so
``derive_team_roster`` returned None → no dispatcher → Send fell
through unauthorized → spawn_fn refused with ``unresolved_member``
because ``resolve_launch_placement`` also failed against the wrong
tp.  Result: agent narrated "dispatched!" but no accordion blade
appeared, no reply ever returned.

The bridge instantiates the page and knows the shard.  It passes
``org_home`` explicitly.  AgentSession uses ``_org_home`` for
routing/placement, ``teaparty_home`` for execution/storage.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest

import yaml


def _make_two_tp_layout() -> tuple[str, str]:
    """Create:

      bridge's tp (registry):  has full management config; registers
                               the external project ``ext-proj`` whose
                               lead is ``ext-lead``.
      project's tp (execution): the external project's own
                                ``.teaparty/`` with project.yaml and
                                no management config.
    """
    root = tempfile.mkdtemp(prefix='session-tp-')
    bridge_repo = os.path.join(root, 'bridge-repo')
    project_repo = os.path.join(root, 'ext-proj')
    bridge_tp = os.path.join(bridge_repo, '.teaparty')
    project_tp = os.path.join(project_repo, '.teaparty')

    # Bridge tp: full mgmt config + a workgroup the external project uses.
    os.makedirs(os.path.join(bridge_tp, 'management', 'workgroups'))
    os.makedirs(os.path.join(
        bridge_tp, 'management', 'agents', 'office-manager'))
    with open(os.path.join(bridge_tp, 'management', 'teaparty.yaml'), 'w') as f:
        yaml.dump({
            'name': 'Mgmt',
            'description': 'Test',
            'lead': 'office-manager',
            'projects': [
                {'name': 'ext-proj', 'path': project_repo,
                 'config': '.teaparty/project/project.yaml'},
            ],
            'members': {
                'projects': ['ext-proj'],
                'workgroups': [],
            },
            'workgroups': [
                {'name': 'Coding',
                 'config': 'workgroups/coding.yaml'},
            ],
        }, f)
    with open(os.path.join(
            bridge_tp, 'management', 'workgroups', 'coding.yaml'), 'w') as f:
        yaml.dump({
            'name': 'Coding',
            'description': 'Code team',
            'lead': 'coding-lead',
            'members': {'agents': ['developer']},
        }, f)
    with open(os.path.join(
            bridge_tp, 'management', 'agents', 'office-manager',
            'agent.md'), 'w') as f:
        f.write('---\nname: office-manager\n---\nplaceholder\n')

    # Project tp: ONLY the project config, no management config.
    os.makedirs(os.path.join(project_tp, 'project'))
    os.makedirs(os.path.join(project_tp, 'management', 'agents', 'ext-lead'))
    with open(os.path.join(project_tp, 'project', 'project.yaml'), 'w') as f:
        yaml.dump({
            'name': 'ext-proj',
            'description': 'External project',
            'lead': 'ext-lead',
            'workgroups': [{'ref': 'coding'}],
            'members': {'workgroups': ['Coding']},
        }, f)
    with open(os.path.join(
            project_tp, 'management', 'agents', 'ext-lead',
            'agent.md'), 'w') as f:
        f.write('---\nname: ext-lead\n---\nplaceholder\n')

    return bridge_tp, project_tp


class TestSessionUsesRegistryTpForRouting(unittest.TestCase):
    """When org_home (registry tp) and teaparty_home (execution tp)
    differ, the session's dispatcher is built from the registry tp
    — only that tree contains the agent's team registration.
    """

    def setUp(self) -> None:
        self.bridge_tp, self.project_tp = _make_two_tp_layout()
        self._root = os.path.dirname(self.bridge_tp)
        self.addCleanup(shutil.rmtree, self._root, True)

    def test_dispatcher_uses_registry_tp_when_execution_tp_lacks_mgmt_config(
        self,
    ) -> None:
        """Pre-fix this would have built no dispatcher (project's
        local tp has no management config).  Post-fix the dispatcher
        IS built — from the bridge's tp — and authorizes ext-lead's
        team mesh.
        """
        from teaparty.messaging.child_dispatch import (
            build_session_dispatcher,
        )

        # Mirror what AgentSession.__init__ now does: when the bridge
        # passes org_home, _org_home holds it (the registry tp).
        registry_tp = self.bridge_tp     # what AgentSession._org_home holds
        execution_tp = self.project_tp   # what AgentSession.teaparty_home holds

        # Crucially: building the dispatcher with the EXECUTION tp
        # would fail (no mgmt config there).
        d_via_execution = build_session_dispatcher(
            teaparty_home=execution_tp, lead_name='ext-lead',
        )
        self.assertIsNone(
            d_via_execution,
            'precondition: project tp has no mgmt config, so derive '
            'against it would return no dispatcher — exactly the '
            'bug condition',
        )

        # Building with the REGISTRY tp (what _ensure_bus_listener
        # now does) succeeds and authorizes the team mesh.
        d_via_registry = build_session_dispatcher(
            teaparty_home=registry_tp, lead_name='ext-lead',
        )
        self.assertIsNotNone(d_via_registry)
        d_via_registry.authorize('ext-lead', 'coding-lead')

    def test_resolve_launch_placement_via_registry_tp(self) -> None:
        """Same principle for placement: spawn_fn's
        ``resolve_launch_placement`` for the dispatched member must
        walk the registry tp, where the member is registered.
        """
        from teaparty.config.roster import (
            resolve_launch_placement, LaunchCwdNotResolved,
        )

        with self.assertRaises(LaunchCwdNotResolved):
            # Project tp has no mgmt config — placement fails.
            resolve_launch_placement('coding-lead', self.project_tp)

        # Registry tp has the member registered.
        cwd, scope = resolve_launch_placement('coding-lead', self.bridge_tp)
        self.assertEqual(scope, 'management')


if __name__ == '__main__':
    unittest.main()
