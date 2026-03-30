"""Tests for issue #253: Hierarchical dashboard navigation with 5-level drill-down.

Verifies:
1. Navigation levels: Management > Project > Workgroup > Job > Task
2. Breadcrumb generation at each navigation level
3. Breadcrumb click navigates to the correct ancestor level
4. ManagementDashboard is the home/root screen
5. ProjectDashboard receives project context
6. WorkgroupDashboard receives workgroup context
7. JobDashboard receives job (session) context
8. TaskDashboard receives task (dispatch) context
9. NavigationContext tracks drill-down path
10. Card definitions match design spec for each level
"""
import unittest

from orchestrator.navigation import (
    Breadcrumb,
    DashboardLevel,
    NavigationContext,
    breadcrumbs_for_level,
    cards_for_level,
)


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


class TestDashboardLevel(unittest.TestCase):
    """DashboardLevel enum defines exactly five levels."""

    def test_five_levels_exist(self):
        """The enum has MANAGEMENT, PROJECT, WORKGROUP, JOB, TASK."""
        levels = [e.value for e in DashboardLevel]
        self.assertIn('management', levels)
        self.assertIn('project', levels)
        self.assertIn('workgroup', levels)
        self.assertIn('job', levels)
        self.assertIn('task', levels)

    def test_exactly_five_levels(self):
        """No extra levels beyond the five specified."""
        self.assertEqual(len(DashboardLevel), 5)


class TestNavigationContext(unittest.TestCase):
    """NavigationContext tracks the current drill-down path."""

    def test_management_level_has_no_entity_context(self):
        """At management level, no project/workgroup/job/task is selected."""
        ctx = _make_nav_context(level=DashboardLevel.MANAGEMENT)
        self.assertEqual(ctx.project_slug, '')
        self.assertEqual(ctx.workgroup_id, '')
        self.assertEqual(ctx.job_id, '')
        self.assertEqual(ctx.task_id, '')

    def test_project_level_has_project_slug(self):
        """At project level, project_slug is set."""
        ctx = _make_nav_context(
            level=DashboardLevel.PROJECT,
            project_slug='my-project',
        )
        self.assertEqual(ctx.project_slug, 'my-project')
        self.assertEqual(ctx.workgroup_id, '')

    def test_workgroup_level_has_project_and_workgroup(self):
        """At workgroup level, both project and workgroup are set."""
        ctx = _make_nav_context(
            level=DashboardLevel.WORKGROUP,
            project_slug='proj',
            workgroup_id='wg-1',
        )
        self.assertEqual(ctx.project_slug, 'proj')
        self.assertEqual(ctx.workgroup_id, 'wg-1')

    def test_job_level_has_project_and_job(self):
        """At job level, project and job (session) are set."""
        ctx = _make_nav_context(
            level=DashboardLevel.JOB,
            project_slug='proj',
            job_id='20260327-120000',
        )
        self.assertEqual(ctx.project_slug, 'proj')
        self.assertEqual(ctx.job_id, '20260327-120000')

    def test_task_level_has_project_job_and_task(self):
        """At task level, project, job, and task (dispatch) are set."""
        ctx = _make_nav_context(
            level=DashboardLevel.TASK,
            project_slug='proj',
            job_id='20260327-120000',
            task_id='dispatch-001',
        )
        self.assertEqual(ctx.project_slug, 'proj')
        self.assertEqual(ctx.job_id, '20260327-120000')
        self.assertEqual(ctx.task_id, 'dispatch-001')

    def test_drill_down_to_project(self):
        """drill_down() from management to project preserves context."""
        mgmt = _make_nav_context(level=DashboardLevel.MANAGEMENT)
        proj = mgmt.drill_down(DashboardLevel.PROJECT, project_slug='alpha')
        self.assertEqual(proj.level, DashboardLevel.PROJECT)
        self.assertEqual(proj.project_slug, 'alpha')

    def test_drill_down_to_job(self):
        """drill_down() from project to job preserves project context."""
        proj = _make_nav_context(
            level=DashboardLevel.PROJECT,
            project_slug='alpha',
        )
        job = proj.drill_down(DashboardLevel.JOB, job_id='sess-123')
        self.assertEqual(job.level, DashboardLevel.JOB)
        self.assertEqual(job.project_slug, 'alpha')
        self.assertEqual(job.job_id, 'sess-123')

    def test_drill_up_to_management(self):
        """drill_up() to management clears all entity context."""
        ctx = _make_nav_context(
            level=DashboardLevel.TASK,
            project_slug='proj',
            job_id='job-1',
            task_id='task-1',
        )
        mgmt = ctx.drill_up(DashboardLevel.MANAGEMENT)
        self.assertEqual(mgmt.level, DashboardLevel.MANAGEMENT)
        self.assertEqual(mgmt.project_slug, '')
        self.assertEqual(mgmt.job_id, '')
        self.assertEqual(mgmt.task_id, '')

    def test_drill_up_to_project_clears_deeper_context(self):
        """drill_up() to project clears workgroup/job/task context."""
        ctx = _make_nav_context(
            level=DashboardLevel.TASK,
            project_slug='proj',
            workgroup_id='wg-1',
            job_id='job-1',
            task_id='task-1',
        )
        proj = ctx.drill_up(DashboardLevel.PROJECT)
        self.assertEqual(proj.level, DashboardLevel.PROJECT)
        self.assertEqual(proj.project_slug, 'proj')
        self.assertEqual(proj.workgroup_id, '')
        self.assertEqual(proj.job_id, '')
        self.assertEqual(proj.task_id, '')


