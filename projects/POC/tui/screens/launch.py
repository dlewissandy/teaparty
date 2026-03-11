"""Launch screen — start a new session with task prompt."""
from __future__ import annotations

import os
import subprocess

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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'launch-btn':
            self._launch_session()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == 'task-input':
            self._launch_session()

    def _launch_session(self) -> None:
        task = self.query_one('#task-input', Input).value.strip()
        if not task:
            return

        project_select = self.query_one('#project-select', Select)
        project = str(project_select.value) if project_select.value != Select.BLANK else 'POC'

        # Build command
        run_script = os.path.join(self.app.poc_root, 'run.sh')
        cmd = ['bash', run_script]
        if project:
            cmd.extend(['--project', project])
        cmd.append(task)

        # Set TUI mode so sessions use FIFO IPC instead of /dev/tty
        env = os.environ.copy()
        env['POC_TUI_MODE'] = '1'

        # Launch as background process
        subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )

        # Return to dashboard
        self.app.pop_screen()

    def action_go_back(self) -> None:
        self.app.pop_screen()
