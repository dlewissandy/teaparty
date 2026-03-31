"""Tests for Issue #333: Config MCP tools — expose TeaParty configuration operations
as scoped MCP tools.

Acceptance criteria:
1. All 19 configuration operations have MCP tool implementations in orchestrator/mcp_server.py
2. Each tool validates required fields and returns a structured error (not a partial write)
3. Each configuration specialist has disallowedTools for out-of-sphere config tools
4. OfficeManagerSession.invoke() passes mcp_config to ClaudeRunner
5. The 19 config skills no longer list Write or Edit in allowed-tools
6. Pybayes .teaparty.local/project.yaml has non-empty lead and decider
7. docs/proposals/configuration-team/proposal.md describes the MCP tool enforcement model
"""
import asyncio
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).parent.parent
_AGENTS_DIR = _REPO_ROOT / '.claude' / 'agents'
_SKILLS_DIR = _REPO_ROOT / '.claude' / 'skills'


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_tmpdir() -> str:
    return tempfile.mkdtemp()


def _make_project_root(tmpdir: str) -> str:
    """Create a minimal project root with .claude/ and .teaparty/ dirs."""
    claude_dir = os.path.join(tmpdir, '.claude')
    agents_dir = os.path.join(claude_dir, 'agents')
    skills_dir = os.path.join(claude_dir, 'skills')
    settings_path = os.path.join(claude_dir, 'settings.json')
    tp_dir = os.path.join(tmpdir, '.teaparty')
    wg_dir = os.path.join(tp_dir, 'workgroups')
    os.makedirs(agents_dir, exist_ok=True)
    os.makedirs(skills_dir, exist_ok=True)
    os.makedirs(wg_dir, exist_ok=True)
    with open(settings_path, 'w') as f:
        json.dump({'hooks': {}}, f)
    return tmpdir


