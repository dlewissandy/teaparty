"""Workgroup Dashboard — single workgroup view with content cards per design spec.

Cards: Escalations, Sessions, Active Tasks, Agents, Skills.
No Jobs or Scheduled Tasks (workgroups participate in jobs via tasks, not own them).
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from projects.POC.tui.navigation import NavigationContext
from projects.POC.tui.widgets.breadcrumb_bar import BreadcrumbBar
from projects.POC.tui.widgets.content_card import ContentCard
from projects.POC.tui.widgets.stats_bar import StatsBar


class WorkgroupDashboard(Screen):
    """Single workgroup view. Cards: escalations, sessions, active tasks, agents, skills."""

    BINDINGS = [
        Binding('escape', 'go_back', 'Back', show=True),
        Binding('r', 'refresh', 'Refresh', show=True),
    ]

    def __init__(self, nav_context: NavigationContext) -> None:
        super().__init__()
        self._nav_context = nav_context

    def compose(self) -> ComposeResult:
        yield Header()
        yield BreadcrumbBar(self._nav_context, id='breadcrumb-bar')
        yield StatsBar(id='wg-stats')
        yield Horizontal(
            VerticalScroll(
                ContentCard('ESCALATIONS', 'escalations', empty_text='No pending escalations'),
                ContentCard('SESSIONS', 'sessions', show_new_button=True, empty_text='No sessions'),
                ContentCard('ACTIVE TASKS', 'active_tasks', empty_text='No active tasks'),
                id='left-card-col',
                classes='card-grid',
            ),
            VerticalScroll(
                ContentCard('AGENTS', 'agents', show_new_button=True, empty_text='No agents'),
                ContentCard('SKILLS', 'skills', show_new_button=True, empty_text='No skills'),
                id='right-card-col',
                classes='card-grid',
            ),
            id='top-panes',
        )
        yield Footer()

    def on_mount(self) -> None:
        # Workgroup data is pending config tree (#251)
        # Show empty cards with the correct structure
        stats = [
            ('Tasks', '0'),
            ('Active', '0'),
            ('Agents', '0'),
        ]
        try:
            self.query_one('#wg-stats', StatsBar).update_stats(stats)
        except Exception:
            pass

    def on_breadcrumb_bar_navigate(self, event: BreadcrumbBar.Navigate) -> None:
        from projects.POC.tui.screens.management_dashboard import _navigate_to_context
        _navigate_to_context(self.app, event.nav_context)

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_refresh(self) -> None:
        pass

    def periodic_refresh(self) -> None:
        pass
