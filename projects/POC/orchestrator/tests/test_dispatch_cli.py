#!/usr/bin/env python3
"""Tests for dispatch_cli.py — child CfA state creation and parent linkage.

Covers:
 1. dispatch() uses make_child_state (not make_initial_state) when parent is available
 2. Child CfA starts at INTENT, not IDEA
 3. Child inherits parent_id, team_id, depth from parent
 4. --cfa-parent-state arg takes priority over POC_CFA_STATE env var
 5. POC_CFA_STATE env var is used when --cfa-parent-state is not set
 6. Missing infra dir returns failed status without touching CfA state
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.dispatch_cli import dispatch
from projects.POC.scripts.cfa_state import (
    make_child_state,
    make_initial_state,
    load_state,
    save_state,
    transition,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _run(coro):
    """Run a coroutine synchronously for testing."""
    return asyncio.run(coro)


def _make_parent_state_file(tmpdir: str, task_id: str = 'uber-001') -> str:
    """Create a parent CfA state file at TASK (ready to dispatch) and return its path."""
    cfa = make_initial_state(task_id=task_id)
    cfa = transition(cfa, 'propose')
    cfa = transition(cfa, 'auto-approve')
    cfa = transition(cfa, 'plan')
    cfa = transition(cfa, 'auto-approve')
    cfa = transition(cfa, 'delegate')
    # cfa.state == 'TASK' — parent is at dispatch point
    path = os.path.join(tmpdir, '.cfa-state.json')
    save_state(cfa, path)
    return path


def _make_mock_orchestrator_result(terminal_state: str = 'COMPLETED_WORK') -> MagicMock:
    result = MagicMock()
    result.terminal_state = terminal_state
    result.escalation_type = ''
    result.backtrack_count = 0
    return result


def _make_mock_dispatch_info(infra_dir: str, dispatch_id: str = 'disp-001') -> dict:
    return {
        'worktree_path': '/tmp/worktree',
        'infra_dir': infra_dir,
        'dispatch_id': dispatch_id,
    }


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestDispatchUsesMakeChildState(unittest.TestCase):
    """dispatch() must use make_child_state, not make_initial_state."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.dispatch_infra = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        shutil.rmtree(self.dispatch_infra, ignore_errors=True)

    def _run_dispatch(self, parent_state_path: str) -> tuple[dict, str]:
        """Run dispatch with mocked internals; return (result, saved_cfa_path)."""
        saved_cfa_path = os.path.join(self.dispatch_infra, '.cfa-state.json')

        mock_result = _make_mock_orchestrator_result()
        mock_dispatch_info = _make_mock_dispatch_info(self.dispatch_infra)

        with patch('projects.POC.orchestrator.dispatch_cli.PhaseConfig') as mock_config_cls, \
             patch('projects.POC.orchestrator.dispatch_cli.create_dispatch_worktree',
                   new=AsyncMock(return_value=mock_dispatch_info)), \
             patch('projects.POC.orchestrator.dispatch_cli.cleanup_worktree',
                   new=AsyncMock()), \
             patch('projects.POC.orchestrator.dispatch_cli.squash_merge',
                   new=AsyncMock()), \
             patch('projects.POC.orchestrator.dispatch_cli.Orchestrator') as mock_orch_cls:

            mock_config = MagicMock()
            mock_config.max_dispatch_retries = 0
            mock_config_cls.return_value = mock_config

            mock_orch = MagicMock()
            mock_orch.run = AsyncMock(return_value=mock_result)
            mock_orch_cls.return_value = mock_orch

            env = {
                'POC_SESSION_DIR': self.tmpdir,
                'POC_SESSION_WORKTREE': self.tmpdir,
                'POC_PROJECT': 'test-project',
            }
            with patch.dict(os.environ, env, clear=False):
                result = _run(dispatch('coding', 'write tests', cfa_parent_state=parent_state_path))

        return result, saved_cfa_path

    def test_child_state_is_not_idea(self):
        """Child CfA state must start at INTENT, not IDEA."""
        parent_path = _make_parent_state_file(self.tmpdir)
        _, saved_cfa_path = self._run_dispatch(parent_path)

        child = load_state(saved_cfa_path)
        self.assertNotEqual(child.state, 'IDEA',
                            "Child must not start at IDEA — it skips intent phase")

    def test_child_state_starts_at_intent(self):
        """Child CfA state must start at INTENT (planning entry point)."""
        parent_path = _make_parent_state_file(self.tmpdir)
        _, saved_cfa_path = self._run_dispatch(parent_path)

        child = load_state(saved_cfa_path)
        self.assertEqual(child.state, 'INTENT')

    def test_child_parent_id_is_set(self):
        """parent_id must be set to the parent's task_id."""
        parent_path = _make_parent_state_file(self.tmpdir, task_id='uber-test-001')
        _, saved_cfa_path = self._run_dispatch(parent_path)

        child = load_state(saved_cfa_path)
        self.assertEqual(child.parent_id, 'uber-test-001')

    def test_child_team_id_is_set(self):
        """team_id must be set to the dispatched team name."""
        parent_path = _make_parent_state_file(self.tmpdir)
        _, saved_cfa_path = self._run_dispatch(parent_path)

        child = load_state(saved_cfa_path)
        self.assertEqual(child.team_id, 'coding')

    def test_child_depth_increments(self):
        """Child depth must be parent.depth + 1."""
        parent_path = _make_parent_state_file(self.tmpdir)
        parent = load_state(parent_path)
        expected_depth = parent.depth + 1

        _, saved_cfa_path = self._run_dispatch(parent_path)

        child = load_state(saved_cfa_path)
        self.assertEqual(child.depth, expected_depth)

    def test_child_depth_is_one_for_root_parent(self):
        """Root parent (depth=0) produces child with depth=1."""
        parent_path = _make_parent_state_file(self.tmpdir)
        _, saved_cfa_path = self._run_dispatch(parent_path)

        child = load_state(saved_cfa_path)
        self.assertEqual(child.depth, 1)

    def test_child_task_id_includes_dispatch_id(self):
        """Child task_id must include the dispatch_id for traceability."""
        parent_path = _make_parent_state_file(self.tmpdir)
        _, saved_cfa_path = self._run_dispatch(parent_path)

        child = load_state(saved_cfa_path)
        self.assertIn('disp-001', child.task_id)
        self.assertIn('coding', child.task_id)


