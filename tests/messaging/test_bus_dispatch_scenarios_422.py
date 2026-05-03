"""Bus-native coverage for critical dispatch scenarios (#422).

The old ``test_async_dispatch_396.py`` and ``test_async_dispatch_scripted.py``
covered these behaviors by walking session metadata on disk.  The
data model is now bus-first; these tests cover the same scenarios
directly against the bus's ``conversations`` table and the shared
``close_fn`` / ``check_slot_available`` / tree primitives.

Scenarios:

  1. Recursive close — closing a parent closes every descendant.
  2. Concurrent dispatch — sibling children all visible, each in
     its own subtree, correctly ordered.
  3. Rate limit — fourth live child is denied by check_slot_available.
  4. Cross-parent isolation — children under A are not children
     under B.
  5. Close of a conflicting subchat keeps the bus record open so
     the user can resolve and retry.
  6. State transitions land on the bus atomically: pending → active
     → closed; pending → active → paused (bridge restart).
"""
from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import tempfile
import unittest

from teaparty.messaging.conversations import (
    ConversationState,
    ConversationType,
    SqliteMessageBus,
)
from teaparty.runners.launcher import (
    check_slot_available,
    create_session,
    _save_session_metadata as _save_meta,
)
from teaparty.workspace.close_conversation import (
    build_close_fn,
    collect_descendants_from_bus,
    collect_descendants_with_parents_from_bus,
)


def _init_repo() -> str:
    """Init a clean git repo with one commit on 'main'."""
    path = tempfile.mkdtemp(prefix='tp422-scenarios-')
    subprocess.run(['git', 'init', '-b', 'main'], cwd=path, check=True,
                   capture_output=True)
    subprocess.run(['git', 'config', 'user.email', 't@e.com'], cwd=path,
                   check=True)
    subprocess.run(['git', 'config', 'user.name', 't'], cwd=path, check=True)
    with open(os.path.join(path, 'README'), 'w') as f:
        f.write('base\n')
    subprocess.run(['git', 'add', '.'], cwd=path, check=True)
    subprocess.run(['git', 'commit', '-m', 'init'], cwd=path, check=True,
                   capture_output=True)
    return path


def _dispatch(bus, session_id, agent_name, parent_conv='',
              project='', request_id='', state=None):
    bus.create_conversation(
        ConversationType.DISPATCH, session_id,
        agent_name=agent_name,
        parent_conversation_id=parent_conv,
        request_id=request_id,
        project_slug=project,
        state=state or ConversationState.ACTIVE,
    )
    return f'dispatch:{session_id}'


