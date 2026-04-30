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

    def test_launch_cwd_is_set_to_clone_path(self) -> None:
        self.runner._prepare_proxy_workspace(
            self.child_session, question='Approve?', context='',
        )
        clone_dir = os.path.join(self.session_path, 'worktree')
        self.assertEqual(
            self.child_session.launch_cwd, clone_dir,
            f"child_session.launch_cwd must point at the clone "
            f"({clone_dir}); the proxy launches there so its file "
            f"reads land in the caller's worktree subtree (#425)",
        )


if __name__ == '__main__':
    unittest.main()
