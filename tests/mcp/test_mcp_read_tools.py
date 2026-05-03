"""Tests for MCP read/list tools — configuration query operations.

Layered:
  1. List tools — enumerate resources, empty and populated cases
  2. Get tools — retrieve single resources by name, including not-found
  3. Pin listing — project-scoped artifact pin queries
"""
import os
import shutil
import tempfile
import unittest

import yaml

from teaparty.mcp.server.main import (
    get_agent_handler,
    get_project_handler,
    get_skill_handler,
    get_workgroup_handler,
    list_agents_handler,
    list_hooks_handler,
    list_pins_handler,
    list_projects_handler,
    list_scheduled_tasks_handler,
    list_skills_handler,
    list_workgroups_handler,
)

import json


def _make_tmp(tc: unittest.TestCase) -> str:
    tmp = tempfile.mkdtemp(prefix='teaparty-test-')
    tc.addCleanup(shutil.rmtree, tmp, True)
    return tmp


def _write_yaml(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)


def _make_teaparty_home(tmp: str) -> str:
    """Create a minimal teaparty home with management/teaparty.yaml."""
    home = os.path.join(tmp, '.teaparty')
    _write_yaml(os.path.join(home, 'management', 'teaparty.yaml'), {
        'name': 'Management Team',
        'lead': 'office-manager',
        'projects': [],
    })
    return home


def _register_project(home: str, name: str, proj_dir: str) -> None:
    """Add a project entry to teaparty.yaml."""
    tp_path = os.path.join(home, 'management', 'teaparty.yaml')
    with open(tp_path) as f:
        data = yaml.safe_load(f) or {}
    data.setdefault('projects', []).append({
        'name': name, 'path': proj_dir,
        'config': '.teaparty/project/project.yaml',
    })
    _write_yaml(tp_path, data)


def _make_project(tmp: str, home: str, name: str) -> str:
    """Create a project directory with project.yaml and register it."""
    proj = os.path.join(tmp, name)
    os.makedirs(proj, exist_ok=True)
    _write_yaml(os.path.join(proj, '.teaparty', 'project', 'project.yaml'), {
        'name': name,
        'lead': f'{name}-lead',
        'humans': {'decider': 'alice'},
        'workgroups': [],
        'artifact_pins': [],
    })
    _register_project(home, name, proj)
    return proj


def _parse(result: str) -> dict:
    return json.loads(result)


# ── Layer 1: List tools ─────────────────────────────────────────────────────


