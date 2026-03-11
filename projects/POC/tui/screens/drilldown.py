"""Drilldown screen — single session activity stream + dispatches + input."""
from __future__ import annotations

import os
import subprocess

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Input, OptionList, RichLog, Static
from textual.widgets.option_list import Option

from projects.POC.tui.event_parser import EventParser
from projects.POC.tui.stream_watcher import StreamWatcher
from projects.POC.tui.todo_reader import format_todo_list, read_todos_from_streams


def _human_age(seconds: int) -> str:
    if seconds < 0:
        return '\u2014'
    if seconds < 60:
        return f'{seconds}s'
    if seconds < 3600:
        return f'{seconds // 60}m'
    return f'{seconds // 3600}h{seconds % 3600 // 60}m'


def _dispatch_icon(status: str) -> str:
    if status == 'active':
        return '\u25b6'
    if status == 'failed':
        return '\u2717'
    if status == 'complete':
        return '\u2713'
    return '\u2591'


class DrilldownScreen(Screen):
    """Deep view into a single session."""

    BINDINGS = [
        Binding('escape', 'go_back', 'Back', show=True),
        Binding('f1', 'open_finder', 'Finder', show=True, priority=True),
        Binding('f2', 'open_vscode', 'VSCode', show=True, priority=True),
        Binding('f3', 'open_intent', 'Intent', show=True, priority=True),
        Binding('f4', 'open_plan', 'Plan', show=True, priority=True),
        Binding('s', 'toggle_scroll', 'Scroll Lock', show=True),
    ]

    def __init__(self, session_id: str):
        super().__init__()
        self.session_id = session_id
        self.parser = EventParser(show_progress=True)
        self.watcher = StreamWatcher(callback=self._on_stream_event)
        self._scroll_locked = False
        self._session = None
        self._dispatch_map: dict[int, object] = {}  # option index -> DispatchState
        self._last_todos: list[dict] = []
        self._input_latched = False  # True while input area is shown
        self._input_cooldown = False  # True briefly after submit to suppress re-show

    def compose(self) -> ComposeResult:
        yield Static('', id='drilldown-header')
        yield Horizontal(
            RichLog(id='activity-log', highlight=True, markup=True),
            Vertical(
                Static('', id='session-meta'),
                Static('TASKS', classes='section-title'),
                Static('', id='tasks-panel'),
                Static('DISPATCHES', classes='section-title'),
                OptionList(id='dispatch-list'),
                id='right-pane',
            ),
        )
        yield Horizontal(
            Static('', id='input-prompt'),
            Input(placeholder='Type your response...', id='input-field'),
            id='input-area',
        )
        yield Footer()

    def on_mount(self) -> None:
        self._session = self.app.state_reader.find_session(self.session_id)
        self._update_header()
        self._update_meta()
        self._update_tasks()
        self._update_dispatches()
        self._update_input_area()

        # Start watching stream files
        self.watcher.start()
        stream_files = self.app.state_reader.active_stream_files(self.session_id)
        for f in stream_files:
            self.watcher.watch(f)

    def on_unmount(self) -> None:
        self.watcher.stop()

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Gray out bindings when their targets don't exist."""
        if action in ('open_finder', 'open_vscode'):
            if self._session_worktree() is None:
                return None
        if action == 'open_intent':
            if self._find_doc('INTENT.md') is None:
                return None
        if action == 'open_plan':
            if self._find_doc('plan.md') is None:
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
                        self._last_todos = todos
                        panel = self.query_one('#tasks-panel', Static)
                        panel.update(format_todo_list(todos))

    def _update_header(self) -> None:
        header = self.query_one('#drilldown-header', Static)
        if self._session:
            s = self._session
            phase_state = f'{s.cfa_phase} \u25b8 {s.cfa_state}' if s.cfa_state else s.status
            if s.is_orphaned:
                attention = '  \u26a0 ORPHANED'
            elif s.needs_input:
                attention = '  \u23f3 YOUR INPUT'
            else:
                attention = ''
            header.update(
                f'[bold]{s.project} \u25b8 Session {s.session_id}[/bold]  '
                f'{phase_state}{attention}\n'
                f'{s.task[:80]}'
            )
        else:
            header.update(f'Session {self.session_id} (not found)')

    def _update_meta(self) -> None:
        meta = self.query_one('#session-meta', Static)
        if not self._session:
            meta.update('')
            return

        s = self._session
        phase = s.cfa_phase or '\u2014'
        state = s.cfa_state or '\u2014'

        intent_exists = self._find_doc('INTENT.md') is not None
        plan_exists = self._find_doc('plan.md') is not None

        lines = [
            f'[bold]PHASE:[/bold]  {phase}',
            f'[bold]STATE:[/bold]  {state}',
            f'[bold]Intent:[/bold] {"INTENT.md" if intent_exists else "[dim](none)[/dim]"}',
            f'[bold]Plan:[/bold]   {"plan.md" if plan_exists else "[dim](none)[/dim]"}',
        ]
        meta.update('\n'.join(lines))

    def _update_tasks(self) -> None:
        """Load the latest task list from stream files."""
        panel = self.query_one('#tasks-panel', Static)
        stream_files = self.app.state_reader.active_stream_files(self.session_id)
        todos = read_todos_from_streams(stream_files)
        self._last_todos = todos
        panel.update(format_todo_list(todos))

    def _update_dispatches(self) -> None:
        ol = self.query_one('#dispatch-list', OptionList)

        if not self._session or not self._session.dispatches:
            self._dispatch_map = {}
            ol.clear_options()
            ol.add_option(Option('(no dispatches)', disabled=True))
            return

        # Build options grouped by team
        by_team: dict[str, list] = {}
        for d in self._session.dispatches:
            by_team.setdefault(d.team or '?', []).append(d)

        options = []
        new_map = {}
        idx = 0

        for team, dispatches in sorted(by_team.items()):
            options.append(Option(f'\u2500\u2500 {team} \u2500\u2500', disabled=True))
            idx += 1
            for d in dispatches:
                icon = _dispatch_icon(d.status)
                name = d.worktree_name
                if '--' in name:
                    name = name.split('--', 1)[1][:25]
                elif not name:
                    # Extract timestamp from infra_dir
                    name = os.path.basename(d.infra_dir) if d.infra_dir else '?'
                age = _human_age(d.stream_age_seconds)
                label = f'{icon} {name:<25} {age}'
                options.append(Option(label))
                new_map[idx] = d
                idx += 1

        self._dispatch_map = new_map
        ol.clear_options()
        for opt in options:
            ol.add_option(opt)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle Enter on a dispatch — drill down."""
        if event.option_list.id != 'dispatch-list':
            return
        dispatch = self._dispatch_map.get(event.option_index)
        if dispatch:
            from projects.POC.tui.screens.dispatch_drilldown import DispatchDrilldownScreen
            self.app.push_screen(DispatchDrilldownScreen(dispatch, self._session))

    def _update_input_area(self) -> None:
        """Show/hide the input area based on whether the session needs input.

        Latch: once shown, stays visible until user submits.
        Cooldown: after submit, skip ONE poll cycle so the shell has time
        to consume the FIFO.  If .input-request.json reappears (dialog
        loop), we re-show immediately regardless of CfA state.
        """
        input_area = self.query_one('#input-area')
        prompt_label = self.query_one('#input-prompt', Static)
        was_visible = input_area.has_class('visible')

        if self._input_latched:
            return

        # One-cycle cooldown after submit — but if a new request file
        # appeared the shell is asking again (dialog turn), so skip cooldown.
        if self._input_cooldown:
            has_request = False
            if self._session and self._session.infra_dir:
                has_request = os.path.exists(
                    os.path.join(self._session.infra_dir, '.input-request.json'))
            if not has_request:
                self._input_cooldown = False
                return
            # New request arrived — fall through to show input
            self._input_cooldown = False

        # Orphaned sessions always show the recovery input area
        if self._session and self._session.is_orphaned and self._session.cfa_state not in ('COMPLETED_WORK', 'WITHDRAWN', ''):
            if not self._input_latched:
                self._input_latched = True
                input_area.add_class('visible')
                state = self._session.cfa_state
                if state in ('WORK_ASSERT', 'PLAN_ASSERT', 'INTENT_ASSERT'):
                    prompt_label.update(f'[bold red]ORPHANED {state}[/bold red]  '
                                        f"type 'approve' or 'abandon'")
                else:
                    prompt_label.update(f'[bold red]ORPHANED {state}[/bold red]  '
                                        f"type 'abandon' to clean up")
                if not was_visible:
                    self.query_one('#input-field', Input).focus()
            return

        if self._session and self._session.needs_input:
            self._input_latched = True
            input_area.add_class('visible')
            state = self._session.cfa_state if self._session else ''
            prompt_label.update(f'[bold yellow]{state}[/bold yellow]')
            if not was_visible:
                self.query_one('#input-field', Input).focus()
        else:
            input_area.remove_class('visible')

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input submission."""
        event.stop()  # Prevent Enter from propagating to OptionList etc.
        response = event.value.strip()
        if not response:
            return

        # Write response via IPC (or handle orphan recovery)
        if self._session and self._session.infra_dir:
            if self._session.is_orphaned:
                from projects.POC.tui.orphan_recovery import handle_orphan_response
                msg = handle_orphan_response(self._session, response)
                log = self.query_one('#activity-log', RichLog)
                from rich.text import Text
                t = Text()
                t.append('[recovery] ', style='bold red')
                t.append(msg)
                log.write(t)
            else:
                from projects.POC.tui.ipc import send_response
                send_response(self._session.infra_dir, response)
                log = self.query_one('#activity-log', RichLog)
                from rich.text import Text
                text = Text()
                text.append('[you] ', style='bold green')
                text.append(response)
                log.write(text)

        # Release latch, enter cooldown (one poll cycle suppression)
        self._input_latched = False
        self._input_cooldown = True
        event.input.clear()
        self.query_one('#input-area').remove_class('visible')
        self.query_one('#activity-log', RichLog).focus()

    def periodic_refresh(self) -> None:
        """Called by the app's periodic refresh."""
        # Reload session state
        self.app.state_reader.reload()
        self._session = self.app.state_reader.find_session(self.session_id)
        self._update_header()
        self._update_meta()
        self._update_dispatches()
        self._update_input_area()
        self.refresh_bindings()

        # Watch any new stream files that appeared
        stream_files = self.app.state_reader.active_stream_files(self.session_id)
        for f in stream_files:
            self.watcher.watch(f)

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def _session_worktree(self) -> str | None:
        """Resolve the worktree directory for the current session."""
        if not self._session:
            return None
        # Explicit worktree path from manifest
        if self._session.worktree_path and os.path.isdir(self._session.worktree_path):
            return self._session.worktree_path
        # Conventional worktree path: {project}/.worktrees/session-{id}/
        proj = self.app.state_reader.find_project(self._session.project)
        if proj:
            wt = os.path.join(proj.path, '.worktrees', f'session-{self._session.session_id}')
            if os.path.isdir(wt):
                return wt
        return None

    def _find_doc(self, filename: str) -> str | None:
        """Find a document in infra dir or worktree. Infra dir takes priority."""
        if self._session and self._session.infra_dir:
            p = os.path.join(self._session.infra_dir, filename)
            if os.path.exists(p):
                return p
        wt = self._session_worktree()
        if wt:
            p = os.path.join(wt, filename)
            if os.path.exists(p):
                return p
        return None

    def action_open_finder(self) -> None:
        path = self._session_worktree()
        if path:
            subprocess.Popen(['open', path])

    def action_open_vscode(self) -> None:
        path = self._session_worktree()
        if path:
            subprocess.Popen(['code', path])

    def action_open_intent(self) -> None:
        path = self._find_doc('INTENT.md')
        if path:
            subprocess.Popen(['open', path])

    def action_open_plan(self) -> None:
        path = self._find_doc('plan.md')
        if path:
            subprocess.Popen(['open', path])

    def action_toggle_scroll(self) -> None:
        self._scroll_locked = not self._scroll_locked
