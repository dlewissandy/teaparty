#!/usr/bin/env python3
"""Tests for teaparty.config.roster.

Covers:
 1. derive_om_roster — single source of truth for "who is on the OM's team"
 2. has_sub_roster — structural check for sub-roster presence
 3. RoutingTable.from_management_roster — OM-level routing
"""
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.config.roster import (
    derive_om_roster,
    has_sub_roster,
)
from teaparty.messaging.dispatcher import RoutingTable


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_teaparty_home(
    teaparty_yaml: str,
    workgroup_files: dict[str, str] | None = None,
    agent_files: dict[str, str] | None = None,
) -> str:
    """Create a temp ~/.teaparty/ tree with management config and optional agents."""
    home = tempfile.mkdtemp()
    mgmt_dir = os.path.join(home, '.teaparty', 'management')
    os.makedirs(mgmt_dir)
    with open(os.path.join(mgmt_dir, 'teaparty.yaml'), 'w') as f:
        f.write(teaparty_yaml)
    if workgroup_files:
        wg_dir = os.path.join(mgmt_dir, 'workgroups')
        os.makedirs(wg_dir, exist_ok=True)
        for name, content in workgroup_files.items():
            with open(os.path.join(wg_dir, name), 'w') as f:
                f.write(content)
    if agent_files:
        agents_dir = os.path.join(home, '.claude', 'agents')
        os.makedirs(agents_dir, exist_ok=True)
        for name, content in agent_files.items():
            with open(os.path.join(agents_dir, name), 'w') as f:
                f.write(content)
    return home


def _make_project_dir(project_yaml: str, workgroup_files: dict[str, str] | None = None) -> str:
    """Create a temp project dir with .teaparty/project/project.yaml."""
    proj = tempfile.mkdtemp()
    tp_project = os.path.join(proj, '.teaparty', 'project')
    os.makedirs(tp_project)
    with open(os.path.join(tp_project, 'project.yaml'), 'w') as f:
        f.write(project_yaml)
    os.makedirs(os.path.join(proj, '.git'), exist_ok=True)
    os.makedirs(os.path.join(proj, '.teaparty'), exist_ok=True)
    if workgroup_files:
        wg_dir = os.path.join(tp_project, 'workgroups')
        os.makedirs(wg_dir, exist_ok=True)
        for name, content in workgroup_files.items():
            with open(os.path.join(wg_dir, name), 'w') as f:
                f.write(content)
    return proj


WORKGROUP_CODING_YAML = textwrap.dedent("""\
    name: Coding
    description: Implements features and fixes bugs.
    lead: coding-lead
    members:
      agents:
        - developer
        - reviewer
        - architect
""")

WORKGROUP_RESEARCH_YAML = textwrap.dedent("""\
    name: Research
    description: Surveys prior art and evaluates approaches.
    lead: research-lead
    members:
      agents:
        - surveyor
""")


# ── 1. derive_om_roster ─────────────────────────────────────────────────────

