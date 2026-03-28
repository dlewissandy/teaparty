"""Tests for issue #202: Human participation model with dynamic proxy handoff.

Covers:
  - HumanPresence tracking: arrive/depart transitions, level tracking
  - Proxy handoff: proxy steps aside when human arrives, resumes on depart
  - Observation recording: proxy records observation chunks during direct participation
  - Gate queue: FIFO ordering for concurrent gates, serial processing
  - Dynamic never-escalate: states become escalatable when human is present
  - Cross-level learning: observation chunks stored as ACT-R memory
  - Backward compatibility: sessions without arrive/depart behave as before
  - Integration: ApprovalGate routes to human when present, proxy when absent
"""
from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from projects.POC.orchestrator.human_presence import (
    HumanPresence,
    PresenceLevel,
)
from projects.POC.orchestrator.gate_queue import GateQueue, GateRequest


def _run(coro):
    return asyncio.run(coro)


def _make_presence() -> HumanPresence:
    """Create a default HumanPresence with no active levels."""
    return HumanPresence()


def _make_gate_request(
    state: str = 'TASK_ASSERT',
    team: str = 'art',
    priority: int = 0,
) -> GateRequest:
    """Create a GateRequest for testing."""
    return GateRequest(state=state, team=team, priority=priority)


def _make_approval_gate(tmpdir, human_presence=None, never_escalate=False):
    """Create an ApprovalGate with optional human presence."""
    from projects.POC.orchestrator.actors import ApprovalGate
    model_path = os.path.join(tmpdir, 'project', '.proxy-confidence.json')
    os.makedirs(os.path.dirname(model_path), exist_ok=True)
    Path(model_path).write_text('{}')
    return ApprovalGate(
        proxy_model_path=model_path,
        input_provider=AsyncMock(return_value='approve'),
        poc_root=tmpdir,
        proxy_enabled=True,
        never_escalate=never_escalate,
        human_presence=human_presence,
    )


def _make_actor_context(tmpdir, state='TASK_ASSERT', team='art'):
    """Create a minimal ActorContext for testing."""
    from projects.POC.orchestrator.actors import ActorContext
    from projects.POC.orchestrator.events import EventBus
    infra_dir = os.path.join(tmpdir, 'infra')
    worktree = os.path.join(tmpdir, 'worktree')
    os.makedirs(infra_dir, exist_ok=True)
    os.makedirs(worktree, exist_ok=True)
    return ActorContext(
        state=state,
        phase='execution',
        task='test task',
        infra_dir=infra_dir,
        project_workdir=tmpdir,
        session_worktree=worktree,
        stream_file='.exec-stream.jsonl',
        phase_spec=MagicMock(
            artifact='',
            stream_file='.exec-stream.jsonl',
            settings_overlay={},
        ),
        poc_root=tmpdir,
        event_bus=EventBus(),
        session_id='test-session',
        env_vars={'POC_PROJECT': 'test', 'POC_TEAM': team},
    )