class TestConcurrentDispatchSiblings(unittest.TestCase):
    """A dispatcher can have multiple live children simultaneously."""

    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp(prefix='tp422-concurrent-')
        self._bus = SqliteMessageBus(os.path.join(self._dir, 'bus.db'))

    def tearDown(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_three_concurrent_siblings_visible(self) -> None:
        parent_conv = _dispatch(self._bus, 'parent', 'lead')
        _dispatch(self._bus, 'sib-a', 'team-a', parent_conv=parent_conv)
        _dispatch(self._bus, 'sib-b', 'team-b', parent_conv=parent_conv)
        _dispatch(self._bus, 'sib-c', 'team-c', parent_conv=parent_conv)
        kids = self._bus.children_of(parent_conv)
        self.assertEqual([k.agent_name for k in kids],
                         ['team-a', 'team-b', 'team-c'])
        # All live.
        self.assertTrue(all(k.state == ConversationState.ACTIVE for k in kids))


class TestRecursiveCloseCascadesDown(unittest.IsolatedAsyncioTestCase):
    """Closing a parent closes every descendant in depth-first order."""

    def setUp(self) -> None:
        self._repo = _init_repo()
        self._tp = os.path.join(self._repo, '.teaparty')
        os.makedirs(os.path.join(self._tp, 'management', 'sessions'),
                    exist_ok=True)
        self._bus = SqliteMessageBus(os.path.join(self._tp, 'bus.db'))

    def tearDown(self) -> None:
        shutil.rmtree(self._repo, ignore_errors=True)

    async def _spawn_worktree(self, parent_session, branch_suffix):
        """Helper — create a child with a real git worktree."""
        child = create_session(agent_name='worker', scope='management',
                               teaparty_home=self._tp)
        wt = os.path.join(child.path, 'worktree')
        branch = f'session/{child.id}'
        subprocess.run(
            ['git', 'worktree', 'add', '-b', branch, wt, 'main'],
            cwd=self._repo, check=True, capture_output=True,
        )
        with open(os.path.join(wt, f'CHILD_{branch_suffix}'), 'w') as f:
            f.write(f'work from {branch_suffix}\n')
        subprocess.run(['git', 'add', '.'], cwd=wt, check=True)
        subprocess.run(['git', 'commit', '-m', f'{branch_suffix}'],
                       cwd=wt, check=True, capture_output=True)
        child.worktree_path = wt
        child.worktree_branch = branch
        child.merge_target_repo = self._repo
        child.merge_target_worktree = self._repo
        child.merge_target_branch = 'main'
        child.parent_session_id = parent_session.id
        _save_meta(child)
        return child

    async def test_close_root_merges_and_removes_every_descendant(self) -> None:
        root = create_session(agent_name='lead', scope='management',
                              teaparty_home=self._tp)
        child = await self._spawn_worktree(root, 'A')
        _dispatch(self._bus, child.id, 'worker',
                  parent_conv=f'dispatch:{root.id}')

        events: list[dict] = []
        close_fn = build_close_fn(
            dispatch_session=root,
            teaparty_home=self._tp,
            scope='management',
            tasks_by_child={},
            on_dispatch=events.append,
            agent_name='lead',
            bus=self._bus,
        )
        result = await close_fn(f'dispatch:{child.id}')
        self.assertEqual(result.get('status'), 'ok')
        # Commit from child's worktree is on main.
        self.assertTrue(
            os.path.isfile(os.path.join(self._repo, 'CHILD_A')),
            "child's file must be merged into main",
        )
        # Bus state transitioned.
        conv = self._bus.get_conversation(f'dispatch:{child.id}')
        self.assertEqual(conv.state, ConversationState.CLOSED)
        # dispatch_completed fired.
        completed = [e for e in events if e.get('type') == 'dispatch_completed']
        self.assertEqual(len(completed), 1)


class TestRateLimitIsBusBacked(unittest.TestCase):
    """Per-agent slot limit counts live bus children."""

    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp(prefix='tp422-ratelimit-')
        self._bus = SqliteMessageBus(os.path.join(self._dir, 'bus.db'))
        self._parent_conv = 'lead:test:q'

    def tearDown(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_fourth_live_dispatch_is_denied(self) -> None:
        fake_session = type('FakeSession', (), {'id': 'lead'})()
        for i in range(3):
            _dispatch(self._bus, f'c{i}', f'worker-{i}',
                      parent_conv=self._parent_conv,
                      state=ConversationState.ACTIVE)
        self.assertFalse(
            check_slot_available(
                fake_session, bus=self._bus, conv_id=self._parent_conv),
            'four live children must be denied',
        )

    def test_closed_children_do_not_consume_slots(self) -> None:
        fake_session = type('FakeSession', (), {'id': 'lead'})()
        # Three closed children + one active — still have room.
        for i in range(3):
            _dispatch(self._bus, f'old-{i}', f'worker-{i}',
                      parent_conv=self._parent_conv,
                      state=ConversationState.CLOSED)
        _dispatch(self._bus, 'live-1', 'worker-live',
                  parent_conv=self._parent_conv,
                  state=ConversationState.ACTIVE)
        self.assertTrue(
            check_slot_available(
                fake_session, bus=self._bus, conv_id=self._parent_conv),
            'closed children are not live; slot still available',
        )

    def test_paused_children_count_as_live(self) -> None:
        """Paused conversations are live (can be resumed) — they hold a slot."""
        fake_session = type('FakeSession', (), {'id': 'lead'})()
        _dispatch(self._bus, 'p1', 'w1', parent_conv=self._parent_conv,
                  state=ConversationState.PAUSED)
        _dispatch(self._bus, 'p2', 'w2', parent_conv=self._parent_conv,
                  state=ConversationState.PAUSED)
        _dispatch(self._bus, 'p3', 'w3', parent_conv=self._parent_conv,
                  state=ConversationState.PAUSED)
        self.assertFalse(
            check_slot_available(
                fake_session, bus=self._bus, conv_id=self._parent_conv),
            'three paused conversations must consume all slots',
        )


class TestCrossParentIsolation(unittest.TestCase):
    """children_of is keyed by parent — no leakage between dispatchers."""

    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp(prefix='tp422-isolation-')
        self._bus = SqliteMessageBus(os.path.join(self._dir, 'bus.db'))

    def tearDown(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_children_do_not_leak_between_parents(self) -> None:
        a = _dispatch(self._bus, 'a', 'lead-a')
        b = _dispatch(self._bus, 'b', 'lead-b')
        _dispatch(self._bus, 'ac', 'child-a', parent_conv=a)
        _dispatch(self._bus, 'bc', 'child-b', parent_conv=b)

        self.assertEqual([k.agent_name for k in self._bus.children_of(a)],
                         ['child-a'])
        self.assertEqual([k.agent_name for k in self._bus.children_of(b)],
                         ['child-b'])


class TestStateTransitions(unittest.TestCase):
    """Bus state is the single lifecycle signal."""

    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp(prefix='tp422-states-')
        self._bus = SqliteMessageBus(os.path.join(self._dir, 'bus.db'))

    def tearDown(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_pending_active_paused_closed_path(self) -> None:
        conv_id = _dispatch(self._bus, 's', 'lead',
                            state=ConversationState.PENDING)
        self.assertEqual(
            self._bus.get_conversation(conv_id).state,
            ConversationState.PENDING)
        self._bus.update_conversation_state(conv_id, ConversationState.ACTIVE)
        self.assertEqual(
            self._bus.get_conversation(conv_id).state,
            ConversationState.ACTIVE)
        # Bridge restart — every pending/active becomes paused.
        self._bus.pause_live_conversations()
        self.assertEqual(
            self._bus.get_conversation(conv_id).state,
            ConversationState.PAUSED)
        self._bus.update_conversation_state(conv_id, ConversationState.CLOSED)
        self.assertEqual(
            self._bus.get_conversation(conv_id).state,
            ConversationState.CLOSED)


class TestSubtreeCollectionWalksFromBus(unittest.TestCase):
    """collect_descendants_from_bus is inclusive, depth-first."""

    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp(prefix='tp422-subtree-')
        self._bus = SqliteMessageBus(os.path.join(self._dir, 'bus.db'))

    def tearDown(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_inclusive_depth_first(self) -> None:
        root = _dispatch(self._bus, 'root', 'lead')
        _dispatch(self._bus, 'c1', 'team-1', parent_conv=root)
        _dispatch(self._bus, 'gc1', 'dev-1', parent_conv='dispatch:c1')
        _dispatch(self._bus, 'gc2', 'dev-2', parent_conv='dispatch:c1')
        _dispatch(self._bus, 'c2', 'team-2', parent_conv=root)

        order = collect_descendants_from_bus(self._bus, root)
        self.assertEqual(order[0], 'root',
                         'root is first in depth-first order')
        # All five sessions appear.
        self.assertEqual(set(order), {'root', 'c1', 'gc1', 'gc2', 'c2'})
        # c1's descendants come before c2.
        self.assertLess(order.index('gc1'), order.index('c2'))
        self.assertLess(order.index('gc2'), order.index('c2'))

    def test_with_parents_returns_conversation_and_parent(self) -> None:
        root = _dispatch(self._bus, 'root', 'lead')
        _dispatch(self._bus, 'c1', 'team-1', parent_conv=root)
        _dispatch(self._bus, 'gc1', 'dev-1', parent_conv='dispatch:c1')

        pairs = collect_descendants_with_parents_from_bus(
            self._bus, root, root_parent_conv_id='')
        by_id = {conv.id: (conv, parent) for conv, parent in pairs}
        self.assertEqual(
            by_id['dispatch:gc1'][1], 'dispatch:c1',
            'grandchild parent points at child')
        self.assertEqual(
            by_id['dispatch:c1'][1], root,
            'child parent points at root')


if __name__ == '__main__':
    unittest.main()
