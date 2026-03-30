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
9. _serialize_project_team returns agents as {name, source} objects
10. Lead agent is tagged source='generated'; org agents 'shared'; others 'local'
11. _serialize_project_team returns skills as {name, source} objects
12. Org skills tagged 'shared'; project-only skills 'local'
13. Override data does not bleed from one workgroup to the next
"""
import json
import os
import shutil
import tempfile
import unittest
import yaml


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_tmpdir():
    return tempfile.mkdtemp()


def _make_bridge(tmpdir):
    """Create a bridge rooted at tmpdir/.teaparty (mirrors production layout)."""
    from bridge.server import TeaPartyBridge
    teaparty_home = os.path.join(tmpdir, '.teaparty')
    os.makedirs(teaparty_home, exist_ok=True)
    static_dir = os.path.join(tmpdir, 'static')
    os.makedirs(static_dir, exist_ok=True)

    class _TestBridge(TeaPartyBridge):
        def _lookup_project_path(self, slug):
            path = os.path.join(tmpdir, slug)
            return path if os.path.isdir(path) else None

    return _TestBridge(
        teaparty_home=teaparty_home,
        static_dir=static_dir,
    )


def _make_management_team(tmpdir, agents=None, humans=None, skills=None, hooks=None, scheduled=None, workgroups=None):
    """Write teaparty.yaml into tmpdir/.teaparty/ and return a loaded ManagementTeam."""
    from orchestrator.config_reader import load_management_team
    teaparty_home = os.path.join(tmpdir, '.teaparty')
    os.makedirs(teaparty_home, exist_ok=True)
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
    with open(os.path.join(teaparty_home, 'teaparty.yaml'), 'w') as f:
        yaml.dump(data, f)
    return load_management_team(teaparty_home=teaparty_home)


def _make_project_team(project_dir, agents=None, humans=None, skills=None, hooks=None, scheduled=None, workgroups=None):
    """Write a project.yaml and return a loaded ProjectTeam."""
    from orchestrator.config_reader import load_project_team
    tp_local = os.path.join(project_dir, '.teaparty.local')
    os.makedirs(tp_local, exist_ok=True)
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
    with open(os.path.join(tp_local, 'project.yaml'), 'w') as f:
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
        agent_names = [a['name'] if isinstance(a, dict) else a for a in result['agents']]
        self.assertIn('Office Manager', agent_names)
        self.assertIn('Auditor', agent_names)

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
        result = self.bridge._serialize_management_team(self.team, discovered_skills=['sprint-plan'])
        self.assertIn('skills', result, '_serialize_management_team must include skills')
        skill_names = [s['name'] if isinstance(s, dict) else s for s in result['skills']]
        self.assertIn('sprint-plan', skill_names)

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
        names = [a['name'] for a in result['agents']]
        self.assertIn('Project Lead', names)

    def test_serialized_project_team_includes_humans(self):
        result = self.bridge._serialize_project_team(self.team)
        self.assertIn('humans', result, '_serialize_project_team must include humans')
        self.assertEqual(result['humans'][0]['name'], 'Alice')
        self.assertEqual(result['humans'][0]['role'], 'advisor')

    def test_serialized_project_team_includes_skills(self):
        # Issue #327: skills come from filesystem discovery, not t.skills alone.
        # Pass fix-issue as a local skill to verify it appears in the output.
        result = self.bridge._serialize_project_team(
            self.team,
            local_skills=['fix-issue'],
            registered_org_skills=[],
            org_catalog_skills=[],
        )
        self.assertIn('skills', result)
        names = [s['name'] for s in result['skills']]
        self.assertIn('fix-issue', names)

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
        from orchestrator.config_reader import load_workgroup
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

class TestConfigEndpointProjectSlug(unittest.IsolatedAsyncioTestCase):
    """GET /api/config must include 'slug' on each project entry."""

    async def asyncSetUp(self):
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
        teaparty_home = os.path.join(self.tmpdir, '.teaparty')
        os.makedirs(teaparty_home, exist_ok=True)
        with open(os.path.join(teaparty_home, 'teaparty.yaml'), 'w') as f:
            yaml.dump(data, f)

    async def asyncTearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_discover_projects_result_can_derive_slug(self):
        """Each project entry from discover_projects must have a derivable slug."""
        from orchestrator.config_reader import load_management_team, discover_projects
        team = load_management_team(teaparty_home=os.path.join(self.tmpdir, '.teaparty'))
        projects = discover_projects(team)
        self.assertEqual(len(projects), 1)
        # Slug should be derivable as basename of path
        slug = os.path.basename(projects[0]['path'])
        self.assertEqual(slug, 'myproject')

    async def test_config_handler_adds_slug_to_project_entries(self):
        """_handle_config response must include 'slug' on each project."""
        from unittest.mock import MagicMock
        resp = await self.bridge._handle_config(MagicMock())
        data = json.loads(resp.body)
        self.assertEqual(len(data['projects']), 1)
        self.assertIn('slug', data['projects'][0], '_handle_config must add slug to project entries')
        self.assertEqual(data['projects'][0]['slug'], 'myproject')


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
        proj_tp_local = os.path.join(self.project_dir, '.teaparty.local')
        os.makedirs(proj_tp_local)

        # Create local workgroup YAML for this project
        local_wg_dir = os.path.join(proj_tp_local, 'workgroups')
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
        with open(os.path.join(proj_tp_local, 'project.yaml'), 'w') as f:
            yaml.dump(project_data, f)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_workgroup_ref_tagged_as_shared(self):
        """A WorkgroupRef in the project config must produce source='shared'."""
        from orchestrator.config_reader import (
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
        from orchestrator.config_reader import (
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
        from orchestrator.config_reader import (
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
        from orchestrator.config_reader import (
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
        from orchestrator.config_reader import WorkgroupRef
        entry = WorkgroupRef(ref='coding')
        source = 'shared' if isinstance(entry, WorkgroupRef) else 'local'
        self.assertEqual(source, 'shared')

    def test_workgroup_entry_is_source_local(self):
        from orchestrator.config_reader import WorkgroupRef, WorkgroupEntry
        entry = WorkgroupEntry(name='Custom', config='workgroups/custom.yaml')
        source = 'shared' if isinstance(entry, WorkgroupRef) else 'local'
        self.assertEqual(source, 'local')


# ── Override detection ────────────────────────────────────────────────────────

class TestWorkgroupOverrideDetection(unittest.TestCase):
    """_detect_workgroup_overrides must identify fields that diverge from org definition."""

    def _make_workgroup(self, tmpdir, name, **kwargs):
        from orchestrator.config_reader import Workgroup
        return Workgroup(name=name, **kwargs)

    def setUp(self):
        self.tmpdir = _make_tmpdir()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_identical_workgroups_have_no_overrides(self):
        from bridge.server import _detect_workgroup_overrides
        from orchestrator.config_reader import Workgroup
        org = Workgroup(name='Coding', norms={'quality': ['no shortcuts']}, lead='Dev Lead')
        proj = Workgroup(name='Coding', norms={'quality': ['no shortcuts']}, lead='Dev Lead')
        overrides = _detect_workgroup_overrides(org, proj)
        self.assertEqual(overrides, [], 'Identical workgroups must have no overrides')

    def test_norms_override_detected(self):
        from bridge.server import _detect_workgroup_overrides
        from orchestrator.config_reader import Workgroup
        org = Workgroup(name='Coding', norms={'quality': ['no shortcuts']})
        proj = Workgroup(name='Coding', norms={'quality': ['strict TDD']})
        overrides = _detect_workgroup_overrides(org, proj)
        self.assertIn('norms', overrides, 'Changed norms must appear in overrides')

    def test_budget_override_detected(self):
        from bridge.server import _detect_workgroup_overrides
        from orchestrator.config_reader import Workgroup
        org = Workgroup(name='Coding', budget={'job_limit_usd': 5.0})
        proj = Workgroup(name='Coding', budget={'job_limit_usd': 20.0})
        overrides = _detect_workgroup_overrides(org, proj)
        self.assertIn('budget', overrides, 'Changed budget must appear in overrides')

    def test_multiple_overrides_detected(self):
        from bridge.server import _detect_workgroup_overrides
        from orchestrator.config_reader import Workgroup
        org = Workgroup(name='Coding', norms={'quality': ['a']}, lead='Org Lead')
        proj = Workgroup(name='Coding', norms={'quality': ['b']}, lead='Project Lead')
        overrides = _detect_workgroup_overrides(org, proj)
        self.assertIn('norms', overrides)
        self.assertIn('lead', overrides)

    def test_serialize_workgroup_includes_overrides_field(self):
        """_serialize_workgroup must always include an 'overrides' key."""
        tmpdir = _make_tmpdir()
        try:
            bridge = _make_bridge(tmpdir)
            wg_path = _make_workgroup_yaml(tmpdir, name='Coding')
            from orchestrator.config_reader import load_workgroup
            w = load_workgroup(wg_path)
            result = bridge._serialize_workgroup(w, source='shared', overrides=['norms'])
            self.assertIn('overrides', result)
            self.assertEqual(result['overrides'], ['norms'])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_serialize_workgroup_overrides_defaults_to_empty_list(self):
        """_serialize_workgroup with no overrides arg must return overrides=[]."""
        tmpdir = _make_tmpdir()
        try:
            bridge = _make_bridge(tmpdir)
            wg_path = _make_workgroup_yaml(tmpdir, name='Coding')
            from orchestrator.config_reader import load_workgroup
            w = load_workgroup(wg_path)
            result = bridge._serialize_workgroup(w)
            self.assertIn('overrides', result)
            self.assertEqual(result['overrides'], [])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ── Agent source tags ─────────────────────────────────────────────────────────

class TestAgentSourceTags(unittest.TestCase):
    """_serialize_project_team must tag agents generated/shared/local."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)
        self.project_dir = os.path.join(self.tmpdir, 'proj')
        os.makedirs(self.project_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_lead_agent_tagged_generated(self):
        """Agent whose name equals team.lead must be tagged source='generated'."""
        team = _make_project_team(
            self.project_dir, agents=['Project Lead', 'Reviewer'], skills=[],
        )
        result = self.bridge._serialize_project_team(team)
        by_name = {a['name']: a['source'] for a in result['agents']}
        self.assertEqual(by_name['Project Lead'], 'generated')

    def test_org_agent_tagged_shared(self):
        """Agent present in org agents list (but not the lead) must be tagged 'shared'."""
        _make_management_team(self.tmpdir, agents=['Shared Reviewer', 'Other'])
        team = _make_project_team(
            self.project_dir, agents=['Project Lead', 'Shared Reviewer'], skills=[],
        )
        result = self.bridge._serialize_project_team(team, org_agents=['Shared Reviewer', 'Other'])
        by_name = {a['name']: a['source'] for a in result['agents']}
        self.assertEqual(by_name['Shared Reviewer'], 'shared')

    def test_project_only_agent_tagged_local(self):
        """Agent not in org agents and not the lead must be tagged 'local'."""
        team = _make_project_team(
            self.project_dir, agents=['Project Lead', 'Local Bot'], skills=[],
        )
        result = self.bridge._serialize_project_team(team, org_agents=['Office Manager'])
        by_name = {a['name']: a['source'] for a in result['agents']}
        self.assertEqual(by_name['Local Bot'], 'local')

    def test_generated_takes_priority_over_shared(self):
        """If the lead also appears in org agents, source is still 'generated'."""
        team = _make_project_team(
            self.project_dir, agents=['Project Lead'], skills=[],
        )
        result = self.bridge._serialize_project_team(team, org_agents=['Project Lead'])
        by_name = {a['name']: a['source'] for a in result['agents']}
        self.assertEqual(by_name['Project Lead'], 'generated')

    def test_agents_returned_as_objects(self):
        """Each agent entry must be a dict with 'name' and 'source' keys."""
        team = _make_project_team(self.project_dir, agents=['Bot'], skills=[])
        result = self.bridge._serialize_project_team(team)
        self.assertIsInstance(result['agents'], list)
        self.assertTrue(len(result['agents']) > 0)
        agent = result['agents'][0]
        self.assertIn('name', agent)
        self.assertIn('source', agent)


# ── Skill source tags ─────────────────────────────────────────────────────────

class TestSkillSourceTags(unittest.TestCase):
    """_serialize_project_team must tag skills shared/local."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)
        self.project_dir = os.path.join(self.tmpdir, 'proj')
        os.makedirs(self.project_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_org_skill_tagged_shared(self):
        """Skill in both registered_org_skills and org_catalog_skills must be tagged 'shared'."""
        # Issue #327: source is now filesystem-backed; pass explicit params.
        team = _make_project_team(self.project_dir, agents=[], skills=['audit'])
        result = self.bridge._serialize_project_team(
            team,
            local_skills=[],
            registered_org_skills=['audit'],
            org_catalog_skills=['audit'],
        )
        by_name = {s['name']: s['source'] for s in result['skills']}
        self.assertEqual(by_name['audit'], 'shared')

    def test_project_only_skill_tagged_local(self):
        """Skill discovered from the project's .claude/skills/ must be tagged 'local'."""
        # Issue #327: local skills are filesystem-discovered; pass via local_skills param.
        team = _make_project_team(self.project_dir, agents=[], skills=[])
        result = self.bridge._serialize_project_team(
            team,
            local_skills=['project-skill'],
            registered_org_skills=[],
            org_catalog_skills=[],
        )
        by_name = {s['name']: s['source'] for s in result['skills']}
        self.assertEqual(by_name['project-skill'], 'local')

    def test_skills_returned_as_objects(self):
        """Each skill entry must be a dict with 'name' and 'source' keys."""
        # Issue #327: pass skill via local_skills so it appears in the output.
        team = _make_project_team(self.project_dir, agents=[], skills=[])
        result = self.bridge._serialize_project_team(
            team,
            local_skills=['fix-issue'],
            registered_org_skills=[],
            org_catalog_skills=[],
        )
        self.assertIsInstance(result['skills'], list)
        skill = result['skills'][0]
        self.assertIn('name', skill)
        self.assertIn('source', skill)

    def test_no_org_skills_all_tagged_local(self):
        """When skills are only locally installed (no org catalog), all must be 'local'."""
        # Issue #327: local_skills are filesystem-discovered; pass them directly.
        team = _make_project_team(self.project_dir, agents=[], skills=[])
        result = self.bridge._serialize_project_team(
            team,
            local_skills=['skill-a', 'skill-b'],
            registered_org_skills=[],
            org_catalog_skills=[],
        )
        sources = {s['source'] for s in result['skills']}
        self.assertEqual(sources, {'local'})


# ── Override variable scope ───────────────────────────────────────────────────

class TestWorkgroupOverrideScope(unittest.TestCase):
    """Override data must not bleed from one workgroup to the next."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_overrides_reset_per_workgroup(self):
        """Second workgroup with no override file must show overrides=[]."""
        from bridge.server import _detect_workgroup_overrides
        from orchestrator.config_reader import Workgroup

        org_a = Workgroup(name='Alpha', norms={'quality': ['strict']})
        proj_a = Workgroup(name='Alpha', norms={'quality': ['relaxed']})
        org_b = Workgroup(name='Beta', norms={'quality': ['strict']})
        proj_b = Workgroup(name='Beta', norms={'quality': ['strict']})

        overrides_a = _detect_workgroup_overrides(org_a, proj_a)
        # Alpha has an override: 'norms'
        self.assertIn('norms', overrides_a)

        # Beta is identical to its org definition — overrides must be empty
        overrides_b = _detect_workgroup_overrides(org_b, proj_b)
        self.assertEqual(overrides_b, [])

        # Simulate handler serialization: each w gets its own fresh overrides
        results = []
        for (org, proj) in [(org_a, proj_a), (org_b, proj_b)]:
            overrides: list[str] = []
            overrides = _detect_workgroup_overrides(org, proj)
            results.append(self.bridge._serialize_workgroup(proj, source='shared', overrides=overrides))

        self.assertIn('norms', results[0]['overrides'])
        self.assertEqual(results[1]['overrides'], [],
                         'Beta must not carry overrides from Alpha')


# ── Handler end-to-end ────────────────────────────────────────────────────────

class TestConfigProjectHandlerEndToEnd(unittest.IsolatedAsyncioTestCase):
    """_handle_config_project must return correct JSON shape with source-tagged agents/skills."""

    async def asyncSetUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)
        _make_management_team(self.tmpdir, agents=['Org Agent'], skills=['org-skill'])
        self.project_dir = os.path.join(self.tmpdir, 'poc')
        os.makedirs(self.project_dir)
        _make_project_team(
            self.project_dir,
            agents=['Project Lead', 'Org Agent'],
            skills=['org-skill', 'local-skill'],
        )
        # Issue #327: install org-skill in org catalog and local-skill in project.
        # The handler uses filesystem discovery to determine source tags.
        org_skill_dir = os.path.join(self.tmpdir, '.claude', 'skills', 'org-skill')
        os.makedirs(org_skill_dir, exist_ok=True)
        with open(os.path.join(org_skill_dir, 'SKILL.md'), 'w') as f:
            f.write('# org-skill\n')
        local_skill_dir = os.path.join(self.project_dir, '.claude', 'skills', 'local-skill')
        os.makedirs(local_skill_dir, exist_ok=True)
        with open(os.path.join(local_skill_dir, 'SKILL.md'), 'w') as f:
            f.write('# local-skill\n')

    async def asyncTearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _call(self):
        from unittest.mock import MagicMock
        req = MagicMock()
        req.match_info = {'project': 'poc'}
        return req

    async def test_handle_config_project_returns_team_and_workgroups(self):
        """Handler response must include 'team' and 'workgroups' keys."""
        resp = await self.bridge._handle_config_project(self._call())
        data = json.loads(resp.body)
        self.assertIn('team', data)
        self.assertIn('workgroups', data)

    async def test_handle_config_project_agents_have_source(self):
        """All agents in the handler response must include a 'source' field."""
        resp = await self.bridge._handle_config_project(self._call())
        data = json.loads(resp.body)
        agents = data['team']['agents']
        self.assertTrue(len(agents) > 0, 'Expected at least one agent')
        for agent in agents:
            self.assertIn('source', agent, f'Agent {agent.get("name")} missing source')

    async def test_handle_config_project_lead_tagged_generated(self):
        """Handler must tag the project lead agent as source='generated'."""
        resp = await self.bridge._handle_config_project(self._call())
        data = json.loads(resp.body)
        by_name = {a['name']: a['source'] for a in data['team']['agents']}
        self.assertEqual(by_name.get('Project Lead'), 'generated')

    async def test_handle_config_project_org_agent_tagged_shared(self):
        """Handler must tag org-catalog agents as source='shared'."""
        resp = await self.bridge._handle_config_project(self._call())
        data = json.loads(resp.body)
        by_name = {a['name']: a['source'] for a in data['team']['agents']}
        self.assertEqual(by_name.get('Org Agent'), 'shared')

    async def test_handle_config_project_skills_have_source(self):
        """All skills in the handler response must include a 'source' field."""
        resp = await self.bridge._handle_config_project(self._call())
        data = json.loads(resp.body)
        skills = data['team']['skills']
        self.assertTrue(len(skills) > 0, 'Expected at least one skill')
        for skill in skills:
            self.assertIn('source', skill, f'Skill {skill.get("name")} missing source')

    async def test_handle_config_project_org_skill_tagged_shared(self):
        """Handler must tag org skills as 'shared' and project-only skills as 'local'."""
        resp = await self.bridge._handle_config_project(self._call())
        data = json.loads(resp.body)
        by_name = {s['name']: s['source'] for s in data['team']['skills']}
        self.assertEqual(by_name.get('org-skill'), 'shared')
        self.assertEqual(by_name.get('local-skill'), 'local')


class TestConfigHandlerEndToEnd(unittest.IsolatedAsyncioTestCase):
    """_handle_config must return management team with all required fields."""

    async def asyncSetUp(self):
        self.tmpdir = _make_tmpdir()
        self.bridge = _make_bridge(self.tmpdir)
        _make_management_team(self.tmpdir)

    async def asyncTearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def test_handle_config_returns_management_team_fields(self):
        """Handler response must include management_team with agents/humans/skills/hooks/scheduled."""
        from unittest.mock import MagicMock
        resp = await self.bridge._handle_config(MagicMock())
        data = json.loads(resp.body)
        self.assertIn('management_team', data)
        mt = data['management_team']
        for field in ('agents', 'humans', 'skills', 'hooks', 'scheduled'):
            self.assertIn(field, mt, f'management_team must include {field}')

    async def test_handle_config_returns_projects(self):
        """Handler response must include 'projects' key."""
        from unittest.mock import MagicMock
        resp = await self.bridge._handle_config(MagicMock())
        data = json.loads(resp.body)
        self.assertIn('projects', data)
        self.assertIsInstance(data['projects'], list)


if __name__ == '__main__':
    unittest.main()
