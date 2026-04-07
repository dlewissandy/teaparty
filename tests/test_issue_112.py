#!/usr/bin/env python3
"""Tests for issue #112: Worktree GC and manifest pruning.

Covers:
 1. cleanup_worktree removes its entry from worktrees.json
 2. Session.run() cleans up the session worktree after completion
 3. find_orphaned_worktrees identifies worktrees with no active session
 4. _unregister_worktree is a no-op when entry doesn't exist
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.worktree import (
    _register_worktree,
    cleanup_worktree,
)


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


def _make_fake_git_output(repo_root):
    """Create an async side_effect for mocked _run_git_output."""
    git_dir = os.path.join(repo_root, '.git')

    async def fake_output(cwd, *args):
        if '--git-common-dir' in args:
            return git_dir
        if '--show-toplevel' in args:
            return repo_root
        if '--abbrev-ref' in args:
            return os.path.basename(cwd)
        return ''
    return fake_output


# ── Tests: cleanup_worktree unregisters from manifest ─────────────────────────

class TestCleanupWorktreeUnregisters(unittest.TestCase):
    """cleanup_worktree() must remove the entry from worktrees.json."""

    def setUp(self):
        self.repo_root = tempfile.mkdtemp()
        self.worktree_path = os.path.join(self.repo_root, '.worktrees', 'session-abc123')
        os.makedirs(self.worktree_path, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.repo_root, ignore_errors=True)

    def test_entry_removed_from_manifest_after_cleanup(self):
        """After cleanup_worktree, the manifest should not contain the entry."""
        entry = _make_worktree_entry('session-abc123', self.worktree_path)
        other_entry = _make_worktree_entry('session-def456', '/other/path', session_id='other')
        _make_manifest(self.repo_root, [entry, other_entry])

        with patch('orchestrator.worktree._run_git_output',
                   side_effect=_make_fake_git_output(self.repo_root)), \
             patch('orchestrator.worktree._run_git',
                   new=AsyncMock()):
            _run(cleanup_worktree(self.worktree_path))

        entries = _read_manifest(self.repo_root)
        names = [e['name'] for e in entries]
        self.assertNotIn('session-abc123', names,
                         "Cleaned-up worktree should be removed from manifest")

    def test_other_entries_preserved_after_cleanup(self):
        """Cleanup should only remove the target entry, not others."""
        entry = _make_worktree_entry('session-abc123', self.worktree_path)
        other_entry = _make_worktree_entry('session-def456', '/other/path', session_id='other')
        _make_manifest(self.repo_root, [entry, other_entry])

        with patch('orchestrator.worktree._run_git_output',
                   side_effect=_make_fake_git_output(self.repo_root)), \
             patch('orchestrator.worktree._run_git',
                   new=AsyncMock()):
            _run(cleanup_worktree(self.worktree_path))

        entries = _read_manifest(self.repo_root)
        names = [e['name'] for e in entries]
        self.assertIn('session-def456', names,
                      "Other entries must be preserved")

    def test_cleanup_without_manifest_does_not_crash(self):
        """cleanup_worktree should not crash if worktrees.json doesn't exist."""
        with patch('orchestrator.worktree._run_git_output',
                   side_effect=_make_fake_git_output(self.repo_root)), \
             patch('orchestrator.worktree._run_git',
                   new=AsyncMock()):
            # Should not raise
            _run(cleanup_worktree(self.worktree_path))


# ── Tests: Session cleans up worktree after completion ────────────────────────

