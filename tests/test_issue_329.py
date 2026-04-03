"""Tests for issue #329: Config workgroup detail view — agents, skills, norms, budget cards.

Acceptance criteria:
1. Clicking a workgroup item in both global catalog and project workgroup list navigates to
   workgroup detail (onclick='configNav(workgroup, ...)' present in live page and mockup).
2. renderWorkgroup() exists in live config.html and mockup/config.html.
3. Agents list shows name, role, model; Skills list shows name and source badge.
4. Norms renders all categories read-only; Budget renders all fields read-only.
5. '+New' and '+Catalog' on Agents and Skills open OM chat.
6. Breadcrumb navigates back to parent level.
7. GET /api/workgroups/{name} returns full workgroup data (agents, skills, norms, budget).
8. GET /api/workgroups/{name} returns 404 for unknown workgroup name.
9. config.md and mockup updated: workgroup detail level in Controls table, renderWorkgroup present.
"""
import asyncio
import os
import tempfile
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).parent.parent


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _make_teaparty_home(workgroup_files=None):
    """Create a temp teaparty_home with optional workgroup YAML files."""
    import yaml
    tmp = tempfile.mkdtemp()
    tp_dir = os.path.join(tmp, '.teaparty')
    os.makedirs(tp_dir)
    mgmt_dir = os.path.join(tp_dir, 'management')
    os.makedirs(mgmt_dir)
    wg_dir = os.path.join(mgmt_dir, 'workgroups')
    os.makedirs(wg_dir)
    with open(os.path.join(mgmt_dir, 'teaparty.yaml'), 'w') as f:
        yaml.dump({'name': 'Org', 'lead': 'om', 'decider': 'om'}, f)
    if workgroup_files:
        for name, data in workgroup_files.items():
            with open(os.path.join(wg_dir, name), 'w') as fh:
                yaml.dump(data, fh)
    return tp_dir


def _make_bridge(tp_dir):
    from bridge.server import TeaPartyBridge
    static_dir = os.path.join(tp_dir, 'static')
    os.makedirs(static_dir, exist_ok=True)
    return TeaPartyBridge(teaparty_home=tp_dir, static_dir=static_dir)


def _make_workgroup(**kwargs):
    from orchestrator.config_reader import Workgroup
    defaults = dict(
        name='Coding', description='Test workgroup', lead='coding-lead',
        members_agents=[], norms={}, budget={},
    )
    defaults.update(kwargs)
    return Workgroup(**defaults)


# ── Criterion 7: _serialize_workgroup exposes full data model ─────────────────

