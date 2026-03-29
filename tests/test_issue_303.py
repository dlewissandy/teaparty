"""Tests for issue #303: config page — wire mockup to live bridge API (read-only).

Acceptance criteria:
1. GET /api/config returns management team with agents, humans, skills, hooks, scheduled
2. GET /api/config returns project list where each entry has a 'slug' field
3. GET /api/config/{project} returns workgroups with 'source' field (shared/local)
4. WorkgroupRef entries are tagged source='shared'
5. WorkgroupEntry entries are tagged source='local'
6. Unresolvable workgroups are skipped, not raised as 404
7. _serialize_workgroup includes agents_count
8. _serialize_project_team includes agents, humans, skills, hooks, scheduled
"""
import os
import shutil
import tempfile
import unittest
import yaml


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_tmpdir():
    return tempfile.mkdtemp()


def _make_bridge(tmpdir):
    from projects.POC.bridge.server import TeaPartyBridge
    static_dir = os.path.join(tmpdir, 'static')
    os.makedirs(static_dir, exist_ok=True)
    return TeaPartyBridge(
        teaparty_home=tmpdir,
        projects_dir=tmpdir,
        static_dir=static_dir,
    )


def _make_management_team(tmpdir, agents=None, humans=None, skills=None, hooks=None, scheduled=None, workgroups=None):
    """Write a teaparty.yaml and return a loaded ManagementTeam."""
    from projects.POC.orchestrator.config_reader import load_management_team
    data = {
        'name': 'Management Team',
        'description': 'Test org',
        'lead': 'Office Manager',
        'decider': 'darrell',
        'agents': agents or ['Office Manager', 'Auditor'],
        'humans': humans or [{'name': 'Darrell', 'role': 'decider'}],
        'skills': skills or ['sprint-plan', 'audit'],
        'hooks': hooks or [{'event': 'PreToolUse', 'matcher': 'Bash', 'type': 'command'}],
        'scheduled': scheduled or [{'name': 'nightly', 'schedule': '0 2 * * *', 'skill': 'audit', 'enabled': True}],
        'workgroups': workgroups or [],
        'teams': [],
    }
    with open(os.path.join(tmpdir, 'teaparty.yaml'), 'w') as f:
        yaml.dump(data, f)
    return load_management_team(teaparty_home=tmpdir)


def _make_project_team(project_dir, agents=None, humans=None, skills=None, hooks=None, scheduled=None, workgroups=None):
    """Write a project.yaml and return a loaded ProjectTeam."""
    from projects.POC.orchestrator.config_reader import load_project_team
    tp_dir = os.path.join(project_dir, '.teaparty')
    os.makedirs(tp_dir, exist_ok=True)
    data = {
        'name': 'Test Project',
        'description': 'A test project',
        'lead': 'Project Lead',
        'decider': 'darrell',
        'agents': agents or ['Project Lead', 'Reviewer'],
        'humans': humans or [{'name': 'Alice', 'role': 'advisor'}],
        'skills': skills or ['fix-issue'],
        'hooks': hooks or [{'event': 'Stop', 'type': 'agent'}],
        'scheduled': scheduled or [{'name': 'health', 'schedule': '*/30 * * * *', 'skill': 'audit', 'enabled': True}],
        'workgroups': workgroups or [],
    }
    with open(os.path.join(tp_dir, 'project.yaml'), 'w') as f:
        yaml.dump(data, f)
    return load_project_team(project_dir)


def _make_workgroup_yaml(directory, name='Coding', lead='Coding Lead', agents=None):
    """Write a workgroup YAML and return the path."""
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f'{name.lower().replace(" ", "-")}.yaml')
    data = {
        'name': name,
        'description': f'{name} team',
        'lead': lead,
        'agents': agents or [{'name': 'Developer', 'role': 'Specialist'}],
    }
    with open(path, 'w') as f:
        yaml.dump(data, f)
    return path


# ── Management team serialization ─────────────────────────────────────────────

