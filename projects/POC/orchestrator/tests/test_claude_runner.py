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
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.claude_runner import ClaudeRunner


def _make_runner(
    agents_file: str | None = None,
    permission_mode: str = 'default',
    env_vars: dict | None = None,
) -> ClaudeRunner:
    return ClaudeRunner(
        prompt='test prompt',
        cwd='/tmp',
        stream_file='/tmp/stream.jsonl',
        agents_file=agents_file,
        permission_mode=permission_mode,
        env_vars=env_vars or {},
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


if __name__ == '__main__':
    unittest.main()