class TestDispatchParentStateFallback(unittest.TestCase):
    """Parent state resolution: explicit arg > POC_CFA_STATE env > infra_dir default."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.dispatch_infra = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        shutil.rmtree(self.dispatch_infra, ignore_errors=True)

    def _run_dispatch_with_env(self, env_overrides: dict, cfa_parent_state: str = '') -> tuple[dict, str]:
        saved_cfa_path = os.path.join(self.dispatch_infra, '.cfa-state.json')
        mock_result = _make_mock_orchestrator_result()
        mock_dispatch_info = _make_mock_dispatch_info(self.dispatch_infra)

        with patch('projects.POC.orchestrator.dispatch_cli.PhaseConfig') as mock_config_cls, \
             patch('projects.POC.orchestrator.dispatch_cli.create_dispatch_worktree',
                   new=AsyncMock(return_value=mock_dispatch_info)), \
             patch('projects.POC.orchestrator.dispatch_cli.cleanup_worktree',
                   new=AsyncMock()), \
             patch('projects.POC.orchestrator.dispatch_cli.squash_merge',
                   new=AsyncMock()), \
             patch('projects.POC.orchestrator.dispatch_cli.Orchestrator') as mock_orch_cls:

            mock_config = MagicMock()
            mock_config.max_dispatch_retries = 0
            mock_config_cls.return_value = mock_config

            mock_orch = MagicMock()
            mock_orch.run = AsyncMock(return_value=mock_result)
            mock_orch_cls.return_value = mock_orch

            base_env = {
                'POC_SESSION_DIR': self.tmpdir,
                'POC_SESSION_WORKTREE': self.tmpdir,
                'POC_PROJECT': 'test-project',
            }
            base_env.update(env_overrides)

            # Remove keys with None values (to unset env vars)
            env_to_set = {k: v for k, v in base_env.items() if v is not None}
            env_to_remove = [k for k, v in base_env.items() if v is None]

            with patch.dict(os.environ, env_to_set, clear=False):
                for key in env_to_remove:
                    os.environ.pop(key, None)
                result = _run(dispatch('writing', 'write docs', cfa_parent_state=cfa_parent_state))

        return result, saved_cfa_path

    def test_explicit_cfa_parent_state_arg_is_used(self):
        """--cfa-parent-state arg (explicit path) takes priority."""
        # Write explicit parent state to a named file
        explicit_path = os.path.join(self.tmpdir, 'explicit-state.json')
        cfa = make_initial_state(task_id='explicit-parent')
        cfa = transition(cfa, 'propose')
        cfa = transition(cfa, 'auto-approve')
        cfa = transition(cfa, 'plan')
        cfa = transition(cfa, 'auto-approve')
        cfa = transition(cfa, 'delegate')
        save_state(cfa, explicit_path)

        # Write a different parent state where POC_CFA_STATE points
        env_state_path = os.path.join(self.tmpdir, 'env-state.json')
        env_cfa = make_initial_state(task_id='env-parent')
        env_cfa = transition(env_cfa, 'propose')
        env_cfa = transition(env_cfa, 'auto-approve')
        env_cfa = transition(env_cfa, 'plan')
        env_cfa = transition(env_cfa, 'auto-approve')
        env_cfa = transition(env_cfa, 'delegate')
        save_state(env_cfa, env_state_path)

        result, saved_cfa_path = self._run_dispatch_with_env(
            {'POC_CFA_STATE': env_state_path},
            cfa_parent_state=explicit_path,
        )

        child = load_state(saved_cfa_path)
        self.assertEqual(child.parent_id, 'explicit-parent',
                         "Explicit --cfa-parent-state should take priority over env var")

    def test_poc_cfa_state_env_var_is_used_as_fallback(self):
        """POC_CFA_STATE env var is used when no explicit path is given."""
        env_state_path = os.path.join(self.tmpdir, 'env-state.json')
        parent = make_initial_state(task_id='env-task-001')
        parent = transition(parent, 'propose')
        parent = transition(parent, 'auto-approve')
        parent = transition(parent, 'plan')
        parent = transition(parent, 'auto-approve')
        parent = transition(parent, 'delegate')
        save_state(parent, env_state_path)

        result, saved_cfa_path = self._run_dispatch_with_env(
            {'POC_CFA_STATE': env_state_path},
            cfa_parent_state='',
        )

        child = load_state(saved_cfa_path)
        self.assertEqual(child.parent_id, 'env-task-001')

    def test_default_infra_dir_cfa_state_is_used(self):
        """Falls back to <infra_dir>/.cfa-state.json when neither arg nor env var is set."""
        # Write parent state to the default location
        default_state_path = os.path.join(self.tmpdir, '.cfa-state.json')
        parent = make_initial_state(task_id='default-task-001')
        parent = transition(parent, 'propose')
        parent = transition(parent, 'auto-approve')
        parent = transition(parent, 'plan')
        parent = transition(parent, 'auto-approve')
        parent = transition(parent, 'delegate')
        save_state(parent, default_state_path)

        result, saved_cfa_path = self._run_dispatch_with_env(
            {'POC_CFA_STATE': None},  # Ensure env var is unset
            cfa_parent_state='',
        )

        child = load_state(saved_cfa_path)
        self.assertEqual(child.parent_id, 'default-task-001')

    def test_missing_infra_dir_returns_failed_status(self):
        """dispatch() returns failed status immediately when POC_SESSION_DIR is not set."""
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('POC_SESSION_DIR', None)
            result = _run(dispatch('coding', 'do something'))

        self.assertEqual(result['status'], 'failed')
        self.assertIn('POC_SESSION_DIR', result.get('reason', ''))

    def test_missing_parent_state_file_returns_failed_status(self):
        """dispatch() returns failed status when the parent CfA state file does not exist."""
        result, _ = self._run_dispatch_with_env(
            {},
            cfa_parent_state='/nonexistent/path/cfa-state.json',
        )
        self.assertEqual(result['status'], 'failed')
        self.assertIn('parent CfA state not found', result.get('reason', ''))


class TestDispatchReturnShape(unittest.TestCase):
    """dispatch() return dict must include expected keys."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.dispatch_infra = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        shutil.rmtree(self.dispatch_infra, ignore_errors=True)

    def _run_dispatch(self, terminal_state: str = 'COMPLETED_WORK') -> dict:
        parent_path = _make_parent_state_file(self.tmpdir)
        mock_result = _make_mock_orchestrator_result(terminal_state)
        mock_dispatch_info = _make_mock_dispatch_info(self.dispatch_infra)

        with patch('projects.POC.orchestrator.dispatch_cli.PhaseConfig') as mock_config_cls, \
             patch('projects.POC.orchestrator.dispatch_cli.create_dispatch_worktree',
                   new=AsyncMock(return_value=mock_dispatch_info)), \
             patch('projects.POC.orchestrator.dispatch_cli.cleanup_worktree',
                   new=AsyncMock()), \
             patch('projects.POC.orchestrator.dispatch_cli.squash_merge',
                   new=AsyncMock()), \
             patch('projects.POC.orchestrator.dispatch_cli.Orchestrator') as mock_orch_cls:

            mock_config = MagicMock()
            mock_config.max_dispatch_retries = 0
            mock_config_cls.return_value = mock_config

            mock_orch = MagicMock()
            mock_orch.run = AsyncMock(return_value=mock_result)
            mock_orch_cls.return_value = mock_orch

            env = {
                'POC_SESSION_DIR': self.tmpdir,
                'POC_SESSION_WORKTREE': self.tmpdir,
                'POC_PROJECT': 'test-project',
            }
            with patch.dict(os.environ, env, clear=False):
                result = _run(dispatch('coding', 'do work', cfa_parent_state=parent_path))

        return result

    def test_completed_dispatch_has_status_completed(self):
        result = self._run_dispatch('COMPLETED_WORK')
        self.assertEqual(result['status'], 'completed')

    def test_withdrawn_dispatch_has_status_failed(self):
        result = self._run_dispatch('WITHDRAWN')
        self.assertEqual(result['status'], 'failed')

    def test_result_includes_team(self):
        result = self._run_dispatch()
        self.assertEqual(result['team'], 'coding')

    def test_result_includes_task(self):
        result = self._run_dispatch()
        self.assertEqual(result['task'], 'do work')

    def test_result_includes_terminal_state(self):
        result = self._run_dispatch()
        self.assertIn('terminal_state', result)

    def test_result_includes_exit_reason(self):
        result = self._run_dispatch()
        self.assertIn('exit_reason', result)


if __name__ == '__main__':
    unittest.main()
