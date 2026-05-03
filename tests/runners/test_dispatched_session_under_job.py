"""Regression: dispatched task sessions live under the dispatching job.

Before option C, a dispatched worker's session was created under
``{teaparty_home}/<scope>/sessions/<sid>/`` — keyed on the agent's
home scope.  A research lead doing work for a joke-book job ended up
with its worktree at ``teaparty/.teaparty/management/sessions/<sid>/
worktree/``, which (a) physically nested operational worktrees inside
the catalog tree, causing the deny-pattern collision, (b) decoupled
the worker's filesystem location from the job that owned its lifetime,
and (c) made it impossible to discover all work belonging to a job
by walking the job's directory.

Option C: dispatched workers live at
``{job_dir}/tasks/<sid>/``.  ``create_session`` and ``load_session``
honor a ``parent_dir`` parameter that overrides the catalog-keyed
default; ``ChildDispatchContext.tasks_dir`` carries the job's path
through the dispatch flow.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.runners.launcher import create_session, load_session


class CreateSessionUnderJobDirTest(unittest.TestCase):
    """``create_session`` with ``parent_dir`` lands under the supplied dir."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix='session-under-job-')
        self.teaparty_home = os.path.join(self._tmp, '.teaparty')
        self.job_dir = os.path.join(
            self._tmp, 'project-repo', '.teaparty', 'jobs', 'job-test',
        )
        os.makedirs(self.teaparty_home)
        os.makedirs(self.job_dir)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_legacy_layout_used_when_parent_dir_omitted(self) -> None:
        """Without ``parent_dir``, sessions land at the catalog-keyed path.

        Top-level chat sessions (OM, project-lead chat) keep this layout.
        """
        session = create_session(
            agent_name='office-manager',
            scope='management',
            teaparty_home=self.teaparty_home,
            session_id='abc123',
        )
        expected = os.path.join(
            self.teaparty_home, 'management', 'sessions', 'abc123',
        )
        self.assertEqual(session.path, expected)
        self.assertTrue(os.path.isfile(os.path.join(expected, 'metadata.json')))

    def test_parent_dir_overrides_default_layout(self) -> None:
        """With ``parent_dir`` set, the session lands under that directory.

        The reported research-lead failure resolves to this case: the
        worker's session lives under the job that dispatched it, not
        under the catalog.
        """
        tasks_dir = os.path.join(self.job_dir, 'tasks')
        session = create_session(
            agent_name='research-lead',
            scope='management',
            teaparty_home=self.teaparty_home,
            session_id='abc123',
            parent_dir=tasks_dir,
        )
        expected = os.path.join(tasks_dir, 'abc123')
        self.assertEqual(session.path, expected)
        self.assertTrue(os.path.isfile(os.path.join(expected, 'metadata.json')))

    def test_dispatched_session_path_is_inside_job_dir(self) -> None:
        """The dispatched-worker path is a descendant of the job dir.

        This is the structural invariant Option C guarantees: walking
        the job's directory tree reaches every worker doing work for it.
        """
        tasks_dir = os.path.join(self.job_dir, 'tasks')
        session = create_session(
            agent_name='research-lead',
            scope='management',
            teaparty_home=self.teaparty_home,
            session_id='xyz789',
            parent_dir=tasks_dir,
        )
        self.assertTrue(
            session.path.startswith(self.job_dir + os.sep),
            f'{session.path!r} must live under the job dir {self.job_dir!r}',
        )

    def test_dispatched_session_path_is_outside_catalog(self) -> None:
        """The dispatched-worker path does not nest under the catalog.

        Confirms the deny-pattern collision is structurally prevented:
        a worker's worktree cannot be inside ``.teaparty/management/``
        or ``.teaparty/project/`` if it lives under the job dir.
        """
        tasks_dir = os.path.join(self.job_dir, 'tasks')
        session = create_session(
            agent_name='research-lead',
            scope='management',
            teaparty_home=self.teaparty_home,
            session_id='xyz789',
            parent_dir=tasks_dir,
        )
        catalog_management = os.path.join(self.teaparty_home, 'management')
        self.assertFalse(
            session.path.startswith(catalog_management + os.sep),
            f'{session.path!r} must not nest under catalog management/',
        )


class LoadSessionFromJobDirTest(unittest.TestCase):
    """``load_session`` finds sessions in either layout."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix='load-session-')
        self.teaparty_home = os.path.join(self._tmp, '.teaparty')
        self.job_dir = os.path.join(
            self._tmp, 'project-repo', '.teaparty', 'jobs', 'job-test',
        )
        os.makedirs(self.teaparty_home)
        os.makedirs(self.job_dir)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_loads_from_parent_dir_when_set(self) -> None:
        tasks_dir = os.path.join(self.job_dir, 'tasks')
        created = create_session(
            agent_name='research-lead',
            scope='management',
            teaparty_home=self.teaparty_home,
            session_id='sid1',
            parent_dir=tasks_dir,
        )
        loaded = load_session(
            agent_name='research-lead',
            scope='management',
            teaparty_home=self.teaparty_home,
            session_id='sid1',
            parent_dir=tasks_dir,
        )
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.path, created.path)

    def test_loads_from_legacy_layout_as_fallback(self) -> None:
        """Sessions created before the layout change still load.

        ``parent_dir`` is supplied (the dispatch context always sets it
        for CfA jobs after the fix) but the on-disk session is still at
        the legacy catalog-keyed path — load_session must find it.
        """
        # Create at the legacy location.
        legacy = create_session(
            agent_name='research-lead',
            scope='management',
            teaparty_home=self.teaparty_home,
            session_id='sid-legacy',
        )
        tasks_dir = os.path.join(self.job_dir, 'tasks')
        loaded = load_session(
            agent_name='research-lead',
            scope='management',
            teaparty_home=self.teaparty_home,
            session_id='sid-legacy',
            parent_dir=tasks_dir,
        )
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.path, legacy.path)

    def test_returns_none_when_neither_layout_has_session(self) -> None:
        tasks_dir = os.path.join(self.job_dir, 'tasks')
        loaded = load_session(
            agent_name='research-lead',
            scope='management',
            teaparty_home=self.teaparty_home,
            session_id='nonexistent',
            parent_dir=tasks_dir,
        )
        self.assertIsNone(loaded)


if __name__ == '__main__':
    unittest.main()
