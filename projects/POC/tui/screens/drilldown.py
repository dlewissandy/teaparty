"""Drilldown screen — single session activity stream + dispatches + input."""
from __future__ import annotations

import json
import os
import subprocess
import traceback
from datetime import datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Footer, Input, OptionList, RichLog, Static, TextArea
from textual.widgets.option_list import Option

from projects.POC.tui.event_parser import EventParser
from projects.POC.tui.stream_watcher import StreamWatcher
from projects.POC.tui.todo_reader import format_todo_list, read_todos_from_streams
from projects.POC.tui.platform_utils import open_file


def _handle_session_crash(infra_dir: str) -> None:
    """Write crash diagnostics to infra_dir for post-mortem analysis.

    Called from except BaseException handlers in run_resumed() and similar
    wrappers.  Writes two artifacts:
      - .crash file with the full traceback
      - CRASH entry appended to session.log
    """
    tb = traceback.format_exc()
    try:
        crash_path = os.path.join(infra_dir, '.crash')
        with open(crash_path, 'w') as f:
            f.write(tb)
    except OSError:
        pass
    try:
        timestamp = datetime.now().strftime('%H:%M:%S')
        exc_line = tb.strip().rsplit('\n', 1)[-1] if tb.strip() else 'unknown'
        log_path = os.path.join(infra_dir, 'session.log')
        with open(log_path, 'a') as f:
            f.write(f'[{timestamp}] CRASH    | {exc_line}\n')
    except OSError:
        pass


_STATE_LABELS: dict[str, str] = {
    'INTENT_ESCALATE': 'Agent has questions about intent',
    'PLANNING_ESCALATE': 'Agent has questions about the plan',
    'TASK_REVIEW_ESCALATE': 'Agent has questions about the task',
    'TASK_ESCALATE': 'Agent has questions about the task',
    'INTENT_ASSERT': 'Review intent',
    'PLAN_ASSERT': 'Review plan',
    'WORK_ASSERT': 'Review completed work',
}