class TestSessionCleansUpWorktree(unittest.TestCase):
    """Session.run() must call cleanup_worktree after successful completion."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_session_calls_cleanup_worktree_on_completed_work(self):
        """After COMPLETED_WORK, Session.run() should clean up the session worktree."""
        from orchestrator.session import Session

        worktree_path = os.path.join(self.tmpdir, '.worktrees', 'session-test')
        os.makedirs(worktree_path, exist_ok=True)
        infra_dir = os.path.join(self.tmpdir, '.sessions', 'test-session')
        os.makedirs(infra_dir, exist_ok=True)

        mock_result = MagicMock()
        mock_result.terminal_state = 'COMPLETED_WORK'
        mock_result.backtrack_count = 0

        cleanup_mock = AsyncMock()

        session_info = {
            'job_id': 'job-test-session',
            'job_dir': infra_dir,
            'worktree_path': worktree_path,
            'branch_name': 'session-test',
        }

        with patch('orchestrator.session.create_job',
                   new=AsyncMock(return_value=session_info)), \
             patch('orchestrator.session.release_worktree',
                   new=cleanup_mock), \
             patch('orchestrator.session.commit_deliverables',
                   new=AsyncMock(return_value='abc123')), \
             patch('orchestrator.session.squash_merge',
                   new=AsyncMock()), \
             patch('orchestrator.session.extract_learnings',
                   new=AsyncMock()), \
             patch.object(Session, '_classify_task', return_value=('test-project', 'normal')), \
             patch.object(Session, '_find_repo_root', return_value=self.tmpdir), \
             patch('orchestrator.session.Orchestrator') as mock_orch_cls, \
             patch('orchestrator.session.StateWriter') as mock_sw_cls, \
             patch('orchestrator.session.PhaseConfig'):

            mock_orch = MagicMock()
            mock_orch.run = AsyncMock(return_value=mock_result)
            mock_orch_cls.return_value = mock_orch

            mock_sw = MagicMock()
            mock_sw.start = AsyncMock()
            mock_sw.stop = AsyncMock()
            mock_sw_cls.return_value = mock_sw

            session = Session(
                'test task',
                poc_root=self.tmpdir,
                projects_dir=self.tmpdir,
                skip_learnings=True,
                proxy_enabled=False,
                skip_learning_retrieval=True,
            )
            _run(session.run())

        cleanup_mock.assert_called_once_with(worktree_path)


# ── Tests: find_orphaned_worktrees ────────────────────────────────────────────

class TestFindOrphanedWorktrees(unittest.TestCase):
    """find_orphaned_worktrees() returns worktrees with no active session."""

    def setUp(self):
        self.repo_root = tempfile.mkdtemp()
        self.worktrees_dir = os.path.join(self.repo_root, '.worktrees')
        os.makedirs(self.worktrees_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.repo_root, ignore_errors=True)

    def test_worktree_with_no_running_sentinel_is_orphaned(self):
        """A worktree whose .running sentinel is gone should be reported as orphaned."""
        from orchestrator.worktree import find_orphaned_worktrees

        # Create a worktree dir without .running sentinel
        wt_path = os.path.join(self.worktrees_dir, 'session-orphan')
        os.makedirs(wt_path)

        entry = _make_worktree_entry('session-orphan', wt_path, session_id='orphan-001')
        _make_manifest(self.repo_root, [entry])

        orphans = find_orphaned_worktrees(self.repo_root)
        orphan_names = [o['name'] for o in orphans]
        self.assertIn('session-orphan', orphan_names)

    def test_worktree_with_stale_pid_is_orphaned(self):
        """A worktree with a .running file whose PID is dead should be orphaned."""
        from orchestrator.worktree import find_orphaned_worktrees

        wt_path = os.path.join(self.worktrees_dir, 'session-stale')
        os.makedirs(wt_path)
        # Write a .running sentinel with a PID that doesn't exist
        with open(os.path.join(wt_path, '.running'), 'w') as f:
            f.write('999999999')  # Very unlikely to be a real PID

        entry = _make_worktree_entry('session-stale', wt_path, session_id='stale-001')
        _make_manifest(self.repo_root, [entry])

        orphans = find_orphaned_worktrees(self.repo_root)
        orphan_names = [o['name'] for o in orphans]
        self.assertIn('session-stale', orphan_names)

    def test_worktree_with_live_pid_is_not_orphaned(self):
        """A worktree with a .running file whose PID is alive should NOT be orphaned."""
        from orchestrator.worktree import find_orphaned_worktrees

        wt_path = os.path.join(self.worktrees_dir, 'session-active')
        os.makedirs(wt_path)
        # Write our own PID — we know it's alive
        with open(os.path.join(wt_path, '.running'), 'w') as f:
            f.write(str(os.getpid()))

        entry = _make_worktree_entry('session-active', wt_path, session_id='active-001')
        _make_manifest(self.repo_root, [entry])

        orphans = find_orphaned_worktrees(self.repo_root)
        orphan_names = [o['name'] for o in orphans]
        self.assertNotIn('session-active', orphan_names)

    def test_nonexistent_worktree_path_is_orphaned(self):
        """A manifest entry whose path doesn't exist on disk is orphaned."""
        from orchestrator.worktree import find_orphaned_worktrees

        entry = _make_worktree_entry('session-gone', '/nonexistent/path', session_id='gone-001')
        _make_manifest(self.repo_root, [entry])

        orphans = find_orphaned_worktrees(self.repo_root)
        orphan_names = [o['name'] for o in orphans]
        self.assertIn('session-gone', orphan_names)


if __name__ == '__main__':
    unittest.main()
