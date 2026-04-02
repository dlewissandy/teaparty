"""Tests for issue #375: Bridge API endpoints for workgroup config, agent config, and catalog.

Acceptance criteria:
1. GET /api/workgroups/{name} returns full workgroup including catalog and active members
2. PATCH /api/workgroups/{name} writes membership changes to YAML and returns updated state
3. GET /api/agents/{name} returns agent frontmatter as structured JSON
4. PATCH /api/agents/{name} writes frontmatter changes to .md without touching prose body
5. GET /api/catalog/{project} returns merged catalog for the project
6. All endpoints covered by specification-based tests
"""
import asyncio
import json
import os
import shutil
import tempfile
import unittest

import yaml


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_workgroup_yaml(
    path: str,
    agents: list,
    hooks: list | None = None,
    humans: dict | None = None,
    artifacts: list | None = None,
) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    name = os.path.basename(path).replace('.yaml', '')
    data = {
        'name': name,
        'description': 'Test workgroup',
        'lead': 'auditor',
        'members': {
            'agents': agents,
            'hooks': hooks or [],
        },
    }
    if humans is not None:
        data['humans'] = humans
    if artifacts is not None:
        data['artifacts'] = artifacts
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _read_workgroup_yaml(path: str) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _make_agent_file(agents_dir: str, name: str, frontmatter: dict | None = None, body: str = '') -> str:
    os.makedirs(agents_dir, exist_ok=True)
    path = os.path.join(agents_dir, f'{name}.md')
    if frontmatter is None:
        frontmatter = {'name': name, 'description': f'The {name} agent', 'model': 'opus', 'maxTurns': 20}
    fm_str = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False).rstrip()
    prose = body if body else f'\nYou are the {name}.\n'
    with open(path, 'w') as f:
        f.write(f'---\n{fm_str}\n---\n{prose}')
    return path


def _make_skill_dir(skills_dir: str, name: str) -> None:
    skill_path = os.path.join(skills_dir, name)
    os.makedirs(skill_path, exist_ok=True)
    with open(os.path.join(skill_path, 'SKILL.md'), 'w') as f:
        f.write(f'# {name}\n')


def _make_settings_json(claude_dir: str, hooks: list[dict]) -> None:
    os.makedirs(claude_dir, exist_ok=True)
    settings: dict = {'hooks': {}}
    for h in hooks:
        event = h['event']
        matcher = h.get('matcher', '')
        if event not in settings['hooks']:
            settings['hooks'][event] = []
        group = next(
            (g for g in settings['hooks'][event] if g.get('matcher') == matcher),
            None,
        )
        if group is None:
            group = {'matcher': matcher, 'hooks': []}
            settings['hooks'][event].append(group)
        group['hooks'].append({'type': h.get('type', 'command'), 'command': h.get('command', '')})
    with open(os.path.join(claude_dir, 'settings.json'), 'w') as f:
        json.dump(settings, f)


def _make_bridge(teaparty_home: str, tmp: str):
    from bridge.server import TeaPartyBridge
    static_dir = os.path.join(tmp, 'static')
    os.makedirs(static_dir, exist_ok=True)
    return TeaPartyBridge(teaparty_home=teaparty_home, static_dir=static_dir)


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── AC3/6: read_agent_frontmatter ─────────────────────────────────────────────