def _human_label(state: str) -> str:
    """Map CfA state to a human-readable prompt label."""
    return _STATE_LABELS.get(state, state)


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
        Binding('f6', 'withdraw', 'Withdraw', show=True, priority=True),
        Binding('f1', 'open_finder', 'Finder', show=True, priority=True),
        Binding('f2', 'open_vscode', 'VSCode', show=True, priority=True),
        Binding('f3', 'open_intent', 'Intent', show=True, priority=True),
        Binding('f4', 'open_plan', 'Plan', show=True, priority=True),
        Binding('f5', 'open_work_summary', 'Work', show=True, priority=True),
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
        self._last_dispatch_key: str = ''  # fingerprint to skip no-op rebuilds
        self._last_header: str = ''  # fingerprint to skip no-op header updates
        self._last_meta: str = ''  # fingerprint to skip no-op meta updates
        self._last_todos: list[dict] = []
        self._input_latched = False  # True while input area is shown
        self._input_cooldown = False  # True briefly after submit to suppress re-show
        self._shown_dialog_reply = ''  # Track last displayed dialog reply to avoid duplicates
        self._in_proc = None  # InProcessSession if running via Python orchestrator
        self._recovery_modal_shown = False  # True while recovery modal is visible

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
        yield Vertical(
            Static('', id='input-prompt'),
            TextArea(id='input-field'),
            id='input-area',
        )
        yield Footer()

    def on_mount(self) -> None:
        self._session = self.app.state_reader.find_session(self.session_id)
        self._in_proc = self.app.get_in_process(self.session_id)
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
        if action == 'withdraw':
            if not self._session or self._session.cfa_state in ('COMPLETED_WORK', 'WITHDRAWN', ''):
                return None
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
            content = (
                f'[bold]{s.project} \u25b8 Session {s.session_id}[/bold]  '
                f'{phase_state}{attention}\n'
                f'{s.task}'
            )
        else:
            content = f'Session {self.session_id} (not found)'
        if content != self._last_header:
            self._last_header = content
            header.update(content)

    def _update_meta(self) -> None:
        meta = self.query_one('#session-meta', Static)
        if not self._session:
            content = ''
        else:
            s = self._session
            phase = s.cfa_phase or '\u2014'
            state = s.cfa_state or '\u2014'

            intent_exists = self._find_doc('INTENT.md') is not None
            plan_exists = self._find_doc('plan.md') is not None

            content = '\n'.join([
                f'[bold]PHASE:[/bold]  {phase}',
                f'[bold]STATE:[/bold]  {state}',
                f'[bold]Intent:[/bold] {"INTENT.md" if intent_exists else "[dim](none)[/dim]"}',
                f'[bold]Plan:[/bold]   {"plan.md" if plan_exists else "[dim](none)[/dim]"}',
            ])
        if content != self._last_meta:
            self._last_meta = content
            meta.update(content)

    def _update_tasks(self) -> None:
        """Load the latest task list from stream files."""
        panel = self.query_one('#tasks-panel', Static)
        stream_files = self.app.state_reader.active_stream_files(self.session_id)
        todos = read_todos_from_streams(stream_files)
        self._last_todos = todos
        panel.update(format_todo_list(todos))

    def _update_dispatches(self) -> None:
        ol = self.query_one('#dispatch-list', OptionList)

        # Only show running dispatches — dead ones are noise after restart
        active = [d for d in (self._session.dispatches if self._session else [])
                  if d.status == 'active']

        if not active:
            if self._last_dispatch_key != '_empty_':
                self._last_dispatch_key = '_empty_'
                self._dispatch_map = {}
                ol.clear_options()
                ol.add_option(Option('(no dispatches)', disabled=True))
            return

        # Build options grouped by team
        by_team: dict[str, list] = {}
        for d in active:
            by_team.setdefault(d.team or '?', []).append(d)

        options = []
        new_map = {}
        key_parts = []
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
                key_parts.append(f'{team}:{name}:{d.status}')
                idx += 1

        # Skip full rebuild if structure unchanged — avoids layout reflow
        # that causes scrollbar jitter in the activity log.
        # But still update age labels in-place every cycle.  Issue #158.
        new_key = '|'.join(key_parts)
        if new_key == self._last_dispatch_key:
            # Structure unchanged — update age labels in-place
            for opt_idx, d in new_map.items():
                icon = _dispatch_icon(d.status)
                name = d.worktree_name
                if '--' in name:
                    name = name.split('--', 1)[1][:25]
                elif not name:
                    name = os.path.basename(d.infra_dir) if d.infra_dir else '?'
                age = _human_age(d.stream_age_seconds)
                label = f'{icon} {name:<25} {age}'
                try:
                    ol.replace_option_prompt_at_index(opt_idx, label)
                except Exception:
                    pass  # Index mismatch — next full rebuild will fix it
            return
        self._last_dispatch_key = new_key

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
        Cooldown: after submit, stay suppressed until needs_input clears
        (i.e., CfA state has advanced past the gate).  A new
        .input-request.json overrides cooldown immediately so multi-turn
        dialog loops re-show without waiting.
        """
        input_area = self.query_one('#input-area')
        prompt_label = self.query_one('#input-prompt', Static)
        was_visible = input_area.has_class('visible')

        # ── In-process path: TUIInputProvider (Python orchestrator) ──
        if self._in_proc and self._in_proc.input_provider.is_waiting:
            req = self._in_proc.input_provider.current_request
            self._input_cooldown = False
            if not self._input_latched:
                self._input_latched = True
                input_area.add_class('visible')
                state = self._session.cfa_state if self._session else ''
                # Use bridge_text as the prompt when available (issue #137)
                if req and req.bridge_text:
                    label = req.bridge_text
                else:
                    label = _human_label(state)
                prompt_label.update(f'[bold yellow]{label}[/bold yellow]')
                # Display bridge_text (dialog reply / review summary) in activity log
                if req and req.bridge_text and req.bridge_text != self._shown_dialog_reply:
                    self._shown_dialog_reply = req.bridge_text
                    log = self.query_one('#activity-log', RichLog)
                    from rich.text import Text
                    t = Text()
                    t.append('[agent] ', style='bold cyan')
                    t.append(req.bridge_text)
                    log.write(t)
                    if not self._scroll_locked:
                        log.scroll_end(animate=False)
                if not was_visible:
                    self.query_one('#input-field', TextArea).focus()
            return

        if self._input_latched:
            return

        # Cooldown after submit — persist until CfA state advances past
        # needs_input, OR a new .input-request.json arrives (dialog loop).
        if self._input_cooldown:
            has_request = False
            request_data = None
            if self._session and self._session.infra_dir:
                req_path = os.path.join(self._session.infra_dir, '.input-request.json')
                if os.path.exists(req_path):
                    has_request = True
                    try:
                        with open(req_path) as _f:
                            request_data = json.load(_f)
                    except (OSError, ValueError):
                        pass
            if has_request:
                # New request arrived (dialog loop) — show dialog reply if present
                if request_data and request_data.get('dialog_reply'):
                    reply = request_data['dialog_reply']
                    if reply != self._shown_dialog_reply:
                        self._shown_dialog_reply = reply
                        log = self.query_one('#activity-log', RichLog)
                        from rich.text import Text
                        t = Text()
                        t.append('[agent] ', style='bold cyan')
                        t.append(reply)
                        log.write(t)
                        if not self._scroll_locked:
                            log.scroll_end(animate=False)
                # Fall through to show input immediately
                self._input_cooldown = False
            else:
                # No new request. Stay suppressed while needs_input is still True
                # (orchestrator hasn't advanced CfA state yet). Also break out if
                # the session became orphaned so the recovery UI is not delayed.
                if self._session and self._session.needs_input and not self._session.is_orphaned:
                    return   # suppress: waiting for orchestrator to advance state
                self._input_cooldown = False
                return

        # Orphaned sessions show a recovery modal (not a text-based prompt)
        if self._session and self._session.is_orphaned and self._session.cfa_state not in ('COMPLETED_WORK', 'WITHDRAWN', ''):
            if not self._recovery_modal_shown:
                self._recovery_modal_shown = True
                from projects.POC.tui.screens.recovery_modal import RecoveryModal
                self.app.push_screen(
                    RecoveryModal(self._session.cfa_state),
                    callback=self._on_recovery_modal_dismiss,
                )
            return

        if self._session and self._session.needs_input:
            self._input_latched = True
            if not input_area.has_class('visible'):
                input_area.add_class('visible')
            state = self._session.cfa_state if self._session else ''
            label = _human_label(state)
            prompt_label.update(f'[bold yellow]{label}[/bold yellow]')
            if not was_visible:
                self.query_one('#input-field', TextArea).focus()
        else:
            if input_area.has_class('visible'):
                input_area.remove_class('visible')

    def _submit_input(self) -> None:
        """Handle user input submission."""
        field = self.query_one('#input-field', TextArea)
        response = field.text.strip()
        if not response:
            return

        # ── In-process path: resolve TUIInputProvider's Future directly ──
        if self._in_proc and self._in_proc.input_provider.is_waiting:
            self._in_proc.input_provider.provide_response(response)
            log = self.query_one('#activity-log', RichLog)
            from rich.text import Text
            text = Text()
            text.append('[you] ', style='bold green')
            text.append(response)
            log.write(text)
            if not self._scroll_locked:
                log.scroll_end(animate=False)
            self._input_latched = False
            self._input_cooldown = True
            field.clear()
            self.query_one('#input-area').remove_class('visible')
            self.query_one('#activity-log', RichLog).focus()
            return

        # ── FIFO IPC path (shell-launched sessions) ──
        # Orphan recovery is handled by the recovery modal, not text input.
        if self._session and self._session.infra_dir and not self._session.is_orphaned:
            from projects.POC.tui.ipc import send_response
            send_response(self._session.infra_dir, response)
            log = self.query_one('#activity-log', RichLog)
            from rich.text import Text
            text = Text()
            text.append('[you] ', style='bold green')
            text.append(response)
            log.write(text)

        # Release latch, enter cooldown (persistent until CfA state advances)
        self._input_latched = False
        self._input_cooldown = True
        field.clear()
        self.query_one('#input-area').remove_class('visible')
        self.query_one('#activity-log', RichLog).focus()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        """Submit when the user presses Enter (newline appears in text)."""
        if event.text_area.id != 'input-field':
            return
        if '\n' in event.text_area.text:
            # Strip the newline the TextArea inserted, then submit
            event.text_area.text = event.text_area.text.replace('\n', '')
            self._submit_input()

    def periodic_refresh(self) -> None:
        """Called by the app's periodic refresh."""
        # Reload session state
        self.app.state_reader.reload()
        self._session = self.app.state_reader.find_session(self.session_id)
        self._in_proc = self.app.get_in_process(self.session_id)
        self._update_header()
        self._update_meta()
        self._update_dispatches()
        self._update_input_area()
        self.refresh_bindings()

        # Watch any new stream files that appeared
        stream_files = self.app.state_reader.active_stream_files(self.session_id)
        for f in stream_files:
            self.watcher.watch(f)

    def _on_recovery_modal_dismiss(self, result: str) -> None:
        """Handle the recovery modal's result: 'resume' or 'cancel'."""
        if result == 'resume' and self._session and self._session.infra_dir:
            self._launch_resume(self._session.infra_dir)
            log = self.query_one('#activity-log', RichLog)
            from rich.text import Text
            t = Text()
            t.append('[recovery] ', style='bold green')
            t.append('Resuming session...')
            log.write(t)
            if not self._scroll_locked:
                log.scroll_end(animate=False)
        else:
            # Cancel — stay on drilldown, suppress modal for this visit
            pass
        # Don't reset _recovery_modal_shown — prevents re-triggering during
        # this drilldown visit. Modal will reappear on next drilldown entry.

    def _launch_resume(self, infra_dir: str) -> None:
        """Resume an orphaned session in-process, mirroring launch.py's pattern."""
        import asyncio
        import logging
        from projects.POC.orchestrator.events import EventBus, Event, EventType
        from projects.POC.orchestrator.tui_bridge import TUIInputProvider, InProcessSession
        from projects.POC.orchestrator.session import Session

        _rlog = logging.getLogger('orchestrator.resume')

        # Dedup: don't start a second resume if one is already running
        if self._in_proc and self._in_proc.run_task and not self._in_proc.run_task.done():
            log = self.query_one('#activity-log', RichLog)
            from rich.text import Text
            t = Text()
            t.append('[recovery] ', style='bold yellow')
            t.append('Session is already running. Wait for it to finish.')
            log.write(t)
            return

        bus = EventBus()
        provider = TUIInputProvider()

        in_proc = InProcessSession(
            session_id=self.session_id,
            project=self._session.project if self._session else '',
            task=self._session.task if self._session else '',
            event_bus=bus,
            input_provider=provider,
        )

        # Register immediately since we already know the session_id
        self.app.register_in_process(self.session_id, in_proc)
        self._in_proc = in_proc

        async def run_resumed() -> None:
            try:
                await Session.resume_from_disk(
                    infra_dir,
                    poc_root=self.app.poc_root,
                    projects_dir=self.app.projects_dir,
                    event_bus=bus,
                    input_provider=provider,
                )
            except BaseException as exc:
                _rlog.exception('Resume failed for %s', infra_dir)
                # Write crash diagnostics so the failure is never silent.
                # Don't remove .running — leave it for orphan detection so the
                # user gets the recovery UI.  The PID in .running is ours (the
                # TUI), and has_in_process() will return False since this task
                # is done, correctly flagging it as orphaned.
                _handle_session_crash(infra_dir)
                try:
                    log = self.query_one('#activity-log', RichLog)
                    from rich.text import Text
                    t = Text()
                    t.append('[recovery] ', style='bold red')
                    t.append(f'Resume failed: {type(exc).__name__}: {exc}')
                    log.write(t)
                except Exception:
                    pass  # Screen may have been unmounted
                raise

        in_proc.run_task = asyncio.create_task(run_resumed())

    def action_withdraw(self) -> None:
        if not self._session:
            self.notify('No session', severity='warning')
            return
        if self._session.cfa_state in ('COMPLETED_WORK', 'WITHDRAWN'):
            self.notify('Session is already terminal', severity='warning')
            return

        self._do_withdraw()

    def _do_withdraw(self) -> None:
        import asyncio
        from projects.POC.tui.withdraw import withdraw_session

        session = self._session
        if not session:
            return

        in_proc = self._in_proc
        in_task = in_proc.run_task if in_proc else None
        bus = in_proc.event_bus if in_proc else None

        async def _withdraw():
            await withdraw_session(
                session,
                event_bus=bus,
                in_process_task=in_task,
            )

        asyncio.create_task(_withdraw())

        log = self.query_one('#activity-log', RichLog)
        from rich.text import Text
        t = Text()
        t.append('[withdraw] ', style='bold red')
        t.append(f'Session {self.session_id} withdrawn')
        log.write(t)
        if not self._scroll_locked:
            log.scroll_end(animate=False)

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def _session_worktree(self) -> str | None:
        """Resolve the worktree directory for the current session."""
        if not self._session:
            return None
        # Explicit worktree path from manifest
        if self._session.worktree_path and os.path.isdir(self._session.worktree_path):
            return self._session.worktree_path
        # Fallback: glob for session-{short_id}--* in .worktrees/
        # (worktrees use session_id[-6:], not the full session_id)
        proj = self.app.state_reader.find_project(self._session.project)
        if proj:
            import glob as _glob
            short_id = self._session.session_id[-6:]
            pattern = os.path.join(proj.path, '.worktrees', f'session-{short_id}--*')
            matches = _glob.glob(pattern)
            if matches and os.path.isdir(matches[0]):
                return matches[0]
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
            open_file(path)
        else:
            self.notify('Worktree not found', severity='warning')

    def action_open_vscode(self) -> None:
        path = self._session_worktree()
        if path:
            subprocess.Popen(['code', path])
        else:
            self.notify('Worktree not found', severity='warning')

    def action_open_intent(self) -> None:
        path = self._find_doc('INTENT.md')
        if path:
            open_file(path)

    def action_open_plan(self) -> None:
        path = self._find_doc('plan.md')
        if path:
            open_file(path)

    def action_open_work_summary(self) -> None:
        path = self._find_doc('.work-summary.md')
        if path:
            open_file(path)

    def action_toggle_scroll(self) -> None:
        self._scroll_locked = not self._scroll_locked