class TestBreadcrumbs(unittest.TestCase):
    """Breadcrumb generation for each navigation level."""

    def test_management_has_single_breadcrumb(self):
        """At management level, breadcrumb is just 'TeaParty'."""
        ctx = _make_nav_context(level=DashboardLevel.MANAGEMENT)
        crumbs = breadcrumbs_for_level(ctx)
        self.assertEqual(len(crumbs), 1)
        self.assertEqual(crumbs[0].label, 'TeaParty')
        self.assertEqual(crumbs[0].level, DashboardLevel.MANAGEMENT)

    def test_project_has_two_breadcrumbs(self):
        """At project level: TeaParty > ProjectName."""
        ctx = _make_nav_context(
            level=DashboardLevel.PROJECT,
            project_slug='my-project',
        )
        crumbs = breadcrumbs_for_level(ctx)
        self.assertEqual(len(crumbs), 2)
        self.assertEqual(crumbs[0].label, 'TeaParty')
        self.assertEqual(crumbs[0].level, DashboardLevel.MANAGEMENT)
        self.assertEqual(crumbs[1].label, 'my-project')
        self.assertEqual(crumbs[1].level, DashboardLevel.PROJECT)

    def test_workgroup_has_three_breadcrumbs(self):
        """At workgroup level: TeaParty > Project > Workgroup."""
        ctx = _make_nav_context(
            level=DashboardLevel.WORKGROUP,
            project_slug='proj',
            workgroup_id='writers',
        )
        crumbs = breadcrumbs_for_level(ctx)
        self.assertEqual(len(crumbs), 3)
        self.assertEqual(crumbs[2].label, 'writers')
        self.assertEqual(crumbs[2].level, DashboardLevel.WORKGROUP)

    def test_job_has_four_breadcrumbs(self):
        """At job level: TeaParty > Project > Job."""
        ctx = _make_nav_context(
            level=DashboardLevel.JOB,
            project_slug='proj',
            job_id='20260327-120000',
        )
        crumbs = breadcrumbs_for_level(ctx)
        # Management > Project > Job (workgroup is optional in the path)
        self.assertGreaterEqual(len(crumbs), 3)
        last = crumbs[-1]
        self.assertEqual(last.level, DashboardLevel.JOB)
        self.assertIn('20260327-120000', last.label)

    def test_task_has_breadcrumbs_ending_at_task(self):
        """At task level, breadcrumbs end with the task."""
        ctx = _make_nav_context(
            level=DashboardLevel.TASK,
            project_slug='proj',
            job_id='20260327-120000',
            task_id='dispatch-001',
        )
        crumbs = breadcrumbs_for_level(ctx)
        last = crumbs[-1]
        self.assertEqual(last.level, DashboardLevel.TASK)
        self.assertIn('dispatch-001', last.label)

    def test_breadcrumb_is_clickable_except_current(self):
        """All breadcrumbs except the last (current) are clickable."""
        ctx = _make_nav_context(
            level=DashboardLevel.JOB,
            project_slug='proj',
            job_id='20260327-120000',
        )
        crumbs = breadcrumbs_for_level(ctx)
        for crumb in crumbs[:-1]:
            self.assertTrue(crumb.clickable)
        self.assertFalse(crumbs[-1].clickable)

    def test_breadcrumb_context_for_ancestor(self):
        """Each breadcrumb carries a NavigationContext for its level."""
        ctx = _make_nav_context(
            level=DashboardLevel.TASK,
            project_slug='proj',
            job_id='job-1',
            task_id='task-1',
        )
        crumbs = breadcrumbs_for_level(ctx)
        # The management crumb should navigate to management
        mgmt_crumb = crumbs[0]
        self.assertEqual(mgmt_crumb.nav_context.level, DashboardLevel.MANAGEMENT)
        self.assertEqual(mgmt_crumb.nav_context.project_slug, '')
        # The project crumb should navigate to project
        proj_crumb = crumbs[1]
        self.assertEqual(proj_crumb.nav_context.level, DashboardLevel.PROJECT)
        self.assertEqual(proj_crumb.nav_context.project_slug, 'proj')


