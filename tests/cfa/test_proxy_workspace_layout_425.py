"""Issue #425: AskQuestionRunner prepares the proxy's workspace correctly.

When the proxy is engaged from an AskQuestion call:

  1. `<session_path>/worktree/` exists and is a real-file clone of the
     caller's worktree.
  2. `child_session.launch_cwd` is set to that clone — the proxy's cwd
     IS the worktree (issue #425 intent table, verbatim).
  3. The clone is real files, no symlinks (so the worktree-jail does not
     reject any of them via realpath resolution).
  4. No `QUESTION.md` is written.  The question reaches the proxy via
     the conversation history (posted to the bus by ``_route``).  The
     workspace is purely a snapshot of the work to review.

Each test pins one slice so a regression names the specific layout fault.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.cfa.gates.escalation import AskQuestionRunner


def _make_caller_worktree(root: str) -> dict[str, str]:
    files = {
        'manuscript/chapter-1.md': '# chapter one\n\nlorem\n',
        'manuscript/chapter-2.md': '# chapter two\n\nipsum\n',
        '.scratch/PLAN.md': '# plan\n',
        'README.md': '# readme\n',
    }
    for relpath, content in files.items():
        full = os.path.join(root, relpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'w') as f:
            f.write(content)
    return files


class _FakeChildSession:
    def __init__(self, path: str) -> None:
        self.path = path
        self.launch_cwd = ''
        self.parent_session_id = ''
        self.initial_message = ''


class PrepareProxyWorkspaceTest(unittest.TestCase):
    """The runner exposes a `_prepare_proxy_workspace` method that produces
    the layout the proxy needs."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix='proxy-workspace-')
        self.caller_worktree = os.path.join(self._tmp, 'caller-job', 'worktree')
        self.session_path = os.path.join(self._tmp, 'proxy-session')
        os.makedirs(self.caller_worktree)
        os.makedirs(self.session_path)
        self.expected_files = _make_caller_worktree(self.caller_worktree)
        self.runner = AskQuestionRunner(
            bus_db_path='',
            session_id='session-test',
            infra_dir=os.path.join(self._tmp, 'caller-job'),
        )
        self.child_session = _FakeChildSession(self.session_path)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_method_exists(self) -> None:
        self.assertTrue(
            hasattr(self.runner, '_prepare_proxy_workspace'),
            "AskQuestionRunner must expose `_prepare_proxy_workspace` "
            "(#425 — materialize the caller's worktree as cwd)",
        )

    def test_clone_exists_under_session_path(self) -> None:
        self.runner._prepare_proxy_workspace(self.child_session)
        clone_dir = os.path.join(self.session_path, 'worktree')
        self.assertTrue(
            os.path.isdir(clone_dir),
            f'expected clone at {clone_dir}; the proxy\'s cwd must '
            f"be a materialized copy of the caller's worktree (#425)",
        )

    def test_clone_holds_every_caller_file(self) -> None:
        self.runner._prepare_proxy_workspace(self.child_session)
        clone_dir = os.path.join(self.session_path, 'worktree')
        for relpath, expected in self.expected_files.items():
            target = os.path.join(clone_dir, relpath)
            self.assertTrue(
                os.path.isfile(target),
                f"clone missing {relpath}; proxy can't review what "
                f"isn't copied (#425)",
            )
            with open(target) as f:
                actual = f.read()
            self.assertEqual(
                actual, expected,
                f'{relpath}: clone content differs from caller worktree',
            )

    def test_clone_contains_no_symlinks(self) -> None:
        self.runner._prepare_proxy_workspace(self.child_session)
        clone_dir = os.path.join(self.session_path, 'worktree')
        symlinks: list[str] = []
        for dirpath, _dirs, files in os.walk(clone_dir):
            for name in files:
                full = os.path.join(dirpath, name)
                if os.path.islink(full):
                    symlinks.append(os.path.relpath(full, clone_dir))
        self.assertEqual(
            symlinks, [],
            f'clone contains symlinks at {symlinks}; #425 forbids '
            f'symlinks (worktree-jail would reject them via realpath)',
        )

    def test_no_question_md_is_written(self) -> None:
        # The question reaches the proxy via the bus (conversation
        # history), not via a file.  Writing one would be redundant
        # and would surface to the diligence walk as a non-deliverable.
        self.runner._prepare_proxy_workspace(self.child_session)
        question_md = os.path.join(self.session_path, 'QUESTION.md')
        self.assertFalse(
            os.path.exists(question_md),
            "no ./QUESTION.md should exist in the proxy workspace; "
            "the question is delivered via the bus (#425)",
        )
        clone_dir = os.path.join(self.session_path, 'worktree')
        self.assertFalse(
            os.path.exists(os.path.join(clone_dir, 'QUESTION.md')),
            "no QUESTION.md should appear inside the worktree clone; "
            "the question is delivered via the bus (#425)",
        )

    def test_launch_cwd_is_set_to_clone_path(self) -> None:
        self.runner._prepare_proxy_workspace(self.child_session)
        clone_dir = os.path.join(self.session_path, 'worktree')
        self.assertEqual(
            self.child_session.launch_cwd, clone_dir,
            f"child_session.launch_cwd must point at the clone "
            f"({clone_dir}); per #425 the proxy's cwd IS the "
            f"materialized worktree, not its parent dir",
        )

    def test_caller_files_reachable_at_cwd_root(self) -> None:
        # The diligence rail says "walk the worktree (your cwd)" —
        # caller files must be at ``./<relpath>`` from cwd, not
        # ``./worktree/<relpath>`` (that would mean cwd is the parent
        # of the worktree).
        self.runner._prepare_proxy_workspace(self.child_session)
        for relpath in self.expected_files:
            self.assertTrue(
                os.path.isfile(
                    os.path.join(self.child_session.launch_cwd, relpath),
                ),
                f"file {relpath} must be reachable from launch_cwd at "
                f"./{relpath} (#425 — cwd is the worktree itself)",
            )


