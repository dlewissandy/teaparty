#!/usr/bin/env python3
"""Tests for Issue #251: Configuration tree — teaparty.yaml and project.yaml readers.

Covers:
 1. Load teaparty.yaml into ManagementTeam dataclass
 2. Load project.yaml into ProjectTeam dataclass
 3. Load workgroup YAML into Workgroup dataclass
 4. Project discovery from teams: entries with path:
 5. ref: workgroup entries resolve to org-level workgroup files
 6. Path expansion (~ → home directory)
 7. Missing file error handling
 8. Round-trip fidelity with design doc example YAML files
"""
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.config_reader import (
    Human,
    ManagementTeam,
    ProjectTeam,
    ScheduledTask,
    Workgroup,
    WorkgroupRef,
    load_management_team,
    load_management_workgroups,
    load_project_team,
    load_workgroup,
    discover_projects,
    resolve_workgroups,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_teaparty_home(teaparty_yaml: str, workgroup_files: dict[str, str] | None = None) -> str:
    """Create a temp ~/.teaparty/ with teaparty.yaml and optional workgroup files."""
    home = tempfile.mkdtemp()
    tp_dir = os.path.join(home, '.teaparty')
    os.makedirs(tp_dir)
    with open(os.path.join(tp_dir, 'teaparty.yaml'), 'w') as f:
        f.write(teaparty_yaml)
    if workgroup_files:
        wg_dir = os.path.join(tp_dir, 'workgroups')
        os.makedirs(wg_dir, exist_ok=True)
        for name, content in workgroup_files.items():
            with open(os.path.join(wg_dir, name), 'w') as f:
                f.write(content)
    return home


def _make_project_dir(project_yaml: str, workgroup_files: dict[str, str] | None = None) -> str:
    """Create a temp project dir with .teaparty.local/project.yaml and optional workgroups."""
    proj = tempfile.mkdtemp()
    tp_local = os.path.join(proj, '.teaparty.local')
    os.makedirs(tp_local)
    with open(os.path.join(tp_local, 'project.yaml'), 'w') as f:
        f.write(project_yaml)
    # Also create .git/ and .claude/ and .teaparty/ so it looks like a valid project
    os.makedirs(os.path.join(proj, '.git'))
    os.makedirs(os.path.join(proj, '.claude'))
    os.makedirs(os.path.join(proj, '.teaparty'))
    if workgroup_files:
        wg_dir = os.path.join(tp_local, 'workgroups')
        os.makedirs(wg_dir, exist_ok=True)
        for name, content in workgroup_files.items():
            with open(os.path.join(wg_dir, name), 'w') as f:
                f.write(content)
    return proj


MINIMAL_TEAPARTY_YAML = textwrap.dedent("""\
    name: Management Team
    description: Cross-project coordination.
    lead: office-manager

    humans:
      decider: darrell
      advisors:
        - alice

    members:
      agents:
        - office-manager
        - auditor
      projects:
        - My Backend

    projects:
      - name: My Backend
        path: {project_path}
        config: ''

    workgroups:
      - name: Configuration
        config: workgroups/configuration.yaml

    scheduled:
      - name: nightly-test-sweep
        schedule: "0 2 * * *"
        skill: test-sweep
        args: "--all-projects"
""")


MINIMAL_PROJECT_YAML = textwrap.dedent("""\
    name: My Backend
    description: Backend API service.
    lead: project-lead

    humans:
      decider: darrell
      inform:
        - bob

    members:
      workgroups:
        - Coding

    workgroups:
      - ref: coding
        status: active
      - name: Research
        config: workgroups/research.yaml
        status: idle

    norms:
      quality:
        - All code changes must have tests
""")


MINIMAL_WORKGROUP_YAML = textwrap.dedent("""\
    name: Coding
    description: Implementation, testing, and code review.
    lead: coding-lead

    humans:
      decider: darrell

    members:
      agents:
        - coding-lead
        - developer
      hooks: []

    artifacts:
      - path: NORMS.md

    norms:
      quality:
        - Code review required before merge
""")


# ── 1. ManagementTeam loading ───────────────────────────────────────────────

class TestLoadManagementTeam(unittest.TestCase):
    """Load teaparty.yaml into ManagementTeam dataclass."""

    def test_basic_fields(self):
        proj = _make_project_dir("name: Dummy\ndescription: d\nlead: x\n")
        yaml_text = MINIMAL_TEAPARTY_YAML.format(project_path=proj)
        home = _make_teaparty_home(yaml_text)
        team = load_management_team(teaparty_home=os.path.join(home, '.teaparty'))
        self.assertEqual(team.name, 'Management Team')
        self.assertEqual(team.description, 'Cross-project coordination.')
        self.assertEqual(team.lead, 'office-manager')
        decider = next((h.name for h in team.humans if h.role == 'decider'), None)
        self.assertEqual(decider, 'darrell')

    def test_agents_list(self):
        proj = _make_project_dir("name: Dummy\ndescription: d\nlead: x\n")
        yaml_text = MINIMAL_TEAPARTY_YAML.format(project_path=proj)
        home = _make_teaparty_home(yaml_text)
        team = load_management_team(teaparty_home=os.path.join(home, '.teaparty'))
        self.assertEqual(team.members_agents, ['office-manager', 'auditor'])

    def test_humans_parsed(self):
        proj = _make_project_dir("name: Dummy\ndescription: d\nlead: x\n")
        yaml_text = MINIMAL_TEAPARTY_YAML.format(project_path=proj)
        home = _make_teaparty_home(yaml_text)
        team = load_management_team(teaparty_home=os.path.join(home, '.teaparty'))
        self.assertEqual(len(team.humans), 2)
        self.assertEqual(team.humans[0].name, 'darrell')
        self.assertEqual(team.humans[0].role, 'decider')
        self.assertEqual(team.humans[1].name, 'alice')
        self.assertEqual(team.humans[1].role, 'advisor')

    def test_projects_with_paths(self):
        proj = _make_project_dir("name: Dummy\ndescription: d\nlead: x\n")
        yaml_text = MINIMAL_TEAPARTY_YAML.format(project_path=proj)
        home = _make_teaparty_home(yaml_text)
        team = load_management_team(teaparty_home=os.path.join(home, '.teaparty'))
        self.assertEqual(len(team.projects), 1)
        self.assertEqual(team.projects[0]['name'], 'My Backend')
        self.assertEqual(team.projects[0]['path'], proj)

    def test_members_projects(self):
        proj = _make_project_dir("name: Dummy\ndescription: d\nlead: x\n")
        yaml_text = MINIMAL_TEAPARTY_YAML.format(project_path=proj)
        home = _make_teaparty_home(yaml_text)
        team = load_management_team(teaparty_home=os.path.join(home, '.teaparty'))
        self.assertEqual(team.members_projects, ['My Backend'])

    def test_scheduled_tasks(self):
        proj = _make_project_dir("name: Dummy\ndescription: d\nlead: x\n")
        yaml_text = MINIMAL_TEAPARTY_YAML.format(project_path=proj)
        home = _make_teaparty_home(yaml_text)
        team = load_management_team(teaparty_home=os.path.join(home, '.teaparty'))
        self.assertEqual(len(team.scheduled), 1)
        self.assertEqual(team.scheduled[0].name, 'nightly-test-sweep')
        self.assertEqual(team.scheduled[0].schedule, '0 2 * * *')
        self.assertEqual(team.scheduled[0].skill, 'test-sweep')
        self.assertEqual(team.scheduled[0].args, '--all-projects')

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_management_team(teaparty_home='/nonexistent/.teaparty')


# ── 2. ProjectTeam loading ──────────────────────────────────────────────────

class TestLoadProjectTeam(unittest.TestCase):
    """Load project.yaml into ProjectTeam dataclass."""

    def test_basic_fields(self):
        proj = _make_project_dir(MINIMAL_PROJECT_YAML)
        team = load_project_team(proj)
        self.assertEqual(team.name, 'My Backend')
        self.assertEqual(team.description, 'Backend API service.')
        self.assertEqual(team.lead, 'project-lead')
        decider = next((h.name for h in team.humans if h.role == 'decider'), None)
        self.assertEqual(decider, 'darrell')

    def test_members_workgroups(self):
        proj = _make_project_dir(MINIMAL_PROJECT_YAML)
        team = load_project_team(proj)
        self.assertEqual(team.members_workgroups, ['Coding'])

    def test_humans(self):
        proj = _make_project_dir(MINIMAL_PROJECT_YAML)
        team = load_project_team(proj)
        self.assertEqual(len(team.humans), 2)
        self.assertEqual(team.humans[1].name, 'bob')
        self.assertEqual(team.humans[1].role, 'informed')

    def test_workgroup_entries(self):
        proj = _make_project_dir(MINIMAL_PROJECT_YAML)
        team = load_project_team(proj)
        # First entry is a ref, second is a definition
        self.assertEqual(len(team.workgroups), 2)
        ref_entry = team.workgroups[0]
        self.assertIsInstance(ref_entry, WorkgroupRef)
        self.assertEqual(ref_entry.ref, 'coding')
        self.assertEqual(ref_entry.status, 'active')

    def test_norms(self):
        proj = _make_project_dir(MINIMAL_PROJECT_YAML)
        team = load_project_team(proj)
        self.assertIn('quality', team.norms)
        self.assertEqual(team.norms['quality'], ['All code changes must have tests'])

    def test_missing_file_raises(self):
        d = tempfile.mkdtemp()
        with self.assertRaises(FileNotFoundError):
            load_project_team(d)


# ── 3. Workgroup loading ────────────────────────────────────────────────────

class TestLoadWorkgroup(unittest.TestCase):
    """Load workgroup YAML into Workgroup dataclass."""

    def test_basic_fields(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, 'coding.yaml')
        with open(path, 'w') as f:
            f.write(MINIMAL_WORKGROUP_YAML)
        wg = load_workgroup(path)
        self.assertEqual(wg.name, 'Coding')
        self.assertEqual(wg.description, 'Implementation, testing, and code review.')
        self.assertEqual(wg.lead, 'coding-lead')

    def test_members_agents(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, 'coding.yaml')
        with open(path, 'w') as f:
            f.write(MINIMAL_WORKGROUP_YAML)
        wg = load_workgroup(path)
        self.assertEqual(wg.members_agents, ['coding-lead', 'developer'])

    def test_artifacts(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, 'coding.yaml')
        with open(path, 'w') as f:
            f.write(MINIMAL_WORKGROUP_YAML)
        wg = load_workgroup(path)
        self.assertEqual(len(wg.artifacts), 1)
        self.assertEqual(wg.artifacts[0]['path'], 'NORMS.md')

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_workgroup('/nonexistent/coding.yaml')


# ── 4. Project discovery ────────────────────────────────────────────────────

class TestDiscoverProjects(unittest.TestCase):
    """Discover projects from teams: entries with path: in teaparty.yaml."""

    def test_discovers_valid_project(self):
        proj = _make_project_dir("name: P\ndescription: d\nlead: x\ndecider: x\n")
        yaml_text = MINIMAL_TEAPARTY_YAML.format(project_path=proj)
        home = _make_teaparty_home(yaml_text)
        team = load_management_team(teaparty_home=os.path.join(home, '.teaparty'))
        projects = discover_projects(team)
        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]['name'], 'My Backend')
        self.assertEqual(projects[0]['path'], proj)
        self.assertTrue(projects[0]['valid'])

    def test_invalid_project_missing_markers(self):
        """A directory without .git/.claude/.teaparty is marked invalid."""
        d = tempfile.mkdtemp()  # bare dir, no markers
        yaml_text = MINIMAL_TEAPARTY_YAML.format(project_path=d)
        home = _make_teaparty_home(yaml_text)
        team = load_management_team(teaparty_home=os.path.join(home, '.teaparty'))
        projects = discover_projects(team)
        self.assertFalse(projects[0]['valid'])

    def test_nonexistent_path_invalid(self):
        """A path that doesn't exist is marked invalid."""
        yaml_text = MINIMAL_TEAPARTY_YAML.format(project_path='/nonexistent/project')
        home = _make_teaparty_home(yaml_text)
        team = load_management_team(teaparty_home=os.path.join(home, '.teaparty'))
        projects = discover_projects(team)
        self.assertFalse(projects[0]['valid'])

    def test_tilde_expansion(self):
        """Paths with ~ are expanded to the user's home directory."""
        yaml_text = textwrap.dedent("""\
            name: Test
            description: test
            lead: x
            projects:
              - name: Tilde Project
                path: ~/nonexistent-teaparty-test-path
                config: ''
        """)
        home = _make_teaparty_home(yaml_text)
        team = load_management_team(teaparty_home=os.path.join(home, '.teaparty'))
        projects = discover_projects(team)
        # Path should be expanded (no ~)
        self.assertNotIn('~', projects[0]['path'])
        self.assertTrue(projects[0]['path'].startswith('/'))

    def test_empty_teams_list(self):
        yaml_text = textwrap.dedent("""\
            name: Test
            description: test
            lead: x
            decider: x
        """)
        home = _make_teaparty_home(yaml_text)
        team = load_management_team(teaparty_home=os.path.join(home, '.teaparty'))
        projects = discover_projects(team)
        self.assertEqual(projects, [])