class TestHumanPresence(unittest.TestCase):
    """HumanPresence tracks which hierarchy level the human occupies."""

    def test_initial_state_no_presence(self):
        """On construction, no levels are active."""
        hp = _make_presence()
        self.assertFalse(hp.is_present(PresenceLevel.PROJECT))
        self.assertFalse(hp.is_present(PresenceLevel.SUBTEAM))
        self.assertFalse(hp.is_present(PresenceLevel.OFFICE_MANAGER))

    def test_arrive_sets_presence(self):
        """arrive() makes the human present at the specified level."""
        hp = _make_presence()
        hp.arrive(PresenceLevel.SUBTEAM, team='art')
        self.assertTrue(hp.is_present(PresenceLevel.SUBTEAM, team='art'))

    def test_depart_clears_presence(self):
        """depart() removes the human from the specified level."""
        hp = _make_presence()
        hp.arrive(PresenceLevel.SUBTEAM, team='art')
        hp.depart(PresenceLevel.SUBTEAM, team='art')
        self.assertFalse(hp.is_present(PresenceLevel.SUBTEAM, team='art'))

    def test_depart_without_arrive_is_noop(self):
        """depart() on a level not arrived at does nothing."""
        hp = _make_presence()
        hp.depart(PresenceLevel.SUBTEAM, team='art')
        self.assertFalse(hp.is_present(PresenceLevel.SUBTEAM, team='art'))

    def test_arrive_multiple_levels(self):
        """Human can be present at multiple levels simultaneously."""
        hp = _make_presence()
        hp.arrive(PresenceLevel.PROJECT)
        hp.arrive(PresenceLevel.SUBTEAM, team='art')
        self.assertTrue(hp.is_present(PresenceLevel.PROJECT))
        self.assertTrue(hp.is_present(PresenceLevel.SUBTEAM, team='art'))

    def test_subteam_presence_is_team_specific(self):
        """Presence at subteam level is scoped to a specific team."""
        hp = _make_presence()
        hp.arrive(PresenceLevel.SUBTEAM, team='art')
        self.assertTrue(hp.is_present(PresenceLevel.SUBTEAM, team='art'))
        self.assertFalse(hp.is_present(PresenceLevel.SUBTEAM, team='code'))

    def test_active_levels_returns_current_presence(self):
        """active_levels() returns all levels where human is present."""
        hp = _make_presence()
        hp.arrive(PresenceLevel.PROJECT)
        hp.arrive(PresenceLevel.SUBTEAM, team='art')
        levels = hp.active_levels()
        self.assertIn((PresenceLevel.PROJECT, ''), levels)
        self.assertIn((PresenceLevel.SUBTEAM, 'art'), levels)
        self.assertEqual(len(levels), 2)

    def test_arrive_records_timestamp(self):
        """arrive() records when the human arrived for observation tracking."""
        hp = _make_presence()
        hp.arrive(PresenceLevel.SUBTEAM, team='art')
        ts = hp.arrival_time(PresenceLevel.SUBTEAM, team='art')
        self.assertIsNotNone(ts)
        self.assertGreater(ts, 0)

    def test_thread_safety(self):
        """Concurrent arrive/depart calls don't corrupt state."""
        import threading
        hp = _make_presence()
        errors = []

        def toggle(team: str):
            try:
                for _ in range(100):
                    hp.arrive(PresenceLevel.SUBTEAM, team=team)
                    hp.depart(PresenceLevel.SUBTEAM, team=team)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=toggle, args=(f't{i}',)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


class TestGateQueue(unittest.TestCase):
    """GateQueue provides FIFO ordering for concurrent gates."""

    def test_fifo_ordering(self):
        """Gates are dequeued in the order they were enqueued."""
        q = GateQueue()
        r1 = _make_gate_request(state='TASK_ASSERT', team='art')
        r2 = _make_gate_request(state='TASK_ASSERT', team='code')
        r3 = _make_gate_request(state='WORK_ASSERT', team='art')
        q.enqueue(r1)
        q.enqueue(r2)
        q.enqueue(r3)
        self.assertIs(q.dequeue(), r1)
        self.assertIs(q.dequeue(), r2)
        self.assertIs(q.dequeue(), r3)

    def test_dequeue_empty_returns_none(self):
        """dequeue() on empty queue returns None."""
        q = GateQueue()
        self.assertIsNone(q.dequeue())

    def test_has_pending(self):
        """has_pending() reflects queue state."""
        q = GateQueue()
        self.assertFalse(q.has_pending())
        q.enqueue(_make_gate_request())
        self.assertTrue(q.has_pending())
        q.dequeue()
        self.assertFalse(q.has_pending())

    def test_size(self):
        """size() returns the number of pending gates."""
        q = GateQueue()
        q.enqueue(_make_gate_request(team='a'))
        q.enqueue(_make_gate_request(team='b'))
        self.assertEqual(q.size(), 2)

    def test_thread_safe_enqueue_dequeue(self):
        """Concurrent enqueue/dequeue doesn't lose or duplicate items."""
        import threading
        q = GateQueue()
        results = []

        def enqueue_batch(start: int):
            for i in range(50):
                q.enqueue(_make_gate_request(team=f't{start + i}'))

        def dequeue_batch():
            found = []
            for _ in range(50):
                r = q.dequeue()
                if r is not None:
                    found.append(r)
            results.extend(found)

        # Enqueue 100 items from 2 threads
        t1 = threading.Thread(target=enqueue_batch, args=(0,))
        t2 = threading.Thread(target=enqueue_batch, args=(50,))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Dequeue all from 2 threads
        t3 = threading.Thread(target=dequeue_batch)
        t4 = threading.Thread(target=dequeue_batch)
        t3.start()
        t4.start()
        t3.join()
        t4.join()

        # All 100 items should be dequeued exactly once
        self.assertEqual(len(results), 100)
        teams = {r.team for r in results}
        self.assertEqual(len(teams), 100)


