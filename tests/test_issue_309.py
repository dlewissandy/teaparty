"""Tests for issue #309: Migrate TUI-dependent tests to bridge-compatible equivalents.

Verifies that business logic previously living in TUI modules has been extracted
to the correct orchestrator modules, making tests resilient to TUI retirement (#305).

Acceptance criteria:
1. _kill_pid, withdraw_session importable from orchestrator.withdraw
2. DashboardLevel, NavigationContext, cards_for_level importable from orchestrator.navigation
3. Dashboard stat/item functions importable from orchestrator.dashboard_stats
4. CardItem importable from orchestrator.dashboard_stats
5. check_message_bus_request, send_message_bus_response importable from orchestrator.messaging
6. tui.withdraw, tui.navigation re-export from orchestrator (backward compat)
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── 1. orchestrator.withdraw ─────────────────────────────────────────────────

class TestWithdrawImportedFromOrchestrator(unittest.TestCase):
    """_kill_pid and withdraw_session must be importable from orchestrator.withdraw."""

    def test_kill_pid_importable(self):
        from projects.POC.orchestrator.withdraw import _kill_pid
        self.assertTrue(callable(_kill_pid))

    def test_withdraw_session_importable(self):
        from projects.POC.orchestrator.withdraw import withdraw_session
        self.assertTrue(callable(withdraw_session))

    def test_kill_pid_skips_self(self):
        """_kill_pid in orchestrator behaves identically to the TUI version."""
        from projects.POC.orchestrator.withdraw import _kill_pid
        from unittest.mock import patch
        own_pid = os.getpid()
        with patch('os.killpg') as mock_killpg, patch('os.kill') as mock_kill:
            _kill_pid(own_pid)
            mock_killpg.assert_not_called()
            mock_kill.assert_not_called()


# ── 2. orchestrator.navigation ───────────────────────────────────────────────

class TestNavigationImportedFromOrchestrator(unittest.TestCase):
    """DashboardLevel, NavigationContext, cards_for_level importable from orchestrator.navigation."""

    def test_dashboard_level_importable(self):
        from projects.POC.orchestrator.navigation import DashboardLevel
        self.assertEqual(DashboardLevel.MANAGEMENT.value, 'management')

    def test_navigation_context_importable(self):
        from projects.POC.orchestrator.navigation import DashboardLevel, NavigationContext
        ctx = NavigationContext(level=DashboardLevel.MANAGEMENT)
        self.assertEqual(ctx.level, DashboardLevel.MANAGEMENT)

    def test_cards_for_level_importable(self):
        from projects.POC.orchestrator.navigation import DashboardLevel, cards_for_level
        names = cards_for_level(DashboardLevel.MANAGEMENT)
        self.assertIn('sessions', names)
        self.assertIn('escalations', names)

    def test_card_defs_for_level_importable(self):
        from projects.POC.orchestrator.navigation import DashboardLevel, card_defs_for_level
        defs = card_defs_for_level(DashboardLevel.PROJECT)
        self.assertTrue(len(defs) > 0)

    def test_breadcrumbs_for_level_importable(self):
        from projects.POC.orchestrator.navigation import (
            DashboardLevel, NavigationContext, breadcrumbs_for_level,
        )
        ctx = NavigationContext(level=DashboardLevel.MANAGEMENT)
        crumbs = breadcrumbs_for_level(ctx)
        self.assertEqual(len(crumbs), 1)


# ── 3. orchestrator.dashboard_stats ──────────────────────────────────────────

class TestDashboardStatsImportedFromOrchestrator(unittest.TestCase):
    """Stat functions and CardItem must be importable from orchestrator.dashboard_stats."""

    def test_card_item_importable(self):
        from projects.POC.orchestrator.dashboard_stats import CardItem
        item = CardItem(label='test', detail='detail')
        self.assertEqual(item.label, 'test')

    def test_compute_management_stats_importable(self):
        from projects.POC.orchestrator.dashboard_stats import compute_management_stats
        self.assertTrue(callable(compute_management_stats))

    def test_compute_project_stats_importable(self):
        from projects.POC.orchestrator.dashboard_stats import compute_project_stats
        self.assertTrue(callable(compute_project_stats))

    def test_compute_job_stats_importable(self):
        from projects.POC.orchestrator.dashboard_stats import compute_job_stats
        self.assertTrue(callable(compute_job_stats))

    def test_compute_task_stats_importable(self):
        from projects.POC.orchestrator.dashboard_stats import compute_task_stats
        self.assertTrue(callable(compute_task_stats))

    def test_format_management_stats_importable(self):
        from projects.POC.orchestrator.dashboard_stats import format_management_stats
        self.assertTrue(callable(format_management_stats))

    def test_format_job_stats_importable(self):
        from projects.POC.orchestrator.dashboard_stats import format_job_stats
        self.assertTrue(callable(format_job_stats))

    def test_format_task_stats_importable(self):
        from projects.POC.orchestrator.dashboard_stats import format_task_stats
        self.assertTrue(callable(format_task_stats))

    def test_format_stat_value_importable(self):
        from projects.POC.orchestrator.dashboard_stats import format_stat_value
        self.assertEqual(format_stat_value(None), '\u2014')
        self.assertEqual(format_stat_value(42), '42')

    def test_proxy_stats_importable(self):
        from projects.POC.orchestrator.dashboard_stats import _proxy_stats
        accuracy, chunks = _proxy_stats([])
        self.assertIsNone(accuracy)
        self.assertIsNone(chunks)

    def test_build_project_items_importable(self):
        from projects.POC.orchestrator.dashboard_stats import _build_project_items
        self.assertTrue(callable(_build_project_items))

    def test_build_escalation_items_importable(self):
        from projects.POC.orchestrator.dashboard_stats import _build_escalation_items
        self.assertTrue(callable(_build_escalation_items))

    def test_heartbeat_icon_importable(self):
        from projects.POC.orchestrator.dashboard_stats import _heartbeat_icon
        self.assertTrue(len(_heartbeat_icon('alive')) > 0)
        self.assertNotEqual(_heartbeat_icon('alive'), _heartbeat_icon('stale'))
        self.assertNotEqual(_heartbeat_icon('dead'), _heartbeat_icon('alive'))

    def test_pre_seeded_message_importable(self):
        from projects.POC.orchestrator.dashboard_stats import pre_seeded_message
        from projects.POC.orchestrator.navigation import DashboardLevel, NavigationContext
        nav = NavigationContext(level=DashboardLevel.MANAGEMENT)
        msg = pre_seeded_message('agents', nav)
        self.assertEqual(msg, 'I would like to create a new agent')


class TestDashboardStatsCorrectness(unittest.TestCase):
    """Verify stat functions produce correct results from the new orchestrator location."""

    def _make_session(self, **kwargs):
        from projects.POC.orchestrator.state_reader import SessionState
        defaults = dict(
            project='test-proj', session_id='20260329-120000',
            worktree_name='wt', worktree_path='/tmp/wt',
            task='task', status='active', cfa_phase='execution',
            cfa_state='WORK_IN_PROGRESS', cfa_actor='uber_team',
            needs_input=False, is_orphaned=False, dispatches=[],
            stream_age_seconds=10, duration_seconds=300, infra_dir='',
            backtrack_count=0,
        )
        defaults.update(kwargs)
        return SessionState(**defaults)

    def _make_dispatch(self, **kwargs):
        from projects.POC.orchestrator.state_reader import DispatchState
        defaults = dict(
            team='coding', worktree_name='wt', worktree_path='/tmp/wt',
            task='task', status='active', cfa_state='WORK_IN_PROGRESS',
            cfa_phase='execution', is_running=True, infra_dir='',
            stream_age_seconds=30, needs_input=False, heartbeat_status='alive',
        )
        defaults.update(kwargs)
        return DispatchState(**defaults)

    def _make_project(self, **kwargs):
        from projects.POC.orchestrator.state_reader import ProjectState
        defaults = dict(
            slug='test-proj', path='/tmp/proj',
            sessions=[], active_count=0, attention_count=0,
        )
        defaults.update(kwargs)
        return ProjectState(**defaults)

    def test_compute_management_stats_keys(self):
        """compute_management_stats returns all 12 expected keys."""
        from projects.POC.orchestrator.dashboard_stats import compute_management_stats
        proj = self._make_project(sessions=[self._make_session()])
        stats = compute_management_stats([proj])
        expected = {
            'jobs_done', 'tasks_done', 'active', 'one_shots',
            'backtracks', 'withdrawals', 'escalations', 'interventions',
            'proxy_accuracy', 'tokens', 'skills_learned', 'uptime',
        }
        self.assertEqual(set(stats.keys()), expected)

    def test_format_management_stats_has_twelve_entries(self):
        """format_management_stats returns 12 (label, value) pairs."""
        from projects.POC.orchestrator.dashboard_stats import format_management_stats
        proj = self._make_project(sessions=[])
        pairs = format_management_stats([proj])
        self.assertEqual(len(pairs), 12)

    def test_format_job_stats_has_five_entries(self):
        """format_job_stats returns 5 (label, value) pairs."""
        from projects.POC.orchestrator.dashboard_stats import format_job_stats
        s = self._make_session(backtrack_count=1, duration_seconds=600)
        pairs = format_job_stats(s)
        self.assertEqual(len(pairs), 5)

    def test_format_task_stats_has_two_entries(self):
        """format_task_stats returns 2 (label, value) pairs."""
        from projects.POC.orchestrator.dashboard_stats import format_task_stats
        d = self._make_dispatch(stream_age_seconds=120)
        pairs = format_task_stats(d)
        self.assertEqual(len(pairs), 2)


# ── 4. orchestrator.messaging IPC functions ────────────────────────────────

class TestIpcFunctionsInOrchestrator(unittest.TestCase):
    """check_message_bus_request and send_message_bus_response importable from orchestrator.messaging."""

    def test_check_message_bus_request_importable(self):
        from projects.POC.orchestrator.messaging import check_message_bus_request
        self.assertTrue(callable(check_message_bus_request))

    def test_send_message_bus_response_importable(self):
        from projects.POC.orchestrator.messaging import send_message_bus_response
        self.assertTrue(callable(send_message_bus_response))

    def test_check_returns_none_for_missing_db(self):
        """check_message_bus_request returns None for missing DB."""
        from projects.POC.orchestrator.messaging import check_message_bus_request
        result = check_message_bus_request('/nonexistent/path.db', 'conv')
        self.assertIsNone(result)


# ── 5. Existing test imports are migrated ────────────────────────────────────

class TestExistingTestImportsMigrated(unittest.TestCase):
    """Verify that the affected test files now import from orchestrator, not TUI."""

    def _get_test_source(self, filename):
        path = Path(__file__).parent.parent / 'projects/POC/orchestrator/tests' / filename
        return path.read_text()

    def test_issue_159_imports_kill_pid_from_orchestrator(self):
        """test_issue_159.py must import _kill_pid from orchestrator.withdraw."""
        source = self._get_test_source('test_issue_159.py')
        self.assertIn('orchestrator.withdraw', source,
                      'test_issue_159.py must import from orchestrator.withdraw')
        self.assertNotIn('tui.withdraw', source,
                         'test_issue_159.py must not import from tui.withdraw')

    def test_issue_271_checks_orchestrator_withdraw(self):
        """test_issue_271.py must check orchestrator.withdraw source, not tui.withdraw."""
        source = self._get_test_source('test_issue_271.py')
        self.assertIn('orchestrator.withdraw', source,
                      'test_issue_271.py must check orchestrator.withdraw source')
        self.assertNotIn('tui.withdraw', source,
                         'test_issue_271.py must not check tui.withdraw source')

    def test_issue_254_imports_navigation_from_orchestrator(self):
        """test_issue_254.py must import DashboardLevel from orchestrator.navigation."""
        source = self._get_test_source('test_issue_254.py')
        self.assertIn('orchestrator.navigation', source,
                      'test_issue_254.py must import from orchestrator.navigation')
        self.assertNotIn('tui.navigation', source,
                         'test_issue_254.py must not import from tui.navigation')

    def test_issue_255_imports_navigation_from_orchestrator(self):
        """test_issue_255.py must import DashboardLevel from orchestrator.navigation."""
        source = self._get_test_source('test_issue_255.py')
        self.assertIn('orchestrator.navigation', source,
                      'test_issue_255.py must import from orchestrator.navigation')
        self.assertNotIn('tui.navigation', source,
                         'test_issue_255.py must not import from tui.navigation')

    def test_issue_200_imports_ipc_from_orchestrator(self):
        """test_issue_200.py must import IPC functions from orchestrator.messaging."""
        source = self._get_test_source('test_issue_200.py')
        self.assertIn('orchestrator.messaging', source,
                      'test_issue_200.py must import from orchestrator.messaging')
        self.assertNotIn('tui.ipc', source,
                         'test_issue_200.py must not import from tui.ipc')

    def test_issue_273_imports_stats_from_orchestrator(self):
        """test_issue_273.py must import stat functions from orchestrator.dashboard_stats."""
        source = self._get_test_source('test_issue_273.py')
        self.assertIn('orchestrator.dashboard_stats', source,
                      'test_issue_273.py must import from orchestrator.dashboard_stats')
        self.assertNotIn('tui.screens.dashboard_screen', source,
                         'test_issue_273.py must not import from tui.screens.dashboard_screen')

    def test_issue_254_imports_stats_from_orchestrator(self):
        """test_issue_254.py must import dashboard functions from orchestrator.dashboard_stats."""
        source = self._get_test_source('test_issue_254.py')
        self.assertIn('orchestrator.dashboard_stats', source,
                      'test_issue_254.py must import from orchestrator.dashboard_stats')
        self.assertNotIn('tui.screens.dashboard_screen', source,
                         'test_issue_254.py must not import from tui.screens.dashboard_screen')

    def test_issue_255_imports_pre_seeded_from_orchestrator(self):
        """test_issue_255.py must import pre_seeded_message from orchestrator.dashboard_stats."""
        source = self._get_test_source('test_issue_255.py')
        self.assertIn('orchestrator.dashboard_stats', source,
                      'test_issue_255.py must import pre_seeded_message from orchestrator.dashboard_stats')
        self.assertNotIn("tui.screens.dashboard_screen import pre_seeded_message", source,
                         'test_issue_255.py must not import pre_seeded_message from tui.screens.dashboard_screen')


if __name__ == '__main__':
    unittest.main()
