"""Management Dashboard — top-level home screen with content cards per design spec.

Cards: Escalations, Sessions, Projects, Workgroups, Humans, Agents, Skills,
Scheduled Tasks, Hooks. Stats bar at top. Breadcrumb shows 'TeaParty'.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

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
        Binding('n', 'new_session', 'New Session', show=True),
        Binding('p', 'new_project', 'New Project', show=True),
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
        yield Horizontal(
            # Left column: primary navigation cards
            VerticalScroll(
                ContentCard('ESCALATIONS', 'escalations', empty_text='No pending escalations'),
                ContentCard('SESSIONS', 'sessions', show_new_button=True, empty_text='No active sessions'),
                ContentCard('PROJECTS', 'projects', show_new_button=True, empty_text='No projects'),
                ContentCard('WORKGROUPS', 'workgroups', show_new_button=True, empty_text='No workgroups'),
                id='left-card-col',
                classes='card-grid',
            ),
            # Right column: resource cards
            VerticalScroll(
                ContentCard('HUMANS', 'humans', empty_text='No humans configured'),
                ContentCard('AGENTS', 'agents', show_new_button=True, empty_text='No agents'),
                ContentCard('SKILLS', 'skills', show_new_button=True, empty_text='No skills'),
                ContentCard('SCHEDULED TASKS', 'scheduled_tasks', show_new_button=True, empty_text='No scheduled tasks'),
                ContentCard('HOOKS', 'hooks', show_new_button=True, empty_text='No hooks'),
                id='right-card-col',
                classes='card-grid',
            ),
            id='top-panes',
        )
        yield Static('', id='chat-attention-label', classes='chat-attention-label')
        yield Static('', id='projects-dir-label', classes='projects-dir-label')
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_data(force=True)
        self._update_projects_dir_label()

    def _refresh_data(self, force: bool = False) -> None:
        reader = self.app.state_reader
        reader.reload()
        self._update_stats(reader)
        self._update_escalations_card(reader)
        self._update_sessions_card(reader)
        self._update_projects_card(reader)
        self._update_workgroups_card()
        self._update_humans_card()
        self._update_agents_card()
        self._update_skills_card()
        self._update_scheduled_tasks_card()
        self._update_hooks_card()
        self._update_projects_dir_label()
        self._update_chat_attention()

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

    def _update_workgroups_card(self) -> None:
        # Workgroups are not yet in the data model (pending #251)
        self._update_card('workgroups', [])

    def _update_humans_card(self) -> None:
        # Humans are not yet in the data model (pending #251)
        self._update_card('humans', [])

    def _update_agents_card(self) -> None:
        # Agents are not yet in the data model (pending #251)
        self._update_card('agents', [])

    def _update_skills_card(self) -> None:
        # Skills are not yet in the data model (pending #251)
        self._update_card('skills', [])

    def _update_scheduled_tasks_card(self) -> None:
        # Scheduled tasks are not yet in the data model (pending #195)
        self._update_card('scheduled_tasks', [])

    def _update_hooks_card(self) -> None:
        # Hooks are not yet in the data model (pending #251)
        self._update_card('hooks', [])

    def _update_card(self, card_name: str, items: list[CardItem]) -> None:
        try:
            for widget in self.query(ContentCard):
                if widget._card_name == card_name:
                    widget.update_items(items)
                    break
        except Exception:
            pass

    def _update_projects_dir_label(self) -> None:
        try:
            self.query_one('#projects-dir-label', Static).update(
                f'Projects: {self.app.projects_dir}'
            )
        except Exception:
            pass

    def _update_chat_attention(self) -> None:
        try:
            label = self.query_one('#chat-attention-label', Static)
        except Exception:
            return
        try:
            count = self._get_chat_attention_count()
        except Exception:
            count = 0
        if count > 0:
            label.update(f'\u23f3 {count} conversation{"s" if count != 1 else ""} need{"" if count != 1 else "s"} your response \u2014 press [bold]c[/bold] to open chat')
        else:
            label.update('')

    def _get_chat_attention_count(self) -> int:
        import os
        bus_paths: list[str] = []
        seen: set[str] = set()
        reader = self.app.state_reader
        for sid, ip in getattr(self.app, '_in_process', {}).items():
            if ip.message_bus_path and os.path.exists(ip.message_bus_path):
                real = os.path.realpath(ip.message_bus_path)
                if real not in seen:
                    seen.add(real)
                    bus_paths.append(ip.message_bus_path)
        for session in reader.sessions:
            if session.infra_dir:
                candidate = os.path.join(session.infra_dir, 'messages.db')
                if os.path.exists(candidate):
                    real = os.path.realpath(candidate)
                    if real not in seen:
                        seen.add(real)
                        bus_paths.append(candidate)
        if not bus_paths:
            return 0
        from projects.POC.tui.chat_model import ChatModel
        model = ChatModel.from_bus_paths(bus_paths)
        try:
            return model.attention_count()
        finally:
            model.close()

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
