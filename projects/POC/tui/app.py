"""Main Textual application — screen routing, global state, periodic refresh."""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import App

from projects.POC.orchestrator.cron_driver import CronDriver
from projects.POC.tui.state_reader import StateReader

_log = logging.getLogger('orchestrator')

if TYPE_CHECKING:
    from projects.POC.orchestrator.tui_bridge import InProcessSession


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
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, projects_dir: str | None = None):
        super().__init__()
        self.poc_root = _find_poc_root()
        # projects_dir: configurable parent of project folders; defaults to dirname(poc_root)
        self.projects_dir = projects_dir if projects_dir is not None else os.path.dirname(self.poc_root)
        self._in_process: dict[str, InProcessSession] = {}
        self.state_reader = StateReader(
            self.poc_root,
            projects_dir=self.projects_dir,
            in_process_checker=self.has_in_process,
        )
        self.cron_driver = CronDriver.from_config(
            project_dir=self.poc_root,
        )

    def set_projects_dir(self, new_dir: str) -> None:
        """Change the active projects directory mid-session."""
        resolved = os.path.realpath(os.path.abspath(new_dir))
        self.projects_dir = resolved
        self.state_reader = StateReader(
            self.poc_root,
            projects_dir=resolved,
            in_process_checker=self.has_in_process,
        )

    def on_mount(self) -> None:
        from projects.POC.tui.screens.dashboard_screen import DashboardScreen
        self.push_screen(DashboardScreen())
        self.set_interval(1.0, self._periodic_refresh)
        self.set_interval(60.0, self._cron_tick)

    # ── In-process session registry ──

    def register_in_process(self, session_id: str, session: InProcessSession) -> None:
        """Register a live in-process session (called on SESSION_STARTED)."""
        session.session_id = session_id
        self._in_process[session_id] = session

    def get_in_process(self, session_id: str) -> InProcessSession | None:
        """Return the InProcessSession for session_id, or None.

        Auto-cleans completed tasks from the registry.
        """
        ip = self._in_process.get(session_id)
        if ip and ip.run_task and ip.run_task.done():
            # Retrieve exception to avoid silent suppression
            if not ip.run_task.cancelled():
                try:
                    ip.run_task.exception()
                except Exception:
                    pass
            del self._in_process[session_id]
            return None
        return ip

    def has_in_process(self, session_id: str) -> bool:
        """Check if a session is running in-process (not yet completed)."""
        ip = self._in_process.get(session_id)
        return ip is not None and ip.run_task is not None and not ip.run_task.done()

    def _periodic_refresh(self) -> None:
        """Refresh the active screen's data every second."""
        screen = self.screen
        if hasattr(screen, 'periodic_refresh'):
            screen.periodic_refresh()

    def _cron_tick(self) -> None:
        """Run one cron scheduler cycle (every 60s)."""
        task = asyncio.create_task(self.cron_driver.tick())
        task.add_done_callback(self._on_cron_tick_done)

    @staticmethod
    def _on_cron_tick_done(task: asyncio.Task) -> None:
        """Log cron tick results and surface errors."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc:
            _log.error('Cron tick failed: %s', exc)
            return
        records = task.result()
        for record in records:
            if record.success:
                _log.info('Cron task %s completed', record.task_name)
            else:
                _log.error('Cron task %s failed: %s', record.task_name, record.reason)

    def on_unmount(self) -> None:
        """Kill all chat windows when the dashboard exits."""
        from projects.POC.tui.chat_main import kill_chat_windows
        kill_chat_windows(self.projects_dir)