class TestListProjects(unittest.TestCase):

    def test_empty_returns_empty_list(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        r = _parse(list_projects_handler(teaparty_home=home))
        self.assertTrue(r['success'])
        self.assertEqual(r['projects'], [])

    def test_returns_registered_projects(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        _make_project(tmp, home, 'alpha')
        _make_project(tmp, home, 'beta')
        r = _parse(list_projects_handler(teaparty_home=home))
        names = [p['name'] for p in r['projects']]
        self.assertIn('alpha', names)
        self.assertIn('beta', names)


class TestListAgents(unittest.TestCase):

    def test_empty_returns_empty_list(self):
        tmp = _make_tmp(self)
        r = _parse(list_agents_handler(project_root=tmp))
        self.assertTrue(r['success'])
        self.assertEqual(r['agents'], [])

    def test_returns_discovered_agents(self):
        tmp = _make_tmp(self)
        agents_dir = os.path.join(tmp, '.teaparty', 'management', 'agents')
        _write_file(os.path.join(agents_dir, 'coder', 'agent.md'),
                     '---\nname: coder\ndescription: writes code\nmodel: sonnet\n---\nBody')
        _write_file(os.path.join(agents_dir, 'reviewer', 'agent.md'),
                     '---\nname: reviewer\ndescription: reviews code\nmodel: opus\n---\nBody')
        r = _parse(list_agents_handler(project_root=tmp))
        names = [a['name'] for a in r['agents']]
        self.assertIn('coder', names)
        self.assertIn('reviewer', names)

    def test_includes_summary_fields(self):
        tmp = _make_tmp(self)
        agents_dir = os.path.join(tmp, '.teaparty', 'management', 'agents')
        _write_file(os.path.join(agents_dir, 'coder', 'agent.md'),
                     '---\nname: coder\ndescription: writes code\nmodel: sonnet\n---\nBody')
        r = _parse(list_agents_handler(project_root=tmp))
        agent = r['agents'][0]
        self.assertEqual(agent['description'], 'writes code')
        self.assertEqual(agent['model'], 'sonnet')

    def test_ignores_directories_without_agent_md(self):
        tmp = _make_tmp(self)
        agents_dir = os.path.join(tmp, '.teaparty', 'management', 'agents', 'empty')
        os.makedirs(agents_dir)
        r = _parse(list_agents_handler(project_root=tmp))
        self.assertEqual(r['agents'], [])


class TestListSkills(unittest.TestCase):

    def test_empty_returns_empty_list(self):
        tmp = _make_tmp(self)
        r = _parse(list_skills_handler(project_root=tmp))
        self.assertTrue(r['success'])
        self.assertEqual(r['skills'], [])

    def test_returns_discovered_skills(self):
        tmp = _make_tmp(self)
        skills_dir = os.path.join(tmp, '.teaparty', 'management', 'skills')
        _write_file(os.path.join(skills_dir, 'commit', 'SKILL.md'),
                     '---\nname: commit\ndescription: git commit\nuser-invocable: true\n---\nBody')
        r = _parse(list_skills_handler(project_root=tmp))
        self.assertEqual(len(r['skills']), 1)
        self.assertEqual(r['skills'][0]['name'], 'commit')
        self.assertTrue(r['skills'][0]['user-invocable'])


class TestListWorkgroups(unittest.TestCase):

    def test_empty_returns_empty_list(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        r = _parse(list_workgroups_handler(teaparty_home=home))
        self.assertTrue(r['success'])
        self.assertEqual(r['workgroups'], [])

    def test_returns_workgroups(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        wg_dir = os.path.join(home, 'management', 'workgroups')
        _write_yaml(os.path.join(wg_dir, 'coding.yaml'), {
            'name': 'Coding', 'description': 'writes code', 'lead': 'coding-lead',
        })
        r = _parse(list_workgroups_handler(teaparty_home=home))
        self.assertEqual(len(r['workgroups']), 1)
        self.assertEqual(r['workgroups'][0]['name'], 'Coding')
        self.assertEqual(r['workgroups'][0]['lead'], 'coding-lead')


class TestListHooks(unittest.TestCase):

    def test_empty_returns_empty_list(self):
        tmp = _make_tmp(self)
        r = _parse(list_hooks_handler(project_root=tmp))
        self.assertTrue(r['success'])
        self.assertEqual(r['hooks'], [])

    def test_returns_hooks_by_event(self):
        tmp = _make_tmp(self)
        settings_path = os.path.join(tmp, '.teaparty', 'management', 'settings.yaml')
        _write_yaml(settings_path, {
            'hooks': {
                'PreToolUse': [{'matcher': 'Edit', 'hooks': [{'type': 'command', 'command': 'echo hi'}]}],
            }
        })
        r = _parse(list_hooks_handler(project_root=tmp))
        self.assertEqual(len(r['hooks']), 1)
        self.assertEqual(r['hooks'][0]['event'], 'PreToolUse')
        self.assertEqual(r['hooks'][0]['matcher'], 'Edit')


class TestListScheduledTasks(unittest.TestCase):

    def test_empty_returns_empty_list(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        r = _parse(list_scheduled_tasks_handler(teaparty_home=home))
        self.assertTrue(r['success'])
        self.assertEqual(r['scheduled_tasks'], [])

    def test_returns_tasks(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        tp_path = os.path.join(home, 'management', 'teaparty.yaml')
        with open(tp_path) as f:
            data = yaml.safe_load(f) or {}
        data['scheduled'] = [
            {'name': 'nightly', 'schedule': '0 2 * * *', 'skill': 'backup', 'enabled': True},
        ]
        _write_yaml(tp_path, data)
        r = _parse(list_scheduled_tasks_handler(teaparty_home=home))
        self.assertEqual(len(r['scheduled_tasks']), 1)
        self.assertEqual(r['scheduled_tasks'][0]['name'], 'nightly')


# ── Layer 2: Get tools ──────────────────────────────────────────────────────


class TestGetProject(unittest.TestCase):

    def test_returns_project_details(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        _make_project(tmp, home, 'myproj')
        r = _parse(get_project_handler(name='myproj', teaparty_home=home))
        self.assertTrue(r['success'])
        self.assertEqual(r['project']['name'], 'myproj')
        self.assertEqual(r['project']['lead'], 'myproj-lead')
        self.assertIn('path', r['project'])

    def test_not_found_returns_error(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        r = _parse(get_project_handler(name='nope', teaparty_home=home))
        self.assertFalse(r['success'])

    def test_empty_name_returns_error(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        r = _parse(get_project_handler(name='', teaparty_home=home))
        self.assertFalse(r['success'])


class TestGetAgent(unittest.TestCase):

    def test_returns_full_definition(self):
        tmp = _make_tmp(self)
        agents_dir = os.path.join(tmp, '.teaparty', 'management', 'agents')
        _write_file(os.path.join(agents_dir, 'coder', 'agent.md'),
                     '---\nname: coder\ndescription: writes code\nmodel: sonnet\ntools: Read,Write\n---\nYou are a coder.')
        r = _parse(get_agent_handler(name='coder', project_root=tmp))
        self.assertTrue(r['success'])
        self.assertEqual(r['agent']['name'], 'coder')
        self.assertEqual(r['agent']['model'], 'sonnet')
        self.assertIn('You are a coder', r['agent']['body'])

    def test_not_found_returns_error(self):
        tmp = _make_tmp(self)
        r = _parse(get_agent_handler(name='nope', project_root=tmp))
        self.assertFalse(r['success'])

    def test_empty_name_returns_error(self):
        r = _parse(get_agent_handler(name=''))
        self.assertFalse(r['success'])


class TestGetSkill(unittest.TestCase):

    def test_returns_full_definition(self):
        tmp = _make_tmp(self)
        skills_dir = os.path.join(tmp, '.teaparty', 'management', 'skills')
        _write_file(os.path.join(skills_dir, 'commit', 'SKILL.md'),
                     '---\nname: commit\ndescription: git commit\nuser-invocable: true\n---\nCommit instructions.')
        r = _parse(get_skill_handler(name='commit', project_root=tmp))
        self.assertTrue(r['success'])
        self.assertEqual(r['skill']['name'], 'commit')
        self.assertIn('Commit instructions', r['skill']['body'])

    def test_not_found_returns_error(self):
        tmp = _make_tmp(self)
        r = _parse(get_skill_handler(name='nope', project_root=tmp))
        self.assertFalse(r['success'])


class TestGetWorkgroup(unittest.TestCase):

    def test_returns_full_config(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        wg_dir = os.path.join(home, 'management', 'workgroups')
        _write_yaml(os.path.join(wg_dir, 'coding.yaml'), {
            'name': 'Coding', 'description': 'writes code',
            'lead': 'coding-lead', 'agents': ['coder-1'],
            'skills': ['commit'], 'norms': {'style': ['use tabs']},
        })
        r = _parse(get_workgroup_handler(name='coding', teaparty_home=home))
        self.assertTrue(r['success'])
        self.assertEqual(r['workgroup']['name'], 'Coding')
        self.assertIn('coder-1', r['workgroup']['agents'])
        self.assertEqual(r['workgroup']['norms']['style'], ['use tabs'])

    def test_not_found_returns_error(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        r = _parse(get_workgroup_handler(name='nope', teaparty_home=home))
        self.assertFalse(r['success'])


# ── Layer 3: Pin listing ────────────────────────────────────────────────────


class TestListPins(unittest.TestCase):

    def test_empty_returns_empty_list(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        _make_project(tmp, home, 'myproj')
        r = _parse(list_pins_handler(project='myproj', teaparty_home=home))
        self.assertTrue(r['success'])
        self.assertEqual(r['pins'], [])

    def test_returns_pinned_artifacts(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        proj = _make_project(tmp, home, 'myproj')
        # Add pins directly to project.yaml
        proj_yaml = os.path.join(proj, '.teaparty', 'project', 'project.yaml')
        with open(proj_yaml) as f:
            data = yaml.safe_load(f)
        data['artifact_pins'] = [
            {'path': 'docs/design.md', 'label': 'Design doc'},
            {'path': 'tests/', 'label': 'Tests'},
        ]
        _write_yaml(proj_yaml, data)
        r = _parse(list_pins_handler(project='myproj', teaparty_home=home))
        self.assertEqual(len(r['pins']), 2)
        paths = [p['path'] for p in r['pins']]
        self.assertIn('docs/design.md', paths)
        self.assertIn('tests/', paths)

    def test_unknown_project_returns_error(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)
        r = _parse(list_pins_handler(project='nope', teaparty_home=home))
        self.assertFalse(r['success'])


if __name__ == '__main__':
    unittest.main()
