"""Workgroup Dashboard — single workgroup view with content cards per design spec.

Cards: Escalations, Sessions, Active Tasks, Agents, Skills.
Data pending config tree (#251).
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header

from projects.POC.tui.navigation import NavigationContext
from projects.POC.tui.widgets.breadcrumb_bar import BreadcrumbBar
from projects.POC.tui.widgets.content_card import ContentCard
from projects.POC.tui.widgets.stats_bar import StatsBar


class WorkgroupDashboard(Screen):
    """Single workgroup view. Cards shown, content pending config tree (#251)."""

    BINDINGS = [
        Binding('escape', 'go_back', 'Back', show=True),
    ]

    def __init__(self, nav_context: NavigationContext) -> None:
        super().__init__()
        self._nav_context = nav_context

    def compose(self) -> ComposeResult:
        yield Header()
        yield BreadcrumbBar(self._nav_context, id='breadcrumb-bar')
        yield StatsBar(id='wg-stats')
        yield VerticalScroll(
            Vertical(
                ContentCard('ESCALATIONS', 'escalations'),
                ContentCard('SESSIONS', 'sessions', show_new_button=True),
                ContentCard('ACTIVE TASKS', 'active_tasks'),
                ContentCard('AGENTS', 'agents', show_new_button=True),
                ContentCard('SKILLS', 'skills', show_new_button=True),
                id='card-col',
                classes='card-grid',
            ),
        )
        yield Footer()

    def on_breadcrumb_bar_navigate(self, event: BreadcrumbBar.Navigate) -> None:
        from projects.POC.tui.screens.management_dashboard import _navigate_to_context
        _navigate_to_context(self.app, event.nav_context)

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def periodic_refresh(self) -> None:
        pass
