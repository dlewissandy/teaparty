"""Specification tests for the dispatch tree (#395 → rewritten for #422).

The dispatch tree is now built from the bus's ``conversations`` table
(single source of truth).  These tests pin the shape of the tree:
one root, children from ``bus.children_of(parent_conversation_id)``,
agent_name and state straight off the record — no disk walks.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from teaparty.bridge.state.dispatch_tree import (
    agent_name_from_conv_id,
    build_dispatch_tree,
)
from teaparty.messaging.conversations import (
    ConversationState,
    ConversationType,
    SqliteMessageBus,
)


class TestBuildDispatchTreeFromBus(unittest.TestCase):
    """The tree reflects bus records, not session metadata."""

    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp(prefix='tp395-')
        self._bus = SqliteMessageBus(os.path.join(self._dir, 'bus.db'))

    def _register(self, session_id, agent_name, parent_conv_id='',
                  request_id='', type_=ConversationType.DISPATCH):
        conv = self._bus.create_conversation(
            type_, session_id,
            agent_name=agent_name,
            parent_conversation_id=parent_conv_id,
            request_id=request_id,
            state=ConversationState.ACTIVE,
        )
        return conv.id

    def test_root_with_no_children_is_single_node(self) -> None:
        root = self._register('root', 'lead')
        tree = build_dispatch_tree(self._bus, root, root_session_id='root')
        self.assertEqual(tree['agent_name'], 'lead')
        self.assertEqual(tree['children'], [])
        self.assertEqual(tree['session_id'], 'root')
        self.assertEqual(tree['conversation_id'], root)
        self.assertEqual(tree['status'], 'active')

    def test_one_child_renders_with_its_agent_name(self) -> None:
        root = self._register('root', 'lead')
        self._register('c1', 'coding-team', parent_conv_id=root,
                       request_id='req-1')
        tree = build_dispatch_tree(self._bus, root, root_session_id='root')
        self.assertEqual(len(tree['children']), 1)
        self.assertEqual(tree['children'][0]['agent_name'], 'coding-team')
        self.assertEqual(tree['children'][0]['session_id'], 'c1')

    def test_grandchild_nested_under_child(self) -> None:
        root = self._register('root', 'lead')
        child = self._register('c1', 'coding-team', parent_conv_id=root)
        self._register('gc1', 'junior-dev', parent_conv_id=child)
        tree = build_dispatch_tree(self._bus, root, root_session_id='root')
        self.assertEqual(len(tree['children']), 1)
        self.assertEqual(len(tree['children'][0]['children']), 1)
        self.assertEqual(
            tree['children'][0]['children'][0]['agent_name'], 'junior-dev')

    def test_siblings_ordered_by_creation_time(self) -> None:
        root = self._register('root', 'lead')
        self._register('c1', 'team-a', parent_conv_id=root)
        self._register('c2', 'team-b', parent_conv_id=root)
        self._register('c3', 'team-c', parent_conv_id=root)
        tree = build_dispatch_tree(self._bus, root, root_session_id='root')
        self.assertEqual(
            [c['agent_name'] for c in tree['children']],
            ['team-a', 'team-b', 'team-c'],
        )

    def test_unrelated_conversation_is_not_a_child(self) -> None:
        root1 = self._register('r1', 'lead-1')
        root2 = self._register('r2', 'lead-2')
        self._register('c1', 'team-a', parent_conv_id=root1)
        self._register('c2', 'team-b', parent_conv_id=root2)
        tree = build_dispatch_tree(self._bus, root1, root_session_id='r1')
        self.assertEqual(
            [c['agent_name'] for c in tree['children']], ['team-a'])

    def test_unregistered_root_falls_back_to_conv_id_prefix(self) -> None:
        """Roots created by the bridge's POST handler (OM, PM, proxy, lead,
        config) may exist without being registered as DISPATCH rows.  The
        walker derives the name from the conv_id prefix — a bounded
        fallback for a small, closed set of root types.
        """
        tree = build_dispatch_tree(self._bus, 'om')
        self.assertEqual(tree['agent_name'], 'office-manager')

    def test_state_is_carried_from_bus_record(self) -> None:
        root = self._register('root', 'lead')
        child = self._register('c1', 'coding-team', parent_conv_id=root)
        self._bus.update_conversation_state(child, ConversationState.PAUSED)
        tree = build_dispatch_tree(self._bus, root, root_session_id='root')
        self.assertEqual(tree['children'][0]['status'], 'paused')

    def test_cycle_guard_does_not_infinite_recurse(self) -> None:
        """A malformed graph where A→B and B→A must not hang the walker."""
        a = self._register('a', 'alpha')
        b = self._register('b', 'beta', parent_conv_id=a)
        # Introduce cycle: make A a child of B too.
        self._bus._conn.execute(
            'UPDATE conversations SET parent_conversation_id = ? WHERE id = ?',
            (b, a),
        )
        self._bus._conn.commit()
        # The walker returns without looping; shape is not guaranteed but
        # recursion must terminate.
        tree = build_dispatch_tree(self._bus, a, root_session_id='a')
        self.assertIsInstance(tree, dict)

    def test_closed_child_is_elided(self) -> None:
        """Closed conversations must not appear in the tree.

        Reproducer: OM dispatches teaparty-lead, teaparty-lead finishes,
        OM calls CloseConversation.  close_fn marks the bus record
        CLOSED.  The next /api/dispatch-tree fetch must not return the
        closed child — otherwise the accordion blade reappears at the
        bottom after the user already saw it close.
        """
        root = self._register('root', 'lead')
        self._register('active-child', 'team-a', parent_conv_id=root)
        closed = self._register('closed-child', 'team-b', parent_conv_id=root)
        self._bus.update_conversation_state(closed, ConversationState.CLOSED)

        tree = build_dispatch_tree(self._bus, root, root_session_id='root')
        child_names = [c['agent_name'] for c in tree['children']]
        self.assertEqual(
            child_names, ['team-a'],
            'Closed children must be elided from the dispatch tree — '
            'they reappeared as phantom blades at the bottom of the '
            'accordion.  The bus row survives for audit; the UI does not.',
        )

    def test_withdrawn_child_is_elided(self) -> None:
        """Withdrawn conversations are terminal — also elided."""
        root = self._register('root', 'lead')
        withdrawn = self._register(
            'withdrawn-child', 'team-c', parent_conv_id=root)
        self._bus.update_conversation_state(
            withdrawn, ConversationState.WITHDRAWN)

        tree = build_dispatch_tree(self._bus, root, root_session_id='root')
        self.assertEqual(
            tree['children'], [],
            'Withdrawn children must be elided from the dispatch tree',
        )

    def test_closed_subtree_is_elided_entirely(self) -> None:
        """When a parent is closed, its descendants are hidden too.

        The parent is elided, so its entire subtree disappears from
        the tree.  Any grandchildren rooted below still exist in the
        bus (close_conversation closes leaves-up so they're CLOSED as
        well) — this test just pins that the walker doesn't surface
        them via some other path.
        """
        root = self._register('root', 'lead')
        closed = self._register(
            'closed-child', 'team-d', parent_conv_id=root)
        # Grandchild under the closed node, also closed.
        gc = self._register('gc', 'team-e', parent_conv_id=closed)
        self._bus.update_conversation_state(closed, ConversationState.CLOSED)
        self._bus.update_conversation_state(gc, ConversationState.CLOSED)

        tree = build_dispatch_tree(self._bus, root, root_session_id='root')
        self.assertEqual(tree['children'], [])

    def test_active_child_remains_visible(self) -> None:
        """Baseline: the filter doesn't erase active children by mistake."""
        root = self._register('root', 'lead')
        self._register('active-child', 'team-live', parent_conv_id=root)
        tree = build_dispatch_tree(self._bus, root, root_session_id='root')
        self.assertEqual(len(tree['children']), 1)
        self.assertEqual(tree['children'][0]['agent_name'], 'team-live')

    def test_paused_child_remains_visible(self) -> None:
        """Paused is not terminal — the user has to decide resume/close/withdraw
        so the blade must keep showing with its paused pill.
        """
        root = self._register('root', 'lead')
        paused = self._register('paused-child', 'team-p', parent_conv_id=root)
        self._bus.update_conversation_state(
            paused, ConversationState.PAUSED)
        tree = build_dispatch_tree(self._bus, root, root_session_id='root')
        self.assertEqual(len(tree['children']), 1)
        self.assertEqual(tree['children'][0]['status'], 'paused')


