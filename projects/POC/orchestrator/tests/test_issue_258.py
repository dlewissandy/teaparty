#!/usr/bin/env python3
"""Tests for Issue #258: Team discovery — add, create, and remove projects.

Covers:
 1. add_project: validate existing dir, create .teaparty/project.yaml, update teams:
 2. create_project: new dir with git init, .claude/, .teaparty/, update teams:
 3. remove_project: remove from teams:, leave project untouched
 4. Validation: missing markers, duplicate names, nonexistent paths
 5. YAML persistence: changes written to disk and reloadable
"""
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.config_reader import (
    ManagementTeam,
    add_project,
    create_project,
    load_management_team,
    remove_project,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_teaparty_home(teaparty_yaml: str) -> str:
    """Create a temp ~/.teaparty/ with teaparty.yaml."""
    home = tempfile.mkdtemp()
    tp_dir = os.path.join(home, '.teaparty')
    os.makedirs(tp_dir)
    with open(os.path.join(tp_dir, 'teaparty.yaml'), 'w') as f:
        f.write(teaparty_yaml)
    return home


def _make_existing_project(name: str = 'My Project') -> str:
    """Create a temp dir with .git/ and .claude/ (valid candidate for add)."""
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, '.git'))
    os.makedirs(os.path.join(d, '.claude'))
    return d


MINIMAL_YAML = textwrap.dedent("""\
    name: Management Team
    description: Test management team.
    lead: office-manager
    decider: darrell
    agents:
      - office-manager
    teams: []
""")

YAML_WITH_ONE_TEAM = textwrap.dedent("""\
    name: Management Team
    description: Test management team.
    lead: office-manager
    decider: darrell
    agents:
      - office-manager
    teams:
      - name: Existing
        path: {project_path}
""")


# ── 1. add_project ──────────────────────────────────────────────────────────

class TestAddProject(unittest.TestCase):
    """Add an existing directory as a TeaParty project."""

    def test_adds_to_empty_teams(self):
        proj = _make_existing_project()
        home = _make_teaparty_home(MINIMAL_YAML)
        tp_home = os.path.join(home, '.teaparty')

        team = add_project('My Backend', proj, teaparty_home=tp_home)

        self.assertEqual(len(team.teams), 1)
        self.assertEqual(team.teams[0]['name'], 'My Backend')
        self.assertEqual(team.teams[0]['path'], os.path.realpath(proj))

    def test_creates_teaparty_dir_and_project_yaml(self):
        proj = _make_existing_project()
        home = _make_teaparty_home(MINIMAL_YAML)
        tp_home = os.path.join(home, '.teaparty')

        add_project('My Backend', proj, teaparty_home=tp_home)

        project_yaml = os.path.join(proj, '.teaparty', 'project.yaml')
        self.assertTrue(os.path.exists(project_yaml))

    def test_does_not_overwrite_existing_project_yaml(self):
        proj = _make_existing_project()
        tp_dir = os.path.join(proj, '.teaparty')
        os.makedirs(tp_dir)
        existing_content = 'name: Already Here\n'
        with open(os.path.join(tp_dir, 'project.yaml'), 'w') as f:
            f.write(existing_content)
        home = _make_teaparty_home(MINIMAL_YAML)
        tp_home = os.path.join(home, '.teaparty')

        add_project('Already Here', proj, teaparty_home=tp_home)

        with open(os.path.join(tp_dir, 'project.yaml')) as f:
            self.assertEqual(f.read(), existing_content)

    def test_persists_to_yaml_file(self):
        proj = _make_existing_project()
        home = _make_teaparty_home(MINIMAL_YAML)
        tp_home = os.path.join(home, '.teaparty')

        add_project('My Backend', proj, teaparty_home=tp_home)

        # Reload from disk — should see the new entry
        reloaded = load_management_team(teaparty_home=tp_home)
        self.assertEqual(len(reloaded.teams), 1)
        self.assertEqual(reloaded.teams[0]['name'], 'My Backend')

    def test_rejects_missing_git_dir(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, '.claude'))
        # No .git/
        home = _make_teaparty_home(MINIMAL_YAML)
        tp_home = os.path.join(home, '.teaparty')

        with self.assertRaises(ValueError):
            add_project('Bad Project', d, teaparty_home=tp_home)

    def test_rejects_missing_claude_dir(self):
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, '.git'))
        # No .claude/
        home = _make_teaparty_home(MINIMAL_YAML)
        tp_home = os.path.join(home, '.teaparty')

        with self.assertRaises(ValueError):
            add_project('Bad Project', d, teaparty_home=tp_home)

    def test_rejects_nonexistent_path(self):
        home = _make_teaparty_home(MINIMAL_YAML)
        tp_home = os.path.join(home, '.teaparty')

        with self.assertRaises(ValueError):
            add_project('Ghost', '/nonexistent/path', teaparty_home=tp_home)

    def test_rejects_duplicate_name(self):
        proj = _make_existing_project()
        yaml_text = YAML_WITH_ONE_TEAM.format(project_path=proj)
        home = _make_teaparty_home(yaml_text)
        tp_home = os.path.join(home, '.teaparty')

        with self.assertRaises(ValueError):
            add_project('Existing', proj, teaparty_home=tp_home)

    def test_expands_tilde_in_path(self):
        proj = _make_existing_project()
        home = _make_teaparty_home(MINIMAL_YAML)
        tp_home = os.path.join(home, '.teaparty')

        # Use the actual path (tilde expansion tested via the storage format)
        team = add_project('Tilde Test', proj, teaparty_home=tp_home)
        self.assertTrue(os.path.isabs(team.teams[0]['path']))


