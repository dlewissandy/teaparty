"""Management Dashboard — top-level home screen showing all projects and org-level cards."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static

from projects.POC.tui.navigation import DashboardLevel, NavigationContext
from projects.POC.tui.widgets.breadcrumb_bar import BreadcrumbBar


def _human_age(seconds: int) -> str:
    if seconds < 0:
        return '\u2014'
    if seconds < 60:
        return f'{seconds}s'
    if seconds < 3600:
        return f'{seconds // 60}m'
    return f'{seconds // 3600}h{seconds % 3600 // 60}m'


def _project_snapshot(reader) -> list[tuple]:
    return [
        (p.slug, len(p.sessions), p.active_count, p.attention_count)
        for p in reader.projects
    ]


class ManagementDashboard(Screen):
    """Home screen. Cards: projects, sessions, escalations, workgroups, etc."""

    BINDINGS = [
        Binding('enter', 'select_project', 'Open Project', show=True),
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
        yield Horizontal(
            Vertical(
                Static('PROJECTS', classes='section-title'),
                DataTable(id='project-table'),
                id='left-pane',
            ),
            Vertical(
                Static('SESSIONS', classes='section-title', id='sessions-title'),
                DataTable(id='session-table'),
                id='right-pane',
            ),
            id='top-panes',
        )
        yield Vertical(
            Static('PROMPT', classes='section-title', id='prompt-title'),
            VerticalScroll(
                Static('', id='dash-prompt-panel'),
                id='prompt-scroll',
            ),
            id='bottom-pane',
        )
        yield Static('', id='chat-attention-label', classes='chat-attention-label')
        yield Static('', id='projects-dir-label', classes='projects-dir-label')
        yield Footer()

    def on_mount(self) -> None:
        ptable = self.query_one('#project-table', DataTable)
        ptable.cursor_type = 'row'
        ptable.add_columns('', 'Project', '#', '')

        stable = self.query_one('#session-table', DataTable)
        stable.cursor_type = 'row'
        stable.add_columns('', 'Session', 'State', 'Idle', 'Dur')

        self._project_slugs: list[str] = []
        self._session_ids: list[str] = []
        self._selected_project: str = ''
        self._last_project_snap: list[tuple] = []
        self._last_session_snap: list[tuple] = []
        self._refresh_data(force=True)
        self._update_projects_dir_label()

    def _update_projects_dir_label(self) -> None:
        self.query_one('#projects-dir-label', Static).update(
            f'Projects: {self.app.projects_dir}'
        )

    def _update_chat_attention(self) -> None:
        label = self.query_one('#chat-attention-label', Static)
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

    def _refresh_data(self, force: bool = False) -> None:
        reader = self.app.state_reader
        reader.reload()

        proj_snap = _project_snapshot(reader)
        if force or proj_snap != self._last_project_snap:
            self._last_project_snap = proj_snap
            self._rebuild_project_table()

        proj = reader.find_project(self._selected_project)
        sess_snap = _session_snapshot(proj)
        if force or sess_snap != self._last_session_snap:
            self._last_session_snap = sess_snap
            self._rebuild_session_table()
        else:
            self._update_session_times()

        self._update_prompt_panel()
        self._update_projects_dir_label()
        self._update_chat_attention()

    def _rebuild_project_table(self) -> None:
        ptable = self.query_one('#project-table', DataTable)
        ptable.clear()
        self._project_slugs = []

        for proj in self.app.state_reader.projects:
            count = str(len(proj.sessions))
            attention = '\u23f3' if proj.attention_count > 0 else ''
            ptable.add_row(' ', proj.slug, count, attention)
            self._project_slugs.append(proj.slug)

        if not self._project_slugs:
            ptable.add_row('', '(no projects)', '', '')
            self._selected_project = ''
            return

        if not self._selected_project or self._selected_project not in self._project_slugs:
            self._selected_project = self._project_slugs[0]

        idx = self._project_slugs.index(self._selected_project)
        ptable.move_cursor(row=idx)

    def _rebuild_session_table(self) -> None:
        stable = self.query_one('#session-table', DataTable)
        title = self.query_one('#sessions-title', Static)
        stable.clear()
        self._session_ids = []

        proj = self.app.state_reader.find_project(self._selected_project)
        if not proj:
            title.update('SESSIONS')
            return

        title.update(f'SESSIONS ({proj.slug})')

        for sess in proj.sessions:
            icon = _status_icon(sess.status, sess.needs_input, getattr(sess, 'is_orphaned', False))
            state = _state_display(sess.cfa_phase, sess.cfa_state)
            idle = _human_age(sess.stream_age_seconds)
            dur = _human_age(sess.duration_seconds)
            stable.add_row(icon, sess.session_id, state, idle, dur)
            self._session_ids.append(sess.session_id)

        if not self._session_ids:
            stable.add_row('', '(no sessions)', '', '', '')

    def _update_session_times(self) -> None:
        from textual.coordinate import Coordinate
        stable = self.query_one('#session-table', DataTable)
        proj = self.app.state_reader.find_project(self._selected_project)
        if not proj:
            return
        for row_idx, sess in enumerate(proj.sessions):
            if row_idx >= len(self._session_ids):
                break
            stable.update_cell_at(Coordinate(row_idx, 3), _human_age(sess.stream_age_seconds))
            stable.update_cell_at(Coordinate(row_idx, 4), _human_age(sess.duration_seconds))

    def _update_prompt_panel(self) -> None:
        title = self.query_one('#prompt-title', Static)
        panel = self.query_one('#dash-prompt-panel', Static)
        stable = self.query_one('#session-table', DataTable)
        cursor_row = stable.cursor_row

        if not self._session_ids or cursor_row < 0 or cursor_row >= len(self._session_ids):
            title.update('PROMPT')
            panel.update('  (no session selected)')
            return

        sid = self._session_ids[cursor_row]
        session = self.app.state_reader.find_session(sid)
        if not session:
            title.update(f'PROMPT ({sid})')
            panel.update('  (no session)')
            return

        title.update(f'PROMPT ({sid})')
        panel.update(f'  {session.task}' if session.task else '  (no prompt)')

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        table_id = event.data_table.id
        if table_id == 'project-table':
            cursor = event.cursor_row
            if 0 <= cursor < len(self._project_slugs):
                new_project = self._project_slugs[cursor]
                if new_project != self._selected_project:
                    self._selected_project = new_project
                    self._last_session_snap = []
                    self._rebuild_session_table()
                    self._update_prompt_panel()
        elif table_id == 'session-table':
            self._update_prompt_panel()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        table_id = event.data_table.id
        if table_id == 'session-table':
            self._navigate_to_job()
        elif table_id == 'project-table':
            self.action_select_project()

    def on_breadcrumb_bar_navigate(self, event: BreadcrumbBar.Navigate) -> None:
        """Handle breadcrumb clicks — navigate to ancestor level."""
        _navigate_to_context(self.app, event.nav_context)

    def action_select_project(self) -> None:
        """Drill down into the selected project."""
        ptable = self.query_one('#project-table', DataTable)
        cursor = ptable.cursor_row
        if 0 <= cursor < len(self._project_slugs):
            slug = self._project_slugs[cursor]
            ctx = self._nav_context.drill_down(
                DashboardLevel.PROJECT, project_slug=slug,
            )
            _navigate_to_context(self.app, ctx)

    def _navigate_to_job(self) -> None:
        """Drill down into the selected session (job)."""
        stable = self.query_one('#session-table', DataTable)
        cursor_row = stable.cursor_row
        if 0 <= cursor_row < len(self._session_ids):
            sid = self._session_ids[cursor_row]
            ctx = self._nav_context.drill_down(
                DashboardLevel.JOB,
                project_slug=self._selected_project,
                job_id=sid,
            )
            _navigate_to_context(self.app, ctx)

    def action_new_session(self) -> None:
        from projects.POC.tui.screens.launch import LaunchScreen
        self.app.push_screen(LaunchScreen(self._selected_project))

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


def _session_snapshot(proj) -> list[tuple]:
    if not proj:
        return []
    return [
        (s.session_id, s.status, s.cfa_phase, s.cfa_state,
         s.needs_input, len(s.dispatches))
        for s in proj.sessions
    ]


def _navigate_to_context(app, ctx: NavigationContext) -> None:
    """Navigate the app to the screen for the given NavigationContext.

    Pops all screens back to the base and pushes the appropriate screen.
    """
    # Pop back to base screen
    while len(app.screen_stack) > 1:
        app.pop_screen()

    if ctx.level == DashboardLevel.MANAGEMENT:
        return  # Already at management (base screen)

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
