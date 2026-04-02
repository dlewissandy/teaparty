"""Tests for issue #364: Config workgroups — registered in catalog but not in chain of command.

Acceptance criteria:
1. Configuration workgroup not listed under members: in teaparty.yaml or project.yaml
2. Configuration workgroup visible in catalog (registered) but not activatable as dispatch member
   — bridge API exposes active field on workgroups in project config endpoint
3. Attempting to dispatch to config workgroup via normal chain of command produces an error
4. Config workgroup remains accessible via chat blade (existing behavior, not tested here)
"""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.dispatch_cli import dispatch
from orchestrator.config_reader import ProjectTeam, WorkgroupEntry, WorkgroupRef
from scripts.cfa_state import make_initial_state, save_state, transition


# ── Helpers ────────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _make_parent_state_file(tmpdir: str) -> str:
    """Create a parent CfA state file at TASK (ready to dispatch)."""
    cfa = make_initial_state(task_id='uber-001')
    cfa = transition(cfa, 'propose')
    cfa = transition(cfa, 'auto-approve')
    cfa = transition(cfa, 'plan')
    cfa = transition(cfa, 'auto-approve')
    cfa = transition(cfa, 'delegate')
    path = os.path.join(tmpdir, '.cfa-state.json')
    save_state(cfa, path)
    return path


def _make_project_team(registered: list[str], members: list[str]) -> ProjectTeam:
    """Build a ProjectTeam with the given registered and member workgroup names."""
    workgroups = [WorkgroupEntry(name=n, config=f'.teaparty/workgroups/{n.lower()}.yaml')
                  for n in registered]
    return ProjectTeam(
        name='TestProject',
        workgroups=workgroups,
        members_workgroups=members,
    )


# ── Criterion 3: dispatch guard rejects non-member workgroups ─────────────────

