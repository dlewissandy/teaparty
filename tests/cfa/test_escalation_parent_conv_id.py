"""Regression: an escalation attaches under the caller's real bus conv_id.

Symptom: a CfA job lead (e.g. joke-book-lead) calls AskQuestion; the
proxy skill fires and the agent stalls waiting for a human reply, but
no accordion blade materializes on the job page for the proxy
conversation.  The user has no UI to answer through.

Cause: the EscalationListener used to stamp the DISPATCH row's
``parent_conversation_id`` with ``f'dispatch:{dispatcher.id}'``
regardless of tier.  The dispatch-tree walker on the job page is
rooted at the JOB conv (``job:{project_slug}:{session_id}``), not at
``dispatch:{session_id}``, so ``bus.children_of(root)`` never found
the escalation row.  Chat-tier dispatched children happened to use
``dispatch:{sid}`` as their own conv_id so the hardcoded form agreed
by coincidence; CfA jobs (and any top-level chat blade whose conv_id
is ``om:...`` or ``lead:...``) did not.

Fix: the caller now supplies ``dispatcher_conv_id`` — its own bus
conv_id in whatever form the tier uses.  The escalation stamps its
DISPATCH row with that value as parent.  One codepath, every tier.

These tests pin:
 1. When ``dispatcher_conv_id`` is supplied, the escalation row is
    keyed by it.
 2. Both the chat-tier form (``dispatch:{sid}``, ``om:{q}``,
    ``lead:{name}:{q}``) and the CfA-job form
    (``job:{project}:{sid}``) work without any per-tier branching in
    the listener.
 3. ``build_dispatch_tree`` rooted at the caller's conv_id finds the
    escalation as a ``proxy`` child.
 4. Backward compat: when ``dispatcher_conv_id`` is omitted, the
    listener falls back to the legacy ``dispatch:{session.id}`` form
    so any pre-migration call site keeps working.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.bridge.state.dispatch_tree import build_dispatch_tree
from teaparty.cfa.gates.escalation import EscalationListener
from teaparty.messaging.conversations import (
    ConversationState,
    ConversationType,
    SqliteMessageBus,
)


class _FakeSession:
    """Stand-in for launcher.Session — all the listener reads is ``.id``."""

    def __init__(self, session_id: str, agent_name: str = 'some-lead'):
        self.id = session_id
        self.agent_name = agent_name


def _make_listener(
    *,
    bus_db: str,
    dispatcher_session,
    dispatcher_conv_id: str = '',
) -> EscalationListener:
    """Build a listener without starting it — we only test _resolve_parent_conv_id."""
    return EscalationListener(
        event_bus=None,
        input_provider=None,
        bus_db_path=bus_db,
        conv_id=f'escalation:{dispatcher_session.id}',
        session_id=dispatcher_session.id,
        infra_dir='',
        proxy_invoker_fn=MagicMock(),
        on_dispatch=None,
        dispatcher_session=dispatcher_session,
        dispatcher_conv_id=dispatcher_conv_id,
        teaparty_home='',
        scope='management',
    )


class TestResolveParentConvId(unittest.TestCase):
    """Unit-level: the helper returns whatever the caller supplied, else falls back."""

    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp(prefix='tp-esc-parent-')
        self._bus_db = os.path.join(self._dir, 'bus.db')

    def tearDown(self) -> None:
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_cfa_job_conv_id_is_used_verbatim(self) -> None:
        """CfA job: caller's conv is ``job:{project_slug}:{sid}``."""
        listener = _make_listener(
            bus_db=self._bus_db,
            dispatcher_session=_FakeSession('20260423-xxx', 'joke-book-lead'),
            dispatcher_conv_id='job:joke-book:20260423-xxx',
        )
        self.assertEqual(
            listener._resolve_parent_conv_id(),
            'job:joke-book:20260423-xxx',
            'CfA-job escalations must attach under the JOB conv_id — '
            'the dispatch-tree walker is rooted there',
        )

    def test_chat_dispatched_conv_id_is_used_verbatim(self) -> None:
        """Chat tier, dispatched child: caller's conv is ``dispatch:{sid}``."""
        listener = _make_listener(
            bus_db=self._bus_db,
            dispatcher_session=_FakeSession('abcdef', 'teaparty-lead'),
            dispatcher_conv_id='dispatch:abcdef',
        )
        self.assertEqual(
            listener._resolve_parent_conv_id(), 'dispatch:abcdef')

    def test_chat_om_conv_id_is_used_verbatim(self) -> None:
        """Chat tier, OM blade: caller's conv is ``om:{qualifier}``."""
        listener = _make_listener(
            bus_db=self._bus_db,
            dispatcher_session=_FakeSession('om-sid', 'office-manager'),
            dispatcher_conv_id='om:some-qualifier',
        )
        self.assertEqual(
            listener._resolve_parent_conv_id(), 'om:some-qualifier')

    def test_chat_lead_conv_id_is_used_verbatim(self) -> None:
        """Chat tier, project-lead blade: ``lead:{name}:{qualifier}``."""
        listener = _make_listener(
            bus_db=self._bus_db,
            dispatcher_session=_FakeSession('lead-sid', 'joke-book-lead'),
            dispatcher_conv_id='lead:joke-book-lead:q42',
        )
        self.assertEqual(
            listener._resolve_parent_conv_id(),
            'lead:joke-book-lead:q42',
        )

    def test_fallback_when_conv_id_missing(self) -> None:
        """Pre-migration caller with no dispatcher_conv_id — fall back.

        The legacy form agreed with chat-tier dispatched children by
        accident; keeping the fallback preserves any call site that
        hasn't been migrated yet.  The fix's correctness comes from
        the two production call sites (chat session, CfA engine) now
        passing the real value; the fallback exists so tests and any
        stragglers don't break outright.
        """
        listener = _make_listener(
            bus_db=self._bus_db,
            dispatcher_session=_FakeSession('legacy-sid'),
            dispatcher_conv_id='',
        )
        self.assertEqual(
            listener._resolve_parent_conv_id(), 'dispatch:legacy-sid')


