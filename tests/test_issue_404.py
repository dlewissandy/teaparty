"""Tests for issue #404: OM project creation capability.

Spec:
1. ManagementTeam.allowed_project_roots loads from teaparty.yaml.
2. add_project and create_project validate paths against allowed_project_roots.
3. Empty allowed_project_roots means no restriction (permissive mode).
4. project-specialist agent definition includes CreateProject and AddProject tools.
5. create-project and add-project skills list the corresponding MCP tools.

Dimensions covered:
- allowed_project_roots: empty/not configured vs. single root vs. multiple roots
- path: within root vs. outside root vs. on boundary
- operation: add_project vs. create_project
- agent/skill config: structural assertions on agent.md and SKILL.md files
"""
import os
import shutil
import tempfile
import unittest

import yaml

from teaparty.config.config_reader import (
    ManagementTeam,
    add_project,
    create_project,
    load_management_team,
)


def _make_tmp(tc: unittest.TestCase) -> str:
    tmp = tempfile.mkdtemp(prefix='teaparty-test-404-')
    tc.addCleanup(shutil.rmtree, tmp, True)
    return tmp


def _make_teaparty_home(tmp: str, allowed_project_roots: list | None = None) -> str:
    """Create a minimal teaparty home, optionally with allowed_project_roots."""
    home = os.path.join(tmp, '.teaparty')
    mgmt = os.path.join(home, 'management')
    data: dict = {
        'name': 'Management Team',
        'lead': 'office-manager',
        'humans': {'decider': 'alice'},
        'projects': [],
        'members': {
            'agents': ['office-manager'],
            'skills': [],
            'workgroups': [],
        },
    }
    if allowed_project_roots is not None:
        data['allowed_project_roots'] = allowed_project_roots
    os.makedirs(mgmt, exist_ok=True)
    with open(os.path.join(mgmt, 'teaparty.yaml'), 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    return home


def _project_root() -> str:
    """Return the project root (two levels above this file)."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── Layer 1: allowed_project_roots config loading ────────────────────────────

class TestAllowedProjectRootsLoading(unittest.TestCase):
    """ManagementTeam must expose allowed_project_roots from teaparty.yaml."""

    def test_allowed_roots_absent_defaults_to_empty_list(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp)  # no allowed_project_roots key
        team = load_management_team(teaparty_home=home)
        self.assertIsInstance(
            team.allowed_project_roots, list,
            'ManagementTeam.allowed_project_roots must be a list when key absent',
        )
        self.assertEqual(
            team.allowed_project_roots, [],
            'allowed_project_roots must default to [] when absent from teaparty.yaml',
        )

    def test_single_allowed_root_loads(self):
        tmp = _make_tmp(self)
        home = _make_teaparty_home(tmp, allowed_project_roots=['/home/user/projects'])
        team = load_management_team(teaparty_home=home)
        self.assertEqual(
            team.allowed_project_roots, ['/home/user/projects'],
            'allowed_project_roots must load the configured list verbatim',
        )

    def test_multiple_allowed_roots_load(self):
        tmp = _make_tmp(self)
        roots = ['/home/user/projects', '/workspace', '/tmp/sandbox']
        home = _make_teaparty_home(tmp, allowed_project_roots=roots)
        team = load_management_team(teaparty_home=home)
        self.assertEqual(
            team.allowed_project_roots, roots,
            'all configured allowed_project_roots must be loaded',
        )


# ── Layer 2: add_project path sandboxing ─────────────────────────────────────

class TestAddProjectAllowedRoots(unittest.TestCase):
    """add_project must enforce allowed_project_roots when configured."""

    def test_path_outside_allowed_root_raises(self):
        tmp = _make_tmp(self)
        root = os.path.join(tmp, 'allowed')
        outside = os.path.join(tmp, 'outside', 'proj')
        os.makedirs(outside)
        home = _make_teaparty_home(tmp, allowed_project_roots=[root])
        with self.assertRaises(ValueError) as ctx:
            add_project('proj', outside, teaparty_home=home)
        msg = str(ctx.exception)
        self.assertIn(
            'allowed', msg.lower(),
            'ValueError must mention allowed roots, not just "invalid path"',
        )
        self.assertIn(
            os.path.realpath(outside), msg,
            'ValueError must name the disallowed path so the operator knows what was rejected',
        )

    def test_path_within_allowed_root_succeeds(self):
        tmp = _make_tmp(self)
        root = tmp  # tmp is the allowed root
        proj = os.path.join(tmp, 'myproject')
        os.makedirs(proj)
        home = _make_teaparty_home(tmp, allowed_project_roots=[root])
        team = add_project('myproject', proj, teaparty_home=home)
        names = [p['name'] for p in team.projects]
        self.assertIn(
            'myproject', names,
            'add_project must succeed when path is within an allowed root',
        )

    def test_empty_allowed_roots_is_permissive(self):
        tmp = _make_tmp(self)
        proj = os.path.join(tmp, 'anywhere')
        os.makedirs(proj)
        home = _make_teaparty_home(tmp, allowed_project_roots=[])
        team = add_project('anywhere', proj, teaparty_home=home)
        names = [p['name'] for p in team.projects]
        self.assertIn(
            'anywhere', names,
            'add_project must be permissive when allowed_project_roots is empty',
        )

    def test_absent_allowed_roots_is_permissive(self):
        tmp = _make_tmp(self)
        proj = os.path.join(tmp, 'unconstrained')
        os.makedirs(proj)
        home = _make_teaparty_home(tmp)  # no allowed_project_roots key
        team = add_project('unconstrained', proj, teaparty_home=home)
        names = [p['name'] for p in team.projects]
        self.assertIn(
            'unconstrained', names,
            'add_project must be permissive when allowed_project_roots key is absent',
        )

    def test_path_in_second_of_multiple_roots_succeeds(self):
        tmp = _make_tmp(self)
        root1 = os.path.join(tmp, 'root1')
        root2 = os.path.join(tmp, 'root2')
        proj = os.path.join(root2, 'myproject')
        os.makedirs(proj)
        home = _make_teaparty_home(tmp, allowed_project_roots=[root1, root2])
        team = add_project('myproject', proj, teaparty_home=home)
        names = [p['name'] for p in team.projects]
        self.assertIn(
            'myproject', names,
            'add_project must succeed when path falls under any of multiple allowed roots',
        )

    def test_path_outside_all_roots_raises(self):
        tmp = _make_tmp(self)
        root1 = os.path.join(tmp, 'root1')
        root2 = os.path.join(tmp, 'root2')
        outside = os.path.join(tmp, 'outside', 'proj')
        os.makedirs(outside)
        home = _make_teaparty_home(tmp, allowed_project_roots=[root1, root2])
        with self.assertRaises(ValueError) as ctx:
            add_project('outside', outside, teaparty_home=home)
        msg = str(ctx.exception)
        self.assertIn(
            'allowed', msg.lower(),
            'ValueError must mention allowed roots when path is outside all roots',
        )
        self.assertIn(
            os.path.realpath(outside), msg,
            'ValueError must name the disallowed path so the operator knows what was rejected',
        )


# ── Layer 3: create_project path sandboxing ──────────────────────────────────

class TestCreateProjectAllowedRoots(unittest.TestCase):
    """create_project must enforce allowed_project_roots when configured."""

    def test_path_outside_allowed_root_raises(self):
        tmp = _make_tmp(self)
        root = os.path.join(tmp, 'allowed')
        outside = os.path.join(tmp, 'outside', 'brand-new')
        os.makedirs(os.path.dirname(outside))  # parent must exist but not 'brand-new'
        home = _make_teaparty_home(tmp, allowed_project_roots=[root])
        with self.assertRaises(ValueError) as ctx:
            create_project('brand-new', outside, teaparty_home=home)
        msg = str(ctx.exception)
        self.assertIn(
            'allowed', msg.lower(),
            'ValueError must mention allowed roots when create path is outside allowed roots',
        )
        self.assertIn(
            os.path.realpath(outside), msg,
            'ValueError must name the disallowed path so the operator knows what was rejected',
        )

    def test_path_within_allowed_root_succeeds(self):
        tmp = _make_tmp(self)
        root = tmp
        proj = os.path.join(tmp, 'brand-new')
        home = _make_teaparty_home(tmp, allowed_project_roots=[root])
        team = create_project('brand-new', proj, teaparty_home=home)
        names = [p['name'] for p in team.projects]
        self.assertIn(
            'brand-new', names,
            'create_project must succeed when path is within an allowed root',
        )

    def test_empty_allowed_roots_is_permissive(self):
        tmp = _make_tmp(self)
        proj = os.path.join(tmp, 'anywhere-new')
        home = _make_teaparty_home(tmp, allowed_project_roots=[])
        team = create_project('anywhere-new', proj, teaparty_home=home)
        names = [p['name'] for p in team.projects]
        self.assertIn(
            'anywhere-new', names,
            'create_project must be permissive when allowed_project_roots is empty',
        )

    def test_absent_allowed_roots_is_permissive(self):
        tmp = _make_tmp(self)
        proj = os.path.join(tmp, 'unconstrained-new')
        home = _make_teaparty_home(tmp)  # no allowed_project_roots key
        team = create_project('unconstrained-new', proj, teaparty_home=home)
        names = [p['name'] for p in team.projects]
        self.assertIn(
            'unconstrained-new', names,
            'create_project must be permissive when allowed_project_roots key is absent',
        )


# ── Layer 4: Agent and skill configuration ───────────────────────────────────

class TestProjectSpecialistAgentConfig(unittest.TestCase):
    """project-specialist agent must have CreateProject and AddProject in its tools."""

    def _agent_path(self) -> str:
        root = _project_root()
        return os.path.join(root, '.teaparty', 'management', 'agents',
                            'project-specialist', 'agent.md')

    def _parse_tools(self) -> list[str]:
        path = self._agent_path()
        with open(path) as f:
            content = f.read()
        # Extract YAML frontmatter between --- delimiters
        parts = content.split('---')
        fm = yaml.safe_load(parts[1])
        tools_str = fm.get('tools', '')
        return [t.strip() for t in tools_str.split(',') if t.strip()]

    def test_agent_file_exists(self):
        self.assertTrue(
            os.path.isfile(self._agent_path()),
            'project-specialist/agent.md must exist',
        )

    def test_create_project_tool_listed(self):
        tools = self._parse_tools()
        self.assertIn(
            'mcp__teaparty-config__CreateProject', tools,
            'project-specialist must list mcp__teaparty-config__CreateProject in tools '
            f'(current tools: {tools})',
        )

    def test_add_project_tool_listed(self):
        tools = self._parse_tools()
        self.assertIn(
            'mcp__teaparty-config__AddProject', tools,
            'project-specialist must list mcp__teaparty-config__AddProject in tools '
            f'(current tools: {tools})',
        )

    def _parse_skills(self) -> list[str]:
        path = self._agent_path()
        with open(path) as f:
            content = f.read()
        parts = content.split('---')
        fm = yaml.safe_load(parts[1])
        return fm.get('skills') or []

    def test_add_project_skill_listed(self):
        skills = self._parse_skills()
        self.assertIn(
            'add-project', skills,
            'project-specialist must list add-project in skills frontmatter '
            f'(current skills: {skills})',
        )

    def test_create_project_skill_listed(self):
        skills = self._parse_skills()
        self.assertIn(
            'create-project', skills,
            'project-specialist must list create-project in skills frontmatter '
            f'(current skills: {skills})',
        )


class TestOfficeManagerAgentConfig(unittest.TestCase):
    """office-manager agent must have a Project Creation routing section
    that explicitly covers both create-new and add-existing paths."""

    def _agent_path(self) -> str:
        root = _project_root()
        return os.path.join(root, '.teaparty', 'management', 'agents',
                            'office-manager', 'agent.md')

    def _agent_body(self) -> str:
        with open(self._agent_path()) as f:
            return f.read()

    def _parse_tools(self) -> list[str]:
        content = self._agent_body()
        parts = content.split('---')
        fm = yaml.safe_load(parts[1])
        tools_str = fm.get('tools', '')
        return [t.strip() for t in tools_str.split(',') if t.strip()]

    def test_project_creation_section_present(self):
        body = self._agent_body()
        self.assertIn(
            '## Project Creation', body,
            'office-manager/agent.md must have a ## Project Creation routing section',
        )

    def test_project_creation_routes_to_configuration_lead(self):
        body = self._agent_body()
        self.assertIn(
            'Configuration Lead', body,
            'office-manager/agent.md must instruct routing project creation to the Configuration Lead',
        )

    def test_add_existing_project_path_covered(self):
        body = self._agent_body()
        # The OM must explicitly address the add-existing-project path
        self.assertTrue(
            'add-project' in body or 'existing' in body.lower(),
            'office-manager/agent.md Project Creation section must cover the add-existing-project path',
        )

    def test_office_manager_does_not_have_create_project_tool(self):
        tools = self._parse_tools()
        self.assertNotIn(
            'mcp__teaparty-config__CreateProject', tools,
            'office-manager must NOT have CreateProject in its tools — it delegates, not materializes '
            f'(current tools: {tools})',
        )


class TestCreateProjectSkillConfig(unittest.TestCase):
    """create-project SKILL.md must list mcp__teaparty-config__CreateProject in allowed-tools."""

    def _skill_path(self) -> str:
        root = _project_root()
        return os.path.join(root, '.teaparty', 'management', 'skills',
                            'create-project', 'SKILL.md')

    def _parse_allowed_tools(self) -> list[str]:
        path = self._skill_path()
        with open(path) as f:
            content = f.read()
        parts = content.split('---')
        fm = yaml.safe_load(parts[1])
        tools_str = fm.get('allowed-tools', '')
        return [t.strip() for t in tools_str.split(',') if t.strip()]

    def test_create_project_mcp_tool_in_allowed_tools(self):
        tools = self._parse_allowed_tools()
        self.assertIn(
            'mcp__teaparty-config__CreateProject', tools,
            'create-project SKILL.md must list mcp__teaparty-config__CreateProject in allowed-tools '
            f'(current allowed-tools: {tools})',
        )


class TestAddProjectSkillConfig(unittest.TestCase):
    """add-project SKILL.md must list mcp__teaparty-config__AddProject in allowed-tools."""

    def _skill_path(self) -> str:
        root = _project_root()
        return os.path.join(root, '.teaparty', 'management', 'skills',
                            'add-project', 'SKILL.md')

    def _parse_allowed_tools(self) -> list[str]:
        path = self._skill_path()
        with open(path) as f:
            content = f.read()
        parts = content.split('---')
        fm = yaml.safe_load(parts[1])
        tools_str = fm.get('allowed-tools', '')
        return [t.strip() for t in tools_str.split(',') if t.strip()]

    def test_add_project_mcp_tool_in_allowed_tools(self):
        tools = self._parse_allowed_tools()
        self.assertIn(
            'mcp__teaparty-config__AddProject', tools,
            'add-project SKILL.md must list mcp__teaparty-config__AddProject in allowed-tools '
            f'(current allowed-tools: {tools})',
        )


# ── Layer 5: Config page seed coverage ───────────────────────────────────────

class TestConfigPageProjectSeeds(unittest.TestCase):
    """config.html must seed both create-new-project and add-existing-project conversations."""

    def _config_html(self) -> str:
        root = _project_root()
        path = os.path.join(root, 'teaparty', 'bridge', 'static', 'config.html')
        with open(path) as f:
            return f.read()

    def test_create_new_project_seed_present(self):
        html = self._config_html()
        self.assertIn(
            'I would like to create a new project',
            html,
            'config.html must contain a seed for creating a new project',
        )

    def test_add_existing_project_seed_present(self):
        html = self._config_html()
        self.assertIn(
            'I would like to add an existing project',
            html,
            'config.html must contain a seed for adding an existing project',
        )
