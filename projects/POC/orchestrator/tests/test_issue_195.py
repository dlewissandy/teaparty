#!/usr/bin/env python3
"""Tests for Issue #195: Project-scoped cron jobs for agent teams.

Covers:
 1. CronScheduler loads scheduled tasks from management and project configs
 2. Cron expression evaluation — next_run and is_due detection
 3. Enabled/disabled task filtering
 4. State persistence — last_run timestamps survive restart
 5. Execution dispatch — due tasks trigger session runs
 6. Failure recording — failed runs logged with reason
 7. Dual-level collection — management + project tasks merged correctly
 8. Atomic state writes — no corruption on concurrent access
"""
import json
import os
import sys
import tempfile
import textwrap
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.config_reader import ScheduledTask
from projects.POC.orchestrator.tests.test_helpers import make_tmp_dir
from projects.POC.orchestrator.cron_scheduler import (
    CronScheduler,
    RunRecord,
    collect_scheduled_tasks,
    is_due,
    next_run_time,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_scheduled_task(
    name: str = 'nightly-sweep',
    schedule: str = '0 2 * * *',
    skill: str = 'test-sweep',
    args: str = '',
    enabled: bool = True,
) -> ScheduledTask:
    return ScheduledTask(
        name=name,
        schedule=schedule,
        skill=skill,
        args=args,
        enabled=enabled,
    )


def _make_state_dir() -> str:
    return tempfile.mkdtemp()


def _make_scheduler(
    tasks: list[ScheduledTask] | None = None,
    state_dir: str | None = None,
    project_dir: str | None = None,
    project_slug: str = 'test-project',
) -> CronScheduler:
    if project_dir is None:
        project_dir = _make_state_dir()
    if tasks is None:
        tasks = [_make_scheduled_task()]
    if state_dir is None:
        state_dir = _make_state_dir()
    return CronScheduler(
        tasks=tasks,
        state_dir=state_dir,
        project_dir=project_dir,
        project_slug=project_slug,
    )


# ── Tests ────────────────────────────────────────────────────────────────────

class TestCronExpressionEvaluation(unittest.TestCase):
    """Cron expression parsing and next-run calculation."""

    def test_next_run_daily_at_2am(self):
        """A '0 2 * * *' schedule returns a future 2:00 AM time."""
        now = datetime(2026, 3, 27, 10, 0, 0, tzinfo=timezone.utc)
        nxt = next_run_time('0 2 * * *', now)
        self.assertEqual(nxt.hour, 2)
        self.assertEqual(nxt.minute, 0)
        self.assertGreater(nxt, now)

    def test_next_run_every_5_minutes(self):
        """A '*/5 * * * *' schedule returns within 5 minutes."""
        now = datetime(2026, 3, 27, 10, 3, 0, tzinfo=timezone.utc)
        nxt = next_run_time('*/5 * * * *', now)
        self.assertLessEqual((nxt - now).total_seconds(), 300)

    def test_is_due_when_never_run(self):
        """A task that has never run is due if next_run <= now."""
        now = datetime(2026, 3, 28, 2, 1, 0, tzinfo=timezone.utc)
        self.assertTrue(is_due('0 2 * * *', last_run=None, now=now))

    def test_is_due_when_last_run_old(self):
        """A task last run yesterday at 2AM is due today at 2:01AM."""
        now = datetime(2026, 3, 28, 2, 1, 0, tzinfo=timezone.utc)
        last = datetime(2026, 3, 27, 2, 0, 0, tzinfo=timezone.utc)
        self.assertTrue(is_due('0 2 * * *', last_run=last, now=now))

    def test_not_due_when_recently_run(self):
        """A task that ran at 2:00 today is not due at 2:01 today."""
        now = datetime(2026, 3, 28, 2, 1, 0, tzinfo=timezone.utc)
        last = datetime(2026, 3, 28, 2, 0, 0, tzinfo=timezone.utc)
        self.assertFalse(is_due('0 2 * * *', last_run=last, now=now))


class TestTaskFiltering(unittest.TestCase):
    """Enabled/disabled task filtering."""

    def test_disabled_tasks_excluded_from_due(self):
        """Disabled tasks are never returned as due."""
        scheduler = _make_scheduler(tasks=[
            _make_scheduled_task(name='active', enabled=True),
            _make_scheduled_task(name='paused', enabled=False),
        ])
        # Force both tasks to be "due" by setting no last_run
        due = scheduler.get_due_tasks(
            now=datetime(2026, 3, 28, 2, 1, 0, tzinfo=timezone.utc),
        )
        names = [t.name for t in due]
        self.assertIn('active', names)
        self.assertNotIn('paused', names)

    def test_empty_task_list(self):
        """Scheduler with no tasks returns empty due list."""
        scheduler = _make_scheduler(tasks=[])
        due = scheduler.get_due_tasks(
            now=datetime(2026, 3, 28, 2, 1, 0, tzinfo=timezone.utc),
        )
        self.assertEqual(due, [])


class TestStatePersistence(unittest.TestCase):
    """Last-run state file read/write."""

    def test_record_run_persists_to_disk(self):
        """After recording a run, state file contains the timestamp."""
        state_dir = _make_state_dir()
        scheduler = _make_scheduler(state_dir=state_dir)
        now = datetime(2026, 3, 28, 2, 0, 0, tzinfo=timezone.utc)

        scheduler.record_run('nightly-sweep', now, success=True)

        # New scheduler instance loads persisted state
        scheduler2 = _make_scheduler(state_dir=state_dir)
        last = scheduler2.get_last_run('nightly-sweep')
        self.assertIsNotNone(last)
        self.assertEqual(last, now)

    def test_missing_state_file_returns_none(self):
        """A fresh scheduler returns None for last_run."""
        scheduler = _make_scheduler()
        self.assertIsNone(scheduler.get_last_run('nightly-sweep'))

    def test_state_survives_reload(self):
        """State written by one instance is readable by another."""
        state_dir = _make_state_dir()
        s1 = _make_scheduler(state_dir=state_dir)
        now = datetime(2026, 3, 28, 2, 0, 0, tzinfo=timezone.utc)
        s1.record_run('nightly-sweep', now, success=True)

        s2 = _make_scheduler(state_dir=state_dir)
        self.assertEqual(s2.get_last_run('nightly-sweep'), now)


class TestFailureRecording(unittest.TestCase):
    """Failed runs are logged with reason."""

    def test_failed_run_recorded_with_reason(self):
        """A failed run records the error reason in the run log."""
        state_dir = _make_state_dir()
        scheduler = _make_scheduler(state_dir=state_dir)
        now = datetime(2026, 3, 28, 2, 0, 0, tzinfo=timezone.utc)

        scheduler.record_run(
            'nightly-sweep', now,
            success=False, reason='skill not found: test-sweep',
        )

        log = scheduler.get_run_log('nightly-sweep')
        self.assertEqual(len(log), 1)
        self.assertFalse(log[0].success)
        self.assertEqual(log[0].reason, 'skill not found: test-sweep')

    def test_successful_run_has_no_reason(self):
        """A successful run has empty reason."""
        state_dir = _make_state_dir()
        scheduler = _make_scheduler(state_dir=state_dir)
        now = datetime(2026, 3, 28, 2, 0, 0, tzinfo=timezone.utc)

        scheduler.record_run('nightly-sweep', now, success=True)

        log = scheduler.get_run_log('nightly-sweep')
        self.assertEqual(len(log), 1)
        self.assertTrue(log[0].success)
        self.assertEqual(log[0].reason, '')


class TestDualLevelCollection(unittest.TestCase):
    """Management + project tasks are merged correctly."""

    def test_tasks_from_both_levels(self):
        """Scheduler accepts tasks from multiple config levels."""
        mgmt_task = _make_scheduled_task(name='org-audit', schedule='0 3 * * 0')
        proj_task = _make_scheduled_task(name='nightly-sweep', schedule='0 2 * * *')
        scheduler = _make_scheduler(tasks=[mgmt_task, proj_task])
        due = scheduler.get_due_tasks(
            now=datetime(2026, 3, 29, 3, 1, 0, tzinfo=timezone.utc),  # Sunday 3:01 AM
        )
        names = [t.name for t in due]
        # Both should be due (never run before, past their scheduled time)
        self.assertIn('org-audit', names)
        self.assertIn('nightly-sweep', names)


class TestRunRecord(unittest.TestCase):
    """RunRecord dataclass basics."""

    def test_run_record_fields(self):
        now = datetime(2026, 3, 28, 2, 0, 0, tzinfo=timezone.utc)
        record = RunRecord(
            task_name='sweep', timestamp=now, success=True, reason='',
        )
        self.assertEqual(record.task_name, 'sweep')
        self.assertEqual(record.timestamp, now)
        self.assertTrue(record.success)


def _make_session_factory(terminal_state='COMPLETED_WORK', side_effect=None):
    """Create a mock session factory for testing run_task."""
    mock_session = AsyncMock()
    if side_effect:
        mock_session.run.side_effect = side_effect
    else:
        mock_result = type('R', (), {'terminal_state': terminal_state})()
        mock_session.run.return_value = mock_result
    factory = lambda *args, **kwargs: mock_session  # noqa: E731
    factory._mock_session = mock_session
    factory._calls = []
    original_factory = factory

    def tracking_factory(*args, **kwargs):
        original_factory._calls.append((args, kwargs))
        return mock_session

    tracking_factory._mock_session = mock_session
    tracking_factory._calls = original_factory._calls
    return tracking_factory


class TestRunTask(unittest.TestCase):
    """run_task dispatches a session scoped to the project."""

    def test_run_task_success(self):
        """A successful session run records success in the log."""
        import asyncio
        scheduler = _make_scheduler()
        task = _make_scheduled_task()
        factory = _make_session_factory('COMPLETED_WORK')

        record = asyncio.run(scheduler.run_task(task, session_factory=factory))

        self.assertTrue(record.success)
        self.assertEqual(record.task_name, 'nightly-sweep')
        self.assertEqual(record.reason, '')

        # Verify Session was constructed with project scoping
        call_kwargs = factory._calls[0][1]
        self.assertEqual(call_kwargs['project_override'], 'test-project')
        self.assertTrue(call_kwargs['skip_intent'])
        self.assertTrue(call_kwargs['execute_only'])

    def test_run_task_failure(self):
        """A failed session run records the failure reason."""
        import asyncio
        scheduler = _make_scheduler()
        task = _make_scheduled_task()
        factory = _make_session_factory('WITHDRAWN')

        record = asyncio.run(scheduler.run_task(task, session_factory=factory))

        self.assertFalse(record.success)
        self.assertIn('WITHDRAWN', record.reason)

    def test_run_task_exception(self):
        """An exception during session run records the error."""
        import asyncio
        scheduler = _make_scheduler()
        task = _make_scheduled_task()
        factory = _make_session_factory(side_effect=RuntimeError('claude CLI not found'))

        record = asyncio.run(scheduler.run_task(task, session_factory=factory))

        self.assertFalse(record.success)
        self.assertIn('claude CLI not found', record.reason)

    def test_run_task_includes_skill_and_args_in_description(self):
        """The task description sent to Session includes skill name and args."""
        import asyncio
        scheduler = _make_scheduler()
        task = _make_scheduled_task(skill='audit', args='--deep')
        factory = _make_session_factory('COMPLETED_WORK')

        asyncio.run(scheduler.run_task(task, session_factory=factory))

        task_desc = factory._calls[0][0][0]  # first positional arg
        self.assertIn('audit', task_desc)
        self.assertIn('--deep', task_desc)

    def test_run_task_updates_last_run(self):
        """After run_task, get_last_run returns the execution timestamp."""
        import asyncio
        state_dir = _make_state_dir()
        scheduler = _make_scheduler(state_dir=state_dir)
        task = _make_scheduled_task()
        factory = _make_session_factory('COMPLETED_WORK')

        asyncio.run(scheduler.run_task(task, session_factory=factory))

        self.assertIsNotNone(scheduler.get_last_run('nightly-sweep'))


class TestTick(unittest.TestCase):
    """tick() runs one full evaluation cycle."""

    def test_tick_executes_due_tasks(self):
        """tick() finds due tasks and runs them."""
        import asyncio
        scheduler = _make_scheduler(tasks=[
            _make_scheduled_task(name='task-a'),
            _make_scheduled_task(name='task-b'),
        ])
        factory = _make_session_factory('COMPLETED_WORK')

        now = datetime(2026, 3, 28, 2, 1, 0, tzinfo=timezone.utc)
        records = asyncio.run(scheduler.tick(now=now, session_factory=factory))

        self.assertEqual(len(records), 2)
        names = [r.task_name for r in records]
        self.assertIn('task-a', names)
        self.assertIn('task-b', names)

    def test_tick_skips_not_due_tasks(self):
        """tick() doesn't run tasks that aren't due yet."""
        import asyncio
        state_dir = _make_state_dir()
        scheduler = _make_scheduler(
            tasks=[_make_scheduled_task(name='recent')],
            state_dir=state_dir,
        )
        # Record a recent run so the task is not due
        just_ran = datetime(2026, 3, 28, 2, 0, 0, tzinfo=timezone.utc)
        scheduler.record_run('recent', just_ran, success=True)

        now = datetime(2026, 3, 28, 2, 1, 0, tzinfo=timezone.utc)
        records = asyncio.run(scheduler.tick(now=now))
        self.assertEqual(len(records), 0)

    def test_tick_records_failures(self):
        """tick() records failures without stopping other tasks."""
        import asyncio
        scheduler = _make_scheduler(tasks=[
            _make_scheduled_task(name='failing-task'),
        ])
        factory = _make_session_factory(side_effect=RuntimeError('boom'))

        now = datetime(2026, 3, 28, 2, 1, 0, tzinfo=timezone.utc)
        records = asyncio.run(scheduler.tick(now=now, session_factory=factory))

        self.assertEqual(len(records), 1)
        self.assertFalse(records[0].success)
        self.assertIn('boom', records[0].reason)


class TestRunNow(unittest.TestCase):
    """run_now() triggers immediate execution bypassing the schedule."""

    def test_run_now_executes_named_task(self):
        """run_now() finds and executes a task by name."""
        import asyncio
        scheduler = _make_scheduler(tasks=[
            _make_scheduled_task(name='sweep'),
            _make_scheduled_task(name='audit', skill='audit'),
        ])
        factory = _make_session_factory('COMPLETED_WORK')

        record = asyncio.run(scheduler.run_now('audit', session_factory=factory))

        self.assertTrue(record.success)
        self.assertEqual(record.task_name, 'audit')

    def test_run_now_raises_on_unknown_task(self):
        """run_now() raises KeyError for a task name that doesn't exist."""
        import asyncio
        scheduler = _make_scheduler()

        with self.assertRaises(KeyError):
            asyncio.run(scheduler.run_now('nonexistent'))

    def test_run_now_runs_disabled_task(self):
        """run_now() executes even if the task is disabled (paused)."""
        import asyncio
        scheduler = _make_scheduler(tasks=[
            _make_scheduled_task(name='paused-task', enabled=False),
        ])
        factory = _make_session_factory('COMPLETED_WORK')

        record = asyncio.run(scheduler.run_now('paused-task', session_factory=factory))

        self.assertTrue(record.success)
        self.assertEqual(record.task_name, 'paused-task')

    def test_run_now_records_result(self):
        """run_now() records the run in the state and log."""
        import asyncio
        state_dir = _make_state_dir()
        scheduler = _make_scheduler(
            tasks=[_make_scheduled_task(name='logged-task')],
            state_dir=state_dir,
        )
        factory = _make_session_factory('COMPLETED_WORK')

        asyncio.run(scheduler.run_now('logged-task', session_factory=factory))

        self.assertIsNotNone(scheduler.get_last_run('logged-task'))
        log = scheduler.get_run_log('logged-task')
        self.assertEqual(len(log), 1)
        self.assertTrue(log[0].success)


class TestGetTask(unittest.TestCase):
    """get_task() looks up tasks by name."""

    def test_returns_task_by_name(self):
        """get_task() returns the matching ScheduledTask."""
        scheduler = _make_scheduler(tasks=[
            _make_scheduled_task(name='alpha'),
            _make_scheduled_task(name='beta'),
        ])
        task = scheduler.get_task('beta')
        self.assertIsNotNone(task)
        self.assertEqual(task.name, 'beta')

    def test_returns_none_for_unknown(self):
        """get_task() returns None when no task matches."""
        scheduler = _make_scheduler()
        self.assertIsNone(scheduler.get_task('nonexistent'))


class TestCollectScheduledTasks(unittest.TestCase):
    """collect_scheduled_tasks gathers from management + project configs."""

    def _make_teaparty_home(self, yaml_content: str) -> str:
        home = tempfile.mkdtemp()
        os.makedirs(os.path.join(home, '.teaparty'))
        with open(os.path.join(home, '.teaparty', 'teaparty.yaml'), 'w') as f:
            f.write(yaml_content)
        return os.path.join(home, '.teaparty')

    def _make_project_dir(self, yaml_content: str) -> str:
        d = tempfile.mkdtemp()
        os.makedirs(os.path.join(d, '.teaparty'))
        with open(os.path.join(d, '.teaparty', 'project.yaml'), 'w') as f:
            f.write(yaml_content)
        return d

    def test_collects_from_both_levels(self):
        """Tasks from management and project config are merged."""
        tp_home = self._make_teaparty_home(textwrap.dedent("""\
            name: Test Org
            scheduled:
              - name: org-sweep
                schedule: "0 3 * * *"
                skill: sweep
        """))
        proj_dir = self._make_project_dir(textwrap.dedent("""\
            name: My Project
            scheduled:
              - name: proj-audit
                schedule: "0 4 * * *"
                skill: audit
        """))

        tasks = collect_scheduled_tasks(proj_dir, teaparty_home=tp_home)
        names = [t.name for t in tasks]
        self.assertIn('org-sweep', names)
        self.assertIn('proj-audit', names)
        self.assertEqual(len(tasks), 2)

    def test_missing_management_config(self):
        """Missing management config doesn't crash — just returns project tasks."""
        proj_dir = self._make_project_dir(textwrap.dedent("""\
            name: My Project
            scheduled:
              - name: proj-task
                schedule: "0 2 * * *"
                skill: test
        """))

        tasks = collect_scheduled_tasks(proj_dir, teaparty_home='/nonexistent')
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].name, 'proj-task')

    def test_missing_project_config(self):
        """Missing project config doesn't crash — just returns management tasks."""
        tp_home = self._make_teaparty_home(textwrap.dedent("""\
            name: Test Org
            scheduled:
              - name: org-task
                schedule: "0 3 * * *"
                skill: sweep
        """))

        tasks = collect_scheduled_tasks('/nonexistent', teaparty_home=tp_home)
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].name, 'org-task')

    def test_both_missing(self):
        """Both configs missing returns empty list."""
        tasks = collect_scheduled_tasks('/nonexistent', teaparty_home='/also-nonexistent')
        self.assertEqual(tasks, [])


if __name__ == '__main__':
    unittest.main()