class TestSerializeWorkgroupExposesFullDataModel(unittest.TestCase):
    """_serialize_workgroup(detail=True) must return agents, skills, norms, budget."""

    def setUp(self):
        self.tp_dir = _make_teaparty_home()
        self.bridge = _make_bridge(self.tp_dir)

    def test_agents_are_included_in_serialized_workgroup(self):
        """_serialize_workgroup(detail=True) must include the agents list."""
        wg = _make_workgroup(members_agents=['developer'])
        result = self.bridge._serialize_workgroup(wg, detail=True)
        self.assertIn('agents', result,
            '_serialize_workgroup(detail=True) must include agents; got: ' + str(list(result.keys())))
        self.assertEqual(len(result['agents']), 1)
        self.assertEqual(result['agents'][0]['name'], 'developer')

    def test_agent_fields_include_name_and_source(self):
        """Each agent entry must have name and source fields.

        Role and model are no longer in workgroup YAML (removed in #362 — they are
        per-agent concerns read from agent config files, not from workgroup YAML).
        """
        wg = _make_workgroup(members_agents=['architect'])
        result = self.bridge._serialize_workgroup(wg, detail=True)
        agent = result['agents'][0]
        self.assertEqual(agent['name'], 'architect')
        self.assertIn('source', agent)

    def test_agent_includes_source_badge(self):
        """Each agent entry in detail mode must have a source field for source badge rendering."""
        wg = _make_workgroup(members_agents=['developer'])
        result = self.bridge._serialize_workgroup(wg, detail=True)
        self.assertIn('source', result['agents'][0],
            'Each agent dict must include a source field for source badge rendering')

    def test_agent_source_is_shared_when_in_org_catalog(self):
        """Agent with name in org catalog must have source='shared'."""
        wg = _make_workgroup(members_agents=['office-manager'])
        result = self.bridge._serialize_workgroup(
            wg, detail=True, org_agents={'office-manager', 'auditor'}
        )
        self.assertEqual(result['agents'][0]['source'], 'shared',
            "Agent in org catalog must have source='shared'")

    def test_agent_source_is_local_when_not_in_org_catalog(self):
        """Agent with name not in org catalog must have source='local'."""
        wg = _make_workgroup(members_agents=['coding-lead'])
        result = self.bridge._serialize_workgroup(
            wg, detail=True, org_agents={'office-manager', 'auditor'}
        )
        self.assertEqual(result['agents'][0]['source'], 'local',
            "Agent not in org catalog must have source='local'")

    def test_skills_not_in_serialized_workgroup(self):
        """_serialize_workgroup must not include a skills key — skills removed from workgroup schema (#362)."""
        wg = _make_workgroup()
        result = self.bridge._serialize_workgroup(wg, detail=True)
        self.assertNotIn('skills', result,
            '_serialize_workgroup must not include skills — workgroup YAML no longer has skills (issue #362)')

    def test_norms_are_included_in_serialized_workgroup(self):
        """_serialize_workgroup(detail=True) must include the norms dict."""
        norms = {'quality': ['Code review required'], 'tools': ['No WebSearch']}
        wg = _make_workgroup(norms=norms)
        result = self.bridge._serialize_workgroup(wg, detail=True)
        self.assertIn('norms', result,
            '_serialize_workgroup(detail=True) must include norms; got: ' + str(list(result.keys())))
        self.assertIn('quality', result['norms'])
        self.assertIn('Code review required', result['norms']['quality'])

    def test_budget_is_included_in_serialized_workgroup(self):
        """_serialize_workgroup(detail=True) must include the budget dict."""
        budget = {'daily_tokens': 1000.0, 'max_cost_usd': 5.0}
        wg = _make_workgroup(budget=budget)
        result = self.bridge._serialize_workgroup(wg, detail=True)
        self.assertIn('budget', result,
            '_serialize_workgroup(detail=True) must include budget; got: ' + str(list(result.keys())))
        self.assertAlmostEqual(result['budget']['daily_tokens'], 1000.0)

    def test_summary_fields_still_present(self):
        """Summary fields (name, description, lead, agents_count) present in both modes."""
        wg = _make_workgroup(
            name='Editorial',
            description='Editorial team',
            lead='editor',
            members_agents=['editor'],
        )
        result = self.bridge._serialize_workgroup(wg)
        self.assertEqual(result['name'], 'Editorial')
        self.assertEqual(result['description'], 'Editorial team')
        self.assertEqual(result['lead'], 'editor')
        self.assertEqual(result['agents_count'], 1)

    def test_empty_budget_is_included_not_omitted_in_detail_mode(self):
        """budget: {} must appear in detail=True result (UI hides it; serializer must not omit)."""
        wg = _make_workgroup(budget={})
        result = self.bridge._serialize_workgroup(wg, detail=True)
        self.assertIn('budget', result,
            'budget must be present even when empty; UI decides whether to hide it')

    def test_list_mode_omits_detail_fields(self):
        """Default (detail=False) must not include agents, norms, budget."""
        wg = _make_workgroup(
            members_agents=['dev'],
            norms={'quality': ['Review required']},
            budget={'daily_tokens': 500.0},
        )
        result = self.bridge._serialize_workgroup(wg)
        self.assertNotIn('agents', result,
            'List mode must omit agents — use detail=True for the detail endpoint')
        self.assertNotIn('norms', result,
            'List mode must omit norms — use detail=True for the detail endpoint')
        self.assertNotIn('budget', result,
            'List mode must omit budget — use detail=True for the detail endpoint')


# ── Criterion 7: GET /api/workgroups/{name} endpoint ─────────────────────────