class TestEscalationAppearsInTreeForCfaJob(unittest.TestCase):
    """Integration: a simulated DISPATCH row for an escalation is found
    by ``build_dispatch_tree`` rooted at the JOB conv.

    Before the fix, the row was keyed under ``dispatch:{sid}`` and the
    walker (rooted at ``job:joke-book:{sid}``) returned zero children.
    The accordion stayed empty and the human had no way to answer.
    """

    def setUp(self) -> None:
        self._dir = tempfile.mkdtemp(prefix='tp-esc-tree-')
        self._bus_db = os.path.join(self._dir, 'bus.db')
        self._bus = SqliteMessageBus(self._bus_db)

        # Register the JOB conv — what the job page's dispatch tree
        # walker roots at.
        self._bus.create_conversation(
            ConversationType.JOB, 'joke-book:session-xyz',
            agent_name='joke-book-lead',
            project_slug='joke-book',
        )
        self._job_conv_id = 'job:joke-book:session-xyz'

    def tearDown(self) -> None:
        try:
            self._bus.close()
        except Exception:
            pass
        shutil.rmtree(self._dir, ignore_errors=True)

    def test_escalation_keyed_by_job_conv_appears_in_tree(self) -> None:
        # Simulate what the listener does when AskQuestion fires and
        # the dispatcher_conv_id is the JOB conv.
        self._bus.create_conversation(
            ConversationType.DISPATCH, 'proxy-session-1',
            agent_name='proxy',
            parent_conversation_id=self._job_conv_id,
            request_id='esc-42',
            project_slug='joke-book',
            state=ConversationState.ACTIVE,
        )

        tree = build_dispatch_tree(
            self._bus, self._job_conv_id, root_session_id='session-xyz',
        )
        self.assertEqual(
            len(tree['children']), 1,
            'The JOB conv must see the escalation as its child — '
            'otherwise the proxy accordion never renders and the '
            'agent stalls with no way for the human to answer',
        )
        child = tree['children'][0]
        self.assertEqual(child['agent_name'], 'proxy')
        self.assertEqual(child['session_id'], 'proxy-session-1')
        self.assertEqual(child['status'], 'active')

    def test_escalation_keyed_by_dispatch_prefix_is_invisible_from_job(self) -> None:
        """The old bug, encoded: if the row's parent is ``dispatch:{sid}``
        but the tree walks from ``job:{project}:{sid}``, the walker
        can't see it.  This test documents the failure mode that was
        live in production before the fix.
        """
        self._bus.create_conversation(
            ConversationType.DISPATCH, 'proxy-session-2',
            agent_name='proxy',
            parent_conversation_id='dispatch:session-xyz',  # the buggy form
            request_id='esc-43',
            project_slug='joke-book',
            state=ConversationState.ACTIVE,
        )

        tree = build_dispatch_tree(
            self._bus, self._job_conv_id, root_session_id='session-xyz',
        )
        self.assertEqual(
            tree['children'], [],
            'Sanity check on the failure mode: when parent_conv_id '
            'is the wrong form, the walker returns nothing',
        )


if __name__ == '__main__':
    unittest.main()
