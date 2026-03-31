#!/usr/bin/env python3
"""Tests for ClaudeRunner._build_args.

Covers:
 1. __POC_DIR__ placeholder is replaced with the SCRIPT_DIR env var
 2. __SESSION_DIR__ placeholder is replaced with the POC_SESSION_DIR env var
 3. An unknown placeholder (no matching env var) is left as-is
 4. --permission-mode is always present in the CLI args, including when value is 'default'
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.claude_runner import ClaudeRunner


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


class TestPlaceholderSubstitution(unittest.TestCase):
    """__POC_DIR__ and __SESSION_DIR__ are substituted from env_vars."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_agents_file(self, content: str) -> str:
        path = os.path.join(self.tmpdir, 'agents.json')
        Path(path).write_text(content)
        return path

    def _get_agents_arg(self, runner: ClaudeRunner) -> str:
        args = runner._build_args(None)
        idx = args.index('--agents')
        return args[idx + 1]

    def test_poc_dir_placeholder_replaced(self):
        """__POC_DIR__ is replaced with the value of SCRIPT_DIR."""
        agents_content = json.dumps({
            'agent': {'prompt': 'Run __POC_DIR__/dispatch.sh'}
        })
        agents_file = self._write_agents_file(agents_content)
        runner = _make_runner(
            agents_file=agents_file,
            env_vars={'SCRIPT_DIR': '/opt/poc'},
        )
        result = self._get_agents_arg(runner)
        self.assertIn('/opt/poc/dispatch.sh', result)
        self.assertNotIn('__POC_DIR__', result)

    def test_session_dir_placeholder_replaced(self):
        """__SESSION_DIR__ is replaced with the value of POC_SESSION_DIR."""
        agents_content = json.dumps({
            'agent': {'prompt': 'Work in __SESSION_DIR__/output'}
        })
        agents_file = self._write_agents_file(agents_content)
        runner = _make_runner(
            agents_file=agents_file,
            env_vars={'POC_SESSION_DIR': '/sessions/abc123'},
        )
        result = self._get_agents_arg(runner)
        self.assertIn('/sessions/abc123/output', result)
        self.assertNotIn('__SESSION_DIR__', result)

    def test_both_placeholders_replaced(self):
        """Both __POC_DIR__ and __SESSION_DIR__ are substituted in one pass."""
        agents_content = json.dumps({
            'agent': {'prompt': 'cd __SESSION_DIR__ && __POC_DIR__/run.sh'}
        })
        agents_file = self._write_agents_file(agents_content)
        runner = _make_runner(
            agents_file=agents_file,
            env_vars={
                'SCRIPT_DIR': '/opt/poc',
                'POC_SESSION_DIR': '/sessions/xyz',
            },
        )
        result = self._get_agents_arg(runner)
        self.assertIn('/opt/poc/run.sh', result)
        self.assertIn('/sessions/xyz', result)
        self.assertNotIn('__POC_DIR__', result)
        self.assertNotIn('__SESSION_DIR__', result)

    def test_unknown_placeholder_left_as_is(self):
        """A placeholder with no matching env var is passed through unchanged."""
        agents_content = json.dumps({
            'agent': {'prompt': 'Use __UNKNOWN_VAR__ here'}
        })
        agents_file = self._write_agents_file(agents_content)
        runner = _make_runner(
            agents_file=agents_file,
            env_vars={},  # no SCRIPT_DIR, no POC_SESSION_DIR
        )
        result = self._get_agents_arg(runner)
        self.assertIn('__UNKNOWN_VAR__', result,
                      "Unknown placeholders must not be corrupted or removed")

    def test_poc_dir_placeholder_left_when_script_dir_missing(self):
        """__POC_DIR__ is not replaced when SCRIPT_DIR is absent from env_vars."""
        agents_content = json.dumps({
            'agent': {'prompt': 'Run __POC_DIR__/dispatch.sh'}
        })
        agents_file = self._write_agents_file(agents_content)
        runner = _make_runner(
            agents_file=agents_file,
            env_vars={'POC_SESSION_DIR': '/sessions/abc'},  # no SCRIPT_DIR
        )
        result = self._get_agents_arg(runner)
        self.assertIn('__POC_DIR__', result,
                      "__POC_DIR__ must remain if SCRIPT_DIR is not set")

    def test_session_dir_placeholder_left_when_env_missing(self):
        """__SESSION_DIR__ is not replaced when POC_SESSION_DIR is absent."""
        agents_content = json.dumps({
            'agent': {'prompt': 'Work in __SESSION_DIR__'}
        })
        agents_file = self._write_agents_file(agents_content)
        runner = _make_runner(
            agents_file=agents_file,
            env_vars={'SCRIPT_DIR': '/opt/poc'},  # no POC_SESSION_DIR
        )
        result = self._get_agents_arg(runner)
        self.assertIn('__SESSION_DIR__', result,
                      "__SESSION_DIR__ must remain if POC_SESSION_DIR is not set")

    def test_no_agents_file_no_agents_arg(self):
        """Without an agents_file, --agents is not added to the CLI args."""
        runner = _make_runner(agents_file=None)
        args = runner._build_args(None)
        self.assertNotIn('--agents', args)


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


class TestBareFlag(unittest.TestCase):
    """_build_args must pass --bare for skill scope suppression (Issue #344)."""

    def _get_args(self) -> list[str]:
        runner = _make_runner()
        return runner._build_args(None)

    def test_bare_flag_present(self):
        """--bare must appear in the CLI args to suppress skill auto-discovery."""
        args = self._get_args()
        self.assertIn('--bare', args)

    def test_setting_sources_not_present(self):
        """--setting-sources must not appear — it controls settings files, not skills."""
        args = self._get_args()
        self.assertNotIn('--setting-sources', args)


class TestClaudeResultDataclass(unittest.TestCase):
    """ClaudeResult dataclass — default values and had_errors property."""

    def test_stderr_lines_default_empty(self):
        """ClaudeResult defaults to empty stderr_lines."""
        from orchestrator.claude_runner import ClaudeResult
        r = ClaudeResult(exit_code=0)
        self.assertEqual(r.stderr_lines, [])
        self.assertFalse(r.had_errors)

    def test_stderr_lines_populated(self):
        """ClaudeResult carries stderr_lines when set."""
        from orchestrator.claude_runner import ClaudeResult
        r = ClaudeResult(exit_code=1, stderr_lines=['error: something broke'])
        self.assertEqual(r.stderr_lines, ['error: something broke'])
        self.assertTrue(r.had_errors)

    def test_had_errors_false_for_empty(self):
        """had_errors is False when stderr_lines is explicitly empty."""
        from orchestrator.claude_runner import ClaudeResult
        r = ClaudeResult(exit_code=0, stderr_lines=[])
        self.assertFalse(r.had_errors)

    def test_had_errors_true_for_multiple_lines(self):
        """had_errors is True when there are multiple stderr lines."""
        from orchestrator.claude_runner import ClaudeResult
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
        from orchestrator.events import EventBus, EventType

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
        from orchestrator.events import EventBus, EventType

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
        from orchestrator.events import EventBus, EventType

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
