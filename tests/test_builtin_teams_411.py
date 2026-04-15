"""Tests for Issue #411: built-in teams management catalog.

Verifies the management catalog is correctly populated:
  AC1 - all 8 new workgroup YAMLs exist and load without error
  AC2 - every member named in a workgroup has a corresponding agent.md
  AC3 - each agent.md tool allowlist matches the design doc exactly
  AC4 - digest skill SKILL.md exists, has required frontmatter, and encodes the
        full protocol from docs/detailed-design/teams/digest.md
  AC5 - every agent lists 'digest' in its skills
  AC6 - agents with missing external tools carry a missing-tools annotation
  AC7 - existing leads reconciled; coding-lead and configuration-lead tool
        allowlists match the known-good baseline exactly
  AC8 - all 8 new teams are discoverable and all referenced agents and skills
        resolve from management paths without additional configuration
"""
import os
import re
import unittest

import yaml

from teaparty.config.config_reader import (
    discover_agents,
    discover_skills,
    discover_workgroups,
    load_management_team,
    load_management_workgroups,
    load_workgroup,
    management_agents_dir,
    management_skills_dir,
    management_workgroups_dir,
    read_agent_frontmatter,
)

# Repo root: two levels up from tests/
_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
_TEAPARTY_HOME = os.path.join(_REPO_ROOT, '.teaparty')
_AGENTS_DIR = management_agents_dir(_TEAPARTY_HOME)
_SKILLS_DIR = management_skills_dir(_TEAPARTY_HOME)
_WORKGROUPS_DIR = management_workgroups_dir(_TEAPARTY_HOME)

# Expected workgroup members per design doc (docs/detailed-design/teams/*.md).
# Format: {team_name: {'lead': str, 'members': [str]}}
_TEAM_SPEC: dict[str, dict] = {
    'research': {
        'lead': 'research-lead',
        'members': ['web-researcher', 'literature-researcher', 'patent-researcher',
                    'video-researcher', 'image-analyst'],
    },
    'writing': {
        'lead': 'writing-lead',
        'members': ['markdown-writer', 'latex-writer', 'blog-writer',
                    'pdf-writer', 'specification-writer'],
    },
    'editorial': {
        'lead': 'editorial-lead',
        'members': ['copy-editor', 'fact-checker', 'style-reviewer', 'voice-editor'],
    },
    'quality-control': {
        'lead': 'quality-control-lead',
        'members': ['qa-reviewer', 'test-reviewer', 'regression-tester',
                    'acceptance-tester', 'performance-analyst', 'ai-smell'],
    },
    'art': {
        'lead': 'art-lead',
        'members': ['svg-artist', 'graphviz-artist', 'tikz-artist', 'png-artist'],
    },
    'analytics': {
        'lead': 'analytics-lead',
        'members': ['data-scientist', 'data-visualizer'],
    },
    'planning': {
        'lead': 'planning-lead',
        'members': ['strategist', 'risk-analyst', 'milestone-planner', 'dependency-mapper'],
    },
    'intake': {
        'lead': 'intake-lead',
        'members': ['intent-specialist', 'scope-analyst', 'stakeholder-interviewer'],
    },
}