class TestAgentNameFromConvId(unittest.TestCase):
    """Bounded fallback for unregistered top-level roots."""

    def test_known_prefixes(self) -> None:
        self.assertEqual(agent_name_from_conv_id('om'), 'office-manager')
        self.assertEqual(agent_name_from_conv_id('om:'), 'office-manager')
        self.assertEqual(agent_name_from_conv_id('pm:xyz'), 'project-manager')
        self.assertEqual(agent_name_from_conv_id('proxy:q'), 'proxy')
        self.assertEqual(agent_name_from_conv_id('config:x'),
                         'configuration-lead')

    def test_lead_conv_id_extracts_name(self) -> None:
        self.assertEqual(
            agent_name_from_conv_id('lead:joke-book-lead:abc'),
            'joke-book-lead',
        )

    def test_job_conv_id_derives_project_lead(self) -> None:
        self.assertEqual(
            agent_name_from_conv_id('job:sample:sid'), 'sample-lead')

    def test_unknown_prefix_returns_empty(self) -> None:
        # Writers must register DISPATCH conversations explicitly with
        # agent_name; the fallback is not a catch-all.  Empty for the
        # rare case of a malformed conv_id.
        self.assertEqual(agent_name_from_conv_id('unknown:x'), '')
        self.assertEqual(agent_name_from_conv_id(''), '')


if __name__ == '__main__':
    unittest.main()
