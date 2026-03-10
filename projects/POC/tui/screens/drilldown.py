"""Drilldown screen — single session activity stream + dispatches + input."""
from __future__ import annotations

import subprocess

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Input, RichLog, Static

from projects.POC.tui.event_parser import EventParser
from projects.POC.tui.stream_watcher import StreamWatcher


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
        Binding('f', 'open_finder', 'Finder', show=True),
        Binding('v', 'open_vscode', 'VSCode', show=True),
        Binding('s', 'toggle_scroll', 'Scroll Lock', show=True),
    ]

    def __init__(self, session_id: str):
        super().__init__()
        self.session_id = session_id
        self.parser = EventParser(show_progress=True)
        self.watcher = StreamWatcher(callback=self._on_stream_event)
        self._scroll_locked = False
        self._session = None

    def compose(self) -> ComposeResult:
        yield Static('', id='drilldown-header')
        yield Horizontal(
            RichLog(id='activity-log', highlight=True, markup=True),
            Vertical(
                Static('DISPATCHES', classes='section-title'),
                Static('', id='dispatch-panel'),
                Static('FILES CHANGED', classes='section-title'),
                Static('', id='files-panel'),
                id='right-pane',
            ),
        )
        yield Vertical(
            Static('', id='input-prompt'),
            Input(placeholder='Type your response...', id='input-field'),
            id='input-area',
        )
        yield Footer()

    def on_mount(self) -> None:
        self._session = self.app.state_reader.find_session(self.session_id)
        self._update_header()
        self._update_dispatches()
        self._update_input_area()

        # Start watching stream files
        self.watcher.start()
        stream_files = self.app.state_reader.active_stream_files(self.session_id)
        for f in stream_files:
            self.watcher.watch(f)

    def on_unmount(self) -> None:
        self.watcher.stop()

    def _on_stream_event(self, file_path: str, event: dict) -> None:
        """Callback from StreamWatcher when a new JSONL event arrives."""
        text = self.parser.format_event(event)
        if text is not None:
            log = self.query_one('#activity-log', RichLog)
            log.write(text)
            if not self._scroll_locked:
                log.scroll_end(animate=False)

    def _update_header(self) -> None:
        header = self.query_one('#drilldown-header', Static)
        if self._session:
            s = self._session
            phase_state = f'{s.cfa_phase} \u25b8 {s.cfa_state}' if s.cfa_state else s.status
            attention = '  \u23f3 YOUR INPUT' if s.needs_input else ''
            header.update(
                f'[bold]{s.project} \u25b8 Session {s.session_id}[/bold]  '
                f'{phase_state}{attention}\n'
                f'{s.task[:80]}'
            )
        else:
            header.update(f'Session {self.session_id} (not found)')

    def _update_dispatches(self) -> None:
        panel = self.query_one('#dispatch-panel', Static)
        if not self._session or not self._session.dispatches:
            panel.update('  (no dispatches)')
            return

        by_team: dict[str, list] = {}
        for d in self._session.dispatches:
            by_team.setdefault(d.team or '?', []).append(d)

        lines = []
        for team, dispatches in sorted(by_team.items()):
            lines.append(f'[bold]{team}[/bold]')
            for d in dispatches:
                icon = _dispatch_icon(d.status)
                name = d.worktree_name
                if '--' in name:
                    name = name.split('--', 1)[1][:25]
                age = _human_age(d.stream_age_seconds)
                status_style = {
                    'active': '',
                    'failed': '[red]',
                    'complete': '[dim]',
                }.get(d.status, '')
                end_style = '[/]' if status_style else ''
                lines.append(f'  {status_style}{icon} {name:<27} {age}{end_style}')

        panel.update('\n'.join(lines))

    def _update_input_area(self) -> None:
        """Show/hide the input area based on whether the session needs input."""
        input_area = self.query_one('#input-area')
        prompt_label = self.query_one('#input-prompt', Static)

        if self._session and self._session.needs_input:
            input_area.add_class('visible')
            state = self._session.cfa_state
            prompt_label.update(
                f'[bold yellow]Review requested ({state})[/bold yellow]\n'
                f'[yellow](y)[/yellow] approve  '
                f'[yellow](n)[/yellow] reject  '
                f'[yellow](e)[/yellow] edit  '
                f'[yellow](w)[/yellow] withdraw'
            )
        else:
            input_area.remove_class('visible')

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle user input submission."""
        response = event.value.strip()
        if not response:
            return

        # Write response via IPC
        if self._session and self._session.infra_dir:
            from projects.POC.tui.ipc import send_response
            send_response(self._session.infra_dir, response)

            # Log the response in the activity stream
            log = self.query_one('#activity-log', RichLog)
            from rich.text import Text
            text = Text()
            text.append('[you] ', style='bold green')
            text.append(response)
            log.write(text)

        # Clear the input
        event.input.clear()

    def on_timer(self) -> None:
        """Called by the app's periodic refresh."""
        # Reload session state
        self.app.state_reader.reload()
        self._session = self.app.state_reader.find_session(self.session_id)
        self._update_header()
        self._update_dispatches()
        self._update_input_area()

        # Watch any new stream files that appeared
        stream_files = self.app.state_reader.active_stream_files(self.session_id)
        for f in stream_files:
            self.watcher.watch(f)

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def action_open_finder(self) -> None:
        if self._session and self._session.worktree_path:
            subprocess.Popen(['open', self._session.worktree_path])

    def action_open_vscode(self) -> None:
        if self._session and self._session.worktree_path:
            subprocess.Popen(['code', self._session.worktree_path])

    def action_toggle_scroll(self) -> None:
        self._scroll_locked = not self._scroll_locked