class TestReadAgentFrontmatter(unittest.TestCase):
    """read_agent_frontmatter must parse frontmatter from .md file and return a dict."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reads_frontmatter_fields(self):
        """read_agent_frontmatter returns all frontmatter fields from .md file."""
        from orchestrator.config_reader import read_agent_frontmatter
        path = _make_agent_file(
            self.tmp,
            'auditor',
            frontmatter={'name': 'auditor', 'description': 'Audit agent', 'model': 'opus', 'maxTurns': 10},
        )
        result = read_agent_frontmatter(path)
        self.assertEqual(result['name'], 'auditor')
        self.assertEqual(result['description'], 'Audit agent')
        self.assertEqual(result['model'], 'opus')
        self.assertEqual(result['maxTurns'], 10)

    def test_returns_empty_dict_when_no_frontmatter(self):
        """read_agent_frontmatter returns {} for .md files without a frontmatter block."""
        from orchestrator.config_reader import read_agent_frontmatter
        path = os.path.join(self.tmp, 'bare.md')
        with open(path, 'w') as f:
            f.write('No frontmatter here\n')
        result = read_agent_frontmatter(path)
        self.assertEqual(result, {})

    def test_raises_file_not_found_for_missing_file(self):
        """read_agent_frontmatter raises FileNotFoundError when the file does not exist."""
        from orchestrator.config_reader import read_agent_frontmatter
        with self.assertRaises(FileNotFoundError):
            read_agent_frontmatter(os.path.join(self.tmp, 'nonexistent.md'))

    def test_does_not_return_prose_body(self):
        """read_agent_frontmatter returns only frontmatter, not the prose body."""
        from orchestrator.config_reader import read_agent_frontmatter
        path = _make_agent_file(
            self.tmp,
            'researcher',
            frontmatter={'name': 'researcher', 'model': 'sonnet'},
            body='\nYou are the researcher. Your job is to research things.\n',
        )
        result = read_agent_frontmatter(path)
        self.assertNotIn('Your job is to research', str(result))


# ── AC4/6: write_agent_frontmatter ───────────────────────────────────────────

class TestWriteAgentFrontmatter(unittest.TestCase):
    """write_agent_frontmatter must update frontmatter fields while preserving prose body."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_updates_named_field(self):
        """write_agent_frontmatter updates a specified frontmatter field."""
        from orchestrator.config_reader import read_agent_frontmatter, write_agent_frontmatter
        path = _make_agent_file(
            self.tmp,
            'auditor',
            frontmatter={'name': 'auditor', 'model': 'opus', 'maxTurns': 20},
        )
        write_agent_frontmatter(path, {'model': 'sonnet'})
        result = read_agent_frontmatter(path)
        self.assertEqual(result['model'], 'sonnet')

    def test_preserves_unmodified_frontmatter_fields(self):
        """write_agent_frontmatter does not remove frontmatter fields not in the update."""
        from orchestrator.config_reader import read_agent_frontmatter, write_agent_frontmatter
        path = _make_agent_file(
            self.tmp,
            'auditor',
            frontmatter={'name': 'auditor', 'model': 'opus', 'maxTurns': 20, 'description': 'orig'},
        )
        write_agent_frontmatter(path, {'model': 'sonnet'})
        result = read_agent_frontmatter(path)
        self.assertEqual(result['name'], 'auditor')
        self.assertEqual(result['maxTurns'], 20)
        self.assertEqual(result['description'], 'orig')

    def test_preserves_prose_body(self):
        """write_agent_frontmatter does not alter the prose body after the frontmatter block."""
        from orchestrator.config_reader import write_agent_frontmatter
        prose = '\nYou are the auditor. Do auditing work.\nSecond paragraph.\n'
        path = _make_agent_file(
            self.tmp,
            'auditor',
            frontmatter={'name': 'auditor', 'model': 'opus'},
            body=prose,
        )
        write_agent_frontmatter(path, {'model': 'haiku'})
        with open(path) as f:
            content = f.read()
        self.assertIn(prose, content)

    def test_updates_integer_field(self):
        """write_agent_frontmatter correctly writes integer maxTurns."""
        from orchestrator.config_reader import read_agent_frontmatter, write_agent_frontmatter
        path = _make_agent_file(
            self.tmp,
            'auditor',
            frontmatter={'name': 'auditor', 'maxTurns': 20},
        )
        write_agent_frontmatter(path, {'maxTurns': 50})
        result = read_agent_frontmatter(path)
        self.assertEqual(result['maxTurns'], 50)
        self.assertIsInstance(result['maxTurns'], int)


# ── AC1/6: GET /api/workgroups/{name} route registration ─────────────────────

