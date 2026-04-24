"""Tests for ``teaparty.workspace.recovery.recover_orphaned_children``.

The function reconciles ``{infra_dir}/.children`` after a parent
restart: completed children get squash-merged into the parent worktree,
dead non-terminal children get re-dispatched (via a caller-supplied
callable), live children are left alone, and the registry is compacted.

These are scenario tests around the behavioral contract.  Each test
sets up a real ``.children`` registry on disk plus matching heartbeat
files, calls the function, and asserts on the outcome — merge invoked
or not, redispatch_fn called or not, registry compacted to the right
shape.

The merge step itself (``squash_merge``) is stubbed because its real
implementation needs git worktrees on disk, which are out of scope for
these tests — we're verifying *that* recovery dispatches the right
calls in the right cases, not that git merging works.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
import unittest
from typing import Any
from unittest.mock import patch, AsyncMock

from teaparty.workspace.recovery import (
    recover_orphaned_children,
    find_dispatch_worktree,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _write_heartbeat(path: str, *, status: str, age_seconds: float = 0.0,
                     pid: int | None = None) -> None:
    """Write a heartbeat file with a given status and age.

    ``age_seconds=0`` means "fresh now"; pass a value larger than the
    staleness threshold (120s) to make ``is_heartbeat_stale`` return
    True for non-terminal entries.

    ``pid=None`` defaults to a guaranteed-dead PID (1) so the staleness
    check's PID liveness probe agrees.
    """
    if pid is None:
        pid = 1  # init — for staleness, we want any live-PID check to
                 # not save us.  Combined with a stale mtime + non-
                 # terminal status, scan_children classifies as 'dead'.
    data = {
        'pid': pid,
        'parent_heartbeat': '',
        'role': 'team',
        'started': time.time() - age_seconds,
        'status': status,
    }
    with open(path, 'w') as f:
        json.dump(data, f)
    if age_seconds > 0:
        old = time.time() - age_seconds
        os.utime(path, (old, old))


def _write_cfa_state(path: str, state: str) -> None:
    """Write a minimal CfA state file."""
    data = {
        'phase': 'terminal' if state in ('DONE', 'WITHDRAWN') else 'execution',
        'state': state,
        'history': [],
        'backtrack_count': 0,
        'task_id': '',
    }
    with open(path, 'w') as f:
        json.dump(data, f)


def _make_child(*, root: str, team: str, status: str, cfa_state: str | None,
                heartbeat_age: float = 0.0,
                with_worktree: bool = True) -> dict:
    """Lay out one child's infra dir + heartbeat + optional CfA state.

    Returns the child registry entry dict.
    """
    child_infra = os.path.join(root, f'child-{team}')
    os.makedirs(child_infra, exist_ok=True)

    if with_worktree:
        wt = os.path.join(child_infra, 'worktree')
        os.makedirs(wt, exist_ok=True)

    hb_path = os.path.join(child_infra, '.heartbeat')
    _write_heartbeat(hb_path, status=status, age_seconds=heartbeat_age)

    if cfa_state is not None:
        _write_cfa_state(
            os.path.join(child_infra, '.cfa-state.json'), cfa_state,
        )

    return {
        'heartbeat': hb_path,
        'team': team,
        'task_id': None,
        'status': 'active',
    }


def _write_children_registry(path: str, entries: list[dict]) -> None:
    with open(path, 'w') as f:
        for entry in entries:
            f.write(json.dumps(entry) + '\n')


def _read_children_registry(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


# ── find_dispatch_worktree (pure helper) ───────────────────────────────────

class TestFindDispatchWorktree(unittest.TestCase):
    """The job-store layout convention: worktree at ``{infra}/worktree/``."""

    def test_returns_worktree_path_when_directory_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            wt = os.path.join(tmp, 'worktree')
            os.makedirs(wt)
            self.assertEqual(find_dispatch_worktree(tmp), wt)

    def test_returns_empty_when_worktree_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(find_dispatch_worktree(tmp), '')

    def test_returns_empty_when_worktree_is_a_file_not_a_directory(self):
        """A file at the worktree path is not a worktree."""
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, 'worktree'), 'w') as f:
                f.write('not a dir')
            self.assertEqual(find_dispatch_worktree(tmp), '')


# ── Recovery scenarios ─────────────────────────────────────────────────────

class TestRecoverOrphanedChildren(unittest.TestCase):
    """End-to-end behavior around the .children registry."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._infra = os.path.join(self._tmp, 'parent-infra')
        os.makedirs(self._infra)
        self._session_worktree = os.path.join(self._tmp, 'session-wt')
        os.makedirs(self._session_worktree)

    def tearDown(self):
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_no_children_registry_returns_immediately(self):
        """Common case on first run — no registry, recovery is a no-op."""
        # Patch the merge so any accidental call would explode the test.
        with patch(
            'teaparty.workspace.merge.squash_merge', new_callable=AsyncMock,
        ) as merge_mock:
            _run(recover_orphaned_children(
                infra_dir=self._infra,
                session_worktree=self._session_worktree,
                task='whatever',
            ))
            merge_mock.assert_not_awaited()

    def test_completed_done_child_is_merged_and_compacted(self):
        """Completed heartbeat + DONE state → squash_merge + drop from registry."""
        child = _make_child(
            root=self._tmp, team='alpha',
            status='completed', cfa_state='DONE',
        )
        children_path = os.path.join(self._infra, '.children')
        _write_children_registry(children_path, [child])

        with patch(
            'teaparty.workspace.merge.squash_merge', new_callable=AsyncMock,
        ) as merge_mock:
            _run(recover_orphaned_children(
                infra_dir=self._infra,
                session_worktree=self._session_worktree,
                task='ship the joke',
            ))

        merge_mock.assert_awaited_once()
        kwargs = merge_mock.await_args.kwargs
        self.assertEqual(
            os.path.realpath(kwargs['source']),
            os.path.realpath(os.path.join(
                os.path.dirname(child['heartbeat']), 'worktree')),
        )
        self.assertEqual(
            os.path.realpath(kwargs['target']),
            os.path.realpath(self._session_worktree),
        )
        self.assertIn('alpha', kwargs['message'])

        # Registry compacted: completed entries removed.
        self.assertEqual(_read_children_registry(children_path), [])

    def test_completed_but_cfa_state_disagrees_is_skipped(self):
        """Heartbeat says 'completed' but CfA state isn't DONE → no merge.

        Half-finished work must not be merged automatically — a status
        mismatch is a signal of a bug or a partial shutdown, not of
        completion.
        """
        child = _make_child(
            root=self._tmp, team='beta',
            status='completed', cfa_state='EXECUTE',
        )
        _write_children_registry(
            os.path.join(self._infra, '.children'), [child],
        )

        with patch(
            'teaparty.workspace.merge.squash_merge', new_callable=AsyncMock,
        ) as merge_mock:
            _run(recover_orphaned_children(
                infra_dir=self._infra,
                session_worktree=self._session_worktree,
                task='whatever',
            ))
            merge_mock.assert_not_awaited()

    def test_dead_non_terminal_child_invokes_redispatch_fn(self):
        """Stale mtime + non-terminal status + dead PID → redispatch_fn."""
        child = _make_child(
            root=self._tmp, team='gamma',
            status='running', cfa_state='EXECUTE',
            heartbeat_age=300.0,  # well past the 120s staleness threshold
        )
        _write_children_registry(
            os.path.join(self._infra, '.children'), [child],
        )

        captured: list[dict] = []

        async def redispatch(*, child, worktree_path, child_infra):
            captured.append({
                'team': child['team'],
                'worktree_path': worktree_path,
                'child_infra': child_infra,
            })

        _run(recover_orphaned_children(
            infra_dir=self._infra,
            session_worktree=self._session_worktree,
            task='whatever',
            redispatch_fn=redispatch,
        ))

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]['team'], 'gamma')
        self.assertTrue(captured[0]['worktree_path'].endswith('worktree'))
        self.assertTrue(os.path.isdir(captured[0]['worktree_path']))

    def test_dead_child_without_redispatch_fn_is_logged_not_relaunched(self):
        """No callable supplied → the dead child is not re-launched.

        The caller has chosen to take responsibility for the worktree;
        recovery must not call into anything we didn't explicitly opt
        into.  Without a callable, we just log + leave the worktree in
        place + drop nothing extra from the registry.
        """
        child = _make_child(
            root=self._tmp, team='delta',
            status='running', cfa_state='EXECUTE',
            heartbeat_age=300.0,
        )
        _write_children_registry(
            os.path.join(self._infra, '.children'), [child],
        )

        # No redispatch_fn passed.  Should not raise; merge should not run.
        with patch(
            'teaparty.workspace.merge.squash_merge', new_callable=AsyncMock,
        ) as merge_mock:
            _run(recover_orphaned_children(
                infra_dir=self._infra,
                session_worktree=self._session_worktree,
                task='whatever',
            ))
            merge_mock.assert_not_awaited()

    def test_live_child_is_left_alone(self):
        """Fresh heartbeat with non-terminal status → no merge, no redispatch."""
        child = _make_child(
            root=self._tmp, team='epsilon',
            status='running', cfa_state='EXECUTE',
            heartbeat_age=0.0,  # fresh
        )
        _write_children_registry(
            os.path.join(self._infra, '.children'), [child],
        )

        captured: list[dict] = []

        async def redispatch(**kw):
            captured.append(kw)

        with patch(
            'teaparty.workspace.merge.squash_merge', new_callable=AsyncMock,
        ) as merge_mock:
            _run(recover_orphaned_children(
                infra_dir=self._infra,
                session_worktree=self._session_worktree,
                task='whatever',
                redispatch_fn=redispatch,
            ))
            merge_mock.assert_not_awaited()

        self.assertEqual(captured, [])

    def test_redispatch_failure_does_not_block_other_children(self):
        """One redispatch raising must not abort the rest of recovery.

        The contract: recovery is best-effort.  If one child can't be
        re-dispatched, we log it and move on so other children aren't
        stranded by an unrelated failure.
        """
        c1 = _make_child(
            root=self._tmp, team='one',
            status='running', cfa_state='EXECUTE',
            heartbeat_age=300.0,
        )
        c2 = _make_child(
            root=self._tmp, team='two',
            status='running', cfa_state='EXECUTE',
            heartbeat_age=300.0,
        )
        _write_children_registry(
            os.path.join(self._infra, '.children'), [c1, c2],
        )

        seen: list[str] = []

        async def redispatch(*, child, worktree_path, child_infra):
            seen.append(child['team'])
            if child['team'] == 'one':
                raise RuntimeError('boom')

        _run(recover_orphaned_children(
            infra_dir=self._infra,
            session_worktree=self._session_worktree,
            task='whatever',
            redispatch_fn=redispatch,
        ))

        self.assertEqual(sorted(seen), ['one', 'two'],
                         'both children must be visited even though one raised')

    def test_emits_recovery_log_events_when_event_bus_provided(self):
        """When an event_bus is given, every merge / redispatch emits LOG."""
        completed = _make_child(
            root=self._tmp, team='alpha',
            status='completed', cfa_state='DONE',
        )
        dead = _make_child(
            root=self._tmp, team='beta',
            status='running', cfa_state='EXECUTE',
            heartbeat_age=300.0,
        )
        _write_children_registry(
            os.path.join(self._infra, '.children'), [completed, dead],
        )

        events: list[Any] = []

        class _Bus:
            async def publish(self, ev):
                events.append(ev)

        async def redispatch(**kw): pass

        with patch(
            'teaparty.workspace.merge.squash_merge', new_callable=AsyncMock,
        ):
            _run(recover_orphaned_children(
                infra_dir=self._infra,
                session_worktree=self._session_worktree,
                task='whatever',
                session_id='sess-1',
                event_bus=_Bus(),
                redispatch_fn=redispatch,
            ))

        categories = [e.data['category'] for e in events]
        self.assertIn('recovery_merge', categories)
        self.assertIn('recovery_redispatch', categories)
        # Every event must carry the parent session_id we passed.
        for e in events:
            self.assertEqual(e.session_id, 'sess-1')

    def test_no_event_bus_means_silent_recovery(self):
        """``event_bus=None`` → recovery happens without trying to publish."""
        child = _make_child(
            root=self._tmp, team='alpha',
            status='completed', cfa_state='DONE',
        )
        _write_children_registry(
            os.path.join(self._infra, '.children'), [child],
        )

        # If recovery tries to use a missing event_bus it will AttributeError.
        with patch(
            'teaparty.workspace.merge.squash_merge', new_callable=AsyncMock,
        ):
            _run(recover_orphaned_children(
                infra_dir=self._infra,
                session_worktree=self._session_worktree,
                task='whatever',
                event_bus=None,
            ))


if __name__ == '__main__':
    unittest.main()
