"""Issue #425: AskQuestionRunner prepares the proxy's workspace correctly.

When the proxy is engaged from an AskQuestion call:

  1. `<session_path>/worktree/` exists and is a real-file clone of the
     caller's worktree (issue invariant: cwd is the caller's worktree;
     clone is the materialization of that).
  2. `<session_path>/QUESTION.md` exists and holds the question text
     (out of the caller's worktree clone, so walking the worktree does
     not surface the question file as a deliverable).
  3. The cwd handed to the proxy invoker is the clone path
     (`<session_path>/worktree/`), not the session dir.
  4. The clone is real files, no symlinks (so the worktree-jail does not
     reject any of them via realpath resolution).

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
            "(#425 — single helper that materializes clone + writes "
            "question)",
        )

    def test_clone_exists_under_session_path(self) -> None:
        self.runner._prepare_proxy_workspace(
            self.child_session, question='Approve?', context='',
        )
        clone_dir = os.path.join(self.session_path, 'worktree')
        self.assertTrue(
            os.path.isdir(clone_dir),
            f'expected clone at {clone_dir} after _prepare_proxy_workspace; '
            f"the proxy's cwd must contain a materialized copy of the "
            f"caller's worktree (#425)",
        )

    def test_clone_holds_every_caller_file(self) -> None:
        self.runner._prepare_proxy_workspace(
            self.child_session, question='Approve?', context='',
        )
        clone_dir = os.path.join(self.session_path, 'worktree')
        for relpath, expected in self.expected_files.items():
            target = os.path.join(clone_dir, relpath)
            self.assertTrue(
                os.path.isfile(target),
                f"clone missing {relpath}; proxy can't review what isn't "
                f"copied (#425)",
            )
            with open(target) as f:
                actual = f.read()
            self.assertEqual(
                actual, expected,
                f'{relpath}: clone content differs from caller worktree',
            )

    def test_clone_contains_no_symlinks(self) -> None:
        self.runner._prepare_proxy_workspace(
            self.child_session, question='Approve?', context='',
        )
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

    def test_question_md_lives_at_session_root_not_in_clone(self) -> None:
        self.runner._prepare_proxy_workspace(
            self.child_session, question='Approve?', context='',
        )
        question_md = os.path.join(self.session_path, 'QUESTION.md')
        self.assertTrue(
            os.path.isfile(question_md),
            f"QUESTION.md must live at session root ({question_md}); "
            f'#425 keeps it out of the caller worktree clone',
        )
        # And NOT under the clone — walking worktree must not surface it.
        clone_dir = os.path.join(self.session_path, 'worktree')
        self.assertFalse(
            os.path.exists(os.path.join(clone_dir, 'QUESTION.md')),
            "QUESTION.md must NOT appear inside the caller-worktree "
            "clone; that pollutes the diligence-rail walk (#425)",
        )

    def test_question_md_holds_the_question_text(self) -> None:
        self.runner._prepare_proxy_workspace(
            self.child_session, question='Should we approve chapter 1?',
            context='',
        )
        with open(os.path.join(self.session_path, 'QUESTION.md')) as f:
            body = f.read()
        self.assertIn(
            'Should we approve chapter 1?', body,
            'QUESTION.md must contain the question text verbatim (#425)',
        )

    def test_launch_cwd_is_set_to_session_path(self) -> None:
        self.runner._prepare_proxy_workspace(
            self.child_session, question='Approve?', context='',
        )
        self.assertEqual(
            self.child_session.launch_cwd, self.session_path,
            f"child_session.launch_cwd must point at the session dir "
            f"({self.session_path}); the worktree-jail then bounds "
            f"reads to that subtree, covering both ./QUESTION.md and "
            f"./worktree/ (#425)",
        )

    def test_clone_is_reachable_from_launch_cwd(self) -> None:
        self.runner._prepare_proxy_workspace(
            self.child_session, question='Approve?', context='',
        )
        clone_dir = os.path.join(self.child_session.launch_cwd, 'worktree')
        for relpath in self.expected_files:
            self.assertTrue(
                os.path.isfile(os.path.join(clone_dir, relpath)),
                f"file {relpath} must be reachable from launch_cwd "
                f"as worktree/{relpath} (#425 — proxy walks the clone "
                f"subtree under cwd)",
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
        self.runner._prepare_proxy_workspace(
            self.child_session, question='Approve?', context='',
        )
        clone_dir = os.path.join(self.session_path, 'worktree')
        for relpath in self.expected_files:
            target = os.path.join(clone_dir, relpath)
            self.assertTrue(
                os.path.isfile(target),
                f'git-source: clone missing {relpath}; runner did not '
                f'dispatch through git clone correctly (#425)',
            )

    def test_git_source_clone_has_no_symlinks(self) -> None:
        self.runner._prepare_proxy_workspace(
            self.child_session, question='Approve?', context='',
        )
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

    def test_git_source_launch_cwd_is_session_path(self) -> None:
        self.runner._prepare_proxy_workspace(
            self.child_session, question='Approve?', context='',
        )
        self.assertEqual(
            self.child_session.launch_cwd, self.session_path,
            'git-source: launch_cwd must point at the session dir, '
            'same as the plain-source case (#425)',
        )


if __name__ == '__main__':
    unittest.main()
