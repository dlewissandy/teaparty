"""Tests for orchestrator/config_reader.py — configuration loading and management.

Layered:
  1. Path helpers — pure functions, no I/O
  2. Data loading — round-trip YAML through load functions
  3. Mutation — add/remove/toggle operations on real temp directories
  4. Resolution — norms, budgets, workgroups, catalogs
"""
import os
import shutil
import tempfile
import unittest

import yaml

from teaparty.config.config_reader import (
    Human,
    ManagementTeam,
    MergedCatalog,
    ProjectTeam,
    ScheduledTask,
    Workgroup,
    WorkgroupEntry,
    WorkgroupRef,
    add_project,
    apply_budget_precedence,
    apply_norms_precedence,
    create_project,
    default_teaparty_home,
    discover_agents,
    discover_hooks,
    discover_skills,
    discover_workgroups,
    external_projects_path,
    format_norms,
    load_management_team,
    load_project_team,
    load_workgroup,
    management_dir,
    management_workgroups_dir,
    merge_catalog,
    project_agents_dir,
    project_config_path,
    project_teaparty_dir,
    read_pins,
    remove_project,
    resolve_budget,
    resolve_norms,
    resolve_workgroups,
    toggle_project_membership,
    write_pins,
)


def _make_tmp(tc: unittest.TestCase) -> str:
    tmp = tempfile.mkdtemp(prefix='teaparty-test-')
    tc.addCleanup(shutil.rmtree, tmp, True)
    return tmp


