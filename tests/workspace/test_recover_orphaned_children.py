"""Tests for ``teaparty.workspace.recovery.recover_orphaned_children``.

Cut 19: the bus is the single source of truth for orphan recovery.
Both tiers (CfA engine + chat-tier AgentSession) call this same
function.  No ``.children`` JSONL walks, no heartbeat-file reads —
the bus's ``conversations`` table records ``parent_conversation_id``,
``state``, ``worktree_path``, ``pid``, ``pid_started`` per dispatch,
and recovery walks ``children_of(parent_conv_id)`` and asks the OS
whether each PID is still alive.

These are scenario tests around the behavioral contract.  Each test
seeds a real SQLite bus with DISPATCH conversations, calls the
function, and asserts on the outcome — merge invoked or not, redispatch
called or not, conversation row closed.

The merge step itself (``squash_merge``) is stubbed because its real
implementation needs git worktrees on disk, which are out of scope for
these tests — we're verifying *that* recovery dispatches the right
calls in the right cases, not that git merging works.
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from typing import Any
from unittest.mock import patch, AsyncMock

from teaparty.messaging.conversations import (
    ConversationState,
    ConversationType,
    SqliteMessageBus,
)
from teaparty.workspace.recovery import (
    recover_orphaned_children,
    _is_pid_dead,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _seed_dispatch(
    bus: SqliteMessageBus,
    *,
    qualifier: str,
    parent: str,
    agent: str,
    worktree_path: str,
    pid: int,
    pid_started: float,
    state: ConversationState = ConversationState.ACTIVE,
) -> str:
    """Create a DISPATCH conversation with the given (pid, started) fingerprint."""
    conv = bus.create_conversation(
        ConversationType.DISPATCH, qualifier,
        agent_name=agent,
        parent_conversation_id=parent,
        state=state,
        worktree_path=worktree_path,
    )
    if pid:
        bus.set_conversation_process(conv.id, pid, pid_started)
    return conv.id


# ── _is_pid_dead (pure helper) ─────────────────────────────────────────────

class TestIsPidDead(unittest.TestCase):
    """The OS-liveness check used at recovery time."""

    def test_pid_zero_is_dead(self):
        """PID 0 means ``set_conversation_process`` never ran — dead."""
        self.assertTrue(_is_pid_dead(0, 0.0))

    def test_negative_pid_is_dead(self):
        self.assertTrue(_is_pid_dead(-1, 0.0))

    def test_live_self_pid_is_alive(self):
        """Our own PID is alive by construction."""
        # No started given → falls back to OS-only check; should be alive.
        self.assertFalse(_is_pid_dead(os.getpid(), 0.0))

    def test_obviously_dead_pid_is_dead(self):
        """A very large PID we never created is dead."""
        # Use 999999999 — wildly out of range, can't possibly be alive.
        # If by some miracle the OS has assigned this PID, started=999.0
        # disagrees with create_time and the staleness branch trips.
        self.assertTrue(_is_pid_dead(999999999, 999.0))


# ── Recovery scenarios ─────────────────────────────────────────────────────

class TestRecoverOrphanedChildren(unittest.TestCase):
    """End-to-end behavior of the bus-based recovery codepath."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self._bus_path = os.path.join(self._tmp, 'messages.db')
        self._bus = SqliteMessageBus(self._bus_path)
        self._session_worktree = os.path.join(self._tmp, 'session-wt')
        os.makedirs(self._session_worktree)
        # The parent conv (a JOB / OM root) — recovery walks its children.
        self._parent_conv_id = 'job:demo:parent'
        self._bus.create_conversation(
            ConversationType.JOB, 'demo:parent',
            agent_name='parent',
        )

    def tearDown(self):
        self._bus.close()
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_worktree(self, name: str) -> str:
        wt = os.path.join(self._tmp, f'wt-{name}')
        os.makedirs(wt, exist_ok=True)
        return wt

    def test_no_children_means_nothing_to_do(self):
        """A parent with no DISPATCH children → recovery is a no-op."""
        with patch(
            'teaparty.workspace.merge.squash_merge', new_callable=AsyncMock,
        ) as merge_mock:
            _run(recover_orphaned_children(
                parent_conversation_id=self._parent_conv_id,
                bus=self._bus,
                session_worktree=self._session_worktree,
                task='whatever',
            ))
            merge_mock.assert_not_awaited()

    def test_dead_pid_with_worktree_is_merged_and_closed(self):
        """Dead PID + extant worktree → squash_merge + state→CLOSED."""
        wt = self._make_worktree('alpha')
        conv_id = _seed_dispatch(
            self._bus, qualifier='alpha', parent=self._parent_conv_id,
            agent='alpha', worktree_path=wt,
            pid=999999999, pid_started=999.0,  # guaranteed dead
        )

        with patch(
            'teaparty.workspace.merge.squash_merge', new_callable=AsyncMock,
        ) as merge_mock:
            _run(recover_orphaned_children(
                parent_conversation_id=self._parent_conv_id,
                bus=self._bus,
                session_worktree=self._session_worktree,
                task='ship the joke',
            ))

        merge_mock.assert_awaited_once()
        kwargs = merge_mock.await_args.kwargs
        self.assertEqual(kwargs['source'], wt)
        self.assertEqual(kwargs['target'], self._session_worktree)
        self.assertIn('alpha', kwargs['message'])

        # Conversation transitioned out of ACTIVE.
        conv = self._bus.get_conversation(conv_id)
        self.assertEqual(conv.state, ConversationState.CLOSED)

    def test_already_closed_conversation_is_skipped(self):
        """CLOSED rows are not visited — recovery only acts on live rows."""
        wt = self._make_worktree('beta')
        _seed_dispatch(
            self._bus, qualifier='beta', parent=self._parent_conv_id,
            agent='beta', worktree_path=wt,
            pid=999999999, pid_started=999.0,
            state=ConversationState.CLOSED,
        )

        with patch(
            'teaparty.workspace.merge.squash_merge', new_callable=AsyncMock,
        ) as merge_mock:
            _run(recover_orphaned_children(
                parent_conversation_id=self._parent_conv_id,
                bus=self._bus,
                session_worktree=self._session_worktree,
                task='whatever',
            ))
            merge_mock.assert_not_awaited()

    def test_live_pid_is_left_alone(self):
        """Living PID + ACTIVE state → no merge, no close."""
        wt = self._make_worktree('gamma')
        conv_id = _seed_dispatch(
            self._bus, qualifier='gamma', parent=self._parent_conv_id,
            agent='gamma', worktree_path=wt,
            pid=os.getpid(), pid_started=0.0,  # our own PID — alive
        )

        with patch(
            'teaparty.workspace.merge.squash_merge', new_callable=AsyncMock,
        ) as merge_mock:
            _run(recover_orphaned_children(
                parent_conversation_id=self._parent_conv_id,
                bus=self._bus,
                session_worktree=self._session_worktree,
                task='whatever',
            ))
            merge_mock.assert_not_awaited()

        conv = self._bus.get_conversation(conv_id)
        self.assertEqual(conv.state, ConversationState.ACTIVE)

    def test_dead_pid_no_worktree_invokes_redispatch_fn(self):
        """No worktree on disk + dead PID → redispatch (no merge)."""
        # We seed worktree_path to something that doesn't exist.
        missing_wt = os.path.join(self._tmp, 'never-existed')
        _seed_dispatch(
            self._bus, qualifier='delta', parent=self._parent_conv_id,
            agent='delta', worktree_path=missing_wt,
            pid=999999999, pid_started=999.0,
        )

        captured: list[dict] = []

        async def redispatch(*, conversation, worktree_path):
            captured.append({
                'agent': conversation.agent_name,
                'worktree_path': worktree_path,
            })

        with patch(
            'teaparty.workspace.merge.squash_merge', new_callable=AsyncMock,
        ) as merge_mock:
            _run(recover_orphaned_children(
                parent_conversation_id=self._parent_conv_id,
                bus=self._bus,
                session_worktree=self._session_worktree,
                task='whatever',
                redispatch_fn=redispatch,
            ))
            merge_mock.assert_not_awaited()

        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0]['agent'], 'delta')

    def test_dead_pid_no_worktree_no_redispatch_fn_just_closes(self):
        """Without redispatch_fn, a dead-no-worktree row is just closed."""
        missing_wt = os.path.join(self._tmp, 'never-existed')
        conv_id = _seed_dispatch(
            self._bus, qualifier='epsilon', parent=self._parent_conv_id,
            agent='epsilon', worktree_path=missing_wt,
            pid=999999999, pid_started=999.0,
        )

        with patch(
            'teaparty.workspace.merge.squash_merge', new_callable=AsyncMock,
        ):
            _run(recover_orphaned_children(
                parent_conversation_id=self._parent_conv_id,
                bus=self._bus,
                session_worktree=self._session_worktree,
                task='whatever',
            ))

        conv = self._bus.get_conversation(conv_id)
        self.assertEqual(conv.state, ConversationState.CLOSED)

    def test_pid_zero_is_treated_as_dead(self):
        """A row with pid=0 (subprocess never started) → dead, gets closed."""
        wt = self._make_worktree('zeta')
        conv_id = _seed_dispatch(
            self._bus, qualifier='zeta', parent=self._parent_conv_id,
            agent='zeta', worktree_path=wt,
            pid=0, pid_started=0.0,
        )

        with patch(
            'teaparty.workspace.merge.squash_merge', new_callable=AsyncMock,
        ) as merge_mock:
            _run(recover_orphaned_children(
                parent_conversation_id=self._parent_conv_id,
                bus=self._bus,
                session_worktree=self._session_worktree,
                task='whatever',
            ))
            merge_mock.assert_awaited_once()  # worktree exists → merge

        conv = self._bus.get_conversation(conv_id)
        self.assertEqual(conv.state, ConversationState.CLOSED)

    def test_redispatch_failure_does_not_block_other_children(self):
        """One redispatch raising must not abort the rest of recovery."""
        missing_wt = os.path.join(self._tmp, 'never-existed')
        _seed_dispatch(
            self._bus, qualifier='one', parent=self._parent_conv_id,
            agent='one', worktree_path=missing_wt,
            pid=999999999, pid_started=999.0,
        )
        _seed_dispatch(
            self._bus, qualifier='two', parent=self._parent_conv_id,
            agent='two', worktree_path=missing_wt,
            pid=999999999, pid_started=999.0,
        )

        seen: list[str] = []

        async def redispatch(*, conversation, worktree_path):
            seen.append(conversation.agent_name)
            if conversation.agent_name == 'one':
                raise RuntimeError('boom')

        _run(recover_orphaned_children(
            parent_conversation_id=self._parent_conv_id,
            bus=self._bus,
            session_worktree=self._session_worktree,
            task='whatever',
            redispatch_fn=redispatch,
        ))

        self.assertEqual(sorted(seen), ['one', 'two'],
                         'both children must be visited even though one raised')

    def test_emits_recovery_log_events_when_event_bus_provided(self):
        """When an event_bus is given, every merge / redispatch emits LOG."""
        wt = self._make_worktree('alpha')
        _seed_dispatch(
            self._bus, qualifier='alpha', parent=self._parent_conv_id,
            agent='alpha', worktree_path=wt,
            pid=999999999, pid_started=999.0,
        )
        missing_wt = os.path.join(self._tmp, 'never-existed')
        _seed_dispatch(
            self._bus, qualifier='beta', parent=self._parent_conv_id,
            agent='beta', worktree_path=missing_wt,
            pid=999999999, pid_started=999.0,
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
                parent_conversation_id=self._parent_conv_id,
                bus=self._bus,
                session_worktree=self._session_worktree,
                task='whatever',
                session_id='sess-1',
                event_bus=_Bus(),
                redispatch_fn=redispatch,
            ))

        categories = [e.data['category'] for e in events]
        self.assertIn('recovery_merge', categories)
        self.assertIn('recovery_redispatch', categories)
        for e in events:
            self.assertEqual(e.session_id, 'sess-1')

    def test_recovery_only_acts_on_dispatch_type(self):
        """JOB / TASK / OM rows under a parent are not "orphans" to merge.

        Only DISPATCH conversations represent dispatched subprocesses
        with worktrees + PIDs.  Other types (a JOB hanging under
        another JOB, say) are organizational and recovery must skip
        them — merging a JOB row's worktree would be category-error.
        """
        # Seed a JOB child (not a DISPATCH).
        self._bus.create_conversation(
            ConversationType.JOB, 'demo:nested-job',
            agent_name='nested',
            parent_conversation_id=self._parent_conv_id,
            worktree_path=self._make_worktree('nested'),
        )

        with patch(
            'teaparty.workspace.merge.squash_merge', new_callable=AsyncMock,
        ) as merge_mock:
            _run(recover_orphaned_children(
                parent_conversation_id=self._parent_conv_id,
                bus=self._bus,
                session_worktree=self._session_worktree,
                task='whatever',
            ))
            merge_mock.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
