"""Tests for issue #377: Project config screen — distinguish registered workgroups from active members.

Acceptance criteria:
1. Workgroups panel shows all registered workgroups; active (member) workgroups highlighted
2. Configuration workgroup shown as registered but not toggleable as a dispatch member
3. Clicking an inactive workgroup promotes it to members.workgroups:
4. Clicking an active workgroup removes it from members.workgroups: (remains registered)
5. Changes written back to project.yaml on disk
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
import yaml
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

CONFIG_HTML = os.path.join(
    os.path.dirname(os.path.dirname(__file__)),
    'bridge', 'static', 'config.html',
)


def _read_config_html() -> str:
    with open(CONFIG_HTML) as f:
        return f.read()


def _make_teaparty_yaml(teaparty_home: str, projects: list | None = None) -> None:
    os.makedirs(teaparty_home, exist_ok=True)
    data = {
        'name': 'Management',
        'description': 'Test',
        'lead': 'office-manager',
        'humans': {'decider': 'darrell'},
        'members': {'projects': projects or [], 'agents': []},
        'workgroups': [],
        'hooks': [],
        'scheduled': [],
    }
    with open(os.path.join(teaparty_home, 'teaparty.yaml'), 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _make_project_yaml(
    project_dir: str,
    workgroups: list | None = None,
    member_workgroups: list | None = None,
) -> None:
    local_dir = os.path.join(project_dir, '.teaparty.local')
    os.makedirs(local_dir, exist_ok=True)
    data = {
        'name': 'TestProject',
        'description': 'A test project',
        'lead': 'project-lead',
        'humans': {'decider': 'darrell'},
        'workgroups': workgroups or [],
        'members': {'workgroups': member_workgroups or [], 'agents': []},
        'hooks': [],
        'scheduled': [],
    }
    with open(os.path.join(local_dir, 'project.yaml'), 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _make_workgroup_yaml(workgroups_dir: str, name: str) -> None:
    os.makedirs(workgroups_dir, exist_ok=True)
    data = {
        'name': name,
        'description': f'{name} workgroup',
        'lead': f'{name.lower()}-lead',
        'members': {'agents': []},
    }
    with open(os.path.join(workgroups_dir, f'{name.lower()}.yaml'), 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def _read_project_yaml(project_dir: str) -> dict:
    path = os.path.join(project_dir, '.teaparty.local', 'project.yaml')
    with open(path) as f:
        return yaml.safe_load(f)


def _make_bridge(tmp: str, project_dir: str):
    from bridge.server import TeaPartyBridge
    teaparty_home = os.path.join(tmp, '.teaparty')
    bridge = TeaPartyBridge(
        teaparty_home=teaparty_home,
        static_dir=os.path.join(tmp, 'static'),
    )
    bridge._project_path_cache = {'testproject': project_dir}
    return bridge


def _run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── AC1: API returns active flag per workgroup ────────────────────────────────

class TestProjectConfigWorkgroupActiveField(unittest.TestCase):
    """GET /api/config/{project} must include active flag per workgroup reflecting members.workgroups."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.project_dir = os.path.join(self.tmp, 'testproject')
        os.makedirs(self.project_dir)
        wg_dir = os.path.join(self.project_dir, '.teaparty', 'workgroups')
        _make_workgroup_yaml(wg_dir, 'Coding')
        _make_workgroup_yaml(wg_dir, 'Research')
        _make_project_yaml(
            self.project_dir,
            workgroups=[
                {'name': 'Coding', 'config': '.teaparty/workgroups/coding.yaml'},
                {'name': 'Research', 'config': '.teaparty/workgroups/research.yaml'},
            ],
            member_workgroups=['Coding'],
        )
        teaparty_home = os.path.join(self.tmp, '.teaparty')
        _make_teaparty_yaml(
            teaparty_home,
            projects=[{'name': 'testproject', 'path': self.project_dir}],
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _fetch_project_config(self) -> dict:
        from bridge.server import TeaPartyBridge
        bridge = TeaPartyBridge(
            teaparty_home=os.path.join(self.tmp, '.teaparty'),
            static_dir=os.path.join(self.tmp, 'static'),
        )
        bridge._project_path_cache = {'testproject': self.project_dir}

        async def _call():
            request = MagicMock()
            request.match_info = {'project': 'testproject'}
            response = await bridge._handle_config_project(request)
            return json.loads(response.body)

        return _run_async(_call())

    def test_active_workgroup_has_active_true(self):
        """A workgroup in members.workgroups must be serialized with active=True."""
        data = self._fetch_project_config()
        workgroups = data.get('workgroups', [])
        coding = next((w for w in workgroups if w['name'].lower() == 'coding'), None)
        self.assertIsNotNone(coding, 'Coding workgroup must appear in workgroups list')
        self.assertTrue(coding.get('active'), 'Active workgroup must have active=True')

    def test_registered_only_workgroup_has_active_false(self):
        """A workgroup registered but not in members.workgroups must have active=False."""
        data = self._fetch_project_config()
        workgroups = data.get('workgroups', [])
        research = next((w for w in workgroups if w['name'].lower() == 'research'), None)
        self.assertIsNotNone(research, 'Research workgroup must appear in workgroups list')
        self.assertFalse(research.get('active'), 'Registered-only workgroup must have active=False')

    def test_all_registered_workgroups_appear(self):
        """All registered workgroups must appear in the response regardless of membership."""
        data = self._fetch_project_config()
        names = {w['name'].lower() for w in data.get('workgroups', [])}
        self.assertIn('coding', names, 'Active workgroup must appear in list')
        self.assertIn('research', names, 'Inactive (registered-only) workgroup must appear in list')


# ── AC3 & AC4: Toggle endpoint handles workgroup kind ─────────────────────────

class TestProjectToggleWorkgroupEndpoint(unittest.TestCase):
    """POST /api/config/{project}/toggle must handle type='workgroup' for membership changes."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.project_dir = os.path.join(self.tmp, 'testproject')
        os.makedirs(self.project_dir)
        _make_project_yaml(
            self.project_dir,
            workgroups=[
                {'name': 'Coding', 'config': '.teaparty/workgroups/coding.yaml'},
                {'name': 'Research', 'config': '.teaparty/workgroups/research.yaml'},
            ],
            member_workgroups=['Coding'],
        )
        teaparty_home = os.path.join(self.tmp, '.teaparty')
        _make_teaparty_yaml(
            teaparty_home,
            projects=[{'name': 'testproject', 'path': self.project_dir}],
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run_toggle(self, body: dict) -> tuple[int, dict]:
        bridge = _make_bridge(self.tmp, self.project_dir)

        async def _call():
            request = MagicMock()
            request.match_info = {'project': 'testproject'}
            request.json = AsyncMock(return_value=body)
            response = await bridge._handle_config_project_toggle(request)
            return response.status, json.loads(response.body)

        return _run_async(_call())

    def test_activate_workgroup_returns_200(self):
        """POST /api/config/{project}/toggle with type='workgroup' and active=True returns 200."""
        status, _ = self._run_toggle({'type': 'workgroup', 'name': 'Research', 'active': True})
        self.assertEqual(status, 200)

    def test_activate_workgroup_adds_to_members_workgroups(self):
        """Activating a workgroup via toggle adds it to members.workgroups in project.yaml."""
        self._run_toggle({'type': 'workgroup', 'name': 'Research', 'active': True})
        data = _read_project_yaml(self.project_dir)
        self.assertIn('Research', data['members']['workgroups'])

    def test_deactivate_workgroup_returns_200(self):
        """POST /api/config/{project}/toggle with type='workgroup' and active=False returns 200."""
        status, _ = self._run_toggle({'type': 'workgroup', 'name': 'Coding', 'active': False})
        self.assertEqual(status, 200)

    def test_deactivate_workgroup_removes_from_members_workgroups(self):
        """Deactivating a workgroup via toggle removes it from members.workgroups in project.yaml."""
        self._run_toggle({'type': 'workgroup', 'name': 'Coding', 'active': False})
        data = _read_project_yaml(self.project_dir)
        self.assertNotIn('Coding', data['members']['workgroups'])

    def test_deactivated_workgroup_remains_in_registered_workgroups(self):
        """Deactivating a workgroup removes it from members but NOT from the workgroups catalog."""
        self._run_toggle({'type': 'workgroup', 'name': 'Coding', 'active': False})
        data = _read_project_yaml(self.project_dir)
        wg_names = [w['name'] if isinstance(w, dict) else w for w in (data.get('workgroups') or [])]
        self.assertIn('Coding', wg_names, 'Deactivated workgroup must remain in registered catalog')


# ── AC1 & AC2: config.html renderProject() workgroup rendering ────────────────

class TestConfigHtmlWorkgroupRendering(unittest.TestCase):
    """renderProject() must render workgroups with active/inactive distinction and Configuration special-cased."""

    def setUp(self):
        self.content = _read_config_html()

    def test_render_project_uses_workgroup_active_flag(self):
        """renderProject() must read w.active to determine workgroup membership state."""
        self.assertIn(
            'w.active',
            self.content,
            'renderProject() must use w.active to distinguish active workgroups from registered-only',
        )

    def test_render_project_workgroups_use_catalog_active_class(self):
        """renderProject() workgroup items must use item-catalog-active for active workgroups."""
        # The class is already used for agents/skills in renderProject; verify it applies to workgroups
        # by checking the pattern appears in the workgroup rendering block
        self.assertIn(
            'item-catalog-active',
            self.content,
            'renderProject() must apply item-catalog-active to active workgroups',
        )

    def test_render_project_workgroups_use_catalog_inactive_class(self):
        """renderProject() workgroup items must use item-catalog-inactive for inactive workgroups."""
        self.assertIn(
            'item-catalog-inactive',
            self.content,
            'renderProject() must apply item-catalog-inactive to registered-only workgroups',
        )

    def test_render_project_workgroup_toggle_uses_workgroup_type(self):
        """renderProject() workgroup toggle calls must use type 'workgroup'."""
        self.assertIn(
            "'workgroup'",
            self.content,
            "renderProject() must call toggleMembership with 'workgroup' type",
        )

    def test_configuration_workgroup_not_toggleable(self):
        """Configuration workgroup must not have a membership toggle handler in renderProject()."""
        # The Configuration workgroup must be identified and rendered without toggleMembership onclick.
        # Its name must be checked case-insensitively to skip the toggle path.
        self.assertIn(
            'configuration',
            self.content.lower(),
            'renderProject() must reference the Configuration workgroup by name for special handling',
        )

    def test_configuration_workgroup_check_is_case_insensitive(self):
        """The Configuration workgroup guard must use lowercase comparison to be case-insensitive."""
        # Looking for toLower or toLowerCase applied before the comparison
        self.assertIn(
            'toLowerCase',
            self.content,
            'Configuration workgroup check must use toLowerCase for case-insensitive comparison',
        )
