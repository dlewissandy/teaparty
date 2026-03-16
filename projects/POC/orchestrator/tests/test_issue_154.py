#!/usr/bin/env python3
"""Tests for issue #154: Orchestrator task dies silently at approval gate.

The run_session() wrapper in launch.py swallows all exceptions with
`except Exception: pass` — no logging, no crash indicator. The run_resumed()
wrapper in drilldown.py logs Exception but doesn't catch BaseException
subclasses (CancelledError, KeyboardInterrupt).

These tests verify that:
  1. When session.run() raises Exception, a crash entry appears in session.log
  2. When session.run() raises Exception, a .crash file is written with traceback
  3. When session.run() raises CancelledError, it is logged before propagating
  4. The same guarantees hold for the resume path
"""
import asyncio
import os
import shutil
import sys
import tempfile
import traceback
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.events import EventBus, Event, EventType
from projects.POC.orchestrator.state_writer import StateWriter


def _run(coro):
    return asyncio.run(coro)


def _make_infra_dir(tmpdir):
    """Create a minimal infra_dir with a session.log."""
    infra = os.path.join(tmpdir, 'infra')
    os.makedirs(infra, exist_ok=True)
    return infra


async def _setup_state_writer(infra_dir):
    """Create and start a StateWriter, publish SESSION_STARTED so .running exists."""
    bus = EventBus()
    writer = StateWriter(infra_dir, bus)
    await writer.start()
    await bus.publish(Event(
        type=EventType.SESSION_STARTED,
        data={'task': 'test', 'session_id': 'test-session'},
        session_id='test-session',
    ))
    return bus, writer


# ── launch.py: run_session() exception handling ─────────────────────────


class TestRunSessionCrashLogging(unittest.TestCase):
    """run_session() must log crashes, not swallow them silently."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.infra_dir = _make_infra_dir(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_exception_writes_crash_file(self):
        """When session.run() raises Exception, a .crash file with traceback must be written."""
        bus, writer = _run(_setup_state_writer(self.infra_dir))

        async def simulate():
            from projects.POC.tui.screens.launch import _handle_session_crash
            try:
                raise RuntimeError('approval gate exploded')
            except Exception:
                _handle_session_crash(self.infra_dir)

        _run(simulate())
        _run(writer.stop())

        crash_path = os.path.join(self.infra_dir, '.crash')
        self.assertTrue(
            os.path.exists(crash_path),
            '.crash file must be written when session.run() raises Exception',
        )
        content = open(crash_path).read()
        self.assertIn('RuntimeError', content)
        self.assertIn('approval gate exploded', content)

    def test_exception_logs_to_session_log(self):
        """When session.run() raises Exception, a CRASH entry must appear in session.log."""
        bus, writer = _run(_setup_state_writer(self.infra_dir))

        async def simulate():
            from projects.POC.tui.screens.launch import _handle_session_crash
            try:
                raise RuntimeError('approval gate exploded')
            except Exception:
                _handle_session_crash(self.infra_dir)

        _run(simulate())
        _run(writer.stop())

        log_path = os.path.join(self.infra_dir, 'session.log')
        self.assertTrue(os.path.exists(log_path))
        content = open(log_path).read()
        self.assertIn('CRASH', content)
        self.assertIn('RuntimeError', content)

    def test_cancelled_error_writes_crash_file(self):
        """When session.run() raises CancelledError, crash file must still be written."""
        bus, writer = _run(_setup_state_writer(self.infra_dir))

        async def simulate():
            from projects.POC.tui.screens.launch import _handle_session_crash
            try:
                raise asyncio.CancelledError()
            except BaseException:
                _handle_session_crash(self.infra_dir)

        _run(simulate())
        _run(writer.stop())

        crash_path = os.path.join(self.infra_dir, '.crash')
        self.assertTrue(
            os.path.exists(crash_path),
            '.crash file must be written when session.run() raises CancelledError',
        )
        content = open(crash_path).read()
        self.assertIn('CancelledError', content)


# ── drilldown.py: run_resumed() exception handling ──────────────────────


class TestRunResumedCrashLogging(unittest.TestCase):
    """run_resumed() must handle BaseException, not just Exception."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.infra_dir = _make_infra_dir(self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_exception_writes_crash_file(self):
        """When resume raises Exception, a .crash file must be written."""
        bus, writer = _run(_setup_state_writer(self.infra_dir))

        async def simulate():
            from projects.POC.tui.screens.drilldown import _handle_session_crash
            try:
                raise FileNotFoundError('infra dir gone')
            except Exception:
                _handle_session_crash(self.infra_dir)

        _run(simulate())
        _run(writer.stop())

        crash_path = os.path.join(self.infra_dir, '.crash')
        self.assertTrue(
            os.path.exists(crash_path),
            '.crash file must be written when resume raises Exception',
        )
        content = open(crash_path).read()
        self.assertIn('FileNotFoundError', content)

    def test_cancelled_error_writes_crash_file(self):
        """When resume raises CancelledError, crash file must still be written."""
        bus, writer = _run(_setup_state_writer(self.infra_dir))

        async def simulate():
            from projects.POC.tui.screens.drilldown import _handle_session_crash
            try:
                raise asyncio.CancelledError()
            except BaseException:
                _handle_session_crash(self.infra_dir)

        _run(simulate())
        _run(writer.stop())

        crash_path = os.path.join(self.infra_dir, '.crash')
        self.assertTrue(
            os.path.exists(crash_path),
            '.crash file must be written when resume raises CancelledError',
        )


if __name__ == '__main__':
    unittest.main()