class TestDynamicNeverEscalate(unittest.TestCase):
    """_NEVER_ESCALATE_STATES becomes dynamic based on human presence."""

    def test_task_assert_never_escalates_without_presence(self):
        """TASK_ASSERT is never-escalate when human is NOT present at subteam."""
        from projects.POC.orchestrator.human_presence import should_never_escalate
        hp = _make_presence()
        self.assertTrue(should_never_escalate('TASK_ASSERT', hp, team='art'))

    def test_task_assert_escalates_with_presence(self):
        """TASK_ASSERT becomes escalatable when human IS present at subteam."""
        from projects.POC.orchestrator.human_presence import should_never_escalate
        hp = _make_presence()
        hp.arrive(PresenceLevel.SUBTEAM, team='art')
        self.assertFalse(should_never_escalate('TASK_ASSERT', hp, team='art'))

    def test_work_assert_always_escalatable(self):
        """WORK_ASSERT is always escalatable (project-level gate)."""
        from projects.POC.orchestrator.human_presence import should_never_escalate
        hp = _make_presence()
        self.assertFalse(should_never_escalate('WORK_ASSERT', hp))

    def test_no_presence_preserves_original_behavior(self):
        """With no HumanPresence object, original static set applies."""
        from projects.POC.orchestrator.human_presence import should_never_escalate
        self.assertTrue(should_never_escalate('TASK_ASSERT', None, team='art'))
        self.assertTrue(should_never_escalate('TASK_ESCALATE', None, team='art'))


class TestProxyHandoff(unittest.TestCase):
    """Proxy steps aside when human arrives, resumes when they leave."""

    def test_proxy_routes_to_human_when_present(self):
        """When human is present at the gate's level, route directly to human."""
        hp = _make_presence()
        hp.arrive(PresenceLevel.SUBTEAM, team='art')
        # The presence check should indicate proxy should NOT answer
        self.assertTrue(hp.human_should_answer('TASK_ASSERT', team='art'))

    def test_proxy_answers_when_absent(self):
        """When human is absent, proxy answers as usual."""
        hp = _make_presence()
        self.assertFalse(hp.human_should_answer('TASK_ASSERT', team='art'))

    def test_project_level_gate_checks_project_presence(self):
        """Project-level gates (WORK_ASSERT, INTENT_ASSERT) check project presence."""
        hp = _make_presence()
        hp.arrive(PresenceLevel.PROJECT)
        self.assertTrue(hp.human_should_answer('WORK_ASSERT'))
        self.assertTrue(hp.human_should_answer('INTENT_ASSERT'))

    def test_office_manager_level_presence(self):
        """Office manager level presence routes OM queries to human."""
        hp = _make_presence()
        hp.arrive(PresenceLevel.OFFICE_MANAGER)
        self.assertTrue(hp.human_should_answer('OFFICE_MANAGER'))


