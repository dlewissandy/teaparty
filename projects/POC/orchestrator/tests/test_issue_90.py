#!/usr/bin/env python3
"""Tests for issue #90: File locking on shared-file writes.

Covers:
 1. Concurrent _register_worktree() calls don't lose entries (proves locking works).
 2. _register_worktree uses FileLock (source inspection).
 3. _reinforce_retrieved uses FileLock (source inspection).
 4. _run_summarize uses FileLock (source inspection).
 5. _call_promote uses FileLock (source inspection).
"""
import inspect
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_worktrees_json(path: str, entries: list | None = None) -> str:
    manifest = {'worktrees': entries or []}
    with open(path, 'w') as f:
        json.dump(manifest, f)
    return path


# ── Tests: _register_worktree locking ─────────────────────────────────────────

class TestRegisterWorktreeLocking(unittest.TestCase):
    """_register_worktree() uses file locking for concurrent safety."""

    def test_register_worktree_uses_filelock(self):
        """_register_worktree source contains FileLock usage."""
        from projects.POC.orchestrator.worktree import _register_worktree
        source = inspect.getsource(_register_worktree)
        self.assertIn('FileLock', source,
                      '_register_worktree should use FileLock')

    def test_concurrent_register_worktree_no_lost_entries(self):
        """Multiple concurrent _register_worktree calls don't lose entries."""
        from projects.POC.orchestrator.worktree import _register_worktree

        with tempfile.TemporaryDirectory() as td:
            manifest_path = os.path.join(td, 'worktrees.json')
            _make_worktrees_json(manifest_path)

            n_threads = 10
            barrier = threading.Barrier(n_threads)
            errors = []

            def register(i):
                try:
                    barrier.wait(timeout=5)
                    _register_worktree(td, {
                        'name': f'wt-{i}',
                        'path': f'/tmp/wt-{i}',
                        'type': 'dispatch',
                    })
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=register, args=(i,)) for i in range(n_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=10)

            self.assertEqual(errors, [], f'Errors during concurrent register: {errors}')

            with open(manifest_path) as f:
                data = json.load(f)
            self.assertEqual(
                len(data['worktrees']), n_threads,
                f'Expected {n_threads} entries but got {len(data["worktrees"])} — '
                'concurrent writes lost entries',
            )


# ── Tests: _reinforce_retrieved locking ───────────────────────────────────────

class TestReinforceRetrievedLocking(unittest.TestCase):
    """_reinforce_retrieved() uses file locking when writing memory files."""

    def test_reinforce_uses_filelock(self):
        """_reinforce_retrieved source contains FileLock usage."""
        from projects.POC.orchestrator.learnings import _reinforce_retrieved
        source = inspect.getsource(_reinforce_retrieved)
        self.assertIn('FileLock', source,
                      '_reinforce_retrieved should use FileLock')


# ── Tests: _run_summarize and _call_promote locking ───────────────────────────

class TestLearningScopeLocking(unittest.TestCase):
    """Learning extraction scopes use file locking on output paths."""

    def test_run_summarize_uses_filelock(self):
        """_run_summarize source contains FileLock usage."""
        from projects.POC.orchestrator.learnings import _run_summarize
        source = inspect.getsource(_run_summarize)
        self.assertIn('FileLock', source,
                      '_run_summarize should use FileLock')

    def test_call_promote_uses_filelock(self):
        """_call_promote source contains FileLock usage."""
        from projects.POC.orchestrator.learnings import _call_promote
        source = inspect.getsource(_call_promote)
        self.assertIn('FileLock', source,
                      '_call_promote should use FileLock')


if __name__ == '__main__':
    unittest.main()
