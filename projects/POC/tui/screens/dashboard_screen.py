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
from textual.widgets import Footer, Static

from projects.POC.tui.navigation import (
    DashboardLevel,
    NavigationContext,
    card_defs_for_level,
    breadcrumbs_for_level,
)
from projects.POC.tui.widgets.content_card import CardItem, ContentCard


class _BreadcrumbStatic(Static):
    """A clickable breadcrumb that calls screen.action_breadcrumb_click."""

    def __init__(self, content: str, index: int, **kwargs):
        super().__init__(content, **kwargs)
        self._index = index

    def on_click(self) -> None:
        self.screen.action_breadcrumb_click(self._index)


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


def _colored_state(session) -> str:
    """Return the CFA state with color markup for a session."""
    state_text = _state_display(session.cfa_phase, session.cfa_state)
    if session.needs_input:
        return f'[dim red]{state_text}[/dim red]'
    if session.cfa_state == 'COMPLETED_WORK':
        return f'[green]{state_text}[/green]'
    if session.cfa_state == 'WITHDRAWN':
        return f'[dim]{state_text}[/dim]'
    return state_text


def _colored_dispatch_state(dispatch) -> str:
    """Return the CFA state with color markup for a dispatch."""
    state_text = _state_display(dispatch.cfa_phase, dispatch.cfa_state)
    if dispatch.cfa_state in _TERMINAL_STATES:
        if dispatch.cfa_state == 'COMPLETED_WORK':
            return f'[green]{state_text}[/green]  {dispatch.team or "?"}'
        return f'[dim]{state_text}[/dim]  {dispatch.team or "?"}'
    if dispatch.status == 'active':
        return f'{state_text}  {dispatch.team or "?"}  {_human_age(dispatch.stream_age_seconds)}'
    return f'[dim]{state_text}[/dim]  {dispatch.team or "?"}'


_TERMINAL_STATES = frozenset({'COMPLETED_WORK', 'WITHDRAWN'})