class TestObservationRecording(unittest.TestCase):
    """Proxy records observation chunks during direct human participation."""

    def test_observe_records_chunk(self):
        """When human answers directly, an observation chunk is created."""
        hp = _make_presence()
        hp.arrive(PresenceLevel.SUBTEAM, team='art')

        observation = hp.record_observation(
            level=PresenceLevel.SUBTEAM,
            team='art',
            state='TASK_ASSERT',
            human_response='The test coverage looks good, approved.',
            context='Review of test_widget.py changes',
        )
        self.assertIsNotNone(observation)
        self.assertEqual(observation.state, 'TASK_ASSERT')
        self.assertEqual(observation.team, 'art')
        self.assertIn('approved', observation.human_response)

    def test_observations_accumulate(self):
        """Multiple observations during a presence session accumulate."""
        hp = _make_presence()
        hp.arrive(PresenceLevel.SUBTEAM, team='art')

        hp.record_observation(
            level=PresenceLevel.SUBTEAM, team='art',
            state='TASK_ASSERT', human_response='Looks good.',
            context='First review',
        )
        hp.record_observation(
            level=PresenceLevel.SUBTEAM, team='art',
            state='TASK_ASSERT', human_response='Needs more tests.',
            context='Second review',
        )

        observations = hp.get_observations(PresenceLevel.SUBTEAM, team='art')
        self.assertEqual(len(observations), 2)

    def test_depart_returns_observations(self):
        """depart() returns accumulated observations for proxy learning."""
        hp = _make_presence()
        hp.arrive(PresenceLevel.SUBTEAM, team='art')

        hp.record_observation(
            level=PresenceLevel.SUBTEAM, team='art',
            state='TASK_ASSERT', human_response='Good work.',
            context='Review',
        )

        observations = hp.depart(PresenceLevel.SUBTEAM, team='art')
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].human_response, 'Good work.')

    def test_no_observation_when_not_present(self):
        """record_observation returns None when human is not present."""
        hp = _make_presence()
        observation = hp.record_observation(
            level=PresenceLevel.SUBTEAM, team='art',
            state='TASK_ASSERT', human_response='test',
            context='test',
        )
        self.assertIsNone(observation)


class TestBackwardCompatibility(unittest.TestCase):
    """Sessions without arrive/depart behave exactly as before."""

    def test_no_presence_object_is_proxy_only(self):
        """When no HumanPresence is configured, proxy always stands in."""
        from projects.POC.orchestrator.human_presence import should_never_escalate
        # None means no presence tracking — original behavior
        self.assertTrue(should_never_escalate('TASK_ASSERT', None))

    def test_fresh_presence_matches_original_behavior(self):
        """A HumanPresence with no arrive() calls matches original behavior."""
        hp = _make_presence()
        self.assertFalse(hp.human_should_answer('TASK_ASSERT', team='art'))
        self.assertFalse(hp.human_should_answer('WORK_ASSERT'))
        self.assertFalse(hp.human_should_answer('INTENT_ASSERT'))