def _make_teaparty_home(tmpdir: str) -> str:
    """Create .teaparty/ structure with a teaparty.yaml."""
    tp_home = os.path.join(tmpdir, '.teaparty')
    os.makedirs(tp_home, exist_ok=True)
    data = {
        'name': 'Test Team',
        'description': 'test',
        'lead': 'office-manager',
        'decider': 'darrell',
        'agents': [],
        'humans': [{'name': 'darrell', 'role': 'decider'}],
        'teams': [],
        'workgroups': [],
        'skills': [],
        'scheduled': [],
    }
    with open(os.path.join(tp_home, 'teaparty.yaml'), 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    return tp_home


def _make_project_dir(tmpdir: str, name: str) -> str:
    """Create a minimal existing project directory."""
    proj = os.path.join(tmpdir, name)
    os.makedirs(proj, exist_ok=True)
    # Not a full TeaParty project — just a directory
    return proj


def _run(coro):
    return asyncio.run(coro)


def _read_agent(agents_dir: str, name: str) -> dict:
    """Parse a .claude/agents/{name}.md file and return frontmatter + body."""
    path = os.path.join(agents_dir, f'{name}.md')
    with open(path) as f:
        content = f.read()
    # Parse YAML frontmatter between --- delimiters
    m = re.match(r'^---\n(.*?\n)---\n(.*)', content, re.DOTALL)
    if not m:
        return {'_body': content, '_raw': content}
    fm = yaml.safe_load(m.group(1))
    fm['_body'] = m.group(2)
    return fm


# ── AC1 + AC2: MCP config tools exist and validate required fields ─────────────

class TestConfigMCPToolsExist(unittest.TestCase):
    """All 19 config tool handlers must be importable from orchestrator.mcp_server."""

    def test_project_tool_handlers_importable(self):
        """Project tool handlers must exist in orchestrator.mcp_server."""
        from orchestrator.mcp_server import (
            add_project_handler,
            create_project_handler,
            remove_project_handler,
            scaffold_project_yaml_handler,
        )
        for fn in [add_project_handler, create_project_handler,
                   remove_project_handler, scaffold_project_yaml_handler]:
            self.assertTrue(callable(fn), f'{fn} must be callable')

    def test_agent_tool_handlers_importable(self):
        """Agent tool handlers must exist in orchestrator.mcp_server."""
        from orchestrator.mcp_server import (
            create_agent_handler,
            edit_agent_handler,
            remove_agent_handler,
        )
        for fn in [create_agent_handler, edit_agent_handler, remove_agent_handler]:
            self.assertTrue(callable(fn), f'{fn} must be callable')

    def test_skill_tool_handlers_importable(self):
        """Skill tool handlers must exist in orchestrator.mcp_server."""
        from orchestrator.mcp_server import (
            create_skill_handler,
            edit_skill_handler,
            remove_skill_handler,
        )
        for fn in [create_skill_handler, edit_skill_handler, remove_skill_handler]:
            self.assertTrue(callable(fn), f'{fn} must be callable')

    def test_workgroup_tool_handlers_importable(self):
        """Workgroup tool handlers must exist in orchestrator.mcp_server."""
        from orchestrator.mcp_server import (
            create_workgroup_handler,
            edit_workgroup_handler,
            remove_workgroup_handler,
        )
        for fn in [create_workgroup_handler, edit_workgroup_handler,
                   remove_workgroup_handler]:
            self.assertTrue(callable(fn), f'{fn} must be callable')

    def test_hook_tool_handlers_importable(self):
        """Hook tool handlers must exist in orchestrator.mcp_server."""
        from orchestrator.mcp_server import (
            create_hook_handler,
            edit_hook_handler,
            remove_hook_handler,
        )
        for fn in [create_hook_handler, edit_hook_handler, remove_hook_handler]:
            self.assertTrue(callable(fn), f'{fn} must be callable')

    def test_scheduled_task_tool_handlers_importable(self):
        """Scheduled task tool handlers must exist in orchestrator.mcp_server."""
        from orchestrator.mcp_server import (
            create_scheduled_task_handler,
            edit_scheduled_task_handler,
            remove_scheduled_task_handler,
        )
        for fn in [create_scheduled_task_handler, edit_scheduled_task_handler,
                   remove_scheduled_task_handler]:
            self.assertTrue(callable(fn), f'{fn} must be callable')

    def test_create_server_registers_all_config_tools(self):
        """create_server() must register all 19 config tools."""
        from orchestrator.mcp_server import create_server
        server = create_server()
        # FastMCP exposes registered tools via _tools dict
        tool_names = set(server._tool_manager._tools.keys())
        expected = {
            'AddProject', 'CreateProject', 'RemoveProject', 'ScaffoldProjectYaml',
            'CreateAgent', 'EditAgent', 'RemoveAgent',
            'CreateSkill', 'EditSkill', 'RemoveSkill',
            'CreateWorkgroup', 'EditWorkgroup', 'RemoveWorkgroup',
            'CreateHook', 'EditHook', 'RemoveHook',
            'CreateScheduledTask', 'EditScheduledTask', 'RemoveScheduledTask',
        }
        missing = expected - tool_names
        self.assertEqual(
            missing, set(),
            f'Missing MCP tools: {missing}',
        )


class TestProjectToolValidation(unittest.TestCase):
    """Project tools must validate required fields."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.tp_home = _make_teaparty_home(self.tmpdir)
        self.proj_dir = _make_project_dir(self.tmpdir, 'testproj')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_add_project_missing_name_returns_error(self):
        """AddProject with empty name must return error, not write anything."""
        from orchestrator.mcp_server import add_project_handler
        result = add_project_handler(name='', path=self.proj_dir,
                                     teaparty_home=self.tp_home)
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])
        self.assertIn('name', parsed['error'].lower())

    def test_add_project_missing_path_returns_error(self):
        """AddProject with empty path must return error."""
        from orchestrator.mcp_server import add_project_handler
        result = add_project_handler(name='myproj', path='',
                                     teaparty_home=self.tp_home)
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])

    def test_add_project_nonexistent_path_returns_error(self):
        """AddProject with path that does not exist must return error."""
        from orchestrator.mcp_server import add_project_handler
        result = add_project_handler(name='myproj',
                                     path='/nonexistent/path/xyz',
                                     teaparty_home=self.tp_home)
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])

    def test_add_project_creates_registry_entry(self):
        """AddProject with valid args must add teams: entry to teaparty.yaml."""
        from orchestrator.mcp_server import add_project_handler
        result = add_project_handler(
            name='testproj',
            path=self.proj_dir,
            description='A test project',
            lead='office-manager',
            decider='darrell',
            teaparty_home=self.tp_home,
        )
        parsed = json.loads(result)
        self.assertTrue(parsed['success'], parsed.get('error'))
        # Verify registry entry
        with open(os.path.join(self.tp_home, 'teaparty.yaml')) as f:
            data = yaml.safe_load(f)
        names = [t['name'] for t in data.get('teams', [])]
        self.assertIn('testproj', names)

    def test_add_project_creates_project_yaml(self):
        """AddProject with valid args must create .teaparty.local/project.yaml."""
        from orchestrator.mcp_server import add_project_handler
        add_project_handler(
            name='testproj',
            path=self.proj_dir,
            description='A test project',
            lead='office-manager',
            decider='darrell',
            teaparty_home=self.tp_home,
        )
        yaml_path = os.path.join(self.proj_dir, '.teaparty.local', 'project.yaml')
        self.assertTrue(os.path.exists(yaml_path))
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        self.assertEqual(data['name'], 'testproj')
        self.assertEqual(data['lead'], 'office-manager')
        self.assertEqual(data['decider'], 'darrell')

    def test_add_project_duplicate_name_returns_error(self):
        """AddProject with a name already in teaparty.yaml must return error."""
        from orchestrator.mcp_server import add_project_handler
        add_project_handler(name='testproj', path=self.proj_dir,
                            teaparty_home=self.tp_home)
        proj2 = _make_project_dir(self.tmpdir, 'testproj2')
        result = add_project_handler(name='testproj', path=proj2,
                                     teaparty_home=self.tp_home)
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])

    def test_remove_project_removes_registry_entry(self):
        """RemoveProject must remove the teams: entry from teaparty.yaml."""
        from orchestrator.mcp_server import add_project_handler, remove_project_handler
        add_project_handler(name='testproj', path=self.proj_dir,
                            teaparty_home=self.tp_home)
        result = remove_project_handler(name='testproj', teaparty_home=self.tp_home)
        parsed = json.loads(result)
        self.assertTrue(parsed['success'], parsed.get('error'))
        with open(os.path.join(self.tp_home, 'teaparty.yaml')) as f:
            data = yaml.safe_load(f)
        names = [t['name'] for t in data.get('teams', [])]
        self.assertNotIn('testproj', names)

    def test_create_project_missing_name_returns_error(self):
        """CreateProject with empty name must return error."""
        from orchestrator.mcp_server import create_project_handler
        result = create_project_handler(name='', path='/tmp/newproj',
                                        teaparty_home=self.tp_home)
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])
        self.assertIn('name', parsed['error'].lower())

    def test_create_project_missing_path_returns_error(self):
        """CreateProject with empty path must return error."""
        from orchestrator.mcp_server import create_project_handler
        result = create_project_handler(name='newproj', path='',
                                        teaparty_home=self.tp_home)
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])

    def test_create_project_existing_directory_returns_error(self):
        """CreateProject on an existing directory must return error."""
        from orchestrator.mcp_server import create_project_handler
        result = create_project_handler(
            name='newproj', path=self.proj_dir,  # already exists
            teaparty_home=self.tp_home,
        )
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])

    def test_remove_project_nonexistent_returns_error(self):
        """RemoveProject for unknown name must return error."""
        from orchestrator.mcp_server import remove_project_handler
        result = remove_project_handler(name='unknown', teaparty_home=self.tp_home)
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])

    def test_scaffold_project_yaml_creates_file_with_fields(self):
        """ScaffoldProjectYaml must create .teaparty.local/project.yaml with all fields."""
        from orchestrator.mcp_server import scaffold_project_yaml_handler
        result = scaffold_project_yaml_handler(
            project_path=self.proj_dir,
            name='testproj',
            description='A test project',
            lead='office-manager',
            decider='darrell',
        )
        parsed = json.loads(result)
        self.assertTrue(parsed['success'], parsed.get('error'))
        yaml_path = os.path.join(self.proj_dir, '.teaparty.local', 'project.yaml')
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        self.assertEqual(data['lead'], 'office-manager')
        self.assertEqual(data['decider'], 'darrell')

    def test_scaffold_project_yaml_overwrites_existing_file(self):
        """ScaffoldProjectYaml must overwrite an existing project.yaml (retroactive fix)."""
        from orchestrator.mcp_server import scaffold_project_yaml_handler
        # Create an existing project.yaml with empty fields (the pybayes scenario)
        tp_local = os.path.join(self.proj_dir, '.teaparty.local')
        os.makedirs(tp_local, exist_ok=True)
        with open(os.path.join(tp_local, 'project.yaml'), 'w') as f:
            yaml.dump({'name': 'testproj', 'lead': '', 'decider': ''}, f)
        # Now scaffold with correct fields
        scaffold_project_yaml_handler(
            project_path=self.proj_dir,
            name='testproj',
            description='updated',
            lead='office-manager',
            decider='darrell',
        )
        with open(os.path.join(tp_local, 'project.yaml')) as f:
            data = yaml.safe_load(f)
        self.assertEqual(data['lead'], 'office-manager')
        self.assertEqual(data['decider'], 'darrell')

    def test_scaffold_project_yaml_accepts_list_params(self):
        """ScaffoldProjectYaml handler must write agents/humans/workgroups/skills."""
        from orchestrator.mcp_server import scaffold_project_yaml_handler
        result = scaffold_project_yaml_handler(
            project_path=self.proj_dir,
            name='testproj',
            description='desc',
            lead='office-manager',
            decider='darrell',
            agents=['agent-a', 'agent-b'],
            humans=[{'name': 'darrell', 'role': 'decider'}],
            workgroups=['wg-config'],
            skills=['commit'],
        )
        parsed = json.loads(result)
        self.assertTrue(parsed['success'], parsed.get('error'))
        yaml_path = os.path.join(self.proj_dir, '.teaparty.local', 'project.yaml')
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
        self.assertEqual(data['agents'], ['agent-a', 'agent-b'])
        self.assertEqual(data['humans'][0]['name'], 'darrell')


class TestAgentToolValidation(unittest.TestCase):
    """Agent tools must validate required fields and write correct artifacts."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.proj = _make_project_root(self.tmpdir)
        self.agents_dir = os.path.join(self.proj, '.claude', 'agents')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_agent_missing_name_returns_error(self):
        """CreateAgent with empty name must return error."""
        from orchestrator.mcp_server import create_agent_handler
        result = create_agent_handler(
            name='', description='A test agent', model='claude-sonnet-4-5',
            tools='Read, Glob', body='You are a test agent.',
            project_root=self.proj,
        )
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])
        self.assertIn('name', parsed['error'].lower())

    def test_create_agent_missing_model_returns_error(self):
        """CreateAgent with empty model must return error."""
        from orchestrator.mcp_server import create_agent_handler
        result = create_agent_handler(
            name='test-agent', description='A test agent', model='',
            tools='Read, Glob', body='You are a test agent.',
            project_root=self.proj,
        )
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])
        self.assertIn('model', parsed['error'].lower())

    def test_create_agent_missing_description_returns_error(self):
        """CreateAgent with empty description must return error."""
        from orchestrator.mcp_server import create_agent_handler
        result = create_agent_handler(
            name='test-agent', description='', model='claude-sonnet-4-5',
            tools='Read, Glob', body='You are a test agent.',
            project_root=self.proj,
        )
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])

    def test_create_agent_writes_correct_frontmatter(self):
        """CreateAgent with valid args must write a .md file with correct frontmatter."""
        from orchestrator.mcp_server import create_agent_handler
        result = create_agent_handler(
            name='test-agent',
            description='A test agent for unit testing.',
            model='claude-sonnet-4-5',
            tools='Read, Glob, Grep',
            body='You are a test agent.',
            max_turns=15,
            project_root=self.proj,
        )
        parsed = json.loads(result)
        self.assertTrue(parsed['success'], parsed.get('error'))
        fm = _read_agent(self.agents_dir, 'test-agent')
        self.assertEqual(fm['name'], 'test-agent')
        self.assertEqual(fm['description'], 'A test agent for unit testing.')
        self.assertEqual(fm['model'], 'claude-sonnet-4-5')
        self.assertIn('Read', fm['tools'])
        self.assertEqual(fm['maxTurns'], 15)

    def test_create_agent_body_written_after_frontmatter(self):
        """CreateAgent must write the body text after the frontmatter block."""
        from orchestrator.mcp_server import create_agent_handler
        create_agent_handler(
            name='test-agent',
            description='desc',
            model='claude-sonnet-4-5',
            tools='Read',
            body='You are a specialized test agent.',
            project_root=self.proj,
        )
        fm = _read_agent(self.agents_dir, 'test-agent')
        self.assertIn('specialized test agent', fm['_body'])

    def test_edit_agent_updates_model_field(self):
        """EditAgent must update a single frontmatter field without rewriting body."""
        from orchestrator.mcp_server import create_agent_handler, edit_agent_handler
        create_agent_handler(
            name='test-agent', description='desc',
            model='claude-sonnet-4-5', tools='Read',
            body='Body text.', project_root=self.proj,
        )
        result = edit_agent_handler(
            name='test-agent', field='model',
            value='claude-opus-4-5', project_root=self.proj,
        )
        parsed = json.loads(result)
        self.assertTrue(parsed['success'], parsed.get('error'))
        fm = _read_agent(self.agents_dir, 'test-agent')
        self.assertEqual(fm['model'], 'claude-opus-4-5')
        # Body must be preserved
        self.assertIn('Body text', fm['_body'])

    def test_edit_agent_nonexistent_returns_error(self):
        """EditAgent on non-existent agent must return error."""
        from orchestrator.mcp_server import edit_agent_handler
        result = edit_agent_handler(
            name='nonexistent', field='model',
            value='claude-sonnet-4-5', project_root=self.proj,
        )
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])

    def test_remove_agent_deletes_file(self):
        """RemoveAgent must delete the .md file."""
        from orchestrator.mcp_server import create_agent_handler, remove_agent_handler
        create_agent_handler(
            name='test-agent', description='desc',
            model='claude-sonnet-4-5', tools='Read',
            body='Body.', project_root=self.proj,
        )
        result = remove_agent_handler(name='test-agent', project_root=self.proj)
        parsed = json.loads(result)
        self.assertTrue(parsed['success'], parsed.get('error'))
        self.assertFalse(
            os.path.exists(os.path.join(self.agents_dir, 'test-agent.md')),
        )

    def test_remove_agent_nonexistent_returns_error(self):
        """RemoveAgent on non-existent agent must return error."""
        from orchestrator.mcp_server import remove_agent_handler
        result = remove_agent_handler(name='nonexistent', project_root=self.proj)
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])


