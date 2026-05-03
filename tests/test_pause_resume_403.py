"""Pause/resume (#403) on the bus-based conversation model (#422).

The original version of this file walked session metadata on disk.
Since #422 the bus's ``conversations`` table is the single source of
truth for the dispatch tree, and pause/resume queries it directly
via ``bus.project_conversations`` and ``bus.children_of``.

These tests verify:
  - ``collect_project_subtree`` returns every DISPATCH conversation
    under a given project_slug, with correct parent session ids.
  - Cross-project isolation: pausing project A does not touch B.
  - Phase persistence (``mark_launching`` / ``mark_awaiting`` /
    ``mark_complete``) — the on-disk phase field used by the resume
    walker to decide whether to re-invoke claude.  Separate from the
    tree structure, which lives in the bus.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest

from teaparty.messaging.conversations import (
    ConversationState,
    ConversationType,
    SqliteMessageBus,
)
from teaparty.runners.launcher import (
    create_session,
    load_session,
    mark_awaiting,
    mark_complete,
    mark_launching,
)
from teaparty.workspace.pause_resume import (
    collect_project_subtree,
    collect_session_subtree,
)


class TestPhasePersistence(unittest.TestCase):
    """mark_* writes the phase field so resume walkers read it back."""

    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp(prefix='tp403-phase-')
        os.makedirs(os.path.join(self._dir, 'management', 'sessions'))

    def tearDown(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_mark_launching_stores_message(self) -> None:
        s = create_session(
            agent_name='a', scope='management', teaparty_home=self._dir)
        mark_launching(s, 'hello world')
        loaded = load_session(
            agent_name='a', scope='management',
            teaparty_home=self._dir, session_id=s.id)
        self.assertEqual(loaded.phase, 'launching')
        self.assertEqual(loaded.current_message, 'hello world')

    def test_mark_awaiting_stores_gc_ids(self) -> None:
        s = create_session(
            agent_name='a', scope='management', teaparty_home=self._dir)
        mark_awaiting(s, ['gc1', 'gc2'])
        loaded = load_session(
            agent_name='a', scope='management',
            teaparty_home=self._dir, session_id=s.id)
        self.assertEqual(loaded.phase, 'awaiting')
        self.assertEqual(loaded.in_flight_gc_ids, ['gc1', 'gc2'])

    def test_mark_complete_records_response_text(self) -> None:
        s = create_session(
            agent_name='a', scope='management', teaparty_home=self._dir)
        mark_complete(s, 'the final integrated reply')
        loaded = load_session(
            agent_name='a', scope='management',
            teaparty_home=self._dir, session_id=s.id)
        self.assertEqual(loaded.phase, 'complete')
        self.assertEqual(loaded.response_text, 'the final integrated reply')


class TestCollectProjectSubtreeFromBus(unittest.TestCase):
    """``collect_project_subtree`` returns every DISPATCH in a project."""

    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp(prefix='tp403-subtree-')
        self._bus = SqliteMessageBus(os.path.join(self._dir, 'bus.db'))

    def tearDown(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def _dispatch(self, sid, agent_name, parent_conv='', project='',
                  request_id=''):
        self._bus.create_conversation(
            ConversationType.DISPATCH, sid,
            agent_name=agent_name,
            parent_conversation_id=parent_conv,
            request_id=request_id,
            project_slug=project,
            state=ConversationState.ACTIVE,
        )
        return f'dispatch:{sid}'

    def test_cross_project_isolation(self) -> None:
        self._dispatch('a-root', 'team-a', project='alpha')
        self._dispatch('a-child', 'worker',
                       parent_conv='dispatch:a-root', project='alpha')
        self._dispatch('b-root', 'team-b', project='beta')
        self._dispatch('b-child', 'worker',
                       parent_conv='dispatch:b-root', project='beta')

        alpha = {sid for sid, _ in collect_project_subtree(self._bus, 'alpha')}
        beta = {sid for sid, _ in collect_project_subtree(self._bus, 'beta')}

        self.assertEqual(alpha, {'a-root', 'a-child'})
        self.assertEqual(beta, {'b-root', 'b-child'})

    def test_empty_project_returns_empty(self) -> None:
        self.assertEqual(
            collect_project_subtree(self._bus, 'nobody'), [])

    def test_parent_session_id_is_extracted_from_dispatch_conv(self) -> None:
        self._dispatch('root', 'lead', project='p')
        self._dispatch('child', 'worker',
                       parent_conv='dispatch:root', project='p')
        out = dict(collect_project_subtree(self._bus, 'p'))
        self.assertEqual(out.get('child'), 'root')
        # Root's parent is a non-dispatch form (empty here); the walker
        # normalises this to empty string — the caller knows the root.
        self.assertEqual(out.get('root'), '')


class TestCollectSessionSubtreeFromBus(unittest.TestCase):
    """``collect_session_subtree`` walks a single dispatch's descendants."""

    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp(prefix='tp403-session-subtree-')
        self._bus = SqliteMessageBus(os.path.join(self._dir, 'bus.db'))

    def tearDown(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def _dispatch(self, sid, agent_name, parent_conv=''):
        self._bus.create_conversation(
            ConversationType.DISPATCH, sid,
            agent_name=agent_name,
            parent_conversation_id=parent_conv,
            state=ConversationState.ACTIVE,
        )
        return f'dispatch:{sid}'

    def test_walks_descendants_depth_first(self) -> None:
        self._dispatch('root', 'lead')
        self._dispatch('c1', 'worker-1',
                       parent_conv='dispatch:root')
        self._dispatch('c2', 'worker-2',
                       parent_conv='dispatch:root')
        self._dispatch('gc', 'grandchild',
                       parent_conv='dispatch:c1')

        subtree = collect_session_subtree(self._bus, 'root')
        sids = [sid for sid, _ in subtree]
        # Root first, then depth-first into each child.
        self.assertEqual(sids[0], 'root')
        self.assertEqual(set(sids), {'root', 'c1', 'c2', 'gc'})
        # Grandchild's parent is c1.
        parent_by_sid = dict(subtree)
        self.assertEqual(parent_by_sid['gc'], 'c1')
        self.assertEqual(parent_by_sid['c1'], 'root')

    def test_unregistered_root_returns_just_that_root(self) -> None:
        # No bus row for 'ghost' — walker still yields (ghost, '').
        subtree = collect_session_subtree(self._bus, 'ghost')
        self.assertEqual(subtree, [('ghost', '')])


if __name__ == '__main__':
    unittest.main()
