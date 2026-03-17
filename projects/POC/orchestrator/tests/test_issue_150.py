#!/usr/bin/env python3
"""Tests for Issue #150: Agents burn cycles on filepath errors.

Root cause: agents receive absolute paths outside their worktree via
--add-dir flags and settings env vars, causing them to write files to
wrong locations.

Covers:
 1. _build_add_dirs() must return an empty list (no --add-dir flags)
 2. AgentRunner must not inject env_vars into settings env
 3. ClaudeRunner still receives env_vars for subprocess environment
 4. Env vars with absolute paths must not appear in settings
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import field as dataclass_field

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_orchestrator():
    """Build a minimal Orchestrator for testing _build_add_dirs."""
    from projects.POC.orchestrator.engine import Orchestrator

    orch = Orchestrator.__new__(Orchestrator)
    orch.session_worktree = '/tmp/worktree'
    orch.project_workdir = '/tmp/project'
    orch.infra_dir = '/tmp/infra'
    return orch


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestNoAddDirs(unittest.TestCase):
    """_build_add_dirs must return an empty list."""

    def test_build_add_dirs_returns_empty(self):
        """No --add-dir flags should be passed to agents."""
        orch = _make_orchestrator()
        dirs = orch._build_add_dirs()
        self.assertEqual(dirs, [],
                         '_build_add_dirs must return empty list — '
                         'agents should not receive --add-dir flags')


class TestNoEnvVarsInSettings(unittest.TestCase):
    """AgentRunner must not inject env_vars into the Claude settings env."""

    def test_settings_env_has_no_absolute_paths(self):
        """The settings dict passed to ClaudeRunner must not contain env vars
        with absolute paths that could leak into the agent's context."""
        from projects.POC.orchestrator.actors import AgentRunner, ActorContext
        from projects.POC.orchestrator.phase_config import PhaseSpec

        spec = PhaseSpec(
            name='intent',
            agent_file='agents/intent-team.json',
            lead='intent-lead',
            permission_mode='plan',
            stream_file='intent-stream.jsonl',
            artifact='INTENT.md',
            approval_state='INTENT_ASSERT',
            settings_overlay={},
        )

        ctx = ActorContext(
            state='PROPOSAL',
            phase='intent',
            task='test task',
            infra_dir='/tmp/infra',
            project_workdir='/tmp/project',
            session_worktree='/tmp/worktree',
            stream_file='intent-stream.jsonl',
            phase_spec=spec,
            poc_root='/tmp/poc',
            event_bus=MagicMock(),
            session_id='test-session',
            env_vars={
                'POC_PROJECT': 'test',
                'POC_PROJECT_DIR': '/tmp/project',
                'POC_SESSION_DIR': '/tmp/infra',
                'POC_SESSION_WORKTREE': '/tmp/worktree',
                'SCRIPT_DIR': '/tmp/poc',
                'PROJECTS_DIR': '/tmp',
            },
            add_dirs=[],
        )

        # Capture the settings dict that would be passed to ClaudeRunner
        captured_settings = {}
        original_init = None

        with patch('projects.POC.orchestrator.actors.ClaudeRunner') as MockRunner:
            mock_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.exit_code = 0
            mock_result.stall_killed = False
            mock_result.session_id = ''
            mock_result.stream_file = ''
            mock_result.stderr_lines = []

            async def fake_run():
                return mock_result
            mock_instance.run = fake_run
            MockRunner.return_value = mock_instance

            def capture_init(**kwargs):
                captured_settings.update(kwargs.get('settings', {}))
                return mock_instance

            MockRunner.side_effect = capture_init

            import asyncio
            runner = AgentRunner()
            try:
                asyncio.run(runner.run(ctx))
            except Exception:
                pass  # We only care about what settings were passed

            # The settings must not contain an 'env' key with absolute paths
            settings_env = captured_settings.get('env', {})
            for key, val in settings_env.items():
                if isinstance(val, str) and val.startswith('/'):
                    self.fail(
                        f'Settings env contains absolute path: {key}={val}. '
                        f'Absolute paths in settings leak into agent context '
                        f'and cause agents to write to wrong locations.'
                    )