class TestDeriveOmRoster(unittest.TestCase):
    """OM roster includes project leads and management agents."""

    def setUp(self):
        self.proj = _make_project_dir(textwrap.dedent("""\
            name: Alpha
            description: Alpha project.
            lead: alpha-lead
            members:
              workgroups:
                - Coding
            workgroups:
              - ref: Coding
        """))
        yaml_text = textwrap.dedent(f"""\
            name: Management Team
            description: Management.
            lead: office-manager
            projects:
              - name: Alpha
                path: {self.proj}
                config: .teaparty/project/project.yaml
            members:
              projects:
                - Alpha
              agents:
                - auditor
        """)
        self.home = _make_teaparty_home(
            yaml_text,
            agent_files={
                'auditor.md': '---\nname: auditor\ndescription: Code audits.\n---\nAuditor agent.',
                'alpha-lead.md': '---\nname: alpha-lead\ndescription: Alpha lead.\n---\n',
            },
        )

    def test_roster_includes_project_lead(self):
        roster = derive_om_roster(os.path.join(self.home, '.teaparty'))
        self.assertIn('alpha-lead', roster)
        self.assertEqual(roster['alpha-lead']['description'], 'Alpha project.')

    def test_roster_excludes_unlisted_agents(self):
        """Agents in members.agents are not included — membership is derived
        from humans, members.projects, and members.workgroups only."""
        roster = derive_om_roster(
            os.path.join(self.home, '.teaparty'),
            agents_dir=os.path.join(self.home, '.claude', 'agents'),
        )
        self.assertNotIn('auditor', roster)

    def test_roster_includes_every_registered_project(self):
        """Every project in the catalog appears in the OM roster (#422).

        Before #422 there were two sources of truth — the catalog
        (``projects``) and a separate ``members.projects`` list.  They
        could disagree: a project could be registered but not
        dispatchable.  #422 collapsed them: the roster is derived from
        the catalog, full stop.  This test pins that invariant.
        """
        proj_b = _make_project_dir(textwrap.dedent("""\
            name: Bravo
            description: Bravo project.
            lead: bravo-lead
            members:
              workgroups: []
            workgroups: []
        """))
        yaml_text = textwrap.dedent(f"""\
            name: Management Team
            description: Management.
            lead: office-manager
            projects:
              - name: Alpha
                path: {self.proj}
                config: .teaparty/project/project.yaml
              - name: Bravo
                path: {proj_b}
                config: .teaparty/project/project.yaml
            members: {{}}
        """)
        home = _make_teaparty_home(yaml_text)
        roster = derive_om_roster(os.path.join(home, '.teaparty'))
        lead_names = sorted(k for k in roster if k.endswith('-lead'))
        self.assertEqual(
            lead_names, ['alpha-lead', 'bravo-lead'],
            'Both registered projects must surface their leads in '
            'the OM roster — the catalog is the single source of truth',
        )

    def test_legacy_members_projects_on_disk_is_ignored(self):
        """A stale ``members.projects: []`` on disk is ignored (#422).

        Under the old two-source model this would have produced an
        empty roster.  Under #422 the catalog is authoritative, so a
        leftover empty ``members.projects`` value must not hide a
        registered project.
        """
        yaml_text = textwrap.dedent(f"""\
            name: Management Team
            description: Management.
            lead: office-manager
            projects:
              - name: Alpha
                path: {self.proj}
                config: .teaparty/project/project.yaml
            members:
              projects: []
        """)
        home = _make_teaparty_home(yaml_text)
        roster = derive_om_roster(os.path.join(home, '.teaparty'))
        self.assertIn(
            'alpha-lead', roster,
            'A legacy empty members.projects list on disk must not '
            'shadow the catalog — otherwise the two-source bug is back',
        )

    def test_roster_includes_member_workgroup_leads(self):
        """Workgroups declared under members.workgroups appear in the
        OM's roster — both the routing layer (via build_session_dispatcher)
        and the list-members tool consume the same dict, so reporting
        and authorization cannot disagree.
        """
        wg_yaml = textwrap.dedent("""\
            name: Configuration
            description: Config team.
            lead: configuration-lead
            members:
              agents: []
        """)
        home = _make_teaparty_home(
            textwrap.dedent("""\
                name: Management Team
                description: Test.
                lead: office-manager
                projects: []
                members:
                  projects: []
                  workgroups:
                  - Configuration
                workgroups:
                - name: Configuration
                  config: workgroups/configuration.yaml
            """),
            workgroup_files={'configuration.yaml': wg_yaml},
        )
        roster = derive_om_roster(os.path.join(home, '.teaparty'))
        self.assertIn(
            'configuration-lead', roster,
            'A workgroup declared in members.workgroups must surface '
            'its lead in the OM roster — otherwise routing refuses '
            'OM → workgroup-lead dispatches that the list-members '
            'tool reports as valid.',
        )
        self.assertEqual(
            roster['configuration-lead']['role'], 'workgroup-lead',
        )

    def test_catalog_only_workgroup_excluded_from_roster(self):
        """A workgroup in the catalog but not in members.workgroups
        must NOT appear in the OM roster — catalog ≠ membership."""
        wg_yaml = textwrap.dedent("""\
            name: Coding
            description: Code team.
            lead: coding-lead
            members:
              agents: []
        """)
        home = _make_teaparty_home(
            textwrap.dedent("""\
                name: Management Team
                description: Test.
                lead: office-manager
                projects: []
                members:
                  projects: []
                  workgroups: []
                workgroups:
                - name: Coding
                  config: workgroups/coding.yaml
            """),
            workgroup_files={'coding.yaml': wg_yaml},
        )
        roster = derive_om_roster(os.path.join(home, '.teaparty'))
        self.assertNotIn(
            'coding-lead', roster,
            'A workgroup in the catalog but not declared via '
            'members.workgroups must not appear in the OM roster.',
        )

    def test_roster_includes_proxy(self):
        """One ``proxy`` entry per declared human."""
        yaml_text = textwrap.dedent(f"""\
            name: Management Team
            description: Test.
            lead: office-manager
            humans:
              decider: alice
            projects:
              - name: Alpha
                path: {self.proj}
                config: .teaparty/project/project.yaml
            members:
              projects: []
              workgroups: []
        """)
        home = _make_teaparty_home(yaml_text)
        roster = derive_om_roster(os.path.join(home, '.teaparty'))
        self.assertIn(
            'proxy', roster,
            'Proxy must be in the roster for the OM to dispatch to it.',
        )
        self.assertEqual(roster['proxy']['role'], 'proxy')


