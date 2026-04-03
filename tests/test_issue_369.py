"""Tests for issue #369: Dashboard — agent config screen.

Acceptance criteria:
1. configNav handles 'agent' level in both config.html and mockup/config.html
2. renderAgent() is defined in both config.html and mockup/config.html
3. Agent items in renderGlobal() call configNav('agent', ...) on click
4. Agent items in renderProject() call configNav('agent', ...) on click
5. Agent items in renderWorkgroup() call configNav('agent', ...) on click
6. config.html?agent=foo and config.html?agent=foo&project=bar handled at page init
7. patchCurrentAgent, saveAgentField, toggleAgentSkill, toggleAgentTool,
   setAgentPermissionMode functions are defined
8. AVAILABLE_TOOLS constant is defined with all standard tool names
9. GET /api/catalog/org returns org-level skills and agents
10. GET /api/catalog/org returns 200 with agents, skills, hooks keys
"""
import asyncio
import os
import re
import tempfile
import unittest
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).parent.parent


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _make_skill_dir(skills_dir: str, name: str) -> None:
    skill_path = os.path.join(skills_dir, name)
    os.makedirs(skill_path, exist_ok=True)
    with open(os.path.join(skill_path, 'SKILL.md'), 'w') as f:
        f.write(f'# {name}\n')


def _make_agent_file(agents_dir: str, name: str, frontmatter: dict | None = None) -> str:
    agent_dir = os.path.join(agents_dir, name)
    os.makedirs(agent_dir, exist_ok=True)
    path = os.path.join(agent_dir, 'agent.md')
    if frontmatter is None:
        frontmatter = {'name': name, 'description': f'The {name} agent', 'model': 'opus', 'maxTurns': 20}
    fm_str = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False).rstrip()
    with open(path, 'w') as f:
        f.write(f'---\n{fm_str}\n---\nYou are {name}.\n')
    return path