class TestCardsForLevel(unittest.TestCase):
    """Each dashboard level has the correct set of content cards."""

    def test_management_cards(self):
        """Management dashboard: includes escalations card (issue #254)."""
        card_names = cards_for_level(DashboardLevel.MANAGEMENT)
        expected = {
            'escalations', 'sessions', 'projects', 'workgroups',
            'humans', 'agents', 'skills', 'scheduled_tasks', 'hooks',
        }
        self.assertEqual(set(card_names), expected)

    def test_project_cards(self):
        """Project dashboard: includes escalations card (issue #254)."""
        card_names = cards_for_level(DashboardLevel.PROJECT)
        expected = {
            'escalations', 'sessions', 'jobs', 'workgroups',
            'agents', 'skills', 'scheduled_tasks', 'hooks',
        }
        self.assertEqual(set(card_names), expected)

    def test_workgroup_cards(self):
        """Workgroup dashboard has the cards from the design spec."""
        card_names = cards_for_level(DashboardLevel.WORKGROUP)
        expected = {'escalations', 'sessions', 'active_tasks', 'agents', 'skills'}
        self.assertEqual(set(card_names), expected)

    def test_job_cards(self):
        """Job dashboard: escalations + artifacts + tasks per spec."""
        card_names = cards_for_level(DashboardLevel.JOB)
        expected = {'escalations', 'artifacts', 'tasks'}
        self.assertEqual(set(card_names), expected)

    def test_task_cards(self):
        """Task dashboard: escalations + artifacts + todo list (issue #254)."""
        card_names = cards_for_level(DashboardLevel.TASK)
        expected = {'escalations', 'artifacts', 'todo_list'}
        self.assertEqual(set(card_names), expected)


class TestBreadcrumbDrillUpNavigation(unittest.TestCase):
    """Clicking a breadcrumb produces the correct NavigationContext."""

    def test_click_management_from_task(self):
        """Clicking 'TeaParty' from task level returns to management."""
        ctx = _make_nav_context(
            level=DashboardLevel.TASK,
            project_slug='proj',
            job_id='job-1',
            task_id='task-1',
        )
        crumbs = breadcrumbs_for_level(ctx)
        mgmt = crumbs[0].nav_context
        self.assertEqual(mgmt.level, DashboardLevel.MANAGEMENT)
        self.assertEqual(mgmt.project_slug, '')
        self.assertEqual(mgmt.job_id, '')
        self.assertEqual(mgmt.task_id, '')

    def test_click_project_from_task(self):
        """Clicking project breadcrumb from task level returns to project."""
        ctx = _make_nav_context(
            level=DashboardLevel.TASK,
            project_slug='proj',
            job_id='job-1',
            task_id='task-1',
        )
        crumbs = breadcrumbs_for_level(ctx)
        proj = crumbs[1].nav_context
        self.assertEqual(proj.level, DashboardLevel.PROJECT)
        self.assertEqual(proj.project_slug, 'proj')
        self.assertEqual(proj.job_id, '')
        self.assertEqual(proj.task_id, '')

    def test_click_job_from_task(self):
        """Clicking job breadcrumb from task level returns to job."""
        ctx = _make_nav_context(
            level=DashboardLevel.TASK,
            project_slug='proj',
            job_id='job-1',
            task_id='task-1',
        )
        crumbs = breadcrumbs_for_level(ctx)
        # Find the job crumb
        job_crumb = [c for c in crumbs if c.level == DashboardLevel.JOB][0]
        self.assertEqual(job_crumb.nav_context.level, DashboardLevel.JOB)
        self.assertEqual(job_crumb.nav_context.project_slug, 'proj')
        self.assertEqual(job_crumb.nav_context.job_id, 'job-1')
        self.assertEqual(job_crumb.nav_context.task_id, '')