class TestWorkgroupDetailRouteRegistered(unittest.TestCase):
    """GET /api/workgroups/{name} must be registered as a GET route."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bridge = _make_bridge(os.path.join(self.tmp, '.teaparty'), self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_get_workgroups_name_route_registered(self):
        """GET /api/workgroups/{name} is registered as an explicit GET route."""
        app = self.bridge._build_app()
        routes = [
            (route.method, resource.canonical)
            for resource in app.router.resources()
            for route in resource
        ]
        self.assertIn(('GET', '/api/workgroups/{name}'), routes)


# ── AC2/6: PATCH /api/workgroups/{name} route registration ───────────────────

class TestWorkgroupPatchRouteRegistered(unittest.TestCase):
    """PATCH /api/workgroups/{name} must be registered as an explicit route."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bridge = _make_bridge(os.path.join(self.tmp, '.teaparty'), self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_patch_workgroups_name_route_registered(self):
        """PATCH /api/workgroups/{name} is registered."""
        app = self.bridge._build_app()
        routes = [
            (route.method, resource.canonical)
            for resource in app.router.resources()
            for route in resource
        ]
        self.assertIn(('PATCH', '/api/workgroups/{name}'), routes)


# ── AC3/6: GET /api/agents/{name} route registration ─────────────────────────

class TestAgentDetailRouteRegistered(unittest.TestCase):
    """GET /api/agents/{name} must be registered."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bridge = _make_bridge(os.path.join(self.tmp, '.teaparty'), self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_get_agents_name_route_registered(self):
        """GET /api/agents/{name} is registered as an explicit GET route."""
        app = self.bridge._build_app()
        routes = [
            (route.method, resource.canonical)
            for resource in app.router.resources()
            for route in resource
        ]
        self.assertIn(('GET', '/api/agents/{name}'), routes)


# ── AC4/6: PATCH /api/agents/{name} route registration ───────────────────────

class TestAgentPatchRouteRegistered(unittest.TestCase):
    """PATCH /api/agents/{name} must be registered."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bridge = _make_bridge(os.path.join(self.tmp, '.teaparty'), self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_patch_agents_name_route_registered(self):
        """PATCH /api/agents/{name} is registered as an explicit PATCH route."""
        app = self.bridge._build_app()
        routes = [
            (route.method, resource.canonical)
            for resource in app.router.resources()
            for route in resource
        ]
        self.assertIn(('PATCH', '/api/agents/{name}'), routes)


# ── AC5/6: GET /api/catalog/{project} route registration ─────────────────────

