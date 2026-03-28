"""Tests for issue #252: D-A-I role enforcement for chat participation.

Verifies:
1. DAIRole enum has decider, advisor, informed values
2. RoleEnforcer rejects sends from informed members
3. RoleEnforcer allows sends from deciders
4. RoleEnforcer allows sends from advisors
5. Non-human senders (agents, orchestrator) pass through without checks
6. InterventionQueue rejects enqueue from informed members
7. Advisor interventions are framed as advisory in the prompt
8. Decider interventions are framed as authoritative
9. Mixed decider+advisor interventions are framed correctly
10. SqliteMessageBus with role enforcement blocks informed sends
"""
import tempfile
import os
import unittest


def _make_bus():
    from projects.POC.orchestrator.messaging import SqliteMessageBus
    tmp = tempfile.mktemp(suffix='.db')
    return SqliteMessageBus(tmp)


def _make_role_map():
    """Role map: darrell=decider, alice=advisor, bob=informed."""
    from projects.POC.orchestrator.role_enforcer import DAIRole
    return {
        'darrell': DAIRole.DECIDER,
        'alice': DAIRole.ADVISOR,
        'bob': DAIRole.INFORMED,
    }


# ── Test 1: DAIRole enum ───────────────────────────────────────────────────

class TestDAIRole(unittest.TestCase):
    """DAIRole enum must have decider, advisor, informed values."""

    def test_decider_value(self):
        from projects.POC.orchestrator.role_enforcer import DAIRole
        self.assertEqual(DAIRole.DECIDER.value, 'decider')

    def test_advisor_value(self):
        from projects.POC.orchestrator.role_enforcer import DAIRole
        self.assertEqual(DAIRole.ADVISOR.value, 'advisor')

    def test_informed_value(self):
        from projects.POC.orchestrator.role_enforcer import DAIRole
        self.assertEqual(DAIRole.INFORMED.value, 'informed')


# ── Test 2: RoleEnforcer blocks informed ────────────────────────────────────

class TestRoleEnforcerBlocking(unittest.TestCase):
    """RoleEnforcer must reject sends from informed members."""

    def _make_enforcer(self):
        from projects.POC.orchestrator.role_enforcer import RoleEnforcer
        return RoleEnforcer(_make_role_map())

    def test_informed_send_raises(self):
        """Informed member 'bob' cannot send messages."""
        from projects.POC.orchestrator.role_enforcer import InformedSendError
        enforcer = self._make_enforcer()
        with self.assertRaises(InformedSendError):
            enforcer.check_send('bob')

    def test_decider_send_allowed(self):
        """Decider 'darrell' can send without exception."""
        enforcer = self._make_enforcer()
        enforcer.check_send('darrell')  # should not raise

    def test_advisor_send_allowed(self):
        """Advisor 'alice' can send without exception."""
        enforcer = self._make_enforcer()
        enforcer.check_send('alice')  # should not raise

    def test_unknown_sender_passes(self):
        """Non-human senders (agents, orchestrator) pass through."""
        enforcer = self._make_enforcer()
        enforcer.check_send('orchestrator')  # should not raise
        enforcer.check_send('coding-team')  # should not raise

    def test_is_advisory_for_advisor(self):
        """Advisor input is identified as advisory."""
        enforcer = self._make_enforcer()
        self.assertTrue(enforcer.is_advisory('alice'))

    def test_is_advisory_false_for_decider(self):
        """Decider input is not advisory."""
        enforcer = self._make_enforcer()
        self.assertFalse(enforcer.is_advisory('darrell'))

    def test_is_advisory_false_for_unknown(self):
        """Unknown senders are not advisory."""
        enforcer = self._make_enforcer()
        self.assertFalse(enforcer.is_advisory('orchestrator'))


# ── Test 3: RoleEnforcer from config ────────────────────────────────────────

class TestRoleEnforcerFromConfig(unittest.TestCase):
    """RoleEnforcer.from_humans() builds a role map from Human dataclasses."""

    def test_from_humans(self):
        from projects.POC.orchestrator.config_reader import Human
        from projects.POC.orchestrator.role_enforcer import RoleEnforcer, DAIRole
        humans = [
            Human(name='darrell', role='decider'),
            Human(name='alice', role='advisor'),
            Human(name='bob', role='informed'),
        ]
        enforcer = RoleEnforcer.from_humans(humans)
        self.assertEqual(enforcer.get_role('darrell'), DAIRole.DECIDER)
        self.assertEqual(enforcer.get_role('alice'), DAIRole.ADVISOR)
        self.assertEqual(enforcer.get_role('bob'), DAIRole.INFORMED)


# ── Test 4: SqliteMessageBus with enforcement ──────────────────────────────

