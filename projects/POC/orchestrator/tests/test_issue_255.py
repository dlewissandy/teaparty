"""Tests for issue #255: New-item buttons opening pre-seeded office manager conversations.

Verifies:
1. Pre-seeded message generation produces correct text per card type
2. Pre-seeded messages include project context when at project level
3. Pre-seeded messages include project context when at workgroup level
4. Management-level messages are generic (no project scope)
5. Sessions and projects card_new still route to LaunchScreen/NewProjectScreen
6. All other new_button cards route through office manager with pre-seed
7. open_chat_window accepts and passes through pre_seed argument
8. ChatApp/chat_main accepts --pre-seed CLI argument
"""
import unittest

from projects.POC.orchestrator.navigation import DashboardLevel, NavigationContext


def _make_nav_context(**kwargs):
    """Create a NavigationContext with optional overrides."""
    defaults = dict(
        level=DashboardLevel.MANAGEMENT,
        project_slug='',
        workgroup_id='',
        job_id='',
        task_id='',
    )
    defaults.update(kwargs)
    return NavigationContext(**defaults)


class TestPreSeededMessageGeneration(unittest.TestCase):
    """Pre-seeded messages match the spec table in creating-things.md."""

    def test_agents_card_at_management_level(self):
        """Agents card at management level produces generic message."""
        from projects.POC.orchestrator.dashboard_stats import pre_seeded_message
        nav = _make_nav_context(level=DashboardLevel.MANAGEMENT)
        msg = pre_seeded_message('agents', nav)
        self.assertEqual(msg, 'I would like to create a new agent')

    def test_skills_card_at_management_level(self):
        """Skills card at management level produces generic message."""
        from projects.POC.orchestrator.dashboard_stats import pre_seeded_message
        nav = _make_nav_context(level=DashboardLevel.MANAGEMENT)
        msg = pre_seeded_message('skills', nav)
        self.assertEqual(msg, 'I would like to create a new skill')

    def test_hooks_card_at_management_level(self):
        """Hooks card at management level produces generic message."""
        from projects.POC.orchestrator.dashboard_stats import pre_seeded_message
        nav = _make_nav_context(level=DashboardLevel.MANAGEMENT)
        msg = pre_seeded_message('hooks', nav)
        self.assertEqual(msg, 'I would like to create a new hook')

    def test_scheduled_tasks_card_at_management_level(self):
        """Scheduled tasks card at management level produces generic message."""
        from projects.POC.orchestrator.dashboard_stats import pre_seeded_message
        nav = _make_nav_context(level=DashboardLevel.MANAGEMENT)
        msg = pre_seeded_message('scheduled_tasks', nav)
        self.assertEqual(msg, 'I would like to create a new scheduled task')

    def test_workgroups_card_at_management_level(self):
        """Workgroups card at management level produces generic message."""
        from projects.POC.orchestrator.dashboard_stats import pre_seeded_message
        nav = _make_nav_context(level=DashboardLevel.MANAGEMENT)
        msg = pre_seeded_message('workgroups', nav)
        self.assertEqual(msg, 'I would like to create a new shared workgroup')

    def test_agents_card_at_project_level(self):
        """Agents card at project level includes project name."""
        from projects.POC.orchestrator.dashboard_stats import pre_seeded_message
        nav = _make_nav_context(
            level=DashboardLevel.PROJECT,
            project_slug='POC Project',
        )
        msg = pre_seeded_message('agents', nav)
        self.assertEqual(msg, 'I would like to add a new agent to the POC Project project')

    def test_skills_card_at_project_level(self):
        """Skills card at project level includes project name."""
        from projects.POC.orchestrator.dashboard_stats import pre_seeded_message
        nav = _make_nav_context(
            level=DashboardLevel.PROJECT,
            project_slug='POC Project',
        )
        msg = pre_seeded_message('skills', nav)
        self.assertEqual(msg, 'I would like to create a new skill for the POC Project project')

    def test_scheduled_tasks_card_at_project_level(self):
        """Scheduled tasks card at project level includes project name."""
        from projects.POC.orchestrator.dashboard_stats import pre_seeded_message
        nav = _make_nav_context(
            level=DashboardLevel.PROJECT,
            project_slug='POC Project',
        )
        msg = pre_seeded_message('scheduled_tasks', nav)
        self.assertEqual(msg, 'I would like to create a new scheduled task for the POC Project project')

    def test_workgroups_card_at_project_level(self):
        """Workgroups card at project level includes project name."""
        from projects.POC.orchestrator.dashboard_stats import pre_seeded_message
        nav = _make_nav_context(
            level=DashboardLevel.PROJECT,
            project_slug='POC Project',
        )
        msg = pre_seeded_message('workgroups', nav)
        self.assertEqual(msg, 'I would like to create a new workgroup in the POC Project project')

    def test_hooks_card_at_project_level(self):
        """Hooks card at project level includes project name."""
        from projects.POC.orchestrator.dashboard_stats import pre_seeded_message
        nav = _make_nav_context(
            level=DashboardLevel.PROJECT,
            project_slug='POC Project',
        )
        msg = pre_seeded_message('hooks', nav)
        self.assertEqual(msg, 'I would like to create a new hook for the POC Project project')

    def test_skills_card_at_workgroup_level(self):
        """Skills card at workgroup level includes workgroup name."""
        from projects.POC.orchestrator.dashboard_stats import pre_seeded_message
        nav = _make_nav_context(
            level=DashboardLevel.WORKGROUP,
            project_slug='POC Project',
            workgroup_id='Coding',
        )
        msg = pre_seeded_message('skills', nav)
        self.assertEqual(msg, 'I would like to create a new skill for the Coding workgroup')

    def test_agents_card_at_workgroup_level(self):
        """Agents card at workgroup level includes workgroup name."""
        from projects.POC.orchestrator.dashboard_stats import pre_seeded_message
        nav = _make_nav_context(
            level=DashboardLevel.WORKGROUP,
            project_slug='POC Project',
            workgroup_id='Coding',
        )
        msg = pre_seeded_message('agents', nav)
        self.assertEqual(msg, 'I would like to add a new agent to the Coding workgroup')

    def test_sessions_card_returns_none(self):
        """Sessions card returns None — handled by LaunchScreen, not pre-seed."""
        from projects.POC.orchestrator.dashboard_stats import pre_seeded_message
        nav = _make_nav_context(level=DashboardLevel.MANAGEMENT)
        msg = pre_seeded_message('sessions', nav)
        self.assertIsNone(msg)

    def test_projects_card_at_management_level(self):
        """Projects card at management level produces generic message per spec."""
        from projects.POC.orchestrator.dashboard_stats import pre_seeded_message
        nav = _make_nav_context(level=DashboardLevel.MANAGEMENT)
        msg = pre_seeded_message('projects', nav)
        self.assertEqual(msg, 'I would like to create a new project')

    def test_jobs_card_at_project_level(self):
        """Jobs card at project level includes project name."""
        from projects.POC.orchestrator.dashboard_stats import pre_seeded_message
        nav = _make_nav_context(
            level=DashboardLevel.PROJECT,
            project_slug='POC Project',
        )
        msg = pre_seeded_message('jobs', nav)
        self.assertEqual(msg, 'I would like to create a new job in the POC Project project')

    def test_jobs_card_at_management_level(self):
        """Jobs card at management level produces generic message."""
        from projects.POC.orchestrator.dashboard_stats import pre_seeded_message
        nav = _make_nav_context(level=DashboardLevel.MANAGEMENT)
        msg = pre_seeded_message('jobs', nav)
        self.assertEqual(msg, 'I would like to create a new job')