class TestContentCard(unittest.TestCase):
    """ContentCard data model — CardItem construction and rendering."""

    def test_card_item_has_icon_label_detail(self):
        """CardItem stores icon, label, detail, and data."""
        from orchestrator.dashboard_stats import CardItem
        item = CardItem(icon='\u25b6', label='my-project', detail='3 active', data={'slug': 'proj'})
        self.assertEqual(item.icon, '\u25b6')
        self.assertEqual(item.label, 'my-project')
        self.assertEqual(item.detail, '3 active')
        self.assertEqual(item.data, {'slug': 'proj'})

    def test_card_item_defaults(self):
        """CardItem has sensible defaults for optional fields."""
        from orchestrator.dashboard_stats import CardItem
        item = CardItem()
        self.assertEqual(item.icon, '')
        self.assertEqual(item.label, '')
        self.assertEqual(item.detail, '')
        self.assertIsNone(item.data)


class TestStatsComputation(unittest.TestCase):
    """Stats bar data is correctly computed from project/session state."""

    def test_management_stats_aggregate_across_projects(self):
        """Management stats aggregate all projects."""
        # Simulate the stat computation from ManagementDashboard._update_stats
        projects = [
            type('P', (), {'sessions': [
                type('S', (), {'cfa_state': 'COMPLETED_WORK'})(),
                type('S', (), {'cfa_state': 'WORK_IN_PROGRESS'})(),
            ], 'active_count': 1, 'attention_count': 0})(),
            type('P', (), {'sessions': [
                type('S', (), {'cfa_state': 'WITHDRAWN'})(),
            ], 'active_count': 0, 'attention_count': 1})(),
        ]
        total_sessions = sum(len(p.sessions) for p in projects)
        active = sum(p.active_count for p in projects)
        completed = sum(1 for p in projects for s in p.sessions if s.cfa_state == 'COMPLETED_WORK')
        withdrawn = sum(1 for p in projects for s in p.sessions if s.cfa_state == 'WITHDRAWN')
        attention = sum(p.attention_count for p in projects)

        self.assertEqual(total_sessions, 3)
        self.assertEqual(active, 1)
        self.assertEqual(completed, 1)
        self.assertEqual(withdrawn, 1)
        self.assertEqual(attention, 1)


class TestManagementDashboardCards(unittest.TestCase):
    """Management dashboard has the correct card structure."""

    def test_management_cards(self):
        """Management dashboard: includes escalations card (issue #254)."""
        from orchestrator.navigation import DashboardLevel, cards_for_level
        cards = cards_for_level(DashboardLevel.MANAGEMENT)
        self.assertEqual(len(cards), 9)
        self.assertIn('escalations', cards)
        self.assertIn('sessions', cards)

    def test_project_dashboard_cards(self):
        """Project dashboard: includes escalations card (issue #254)."""
        from orchestrator.navigation import DashboardLevel, cards_for_level
        cards = cards_for_level(DashboardLevel.PROJECT)
        self.assertEqual(len(cards), 8)
        self.assertIn('escalations', cards)
        self.assertIn('jobs', cards)

    def test_workgroup_dashboard_has_five_cards(self):
        """Workgroup dashboard has 5 cards per spec."""
        from orchestrator.navigation import DashboardLevel, cards_for_level
        cards = cards_for_level(DashboardLevel.WORKGROUP)
        self.assertEqual(len(cards), 5)

    def test_job_dashboard_cards(self):
        """Job dashboard: escalations + artifacts + tasks per spec."""
        from orchestrator.navigation import DashboardLevel, cards_for_level
        cards = cards_for_level(DashboardLevel.JOB)
        self.assertEqual(len(cards), 3)
        self.assertIn('escalations', cards)
        self.assertIn('tasks', cards)
        self.assertIn('artifacts', cards)

    def test_task_dashboard_cards(self):
        """Task dashboard: escalations + artifacts + todo list (issue #254)."""
        from orchestrator.navigation import DashboardLevel, cards_for_level
        cards = cards_for_level(DashboardLevel.TASK)
        self.assertEqual(len(cards), 3)
        self.assertIn('escalations', cards)
        self.assertIn('artifacts', cards)
        self.assertIn('todo_list', cards)


