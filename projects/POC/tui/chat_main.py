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


def _pid_dir(projects_dir: str) -> str:
    """Directory where chat window PIDs are registered."""
    d = os.path.join(projects_dir, '.chat-pids')
    os.makedirs(d, exist_ok=True)
    return d


def _register_pid(projects_dir: str) -> str:
    """Write this process's PID to a file. Returns the path."""
    pid_file = os.path.join(_pid_dir(projects_dir), str(os.getpid()))
    with open(pid_file, 'w') as f:
        f.write(str(os.getpid()))
    return pid_file


def _unregister_pid(pid_file: str) -> None:
    """Remove the PID file on exit."""
    try:
        os.unlink(pid_file)
    except OSError:
        pass


def kill_chat_windows(projects_dir: str) -> None:
    """Kill all registered chat window processes."""
    import signal
    d = os.path.join(projects_dir, '.chat-pids')
    if not os.path.isdir(d):
        return
    for name in os.listdir(d):
        path = os.path.join(d, name)
        try:
            with open(path) as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
        except (ValueError, OSError, ProcessLookupError):
            pass
        try:
            os.unlink(path)
        except OSError:
            pass


def global_bus_path(projects_dir: str) -> str:
    """Path to the global message bus (conversations not tied to a session)."""
    return os.path.join(projects_dir, '.messages.db')


def ensure_proxy_review_conversation(projects_dir: str, username: str) -> None:
    """Create the proxy_review conversation for the user if it doesn't exist."""
    from projects.POC.orchestrator.messaging import (
        ConversationType, SqliteMessageBus,
    )
    bus = SqliteMessageBus(global_bus_path(projects_dir))
    bus.create_conversation(ConversationType.PROXY_REVIEW, username)
    bus.close()


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
        self._pid_file: str = ''
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
        self._pid_file = _register_pid(self.projects_dir)
        from projects.POC.tui.screens.chat import ChatScreen
        self.push_screen(ChatScreen())
        self.set_interval(1.0, self._periodic_refresh)

    def on_unmount(self) -> None:
        if self._pid_file:
            _unregister_pid(self._pid_file)

    def _periodic_refresh(self) -> None:
        screen = self.screen
        if hasattr(screen, 'periodic_refresh'):
            screen.periodic_refresh()


def main():
    parser = argparse.ArgumentParser(description='TeaParty Chat Window')
    parser.add_argument('--project-dir', type=str, default=None)
    parser.add_argument('--ensure-proxy-review', type=str, default=None,
                        metavar='USERNAME',
                        help='Ensure a proxy_review conversation exists for this user')
    args = parser.parse_args()

    projects_dir = None
    if args.project_dir:
        projects_dir = os.path.realpath(os.path.abspath(args.project_dir))

    if args.ensure_proxy_review and projects_dir:
        ensure_proxy_review_conversation(projects_dir, args.ensure_proxy_review)

    app = ChatApp(projects_dir=projects_dir)
    app.run()


if __name__ == '__main__':
    main()
