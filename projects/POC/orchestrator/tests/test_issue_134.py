#!/usr/bin/env python3
"""Tests for issue #134: Project sessions must use an isolated project repo.

Covers:
 1. New project gets its own git repo (git init) when no .git exists.
 2. The new repo is empty — no files inherited from the parent repo.
 3. _find_repo_root returns the project repo, not the outer repo.
 4. Existing projects with .git are not re-initialized.
"""
import asyncio
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.session import Session, _find_repo_root_from


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_outer_repo(tmpdir: str) -> str:
    """Create a minimal outer git repo (simulating the teaparty repo)."""
    repo = os.path.join(tmpdir, 'outer-repo')
    os.makedirs(repo)
    subprocess.run(['git', 'init'], cwd=repo, capture_output=True, check=True)
    subprocess.run(['git', 'commit', '--allow-empty', '-m', 'init'],
                   cwd=repo, capture_output=True, check=True)
    # Create a sentinel file so we can detect if worktree inherits it
    sentinel = os.path.join(repo, 'OUTER_REPO_SENTINEL.txt')
    Path(sentinel).write_text('this file belongs to the outer repo')
    subprocess.run(['git', 'add', '.'], cwd=repo, capture_output=True, check=True)
    subprocess.run(['git', 'commit', '-m', 'add sentinel'],
                   cwd=repo, capture_output=True, check=True)
    return repo


def _make_session_for_find_repo_root(outer_repo: str) -> Session:
    """Create a Session instance without triggering PhaseConfig file I/O.

    We only need the _find_repo_root method, so we bypass __init__ and
    set just the attributes that method uses.
    """
    session = object.__new__(Session)
    poc_root = os.path.join(outer_repo, 'projects', 'POC')
    os.makedirs(poc_root, exist_ok=True)
    session.poc_root = poc_root
    return session


# ── Tests ────────────────────────────────────────────────────────────────────

class TestProjectRepoInitialization(unittest.TestCase):
    """New projects must get their own empty git repo."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.outer_repo = _make_outer_repo(self.tmpdir)

    def test_new_project_gets_own_git_repo(self):
        """A new project directory should have its own .git after _find_repo_root."""
        session = _make_session_for_find_repo_root(self.outer_repo)
        project_dir = os.path.join(self.outer_repo, 'projects', 'new-project')
        os.makedirs(project_dir, exist_ok=True)

        repo_root = session._find_repo_root(project_dir)

        # The repo root must be the project dir, not the outer repo
        self.assertEqual(
            os.path.realpath(repo_root),
            os.path.realpath(project_dir),
            f"repo_root should be the project dir, got {repo_root}"
        )
        # The project dir must have its own .git
        self.assertTrue(
            os.path.exists(os.path.join(project_dir, '.git')),
            "Project directory should have its own .git"
        )

    def test_new_project_repo_is_empty(self):
        """The new project repo must start empty — no files from the parent."""
        session = _make_session_for_find_repo_root(self.outer_repo)
        project_dir = os.path.join(self.outer_repo, 'projects', 'clean-project')
        os.makedirs(project_dir, exist_ok=True)

        repo_root = session._find_repo_root(project_dir)

        # The project must have its own .git — otherwise this test is vacuous
        self.assertTrue(
            os.path.exists(os.path.join(project_dir, '.git')),
            "Project directory must have its own .git for isolation"
        )

        # The project repo must have zero tracked files (only the seed commit)
        result = subprocess.run(
            ['git', 'ls-tree', '-r', '--name-only', 'HEAD'],
            cwd=project_dir, capture_output=True, text=True,
        )
        tracked_files = result.stdout.strip().split('\n') if result.stdout.strip() else []
        self.assertEqual(
            tracked_files, [],
            f"Project repo should have no tracked files, got {tracked_files}"
        )

    def test_new_project_repo_has_initial_commit(self):
        """The new project repo must have at least one commit (for worktree add)."""
        session = _make_session_for_find_repo_root(self.outer_repo)
        project_dir = os.path.join(self.outer_repo, 'projects', 'needs-commit')
        os.makedirs(project_dir, exist_ok=True)

        session._find_repo_root(project_dir)

        # Must have its own .git first
        self.assertTrue(
            os.path.exists(os.path.join(project_dir, '.git')),
            "Project directory must have its own .git"
        )

        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=project_dir, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0,
                         "Project repo must have at least one commit")

    def test_existing_project_repo_not_reinitialized(self):
        """A project that already has .git must not be re-initialized."""
        project_dir = os.path.join(self.outer_repo, 'projects', 'existing-project')
        os.makedirs(project_dir, exist_ok=True)

        # Create an existing repo with a commit
        subprocess.run(['git', 'init'], cwd=project_dir, capture_output=True, check=True)
        subprocess.run(['git', 'commit', '--allow-empty', '-m', 'existing work'],
                       cwd=project_dir, capture_output=True, check=True)

        # Record the initial commit hash
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=project_dir, capture_output=True, text=True,
        )
        original_head = result.stdout.strip()

        session = _make_session_for_find_repo_root(self.outer_repo)
        repo_root = session._find_repo_root(project_dir)

        # Must return the existing project dir
        self.assertEqual(
            os.path.realpath(repo_root),
            os.path.realpath(project_dir),
        )

        # Original commit must still be HEAD (not re-initialized)
        result = subprocess.run(
            ['git', 'rev-parse', 'HEAD'],
            cwd=project_dir, capture_output=True, text=True,
        )
        self.assertEqual(result.stdout.strip(), original_head,
                         "Existing repo HEAD was changed — repo may have been re-initialized")


class TestSessionWorktreeIsolation(unittest.TestCase):
    """_find_repo_root must return the project dir, not the outer repo."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.outer_repo = _make_outer_repo(self.tmpdir)

    def test_find_repo_root_returns_project_not_outer(self):
        """_find_repo_root must return project_dir for a new project,
        never the outer repo root."""
        session = _make_session_for_find_repo_root(self.outer_repo)
        project_dir = os.path.join(self.outer_repo, 'projects', 'isolated-project')
        os.makedirs(project_dir, exist_ok=True)

        repo_root = session._find_repo_root(project_dir)

        self.assertNotEqual(
            os.path.realpath(repo_root),
            os.path.realpath(self.outer_repo),
            "_find_repo_root must not fall back to the outer repo"
        )

    def test_find_repo_root_idempotent(self):
        """Calling _find_repo_root twice on the same project must be safe."""
        session = _make_session_for_find_repo_root(self.outer_repo)
        project_dir = os.path.join(self.outer_repo, 'projects', 'idem-project')
        os.makedirs(project_dir, exist_ok=True)

        root1 = session._find_repo_root(project_dir)
        root2 = session._find_repo_root(project_dir)

        self.assertEqual(
            os.path.realpath(root1),
            os.path.realpath(root2),
            "Two calls to _find_repo_root should return the same result"
        )


if __name__ == '__main__':
    unittest.main()