class TestApprovalGateHumanPresenceIntegration(unittest.TestCase):
    """ApprovalGate._ask_human_through_proxy routes based on HumanPresence."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_human_present_routes_to_input_provider(self):
        """When human is present at subteam, gate asks human directly."""
        hp = _make_presence()
        hp.arrive(PresenceLevel.SUBTEAM, team='art')
        gate = _make_approval_gate(self.tmpdir, human_presence=hp)
        ctx = _make_actor_context(self.tmpdir, state='TASK_ASSERT', team='art')

        # Mock consult_proxy to return a low-confidence result (would normally
        # trigger escalation, but presence check should short-circuit first)
        proxy_result = MagicMock(
            text='proxy says approve', confidence=0.5,
            from_agent=True,
            prior_action='approve', prior_confidence=0.5,
            posterior_action='approve', posterior_confidence=0.5,
            prediction_delta='', salient_percepts=[],
        )
        with patch('projects.POC.orchestrator.proxy_agent.consult_proxy',
                   new_callable=AsyncMock, return_value=proxy_result):
            text, from_proxy = _run(gate._ask_human_through_proxy(
                ctx=ctx, question='Review this?',
                artifact_path='', project_slug='test', team='art',
                dialog_history='',
            ))

        # Human answered, not proxy
        self.assertFalse(from_proxy)
        # The input_provider was called (human answered)
        gate.input_provider.assert_called_once()

    def test_human_absent_uses_proxy(self):
        """When human is absent, proxy answers as usual (never-escalate state)."""
        hp = _make_presence()
        # Human NOT present at subteam
        gate = _make_approval_gate(self.tmpdir, human_presence=hp)
        ctx = _make_actor_context(self.tmpdir, state='TASK_ASSERT', team='art')

        proxy_result = MagicMock(
            text='proxy approves', confidence=0.9,
            from_agent=True,
            prior_action='approve', prior_confidence=0.9,
            posterior_action='approve', posterior_confidence=0.9,
            prediction_delta='', salient_percepts=[],
        )
        with patch('projects.POC.orchestrator.proxy_agent.consult_proxy',
                   new_callable=AsyncMock, return_value=proxy_result):
            text, from_proxy = _run(gate._ask_human_through_proxy(
                ctx=ctx, question='Review this?',
                artifact_path='', project_slug='test', team='art',
                dialog_history='',
            ))

        # Proxy answered (confident)
        self.assertTrue(from_proxy)
        self.assertEqual(text, 'proxy approves')
        # Human input_provider was NOT called
        gate.input_provider.assert_not_called()

    def test_presence_records_observation_on_direct_answer(self):
        """When human answers directly, an observation is recorded."""
        hp = _make_presence()
        hp.arrive(PresenceLevel.SUBTEAM, team='art')
        gate = _make_approval_gate(self.tmpdir, human_presence=hp)
        ctx = _make_actor_context(self.tmpdir, state='TASK_ASSERT', team='art')

        proxy_result = MagicMock(
            text='proxy text', confidence=0.5, from_agent=True,
            prior_action='approve', prior_confidence=0.5,
            posterior_action='approve', posterior_confidence=0.5,
            prediction_delta='', salient_percepts=[],
        )
        with patch('projects.POC.orchestrator.proxy_agent.consult_proxy',
                   new_callable=AsyncMock, return_value=proxy_result):
            _run(gate._ask_human_through_proxy(
                ctx=ctx, question='Review this?',
                artifact_path='test.py', project_slug='test', team='art',
                dialog_history='',
            ))

        # Check that an observation was recorded
        observations = hp.get_observations(PresenceLevel.SUBTEAM, team='art')
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].state, 'TASK_ASSERT')
        self.assertEqual(observations[0].human_response, 'approve')

    def test_no_presence_object_preserves_never_escalate(self):
        """ApprovalGate without HumanPresence preserves original behavior."""
        gate = _make_approval_gate(self.tmpdir, human_presence=None)
        ctx = _make_actor_context(self.tmpdir, state='TASK_ASSERT', team='art')

        # Proxy not confident, but TASK_ASSERT is never-escalate → proxy answers
        proxy_result = MagicMock(
            text='proxy guess', confidence=0.3,
            from_agent=True,
            prior_action='approve', prior_confidence=0.3,
            posterior_action='approve', posterior_confidence=0.3,
            prediction_delta='', salient_percepts=[],
        )
        with patch('projects.POC.orchestrator.proxy_agent.consult_proxy',
                   new_callable=AsyncMock, return_value=proxy_result):
            text, from_proxy = _run(gate._ask_human_through_proxy(
                ctx=ctx, question='Review this?',
                artifact_path='', project_slug='test', team='art',
                dialog_history='',
            ))

        # Proxy answered (never-escalate, original behavior)
        self.assertTrue(from_proxy)
        self.assertEqual(text, 'proxy guess')

    def test_human_present_at_wrong_level_still_uses_proxy(self):
        """Human present at project level doesn't affect subteam gates."""
        hp = _make_presence()
        hp.arrive(PresenceLevel.PROJECT)  # present at project, not subteam
        gate = _make_approval_gate(self.tmpdir, human_presence=hp)
        ctx = _make_actor_context(self.tmpdir, state='TASK_ASSERT', team='art')

        proxy_result = MagicMock(
            text='proxy answers', confidence=0.9,
            from_agent=True,
            prior_action='approve', prior_confidence=0.9,
            posterior_action='approve', posterior_confidence=0.9,
            prediction_delta='', salient_percepts=[],
        )
        with patch('projects.POC.orchestrator.proxy_agent.consult_proxy',
                   new_callable=AsyncMock, return_value=proxy_result):
            text, from_proxy = _run(gate._ask_human_through_proxy(
                ctx=ctx, question='Review this?',
                artifact_path='', project_slug='test', team='art',
                dialog_history='',
            ))

        # Proxy answered — human at project level doesn't affect task gate
        self.assertTrue(from_proxy)


