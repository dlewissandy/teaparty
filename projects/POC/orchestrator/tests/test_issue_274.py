#!/usr/bin/env python3
"""Tests for Issue #274: Cron scheduler runtime driver.

Covers:
 1. CronDriver creates a scheduler from collect_scheduled_tasks
 2. tick() dispatches due tasks via the scheduler
 3. Overlapping ticks are rejected (guard against re-entrancy)
 4. Config errors at startup don't crash — driver starts with empty schedule
 5. TUI integration — app creates and starts the cron driver
"""
import asyncio
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.config_reader import ScheduledTask
from projects.POC.orchestrator.cron_scheduler import CronScheduler, RunRecord


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_scheduled_task(
    name: str = 'nightly-sweep',
    schedule: str = '0 2 * * *',
    skill: str = 'test-sweep',
    args: str = '',
    enabled: bool = True,
) -> ScheduledTask:
    return ScheduledTask(
        name=name, schedule=schedule, skill=skill,
        args=args, enabled=enabled,
    )


def _make_state_dir() -> str:
    return tempfile.mkdtemp()


def _make_scheduler(
    tasks: list[ScheduledTask] | None = None,
    state_dir: str | None = None,
) -> CronScheduler:
    if tasks is None:
        tasks = [_make_scheduled_task()]
    if state_dir is None:
        state_dir = _make_state_dir()
    return CronScheduler(
        tasks=tasks, state_dir=state_dir,
        project_dir='/tmp/fake-project', project_slug='test-project',
    )


def _make_session_factory(terminal_state='COMPLETED_WORK', side_effect=None):
    mock_session = AsyncMock()
    if side_effect:
        mock_session.run.side_effect = side_effect
    else:
        mock_result = type('R', (), {'terminal_state': terminal_state})()
        mock_session.run.return_value = mock_result
    return lambda *args, **kwargs: mock_session


# ── Tests ────────────────────────────────────────────────────────────────────

class TestCronDriverCreation(unittest.TestCase):
    """CronDriver creates a scheduler from config at startup."""

    def test_driver_creates_scheduler_from_tasks(self):
        """Driver wraps a CronScheduler with the provided tasks."""
        from projects.POC.orchestrator.cron_driver import CronDriver

        tasks = [_make_scheduled_task(name='a'), _make_scheduled_task(name='b')]
        driver = CronDriver(
            tasks=tasks,
            state_dir=_make_state_dir(),
            project_dir='/tmp/fake',
            project_slug='test',
        )
        self.assertIsInstance(driver.scheduler, CronScheduler)
        self.assertEqual(len(driver.scheduler.tasks), 2)

    def test_driver_with_empty_task_list(self):
        """Driver starts successfully with no scheduled tasks."""
        from projects.POC.orchestrator.cron_driver import CronDriver

        driver = CronDriver(
            tasks=[],
            state_dir=_make_state_dir(),
            project_dir='/tmp/fake',
            project_slug='test',
        )
        self.assertEqual(len(driver.scheduler.tasks), 0)


class TestCronDriverTick(unittest.TestCase):
    """Driver tick() dispatches due tasks."""

    def test_tick_runs_due_tasks(self):
        """tick() delegates to scheduler.tick() and returns records."""
        from projects.POC.orchestrator.cron_driver import CronDriver

        driver = CronDriver(
            tasks=[_make_scheduled_task()],
            state_dir=_make_state_dir(),
            project_dir='/tmp/fake',
            project_slug='test',
        )
        factory = _make_session_factory('COMPLETED_WORK')
        now = datetime(2026, 3, 28, 2, 1, 0, tzinfo=timezone.utc)

        records = asyncio.run(driver.tick(now=now, session_factory=factory))

        self.assertEqual(len(records), 1)
        self.assertTrue(records[0].success)

    def test_tick_returns_empty_when_nothing_due(self):
        """tick() returns empty list when no tasks are due."""
        from projects.POC.orchestrator.cron_driver import CronDriver

        state_dir = _make_state_dir()
        driver = CronDriver(
            tasks=[_make_scheduled_task()],
            state_dir=state_dir,
            project_dir='/tmp/fake',
            project_slug='test',
        )
        # Mark the task as recently run
        driver.scheduler.record_run(
            'nightly-sweep',
            datetime(2026, 3, 28, 2, 0, 0, tzinfo=timezone.utc),
            success=True,
        )
        now = datetime(2026, 3, 28, 2, 1, 0, tzinfo=timezone.utc)

        records = asyncio.run(driver.tick(now=now))
        self.assertEqual(len(records), 0)