# ── 5. ref: workgroup resolution ────────────────────────────────────────────

class TestResolveWorkgroups(unittest.TestCase):
    """ref: entries resolve to org-level workgroup definitions."""

    def _research_yaml(self):
        return "name: Research\ndescription: Research workgroup.\nlead: research-lead\n"

    def test_ref_resolves_to_org_workgroup(self):
        proj = _make_project_dir(
            MINIMAL_PROJECT_YAML,
            workgroup_files={'research.yaml': self._research_yaml()},
        )
        home = _make_teaparty_home(
            MINIMAL_TEAPARTY_YAML.format(project_path=proj),
            workgroup_files={'coding.yaml': MINIMAL_WORKGROUP_YAML},
        )
        team = load_project_team(proj)
        resolved = resolve_workgroups(
            team.workgroups,
            project_dir=proj,
            teaparty_home=os.path.join(home, '.teaparty'),
        )
        # First entry was ref: coding → should now be a Workgroup
        self.assertIsInstance(resolved[0], Workgroup)
        self.assertEqual(resolved[0].name, 'Coding')

    def test_project_override_trumps_org(self):
        """Project-level workgroup definition overrides org-level for same name."""
        override_yaml = textwrap.dedent("""\
            name: Coding
            description: Project-specific coding team.
            lead: project-coding-lead
        """)
        proj = _make_project_dir(
            MINIMAL_PROJECT_YAML,
            workgroup_files={
                'coding.yaml': override_yaml,
                'research.yaml': self._research_yaml(),
            },
        )
        home = _make_teaparty_home(
            MINIMAL_TEAPARTY_YAML.format(project_path=proj),
            workgroup_files={'coding.yaml': MINIMAL_WORKGROUP_YAML},
        )
        team = load_project_team(proj)
        resolved = resolve_workgroups(
            team.workgroups,
            project_dir=proj,
            teaparty_home=os.path.join(home, '.teaparty'),
        )
        # Should use project-level override
        self.assertEqual(resolved[0].description, 'Project-specific coding team.')

    def test_missing_ref_raises(self):
        """ref: to a nonexistent org workgroup raises FileNotFoundError."""
        proj = _make_project_dir(MINIMAL_PROJECT_YAML)
        home = _make_teaparty_home(
            MINIMAL_TEAPARTY_YAML.format(project_path=proj),
            # No coding.yaml provided
        )
        team = load_project_team(proj)
        with self.assertRaises(FileNotFoundError):
            resolve_workgroups(
                team.workgroups,
                project_dir=proj,
                teaparty_home=os.path.join(home, '.teaparty'),
            )