class TestWorktreeJailHookWired(unittest.TestCase):
    """AgentRunner must inject worktree jail hooks into settings."""

    def test_settings_contain_jail_hooks(self):
        """Settings must have PreToolUse hooks for Read, Edit, Write."""
        from projects.POC.orchestrator.actors import AgentRunner, ActorContext
        from projects.POC.orchestrator.phase_config import PhaseSpec

        spec = PhaseSpec(
            name='intent',
            agent_file='agents/intent-team.json',
            lead='intent-lead',
            permission_mode='plan',
            stream_file='intent-stream.jsonl',
            artifact='INTENT.md',
            approval_state='INTENT_ASSERT',
            settings_overlay={},
        )

        ctx = ActorContext(
            state='PROPOSAL',
            phase='intent',
            task='test task',
            infra_dir='/tmp/infra',
            project_workdir='/tmp/project',
            session_worktree='/tmp/worktree',
            stream_file='intent-stream.jsonl',
            phase_spec=spec,
            poc_root='/tmp/poc',
            event_bus=MagicMock(),
            session_id='test-session',
            env_vars={},
            add_dirs=[],
        )

        captured_settings = {}

        with patch('projects.POC.orchestrator.actors.ClaudeRunner') as MockRunner:
            mock_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.exit_code = 0
            mock_result.stall_killed = False
            mock_result.session_id = ''
            mock_result.stream_file = ''
            mock_result.stderr_lines = []

            async def fake_run():
                return mock_result
            mock_instance.run = fake_run

            def capture_init(**kwargs):
                captured_settings.update(kwargs.get('settings', {}))
                return mock_instance
            MockRunner.side_effect = capture_init

            import asyncio
            runner = AgentRunner()
            try:
                asyncio.run(runner.run(ctx))
            except Exception:
                pass

        hooks = captured_settings.get('hooks', [])
        hook_tools = set()
        for hook in hooks:
            if hook.get('event') == 'PreToolUse':
                for m in hook.get('matchers', []):
                    hook_tools.add(m.get('tool'))

        for tool in ('Read', 'Edit', 'Write', 'Glob', 'Grep'):
            self.assertIn(tool, hook_tools,
                          f'Missing PreToolUse jail hook for {tool}')

    def test_jail_hook_uses_relative_path(self):
        """Jail hook command must not contain absolute paths."""
        from projects.POC.orchestrator.actors import AgentRunner, ActorContext
        from projects.POC.orchestrator.phase_config import PhaseSpec

        spec = PhaseSpec(
            name='intent',
            agent_file='agents/intent-team.json',
            lead='intent-lead',
            permission_mode='plan',
            stream_file='intent-stream.jsonl',
            artifact='INTENT.md',
            approval_state='INTENT_ASSERT',
            settings_overlay={},
        )

        ctx = ActorContext(
            state='PROPOSAL', phase='intent', task='test',
            infra_dir='/tmp/infra', project_workdir='/tmp/project',
            session_worktree='/tmp/worktree', stream_file='intent-stream.jsonl',
            phase_spec=spec, poc_root='/tmp/poc', event_bus=MagicMock(),
            session_id='test', env_vars={}, add_dirs=[],
        )

        captured_settings = {}

        with patch('projects.POC.orchestrator.actors.ClaudeRunner') as MockRunner:
            mock_instance = MagicMock()
            mock_result = MagicMock()
            mock_result.exit_code = 0
            mock_result.stall_killed = False
            mock_result.session_id = ''
            mock_result.stream_file = ''
            mock_result.stderr_lines = []

            async def fake_run():
                return mock_result
            mock_instance.run = fake_run

            def capture_init(**kwargs):
                captured_settings.update(kwargs.get('settings', {}))
                return mock_instance
            MockRunner.side_effect = capture_init

            import asyncio
            runner = AgentRunner()
            try:
                asyncio.run(runner.run(ctx))
            except Exception:
                pass

        for hook in captured_settings.get('hooks', []):
            cmd = hook.get('handler', {}).get('command', '')
            # The command should not contain absolute paths
            parts = cmd.split()
            for part in parts[1:]:  # skip 'python3'
                self.assertFalse(
                    part.startswith('/'),
                    f'Hook command contains absolute path: {cmd}',
                )


class TestSubprocessEnvStillHasVars(unittest.TestCase):
    """ClaudeRunner must still receive env_vars for subprocess environment."""

    def test_claude_runner_receives_env_vars(self):
        """env_vars must still be passed to ClaudeRunner for subprocess env."""
        from projects.POC.orchestrator.claude_runner import ClaudeRunner

        env_vars = {
            'POC_SESSION_DIR': '/tmp/infra',
            'POC_SESSION_WORKTREE': '/tmp/worktree',
        }

        runner = ClaudeRunner(
            prompt='test',
            cwd='/tmp/worktree',
            stream_file='/tmp/stream.jsonl',
            env_vars=env_vars,
        )

        env = runner._build_env()
        self.assertEqual(env['POC_SESSION_DIR'], '/tmp/infra')
        self.assertEqual(env['POC_SESSION_WORKTREE'], '/tmp/worktree')


