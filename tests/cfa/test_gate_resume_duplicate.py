"""Regression tests for the joke-book gate-crash-then-duplicate bug.

Three separable failures chained to produce the symptom: user posts at
the INTENT_ASSERT gate, the session crashes, the user clicks Wake, and
their message gets posted a second time to chat history.

1. ``ApprovalGate`` routes on ``(escalation_mode, proxy_confidence)``
   only — no ``HumanPresence`` consulted, no presence-coupled
   ``record_observation`` call.  (The original crash at ``actors.py``
   was an AttributeError triggered by a ``force_human`` gate invoking
   ``record_observation`` on a ``None`` presence; the right answer was
   to remove the presence abstraction from the routing path entirely.)

2. ``InterventionQueue.enqueue`` must accept ``persist=False`` so that
   resume-seeding (which reads messages *from* the bus) does not write
   them *back* to the bus and create duplicate rows on every wake.

3. The bridge's session-status done-callback must auto-fire resume
   when the task dies with trailing unconsumed human input — level-
   triggered, not edge-triggered on POST arrival. Subject to a cooldown
   so a crash loop doesn't hammer resume forever.
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, AsyncMock


# ── Fix #1: HumanPresence is out of the gate routing decision ───────────

class GateRoutingDoesNotDependOnHumanPresence(unittest.TestCase):
    """ApprovalGate.run() routes on ``(escalation_mode, proxy_confidence)`` only.

    Per the proxy-escalation spec: the decision inputs are the per-gate
    escalation_mode from project.yaml and the proxy's confidence score.
    ``HumanPresence`` is a parallel abstraction that does not belong in
    the routing path.  Before this fix, ``actors.py`` consulted
    ``self.human_presence.human_should_answer(...)`` alongside
    ``force_human`` and called ``record_observation()`` in the force-
    human branch, which crashed when the bridge (which does not
    construct a HumanPresence) routed through a gate with ``always``
    escalation.
    """

    def _actors_source(self) -> str:
        actors_src = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            'teaparty', 'cfa', 'actors.py',
        )
        with open(actors_src) as f:
            return f.read()

    def test_routing_does_not_call_human_should_answer(self) -> None:
        """The gate's routing decision must not call human_should_answer."""
        content = self._actors_source()
        self.assertNotIn(
            'human_should_answer', content,
            'actors.py: ApprovalGate must not consult '
            'HumanPresence.human_should_answer() — the routing inputs '
            'are (escalation_mode, proxy_confidence) per spec.',
        )

    def test_routing_does_not_call_record_observation(self) -> None:
        """The gate must not call HumanPresence.record_observation.

        Proxy learning is persisted via ``_proxy_record`` (ACT-R memory);
        HumanPresence.record_observation is a presence-coupled path that
        only works while the human is 'arrived' at a level — an
        abstraction the routing decision no longer respects.
        """
        content = self._actors_source()
        self.assertNotIn(
            'human_presence.record_observation', content,
            'actors.py: record_observation through HumanPresence is out. '
            'Learning goes through _proxy_record (ACT-R); presence-'
            'coupled observation recording is a dead abstraction here.',
        )

    def test_no_imports_or_references_to_presence_module(self) -> None:
        """The ``teaparty.proxy.presence`` module was removed; nothing
        in ``actors.py`` may reference it."""
        content = self._actors_source()
        self.assertNotIn(
            'teaparty.proxy.presence', content,
            'actors.py must not import from the removed '
            '``teaparty.proxy.presence`` module',
        )
        self.assertNotIn(
            'HumanPresence', content,
            'actors.py must not reference HumanPresence — the class has '
            'been removed',
        )
        self.assertNotIn(
            'should_never_escalate', content,
            'actors.py must not call the removed ``should_never_escalate`` '
            'helper; the never-escalate check is now inlined as '
            '``state in _DEFAULT_NEVER_ESCALATE``',
        )

    def test_presence_module_does_not_exist(self) -> None:
        """teaparty/proxy/presence.py has been removed entirely."""
        presence_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            'teaparty', 'proxy', 'presence.py',
        )
        self.assertFalse(
            os.path.exists(presence_path),
            f'teaparty/proxy/presence.py must be deleted, found at {presence_path}',
        )


# ── Fix #2: InterventionQueue.enqueue respects persist=False ─────────────

class InterventionQueuePersistFlag(unittest.TestCase):
    """enqueue(persist=False) must NOT write the message back to the bus.

    On ``Session.resume_from_disk``, the code reads trailing human
    messages *from* the bus and feeds them into
    ``intervention_queue.enqueue(...)``. Before the fix, enqueue
    unconditionally wrote the content to the bus via ``_message_bus.send``,
    producing a duplicate row on every wake.
    """

    def test_enqueue_default_persists_to_bus(self) -> None:
        from teaparty.cfa.gates.intervention import InterventionQueue
        bus = MagicMock()
        q = InterventionQueue(message_bus=bus, conversation_id='job:x:1')
        q.enqueue('hello', sender='human')
        bus.send.assert_called_once_with('job:x:1', 'human', 'hello')

    def test_enqueue_persist_false_does_not_write_to_bus(self) -> None:
        from teaparty.cfa.gates.intervention import InterventionQueue
        bus = MagicMock()
        q = InterventionQueue(message_bus=bus, conversation_id='job:x:1')
        q.enqueue('hello', sender='human', persist=False)
        bus.send.assert_not_called()

    def test_enqueue_persist_false_still_appends_to_in_memory_queue(self) -> None:
        """persist=False is about bus write-back only; the queue itself
        must still hold the message for the orchestrator to drain."""
        from teaparty.cfa.gates.intervention import InterventionQueue
        bus = MagicMock()
        q = InterventionQueue(message_bus=bus, conversation_id='job:x:1')
        q.enqueue('hello', sender='human', persist=False)
        self.assertTrue(q.has_pending())
        msgs = q.drain()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0].content, 'hello')
        self.assertEqual(msgs[0].sender, 'human')


