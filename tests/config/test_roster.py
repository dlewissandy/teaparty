#!/usr/bin/env python3
"""Tests for teaparty.config.roster.

Covers:
 1. derive_team_roster — the single public entry point: given a lead
    name, returns the flat roster of the team that lead heads
 2. build_routing_table from a management Roster — OM-level routing
"""
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.config.roster import derive_team_roster
from teaparty.messaging.dispatcher import RoutingTable, build_routing_table


def _names(roster) -> dict[str, dict]:
    """Convert a Roster to a {name: {role, description, ...}} dict
    matching the legacy shape (so existing assertions read naturally)."""
    out: dict[str, dict] = {}
    for m in roster.members:
        entry = {'role': m.role, 'description': m.description}
        if m.project:
            entry['project'] = m.project
        if m.workgroup:
            entry['workgroup'] = m.workgroup
        if m.human:
            entry['human'] = m.human
        out[m.name] = entry
    return out


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


# ── 1. derive_team_roster (OM's team) ───────────────────────────────────────

class TestDeriveRoster(unittest.TestCase):
    """OM roster includes project leads and management agents.

    Calls ``derive_team_roster('office-manager', teaparty_home)`` —
    the single public entry point.  The OM is found at the root of
    the org tree, so its team's roster is returned.
    """

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
        roster = _names(derive_team_roster(
            'office-manager', os.path.join(self.home, '.teaparty'),
        ))
        self.assertIn('alpha-lead', roster)
        self.assertEqual(roster['alpha-lead']['description'], 'Alpha project.')

    def test_roster_excludes_unlisted_agents(self):
        """Agents in members.agents are not included — membership is derived
        from humans, members.projects, and members.workgroups only."""
        roster = _names(derive_team_roster(
            'office-manager', os.path.join(self.home, '.teaparty'),
        ))
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
        roster = _names(derive_team_roster(
            'office-manager', os.path.join(home, '.teaparty'),
        ))
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
        roster = _names(derive_team_roster(
            'office-manager', os.path.join(home, '.teaparty'),
        ))
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
        roster = _names(derive_team_roster(
            'office-manager', os.path.join(home, '.teaparty'),
        ))
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
        roster = _names(derive_team_roster(
            'office-manager', os.path.join(home, '.teaparty'),
        ))
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
        roster = _names(derive_team_roster(
            'office-manager', os.path.join(home, '.teaparty'),
        ))
        self.assertIn(
            'proxy', roster,
            'Proxy must be in the roster for the OM to dispatch to it.',
        )
        self.assertEqual(roster['proxy']['role'], 'proxy')


# ── 1b. derive_team_roster lead-only contract ──────────────────────────────

class TestDeriveTeamRosterLeadOnly(unittest.TestCase):
    """``derive_team_roster`` is keyed by **lead**, not by any agent name.

    A workgroup member can belong to several workgroups — the same
    agent can appear in multiple ``members.agents`` lists — so
    "their team" is ambiguous.  Leads, on the other hand, are 1:1
    with their team: a lead heads exactly one team.  The lookup is
    therefore restricted to leads; non-leads return ``None``.
    """

    def setUp(self):
        # Two workgroups that BOTH contain agent 'shared-dev'.
        wg_alpha = textwrap.dedent("""\
            name: Alpha-WG
            description: Alpha workgroup.
            lead: alpha-wg-lead
            members:
              agents:
                - shared-dev
                - alpha-only
        """)
        wg_beta = textwrap.dedent("""\
            name: Beta-WG
            description: Beta workgroup.
            lead: beta-wg-lead
            members:
              agents:
                - shared-dev
                - beta-only
        """)
        self.home = _make_teaparty_home(
            textwrap.dedent("""\
                name: Management Team
                description: Test.
                lead: office-manager
                projects: []
                members:
                  projects: []
                  workgroups:
                    - Alpha-WG
                    - Beta-WG
                workgroups:
                  - name: Alpha-WG
                    config: workgroups/alpha.yaml
                  - name: Beta-WG
                    config: workgroups/beta.yaml
            """),
            workgroup_files={
                'alpha.yaml': wg_alpha,
                'beta.yaml': wg_beta,
            },
        )
        self.tp = os.path.join(self.home, '.teaparty')

    def test_lead_lookup_returns_their_team(self):
        """A workgroup lead's lookup returns their workgroup's roster."""
        roster = derive_team_roster('alpha-wg-lead', self.tp)
        self.assertIsNotNone(roster, 'workgroup lead must resolve')
        self.assertEqual(roster.lead, 'alpha-wg-lead')
        names = {m.name for m in roster.members}
        self.assertIn('shared-dev', names)
        self.assertIn('alpha-only', names)
        # The OTHER workgroup's members must not bleed in.
        self.assertNotIn('beta-only', names)

    def test_om_lookup_returns_om_team(self):
        roster = derive_team_roster('office-manager', self.tp)
        self.assertIsNotNone(roster)
        self.assertEqual(roster.lead, 'office-manager')

    def test_member_in_multiple_workgroups_returns_none(self):
        """An agent who is a member of multiple workgroups has no
        single team — the lookup returns ``None`` rather than
        arbitrarily picking one.  Ambiguity is the exact reason
        the function is keyed by lead.
        """
        result = derive_team_roster('shared-dev', self.tp)
        self.assertIsNone(
            result,
            'A non-lead agent in two workgroups must not resolve to '
            'either one — that lookup is ill-defined and the function '
            'must say so by returning None',
        )

    def test_unknown_agent_returns_none(self):
        result = derive_team_roster('does-not-exist', self.tp)
        self.assertIsNone(result)