class TestWorktreeHook(unittest.TestCase):
    """PreToolUse hook must restrict file access to the worktree."""

    def setUp(self):
        self.worktree = '/Users/darrell/git/teaparty-issue-42'

    def _check(self, tool_name, target_path, param='file_path'):
        from projects.POC.orchestrator.worktree_hook import _check
        with patch('os.getcwd', return_value=self.worktree):
            return _check(tool_name, {param: target_path})

    def test_relative_path_allowed(self):
        """Relative paths are always allowed — they resolve within worktree."""
        result = self._check('Write', 'projects/POC/orchestrator/session.py')
        self.assertTrue(result['allowed'])

    def test_relative_dotslash_allowed(self):
        result = self._check('Edit', './README.md')
        self.assertTrue(result['allowed'])

    def test_absolute_outside_worktree_blocked(self):
        """Absolute path to different project is blocked with generic message."""
        result = self._check('Write', '/Users/darrell/git/teaparty/projects/foo/bar.py')
        self.assertFalse(result['allowed'])
        self.assertEqual(result['reason'], 'You are restricted to files in your worktree')

    def test_absolute_outside_worktree_no_path_leak(self):
        """Rejection message must not reveal the worktree path."""
        result = self._check('Write', '/tmp/other/file.txt')
        self.assertNotIn(self.worktree, result['reason'])
        self.assertNotIn('/tmp', result['reason'])

    def test_absolute_to_own_worktree_suggests_relative(self):
        """Absolute path to own worktree is blocked with relative path suggestion."""
        abs_path = self.worktree + '/projects/POC/orchestrator/session.py'
        result = self._check('Write', abs_path)
        self.assertFalse(result['allowed'])
        self.assertIn('projects/POC/orchestrator/session.py', result['reason'])
        self.assertIn('relative path', result['reason'])

    def test_absolute_to_own_worktree_suggests_instead(self):
        """All tools get the same 'instead' message for own-worktree absolute paths."""
        for tool in ('Read', 'Edit', 'Write'):
            result = self._check(tool, self.worktree + '/file.txt')
            self.assertIn('instead', result['reason'])

    def test_empty_file_path_allowed(self):
        """Missing or empty file_path is allowed (e.g. Glob patterns)."""
        result = self._check('Glob', '')
        self.assertTrue(result['allowed'])

    def test_no_file_path_key_allowed(self):
        """No file_path key is allowed."""
        from projects.POC.orchestrator.worktree_hook import _check
        with patch('os.getcwd', return_value=self.worktree):
            result = _check('Grep', {'pattern': 'foo'})
        self.assertTrue(result['allowed'])

    def test_worktree_root_itself_blocked(self):
        """Absolute path to worktree root itself is blocked with suggestion."""
        result = self._check('Read', self.worktree)
        self.assertFalse(result['allowed'])
        self.assertIn('relative path', result['reason'])

    # ── Glob/Grep path parameter ──

    def test_glob_absolute_outside_blocked(self):
        """Glob with absolute path outside worktree is blocked."""
        result = self._check('Glob', '/tmp/other/dir', param='path')
        self.assertFalse(result['allowed'])
        self.assertEqual(result['reason'], 'You are restricted to files in your worktree')

    def test_glob_absolute_own_worktree_suggests_relative(self):
        """Glob with absolute path to own worktree suggests relative."""
        result = self._check('Glob', self.worktree + '/projects/POC', param='path')
        self.assertFalse(result['allowed'])
        self.assertIn('projects/POC', result['reason'])

    def test_glob_relative_allowed(self):
        """Glob with relative path is allowed."""
        result = self._check('Glob', 'projects/POC', param='path')
        self.assertTrue(result['allowed'])

    def test_grep_absolute_outside_blocked(self):
        """Grep with absolute path outside worktree is blocked."""
        result = self._check('Grep', '/usr/local/src', param='path')
        self.assertFalse(result['allowed'])

    def test_grep_no_path_allowed(self):
        """Grep with no path (searches cwd) is allowed."""
        from projects.POC.orchestrator.worktree_hook import _check
        with patch('os.getcwd', return_value=self.worktree):
            result = _check('Grep', {'pattern': 'foo'})
        self.assertTrue(result['allowed'])


if __name__ == '__main__':
    unittest.main()
