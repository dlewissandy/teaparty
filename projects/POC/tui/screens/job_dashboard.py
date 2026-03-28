"""Job Dashboard — single CfA job view with workflow progress, tasks, chat, and input.

Refactored from DrilldownScreen (issue #253). Preserves all existing functionality:
stream watching, input handling, recovery modal, chat panel, withdraw.
"""
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
from textual.widgets import Footer, RichLog, Static, TextArea

from projects.POC.tui.event_parser import EventParser
from projects.POC.tui.navigation import DashboardLevel, NavigationContext
from projects.POC.tui.platform_utils import open_file
from projects.POC.tui.stream_watcher import StreamWatcher
from projects.POC.tui.todo_reader import format_todo_list, read_todos_from_streams
from projects.POC.tui.widgets.breadcrumb_bar import BreadcrumbBar
from projects.POC.tui.widgets.content_card import CardItem, ContentCard
from projects.POC.tui.widgets.stats_bar import StatsBar
from projects.POC.tui.widgets.workflow_progress import WorkflowProgress


def _handle_session_crash(infra_dir: str) -> None:
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
    'TASK_ESCALATE': 'Agent has questions about the task',
    'INTENT_ASSERT': 'Review intent',
    'PLAN_ASSERT': 'Review plan',
    'WORK_ASSERT': 'Review completed work',
}


def _human_label(state: str) -> str:
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