class TestWorkgroupDetailEndpointReturnsFullData(unittest.TestCase):
    """GET /api/workgroups/{name} must return a single workgroup with full detail."""

    def _make_bridge_with_workgroup(self, wg_name, wg_data):
        tp_dir = _make_teaparty_home(workgroup_files={f'{wg_name}.yaml': wg_data})
        # Register the workgroup in teaparty.yaml
        import yaml
        teaparty_yaml = os.path.join(tp_dir, 'management', 'teaparty.yaml')
        with open(teaparty_yaml) as f:
            data = yaml.safe_load(f)
        data['workgroups'] = [{'name': wg_data['name'], 'config': f'workgroups/{wg_name}.yaml'}]
        with open(teaparty_yaml, 'w') as f:
            yaml.dump(data, f)
        return _make_bridge(tp_dir)

    def test_get_workgroup_detail_returns_200(self):
        """GET /api/workgroups/{name} must return 200 for a known workgroup."""
        from aiohttp.test_utils import TestClient, TestServer

        bridge = self._make_bridge_with_workgroup('coding', {
            'name': 'Coding', 'description': 'Implementation', 'lead': 'coding-lead',
            'agents': [{'name': 'Dev', 'role': 'specialist', 'model': 'claude-sonnet-4'}],
            'skills': ['fix-issue'],
            'norms': {'quality': ['Review required']},
            'budget': {'daily_tokens': 500.0},
        })

        async def run():
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/workgroups/Coding')
                return resp.status

        self.assertEqual(_run(run()), 200,
            'GET /api/workgroups/{name} must return 200 for a known workgroup')

    def test_get_workgroup_detail_returns_agents(self):
        """GET /api/workgroups/{name} body must include agents list."""
        from aiohttp.test_utils import TestClient, TestServer

        bridge = self._make_bridge_with_workgroup('coding', {
            'name': 'Coding', 'description': 'Implementation', 'lead': 'coding-lead',
            'members': {'agents': ['developer'], 'hooks': []},
            'norms': {}, 'budget': {},
        })

        async def run():
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/workgroups/Coding')
                return await resp.json()

        body = _run(run())
        self.assertIn('agents', body,
            'GET /api/workgroups/{name} response must include agents')
        self.assertEqual(body['agents'][0]['name'], 'developer')

    def test_get_workgroup_detail_has_no_skills(self):
        """GET /api/workgroups/{name} must not include skills — removed from workgroup schema (#362)."""
        from aiohttp.test_utils import TestClient, TestServer

        bridge = self._make_bridge_with_workgroup('coding', {
            'name': 'Coding', 'description': 'Implementation', 'lead': 'coding-lead',
            'members': {'agents': [], 'hooks': []},
            'norms': {}, 'budget': {},
        })

        async def run():
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/workgroups/Coding')
                return await resp.json()

        body = _run(run())
        self.assertNotIn('skills', body,
            'GET /api/workgroups/{name} must not include skills — removed in issue #362')

    def test_get_workgroup_detail_returns_norms(self):
        """GET /api/workgroups/{name} body must include norms dict."""
        from aiohttp.test_utils import TestClient, TestServer

        bridge = self._make_bridge_with_workgroup('coding', {
            'name': 'Coding', 'description': 'Implementation', 'lead': 'coding-lead',
            'members': {'agents': [], 'hooks': []},
            'norms': {'quality': ['Code review required']},
            'budget': {},
        })

        async def run():
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/workgroups/Coding')
                return await resp.json()

        body = _run(run())
        self.assertIn('norms', body,
            'GET /api/workgroups/{name} response must include norms')
        self.assertIn('quality', body['norms'])

    def test_get_workgroup_detail_returns_budget(self):
        """GET /api/workgroups/{name} body must include budget dict."""
        from aiohttp.test_utils import TestClient, TestServer

        bridge = self._make_bridge_with_workgroup('coding', {
            'name': 'Coding', 'description': 'Implementation', 'lead': 'coding-lead',
            'members': {'agents': [], 'hooks': []},
            'norms': {},
            'budget': {'daily_tokens': 1000.0},
        })

        async def run():
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/workgroups/Coding')
                return await resp.json()

        body = _run(run())
        self.assertIn('budget', body,
            'GET /api/workgroups/{name} response must include budget')

    def test_get_workgroup_detail_route_is_registered(self):
        """GET /api/workgroups/{name} must be registered as an explicit route."""
        tp_dir = _make_teaparty_home()
        bridge = _make_bridge(tp_dir)
        app = bridge._build_app()
        routes = [
            resource.canonical
            for resource in app.router.resources()
            for route in resource
            if route.method == 'GET'
        ]
        self.assertIn('/api/workgroups/{name}', routes,
            'GET /api/workgroups/{name} must be a registered route in _build_app')


