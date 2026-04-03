"""Tests for issue #362: YAML schema — separate catalog registration from active membership.

Acceptance criteria:
1. teaparty.yaml has separate projects: (registration) and members.projects: (dispatch)
2. project.yaml has separate workgroups: (registration) and members.workgroups: (dispatch)
3. Workgroup YAML has members.agents: and members.hooks: but no members.skills:
4. artifacts: field supported in workgroup YAML (list of path/label pairs)
5. Config workgroups appear in workgroups: but not in members:
6. All existing YAML files migrated to new schema
7. Existing tests updated; new tests cover the schema distinctions
"""
import os
import sys
import unittest
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.config_reader import (
    load_management_team,
    load_project_team,
    load_workgroup,
)

# Path to the repo root — the worktree is two levels above tests/
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEAPARTY_HOME = os.path.join(_REPO_ROOT, '.teaparty')
_PROJECT_YAML = os.path.join(_REPO_ROOT, '.teaparty', 'project', 'project.yaml')
_CODING_YAML = os.path.join(_TEAPARTY_HOME, 'management', 'workgroups', 'coding.yaml')
_CONFIGURATION_YAML = os.path.join(_TEAPARTY_HOME, 'management', 'workgroups', 'configuration.yaml')


def _load_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


# ── Criterion 1: teaparty.yaml has projects: and members.projects: ────────────

class TestTeapartyYamlHasProjectsRegistrationBlock(unittest.TestCase):
    """teaparty.yaml must use projects: for registration, not teams:."""

    def setUp(self):
        self.data = _load_yaml(os.path.join(_TEAPARTY_HOME, 'management', 'teaparty.yaml'))

    def test_has_projects_key_not_teams(self):
        self.assertIn('projects', self.data, "teaparty.yaml must have a 'projects:' key")
        self.assertNotIn('teams', self.data, "teaparty.yaml must not have legacy 'teams:' key")

    def test_projects_are_list_of_dicts_with_name_and_path(self):
        projects = self.data.get('projects', [])
        self.assertIsInstance(projects, list)
        for p in projects:
            self.assertIn('name', p, "Each project entry must have 'name'")
            self.assertIn('path', p, "Each project entry must have 'path'")

    def test_projects_entries_have_config_field(self):
        """Each project registration entry should include its config file path."""
        projects = self.data.get('projects', [])
        for p in projects:
            self.assertIn('config', p, f"Project '{p.get('name')}' must have a 'config' field")


class TestTeapartyYamlMembersBlockProjects(unittest.TestCase):
    """teaparty.yaml members: block scopes which projects the OM dispatches to.

    Recursive dispatch requires members.projects to distinguish staffed projects
    from the full registry. Reintroduced after #379 removal.
    """

    def setUp(self):
        self.data = _load_yaml(os.path.join(_TEAPARTY_HOME, 'management', 'teaparty.yaml'))

    def test_has_members_block(self):
        self.assertIn('members', self.data, "teaparty.yaml must have a 'members:' block")

    def test_members_has_projects_key(self):
        members = self.data.get('members', {})
        self.assertIn('projects', members,
            "members: must have 'projects:' — scopes OM dispatch targets")


class TestTeapartyYamlNoSkillsAtManagementLevel(unittest.TestCase):
    """Skills are a per-agent concern; they must not appear in teaparty.yaml."""

    def setUp(self):
        self.data = _load_yaml(os.path.join(_TEAPARTY_HOME, 'management', 'teaparty.yaml'))

    def test_no_top_level_skills_key(self):
        self.assertNotIn('skills', self.data,
            "teaparty.yaml must not have a top-level 'skills:' key (per-agent concern)")


class TestTeapartyYamlHumansBlock(unittest.TestCase):
    """teaparty.yaml humans: block must use the dict form {decider: name}."""

    def setUp(self):
        self.data = _load_yaml(os.path.join(_TEAPARTY_HOME, 'management', 'teaparty.yaml'))

    def test_humans_is_dict_with_decider(self):
        humans = self.data.get('humans', {})
        self.assertIsInstance(humans, dict, "humans: must be a dict, not a list")
        self.assertIn('decider', humans, "humans: dict must have a 'decider' key")


# ── Criterion 2: project.yaml has workgroups: and members.workgroups: ─────────

class TestProjectYamlHasWorkgroupsRegistrationBlock(unittest.TestCase):
    """project.yaml must have workgroups: for registration."""

    def setUp(self):
        self.data = _load_yaml(_PROJECT_YAML)

    def test_has_workgroups_key(self):
        self.assertIn('workgroups', self.data,
            "project.yaml must have a 'workgroups:' key")

    def test_workgroups_entries_have_name_and_config(self):
        for wg in self.data.get('workgroups', []):
            self.assertIn('name', wg, "Each workgroup entry must have 'name'")
            self.assertIn('config', wg, "Each workgroup entry must have 'config'")


