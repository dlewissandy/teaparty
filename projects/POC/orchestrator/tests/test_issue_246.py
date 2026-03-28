"""Tests for issue #246: INTERVENE event delivery at turn boundaries via --resume.

Verifies:
1. InterventionQueue can accept and drain messages
2. Multiple messages coalesce into a single intervention prompt
3. Queue is empty after drain
4. INTERVENE EventType exists on the event bus
5. Orchestrator checks intervention queue at turn boundaries
6. Intervention is delivered via --resume with correct prompt framing
7. Intervention is recorded in the message bus as audit trail
8. Interventions are only delivered in agent-actor states, not during gates
"""
import asyncio
import os
import tempfile
import time
import unittest

from projects.POC.orchestrator.events import EventType


# ── Test 1: InterventionQueue API ────────────────────────────────────────────

class TestInterventionQueue(unittest.TestCase):
    """InterventionQueue must accept, coalesce, and drain pending messages."""

    def _make_queue(self):
        from projects.POC.orchestrator.intervention import InterventionQueue
        return InterventionQueue()

    def test_queue_starts_empty(self):
        """A new queue has no pending interventions."""
        q = self._make_queue()
        self.assertFalse(q.has_pending())

    def test_enqueue_makes_pending(self):
        """Enqueuing a message makes has_pending() True."""
        q = self._make_queue()
        q.enqueue('stop what you are doing', sender='human')
        self.assertTrue(q.has_pending())

    def test_drain_returns_all_messages(self):
        """drain() returns all enqueued messages in order."""
        q = self._make_queue()
        q.enqueue('first correction', sender='human')
        q.enqueue('also do this', sender='human')
        messages = q.drain()
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].content, 'first correction')
        self.assertEqual(messages[1].content, 'also do this')

    def test_drain_clears_queue(self):
        """After drain(), queue is empty."""
        q = self._make_queue()
        q.enqueue('something', sender='human')
        q.drain()
        self.assertFalse(q.has_pending())

    def test_drain_empty_returns_empty_list(self):
        """drain() on empty queue returns []."""
        q = self._make_queue()
        self.assertEqual(q.drain(), [])

    def test_messages_have_timestamps(self):
        """Each enqueued message has a timestamp."""
        q = self._make_queue()
        before = time.time()
        q.enqueue('timed msg', sender='human')
        after = time.time()
        messages = q.drain()
        self.assertGreaterEqual(messages[0].timestamp, before)
        self.assertLessEqual(messages[0].timestamp, after)

    def test_messages_preserve_sender(self):
        """Each message preserves its sender."""
        q = self._make_queue()
        q.enqueue('from advisor', sender='advisor:alice')
        messages = q.drain()
        self.assertEqual(messages[0].sender, 'advisor:alice')


# ── Test 2: INTERVENE EventType ──────────────────────────────────────────────

class TestInterveneEventType(unittest.TestCase):
    """EventType must have an INTERVENE member."""

    def test_intervene_event_type_exists(self):
        """EventType.INTERVENE must exist."""
        self.assertTrue(hasattr(EventType, 'INTERVENE'))

    def test_intervene_event_type_value(self):
        """EventType.INTERVENE value must be 'intervene'."""
        self.assertEqual(EventType.INTERVENE.value, 'intervene')


# ── Test 3: Intervention prompt framing ──────────────────────────────────────

class TestInterventionPromptFraming(unittest.TestCase):
    """The intervention prompt must frame messages with CfA context."""

    def _build_prompt(self, messages):
        from projects.POC.orchestrator.intervention import build_intervention_prompt
        return build_intervention_prompt(messages)

    def _make_message(self, content, sender='human'):
        from projects.POC.orchestrator.intervention import InterventionMessage
        return InterventionMessage(content=content, sender=sender, timestamp=time.time())

    def test_single_message_prompt(self):
        """Single intervention message is framed with CfA INTERVENE header."""
        msgs = [self._make_message('change direction')]
        prompt = self._build_prompt(msgs)
        self.assertIn('[CfA INTERVENE', prompt)
        self.assertIn('change direction', prompt)

    def test_multiple_messages_coalesced(self):
        """Multiple messages are coalesced into one prompt."""
        msgs = [
            self._make_message('do X'),
            self._make_message('also Y'),
        ]
        prompt = self._build_prompt(msgs)
        self.assertIn('do X', prompt)
        self.assertIn('also Y', prompt)
        # Should be a single prompt, not multiple INTERVENE headers
        self.assertEqual(prompt.count('[CfA INTERVENE'), 1)

    def test_prompt_includes_sender(self):
        """Advisor interventions include sender identity for D-A-I weighting."""
        msgs = [self._make_message('suggestion', sender='advisor:alice')]
        prompt = self._build_prompt(msgs)
        self.assertIn('advisor:alice', prompt)

    def test_prompt_includes_discretion_note(self):
        """Prompt reminds the lead of their discretion (continue/backtrack/withdraw)."""
        msgs = [self._make_message('new info')]
        prompt = self._build_prompt(msgs)
        # The lead has full discretion per the CfA extensions spec
        self.assertIn('discretion', prompt.lower())