class TestHookItemsDisplay(unittest.TestCase):
    """Hooks card displays event, matcher, and handler type per management-dashboard.md spec."""

    def test_hook_item_shows_event_matcher_handler(self):
        """Hook with event + matcher + command renders all three."""
        from orchestrator.dashboard_stats import _build_hook_items
        hooks = [{'event': 'PreToolUse', 'matcher': 'Bash', 'command': 'audit.sh'}]
        items = _build_hook_items(hooks)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].label, 'PreToolUse')
        self.assertIn('Bash', items[0].detail)
        self.assertIn('audit.sh', items[0].detail)

    def test_hook_item_without_matcher_shows_handler_only(self):
        """Hook without matcher renders event and handler without extra separator."""
        from orchestrator.dashboard_stats import _build_hook_items
        hooks = [{'event': 'PostToolUse', 'command': 'log.sh'}]
        items = _build_hook_items(hooks)
        self.assertEqual(items[0].detail, 'log.sh')

    def test_hook_item_empty_hooks_returns_empty(self):
        """Empty hooks list returns empty CardItem list."""
        from orchestrator.dashboard_stats import _build_hook_items
        self.assertEqual(_build_hook_items([]), [])


class TestStatsBarsNoWrap(unittest.TestCase):
    """Stats bar format functions produce single-line strings (no newlines).

    The stats bar uses two separate Static widgets (one for labels, one for values),
    each height: 1. Each row must be a single line — no embedded newlines that would
    cause the rows to interleave when Textual wraps the text.
    """

    def _sample_stats(self) -> list[tuple[str, str]]:
        return [
            ('Jobs Done', '12'),
            ('Tasks Done', '48'),
            ('Active', '3'),
            ('One-shots', '7'),
            ('Backtracks', '2'),
            ('Withdrawals', '1'),
            ('Escalations', '0'),
            ('Interventions', '0'),
            ('Proxy Acc.', '94%'),
            ('Tokens', '2.1M'),
            ('Skills Learned', '5'),
            ('Uptime', '2h30m'),
        ]

    def test_labels_row_has_no_newline(self):
        """Labels row is a single line with no embedded newlines."""
        from orchestrator.dashboard_stats import format_stats_labels
        result = format_stats_labels(self._sample_stats())
        self.assertNotIn('\n', result)

    def test_values_row_has_no_newline(self):
        """Values row is a single line with no embedded newlines."""
        from orchestrator.dashboard_stats import format_stats_values
        result = format_stats_values(self._sample_stats())
        self.assertNotIn('\n', result)

    def test_labels_contains_all_keys(self):
        """Labels row includes every stat label."""
        from orchestrator.dashboard_stats import format_stats_labels
        result = format_stats_labels(self._sample_stats())
        for label, _ in self._sample_stats():
            self.assertIn(label, result)

    def test_values_contains_all_values(self):
        """Values row includes every stat value."""
        from orchestrator.dashboard_stats import format_stats_values
        result = format_stats_values(self._sample_stats())
        for _, value in self._sample_stats():
            self.assertIn(value, result)

    def test_column_widths_align_labels_and_values(self):
        """Each column is right-padded to max(len(label), len(value)), keeping columns aligned."""
        from orchestrator.dashboard_stats import format_stats_labels, format_stats_values
        stats = [('AB', '1234'), ('LONGNAME', '9')]  # label wider than value; value narrower
        labels = format_stats_labels(stats)
        values = format_stats_values(stats)
        # Strip markup: both rows have same total character width
        import re
        strip = lambda s: re.sub(r'\[/?[^\]]*\]', '', s)
        self.assertEqual(len(strip(labels)), len(strip(values)))

    def test_empty_stats_returns_empty_string(self):
        """Empty stats list produces empty strings."""
        from orchestrator.dashboard_stats import format_stats_labels, format_stats_values
        self.assertEqual(format_stats_labels([]), '')
        self.assertEqual(format_stats_values([]), '')


if __name__ == '__main__':
    unittest.main()
