"""Standalone chat window — runs as a separate Textual app in its own terminal.

Usage:
    uv run python -m projects.POC.tui.chat_main [--project-dir DIR]
"""
from __future__ import annotations

import argparse
import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from textual.app import App, ComposeResult

from projects.POC.tui.state_reader import StateReader


class ChatApp(App):
    """Standalone chat application in its own terminal window."""

    TITLE = 'TeaParty Chat'
    CSS_PATH = 'styles.tcss'
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, projects_dir: str | None = None):
        super().__init__()
        from pathlib import Path
        here = Path(__file__).resolve().parent
        self.poc_root = str(here.parent)
        self.projects_dir = projects_dir if projects_dir is not None else os.path.dirname(self.poc_root)
        self._in_process: dict = {}
        self.state_reader = StateReader(
            self.poc_root,
            projects_dir=self.projects_dir,
            in_process_checker=self.has_in_process,
        )

    def has_in_process(self, session_id: str) -> bool:
        return False

    def get_in_process(self, session_id: str):
        return None

    def on_mount(self) -> None:
        from projects.POC.tui.screens.chat import ChatScreen
        self.push_screen(ChatScreen())
        self.set_interval(1.0, self._periodic_refresh)

    def _periodic_refresh(self) -> None:
        screen = self.screen
        if hasattr(screen, 'periodic_refresh'):
            screen.periodic_refresh()


def main():
    parser = argparse.ArgumentParser(description='TeaParty Chat Window')
    parser.add_argument('--project-dir', type=str, default=None)
    args = parser.parse_args()

    projects_dir = None
    if args.project_dir:
        projects_dir = os.path.realpath(os.path.abspath(args.project_dir))

    app = ChatApp(projects_dir=projects_dir)
    app.run()


if __name__ == '__main__':
    main()
