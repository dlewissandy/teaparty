"""BreadcrumbBar widget — clickable navigation trail for dashboard hierarchy."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from projects.POC.tui.navigation import (
    Breadcrumb,
    NavigationContext,
    breadcrumbs_for_level,
)


class BreadcrumbBar(Widget):
    """Horizontal bar showing clickable breadcrumbs: TeaParty > Project > Job > Task."""

    class Navigate(Message):
        """Posted when the user clicks a breadcrumb to navigate."""
        def __init__(self, nav_context: NavigationContext) -> None:
            super().__init__()
            self.nav_context = nav_context

    def __init__(self, nav_context: NavigationContext, **kwargs) -> None:
        super().__init__(**kwargs)
        self._nav_context = nav_context
        self._crumbs: list[Breadcrumb] = []

    def compose(self) -> ComposeResult:
        self._crumbs = breadcrumbs_for_level(self._nav_context)
        parts: list[str] = []
        for i, crumb in enumerate(self._crumbs):
            if i > 0:
                parts.append(' > ')
            if crumb.clickable:
                parts.append(f'[@click=navigate({i})][bold]{crumb.label}[/bold][/]')
            else:
                parts.append(f'[dim]{crumb.label}[/dim]')
        yield Static(''.join(parts), id='breadcrumb-text')

    def action_navigate(self, index: int) -> None:
        """Handle breadcrumb click."""
        if 0 <= index < len(self._crumbs) and self._crumbs[index].clickable:
            self.post_message(self.Navigate(self._crumbs[index].nav_context))

    def update_context(self, nav_context: NavigationContext) -> None:
        """Update the breadcrumbs for a new navigation context."""
        self._nav_context = nav_context
        self._crumbs = breadcrumbs_for_level(nav_context)
        parts: list[str] = []
        for i, crumb in enumerate(self._crumbs):
            if i > 0:
                parts.append(' > ')
            if crumb.clickable:
                parts.append(f'[@click=navigate({i})][bold]{crumb.label}[/bold][/]')
            else:
                parts.append(f'[dim]{crumb.label}[/dim]')
        try:
            self.query_one('#breadcrumb-text', Static).update(''.join(parts))
        except Exception:
            pass
