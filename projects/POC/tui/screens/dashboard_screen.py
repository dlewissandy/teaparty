"""Unified dashboard screen — one parameterized screen for all five navigation levels.

Layout: breadcrumb bar, stats bar, scrollable two-column card grid.
Cards, stats, and click behavior are determined by the NavigationContext.
"""
from __future__ import annotations

import os
import subprocess

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Click
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from projects.POC.tui.navigation import (
    DashboardLevel,
    NavigationContext,
    card_defs_for_level,
    breadcrumbs_for_level,
)
from projects.POC.tui.widgets.breadcrumb_bar import BreadcrumbBar
from projects.POC.tui.widgets.content_card import CardItem, ContentCard
from projects.POC.tui.widgets.stats_bar import StatsBar


# ── Helpers ──

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


# ── Screen ──

class DashboardScreen(Screen):
    """Unified dashboard for all five navigation levels."""

    BINDINGS = [
        Binding('escape', 'go_back', 'Back', show=True),
        Binding('r', 'refresh', 'Refresh', show=True),
        Binding('q', 'quit_app', 'Quit', show=True),
        Binding('c', 'open_chat', 'Chat', show=True),
        Binding('f', 'change_folder', 'Folder', show=False),
        Binding('n', 'new_session', 'New Session', show=False),
        Binding('p', 'new_project', 'New Project', show=False),
        Binding('d', 'diagnostics', 'Diagnostics', show=False),
        Binding('x', 'proxy_review', 'Proxy Review', show=False),
    ]

    def __init__(self, nav_context: NavigationContext | None = None):
        super().__init__()
        self._nav = nav_context or NavigationContext(level=DashboardLevel.MANAGEMENT)

    def compose(self) -> ComposeResult:
        yield Header()
        yield BreadcrumbBar(self._nav, id='breadcrumb-bar')
        yield StatsBar(id='dash-stats')
        card_defs = card_defs_for_level(self._nav.level)
        mid = (len(card_defs) + 1) // 2
        left_defs = card_defs[:mid]
        right_defs = card_defs[mid:]
        yield VerticalScroll(
            Horizontal(
                Vertical(
                    *(ContentCard(d.title, d.name, show_new_button=d.new_button)
                      for d in left_defs),
                    id='card-col-left',
                    classes='card-column',
                ),
                Vertical(
                    *(ContentCard(d.title, d.name, show_new_button=d.new_button)
                      for d in right_defs),
                    id='card-col-right',
                    classes='card-column',
                ),
                id='card-cols',
                classes='card-columns',
            ),
        )
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_data()
        self._update_columns()

    def on_resize(self) -> None:
        self._update_columns()

    def _update_columns(self) -> None:
        try:
            cols = self.query_one('#card-cols')
            if self.size.width < 80:
                cols.add_class('-narrow')
            else:
                cols.remove_class('-narrow')
        except Exception:
            pass

    # ── Data refresh ──

    def _refresh_data(self) -> None:
        reader = self.app.state_reader
        reader.reload()
        level = self._nav.level

        if level == DashboardLevel.MANAGEMENT:
            self._refresh_management(reader)
        elif level == DashboardLevel.PROJECT:
            proj = reader.find_project(self._nav.project_slug)
            self._refresh_project(reader, proj)
        elif level == DashboardLevel.WORKGROUP:
            pass  # data pending #251
        elif level == DashboardLevel.JOB:
            session = reader.find_session(self._nav.job_id)
            self._refresh_job(reader, session)
        elif level == DashboardLevel.TASK:
            session = reader.find_session(self._nav.job_id)
            dispatch = self._find_dispatch(session)
            self._refresh_task(reader, session, dispatch)

    def _refresh_management(self, reader) -> None:
        projects = reader.projects
        total = sum(len(p.sessions) for p in projects)
        active = sum(p.active_count for p in projects)
        done = sum(1 for p in projects for s in p.sessions if s.cfa_state == 'COMPLETED_WORK')
        withdrawn = sum(1 for p in projects for s in p.sessions if s.cfa_state == 'WITHDRAWN')
        attention = sum(p.attention_count for p in projects)
        self._set_stats([
            ('Projects', str(len(projects))), ('Jobs', str(total)),
            ('Active', str(active)), ('Done', str(done)),
            ('Withdrawn', str(withdrawn)), ('Escalations', str(attention)),
        ])

        # Escalations
        items = []
        for proj in projects:
            for sess in proj.sessions:
                if sess.needs_input:
                    items.append(CardItem(
                        icon='\u23f3', label=f'{proj.slug}/{sess.session_id}',
                        detail=sess.cfa_state,
                        data={'project': proj.slug, 'session_id': sess.session_id},
                    ))
        self._set_card('escalations', items)

        # Sessions (active only)
        items = []
        for proj in projects:
            for sess in proj.sessions:
                if sess.status == 'active':
                    items.append(CardItem(
                        icon=_status_icon(sess.status, sess.needs_input, sess.is_orphaned),
                        label=f'{proj.slug}/{sess.session_id}',
                        detail=_state_display(sess.cfa_phase, sess.cfa_state),
                        data={'project': proj.slug, 'session_id': sess.session_id},
                    ))
        self._set_card('sessions', items)

        # Projects
        items = []
        for proj in projects:
            attn = ' \u23f3' if proj.attention_count > 0 else ''
            items.append(CardItem(
                icon='\u25b6' if proj.active_count > 0 else '\u2713',
                label=proj.slug,
                detail=f'{proj.active_count} active / {len(proj.sessions)} total{attn}',
                data={'project': proj.slug},
            ))
        self._set_card('projects', items)

        # Humans — always show the current user
        import getpass
        username = getpass.getuser()
        self._set_card('humans', [
            CardItem(icon='\u263a', label=username, detail='decider'),
        ])

    def _refresh_project(self, reader, proj) -> None:
        if not proj:
            return
        total = len(proj.sessions)
        active = proj.active_count
        done = sum(1 for s in proj.sessions if s.cfa_state == 'COMPLETED_WORK')
        withdrawn = sum(1 for s in proj.sessions if s.cfa_state == 'WITHDRAWN')
        self._set_stats([
            ('Jobs', str(total)), ('Active', str(active)),
            ('Done', str(done)), ('Withdrawn', str(withdrawn)),
            ('Escalations', str(proj.attention_count)),
        ])

        # Escalations
        items = [
            CardItem(icon='\u23f3', label=s.session_id, detail=s.cfa_state,
                     data={'session_id': s.session_id})
            for s in proj.sessions if s.needs_input
        ]
        self._set_card('escalations', items)

        # Sessions (active)
        items = [
            CardItem(
                icon=_status_icon(s.status, s.needs_input, s.is_orphaned),
                label=s.session_id,
                detail=f'{_state_display(s.cfa_phase, s.cfa_state)} {_human_age(s.stream_age_seconds)}',
                data={'session_id': s.session_id},
            )
            for s in proj.sessions if s.status == 'active'
        ]
        self._set_card('sessions', items)

        # Jobs (all sessions)
        items = [
            CardItem(
                icon=_status_icon(s.status, s.needs_input, s.is_orphaned),
                label=s.session_id,
                detail=f'{_state_display(s.cfa_phase, s.cfa_state)}  {_human_age(s.duration_seconds)}',
                data={'session_id': s.session_id},
            )
            for s in proj.sessions
        ]
        self._set_card('jobs', items)

    def _refresh_job(self, reader, session) -> None:
        if not session:
            return
        dispatches = session.dispatches or []
        active_d = sum(1 for d in dispatches if d.status == 'active')
        complete_d = sum(1 for d in dispatches if d.status == 'complete')
        self._set_stats([
            ('Tasks', f'{complete_d}/{len(dispatches)}'),
            ('Active', str(active_d)),
            ('Elapsed', _human_age(session.duration_seconds)),
            ('Idle', _human_age(session.stream_age_seconds)),
        ])

        # Escalations
        items = []
        if session.needs_input:
            items.append(CardItem(icon='\u23f3', label=session.cfa_state))
        self._set_card('escalations', items)

        # Artifacts
        items = []
        for name, label in [('INTENT.md', 'Intent'), ('plan.md', 'Plan'), ('.work-summary.md', 'Work Summary')]:
            path = self._find_doc(session, name)
            if path:
                items.append(CardItem(icon='\u2713', label=label, detail=name, data={'path': path}))
            else:
                items.append(CardItem(icon='\u2591', label=f'[dim]{label}[/dim]'))
        self._set_card('artifacts', items)

        # Tasks (dispatches)
        items = []
        for d in dispatches:
            if d.status == 'active':
                name = d.worktree_name
                if '--' in name:
                    name = name.split('--', 1)[1][:25]
                elif not name:
                    name = os.path.basename(d.infra_dir) if d.infra_dir else '?'
                items.append(CardItem(
                    icon='\u25b6', label=name,
                    detail=f'{d.team or "?"} {_human_age(d.stream_age_seconds)}',
                    data={'dispatch': d},
                ))
        self._set_card('tasks', items)

    def _refresh_task(self, reader, session, dispatch) -> None:
        if not dispatch:
            return
        self._set_stats([
            ('Team', dispatch.team or '?'),
            ('Status', dispatch.status or '\u2014'),
            ('Age', _human_age(dispatch.stream_age_seconds)),
        ])

        # Escalations (none in current model)
        self._set_card('escalations', [])

        # Artifacts (changed files)
        wt = self._dispatch_worktree(dispatch, session)
        items = []
        if wt:
            try:
                result = subprocess.run(
                    ['git', 'diff', '--name-only', 'HEAD'],
                    cwd=wt, capture_output=True, text=True, timeout=5,
                )
                for f in result.stdout.strip().split('\n'):
                    if f:
                        items.append(CardItem(label=f))
            except (subprocess.TimeoutExpired, OSError):
                pass
        self._set_card('artifacts', items)

        # Todo list
        from projects.POC.tui.todo_reader import read_todos_from_streams
        stream_files = self._dispatch_stream_files(dispatch)
        todos = read_todos_from_streams(stream_files)
        items = []
        for todo in todos:
            status = todo.get('status', 'pending')
            icon = '\u2713' if status == 'completed' else '\u2610' if status == 'in_progress' else '\u2591'
            items.append(CardItem(icon=icon, label=todo.get('content', '?')))
        self._set_card('todo_list', items)

    # ── Card/stats helpers ──

    def _set_stats(self, stats: list[tuple[str, str]]) -> None:
        try:
            self.query_one('#dash-stats', StatsBar).update_stats(stats)
        except Exception:
            pass

    def _set_card(self, card_name: str, items: list[CardItem]) -> None:
        try:
            for widget in self.query(ContentCard):
                if widget._card_name == card_name:
                    widget.update_items(items)
                    break
        except Exception:
            pass

    # ── Click routing (called directly from item markup via screen.card_click) ──

    def _find_card(self, card_name: str) -> ContentCard | None:
        for widget in self.query(ContentCard):
            if widget._card_name == card_name:
                return widget
        return None

    def action_card_click(self, card_name: str, index: int) -> None:
        """Handle click on a card item. Called via [@click=screen.card_click(...)]."""
        card = self._find_card(card_name)
        if not card or index < 0 or index >= len(card._items):
            return
        item = card._items[index]
        data = item.data or {}
        level = self._nav.level

        if card_name == 'projects':
            slug = data.get('project', '')
            if slug:
                self._navigate(self._nav.drill_down(DashboardLevel.PROJECT, project_slug=slug))

        elif card_name == 'jobs':
            if level == DashboardLevel.MANAGEMENT:
                project = data.get('project', '')
                sid = data.get('session_id', '')
                if project and sid:
                    self._navigate(self._nav.drill_down(
                        DashboardLevel.JOB, project_slug=project, job_id=sid,
                    ))
            else:
                sid = data.get('session_id', '')
                if sid:
                    self._navigate(self._nav.drill_down(DashboardLevel.JOB, job_id=sid))

        elif card_name in ('escalations', 'sessions'):
            sid = data.get('session_id', '')
            conv = f'session:{sid}' if sid else ''
            open_chat_window(self.app, conversation=conv)

        elif card_name == 'humans':
            import getpass
            open_chat_window(self.app, ensure_proxy_review=getpass.getuser())

        elif card_name == 'workgroups':
            wg_id = data.get('workgroup_id', '')
            if wg_id:
                self._navigate(self._nav.drill_down(DashboardLevel.WORKGROUP, workgroup_id=wg_id))

        elif card_name == 'tasks':
            dispatch = data.get('dispatch')
            if dispatch:
                task_id = os.path.basename(dispatch.infra_dir) if dispatch.infra_dir else dispatch.worktree_name
                self._navigate(self._nav.drill_down(DashboardLevel.TASK, task_id=task_id))

        elif card_name == 'artifacts':
            path = data.get('path', '')
            if path:
                from projects.POC.tui.platform_utils import open_file
                open_file(path)

    def action_card_new(self, card_name: str) -> None:
        """Handle '+ New' click on a card. Called via [@click=screen.card_new(...)]."""
        if card_name in ('sessions', 'jobs'):
            self.action_new_session()
        elif card_name == 'projects':
            self.action_new_project()

    def on_breadcrumb_bar_navigate(self, event: BreadcrumbBar.Navigate) -> None:
        self._navigate(event.nav_context)

    # ── Navigation ──

    def _navigate(self, ctx: NavigationContext) -> None:
        navigate_to(self.app, ctx)

    # ── Actions ──

    def action_go_back(self) -> None:
        if self._nav.level == DashboardLevel.MANAGEMENT:
            self.app.exit()
        else:
            self.app.pop_screen()

    def action_refresh(self) -> None:
        self._refresh_data()

    def action_quit_app(self) -> None:
        self.app.exit()

    def action_open_chat(self) -> None:
        open_chat_window(self.app)

    def action_new_session(self) -> None:
        from projects.POC.tui.screens.launch import LaunchScreen
        project = self._nav.project_slug
        if not project:
            reader = self.app.state_reader
            project = reader.projects[0].slug if reader.projects else ''
        self.app.push_screen(LaunchScreen(project))

    def action_new_project(self) -> None:
        from projects.POC.tui.screens.new_project import NewProjectScreen
        self.app.push_screen(NewProjectScreen())

    def action_diagnostics(self) -> None:
        from projects.POC.tui.screens.diagnostics import DiagnosticsScreen
        self.app.push_screen(DiagnosticsScreen())

    def action_change_folder(self) -> None:
        from projects.POC.tui.screens.dashboard import ChangeProjectDirScreen
        self.app.push_screen(ChangeProjectDirScreen())

    def action_proxy_review(self) -> None:
        import getpass
        open_chat_window(self.app, ensure_proxy_review=getpass.getuser())

    def periodic_refresh(self) -> None:
        self._refresh_data()

    # ── File resolution helpers ──

    def _find_doc(self, session, filename: str) -> str | None:
        if session and session.infra_dir:
            p = os.path.join(session.infra_dir, filename)
            if os.path.exists(p):
                return p
        if session and session.worktree_path and os.path.isdir(session.worktree_path):
            p = os.path.join(session.worktree_path, filename)
            if os.path.exists(p):
                return p
        return None

    def _find_dispatch(self, session) -> object | None:
        if not session:
            return None
        for d in session.dispatches:
            task_id = os.path.basename(d.infra_dir) if d.infra_dir else d.worktree_name
            if task_id == self._nav.task_id:
                return d
        return session.dispatches[0] if session.dispatches else None

    def _dispatch_worktree(self, dispatch, session) -> str | None:
        if not dispatch:
            return None
        if dispatch.worktree_path and os.path.isdir(dispatch.worktree_path):
            return dispatch.worktree_path
        if dispatch.worktree_name and session:
            proj = self.app.state_reader.find_project(session.project)
            if proj:
                wt = os.path.join(proj.path, '.worktrees', dispatch.worktree_name)
                if os.path.isdir(wt):
                    return wt
        return None

    def _dispatch_stream_files(self, dispatch) -> list[str]:
        if not dispatch or not dispatch.infra_dir or not os.path.isdir(dispatch.infra_dir):
            return []
        files = []
        try:
            for name in os.listdir(dispatch.infra_dir):
                if name.endswith('.jsonl'):
                    files.append(os.path.join(dispatch.infra_dir, name))
        except OSError:
            pass
        return files


# ── Module-level helpers (used by app.py and other screens) ──

def navigate_to(app, ctx: NavigationContext) -> None:
    """Navigate the app to the screen for the given NavigationContext."""
    while len(app.screen_stack) > 1:
        app.pop_screen()

    if ctx.level == DashboardLevel.MANAGEMENT:
        return  # base screen is already management

    app.push_screen(DashboardScreen(ctx))


def open_chat_window(app, conversation: str = '', ensure_proxy_review: str = '') -> None:
    """Spawn the chat UI in a separate terminal window.

    If conversation is given, the chat opens to that specific conversation.
    """
    from pathlib import Path
    from projects.POC.tui.platform_utils import open_terminal
    repo_root = str(Path(app.poc_root).parent.parent)
    cmd = ['uv', 'run', 'python', '-m', 'projects.POC.tui.chat_main',
           '--project-dir', app.projects_dir]
    if conversation:
        cmd += ['--conversation', conversation]
    if ensure_proxy_review:
        cmd += ['--ensure-proxy-review', ensure_proxy_review]
    open_terminal(cmd, title='TeaParty Chat', cwd=repo_root)
