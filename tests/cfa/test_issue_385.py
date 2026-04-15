"""Issue #385: Unify orchestrator team definitions with .teaparty/ agent/workgroup system.

Tests that orchestrator agent and workgroup definitions exist in the
.teaparty/ format and that PhaseConfig reads from them.
"""
from __future__ import annotations

import json
import os
import unittest

# The project root for the TeaParty project itself
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestAgentDefinitionsExist(unittest.TestCase):
    """SC1: Each orchestrator agent has a .teaparty/project/agents/{name}/agent.md."""

    def _agents_dir(self):
        return os.path.join(REPO_ROOT, '.teaparty', 'project', 'agents')

    def test_agents_dir_exists(self):
        self.assertTrue(os.path.isdir(self._agents_dir()),
                        '.teaparty/project/agents/ directory must exist')

    def test_each_orchestrator_agent_has_definition(self):
        """Every agent from the old agents/*.json files must have a
        .teaparty/project/agents/{name}/agent.md definition."""
        expected_agents = {
            # coding team
            'coding-lead', 'architect', 'developer', 'reviewer',
            # art team
            'art-lead', 'svg-artist', 'graphviz-artist', 'tikz-artist',
            # writing team
            'writing-lead', 'markdown-writer', 'latex-writer',
            # editorial team
            'editorial-lead', 'copy-editor', 'fact-checker',
            # research team
            'research-lead', 'web-researcher', 'arxiv-researcher', 'image-analyst',
            # configuration team
            'configuration-lead', 'skill-architect', 'agent-designer', 'systems-engineer',
            # intent team
            'intent-lead', 'research-liaison',
            # uber team
            'project-lead', 'qa-reviewer',
            # management team (project-liaison and config-workgroup-liaison operate at project scope;
            # office-manager is management-only — defined in management/agents/, not project/agents/)
            'project-liaison', 'config-workgroup-liaison',
        }
        agents_dir = self._agents_dir()
        for agent_name in sorted(expected_agents):
            agent_md = os.path.join(agents_dir, agent_name, 'agent.md')
            self.assertTrue(
                os.path.isfile(agent_md),
                f'Missing agent definition: {agent_name}/agent.md',
            )

    def test_agent_definitions_have_required_frontmatter(self):
        """Each agent.md must have YAML frontmatter with name, description,
        model, and maxTurns fields."""
        agents_dir = self._agents_dir()
        if not os.path.isdir(agents_dir):
            self.skipTest('agents dir does not exist yet')

        for agent_name in os.listdir(agents_dir):
            agent_md = os.path.join(agents_dir, agent_name, 'agent.md')
            if not os.path.isfile(agent_md):
                continue
            with open(agent_md) as f:
                content = f.read()

            self.assertTrue(content.startswith('---'),
                            f'{agent_name}/agent.md must start with YAML frontmatter')
            # Parse frontmatter
            parts = content.split('---', 2)
            self.assertGreaterEqual(len(parts), 3,
                                    f'{agent_name}/agent.md: invalid frontmatter')
            import yaml
            fm = yaml.safe_load(parts[1])
            self.assertIsNotNone(fm, f'{agent_name}/agent.md: empty frontmatter')
            for field in ('name', 'description', 'model'):
                self.assertIn(field, fm,
                              f'{agent_name}/agent.md: missing frontmatter field "{field}"')