def _write_yaml(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _make_teaparty_home(tmp: str) -> str:
    """Create a minimal teaparty home with management/teaparty.yaml."""
    home = os.path.join(tmp, '.teaparty')
    mgmt = os.path.join(home, 'management')
    _write_yaml(os.path.join(mgmt, 'teaparty.yaml'), {
        'name': 'Management Team',
        'lead': 'office-manager',
        'humans': {'decider': 'alice'},
        'projects': [],
        'members': {
            'agents': ['office-manager'],
            'skills': [],
            'workgroups': [],
        },
    })
    return home


def _make_project(tmp: str, name: str, lead: str = 'proj-lead',
                  decider: str = 'alice') -> str:
    """Create a project directory with .teaparty/project/project.yaml."""
    proj = os.path.join(tmp, name)
    os.makedirs(proj, exist_ok=True)
    tp = os.path.join(proj, '.teaparty', 'project')
    _write_yaml(os.path.join(tp, 'project.yaml'), {
        'name': name,
        'description': f'{name} project',
        'lead': lead,
        'humans': {'decider': decider},
        'workgroups': [],
        'members': {'workgroups': []},
        'artifact_pins': [],
    })
    return proj


# ── Layer 1: Path helpers ──────────────��─────────────────────────────────────

class TestPathHelpers(unittest.TestCase):
    """Path helpers must return deterministic paths from inputs."""

    def test_project_teaparty_dir(self):
        self.assertEqual(
            project_teaparty_dir('/foo/bar'),
            '/foo/bar/.teaparty/project',
        )

    def test_project_agents_dir(self):
        self.assertEqual(
            project_agents_dir('/foo/bar'),
            '/foo/bar/.teaparty/project/agents',
        )

    def test_project_config_path(self):
        self.assertEqual(
            project_config_path('/foo/bar'),
            '/foo/bar/.teaparty/project/project.yaml',
        )

    def test_management_dir(self):
        self.assertEqual(
            management_dir('/home/user/.teaparty'),
            '/home/user/.teaparty/management',
        )

    def test_external_projects_path(self):
        self.assertEqual(
            external_projects_path('/home/user/.teaparty'),
            '/home/user/.teaparty/management/external-projects.yaml',
        )


# ── Layer 2: Data loading ────────��───────────────────────────────────────────

class TestLoadManagementTeam(unittest.TestCase):
    """load_management_team must parse teaparty.yaml into ManagementTeam."""

    def test_loads_basic_management_team(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        team = load_management_team(teaparty_home=home)
        self.assertIsInstance(team, ManagementTeam)
        self.assertEqual(team.name, 'Management Team')
        self.assertEqual(team.lead, 'office-manager')

    def test_humans_parsed_as_human_objects(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        team = load_management_team(teaparty_home=home)
        self.assertEqual(len(team.humans), 1)
        self.assertIsInstance(team.humans[0], Human)
        self.assertEqual(team.humans[0].name, 'alice')
        self.assertEqual(team.humans[0].role, 'decider')

    def test_members_agents_populated(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        team = load_management_team(teaparty_home=home)
        self.assertIn('office-manager', team.members_agents)

    def test_merges_external_projects(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = _make_project(tmp, 'ext-proj')
        ext_path = external_projects_path(home)
        _write_yaml(ext_path, [{'name': 'ext-proj', 'path': proj,
                                'config': '.teaparty/project/project.yaml'}])
        team = load_management_team(teaparty_home=home)
        names = [p['name'] for p in team.projects]
        self.assertIn('ext-proj', names)


class TestLoadProjectTeam(unittest.TestCase):
    """load_project_team must parse project.yaml into ProjectTeam."""

    def test_loads_basic_project(self):
        tmp = _make_tmp(self)
        proj = _make_project(tmp, 'myproj')
        team = load_project_team(proj)
        self.assertIsInstance(team, ProjectTeam)
        self.assertEqual(team.name, 'myproj')
        self.assertEqual(team.lead, 'proj-lead')

    def test_humans_parsed(self):
        tmp = _make_tmp(self)
        proj = _make_project(tmp, 'myproj')
        team = load_project_team(proj)
        self.assertTrue(len(team.humans) >= 1)
        deciders = [h for h in team.humans if h.role == 'decider']
        self.assertEqual(len(deciders), 1)
        self.assertEqual(deciders[0].name, 'alice')

    def test_missing_config_raises(self):
        tmp = _make_tmp(self)
        proj = os.path.join(tmp, 'empty')
        os.makedirs(proj)
        with self.assertRaises(FileNotFoundError):
            load_project_team(proj)


class TestLoadWorkgroup(unittest.TestCase):
    """load_workgroup must parse a workgroup YAML into Workgroup."""

    def test_loads_basic_workgroup(self):
        tmp = _make_tmp(self)
        wg_path = os.path.join(tmp, 'coding.yaml')
        _write_yaml(wg_path, {
            'name': 'Coding',
            'description': 'writes code',
            'lead': 'coding-lead',
            'members': {'agents': ['coder-1', 'coder-2']},
        })
        wg = load_workgroup(wg_path)
        self.assertIsInstance(wg, Workgroup)
        self.assertEqual(wg.name, 'Coding')
        self.assertEqual(wg.lead, 'coding-lead')
        self.assertIn('coder-1', wg.members_agents)
        self.assertIn('coder-2', wg.members_agents)


# ── Layer 3: Mutation operations ─────────────────────────────────────────────

class TestAddProject(unittest.TestCase):
    """add_project must register an existing directory."""

    def test_adds_to_external_projects(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'newproj')
        os.makedirs(proj)
        team = add_project('newproj', proj, teaparty_home=home,
                           lead='np-lead', decider='alice')
        names = [p['name'] for p in team.projects]
        self.assertIn('newproj', names)

    def test_scaffolds_project_yaml(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'newproj')
        os.makedirs(proj)
        add_project('newproj', proj, teaparty_home=home)
        self.assertTrue(os.path.exists(project_config_path(proj)))

    def test_ensures_directory_structure(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'newproj')
        os.makedirs(proj)
        add_project('newproj', proj, teaparty_home=home)
        self.assertTrue(os.path.isdir(os.path.join(proj, '.claude')))
        self.assertTrue(os.path.isdir(os.path.join(proj, '.teaparty', 'project', 'agents')))

    def test_duplicate_name_raises(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'dup')
        os.makedirs(proj)
        add_project('dup', proj, teaparty_home=home)
        proj2 = os.path.join(tmp, 'dup2')
        os.makedirs(proj2)
        with self.assertRaises(ValueError):
            add_project('dup', proj2, teaparty_home=home)

    def test_nonexistent_path_raises(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        with self.assertRaises(ValueError):
            add_project('ghost', '/nonexistent/path', teaparty_home=home)


class TestCreateProject(unittest.TestCase):
    """create_project must scaffold a new project directory."""

    def test_creates_directory_and_git_init(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'brand-new')
        create_project('brand-new', proj, teaparty_home=home,
                       lead='bn-lead', decider='alice')
        self.assertTrue(os.path.isdir(proj))
        self.assertTrue(os.path.isdir(os.path.join(proj, '.git')))
        self.assertTrue(os.path.isdir(os.path.join(proj, '.claude')))
        self.assertTrue(os.path.exists(project_config_path(proj)))

    def test_existing_directory_raises(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'exists')
        os.makedirs(proj)
        with self.assertRaises(ValueError):
            create_project('exists', proj, teaparty_home=home)


class TestRemoveProject(unittest.TestCase):
    """remove_project must deregister without deleting the directory."""

    def test_removes_from_registry(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'removeme')
        os.makedirs(proj)
        add_project('removeme', proj, teaparty_home=home)
        team = remove_project('removeme', teaparty_home=home)
        names = [p['name'] for p in team.projects]
        self.assertNotIn('removeme', names)

    def test_directory_survives(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = os.path.join(tmp, 'keepdir')
        os.makedirs(proj)
        add_project('keepdir', proj, teaparty_home=home)
        remove_project('keepdir', teaparty_home=home)
        self.assertTrue(os.path.isdir(proj))

    def test_unknown_project_raises(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        with self.assertRaises(ValueError):
            remove_project('nope', teaparty_home=home)

    def test_teaparty_project_protected(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        with self.assertRaises(ValueError):
            remove_project('teaparty', teaparty_home=home)

    def test_teaparty_project_protected_case_insensitive(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        for name in ('TeaParty', 'TEAPARTY', 'Teaparty'):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    remove_project(name, teaparty_home=home)


# ── Layer 4: Resolution ─────────────���────────────────────────────────────────

class TestNormsResolution(unittest.TestCase):
    """Norms must follow category-level precedence: org < workgroup < project."""

    def test_higher_level_replaces_category(self):
        org = {'style': ['use tabs']}
        wg = {'style': ['use spaces']}
        merged = apply_norms_precedence(org, wg)
        self.assertEqual(merged['style'], ['use spaces'])

    def test_disjoint_categories_merge(self):
        org = {'style': ['use tabs']}
        wg = {'testing': ['use mocks']}
        merged = apply_norms_precedence(org, wg)
        self.assertIn('style', merged)
        self.assertIn('testing', merged)

    def test_format_norms_empty(self):
        self.assertEqual(format_norms({}), '')

    def test_format_norms_produces_text(self):
        text = format_norms({'style': ['be concise', 'no emojis']})
        self.assertIn('concise', text)
        self.assertIn('emojis', text)

    def test_resolve_norms_integration(self):
        result = resolve_norms(
            org_norms={'style': ['org rule']},
            project_norms={'style': ['project rule']},
        )
        self.assertIn('project rule', result)
        self.assertNotIn('org rule', result)


class TestBudgetResolution(unittest.TestCase):
    """Budgets must follow key-level precedence: org < workgroup < project."""

    def test_higher_level_overrides_key(self):
        org = {'max_turns': 10.0}
        wg = {'max_turns': 5.0}
        merged = apply_budget_precedence(org, wg)
        self.assertEqual(merged['max_turns'], 5.0)

    def test_disjoint_keys_merge(self):
        org = {'max_turns': 10.0}
        wg = {'max_cost': 1.0}
        merged = apply_budget_precedence(org, wg)
        self.assertEqual(merged['max_turns'], 10.0)
        self.assertEqual(merged['max_cost'], 1.0)


class TestPins(unittest.TestCase):
    """Pins YAML round-trips correctly."""

    def test_read_empty_returns_empty_list(self):
        tmp = _make_tmp(self)
        self.assertEqual(read_pins(tmp), [])

    def test_write_then_read_roundtrip(self):
        tmp = _make_tmp(self)
        pins = [{'path': '/foo/bar.md', 'label': 'Design doc'}]
        write_pins(tmp, pins)
        loaded = read_pins(tmp)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]['path'], '/foo/bar.md')
        self.assertEqual(loaded[0]['label'], 'Design doc')


class TestDiscovery(unittest.TestCase):
    """discover_agents and discover_skills must scan directories."""

    def test_discover_agents(self):
        tmp = _make_tmp(self)
        agent_dir = os.path.join(tmp, 'agents', 'my-agent')
        os.makedirs(agent_dir)
        with open(os.path.join(agent_dir, 'agent.md'), 'w') as f:
            f.write('# My Agent\n')
        agents = discover_agents(os.path.join(tmp, 'agents'))
        self.assertIn('my-agent', agents)

    def test_discover_skills(self):
        tmp = _make_tmp(self)
        skill_dir = os.path.join(tmp, 'skills', 'my-skill')
        os.makedirs(skill_dir)
        with open(os.path.join(skill_dir, 'SKILL.md'), 'w') as f:
            f.write('# My Skill\n')
        skills = discover_skills(os.path.join(tmp, 'skills'))
        self.assertIn('my-skill', skills)

    def test_discover_ignores_non_matching(self):
        tmp = _make_tmp(self)
        agents_dir = os.path.join(tmp, 'agents')
        # Directory without agent.md should not be discovered
        os.makedirs(os.path.join(agents_dir, 'empty-dir'))
        agents = discover_agents(agents_dir)
        self.assertEqual(agents, [])

    def test_discover_workgroups(self):
        tmp = _make_tmp(self)
        wg_dir = os.path.join(tmp, 'workgroups')
        os.makedirs(wg_dir)
        for name in ['coding', 'research']:
            with open(os.path.join(wg_dir, f'{name}.yaml'), 'w') as f:
                yaml.dump({'name': name.capitalize()}, f)
        # Non-yaml file should be ignored
        with open(os.path.join(wg_dir, 'NORMS-coding.md'), 'w') as f:
            f.write('norms')
        result = discover_workgroups(wg_dir)
        self.assertIn('coding', result)
        self.assertIn('research', result)
        self.assertNotIn('NORMS-coding', result)

    def test_discover_workgroups_missing_dir(self):
        result = discover_workgroups('/nonexistent/path')
        self.assertEqual(result, [])


class TestToggleProjectWorkgroup(unittest.TestCase):
    """toggle_project_membership for shared workgroups must manage both
    the workgroups: refs list and members.workgroups."""

    def _make_home_with_wg(self, tmp: str, wg_name: str) -> str:
        """Create a teaparty home with one management catalog workgroup."""
        home = _make_teaparty_home(tmp)
        wg_dir = management_workgroups_dir(home)
        os.makedirs(wg_dir, exist_ok=True)
        with open(os.path.join(wg_dir, f'{wg_name}.yaml'), 'w') as f:
            yaml.dump({'name': wg_name}, f)
        return home

    def _read_project_yaml(self, proj: str) -> dict:
        path = project_config_path(proj)
        with open(path) as f:
            return yaml.safe_load(f) or {}

    def test_activate_shared_adds_ref_and_member(self):
        tmp = _make_tmp(self)
        home = self._make_home_with_wg(tmp, 'coding')
        proj = _make_project(tmp, 'myproject')

        toggle_project_membership(proj, 'workgroup', 'coding', True, teaparty_home=home)

        data = self._read_project_yaml(proj)
        refs = data.get('workgroups') or []
        self.assertTrue(any(e.get('ref') == 'coding' for e in refs),
                        'WorkgroupRef should be added to workgroups:')
        members = (data.get('members') or {}).get('workgroups') or []
        self.assertIn('coding', members)

    def test_deactivate_shared_removes_ref_and_member(self):
        tmp = _make_tmp(self)
        home = self._make_home_with_wg(tmp, 'coding')
        proj = _make_project(tmp, 'myproject')

        # Activate first, then deactivate
        toggle_project_membership(proj, 'workgroup', 'coding', True, teaparty_home=home)
        toggle_project_membership(proj, 'workgroup', 'coding', False, teaparty_home=home)

        data = self._read_project_yaml(proj)
        refs = data.get('workgroups') or []
        self.assertFalse(any(e.get('ref') == 'coding' for e in refs),
                         'WorkgroupRef should be removed from workgroups:')
        members = (data.get('members') or {}).get('workgroups') or []
        self.assertNotIn('coding', members)

    def test_activate_idempotent(self):
        tmp = _make_tmp(self)
        home = self._make_home_with_wg(tmp, 'coding')
        proj = _make_project(tmp, 'myproject')

        toggle_project_membership(proj, 'workgroup', 'coding', True, teaparty_home=home)
        toggle_project_membership(proj, 'workgroup', 'coding', True, teaparty_home=home)

        data = self._read_project_yaml(proj)
        refs = [e for e in (data.get('workgroups') or []) if e.get('ref') == 'coding']
        self.assertEqual(len(refs), 1, 'WorkgroupRef must not be duplicated')
        members = (data.get('members') or {}).get('workgroups') or []
        self.assertEqual(members.count('coding'), 1, 'members entry must not be duplicated')

    def test_local_workgroup_ref_not_touched(self):
        """Toggling a local workgroup (not in org catalog) only manages members."""
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = _make_project(tmp, 'myproject')

        # Seed a local WorkgroupEntry (no yaml in management catalog)
        yaml_path = project_config_path(proj)
        with open(yaml_path) as f:
            data = yaml.safe_load(f) or {}
        data['workgroups'] = [{'name': 'LocalWG', 'config': 'workgroups/local.yaml'}]
        data.setdefault('members', {})['workgroups'] = []
        with open(yaml_path, 'w') as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

        toggle_project_membership(proj, 'workgroup', 'LocalWG', True, teaparty_home=home)

        data = self._read_project_yaml(proj)
        refs = data.get('workgroups') or []
        # The local entry must remain, no ref added
        self.assertEqual(len(refs), 1)
        self.assertIn('name', refs[0])
        members = (data.get('members') or {}).get('workgroups') or []
        self.assertIn('LocalWG', members)


if __name__ == '__main__':
    unittest.main()