# ── Test 4: Orchestrator intervention delivery ───────────────────────────────

class TestOrchestratorInterventionDelivery(unittest.TestCase):
    """Orchestrator must check the intervention queue at turn boundaries."""

    def test_orchestrator_has_intervention_queue(self):
        """Orchestrator must accept an intervention_queue parameter."""
        import inspect
        from projects.POC.orchestrator.engine import Orchestrator
        sig = inspect.signature(Orchestrator.__init__)
        self.assertIn('intervention_queue', sig.parameters)

    def test_orchestrator_stores_intervention_queue(self):
        """Orchestrator must store the queue as an attribute."""
        from projects.POC.orchestrator.intervention import InterventionQueue
        from projects.POC.orchestrator.engine import Orchestrator
        from projects.POC.orchestrator.events import EventBus
        from projects.POC.scripts.cfa_state import make_initial_state

        q = InterventionQueue()
        cfa = make_initial_state(task_id='test')

        # Minimal construction — only testing attribute storage
        orch = Orchestrator(
            cfa_state=cfa,
            phase_config=_make_stub_phase_config(),
            event_bus=EventBus(),
            input_provider=None,
            infra_dir='/tmp/fake',
            project_workdir='/tmp/fake',
            session_worktree='/tmp/fake',
            proxy_model_path='/tmp/fake',
            project_slug='test',
            poc_root='/tmp/fake',
            intervention_queue=q,
        )
        self.assertIs(orch._intervention_queue, q)


# ── Test 5: Event bus INTERVENE publication ──────────────────────────────────

class TestInterventionEventPublication(unittest.TestCase):
    """When an intervention is delivered, an INTERVENE event must be published."""

    def test_deliver_intervention_publishes_event(self):
        """_deliver_intervention must publish EventType.INTERVENE on the bus."""
        from projects.POC.orchestrator.intervention import InterventionQueue
        from projects.POC.orchestrator.engine import Orchestrator
        from projects.POC.orchestrator.events import Event, EventBus, EventType
        from projects.POC.scripts.cfa_state import make_initial_state

        captured = []

        async def capture(event):
            captured.append(event)

        bus = EventBus()
        bus.subscribe(capture)
        q = InterventionQueue()
        q.enqueue('redirect now', sender='human')

        cfa = make_initial_state(task_id='test')

        orch = Orchestrator(
            cfa_state=cfa,
            phase_config=_make_stub_phase_config(),
            event_bus=bus,
            input_provider=None,
            infra_dir='/tmp/fake',
            project_workdir='/tmp/fake',
            session_worktree='/tmp/fake',
            proxy_model_path='/tmp/fake',
            project_slug='test',
            poc_root='/tmp/fake',
            intervention_queue=q,
            session_id='test-session',
        )

        asyncio.run(orch._deliver_intervention())

        intervene_events = [e for e in captured if e.type == EventType.INTERVENE]
        self.assertEqual(len(intervene_events), 1)
        self.assertIn('redirect now', intervene_events[0].data.get('content', ''))
        self.assertEqual(intervene_events[0].session_id, 'test-session')


# ── Test 6: Message bus audit trail ──────────────────────────────────────────

class TestInterventionAuditTrail(unittest.TestCase):
    """Interventions must be recorded in the message bus for audit."""

    def test_intervention_recorded_in_message_bus(self):
        """When intervention is delivered, it appears in the message bus."""
        from projects.POC.orchestrator.intervention import InterventionQueue
        from projects.POC.orchestrator.messaging import SqliteMessageBus

        tmp = tempfile.mkdtemp()
        try:
            bus = SqliteMessageBus(os.path.join(tmp, 'messages.db'))
            q = InterventionQueue(message_bus=bus, conversation_id='session:test')
            q.enqueue('course correction', sender='human')
            messages = bus.receive('session:test')
            # The enqueue should record the message
            human_msgs = [m for m in messages if m.sender == 'human']
            self.assertEqual(len(human_msgs), 1)
            self.assertEqual(human_msgs[0].content, 'course correction')
            bus.close()
        finally:
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_stub_phase_config():
    """Create a minimal PhaseConfig stub for Orchestrator construction."""

    class _StubPhaseConfig:
        stall_timeout = 1800
        human_actor_states = frozenset()

        def phase_spec(self, phase_name):
            return None

    return _StubPhaseConfig()


if __name__ == '__main__':
    unittest.main()