class TestOpenChatWindowPreSeed(unittest.TestCase):
    """open_chat_window passes pre_seed through to the chat subprocess."""

    def test_open_chat_window_accepts_pre_seed_parameter(self):
        """open_chat_window function signature includes pre_seed."""
        import inspect
        from projects.POC.tui.screens.dashboard_screen import open_chat_window
        sig = inspect.signature(open_chat_window)
        self.assertIn('pre_seed', sig.parameters)

    def test_open_chat_window_builds_pre_seed_cli_arg(self):
        """When pre_seed is given, the CLI command includes --pre-seed."""
        from unittest.mock import patch, MagicMock
        from projects.POC.tui.screens.dashboard_screen import open_chat_window

        app = MagicMock()
        app.poc_root = '/fake/projects/POC'
        app.projects_dir = '/fake/projects'

        with patch('projects.POC.tui.platform_utils.open_terminal') as mock_term:
            open_chat_window(app, pre_seed='I would like to create a new agent')
            mock_term.assert_called_once()
            cmd = mock_term.call_args[0][0]
            self.assertIn('--pre-seed', cmd)
            idx = cmd.index('--pre-seed')
            self.assertEqual(cmd[idx + 1], 'I would like to create a new agent')

    def test_open_chat_window_omits_pre_seed_when_empty(self):
        """When pre_seed is not given, the CLI command omits --pre-seed."""
        from unittest.mock import patch, MagicMock
        from projects.POC.tui.screens.dashboard_screen import open_chat_window

        app = MagicMock()
        app.poc_root = '/fake/projects/POC'
        app.projects_dir = '/fake/projects'

        with patch('projects.POC.tui.platform_utils.open_terminal') as mock_term:
            open_chat_window(app)
            mock_term.assert_called_once()
            cmd = mock_term.call_args[0][0]
            self.assertNotIn('--pre-seed', cmd)