# ── Criterion 8: 404 for unknown workgroup ────────────────────────────────────

class TestWorkgroupDetailEndpoint404(unittest.TestCase):
    """GET /api/workgroups/{name} must return 404 for an unknown workgroup name."""

    def test_get_unknown_workgroup_returns_404(self):
        """GET /api/workgroups/nonexistent must return 404."""
        from aiohttp.test_utils import TestClient, TestServer

        tp_dir = _make_teaparty_home()
        bridge = _make_bridge(tp_dir)

        async def run():
            app = bridge._build_app()
            async with TestClient(TestServer(app)) as client:
                resp = await client.get('/api/workgroups/nonexistent-workgroup')
                return resp.status

        self.assertEqual(_run(run()), 404,
            'GET /api/workgroups/{name} must return 404 for an unknown workgroup')


# ── Criterion 1: config.html workgroup items have onclick for navigation ───────

class TestConfigHtmlWorkgroupItemsHaveOnclick(unittest.TestCase):
    """Workgroup items in renderGlobal() and renderProject() must have onclick configNav('workgroup',...)."""

    def _get_config_html(self) -> str:
        path = _REPO_ROOT / 'bridge' / 'static' / 'config.html'
        self.assertTrue(path.exists(), f'config.html not found at {path}')
        return path.read_text()

    def test_global_workgroup_items_have_workgroup_onclick(self):
        """Workgroup items in the global catalog must have onclick to navigate to workgroup detail."""
        source = self._get_config_html()
        # In the JS template string, single quotes are backslash-escaped: configNav(\'workgroup\'
        self.assertTrue(
            "configNav('workgroup'" in source or "configNav(\\'workgroup\\'" in source,
            "config.html must have configNav('workgroup', ...) for workgroup navigation",
        )

    def test_configNav_handles_workgroup_level(self):
        """configNav must handle level === 'workgroup' in its switch/if logic."""
        source = self._get_config_html()
        self.assertIn("'workgroup'", source,
            "configNav in config.html must handle 'workgroup' navigation level")


# ── Criterion 2: renderWorkgroup() exists in live page ────────────────────────

class TestRenderWorkgroupFunctionExists(unittest.TestCase):
    """renderWorkgroup() must be defined in both live config.html and mockup/config.html."""

    def test_live_config_html_has_renderWorkgroup(self):
        """bridge/static/config.html must define renderWorkgroup()."""
        path = _REPO_ROOT / 'bridge' / 'static' / 'config.html'
        source = path.read_text()
        self.assertIn('renderWorkgroup', source,
            'bridge/static/config.html must define renderWorkgroup() function')

    def test_mockup_config_html_has_renderWorkgroup(self):
        """docs/proposals/ui-redesign/mockup/config.html must define renderWorkgroup()."""
        path = _REPO_ROOT / 'docs' / 'proposals' / 'ui-redesign' / 'mockup' / 'config.html'
        source = path.read_text()
        self.assertIn('renderWorkgroup', source,
            'mockup/config.html must define renderWorkgroup() function')


# ── Criterion 9: config.md documents workgroup detail level ──────────────────

