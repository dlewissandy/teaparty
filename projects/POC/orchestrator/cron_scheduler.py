"""Project-scoped cron scheduler for agent teams.

Evaluates cron expressions from ScheduledTask configs, tracks last-run
timestamps, and dispatches due tasks as orchestrator sessions scoped to
the project's worktree and configuration.

Issue #195.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from croniter import croniter

from projects.POC.orchestrator.config_reader import (
    ScheduledTask,
    load_management_team,
    load_project_team,
)

_log = logging.getLogger('orchestrator')


# ── Public helpers ───────────────────────────────────────────────────────────

def next_run_time(cron_expr: str, after: datetime) -> datetime:
    """Return the next occurrence of a cron expression after the given time."""
    cron = croniter(cron_expr, after)
    return cron.get_next(datetime).replace(tzinfo=after.tzinfo)


def is_due(
    cron_expr: str,
    last_run: datetime | None,
    now: datetime,
) -> bool:
    """Check whether a task is due for execution.

    A task is due when the next scheduled time after last_run (or epoch
    if never run) is at or before now.
    """
    base = last_run if last_run else datetime(2000, 1, 1, tzinfo=timezone.utc)
    nxt = next_run_time(cron_expr, base)
    return nxt <= now


# ── Run record ───────────────────────────────────────────────────────────────

@dataclass
class RunRecord:
    """A single execution record for a scheduled task."""
    task_name: str
    timestamp: datetime
    success: bool
    reason: str = ''


# ── State file helpers ───────────────────────────────────────────────────────

_STATE_FILENAME = '.cron-state.json'
_LOG_FILENAME = '.cron-log.jsonl'


def _load_state(state_dir: str) -> dict:
    """Load the cron state file. Returns empty dict if missing/corrupt."""
    path = os.path.join(state_dir, _STATE_FILENAME)
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        _log.warning('Corrupt cron state file: %s', path)
        return {}


def _save_state(state_dir: str, state: dict) -> None:
    """Atomic write of cron state file (write-to-temp + rename)."""
    path = os.path.join(state_dir, _STATE_FILENAME)
    fd, tmp = tempfile.mkstemp(dir=state_dir, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(state, f, indent=2, default=str)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _append_log(state_dir: str, record: RunRecord) -> None:
    """Append a run record to the JSONL log."""
    path = os.path.join(state_dir, _LOG_FILENAME)
    entry = {
        'task_name': record.task_name,
        'timestamp': record.timestamp.isoformat(),
        'success': record.success,
        'reason': record.reason,
    }
    with open(path, 'a') as f:
        f.write(json.dumps(entry) + '\n')


def _load_log(state_dir: str, task_name: str) -> list[RunRecord]:
    """Load run records for a specific task from the JSONL log."""
    path = os.path.join(state_dir, _LOG_FILENAME)
    if not os.path.exists(path):
        return []
    records: list[RunRecord] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get('task_name') != task_name:
                continue
            records.append(RunRecord(
                task_name=entry['task_name'],
                timestamp=datetime.fromisoformat(entry['timestamp']),
                success=entry['success'],
                reason=entry.get('reason', ''),
            ))
    return records


# ── Scheduler ────────────────────────────────────────────────────────────────

class CronScheduler:
    """Evaluates cron schedules and dispatches due tasks.

    Args:
        tasks: Scheduled tasks from config (management + project merged).
        state_dir: Directory for state and log files.
        project_dir: Project root for scoped execution.
        project_slug: Project identifier for session dispatch.
    """

    def __init__(
        self,
        tasks: list[ScheduledTask],
        state_dir: str,
        project_dir: str,
        project_slug: str,
    ):
        self.tasks = tasks
        self.state_dir = state_dir
        self.project_dir = project_dir
        self.project_slug = project_slug
        self._state = _load_state(state_dir)

    def get_due_tasks(self, now: datetime | None = None) -> list[ScheduledTask]:
        """Return tasks that are due for execution."""
        if now is None:
            now = datetime.now(timezone.utc)
        due: list[ScheduledTask] = []
        for task in self.tasks:
            if not task.enabled:
                continue
            last = self.get_last_run(task.name)
            if is_due(task.schedule, last, now):
                due.append(task)
        return due

    def get_last_run(self, task_name: str) -> datetime | None:
        """Return the last run timestamp for a task, or None if never run."""
        iso = self._state.get(task_name, {}).get('last_run')
        if iso is None:
            return None
        return datetime.fromisoformat(iso)

    def record_run(
        self,
        task_name: str,
        timestamp: datetime,
        success: bool,
        reason: str = '',
    ) -> None:
        """Record a task run — updates state and appends to log."""
        if task_name not in self._state:
            self._state[task_name] = {}
        self._state[task_name]['last_run'] = timestamp.isoformat()
        _save_state(self.state_dir, self._state)

        record = RunRecord(
            task_name=task_name,
            timestamp=timestamp,
            success=success,
            reason=reason,
        )
        _append_log(self.state_dir, record)

    def get_run_log(self, task_name: str) -> list[RunRecord]:
        """Return all run records for a task."""
        return _load_log(self.state_dir, task_name)

    async def run_task(
        self,
        task: ScheduledTask,
        session_factory: Any = None,
    ) -> RunRecord:
        """Execute a single scheduled task as a session.

        Constructs a task description from the skill name and args,
        then launches a Session scoped to this scheduler's project.
        Records the result (success/failure) and returns the RunRecord.

        Args:
            task: The scheduled task to execute.
            session_factory: Callable that creates a Session (default: real
                Session class). Injected for testing.
        """
        from projects.POC.orchestrator import find_poc_root
        from projects.POC.orchestrator.events import EventBus

        if session_factory is None:
            from projects.POC.orchestrator.session import Session
            session_factory = Session

        now = datetime.now(timezone.utc)
        task_description = f'[scheduled:{task.name}] {task.skill}'
        if task.args:
            task_description += f' {task.args}'

        poc_root = find_poc_root()
        try:
            session = session_factory(
                task_description,
                poc_root=poc_root,
                project_override=self.project_slug,
                skip_intent=True,
                execute_only=True,
                skip_learnings=True,
                event_bus=EventBus(),
                input_provider=None,
            )
            result = await session.run()
            success = result.terminal_state == 'COMPLETED_WORK'
            reason = '' if success else f'terminal_state={result.terminal_state}'
        except Exception as exc:
            success = False
            reason = str(exc)

        self.record_run(task.name, now, success=success, reason=reason)
        return RunRecord(
            task_name=task.name, timestamp=now,
            success=success, reason=reason,
        )

    async def tick(
        self,
        now: datetime | None = None,
        session_factory: Any = None,
    ) -> list[RunRecord]:
        """Run one evaluation cycle: find due tasks, execute them, record results.

        Returns a list of RunRecords for all tasks that were executed.
        """
        due = self.get_due_tasks(now=now)
        records: list[RunRecord] = []
        for task in due:
            _log.info('Cron executing: %s (skill=%s)', task.name, task.skill)
            record = await self.run_task(task, session_factory=session_factory)
            records.append(record)
            if not record.success:
                _log.error(
                    'Cron task %s failed: %s', task.name, record.reason,
                )
        return records


# ── Task collection ──────────────────────────────────────────────────────────

def collect_scheduled_tasks(
    project_dir: str,
    teaparty_home: str = '~/.teaparty',
) -> list[ScheduledTask]:
    """Collect scheduled tasks from management team and project config.

    Merges both levels. Management-level tasks apply to the org;
    project-level tasks are scoped to the project.
    """
    tasks: list[ScheduledTask] = []
    try:
        mgmt = load_management_team(teaparty_home=teaparty_home)
        tasks.extend(mgmt.scheduled)
    except FileNotFoundError:
        _log.debug('No management config found at %s', teaparty_home)

    try:
        proj = load_project_team(project_dir)
        tasks.extend(proj.scheduled)
    except FileNotFoundError:
        _log.debug('No project config found at %s', project_dir)

    return tasks
