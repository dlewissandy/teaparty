"""Regression tests for the continuation-Send fan-in bug.

Scenario reproduced from a real e2e failure on the joke-book CFA job:

  1. Lead Delegates to writing-lead → run_agent_loop awaits the dispatch
     task, gets writing-lead's first Reply, lead's claude resumes.
  2. Lead Sends a *correction* into the same dispatch (continuation, not
     a new Delegate) and ends turn.
  3. The previous fix-point: ``new_gc_ids = after_ids - before_ids`` was
     empty (no new dispatch this turn), the loop fell to natural-exit,
     ``on_terminate`` returned None (no .phase-outcome.json yet), the
     loop returned ``terminal=None``.
  4. CfA engine raised "skill turn ended without writing
     .phase-outcome.json and no workers are in flight" — even though
     writing-lead was still ACTIVE on the bus and would eventually Reply.
  5. Asyncio task died.  When writing-lead's eventual reply landed, no
     one was listening; job stranded.

Fix: the natural-exit branch now scans ``bus.children_of(conv_id)`` for
any dispatch still in non-CLOSED state.  If any exist, it awaits the
next non-human message via ``_await_continuation_reply`` and feeds it
as the next turn's message.  Only when every initially-open dispatch
closes without a reply does the loop exit.

Each test pins one slice of that contract.
"""
from __future__ import annotations

import asyncio
import sys
import time
import unittest
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.messaging import child_dispatch
from teaparty.messaging.conversations import ConversationState


@dataclass
class _Msg:
    id: str
    conversation: str
    sender: str
    content: str
    timestamp: float


@dataclass
class _Conv:
    id: str
    state: ConversationState


class _FakeBus:
    """Minimal bus stub that supports the surface ``_await_continuation_reply`` uses.

    State is mutable so the test can inject a Reply mid-poll, simulating
    the child agent producing a deferred response while the parent's
    loop is awaiting.
    """

    def __init__(self) -> None:
        self._messages: dict[str, list[_Msg]] = {}
        self._children: dict[str, list[_Conv]] = {}
        self._mid = 0

    def add_message(
        self, conv_id: str, sender: str, content: str,
        ts: float | None = None,
    ) -> None:
        self._mid += 1
        msg = _Msg(
            id=f'm{self._mid}',
            conversation=conv_id,
            sender=sender,
            content=content,
            timestamp=ts if ts is not None else time.time(),
        )
        self._messages.setdefault(conv_id, []).append(msg)

    def set_children(self, parent_id: str, conv_states: list[_Conv]) -> None:
        self._children[parent_id] = list(conv_states)

    def close_child(self, parent_id: str, child_id: str) -> None:
        for c in self._children.get(parent_id, []):
            if c.id == child_id:
                c.state = ConversationState.CLOSED

    # API surface used by the helper:

    def children_of(self, parent_id: str) -> list[_Conv]:
        return list(self._children.get(parent_id, []))

    def receive(
        self, conv_id: str, since_timestamp: float = 0.0,
    ) -> list[_Msg]:
        return [
            m for m in self._messages.get(conv_id, [])
            if m.timestamp > since_timestamp
        ]


