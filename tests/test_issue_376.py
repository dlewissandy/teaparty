"""Tests for issue #376: Management config screen — distinguish registered projects from active members.

Acceptance criteria:
1. Projects panel shows all registered projects; active (member) projects highlighted
2. Clicking an inactive project promotes it to members.projects:
3. Clicking an active project removes it from members.projects: (remains registered)
4. Workgroups panel at management level follows the same pattern
5. Changes written back to teaparty.yaml on disk
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
import yaml
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.config_reader import (
    ManagementTeam,
    load_management_team,
    toggle_management_membership,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_tmpdir():
    return tempfile.mkdtemp()


def _make_teaparty_yaml(teaparty_home: str, data: dict) -> str:
    os.makedirs(teaparty_home, exist_ok=True)
    path = os.path.join(teaparty_home, 'teaparty.yaml')
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    return path


def _make_workgroup_yaml(directory: str, name: str, lead: str = 'wg-lead') -> str:
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f'{name}.yaml')
    data = {
        'name': name,
        'description': f'{name} workgroup',
        'lead': lead,
        'members': {'agents': [], 'hooks': []},
        'artifacts': [],
    }
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    return path


def _make_bridge(tmpdir: str):
    from bridge.server import TeaPartyBridge

    teaparty_home = os.path.join(tmpdir, '.teaparty')
    os.makedirs(teaparty_home, exist_ok=True)
    static_dir = os.path.join(tmpdir, 'static')
    os.makedirs(static_dir, exist_ok=True)

    class _TestBridge(TeaPartyBridge):
        def _lookup_project_path(self, slug):
            path = os.path.join(tmpdir, slug)
            return path if os.path.isdir(path) else None

    return _TestBridge(teaparty_home=teaparty_home, static_dir=static_dir)


def _minimal_management_data(**overrides) -> dict:
    data = {
        'name': 'Management',
        'description': 'Test',
        'lead': 'office-manager',
        'humans': {'decider': 'darrell'},
        'projects': [],
        'members': {'projects': [], 'agents': [], 'workgroups': []},
        'workgroups': [],
        'hooks': [],
        'scheduled': [],
    }
    data.update(overrides)
    return data


# ── AC4: ManagementTeam.members_workgroups is parsed from members.workgroups ──

class TestManagementTeamHasMembersWorkgroupsField(unittest.TestCase):
    """ManagementTeam must have a members_workgroups field populated from members.workgroups."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        data = _minimal_management_data(
            workgroups=[
                {'name': 'Configuration', 'config': 'workgroups/configuration.yaml'},
                {'name': 'Coding', 'config': 'workgroups/coding.yaml'},
            ],
            members={
                'projects': [],
                'agents': [],
                'workgroups': ['Configuration'],
            },
        )
        self._home = os.path.join(self._tmpdir, '.teaparty')
        _make_teaparty_yaml(self._home, data)
        self.team = load_management_team(teaparty_home=self._home)

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_management_team_has_members_workgroups_attribute(self):
        """ManagementTeam must expose a members_workgroups attribute."""
        self.assertTrue(
            hasattr(self.team, 'members_workgroups'),
            'ManagementTeam must have a members_workgroups field',
        )

    def test_active_workgroup_is_in_members_workgroups(self):
        """A workgroup listed under members.workgroups in YAML appears in members_workgroups."""
        self.assertIn('Configuration', self.team.members_workgroups)

    def test_inactive_workgroup_is_not_in_members_workgroups(self):
        """A workgroup registered but absent from members.workgroups is not in members_workgroups."""
        self.assertNotIn('Coding', self.team.members_workgroups)

    def test_members_workgroups_is_list(self):
        """members_workgroups must be a list."""
        self.assertIsInstance(self.team.members_workgroups, list)