class ResumeSeedingUsesPersistFalse(unittest.TestCase):
    """Session.resume_from_disk must pass persist=False when seeding the queue.

    This is the concrete user-observable bug: after a crash at the gate,
    clicking Wake triggered resume_from_disk; the trailing human message
    on the bus was enqueued and the default persist=True wrote it back
    as a new row. The user saw their comment appear twice in chat.
    """

    def test_resume_seeding_call_site_uses_persist_false(self) -> None:
        """Assert the call site in session.py passes persist=False.

        A source-level check because spinning up a full Session to
        exercise resume_from_disk end-to-end would pull in the entire
        orchestrator stack. The contract we need is that the specific
        call site — where resume reads trailing human messages from the
        bus and enqueues them — does not double-persist. A source check
        is precise about that contract and will fail loudly if a future
        refactor drops the flag.
        """
        import re
        session_src = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            'teaparty', 'cfa', 'session.py',
        )
        with open(session_src) as f:
            content = f.read()
        # Look for the enqueue call inside the resume-seeding block.
        # The block is marked by the "Seed intervention queue" comment;
        # within it, enqueue must carry persist=False.
        seed_block = re.search(
            r'Seed intervention queue.*?intervention_queue\.enqueue\([^)]*\)',
            content, re.DOTALL,
        )
        self.assertIsNotNone(
            seed_block,
            'could not locate the resume-seeding enqueue call in session.py',
        )
        self.assertIn(
            'persist=False', seed_block.group(),
            'resume-seeding enqueue must pass persist=False; '
            'otherwise the trailing human message gets written back '
            'to the bus as a duplicate on every wake.',
        )


# ── Fix #3: level-triggered auto-resume in the bridge ────────────────────

class BridgeAutoResumeOnTaskEnd(unittest.TestCase):
    """Bridge._maybe_auto_resume fires on task death if bus has trailing human."""

    def _make_bridge(self):
        from teaparty.bridge.server import TeaPartyBridge
        b = TeaPartyBridge.__new__(TeaPartyBridge)
        b._last_auto_resume = {}
        b._active_job_tasks = {}
        return b

    def _run_maybe_auto_resume(self, bridge, *args) -> None:
        """Invoke _maybe_auto_resume inside a running loop and drain its tasks."""
        import asyncio

        async def _driver():
            bridge._maybe_auto_resume(*args)
            # Drain any task _maybe_auto_resume scheduled.
            pending = [
                t for t in asyncio.all_tasks()
                if t is not asyncio.current_task()
            ]
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        asyncio.run(_driver())

    def test_auto_resume_fires_when_bus_trails_with_human(self) -> None:
        b = self._make_bridge()
        bus = MagicMock()
        msg = MagicMock(); msg.sender = 'human'
        bus.receive.return_value = [msg]
        b._bus_for_conversation = MagicMock(return_value=bus)

        resumed = []

        async def fake_resume(project, session):
            resumed.append((project, session))

        b._resume_job_session = fake_resume  # type: ignore[attr-defined]

        self._run_maybe_auto_resume(b, 'joke-book', 'abc')

        self.assertEqual(
            resumed, [('joke-book', 'abc')],
            'auto-resume must fire exactly once when the bus ends with a '
            'human message that the dying session never consumed',
        )

    def test_auto_resume_noop_when_bus_trails_with_non_human(self) -> None:
        """If the last message is from an agent, the session finished its
        turn normally — no auto-resume."""
        b = self._make_bridge()
        bus = MagicMock()
        msg = MagicMock(); msg.sender = 'joke-book-lead'
        bus.receive.return_value = [msg]
        b._bus_for_conversation = MagicMock(return_value=bus)

        resumed = []
        async def fake_resume(project, session):
            resumed.append((project, session))
        b._resume_job_session = fake_resume  # type: ignore[attr-defined]

        self._run_maybe_auto_resume(b, 'joke-book', 'abc')
        self.assertEqual(resumed, [])

    def test_auto_resume_noop_when_bus_empty(self) -> None:
        b = self._make_bridge()
        bus = MagicMock()
        bus.receive.return_value = []
        b._bus_for_conversation = MagicMock(return_value=bus)

        resumed = []
        async def fake_resume(project, session):
            resumed.append((project, session))
        b._resume_job_session = fake_resume  # type: ignore[attr-defined]

        self._run_maybe_auto_resume(b, 'joke-book', 'abc')
        self.assertEqual(resumed, [])

    def test_auto_resume_honours_cooldown(self) -> None:
        """Second attempt within the cooldown window is suppressed —
        prevents a crash loop from hammering resume indefinitely."""
        b = self._make_bridge()
        bus = MagicMock()
        msg = MagicMock(); msg.sender = 'human'
        bus.receive.return_value = [msg]
        b._bus_for_conversation = MagicMock(return_value=bus)

        resume_count = [0]
        async def fake_resume(project, session):
            resume_count[0] += 1
        b._resume_job_session = fake_resume  # type: ignore[attr-defined]

        import asyncio
        async def _driver():
            b._maybe_auto_resume('joke-book', 'abc')  # 1st — fires
            b._maybe_auto_resume('joke-book', 'abc')  # 2nd — suppressed
            pending = [
                t for t in asyncio.all_tasks()
                if t is not asyncio.current_task()
            ]
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        asyncio.run(_driver())

        self.assertEqual(
            resume_count[0], 1,
            'auto-resume must fire at most once per cooldown window; '
            'a crash loop would otherwise spin forever',
        )


if __name__ == '__main__':
    unittest.main()