class TestCronDriverReentrancyGuard(unittest.TestCase):
    """Overlapping ticks are rejected."""

    def test_concurrent_tick_is_rejected(self):
        """A second tick() while the first is running returns empty."""
        from projects.POC.orchestrator.cron_driver import CronDriver

        driver = CronDriver(
            tasks=[_make_scheduled_task()],
            state_dir=_make_state_dir(),
            project_dir='/tmp/fake',
            project_slug='test',
        )

        # Create a slow session factory that blocks
        gate = asyncio.Event()
        slow_session = AsyncMock()
        slow_result = type('R', (), {'terminal_state': 'COMPLETED_WORK'})()

        async def slow_run():
            await gate.wait()
            return slow_result
        slow_session.run = slow_run
        slow_factory = lambda *a, **kw: slow_session

        now = datetime(2026, 3, 28, 2, 1, 0, tzinfo=timezone.utc)

        async def run_test():
            # Start first tick (will block on gate)
            t1 = asyncio.create_task(driver.tick(now=now, session_factory=slow_factory))
            # Give t1 a moment to acquire the lock
            await asyncio.sleep(0.05)
            # Second tick should return empty (locked out)
            records2 = await driver.tick(now=now, session_factory=slow_factory)
            # Release the gate
            gate.set()
            records1 = await t1
            return records1, records2

        records1, records2 = asyncio.run(run_test())
        self.assertEqual(len(records1), 1)
        self.assertEqual(len(records2), 0)


class TestCronDriverFromConfig(unittest.TestCase):
    """Driver factory from_config creates from collect_scheduled_tasks."""

    @patch('projects.POC.orchestrator.cron_driver.collect_scheduled_tasks')
    def test_from_config_collects_tasks(self, mock_collect):
        """from_config uses collect_scheduled_tasks to build the driver."""
        from projects.POC.orchestrator.cron_driver import CronDriver

        mock_collect.return_value = [_make_scheduled_task(name='config-task')]

        driver = CronDriver.from_config(
            project_dir='/tmp/fake',
            project_slug='test',
        )
        mock_collect.assert_called_once()
        self.assertEqual(len(driver.scheduler.tasks), 1)
        self.assertEqual(driver.scheduler.tasks[0].name, 'config-task')

    @patch('projects.POC.orchestrator.cron_driver.collect_scheduled_tasks')
    def test_from_config_handles_errors_gracefully(self, mock_collect):
        """Config errors produce an empty-schedule driver, not a crash."""
        from projects.POC.orchestrator.cron_driver import CronDriver

        mock_collect.side_effect = Exception('bad YAML')

        driver = CronDriver.from_config(
            project_dir='/tmp/fake',
            project_slug='test',
        )
        self.assertEqual(len(driver.scheduler.tasks), 0)


class TestTUIIntegration(unittest.TestCase):
    """TUI app creates and drives the cron scheduler."""

    @patch('projects.POC.orchestrator.cron_driver.collect_scheduled_tasks')
    def test_app_creates_cron_driver(self, mock_collect):
        """TeaPartyTUI initializes a CronDriver at startup."""
        from projects.POC.orchestrator.cron_driver import CronDriver

        mock_collect.return_value = []
        from projects.POC.tui.app import TeaPartyTUI

        app = TeaPartyTUI()
        self.assertIsNotNone(app.cron_driver)
        self.assertIsInstance(app.cron_driver, CronDriver)

    def test_cron_tick_done_callback_logs_results(self):
        """_on_cron_tick_done logs success and failure records."""
        from projects.POC.orchestrator.cron_scheduler import RunRecord
        from projects.POC.tui.app import TeaPartyTUI

        now = datetime(2026, 3, 28, 2, 0, 0, tzinfo=timezone.utc)
        records = [
            RunRecord(task_name='ok-task', timestamp=now, success=True),
            RunRecord(task_name='bad-task', timestamp=now, success=False, reason='boom'),
        ]

        # Create a completed task with records as result
        loop = asyncio.new_event_loop()
        future = loop.create_future()
        future.set_result(records)

        with patch('projects.POC.tui.app._log') as mock_log:
            TeaPartyTUI._on_cron_tick_done(future)
            # Should log info for success, error for failure
            info_calls = [c for c in mock_log.info.call_args_list if 'ok-task' in str(c)]
            error_calls = [c for c in mock_log.error.call_args_list if 'bad-task' in str(c)]
            self.assertEqual(len(info_calls), 1)
            self.assertEqual(len(error_calls), 1)

        loop.close()

    def test_cron_tick_done_callback_logs_exceptions(self):
        """_on_cron_tick_done logs exceptions from tick()."""
        from projects.POC.tui.app import TeaPartyTUI

        loop = asyncio.new_event_loop()
        future = loop.create_future()
        future.set_exception(RuntimeError('event loop died'))

        with patch('projects.POC.tui.app._log') as mock_log:
            TeaPartyTUI._on_cron_tick_done(future)
            error_calls = [c for c in mock_log.error.call_args_list if 'event loop died' in str(c)]
            self.assertEqual(len(error_calls), 1)

        loop.close()


if __name__ == '__main__':
    unittest.main()
