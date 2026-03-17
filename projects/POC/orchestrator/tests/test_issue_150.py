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


if __name__ == '__main__':
    unittest.main()