class TestSkillToolValidation(unittest.TestCase):
    """Skill tools must validate required fields and write correct artifacts."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.proj = _make_project_root(self.tmpdir)
        self.skills_dir = os.path.join(self.proj, '.claude', 'skills')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_skill_missing_name_returns_error(self):
        """CreateSkill with empty name must return error."""
        from orchestrator.mcp_server import create_skill_handler
        result = create_skill_handler(
            name='', description='desc', body='Content.',
            project_root=self.proj,
        )
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])
        self.assertIn('name', parsed['error'].lower())

    def test_create_skill_missing_description_returns_error(self):
        """CreateSkill with empty description must return error."""
        from orchestrator.mcp_server import create_skill_handler
        result = create_skill_handler(
            name='test-skill', description='', body='Content.',
            project_root=self.proj,
        )
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])

    def test_create_skill_writes_skill_md(self):
        """CreateSkill must write .claude/skills/{name}/SKILL.md with frontmatter."""
        from orchestrator.mcp_server import create_skill_handler
        result = create_skill_handler(
            name='test-skill',
            description='A test skill.',
            body='Do the thing.',
            allowed_tools='Read, Glob',
            project_root=self.proj,
        )
        parsed = json.loads(result)
        self.assertTrue(parsed['success'], parsed.get('error'))
        skill_path = os.path.join(self.skills_dir, 'test-skill', 'SKILL.md')
        self.assertTrue(os.path.exists(skill_path))
        with open(skill_path) as f:
            content = f.read()
        self.assertIn('name: test-skill', content)
        self.assertIn('A test skill.', content)
        self.assertIn('Do the thing.', content)

    def test_create_skill_directory_created(self):
        """CreateSkill must create .claude/skills/{name}/ directory."""
        from orchestrator.mcp_server import create_skill_handler
        create_skill_handler(
            name='test-skill', description='desc', body='body',
            project_root=self.proj,
        )
        self.assertTrue(
            os.path.isdir(os.path.join(self.skills_dir, 'test-skill')),
        )

    def test_edit_skill_updates_body(self):
        """EditSkill with field='body' must update the body content of SKILL.md."""
        from orchestrator.mcp_server import create_skill_handler, edit_skill_handler
        create_skill_handler(
            name='test-skill', description='desc', body='Original body.',
            project_root=self.proj,
        )
        result = edit_skill_handler(
            name='test-skill', field='body', value='Updated body.',
            project_root=self.proj,
        )
        parsed = json.loads(result)
        self.assertTrue(parsed['success'], parsed.get('error'))
        skill_path = os.path.join(self.skills_dir, 'test-skill', 'SKILL.md')
        with open(skill_path) as f:
            content = f.read()
        self.assertIn('Updated body.', content)
        self.assertNotIn('Original body.', content)

    def test_edit_skill_updates_allowed_tools(self):
        """EditSkill with field='allowed-tools' must update the frontmatter."""
        from orchestrator.mcp_server import create_skill_handler, edit_skill_handler
        create_skill_handler(
            name='test-skill', description='desc', body='body.',
            allowed_tools='Read, Glob', project_root=self.proj,
        )
        result = edit_skill_handler(
            name='test-skill', field='allowed-tools', value='Read, Glob, Bash',
            project_root=self.proj,
        )
        parsed = json.loads(result)
        self.assertTrue(parsed['success'], parsed.get('error'))
        skill_path = os.path.join(self.skills_dir, 'test-skill', 'SKILL.md')
        with open(skill_path) as f:
            content = f.read()
        self.assertIn('Read, Glob, Bash', content)

    def test_edit_skill_updates_description(self):
        """EditSkill with field='description' must update the frontmatter."""
        from orchestrator.mcp_server import create_skill_handler, edit_skill_handler
        create_skill_handler(
            name='test-skill', description='old desc', body='body.',
            project_root=self.proj,
        )
        result = edit_skill_handler(
            name='test-skill', field='description', value='new description',
            project_root=self.proj,
        )
        parsed = json.loads(result)
        self.assertTrue(parsed['success'], parsed.get('error'))
        skill_path = os.path.join(self.skills_dir, 'test-skill', 'SKILL.md')
        with open(skill_path) as f:
            content = f.read()
        self.assertIn('new description', content)

    def test_edit_skill_nonexistent_returns_error(self):
        """EditSkill on non-existent skill must return error."""
        from orchestrator.mcp_server import edit_skill_handler
        result = edit_skill_handler(
            name='nonexistent', field='body', value='body', project_root=self.proj,
        )
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])

    def test_remove_skill_removes_directory(self):
        """RemoveSkill must remove the entire .claude/skills/{name}/ directory."""
        from orchestrator.mcp_server import create_skill_handler, remove_skill_handler
        create_skill_handler(
            name='test-skill', description='desc', body='body',
            project_root=self.proj,
        )
        result = remove_skill_handler(name='test-skill', project_root=self.proj)
        parsed = json.loads(result)
        self.assertTrue(parsed['success'], parsed.get('error'))
        self.assertFalse(
            os.path.exists(os.path.join(self.skills_dir, 'test-skill')),
        )

    def test_remove_skill_nonexistent_returns_error(self):
        """RemoveSkill on non-existent skill must return error."""
        from orchestrator.mcp_server import remove_skill_handler
        result = remove_skill_handler(name='nonexistent', project_root=self.proj)
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])


class TestWorkgroupToolValidation(unittest.TestCase):
    """Workgroup tools must validate and write correct artifacts."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.proj = _make_project_root(self.tmpdir)
        self.tp_home = _make_teaparty_home(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_workgroup_missing_name_returns_error(self):
        """CreateWorkgroup with empty name must return error."""
        from orchestrator.mcp_server import create_workgroup_handler
        result = create_workgroup_handler(
            name='', teaparty_home=self.tp_home,
        )
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])
        self.assertIn('name', parsed['error'].lower())

    def test_create_workgroup_writes_yaml(self):
        """CreateWorkgroup must write a YAML file in .teaparty/workgroups/."""
        from orchestrator.mcp_server import create_workgroup_handler
        result = create_workgroup_handler(
            name='test-wg',
            description='A test workgroup',
            lead='office-manager',
            teaparty_home=self.tp_home,
        )
        parsed = json.loads(result)
        self.assertTrue(parsed['success'], parsed.get('error'))
        wg_path = os.path.join(self.tp_home, 'workgroups', 'test-wg.yaml')
        self.assertTrue(os.path.exists(wg_path))
        with open(wg_path) as f:
            data = yaml.safe_load(f)
        self.assertEqual(data['name'], 'test-wg')
        self.assertEqual(data['lead'], 'office-manager')

    def test_edit_workgroup_updates_field(self):
        """EditWorkgroup must update a field in the workgroup YAML."""
        from orchestrator.mcp_server import create_workgroup_handler, edit_workgroup_handler
        create_workgroup_handler(
            name='test-wg', lead='office-manager', teaparty_home=self.tp_home,
        )
        result = edit_workgroup_handler(
            name='test-wg', field='lead', value='configuration-lead',
            teaparty_home=self.tp_home,
        )
        parsed = json.loads(result)
        self.assertTrue(parsed['success'], parsed.get('error'))
        wg_path = os.path.join(self.tp_home, 'workgroups', 'test-wg.yaml')
        with open(wg_path) as f:
            data = yaml.safe_load(f)
        self.assertEqual(data['lead'], 'configuration-lead')

    def test_edit_workgroup_nonexistent_returns_error(self):
        """EditWorkgroup on non-existent workgroup must return error."""
        from orchestrator.mcp_server import edit_workgroup_handler
        result = edit_workgroup_handler(
            name='nonexistent', field='lead', value='x',
            teaparty_home=self.tp_home,
        )
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])

    def test_remove_workgroup_removes_file(self):
        """RemoveWorkgroup must delete the workgroup YAML file."""
        from orchestrator.mcp_server import create_workgroup_handler, remove_workgroup_handler
        create_workgroup_handler(
            name='test-wg', teaparty_home=self.tp_home,
        )
        result = remove_workgroup_handler(name='test-wg', teaparty_home=self.tp_home)
        parsed = json.loads(result)
        self.assertTrue(parsed['success'], parsed.get('error'))
        wg_path = os.path.join(self.tp_home, 'workgroups', 'test-wg.yaml')
        self.assertFalse(os.path.exists(wg_path))

    def test_remove_workgroup_nonexistent_returns_error(self):
        """RemoveWorkgroup on non-existent workgroup must return error."""
        from orchestrator.mcp_server import remove_workgroup_handler
        result = remove_workgroup_handler(name='nonexistent', teaparty_home=self.tp_home)
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])


