"""Issue #426: AskQuestion answer-propagation must survive caller restarts.

Specification (per the issue body and the laser-focused refinement
comment):

  1. When the caller's claude session is killed and resumed mid-wait, the
     buffered ``AskQuestion`` re-fires.  The runner MUST consult the bus
     for an in-flight escalation under this caller's parent conv that
     already has a proxy reply emitted, and return that reply directly —
     no new proxy spawn, no new ``proxy:`` row.

  2. After a reply propagates back to the caller — whether via the
     happy-path RESPONSE or the resume-pickup path — the proxy
     conversation row's state MUST be ``CLOSED``.  The bus reflects the
     real lifecycle.

  3. There MUST be exactly ONE ``proxy:`` row per logical AskQuestion.
     A kill+resume must not produce a duplicate.

  4. When two different questions are outstanding, the runner must not
     cross-deliver — pickup is matched on question content, not on
     "any reply for any escalation belonging to this caller."

These tests are load-bearing: each failure points at the specific
invariant the fix must establish.  Reverting the resume-pickup logic
flips at least one positive assertion and at least one negative one.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.cfa.gates.escalation import AskQuestionRunner
from teaparty.messaging.conversations import (
    ConversationState,
    ConversationType,
    SqliteMessageBus,
    make_conversation_id,
)
from teaparty.proxy.hooks import proxy_bus_path
from teaparty.runners.launcher import create_session


def _run(coro):
    return asyncio.run(coro)


class _AskQuestionResilienceCase(unittest.TestCase):
    """Common scaffolding: temp dirs, two buses, runner factory."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix='tp-426-')
        self.teaparty_home = os.path.join(self.tmpdir, '.teaparty')
        self.infra_dir = os.path.join(
            self.teaparty_home, 'management', 'agents', 'proxy',
        )
        os.makedirs(self.infra_dir, exist_ok=True)
        os.makedirs(
            os.path.join(self.teaparty_home, 'management', 'sessions'),
            exist_ok=True,
        )
        os.makedirs(
            os.path.join(self.teaparty_home, 'proxy'),
            exist_ok=True,
        )
        self.caller_bus_db = os.path.join(self.infra_dir, 'messages.db')
        self.proxy_bus_db = proxy_bus_path(self.teaparty_home)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        # Always clear the in-memory escalation registry to avoid leaks
        # between tests; otherwise a residual mark from a prior run can
        # silently change watchdog suppression in the next.
        from teaparty.mcp.registry import clear as _clear_registry
        _clear_registry()

    def _make_dispatcher(self) -> tuple[object, str]:
        """Return (dispatcher_session, dispatcher_conv_id)."""
        dispatcher = create_session(
            agent_name='joke-book-lead',
            scope='management',
            teaparty_home=self.teaparty_home,
            session_id='caller-session-426',
        )
        return dispatcher, f'dispatch:{dispatcher.id}'

    def _make_runner(self, *, proxy_invoker) -> AskQuestionRunner:
        dispatcher, conv_id = self._make_dispatcher()
        return AskQuestionRunner(
            bus_db_path=self.caller_bus_db,
            session_id=dispatcher.id,
            infra_dir=self.infra_dir,
            proxy_invoker_fn=proxy_invoker,
            on_dispatch=None,
            dispatcher_session=dispatcher,
            dispatcher_conv_id=conv_id,
            teaparty_home=self.teaparty_home,
            scope='management',
        )

    def _seed_existing_escalation(
        self,
        *,
        question: str,
        proxy_reply: str | None,
        state: ConversationState = ConversationState.ACTIVE,
        escalation_id: str = 'esc-prior',
    ) -> str:
        """Seed both buses with a pre-existing escalation row.

        Returns the proxy conv_id so callers can probe state after.
        """
        dispatcher_id = 'caller-session-426'
        qualifier = f'{dispatcher_id}:{escalation_id}'
        proxy_conv_id = make_conversation_id(ConversationType.PROXY, qualifier)

        caller_bus = SqliteMessageBus(self.caller_bus_db)
        try:
            caller_bus.create_conversation(
                ConversationType.PROXY, qualifier,
                agent_name='proxy',
                parent_conversation_id=f'dispatch:{dispatcher_id}',
                request_id=escalation_id,
                state=state,
            )
        finally:
            caller_bus.close()

        proxy_bus = SqliteMessageBus(self.proxy_bus_db)
        try:
            proxy_bus.create_conversation(
                ConversationType.PROXY, qualifier,
                state=state,
            )
            # Seed the requestor's question — this is the byte-identical
            # payload the lead's --resume re-fires with.
            proxy_bus.send(proxy_conv_id, 'joke-book-lead', question)
            if proxy_reply is not None:
                proxy_bus.send(
                    proxy_conv_id, 'proxy',
                    json.dumps({'status': 'RESPONSE', 'message': proxy_reply}),
                )
        finally:
            proxy_bus.close()
        return proxy_conv_id

    def _seed_existing_escalation_with_status(
        self,
        *,
        question: str,
        status: str,
        message: str,
        state: ConversationState = ConversationState.ACTIVE,
        escalation_id: str = 'esc-prior',
    ) -> str:
        """Seed an existing escalation whose terminal status is custom
        (RESPONSE or WITHDRAW).  Used by the WITHDRAW-pickup test."""
        dispatcher_id = 'caller-session-426'
        qualifier = f'{dispatcher_id}:{escalation_id}'
        proxy_conv_id = make_conversation_id(ConversationType.PROXY, qualifier)

        caller_bus = SqliteMessageBus(self.caller_bus_db)
        try:
            caller_bus.create_conversation(
                ConversationType.PROXY, qualifier,
                agent_name='proxy',
                parent_conversation_id=f'dispatch:{dispatcher_id}',
                request_id=escalation_id,
                state=state,
            )
        finally:
            caller_bus.close()

        proxy_bus = SqliteMessageBus(self.proxy_bus_db)
        try:
            proxy_bus.create_conversation(
                ConversationType.PROXY, qualifier, state=state,
            )
            proxy_bus.send(proxy_conv_id, 'joke-book-lead', question)
            proxy_bus.send(
                proxy_conv_id, 'proxy',
                json.dumps({'status': status, 'message': message}),
            )
        finally:
            proxy_bus.close()
        return proxy_conv_id

    def _count_proxy_rows(self, parent_conv_id: str) -> int:
        bus = SqliteMessageBus(self.caller_bus_db)
        try:
            return sum(
                1 for c in bus.children_of(parent_conv_id)
                if c.agent_name == 'proxy'
            )
        finally:
            bus.close()

    def _conv_state(self, conv_id: str) -> ConversationState:
        bus = SqliteMessageBus(self.caller_bus_db)
        try:
            conv = bus.get_conversation(conv_id)
            assert conv is not None, f'conv not found: {conv_id}'
            return conv.state
        finally:
            bus.close()


