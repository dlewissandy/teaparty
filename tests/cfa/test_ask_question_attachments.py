"""AskQuestion attachments: agent-named files copied to the proxy's workspace.

The agent decides what context the responder needs.  ``attachments``
is an optional list of filepaths relative to the agent's worktree.
The runner copies each into the proxy's session dir at the same
relative path, so the proxy reads ``./.scratch/research-brief.md``
the same way the agent does in its own worktree.

This test pins the contract:
  * Files inside the worktree are copied with structure preserved.
  * Absolute paths are rejected (no arbitrary filesystem reads).
  * Path traversal via ``..`` is rejected.
  * Bytes past the budget are skipped, not failed.
  * QUESTION.md gains an Attachments section listing what arrived.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.cfa.gates.escalation import AskQuestionRunner


def _make_runner(infra_dir: str, bus_db_path: str = '') -> AskQuestionRunner:
    return AskQuestionRunner(
        bus_db_path=bus_db_path,
        session_id='session-test',
        infra_dir=infra_dir,
    )


class CopyAttachmentsTest(unittest.TestCase):
    """The runner copies named attachments into the proxy's session dir."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix='askq-attach-')
        self.caller_worktree = os.path.join(
            self._tmp, 'job-test', 'worktree',
        )
        self.dest_dir = os.path.join(self._tmp, 'proxy-session')
        os.makedirs(self.caller_worktree)
        os.makedirs(self.dest_dir)
        # Set up a minimal worktree the runner will resolve to.
        os.makedirs(os.path.join(self.caller_worktree, '.scratch'))
        with open(
            os.path.join(self.caller_worktree, '.scratch', 'brief.md'), 'w',
        ) as f:
            f.write('# Research brief\n\nSeven chapters, etc.\n')
        with open(
            os.path.join(self.caller_worktree, '.scratch', 'plan.md'), 'w',
        ) as f:
            f.write('# Plan\n\n- step one\n- step two\n')
        # job_dir = parent of worktree.
        self.infra_dir = os.path.join(self._tmp, 'job-test')
        # The runner's _resolve_caller_worktree returns
        # {infra_dir}/worktree when the caller is the job lead.
        self.runner = _make_runner(self.infra_dir)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_copies_relative_path_with_structure_preserved(self) -> None:
        copied = self.runner._copy_attachments(
            self.dest_dir, ['.scratch/brief.md'],
        )
        self.assertEqual(copied, ['.scratch/brief.md'])
        dest = os.path.join(self.dest_dir, '.scratch', 'brief.md')
        self.assertTrue(os.path.isfile(dest))
        with open(dest) as f:
            self.assertIn('Research brief', f.read())

    def test_copies_multiple_attachments_in_input_order(self) -> None:
        copied = self.runner._copy_attachments(
            self.dest_dir, ['.scratch/plan.md', '.scratch/brief.md'],
        )
        self.assertEqual(copied, ['.scratch/plan.md', '.scratch/brief.md'])
        for relpath in copied:
            self.assertTrue(
                os.path.isfile(os.path.join(self.dest_dir, relpath)),
            )

    def test_rejects_absolute_path(self) -> None:
        copied = self.runner._copy_attachments(
            self.dest_dir, ['/etc/passwd'],
        )
        self.assertEqual(copied, [])

    def test_rejects_path_traversal(self) -> None:
        # Even after normalization, '..' segments at the front escape.
        copied = self.runner._copy_attachments(
            self.dest_dir, ['../../../etc/passwd'],
        )
        self.assertEqual(copied, [])

    def test_rejects_symlink_escaping_worktree(self) -> None:
        """A symlink pointing outside the worktree is rejected.

        The realpath check after join must resolve through symlinks,
        not just lexically reject ``..``.
        """
        outside = os.path.join(self._tmp, 'secret.txt')
        with open(outside, 'w') as f:
            f.write('outside')
        link = os.path.join(self.caller_worktree, '.scratch', 'leak.md')
        os.symlink(outside, link)
        copied = self.runner._copy_attachments(
            self.dest_dir, ['.scratch/leak.md'],
        )
        self.assertEqual(copied, [])

    def test_skips_missing_files(self) -> None:
        copied = self.runner._copy_attachments(
            self.dest_dir, ['.scratch/missing.md', '.scratch/brief.md'],
        )
        self.assertEqual(copied, ['.scratch/brief.md'])

    def test_budget_skips_oversize_files(self) -> None:
        """Files past the 200KB budget are skipped, not failed."""
        big = os.path.join(self.caller_worktree, '.scratch', 'big.md')
        with open(big, 'w') as f:
            f.write('x' * (250 * 1024))
        copied = self.runner._copy_attachments(
            self.dest_dir, ['.scratch/brief.md', '.scratch/big.md'],
        )
        self.assertIn('.scratch/brief.md', copied)
        self.assertNotIn('.scratch/big.md', copied)

    def test_empty_list_returns_empty(self) -> None:
        self.assertEqual(self.runner._copy_attachments(self.dest_dir, []), [])


class ResolveCallerWorktreeTest(unittest.TestCase):
    """``_resolve_caller_worktree`` picks the right path for each tier."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix='askq-resolve-')
        self.infra_dir = os.path.join(self._tmp, 'job')
        os.makedirs(os.path.join(self.infra_dir, 'worktree'))

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_no_contextvar_returns_job_worktree(self) -> None:
        """No caller_sid → project lead → use the job's worktree."""
        runner = _make_runner(self.infra_dir)
        # The contextvar defaults to '' in a fresh execution context.
        result = runner._resolve_caller_worktree()
        self.assertEqual(
            result, os.path.join(self.infra_dir, 'worktree'),
        )

    def test_caller_is_job_session_returns_job_worktree(self) -> None:
        runner = _make_runner(self.infra_dir)
        from teaparty.mcp.registry import current_session_id
        token = current_session_id.set('session-test')
        try:
            self.assertEqual(
                runner._resolve_caller_worktree(),
                os.path.join(self.infra_dir, 'worktree'),
            )
        finally:
            current_session_id.reset(token)


if __name__ == '__main__':
    unittest.main()
