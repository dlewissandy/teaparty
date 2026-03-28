"""Project Dashboard — single project view with jobs, workgroups, and project-scoped cards."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.coordinate import Coordinate
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


class ProjectDashboard(Screen):
    """Single project view. Cards: escalations, sessions/jobs, workgroups, agents, skills."""

    BINDINGS = [
        Binding('escape', 'go_back', 'Back', show=True),
        Binding('enter', 'select_job', 'Open Job', show=True),
        Binding('w', 'withdraw', 'Withdraw', show=True),
        Binding('n', 'new_session', 'New Session', show=True),
        Binding('r', 'refresh', 'Refresh', show=True),
        Binding('c', 'open_chat', 'Chat', show=True),
    ]

    def __init__(self, nav_context: NavigationContext) -> None:
        super().__init__()
        self._nav_context = nav_context

    def compose(self) -> ComposeResult:
        yield Header()
        yield BreadcrumbBar(self._nav_context, id='breadcrumb-bar')
        yield Horizontal(
            Vertical(
                Static(f'JOBS ({self._nav_context.project_slug})', classes='section-title'),
                DataTable(id='job-table'),
                id='left-pane',
            ),
            Vertical(
                Static('DETAILS', classes='section-title', id='details-title'),
                VerticalScroll(
                    Static('', id='job-details-panel'),
                    id='details-scroll',
                ),
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
        yield Footer()

    def on_mount(self) -> None:
        jtable = self.query_one('#job-table', DataTable)
        jtable.cursor_type = 'row'
        jtable.add_columns('', 'Session', 'State', 'Idle', 'Dur')

        self._session_ids: list[str] = []
        self._last_snap: list[tuple] = []
        self._refresh_data(force=True)

    def _refresh_data(self, force: bool = False) -> None:
        reader = self.app.state_reader
        reader.reload()

        proj = reader.find_project(self._nav_context.project_slug)
        snap = _session_snapshot(proj)
        if force or snap != self._last_snap:
            self._last_snap = snap
            self._rebuild_job_table(proj)
        else:
            self._update_times(proj)

        self._update_details()
        self._update_prompt_panel()

    def _rebuild_job_table(self, proj) -> None:
        jtable = self.query_one('#job-table', DataTable)
        old_cursor = jtable.cursor_row
        jtable.clear()
        self._session_ids = []

        if not proj:
            jtable.add_row('', '(project not found)', '', '', '')
            return

        for sess in proj.sessions:
            icon = _status_icon(sess.status, sess.needs_input, getattr(sess, 'is_orphaned', False))
            state = _state_display(sess.cfa_phase, sess.cfa_state)
            idle = _human_age(sess.stream_age_seconds)
            dur = _human_age(sess.duration_seconds)
            jtable.add_row(icon, sess.session_id, state, idle, dur)
            self._session_ids.append(sess.session_id)

        if not self._session_ids:
            jtable.add_row('', '(no jobs)', '', '', '')

        if 0 <= old_cursor < len(self._session_ids):
            jtable.move_cursor(row=old_cursor)

    def _update_times(self, proj) -> None:
        if not proj:
            return
        jtable = self.query_one('#job-table', DataTable)
        for row_idx, sess in enumerate(proj.sessions):
            if row_idx >= len(self._session_ids):
                break
            jtable.update_cell_at(Coordinate(row_idx, 3), _human_age(sess.stream_age_seconds))
            jtable.update_cell_at(Coordinate(row_idx, 4), _human_age(sess.duration_seconds))

    def _update_details(self) -> None:
        panel = self.query_one('#job-details-panel', Static)
        jtable = self.query_one('#job-table', DataTable)
        cursor_row = jtable.cursor_row

        if not self._session_ids or cursor_row < 0 or cursor_row >= len(self._session_ids):
            panel.update('  (no job selected)')
            return

        sid = self._session_ids[cursor_row]
        session = self.app.state_reader.find_session(sid)
        if not session:
            panel.update('  (session not found)')
            return

        lines = [
            f'[bold]Job:[/bold] {session.session_id}',
            f'[bold]Phase:[/bold] {session.cfa_phase or chr(0x2014)}',
            f'[bold]State:[/bold] {session.cfa_state or chr(0x2014)}',
            f'[bold]Dispatches:[/bold] {len(session.dispatches)}',
        ]
        panel.update('\n'.join(lines))

    def _update_prompt_panel(self) -> None:
        title = self.query_one('#prompt-title', Static)
        panel = self.query_one('#dash-prompt-panel', Static)
        jtable = self.query_one('#job-table', DataTable)
        cursor_row = jtable.cursor_row

        if not self._session_ids or cursor_row < 0 or cursor_row >= len(self._session_ids):
            title.update('PROMPT')
            panel.update('  (no job selected)')
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
        self._update_details()
        self._update_prompt_panel()

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.action_select_job()

    def on_breadcrumb_bar_navigate(self, event: BreadcrumbBar.Navigate) -> None:
        from projects.POC.tui.screens.management_dashboard import _navigate_to_context
        _navigate_to_context(self.app, event.nav_context)

    def action_select_job(self) -> None:
        jtable = self.query_one('#job-table', DataTable)
        cursor_row = jtable.cursor_row
        if 0 <= cursor_row < len(self._session_ids):
            sid = self._session_ids[cursor_row]
            ctx = self._nav_context.drill_down(DashboardLevel.JOB, job_id=sid)
            from projects.POC.tui.screens.management_dashboard import _navigate_to_context
            _navigate_to_context(self.app, ctx)

    def action_withdraw(self) -> None:
        jtable = self.query_one('#job-table', DataTable)
        cursor_row = jtable.cursor_row
        if cursor_row < 0 or cursor_row >= len(self._session_ids):
            self.notify('No job selected', severity='warning')
            return
        sid = self._session_ids[cursor_row]
        session = self.app.state_reader.find_session(sid)
        if not session:
            self.notify('Session not found', severity='warning')
            return
        if session.cfa_state in ('COMPLETED_WORK', 'WITHDRAWN'):
            self.notify('Job is already terminal', severity='warning')
            return

        import asyncio
        from projects.POC.tui.withdraw import withdraw_session
        in_proc = self.app.get_in_process(sid)
        in_task = in_proc.run_task if in_proc else None
        bus = in_proc.event_bus if in_proc else None

        async def _withdraw():
            await withdraw_session(session, event_bus=bus, in_process_task=in_task)

        asyncio.create_task(_withdraw())
        self.notify(f'Job {sid} withdrawn')
        self._refresh_data(force=True)

    def action_new_session(self) -> None:
        from projects.POC.tui.screens.launch import LaunchScreen
        self.app.push_screen(LaunchScreen(self._nav_context.project_slug))

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_refresh(self) -> None:
        self._refresh_data(force=True)

    def action_open_chat(self) -> None:
        from projects.POC.tui.screens.chat import ChatScreen
        self.app.push_screen(ChatScreen())

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