# ── Acceptance #1+#3+#4: resume-pickup with reply already on bus ─────


class TestResumePickupReturnsExistingReply(_AskQuestionResilienceCase):
    """Caller killed mid-wait; proxy reply landed; AskQuestion re-fires.

    On entry, the runner MUST detect the in-flight escalation row whose
    question matches and whose proxy reply is on the bus, return that
    reply directly, transition the row to CLOSED, and skip spawning a
    new proxy.
    """

    def test_existing_active_proxy_with_reply_is_returned_no_spawn(self) -> None:
        from teaparty.mcp.registry import (
            _active_escalations, mark_escalation_active,
        )

        question = 'Pass 7: re-submitting for approval. OK to merge?'
        expected_reply = 'Yes, merge.'

        proxy_conv_id = self._seed_existing_escalation(
            question=question,
            proxy_reply=expected_reply,
            state=ConversationState.ACTIVE,
        )
        # Simulate the bridge-restart re-marking (``rehydrate()`` marks
        # every in-flight proxy child on startup).  Without this
        # precondition the marker-leak invariant cannot be exercised:
        # the runner.run() entrance path doesn't set the marker until
        # the spawn branch, and the resume-pickup branch returns before
        # that — so a marker leak only manifests when something else
        # has already set the marker.
        mark_escalation_active('caller-session-426:esc-prior')

        invoker = MagicMock()  # MagicMock is not awaitable; if called, fails

        async def _should_not_be_called(**_: object) -> None:
            invoker()
            raise AssertionError(
                'proxy_invoker_fn must NOT be called on resume-pickup; '
                'a fresh proxy spawn defeats the entire fix and produces '
                'a duplicate proxy: row',
            )

        runner = self._make_runner(proxy_invoker=_should_not_be_called)
        answer = _run(runner.run(question))

        self.assertEqual(
            answer, expected_reply,
            'resume-pickup must return the proxy reply that was already '
            'on the bus when AskQuestion re-fired',
        )
        self.assertEqual(
            invoker.call_count, 0,
            'proxy_invoker_fn must not be called when the existing '
            'escalation already has a reply on the bus',
        )
        # No duplicate row.
        self.assertEqual(
            self._count_proxy_rows(f'dispatch:caller-session-426'), 1,
            'exactly one PROXY row must exist per logical AskQuestion; '
            'a duplicate means the resume re-fired a fresh escalation',
        )
        # Row transitions to CLOSED after delivery.
        self.assertEqual(
            self._conv_state(proxy_conv_id), ConversationState.CLOSED,
            'after the reply propagates to the caller, the proxy '
            'conversation row state MUST be CLOSED — otherwise the bus '
            'leaks ACTIVE rows whose subprocess is long gone',
        )
        # Marker hygiene: pickup-path return must not leave a marker
        # behind.  ``rehydrate()`` re-marks every active proxy child
        # on bridge restart, so a leaked qualifier here would deadlock
        # the watchdog for the caller's session forever (suppressing
        # any future non-AskQuestion stall — exactly what Risk #1 in
        # the issue's risk comment warns against).
        leaked = [
            q for q in _active_escalations
            if q.startswith('caller-session-426:')
        ]
        self.assertEqual(
            leaked, [],
            'resume-pickup return must clear the in-memory escalation '
            'marker; otherwise the watchdog sees the session as still '
            'in an in-flight escalation and never declares a stall, '
            'even for unrelated hung tools',
        )

    def test_existing_paused_proxy_with_reply_is_returned(self) -> None:
        """Bridge-restart variant: the bus startup sweep moves ACTIVE
        rows to PAUSED.  The resume-pickup path MUST still recognise
        them — otherwise a post-bridge-restart resume always falls
        through to a fresh spawn.
        """
        from teaparty.mcp.registry import (
            _active_escalations, mark_escalation_active,
        )

        question = 'After bridge restart: same question, still waiting'
        expected_reply = 'reply that survived the restart'

        proxy_conv_id = self._seed_existing_escalation(
            question=question,
            proxy_reply=expected_reply,
            state=ConversationState.PAUSED,
        )
        mark_escalation_active('caller-session-426:esc-prior')

        async def _should_not_be_called(**_: object) -> None:
            raise AssertionError(
                'PAUSED escalation with a reply on bus must not respawn',
            )

        runner = self._make_runner(proxy_invoker=_should_not_be_called)
        answer = _run(runner.run(question))

        self.assertEqual(answer, expected_reply)
        self.assertEqual(
            self._conv_state(proxy_conv_id), ConversationState.CLOSED,
            'PAUSED-with-reply pickup must also CLOSE the row on delivery',
        )
        leaked = [
            q for q in _active_escalations
            if q.startswith('caller-session-426:')
        ]
        self.assertEqual(
            leaked, [],
            'paused-pickup return must clear the in-memory escalation '
            'marker (rehydrate() may have re-marked the qualifier on '
            'bridge restart, and the pickup-path close must clear it)',
        )

    def test_existing_paused_proxy_with_withdraw_reply_is_returned(self) -> None:
        """WITHDRAW is the second terminal status the proxy can emit;
        ``_find_resumable_reply`` formats WITHDRAW as
        ``[WITHDRAW]\\n<reason>`` — distinct from RESPONSE — and must
        be exercised lest a regression silently swap the formatting or
        drop the WITHDRAW arm of the parser.
        """
        question = 'Should we proceed with the migration?'

        proxy_conv_id = self._seed_existing_escalation_with_status(
            question=question,
            status='WITHDRAW',
            message='abandoned — out of scope',
            state=ConversationState.PAUSED,
        )

        async def _should_not_be_called(**_: object) -> None:
            raise AssertionError(
                'WITHDRAW pickup must not re-spawn the proxy',
            )

        runner = self._make_runner(proxy_invoker=_should_not_be_called)
        answer = _run(runner.run(question))

        self.assertEqual(
            answer, '[WITHDRAW]\nabandoned — out of scope',
            'WITHDRAW pickup must format the answer as '
            "'[WITHDRAW]\\n<reason>' — exact match including bracket "
            'prefix and newline; matches the contract that the '
            'happy-path runner uses for the same terminal status',
        )
        self.assertEqual(
            self._conv_state(proxy_conv_id), ConversationState.CLOSED,
            'WITHDRAW pickup must also CLOSE the row',
        )