class AwaitContinuationReplyTest(unittest.TestCase):
    """Unit-level coverage of the new helper."""

    def setUp(self) -> None:
        self.parent_id = 'job:test:1'
        self.dispatch_id = 'dispatch:writing-lead-1'
        self.bus = _FakeBus()
        self.bus.set_children(
            self.parent_id,
            [_Conv(id=self.dispatch_id, state=ConversationState.ACTIVE)],
        )
        # Pre-existing turn-history messages so the snapshot has a
        # baseline; the helper must not surface these as the "reply."
        now = time.time()
        self.bus.add_message(
            self.dispatch_id, 'human', '/attempt-task initial', ts=now - 10,
        )
        self.bus.add_message(
            self.dispatch_id, 'writing-lead',
            'first response (already seen by parent)', ts=now - 5,
        )
        self.bus.add_message(
            self.dispatch_id, 'project-lead',
            'send correction (continuation)', ts=now - 0.1,
        )

    def test_returns_formatted_reply_when_child_replies(self) -> None:
        async def _run():
            poll_task = asyncio.create_task(
                child_dispatch._await_continuation_reply(
                    self.bus, self.parent_id,
                    [self.dispatch_id], poll_interval=0.05,
                ),
            )
            await asyncio.sleep(0.15)
            # Inject the new reply that writing-lead sends after
            # processing the parent's correction.
            self.bus.add_message(
                self.dispatch_id, 'writing-lead',
                'corrections applied; re-delivering ch3',
            )
            return await asyncio.wait_for(poll_task, timeout=2.0)

        result = asyncio.run(_run())
        self.assertEqual(
            result,
            '[dispatch:writing-lead-1] corrections applied; re-delivering ch3',
            'helper must surface the most recent non-human message '
            'in the same shape as the existing gc_replies path '
            '(``[dispatch:<gid>] <content>``) so the caller can '
            'feed it straight into ``current_message`` for the '
            'next turn',
        )

    def test_human_messages_do_not_count_as_a_reply(self) -> None:
        # The bus may receive human/system messages on the dispatch
        # conversation (rare, but the parent might Send into it again).
        # The helper must keep waiting for a non-human reply rather
        # than returning the human message itself — that would
        # short-circuit the wait and feed the parent's own message
        # back as the next-turn input.
        async def _run():
            poll_task = asyncio.create_task(
                child_dispatch._await_continuation_reply(
                    self.bus, self.parent_id,
                    [self.dispatch_id], poll_interval=0.05,
                ),
            )
            await asyncio.sleep(0.1)
            self.bus.add_message(self.dispatch_id, 'human', 'noise')
            await asyncio.sleep(0.1)
            self.bus.add_message(
                self.dispatch_id, 'writing-lead', 'real reply at last',
            )
            return await asyncio.wait_for(poll_task, timeout=2.0)

        result = asyncio.run(_run())
        self.assertIn(
            'real reply at last', result,
            'human messages must be ignored; the helper waits for a '
            'message from the child (or a downstream agent reporting '
            'through the dispatch)',
        )

    def test_returns_none_when_every_dispatch_closes_without_reply(
        self,
    ) -> None:
        # If the parent CloseConversation's the dispatch out of band
        # (or some other terminal happens), the helper has nothing
        # to wait for and must return None — letting run_agent_loop's
        # natural-exit branch fall through.  Looping forever on a
        # CLOSED dispatch would deadlock the parent.
        async def _run():
            poll_task = asyncio.create_task(
                child_dispatch._await_continuation_reply(
                    self.bus, self.parent_id,
                    [self.dispatch_id], poll_interval=0.05,
                ),
            )
            await asyncio.sleep(0.1)
            self.bus.close_child(self.parent_id, self.dispatch_id)
            return await asyncio.wait_for(poll_task, timeout=2.0)

        result = asyncio.run(_run())
        self.assertIsNone(
            result,
            'every initially-open dispatch closed quietly; helper '
            'must return None so the loop exits cleanly rather than '
            'polling forever',
        )

    def test_first_reply_among_multiple_open_dispatches_wins(self) -> None:
        # The lead may have several active dispatches in flight at
        # once; whichever Replies first feeds the next turn.  This
        # mirrors the existing parallel-dispatch behaviour for fresh
        # Delegates.
        second_id = 'dispatch:research-lead-1'
        self.bus.set_children(
            self.parent_id,
            [
                _Conv(id=self.dispatch_id, state=ConversationState.ACTIVE),
                _Conv(id=second_id, state=ConversationState.ACTIVE),
            ],
        )

        async def _run():
            poll_task = asyncio.create_task(
                child_dispatch._await_continuation_reply(
                    self.bus, self.parent_id,
                    [self.dispatch_id, second_id], poll_interval=0.05,
                ),
            )
            await asyncio.sleep(0.1)
            self.bus.add_message(
                second_id, 'research-lead', 'fast reply from research',
            )
            return await asyncio.wait_for(poll_task, timeout=2.0)

        result = asyncio.run(_run())
        self.assertIn(
            'research-lead-1', result,
            'first reply among the open dispatches must win — '
            'matching the parallel-Delegate semantics for fresh '
            'dispatches',
        )
        self.assertIn(
            'fast reply from research', result,
            'reply content must be carried into the formatted '
            'string so the parent\'s next turn sees what the child '
            'said',
        )


if __name__ == '__main__':
    unittest.main()