class TestOrchestratorHumanPresenceWiring(unittest.TestCase):
    """Orchestrator passes HumanPresence through to ApprovalGate."""

    def test_orchestrator_passes_presence_to_gate(self):
        """Orchestrator constructor wires human_presence to ApprovalGate."""
        from projects.POC.orchestrator.engine import Orchestrator
        from projects.POC.orchestrator.events import EventBus
        from projects.POC.scripts.cfa_state import make_initial_state
        from projects.POC.orchestrator.phase_config import PhaseConfig

        tmpdir = tempfile.mkdtemp()
        try:
            infra_dir = os.path.join(tmpdir, 'infra')
            worktree = os.path.join(tmpdir, 'worktree')
            os.makedirs(infra_dir)
            os.makedirs(worktree)

            hp = _make_presence()
            cfa = make_initial_state()

            orch = Orchestrator(
                cfa_state=cfa,
                phase_config=MagicMock(stall_timeout=300),
                event_bus=EventBus(),
                input_provider=AsyncMock(),
                infra_dir=infra_dir,
                project_workdir=tmpdir,
                session_worktree=worktree,
                proxy_model_path=os.path.join(tmpdir, '.proxy-confidence.json'),
                project_slug='test',
                poc_root=tmpdir,
                human_presence=hp,
            )
            self.assertIs(orch.human_presence, hp)
            self.assertIs(orch._approval_gate.human_presence, hp)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_orchestrator_without_presence_is_none(self):
        """Orchestrator without human_presence has None on gate."""
        from projects.POC.orchestrator.engine import Orchestrator
        from projects.POC.orchestrator.events import EventBus
        from projects.POC.scripts.cfa_state import make_initial_state
        from projects.POC.orchestrator.phase_config import PhaseConfig

        tmpdir = tempfile.mkdtemp()
        try:
            infra_dir = os.path.join(tmpdir, 'infra')
            worktree = os.path.join(tmpdir, 'worktree')
            os.makedirs(infra_dir)
            os.makedirs(worktree)

            cfa = make_initial_state()
            orch = Orchestrator(
                cfa_state=cfa,
                phase_config=MagicMock(stall_timeout=300),
                event_bus=EventBus(),
                input_provider=AsyncMock(),
                infra_dir=infra_dir,
                project_workdir=tmpdir,
                session_worktree=worktree,
                proxy_model_path=os.path.join(tmpdir, '.proxy-confidence.json'),
                project_slug='test',
                poc_root=tmpdir,
            )
            self.assertIsNone(orch.human_presence)
            self.assertIsNone(orch._approval_gate.human_presence)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestGateSerialization(unittest.TestCase):
    """Concurrent gates are serialized via _gate_lock (Issue #202 FIFO)."""

    def test_gate_lock_serializes_concurrent_calls(self):
        """Two concurrent _ask_human_through_proxy calls execute sequentially."""
        tmpdir = tempfile.mkdtemp()
        try:
            hp = _make_presence()
            gate = _make_approval_gate(tmpdir, human_presence=hp)

            call_order = []

            original_inner = gate._ask_human_through_proxy_inner

            async def tracking_inner(*args, **kwargs):
                call_order.append('start')
                await asyncio.sleep(0.05)
                call_order.append('end')
                return ('ok', True)

            gate._ask_human_through_proxy_inner = tracking_inner

            async def run_two():
                ctx = _make_actor_context(tmpdir, state='TASK_ASSERT', team='art')
                t1 = asyncio.create_task(gate._ask_human_through_proxy(
                    ctx=ctx, question='q1', artifact_path='',
                    project_slug='test', team='art', dialog_history='',
                ))
                t2 = asyncio.create_task(gate._ask_human_through_proxy(
                    ctx=ctx, question='q2', artifact_path='',
                    project_slug='test', team='art', dialog_history='',
                ))
                await asyncio.gather(t1, t2)

            _run(run_two())
            # If serialized: start, end, start, end (not interleaved)
            self.assertEqual(call_order, ['start', 'end', 'start', 'end'])
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_gate_queue_enqueue_dequeue_called(self):
        """GateQueue.enqueue and dequeue are called during gate processing."""
        from projects.POC.orchestrator.gate_queue import GateQueue
        tmpdir = tempfile.mkdtemp()
        try:
            gq = GateQueue()
            from projects.POC.orchestrator.actors import ApprovalGate
            model_path = os.path.join(tmpdir, 'project', '.proxy-confidence.json')
            os.makedirs(os.path.dirname(model_path), exist_ok=True)
            Path(model_path).write_text('{}')
            gate = ApprovalGate(
                proxy_model_path=model_path,
                input_provider=AsyncMock(return_value='approve'),
                poc_root=tmpdir,
                human_presence=_make_presence(),
                gate_queue=gq,
            )
            ctx = _make_actor_context(tmpdir, state='TASK_ASSERT', team='art')

            proxy_result = MagicMock(
                text='proxy ok', confidence=0.9, from_agent=True,
                prior_action='approve', prior_confidence=0.9,
                posterior_action='approve', posterior_confidence=0.9,
                prediction_delta='', salient_percepts=[],
            )
            with patch('projects.POC.orchestrator.proxy_agent.consult_proxy',
                       new_callable=AsyncMock, return_value=proxy_result):
                _run(gate._ask_human_through_proxy(
                    ctx=ctx, question='q', artifact_path='',
                    project_slug='test', team='art', dialog_history='',
                ))

            # Queue should be empty after dequeue (enqueue then dequeue happened)
            self.assertEqual(gq.size(), 0)
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class TestObservationLevelMapping(unittest.TestCase):
    """Observation recording uses _STATE_TO_LEVEL, not heuristic."""

    def test_office_manager_state_records_at_om_level(self):
        """OFFICE_MANAGER state observations are recorded at OFFICE_MANAGER level."""
        hp = _make_presence()
        hp.arrive(PresenceLevel.OFFICE_MANAGER)
        obs = hp.record_observation(
            level=PresenceLevel.OFFICE_MANAGER,
            team='',
            state='OFFICE_MANAGER',
            human_response='looks good',
            context='test',
        )
        self.assertIsNotNone(obs)
        observations = hp.get_observations(PresenceLevel.OFFICE_MANAGER)
        self.assertEqual(len(observations), 1)

    def test_state_to_level_mapping_used_in_gate(self):
        """The _STATE_TO_LEVEL mapping is imported and accessible in actors."""
        from projects.POC.orchestrator.human_presence import _STATE_TO_LEVEL
        self.assertEqual(_STATE_TO_LEVEL['TASK_ASSERT'], PresenceLevel.SUBTEAM)
        self.assertEqual(_STATE_TO_LEVEL['WORK_ASSERT'], PresenceLevel.PROJECT)
        self.assertEqual(_STATE_TO_LEVEL['OFFICE_MANAGER'], PresenceLevel.OFFICE_MANAGER)