class TestCatalogRouteRegistered(unittest.TestCase):
    """GET /api/catalog/{project} must be registered."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.bridge = _make_bridge(os.path.join(self.tmp, '.teaparty'), self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_get_catalog_project_route_registered(self):
        """GET /api/catalog/{project} is registered as an explicit GET route."""
        app = self.bridge._build_app()
        routes = [
            (route.method, resource.canonical)
            for resource in app.router.resources()
            for route in resource
        ]
        self.assertIn(('GET', '/api/catalog/{project}'), routes)


# ── AC1/6: GET /api/workgroups/{name} returns full workgroup ──────────────────

class TestWorkgroupDetailReturnsFullData(unittest.TestCase):
    """GET /api/workgroups/{name} must return full workgroup with catalog and active members."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.teaparty_home = os.path.join(self.tmp, '.teaparty')
        wg_dir = os.path.join(self.teaparty_home, 'workgroups')
        os.makedirs(wg_dir, exist_ok=True)
        self.wg_path = os.path.join(wg_dir, 'coding.yaml')
        _make_workgroup_yaml(self.wg_path, agents=['auditor'], hooks=['PreToolUse'])
        # Create agent files in org catalog
        org_agents_dir = os.path.join(self.tmp, '.claude', 'agents')
        _make_agent_file(org_agents_dir, 'auditor')
        _make_agent_file(org_agents_dir, 'researcher')
        # Create org hooks
        _make_settings_json(os.path.join(self.tmp, '.claude'), [
            {'event': 'PreToolUse', 'matcher': '', 'command': 'echo pre'},
            {'event': 'PostToolUse', 'matcher': '', 'command': 'echo post'},
        ])
        # Management team yaml (minimal) — config path is relative to teaparty_home
        mgmt_data = {
            'name': 'Management',
            'workgroups': [{'name': 'coding', 'config': 'workgroups/coding.yaml'}],
            'members': {'agents': []},
        }
        with open(os.path.join(self.teaparty_home, 'teaparty.yaml'), 'w') as f:
            yaml.dump(mgmt_data, f, default_flow_style=False, sort_keys=False)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_detail(self, wg_name: str) -> tuple[int, dict]:
        from unittest.mock import MagicMock
        bridge = _make_bridge(self.teaparty_home, self.tmp)

        async def _call():
            request = MagicMock()
            request.match_info = {'name': wg_name}
            request.rel_url.query.get = MagicMock(return_value=None)
            response = await bridge._handle_workgroup_detail(request)
            return response.status, json.loads(response.body)

        return _run_async(_call())

    def test_returns_200(self):
        """GET /api/workgroups/{name} returns 200 for a known workgroup."""
        status, _ = self._run_detail('coding')
        self.assertEqual(status, 200)

    def test_returns_agents_list_with_active_flag(self):
        """GET /api/workgroups/{name} returns agents list where active members are flagged."""
        _, body = self._run_detail('coding')
        self.assertIn('agents', body)
        active_agents = [a for a in body['agents'] if a.get('active')]
        active_names = [a['name'] for a in active_agents]
        self.assertIn('auditor', active_names)

    def test_returns_inactive_catalog_agents(self):
        """GET /api/workgroups/{name} includes catalog agents not in members (active=False)."""
        _, body = self._run_detail('coding')
        all_names = [a['name'] for a in body['agents']]
        self.assertIn('researcher', all_names)
        researcher = next(a for a in body['agents'] if a['name'] == 'researcher')
        self.assertFalse(researcher['active'])

    def test_returns_hooks_with_active_flag(self):
        """GET /api/workgroups/{name} returns hooks list with active flag set."""
        _, body = self._run_detail('coding')
        self.assertIn('hooks', body)
        pre_hooks = [h for h in body['hooks'] if h.get('event') == 'PreToolUse']
        self.assertTrue(len(pre_hooks) > 0)
        self.assertTrue(pre_hooks[0]['active'])

    def test_returns_inactive_hooks_in_catalog(self):
        """GET /api/workgroups/{name} includes hooks not in members with active=False."""
        _, body = self._run_detail('coding')
        post_hooks = [h for h in body['hooks'] if h.get('event') == 'PostToolUse']
        self.assertTrue(len(post_hooks) > 0)
        self.assertFalse(post_hooks[0]['active'])

    def test_returns_404_for_unknown_workgroup(self):
        """GET /api/workgroups/{name} returns 404 for an unknown workgroup name."""
        status, body = self._run_detail('no-such-workgroup')
        self.assertEqual(status, 404)