class TestConfigMdDocumentsWorkgroupDetailLevel(unittest.TestCase):
    """config.md must document the workgroup detail level and its Controls entry."""

    def _get_config_md(self) -> str:
        path = _REPO_ROOT / 'docs' / 'proposals' / 'ui-redesign' / 'references' / 'config.md'
        self.assertTrue(path.exists(), f'config.md not found at {path}')
        return path.read_text()

    def test_config_md_has_workgroup_config_section(self):
        """config.md must have a Workgroup Config section describing the detail level."""
        source = self._get_config_md()
        self.assertIn('Workgroup', source,
            'config.md must document the Workgroup detail level')

    def test_config_md_controls_table_has_workgroup_entry(self):
        """The Controls table in config.md must include the workgroup click-to-drill action."""
        source = self._get_config_md()
        # Must mention clicking a workgroup item to drill down
        self.assertIn('workgroup', source.lower(),
            'config.md Controls table must include a workgroup drill-down entry')

    def test_config_md_mentions_three_level_nav(self):
        """config.md must describe the three-level nav: global → project → workgroup."""
        source = self._get_config_md()
        # The doc should acknowledge the three navigation levels
        self.assertTrue(
            'workgroup' in source.lower() and 'global' in source.lower(),
            'config.md must describe the full three-level navigation path including workgroup',
        )


# ── Criterion 6: breadcrumb navigates back to parent ─────────────────────────

class TestWorkgroupDetailBreadcrumb(unittest.TestCase):
    """renderWorkgroup() must include a breadcrumb that links back to the parent level."""

    def _get_config_html(self) -> str:
        path = _REPO_ROOT / 'bridge' / 'static' / 'config.html'
        return path.read_text()

    def test_renderWorkgroup_includes_breadcrumb_bar(self):
        """renderWorkgroup must produce a breadcrumb-bar navigating to parent."""
        source = self._get_config_html()
        # renderWorkgroup must include breadcrumb-bar markup
        self.assertIn('breadcrumb-bar', source,
            'renderWorkgroup must include a breadcrumb-bar element for back navigation')

    def test_renderWorkgroup_breadcrumb_links_to_global_config(self):
        """Breadcrumb in renderWorkgroup must include a 'Global Config' link."""
        source = self._get_config_html()
        self.assertIn('Global Config', source,
            'renderWorkgroup breadcrumb must include Global Config link')


# ── Criterion 3 & 5: renderWorkgroup renders Agents with source badges ────────

class TestRenderWorkgroupRendersAgentsAndSkills(unittest.TestCase):
    """renderWorkgroup must render Agents and Skills cards with source badges, + New, + Catalog."""

    def _get_config_html(self) -> str:
        return (_REPO_ROOT / 'bridge' / 'static' / 'config.html').read_text()

    def _get_renderWorkgroup_body(self) -> str:
        """Extract the renderWorkgroup function body from config.html."""
        source = self._get_config_html()
        start = source.find('async function renderWorkgroup(')
        self.assertNotEqual(start, -1, 'renderWorkgroup function not found in config.html')
        # Find the next top-level function or end of script to bound the body
        end = source.find('\nasync function ', start + 1)
        if end == -1:
            end = source.find('\nvar urlParams', start)
        return source[start:end] if end != -1 else source[start:]

    def test_renderWorkgroup_does_not_render_norms_section(self):
        """renderWorkgroup must not render inline Norms — norms are managed via chat blade (#368)."""
        source = self._get_renderWorkgroup_body()
        self.assertNotIn("sectionCard('Norms'", source,
            "renderWorkgroup must not render inline Norms section — norms managed via chat blade (#368)")

    def test_renderWorkgroup_does_not_render_budget_section(self):
        """renderWorkgroup must not render inline Budget — budget is managed via chat blade (#368)."""
        source = self._get_renderWorkgroup_body()
        self.assertNotIn("sectionCard('Budget'", source,
            "renderWorkgroup must not render inline Budget section — budget managed via chat blade (#368)")

    def test_renderWorkgroup_renders_agents_with_source_badge(self):
        """renderWorkgroup must call sourceBadge with a.source for agent source badge."""
        source = self._get_renderWorkgroup_body()
        self.assertIn('sourceBadge(', source,
            "renderWorkgroup must call sourceBadge for agent source badge (SC#3)")
        self.assertIn('a.source', source,
            "renderWorkgroup must reference a.source for agent source badge (SC#3)")

    def test_renderWorkgroup_renders_hooks_panel(self):
        """renderWorkgroup must render a Hooks section — workgroups have no skills (issue #367)."""
        source = self._get_renderWorkgroup_body()
        self.assertIn("'Hooks'", source,
            "renderWorkgroup must render a Hooks section card (workgroups have no skills per spec)")


if __name__ == '__main__':
    unittest.main()