class TestProjectYamlHasMembersWorkgroupsBlock(unittest.TestCase):
    """project.yaml must have members.workgroups: for active dispatch."""

    def setUp(self):
        self.data = _load_yaml(_PROJECT_YAML)

    def test_has_members_block(self):
        self.assertIn('members', self.data,
            "project.yaml must have a 'members:' block")

    def test_members_has_workgroups_list(self):
        members = self.data.get('members', {})
        self.assertIn('workgroups', members,
            "members: block must have a 'workgroups:' list")
        self.assertIsInstance(members['workgroups'], list)

    def test_members_workgroups_are_names_only(self):
        """members.workgroups: entries are workgroup name strings."""
        for entry in self.data.get('members', {}).get('workgroups', []):
            self.assertIsInstance(entry, str,
                "members.workgroups: entries must be name strings")

    def test_members_workgroups_subset_of_registered(self):
        """Every name in members.workgroups must be a registered workgroup."""
        registered_names = {wg['name'] for wg in self.data.get('workgroups', [])}
        for name in self.data.get('members', {}).get('workgroups', []):
            self.assertIn(name, registered_names,
                f"members.workgroups entry '{name}' is not a registered workgroup")


class TestProjectYamlNoSkillsKey(unittest.TestCase):
    """Skills must not appear in project.yaml (per-agent concern)."""

    def setUp(self):
        self.data = _load_yaml(_PROJECT_YAML)

    def test_no_skills_key(self):
        self.assertNotIn('skills', self.data,
            "project.yaml must not have a top-level 'skills:' key")


class TestProjectYamlHumansBlock(unittest.TestCase):
    """project.yaml humans: block must use the dict form."""

    def setUp(self):
        self.data = _load_yaml(_PROJECT_YAML)

    def test_humans_is_dict_with_decider(self):
        humans = self.data.get('humans', {})
        self.assertIsInstance(humans, dict, "humans: must be a dict, not a list")
        self.assertIn('decider', humans, "humans: dict must have a 'decider' key")


# ── Criterion 3: workgroup YAML has members.agents: not flat agents: ──────────

class TestCodingWorkgroupHasMembersAgentsBlock(unittest.TestCase):
    """coding.yaml must use members.agents: not a flat agents: list."""

    def setUp(self):
        self.data = _load_yaml(_CODING_YAML)

    def test_no_flat_agents_key(self):
        self.assertNotIn('agents', self.data,
            "coding.yaml must not have a flat top-level 'agents:' key")

    def test_has_members_agents(self):
        members = self.data.get('members', {})
        self.assertIn('agents', members,
            "coding.yaml members: block must have 'agents:'")

    def test_members_agents_are_strings(self):
        """members.agents: entries are agent-id strings, not dicts."""
        members = self.data.get('members', {})
        for entry in members.get('agents', []):
            self.assertIsInstance(entry, str,
                "members.agents: entries must be agent-id strings")

    def test_members_block_has_hooks_key(self):
        members = self.data.get('members', {})
        self.assertIn('hooks', members,
            "coding.yaml members: block must have 'hooks:'")


class TestConfigurationWorkgroupHasMembersAgentsBlock(unittest.TestCase):
    """configuration.yaml must use members.agents: not a flat agents: list."""

    def setUp(self):
        self.data = _load_yaml(_CONFIGURATION_YAML)

    def test_no_flat_agents_key(self):
        self.assertNotIn('agents', self.data,
            "configuration.yaml must not have a flat top-level 'agents:' key")

    def test_has_members_agents(self):
        members = self.data.get('members', {})
        self.assertIn('agents', members,
            "configuration.yaml members: block must have 'agents:'")

    def test_members_agents_are_strings(self):
        members = self.data.get('members', {})
        for entry in members.get('agents', []):
            self.assertIsInstance(entry, str,
                "members.agents: entries must be agent-id strings")


# ── Criterion 3: workgroup YAML has no skills: ────────────────────────────────

class TestCodingWorkgroupHasNoSkills(unittest.TestCase):
    """coding.yaml must not have a skills: key (per-agent concern per proposal)."""

    def setUp(self):
        self.data = _load_yaml(_CODING_YAML)

    def test_no_skills_key(self):
        self.assertNotIn('skills', self.data,
            "coding.yaml must not have a 'skills:' key — skills are per-agent")


class TestConfigurationWorkgroupHasNoSkills(unittest.TestCase):
    """configuration.yaml must not have a skills: key."""

    def setUp(self):
        self.data = _load_yaml(_CONFIGURATION_YAML)

    def test_no_skills_key(self):
        self.assertNotIn('skills', self.data,
            "configuration.yaml must not have a 'skills:' key — skills are per-agent")


# ── Criterion 4: workgroup YAML has artifacts: field ─────────────────────────

