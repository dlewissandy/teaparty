"""Launch screen — start a new session with task prompt."""
from __future__ import annotations

import asyncio
import os

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Select, Static


class LaunchScreen(Screen):
    """New session launcher."""

    BINDINGS = [
        Binding('escape', 'go_back', 'Cancel', show=True),
    ]

    def __init__(self, project: str = 'POC'):
        super().__init__()
        self._default_project = project or 'POC'

    def compose(self) -> ComposeResult:
        yield Vertical(
            Center(
                Vertical(
                    Static(f'New Session ({self._default_project})', classes='form-title'),
                    Static('Task:'),
                    Input(placeholder='Describe the task...', id='task-input'),
                    Static('Project:'),
                    Select(
                        self._get_project_options(),
                        id='project-select',
                        value=self._default_project,
                    ),
                    Button('Launch', variant='success', id='launch-btn'),
                    id='launch-form',
                ),
            ),
        )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one('#task-input', Input).focus()

    def _get_project_options(self) -> list[tuple[str, str]]:
        """Scan projects directory for available projects."""
        options = []
        projects_dir = self.app.projects_dir
        try:
            for name in sorted(os.listdir(projects_dir)):
                full = os.path.join(projects_dir, name)
                sessions = os.path.join(full, '.sessions')
                if os.path.isdir(sessions) and not name.startswith('.'):
                    options.append((name, name))
        except OSError:
            pass
        if not options:
            options = [('POC', 'POC')]
        return options

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'launch-btn':
            await self._launch_session()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == 'task-input':
            await self._launch_session()

    async def _launch_session(self) -> None:
        task = self.query_one('#task-input', Input).value.strip()
        if not task:
            return

        project_select = self.query_one('#project-select', Select)
        project = str(project_select.value) if project_select.value != Select.BLANK else 'POC'

        from projects.POC.orchestrator.events import EventBus, Event, EventType
        from projects.POC.orchestrator.tui_bridge import TUIInputProvider, InProcessSession
        from projects.POC.orchestrator.session import Session

        bus = EventBus()
        provider = TUIInputProvider()

        session = Session(
            task=task,
            poc_root=self.app.poc_root,
            projects_dir=self.app.projects_dir,
            project_override=project,
            event_bus=bus,
            input_provider=provider,
        )

        in_proc = InProcessSession(
            session_id='',
            project=project,
            task=task,
            event_bus=bus,
            input_provider=provider,
        )

        # Capture session_id when the session starts
        async def on_session_started(event: Event) -> None:
            if event.type == EventType.SESSION_STARTED:
                sid = event.data.get('session_id', '')
                if sid:
                    self.app.register_in_process(sid, in_proc)
                bus.unsubscribe(on_session_started)

        bus.subscribe(on_session_started)

        # Run session as async task
        async def run_session() -> None:
            try:
                await session.run()
            except Exception:
                # Don't remove .running — leave it for orphan detection so the
                # user gets the recovery UI rather than a silently dead session.
                pass

        in_proc.run_task = asyncio.create_task(run_session())

        # Return to dashboard
        self.app.pop_screen()

    def action_go_back(self) -> None:
        self.app.pop_screen()