# ── 6. Management-level workgroup loading ────────────────────────────────────

class TestLoadManagementWorkgroups(unittest.TestCase):
    """Management-level workgroups are loaded from ~/.teaparty/workgroups/."""

    def test_loads_management_workgroups(self):
        config_yaml = textwrap.dedent("""\
            name: Configuration
            description: Configuration management.
            lead: config-lead
        """)
        proj = _make_project_dir("name: D\ndescription: d\nlead: x\ndecider: x\n")
        home = _make_teaparty_home(
            MINIMAL_TEAPARTY_YAML.format(project_path=proj),
            workgroup_files={'configuration.yaml': config_yaml},
        )
        team = load_management_team(teaparty_home=os.path.join(home, '.teaparty'))
        workgroups = load_management_workgroups(team, teaparty_home=os.path.join(home, '.teaparty'))
        self.assertEqual(len(workgroups), 1)
        self.assertEqual(workgroups[0].name, 'Configuration')
        self.assertEqual(workgroups[0].lead, 'config-lead')

    def test_missing_management_workgroup_raises(self):
        proj = _make_project_dir("name: D\ndescription: d\nlead: x\ndecider: x\n")
        home = _make_teaparty_home(
            MINIMAL_TEAPARTY_YAML.format(project_path=proj),
            # No configuration.yaml provided
        )
        team = load_management_team(teaparty_home=os.path.join(home, '.teaparty'))
        with self.assertRaises(FileNotFoundError):
            load_management_workgroups(team, teaparty_home=os.path.join(home, '.teaparty'))


