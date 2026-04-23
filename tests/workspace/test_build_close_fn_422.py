"""Behavioral tests for build_close_fn, the shared close_fn factory (#422).

Both chat tier (AgentSession._ensure_bus_listener) and CfA
(Orchestrator.run) install the same close_fn built by this factory.
This test file pins its behaviour end-to-end:

- The dispatched child's worktree is squash-merged into its parent
  and the session dir is removed.
- In-flight child tasks inside the subtree are cancelled before the
  rmtree so nothing writes into a directory being deleted.
- ``dispatch_completed`` events fire once per removed session,
  deepest-first.
- A merge conflict surfaces as a structured error to the calling
  agent and leaves the worktree on disk (no events, no map eviction).
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import uuid

from teaparty.runners.launcher import (
    create_session, _save_session_metadata as _save_meta,
    record_child_session,
)
from teaparty.workspace.close_conversation import build_close_fn


def _init_git_repo() -> str:
    """Initialise a clean git repo with one commit; return its path."""
    path = tempfile.mkdtemp(prefix='tp422-')
    subprocess.run(['git', 'init', '-b', 'main'], cwd=path, check=True,
                   capture_output=True)
    subprocess.run(['git', 'config', 'user.email', 't@e.com'], cwd=path,
                   check=True)
    subprocess.run(['git', 'config', 'user.name', 't'], cwd=path, check=True)
    with open(os.path.join(path, 'README'), 'w') as f:
        f.write('hello\n')
    subprocess.run(['git', 'add', '.'], cwd=path, check=True)
    subprocess.run(['git', 'commit', '-m', 'init'], cwd=path, check=True,
                   capture_output=True)
    return path


def _make_teaparty_home(repo_root: str) -> str:
    """Create a .teaparty/management directory under *repo_root*."""
    tp = os.path.join(repo_root, '.teaparty')
    mgmt = os.path.join(tp, 'management')
    os.makedirs(os.path.join(mgmt, 'sessions'), exist_ok=True)
    return tp


class TestBuildCloseFnMerge(unittest.IsolatedAsyncioTestCase):
    """close_fn merges a subchat's worktree back into its parent."""

    def setUp(self) -> None:
        self._repo = _init_git_repo()
        self._tp = _make_teaparty_home(self._repo)

    def tearDown(self) -> None:
        shutil.rmtree(self._repo, ignore_errors=True)

    async def _make_child_with_worktree(self, parent, child_name='child'):
        """Create a child session with its own branch + worktree ready to merge."""
        child = create_session(agent_name=child_name, scope='management',
                               teaparty_home=self._tp)
        wt = os.path.join(child.path, 'worktree')
        branch = f'session/{child.id}'
        subprocess.run(
            ['git', 'worktree', 'add', '-b', branch, wt, 'main'],
            cwd=self._repo, check=True, capture_output=True,
        )
        # Make a distinct commit in the child's worktree so merge has content.
        with open(os.path.join(wt, 'CHILD_FILE'), 'w') as f:
            f.write('from the child\n')
        subprocess.run(['git', 'add', '.'], cwd=wt, check=True)
        subprocess.run(['git', 'commit', '-m', 'child work'], cwd=wt,
                       check=True, capture_output=True)

        child.worktree_path = wt
        child.worktree_branch = branch
        child.merge_target_repo = self._repo
        child.merge_target_worktree = self._repo
        child.merge_target_branch = 'main'
        child.parent_session_id = parent.id
        _save_meta(child)

        ctx_id = f'req-{uuid.uuid4().hex[:8]}'
        record_child_session(parent, request_id=ctx_id, child_session_id=child.id)
        return child

    async def test_close_fn_merges_child_worktree_and_emits_event(self):
        """close_fn succeeds end-to-end: merge, rmtree, dispatch_completed."""
        parent = create_session(agent_name='lead', scope='management',
                                teaparty_home=self._tp)
        child = await self._make_child_with_worktree(parent)

        events: list[dict] = []
        close_fn = build_close_fn(
            dispatch_session=parent,
            teaparty_home=self._tp,
            scope='management',
            tasks_by_child={},
            on_dispatch=events.append,
            agent_name='lead',
        )

        result = await close_fn(f'dispatch:{child.id}')

        self.assertEqual(result.get('status'), 'ok',
                         f'merge should have succeeded: {result}')
        # Child file is now on main in the repo.
        self.assertTrue(
            os.path.isfile(os.path.join(self._repo, 'CHILD_FILE')),
            'child worktree content must be merged into the parent repo',
        )
        # Session dir is gone.
        self.assertFalse(
            os.path.isdir(os.path.join(
                self._tp, 'management', 'sessions', child.id)),
            'closed session directory must be rmtree-d',
        )
        # dispatch_completed emitted once for the child.
        completed = [e for e in events if e.get('type') == 'dispatch_completed']
        self.assertEqual(len(completed), 1,
                         f'expected 1 dispatch_completed, got {events}')
        self.assertEqual(completed[0]['child_session_id'], child.id)
        self.assertEqual(completed[0]['parent_session_id'], parent.id)

    async def test_close_fn_cancels_in_flight_tasks_in_subtree(self):
        """In-flight child tasks are cancelled before rmtree."""
        parent = create_session(agent_name='lead', scope='management',
                                teaparty_home=self._tp)
        child = await self._make_child_with_worktree(parent)

        started = asyncio.Event()

        async def _never_returns():
            started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                raise

        task = asyncio.create_task(_never_returns())
        await started.wait()
        tasks_by_child = {child.id: task}

        close_fn = build_close_fn(
            dispatch_session=parent,
            teaparty_home=self._tp,
            scope='management',
            tasks_by_child=tasks_by_child,
            on_dispatch=None,
            agent_name='lead',
        )
        result = await close_fn(f'dispatch:{child.id}')

        self.assertEqual(result.get('status'), 'ok')
        self.assertTrue(task.cancelled() or task.done(),
                        'in-flight task must be cancelled before rmtree')
        self.assertNotIn(child.id, tasks_by_child,
                         'cancelled task entry must be removed from the dict')


