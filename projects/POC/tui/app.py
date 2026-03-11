"""Main Textual application — screen routing, global state, periodic refresh."""
from __future__ import annotations

import os
from pathlib import Path

from textual.app import App

from projects.POC.tui.state_reader import StateReader


def _find_poc_root() -> str:
    """Walk up from this file to find projects/POC/."""
    here = Path(__file__).resolve().parent  # tui/
    poc = here.parent                       # POC/
    if not (poc / '.sessions').exists() and not (poc / 'run.sh').exists():
        # Fallback: try CWD
        cwd = Path.cwd()
        for candidate in [cwd / 'projects' / 'POC', cwd]:
            if (candidate / 'run.sh').exists():
                return str(candidate)
    return str(poc)


class TeaPartyTUI(App):
    """TeaParty POC Dashboard."""

    TITLE = 'TeaParty'
    CSS_PATH = 'styles.tcss'

    def __init__(self, projects_dir: str | None = None):
        super().__init__()
        self.poc_root = _find_poc_root()
        # projects_dir: configurable parent of project folders; defaults to dirname(poc_root)
        self.projects_dir = projects_dir if projects_dir is not None else os.path.dirname(self.poc_root)
        self.state_reader = StateReader(self.poc_root, projects_dir=self.projects_dir)

    def set_projects_dir(self, new_dir: str) -> None:
        """Change the active projects directory mid-session."""
        resolved = os.path.realpath(os.path.abspath(new_dir))
        self.projects_dir = resolved
        self.state_reader = StateReader(self.poc_root, projects_dir=resolved)

    def on_mount(self) -> None:
        from projects.POC.tui.screens.dashboard import DashboardScreen
        self.push_screen(DashboardScreen())
        self.set_interval(1.0, self._periodic_refresh)

    def _periodic_refresh(self) -> None:
        """Refresh the active screen's data every second."""
        screen = self.screen
        if hasattr(screen, 'periodic_refresh'):
            screen.periodic_refresh()