# ── 1c. Matrix workgroup loans (regression: shared workgroup) ──────────────

class TestMatrixWorkgroupLoan(unittest.TestCase):
    """A workgroup loaned to multiple projects is ONE team.

    Pre-fix bug: ``_org_tree`` materialized the org as a recursive
    structure where every project got its own copy of every workgroup
    it referenced.  When the SAME workgroup was loaned to two projects,
    its lead appeared as the lead of two distinct sub-rosters and the
    OM session crashed with ``DuplicateAgentName``.

    Under the matrix model the team is one team; ``parent_lead`` is a
    conversation property set by the dispatcher per-session, not baked
    into a global tree.
    """

    def setUp(self):
        # Two projects that BOTH reference the management-level
        # 'Research' workgroup via ``ref:``.  Pre-fix, this layout
        # crashed OM dispatcher construction.
        proj_comics = _make_project_dir(textwrap.dedent("""\
            name: Comics
            description: Comics project.
            lead: comics-lead
            members:
              workgroups:
                - Research
            workgroups:
              - ref: Research
        """))
        proj_jokebook = _make_project_dir(textwrap.dedent("""\
            name: JokeBook
            description: JokeBook project.
            lead: joke-book-lead
            members:
              workgroups:
                - Research
            workgroups:
              - ref: Research
        """))
        self.home = _make_teaparty_home(
            textwrap.dedent(f"""\
                name: Management Team
                description: Test.
                lead: office-manager
                projects:
                  - name: Comics
                    path: {proj_comics}
                    config: .teaparty/project/project.yaml
                  - name: JokeBook
                    path: {proj_jokebook}
                    config: .teaparty/project/project.yaml
                members:
                  projects:
                    - Comics
                    - JokeBook
            """),
            workgroup_files={'Research.yaml': WORKGROUP_RESEARCH_YAML},
        )
        self.tp = os.path.join(self.home, '.teaparty')

    def test_om_roster_builds_without_duplicate_lead_crash(self):
        """The OM session derivation must succeed with shared workgroups."""
        roster = derive_team_roster('office-manager', self.tp)
        self.assertIsNotNone(roster)
        # And the routing table builds cleanly.
        table = build_routing_table(roster)
        self.assertTrue(
            table.allows('office-manager', 'comics-lead'),
            'OM must reach both project leads regardless of any '
            'workgroup they share',
        )
        self.assertTrue(table.allows('office-manager', 'joke-book-lead'))

    def test_workgroup_lead_resolves_to_one_team(self):
        """``research-lead`` is the lead of ONE Research workgroup,
        no matter how many projects loan it.
        """
        roster = derive_team_roster('research-lead', self.tp)
        self.assertIsNotNone(
            roster,
            'Workgroup leads loaned to multiple projects must still '
            'resolve to their (single) team',
        )
        self.assertEqual(roster.lead, 'research-lead')
        member_names = {m.name for m in roster.members}
        self.assertIn('surveyor', member_names)