def _build_session_items(
    tagged_sessions: list[tuple[str, object]],
    include_project: bool = False,
    hide_done: bool = False,
) -> list[CardItem]:
    """Build sorted, color-coded CardItems from (project_slug, session) pairs.

    Three groups, each sorted newest first:
    1. Escalations (needs_input)
    2. Active (non-terminal, non-escalation)
    3. Terminal (COMPLETED_WORK, WITHDRAWN) — omitted if hide_done
    """
    escalations = []
    active = []
    terminal = []
    for slug, s in tagged_sessions:
        if s.needs_input:
            escalations.append((slug, s))
        elif s.cfa_state in _TERMINAL_STATES:
            terminal.append((slug, s))
        else:
            active.append((slug, s))
    escalations.sort(key=lambda t: t[1].session_id, reverse=True)
    active.sort(key=lambda t: t[1].session_id, reverse=True)
    terminal.sort(key=lambda t: t[1].session_id, reverse=True)

    combined = escalations + active
    if not hide_done:
        combined += terminal

    items = []
    for slug, s in combined:
        icon = _status_icon(s.status, s.needs_input, getattr(s, 'is_orphaned', False))
        label = f'{slug}/{s.session_id}' if include_project and slug else s.session_id
        detail = f'{_colored_state(s)}  {_human_age(s.duration_seconds)}'
        data = {'session_id': s.session_id}
        if slug:
            data['project'] = slug
        items.append(CardItem(icon=icon, label=label, detail=detail, data=data))
    return items


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

    _LEVEL_TITLES = {
        DashboardLevel.MANAGEMENT: 'Management Dashboard',
        DashboardLevel.PROJECT: 'Project Dashboard',
        DashboardLevel.WORKGROUP: 'Workgroup Dashboard',
        DashboardLevel.JOB: 'Job Dashboard',
        DashboardLevel.TASK: 'Task Dashboard',
    }

    def __init__(self, nav_context: NavigationContext | None = None):
        super().__init__()
        self._nav = nav_context or NavigationContext(level=DashboardLevel.MANAGEMENT)
        self._breadcrumb_contexts: list[NavigationContext] = []
        self._hide_done: dict[str, bool] = {'sessions': True, 'jobs': True}  # default: hide terminal

    def _title_text(self) -> str:
        title = self._LEVEL_TITLES.get(self._nav.level, 'Dashboard')
        # Add context info
        if self._nav.project_slug:
            title += f' \u2014 {self._nav.project_slug}'
        if self._nav.job_id:
            title += f' \u2014 {self._nav.job_id}'
        if self._nav.task_id:
            title += f' \u2014 {self._nav.task_id}'
        return f'[bold]{title}[/bold]'

    def _compose_breadcrumbs(self) -> ComposeResult:
        crumbs = breadcrumbs_for_level(self._nav)
        self._breadcrumb_contexts = []
        widgets = []
        for i, crumb in enumerate(crumbs):
            if i > 0:
                widgets.append(Static(' > ', classes='crumb-sep'))
            if crumb.clickable:
                self._breadcrumb_contexts.append(crumb.nav_context)
                idx = len(self._breadcrumb_contexts) - 1
                w = _BreadcrumbStatic(f'[bold]{crumb.label}[/bold]', index=idx, classes='crumb-link')
                widgets.append(w)
            else:
                widgets.append(Static(f'[dim]{crumb.label}[/dim]', classes='crumb-current'))
        return widgets

    def action_breadcrumb_click(self, index: int) -> None:
        if 0 <= index < len(self._breadcrumb_contexts):
            self._navigate(self._breadcrumb_contexts[index])

    def compose(self) -> ComposeResult:
        yield Static(self._title_text(), id='dash-title')
        yield Horizontal(*self._compose_breadcrumbs(), id='dash-breadcrumbs')
        yield Static('', id='dash-stats')
        card_defs = card_defs_for_level(self._nav.level)
        mid = (len(card_defs) + 1) // 2
        left_defs = card_defs[:mid]
        right_defs = card_defs[mid:]
        yield VerticalScroll(
            Horizontal(
                Vertical(
                    *(ContentCard(d.title, d.name, show_new_button=d.new_button, show_filter_button=d.filter_button)
                      for d in left_defs),
                    id='card-col-left',
                    classes='card-column',
                ),
                Vertical(
                    *(ContentCard(d.title, d.name, show_new_button=d.new_button, show_filter_button=d.filter_button)
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
        # Set initial filter state on cards
        for card_name, active in self._hide_done.items():
            card = self._find_card(card_name)
            if card:
                card.set_filter_active(active)
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

        # Sessions — escalations first, then rest, newest first
        tagged = [(proj.slug, s) for proj in projects for s in proj.sessions]
        self._set_card('sessions', _build_session_items(tagged, include_project=True, hide_done=self._hide_done.get('sessions', True)))

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

        # Sessions (active only)
        active = [('', s) for s in proj.sessions if s.status == 'active']
        self._set_card('sessions', _build_session_items(active, hide_done=self._hide_done.get('sessions', True)))

        # Jobs (all)
        all_jobs = [('', s) for s in proj.sessions]
        self._set_card('jobs', _build_session_items(all_jobs, hide_done=self._hide_done.get('jobs', True)))

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

        # Sessions — parent job session + all dispatch (subteam) sessions
        session_items = _build_session_items([('', session)])
        for d in dispatches:
            name = d.worktree_name
            if '--' in name:
                name = name.split('--', 1)[1][:25]
            elif not name:
                name = os.path.basename(d.infra_dir) if d.infra_dir else '?'
            state_text = _state_display(d.cfa_phase, d.cfa_state)
            if d.status == 'active':
                icon = '\u25b6'
                detail = f'{state_text}  {d.team or "?"}  {_human_age(d.stream_age_seconds)}'
            elif d.status == 'complete':
                icon = '\u2713'
                detail = f'[green]{state_text}[/green]  {d.team or "?"}'
            else:
                icon = '\u2717'
                detail = f'[dim]{state_text}[/dim]  {d.team or "?"}'
            session_items.append(CardItem(
                icon=icon, label=name, detail=detail,
                data={'dispatch': d},
            ))
        self._set_card('sessions', session_items)

        # Tasks — all dispatches with CFA state, same color coding
        task_items = []
        for d in dispatches:
            name = d.worktree_name
            if '--' in name:
                name = name.split('--', 1)[1][:25]
            elif not name:
                name = os.path.basename(d.infra_dir) if d.infra_dir else '?'
            task_items.append(CardItem(
                icon=_status_icon(d.status, False, False),
                label=name,
                detail=_colored_dispatch_state(d),
                data={'dispatch': d},
            ))
        self._set_card('tasks', task_items)

        # Artifacts
        items = []
        for name, label in [('INTENT.md', 'Intent'), ('plan.md', 'Plan'), ('.work-summary.md', 'Work Summary')]:
            path = self._find_doc(session, name)
            if path:
                items.append(CardItem(icon='\u2713', label=label, detail=name, data={'path': path}))
            else:
                items.append(CardItem(icon='\u2591', label=f'[dim]{label}[/dim]'))
        self._set_card('artifacts', items)

    def _refresh_task(self, reader, session, dispatch) -> None:
        if not dispatch:
            return
        self._set_stats([
            ('Team', dispatch.team or '?'),
            ('Status', dispatch.status or '\u2014'),
            ('Age', _human_age(dispatch.stream_age_seconds)),
        ])

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
        parts = [f'[bold]{k}:[/bold] {v}' for k, v in stats]
        try:
            self.query_one('#dash-stats', Static).update('  \u2502  '.join(parts))
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
            # At job level, dispatch items navigate to task dashboard
            dispatch = data.get('dispatch')
            if dispatch:
                task_id = os.path.basename(dispatch.infra_dir) if dispatch.infra_dir else dispatch.worktree_name
                self._navigate(self._nav.drill_down(DashboardLevel.TASK, task_id=task_id))
            else:
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
        """Handle '+ New' click on a card."""
        if card_name in ('sessions', 'jobs'):
            self.action_new_session()
        elif card_name == 'projects':
            self.action_new_project()

    def action_card_filter(self, card_name: str) -> None:
        """Toggle hide/show terminal states on a card."""
        self._hide_done[card_name] = not self._hide_done.get(card_name, False)
        # Update the toggle label
        card = self._find_card(card_name)
        if card:
            card.set_filter_active(self._hide_done[card_name])
        # Re-populate
        self._refresh_data()

    # ── Navigation ──

    def _navigate(self, ctx: NavigationContext) -> None:
        navigate_to(self.app, ctx)

    # ── Actions ──

    def action_go_back(self) -> None:
        if self._nav.level == DashboardLevel.MANAGEMENT:
            self.app.exit()
        else:
            # Navigate to parent level via breadcrumbs
            crumbs = breadcrumbs_for_level(self._nav)
            if len(crumbs) >= 2:
                # Second-to-last crumb is the parent
                parent_ctx = crumbs[-2].nav_context
                self._navigate(parent_ctx)
            else:
                self._navigate(NavigationContext(level=DashboardLevel.MANAGEMENT))

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
    """Navigate the app to the screen for the given NavigationContext.

    Pops all pushed screens, then pushes a fresh DashboardScreen.
    The base screen (Textual's _default) is never touched.
    """
    while len(app.screen_stack) > 2:
        app.pop_screen()
    # Pop the last pushed DashboardScreen if there is one
    if len(app.screen_stack) > 1:
        app.pop_screen()
    # Push the target level
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