# ── Acceptance #1: resume without a reply yet — must NOT pick up ─────


class TestResumeWithNoReplyFallsThroughToSpawn(_AskQuestionResilienceCase):
    """If the existing escalation has no proxy reply yet, resume-pickup
    must NOT trigger.  The runner falls through to its normal flow
    (spawn a proxy).  Otherwise we'd return an empty answer or wait
    forever on a row whose proxy is dead.
    """

    def test_no_reply_yet_runner_proceeds_normally(self) -> None:
        question = 'still pending — no reply on bus yet'

        # Seed a PAUSED escalation with NO proxy reply.  Setting up the
        # row but no reply mirrors the "caller resumed before proxy
        # answered" sub-case — resume-pickup must defer.
        self._seed_existing_escalation(
            question=question,
            proxy_reply=None,
            state=ConversationState.PAUSED,
        )

        spawned_qualifiers: list[str] = []

        async def mock_invoker(qualifier: str, cwd: str, **_: object) -> None:
            spawned_qualifiers.append(qualifier)
            # Provide a synthetic RESPONSE so the runner terminates.
            proxy_bus = SqliteMessageBus(self.proxy_bus_db)
            try:
                conv_id = make_conversation_id(
                    ConversationType.PROXY, qualifier,
                )
                proxy_bus.send(conv_id, 'proxy', json.dumps({
                    'status': 'RESPONSE', 'message': 'fresh reply',
                }))
            finally:
                proxy_bus.close()

        runner = self._make_runner(proxy_invoker=mock_invoker)
        answer = _run(runner.run(question))

        self.assertEqual(answer, 'fresh reply')
        self.assertEqual(
            len(spawned_qualifiers), 1,
            'a stale ACTIVE row with no reply must NOT short-circuit '
            'the runner — the proxy must be spawned to actually answer',
        )