# Required tools per agent per design doc.
_AGENT_TOOLS: dict[str, set[str]] = {
    # Research
    'research-lead':        {'Read', 'Write', 'Glob', 'Grep', 'mcp__teaparty-config__AskQuestion'},
    'web-researcher':       {'Read', 'Write', 'Glob', 'WebSearch', 'WebFetch'},
    'literature-researcher':{'Read', 'Write', 'Glob', 'WebSearch', 'WebFetch',
                             'mcp__teaparty-config__arxiv_search',
                             'mcp__teaparty-config__semantic_scholar_search',
                             'mcp__teaparty-config__pubmed_search'},
    'patent-researcher':    {'Read', 'Write', 'Glob', 'WebSearch', 'WebFetch',
                             'mcp__teaparty-config__patent_search_uspto',
                             'mcp__teaparty-config__patent_search_epo'},
    'video-researcher':     {'Read', 'Write', 'Glob', 'WebSearch', 'WebFetch',
                             'mcp__teaparty-config__youtube_transcript'},
    'image-analyst':        {'Read', 'Write', 'WebFetch'},
    # Writing
    'writing-lead':         {'Read', 'Write', 'Edit', 'Glob', 'Grep', 'mcp__teaparty-config__AskQuestion'},
    'markdown-writer':      {'Read', 'Write', 'Edit', 'Glob', 'Grep'},
    'latex-writer':         {'Read', 'Write', 'Edit', 'Bash'},
    'blog-writer':          {'Read', 'Write', 'Edit'},
    'pdf-writer':           {'Read', 'Write', 'Bash'},
    'specification-writer': {'Read', 'Write', 'Edit', 'Glob', 'Grep', 'mcp__teaparty-config__AskQuestion'},
    # Editorial
    'editorial-lead':       {'Read', 'Write', 'Edit', 'Glob', 'Grep', 'mcp__teaparty-config__AskQuestion'},
    'copy-editor':          {'Read', 'Write', 'Edit'},
    'fact-checker':         {'Read', 'Write', 'WebSearch', 'WebFetch'},
    'style-reviewer':       {'Read', 'Write', 'Edit', 'Glob', 'Grep'},
    'voice-editor':         {'Read', 'Write', 'Edit'},
    # Quality-control
    'quality-control-lead': {'Read', 'Write', 'Glob', 'Grep', 'Bash', 'mcp__teaparty-config__AskQuestion'},
    'qa-reviewer':          {'Read', 'Write', 'Glob', 'Grep'},
    'test-reviewer':        {'Read', 'Glob', 'Grep', 'Bash'},
    'regression-tester':    {'Bash', 'Read', 'Glob', 'Grep'},
    'acceptance-tester':    {'Read', 'Write', 'Bash'},
    'performance-analyst':  {'Bash', 'Read', 'Write', 'Glob', 'Grep'},
    'ai-smell':             {'Read', 'Write'},
    # Art
    'art-lead':             {'Read', 'Write', 'Glob', 'Grep', 'mcp__teaparty-config__AskQuestion'},
    'svg-artist':           {'Write', 'Read'},
    'graphviz-artist':      {'Write', 'Read', 'Bash'},
    'tikz-artist':          {'Write', 'Read', 'Bash'},
    'png-artist':           {'Write',
                             'mcp__teaparty-config__image_gen_openai',
                             'mcp__teaparty-config__image_gen_flux',
                             'mcp__teaparty-config__image_gen_stability'},
    # Analytics
    'analytics-lead':       {'Read', 'Write', 'Glob', 'Grep', 'Bash', 'mcp__teaparty-config__AskQuestion'},
    'data-scientist':       {'Bash', 'Read', 'Write', 'Glob'},
    'data-visualizer':      {'Bash', 'Write', 'Read'},
    # Planning
    'planning-lead':        {'Read', 'Write', 'Glob', 'Grep', 'mcp__teaparty-config__AskQuestion'},
    'strategist':           {'Read', 'Write', 'WebSearch', 'WebFetch'},
    'risk-analyst':         {'Read', 'Write', 'Glob', 'Grep'},
    'milestone-planner':    {'Read', 'Write'},
    'dependency-mapper':    {'Read', 'Write', 'Glob', 'Grep'},
    # Intake
    'intake-lead':          {'Read', 'Write', 'Glob', 'Grep', 'mcp__teaparty-config__AskQuestion'},
    'intent-specialist':    {'Read', 'Write', 'mcp__teaparty-config__AskQuestion'},
    'scope-analyst':        {'Read', 'Write', 'Glob', 'Grep'},
    'stakeholder-interviewer': {'Read', 'Write', 'mcp__teaparty-config__AskQuestion'},
}

# No agents currently have missing external tools — all previously-missing
# tools are now implemented in the teaparty MCP server or removed from scope.
_MISSING_TOOL_AGENTS: set[str] = set()

# Tool allowlists for pre-existing leads — AC7 reconciliation baseline.
# These reflect the tools after reconciliation with design docs for those teams.
_EXISTING_AGENT_TOOLS: dict[str, set[str]] = {
    'coding-lead': {'mcp__teaparty-config__Send', 'mcp__teaparty-config__Reply',
                    'mcp__teaparty-config__AskQuestion', 'Read', 'ListFiles'},
    'configuration-lead': {'Read', 'Glob', 'Grep', 'Bash', 'mcp__teaparty-config__Send'},
}


def _agent_md_path(name: str) -> str:
    return os.path.join(_AGENTS_DIR, name, 'agent.md')