class TestACTRPersistenceFromHumanPresence(unittest.TestCase):
    """Human-present path persists observations to ACT-R memory."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_human_present_calls_proxy_record(self):
        """When human answers directly, _proxy_record is called for ACT-R storage."""
        hp = _make_presence()
        hp.arrive(PresenceLevel.SUBTEAM, team='art')
        gate = _make_approval_gate(self.tmpdir, human_presence=hp)
        ctx = _make_actor_context(self.tmpdir, state='TASK_ASSERT', team='art')

        proxy_result = MagicMock(
            text='proxy text', confidence=0.5, from_agent=True,
            prior_action='approve', prior_confidence=0.5,
            posterior_action='approve', posterior_confidence=0.5,
            prediction_delta='', salient_percepts=[],
        )
        with patch('projects.POC.orchestrator.proxy_agent.consult_proxy',
                   new_callable=AsyncMock, return_value=proxy_result), \
             patch.object(gate, '_proxy_record') as mock_record, \
             patch.object(gate, '_log_interaction') as mock_log:
            _run(gate._ask_human_through_proxy(
                ctx=ctx, question='Review this?',
                artifact_path='test.py', project_slug='test', team='art',
                dialog_history='',
            ))

        mock_record.assert_called_once()
        mock_log.assert_called_once()
        # Verify _log_interaction was called with 'human_direct' outcome
        log_call = mock_log.call_args
        self.assertEqual(log_call[1].get('outcome') or log_call[0][3], 'human_direct')


if __name__ == '__main__':
    unittest.main()