class TestManagementTeamMembersWorkgroupsAbsentBlock(unittest.TestCase):
    """ManagementTeam with no members.workgroups must not raise."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_absent_members_workgroups_yields_empty_list(self):
        """No members.workgroups key → members_workgroups is empty list."""
        data = _minimal_management_data(members={'projects': [], 'agents': []})
        home = os.path.join(self._tmpdir, '.teaparty')
        _make_teaparty_yaml(home, data)
        team = load_management_team(teaparty_home=home)
        self.assertTrue(hasattr(team, 'members_workgroups'))
        self.assertEqual(team.members_workgroups, [])

    def test_absent_members_block_yields_empty_members_workgroups(self):
        """No members: key at all → members_workgroups is empty list."""
        data = {
            'name': 'Management',
            'lead': 'office-manager',
            'humans': {'decider': 'darrell'},
        }
        home = os.path.join(self._tmpdir, '.teaparty2')
        _make_teaparty_yaml(home, data)
        team = load_management_team(teaparty_home=home)
        self.assertEqual(getattr(team, 'members_workgroups', None), [])


# ── AC4/5: toggle_management_membership supports 'workgroup' kind ─────────────

class TestToggleManagementMembershipWorkgroup(unittest.TestCase):
    """toggle_management_membership must support kind='workgroup' to toggle members.workgroups."""

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        data = _minimal_management_data(
            workgroups=[
                {'name': 'Configuration', 'config': 'workgroups/configuration.yaml'},
                {'name': 'Coding', 'config': 'workgroups/coding.yaml'},
            ],
            members={
                'projects': [],
                'agents': [],
                'workgroups': ['Configuration'],
            },
        )
        self._home = os.path.join(self._tmpdir, '.teaparty')
        _make_teaparty_yaml(self._home, data)

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def test_activate_workgroup_adds_to_members_workgroups(self):
        """Activating an inactive workgroup adds it to members.workgroups in YAML."""
        toggle_management_membership(self._home, 'workgroup', 'Coding', True)
        team = load_management_team(teaparty_home=self._home)
        self.assertIn('Coding', team.members_workgroups)

    def test_deactivate_workgroup_removes_from_members_workgroups(self):
        """Deactivating an active workgroup removes it from members.workgroups in YAML."""
        toggle_management_membership(self._home, 'workgroup', 'Configuration', False)
        team = load_management_team(teaparty_home=self._home)
        self.assertNotIn('Configuration', team.members_workgroups)

    def test_deactivated_workgroup_remains_in_registered_workgroups(self):
        """Deactivating a workgroup keeps it registered; it's still in the workgroups catalog."""
        toggle_management_membership(self._home, 'workgroup', 'Configuration', False)
        team = load_management_team(teaparty_home=self._home)
        registered_names = [w.name for w in team.workgroups]
        self.assertIn('Configuration', registered_names)

    def test_activating_already_active_workgroup_is_idempotent(self):
        """Activating an already-active workgroup does not duplicate it."""
        toggle_management_membership(self._home, 'workgroup', 'Configuration', True)
        team = load_management_team(teaparty_home=self._home)
        self.assertEqual(team.members_workgroups.count('Configuration'), 1)

    def test_deactivating_inactive_workgroup_is_safe(self):
        """Deactivating a workgroup not in members.workgroups does not raise."""
        toggle_management_membership(self._home, 'workgroup', 'Coding', False)
        team = load_management_team(teaparty_home=self._home)
        self.assertNotIn('Coding', team.members_workgroups)

    def test_toggling_workgroup_preserves_other_members(self):
        """Toggling workgroup active state must not alter members.agents or members.projects."""
        data = _minimal_management_data(
            workgroups=[{'name': 'Coding', 'config': 'workgroups/coding.yaml'}],
            members={
                'projects': ['TeaParty'],
                'agents': ['auditor', 'researcher'],
                'workgroups': [],
            },
        )
        _make_teaparty_yaml(self._home, data)
        toggle_management_membership(self._home, 'workgroup', 'Coding', True)
        team = load_management_team(teaparty_home=self._home)
        self.assertEqual(team.members_agents, ['auditor', 'researcher'])
        self.assertEqual(team.members_projects, ['TeaParty'])


# ── AC4: _handle_workgroups returns active flag ──────────────────────────────

