"""Workgroup Dashboard — single workgroup view with tasks, agents, and skills."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Static
from textual.containers import Vertical

from projects.POC.tui.navigation import NavigationContext
from projects.POC.tui.widgets.breadcrumb_bar import BreadcrumbBar


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
        yield Vertical(
            Static(f'[bold]Workgroup: {self._nav_context.workgroup_id}[/bold]', id='wg-title'),
            Static('', id='wg-content'),
        )
        yield Footer()

    def on_mount(self) -> None:
        content = self.query_one('#wg-content', Static)
        content.update(
            '[dim]Workgroup data will be populated when the configuration tree (#251) provides workgroup definitions.[/dim]\n\n'
            'Cards: Escalations, Sessions, Active Tasks, Agents, Skills'
        )

    def on_breadcrumb_bar_navigate(self, event: BreadcrumbBar.Navigate) -> None:
        from projects.POC.tui.screens.management_dashboard import _navigate_to_context
        _navigate_to_context(self.app, event.nav_context)

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_refresh(self) -> None:
        pass

    def periodic_refresh(self) -> None:
        pass