class TestWorkgroupDetailIncludesHumansAndArtifacts(unittest.TestCase):
    """GET /api/workgroups/{name} must include humans and artifacts in detail response."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.teaparty_home = os.path.join(self.tmp, '.teaparty')
        wg_dir = os.path.join(self.teaparty_home, 'workgroups')
        os.makedirs(wg_dir, exist_ok=True)
        self.wg_path = os.path.join(wg_dir, 'coding.yaml')
        _make_workgroup_yaml(
            self.wg_path,
            agents=['auditor'],
            humans={'decider': 'darrell', 'advisors': ['alice']},
            artifacts=[{'path': 'NORMS.md'}, {'path': 'docs/', 'label': 'Docs'}],
        )
        org_agents_dir = os.path.join(self.tmp, '.claude', 'agents')
        _make_agent_file(org_agents_dir, 'auditor')
        mgmt_data = {
            'name': 'Management',
            'workgroups': [{'name': 'coding', 'config': 'workgroups/coding.yaml'}],
            'members': {'agents': []},
        }
        with open(os.path.join(self.teaparty_home, 'teaparty.yaml'), 'w') as f:
            yaml.dump(mgmt_data, f, default_flow_style=False, sort_keys=False)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_detail(self, wg_name: str) -> tuple[int, dict]:
        from unittest.mock import MagicMock
        bridge = _make_bridge(self.teaparty_home, self.tmp)

        async def _call():
            request = MagicMock()
            request.match_info = {'name': wg_name}
            request.rel_url.query.get = MagicMock(return_value=None)
            response = await bridge._handle_workgroup_detail(request)
            return response.status, json.loads(response.body)

        return _run_async(_call())

    def test_returns_humans_in_detail_response(self):
        """GET /api/workgroups/{name} includes humans list in detail response."""
        _, body = self._run_detail('coding')
        self.assertIn('humans', body)

    def test_humans_contains_decider_with_role(self):
        """GET /api/workgroups/{name} humans list includes the decider with role."""
        _, body = self._run_detail('coding')
        deciders = [h for h in body['humans'] if h.get('role') == 'decider']
        self.assertTrue(len(deciders) > 0)
        self.assertEqual(deciders[0]['name'], 'darrell')

    def test_humans_contains_advisor_with_role(self):
        """GET /api/workgroups/{name} humans list includes advisors with role."""
        _, body = self._run_detail('coding')
        advisors = [h for h in body['humans'] if h.get('role') == 'advisor']
        self.assertTrue(len(advisors) > 0)
        self.assertEqual(advisors[0]['name'], 'alice')

    def test_returns_artifacts_in_detail_response(self):
        """GET /api/workgroups/{name} includes artifacts list in detail response."""
        _, body = self._run_detail('coding')
        self.assertIn('artifacts', body)

    def test_artifacts_contains_pinned_paths(self):
        """GET /api/workgroups/{name} artifacts list includes pinned file paths."""
        _, body = self._run_detail('coding')
        paths = [a.get('path') for a in body['artifacts']]
        self.assertIn('NORMS.md', paths)
        self.assertIn('docs/', paths)


# ── AC2/6: PATCH /api/workgroups/{name} writes membership changes ─────────────

class TestWorkgroupPatchWritesMembership(unittest.TestCase):
    """PATCH /api/workgroups/{name} must write membership changes to YAML."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.teaparty_home = os.path.join(self.tmp, '.teaparty')
        wg_dir = os.path.join(self.teaparty_home, 'workgroups')
        os.makedirs(wg_dir, exist_ok=True)
        self.wg_path = os.path.join(wg_dir, 'coding.yaml')
        _make_workgroup_yaml(self.wg_path, agents=['auditor'], hooks=['PreToolUse'])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_patch(self, wg_name: str, body: dict) -> tuple[int, dict]:
        from unittest.mock import AsyncMock, MagicMock
        bridge = _make_bridge(self.teaparty_home, self.tmp)

        async def _call():
            request = MagicMock()
            request.match_info = {'name': wg_name}
            request.rel_url.query.get = MagicMock(return_value=None)
            request.json = AsyncMock(return_value=body)
            response = await bridge._handle_workgroup_patch(request)
            return response.status, json.loads(response.body)

        return _run_async(_call())

    def test_patch_agents_writes_yaml(self):
        """PATCH /api/workgroups/{name} with agents list writes to workgroup YAML."""
        self._run_patch('coding', {'agents': ['auditor', 'researcher']})
        data = _read_workgroup_yaml(self.wg_path)
        self.assertIn('researcher', data['members']['agents'])

    def test_patch_agents_replaces_existing_list(self):
        """PATCH /api/workgroups/{name} replaces the agents list (not append)."""
        self._run_patch('coding', {'agents': ['researcher']})
        data = _read_workgroup_yaml(self.wg_path)
        self.assertNotIn('auditor', data['members']['agents'])
        self.assertIn('researcher', data['members']['agents'])

    def test_patch_returns_200(self):
        """PATCH /api/workgroups/{name} returns 200 on success."""
        status, _ = self._run_patch('coding', {'agents': ['auditor']})
        self.assertEqual(status, 200)

    def test_patch_returns_updated_workgroup_state(self):
        """PATCH /api/workgroups/{name} response reflects the updated membership."""
        _, body = self._run_patch('coding', {'agents': ['researcher']})
        self.assertIn('agents', body)
        active = [a['name'] for a in body['agents'] if a.get('active')]
        self.assertIn('researcher', active)

    def test_patch_partial_update_preserves_hooks(self):
        """PATCH /api/workgroups/{name} with only agents does not overwrite hooks."""
        self._run_patch('coding', {'agents': ['researcher']})
        data = _read_workgroup_yaml(self.wg_path)
        self.assertIn('PreToolUse', data['members'].get('hooks', []))

    def test_patch_hooks_writes_yaml(self):
        """PATCH /api/workgroups/{name} with hooks list writes to workgroup YAML."""
        self._run_patch('coding', {'hooks': ['PostToolUse']})
        data = _read_workgroup_yaml(self.wg_path)
        self.assertIn('PostToolUse', data['members']['hooks'])

    def test_patch_returns_404_for_unknown_workgroup(self):
        """PATCH /api/workgroups/{name} returns 404 for an unknown workgroup."""
        status, _ = self._run_patch('no-such-workgroup', {'agents': []})
        self.assertEqual(status, 404)

    def test_patch_returns_400_for_invalid_body(self):
        """PATCH /api/workgroups/{name} returns 400 when agents is not a list."""
        status, _ = self._run_patch('coding', {'agents': 'not-a-list'})
        self.assertEqual(status, 400)


