"""Dispatch drilldown screen — activity stream, state, and files for a single dispatch."""
from __future__ import annotations

import os
import subprocess

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, RichLog, Static

from projects.POC.tui.event_parser import EventParser
from projects.POC.tui.stream_watcher import StreamWatcher
from projects.POC.tui.todo_reader import format_todo_list, read_todos_from_streams
from projects.POC.tui.platform_utils import open_file


def _human_age(seconds: int) -> str:
    if seconds < 0:
        return '\u2014'
    if seconds < 60:
        return f'{seconds}s'
    if seconds < 3600:
        return f'{seconds // 60}m'
    return f'{seconds // 3600}h{seconds % 3600 // 60}m'


class DispatchDrilldownScreen(Screen):
    """Deep view into a single dispatch."""

    BINDINGS = [
        Binding('escape', 'go_back', 'Back', show=True),
        Binding('f1', 'open_finder', 'Finder', show=True),
        Binding('f2', 'open_vscode', 'VSCode', show=True),
        Binding('f4', 'open_plan', 'Plan', show=True),
        Binding('s', 'toggle_scroll', 'Scroll Lock', show=True),
    ]

    def __init__(self, dispatch, parent_session):
        super().__init__()
        self._dispatch = dispatch
        self._parent_session = parent_session
        self.parser = EventParser()
        self.watcher = StreamWatcher(callback=self._on_stream_event)
        self._scroll_locked = False

    def compose(self) -> ComposeResult:
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

        # Start watching dispatch stream files
        self.watcher.start()
        for f in self._dispatch_stream_files():
            self.watcher.watch(f)

    def on_unmount(self) -> None:
        self.watcher.stop()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Gray out bindings when their targets don't exist."""
        if action in ('open_finder', 'open_vscode'):
            if self._dispatch_worktree() is None:
                return None
        if action == 'open_plan':
            if self._find_dispatch_plan() is None:
                return None
        return True

    def _on_stream_event(self, file_path: str, event: dict) -> None:
        """Callback from StreamWatcher when a new JSONL event arrives."""
        text = self.parser.format_event(event)
        if text is not None:
            log = self.query_one('#activity-log', RichLog)
            log.write(text)
            if not self._scroll_locked:
                log.scroll_end(animate=False)

        # Live-update tasks panel on TodoWrite events
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
        team = d.team or '?'
        # Extract dispatch timestamp from infra_dir basename
        dispatch_ts = os.path.basename(d.infra_dir) if d.infra_dir else d.worktree_name
        phase_state = f'{d.cfa_phase} \u25b8 {d.cfa_state}' if d.cfa_state else d.status
        header.update(
            f'[bold]{team} dispatch {dispatch_ts}[/bold]  {phase_state}\n'
            f'{d.task if d.task else "(no task)"}'
        )

    def _update_meta(self) -> None:
        meta = self.query_one('#dispatch-meta', Static)
        d = self._dispatch
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
        """Load the latest task list from dispatch stream files."""
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
        """Return all JSONL stream files in the dispatch infra dir."""
        infra = self._dispatch.infra_dir
        if not infra or not os.path.isdir(infra):
            return []
        files = []
        try:
            for name in os.listdir(infra):
                if name.endswith('.jsonl'):
                    files.append(os.path.join(infra, name))
        except OSError:
            pass
        return files

    def _find_dispatch_plan(self) -> str | None:
        """Find plan.md in infra dir or dispatch worktree."""
        if self._dispatch.infra_dir:
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
        """Resolve the worktree directory for the dispatch."""
        d = self._dispatch
        if d.worktree_path and os.path.isdir(d.worktree_path):
            return d.worktree_path
        # Try conventional path: {project}/.worktrees/{worktree_name}/
        if d.worktree_name:
            proj = self.app.state_reader.find_project(self._parent_session.project)
            if proj:
                wt = os.path.join(proj.path, '.worktrees', d.worktree_name)
                if os.path.isdir(wt):
                    return wt
        return None

    def periodic_refresh(self) -> None:
        """Called by the app's periodic refresh."""
        self.app.state_reader.reload()
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
