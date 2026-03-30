"""Tests for issue #323: index.html shows no projects — registry not loaded.

Acceptance criteria:
1. StateReader.reload() returns all projects registered in teaparty.yaml,
   including those with no .sessions/ directory.
2. A project with no sessions appears with empty sessions list,
   active_count=0, and attention_count=0.
3. Registry load errors (e.g. malformed teaparty.yaml) propagate out of
   StateReader.reload() rather than being swallowed silently.
"""
import os
import shutil
import tempfile
import unittest

import yaml


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_tmpdir() -> str:
    return tempfile.mkdtemp()


def _make_teaparty_home(tmpdir: str) -> str:
    """Create a .teaparty/ directory in tmpdir and return its path."""
    home = os.path.join(tmpdir, '.teaparty')
    os.makedirs(home, exist_ok=True)
    return home


def _write_teaparty_yaml(home: str, teams: list[dict]) -> None:
    """Write a minimal teaparty.yaml into home with the given teams list."""
    data = {
        'name': 'Test Management Team',
        'description': '',
        'lead': '',
        'decider': '',
        'agents': [],
        'humans': [],
        'teams': teams,
        'workgroups': [],
        'skills': [],
    }
    with open(os.path.join(home, 'teaparty.yaml'), 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _make_project_dir(tmpdir: str, name: str) -> str:
    """Create a valid TeaParty project directory (has .git, .claude, .teaparty)."""
    proj = os.path.join(tmpdir, name)
    os.makedirs(proj)
    for marker in ('.git', '.claude', '.teaparty'):
        os.makedirs(os.path.join(proj, marker))
    return proj


def _make_state_reader(repo_root: str, teaparty_home: str):
    from orchestrator.state_reader import StateReader
    return StateReader(repo_root=repo_root, teaparty_home=teaparty_home)


# ── AC1 & AC2: sessionless projects appear in reload() ───────────────────────

class TestRegisteredProjectWithoutSessions(unittest.TestCase):
    """StateReader.reload() must include registry projects with no .sessions/."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.home = _make_teaparty_home(self.tmpdir)
        self.proj_dir = _make_project_dir(self.tmpdir, 'my-project')
        _write_teaparty_yaml(self.home, [
            {'name': 'my-project', 'path': self.proj_dir},
        ])
        self.reader = _make_state_reader(self.tmpdir, self.home)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_project_without_sessions_dir_is_returned(self):
        """A registered project with no .sessions/ must appear in reload() output."""
        self.assertFalse(
            os.path.isdir(os.path.join(self.proj_dir, '.sessions')),
            'precondition: .sessions/ must not exist',
        )
        projects = self.reader.reload()
        slugs = [p.slug for p in projects]
        self.assertIn(
            'my-project', slugs,
            f'registered project "my-project" missing from reload() result; got: {slugs}',
        )

    def test_project_without_sessions_has_empty_sessions_list(self):
        """A registered project with no sessions must have an empty sessions list."""
        projects = self.reader.reload()
        proj = next((p for p in projects if p.slug == 'my-project'), None)
        self.assertIsNotNone(proj, 'project not found in reload() result')
        self.assertEqual(
            proj.sessions, [],
            f'expected empty sessions list, got: {proj.sessions}',
        )

    def test_project_without_sessions_has_zero_active_count(self):
        """A registered project with no sessions must have active_count=0."""
        projects = self.reader.reload()
        proj = next((p for p in projects if p.slug == 'my-project'), None)
        self.assertIsNotNone(proj, 'project not found in reload() result')
        self.assertEqual(
            proj.active_count, 0,
            f'expected active_count=0, got: {proj.active_count}',
        )

    def test_project_without_sessions_has_zero_attention_count(self):
        """A registered project with no sessions must have attention_count=0."""
        projects = self.reader.reload()
        proj = next((p for p in projects if p.slug == 'my-project'), None)
        self.assertIsNotNone(proj, 'project not found in reload() result')
        self.assertEqual(
            proj.attention_count, 0,
            f'expected attention_count=0, got: {proj.attention_count}',
        )

    def test_project_path_is_preserved(self):
        """The ProjectState.path for a sessionless project must match the registered path."""
        projects = self.reader.reload()
        proj = next((p for p in projects if p.slug == 'my-project'), None)
        self.assertIsNotNone(proj, 'project not found in reload() result')
        self.assertEqual(
            proj.path, self.proj_dir,
            f'expected path={self.proj_dir!r}, got: {proj.path!r}',
        )


class TestMultipleProjectsSomeWithoutSessions(unittest.TestCase):
    """When some projects have sessions and some don't, all must appear."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.home = _make_teaparty_home(self.tmpdir)

        self.proj_with = _make_project_dir(self.tmpdir, 'proj-with-sessions')
        # Give it a sessions dir with one session
        sess_dir = os.path.join(self.proj_with, '.sessions', '20260101-120000')
        os.makedirs(sess_dir)
        import json
        with open(os.path.join(sess_dir, '.cfa-state.json'), 'w') as f:
            json.dump({'phase': 'execution', 'state': 'TASK_IN_PROGRESS',
                       'actor': 'planning_team', 'history': [],
                       'backtrack_count': 0, 'task_id': '', 'parent_id': '',
                       'team_id': '', 'depth': 0}, f)

        self.proj_without = _make_project_dir(self.tmpdir, 'proj-without-sessions')

        _write_teaparty_yaml(self.home, [
            {'name': 'proj-with-sessions', 'path': self.proj_with},
            {'name': 'proj-without-sessions', 'path': self.proj_without},
        ])
        self.reader = _make_state_reader(self.tmpdir, self.home)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_both_projects_appear_in_reload(self):
        """Both the project with sessions and the one without must appear."""
        projects = self.reader.reload()
        slugs = {p.slug for p in projects}
        self.assertIn('proj-with-sessions', slugs,
                      'project with sessions missing from reload()')
        self.assertIn('proj-without-sessions', slugs,
                      'project without sessions missing from reload()')

    def test_project_with_sessions_has_sessions(self):
        """The project that has a session dir must show it."""
        projects = self.reader.reload()
        proj = next(p for p in projects if p.slug == 'proj-with-sessions')
        self.assertEqual(len(proj.sessions), 1,
                         'proj-with-sessions must have 1 session')

    def test_project_without_sessions_has_none(self):
        """The project without a sessions dir must have empty sessions list."""
        projects = self.reader.reload()
        proj = next(p for p in projects if p.slug == 'proj-without-sessions')
        self.assertEqual(proj.sessions, [],
                         'proj-without-sessions must have empty sessions list')


# ── AC3: registry errors propagate ───────────────────────────────────────────

class TestRegistryLoadErrorPropagates(unittest.TestCase):
    """A malformed teaparty.yaml must not be silently swallowed."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.home = _make_teaparty_home(self.tmpdir)
        # Write intentionally malformed YAML
        with open(os.path.join(self.home, 'teaparty.yaml'), 'w') as f:
            f.write('name: [unclosed bracket\n')
        self.reader = _make_state_reader(self.tmpdir, self.home)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_malformed_yaml_raises_rather_than_returning_empty(self):
        """StateReader.reload() must raise on malformed teaparty.yaml, not silently return []."""
        with self.assertRaises(Exception,
                               msg='malformed teaparty.yaml must raise, not silently return []'):
            self.reader.reload()


class TestMissingTeapartyYamlRaises(unittest.TestCase):
    """A missing teaparty.yaml must not be silently swallowed."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.home = _make_teaparty_home(self.tmpdir)
        # teaparty.yaml is intentionally absent
        self.reader = _make_state_reader(self.tmpdir, self.home)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_yaml_raises_rather_than_returning_empty(self):
        """StateReader.reload() must raise when teaparty.yaml is absent."""
        with self.assertRaises(Exception,
                               msg='missing teaparty.yaml must raise, not silently return []'):
            self.reader.reload()