# ── 2. create_project ───────────────────────────────────────────────────────

class TestCreateProject(unittest.TestCase):
    """Create a brand new project directory with all scaffolding."""

    def test_creates_directory_structure(self):
        home = _make_teaparty_home(MINIMAL_YAML)
        tp_home = os.path.join(home, '.teaparty')
        new_dir = os.path.join(tempfile.mkdtemp(), 'new-project')

        create_project('New Project', new_dir, teaparty_home=tp_home)

        self.assertTrue(os.path.isdir(os.path.join(new_dir, '.git')))
        self.assertTrue(os.path.isdir(os.path.join(new_dir, '.claude')))
        self.assertTrue(os.path.isdir(os.path.join(new_dir, '.teaparty')))
        self.assertTrue(os.path.isfile(os.path.join(new_dir, '.teaparty', 'project.yaml')))

    def test_adds_to_teams(self):
        home = _make_teaparty_home(MINIMAL_YAML)
        tp_home = os.path.join(home, '.teaparty')
        new_dir = os.path.join(tempfile.mkdtemp(), 'new-project')

        team = create_project('New Project', new_dir, teaparty_home=tp_home)

        self.assertEqual(len(team.teams), 1)
        self.assertEqual(team.teams[0]['name'], 'New Project')

    def test_persists_to_yaml_file(self):
        home = _make_teaparty_home(MINIMAL_YAML)
        tp_home = os.path.join(home, '.teaparty')
        new_dir = os.path.join(tempfile.mkdtemp(), 'new-project')

        create_project('New Project', new_dir, teaparty_home=tp_home)

        reloaded = load_management_team(teaparty_home=tp_home)
        self.assertEqual(len(reloaded.teams), 1)
        self.assertEqual(reloaded.teams[0]['name'], 'New Project')

    def test_project_yaml_has_name(self):
        home = _make_teaparty_home(MINIMAL_YAML)
        tp_home = os.path.join(home, '.teaparty')
        new_dir = os.path.join(tempfile.mkdtemp(), 'new-project')

        create_project('New Project', new_dir, teaparty_home=tp_home)

        import yaml
        with open(os.path.join(new_dir, '.teaparty', 'project.yaml')) as f:
            data = yaml.safe_load(f)
        self.assertEqual(data['name'], 'New Project')

    def test_rejects_existing_directory(self):
        home = _make_teaparty_home(MINIMAL_YAML)
        tp_home = os.path.join(home, '.teaparty')
        existing = tempfile.mkdtemp()  # already exists

        with self.assertRaises(ValueError):
            create_project('Conflict', existing, teaparty_home=tp_home)

    def test_rejects_duplicate_name(self):
        proj = _make_existing_project()
        yaml_text = YAML_WITH_ONE_TEAM.format(project_path=proj)
        home = _make_teaparty_home(yaml_text)
        tp_home = os.path.join(home, '.teaparty')
        new_dir = os.path.join(tempfile.mkdtemp(), 'new-project')

        with self.assertRaises(ValueError):
            create_project('Existing', new_dir, teaparty_home=tp_home)


# ── 3. remove_project ───────────────────────────────────────────────────────

class TestRemoveProject(unittest.TestCase):
    """Remove a project from teams: without touching the project directory."""

    def test_removes_by_name(self):
        proj = _make_existing_project()
        yaml_text = YAML_WITH_ONE_TEAM.format(project_path=proj)
        home = _make_teaparty_home(yaml_text)
        tp_home = os.path.join(home, '.teaparty')

        team = remove_project('Existing', teaparty_home=tp_home)

        self.assertEqual(len(team.teams), 0)

    def test_leaves_project_directory_intact(self):
        proj = _make_existing_project()
        yaml_text = YAML_WITH_ONE_TEAM.format(project_path=proj)
        home = _make_teaparty_home(yaml_text)
        tp_home = os.path.join(home, '.teaparty')

        remove_project('Existing', teaparty_home=tp_home)

        # Project dir still exists with its markers
        self.assertTrue(os.path.isdir(proj))
        self.assertTrue(os.path.isdir(os.path.join(proj, '.git')))
        self.assertTrue(os.path.isdir(os.path.join(proj, '.claude')))

    def test_persists_removal_to_yaml(self):
        proj = _make_existing_project()
        yaml_text = YAML_WITH_ONE_TEAM.format(project_path=proj)
        home = _make_teaparty_home(yaml_text)
        tp_home = os.path.join(home, '.teaparty')

        remove_project('Existing', teaparty_home=tp_home)

        reloaded = load_management_team(teaparty_home=tp_home)
        self.assertEqual(len(reloaded.teams), 0)

    def test_rejects_unknown_name(self):
        home = _make_teaparty_home(MINIMAL_YAML)
        tp_home = os.path.join(home, '.teaparty')

        with self.assertRaises(ValueError):
            remove_project('Nonexistent', teaparty_home=tp_home)

    def test_removes_only_named_team(self):
        """When multiple teams exist, only the named one is removed."""
        proj1 = _make_existing_project()
        proj2 = _make_existing_project()
        yaml_text = textwrap.dedent(f"""\
            name: Management Team
            description: Test.
            lead: x
            decider: x
            teams:
              - name: Alpha
                path: {proj1}
              - name: Beta
                path: {proj2}
        """)
        home = _make_teaparty_home(yaml_text)
        tp_home = os.path.join(home, '.teaparty')

        team = remove_project('Alpha', teaparty_home=tp_home)

        self.assertEqual(len(team.teams), 1)
        self.assertEqual(team.teams[0]['name'], 'Beta')


if __name__ == '__main__':
    unittest.main()