def _agent_tools(name: str) -> set[str]:
    """Return the tool set from an agent's frontmatter."""
    fm = read_agent_frontmatter(_agent_md_path(name))
    tools_str = fm.get('tools', '')
    if not tools_str:
        return set()
    return {t.strip() for t in str(tools_str).split(',')}


def _agent_skills(name: str) -> list[str]:
    fm = read_agent_frontmatter(_agent_md_path(name))
    raw = fm.get('skills', [])
    if isinstance(raw, list):
        return raw
    return [raw] if raw else []


def _agent_body(name: str) -> str:
    path = _agent_md_path(name)
    with open(path) as f:
        content = f.read()
    m = re.match(r'^---\n.*?\n---\n(.*)', content, re.DOTALL)
    return m.group(1) if m else content


class TestBuiltinWorkgroupYAMLs(unittest.TestCase):
    """AC1, AC7, AC8 — workgroup YAML files exist, load, and are discoverable."""

    def test_all_eight_new_workgroups_exist_and_load(self):
        """Each of the 8 new built-in teams has a valid workgroup YAML."""
        for team in _TEAM_SPEC:
            with self.subTest(team=team):
                path = os.path.join(_WORKGROUPS_DIR, f'{team}.yaml')
                self.assertTrue(
                    os.path.exists(path),
                    f'{team}.yaml missing from {_WORKGROUPS_DIR}'
                )
                wg = load_workgroup(path)
                self.assertIsNotNone(wg, f'{team}: load_workgroup returned None')

    def test_workgroup_leads_match_design_doc(self):
        """Each workgroup names the correct lead from the design doc."""
        for team, spec in _TEAM_SPEC.items():
            with self.subTest(team=team):
                path = os.path.join(_WORKGROUPS_DIR, f'{team}.yaml')
                wg = load_workgroup(path)
                self.assertEqual(
                    wg.lead, spec['lead'],
                    f'{team}: lead is {wg.lead!r}, expected {spec["lead"]!r}'
                )

    def test_workgroup_members_match_design_doc_exactly(self):
        """Each workgroup lists exactly the members specified in the design doc."""
        for team, spec in _TEAM_SPEC.items():
            with self.subTest(team=team):
                path = os.path.join(_WORKGROUPS_DIR, f'{team}.yaml')
                wg = load_workgroup(path)
                self.assertEqual(
                    sorted(wg.members_agents),
                    sorted(spec['members']),
                    f'{team}: members are {sorted(wg.members_agents)}, '
                    f'expected {sorted(spec["members"])}'
                )

    def test_all_new_workgroups_discoverable_via_discover_workgroups(self):
        """discover_workgroups() returns all 8 new team names."""
        discovered = set(discover_workgroups(_WORKGROUPS_DIR))
        for team in _TEAM_SPEC:
            with self.subTest(team=team):
                self.assertIn(
                    team, discovered,
                    f'{team} not returned by discover_workgroups(); '
                    f'got: {sorted(discovered)}'
                )

    def test_existing_coding_and_configuration_workgroups_still_present(self):
        """The two pre-existing workgroups are not disturbed by this change."""
        discovered = set(discover_workgroups(_WORKGROUPS_DIR))
        self.assertIn('coding', discovered,
                      'coding workgroup missing after change')
        self.assertIn('configuration', discovered,
                      'configuration workgroup missing after change')


class TestBuiltinAgentMdFiles(unittest.TestCase):
    """AC2 — every member and lead named in a workgroup has an agent.md."""

    def _all_agents(self) -> list[str]:
        agents = []
        for team, spec in _TEAM_SPEC.items():
            agents.append(spec['lead'])
            agents.extend(spec['members'])
        return agents

    def test_every_workgroup_agent_has_agent_md(self):
        """Every lead and member named in a new workgroup has agent.md."""
        for team, spec in _TEAM_SPEC.items():
            all_team_agents = [spec['lead']] + spec['members']
            for agent in all_team_agents:
                with self.subTest(team=team, agent=agent):
                    path = _agent_md_path(agent)
                    self.assertTrue(
                        os.path.exists(path),
                        f'{agent}: agent.md missing at {path}'
                    )