# ── 2. has_sub_roster ───────────────────────────────────────────────────────

class TestHasSubRoster(unittest.TestCase):
    """Structural check for sub-roster presence."""

    def setUp(self):
        self.proj = _make_project_dir(
            textwrap.dedent("""\
                name: Alpha
                description: Alpha project.
                lead: alpha-lead
                members:
                  workgroups:
                    - Coding
                workgroups:
                  - ref: Coding
            """),
            workgroup_files={'Coding.yaml': WORKGROUP_CODING_YAML},
        )
        yaml_text = textwrap.dedent(f"""\
            name: Management Team
            description: Management.
            lead: office-manager
            projects:
              - name: Alpha
                path: {self.proj}
                config: .teaparty/project/project.yaml
            members:
              projects:
                - Alpha
              agents:
                - auditor
        """)
        self.home = _make_teaparty_home(yaml_text)
        self.teaparty_home = os.path.join(self.home, '.teaparty')

    def test_project_lead_has_sub_roster(self):
        self.assertTrue(has_sub_roster(
            'alpha-lead', self.teaparty_home, project_dir=self.proj,
        ))

    def test_workgroup_lead_has_sub_roster(self):
        self.assertTrue(has_sub_roster(
            'coding-lead', self.teaparty_home, project_dir=self.proj,
        ))

    def test_leaf_agent_has_no_sub_roster(self):
        self.assertFalse(has_sub_roster(
            'developer', self.teaparty_home, project_dir=self.proj,
        ))

    def test_management_agent_has_no_sub_roster(self):
        self.assertFalse(has_sub_roster(
            'auditor', self.teaparty_home, project_dir=self.proj,
        ))


# ── 5. RoutingTable.from_management_roster ──────────────────────────────────

class TestRoutingTableFromManagementRoster(unittest.TestCase):
    """OM-level routing table from roster — keys directly on agent names."""

    def test_om_can_send_to_roster_members(self):
        roster = {'alpha-lead': {}, 'auditor': {}}
        table = RoutingTable.from_management_roster(
            roster, om_agent_name='office-manager',
        )
        self.assertTrue(table.allows('office-manager', 'alpha-lead'))
        self.assertTrue(table.allows('office-manager', 'auditor'))

    def test_roster_members_can_reply_to_om(self):
        roster = {'alpha-lead': {}}
        table = RoutingTable.from_management_roster(
            roster, om_agent_name='office-manager',
        )
        self.assertTrue(table.allows('alpha-lead', 'office-manager'))

    def test_roster_members_cannot_reach_each_other(self):
        roster = {'alpha-lead': {}, 'auditor': {}}
        table = RoutingTable.from_management_roster(
            roster, om_agent_name='office-manager',
        )
        self.assertFalse(table.allows('alpha-lead', 'auditor'))

    def test_om_in_its_own_roster_raises(self):
        """OM is the subject of the roster, not a member.  A duplicate
        is a configuration error."""
        from teaparty.messaging.dispatcher import DuplicateAgentName
        roster = {'office-manager': {}, 'alpha-lead': {}}
        with self.assertRaises(DuplicateAgentName):
            RoutingTable.from_management_roster(
                roster, om_agent_name='office-manager',
            )


if __name__ == '__main__':
    unittest.main()