# ── Acceptance #4 (negative space): question-matching is exact ────────


class TestPickupMatchesByQuestionContent(_AskQuestionResilienceCase):
    """Multiple distinct AskQuestion calls under the same caller MUST
    NOT cross-deliver.  Pickup is matched on question content; the
    re-fired ``--resume`` payload is byte-identical, so exact match is
    sufficient.  Fuzzy match here would deliver the wrong answer.
    """

    def test_unrelated_existing_reply_does_not_short_circuit(self) -> None:
        # Seed an existing escalation answering question A.
        self._seed_existing_escalation(
            question='What was the audience age?',
            proxy_reply='Ages 5-8',
            state=ConversationState.ACTIVE,
            escalation_id='esc-A',
        )

        # Now fire AskQuestion for a *different* question B.  The
        # runner must spawn a fresh proxy and NOT return "Ages 5-8".
        spawned: list[str] = []

        async def mock_invoker(qualifier: str, cwd: str, **_: object) -> None:
            spawned.append(qualifier)
            proxy_bus = SqliteMessageBus(self.proxy_bus_db)
            try:
                conv_id = make_conversation_id(
                    ConversationType.PROXY, qualifier,
                )
                proxy_bus.send(conv_id, 'proxy', json.dumps({
                    'status': 'RESPONSE', 'message': 'B-answer',
                }))
            finally:
                proxy_bus.close()

        runner = self._make_runner(proxy_invoker=mock_invoker)
        answer = _run(runner.run('Which database engine?'))

        self.assertEqual(
            answer, 'B-answer',
            'the runner must not cross-deliver the answer for question A '
            'when asked question B',
        )
        self.assertNotIn(
            'Ages 5-8', answer,
            'negative space: the unrelated existing reply must not leak '
            'into the answer for a different question',
        )
        self.assertEqual(
            len(spawned), 1,
            'an unrelated existing escalation must not short-circuit '
            'a different question — the proxy must be spawned for B',
        )


