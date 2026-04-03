"""Tests for issue #373: Config reader — update orchestrator to read new workgroup model schema.

Acceptance criteria:
1. Config reader parses members: block correctly across all three YAML types
2. Reader distinguishes registered (catalog) entries from active (members) entries and exposes both
3. artifacts: field parsed and returned as list of path/label pairs
4. Skills no longer expected in workgroup YAML; no error if absent
5. All existing tests updated for new schema; new tests cover each new field
6. Bridge server and orchestrator continue to function with updated reader output
"""
import os
import sys
import tempfile
import unittest
import yaml
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.config_reader import (
    ManagementTeam,
    ProjectTeam,
    Workgroup,
    WorkgroupEntry,
    WorkgroupRef,
    load_management_team,
    load_project_team,
    load_workgroup,
    toggle_management_membership,
    toggle_project_membership,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_teaparty_yaml(teaparty_home: str, data: dict) -> str:
    mgmt_dir = os.path.join(teaparty_home, 'management')
    os.makedirs(mgmt_dir, exist_ok=True)
    path = os.path.join(mgmt_dir, 'teaparty.yaml')
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    return path


def _make_project_yaml(project_dir: str, data: dict) -> str:
    local_dir = os.path.join(project_dir, '.teaparty', 'project')
    os.makedirs(local_dir, exist_ok=True)
    path = os.path.join(local_dir, 'project.yaml')
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    return path


def _make_workgroup_yaml(directory: str, name: str, data: dict) -> str:
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f'{name}.yaml')
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    return path


def _minimal_management_data(**overrides) -> dict:
    data = {
        'name': 'Management',
        'description': 'Test',
        'lead': 'office-manager',
        'humans': {'decider': 'darrell'},
        'projects': [],
        'members': {'agents': []},
        'workgroups': [],
        'hooks': [],
        'scheduled': [],
    }
    data.update(overrides)
    return data


def _minimal_project_data(**overrides) -> dict:
    data = {
        'name': 'MyProject',
        'description': 'Test project',
        'lead': 'project-lead',
        'humans': {'decider': 'darrell'},
        'workgroups': [],
        'members': {'workgroups': []},
        'hooks': [],
        'scheduled': [],
    }
    data.update(overrides)
    return data


def _minimal_workgroup_data(**overrides) -> dict:
    data = {
        'name': 'Coding',
        'description': 'Test workgroup',
        'lead': 'coding-lead',
        'members': {'agents': [], 'hooks': []},
        'artifacts': [],
    }
    data.update(overrides)
    return data


# ── AC1: members: block parsed across all three YAML types ────────────────────

class TestLoadManagementTeamParsesNewMembersBlock(unittest.TestCase):
    """load_management_team() must parse members: with agents: and projects: sub-keys."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        data = _minimal_management_data(
            projects=[
                {'name': 'Alpha', 'path': '/tmp/alpha', 'config': '.teaparty/project/project.yaml'},
                {'name': 'Beta', 'path': '/tmp/beta', 'config': '.teaparty/project/project.yaml'},
            ],
            members={
                'projects': ['Alpha'],
                'agents': ['auditor', 'researcher'],
            },
        )
        _make_teaparty_yaml(os.path.join(self._tmpdir, '.teaparty'), data)
        self.team = load_management_team(
            teaparty_home=os.path.join(self._tmpdir, '.teaparty')
        )

    def test_members_agents_parsed(self):
        """members.agents: list loaded into members_agents field."""
        self.assertEqual(self.team.members_agents, ['auditor', 'researcher'])

    def test_projects_catalog_loaded(self):
        """projects: registration block loaded into projects field."""
        self.assertEqual(len(self.team.projects), 2)
        names = [p['name'] for p in self.team.projects]
        self.assertIn('Alpha', names)
        self.assertIn('Beta', names)


class TestLoadProjectTeamParsesNewMembersBlock(unittest.TestCase):
    """load_project_team() must parse members.workgroups: into members_workgroups."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        data = _minimal_project_data(
            workgroups=[
                {'name': 'Coding', 'config': '.teaparty/management/workgroups/coding.yaml'},
                {'name': 'Configuration', 'config': '.teaparty/management/workgroups/configuration.yaml'},
            ],
            members={'workgroups': ['Coding']},
        )
        _make_project_yaml(self._tmpdir, data)
        self.team = load_project_team(self._tmpdir)

    def test_members_workgroups_parsed(self):
        """members.workgroups: list loaded into members_workgroups field."""
        self.assertEqual(self.team.members_workgroups, ['Coding'])

    def test_workgroups_catalog_loaded(self):
        """workgroups: registration block loaded into workgroups field."""
        self.assertEqual(len(self.team.workgroups), 2)
        names = [e.name for e in self.team.workgroups]
        self.assertIn('Coding', names)
        self.assertIn('Configuration', names)