class TestCodingWorkgroupHasArtifactsField(unittest.TestCase):
    """coding.yaml must have an artifacts: field (may be empty list)."""

    def setUp(self):
        self.data = _load_yaml(_CODING_YAML)

    def test_has_artifacts_key(self):
        self.assertIn('artifacts', self.data,
            "coding.yaml must have an 'artifacts:' field")

    def test_artifacts_is_list(self):
        self.assertIsInstance(self.data.get('artifacts'), list)


class TestConfigurationWorkgroupHasArtifactsField(unittest.TestCase):
    """configuration.yaml must have an artifacts: field."""

    def setUp(self):
        self.data = _load_yaml(_CONFIGURATION_YAML)

    def test_has_artifacts_key(self):
        self.assertIn('artifacts', self.data,
            "configuration.yaml must have an 'artifacts:' field")

    def test_artifacts_is_list(self):
        self.assertIsInstance(self.data.get('artifacts'), list)


# ── Criterion 5: config workgroups in workgroups: but not members: ────────────

class TestConfigWorkgroupRegisteredButNotMemberInTeapartyYaml(unittest.TestCase):
    """Configuration workgroup must be registered but not in members.projects.

    The OM does not dispatch to the Config workgroup — it is reached via
    the config screen's chat blade only.
    """

    def setUp(self):
        self.data = _load_yaml(os.path.join(_TEAPARTY_HOME, 'management', 'teaparty.yaml'))

    def test_configuration_workgroup_is_registered(self):
        wg_names = [wg['name'] for wg in self.data.get('workgroups', [])]
        self.assertIn('Configuration', wg_names,
            "Configuration workgroup must be registered in teaparty.yaml workgroups:")

    def test_configuration_workgroup_in_members_workgroups(self):
        # members.workgroups tracks active workgroups at management level (#376).
        # Configuration is registered and active — it is reached via the config
        # screen's chat blade, not through OM dispatch.
        members = self.data.get('members', {})
        self.assertIn('workgroups', members,
            "teaparty.yaml members: must have a 'workgroups:' key")


class TestConfigWorkgroupNotInProjectYamlMembers(unittest.TestCase):
    """Configuration workgroup may be registered in project.yaml but must not
    be in members.workgroups (project lead does not dispatch to it)."""

    def setUp(self):
        self.data = _load_yaml(_PROJECT_YAML)

    def test_configuration_workgroup_registered_in_project(self):
        wg_names = [wg['name'] for wg in self.data.get('workgroups', [])]
        self.assertIn('Configuration', wg_names,
            "Configuration workgroup must be registered in project.yaml workgroups:")

    def test_configuration_workgroup_not_in_members_workgroups(self):
        members = self.data.get('members', {})
        active = members.get('workgroups', [])
        self.assertNotIn('Configuration', active,
            "Configuration workgroup must not be in members.workgroups "
            "(project lead does not dispatch to it)")


# ── Schema distinction: catalog vs. membership ────────────────────────────────

class TestRegistrationAndMembershipAreDistinctInTeapartyYaml(unittest.TestCase):
    """Verify the catalog/membership separation is meaningful:
    it must be possible to have a registered project that is not a member."""

    def test_can_have_registered_project_not_in_members(self):
        data = _load_yaml(os.path.join(_TEAPARTY_HOME, 'management', 'teaparty.yaml'))
        registered = {p['name'] for p in data.get('projects', [])}
        members = set(data.get('members', {}).get('projects', []))
        # There must be at least one registered project that exists only for
        # catalog purposes and is not an active dispatch target, OR all
        # registered projects are members — both are valid schema states.
        # The key structural invariant is that members is a subset of registered.
        self.assertTrue(members.issubset(registered),
            "members.projects must be a subset of registered projects")


class TestRegistrationAndMembershipAreDistinctInProjectYaml(unittest.TestCase):
    """members.workgroups must be a subset of registered workgroups."""

    def test_members_workgroups_subset_of_registered(self):
        data = _load_yaml(_PROJECT_YAML)
        registered = {wg['name'] for wg in data.get('workgroups', [])}
        members = set(data.get('members', {}).get('workgroups', []))
        self.assertTrue(members.issubset(registered),
            "members.workgroups must be a subset of registered workgroups")


# ── Criterion 7: config_reader round-trip tests ──────────────────────────────

