"""Tests for project lead scaffolding on project creation.

Verifies that add_project_handler and create_project_handler automatically
create agent.md and settings.yaml for the named project lead, and that the
generated files contain the canonical tool set.
"""
import json
import os
import shutil
import tempfile
import unittest

import yaml

from teaparty.mcp.tools.config_crud import (
    _PROJECT_LEAD_PERMISSIONS,
    _PROJECT_LEAD_TOOLS,
    _scaffold_project_lead,
    add_project_handler,
    create_project_handler,
)


def _make_tmp(tc: unittest.TestCase) -> str:
    tmp = tempfile.mkdtemp(prefix='teaparty-test-')
    tc.addCleanup(shutil.rmtree, tmp, True)
    return tmp


def _home(base: str) -> str:
    return os.path.join(base, '.teaparty')


def _init_home(base: str) -> str:
    """Create a minimal teaparty_home with management/teaparty.yaml."""
    home = _home(base)
    os.makedirs(os.path.join(home, 'management'), exist_ok=True)
    teaparty_yaml = os.path.join(home, 'management', 'teaparty.yaml')
    with open(teaparty_yaml, 'w') as f:
        yaml.dump({'name': 'test-org', 'projects': []}, f)
    return home


def _read_agent_md(home: str, lead_name: str) -> tuple[dict, str]:
    path = os.path.join(home, 'management', 'agents', lead_name, 'agent.md')
    with open(path) as f:
        content = f.read()
    import re
    m = re.match(r'^---\n(.*?\n)---\n(.*)', content, re.DOTALL)
    if not m:
        return {}, content
    return yaml.safe_load(m.group(1)) or {}, m.group(2)


def _read_settings(home: str, lead_name: str) -> dict:
    path = os.path.join(home, 'management', 'agents', lead_name, 'settings.yaml')
    with open(path) as f:
        return yaml.safe_load(f) or {}


class TestScaffoldProjectLead(unittest.TestCase):
    """Direct tests for _scaffold_project_lead."""

    def _make_home(self) -> str:
        base = _make_tmp(self)
        return _init_home(base)

    def test_creates_agent_md(self):
        home = self._make_home()
        _scaffold_project_lead('alpha-lead', 'alpha', '/repos/alpha', 'darrell', home)
        agent_dir = os.path.join(home, 'management', 'agents', 'alpha-lead')
        self.assertTrue(os.path.isfile(os.path.join(agent_dir, 'agent.md')))

    def test_creates_settings_yaml(self):
        home = self._make_home()
        _scaffold_project_lead('alpha-lead', 'alpha', '/repos/alpha', 'darrell', home)
        agent_dir = os.path.join(home, 'management', 'agents', 'alpha-lead')
        self.assertTrue(os.path.isfile(os.path.join(agent_dir, 'settings.yaml')))

    def test_creates_pins_yaml(self):
        home = self._make_home()
        _scaffold_project_lead('alpha-lead', 'alpha', '/repos/alpha', 'darrell', home)
        agent_dir = os.path.join(home, 'management', 'agents', 'alpha-lead')
        self.assertTrue(os.path.isfile(os.path.join(agent_dir, 'pins.yaml')))

    def test_agent_md_has_required_tools(self):
        home = self._make_home()
        _scaffold_project_lead('alpha-lead', 'alpha', '/repos/alpha', 'darrell', home)
        fm, _ = _read_agent_md(home, 'alpha-lead')
        tools_str = fm.get('tools', '')
        required = [
            'Read', 'Glob', 'Grep', 'Bash',
            'mcp__teaparty-config__Send',
            'mcp__teaparty-config__ProjectStatus',
            'mcp__teaparty-config__ListAgents',
            'mcp__teaparty-config__ListPins',
            'mcp__teaparty-config__ListHooks',
            'mcp__teaparty-config__ListScheduledTasks',
            'mcp__teaparty-config__ListTeamMembers',
            'mcp__teaparty-config__PinArtifact',
            'mcp__teaparty-config__UnpinArtifact',
            'mcp__teaparty-config__WithdrawSession',
        ]
        for tool in required:
            self.assertIn(tool, tools_str, f'Missing tool: {tool}')

    def test_settings_yaml_has_required_permissions(self):
        home = self._make_home()
        _scaffold_project_lead('alpha-lead', 'alpha', '/repos/alpha', 'darrell', home)
        settings = _read_settings(home, 'alpha-lead')
        allowed = settings.get('permissions', {}).get('allow', [])
        for tool in _PROJECT_LEAD_PERMISSIONS:
            self.assertIn(tool, allowed, f'Missing permission: {tool}')

    def test_agent_md_frontmatter_fields(self):
        home = self._make_home()
        _scaffold_project_lead('beta-lead', 'beta', '/repos/beta', 'alice', home)
        fm, _ = _read_agent_md(home, 'beta-lead')
        self.assertEqual(fm['name'], 'beta-lead')
        self.assertEqual(fm['model'], 'sonnet')
        self.assertEqual(fm['maxTurns'], 30)
        self.assertIn('beta', fm['description'])

    def test_agent_md_body_contains_project_path(self):
        home = self._make_home()
        _scaffold_project_lead('beta-lead', 'beta', '/repos/beta', 'alice', home)
        _, body = _read_agent_md(home, 'beta-lead')
        self.assertIn('/repos/beta', body)

    def test_non_destructive_agent_md(self):
        """Existing agent.md is not overwritten."""
        home = self._make_home()
        agent_dir = os.path.join(home, 'management', 'agents', 'gamma-lead')
        os.makedirs(agent_dir, exist_ok=True)
        sentinel = '# sentinel content\n'
        with open(os.path.join(agent_dir, 'agent.md'), 'w') as f:
            f.write(sentinel)
        _scaffold_project_lead('gamma-lead', 'gamma', '/repos/gamma', 'bob', home)
        with open(os.path.join(agent_dir, 'agent.md')) as f:
            self.assertEqual(f.read(), sentinel)

    def test_non_destructive_settings_yaml(self):
        """Existing settings.yaml is not overwritten."""
        home = self._make_home()
        agent_dir = os.path.join(home, 'management', 'agents', 'gamma-lead')
        os.makedirs(agent_dir, exist_ok=True)
        sentinel = {'custom': True}
        with open(os.path.join(agent_dir, 'settings.yaml'), 'w') as f:
            yaml.dump(sentinel, f)
        _scaffold_project_lead('gamma-lead', 'gamma', '/repos/gamma', 'bob', home)
        with open(os.path.join(agent_dir, 'settings.yaml')) as f:
            self.assertEqual(yaml.safe_load(f), sentinel)


