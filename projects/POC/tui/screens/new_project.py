"""New project screen — create a project directory."""
from __future__ import annotations

import os
import re

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Input, Static


class NewProjectScreen(Screen):
    """Create a new project."""

    BINDINGS = [
        Binding('escape', 'go_back', 'Cancel', show=True),
    ]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Center(
                Vertical(
                    Static('New Project', classes='form-title'),
                    Static('Project name:'),
                    Input(placeholder='e.g. my-research-paper', id='project-name-input'),
                    Static('', id='project-error'),
                    Button('Create', variant='success', id='create-btn'),
                    id='launch-form',
                ),
            ),
        )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one('#project-name-input', Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'create-btn':
            self._create_project()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == 'project-name-input':
            self._create_project()

    def _create_project(self) -> None:
        name = self.query_one('#project-name-input', Input).value.strip()
        error_widget = self.query_one('#project-error', Static)

        if not name:
            error_widget.update('[red]Project name is required[/red]')
            return

        # Validate: alphanumeric, hyphens, underscores
        if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_-]*$', name):
            error_widget.update('[red]Use letters, numbers, hyphens, underscores[/red]')
            return

        projects_dir = os.path.dirname(self.app.poc_root)
        project_path = os.path.join(projects_dir, name)

        if os.path.exists(project_path):
            error_widget.update(f'[red]Project "{name}" already exists[/red]')
            return

        # Create project directory with .sessions/
        try:
            os.makedirs(os.path.join(project_path, '.sessions'), exist_ok=True)
            error_widget.update('')
        except OSError as e:
            error_widget.update(f'[red]Failed: {e}[/red]')
            return

        self.app.pop_screen()

    def action_go_back(self) -> None:
        self.app.pop_screen()
