"""Dashboard screen — projects, sessions, and dispatches hierarchy."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Static


def _human_age(seconds: int) -> str:
    if seconds < 0:
        return '\u2014'
    if seconds < 60:
        return f'{seconds}s'
    if seconds < 3600:
        return f'{seconds // 60}m'
    return f'{seconds // 3600}h{seconds % 3600 // 60}m'


def _status_icon(status: str, needs_input: bool = False) -> str:
    if needs_input:
        return '\u23f3'  # hourglass
    if status == 'active':
        return '\u25b6'  # right-pointing triangle
    if status == 'complete':
        return '\u2713'  # check mark
    if status == 'failed':
        return '\u2717'  # ballot x
    return ' '


def _dispatch_icon(status: str) -> str:
    if status == 'active':
        return '\u25b6'
    if status == 'failed':
        return '\u2717'
    if status == 'complete':
        return '\u2713'
    return '\u2591'


def _state_display(phase: str, state: str) -> str:
    if not phase and not state:
        return '\u2014'
    if state in ('COMPLETED_WORK', 'WITHDRAWN'):
        return state
    if phase:
        return f'{phase}/{state}'
    return state


def _project_snapshot(reader) -> list[tuple]:
    """Build a comparable snapshot of project data."""
    return [
        (p.slug, len(p.sessions), p.active_count, p.attention_count)
        for p in reader.projects
    ]


def _session_snapshot(proj) -> list[tuple]:
    """Build a comparable snapshot of session data for a project."""
    if not proj:
        return []
    return [
        (s.session_id, s.status, s.cfa_phase, s.cfa_state,
         s.needs_input, len(s.dispatches), s.stream_age_seconds)
        for s in proj.sessions
    ]


class DashboardScreen(Screen):
    """Main dashboard showing Projects \u2192 Sessions \u2192 Dispatches."""

    BINDINGS = [
        Binding('enter', 'select_session', 'Drilldown', show=True),
        Binding('n', 'new_session', 'New Session', show=True),
        Binding('d', 'diagnostics', 'Diagnostics', show=True),
        Binding('r', 'refresh', 'Refresh', show=True),
        Binding('q', 'quit_app', 'Quit', show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
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
            Static('DISPATCHES', classes='section-title', id='dispatch-title'),
            Static('', id='dash-dispatch-panel'),
            id='bottom-pane',
        )
        yield Footer()

    def on_mount(self) -> None:
        # Project table
        ptable = self.query_one('#project-table', DataTable)
        ptable.cursor_type = 'row'
        ptable.add_columns('', 'Project', '#', '')

        # Session table
        stable = self.query_one('#session-table', DataTable)
        stable.cursor_type = 'row'
        stable.add_columns('', 'Session', 'Task', 'State', '#D', 'Age')

        self._project_slugs: list[str] = []
        self._session_ids: list[str] = []
        self._selected_project: str = ''
        self._last_project_snap: list[tuple] = []
        self._last_session_snap: list[tuple] = []
        self._refresh_data(force=True)

    def _refresh_data(self, force: bool = False) -> None:
        reader = self.app.state_reader
        reader.reload()

        # Only rebuild project table if data changed
        proj_snap = _project_snapshot(reader)
        if force or proj_snap != self._last_project_snap:
            self._last_project_snap = proj_snap
            self._rebuild_project_table()

        # Only rebuild session table if data changed
        proj = reader.find_project(self._selected_project)
        sess_snap = _session_snapshot(proj)
        if force or sess_snap != self._last_session_snap:
            self._last_session_snap = sess_snap
            self._rebuild_session_table()

        self._update_dispatch_panel()

    def _rebuild_project_table(self) -> None:
        ptable = self.query_one('#project-table', DataTable)
        old_cursor = ptable.cursor_row
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

        # Preserve selection by slug, fall back to first project
        if not self._selected_project or self._selected_project not in self._project_slugs:
            self._selected_project = self._project_slugs[0]

        # Move cursor to the selected project's current position
        idx = self._project_slugs.index(self._selected_project)
        ptable.move_cursor(row=idx)

    def _rebuild_session_table(self) -> None:
        stable = self.query_one('#session-table', DataTable)
        title = self.query_one('#sessions-title', Static)
        old_cursor = stable.cursor_row
        stable.clear()

        self._session_ids = []

        proj = self.app.state_reader.find_project(self._selected_project)
        if not proj:
            title.update('SESSIONS')
            return

        title.update(f'SESSIONS ({proj.slug})')

        for sess in proj.sessions:
            icon = _status_icon(sess.status, sess.needs_input)
            task_short = sess.task[:45] + ('...' if len(sess.task) > 45 else '')
            state = _state_display(sess.cfa_phase, sess.cfa_state)
            dispatches = str(len(sess.dispatches))
            age = _human_age(sess.stream_age_seconds)
            stable.add_row(icon, sess.session_id, task_short, state, dispatches, age)
            self._session_ids.append(sess.session_id)

        if not self._session_ids:
            stable.add_row('', '(no sessions)', '', '', '', '')

        # Restore cursor
        if 0 <= old_cursor < len(self._session_ids):
            stable.move_cursor(row=old_cursor)

    def _update_dispatch_panel(self) -> None:
        title = self.query_one('#dispatch-title', Static)
        panel = self.query_one('#dash-dispatch-panel', Static)

        stable = self.query_one('#session-table', DataTable)
        cursor_row = stable.cursor_row

        if not self._session_ids or cursor_row < 0 or cursor_row >= len(self._session_ids):
            title.update('DISPATCHES')
            panel.update('  (no session selected)')
            return

        sid = self._session_ids[cursor_row]
        session = self.app.state_reader.find_session(sid)
        if not session or not session.dispatches:
            title.update(f'DISPATCHES ({sid})')
            panel.update('  (no dispatches)')
            return

        title.update(f'DISPATCHES ({sid})')

        by_team: dict[str, list] = {}
        for d in session.dispatches:
            by_team.setdefault(d.team or '?', []).append(d)

        lines = []
        for team, dispatches in sorted(by_team.items()):
            lines.append(f'  [bold]{team}[/bold]')
            for d in dispatches:
                icon = _dispatch_icon(d.status)
                name = d.worktree_name
                if '--' in name:
                    name = name.split('--', 1)[1][:30]
                state = _state_display(d.cfa_phase, d.cfa_state) if d.cfa_state else d.status
                age = _human_age(d.stream_age_seconds)
                lines.append(f'    {icon} {name:<32} {state:<24} {age}')

        panel.update('\n'.join(lines))

    def on_data_table_cursor_moved(self, event: DataTable.CursorMoved) -> None:
        table_id = event.data_table.id
        if table_id == 'project-table':
            cursor = event.data_table.cursor_row
            if 0 <= cursor < len(self._project_slugs):
                new_project = self._project_slugs[cursor]
                if new_project != self._selected_project:
                    self._selected_project = new_project
                    self._last_session_snap = []  # force session rebuild
                    self._rebuild_session_table()
                    self._update_dispatch_panel()
        elif table_id == 'session-table':
            self._update_dispatch_panel()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Handle Enter key on DataTable row."""
        table_id = event.data_table.id
        if table_id == 'session-table':
            self.action_select_session()
        elif table_id == 'project-table':
            # Enter on project focuses the session table
            self.query_one('#session-table', DataTable).focus()

    def action_select_session(self) -> None:
        stable = self.query_one('#session-table', DataTable)
        cursor_row = stable.cursor_row
        if 0 <= cursor_row < len(self._session_ids):
            sid = self._session_ids[cursor_row]
            from projects.POC.tui.screens.drilldown import DrilldownScreen
            self.app.push_screen(DrilldownScreen(sid))

    def action_new_session(self) -> None:
        from projects.POC.tui.screens.launch import LaunchScreen
        self.app.push_screen(LaunchScreen())

    def action_diagnostics(self) -> None:
        from projects.POC.tui.screens.diagnostics import DiagnosticsScreen
        self.app.push_screen(DiagnosticsScreen())

    def action_refresh(self) -> None:
        self._refresh_data(force=True)

    def action_quit_app(self) -> None:
        self.app.exit()

    def on_timer(self) -> None:
        """Called by the app's periodic refresh."""
        self._refresh_data()