class TestHookToolValidation(unittest.TestCase):
    """Hook tools must validate and write correct entries in settings.json."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.proj = _make_project_root(self.tmpdir)
        self.settings_path = os.path.join(self.proj, '.claude', 'settings.json')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_hook_missing_event_returns_error(self):
        """CreateHook with empty event must return error."""
        from orchestrator.mcp_server import create_hook_handler
        result = create_hook_handler(
            event='', matcher='Edit', handler_type='command',
            command='echo test', project_root=self.proj,
        )
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])
        self.assertIn('event', parsed['error'].lower())

    def test_create_hook_missing_command_returns_error(self):
        """CreateHook with empty command must return error."""
        from orchestrator.mcp_server import create_hook_handler
        result = create_hook_handler(
            event='PostToolUse', matcher='Edit', handler_type='command',
            command='', project_root=self.proj,
        )
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])

    def test_create_hook_adds_to_settings_json(self):
        """CreateHook must add a hook entry to .claude/settings.json."""
        from orchestrator.mcp_server import create_hook_handler
        result = create_hook_handler(
            event='PostToolUse',
            matcher='Edit',
            handler_type='command',
            command='echo file-written',
            project_root=self.proj,
        )
        parsed = json.loads(result)
        self.assertTrue(parsed['success'], parsed.get('error'))
        with open(self.settings_path) as f:
            data = json.load(f)
        hooks = data.get('hooks', {})
        self.assertIn('PostToolUse', hooks)
        entries = hooks['PostToolUse']
        found = any(
            e.get('matcher') == 'Edit'
            for e in entries
        )
        self.assertTrue(found, 'Hook entry for matcher "Edit" not found')

    def test_create_hook_preserves_existing_hooks(self):
        """CreateHook must not overwrite existing hooks in settings.json."""
        from orchestrator.mcp_server import create_hook_handler
        # Add a first hook
        create_hook_handler(
            event='PostToolUse', matcher='Write',
            handler_type='command', command='echo write',
            project_root=self.proj,
        )
        # Add a second hook
        create_hook_handler(
            event='PostToolUse', matcher='Edit',
            handler_type='command', command='echo edit',
            project_root=self.proj,
        )
        with open(self.settings_path) as f:
            data = json.load(f)
        matchers = [e.get('matcher') for e in data['hooks']['PostToolUse']]
        self.assertIn('Write', matchers)
        self.assertIn('Edit', matchers)

    def test_remove_hook_removes_entry(self):
        """RemoveHook must remove the matching hook entry from settings.json."""
        from orchestrator.mcp_server import create_hook_handler, remove_hook_handler
        create_hook_handler(
            event='PostToolUse', matcher='Edit',
            handler_type='command', command='echo test',
            project_root=self.proj,
        )
        result = remove_hook_handler(
            event='PostToolUse', matcher='Edit', project_root=self.proj,
        )
        parsed = json.loads(result)
        self.assertTrue(parsed['success'], parsed.get('error'))
        with open(self.settings_path) as f:
            data = json.load(f)
        hooks = data.get('hooks', {}).get('PostToolUse', [])
        found = any(e.get('matcher') == 'Edit' for e in hooks)
        self.assertFalse(found, 'Hook entry should have been removed')

    def test_remove_hook_nonexistent_returns_error(self):
        """RemoveHook for non-existent hook must return error."""
        from orchestrator.mcp_server import remove_hook_handler
        result = remove_hook_handler(
            event='PostToolUse', matcher='NoSuchMatcher',
            project_root=self.proj,
        )
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])

    def test_edit_hook_updates_command(self):
        """EditHook must update a field in an existing hook entry."""
        from orchestrator.mcp_server import create_hook_handler, edit_hook_handler
        create_hook_handler(
            event='PostToolUse', matcher='Edit',
            handler_type='command', command='echo old',
            project_root=self.proj,
        )
        result = edit_hook_handler(
            event='PostToolUse', matcher='Edit',
            field='command', value='echo new',
            project_root=self.proj,
        )
        parsed = json.loads(result)
        self.assertTrue(parsed['success'], parsed.get('error'))
        with open(self.settings_path) as f:
            data = json.load(f)
        for entry in data['hooks']['PostToolUse']:
            if entry.get('matcher') == 'Edit':
                cmd = entry['hooks'][0]['command']
                self.assertEqual(cmd, 'echo new')
                break


class TestScheduledTaskToolValidation(unittest.TestCase):
    """Scheduled task tools must validate and write correct entries."""

    def setUp(self):
        self.tmpdir = _make_tmpdir()
        self.tp_home = _make_teaparty_home(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_scheduled_task_missing_name_returns_error(self):
        """CreateScheduledTask with empty name must return error."""
        from orchestrator.mcp_server import create_scheduled_task_handler
        result = create_scheduled_task_handler(
            name='', schedule='0 2 * * *', skill='digest',
            teaparty_home=self.tp_home,
        )
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])
        self.assertIn('name', parsed['error'].lower())

    def test_create_scheduled_task_missing_schedule_returns_error(self):
        """CreateScheduledTask with empty schedule must return error."""
        from orchestrator.mcp_server import create_scheduled_task_handler
        result = create_scheduled_task_handler(
            name='nightly', schedule='', skill='digest',
            teaparty_home=self.tp_home,
        )
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])

    def test_create_scheduled_task_missing_skill_returns_error(self):
        """CreateScheduledTask with empty skill must return error."""
        from orchestrator.mcp_server import create_scheduled_task_handler
        result = create_scheduled_task_handler(
            name='nightly', schedule='0 2 * * *', skill='',
            teaparty_home=self.tp_home,
        )
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])

    def test_create_scheduled_task_adds_to_yaml(self):
        """CreateScheduledTask must add a scheduled entry to teaparty.yaml."""
        from orchestrator.mcp_server import create_scheduled_task_handler
        result = create_scheduled_task_handler(
            name='nightly-digest',
            schedule='0 2 * * *',
            skill='digest',
            args='--format markdown',
            teaparty_home=self.tp_home,
        )
        parsed = json.loads(result)
        self.assertTrue(parsed['success'], parsed.get('error'))
        with open(os.path.join(self.tp_home, 'teaparty.yaml')) as f:
            data = yaml.safe_load(f)
        scheduled = data.get('scheduled', [])
        names = [s['name'] for s in scheduled]
        self.assertIn('nightly-digest', names)
        entry = next(s for s in scheduled if s['name'] == 'nightly-digest')
        self.assertEqual(entry['schedule'], '0 2 * * *')
        self.assertEqual(entry['skill'], 'digest')

    def test_edit_scheduled_task_updates_field(self):
        """EditScheduledTask must update a field in the scheduled entry."""
        from orchestrator.mcp_server import (
            create_scheduled_task_handler, edit_scheduled_task_handler,
        )
        create_scheduled_task_handler(
            name='nightly', schedule='0 2 * * *', skill='digest',
            teaparty_home=self.tp_home,
        )
        result = edit_scheduled_task_handler(
            name='nightly', field='schedule', value='0 3 * * *',
            teaparty_home=self.tp_home,
        )
        parsed = json.loads(result)
        self.assertTrue(parsed['success'], parsed.get('error'))
        with open(os.path.join(self.tp_home, 'teaparty.yaml')) as f:
            data = yaml.safe_load(f)
        entry = next(s for s in data['scheduled'] if s['name'] == 'nightly')
        self.assertEqual(entry['schedule'], '0 3 * * *')

    def test_edit_scheduled_task_nonexistent_returns_error(self):
        """EditScheduledTask on non-existent task must return error."""
        from orchestrator.mcp_server import edit_scheduled_task_handler
        result = edit_scheduled_task_handler(
            name='nonexistent', field='schedule', value='0 3 * * *',
            teaparty_home=self.tp_home,
        )
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])

    def test_remove_scheduled_task_removes_entry(self):
        """RemoveScheduledTask must remove the entry from teaparty.yaml."""
        from orchestrator.mcp_server import (
            create_scheduled_task_handler, remove_scheduled_task_handler,
        )
        create_scheduled_task_handler(
            name='nightly', schedule='0 2 * * *', skill='digest',
            teaparty_home=self.tp_home,
        )
        result = remove_scheduled_task_handler(
            name='nightly', teaparty_home=self.tp_home,
        )
        parsed = json.loads(result)
        self.assertTrue(parsed['success'], parsed.get('error'))
        with open(os.path.join(self.tp_home, 'teaparty.yaml')) as f:
            data = yaml.safe_load(f)
        names = [s['name'] for s in data.get('scheduled', [])]
        self.assertNotIn('nightly', names)

    def test_remove_scheduled_task_nonexistent_returns_error(self):
        """RemoveScheduledTask on non-existent task must return error."""
        from orchestrator.mcp_server import remove_scheduled_task_handler
        result = remove_scheduled_task_handler(
            name='nonexistent', teaparty_home=self.tp_home,
        )
        parsed = json.loads(result)
        self.assertFalse(parsed['success'])


# ── AC3: Tool scoping — specialists have disallowedTools ───────────────────────

def _read_agent_frontmatter(path: Path) -> dict:
    """Parse YAML frontmatter from an agent .md file."""
    content = path.read_text()
    m = re.match(r'^---\n(.*?\n)---\n', content, re.DOTALL)
    if not m:
        return {}
    return yaml.safe_load(m.group(1)) or {}


_ALL_CONFIG_TOOLS = {
    'AddProject', 'CreateProject', 'RemoveProject', 'ScaffoldProjectYaml',
    'CreateAgent', 'EditAgent', 'RemoveAgent',
    'CreateSkill', 'EditSkill', 'RemoveSkill',
    'CreateWorkgroup', 'EditWorkgroup', 'RemoveWorkgroup',
    'CreateHook', 'EditHook', 'RemoveHook',
    'CreateScheduledTask', 'EditScheduledTask', 'RemoveScheduledTask',
}

_SPHERE = {
    'project-specialist': {'AddProject', 'CreateProject', 'RemoveProject',
                           'ScaffoldProjectYaml'},
    'agent-specialist': {'CreateAgent', 'EditAgent', 'RemoveAgent'},
    'skills-specialist': {'CreateSkill', 'EditSkill', 'RemoveSkill'},
    'workgroup-specialist': {'CreateWorkgroup', 'EditWorkgroup', 'RemoveWorkgroup'},
    'systems-engineer': {'CreateHook', 'EditHook', 'RemoveHook',
                         'CreateScheduledTask', 'EditScheduledTask',
                         'RemoveScheduledTask'},
}


class TestToolScoping(unittest.TestCase):
    """Specialists must have disallowedTools for out-of-sphere config tools."""

    def _check_specialist_scoping(self, agent_name: str):
        """Verify that agent_name has disallowedTools covering all out-of-sphere tools."""
        path = _AGENTS_DIR / f'{agent_name}.md'
        self.assertTrue(path.exists(), f'{path} must exist')
        fm = _read_agent_frontmatter(path)
        disallowed = set(fm.get('disallowedTools', []))
        allowed_sphere = _SPHERE[agent_name]
        out_of_sphere = _ALL_CONFIG_TOOLS - allowed_sphere
        missing_from_disallowed = out_of_sphere - disallowed
        self.assertEqual(
            missing_from_disallowed, set(),
            f'{agent_name} must disallow out-of-sphere tools: {missing_from_disallowed}',
        )

    def test_project_specialist_disallows_out_of_sphere_tools(self):
        """project-specialist must disallow all non-project config tools."""
        self._check_specialist_scoping('project-specialist')

    def test_agent_specialist_disallows_out_of_sphere_tools(self):
        """agent-specialist must disallow all non-agent config tools."""
        self._check_specialist_scoping('agent-specialist')

    def test_skills_specialist_disallows_out_of_sphere_tools(self):
        """skills-specialist must disallow all non-skill config tools."""
        self._check_specialist_scoping('skills-specialist')

    def test_workgroup_specialist_disallows_out_of_sphere_tools(self):
        """workgroup-specialist must disallow all non-workgroup config tools."""
        self._check_specialist_scoping('workgroup-specialist')

    def test_systems_engineer_disallows_out_of_sphere_tools(self):
        """systems-engineer must disallow all non-hook/scheduled-task config tools."""
        self._check_specialist_scoping('systems-engineer')

    def test_configuration_lead_has_no_disallowed_config_tools(self):
        """configuration-lead must NOT disallow any config tools — it needs all of them."""
        path = _AGENTS_DIR / 'configuration-lead.md'
        fm = _read_agent_frontmatter(path)
        disallowed = set(fm.get('disallowedTools', []))
        disallowed_config = disallowed & _ALL_CONFIG_TOOLS
        self.assertEqual(
            disallowed_config, set(),
            f'configuration-lead must not disallow config tools: {disallowed_config}',
        )


# ── AC4: OfficeManagerSession.invoke() passes mcp_config ─────────────────────

class TestOmSessionPassesMcpConfig(unittest.TestCase):
    """OfficeManagerSession.invoke() must pass mcp_config to ClaudeRunner."""

    def test_invoke_constructs_runner_with_mcp_config(self):
        """invoke() must pass a non-None mcp_config dict to ClaudeRunner."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch
        from orchestrator.office_manager import OfficeManagerSession
        from orchestrator.messaging import SqliteMessageBus

        tmpdir = _make_tmpdir()
        try:
            tp_home = _make_teaparty_home(tmpdir)
            om_dir = os.path.join(tp_home, 'om')
            os.makedirs(om_dir, exist_ok=True)
            bus_path = os.path.join(om_dir, 'om-messages.db')
            bus = SqliteMessageBus(bus_path)
            # Add a human message so there's something to respond to
            from orchestrator.messaging import ConversationType, make_conversation_id
            conv = bus.create_conversation(ConversationType.OFFICE_MANAGER, 'test')
            bus.send(conv.id, 'human', 'Hello')

            session = OfficeManagerSession(
                teaparty_home=tp_home,
                user_id='test',
            )

            captured = {}

            class FakeResult:
                session_id = None

            class FakeRunner:
                def __init__(self, **kwargs):
                    captured.update(kwargs)

                async def run(self):
                    return FakeResult()

            with patch('orchestrator.claude_runner.ClaudeRunner', FakeRunner):
                with patch('orchestrator.office_manager._iter_stream_events',
                           return_value=[]):
                    asyncio.run(session.invoke(cwd=tmpdir))

            self.assertIn('mcp_config', captured,
                          'invoke() must pass mcp_config to ClaudeRunner')
            self.assertIsNotNone(captured['mcp_config'],
                                 'mcp_config must not be None')
            self.assertIsInstance(captured['mcp_config'], dict,
                                  'mcp_config must be a dict')
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ── AC5: Config skills do not list Write or Edit in allowed-tools ─────────────