def _make_teaparty_home(tmp: str) -> str:
    """Create tmp/.teaparty/management/ with teaparty.yaml; returns path to .teaparty dir."""
    tp_home = os.path.join(tmp, '.teaparty')
    mgmt_dir = os.path.join(tp_home, 'management')
    os.makedirs(mgmt_dir)
    data = {
        'name': 'Test Org',
        'description': 'test',
        'lead': 'office-manager',
        'humans': {'decider': 'tester'},
        'members': {'agents': [], 'projects': []},
        'projects': [],
        'workgroups': [],
        'scheduled': [],
    }
    with open(os.path.join(mgmt_dir, 'teaparty.yaml'), 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    return tp_home


def _make_bridge(teaparty_home: str, tmp: str):
    from bridge.server import TeaPartyBridge
    static_dir = os.path.join(tmp, 'static')
    os.makedirs(static_dir, exist_ok=True)
    return TeaPartyBridge(teaparty_home=teaparty_home, static_dir=static_dir)


def _make_request_mock():
    from unittest.mock import MagicMock
    return MagicMock()


# ── AC1: configNav handles 'agent' level ─────────────────────────────────────

class TestConfigNavHandlesAgentLevel(unittest.TestCase):
    """configNav must handle level === 'agent' in both config.html and mockup."""

    def _read_live(self) -> str:
        path = _REPO_ROOT / 'bridge' / 'static' / 'config.html'
        self.assertTrue(path.exists(), f'config.html not found at {path}')
        return path.read_text()

    def _read_mockup(self) -> str:
        path = _REPO_ROOT / 'docs' / 'proposals' / 'ui-redesign' / 'mockup' / 'config.html'
        self.assertTrue(path.exists(), f'mockup config.html not found at {path}')
        return path.read_text()

    def test_live_configNav_handles_agent_level(self):
        """configNav in bridge/static/config.html must handle level === 'agent'."""
        source = self._read_live()
        self.assertIn("level === 'agent'", source,
            "configNav must handle level === 'agent' in bridge/static/config.html")

    def test_mockup_configNav_handles_agent_level(self):
        """configNav in mockup/config.html must handle level === 'agent'."""
        source = self._read_mockup()
        self.assertIn("level === 'agent'", source,
            "configNav must handle level === 'agent' in mockup/config.html")

    def test_live_configNav_sets_agent_url(self):
        """configNav('agent', ...) must push ?agent=... to browser history."""
        source = self._read_live()
        self.assertIn('agent=', source,
            "configNav agent level must push ?agent=... URL in bridge/static/config.html")

    def test_mockup_configNav_sets_agent_url(self):
        """configNav('agent', ...) must push ?agent=... URL in mockup."""
        source = self._read_mockup()
        self.assertIn('agent=', source,
            "configNav agent level must push ?agent=... URL in mockup/config.html")


# ── AC2: renderAgent function is defined ─────────────────────────────────────

class TestRenderAgentFunctionExists(unittest.TestCase):
    """renderAgent() must be defined in both config.html and mockup/config.html."""

    def test_live_config_html_has_renderAgent(self):
        """bridge/static/config.html must define renderAgent()."""
        path = _REPO_ROOT / 'bridge' / 'static' / 'config.html'
        source = path.read_text()
        self.assertIn('function renderAgent(', source,
            'bridge/static/config.html must define renderAgent() function')

    def test_mockup_config_html_has_renderAgent(self):
        """docs/proposals/ui-redesign/mockup/config.html must define renderAgent()."""
        path = _REPO_ROOT / 'docs' / 'proposals' / 'ui-redesign' / 'mockup' / 'config.html'
        source = path.read_text()
        self.assertIn('function renderAgent(', source,
            'mockup/config.html must define renderAgent() function')


# ── AC3: Agent items in renderGlobal call configNav('agent', ...) ─────────────

class TestRenderGlobalAgentClicksUseConfigNav(unittest.TestCase):
    """Agent items in renderGlobal() must navigate to agent config, not artifacts.html."""

    def _get_config_html(self) -> str:
        path = _REPO_ROOT / 'bridge' / 'static' / 'config.html'
        return path.read_text()

    def test_renderGlobal_agent_items_call_configNav_agent(self):
        """renderGlobal() agent items must call configNav('agent', ...) on click."""
        source = self._get_config_html()
        # Find renderGlobal function body
        m = re.search(r'async function renderGlobal\(\)(.*?)(?=\nasync function |\nfunction )', source, re.DOTALL)
        self.assertIsNotNone(m, 'renderGlobal() function not found in config.html')
        body = m.group(1)
        self.assertTrue(
            "configNav('agent'" in body or "configNav(\\'agent\\'" in body,
            "renderGlobal() agent items must call configNav('agent', ...) for navigation; "
            "currently links to artifacts.html"
        )

    def test_renderGlobal_agent_items_do_not_open_artifacts_html(self):
        """renderGlobal() agent items must NOT link directly to artifacts.html."""
        source = self._get_config_html()
        m = re.search(r'async function renderGlobal\(\)(.*?)(?=\nasync function |\nfunction )', source, re.DOTALL)
        self.assertIsNotNone(m, 'renderGlobal() function not found in config.html')
        body = m.group(1)
        # Check that the agent items section doesn't use artifacts.html for the click
        agent_section = re.search(r'agentItems\s*=.*?\.map\(function\(a\)(.*?)\);', body, re.DOTALL)
        if agent_section:
            self.assertNotIn(
                "artifacts.html",
                agent_section.group(1),
                "renderGlobal() agent items must not link to artifacts.html; use configNav('agent',...)"
            )


# ── AC4: Agent items in renderProject call configNav('agent', ...) ────────────

class TestRenderProjectAgentClicksUseConfigNav(unittest.TestCase):
    """Agent items in renderProject() must navigate to agent config screen."""

    def _get_config_html(self) -> str:
        return (_REPO_ROOT / 'bridge' / 'static' / 'config.html').read_text()

    def test_renderProject_agent_items_call_configNav_agent(self):
        """renderProject() agent items must call configNav('agent', ...) on click."""
        source = self._get_config_html()
        m = re.search(r'async function renderProject\(.*?\)(.*?)(?=\nasync function |\nfunction )', source, re.DOTALL)
        self.assertIsNotNone(m, 'renderProject() function not found in config.html')
        body = m.group(1)
        self.assertTrue(
            "configNav('agent'" in body or "configNav(\\'agent\\'" in body,
            "renderProject() agent items must call configNav('agent', ...) for navigation"
        )


# ── AC5: Agent items in renderWorkgroup call configNav('agent', ...) ──────────

class TestRenderWorkgroupAgentClicksUseConfigNav(unittest.TestCase):
    """Agent items in renderWorkgroup() must navigate to agent config screen."""

    def _get_config_html(self) -> str:
        return (_REPO_ROOT / 'bridge' / 'static' / 'config.html').read_text()

    def test_renderWorkgroup_agent_items_call_configNav_agent(self):
        """renderWorkgroup() agent items must call configNav('agent', ...) on click."""
        source = self._get_config_html()
        m = re.search(r'async function renderWorkgroup\(.*?\)(.*?)(?=\nasync function |\nfunction |\nvar urlParams)', source, re.DOTALL)
        self.assertIsNotNone(m, 'renderWorkgroup() function not found in config.html')
        body = m.group(1)
        self.assertTrue(
            "configNav('agent'" in body or "configNav(\\'agent\\'" in body,
            "renderWorkgroup() agent items must call configNav('agent', ...) for navigation"
        )


# ── AC6: URL init block handles ?agent= ──────────────────────────────────────

class TestUrlInitHandlesAgentParam(unittest.TestCase):
    """config.html page init must check ?agent= param and call renderAgent."""

    def test_live_config_html_reads_agent_url_param(self):
        """bridge/static/config.html init block must read ?agent= URL param."""
        source = (_REPO_ROOT / 'bridge' / 'static' / 'config.html').read_text()
        self.assertIn("get('agent')", source,
            "config.html init block must call urlParams.get('agent') to handle ?agent= URL")

    def test_live_config_html_calls_renderAgent_on_init(self):
        """bridge/static/config.html init block must call renderAgent when ?agent= is set."""
        source = (_REPO_ROOT / 'bridge' / 'static' / 'config.html').read_text()
        # Look for the init block at the bottom that calls renderAgent
        init_section = source[source.rfind('var urlParams'):]
        self.assertIn('renderAgent', init_section,
            "config.html init block must call renderAgent() when ?agent= param is present")

    def test_mockup_config_html_reads_agent_url_param(self):
        """mockup/config.html init block must read ?agent= URL param."""
        source = (_REPO_ROOT / 'docs' / 'proposals' / 'ui-redesign' / 'mockup' / 'config.html').read_text()
        self.assertIn("get('agent')", source,
            "mockup/config.html init block must call urlParams.get('agent')")


# ── AC7: Helper functions are defined ────────────────────────────────────────

class TestAgentHelperFunctionsDefined(unittest.TestCase):
    """patchCurrentAgent, saveAgentField, toggleAgentSkill, toggleAgentTool,
    setAgentPermissionMode must be defined in config.html."""

    def _source(self) -> str:
        return (_REPO_ROOT / 'bridge' / 'static' / 'config.html').read_text()

    def test_patchCurrentAgent_is_defined(self):
        """patchCurrentAgent() must be defined."""
        self.assertIn('function patchCurrentAgent(', self._source(),
            'config.html must define patchCurrentAgent()')

    def test_saveAgentField_is_defined(self):
        """saveAgentField() must be defined."""
        self.assertIn('function saveAgentField(', self._source(),
            'config.html must define saveAgentField()')

    def test_toggleAgentSkill_is_defined(self):
        """toggleAgentSkill() must be defined."""
        self.assertIn('function toggleAgentSkill(', self._source(),
            'config.html must define toggleAgentSkill()')

    def test_toggleAgentTool_is_defined(self):
        """toggleAgentTool() must be defined."""
        self.assertIn('function toggleAgentTool(', self._source(),
            'config.html must define toggleAgentTool()')

    def test_setAgentPermissionMode_is_defined(self):
        """setAgentPermissionMode() must be defined."""
        self.assertIn('function setAgentPermissionMode(', self._source(),
            'config.html must define setAgentPermissionMode()')


# ── AC8: AVAILABLE_TOOLS constant is defined ─────────────────────────────────

class TestAvailableToolsConstant(unittest.TestCase):
    """AVAILABLE_TOOLS must be defined with all standard Claude tool names."""

    EXPECTED_TOOLS = [
        'Read', 'Glob', 'Grep', 'Bash', 'Write', 'Edit',
        'WebSearch', 'WebFetch', 'Send', 'Reply',
        'TodoRead', 'TodoWrite',
    ]

    def _source(self) -> str:
        return (_REPO_ROOT / 'bridge' / 'static' / 'config.html').read_text()

    def test_AVAILABLE_TOOLS_is_defined(self):
        """AVAILABLE_TOOLS variable must be defined in config.html."""
        self.assertIn('AVAILABLE_TOOLS', self._source(),
            'config.html must define AVAILABLE_TOOLS constant')

    def test_AVAILABLE_TOOLS_includes_core_tools(self):
        """AVAILABLE_TOOLS must include all standard agent tools."""
        source = self._source()
        for tool in self.EXPECTED_TOOLS:
            self.assertIn(f"'{tool}'", source,
                f"AVAILABLE_TOOLS must include '{tool}'")


# ── AC9: GET /api/catalog/org returns org-level skills ───────────────────────

class TestCatalogOrgEndpoint(unittest.TestCase):
    """GET /api/catalog/org must return the org-level skill and agent catalog."""

    def setUp(self):
        import shutil
        self.tmp = tempfile.mkdtemp()
        self.tp_home = _make_teaparty_home(self.tmp)
        # Add org-level skills in tmp/.teaparty/management/skills/
        mgmt_dir = os.path.join(self.tp_home, 'management')
        skills_dir = os.path.join(mgmt_dir, 'skills')
        _make_skill_dir(skills_dir, 'commit')
        _make_skill_dir(skills_dir, 'review')
        # Add org-level agent in tmp/.teaparty/management/agents/
        agents_dir = os.path.join(mgmt_dir, 'agents')
        _make_agent_file(agents_dir, 'auditor')
        self.bridge = _make_bridge(self.tp_home, self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_catalog_org_returns_200(self):
        """GET /api/catalog/org returns HTTP 200."""
        request = _make_request_mock()
        response = _run(self.bridge._handle_catalog_org(request))
        self.assertEqual(response.status, 200,
            f'GET /api/catalog/org must return 200; got {response.status}')

    def test_catalog_org_response_has_required_keys(self):
        """GET /api/catalog/org response must contain agents, skills, and hooks keys."""
        import json as _json
        request = _make_request_mock()
        response = _run(self.bridge._handle_catalog_org(request))
        data = _json.loads(response.body)
        self.assertIn('agents', data,
            'GET /api/catalog/org response must include agents key')
        self.assertIn('skills', data,
            'GET /api/catalog/org response must include skills key')
        self.assertIn('hooks', data,
            'GET /api/catalog/org response must include hooks key')

    def test_catalog_org_returns_org_skills(self):
        """GET /api/catalog/org returns skills discovered from org .claude/skills/ directory."""
        import json as _json
        request = _make_request_mock()
        response = _run(self.bridge._handle_catalog_org(request))
        data = _json.loads(response.body)
        skills = data.get('skills', [])
        self.assertIn('commit', skills,
            f'GET /api/catalog/org must return org-level skills; got: {skills}')
        self.assertIn('review', skills,
            f'GET /api/catalog/org must return org-level skills; got: {skills}')

    def test_catalog_org_returns_org_agents(self):
        """GET /api/catalog/org returns agents discovered from org .claude/agents/ directory."""
        import json as _json
        request = _make_request_mock()
        response = _run(self.bridge._handle_catalog_org(request))
        data = _json.loads(response.body)
        agents = data.get('agents', [])
        self.assertIn('auditor', agents,
            f'GET /api/catalog/org must return org-level agents; got: {agents}')


# ── AC10: /api/catalog/org route is registered ───────────────────────────────

class TestCatalogOrgRouteRegistered(unittest.TestCase):
    """GET /api/catalog/org must be registered as an explicit route before /api/catalog/{project}."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tp_home = _make_teaparty_home(self.tmp)
        self.bridge = _make_bridge(self.tp_home, self.tmp)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_catalog_org_route_registered(self):
        """GET /api/catalog/org is registered and distinct from /api/catalog/{project}."""
        app = self.bridge._build_app()
        routes = [
            (route.method, resource.canonical)
            for resource in app.router.resources()
            for route in resource
        ]
        self.assertIn(('GET', '/api/catalog/org'), routes,
            "GET /api/catalog/org must be registered as an explicit route before /api/catalog/{project}")


# ── Behavioral content tests ──────────────────────────────────────────────────

class TestRenderAgentContentSections(unittest.TestCase):
    """_renderAgentContent() must produce all required section panels."""

    def _source(self) -> str:
        return (_REPO_ROOT / 'bridge' / 'static' / 'config.html').read_text()

    def test_renderAgentContent_produces_artifacts_section(self):
        """_renderAgentContent must call sectionCard('Artifacts', ...) for browsing agent files."""
        source = self._source()
        m = re.search(r'function _renderAgentContent\(\)(.*?)(?=\nasync function |\nfunction )', source, re.DOTALL)
        self.assertIsNotNone(m, '_renderAgentContent not found in config.html')
        body = m.group(1)
        self.assertIn("sectionCard('Artifacts'", body,
            "_renderAgentContent must render an Artifacts section for browsing agent files")

    def test_renderAgentContent_produces_skills_section(self):
        """_renderAgentContent must call sectionCard('Skills', ...) for the skill catalog panel."""
        source = self._source()
        m = re.search(r'function _renderAgentContent\(\)(.*?)(?=\nasync function |\nfunction )', source, re.DOTALL)
        self.assertIsNotNone(m, '_renderAgentContent not found in config.html')
        body = m.group(1)
        self.assertIn("sectionCard('Skills'", body,
            "_renderAgentContent must render a Skills section showing the full catalog")

    def test_renderAgentContent_produces_tools_section(self):
        """_renderAgentContent must call sectionCard('Tools', ...) for the tools panel."""
        source = self._source()
        m = re.search(r'function _renderAgentContent\(\)(.*?)(?=\nasync function |\nfunction )', source, re.DOTALL)
        self.assertIsNotNone(m, '_renderAgentContent not found in config.html')
        body = m.group(1)
        self.assertIn("sectionCard('Tools'", body,
            "_renderAgentContent must render a Tools section showing available tools")

    def test_renderAgentContent_has_permissions_in_settings(self):
        """_renderAgentContent must include a Permissions dropdown in Settings."""
        source = self._source()
        m = re.search(r'function _renderAgentContent\(\)(.*?)(?=\nasync function |\nfunction )', source, re.DOTALL)
        self.assertIsNotNone(m, '_renderAgentContent not found in config.html')
        body = m.group(1)
        self.assertIn("Permissions", body,
            "_renderAgentContent must include Permissions as a setting")

    def test_renderAgentContent_highlights_active_skills(self):
        """_renderAgentContent must apply item-catalog-active class to whitelisted skills."""
        source = self._source()
        m = re.search(r'function _renderAgentContent\(\)(.*?)(?=\nasync function |\nfunction )', source, re.DOTALL)
        self.assertIsNotNone(m, '_renderAgentContent not found in config.html')
        body = m.group(1)
        self.assertIn('item-catalog-active', body,
            "_renderAgentContent must apply item-catalog-active to whitelisted skills/tools/permissions")

    def test_renderAgentContent_shows_agent_name_in_title(self):
        """_renderAgentContent must display the agent name in the page title."""
        source = self._source()
        m = re.search(r'function _renderAgentContent\(\)(.*?)(?=\nasync function |\nfunction )', source, re.DOTALL)
        self.assertIsNotNone(m, '_renderAgentContent not found in config.html')
        body = m.group(1)
        self.assertIn('pane-title', body,
            "_renderAgentContent must render the agent name as page title")

    def test_renderAgentContent_shows_description(self):
        """_renderAgentContent must display the agent description."""
        source = self._source()
        m = re.search(r'function _renderAgentContent\(\)(.*?)(?=\nasync function |\nfunction )', source, re.DOTALL)
        self.assertIsNotNone(m, '_renderAgentContent not found in config.html')
        body = m.group(1)
        self.assertIn('pane-description', body,
            "_renderAgentContent must render the agent description")

    def test_renderAgentContent_renders_model_dropdown_with_onchange_save(self):
        """_renderAgentContent must render the model as a dropdown with onchange save."""
        source = self._source()
        m = re.search(r'function _renderAgentContent\(\)(.*?)(?=\nasync function |\nfunction )', source, re.DOTALL)
        self.assertIsNotNone(m, '_renderAgentContent not found in config.html')
        body = m.group(1)
        # In the HTML JS string, single quotes are escaped: saveAgentField(\'model\'
        self.assertIn("saveAgentField(\\'model\\'", body,
            "_renderAgentContent model dropdown must call saveAgentField('model', ...) on change")


class TestSaveAgentFieldCallsPatch(unittest.TestCase):
    """saveAgentField() must call patchCurrentAgent to persist changes to the backend."""

    def _source(self) -> str:
        return (_REPO_ROOT / 'bridge' / 'static' / 'config.html').read_text()

    def test_saveAgentField_calls_patchCurrentAgent(self):
        """saveAgentField() must call patchCurrentAgent() to persist the field change."""
        source = self._source()
        m = re.search(r'function saveAgentField\(.*?\)\s*\{(.*?)(?=\n\})', source, re.DOTALL)
        self.assertIsNotNone(m, 'saveAgentField function body not found in config.html')
        body = m.group(1)
        self.assertIn('patchCurrentAgent', body,
            "saveAgentField must call patchCurrentAgent() to persist changes via PATCH")

    def test_patchCurrentAgent_uses_patch_method(self):
        """patchCurrentAgent() must use the PATCH HTTP method to save to /api/agents/{name}."""
        source = self._source()
        m = re.search(r"function patchCurrentAgent\(.*?\)\s*\{(.*?)(?=\n\})", source, re.DOTALL)
        self.assertIsNotNone(m, 'patchCurrentAgent function body not found in config.html')
        body = m.group(1)
        self.assertIn("'PATCH'", body,
            "patchCurrentAgent must use PATCH method to update agent frontmatter")
        self.assertIn('/api/agents/', body,
            "patchCurrentAgent must POST to /api/agents/{name} endpoint")