class PrepareProxyWorkspaceGitSourceTest(unittest.TestCase):
    """End-to-end through the runner with a git-repo caller worktree.

    The materialize unit tests cover ``git clone`` and ``copytree`` in
    isolation; this test pins that ``_prepare_proxy_workspace`` uses
    the right one (git path) when the caller's worktree is a real
    repo, and that the layout invariants still hold (clone exists,
    files reachable, no symlinks).
    """

    def setUp(self) -> None:
        import subprocess
        self._tmp = tempfile.mkdtemp(prefix='proxy-workspace-git-')
        self.caller_worktree = os.path.join(self._tmp, 'caller-job', 'worktree')
        self.session_path = os.path.join(self._tmp, 'proxy-session')
        os.makedirs(self.caller_worktree)
        os.makedirs(self.session_path)
        self.expected_files = _make_caller_worktree(self.caller_worktree)
        # Make the caller worktree a real git repo with one commit.
        subprocess.run(
            ['git', 'init', '-q', self.caller_worktree],
            check=True, capture_output=True,
        )
        subprocess.run(
            ['git', '-C', self.caller_worktree, 'config', 'user.email', 't@t'],
            check=True,
        )
        subprocess.run(
            ['git', '-C', self.caller_worktree, 'config', 'user.name', 't'],
            check=True,
        )
        subprocess.run(
            ['git', '-C', self.caller_worktree, 'add', '.'],
            check=True, capture_output=True,
        )
        subprocess.run(
            ['git', '-C', self.caller_worktree, 'commit', '-q', '-m', 'init'],
            check=True, capture_output=True,
        )
        self.runner = AskQuestionRunner(
            bus_db_path='',
            session_id='session-test',
            infra_dir=os.path.join(self._tmp, 'caller-job'),
        )
        self.child_session = _FakeChildSession(self.session_path)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_git_source_files_reachable_in_clone(self) -> None:
        self.runner._prepare_proxy_workspace(self.child_session)
        clone_dir = os.path.join(self.session_path, 'worktree')
        for relpath in self.expected_files:
            target = os.path.join(clone_dir, relpath)
            self.assertTrue(
                os.path.isfile(target),
                f'git-source: clone missing {relpath}; runner did not '
                f'dispatch through git clone correctly (#425)',
            )

    def test_git_source_clone_has_no_symlinks(self) -> None:
        self.runner._prepare_proxy_workspace(self.child_session)
        clone_dir = os.path.join(self.session_path, 'worktree')
        symlinks: list[str] = []
        for dirpath, _dirs, files in os.walk(clone_dir):
            for name in files:
                full = os.path.join(dirpath, name)
                if os.path.islink(full):
                    symlinks.append(os.path.relpath(full, clone_dir))
        self.assertEqual(
            symlinks, [],
            f'git-source clone contains symlinks: {symlinks}; '
            f'#425 forbids symlinks',
        )

    def test_git_source_launch_cwd_is_clone_path(self) -> None:
        self.runner._prepare_proxy_workspace(self.child_session)
        clone_dir = os.path.join(self.session_path, 'worktree')
        self.assertEqual(
            self.child_session.launch_cwd, clone_dir,
            'git-source: launch_cwd must point at the clone, same as '
            'the plain-source case — the proxy launches inside the '
            'materialized worktree (#425)',
        )


if __name__ == '__main__':
    unittest.main()
