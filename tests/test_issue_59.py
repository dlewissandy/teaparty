#!/usr/bin/env python3
"""Tests for issue #59: Collision detection for dispatch worktree names.

Covers:
 1. Two dispatches in the same second produce different worktree names.
 2. Two dispatches in the same second produce different infra directories.
 3. The dispatch_id includes sub-second precision to avoid collisions.
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.worktree import create_dispatch_worktree


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _make_dispatch_env(tmpdir: str) -> dict:
    """Create minimal filesystem layout for dispatch worktree creation."""
    session_wt = os.path.join(tmpdir, 'worktrees', 'session-test')
    infra_dir = os.path.join(tmpdir, 'sessions', 'test-session')
    repo_root = tmpdir

    os.makedirs(session_wt, exist_ok=True)
    os.makedirs(infra_dir, exist_ok=True)
    for team in ('coding',):
        os.makedirs(os.path.join(infra_dir, team), exist_ok=True)

    # Initialize manifest
    manifest_path = os.path.join(repo_root, 'worktrees.json')
    with open(manifest_path, 'w') as f:
        json.dump({'worktrees': []}, f)

    return {
        'session_worktree': session_wt,
        'infra_dir': infra_dir,
        'repo_root': repo_root,
    }


# ── Tests ────────────────────────────────────────────────────────────────────

class TestDispatchWorktreeCollision(unittest.TestCase):
    """Two dispatches in the same second must produce different names."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.env = _make_dispatch_env(self.tmpdir)

    def test_same_second_different_names(self):
        """Two dispatches with identical team/task in the same second
        must produce different worktree_name values."""
        frozen_time = datetime(2026, 3, 14, 16, 30, 0)

        async def fake_run_git(cwd, *args):
            pass

        async def fake_run_git_output(cwd, *args):
            if '--git-common-dir' in args:
                return os.path.join(self.env['repo_root'], '.git') + '\n'
            return '\n'

        with patch('orchestrator.worktree._run_git', new=fake_run_git), \
             patch('orchestrator.worktree._run_git_output', new=fake_run_git_output), \
             patch('orchestrator.worktree.datetime') as mock_dt:
            mock_dt.now.return_value = frozen_time
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            info1 = _run(create_dispatch_worktree(
                team='coding', task='build feature',
                session_worktree=self.env['session_worktree'],
                infra_dir=self.env['infra_dir'],
                repo_root=self.env['repo_root'],
            ))
            info2 = _run(create_dispatch_worktree(
                team='coding', task='build feature',
                session_worktree=self.env['session_worktree'],
                infra_dir=self.env['infra_dir'],
                repo_root=self.env['repo_root'],
            ))

        self.assertNotEqual(
            info1['worktree_name'], info2['worktree_name'],
            "Two dispatches in the same second must have different worktree names"
        )

    def test_same_second_different_infra_dirs(self):
        """Two dispatches in the same second must produce different infra directories."""
        frozen_time = datetime(2026, 3, 14, 16, 30, 0)

        async def fake_run_git(cwd, *args):
            pass

        async def fake_run_git_output(cwd, *args):
            if '--git-common-dir' in args:
                return os.path.join(self.env['repo_root'], '.git') + '\n'
            return '\n'

        with patch('orchestrator.worktree._run_git', new=fake_run_git), \
             patch('orchestrator.worktree._run_git_output', new=fake_run_git_output), \
             patch('orchestrator.worktree.datetime') as mock_dt:
            mock_dt.now.return_value = frozen_time
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

            info1 = _run(create_dispatch_worktree(
                team='coding', task='build feature',
                session_worktree=self.env['session_worktree'],
                infra_dir=self.env['infra_dir'],
                repo_root=self.env['repo_root'],
            ))
            info2 = _run(create_dispatch_worktree(
                team='coding', task='build feature',
                session_worktree=self.env['session_worktree'],
                infra_dir=self.env['infra_dir'],
                repo_root=self.env['repo_root'],
            ))

        self.assertNotEqual(
            info1['infra_dir'], info2['infra_dir'],
            "Two dispatches in the same second must have different infra dirs"
        )

    def test_dispatch_id_has_subsecond_precision(self):
        """The dispatch_id must include sub-second precision to avoid collisions."""
        async def fake_run_git(cwd, *args):
            pass

        async def fake_run_git_output(cwd, *args):
            if '--git-common-dir' in args:
                return os.path.join(self.env['repo_root'], '.git') + '\n'
            return '\n'

        with patch('orchestrator.worktree._run_git', new=fake_run_git), \
             patch('orchestrator.worktree._run_git_output', new=fake_run_git_output):
            info = _run(create_dispatch_worktree(
                team='coding', task='test task',
                session_worktree=self.env['session_worktree'],
                infra_dir=self.env['infra_dir'],
                repo_root=self.env['repo_root'],
            ))

        dispatch_id = info['dispatch_id']
        # Must be longer than 'YYYYMMDD-HHMMSS' (15 chars) to have sub-second precision
        self.assertGreater(
            len(dispatch_id), 15,
            f"dispatch_id '{dispatch_id}' lacks sub-second precision"
        )


if __name__ == '__main__':
    unittest.main()