_CONFIG_SKILL_NAMES = [
    'create-agent', 'edit-agent', 'remove-agent',
    'create-skill', 'edit-skill', 'remove-skill',
    'create-hook', 'edit-hook', 'remove-hook',
    'create-project', 'edit-project', 'remove-project',
    'create-workgroup', 'edit-workgroup', 'remove-workgroup',
    'create-scheduled-task', 'edit-scheduled-task', 'remove-scheduled-task',
]


class TestConfigSkillsNoDirectWrite(unittest.TestCase):
    """Config skills must not have Write or Edit in allowed-tools."""

    def _check_skill(self, skill_name: str):
        path = _SKILLS_DIR / skill_name / 'SKILL.md'
        self.assertTrue(path.exists(), f'{path} must exist')
        content = path.read_text()
        m = re.match(r'^---\n(.*?\n)---\n', content, re.DOTALL)
        self.assertIsNotNone(m, f'{skill_name}/SKILL.md must have frontmatter')
        fm = yaml.safe_load(m.group(1)) or {}
        allowed = fm.get('allowed-tools', '')
        allowed_list = [t.strip() for t in allowed.split(',')]
        self.assertNotIn(
            'Write', allowed_list,
            f'{skill_name}/SKILL.md must not list Write in allowed-tools',
        )
        self.assertNotIn(
            'Edit', allowed_list,
            f'{skill_name}/SKILL.md must not list Edit in allowed-tools',
        )

    def test_create_agent_skill_has_no_write_edit(self):
        self._check_skill('create-agent')

    def test_edit_agent_skill_has_no_write_edit(self):
        self._check_skill('edit-agent')

    def test_remove_agent_skill_has_no_write_edit(self):
        self._check_skill('remove-agent')

    def test_create_skill_skill_has_no_write_edit(self):
        self._check_skill('create-skill')

    def test_edit_skill_skill_has_no_write_edit(self):
        self._check_skill('edit-skill')

    def test_remove_skill_skill_has_no_write_edit(self):
        self._check_skill('remove-skill')

    def test_create_hook_skill_has_no_write_edit(self):
        self._check_skill('create-hook')

    def test_edit_hook_skill_has_no_write_edit(self):
        self._check_skill('edit-hook')

    def test_remove_hook_skill_has_no_write_edit(self):
        self._check_skill('remove-hook')

    def test_create_project_skill_has_no_write_edit(self):
        self._check_skill('create-project')

    def test_edit_project_skill_has_no_write_edit(self):
        self._check_skill('edit-project')

    def test_remove_project_skill_has_no_write_edit(self):
        self._check_skill('remove-project')

    def test_create_workgroup_skill_has_no_write_edit(self):
        self._check_skill('create-workgroup')

    def test_edit_workgroup_skill_has_no_write_edit(self):
        self._check_skill('edit-workgroup')

    def test_remove_workgroup_skill_has_no_write_edit(self):
        self._check_skill('remove-workgroup')

    def test_create_scheduled_task_skill_has_no_write_edit(self):
        self._check_skill('create-scheduled-task')

    def test_edit_scheduled_task_skill_has_no_write_edit(self):
        self._check_skill('edit-scheduled-task')

    def test_remove_scheduled_task_skill_has_no_write_edit(self):
        self._check_skill('remove-scheduled-task')