class TestDispatchGuardRejectsConfigWorkgroup(unittest.TestCase):
    """dispatch() must return status=failed when team matches a registered workgroup
    that is not in members_workgroups.

    Criterion 3: attempting to dispatch to config workgroup produces an error.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _dispatch_with_project_team(self, team: str, project_team: ProjectTeam) -> dict:
        """Run dispatch with mocked project team, no real infra needed for blocked cases."""
        env = {
            'POC_PROJECT_DIR': self.tmpdir,
            'POC_SESSION_DIR': '',
            'POC_SESSION_WORKTREE': self.tmpdir,
            'POC_PROJECT': 'test',
        }
        with patch('orchestrator.dispatch_cli.load_project_team', return_value=project_team), \
             patch.dict(os.environ, env, clear=False):
            return _run(dispatch(team, 'some task', infra_dir=''))

    def test_dispatch_to_non_member_workgroup_returns_failed(self):
        """dispatch() to a registered but non-member workgroup must return status=failed."""
        team = _make_project_team(
            registered=['Coding', 'Configuration'],
            members=['Coding'],
        )
        result = self._dispatch_with_project_team('configuration', team)
        self.assertEqual(result['status'], 'failed',
            "dispatch() must return failed when team is a non-member workgroup")
        self.assertIn('registered in catalog but not an active dispatch member',
            result.get('reason', ''),
            "Error must explain the guard rule, not some unrelated failure")

    def test_dispatch_error_reason_names_the_workgroup(self):
        """The error reason must mention the workgroup name so the caller knows what was blocked."""
        team = _make_project_team(
            registered=['Coding', 'Configuration'],
            members=['Coding'],
        )
        result = self._dispatch_with_project_team('configuration', team)
        self.assertIn('configuration', result.get('reason', '').lower(),
            "Error reason must name the blocked workgroup")

    def test_dispatch_guard_uses_case_insensitive_matching(self):
        """Team name 'configuration' must match workgroup named 'Configuration'."""
        # YAML uses title-case names; phase-config.json uses lowercase team names
        team = _make_project_team(
            registered=['Configuration'],
            members=[],
        )
        result = self._dispatch_with_project_team('configuration', team)
        self.assertEqual(result['status'], 'failed',
            "Guard must match 'configuration' team name to 'Configuration' workgroup name")

    def test_dispatch_to_member_workgroup_is_not_blocked_by_guard(self):
        """dispatch() to a workgroup that IS in members_workgroups must not be blocked."""
        team = _make_project_team(
            registered=['Coding', 'Configuration'],
            members=['Coding'],
        )
        # Coding is in members — guard must not block it.
        # Without infra_dir set, dispatch will fail later (missing infra), not at the guard.
        # We verify the failure reason is NOT the guard message.
        env = {
            'POC_PROJECT_DIR': self.tmpdir,
            'POC_SESSION_DIR': '',
            'POC_SESSION_WORKTREE': self.tmpdir,
            'POC_PROJECT': 'test',
        }
        with patch('orchestrator.dispatch_cli.load_project_team', return_value=team), \
             patch.dict(os.environ, env, clear=False):
            result = _run(dispatch('coding', 'write code', infra_dir=''))

        # Guard should not trigger for a member workgroup
        reason = result.get('reason', '')
        self.assertNotIn('registered in catalog but not an active dispatch member', reason,
            "Guard must not block dispatch to a workgroup that is in members_workgroups")

    def test_dispatch_to_non_workgroup_team_is_not_blocked(self):
        """dispatch() to a team that isn't registered as a workgroup must not be blocked."""
        # 'art' is not a registered workgroup in this project
        team = _make_project_team(
            registered=['Coding', 'Configuration'],
            members=['Coding'],
        )
        env = {
            'POC_PROJECT_DIR': self.tmpdir,
            'POC_SESSION_DIR': '',
            'POC_SESSION_WORKTREE': self.tmpdir,
            'POC_PROJECT': 'test',
        }
        with patch('orchestrator.dispatch_cli.load_project_team', return_value=team), \
             patch.dict(os.environ, env, clear=False):
            result = _run(dispatch('art', 'make art', infra_dir=''))

        reason = result.get('reason', '')
        self.assertNotIn('registered in catalog but not an active dispatch member', reason,
            "Guard must not block dispatch to a team that is not a registered workgroup")

    def test_guard_skipped_when_no_project_dir(self):
        """Without POC_PROJECT_DIR, guard is skipped (no workgroup context to check)."""
        env = {
            'POC_SESSION_DIR': '',
            'POC_SESSION_WORKTREE': self.tmpdir,
            'POC_PROJECT': 'test',
        }
        # Remove POC_PROJECT_DIR from env entirely
        clean_env = {k: v for k, v in os.environ.items() if k != 'POC_PROJECT_DIR'}
        clean_env.update(env)
        with patch.dict(os.environ, clean_env, clear=True):
            result = _run(dispatch('configuration', 'configure', infra_dir=''))

        reason = result.get('reason', '')
        self.assertNotIn('registered in catalog but not an active dispatch member', reason,
            "Guard must be skipped when no project context is available")

    def test_guard_skipped_when_project_team_not_found(self):
        """If project.yaml doesn't exist, guard fails silently and dispatch proceeds."""
        env = {
            'POC_PROJECT_DIR': self.tmpdir,
            'POC_SESSION_DIR': '',
            'POC_SESSION_WORKTREE': self.tmpdir,
            'POC_PROJECT': 'test',
        }
        # project.yaml doesn't exist in tmpdir — load_project_team raises FileNotFoundError
        with patch.dict(os.environ, env, clear=False):
            result = _run(dispatch('configuration', 'configure', infra_dir=''))

        reason = result.get('reason', '')
        self.assertNotIn('registered in catalog but not an active dispatch member', reason,
            "Guard must not block when project config cannot be loaded")


