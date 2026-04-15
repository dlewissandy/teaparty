"""Tests for Issue #411: built-in teams management catalog.

Verifies the management catalog is correctly populated:
  AC1 - all 8 new workgroup YAMLs exist and load without error
  AC2 - every member named in a workgroup has a corresponding agent.md
  AC3 - each agent.md tool allowlist matches the design doc exactly
  AC4 - digest skill SKILL.md exists and has required frontmatter
  AC5 - every agent lists 'digest' in its skills
  AC6 - agents with missing external tools carry a missing-tools annotation
  AC7 - existing leads reconciled; coding-lead and configuration-lead tools unchanged
  AC8 - all 8 new teams are discoverable via discover_workgroups()
"""
import os
import re
import unittest

import yaml

from teaparty.config.config_reader import (
    discover_skills,
    discover_workgroups,
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
    'research-lead':        {'Read', 'Write', 'Glob', 'Grep', 'AskQuestion'},
    'web-researcher':       {'Read', 'Write', 'Glob', 'WebSearch', 'WebFetch'},
    'literature-researcher':{'Read', 'Write', 'Glob', 'WebSearch', 'WebFetch'},
    'patent-researcher':    {'Read', 'Write', 'Glob', 'WebSearch', 'WebFetch'},
    'video-researcher':     {'Read', 'Write', 'Glob', 'WebSearch', 'WebFetch'},
    'image-analyst':        {'Read', 'Write', 'WebFetch'},
    # Writing
    'writing-lead':         {'Read', 'Write', 'Edit', 'Glob', 'Grep', 'AskQuestion'},
    'markdown-writer':      {'Read', 'Write', 'Edit', 'Glob', 'Grep'},
    'latex-writer':         {'Read', 'Write', 'Edit', 'Bash'},
    'blog-writer':          {'Read', 'Write', 'Edit'},
    'pdf-writer':           {'Read', 'Write', 'Bash'},
    'specification-writer': {'Read', 'Write', 'Edit', 'Glob', 'Grep', 'AskQuestion'},
    # Editorial
    'editorial-lead':       {'Read', 'Write', 'Edit', 'Glob', 'Grep', 'AskQuestion'},
    'copy-editor':          {'Read', 'Write', 'Edit'},
    'fact-checker':         {'Read', 'Write', 'WebSearch', 'WebFetch'},
    'style-reviewer':       {'Read', 'Write', 'Edit', 'Glob', 'Grep'},
    'voice-editor':         {'Read', 'Write', 'Edit'},
    # Quality-control
    'quality-control-lead': {'Read', 'Write', 'Glob', 'Grep', 'Bash', 'AskQuestion'},
    'qa-reviewer':          {'Read', 'Write', 'Glob', 'Grep'},
    'test-reviewer':        {'Read', 'Glob', 'Grep', 'Bash'},
    'regression-tester':    {'Bash', 'Read', 'Glob', 'Grep'},
    'acceptance-tester':    {'Read', 'Write', 'Bash'},
    'performance-analyst':  {'Bash', 'Read', 'Write', 'Glob', 'Grep'},
    'ai-smell':             {'Read', 'Write'},
    # Art
    'art-lead':             {'Read', 'Write', 'Glob', 'Grep', 'AskQuestion'},
    'svg-artist':           {'Write', 'Read'},
    'graphviz-artist':      {'Write', 'Read', 'Bash'},
    'tikz-artist':          {'Write', 'Read', 'Bash'},
    'png-artist':           {'Write'},
    # Analytics
    'analytics-lead':       {'Read', 'Write', 'Glob', 'Grep', 'Bash', 'AskQuestion'},
    'data-scientist':       {'Bash', 'Read', 'Write', 'Glob'},
    'data-visualizer':      {'Bash', 'Write', 'Read'},
    # Planning
    'planning-lead':        {'Read', 'Write', 'Glob', 'Grep', 'AskQuestion'},
    'strategist':           {'Read', 'Write', 'WebSearch', 'WebFetch'},
    'risk-analyst':         {'Read', 'Write', 'Glob', 'Grep'},
    'milestone-planner':    {'Read', 'Write'},
    'dependency-mapper':    {'Read', 'Write', 'Glob', 'Grep'},
    # Intake
    'intake-lead':          {'Read', 'Write', 'Glob', 'Grep', 'AskQuestion'},
    'intent-specialist':    {'Read', 'Write', 'AskQuestion'},
    'scope-analyst':        {'Read', 'Write', 'Glob', 'Grep'},
    'stakeholder-interviewer': {'Read', 'Write', 'AskQuestion'},
}

# Agents that require missing external tools — their agent.md body must
# reference missing-tools.md so the gap is not silently hidden.
_MISSING_TOOL_AGENTS = {
    'png-artist', 'video-researcher', 'literature-researcher',
    'patent-researcher', 'acceptance-tester',
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
                    'AskQuestion', actual,
                    f'{lead}: AskQuestion missing from tools {sorted(actual)}'
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