# ── AC6: Pybayes project.yaml has required fields ─────────────────────────────

@unittest.skipUnless(
    Path('/Users/darrell/git/pybayes/.teaparty.local/project.yaml').exists(),
    'pybayes project.yaml not present in this environment',
)
class TestPybayesProjectYaml(unittest.TestCase):
    """Pybayes .teaparty.local/project.yaml must have required fields."""

    _PYBAYES_YAML = Path('/Users/darrell/git/pybayes/.teaparty.local/project.yaml')

    def test_pybayes_project_yaml_exists(self):
        """Pybayes must have .teaparty.local/project.yaml."""
        self.assertTrue(
            self._PYBAYES_YAML.exists(),
            f'{self._PYBAYES_YAML} must exist',
        )

    def test_pybayes_project_yaml_has_nonempty_lead(self):
        """Pybayes project.yaml must have a non-empty lead field."""
        with open(self._PYBAYES_YAML) as f:
            data = yaml.safe_load(f)
        lead = data.get('lead', '')
        self.assertTrue(
            lead and lead.strip(),
            f'pybayes project.yaml lead must be non-empty, got: {lead!r}',
        )

    def test_pybayes_project_yaml_has_nonempty_decider(self):
        """Pybayes project.yaml must have a non-empty decider field."""
        with open(self._PYBAYES_YAML) as f:
            data = yaml.safe_load(f)
        decider = data.get('decider', '')
        self.assertTrue(
            decider and decider.strip(),
            f'pybayes project.yaml decider must be non-empty, got: {decider!r}',
        )


# ── AC7: Proposal doc updated ─────────────────────────────────────────────────

class TestProposalDocUpdated(unittest.TestCase):
    """Proposal doc must describe the MCP tool enforcement model."""

    _PROPOSAL = _REPO_ROOT / 'docs' / 'proposals' / 'configuration-team' / 'proposal.md'

    def test_proposal_mentions_mcp_tools(self):
        """proposal.md must mention MCP tools as the execution layer."""
        content = self._PROPOSAL.read_text()
        self.assertIn(
            'MCP', content,
            'proposal.md must describe the MCP tool enforcement model',
        )

    def test_proposal_describes_disallowed_tools_scoping(self):
        """proposal.md must describe disallowedTools as the scoping mechanism."""
        content = self._PROPOSAL.read_text()
        self.assertIn(
            'disallowedTools', content,
            'proposal.md must document disallowedTools scoping',
        )

    def test_proposal_describes_validation(self):
        """proposal.md must describe how tools validate required fields."""
        content = self._PROPOSAL.read_text()
        # The doc should describe that tools validate and return structured errors
        self.assertTrue(
            'validat' in content.lower(),
            'proposal.md must describe validation in MCP tools',
        )


if __name__ == '__main__':
    unittest.main()