class JobDashboard(Screen):
    """Deep view into a single job (session). Breadcrumbs + full drilldown functionality."""

    BINDINGS = [
        Binding('escape', 'go_back', 'Back', show=True),
        Binding('f6', 'withdraw', 'Withdraw', show=True, priority=True),
        Binding('f1', 'open_finder', 'Finder', show=True, priority=True),
        Binding('f2', 'open_vscode', 'VSCode', show=True, priority=True),
        Binding('f3', 'open_intent', 'Intent', show=True, priority=True),
        Binding('f4', 'open_plan', 'Plan', show=True, priority=True),
        Binding('f5', 'open_work_summary', 'Work', show=True, priority=True),
        Binding('s', 'toggle_scroll', 'Scroll Lock', show=True),
        Binding('c', 'open_chat', 'Chat', show=True),
    ]

    def __init__(self, nav_context: NavigationContext):
        super().__init__()
        self._nav_context = nav_context
        self.session_id = nav_context.job_id
        self.parser = EventParser()
        self.watcher = StreamWatcher(callback=self._on_stream_event)
        self._scroll_locked = False
        self._session = None
        self._dispatch_map: dict[int, object] = {}
        self._last_dispatch_key: str = ''
        self._last_header: str = ''
        self._last_meta: str = ''
        self._last_todos: list[dict] = []
        self._input_latched = False
        self._input_cooldown = False
        self._shown_dialog_reply = ''
        self._in_proc = None
        self._recovery_modal_shown = False

    def compose(self) -> ComposeResult:
        yield BreadcrumbBar(self._nav_context, id='breadcrumb-bar')
        yield Static('', id='drilldown-header')
        yield WorkflowProgress(id='workflow-progress')
        yield StatsBar(id='job-stats')
        yield Horizontal(
            RichLog(id='activity-log', highlight=True, markup=True),
            Vertical(
                Static('', id='session-meta'),
                ContentCard('ESCALATIONS', 'escalations'),
                ContentCard('ARTIFACTS', 'artifacts'),
                ContentCard('TASKS', 'job_tasks'),
                id='right-pane',
            ),
        )
        yield Vertical(
            Static('CONVERSATION', classes='section-title'),
            RichLog(id='chat-panel', highlight=True, markup=True),
            id='chat-area',
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
        self._chat_msg_count = 0
        self._update_header()
        self._update_meta()
        self._update_workflow_progress()
        self._update_stats()
        self._update_escalation_card()
        self._update_artifacts_card()
        self._update_tasks_card()
        self._update_todos()
        self._update_input_area()
        self._update_chat_panel()

        self.watcher.start()
        stream_files = self.app.state_reader.active_stream_files(self.session_id)
        for f in stream_files:
            self.watcher.watch(f)

    def on_unmount(self) -> None:
        self.watcher.stop()

    def on_breadcrumb_bar_navigate(self, event: BreadcrumbBar.Navigate) -> None:
        from projects.POC.tui.screens.management_dashboard import _navigate_to_context
        _navigate_to_context(self.app, event.nav_context)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
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
                        self._last_todos = todos

    def _update_header(self) -> None:
        header = self.query_one('#drilldown-header', Static)
        if self._session:
            s = self._session
            phase_state = f'{s.cfa_phase} \u25b8 {s.cfa_state}' if s.cfa_state else s.status
            if s.is_orphaned:
                attention = '  \u26a0 ORPHANED'
            elif s.needs_input:
                attention = '  \u23f3 YOUR INPUT'
            elif self._check_overloaded(s):
                attention = '  \u23f1 API OVERLOADED \u2014 retrying'
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

    def _update_workflow_progress(self) -> None:
        if self._session:
            try:
                self.query_one('#workflow-progress', WorkflowProgress).update_progress(
                    self._session.cfa_phase, self._session.cfa_state,
                )
            except Exception:
                pass

    def _update_stats(self) -> None:
        if not self._session:
            return
        dispatches = self._session.dispatches if self._session else []
        active = sum(1 for d in dispatches if d.status == 'active')
        complete = sum(1 for d in dispatches if d.status == 'complete')
        stats = [
            ('Tasks', f'{complete}/{len(dispatches)}'),
            ('Active', str(active)),
            ('Elapsed', _human_age(self._session.duration_seconds)),
            ('Idle', _human_age(self._session.stream_age_seconds)),
        ]
        try:
            self.query_one('#job-stats', StatsBar).update_stats(stats)
        except Exception:
            pass

    def _update_escalation_card(self) -> None:
        items = []
        if self._session and self._session.needs_input:
            items.append(CardItem(
                icon='\u23f3',
                label=self._session.cfa_state,
                detail=_human_label(self._session.cfa_state),
            ))
        self._update_card('escalations', items)

    def _update_artifacts_card(self) -> None:
        items = []
        for name, label in [('INTENT.md', 'Intent'), ('plan.md', 'Plan'), ('.work-summary.md', 'Work Summary')]:
            path = self._find_doc(name)
            if path:
                items.append(CardItem(icon='\u2713', label=label, detail=name))
            else:
                items.append(CardItem(icon='\u2591', label=f'[dim]{label}[/dim]', detail=''))
        self._update_card('artifacts', items)

    def _update_tasks_card(self) -> None:
        dispatches = self._session.dispatches if self._session else []
        active = [d for d in dispatches if d.status == 'active']
        items = []
        for d in active:
            icon = _dispatch_icon(d.status)
            name = d.worktree_name
            if '--' in name:
                name = name.split('--', 1)[1][:25]
            elif not name:
                name = os.path.basename(d.infra_dir) if d.infra_dir else '?'
            age = _human_age(d.stream_age_seconds)
            items.append(CardItem(
                icon=icon,
                label=name,
                detail=f'{d.team or "?"} {age}',
                data=d,
            ))
        self._update_card('job_tasks', items)

    def _update_card(self, card_name: str, items: list[CardItem]) -> None:
        try:
            for widget in self.query(ContentCard):
                if widget._card_name == card_name:
                    widget.update_items(items)
                    break
        except Exception:
            pass

    def _update_todos(self) -> None:
        stream_files = self.app.state_reader.active_stream_files(self.session_id)
        todos = read_todos_from_streams(stream_files)
        self._last_todos = todos

    def on_content_card_item_selected(self, event: ContentCard.ItemSelected) -> None:
        if event.card_name == 'job_tasks' and event.item.data:
            dispatch = event.item.data
            ctx = self._nav_context.drill_down(
                DashboardLevel.TASK,
                task_id=os.path.basename(dispatch.infra_dir) if dispatch.infra_dir else dispatch.worktree_name,
            )
            from projects.POC.tui.screens.task_dashboard import TaskDashboard
            self.app.push_screen(TaskDashboard(ctx, dispatch, self._session))

    def _update_input_area(self) -> None:
        input_area = self.query_one('#input-area')
        prompt_label = self.query_one('#input-prompt', Static)
        was_visible = input_area.has_class('visible')

        _bus_bridge_text = ''
        _input_waiting = False
        if self._in_proc and self._in_proc.message_bus_path and self._in_proc.conversation_id:
            from projects.POC.tui.ipc import check_message_bus_request
            _bus_req = check_message_bus_request(
                self._in_proc.message_bus_path,
                self._in_proc.conversation_id,
            )
            if _bus_req is not None:
                _input_waiting = True
                _bus_bridge_text = _bus_req.get('bridge_text', '')
        if not _input_waiting and self._in_proc and self._in_proc.input_provider.is_waiting:
            _input_waiting = True
            req = self._in_proc.input_provider.current_request
            if req and req.bridge_text:
                _bus_bridge_text = req.bridge_text

        if _input_waiting and self._in_proc:
            self._input_cooldown = False
            if not self._input_latched:
                self._input_latched = True
                input_area.add_class('visible')
                state = self._session.cfa_state if self._session else ''
                label = _bus_bridge_text if _bus_bridge_text else _human_label(state)
                prompt_label.update(f'[bold yellow]{label}[/bold yellow]')
                if _bus_bridge_text and _bus_bridge_text != self._shown_dialog_reply:
                    self._shown_dialog_reply = _bus_bridge_text
                    log = self.query_one('#activity-log', RichLog)
                    from rich.text import Text
                    t = Text()
                    t.append('[agent] ', style='bold cyan')
                    t.append(_bus_bridge_text)
                    log.write(t)
                    if not self._scroll_locked:
                        log.scroll_end(animate=False)
                if not was_visible:
                    self.query_one('#input-field', TextArea).focus()
            return

        if self._input_latched:
            return

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
                self._input_cooldown = False
            else:
                if self._session and self._session.needs_input and not self._session.is_orphaned:
                    return
                self._input_cooldown = False
                return

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
        field = self.query_one('#input-field', TextArea)
        response = field.text.strip()
        if not response:
            return

        sent = False

        if self._in_proc and self._in_proc.message_bus_path and self._in_proc.conversation_id:
            from projects.POC.tui.ipc import send_message_bus_response
            send_message_bus_response(
                self._in_proc.message_bus_path,
                self._in_proc.conversation_id,
                response,
            )
            sent = True
        elif self._session and self._session.infra_dir and not self._session.is_orphaned:
            from projects.POC.tui.ipc import send_message_bus_response
            bus_path = os.path.join(self._session.infra_dir, 'messages.db')
            if os.path.exists(bus_path):
                conv_id = f'session:{os.path.basename(self._session.infra_dir)}'
                send_message_bus_response(bus_path, conv_id, response)
                sent = True
            else:
                from projects.POC.tui.ipc import send_response
                send_response(self._session.infra_dir, response)
                sent = True

        if sent:
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

    def _update_chat_panel(self) -> None:
        chat = self.query_one('#chat-panel', RichLog)
        bus_path = ''
        conv_id = ''
        if self._in_proc and self._in_proc.message_bus_path and self._in_proc.conversation_id:
            bus_path = self._in_proc.message_bus_path
            conv_id = self._in_proc.conversation_id
        elif self._session and self._session.infra_dir:
            candidate = os.path.join(self._session.infra_dir, 'messages.db')
            if os.path.exists(candidate):
                bus_path = candidate
                conv_id = f'session:{os.path.basename(self._session.infra_dir)}'

        if not bus_path or not conv_id:
            return

        try:
            from projects.POC.orchestrator.messaging import SqliteMessageBus
            bus = SqliteMessageBus(bus_path)
            try:
                messages = bus.receive(conv_id)
            finally:
                bus.close()
        except Exception:
            return

        if len(messages) <= self._chat_msg_count:
            return

        from rich.text import Text
        from projects.POC.tui.chat_model import format_gate_context
        for msg in messages[self._chat_msg_count:]:
            t = Text()
            if msg.sender == 'human':
                t.append('[you] ', style='bold green')
            elif msg.sender == 'orchestrator':
                t.append('[agent] ', style='bold cyan')
                if self._session and self._session.cfa_state:
                    artifact = ''
                    state = self._session.cfa_state
                    if 'INTENT' in state:
                        p = self._find_doc('INTENT.md')
                        if p:
                            artifact = p
                    elif 'PLAN' in state:
                        p = self._find_doc('plan.md')
                        if p:
                            artifact = p
                    elif 'WORK' in state:
                        p = self._find_doc('.work-summary.md')
                        if p:
                            artifact = p
                    gate_ctx = format_gate_context(state, artifact)
                    if gate_ctx and gate_ctx != state:
                        t.append(f'[{gate_ctx}] ', style='dim yellow')
            else:
                t.append(f'[{msg.sender}] ', style='bold')
            t.append(msg.content)
            chat.write(t)

        self._chat_msg_count = len(messages)
        chat.scroll_end(animate=False)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        if event.text_area.id != 'input-field':
            return
        if '\n' in event.text_area.text:
            event.text_area.text = event.text_area.text.replace('\n', '')
            self._submit_input()

    def periodic_refresh(self) -> None:
        self.app.state_reader.reload()
        self._session = self.app.state_reader.find_session(self.session_id)
        self._in_proc = self.app.get_in_process(self.session_id)
        self._update_header()
        self._update_meta()
        self._update_workflow_progress()
        self._update_stats()
        self._update_escalation_card()
        self._update_artifacts_card()
        self._update_tasks_card()
        self._update_input_area()
        self._update_chat_panel()
        self.refresh_bindings()

        stream_files = self.app.state_reader.active_stream_files(self.session_id)
        for f in stream_files:
            self.watcher.watch(f)

    def _on_recovery_modal_dismiss(self, result: str) -> None:
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

    def _launch_resume(self, infra_dir: str) -> None:
        import asyncio
        import logging
        from projects.POC.orchestrator.events import EventBus, Event, EventType
        from projects.POC.orchestrator.tui_bridge import TUIInputProvider, InProcessSession
        from projects.POC.orchestrator.session import Session

        _rlog = logging.getLogger('orchestrator.resume')

        if self._in_proc and self._in_proc.run_task and not self._in_proc.run_task.done():
            log = self.query_one('#activity-log', RichLog)
            from rich.text import Text
            t = Text()
            t.append('[recovery] ', style='bold yellow')
            t.append('Session is already running. Wait for it to finish.')
            log.write(t)
            return

        event_bus = EventBus()
        provider = TUIInputProvider()

        in_proc = InProcessSession(
            session_id=self.session_id,
            project=self._session.project if self._session else '',
            task=self._session.task if self._session else '',
            event_bus=event_bus,
            input_provider=provider,
        )

        async def on_session_started(event: Event) -> None:
            if event.type == EventType.SESSION_STARTED:
                in_proc.message_bus_path = event.data.get('message_bus_path', '')
                in_proc.conversation_id = event.data.get('conversation_id', '')
                event_bus.unsubscribe(on_session_started)
        event_bus.subscribe(on_session_started)

        self.app.register_in_process(self.session_id, in_proc)
        self._in_proc = in_proc

        async def run_resumed() -> None:
            try:
                await Session.resume_from_disk(
                    infra_dir,
                    poc_root=self.app.poc_root,
                    projects_dir=self.app.projects_dir,
                    event_bus=event_bus,
                    input_provider=provider,
                )
            except BaseException as exc:
                _rlog.exception('Resume failed for %s', infra_dir)
                _handle_session_crash(infra_dir)
                try:
                    log = self.query_one('#activity-log', RichLog)
                    from rich.text import Text
                    t = Text()
                    t.append('[recovery] ', style='bold red')
                    t.append(f'Resume failed: {type(exc).__name__}: {exc}')
                    log.write(t)
                except Exception:
                    pass
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
            try:
                await withdraw_session(
                    session,
                    event_bus=bus,
                    in_process_task=in_task,
                )
            except Exception:
                pass

        asyncio.create_task(_withdraw())
        self.app.pop_screen()

    def _check_overloaded(self, session) -> bool:
        if not session.infra_dir:
            return False
        return os.path.exists(os.path.join(session.infra_dir, '.api-overloaded'))

    def action_go_back(self) -> None:
        self.app.pop_screen()

    def _session_worktree(self) -> str | None:
        if not self._session:
            return None
        if self._session.worktree_path and os.path.isdir(self._session.worktree_path):
            return self._session.worktree_path
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

    def action_open_chat(self) -> None:
        from projects.POC.tui.screens.management_dashboard import _open_chat_window
        _open_chat_window(self.app)