class TestAddProjectHandlerScaffoldsLead(unittest.TestCase):
    """add_project_handler creates the project lead when lead is specified."""

    def _make_env(self) -> tuple[str, str]:
        """Return (project_path, teaparty_home) in a temp dir."""
        base = _make_tmp(self)
        project_path = os.path.join(base, 'myproject')
        os.makedirs(project_path)
        home = _init_home(base)
        return project_path, home

    def test_lead_agent_md_created(self):
        project_path, home = self._make_env()
        result = json.loads(add_project_handler(
            name='myproject',
            path=project_path,
            lead='myproject-lead',
            decider='darrell',
            teaparty_home=home,
        ))
        self.assertTrue(result.get('success'), result)
        agent_md = os.path.join(home, 'management', 'agents', 'myproject-lead', 'agent.md')
        self.assertTrue(os.path.isfile(agent_md))

    def test_lead_settings_yaml_created(self):
        project_path, home = self._make_env()
        add_project_handler(
            name='myproject',
            path=project_path,
            lead='myproject-lead',
            decider='darrell',
            teaparty_home=home,
        )
        settings = os.path.join(home, 'management', 'agents', 'myproject-lead', 'settings.yaml')
        self.assertTrue(os.path.isfile(settings))

    def test_no_lead_no_agent_created(self):
        project_path, home = self._make_env()
        add_project_handler(
            name='myproject',
            path=project_path,
            teaparty_home=home,
        )
        agents_dir = os.path.join(home, 'management', 'agents')
        self.assertFalse(os.path.isdir(agents_dir))


class TestCreateProjectHandlerScaffoldsLead(unittest.TestCase):
    """create_project_handler creates the project lead when lead is specified."""

    def _make_env(self) -> tuple[str, str]:
        base = _make_tmp(self)
        project_path = os.path.join(base, 'newproject')
        home = _init_home(base)
        return project_path, home

    def test_lead_agent_md_created(self):
        project_path, home = self._make_env()
        result = json.loads(create_project_handler(
            name='newproject',
            path=project_path,
            lead='newproject-lead',
            decider='darrell',
            teaparty_home=home,
        ))
        self.assertTrue(result.get('success'), result)
        agent_md = os.path.join(home, 'management', 'agents', 'newproject-lead', 'agent.md')
        self.assertTrue(os.path.isfile(agent_md))

    def test_lead_settings_yaml_permissions(self):
        project_path, home = self._make_env()
        create_project_handler(
            name='newproject',
            path=project_path,
            lead='newproject-lead',
            decider='darrell',
            teaparty_home=home,
        )
        settings = _read_settings(home, 'newproject-lead')
        allowed = settings.get('permissions', {}).get('allow', [])
        self.assertIn('mcp__teaparty-config__WithdrawSession', allowed)
        self.assertIn('mcp__teaparty-config__PinArtifact', allowed)
        self.assertIn('mcp__teaparty-config__ListScheduledTasks', allowed)
