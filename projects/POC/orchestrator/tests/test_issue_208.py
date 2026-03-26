#!/usr/bin/env python3
"""Tests for issue #208: has_running_agents flag is write-only.

The has_running_agents flag in _stream_with_watchdog is set True on
task_started but never cleared.  This causes the stall timeout to
permanently jump to max(stall_timeout, 7200) once any background agent
starts — a stalled process after agents finish hangs for up to 2 hours.

Strategy: Mock time.time for fast clock advancement, mock asyncio.sleep
to yield without real delay, and mock _kill_process_tree to observe
whether the watchdog fires a stall kill within a bounded number of polls.
"""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

import projects.POC.orchestrator.claude_runner as cr_module
from projects.POC.orchestrator.claude_runner import ClaudeRunner

_real_sleep = asyncio.sleep


def _run(coro):
    return asyncio.run(coro)


def _make_runner(stall_timeout=1800) -> ClaudeRunner:
    return ClaudeRunner(
        prompt='test prompt',
        cwd='/tmp',
        stream_file='/tmp/stream.jsonl',
        stall_timeout=stall_timeout,
    )


def _event_line(subtype, task_id='task-1'):
    return json.dumps({'type': 'system', 'subtype': subtype, 'task_id': task_id})


def _setup_runner(stdout_lines, stall_timeout=5):
    """Build a runner with given stdout lines and a mock process."""
    runner = _make_runner(stall_timeout=stall_timeout)

    async def _async_stdout():
        for line in stdout_lines:
            yield line.encode() if isinstance(line, str) else line

    async def _async_empty():
        return
        yield

    proc = MagicMock()
    proc.returncode = None
    proc.stdout = _async_stdout()
    proc.stderr = _async_empty()
    proc.pid = 99999

    async def _wait():
        try:
            while proc.returncode is None:
                await _real_sleep(0.001)
        except asyncio.CancelledError:
            raise
        return proc.returncode

    proc.wait = _wait
    runner._process = proc

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.jsonl')
    tmp.close()
    runner.stream_file = tmp.name

    return runner


def _run_watchdog_test(runner, max_polls=5, advance_per_poll=31):
    """Run _stream_with_watchdog with fake clock, bounded poll count.

    After max_polls watchdog cycles without a stall kill, terminates the
    process normally.  Returns (kill_called, polls_at_kill).
    """
    clock = [1000.0]
    polls = [0]
    kill_called = [False]
    kill_poll = [None]

    def fake_time():
        return clock[0]

    def fake_kill(pid):
        kill_called[0] = True
        kill_poll[0] = polls[0]
        runner._process.returncode = -15

    async def fake_sleep(seconds):
        if seconds == 30:  # watchdog poll
            polls[0] += 1
            clock[0] += advance_per_poll
            # Terminate process normally after max_polls if no kill yet
            if polls[0] >= max_polls and not kill_called[0]:
                runner._process.returncode = 0
        await _real_sleep(0)

    with patch.object(cr_module.time, 'time', fake_time), \
         patch.object(cr_module.asyncio, 'sleep', fake_sleep), \
         patch.object(cr_module, '_kill_process_tree', fake_kill):
        _run(runner._stream_with_watchdog([]))

    return kill_called[0], kill_poll[0]


class TestAgentTrackingClearsOnCompletion(unittest.TestCase):
    """has_running_agents must be cleared when all background agents complete."""

    def test_single_agent_complete_restores_base_timeout(self):
        """After task_started then task_notification, stall timeout must
        revert to base value.  With stall_timeout=5 and 31s per poll,
        the watchdog should fire on the FIRST poll (31 >= 5).

        With the bug: has_running_agents stuck True, effective_timeout=7200,
        so 31s < 7200 and the watchdog does NOT fire within 5 polls."""
        runner = _setup_runner([
            _event_line('task_started', 'a'),
            _event_line('task_notification', 'a'),
        ], stall_timeout=5)

        kill_called, kill_poll = _run_watchdog_test(runner, max_polls=5)

        self.assertTrue(kill_called,
                        'Watchdog did not fire stall kill within 5 polls — '
                        'has_running_agents likely stuck True '
                        '(effective_timeout=7200 instead of 5)')
        self.assertEqual(kill_poll, 1,
                         'Stall kill should fire on first poll (31s > 5s)')

    def test_no_agents_baseline_still_fires(self):
        """Sanity check: without any agent events, the watchdog still fires
        at the base stall_timeout."""
        runner = _setup_runner([], stall_timeout=5)

        kill_called, kill_poll = _run_watchdog_test(runner, max_polls=5)

        self.assertTrue(kill_called)
        self.assertEqual(kill_poll, 1)


class TestMultipleAgentTracking(unittest.TestCase):
    """With multiple agents, extended timeout persists until the last completes."""

    def test_two_agents_one_completes_timeout_stays_extended(self):
        """When two agents start and only one completes, stall timeout
        must remain extended.  5 polls * 31s = 155s < 7200, so no kill."""
        runner = _setup_runner([
            _event_line('task_started', 'a'),
            _event_line('task_started', 'b'),
            _event_line('task_notification', 'a'),
            # Agent b still running
        ], stall_timeout=5)

        kill_called, _ = _run_watchdog_test(runner, max_polls=5)

        self.assertFalse(kill_called,
                         'Watchdog killed process while agent b was still running')

    def test_all_agents_complete_then_stall_kills(self):
        """After ALL agents complete, stall timeout reverts to base."""
        runner = _setup_runner([
            _event_line('task_started', 'a'),
            _event_line('task_started', 'b'),
            _event_line('task_notification', 'a'),
            _event_line('task_notification', 'b'),
        ], stall_timeout=5)

        kill_called, kill_poll = _run_watchdog_test(runner, max_polls=5)

        self.assertTrue(kill_called,
                        'Watchdog did not fire after all agents completed')
        self.assertEqual(kill_poll, 1)


class TestOrphanedNotification(unittest.TestCase):
    """Orphaned task_notification must not cause negative agent count."""

    def test_orphan_then_real_agent_no_premature_kill(self):
        """An orphaned notification followed by a real agent start must
        not cause premature stall kill.  If the orphan decrements to -1,
        then task_started increments to 0, reading as 'no agents' and
        causing kill at base timeout while an agent is actually running."""
        runner = _setup_runner([
            _event_line('task_notification', 'orphan'),
            _event_line('task_started', 'real'),
            # real agent still running
        ], stall_timeout=5)

        kill_called, _ = _run_watchdog_test(runner, max_polls=5)

        self.assertFalse(kill_called,
                         'Watchdog killed process while real agent was running — '
                         'orphaned notification likely caused negative count')


if __name__ == '__main__':
    unittest.main()
