#!/usr/bin/env python3
"""Tests for issue #209: cleanup_worktree resolves wrong git root and silently swallows failures.

Covers:
 1. cleanup_worktree uses --git-common-dir (not --show-toplevel) to find the repo root
 2. cleanup_worktree still removes the branch and manifest entry when worktree remove fails
 3. cleanup_worktree logs warnings on partial failures instead of silently swallowing
"""
import asyncio
import json
import logging
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, call, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.worktree import cleanup_worktree


# ── Helpers ────────────────────────────────────────────────────────────────────

def _run(coro):
    """Run a coroutine synchronously for testing."""
    return asyncio.run(coro)


def _make_manifest(repo_root, entries):
    """Write a worktrees.json manifest with the given entries."""
    manifest_path = os.path.join(repo_root, 'worktrees.json')
    with open(manifest_path, 'w') as f:
        json.dump({'worktrees': entries}, f, indent=2)
    return manifest_path


def _read_manifest(repo_root):
    """Read and return the worktrees.json entries."""
    manifest_path = os.path.join(repo_root, 'worktrees.json')
    with open(manifest_path) as f:
        return json.load(f).get('worktrees', [])


def _make_worktree_entry(name, path, status='active', session_id='test-session'):
    """Create a worktree manifest entry."""
    return {
        'name': name,
        'path': path,
        'type': 'session',
        'team': '',
        'task': 'test task',
        'session_id': session_id,
        'created_at': '2026-01-01T00:00:00+00:00',
        'status': status,
    }


# ── Tests: cleanup_worktree resolves repo root correctly ──────────────────────

class TestCleanupWorktreeResolvesRepoRoot(unittest.TestCase):
    """cleanup_worktree must use --git-common-dir to find the real repo root,
    not --show-toplevel which returns the worktree root."""

    def setUp(self):
        self.repo_root = tempfile.mkdtemp()
        self.worktree_path = os.path.join(self.repo_root, '.worktrees', 'session-abc123')
        os.makedirs(self.worktree_path, exist_ok=True)
        # Pre-populate manifest so we can verify correct unregistration
        entry = _make_worktree_entry('session-abc123', self.worktree_path)
        _make_manifest(self.repo_root, [entry])

    def tearDown(self):
        shutil.rmtree(self.repo_root, ignore_errors=True)

    def _make_git_output(self):
        """Create async side_effect that returns correct values for --git-common-dir."""
        repo_root = self.repo_root
        git_dir = os.path.join(repo_root, '.git')

        async def fake_output(cwd, *args):
            if '--git-common-dir' in args:
                return git_dir + '\n'
            if '--abbrev-ref' in args:
                return 'session-abc123\n'
            # --show-toplevel would return the worktree path (wrong!)
            if '--show-toplevel' in args:
                return cwd + '\n'
            return ''
        return fake_output

    def test_uses_git_common_dir_not_show_toplevel(self):
        """cleanup_worktree must call --git-common-dir, not --show-toplevel."""
        git_output_mock = AsyncMock(side_effect=self._make_git_output())

        with patch('projects.POC.orchestrator.worktree._run_git_output',
                   git_output_mock), \
             patch('projects.POC.orchestrator.worktree._run_git',
                   new=AsyncMock()):
            _run(cleanup_worktree(self.worktree_path))

        # Inspect what git commands were called
        git_args_list = [c.args for c in git_output_mock.call_args_list]
        used_show_toplevel = any('--show-toplevel' in args for args in git_args_list)
        used_git_common_dir = any('--git-common-dir' in args for args in git_args_list)

        self.assertFalse(used_show_toplevel,
                         "cleanup_worktree must NOT use --show-toplevel (returns worktree root)")
        self.assertTrue(used_git_common_dir,
                        "cleanup_worktree must use --git-common-dir (returns real repo .git dir)")

    def test_passes_repo_root_not_worktree_to_git_commands(self):
        """worktree remove and branch -D must be called with the real repo root,
        not the worktree path."""
        git_output_mock = AsyncMock(side_effect=self._make_git_output())
        git_run_mock = AsyncMock()

        with patch('projects.POC.orchestrator.worktree._run_git_output',
                   git_output_mock), \
             patch('projects.POC.orchestrator.worktree._run_git',
                   git_run_mock):
            _run(cleanup_worktree(self.worktree_path))

        # The cwd passed to worktree remove and branch -D should be repo_root
        for c in git_run_mock.call_args_list:
            cwd_arg = c.args[0]
            self.assertEqual(cwd_arg, self.repo_root,
                             f"Expected repo_root={self.repo_root}, got cwd={cwd_arg}")