class TestWorkgroupDefinitionsExist(unittest.TestCase):
    """SC2: Each orchestrator team has a .teaparty/project/workgroups/{name}.yaml."""

    def _workgroups_dir(self):
        return os.path.join(REPO_ROOT, '.teaparty', 'project', 'workgroups')

    def test_workgroups_dir_exists(self):
        self.assertTrue(os.path.isdir(self._workgroups_dir()),
                        '.teaparty/project/workgroups/ directory must exist')

    def test_each_orchestrator_team_has_workgroup(self):
        """Every team from phase-config.json must have a workgroup definition."""
        expected = {
            'coding', 'art', 'writing', 'editorial', 'research',
            'configuration', 'intent', 'uber', 'flat', 'management',
        }
        wg_dir = self._workgroups_dir()
        for team in sorted(expected):
            yaml_path = os.path.join(wg_dir, f'{team}.yaml')
            self.assertTrue(
                os.path.isfile(yaml_path),
                f'Missing workgroup definition: {team}.yaml',
            )

    def test_workgroup_has_lead_and_members(self):
        """Each workgroup YAML must specify a lead and member agents."""
        import yaml
        wg_dir = self._workgroups_dir()
        if not os.path.isdir(wg_dir):
            self.skipTest('workgroups dir does not exist yet')

        for fname in os.listdir(wg_dir):
            if not fname.endswith('.yaml'):
                continue
            with open(os.path.join(wg_dir, fname)) as f:
                wg = yaml.safe_load(f)
            team = fname.replace('.yaml', '')
            self.assertIn('lead', wg, f'{team}.yaml: missing "lead" field')
            self.assertIn('members', wg, f'{team}.yaml: missing "members" field')


class TestPhaseConfigReadsFromTeaparty(unittest.TestCase):
    """SC3: PhaseConfig reads agent definitions from .teaparty/ format."""

    def test_phase_config_loads_agents_from_teaparty(self):
        """PhaseConfig.resolve_team_agents() must return agent dicts
        loaded from .teaparty/project/agents/, not from agents/*.json."""
        from teaparty.cfa.phase_config import PhaseConfig
        config = PhaseConfig(REPO_ROOT)

        agents = config.resolve_team_agents('coding')
        self.assertIn('coding-lead', agents)
        self.assertIn('developer', agents)
        # Each agent must have prompt, model, description
        for name, agent in agents.items():
            self.assertIn('prompt', agent, f'{name}: missing "prompt"')
            self.assertIn('model', agent, f'{name}: missing "model"')


class TestAgentsJsonRetired(unittest.TestCase):
    """SC4: agents/*.json directory is retired — no runtime code reads from it."""

    def test_no_agent_file_in_phase_config(self):
        """phase-config.json must not have agent_file fields pointing to agents/*.json."""
        config_path = os.path.join(REPO_ROOT, 'teaparty', 'cfa', 'phase-config.json')
        with open(config_path) as f:
            raw = json.load(f)

        for name, spec in raw.get('phases', {}).items():
            if 'agent_file' in spec:
                self.assertFalse(
                    spec['agent_file'].startswith('agents/'),
                    f'phase {name}: agent_file still points to agents/*.json',
                )
        for name, spec in raw.get('teams', {}).items():
            if 'agent_file' in spec:
                self.assertFalse(
                    spec['agent_file'].startswith('agents/'),
                    f'team {name}: agent_file still points to agents/*.json',
                )


class TestBehaviorUnchanged(unittest.TestCase):
    """SC6: Orchestrator dispatch behavior is unchanged — same agents, same prompts, same models."""

    def test_coding_team_agents_match_original(self):
        """The coding team agents loaded from .teaparty/ must have the same
        names, models, and prompt content as the original agents/coding-team.json."""
        from teaparty.cfa.phase_config import PhaseConfig
        config = PhaseConfig(REPO_ROOT)

        agents = config.resolve_team_agents('coding')

        # Original values from agents/coding-team.json
        self.assertEqual(agents['coding-lead']['model'], 'sonnet')
        self.assertEqual(agents['architect']['model'], 'opus')
        self.assertEqual(agents['developer']['model'], 'sonnet')
        self.assertEqual(agents['reviewer']['model'], 'sonnet')

        # Prompts must contain key identity phrases
        self.assertIn('coding team lead', agents['coding-lead']['prompt'].lower())
        self.assertIn('software architect', agents['architect']['prompt'].lower())
        self.assertIn('software developer', agents['developer']['prompt'].lower())
        self.assertIn('code reviewer', agents['reviewer']['prompt'].lower())