class TestLoadWorkgroupParsesNewMembersBlock(unittest.TestCase):
    """load_workgroup() must parse members.agents: and members.hooks: sub-keys."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        data = _minimal_workgroup_data(
            members={
                'agents': ['architect', 'developer'],
                'hooks': ['PostToolUse'],
            },
        )
        self._path = _make_workgroup_yaml(self._tmpdir, 'coding', data)
        self.wg = load_workgroup(self._path)

    def test_members_agents_parsed(self):
        """members.agents: list loaded into members_agents field."""
        self.assertEqual(self.wg.members_agents, ['architect', 'developer'])

    def test_members_hooks_parsed(self):
        """members.hooks: list loaded into members_hooks field."""
        self.assertEqual(self.wg.members_hooks, ['PostToolUse'])


# ── AC2: reader exposes both catalog and members (distinction) ────────────────

class TestManagementTeamRegisteredProjects(unittest.TestCase):
    """Reader must expose all registered projects (no active/inactive distinction)."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        data = _minimal_management_data(
            projects=[
                {'name': 'Alpha', 'path': '/tmp/alpha', 'config': '.teaparty/project/project.yaml'},
                {'name': 'Beta', 'path': '/tmp/beta', 'config': '.teaparty/project/project.yaml'},
            ],
        )
        _make_teaparty_yaml(os.path.join(self._tmpdir, '.teaparty'), data)
        self.team = load_management_team(
            teaparty_home=os.path.join(self._tmpdir, '.teaparty')
        )

    def test_registered_catalog_includes_all_projects(self):
        """projects field includes both Alpha and Beta."""
        names = {p['name'] for p in self.team.projects}
        self.assertIn('Alpha', names)
        self.assertIn('Beta', names)

    def test_no_members_projects_attribute(self):
        """ManagementTeam must not have members_projects — all registered projects are active."""
        self.assertFalse(hasattr(self.team, 'members_projects'))