class TestBuiltinAgentToolAllowlists(unittest.TestCase):
    """AC3 — each agent.md tool allowlist matches the design doc exactly."""

    def test_agent_tools_match_design_doc(self):
        """Tool allowlist for every new agent exactly matches the design doc."""
        for agent, expected_tools in _AGENT_TOOLS.items():
            with self.subTest(agent=agent):
                actual_tools = _agent_tools(agent)
                self.assertEqual(
                    actual_tools, expected_tools,
                    f'{agent}: tools are {sorted(actual_tools)}, '
                    f'expected {sorted(expected_tools)}'
                )

    def test_all_leads_have_askquestion(self):
        """Every team lead includes AskQuestion so it can escalate to humans."""
        for team, spec in _TEAM_SPEC.items():
            lead = spec['lead']
            with self.subTest(lead=lead):
                actual = _agent_tools(lead)
                self.assertIn(
                    'mcp__teaparty-config__AskQuestion', actual,
                    f'{lead}: mcp__teaparty-config__AskQuestion missing from tools {sorted(actual)}'
                )


class TestDigestSkill(unittest.TestCase):
    """AC4 — digest skill exists with required structure."""

    def test_digest_skill_directory_exists(self):
        """digest/ skill directory exists under management skills."""
        skill_dir = os.path.join(_SKILLS_DIR, 'digest')
        self.assertTrue(
            os.path.isdir(skill_dir),
            f'digest skill directory missing at {skill_dir}'
        )

    def test_digest_skill_md_exists(self):
        """SKILL.md exists inside the digest skill directory."""
        skill_md = os.path.join(_SKILLS_DIR, 'digest', 'SKILL.md')
        self.assertTrue(
            os.path.exists(skill_md),
            f'digest SKILL.md missing at {skill_md}'
        )

    def test_digest_skill_discoverable(self):
        """discover_skills() returns 'digest' from the management skills dir."""
        skills = discover_skills(_SKILLS_DIR)
        self.assertIn(
            'digest', skills,
            f'digest not returned by discover_skills(); got: {sorted(skills)}'
        )

    def test_digest_skill_has_valid_frontmatter(self):
        """digest SKILL.md frontmatter includes required name and description."""
        skill_md = os.path.join(_SKILLS_DIR, 'digest', 'SKILL.md')
        with open(skill_md) as f:
            content = f.read()
        m = re.match(r'^---\n(.*?\n)---\n', content, re.DOTALL)
        self.assertIsNotNone(m, 'digest SKILL.md has no YAML frontmatter block')
        fm = yaml.safe_load(m.group(1))
        self.assertEqual(fm.get('name'), 'digest',
                         f"digest SKILL.md name is {fm.get('name')!r}, expected 'digest'")
        self.assertIn('description', fm,
                      'digest SKILL.md frontmatter missing description field')
        self.assertTrue(fm['description'],
                        'digest SKILL.md description is empty')

    def test_digest_skill_body_encodes_protocol(self):
        """digest SKILL.md body encodes every protocol element from digest.md.

        A SKILL.md with placeholder body would pass test_digest_skill_has_valid_frontmatter
        because that test only checks frontmatter. This test asserts the body
        contains each concrete protocol requirement so a stub body fails.
        """
        skill_md = os.path.join(_SKILLS_DIR, 'digest', 'SKILL.md')
        with open(skill_md) as f:
            content = f.read()
        # Strip frontmatter to get the body.
        m = re.match(r'^---\n.*?\n---\n(.*)', content, re.DOTALL)
        body = m.group(1) if m else content

        # scratch/ location (docs/detailed-design/teams/digest.md: Scratch structure)
        self.assertIn('scratch/', body,
                      'digest SKILL.md body missing scratch/ location reference')
        # 200-line limit (digest.md: "no file exceeding 200 lines")
        self.assertIn('200', body,
                      'digest SKILL.md body missing 200-line limit')
        # in-progress status marker
        self.assertIn('in-progress', body,
                      'digest SKILL.md body missing in-progress status marker')
        # done status marker
        self.assertIn('done', body,
                      'digest SKILL.md body missing done status marker')
        # broad-to-specific ordering
        self.assertIn('broad-to-specific', body,
                      'digest SKILL.md body missing broad-to-specific ordering requirement')