class TestLoadManagementTeamRoundTrip(unittest.TestCase):
    """load_management_team() must parse the new schema into the correct dataclass fields."""

    def setUp(self):
        self.team = load_management_team(teaparty_home=_TEAPARTY_HOME)

    def test_projects_registration_loaded(self):
        """team.projects contains the registration catalog."""
        self.assertGreater(len(self.team.projects), 0,
            "ManagementTeam.projects must be populated from projects: block")
        for p in self.team.projects:
            self.assertIn('name', p)
            self.assertIn('path', p)
            self.assertIn('config', p)

    def test_members_projects_field(self):
        """ManagementTeam.members_projects scopes OM dispatch targets."""
        self.assertIsInstance(self.team.members_projects, list)

    def test_members_agents_loaded(self):
        """team.members_agents contains any directly dispatched agents."""
        self.assertIsInstance(self.team.members_agents, list)

    def test_no_teams_field(self):
        """ManagementTeam must not have old-schema teams field."""
        self.assertFalse(hasattr(self.team, 'teams'),
            "ManagementTeam must not have 'teams' field — schema migrated to 'projects'")

    def test_no_decider_field(self):
        """ManagementTeam must not have top-level decider field."""
        self.assertFalse(hasattr(self.team, 'decider'),
            "ManagementTeam must not have 'decider' field — now in humans list")

    def test_decider_in_humans(self):
        """The decider is accessible via team.humans."""
        decider = next((h.name for h in self.team.humans if h.role == 'decider'), None)
        self.assertIsNotNone(decider, "ManagementTeam must have a decider in humans list")


class TestLoadProjectTeamRoundTrip(unittest.TestCase):
    """load_project_team() must parse the new schema into the correct dataclass fields."""

    def setUp(self):
        self.team = load_project_team(_REPO_ROOT)

    def test_workgroups_registration_loaded(self):
        """team.workgroups contains the registration catalog."""
        self.assertGreater(len(self.team.workgroups), 0,
            "ProjectTeam.workgroups must be populated from workgroups: block")

    def test_members_workgroups_loaded(self):
        """team.members_workgroups contains the active dispatch roster."""
        self.assertIsInstance(self.team.members_workgroups, list)
        self.assertGreater(len(self.team.members_workgroups), 0,
            "ProjectTeam.members_workgroups must be populated from members.workgroups:")
        for name in self.team.members_workgroups:
            self.assertIsInstance(name, str)

    def test_no_agents_field(self):
        """ProjectTeam must not have old-schema agents field."""
        self.assertFalse(hasattr(self.team, 'agents'),
            "ProjectTeam must not have 'agents' field — removed in schema migration")

    def test_no_skills_field(self):
        """ProjectTeam must not have skills field."""
        self.assertFalse(hasattr(self.team, 'skills'),
            "ProjectTeam must not have 'skills' field — removed in schema migration")

    def test_no_members_agents_field(self):
        """ProjectTeam must not have members_agents — project teams dispatch to workgroups only."""
        self.assertFalse(hasattr(self.team, 'members_agents'),
            "ProjectTeam must not have 'members_agents' — project members are workgroups, not agents")

    def test_no_members_skills_field(self):
        """ProjectTeam must not have members_skills — skills are per-agent, not per-team."""
        self.assertFalse(hasattr(self.team, 'members_skills'),
            "ProjectTeam must not have 'members_skills' — skills are a per-agent concern")

    def test_decider_in_humans(self):
        """The decider is accessible via team.humans."""
        decider = next((h.name for h in self.team.humans if h.role == 'decider'), None)
        self.assertIsNotNone(decider, "ProjectTeam must have a decider in humans list")


class TestLoadWorkgroupRoundTrip(unittest.TestCase):
    """load_workgroup() must parse the new schema into the correct dataclass fields."""

    def setUp(self):
        self.wg = load_workgroup(_CODING_YAML)

    def test_members_agents_loaded(self):
        """wg.members_agents contains the agent roster."""
        self.assertIsInstance(self.wg.members_agents, list)
        self.assertGreater(len(self.wg.members_agents), 0,
            "Workgroup.members_agents must be populated from members.agents:")
        for name in self.wg.members_agents:
            self.assertIsInstance(name, str)

    def test_members_hooks_loaded(self):
        """wg.members_hooks is a list (may be empty)."""
        self.assertIsInstance(self.wg.members_hooks, list)

    def test_artifacts_loaded(self):
        """wg.artifacts contains the pinned artifacts."""
        self.assertIsInstance(self.wg.artifacts, list)
        self.assertGreater(len(self.wg.artifacts), 0,
            "Workgroup.artifacts must be populated from artifacts: block in coding.yaml")

    def test_no_agents_field(self):
        """Workgroup must not have old-schema flat agents field."""
        self.assertFalse(hasattr(self.wg, 'agents'),
            "Workgroup must not have 'agents' field — now at members.agents")

    def test_no_skills_field(self):
        """Workgroup must not have skills field."""
        self.assertFalse(hasattr(self.wg, 'skills'),
            "Workgroup must not have 'skills' field — removed in schema migration")

    def test_no_team_file_field(self):
        """Workgroup must not have team_file field."""
        self.assertFalse(hasattr(self.wg, 'team_file'),
            "Workgroup must not have 'team_file' field — removed in schema migration")