class TestMessageBusRoleEnforcement(unittest.TestCase):
    """SqliteMessageBus.send() must check roles when enforcer is configured."""

    def _make_enforced_bus(self):
        from projects.POC.orchestrator.messaging import SqliteMessageBus
        from projects.POC.orchestrator.role_enforcer import RoleEnforcer
        tmp = tempfile.mktemp(suffix='.db')
        bus = SqliteMessageBus(tmp)
        enforcer = RoleEnforcer(_make_role_map())
        bus.role_enforcer = enforcer
        return bus

    def test_informed_send_blocked(self):
        """Informed member cannot send through bus."""
        from projects.POC.orchestrator.role_enforcer import InformedSendError
        bus = self._make_enforced_bus()
        with self.assertRaises(InformedSendError):
            bus.send('conv1', 'bob', 'hello')

    def test_decider_send_works(self):
        """Decider can send through bus."""
        bus = self._make_enforced_bus()
        msg_id = bus.send('conv1', 'darrell', 'hello')
        self.assertTrue(msg_id)

    def test_advisor_send_works(self):
        """Advisor can send through bus."""
        bus = self._make_enforced_bus()
        msg_id = bus.send('conv1', 'alice', 'suggestion')
        self.assertTrue(msg_id)

    def test_agent_send_works(self):
        """Agent senders pass through without role checks."""
        bus = self._make_enforced_bus()
        msg_id = bus.send('conv1', 'orchestrator', 'status')
        self.assertTrue(msg_id)

    def test_no_enforcer_allows_all(self):
        """Without an enforcer, any sender works (backwards compatible)."""
        bus = _make_bus()
        msg_id = bus.send('conv1', 'bob', 'hello')
        self.assertTrue(msg_id)


# ── Test 5: InterventionQueue with enforcement ─────────────────────────────

class TestInterventionQueueRoleEnforcement(unittest.TestCase):
    """InterventionQueue.enqueue() must check roles when enforcer is set."""

    def _make_enforced_queue(self):
        from projects.POC.orchestrator.intervention import InterventionQueue
        from projects.POC.orchestrator.role_enforcer import RoleEnforcer
        enforcer = RoleEnforcer(_make_role_map())
        q = InterventionQueue()
        q.role_enforcer = enforcer
        return q

    def test_informed_enqueue_blocked(self):
        """Informed member cannot enqueue interventions."""
        from projects.POC.orchestrator.role_enforcer import InformedSendError
        q = self._make_enforced_queue()
        with self.assertRaises(InformedSendError):
            q.enqueue('hello', sender='bob')

    def test_decider_enqueue_works(self):
        """Decider can enqueue interventions."""
        q = self._make_enforced_queue()
        q.enqueue('change direction', sender='darrell')
        self.assertTrue(q.has_pending())

    def test_advisor_enqueue_works(self):
        """Advisor can enqueue interventions."""
        q = self._make_enforced_queue()
        q.enqueue('consider this', sender='alice')
        self.assertTrue(q.has_pending())

    def test_no_enforcer_allows_all(self):
        """Without enforcer, any sender can enqueue (backwards compatible)."""
        from projects.POC.orchestrator.intervention import InterventionQueue
        q = InterventionQueue()
        q.enqueue('hello', sender='bob')
        self.assertTrue(q.has_pending())


# ── Test 6: Intervention prompt framing by role ────────────────────────────

class TestInterventionPromptFraming(unittest.TestCase):
    """build_intervention_prompt must frame advisor input as advisory."""

    def _make_msg(self, content, sender='human', **kwargs):
        from projects.POC.orchestrator.intervention import InterventionMessage
        import time
        return InterventionMessage(content=content, sender=sender, timestamp=time.time())

    def test_decider_prompt_is_authoritative(self):
        """Decider intervention uses authoritative framing."""
        from projects.POC.orchestrator.intervention import build_intervention_prompt
        from projects.POC.orchestrator.role_enforcer import RoleEnforcer, DAIRole
        enforcer = RoleEnforcer({'darrell': DAIRole.DECIDER})
        msgs = [self._make_msg('change the approach', sender='darrell')]
        prompt = build_intervention_prompt(msgs, role_enforcer=enforcer)
        self.assertIn('[CfA INTERVENE', prompt)
        self.assertNotIn('advisory', prompt.lower())

    def test_advisor_prompt_is_advisory(self):
        """Advisor intervention uses advisory framing."""
        from projects.POC.orchestrator.intervention import build_intervention_prompt
        from projects.POC.orchestrator.role_enforcer import RoleEnforcer, DAIRole
        enforcer = RoleEnforcer({'alice': DAIRole.ADVISOR})
        msgs = [self._make_msg('consider doing X', sender='alice')]
        prompt = build_intervention_prompt(msgs, role_enforcer=enforcer)
        self.assertIn('advisory', prompt.lower())

    def test_mixed_messages_frame_each_role(self):
        """Mixed decider+advisor messages frame each appropriately."""
        from projects.POC.orchestrator.intervention import build_intervention_prompt
        from projects.POC.orchestrator.role_enforcer import RoleEnforcer, DAIRole
        enforcer = RoleEnforcer({
            'darrell': DAIRole.DECIDER,
            'alice': DAIRole.ADVISOR,
        })
        msgs = [
            self._make_msg('do this now', sender='darrell'),
            self._make_msg('also think about Y', sender='alice'),
        ]
        prompt = build_intervention_prompt(msgs, role_enforcer=enforcer)
        self.assertIn('advisory', prompt.lower())
        self.assertIn('do this now', prompt)
        self.assertIn('also think about Y', prompt)

    def test_no_enforcer_backwards_compatible(self):
        """Without enforcer, prompt uses original framing."""
        from projects.POC.orchestrator.intervention import build_intervention_prompt
        msgs = [self._make_msg('hello', sender='human')]
        prompt = build_intervention_prompt(msgs)
        self.assertIn('[CfA INTERVENE', prompt)
