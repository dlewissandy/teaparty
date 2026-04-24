#!/usr/bin/env python3
"""Tests for dispatch_cli.py — child CfA state creation and parent state resolution.

Covers:
 1. Child CfA starts at INTENT (parent/child linkage lives in .children registry)
 2. Child task_id has the form ``dispatch-{team}-{dispatch_id}``
 3. --cfa-parent-state arg takes priority over POC_CFA_STATE env var
 4. POC_CFA_STATE env var is used when --cfa-parent-state is not set
 5. Infra-dir default is used when neither arg nor env var is set
 6. Missing infra dir / parent state file returns failed status
 """
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.cfa.dispatch import dispatch
from teaparty.cfa.statemachine.cfa_state import (
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
    """Create a parent CfA state file at WORK_IN_PROGRESS (ready to dispatch) and return its path."""
    cfa = make_initial_state(task_id=task_id)
    cfa = transition(cfa, 'approve')  # INTENT → PLAN
    cfa = transition(cfa, 'approve')  # PLAN → EXECUTE
    # cfa.state == 'EXECUTE' — parent is at dispatch point
    path = os.path.join(tmpdir, '.cfa-state.json')
    save_state(cfa, path)
    return path


def _make_mock_orchestrator_result(terminal_state: str = 'DONE') -> MagicMock:
    result = MagicMock()
    result.terminal_state = terminal_state
    result.escalation_type = ''
    result.backtrack_count = 0
    return result


def _make_mock_dispatch_info(infra_dir: str, dispatch_id: str = 'disp-001') -> dict:
    return {
        'task_id': f'task-{dispatch_id}',
        'task_dir': infra_dir,
        'worktree_path': '/tmp/worktree',
        'branch_name': f'task-{dispatch_id}--mock',
    }


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestDispatchChildStateShape(unittest.TestCase):
    """Child CfA state written by dispatch() has the correct shape."""

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

        with patch('teaparty.cfa.dispatch.PhaseConfig') as mock_config_cls, \
             patch('teaparty.cfa.dispatch.create_task',
                   new=AsyncMock(return_value=mock_dispatch_info)), \
             patch('teaparty.cfa.dispatch.release_worktree',
                   new=AsyncMock()), \
             patch('teaparty.cfa.dispatch.squash_merge',
                   new=AsyncMock()), \
             patch('teaparty.cfa.dispatch.load_management_team',
                   side_effect=FileNotFoundError), \
             patch('teaparty.cfa.dispatch.load_project_team',
                   side_effect=FileNotFoundError), \
             patch('teaparty.cfa.dispatch.Orchestrator') as mock_orch_cls:

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

    def test_child_state_starts_at_intent(self):
        """Child CfA state must start at INTENT — the entry point for every CfA.

        Parent/child linkage is tracked via the ``.children`` registry, not
        by CfaState fields; CfaState itself carries no hierarchy info.
        """
        parent_path = _make_parent_state_file(self.tmpdir)
        _, saved_cfa_path = self._run_dispatch(parent_path)

        child = load_state(saved_cfa_path)
        self.assertEqual(child.state, 'INTENT')

    def test_child_task_id_includes_team_and_dispatch_id(self):
        """Child task_id must include the team name and a dispatch ID for traceability."""
        parent_path = _make_parent_state_file(self.tmpdir)
        _, saved_cfa_path = self._run_dispatch(parent_path)

        child = load_state(saved_cfa_path)
        self.assertIn('coding', child.task_id)
        # dispatch_id is a timestamp like 20260407-100036-829688
        self.assertRegex(child.task_id, r'dispatch-coding-\d{8}-\d{6}')


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

        with patch('teaparty.cfa.dispatch.PhaseConfig') as mock_config_cls, \
             patch('teaparty.cfa.dispatch.create_task',
                   new=AsyncMock(return_value=mock_dispatch_info)), \
             patch('teaparty.cfa.dispatch.release_worktree',
                   new=AsyncMock()), \
             patch('teaparty.cfa.dispatch.squash_merge',
                   new=AsyncMock()), \
             patch('teaparty.cfa.dispatch.load_management_team',
                   side_effect=FileNotFoundError), \
             patch('teaparty.cfa.dispatch.load_project_team',
                   side_effect=FileNotFoundError), \
             patch('teaparty.cfa.dispatch.Orchestrator') as mock_orch_cls:

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
        """--cfa-parent-state arg (explicit path) takes priority.

        Verified by: only the explicit path exists; env path and default
        path do NOT exist.  Dispatch succeeds, proving that the explicit
        path was the one consulted for existence.
        """
        # Explicit path exists
        explicit_path = os.path.join(self.tmpdir, 'explicit-state.json')
        save_state(make_initial_state(task_id='explicit-parent'), explicit_path)

        # Env path deliberately does NOT exist — if env had priority, dispatch fails
        env_state_path = os.path.join(self.tmpdir, 'does-not-exist.json')

        result, _ = self._run_dispatch_with_env(
            {'POC_CFA_STATE': env_state_path},
            cfa_parent_state=explicit_path,
        )

        self.assertNotEqual(
            result.get('status'), 'failed',
            f'Explicit arg should have been used; dispatch failed with: {result}',
        )

    def test_poc_cfa_state_env_var_is_used_as_fallback(self):
        """POC_CFA_STATE env var is used when no explicit path is given.

        Verified by: env path exists; infra-dir default does NOT.  If env
        lookup didn't happen, dispatch would fall through to the default
        and fail.
        """
        env_state_path = os.path.join(self.tmpdir, 'env-state.json')
        save_state(make_initial_state(task_id='env-task-001'), env_state_path)

        # Infra-dir default path deliberately NOT written

        result, _ = self._run_dispatch_with_env(
            {'POC_CFA_STATE': env_state_path},
            cfa_parent_state='',
        )
        self.assertNotEqual(
            result.get('status'), 'failed',
            f'Env fallback should have been used; dispatch failed with: {result}',
        )

    def test_default_infra_dir_cfa_state_is_used(self):
        """Falls back to <infra_dir>/.cfa-state.json when neither arg nor env var is set."""
        default_state_path = os.path.join(self.tmpdir, '.cfa-state.json')
        save_state(make_initial_state(task_id='default-task-001'), default_state_path)

        result, _ = self._run_dispatch_with_env(
            {'POC_CFA_STATE': None},  # Ensure env var is unset
            cfa_parent_state='',
        )
        self.assertNotEqual(
            result.get('status'), 'failed',
            f'Default path should have been used; dispatch failed with: {result}',
        )

    def test_missing_infra_dir_returns_failed_status(self):
        """dispatch() returns failed status immediately when POC_SESSION_DIR is not set."""
        with patch('teaparty.cfa.dispatch.load_management_team', side_effect=FileNotFoundError), \
             patch('teaparty.cfa.dispatch.load_project_team', side_effect=FileNotFoundError), \
             patch.dict(os.environ, {}, clear=False):
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

    def _run_dispatch(self, terminal_state: str = 'DONE') -> dict:
        parent_path = _make_parent_state_file(self.tmpdir)
        mock_result = _make_mock_orchestrator_result(terminal_state)
        mock_dispatch_info = _make_mock_dispatch_info(self.dispatch_infra)

        with patch('teaparty.cfa.dispatch.PhaseConfig') as mock_config_cls, \
             patch('teaparty.cfa.dispatch.create_task',
                   new=AsyncMock(return_value=mock_dispatch_info)), \
             patch('teaparty.cfa.dispatch.release_worktree',
                   new=AsyncMock()), \
             patch('teaparty.cfa.dispatch.squash_merge',
                   new=AsyncMock()), \
             patch('teaparty.cfa.dispatch.load_management_team',
                   side_effect=FileNotFoundError), \
             patch('teaparty.cfa.dispatch.load_project_team',
                   side_effect=FileNotFoundError), \
             patch('teaparty.cfa.dispatch.Orchestrator') as mock_orch_cls:

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
        result = self._run_dispatch('DONE')
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