# ── 2. build_routing_table from a management Roster ───────────────────────

class TestRoutingTableFromManagementRoster(unittest.TestCase):
    """OM-level routing table — keys directly on agent names."""

    def _make_roster(self, member_names: list[str]) -> 'Roster':
        from teaparty.config.roster import Roster, Member
        return Roster(
            lead='office-manager',
            members=[
                Member(name=n, role='project-lead') for n in member_names
            ],
            mesh_among_members=False,
            parent_lead='',
        )

    def test_om_can_send_to_roster_members(self):
        table = build_routing_table(self._make_roster(['alpha-lead', 'auditor']))
        self.assertTrue(table.allows('office-manager', 'alpha-lead'))
        self.assertTrue(table.allows('office-manager', 'auditor'))

    def test_roster_members_can_reply_to_om(self):
        table = build_routing_table(self._make_roster(['alpha-lead']))
        self.assertTrue(table.allows('alpha-lead', 'office-manager'))

    def test_roster_members_cannot_reach_each_other(self):
        table = build_routing_table(self._make_roster(['alpha-lead', 'auditor']))
        self.assertFalse(table.allows('alpha-lead', 'auditor'))

    def test_same_agent_in_two_workgroup_rosters(self):
        """``shared-dev`` is a legitimate member of two workgroups.

        Each workgroup's session has its OWN flat roster with its own
        dispatcher.  ``shared-dev`` ends up in alpha's mesh in alpha's
        session and in beta's mesh in beta's session — no nesting,
        no shared routing table, no duplicate-name conflict.
        """
        from teaparty.config.roster import Roster, Member
        wg_alpha = Roster(
            lead='alpha-wg-lead',
            members=[
                Member(name='shared-dev', role='workgroup-agent'),
                Member(name='alpha-only', role='workgroup-agent'),
            ],
            mesh_among_members=True,
        )
        wg_beta = Roster(
            lead='beta-wg-lead',
            members=[
                Member(name='shared-dev', role='workgroup-agent'),
                Member(name='beta-only', role='workgroup-agent'),
            ],
            mesh_among_members=True,
        )
        # Each workgroup builds its own routing table — independent
        # sessions, independent dispatchers, no conflict.
        alpha_table = build_routing_table(wg_alpha)
        beta_table = build_routing_table(wg_beta)
        self.assertTrue(alpha_table.allows('shared-dev', 'alpha-only'))
        self.assertTrue(beta_table.allows('shared-dev', 'beta-only'))
        # Alpha's session can't route to beta-only (it isn't on alpha's
        # team), and vice versa.  Cross-team routing happens via the
        # parent_lead gateway in each session.
        self.assertFalse(alpha_table.allows('shared-dev', 'beta-only'))
        self.assertFalse(beta_table.allows('shared-dev', 'alpha-only'))

    def test_parent_lead_gateway_pair(self):
        """``parent_lead`` is conversation-scoped and creates the
        cross-team gateway pair lead↔parent_lead in this session's
        routing table.  Same workgroup loaned to a different project
        sets a different ``parent_lead`` — same team, different
        conversation context.
        """
        from teaparty.config.roster import Roster, Member
        # Coding workgroup loaned to Comics project.
        coding_in_comics = Roster(
            lead='coding-lead',
            members=[
                Member(name='developer', role='workgroup-agent'),
            ],
            mesh_among_members=True,
            parent_lead='comics-lead',
        )
        comics_table = build_routing_table(coding_in_comics)
        self.assertTrue(comics_table.allows('coding-lead', 'comics-lead'))
        self.assertTrue(comics_table.allows('comics-lead', 'coding-lead'))

        # Same workgroup, different conversation context (loaned to
        # JokeBook).  Same team, different parent_lead.
        coding_in_jokebook = Roster(
            lead='coding-lead',
            members=[
                Member(name='developer', role='workgroup-agent'),
            ],
            mesh_among_members=True,
            parent_lead='joke-book-lead',
        )
        jb_table = build_routing_table(coding_in_jokebook)
        self.assertTrue(jb_table.allows('coding-lead', 'joke-book-lead'))
        self.assertFalse(jb_table.allows('coding-lead', 'comics-lead'))


if __name__ == '__main__':
    unittest.main()
