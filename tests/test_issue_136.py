#!/usr/bin/env python3
"""Tests for issue #136: Linked-repo detection missing from Python orchestrator.

Covers:
 1. .linked-repo sentinel causes _ensure_project_repo to return the parent repo root.
 2. Without .linked-repo, _ensure_project_repo still initializes a new repo (no regression).
 3. When both .linked-repo and .git exist, .linked-repo wins.
 4. .linked-repo in a directory not inside any git repo produces a clear error.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.session import _ensure_project_repo, _find_repo_root_from


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_outer_repo(tmpdir: str) -> str:
    """Create a minimal outer git repo (simulating the teaparty repo)."""
    repo = os.path.join(tmpdir, 'outer-repo')
    os.makedirs(repo)
    subprocess.run(['git', 'init'], cwd=repo, capture_output=True, check=True)
    subprocess.run(['git', 'commit', '--allow-empty', '-m', 'init'],
                   cwd=repo, capture_output=True, check=True)
    return repo


def _make_project_with_linked_repo(outer_repo: str, name: str = 'POC') -> str:
    """Create a project directory with a .linked-repo sentinel inside outer_repo."""
    project_dir = os.path.join(outer_repo, 'projects', name)
    os.makedirs(project_dir, exist_ok=True)
    Path(os.path.join(project_dir, '.linked-repo')).write_text(
        '# This project uses the parent git repository instead of its own.\n'
    )
    return project_dir


# ── Tests ────────────────────────────────────────────────────────────────────

class TestLinkedRepoDetection(unittest.TestCase):
    """_ensure_project_repo must detect .linked-repo and return the parent repo."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.outer_repo = _make_outer_repo(self.tmpdir)

    def test_linked_repo_returns_parent_repo_root(self):
        """When .linked-repo exists, _ensure_project_repo returns the parent repo root."""
        project_dir = _make_project_with_linked_repo(self.outer_repo)

        repo_root = _ensure_project_repo(project_dir)

        self.assertEqual(
            os.path.realpath(repo_root),
            os.path.realpath(self.outer_repo),
            f"Expected parent repo root {self.outer_repo}, got {repo_root}",
        )

    def test_linked_repo_does_not_create_git_dir(self):
        """When .linked-repo exists, no .git directory should be created in project_dir."""
        project_dir = _make_project_with_linked_repo(self.outer_repo)

        _ensure_project_repo(project_dir)

        self.assertFalse(
            os.path.exists(os.path.join(project_dir, '.git')),
            "Project dir with .linked-repo should NOT get its own .git",
        )

    def test_linked_repo_beats_existing_git(self):
        """When both .linked-repo and .git exist, .linked-repo wins."""
        project_dir = _make_project_with_linked_repo(self.outer_repo)
        # Also give it its own .git
        subprocess.run(['git', 'init'], cwd=project_dir,
                       capture_output=True, check=True)
        subprocess.run(['git', 'commit', '--allow-empty', '-m', 'local init'],
                       cwd=project_dir, capture_output=True, check=True)

        repo_root = _ensure_project_repo(project_dir)

        self.assertEqual(
            os.path.realpath(repo_root),
            os.path.realpath(self.outer_repo),
            ".linked-repo should take precedence over local .git",
        )

    def test_no_linked_repo_still_inits(self):
        """Without .linked-repo, _ensure_project_repo still creates a new repo (regression guard)."""
        project_dir = os.path.join(self.outer_repo, 'projects', 'standalone')
        os.makedirs(project_dir, exist_ok=True)

        repo_root = _ensure_project_repo(project_dir)

        self.assertEqual(
            os.path.realpath(repo_root),
            os.path.realpath(project_dir),
            "Without .linked-repo, repo root should be the project dir itself",
        )
        self.assertTrue(
            os.path.exists(os.path.join(project_dir, '.git')),
            "Without .linked-repo, project dir should get its own .git",
        )

    def test_linked_repo_outside_any_repo_raises(self):
        """If .linked-repo exists but parent is not inside any git repo, raise an error."""
        # Create a project dir NOT inside a git repo
        standalone_dir = os.path.join(self.tmpdir, 'no-git', 'projects', 'orphan')
        os.makedirs(standalone_dir, exist_ok=True)
        Path(os.path.join(standalone_dir, '.linked-repo')).write_text('# linked\n')

        with self.assertRaises(RuntimeError):
            _ensure_project_repo(standalone_dir)


if __name__ == '__main__':
    unittest.main()