class TestBuildCloseFnConflict(unittest.IsolatedAsyncioTestCase):
    """Merge conflict surfaces as a structured error and preserves state."""

    def setUp(self) -> None:
        self._repo = _init_git_repo()
        self._tp = _make_teaparty_home(self._repo)

    def tearDown(self) -> None:
        shutil.rmtree(self._repo, ignore_errors=True)

    async def test_conflict_returns_structured_status_and_no_events(self):
        parent = create_session(agent_name='lead', scope='management',
                                teaparty_home=self._tp)

        # Parent: modify the same file on main.
        with open(os.path.join(self._repo, 'README'), 'w') as f:
            f.write('parent edit\n')
        subprocess.run(['git', 'add', '.'], cwd=self._repo, check=True)
        subprocess.run(['git', 'commit', '-m', 'parent edit'], cwd=self._repo,
                       check=True, capture_output=True)

        # Child: worktree forked from the original main, touching the same file.
        child = create_session(agent_name='child', scope='management',
                               teaparty_home=self._tp)
        wt = os.path.join(child.path, 'worktree')
        branch = f'session/{child.id}'
        # Use the original initial commit as the fork point so the child
        # branch and main both edit README from different parents.
        initial_commit = subprocess.run(
            ['git', 'rev-parse', 'HEAD~1'], cwd=self._repo,
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        subprocess.run(
            ['git', 'worktree', 'add', '-b', branch, wt, initial_commit],
            cwd=self._repo, check=True, capture_output=True,
        )
        with open(os.path.join(wt, 'README'), 'w') as f:
            f.write('child edit\n')
        subprocess.run(['git', 'add', '.'], cwd=wt, check=True)
        subprocess.run(['git', 'commit', '-m', 'child edit'], cwd=wt,
                       check=True, capture_output=True)

        child.worktree_path = wt
        child.worktree_branch = branch
        child.merge_target_repo = self._repo
        child.merge_target_worktree = self._repo
        child.merge_target_branch = 'main'
        child.parent_session_id = parent.id
        _save_meta(child)

        record_child_session(parent, request_id='req-1',
                             child_session_id=child.id)

        events: list[dict] = []
        close_fn = build_close_fn(
            dispatch_session=parent,
            teaparty_home=self._tp,
            scope='management',
            tasks_by_child={},
            on_dispatch=events.append,
            agent_name='lead',
        )
        result = await close_fn(f'dispatch:{child.id}')

        self.assertNotEqual(result.get('status'), 'ok',
                            'merge must not succeed when both sides edit README')
        # Worktree + session dir still on disk so the agent can resolve and retry.
        self.assertTrue(
            os.path.isdir(os.path.join(
                self._tp, 'management', 'sessions', child.id)),
            'session dir must remain on disk on conflict',
        )
        # No dispatch_completed event emitted for the un-closed child.
        completed = [e for e in events if e.get('type') == 'dispatch_completed']
        self.assertEqual(completed, [],
                         'dispatch_completed must NOT fire on merge failure')


if __name__ == '__main__':
    unittest.main()
