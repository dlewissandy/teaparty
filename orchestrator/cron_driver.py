"""Runtime driver for the cron scheduler.

Wraps CronScheduler with a re-entrancy guard and a factory that builds
from project config.  The bridge (or any other runtime) calls tick()
periodically; the driver handles the rest.

Issue #274.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from orchestrator.cron_scheduler import (
    CronScheduler,
    RunRecord,
    collect_scheduled_tasks,
)

_log = logging.getLogger('orchestrator')


class CronDriver:
    """Periodic driver for CronScheduler.

    Provides a re-entrancy-safe tick() and a from_config() factory
    that collects tasks from management + project YAML.
    """

    def __init__(
        self,
        tasks: list,
        state_dir: str,
        project_dir: str,
        project_slug: str,
    ):
        self.scheduler = CronScheduler(
            tasks=tasks,
            state_dir=state_dir,
            project_dir=project_dir,
            project_slug=project_slug,
        )
        self._lock = asyncio.Lock()

    async def tick(
        self,
        now: datetime | None = None,
        session_factory: Any = None,
    ) -> list[RunRecord]:
        """Run one scheduler cycle, guarded against re-entrancy.

        If a tick is already in progress, returns immediately with
        an empty list.
        """
        if self._lock.locked():
            _log.debug('Cron tick skipped — previous tick still running')
            return []

        async with self._lock:
            return await self.scheduler.tick(
                now=now, session_factory=session_factory,
            )

    async def run_now(
        self,
        task_name: str,
        session_factory: Any = None,
    ) -> RunRecord:
        """Trigger immediate execution of a task, bypassing the cron schedule.

        Re-entrancy safe: waits for any in-progress tick to finish first.
        Raises KeyError if no task with the given name exists.
        """
        async with self._lock:
            return await self.scheduler.run_now(
                task_name, session_factory=session_factory,
            )

    @classmethod
    def from_config(
        cls,
        project_dir: str,
        project_slug: str = '',
        state_dir: str | None = None,
        teaparty_home: str | None = None,
    ) -> CronDriver:
        """Build a CronDriver from project and management config.

        Config errors are caught so the caller always gets a usable
        driver (possibly with an empty schedule).
        """
        try:
            tasks = collect_scheduled_tasks(
                project_dir, teaparty_home=teaparty_home,
            )
        except Exception:
            _log.warning(
                'Failed to collect scheduled tasks; starting with empty schedule',
                exc_info=True,
            )
            tasks = []

        if state_dir is None:
            import os
            state_dir = os.path.join(project_dir, '.sessions')
            os.makedirs(state_dir, exist_ok=True)

        return cls(
            tasks=tasks,
            state_dir=state_dir,
            project_dir=project_dir,
            project_slug=project_slug,
        )