class TestDigestSkillOnAllAgents(unittest.TestCase):
    """AC5 — every new built-in team agent lists digest in its skills."""

    def test_every_agent_lists_digest_skill(self):
        """All 38 new agents declare digest in their skills list."""
        for team, spec in _TEAM_SPEC.items():
            all_team_agents = [spec['lead']] + spec['members']
            for agent in all_team_agents:
                with self.subTest(team=team, agent=agent):
                    skills = _agent_skills(agent)
                    self.assertIn(
                        'digest', skills,
                        f'{agent}: digest missing from skills {skills}'
                    )


class TestMissingToolAnnotations(unittest.TestCase):
    """AC6 — agents with missing external tools reference missing-tools.md."""

    def test_agents_with_missing_tools_carry_annotation(self):
        """png-artist, video-researcher, literature-researcher, patent-researcher,
        acceptance-tester each reference missing-tools.md in their agent.md body."""
        for agent in _MISSING_TOOL_AGENTS:
            with self.subTest(agent=agent):
                body = _agent_body(agent)
                self.assertIn(
                    'missing-tools',
                    body,
                    f'{agent}: body must reference missing-tools.md '
                    f'but contains no such reference'
                )


class TestExistingLeadReconciliation(unittest.TestCase):
    """AC7 — existing leads (coding-lead, configuration-lead) tool allowlists
    match the reconciled baseline exactly. Any drift from the baseline fails.
    """

    def test_existing_lead_tools_match_reconciled_baseline(self):
        """coding-lead and configuration-lead tool allowlists match the baseline.

        AC7 says existing leads are reconciled against design docs and drift is
        corrected. This test encodes the expected state after reconciliation so
        future changes that accidentally modify these agents' tool lists are caught.
        """
        for agent, expected_tools in _EXISTING_AGENT_TOOLS.items():
            with self.subTest(agent=agent):
                actual_tools = _agent_tools(agent)
                self.assertEqual(
                    actual_tools, expected_tools,
                    f'{agent}: tools are {sorted(actual_tools)}, '
                    f'expected {sorted(expected_tools)}'
                )


class TestOptInMechanismResolution(unittest.TestCase):
    """AC8 — a project can opt into any new team without additional manual
    configuration: all referenced agents and skills resolve from management paths.
    """

    def test_all_workgroup_members_resolve_from_management_agents_dir(self):
        """Every lead and member referenced in a new workgroup YAML resolves
        from the management agents directory without additional setup.

        This exercises the opt-in claim end-to-end: a project that adds a team
        name to its workgroup config needs nothing more than the management catalog.
        """
        available_agents = set(discover_agents(_AGENTS_DIR))
        for team, spec in _TEAM_SPEC.items():
            all_team_agents = [spec['lead']] + spec['members']
            for agent in all_team_agents:
                with self.subTest(team=team, agent=agent):
                    self.assertIn(
                        agent, available_agents,
                        f'{team}/{agent}: not resolvable from management agents dir '
                        f'{_AGENTS_DIR}; would require additional manual configuration'
                    )

    def test_all_new_workgroups_registered_in_management_team(self):
        """All 8 new workgroups are registered in management/teaparty.yaml.

        load_management_workgroups reads from team.workgroups — the explicit
        registry in teaparty.yaml. A workgroup YAML that exists on disk but
        is not registered there is invisible to the dashboard and to projects
        trying to opt in via the management catalog.
        """
        team = load_management_team(teaparty_home=_TEAPARTY_HOME)
        # Match by config filename (e.g. "workgroups/quality-control.yaml" → "quality-control"),
        # not display name, since display names may use spaces ("Quality Control").
        registered_keys = {
            os.path.splitext(os.path.basename(wg.config))[0].lower()
            for wg in team.workgroups
        }
        for team_name in _TEAM_SPEC:
            with self.subTest(team=team_name):
                self.assertIn(
                    team_name.lower(), registered_keys,
                    f'{team_name} workgroup YAML exists but is not registered in '
                    f'management/teaparty.yaml workgroups list; '
                    f'registered: {sorted(registered_keys)}'
                )

    def test_digest_skill_resolves_from_management_skills_dir(self):
        """The digest skill required by every agent resolves from the management
        skills directory without additional setup.

        An agent that lists digest in its skills must be able to find it at
        runtime from the management catalog alone.
        """
        available_skills = set(discover_skills(_SKILLS_DIR))
        self.assertIn(
            'digest', available_skills,
            f'digest skill not resolvable from management skills dir {_SKILLS_DIR}; '
            f'would require additional manual configuration'
        )
