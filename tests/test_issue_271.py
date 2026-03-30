"""Tests for issue #271: Migrate agent and team definitions to milestone 3 structure.

Acceptance criteria:
1. coding-team.json has exactly 4 agents matching workgroup-coding.yaml
2. configuration-team.json exists with 4 agents matching workgroup-configuration.yaml
3. uber-team.json migrated to project-lead + qa-reviewer per project.yaml
4. project-team.json removed (redundant with migrated uber-team)
5. phase-config.json references updated
6. engine.py flat-mode logic updated
7. All test references updated — covered by the test suite itself passing
"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

AGENTS_DIR = Path(__file__).parent.parent / 'agents'


def _load_agents(filename):
    """Load agent definitions from a team JSON file."""
    path = AGENTS_DIR / filename
    with open(path) as f:
        return json.load(f)


def _poc_root():
    return str(Path(__file__).parent.parent)


# ── 1. coding-team.json matches workgroup-coding.yaml ────────────────────────

class TestCodingTeamMatchesProposal(unittest.TestCase):
    """coding-team.json must match workgroup-coding.yaml agent structure."""

    def setUp(self):
        self.agents = _load_agents('coding-team.json')

    def test_has_exactly_four_agents(self):
        """Proposal specifies 4 agents: coding-lead, architect, developer, reviewer."""
        self.assertEqual(sorted(self.agents.keys()),
                         ['architect', 'coding-lead', 'developer', 'reviewer'])

    def test_coding_lead_model_is_sonnet(self):
        self.assertEqual(self.agents['coding-lead']['model'], 'sonnet')

    def test_architect_model_is_opus(self):
        self.assertEqual(self.agents['architect']['model'], 'opus')

    def test_developer_model_is_sonnet(self):
        self.assertEqual(self.agents['developer']['model'], 'sonnet')

    def test_reviewer_model_is_sonnet(self):
        """Proposal specifies reviewer uses claude-sonnet-4, not opus."""
        self.assertEqual(self.agents['reviewer']['model'], 'sonnet')

    def test_no_tester_agent(self):
        """Proposal does not include a tester agent."""
        self.assertNotIn('tester', self.agents)

    def test_no_coder_agent(self):
        """Agent was renamed to 'developer' per proposal."""
        self.assertNotIn('coder', self.agents)


# ── 2. configuration-team.json exists and matches proposal ───────────────────

class TestConfigurationTeamMatchesProposal(unittest.TestCase):
    """configuration-team.json must match workgroup-configuration.yaml."""

    def test_file_exists(self):
        path = AGENTS_DIR / 'configuration-team.json'
        self.assertTrue(path.exists(),
                        'configuration-team.json must exist')

    def test_has_exactly_four_agents(self):
        agents = _load_agents('configuration-team.json')
        self.assertEqual(sorted(agents.keys()),
                         ['agent-designer', 'configuration-lead',
                          'skill-architect', 'systems-engineer'])

    def test_configuration_lead_model_is_sonnet(self):
        agents = _load_agents('configuration-team.json')
        self.assertEqual(agents['configuration-lead']['model'], 'sonnet')

    def test_skill_architect_model_is_opus(self):
        agents = _load_agents('configuration-team.json')
        self.assertEqual(agents['skill-architect']['model'], 'opus')

    def test_agent_designer_model_is_opus(self):
        agents = _load_agents('configuration-team.json')
        self.assertEqual(agents['agent-designer']['model'], 'opus')

    def test_systems_engineer_model_is_sonnet(self):
        agents = _load_agents('configuration-team.json')
        self.assertEqual(agents['systems-engineer']['model'], 'sonnet')


# ── 3. uber-team.json migrated to project-lead + qa-reviewer ────────────────

class TestUberTeamMatchesProjectProposal(unittest.TestCase):
    """uber-team.json must match project.yaml: project-lead + qa-reviewer."""

    def setUp(self):
        self.agents = _load_agents('uber-team.json')

    def test_has_project_lead(self):
        self.assertIn('project-lead', self.agents)

    def test_has_qa_reviewer(self):
        self.assertIn('qa-reviewer', self.agents)

    def test_has_exactly_two_agents(self):
        self.assertEqual(sorted(self.agents.keys()),
                         ['project-lead', 'qa-reviewer'])

    def test_no_liaisons_remain(self):
        """Old liaison agents must be removed."""
        for old in ('art-liaison', 'writing-liaison', 'editorial-liaison',
                    'research-liaison', 'coding-liaison'):
            self.assertNotIn(old, self.agents, f'{old} should be removed')


# ── 4. project-team.json removed ────────────────────────────────────────────

class TestProjectTeamRemoved(unittest.TestCase):
    """project-team.json is redundant with migrated uber-team and must be removed."""

    def test_file_does_not_exist(self):
        path = AGENTS_DIR / 'project-team.json'
        self.assertFalse(path.exists(),
                         'project-team.json should be removed — redundant with uber-team')


# ── 5. phase-config.json references are valid ───────────────────────────────

class TestPhaseConfigReferencesValid(unittest.TestCase):
    """All agent_file references in phase-config.json must point to existing files."""

    def setUp(self):
        config_path = os.path.join(_poc_root(), 'orchestrator', 'phase-config.json')
        with open(config_path) as f:
            self.config = json.load(f)

    def test_all_phase_agent_files_exist(self):
        for phase_name, phase in self.config['phases'].items():
            agent_file = phase['agent_file']
            path = os.path.join(_poc_root(), agent_file)
            self.assertTrue(os.path.exists(path),
                            f'Phase {phase_name} references {agent_file} which does not exist')

    def test_all_team_agent_files_exist(self):
        for team_name, team in self.config['teams'].items():
            agent_file = team['agent_file']
            path = os.path.join(_poc_root(), agent_file)
            self.assertTrue(os.path.exists(path),
                            f'Team {team_name} references {agent_file} which does not exist')

    def test_configuration_team_references_configuration_team_json(self):
        self.assertEqual(self.config['teams']['configuration']['agent_file'],
                         'agents/configuration-team.json')


# ── 6. engine.py flat-mode logic works with migrated team ───────────────────

class TestFlatModeLogicUpdated(unittest.TestCase):
    """engine.py flat-mode swap must work with the migrated uber-team file."""

    def test_flat_mode_detects_uber_team(self):
        """The flat-mode check in engine.py must match the current uber-team filename."""
        import orchestrator.engine as engine_mod
        source = open(engine_mod.__file__).read()
        # The engine must have a flat-mode swap that references uber-team
        self.assertIn('uber-team', source,
                      'engine.py must reference uber-team for flat-mode swap')


# ── 7. No hardcoded team lists in runtime code ──────────────────────────────

class TestNoHardcodedTeamLists(unittest.TestCase):
    """Runtime code must load team names from phase-config.json, not hardcode them."""

    def test_get_team_names_includes_configuration(self):
        """get_team_names() must return the configuration team."""
        from orchestrator.phase_config import get_team_names
        names = get_team_names(_poc_root())
        self.assertIn('configuration', names)

    def test_get_team_names_matches_phase_config(self):
        """get_team_names() must match the teams in phase-config.json."""
        from orchestrator.phase_config import get_team_names
        config_path = os.path.join(_poc_root(), 'orchestrator', 'phase-config.json')
        with open(config_path) as f:
            config = json.load(f)
        expected = tuple(config['teams'].keys())
        # Clear cache to get fresh result
        import orchestrator.phase_config as pc
        pc._team_names_cache = None
        actual = get_team_names(_poc_root())
        self.assertEqual(actual, expected)

    def test_state_reader_no_hardcoded_teams(self):
        """state_reader.py must not contain a hardcoded team tuple."""
        import orchestrator.state_reader as sr
        source = open(sr.__file__).read()
        self.assertNotIn("'art', 'writing', 'editorial', 'research', 'coding'", source,
                         'state_reader.py still has hardcoded team list')

    def test_withdraw_no_hardcoded_teams(self):
        """withdraw.py must not contain a hardcoded team tuple."""
        import orchestrator.withdraw as wd
        source = open(wd.__file__).read()
        self.assertNotIn("'art', 'writing', 'editorial', 'research', 'coding'", source,
                         'orchestrator/withdraw.py still has hardcoded team list')


if __name__ == '__main__':
    unittest.main()
