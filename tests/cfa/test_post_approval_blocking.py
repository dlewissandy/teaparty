#!/usr/bin/env python3
"""Tests for issue #124: post-WORK_ASSERT cleanup must not block the event loop.

These tests define the DESIRED behavior:
  1. extract_learnings() must not starve the async event loop.
  2. SESSION_COMPLETED must fire before extraction begins, so the TUI can
     update immediately after WORK_ASSERT approval.
"""
import asyncio
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.messaging.bus import Event, EventBus, EventType
from teaparty.learning.extract import extract_learnings


def _run(coro):
    return asyncio.run(coro)


class TestExtractLearningsMustNotBlockEventLoop(unittest.TestCase):
    """extract_learnings() must yield control so concurrent tasks can run."""

    def test_concurrent_task_gets_ticks_during_extraction(self):
        """A concurrent coroutine must be able to run while extract_learnings executes.

        Currently fails because _run_summarize and _call_promote are sync
        functions that call subprocess.run(), blocking the event loop.
        """
        ticks = []

        async def monitor():
            while True:
                ticks.append(time.monotonic())
                await asyncio.sleep(0.01)

        async def run_test():
            ticks.clear()
            monitor_task = asyncio.create_task(monitor())

            # Let monitor establish a baseline
            await asyncio.sleep(0.05)
            self.assertGreater(len(ticks), 0)

            ticks_before = len(ticks)

            with patch('teaparty.learning.extract._run_summarize') as mock_sum, \
                 patch('teaparty.learning.extract._promote_team') as m1, \
                 patch('teaparty.learning.extract._promote_session') as m2, \
                 patch('teaparty.learning.extract._promote_project') as m3, \
                 patch('teaparty.learning.extract._promote_global') as m4, \
                 patch('teaparty.learning.extract._promote_prospective') as m5, \
                 patch('teaparty.learning.extract._promote_in_flight') as m6, \
                 patch('teaparty.learning.extract._promote_corrective') as m7:

                # Simulate blocking work (as production code does today)
                mock_sum.side_effect = lambda *a, **kw: time.sleep(0.15)
                for m in [m1, m2, m3, m4, m5, m6, m7]:
                    m.side_effect = lambda *a, **kw: time.sleep(0.05)

                await extract_learnings(
                    infra_dir='/tmp/test-infra',
                    project_dir='/tmp/test-project',
                    session_worktree='/tmp/test-worktree',
                    task='test task',
                    poc_root='/tmp/test-poc',
                )

            ticks_during = len(ticks) - ticks_before

            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass

            # The monitor MUST get ticks during extraction.
            # With ~0.8s of work at 10ms intervals, expect at least 10 ticks.
            self.assertGreaterEqual(
                ticks_during, 10,
                f'Monitor got only {ticks_during} ticks during extraction — '
                f'event loop is starved by blocking calls'
            )

        _run(run_test())


if __name__ == '__main__':
    unittest.main()
