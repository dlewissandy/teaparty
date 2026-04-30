"""Issue #425: materialize the caller's worktree as a real-file clone.

The proxy launches in `cwd`.  `cwd` must be a real-file copy of the caller's
worktree — every file appears at the same relative path with identical
content, no symlinks.  Symlinks are not viable: the worktree-jail hook
would resolve them via realpath and reject targets outside the cwd subtree.
A real copy also gives the proxy a stable snapshot — what the caller
submitted at escalation time, not a moving target.

Each test pins one slice of the contract:

  * Real files (not symlinks).
  * Same relative paths.
  * Identical content (sha256).
  * Nested directories descended.
  * Hidden files included.
  * Source can be a git worktree or a plain directory; both work.
  * Idempotent on retry into a clean dest, raises on a non-empty dest
    (we do not silently merge into someone else's tree).
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.workspace.materialize import (
    MaterializationError,
    materialize_worktree,
)


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def _make_plain_worktree(root: str) -> dict[str, str]:
    """Create a directory with nested files; return path → sha256."""
    files = {
        'README.md': '# Caller worktree\n\nA mix of files.\n',
        'src/main.py': 'print("hello")\n',
        'src/sub/nested.txt': 'depth-2 file\n',
        '.scratch/QUESTION.md': '# planning\n',
        'docs/chapter-1.md': 'lorem ipsum\n' * 100,
    }
    digests: dict[str, str] = {}
    for relpath, content in files.items():
        full = os.path.join(root, relpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'w') as f:
            f.write(content)
        digests[relpath] = _sha256(full)
    return digests


def _make_git_worktree(root: str) -> dict[str, str]:
    """Same but make `root` a real git repo with one committed file."""
    digests = _make_plain_worktree(root)
    subprocess.run(
        ['git', 'init', '-q', root], check=True, capture_output=True,
    )
    subprocess.run(
        ['git', '-C', root, 'config', 'user.email', 't@t'], check=True,
    )
    subprocess.run(
        ['git', '-C', root, 'config', 'user.name', 't'], check=True,
    )
    subprocess.run(
        ['git', '-C', root, 'add', '.'], check=True, capture_output=True,
    )
    subprocess.run(
        ['git', '-C', root, 'commit', '-q', '-m', 'initial'],
        check=True, capture_output=True,
    )
    return digests


class MaterializeRealFilesTest(unittest.TestCase):
    """No symlinks anywhere in the materialized tree."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix='materialize-real-')
        self.src = os.path.join(self._tmp, 'caller')
        self.dest = os.path.join(self._tmp, 'proxy-cwd')
        os.makedirs(self.src)
        _make_plain_worktree(self.src)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_no_symlinks_in_destination(self) -> None:
        materialize_worktree(self.src, self.dest)
        symlinks = []
        for dirpath, _dirnames, filenames in os.walk(self.dest):
            for name in filenames:
                full = os.path.join(dirpath, name)
                if os.path.islink(full):
                    symlinks.append(os.path.relpath(full, self.dest))
        self.assertEqual(
            symlinks, [],
            f'destination contains symlinks at {symlinks}; '
            f'#425 forbids symlinks because the worktree-jail hook '
            f'rejects symlinked targets',
        )


class MaterializePlainCopyTest(unittest.TestCase):
    """Plain (non-git) source: every file copied at same path with same content."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix='materialize-plain-')
        self.src = os.path.join(self._tmp, 'caller')
        self.dest = os.path.join(self._tmp, 'proxy-cwd')
        os.makedirs(self.src)
        self.expected = _make_plain_worktree(self.src)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_every_source_file_appears_at_same_relative_path(self) -> None:
        materialize_worktree(self.src, self.dest)
        for relpath in self.expected:
            full = os.path.join(self.dest, relpath)
            self.assertTrue(
                os.path.isfile(full),
                f'expected {relpath} in destination at {full}; '
                f'materialization dropped it',
            )

    def test_file_content_is_identical(self) -> None:
        materialize_worktree(self.src, self.dest)
        for relpath, expected_sha in self.expected.items():
            actual_sha = _sha256(os.path.join(self.dest, relpath))
            self.assertEqual(
                actual_sha, expected_sha,
                f'{relpath}: content sha256 mismatch '
                f'(expected {expected_sha[:12]}, got {actual_sha[:12]})',
            )

    def test_no_extra_files_appear_in_destination(self) -> None:
        materialize_worktree(self.src, self.dest)
        actual: set[str] = set()
        for dirpath, _dirs, files in os.walk(self.dest):
            for name in files:
                rel = os.path.relpath(
                    os.path.join(dirpath, name), self.dest,
                )
                actual.add(rel)
        # Plain copytree preserves exactly the source set.
        self.assertEqual(
            actual, set(self.expected.keys()),
            f'destination has unexpected files {actual - set(self.expected)} '
            f'or missing files {set(self.expected) - actual}',
        )


class MaterializeGitCloneTest(unittest.TestCase):
    """Git source: cloned (not copytree); working tree intact."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix='materialize-git-')
        self.src = os.path.join(self._tmp, 'caller')
        self.dest = os.path.join(self._tmp, 'proxy-cwd')
        os.makedirs(self.src)
        self.expected = _make_git_worktree(self.src)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_committed_files_appear_in_destination(self) -> None:
        materialize_worktree(self.src, self.dest)
        for relpath in self.expected:
            full = os.path.join(self.dest, relpath)
            self.assertTrue(
                os.path.isfile(full),
                f'committed file {relpath} missing in destination '
                f'(materialization dropped it)',
            )

    def test_committed_file_content_is_identical(self) -> None:
        materialize_worktree(self.src, self.dest)
        for relpath, expected_sha in self.expected.items():
            actual_sha = _sha256(os.path.join(self.dest, relpath))
            self.assertEqual(
                actual_sha, expected_sha,
                f'{relpath}: committed content differs after clone',
            )


class MaterializeNonEmptyDestTest(unittest.TestCase):
    """Non-empty destination is a hard error — we don't merge into someone else's tree."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix='materialize-collide-')
        self.src = os.path.join(self._tmp, 'caller')
        self.dest = os.path.join(self._tmp, 'proxy-cwd')
        os.makedirs(self.src)
        os.makedirs(self.dest)
        with open(os.path.join(self.src, 'README.md'), 'w') as f:
            f.write('source\n')
        with open(os.path.join(self.dest, 'preexisting.md'), 'w') as f:
            f.write('not empty\n')

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_non_empty_destination_raises_materialization_error(self) -> None:
        # The specific exception type matters: a future regression that
        # silently merged the source into the dest could happen to raise
        # an unrelated error elsewhere, and ``assertRaises(Exception)``
        # would let that pass.  We pin the exact class.
        with self.assertRaises(MaterializationError) as cm:
            materialize_worktree(self.src, self.dest)
        self.assertIn(
            'not empty', str(cm.exception).lower(),
            'MaterializationError on a non-empty dest must explain '
            'the reason in its message ("not empty" / "refusing to '
            'merge"); a generic message hides the invariant.',
        )

    def test_non_empty_destination_does_not_partially_copy(self) -> None:
        # The error should fire BEFORE any source files leak into the
        # dest — a half-merged state is the bug pattern this guards.
        try:
            materialize_worktree(self.src, self.dest)
        except MaterializationError:
            pass
        # Dest should still contain only the pre-existing file.
        self.assertEqual(
            sorted(os.listdir(self.dest)), ['preexisting.md'],
            'non-empty-dest rejection must NOT partially merge source '
            'files; dest must be untouched',
        )


if __name__ == '__main__':
    unittest.main()