class TestProjectTeamRegisteredVsActiveMembership(unittest.TestCase):
    """Reader must expose all registered workgroups and only active members_workgroups."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        data = _minimal_project_data(
            workgroups=[
                {'name': 'Coding', 'config': '.teaparty/management/workgroups/coding.yaml'},
                {'name': 'Configuration', 'config': '.teaparty/management/workgroups/configuration.yaml'},
            ],
            members={'workgroups': ['Coding']},
        )
        _make_project_yaml(self._tmpdir, data)
        self.team = load_project_team(self._tmpdir)

    def test_workgroups_catalog_includes_all_registered(self):
        """workgroups field includes both Coding and Configuration."""
        names = {e.name for e in self.team.workgroups}
        self.assertIn('Coding', names)
        self.assertIn('Configuration', names)

    def test_members_workgroups_contains_only_active(self):
        """members_workgroups contains only Coding, not Configuration."""
        self.assertIn('Coding', self.team.members_workgroups)
        self.assertNotIn('Configuration', self.team.members_workgroups)


# ── AC3: artifacts: field parsed as list of path/label pairs ─────────────────

class TestLoadWorkgroupParsesArtifactsAsDicts(unittest.TestCase):
    """artifacts: field must be returned as list of {path, label} dicts."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        data = _minimal_workgroup_data(
            artifacts=[
                {'path': '.teaparty/management/workgroups/NORMS.md', 'label': 'Norms'},
                {'path': '.teaparty/management/workgroups/DESIGN.md', 'label': 'Design Doc'},
            ],
        )
        self._path = _make_workgroup_yaml(self._tmpdir, 'coding', data)
        self.wg = load_workgroup(self._path)

    def test_artifacts_loaded_as_list(self):
        """wg.artifacts must be a list."""
        self.assertIsInstance(self.wg.artifacts, list)

    def test_artifacts_length_matches_yaml(self):
        """All artifact entries from YAML are loaded."""
        self.assertEqual(len(self.wg.artifacts), 2)

    def test_artifacts_contain_path_key(self):
        """Each artifact entry must have a 'path' key."""
        for artifact in self.wg.artifacts:
            self.assertIn('path', artifact)

    def test_artifacts_with_label_contain_label_key(self):
        """Artifact entries that have a label in YAML expose it in the dict."""
        labeled = [a for a in self.wg.artifacts if 'label' in a]
        self.assertGreater(len(labeled), 0, 'Fixture must include at least one labeled artifact')
        for artifact in labeled:
            self.assertIsInstance(artifact['label'], str)

    def test_artifacts_path_and_label_values(self):
        """Artifact path and label values match the YAML."""
        paths = {a['path'] for a in self.wg.artifacts}
        labels = {a['label'] for a in self.wg.artifacts}
        self.assertIn('.teaparty/management/workgroups/NORMS.md', paths)
        self.assertIn('Norms', labels)

    def test_empty_artifacts_list_is_valid(self):
        """A workgroup with no artifacts must not raise an error."""
        data = _minimal_workgroup_data(artifacts=[])
        path = _make_workgroup_yaml(self._tmpdir, 'empty', data)
        wg = load_workgroup(path)
        self.assertEqual(wg.artifacts, [])

    def test_artifact_without_label_key_loads_correctly(self):
        """An artifact entry with only path: and no label: must load without error.

        The spec (proposal.md lines 167-169) shows label: is optional:
          artifacts:
            - path: NORMS.md        # no label
            - path: docs/
              label: Docs
        """
        data = _minimal_workgroup_data(
            artifacts=[
                {'path': 'NORMS.md'},  # label-less — spec-compliant
                {'path': 'docs/', 'label': 'Docs'},
            ],
        )
        path = _make_workgroup_yaml(self._tmpdir, 'nolabel', data)
        wg = load_workgroup(path)
        self.assertEqual(len(wg.artifacts), 2)
        # First artifact has no label key
        paths = [a['path'] for a in wg.artifacts]
        self.assertIn('NORMS.md', paths)
        label_less = next(a for a in wg.artifacts if a['path'] == 'NORMS.md')
        self.assertNotIn('label', label_less)


# ── AC4: no skills: expected in workgroup YAML; no error if absent ────────────

