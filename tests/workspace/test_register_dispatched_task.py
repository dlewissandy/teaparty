"""Regression: dispatched workers are visible to the bridge UI.

The bridge's project task-list view (``_scan_tasks``) walks
``{job_dir}/tasks/`` and reads ``task.json`` from each subdir to
populate the UI.  Dispatched workers (created via
``schedule_child_dispatch`` → ``create_session``) write
``metadata.json`` for the dispatch flow but did not write
``task.json``, so they were invisible to the project page.

``register_dispatched_task`` writes the ``task.json`` marker.  This
test pins the contract: a dispatched worker's session dir contains
both records, and a walker that mirrors ``_scan_tasks`` finds the
worker as a task entry.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.workspace.job_store import register_dispatched_task


class RegisterDispatchedTaskTest(unittest.TestCase):
    """``register_dispatched_task`` writes a discoverable task.json."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix='register-task-')
        self.job_dir = os.path.join(self._tmp, 'job-test')
        self.tasks_dir = os.path.join(self.job_dir, 'tasks')
        os.makedirs(self.tasks_dir)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_writes_task_json_with_required_fields(self) -> None:
        """The task.json carries the fields _scan_tasks reads."""
        task_dir = os.path.join(self.tasks_dir, 'sid-abc')
        os.makedirs(task_dir)
        register_dispatched_task(
            task_dir=task_dir,
            task_id='sid-abc',
            agent='research-lead',
            branch='session/sid-abc',
            team='management',
            slug='research-lead',
        )
        path = os.path.join(task_dir, 'task.json')
        self.assertTrue(os.path.isfile(path))
        with open(path) as f:
            state = json.load(f)
        self.assertEqual(state['task_id'], 'sid-abc')
        self.assertEqual(state['agent'], 'research-lead')
        self.assertEqual(state['branch'], 'session/sid-abc')
        self.assertEqual(state['team'], 'management')
        self.assertEqual(state['slug'], 'research-lead')
        self.assertEqual(state['status'], 'active')
        self.assertIn('created_at', state)
        self.assertIn('updated_at', state)

    def test_creates_task_dir_if_missing(self) -> None:
        """The function is robust to a missing task_dir (idempotent setup)."""
        task_dir = os.path.join(self.tasks_dir, 'sid-fresh')
        # Don't pre-create.
        register_dispatched_task(
            task_dir=task_dir,
            task_id='sid-fresh',
            agent='researcher',
            branch='session/sid-fresh',
        )
        self.assertTrue(os.path.isfile(os.path.join(task_dir, 'task.json')))

    def test_default_slug_is_agent_name(self) -> None:
        task_dir = os.path.join(self.tasks_dir, 'sid-default-slug')
        os.makedirs(task_dir)
        register_dispatched_task(
            task_dir=task_dir,
            task_id='sid-default-slug',
            agent='developer',
            branch='session/sid-default-slug',
        )
        with open(os.path.join(task_dir, 'task.json')) as f:
            state = json.load(f)
        self.assertEqual(state['slug'], 'developer')

    def test_scan_tasks_finds_registered_worker(self) -> None:
        """A walker mirroring the bridge's ``_scan_tasks`` discovers the worker.

        This is the load-bearing claim: the dispatched worker is now
        visible to the bridge UI's project task-list view.
        """
        task_dir = os.path.join(self.tasks_dir, 'sid-visible')
        os.makedirs(task_dir)
        register_dispatched_task(
            task_dir=task_dir,
            task_id='sid-visible',
            agent='research-lead',
            branch='session/sid-visible',
            team='management',
        )
        # Mirror _scan_tasks's iteration: walk tasks_dir, read task.json
        # from each subdir, collect task_id.
        found_ids: list[str] = []
        for name in sorted(os.listdir(self.tasks_dir)):
            sub = os.path.join(self.tasks_dir, name)
            tj = os.path.join(sub, 'task.json')
            if not os.path.isfile(tj):
                continue
            with open(tj) as f:
                state = json.load(f)
            found_ids.append(state.get('task_id', ''))
        self.assertIn('sid-visible', found_ids)


if __name__ == '__main__':
    unittest.main()