# ── AC3/6: GET /api/agents/{name} returns frontmatter ────────────────────────

class TestAgentDetailEndpoint(unittest.TestCase):
    """GET /api/agents/{name} must return agent frontmatter as structured JSON."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.teaparty_home = os.path.join(self.tmp, '.teaparty')
        os.makedirs(self.teaparty_home, exist_ok=True)
        # Create org-level agent
        org_agents_dir = os.path.join(self.tmp, '.claude', 'agents')
        _make_agent_file(
            org_agents_dir, 'auditor',
            frontmatter={'name': 'auditor', 'description': 'The auditor', 'model': 'opus', 'maxTurns': 20},
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_get(self, name: str, project: str | None = None) -> tuple[int, dict]:
        from unittest.mock import MagicMock
        bridge = _make_bridge(self.teaparty_home, self.tmp)

        async def _call():
            request = MagicMock()
            request.match_info = {'name': name}
            request.rel_url.query.get = MagicMock(return_value=project)
            response = await bridge._handle_agent_detail(request)
            return response.status, json.loads(response.body)

        return _run_async(_call())

    def test_returns_200_for_known_agent(self):
        """GET /api/agents/{name} returns 200 for a known org-level agent."""
        status, _ = self._run_get('auditor')
        self.assertEqual(status, 200)

    def test_returns_frontmatter_fields(self):
        """GET /api/agents/{name} returns all frontmatter fields as structured JSON."""
        _, body = self._run_get('auditor')
        self.assertEqual(body['name'], 'auditor')
        self.assertEqual(body['model'], 'opus')
        self.assertEqual(body['maxTurns'], 20)

    def test_returns_404_for_unknown_agent(self):
        """GET /api/agents/{name} returns 404 when the agent does not exist."""
        status, _ = self._run_get('no-such-agent')
        self.assertEqual(status, 404)

    def test_returns_project_level_agent_first(self):
        """GET /api/agents/{name}?project=x returns project-level agent when it exists."""
        self.project_dir = os.path.join(self.tmp, 'myproject')
        proj_agents_dir = os.path.join(self.project_dir, '.claude', 'agents')
        _make_agent_file(
            proj_agents_dir, 'auditor',
            frontmatter={'name': 'auditor', 'description': 'Project auditor', 'model': 'haiku'},
        )
        bridge = _make_bridge(self.teaparty_home, self.tmp)
        bridge._project_path_cache = {'myproject': self.project_dir}

        async def _call():
            from unittest.mock import MagicMock
            request = MagicMock()
            request.match_info = {'name': 'auditor'}
            request.rel_url.query.get = MagicMock(return_value='myproject')
            response = await bridge._handle_agent_detail(request)
            return response.status, json.loads(response.body)

        status, body = _run_async(_call())
        self.assertEqual(status, 200)
        self.assertEqual(body['model'], 'haiku')

    def test_falls_back_to_org_agent_when_no_project_level(self):
        """GET /api/agents/{name}?project=x returns org agent if not overridden at project."""
        self.project_dir = os.path.join(self.tmp, 'myproject')
        os.makedirs(os.path.join(self.project_dir, '.claude', 'agents'), exist_ok=True)
        bridge = _make_bridge(self.teaparty_home, self.tmp)
        bridge._project_path_cache = {'myproject': self.project_dir}

        async def _call():
            from unittest.mock import MagicMock
            request = MagicMock()
            request.match_info = {'name': 'auditor'}
            request.rel_url.query.get = MagicMock(return_value='myproject')
            response = await bridge._handle_agent_detail(request)
            return response.status, json.loads(response.body)

        status, body = _run_async(_call())
        self.assertEqual(status, 200)
        self.assertEqual(body['model'], 'opus')


# ── AC4/6: PATCH /api/agents/{name} writes frontmatter ───────────────────────

class TestAgentPatchEndpoint(unittest.TestCase):
    """PATCH /api/agents/{name} must update frontmatter without touching prose body."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.teaparty_home = os.path.join(self.tmp, '.teaparty')
        os.makedirs(self.teaparty_home, exist_ok=True)
        org_agents_dir = os.path.join(self.tmp, '.claude', 'agents')
        self.agent_path = _make_agent_file(
            org_agents_dir, 'auditor',
            frontmatter={'name': 'auditor', 'model': 'opus', 'maxTurns': 20},
            body='\nYou are the auditor. Review code carefully.\n',
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_patch(self, name: str, body: dict, project: str | None = None) -> tuple[int, dict]:
        from unittest.mock import AsyncMock, MagicMock
        bridge = _make_bridge(self.teaparty_home, self.tmp)

        async def _call():
            request = MagicMock()
            request.match_info = {'name': name}
            request.rel_url.query.get = MagicMock(return_value=project)
            request.json = AsyncMock(return_value=body)
            response = await bridge._handle_agent_patch(request)
            return response.status, json.loads(response.body)

        return _run_async(_call())

    def test_patch_returns_200(self):
        """PATCH /api/agents/{name} returns 200 on success."""
        status, _ = self._run_patch('auditor', {'model': 'sonnet'})
        self.assertEqual(status, 200)

    def test_patch_updates_frontmatter_on_disk(self):
        """PATCH /api/agents/{name} writes the updated frontmatter to the .md file."""
        from orchestrator.config_reader import read_agent_frontmatter
        self._run_patch('auditor', {'model': 'sonnet'})
        result = read_agent_frontmatter(self.agent_path)
        self.assertEqual(result['model'], 'sonnet')

    def test_patch_returns_updated_frontmatter(self):
        """PATCH /api/agents/{name} response contains the updated frontmatter."""
        _, body = self._run_patch('auditor', {'model': 'sonnet'})
        self.assertEqual(body['model'], 'sonnet')

    def test_patch_preserves_prose_body_on_disk(self):
        """PATCH /api/agents/{name} does not alter the prose body of the .md file."""
        self._run_patch('auditor', {'model': 'sonnet'})
        with open(self.agent_path) as f:
            content = f.read()
        self.assertIn('You are the auditor. Review code carefully.', content)

    def test_patch_returns_404_for_unknown_agent(self):
        """PATCH /api/agents/{name} returns 404 when the agent does not exist."""
        status, _ = self._run_patch('no-such-agent', {'model': 'sonnet'})
        self.assertEqual(status, 404)

    def test_patch_preserves_unmodified_fields(self):
        """PATCH /api/agents/{name} preserves frontmatter fields not in the update."""
        from orchestrator.config_reader import read_agent_frontmatter
        self._run_patch('auditor', {'model': 'sonnet'})
        result = read_agent_frontmatter(self.agent_path)
        self.assertEqual(result['maxTurns'], 20)
        self.assertEqual(result['name'], 'auditor')


# ── AC5/6: GET /api/catalog/{project} returns merged catalog ─────────────────

class TestCatalogEndpoint(unittest.TestCase):
    """GET /api/catalog/{project} must return merged catalog for the project."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.teaparty_home = os.path.join(self.tmp, '.teaparty')
        self.project_dir = os.path.join(self.tmp, 'myproject')
        os.makedirs(self.teaparty_home, exist_ok=True)
        os.makedirs(self.project_dir, exist_ok=True)

        # Org-level agents + skills + hooks
        org_claude = os.path.join(self.tmp, '.claude')
        _make_agent_file(os.path.join(org_claude, 'agents'), 'auditor')
        _make_agent_file(os.path.join(org_claude, 'agents'), 'researcher')
        _make_skill_dir(os.path.join(org_claude, 'skills'), 'commit')
        _make_settings_json(org_claude, [
            {'event': 'PostToolUse', 'matcher': '', 'command': 'echo org'},
        ])

        # Project-level agent + skill
        proj_claude = os.path.join(self.project_dir, '.claude')
        _make_agent_file(os.path.join(proj_claude, 'agents'), 'domain-expert')
        _make_skill_dir(os.path.join(proj_claude, 'skills'), 'deploy')

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_catalog(self, slug: str) -> tuple[int, dict]:
        from unittest.mock import MagicMock
        bridge = _make_bridge(self.teaparty_home, self.tmp)
        bridge._project_path_cache = {'myproject': self.project_dir}

        async def _call():
            request = MagicMock()
            request.match_info = {'project': slug}
            response = await bridge._handle_catalog(request)
            return response.status, json.loads(response.body)

        return _run_async(_call())

    def test_returns_200(self):
        """GET /api/catalog/{project} returns 200 for a known project."""
        status, _ = self._run_catalog('myproject')
        self.assertEqual(status, 200)

    def test_returns_agents_key(self):
        """GET /api/catalog/{project} response includes agents list."""
        _, body = self._run_catalog('myproject')
        self.assertIn('agents', body)

    def test_returns_skills_key(self):
        """GET /api/catalog/{project} response includes skills list."""
        _, body = self._run_catalog('myproject')
        self.assertIn('skills', body)

    def test_returns_hooks_key(self):
        """GET /api/catalog/{project} response includes hooks list."""
        _, body = self._run_catalog('myproject')
        self.assertIn('hooks', body)

    def test_catalog_includes_org_agents(self):
        """GET /api/catalog/{project} includes management-level agents."""
        _, body = self._run_catalog('myproject')
        self.assertIn('auditor', body['agents'])
        self.assertIn('researcher', body['agents'])

    def test_catalog_includes_project_agents(self):
        """GET /api/catalog/{project} includes project-level agents."""
        _, body = self._run_catalog('myproject')
        self.assertIn('domain-expert', body['agents'])

    def test_catalog_includes_org_skills(self):
        """GET /api/catalog/{project} includes management-level skills."""
        _, body = self._run_catalog('myproject')
        self.assertIn('commit', body['skills'])

    def test_catalog_includes_project_skills(self):
        """GET /api/catalog/{project} includes project-level skills."""
        _, body = self._run_catalog('myproject')
        self.assertIn('deploy', body['skills'])

    def test_catalog_includes_hooks(self):
        """GET /api/catalog/{project} includes hooks from the org catalog."""
        _, body = self._run_catalog('myproject')
        events = [h['event'] for h in body['hooks']]
        self.assertIn('PostToolUse', events)

    def test_returns_404_for_unknown_project(self):
        """GET /api/catalog/{project} returns 404 for an unknown project slug."""
        status, _ = self._run_catalog('no-such-project')
        self.assertEqual(status, 404)
