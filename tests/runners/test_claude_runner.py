#!/usr/bin/env python3
"""Tests for ClaudeRunner._build_args.

Covers:
 1. ``--agents`` is set when an agents_file is provided
 2. --permission-mode is always present in the CLI args, including when value is 'default'

Cut 22 deleted the ``__POC_DIR__`` / ``__SESSION_DIR__`` placeholder
substitution machinery — those placeholders had no real consumers in
agent JSON files; the tests here previously pinned that dead machinery
to itself.  Removed along with the substitution code.
"""
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.runners.claude import ClaudeRunner


def _make_runner(
    agents_file: str | None = None,
    permission_mode: str = 'default',
    env_vars: dict | None = None,
    event_bus=None,
) -> ClaudeRunner:
    return ClaudeRunner(
        prompt='test prompt',
        cwd='/tmp',
        stream_file='/tmp/stream.jsonl',
        agents_file=agents_file,
        permission_mode=permission_mode,
        env_vars=env_vars or {},
        event_bus=event_bus,
    )


class TestAgentsArg(unittest.TestCase):
    """``--agents`` is added only when agents_file is provided."""

    def test_no_agents_file_no_agents_arg(self):
        """Without an agents_file, --agents is not added to the CLI args."""
        runner = _make_runner(agents_file=None)
        args = runner._build_args(None)
        self.assertNotIn('--agents', args)

    def test_agents_file_contents_passed_verbatim(self):
        """When agents_file is set, its raw bytes go to --agents (no substitution)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'agents.json'
            path.write_text('{"agent": {"prompt": "do a thing"}}')
            runner = _make_runner(agents_file=str(path))
            args = runner._build_args(None)
            idx = args.index('--agents')
            self.assertEqual(
                args[idx + 1],
                '{"agent": {"prompt": "do a thing"}}',
            )


class TestPermissionModeAlwaysPresent(unittest.TestCase):
    """--permission-mode must always be in the CLI args."""

    def _get_args(self, permission_mode: str) -> list[str]:
        runner = _make_runner(permission_mode=permission_mode)
        return runner._build_args(None)

    def test_permission_mode_default_is_present(self):
        """--permission-mode default must be explicit even when value is 'default'."""
        args = self._get_args('default')
        self.assertIn('--permission-mode', args)
        idx = args.index('--permission-mode')
        self.assertEqual(args[idx + 1], 'default')

    def test_permission_mode_accept_edits_is_present(self):
        """--permission-mode acceptEdits is emitted."""
        args = self._get_args('acceptEdits')
        self.assertIn('--permission-mode', args)
        idx = args.index('--permission-mode')
        self.assertEqual(args[idx + 1], 'acceptEdits')

    def test_permission_mode_plan_is_present(self):
        """--permission-mode plan is emitted."""
        args = self._get_args('plan')
        self.assertIn('--permission-mode', args)
        idx = args.index('--permission-mode')
        self.assertEqual(args[idx + 1], 'plan')

    def test_permission_mode_dont_ask_is_present(self):
        """--permission-mode dontAsk is emitted."""
        args = self._get_args('dontAsk')
        self.assertIn('--permission-mode', args)
        idx = args.index('--permission-mode')
        self.assertEqual(args[idx + 1], 'dontAsk')


class TestClaudeResultDataclass(unittest.TestCase):
    """ClaudeResult dataclass — default values and had_errors property."""

    def test_stderr_lines_default_empty(self):
        """ClaudeResult defaults to empty stderr_lines."""
        from teaparty.runners.claude import ClaudeResult
        r = ClaudeResult(exit_code=0)
        self.assertEqual(r.stderr_lines, [])
        self.assertFalse(r.had_errors)

    def test_stderr_lines_populated(self):
        """ClaudeResult carries stderr_lines when set."""
        from teaparty.runners.claude import ClaudeResult
        r = ClaudeResult(exit_code=1, stderr_lines=['error: something broke'])
        self.assertEqual(r.stderr_lines, ['error: something broke'])
        self.assertTrue(r.had_errors)

    def test_had_errors_false_for_empty(self):
        """had_errors is False when stderr_lines is explicitly empty."""
        from teaparty.runners.claude import ClaudeResult
        r = ClaudeResult(exit_code=0, stderr_lines=[])
        self.assertFalse(r.had_errors)

    def test_had_errors_true_for_multiple_lines(self):
        """had_errors is True when there are multiple stderr lines."""
        from teaparty.runners.claude import ClaudeResult
        r = ClaudeResult(exit_code=0, stderr_lines=['line1', 'line2', 'line3'])
        self.assertTrue(r.had_errors)
        self.assertEqual(len(r.stderr_lines), 3)


def _run(coro):
    """Run a coroutine synchronously for testing."""
    import asyncio
    return asyncio.run(coro)


class TestStreamWithWatchdogStderr(unittest.TestCase):
    """_stream_with_watchdog collects stderr lines and publishes STREAM_ERROR events."""

    def _make_runner_with_fake_process(self, stdout_lines, stderr_lines, event_bus=None):
        """Build a ClaudeRunner whose _process is a mock with fake stdout/stderr."""
        import asyncio
        import io
        from unittest.mock import AsyncMock, MagicMock

        runner = _make_runner(event_bus=event_bus)

        # Build async iterators that yield encoded lines then stop
        async def _async_iter(lines):
            for line in lines:
                yield line.encode() if isinstance(line, str) else line

        proc = MagicMock()
        proc.returncode = None
        proc.stdout = _async_iter(stdout_lines)
        proc.stderr = _async_iter(stderr_lines)

        # Make proc.wait() set returncode=0 and return immediately
        async def _wait():
            proc.returncode = 0
            return 0

        proc.wait = _wait
        runner._process = proc

        # Write stream output to a temp file
        import tempfile
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.jsonl')
        tmp.close()
        runner.stream_file = tmp.name

        return runner

    def test_stderr_lines_collected(self):
        """stderr lines from the subprocess are collected into the list."""
        runner = self._make_runner_with_fake_process(
            stdout_lines=[],
            stderr_lines=['Error: tool execution failed', 'Warning: rate limited'],
        )
        stderr_lines = []
        _run(runner._stream_with_watchdog(stderr_lines))
        self.assertEqual(stderr_lines, ['Error: tool execution failed', 'Warning: rate limited'])

    def test_empty_stderr_lines_skipped(self):
        """Blank lines from stderr are not collected."""
        runner = self._make_runner_with_fake_process(
            stdout_lines=[],
            stderr_lines=['', 'real error', '', ''],
        )
        stderr_lines = []
        _run(runner._stream_with_watchdog(stderr_lines))
        self.assertEqual(stderr_lines, ['real error'])

    def test_stream_error_events_published(self):
        """Each stderr line causes a STREAM_ERROR event on the event bus."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from teaparty.messaging.bus import EventBus, EventType

        bus = MagicMock(spec=EventBus)
        published = []

        async def capture(event):
            published.append(event)

        bus.publish = capture

        runner = self._make_runner_with_fake_process(
            stdout_lines=[],
            stderr_lines=['fatal: API key invalid', 'Connection refused'],
            event_bus=bus,
        )
        runner.session_id = 'sess-abc'
        stderr_lines = []
        _run(runner._stream_with_watchdog(stderr_lines))

        stream_error_events = [e for e in published if e.type == EventType.STREAM_ERROR]
        self.assertEqual(len(stream_error_events), 2)

        lines_in_events = [e.data['line'] for e in stream_error_events]
        self.assertIn('fatal: API key invalid', lines_in_events)
        self.assertIn('Connection refused', lines_in_events)

    def test_stream_error_events_carry_session_id(self):
        """STREAM_ERROR events carry the runner's session_id."""
        from unittest.mock import MagicMock
        from teaparty.messaging.bus import EventBus, EventType

        bus = MagicMock(spec=EventBus)
        published = []

        async def capture(event):
            published.append(event)

        bus.publish = capture

        runner = self._make_runner_with_fake_process(
            stdout_lines=[],
            stderr_lines=['tool failed'],
            event_bus=bus,
        )
        runner.session_id = 'my-session-id'
        stderr_lines = []
        _run(runner._stream_with_watchdog(stderr_lines))

        error_events = [e for e in published if e.type == EventType.STREAM_ERROR]
        self.assertEqual(len(error_events), 1)
        self.assertEqual(error_events[0].session_id, 'my-session-id')

    def test_no_stream_error_events_when_no_stderr(self):
        """No STREAM_ERROR events are published when stderr is silent."""
        from unittest.mock import MagicMock
        from teaparty.messaging.bus import EventBus, EventType

        bus = MagicMock(spec=EventBus)
        published = []

        async def capture(event):
            published.append(event)

        bus.publish = capture

        runner = self._make_runner_with_fake_process(
            stdout_lines=[],
            stderr_lines=[],
            event_bus=bus,
        )
        stderr_lines = []
        _run(runner._stream_with_watchdog(stderr_lines))

        error_events = [e for e in published if e.type == EventType.STREAM_ERROR]
        self.assertEqual(error_events, [])


if __name__ == '__main__':
    unittest.main()