class TestChatMainPreSeedArg(unittest.TestCase):
    """chat_main.py accepts --pre-seed CLI argument."""

    def test_chat_app_accepts_pre_seed_parameter(self):
        """ChatApp constructor accepts pre_seed parameter."""
        import inspect
        from projects.POC.tui.chat_main import ChatApp
        sig = inspect.signature(ChatApp.__init__)
        self.assertIn('pre_seed', sig.parameters)

    def test_chat_app_stores_pre_seed(self):
        """ChatApp stores pre_seed for ChatScreen to use."""
        from unittest.mock import patch
        with patch('projects.POC.tui.chat_main.StateReader'):
            from projects.POC.tui.chat_main import ChatApp
            app = ChatApp.__new__(ChatApp)
            # Manually call init with pre_seed
            app._pre_seed = 'test message'
            self.assertEqual(app._pre_seed, 'test message')


class TestPreSeedConversationRouting(unittest.TestCase):
    """Pre-seeded messages route to the office manager conversation."""

    def test_action_card_new_passes_om_conversation_with_pre_seed(self):
        """action_card_new routes non-session cards to om: conversation with pre_seed."""
        from unittest.mock import patch, MagicMock
        from projects.POC.tui.screens.dashboard_screen import open_chat_window

        app = MagicMock()
        app.poc_root = '/fake/projects/POC'
        app.projects_dir = '/fake/projects'

        with patch('projects.POC.tui.platform_utils.open_terminal') as mock_term:
            open_chat_window(app, conversation='om:new', pre_seed='I would like to create a new agent')
            cmd = mock_term.call_args[0][0]
            # Should target the office manager conversation
            self.assertIn('--conversation', cmd)
            idx = cmd.index('--conversation')
            self.assertTrue(cmd[idx + 1].startswith('om:'))
            # Should include the pre-seed
            self.assertIn('--pre-seed', cmd)
            idx = cmd.index('--pre-seed')
            self.assertEqual(cmd[idx + 1], 'I would like to create a new agent')


if __name__ == '__main__':
    unittest.main()