# ── Tests: cleanup_worktree handles partial failures ──────────────────────────

class TestCleanupWorktreePartialFailure(unittest.TestCase):
    """When one cleanup step fails, the remaining steps must still execute."""

    def setUp(self):
        self.repo_root = tempfile.mkdtemp()
        self.worktree_path = os.path.join(self.repo_root, '.worktrees', 'session-partial')
        os.makedirs(self.worktree_path, exist_ok=True)
        entry = _make_worktree_entry('session-partial', self.worktree_path)
        _make_manifest(self.repo_root, [entry])

    def tearDown(self):
        shutil.rmtree(self.repo_root, ignore_errors=True)

    def _make_git_output(self):
        repo_root = self.repo_root
        git_dir = os.path.join(repo_root, '.git')

        async def fake_output(cwd, *args):
            if '--git-common-dir' in args:
                return git_dir + '\n'
            if '--abbrev-ref' in args:
                return 'session-partial\n'
            if '--show-toplevel' in args:
                return cwd + '\n'
            return ''
        return fake_output

    def test_manifest_cleaned_even_when_worktree_remove_fails(self):
        """If 'git worktree remove' fails, the manifest entry must still be removed."""
        async def failing_git_run(cwd, *args):
            if 'worktree' in args and 'remove' in args:
                raise RuntimeError("worktree remove failed")

        with patch('projects.POC.orchestrator.worktree._run_git_output',
                   AsyncMock(side_effect=self._make_git_output())), \
             patch('projects.POC.orchestrator.worktree._run_git',
                   AsyncMock(side_effect=failing_git_run)):
            _run(cleanup_worktree(self.worktree_path))

        entries = _read_manifest(self.repo_root)
        names = [e['name'] for e in entries]
        self.assertNotIn('session-partial', names,
                         "Manifest entry must be removed even when worktree remove fails")

    def test_branch_deleted_even_when_worktree_remove_fails(self):
        """If 'git worktree remove' fails, branch deletion must still be attempted."""
        branch_delete_called = []

        async def selective_git_run(cwd, *args):
            if 'worktree' in args and 'remove' in args:
                raise RuntimeError("worktree remove failed")
            if 'branch' in args and '-D' in args:
                branch_delete_called.append(args)

        with patch('projects.POC.orchestrator.worktree._run_git_output',
                   AsyncMock(side_effect=self._make_git_output())), \
             patch('projects.POC.orchestrator.worktree._run_git',
                   AsyncMock(side_effect=selective_git_run)):
            _run(cleanup_worktree(self.worktree_path))

        self.assertTrue(branch_delete_called,
                        "Branch deletion must be attempted even when worktree remove fails")


# ── Tests: cleanup_worktree logs failures ─────────────────────────────────────

class TestCleanupWorktreeLogsFailures(unittest.TestCase):
    """cleanup_worktree must log warnings instead of silently swallowing errors."""

    def setUp(self):
        self.repo_root = tempfile.mkdtemp()
        self.worktree_path = os.path.join(self.repo_root, '.worktrees', 'session-logtest')
        os.makedirs(self.worktree_path, exist_ok=True)
        entry = _make_worktree_entry('session-logtest', self.worktree_path)
        _make_manifest(self.repo_root, [entry])

    def tearDown(self):
        shutil.rmtree(self.repo_root, ignore_errors=True)

    def _make_git_output(self):
        repo_root = self.repo_root
        git_dir = os.path.join(repo_root, '.git')

        async def fake_output(cwd, *args):
            if '--git-common-dir' in args:
                return git_dir + '\n'
            if '--abbrev-ref' in args:
                return 'session-logtest\n'
            if '--show-toplevel' in args:
                return cwd + '\n'
            return ''
        return fake_output

    def test_logs_warning_when_worktree_remove_fails(self):
        """A failed worktree removal must produce a log warning, not silent pass."""
        async def failing_git_run(cwd, *args):
            if 'worktree' in args and 'remove' in args:
                raise RuntimeError("worktree remove failed")

        with patch('projects.POC.orchestrator.worktree._run_git_output',
                   AsyncMock(side_effect=self._make_git_output())), \
             patch('projects.POC.orchestrator.worktree._run_git',
                   AsyncMock(side_effect=failing_git_run)), \
             self.assertLogs('projects.POC.orchestrator.worktree', level='WARNING') as cm:
            _run(cleanup_worktree(self.worktree_path))

        # At least one warning about the failure
        self.assertTrue(any('worktree' in msg.lower() for msg in cm.output),
                        f"Expected warning about worktree removal failure, got: {cm.output}")


if __name__ == '__main__':
    unittest.main()
