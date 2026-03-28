"""Management Dashboard — top-level home screen with content cards per design spec.

Cards: Escalations, Sessions, Projects, Workgroups, Humans, Agents, Skills,
Scheduled Tasks, Hooks. Stats bar at top. Breadcrumb shows 'TeaParty'.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from projects.POC.tui.navigation import DashboardLevel, NavigationContext
from projects.POC.tui.widgets.breadcrumb_bar import BreadcrumbBar
from projects.POC.tui.widgets.content_card import CardItem, ContentCard
from projects.POC.tui.widgets.stats_bar import StatsBar


def _human_age(seconds: int) -> str:
    if seconds < 0:
        return '\u2014'
    if seconds < 60:
        return f'{seconds}s'
    if seconds < 3600:
        return f'{seconds // 60}m'
    return f'{seconds // 3600}h{seconds % 3600 // 60}m'


def _status_icon(status: str, needs_input: bool = False, is_orphaned: bool = False) -> str:
    if is_orphaned:
        return '\u26a0'
    if needs_input:
        return '\u23f3'
    if status == 'active':
        return '\u25b6'
    if status == 'complete':
        return '\u2713'
    if status == 'failed':
        return '\u2717'
    return ' '


def _state_display(phase: str, state: str) -> str:
    if not phase and not state:
        return '\u2014'
    if state in ('COMPLETED_WORK', 'WITHDRAWN'):
        return state
    if phase:
        return f'{phase}/{state}'
    return state


class ManagementDashboard(Screen):
    """Home screen. Cards per design spec + stats bar + breadcrumbs."""

    BINDINGS = [
        Binding('enter', 'select_item', 'Open', show=True),
        Binding('n', 'new_session', 'New Session', show=False),
        Binding('p', 'new_project', 'New Project', show=False),
        Binding('d', 'diagnostics', 'Diagnostics', show=True),
        Binding('r', 'refresh', 'Refresh', show=True),
        Binding('q', 'quit_app', 'Quit', show=True),
        Binding('f', 'change_folder', 'Folder', show=True),
        Binding('c', 'open_chat', 'Chat', show=True),
        Binding('x', 'proxy_review', 'Proxy Review', show=True),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._nav_context = NavigationContext(level=DashboardLevel.MANAGEMENT)

    def compose(self) -> ComposeResult:
        yield Header()
        yield BreadcrumbBar(self._nav_context, id='breadcrumb-bar')
        yield StatsBar(id='mgmt-stats')
        yield VerticalScroll(
            Horizontal(
                Vertical(
                    ContentCard('ESCALATIONS', 'escalations'),
                    ContentCard('SESSIONS', 'sessions', show_new_button=True),
                    ContentCard('PROJECTS', 'projects', show_new_button=True),
                    ContentCard('WORKGROUPS', 'workgroups', show_new_button=True),
                    ContentCard('HUMANS', 'humans'),
                    id='card-col-left',
                    classes='card-column',
                ),
                Vertical(
                    ContentCard('AGENTS', 'agents', show_new_button=True),
                    ContentCard('SKILLS', 'skills', show_new_button=True),
                    ContentCard('SCHEDULED TASKS', 'scheduled_tasks', show_new_button=True),
                    ContentCard('HOOKS', 'hooks', show_new_button=True),
                    id='card-col-right',
                    classes='card-column',
                ),
                id='card-cols',
                classes='card-columns',
            ),
        )
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_data(force=True)
        self._update_grid_columns()

    def on_resize(self) -> None:
        self._update_grid_columns()

    def _update_grid_columns(self) -> None:
        try:
            cols = self.query_one('#card-cols')
            if self.size.width < 80:
                cols.add_class('-narrow')
            else:
                cols.remove_class('-narrow')
        except Exception:
            pass

    def _refresh_data(self, force: bool = False) -> None:
        reader = self.app.state_reader
        reader.reload()
        self._update_stats(reader)
        self._update_escalations_card(reader)
        self._update_sessions_card(reader)
        self._update_projects_card(reader)

    def _update_stats(self, reader) -> None:
        total_sessions = sum(len(p.sessions) for p in reader.projects)
        active_sessions = sum(p.active_count for p in reader.projects)
        completed = sum(
            1 for p in reader.projects for s in p.sessions
            if s.cfa_state == 'COMPLETED_WORK'
        )
        withdrawn = sum(
            1 for p in reader.projects for s in p.sessions
            if s.cfa_state == 'WITHDRAWN'
        )
        attention = sum(p.attention_count for p in reader.projects)

        stats = [
            ('Projects', str(len(reader.projects))),
            ('Jobs', str(total_sessions)),
            ('Active', str(active_sessions)),
            ('Done', str(completed)),
            ('Withdrawn', str(withdrawn)),
            ('Escalations', str(attention)),
        ]
        try:
            self.query_one('#mgmt-stats', StatsBar).update_stats(stats)
        except Exception:
            pass

    def _update_escalations_card(self, reader) -> None:
        items = []
        for proj in reader.projects:
            for sess in proj.sessions:
                if sess.needs_input:
                    items.append(CardItem(
                        icon='\u23f3',
                        label=f'{proj.slug}/{sess.session_id}',
                        detail=sess.cfa_state,
                        data={'project': proj.slug, 'session_id': sess.session_id},
                    ))
        self._update_card('escalations', items)

    def _update_sessions_card(self, reader) -> None:
        items = []
        for proj in reader.projects:
            for sess in proj.sessions:
                if sess.status == 'active':
                    icon = _status_icon(sess.status, sess.needs_input, sess.is_orphaned)
                    items.append(CardItem(
                        icon=icon,
                        label=f'{proj.slug}/{sess.session_id}',
                        detail=_state_display(sess.cfa_phase, sess.cfa_state),
                        data={'project': proj.slug, 'session_id': sess.session_id},
                    ))
        self._update_card('sessions', items)

    def _update_projects_card(self, reader) -> None:
        items = []
        for proj in reader.projects:
            active = proj.active_count
            total = len(proj.sessions)
            attn = f' \u23f3' if proj.attention_count > 0 else ''
            items.append(CardItem(
                icon='\u25b6' if active > 0 else '\u2713',
                label=proj.slug,
                detail=f'{active} active / {total} total{attn}',
                data={'project': proj.slug},
            ))
        self._update_card('projects', items)

    def _update_card(self, card_name: str, items: list[CardItem]) -> None:
        try:
            for widget in self.query(ContentCard):
                if widget._card_name == card_name:
                    widget.update_items(items)
                    break
        except Exception:
            pass

    def on_content_card_item_selected(self, event: ContentCard.ItemSelected) -> None:
        """Handle clicks on card items — navigate to the appropriate level."""
        data = event.item.data or {}
        if event.card_name == 'projects':
            slug = data.get('project', '')
            if slug:
                ctx = self._nav_context.drill_down(DashboardLevel.PROJECT, project_slug=slug)
                _navigate_to_context(self.app, ctx)
        elif event.card_name in ('escalations', 'sessions'):
            project = data.get('project', '')
            sid = data.get('session_id', '')
            if project and sid:
                ctx = self._nav_context.drill_down(
                    DashboardLevel.JOB, project_slug=project, job_id=sid,
                )
                _navigate_to_context(self.app, ctx)

    def on_content_card_new_requested(self, event: ContentCard.NewRequested) -> None:
        """Handle '+ New' clicks on cards."""
        if event.card_name == 'projects':
            self.action_new_project()
        elif event.card_name == 'sessions':
            self.action_new_session()

    def on_breadcrumb_bar_navigate(self, event: BreadcrumbBar.Navigate) -> None:
        _navigate_to_context(self.app, event.nav_context)

    def action_select_item(self) -> None:
        # Enter key — try to navigate to focused project card item
        pass

    def action_new_session(self) -> None:
        from projects.POC.tui.screens.launch import LaunchScreen
        # Use first project if available
        reader = self.app.state_reader
        project = reader.projects[0].slug if reader.projects else ''
        self.app.push_screen(LaunchScreen(project))

    def action_new_project(self) -> None:
        from projects.POC.tui.screens.new_project import NewProjectScreen
        self.app.push_screen(NewProjectScreen())

    def action_diagnostics(self) -> None:
        from projects.POC.tui.screens.diagnostics import DiagnosticsScreen
        self.app.push_screen(DiagnosticsScreen())

    def action_refresh(self) -> None:
        self._refresh_data(force=True)

    def action_quit_app(self) -> None:
        self.app.exit()

    def action_open_chat(self) -> None:
        from projects.POC.tui.screens.chat import ChatScreen
        self.app.push_screen(ChatScreen())

    def action_change_folder(self) -> None:
        from projects.POC.tui.screens.dashboard import ChangeProjectDirScreen
        self.app.push_screen(ChangeProjectDirScreen())

    def action_proxy_review(self) -> None:
        from projects.POC.tui.screens.proxy_review import ProxyReviewScreen
        self.app.push_screen(ProxyReviewScreen())

    def periodic_refresh(self) -> None:
        self._refresh_data()


def _session_snapshot(proj) -> list[tuple]:
    if not proj:
        return []
    return [
        (s.session_id, s.status, s.cfa_phase, s.cfa_state,
         s.needs_input, len(s.dispatches))
        for s in proj.sessions
    ]


def _navigate_to_context(app, ctx: NavigationContext) -> None:
    """Navigate the app to the screen for the given NavigationContext."""
    while len(app.screen_stack) > 1:
        app.pop_screen()

    if ctx.level == DashboardLevel.MANAGEMENT:
        return

    if ctx.level == DashboardLevel.PROJECT:
        from projects.POC.tui.screens.project_dashboard import ProjectDashboard
        app.push_screen(ProjectDashboard(ctx))
    elif ctx.level == DashboardLevel.WORKGROUP:
        from projects.POC.tui.screens.workgroup_dashboard import WorkgroupDashboard
        app.push_screen(WorkgroupDashboard(ctx))
    elif ctx.level == DashboardLevel.JOB:
        from projects.POC.tui.screens.job_dashboard import JobDashboard
        app.push_screen(JobDashboard(ctx))
    elif ctx.level == DashboardLevel.TASK:
        from projects.POC.tui.screens.task_dashboard import TaskDashboard
        app.push_screen(TaskDashboard(ctx))