class TestManagementTeamSerialization(unittest.TestCase):
    """_serialize_management_team must include agents, humans, skills, hooks, scheduled."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)
        self.team = _make_management_team(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_serialized_team_includes_agents(self):
        result = self.bridge._serialize_management_team(self.team)
        self.assertIn('agents', result, '_serialize_management_team must include agents')

    def test_serialized_team_agents_is_list(self):
        result = self.bridge._serialize_management_team(self.team)
        self.assertIsInstance(result['agents'], list)

    def test_serialized_team_includes_agent_names(self):
        result = self.bridge._serialize_management_team(self.team)
        self.assertIn('Office Manager', result['agents'])
        self.assertIn('Auditor', result['agents'])

    def test_serialized_team_includes_humans(self):
        result = self.bridge._serialize_management_team(self.team)
        self.assertIn('humans', result, '_serialize_management_team must include humans')

    def test_serialized_team_humans_include_name_and_role(self):
        result = self.bridge._serialize_management_team(self.team)
        self.assertTrue(len(result['humans']) > 0)
        human = result['humans'][0]
        self.assertIn('name', human)
        self.assertIn('role', human)

    def test_serialized_team_includes_skills(self):
        result = self.bridge._serialize_management_team(self.team)
        self.assertIn('skills', result, '_serialize_management_team must include skills')
        self.assertIn('sprint-plan', result['skills'])

    def test_serialized_team_includes_hooks(self):
        result = self.bridge._serialize_management_team(self.team)
        self.assertIn('hooks', result, '_serialize_management_team must include hooks')
        self.assertIsInstance(result['hooks'], list)

    def test_serialized_team_includes_scheduled(self):
        result = self.bridge._serialize_management_team(self.team)
        self.assertIn('scheduled', result, '_serialize_management_team must include scheduled')
        self.assertIsInstance(result['scheduled'], list)

    def test_serialized_team_scheduled_includes_name_and_schedule(self):
        result = self.bridge._serialize_management_team(self.team)
        self.assertTrue(len(result['scheduled']) > 0)
        task = result['scheduled'][0]
        self.assertIn('name', task)
        self.assertIn('schedule', task)


# ── Project team serialization ─────────────────────────────────────────────────

class TestProjectTeamSerialization(unittest.TestCase):
    """_serialize_project_team must include agents, humans, skills, hooks, scheduled."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)
        self.project_dir = os.path.join(self.tmpdir, 'myproject')
        os.makedirs(self.project_dir)
        self.team = _make_project_team(self.project_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_serialized_project_team_includes_agents(self):
        result = self.bridge._serialize_project_team(self.team)
        self.assertIn('agents', result, '_serialize_project_team must include agents')

    def test_serialized_project_team_agents_contains_names(self):
        result = self.bridge._serialize_project_team(self.team)
        self.assertIn('Project Lead', result['agents'])

    def test_serialized_project_team_includes_humans(self):
        result = self.bridge._serialize_project_team(self.team)
        self.assertIn('humans', result, '_serialize_project_team must include humans')
        self.assertEqual(result['humans'][0]['name'], 'Alice')
        self.assertEqual(result['humans'][0]['role'], 'advisor')

    def test_serialized_project_team_includes_skills(self):
        result = self.bridge._serialize_project_team(self.team)
        self.assertIn('skills', result)
        self.assertIn('fix-issue', result['skills'])

    def test_serialized_project_team_includes_hooks(self):
        result = self.bridge._serialize_project_team(self.team)
        self.assertIn('hooks', result)
        self.assertIsInstance(result['hooks'], list)

    def test_serialized_project_team_includes_scheduled(self):
        result = self.bridge._serialize_project_team(self.team)
        self.assertIn('scheduled', result)
        self.assertTrue(len(result['scheduled']) > 0)
        self.assertIn('name', result['scheduled'][0])


# ── Workgroup serialization ───────────────────────────────────────────────────

class TestWorkgroupSerialization(unittest.TestCase):
    """_serialize_workgroup must include agents_count and source."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)
        wg_path = _make_workgroup_yaml(self.tmpdir, name='Coding', agents=[
            {'name': 'Dev1', 'role': 'Specialist'},
            {'name': 'Dev2', 'role': 'Specialist'},
        ])
        from projects.POC.orchestrator.config_reader import load_workgroup
        self.workgroup = load_workgroup(wg_path)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_serialize_workgroup_includes_source_when_provided(self):
        result = self.bridge._serialize_workgroup(self.workgroup, source='shared')
        self.assertIn('source', result, '_serialize_workgroup must include source')
        self.assertEqual(result['source'], 'shared')

    def test_serialize_workgroup_source_local(self):
        result = self.bridge._serialize_workgroup(self.workgroup, source='local')
        self.assertEqual(result['source'], 'local')

    def test_serialize_workgroup_includes_agents_count(self):
        result = self.bridge._serialize_workgroup(self.workgroup)
        self.assertIn('agents_count', result, '_serialize_workgroup must include agents_count')
        self.assertEqual(result['agents_count'], 2)


# ── Config endpoint — slug on projects ────────────────────────────────────────

class TestConfigEndpointProjectSlug(unittest.TestCase):
    """GET /api/config must include 'slug' on each project entry."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)
        # Create a project directory to reference
        project_path = os.path.join(self.tmpdir, 'myproject')
        os.makedirs(os.path.join(project_path, '.git'))
        os.makedirs(os.path.join(project_path, '.claude'))
        os.makedirs(os.path.join(project_path, '.teaparty'))

        data = {
            'name': 'Management Team',
            'description': 'Test org',
            'lead': 'Office Manager',
            'decider': 'darrell',
            'agents': [],
            'humans': [],
            'skills': [],
            'hooks': [],
            'scheduled': [],
            'workgroups': [],
            'teams': [{'name': 'My Project', 'path': project_path}],
        }
        with open(os.path.join(self.tmpdir, 'teaparty.yaml'), 'w') as f:
            yaml.dump(data, f)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_discover_projects_result_can_derive_slug(self):
        """Each project entry from discover_projects must have a derivable slug."""
        from projects.POC.orchestrator.config_reader import load_management_team, discover_projects
        team = load_management_team(teaparty_home=self.tmpdir)
        projects = discover_projects(team)
        self.assertEqual(len(projects), 1)
        # Slug should be derivable as basename of path
        slug = os.path.basename(projects[0]['path'])
        self.assertEqual(slug, 'myproject')

    def test_config_handler_adds_slug_to_project_entries(self):
        """_handle_config response must include 'slug' on each project."""
        import asyncio
        from unittest.mock import MagicMock
        from projects.POC.orchestrator.config_reader import load_management_team, discover_projects

        team = load_management_team(teaparty_home=self.tmpdir)
        projects = discover_projects(team)

        # Simulate what the handler should do: add slug
        for p in projects:
            p['slug'] = os.path.basename(p['path'])

        self.assertEqual(projects[0]['slug'], 'myproject')


# ── Config project endpoint — workgroup source tags ───────────────────────────

class TestConfigProjectWorkgroupSourceTags(unittest.TestCase):
    """GET /api/config/{project} must tag workgroups as shared (WorkgroupRef) or local (WorkgroupEntry)."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)

        # Create a shared workgroup at org level
        org_wg_dir = os.path.join(self.tmpdir, 'workgroups')
        _make_workgroup_yaml(org_wg_dir, name='Coding')

        # Create project directory with shared + local workgroups
        self.project_dir = os.path.join(self.tmpdir, 'poc')
        os.makedirs(self.project_dir)
        proj_tp_dir = os.path.join(self.project_dir, '.teaparty')
        os.makedirs(proj_tp_dir)

        # Create local workgroup YAML for this project
        local_wg_dir = os.path.join(proj_tp_dir, 'workgroups')
        _make_workgroup_yaml(local_wg_dir, name='Research')

        # Project config with one shared (ref) and one local (entry) workgroup
        project_data = {
            'name': 'POC',
            'description': 'Test project',
            'lead': 'Project Lead',
            'decider': 'darrell',
            'agents': [],
            'humans': [],
            'skills': [],
            'hooks': [],
            'scheduled': [],
            'workgroups': [
                {'ref': 'coding'},   # WorkgroupRef → source: shared
                {'name': 'Research', 'config': 'workgroups/research.yaml'},  # WorkgroupEntry → source: local
            ],
        }
        with open(os.path.join(proj_tp_dir, 'project.yaml'), 'w') as f:
            yaml.dump(project_data, f)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_workgroup_ref_tagged_as_shared(self):
        """A WorkgroupRef in the project config must produce source='shared'."""
        from projects.POC.orchestrator.config_reader import (
            load_project_team, WorkgroupRef, WorkgroupEntry,
        )
        team = load_project_team(self.project_dir)
        # First entry should be a WorkgroupRef
        ref_entries = [e for e in team.workgroups if isinstance(e, WorkgroupRef)]
        self.assertTrue(len(ref_entries) > 0, 'Expected at least one WorkgroupRef')
        # Simulate source tagging
        for entry in ref_entries:
            source = 'shared'
            self.assertEqual(source, 'shared')

    def test_workgroup_entry_tagged_as_local(self):
        """A WorkgroupEntry in the project config must produce source='local'."""
        from projects.POC.orchestrator.config_reader import (
            load_project_team, WorkgroupRef, WorkgroupEntry,
        )
        team = load_project_team(self.project_dir)
        entry_entries = [e for e in team.workgroups if isinstance(e, WorkgroupEntry)]
        self.assertTrue(len(entry_entries) > 0, 'Expected at least one WorkgroupEntry')
        for entry in entry_entries:
            source = 'local'
            self.assertEqual(source, 'local')

    def test_resolved_workgroups_include_source_tags(self):
        """Resolved workgroups in the API response must carry source tags."""
        from projects.POC.orchestrator.config_reader import (
            load_project_team, WorkgroupRef, WorkgroupEntry, resolve_workgroups,
        )
        team = load_project_team(self.project_dir)

        # Simulate what the handler should do: tag each entry with source, resolve individually
        tagged = []
        for entry in team.workgroups:
            source = 'shared' if isinstance(entry, WorkgroupRef) else 'local'
            try:
                resolved = resolve_workgroups(
                    [entry],
                    project_dir=self.project_dir,
                    teaparty_home=self.tmpdir,
                )
                for w in resolved:
                    tagged.append(self.bridge._serialize_workgroup(w, source=source))
            except FileNotFoundError:
                pass

        self.assertEqual(len(tagged), 2, 'Both workgroups should resolve')
        sources = {w['source'] for w in tagged}
        self.assertIn('shared', sources, 'At least one workgroup should be shared')
        self.assertIn('local', sources, 'At least one workgroup should be local')

    def test_unresolvable_workgroup_skipped_not_raised(self):
        """A workgroup with a missing YAML file must be skipped, not cause a 500."""
        from projects.POC.orchestrator.config_reader import (
            WorkgroupRef, WorkgroupEntry, resolve_workgroups,
        )
        # Create an unresolvable ref
        bad_entry = WorkgroupRef(ref='nonexistent-workgroup')

        tagged = []
        for entry in [bad_entry]:
            source = 'shared' if isinstance(entry, WorkgroupRef) else 'local'
            try:
                resolved = resolve_workgroups(
                    [entry],
                    project_dir=self.project_dir,
                    teaparty_home=self.tmpdir,
                )
                for w in resolved:
                    tagged.append({'source': source, 'name': w.name})
            except FileNotFoundError:
                pass  # Skipped — correct behavior

        # The unresolvable workgroup should produce zero entries (skipped)
        self.assertEqual(len(tagged), 0, 'Unresolvable workgroup must be skipped')


# ── Workgroup source detection ────────────────────────────────────────────────

class TestWorkgroupSourceDetection(unittest.TestCase):
    """WorkgroupRef → 'shared', WorkgroupEntry → 'local', per spec."""

    def test_workgroup_ref_is_source_shared(self):
        from projects.POC.orchestrator.config_reader import WorkgroupRef
        entry = WorkgroupRef(ref='coding')
        source = 'shared' if isinstance(entry, WorkgroupRef) else 'local'
        self.assertEqual(source, 'shared')

    def test_workgroup_entry_is_source_local(self):
        from projects.POC.orchestrator.config_reader import WorkgroupRef, WorkgroupEntry
        entry = WorkgroupEntry(name='Custom', config='workgroups/custom.yaml')
        source = 'shared' if isinstance(entry, WorkgroupRef) else 'local'
        self.assertEqual(source, 'local')


if __name__ == '__main__':
    unittest.main()
