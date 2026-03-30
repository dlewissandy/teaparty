#!/usr/bin/env python3
"""Tests for issue #207: dispatch merge failure must not silently discard work.

When squash_merge raises during a COMPLETED_WORK dispatch, the dispatch must:
  1. Return status='failed' with a reason mentioning the merge failure
  2. NOT write dispatch memory (rollup chain would see phantom completion)
  3. Return empty deliverables (no stale data from prior commits)
  4. Still clean up the worktree and .running sentinel

Additionally, commit-message generation failures must NOT prevent the merge
from being attempted — the fallback message should be used instead.
"""
import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.dispatch_cli import dispatch
from scripts.cfa_state import (
    make_initial_state,
    save_state,
    transition,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _make_parent_state_file(tmpdir: str, task_id: str = 'uber-001') -> str:
    cfa = make_initial_state(task_id=task_id)
    cfa = transition(cfa, 'propose')
    cfa = transition(cfa, 'auto-approve')
    cfa = transition(cfa, 'plan')
    cfa = transition(cfa, 'auto-approve')
    cfa = transition(cfa, 'delegate')
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


def _standard_patches(dispatch_infra, mock_result, squash_merge_side_effect=None,
                       generate_async_side_effect=None):
    """Return a dict of patch targets for dispatch().

    Caller uses these in a `with` block.  squash_merge and generate_async
    can be given side_effect to simulate failures.
    """
    mock_dispatch_info = _make_mock_dispatch_info(dispatch_infra)

    squash_mock = AsyncMock()
    if squash_merge_side_effect:
        squash_mock.side_effect = squash_merge_side_effect

    generate_mock = AsyncMock(return_value='commit msg')
    if generate_async_side_effect:
        generate_mock.side_effect = generate_async_side_effect

    return {
        'config_cls': patch('orchestrator.dispatch_cli.PhaseConfig'),
        'create_wt': patch('orchestrator.dispatch_cli.create_dispatch_worktree',
                           new=AsyncMock(return_value=mock_dispatch_info)),
        'cleanup_wt': patch('orchestrator.dispatch_cli.cleanup_worktree',
                            new=AsyncMock()),
        'squash': patch('orchestrator.dispatch_cli.squash_merge',
                        new=squash_mock),
        'orch_cls': patch('orchestrator.dispatch_cli.Orchestrator'),
        'generate': patch('orchestrator.dispatch_cli.generate_async',
                          new=generate_mock),
        'build_fb': patch('orchestrator.dispatch_cli.build_fallback',
                          return_value='fallback msg'),
        'git_output': patch('orchestrator.dispatch_cli.git_output',
                            new=AsyncMock(return_value='file.txt')),
        '_mock_result': mock_result,
        '_squash_mock': squash_mock,
        '_generate_mock': generate_mock,
    }


def _run_dispatch_with_patches(tmpdir, dispatch_infra, patches_dict):
    """Execute dispatch() inside the given patches, return result dict."""
    mock_result = patches_dict.pop('_mock_result')
    squash_mock = patches_dict.pop('_squash_mock')
    generate_mock = patches_dict.pop('_generate_mock')

    parent_path = _make_parent_state_file(tmpdir)

    # Stack all the context managers
    import contextlib
    cms = {k: v for k, v in patches_dict.items()}
    active = {}
    with contextlib.ExitStack() as stack:
        for name, cm in cms.items():
            active[name] = stack.enter_context(cm)

        # Wire up orchestrator mock
        mock_config = MagicMock()
        mock_config.max_dispatch_retries = 0
        active['config_cls'].return_value = mock_config

        mock_orch = MagicMock()
        mock_orch.run = AsyncMock(return_value=mock_result)
        active['orch_cls'].return_value = mock_orch

        env = {
            'POC_SESSION_DIR': tmpdir,
            'POC_SESSION_WORKTREE': tmpdir,
            'POC_PROJECT': 'test-project',
        }
        with patch.dict(os.environ, env, clear=False):
            result = _run(dispatch('coding', 'write tests',
                                   cfa_parent_state=parent_path))

    return result


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestDispatchMergeFailureSurfaced(unittest.TestCase):
    """Issue #207: merge failures must not be silently swallowed."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.dispatch_infra = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        shutil.rmtree(self.dispatch_infra, ignore_errors=True)

    def test_squash_merge_failure_returns_failed_status(self):
        """When squash_merge raises, dispatch must return status='failed'."""
        patches = _standard_patches(
            self.dispatch_infra,
            _make_mock_orchestrator_result('COMPLETED_WORK'),
            squash_merge_side_effect=RuntimeError('git lock contention'),
        )
        result = _run_dispatch_with_patches(self.tmpdir, self.dispatch_infra, patches)
        self.assertEqual(result['status'], 'failed',
                         "Merge failure must surface as status='failed', not 'completed'")

    def test_squash_merge_failure_reason_mentions_merge(self):
        """The failure reason must indicate it was a merge problem."""
        patches = _standard_patches(
            self.dispatch_infra,
            _make_mock_orchestrator_result('COMPLETED_WORK'),
            squash_merge_side_effect=RuntimeError('git lock contention'),
        )
        result = _run_dispatch_with_patches(self.tmpdir, self.dispatch_infra, patches)
        reason = result.get('reason', result.get('exit_reason', ''))
        self.assertIn('merge', reason.lower(),
                      f"Failure reason should mention 'merge', got: {reason}")

    def test_squash_merge_failure_has_empty_deliverables(self):
        """When merge fails, deliverables must be empty — no stale data."""
        patches = _standard_patches(
            self.dispatch_infra,
            _make_mock_orchestrator_result('COMPLETED_WORK'),
            squash_merge_side_effect=RuntimeError('conflict'),
        )
        result = _run_dispatch_with_patches(self.tmpdir, self.dispatch_infra, patches)
        self.assertEqual(result.get('deliverables', ''), '',
                         "Deliverables must be empty when merge fails")


class TestDispatchMergeFailureSkipsMemory(unittest.TestCase):
    """When merge fails, _write_dispatch_memory must NOT be called."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.dispatch_infra = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        shutil.rmtree(self.dispatch_infra, ignore_errors=True)

    def test_memory_not_written_on_merge_failure(self):
        """_write_dispatch_memory must not run when merge failed."""
        patches = _standard_patches(
            self.dispatch_infra,
            _make_mock_orchestrator_result('COMPLETED_WORK'),
            squash_merge_side_effect=RuntimeError('filesystem error'),
        )
        with patch('orchestrator.dispatch_cli._write_dispatch_memory') as mock_mem:
            result = _run_dispatch_with_patches(self.tmpdir, self.dispatch_infra, patches)
            mock_mem.assert_not_called()


class TestDispatchMessageGenerationFailure(unittest.TestCase):
    """Commit-message generation failure must NOT prevent the merge."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.dispatch_infra = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        shutil.rmtree(self.dispatch_infra, ignore_errors=True)

    def test_generate_async_failure_still_merges(self):
        """When generate_async raises, merge should still proceed with fallback message."""
        patches = _standard_patches(
            self.dispatch_infra,
            _make_mock_orchestrator_result('COMPLETED_WORK'),
            generate_async_side_effect=RuntimeError('LLM unavailable'),
        )
        squash_mock = patches['_squash_mock']
        result = _run_dispatch_with_patches(self.tmpdir, self.dispatch_infra, patches)
        # The merge should have been attempted (squash_merge called)
        squash_mock.assert_called_once()
        # And dispatch should report success since the merge itself succeeded
        self.assertEqual(result['status'], 'completed')


class TestDispatchCleanupAfterMergeFailure(unittest.TestCase):
    """Worktree cleanup and .running sentinel removal must happen even on merge failure."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.dispatch_infra = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        shutil.rmtree(self.dispatch_infra, ignore_errors=True)

    def test_cleanup_worktree_called_on_merge_failure(self):
        """cleanup_worktree must still be called when merge fails."""
        mock_result = _make_mock_orchestrator_result('COMPLETED_WORK')
        mock_dispatch_info = _make_mock_dispatch_info(self.dispatch_infra)
        parent_path = _make_parent_state_file(self.tmpdir)

        cleanup_mock = AsyncMock()

        with patch('orchestrator.dispatch_cli.PhaseConfig') as cfg_cls, \
             patch('orchestrator.dispatch_cli.create_dispatch_worktree',
                   new=AsyncMock(return_value=mock_dispatch_info)), \
             patch('orchestrator.dispatch_cli.cleanup_worktree',
                   new=cleanup_mock), \
             patch('orchestrator.dispatch_cli.squash_merge',
                   new=AsyncMock(side_effect=RuntimeError('merge boom'))), \
             patch('orchestrator.dispatch_cli.Orchestrator') as orch_cls, \
             patch('orchestrator.dispatch_cli.generate_async',
                   new=AsyncMock(return_value='msg')), \
             patch('orchestrator.dispatch_cli.build_fallback',
                   return_value='fallback'), \
             patch('orchestrator.dispatch_cli.git_output',
                   new=AsyncMock(return_value='file.txt')):

            mock_config = MagicMock()
            mock_config.max_dispatch_retries = 0
            cfg_cls.return_value = mock_config

            mock_orch = MagicMock()
            mock_orch.run = AsyncMock(return_value=mock_result)
            orch_cls.return_value = mock_orch

            env = {
                'POC_SESSION_DIR': self.tmpdir,
                'POC_SESSION_WORKTREE': self.tmpdir,
                'POC_PROJECT': 'test-project',
            }
            with patch.dict(os.environ, env, clear=False):
                _run(dispatch('coding', 'write tests',
                              cfa_parent_state=parent_path))

        cleanup_mock.assert_called_once()


if __name__ == '__main__':
    unittest.main()
