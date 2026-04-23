#!/usr/bin/env python3
"""Tests for teaparty.config.roster — roster derivation for recursive bus dispatch.

Covers:
 1. derive_om_roster — OM roster from teaparty.yaml members.projects + members.agents
 2. derive_project_roster — project lead roster from project.yaml members.workgroups
 3. derive_workgroup_roster — workgroup lead roster from workgroup YAML members.agents
 4. has_sub_roster — structural check for sub-roster presence
 5. agent_id_map — agent name to scoped agent ID mapping
 6. RoutingTable.from_management_roster — OM-level routing
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
    derive_project_roster,
    derive_workgroup_roster,
    has_sub_roster,
    agent_id_map,
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


# ── 2. derive_project_roster ────────────────────────────────────────────────

class TestDeriveProjectRoster(unittest.TestCase):
    """Project lead roster includes workgroup leads."""

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
        self.home = _make_teaparty_home(textwrap.dedent("""\
            name: Management Team
            description: Management.
            lead: office-manager
            projects: []
        """))

    def test_roster_includes_workgroup_lead(self):
        roster = derive_project_roster(
            self.proj, os.path.join(self.home, '.teaparty'),
        )
        self.assertIn('coding-lead', roster)
        self.assertEqual(roster['coding-lead']['description'], 'Implements features and fixes bugs.')

    def test_empty_workgroups_produces_empty_roster(self):
        proj = _make_project_dir(textwrap.dedent("""\
            name: Beta
            description: Beta project.
            lead: beta-lead
            workgroups: []
        """))
        roster = derive_project_roster(
            proj, os.path.join(self.home, '.teaparty'),
        )
        self.assertEqual(roster, {})


# ── 3. derive_workgroup_roster ──────────────────────────────────────────────

class TestDeriveWorkgroupRoster(unittest.TestCase):
    """Workgroup lead roster includes member agents."""

    def setUp(self):
        self.wg_dir = tempfile.mkdtemp()
        self.wg_path = os.path.join(self.wg_dir, 'coding.yaml')
        with open(self.wg_path, 'w') as f:
            f.write(WORKGROUP_CODING_YAML)

    def test_roster_includes_all_agents(self):
        roster = derive_workgroup_roster(self.wg_path)
        self.assertIn('developer', roster)
        self.assertIn('reviewer', roster)
        self.assertIn('architect', roster)
        self.assertEqual(len(roster), 3)

    def test_agent_descriptions_from_frontmatter(self):
        agents_dir = os.path.join(self.wg_dir, 'agents')
        os.makedirs(agents_dir)
        with open(os.path.join(agents_dir, 'developer.md'), 'w') as f:
            f.write('---\nname: developer\ndescription: Writes code.\n---\n')
        roster = derive_workgroup_roster(self.wg_path, agents_dir=agents_dir)
        self.assertEqual(roster['developer']['description'], 'Writes code.')

    def test_missing_agent_file_uses_name(self):
        roster = derive_workgroup_roster(self.wg_path)
        # No agent files exist, so description falls back to agent name
        self.assertEqual(roster['developer']['description'], 'developer')


# ── 4. has_sub_roster ───────────────────────────────────────────────────────

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


# ── 5. agent_id_map ────────────────────────────────────────────────────────

class TestAgentIdMap(unittest.TestCase):
    """Agent name to scoped agent ID mapping."""

    def test_om_level_project_leads(self):
        roster = {'alpha-lead': {}, 'auditor': {}}
        mapping = agent_id_map(roster, 'om')
        self.assertEqual(mapping['alpha-lead'], 'alpha/lead')
        self.assertEqual(mapping['auditor'], 'om/auditor')

    def test_project_level_workgroup_leads(self):
        roster = {'coding-lead': {}, 'research-lead': {}}
        mapping = agent_id_map(roster, 'project', project_name='alpha')
        self.assertEqual(mapping['coding-lead'], 'alpha/coding/lead')
        self.assertEqual(mapping['research-lead'], 'alpha/research/lead')

    def test_workgroup_level_agents(self):
        roster = {'developer': {}, 'reviewer': {}}
        mapping = agent_id_map(
            roster, 'workgroup',
            project_name='alpha', workgroup_name='coding',
        )
        self.assertEqual(mapping['developer'], 'alpha/coding/developer')
        self.assertEqual(mapping['reviewer'], 'alpha/coding/reviewer')


# ── 6. RoutingTable.from_management_roster ──────────────────────────────────

class TestRoutingTableFromManagementRoster(unittest.TestCase):
    """OM-level routing table from roster."""

    def test_om_can_send_to_roster_members(self):
        roster = {'alpha-lead': {}, 'auditor': {}}
        id_map = {'alpha-lead': 'alpha/lead', 'auditor': 'om/auditor'}
        table = RoutingTable.from_management_roster(roster, id_map)
        self.assertTrue(table.allows('om', 'alpha/lead'))
        self.assertTrue(table.allows('om', 'om/auditor'))

    def test_roster_members_can_reply_to_om(self):
        roster = {'alpha-lead': {}}
        id_map = {'alpha-lead': 'alpha/lead'}
        table = RoutingTable.from_management_roster(roster, id_map)
        self.assertTrue(table.allows('alpha/lead', 'om'))

    def test_roster_members_cannot_reach_each_other(self):
        roster = {'alpha-lead': {}, 'auditor': {}}
        id_map = {'alpha-lead': 'alpha/lead', 'auditor': 'om/auditor'}
        table = RoutingTable.from_management_roster(roster, id_map)
        self.assertFalse(table.allows('alpha/lead', 'om/auditor'))


if __name__ == '__main__':
    unittest.main()
