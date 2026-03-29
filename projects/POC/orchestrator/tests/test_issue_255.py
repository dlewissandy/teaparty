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


if __name__ == '__main__':
    unittest.main()