# ── Acceptance #2: terminal CLOSED state on the happy path ───────────


class TestHappyPathClosesProxyConversation(_AskQuestionResilienceCase):
    """Pin the existing CLOSED transition on the normal RESPONSE path.

    This is partially regression-coverage for code that already exists
    (lines 372-393 of escalation.py).  It also pins that the CLOSED
    transition uses the proxy_conv_id that the caller's bus row is
    keyed by — a rename or drift here would silently leave rows ACTIVE.
    """

    def test_response_terminal_transitions_proxy_row_to_closed(self) -> None:
        captured_qualifier: list[str] = []

        async def mock_invoker(qualifier: str, cwd: str, **_: object) -> None:
            captured_qualifier.append(qualifier)
            proxy_bus = SqliteMessageBus(self.proxy_bus_db)
            try:
                conv_id = make_conversation_id(
                    ConversationType.PROXY, qualifier,
                )
                proxy_bus.send(conv_id, 'proxy', json.dumps({
                    'status': 'RESPONSE', 'message': 'merged',
                }))
            finally:
                proxy_bus.close()

        runner = self._make_runner(proxy_invoker=mock_invoker)
        answer = _run(runner.run('Approve?'))

        self.assertEqual(answer, 'merged')
        self.assertEqual(len(captured_qualifier), 1)
        proxy_conv_id = make_conversation_id(
            ConversationType.PROXY, captured_qualifier[0],
        )
        self.assertEqual(
            self._conv_state(proxy_conv_id), ConversationState.CLOSED,
            'happy-path RESPONSE must leave the proxy row CLOSED — '
            'this invariant is what lets the bus reflect real lifecycle',
        )
        # Marker hygiene on the happy path: the spawn-path ``finally``
        # must clear the marker on RESPONSE termination.  Asymmetry
        # between the spawn-path's terminal cleanup and the cancellation
        # cleanup would defeat the marker hygiene the issue's mechanism
        # describes ("the runner clears the sentinel and the watchdog
        # resumes normal behaviour for the next turn").
        from teaparty.mcp.registry import is_escalation_active
        self.assertFalse(
            is_escalation_active(captured_qualifier[0]),
            'happy-path RESPONSE termination must clear the in-memory '
            'escalation marker; otherwise the watchdog stays suppressed '
            'after the wait completes successfully',
        )


# ── Risk #1: marker MUST clear on every exit (cancellation, error) ──


class TestEscalationMarkerClearedOnNonTerminalExit(_AskQuestionResilienceCase):
    """The in-memory ``_active_escalations`` marker is what the
    watchdog reads to suppress stall kills (#426).  If a runner exits
    via cancellation or exception with the marker still set, the
    watchdog is permanently exempted from stall detection for that
    session — a hung tool unrelated to the escalation could never be
    killed.  This test pins that the marker clears on the cancellation
    path.
    """

    def test_marker_cleared_when_proxy_invoker_raises(self) -> None:
        from teaparty.mcp.registry import is_escalation_active

        async def boom_invoker(qualifier: str, cwd: str, **_: object) -> None:
            # Snapshot: while the runner is awaiting us, the marker is
            # set.  This is the precondition for the cleanup invariant
            # below.
            self.assertTrue(
                is_escalation_active(qualifier),
                'precondition: marker must be set while runner awaits',
            )
            raise RuntimeError('synthetic invoker failure')

        runner = self._make_runner(proxy_invoker=boom_invoker)

        # The runner catches its own exceptions in ``run()`` and returns
        # an empty answer; the cleanup must happen anyway.
        answer = _run(runner.run('A question whose proxy will fail'))
        self.assertEqual(answer, '')

        # Walk every qualifier whose prefix could have been ours.  None
        # may remain — otherwise the watchdog would treat any future
        # stall on this session as suppressed.
        from teaparty.mcp.registry import _active_escalations
        leaked = [
            q for q in _active_escalations
            if q.startswith('caller-session-426:')
        ]
        self.assertEqual(
            leaked, [],
            "marker leak: escalation marker must clear on every exit "
            "path, even when the proxy invoker raises.  A leaked marker "
            "permanently disables the stall watchdog for this session, "
            "so an unrelated hung tool (not an AskQuestion wait) would "
            "never be killed.",
        )


if __name__ == '__main__':
    unittest.main()