class TestDispatchGuardWithWorkgroupRef(unittest.TestCase):
    """Guard must also handle WorkgroupRef entries (shared workgroups by reference)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_dispatch_to_non_member_workgroup_ref_returns_failed(self):
        """WorkgroupRef entries (shared workgroups) are also subject to the guard."""
        # Project uses a WorkgroupRef to reference a shared configuration workgroup
        team = ProjectTeam(
            name='TestProject',
            workgroups=[
                WorkgroupEntry(name='Coding', config='.teaparty/workgroups/coding.yaml'),
                WorkgroupRef(ref='configuration'),
            ],
            members_workgroups=['Coding'],
        )
        env = {
            'POC_PROJECT_DIR': self.tmpdir,
            'POC_SESSION_DIR': '',
            'POC_SESSION_WORKTREE': self.tmpdir,
            'POC_PROJECT': 'test',
        }
        with patch('orchestrator.dispatch_cli.load_project_team', return_value=team), \
             patch.dict(os.environ, env, clear=False):
            result = _run(dispatch('configuration', 'some task', infra_dir=''))

        self.assertEqual(result['status'], 'failed',
            "Guard must block WorkgroupRef workgroups not in members_workgroups")


# ── Criterion 1 & 2: YAML state and catalog visibility ───────────────────────

class TestConfigWorkgroupYamlState(unittest.TestCase):
    """Configuration workgroup must be registered but not in dispatch members.

    Criteria 1 and 2 — the YAML files must encode the catalog/dispatch distinction.
    """

    _REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _PROJECT_YAML = os.path.join(_REPO_ROOT, '.teaparty.local', 'project.yaml')
    _TEAPARTY_HOME = os.path.join(_REPO_ROOT, '.teaparty')

    def test_configuration_workgroup_registered_in_project_yaml(self):
        """Configuration workgroup must appear in project.yaml workgroups: catalog."""
        import yaml
        with open(self._PROJECT_YAML) as f:
            data = yaml.safe_load(f)
        wg_names = [wg['name'] for wg in data.get('workgroups', [])]
        self.assertIn('Configuration', wg_names,
            "Configuration must be registered in project.yaml workgroups:")

    def test_configuration_workgroup_not_in_project_members_workgroups(self):
        """Configuration must NOT appear in project.yaml members.workgroups (not a dispatch target)."""
        import yaml
        with open(self._PROJECT_YAML) as f:
            data = yaml.safe_load(f)
        members = data.get('members', {}).get('workgroups', [])
        self.assertNotIn('Configuration', members,
            "Configuration must not be in members.workgroups — project lead cannot dispatch to it")

    def test_configuration_workgroup_registered_in_teaparty_yaml(self):
        """Configuration workgroup must appear in teaparty.yaml workgroups: catalog."""
        import yaml
        with open(os.path.join(self._TEAPARTY_HOME, 'teaparty.yaml')) as f:
            data = yaml.safe_load(f)
        wg_names = [wg['name'] for wg in data.get('workgroups', [])]
        self.assertIn('Configuration', wg_names,
            "Configuration must be registered in teaparty.yaml workgroups:")

    def test_teaparty_yaml_members_has_no_workgroups_key(self):
        """OM dispatches to projects, not workgroups — members: must have no workgroups: key."""
        import yaml
        with open(os.path.join(self._TEAPARTY_HOME, 'teaparty.yaml')) as f:
            data = yaml.safe_load(f)
        members = data.get('members', {})
        self.assertNotIn('workgroups', members,
            "teaparty.yaml members: must not have workgroups: — OM dispatches to projects only")


# ── Criterion 2: bridge API exposes active field on project workgroups ────────

class TestBridgeWorkgroupActiveSerialization(unittest.TestCase):
    """_serialize_workgroup must include active field when called in project context.

    Criterion 2: configuration workgroup visible in catalog but not activatable as dispatch member.
    The active=False field signals that it is registered but not a dispatch target.
    """

    def _make_server(self):
        """Create a TeaPartyBridge instance (no listening) for method testing."""
        from bridge.server import TeaPartyBridge
        server = TeaPartyBridge.__new__(TeaPartyBridge)
        server.teaparty_home = '/fake/.teaparty'
        return server

    def _make_workgroup(self, name: str = 'Configuration') -> object:
        """Build a minimal Workgroup object."""
        from orchestrator.config_reader import Workgroup
        return Workgroup(
            name=name,
            description='Test workgroup',
            lead='config-lead',
            members_agents=['agent-a'],
        )

    def test_serialize_workgroup_with_active_false_includes_active_field(self):
        """active=False must appear in serialized workgroup dict."""
        server = self._make_server()
        wg = self._make_workgroup('Configuration')
        result = server._serialize_workgroup(wg, active=False)
        self.assertIn('active', result,
            "_serialize_workgroup must include 'active' key when active= is given")
        self.assertFalse(result['active'],
            "Serialized workgroup with active=False must have active=False")

    def test_serialize_workgroup_with_active_true_includes_active_field(self):
        """active=True must appear in serialized workgroup dict."""
        server = self._make_server()
        wg = self._make_workgroup('Coding')
        result = server._serialize_workgroup(wg, active=True)
        self.assertIn('active', result,
            "_serialize_workgroup must include 'active' key when active= is given")
        self.assertTrue(result['active'],
            "Serialized workgroup with active=True must have active=True")

    def test_serialize_workgroup_without_active_omits_field(self):
        """When active= is not given (management context), active key must not appear."""
        server = self._make_server()
        wg = self._make_workgroup()
        result = server._serialize_workgroup(wg)
        self.assertNotIn('active', result,
            "_serialize_workgroup must not include 'active' when no active= arg is given")
