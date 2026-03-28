"""Project Dashboard — single project view with content cards per design spec.

Cards: Escalations, Sessions, Jobs, Workgroups, Agents, Skills, Scheduled Tasks, Hooks.
Stats bar scoped to this project. Breadcrumb: TeaParty > ProjectName.
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


class ProjectDashboard(Screen):
    """Single project view with content cards + stats + breadcrumbs."""

    BINDINGS = [
        Binding('escape', 'go_back', 'Back', show=True),
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
        yield StatsBar(id='project-stats')
        yield VerticalScroll(
            Horizontal(
                Vertical(
                    ContentCard('ESCALATIONS', 'escalations'),
                    ContentCard('SESSIONS', 'sessions', show_new_button=True),
                    ContentCard('JOBS', 'jobs', show_new_button=True),
                    ContentCard('WORKGROUPS', 'workgroups', show_new_button=True),
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
        proj = reader.find_project(self._nav_context.project_slug)
        self._update_stats(proj)
        self._update_escalations(proj)
        self._update_sessions(proj)
        self._update_jobs(proj)

    def _update_stats(self, proj) -> None:
        if not proj:
            return
        total = len(proj.sessions)
        active = proj.active_count
        completed = sum(1 for s in proj.sessions if s.cfa_state == 'COMPLETED_WORK')
        withdrawn = sum(1 for s in proj.sessions if s.cfa_state == 'WITHDRAWN')
        escalations = proj.attention_count

        stats = [
            ('Jobs', str(total)),
            ('Active', str(active)),
            ('Done', str(completed)),
            ('Withdrawn', str(withdrawn)),
            ('Escalations', str(escalations)),
        ]
        try:
            self.query_one('#project-stats', StatsBar).update_stats(stats)
        except Exception:
            pass

    def _update_escalations(self, proj) -> None:
        if not proj:
            return
        items = []
        for sess in proj.sessions:
            if sess.needs_input:
                items.append(CardItem(
                    icon='\u23f3',
                    label=sess.session_id,
                    detail=sess.cfa_state,
                    data={'session_id': sess.session_id},
                ))
        self._update_card('escalations', items)

    def _update_sessions(self, proj) -> None:
        if not proj:
            return
        items = []
        for sess in proj.sessions:
            if sess.status == 'active':
                icon = _status_icon(sess.status, sess.needs_input, sess.is_orphaned)
                items.append(CardItem(
                    icon=icon,
                    label=sess.session_id,
                    detail=f'{_state_display(sess.cfa_phase, sess.cfa_state)} {_human_age(sess.stream_age_seconds)}',
                    data={'session_id': sess.session_id},
                ))
        self._update_card('sessions', items)

    def _update_jobs(self, proj) -> None:
        if not proj:
            return
        items = []
        for sess in proj.sessions:
            icon = _status_icon(sess.status, sess.needs_input, sess.is_orphaned)
            state = _state_display(sess.cfa_phase, sess.cfa_state)
            dur = _human_age(sess.duration_seconds)
            items.append(CardItem(
                icon=icon,
                label=sess.session_id,
                detail=f'{state}  {dur}',
                data={'session_id': sess.session_id},
            ))
        self._update_card('jobs', items)

    def _update_card(self, card_name: str, items: list[CardItem]) -> None:
        try:
            for widget in self.query(ContentCard):
                if widget._card_name == card_name:
                    widget.update_items(items)
                    break
        except Exception:
            pass

    def on_content_card_item_selected(self, event: ContentCard.ItemSelected) -> None:
        data = event.item.data or {}
        if event.card_name in ('jobs', 'escalations', 'sessions'):
            sid = data.get('session_id', '')
            if sid:
                ctx = self._nav_context.drill_down(DashboardLevel.JOB, job_id=sid)
                from projects.POC.tui.screens.management_dashboard import _navigate_to_context
                _navigate_to_context(self.app, ctx)

    def on_content_card_new_requested(self, event: ContentCard.NewRequested) -> None:
        if event.card_name in ('sessions', 'jobs'):
            self.action_new_session()

    def on_breadcrumb_bar_navigate(self, event: BreadcrumbBar.Navigate) -> None:
        from projects.POC.tui.screens.management_dashboard import _navigate_to_context
        _navigate_to_context(self.app, event.nav_context)

    def action_withdraw(self) -> None:
        self.notify('Select a job to withdraw', severity='warning')

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