class TestHandleWorkgroupsReturnsActiveFlag(unittest.IsolatedAsyncioTestCase):
    """GET /api/workgroups must include active: bool on each workgroup entry."""

    def setUp(self):
        self._tmpdir = _make_tmpdir()
        self._home = os.path.join(self._tmpdir, '.teaparty')

        wg_dir = os.path.join(self._home, 'workgroups')
        _make_workgroup_yaml(wg_dir, 'Configuration')
        _make_workgroup_yaml(wg_dir, 'Coding')

        data = _minimal_management_data(
            workgroups=[
                {'name': 'Configuration', 'config': 'workgroups/Configuration.yaml'},
                {'name': 'Coding', 'config': 'workgroups/Coding.yaml'},
            ],
            members={
                'projects': [],
                'agents': [],
                'workgroups': ['Configuration'],
            },
        )
        _make_teaparty_yaml(self._home, data)
        self._bridge = _make_bridge(self._tmpdir)

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    async def test_handle_workgroups_includes_active_field(self):
        """Each entry in the _handle_workgroups response must have an 'active' key."""
        resp = await self._bridge._handle_workgroups(MagicMock())
        data = json.loads(resp.body)
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0, 'Expected at least one workgroup in response')
        for entry in data:
            self.assertIn('active', entry, f"Workgroup {entry.get('name')} missing 'active' field")

    async def test_active_workgroup_has_active_true(self):
        """A workgroup in members.workgroups must have active=True in the response."""
        resp = await self._bridge._handle_workgroups(MagicMock())
        data = json.loads(resp.body)
        config_entry = next((w for w in data if w['name'] == 'Configuration'), None)
        self.assertIsNotNone(config_entry, 'Configuration workgroup not found in response')
        self.assertTrue(config_entry['active'],
            'Configuration is in members.workgroups and must have active=True')

    async def test_inactive_workgroup_has_active_false(self):
        """A workgroup NOT in members.workgroups must have active=False in the response."""
        resp = await self._bridge._handle_workgroups(MagicMock())
        data = json.loads(resp.body)
        coding_entry = next((w for w in data if w['name'] == 'Coding'), None)
        self.assertIsNotNone(coding_entry, 'Coding workgroup not found in response')
        self.assertFalse(coding_entry['active'],
            'Coding is not in members.workgroups and must have active=False')


# ── AC4: _handle_config_management_toggle accepts 'workgroup' kind ─────────

class TestManagementToggleAcceptsWorkgroupKind(unittest.IsolatedAsyncioTestCase):
    """POST /api/config/management/toggle must accept type='workgroup'."""

    def setUp(self):
        self._tmpdir = _make_tmpdir()
        self._home = os.path.join(self._tmpdir, '.teaparty')

        wg_dir = os.path.join(self._home, 'workgroups')
        _make_workgroup_yaml(wg_dir, 'coding')

        data = _minimal_management_data(
            workgroups=[{'name': 'Coding', 'config': 'workgroups/coding.yaml'}],
            members={'projects': [], 'agents': [], 'workgroups': []},
        )
        _make_teaparty_yaml(self._home, data)
        self._bridge = _make_bridge(self._tmpdir)

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _mock_request(self, body: dict) -> MagicMock:
        req = MagicMock()

        async def _json():
            return body

        req.json = _json
        return req

    async def test_toggle_workgroup_active_returns_ok(self):
        """POST with type='workgroup' must return HTTP 200 with {ok: True}."""
        req = self._mock_request({'type': 'workgroup', 'name': 'Coding', 'active': True})
        resp = await self._bridge._handle_config_management_toggle(req)
        data = json.loads(resp.body)
        self.assertEqual(resp.status, 200,
            f'Expected 200 but got {resp.status}: type=workgroup must be accepted')
        self.assertTrue(data.get('ok'), "Response body must be {'ok': True}")

    async def test_toggle_workgroup_inactive_returns_ok(self):
        """POST with type='workgroup' and active=False must return HTTP 200."""
        req = self._mock_request({'type': 'workgroup', 'name': 'Coding', 'active': False})
        resp = await self._bridge._handle_config_management_toggle(req)
        self.assertEqual(resp.status, 200,
            f'Deactivating workgroup must return 200, got {resp.status}')

    async def test_toggle_workgroup_persists_to_yaml(self):
        """Toggling workgroup active through the endpoint must write to teaparty.yaml."""
        req = self._mock_request({'type': 'workgroup', 'name': 'Coding', 'active': True})
        await self._bridge._handle_config_management_toggle(req)
        team = load_management_team(teaparty_home=self._home)
        self.assertIn('Coding', team.members_workgroups,
            'After toggle endpoint call, Coding must be in members_workgroups')

    async def test_invalid_type_still_returns_400(self):
        """POST with an unrecognized type must still return HTTP 400."""
        req = self._mock_request({'type': 'invalid_kind', 'name': 'Coding', 'active': True})
        resp = await self._bridge._handle_config_management_toggle(req)
        self.assertEqual(resp.status, 400)
