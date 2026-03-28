"""Task Dashboard — single task (dispatch) view with activity, todos, and files.

Refactored from DispatchDrilldownScreen (issue #253). Adds breadcrumbs.
"""
from __future__ import annotations

import os
import subprocess

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, RichLog, Static

from projects.POC.tui.event_parser import EventParser
from projects.POC.tui.navigation import NavigationContext
from projects.POC.tui.platform_utils import open_file
from projects.POC.tui.stream_watcher import StreamWatcher
from projects.POC.tui.todo_reader import format_todo_list, read_todos_from_streams
from projects.POC.tui.widgets.breadcrumb_bar import BreadcrumbBar


def _human_age(seconds: int) -> str:
    if seconds < 0:
        return '\u2014'
    if seconds < 60:
        return f'{seconds}s'
    if seconds < 3600:
        return f'{seconds // 60}m'
    return f'{seconds // 3600}h{seconds % 3600 // 60}m'


class TaskDashboard(Screen):
    """Deep view into a single task (dispatch). Breadcrumbs + full dispatch functionality."""

    BINDINGS = [
        Binding('escape', 'go_back', 'Back', show=True),
        Binding('f1', 'open_finder', 'Finder', show=True),
        Binding('f2', 'open_vscode', 'VSCode', show=True),
        Binding('f4', 'open_plan', 'Plan', show=True),
        Binding('s', 'toggle_scroll', 'Scroll Lock', show=True),
    ]

    def __init__(self, nav_context: NavigationContext, dispatch=None, parent_session=None):
        super().__init__()
        self._nav_context = nav_context
        self._dispatch = dispatch
        self._parent_session = parent_session
        self.parser = EventParser()
        self.watcher = StreamWatcher(callback=self._on_stream_event)
        self._scroll_locked = False

    def compose(self) -> ComposeResult:
        yield BreadcrumbBar(self._nav_context, id='breadcrumb-bar')
        yield Static('', id='drilldown-header')
        yield Horizontal(
            RichLog(id='activity-log', highlight=True, markup=True),
            Vertical(
                Static('', id='dispatch-meta'),
                Static('TASKS', classes='section-title'),
                Static('', id='tasks-panel'),
                Static('FILES CHANGED', classes='section-title'),
                Static('', id='files-panel'),
                id='right-pane',
            ),
        )
        yield Footer()

    def on_mount(self) -> None:
        self._update_header()
        self._update_meta()
        self._update_tasks()
        self._update_files()

        self.watcher.start()
        for f in self._dispatch_stream_files():
            self.watcher.watch(f)

    def on_unmount(self) -> None:
        self.watcher.stop()

    def on_breadcrumb_bar_navigate(self, event: BreadcrumbBar.Navigate) -> None:
        from projects.POC.tui.screens.management_dashboard import _navigate_to_context
        _navigate_to_context(self.app, event.nav_context)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in ('open_finder', 'open_vscode'):
            if self._dispatch_worktree() is None:
                return None
        if action == 'open_plan':
            if self._find_dispatch_plan() is None:
                return None
        return True

    def _on_stream_event(self, file_path: str, event: dict) -> None:
        text = self.parser.format_event(event)
        if text is not None:
            log = self.query_one('#activity-log', RichLog)
            log.write(text)
            if not self._scroll_locked:
                log.scroll_end(animate=False)

        if event.get('type') == 'assistant':
            for block in event.get('message', {}).get('content', []):
                if isinstance(block, dict) and block.get('type') == 'tool_use' and block.get('name') == 'TodoWrite':
                    todos = block.get('input', {}).get('todos', [])
                    if todos:
                        panel = self.query_one('#tasks-panel', Static)
                        panel.update(format_todo_list(todos))

    def _update_header(self) -> None:
        header = self.query_one('#drilldown-header', Static)
        d = self._dispatch
        if not d:
            header.update('Task (no data)')
            return
        team = d.team or '?'
        dispatch_ts = os.path.basename(d.infra_dir) if d.infra_dir else d.worktree_name
        phase_state = f'{d.cfa_phase} \u25b8 {d.cfa_state}' if d.cfa_state else d.status
        header.update(
            f'[bold]{team} dispatch {dispatch_ts}[/bold]  {phase_state}\n'
            f'{d.task if d.task else "(no task)"}'
        )

    def _update_meta(self) -> None:
        meta = self.query_one('#dispatch-meta', Static)
        d = self._dispatch
        if not d:
            meta.update('')
            return
        phase = d.cfa_phase or '\u2014'
        state = d.cfa_state or '\u2014'
        status = d.status or '\u2014'
        plan_exists = d.infra_dir and os.path.exists(os.path.join(d.infra_dir, 'plan.md'))
        age = _human_age(d.stream_age_seconds)
        lines = [
            f'[bold]PHASE:[/bold]   {phase}',
            f'[bold]STATE:[/bold]   {state}',
            f'[bold]STATUS:[/bold]  {status}',
            f'[bold]AGE:[/bold]     {age}',
            f'[bold]Plan:[/bold]    {"plan.md" if plan_exists else "[dim](none)[/dim]"}',
        ]
        meta.update('\n'.join(lines))

    def _update_tasks(self) -> None:
        panel = self.query_one('#tasks-panel', Static)
        todos = read_todos_from_streams(self._dispatch_stream_files())
        panel.update(format_todo_list(todos))

    def _update_files(self) -> None:
        panel = self.query_one('#files-panel', Static)
        wt = self._dispatch_worktree()
        if not wt:
            panel.update('  [dim](no worktree)[/dim]')
            return
        try:
            result = subprocess.run(
                ['git', 'diff', '--name-only', 'HEAD'],
                cwd=wt,
                capture_output=True, text=True, timeout=5,
            )
            files = [f for f in result.stdout.strip().split('\n') if f]
            if files:
                panel.update('\n'.join(f'  {f}' for f in files[:20]))
            else:
                panel.update('  [dim](no changes)[/dim]')
        except (subprocess.TimeoutExpired, OSError):
            panel.update('  [dim](error reading files)[/dim]')

    def _dispatch_stream_files(self) -> list[str]:
        if not self._dispatch or not self._dispatch.infra_dir or not os.path.isdir(self._dispatch.infra_dir):
            return []
        files = []
        try:
            for name in os.listdir(self._dispatch.infra_dir):
                if name.endswith('.jsonl'):
                    files.append(os.path.join(self._dispatch.infra_dir, name))
        except OSError:
            pass
        return files

    def _find_dispatch_plan(self) -> str | None:
        if self._dispatch and self._dispatch.infra_dir:
            p = os.path.join(self._dispatch.infra_dir, 'plan.md')
            if os.path.exists(p):
                return p
        wt = self._dispatch_worktree()
        if wt:
            p = os.path.join(wt, 'plan.md')
            if os.path.exists(p):
                return p
        return None

    def _dispatch_worktree(self) -> str | None:
        if not self._dispatch:
            return None
        d = self._dispatch
        if d.worktree_path and os.path.isdir(d.worktree_path):
            return d.worktree_path
        if d.worktree_name and self._parent_session:
            proj = self.app.state_reader.find_project(self._parent_session.project)
            if proj:
                wt = os.path.join(proj.path, '.worktrees', d.worktree_name)
                if os.path.isdir(wt):
                    return wt
        return None

    def periodic_refresh(self) -> None:
        self.app.state_reader.reload()
        if self._parent_session:
            parent = self.app.state_reader.find_session(self._parent_session.session_id)
            if parent:
                self._parent_session = parent
                for d in parent.dispatches:
                    if d.infra_dir == self._dispatch.infra_dir:
                        self._dispatch = d
                        break
        self._update_header()
        self._update_meta()
        self._update_files()
        self.refresh_bindings()

        for f in self._dispatch_stream_files():
            self.watcher.watch(f)

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_open_finder(self) -> None:
        path = self._dispatch_worktree()
        if path:
            open_file(path)
        else:
            self.notify('Worktree not found', severity='warning')

    def action_open_vscode(self) -> None:
        path = self._dispatch_worktree()
        if path:
            subprocess.Popen(['code', path])
        else:
            self.notify('Worktree not found', severity='warning')

    def action_open_plan(self) -> None:
        path = self._find_dispatch_plan()
        if path:
            open_file(path)

    def action_toggle_scroll(self) -> None:
        self._scroll_locked = not self._scroll_locked