class TestLoadWorkgroupNoSkillsKeyRequired(unittest.TestCase):
    """load_workgroup() must not require or fail on absence of skills: key."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def test_workgroup_without_skills_key_loads_without_error(self):
        """A workgroup YAML with no skills: key must load cleanly."""
        data = _minimal_workgroup_data()
        self.assertNotIn('skills', data, 'Fixture must not have skills: key')
        path = _make_workgroup_yaml(self._tmpdir, 'noskills', data)
        wg = load_workgroup(path)  # must not raise
        self.assertEqual(wg.name, 'Coding')

    def test_workgroup_has_no_skills_attribute(self):
        """Workgroup dataclass must not have a 'skills' attribute."""
        data = _minimal_workgroup_data()
        path = _make_workgroup_yaml(self._tmpdir, 'noskills2', data)
        wg = load_workgroup(path)
        self.assertFalse(hasattr(wg, 'skills'),
            'Workgroup must not have skills attribute — skills are per-agent')

    def test_workgroup_with_skills_key_loads_without_error(self):
        """A workgroup YAML that still has a legacy skills: key must not crash.

        Old YAML files may have skills: before migration; the reader must
        tolerate this gracefully (silently ignores it).
        """
        data = _minimal_workgroup_data()
        data['skills'] = ['commit', 'fix-issue']  # old-schema residue
        path = _make_workgroup_yaml(self._tmpdir, 'oldschema', data)
        wg = load_workgroup(path)  # must not raise
        self.assertFalse(hasattr(wg, 'skills'),
            'Workgroup must not expose skills even if present in YAML')


# ── Project toggle removed — all registered projects are active ──────────────
# TestToggleManagementMembershipProject and
# TestToggleManagementMembershipProjectDoesNotAffectOtherMembers were removed:
# members_projects was dead weight (#379). All registered projects are active.


# ── AC6: empty members: block is handled gracefully ──────────────────────────

class TestLoadManagementTeamWithEmptyMembersBlock(unittest.TestCase):
    """Management YAML with empty or absent members: block must not raise."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def test_absent_members_block_yields_empty_lists(self):
        """No members: key at all → members_agents are empty."""
        data = {
            'name': 'Management',
            'lead': 'office-manager',
            'humans': {'decider': 'darrell'},
        }
        home = os.path.join(self._tmpdir, '.teaparty')
        _make_teaparty_yaml(home, data)
        team = load_management_team(teaparty_home=home)
        self.assertEqual(team.members_agents, [])

    def test_empty_members_dict_yields_empty_lists(self):
        """Empty members: {} → members_agents are empty."""
        data = {
            'name': 'Management',
            'lead': 'office-manager',
            'humans': {'decider': 'darrell'},
            'members': {},
        }
        home = os.path.join(self._tmpdir, '.teaparty2')
        _make_teaparty_yaml(home, data)
        team = load_management_team(teaparty_home=home)
        self.assertEqual(team.members_agents, [])


class TestLoadProjectTeamWithEmptyMembersBlock(unittest.TestCase):
    """Project YAML with empty or absent members: block must not raise."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def test_absent_members_block_yields_empty_members_workgroups(self):
        """No members: key → members_workgroups is empty."""
        data = {
            'name': 'MyProject',
            'lead': 'project-lead',
            'humans': {'decider': 'darrell'},
            'workgroups': [],
        }
        _make_project_yaml(self._tmpdir, data)
        team = load_project_team(self._tmpdir)
        self.assertEqual(team.members_workgroups, [])

    def test_empty_members_dict_yields_empty_members_workgroups(self):
        """Empty members: {} → members_workgroups is empty."""
        data = {
            'name': 'MyProject',
            'lead': 'project-lead',
            'humans': {'decider': 'darrell'},
            'workgroups': [],
            'members': {},
        }
        project_dir = os.path.join(self._tmpdir, 'proj2')
        os.makedirs(project_dir)
        _make_project_yaml(project_dir, data)
        team = load_project_team(project_dir)
        self.assertEqual(team.members_workgroups, [])


class TestWorkgroupHasNoScheduledField(unittest.TestCase):
    """Scheduled tasks are only at management and project level — not in workgroup YAML."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def test_workgroup_has_no_scheduled_attribute(self):
        """Workgroup dataclass must not have a 'scheduled' attribute."""
        data = _minimal_workgroup_data()
        path = _make_workgroup_yaml(self._tmpdir, 'noscheduled', data)
        wg = load_workgroup(path)
        self.assertFalse(hasattr(wg, 'scheduled'),
            'Workgroup must not have scheduled attribute — tasks are management/project only')

    def test_workgroup_yaml_with_scheduled_key_does_not_expose_it(self):
        """A workgroup YAML with a legacy scheduled: key must load without exposing it."""
        data = _minimal_workgroup_data()
        data['scheduled'] = [{'name': 'nightly', 'schedule': '0 0 * * *', 'skill': 'audit'}]
        path = _make_workgroup_yaml(self._tmpdir, 'legacysched', data)
        wg = load_workgroup(path)  # must not raise
        self.assertFalse(hasattr(wg, 'scheduled'))

    def test_management_team_has_scheduled_field(self):
        """ManagementTeam must have a scheduled field for cron tasks."""
        home = os.path.join(self._tmpdir, '.teaparty')
        data = _minimal_management_data(
            scheduled=[{'name': 'nightly', 'schedule': '0 0 * * *', 'skill': 'audit'}],
        )
        _make_teaparty_yaml(home, data)
        team = load_management_team(teaparty_home=home)
        self.assertTrue(hasattr(team, 'scheduled'))
        self.assertEqual(len(team.scheduled), 1)
        self.assertEqual(team.scheduled[0].name, 'nightly')

    def test_project_team_has_scheduled_field(self):
        """ProjectTeam must have a scheduled field for cron tasks."""
        data = _minimal_project_data(
            scheduled=[{'name': 'weekly', 'schedule': '0 0 * * 0', 'skill': 'digest'}],
        )
        _make_project_yaml(self._tmpdir, data)
        team = load_project_team(self._tmpdir)
        self.assertTrue(hasattr(team, 'scheduled'))
        self.assertEqual(len(team.scheduled), 1)
        self.assertEqual(team.scheduled[0].name, 'weekly')


