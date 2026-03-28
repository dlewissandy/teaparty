"""Workgroup Dashboard — single workgroup view.

Cards will be populated when the configuration tree (#251) provides workgroup data.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from projects.POC.tui.navigation import NavigationContext
from projects.POC.tui.widgets.breadcrumb_bar import BreadcrumbBar


class WorkgroupDashboard(Screen):
    """Single workgroup view. Pending config tree (#251) for data."""

    BINDINGS = [
        Binding('escape', 'go_back', 'Back', show=True),
    ]

    def __init__(self, nav_context: NavigationContext) -> None:
        super().__init__()
        self._nav_context = nav_context

    def compose(self) -> ComposeResult:
        yield Header()
        yield BreadcrumbBar(self._nav_context, id='breadcrumb-bar')
        yield Static(f'[bold]Workgroup: {self._nav_context.workgroup_id}[/bold]', id='wg-title')
        yield Footer()

    def on_breadcrumb_bar_navigate(self, event: BreadcrumbBar.Navigate) -> None:
        from projects.POC.tui.screens.management_dashboard import _navigate_to_context
        _navigate_to_context(self.app, event.nav_context)

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def periodic_refresh(self) -> None:
        pass