# ── 7. Design doc example YAML fidelity ─────────────────────────────────────

class TestDesignDocExamples(unittest.TestCase):
    """The reader can load the actual example YAML files from the design doc."""

    def _example_path(self, filename):
        # Resolve relative to repo root
        here = Path(__file__).resolve().parent
        return here.parent / 'docs' / 'proposals' / 'team-configuration' / 'examples' / filename

    def test_load_teaparty_yaml_example(self):
        path = self._example_path('teaparty.yaml')
        if not path.exists():
            self.skipTest('Example YAML not found')
        team = load_management_team(teaparty_home=str(path.parent), config_filename=str(path.name))
        self.assertEqual(team.name, 'Management Team')
        self.assertEqual(team.lead, 'office-manager')
        self.assertEqual(len(team.humans), 2)

    def test_load_project_yaml_example(self):
        path = self._example_path('project.yaml')
        if not path.exists():
            self.skipTest('Example YAML not found')
        team = load_project_team(str(path.parent.parent), config_path=str(path))
        self.assertEqual(team.name, 'My Backend')
        self.assertEqual(team.lead, 'project-lead')

    def test_load_workgroup_yaml_example(self):
        path = self._example_path('workgroup-coding.yaml')
        if not path.exists():
            self.skipTest('Example YAML not found')
        wg = load_workgroup(str(path))
        self.assertEqual(wg.name, 'Coding')
        self.assertEqual(wg.lead, 'coding-lead')


if __name__ == '__main__':
    unittest.main()