class TestLoadWorkgroupWithEmptyMembersBlock(unittest.TestCase):
    """Workgroup YAML with empty or absent members: block must not raise."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def test_absent_members_block_yields_empty_lists(self):
        """No members: key → members_agents and members_hooks are empty."""
        data = {'name': 'Coding', 'lead': 'coding-lead', 'artifacts': []}
        path = _make_workgroup_yaml(self._tmpdir, 'bare', data)
        wg = load_workgroup(path)
        self.assertEqual(wg.members_agents, [])
        self.assertEqual(wg.members_hooks, [])

    def test_empty_members_dict_yields_empty_lists(self):
        """Empty members: {} → members_agents and members_hooks are empty."""
        data = {'name': 'Coding', 'lead': 'coding-lead', 'members': {}, 'artifacts': []}
        path = _make_workgroup_yaml(self._tmpdir, 'empty_members', data)
        wg = load_workgroup(path)
        self.assertEqual(wg.members_agents, [])
        self.assertEqual(wg.members_hooks, [])


# ── AC6: toggle_project_membership supports 'workgroup' kind ─────────────────

class TestToggleProjectMembershipWorkgroup(unittest.TestCase):
    """toggle_project_membership must support kind='workgroup' to toggle members.workgroups."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        data = _minimal_project_data(
            workgroups=[
                {'name': 'Coding', 'config': '.teaparty/management/workgroups/coding.yaml'},
                {'name': 'Research', 'config': '.teaparty/management/workgroups/research.yaml'},
            ],
            members={'workgroups': ['Coding']},
        )
        _make_project_yaml(self._tmpdir, data)

    def test_activate_workgroup_adds_to_members_workgroups(self):
        """Activating an inactive workgroup adds it to members.workgroups in YAML."""
        toggle_project_membership(self._tmpdir, 'workgroup', 'Research', True)
        team = load_project_team(self._tmpdir)
        self.assertIn('Research', team.members_workgroups)

    def test_deactivate_workgroup_removes_from_members_workgroups(self):
        """Deactivating an active workgroup removes it from members.workgroups in YAML."""
        toggle_project_membership(self._tmpdir, 'workgroup', 'Coding', False)
        team = load_project_team(self._tmpdir)
        self.assertNotIn('Coding', team.members_workgroups)

    def test_activating_already_active_workgroup_is_idempotent(self):
        """Activating an already-active workgroup does not duplicate it."""
        toggle_project_membership(self._tmpdir, 'workgroup', 'Coding', True)
        team = load_project_team(self._tmpdir)
        self.assertEqual(team.members_workgroups.count('Coding'), 1)

    def test_deactivating_inactive_workgroup_is_safe(self):
        """Deactivating a workgroup not in members.workgroups does not raise."""
        toggle_project_membership(self._tmpdir, 'workgroup', 'Research', False)
        team = load_project_team(self._tmpdir)
        self.assertNotIn('Research', team.members_workgroups)


# ── Bridge project active flag removed ───────────────────────────────────────
# TestBridgeConfigProjectsIncludeActiveFlag was removed:
# members_projects was dead weight (#379). All registered projects are active.
