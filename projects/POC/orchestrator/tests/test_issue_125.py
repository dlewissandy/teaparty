#!/usr/bin/env python3
"""Tests for Issue #125: Proxy-driven intake dialog for intent and planning phases.

Phase 1 requirements:
 1. Cold-start detection — proxy observation count exposed to agent context
 2. Cold-start context injected into agent task prompt on cold start
 3. Bridge text reframing — "wants to discuss" at escalation states
 4. Observation count uses approval_state (INTENT_ASSERT), not current state (PROPOSAL)
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.actors import (
    ActorContext,
    ActorResult,
    AgentRunner,
    ApprovalGate,
)
from projects.POC.orchestrator.engine import Orchestrator
from projects.POC.orchestrator.events import EventBus, InputRequest
from projects.POC.orchestrator.phase_config import PhaseConfig, PhaseSpec
from projects.POC.scripts.approval_gate import (
    COLD_START_THRESHOLD,
    ConfidenceModel,
    make_model,
    record_outcome,
    save_model,
)
from projects.POC.scripts.cfa_state import CfaState


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    """Run a coroutine synchronously for testing."""
    return asyncio.run(coro)


def _make_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


def _make_phase_spec(
    name: str = 'intent',
    artifact: str | None = 'INTENT.md',
    escalation_file: str = '.intent-escalation.md',
    approval_state: str = 'INTENT_ASSERT',
    escalation_state: str = 'INTENT_ESCALATE',
) -> PhaseSpec:
    return PhaseSpec(
        name=name,
        agent_file='agents/intent-team.json',
        lead='intent-lead',
        permission_mode='acceptEdits',
        stream_file='.intent-stream.jsonl',
        artifact=artifact,
        approval_state=approval_state,
        escalation_state=escalation_state,
        escalation_file=escalation_file,
        settings_overlay={},
    )


def _make_phase_config() -> PhaseConfig:
    """Build a minimal PhaseConfig mock."""
    cfg = MagicMock(spec=PhaseConfig)
    cfg.stall_timeout = 1800
    cfg.human_actor_states = frozenset({
        'INTENT_ASSERT', 'INTENT_ESCALATE',
        'PLAN_ASSERT', 'PLANNING_ESCALATE',
    })
    cfg.phase.return_value = _make_phase_spec()
    cfg.team.return_value = MagicMock()
    return cfg


def _make_cfa_state(state: str = 'PROPOSAL', phase: str = 'intent') -> CfaState:
    return CfaState(
        state=state,
        phase=phase,
        actor='agent',
        history=[],
        backtrack_count=0,
    )


def _make_proxy_model_with_observations(
    state: str, task_type: str, count: int,
) -> ConfidenceModel:
    """Build a proxy model with `count` approve observations for a state-task pair."""
    model = make_model()
    for _ in range(count):
        model = record_outcome(model, state, task_type, 'approve')
    return model


def _make_orchestrator(
    cfa_state: CfaState | None = None,
    proxy_model_path: str = '/tmp/proxy.json',
    project_slug: str = 'test-project',
    task: str = 'Build a feature',
    last_actor_data: dict | None = None,
) -> Orchestrator:
    if cfa_state is None:
        cfa_state = _make_cfa_state()
    return Orchestrator(
        cfa_state=cfa_state,
        phase_config=_make_phase_config(),
        event_bus=_make_event_bus(),
        input_provider=AsyncMock(return_value='approve'),
        infra_dir='/tmp/infra',
        project_workdir='/tmp/project',
        session_worktree='/tmp/worktree',
        proxy_model_path=proxy_model_path,
        project_slug=project_slug,
        poc_root='/tmp/poc',
        task=task,
        session_id='test-session',
        last_actor_data=last_actor_data or {},
    )


def _make_ctx(
    state: str = 'INTENT_ESCALATE',
    phase: str = 'intent',
    env_vars: dict | None = None,
) -> ActorContext:
    return ActorContext(
        state=state,
        phase=phase,
        task='Build a feature',
        infra_dir='/tmp/infra',
        project_workdir='/tmp/project',
        session_worktree='/tmp/worktree',
        stream_file='.intent-stream.jsonl',
        phase_spec=_make_phase_spec(),
        poc_root='/tmp/poc',
        event_bus=_make_event_bus(),
        session_id='test-session',
        env_vars=env_vars or {},
    )


# ── Test 1: Cold-start observation count in env vars ─────────────────────────

class TestColdStartObservationCountInEnvVars(unittest.TestCase):
    """The orchestrator must expose proxy observation count via POC_PROXY_OBSERVATIONS."""

    def test_env_vars_include_observation_count(self):
        """_build_env_vars includes POC_PROXY_OBSERVATIONS from the proxy model."""
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = os.path.join(tmpdir, '.proxy-confidence.json')
            model = _make_proxy_model_with_observations(
                'INTENT_ASSERT', 'test-project', count=3,
            )
            save_model(model, model_path)

            orch = _make_orchestrator(proxy_model_path=model_path)
            env = orch._build_env_vars()

            self.assertIn('POC_PROXY_OBSERVATIONS', env)
            self.assertEqual(env['POC_PROXY_OBSERVATIONS'], '3')

    def test_env_vars_zero_when_no_model_file(self):
        """When proxy model doesn't exist, POC_PROXY_OBSERVATIONS defaults to '0'."""
        orch = _make_orchestrator(
            proxy_model_path='/nonexistent/proxy.json',
        )
        env = orch._build_env_vars()

        self.assertIn('POC_PROXY_OBSERVATIONS', env)
        self.assertEqual(env['POC_PROXY_OBSERVATIONS'], '0')

    def test_observation_count_uses_approval_state_not_current_state(self):
        """Count is looked up against INTENT_ASSERT (approval state), not PROPOSAL (current state).

        Pre-mortem Risk 4: if we check PROPOSAL instead of INTENT_ASSERT,
        the count will always be 0 because observations are recorded at INTENT_ASSERT.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = os.path.join(tmpdir, '.proxy-confidence.json')
            # Record observations at INTENT_ASSERT (where gate decisions happen)
            model = _make_proxy_model_with_observations(
                'INTENT_ASSERT', 'test-project', count=7,
            )
            save_model(model, model_path)

            orch = _make_orchestrator(
                cfa_state=_make_cfa_state(state='PROPOSAL'),
                proxy_model_path=model_path,
            )
            env = orch._build_env_vars()

            # Must reflect INTENT_ASSERT observations, not PROPOSAL (which has 0)
            self.assertEqual(env['POC_PROXY_OBSERVATIONS'], '7')

    def test_planning_phase_uses_plan_assert_count(self):
        """For the planning phase, observation count comes from PLAN_ASSERT."""
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = os.path.join(tmpdir, '.proxy-confidence.json')
            model = _make_proxy_model_with_observations(
                'PLAN_ASSERT', 'test-project', count=12,
            )
            save_model(model, model_path)

            cfg = _make_phase_config()
            cfg.phase.return_value = _make_phase_spec(
                name='planning',
                artifact='PLAN.md',
                approval_state='PLAN_ASSERT',
                escalation_state='PLANNING_ESCALATE',
                escalation_file='.plan-escalation.md',
            )

            orch = _make_orchestrator(
                cfa_state=_make_cfa_state(state='DRAFT', phase='planning'),
                proxy_model_path=model_path,
            )
            orch.config = cfg
            env = orch._build_env_vars()

            self.assertEqual(env['POC_PROXY_OBSERVATIONS'], '12')


# ── Test 2: Cold-start context in agent task prompt ──────────────────────────

class TestColdStartContextInTaskPrompt(unittest.TestCase):
    """On cold start, the agent task prompt must include cold-start context."""

    def test_cold_start_context_injected_below_threshold(self):
        """When observation count < COLD_START_THRESHOLD, task prompt includes cold-start context."""
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = os.path.join(tmpdir, '.proxy-confidence.json')
            model = _make_proxy_model_with_observations(
                'INTENT_ASSERT', 'test-project', count=2,
            )
            save_model(model, model_path)

            orch = _make_orchestrator(
                proxy_model_path=model_path,
                task='Build a widget',
            )

            # Capture the task prompt the agent would receive
            task_prompt = orch._task_for_phase('intent')

            # Must contain cold-start indicator
            self.assertIn('cold start', task_prompt.lower())

    def test_no_cold_start_context_above_threshold(self):
        """When observation count >= COLD_START_THRESHOLD, no cold-start context is injected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            model_path = os.path.join(tmpdir, '.proxy-confidence.json')
            model = _make_proxy_model_with_observations(
                'INTENT_ASSERT', 'test-project', count=COLD_START_THRESHOLD + 5,
            )
            save_model(model, model_path)

            orch = _make_orchestrator(
                proxy_model_path=model_path,
                task='Build a widget',
            )

            task_prompt = orch._task_for_phase('intent')

            # Should NOT contain cold-start context
            self.assertNotIn('cold start', task_prompt.lower())


# ── Test 3: Bridge text reframing ────────────────────────────────────────────

class TestBridgeTextReframing(unittest.TestCase):
    """At escalation states, bridge text must use 'wants to discuss' framing."""

    def test_intent_escalate_bridge_uses_discuss_framing(self):
        """At INTENT_ESCALATE, bridge text says 'wants to discuss', not 'escalated'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            esc_path = os.path.join(tmpdir, '.intent-escalation.md')
            Path(esc_path).write_text(
                'I found some relevant code. Before I write this up:\n'
                '1. Should we include offline support?\n'
                '2. What is the target audience?\n'
            )

            gate = ApprovalGate(
                proxy_model_path='/tmp/proxy.json',
                input_provider=AsyncMock(return_value='approve'),
                poc_root='/tmp/poc',
            )

            ctx = _make_ctx(state='INTENT_ESCALATE')
            ctx.data = {'escalation_file': esc_path}

            # Capture what bridge text is shown to the human
            captured_bridge = []
            original_provider = gate.input_provider

            async def capture_input(request: InputRequest) -> str:
                captured_bridge.append(request.bridge_text)
                return 'approve'

            gate.input_provider = capture_input

            # The gate tries generative response first; mock it to return None
            # so it falls through to the human path.
            with patch.object(gate, '_try_generate_response', return_value=None):
                _run(gate.run(ctx))

            self.assertTrue(len(captured_bridge) > 0, 'No bridge text captured')
            bridge = captured_bridge[0]
            # Must use engagement framing
            self.assertIn('discuss', bridge.lower())
            # Must NOT use escalation framing
            self.assertNotIn('escalated', bridge.lower())

    def test_planning_escalate_bridge_uses_discuss_framing(self):
        """At PLANNING_ESCALATE, bridge text says 'wants to discuss'."""
        with tempfile.TemporaryDirectory() as tmpdir:
            esc_path = os.path.join(tmpdir, '.plan-escalation.md')
            Path(esc_path).write_text(
                'I see two viable approaches. Which direction feels right?\n'
            )

            gate = ApprovalGate(
                proxy_model_path='/tmp/proxy.json',
                input_provider=AsyncMock(return_value='approve'),
                poc_root='/tmp/poc',
            )

            spec = _make_phase_spec(
                name='planning',
                artifact='PLAN.md',
                approval_state='PLAN_ASSERT',
                escalation_state='PLANNING_ESCALATE',
                escalation_file='.plan-escalation.md',
            )
            ctx = _make_ctx(state='PLANNING_ESCALATE', phase='planning')
            ctx.phase_spec = spec
            ctx.data = {'escalation_file': esc_path}

            captured_bridge = []

            async def capture_input(request: InputRequest) -> str:
                captured_bridge.append(request.bridge_text)
                return 'approve'

            gate.input_provider = capture_input

            with patch.object(gate, '_try_generate_response', return_value=None):
                _run(gate.run(ctx))

            self.assertTrue(len(captured_bridge) > 0, 'No bridge text captured')
            bridge = captured_bridge[0]
            self.assertIn('discuss', bridge.lower())
            self.assertNotIn('escalated', bridge.lower())


# ── Test 4: Escalation bridge includes escalation file content ───────────────

class TestEscalationBridgeIncludesContent(unittest.TestCase):
    """When an escalation file exists, its content must appear in the bridge text."""

    def test_escalation_file_content_in_bridge(self):
        """The intake dialog content from the escalation file is shown to the human."""
        with tempfile.TemporaryDirectory() as tmpdir:
            esc_path = os.path.join(tmpdir, '.intent-escalation.md')
            content = (
                "I've looked at the codebase and here's what's relevant:\n"
                "A few things I want to confirm:\n"
                "1. Should we support offline mode?\n"
            )
            Path(esc_path).write_text(content)

            gate = ApprovalGate(
                proxy_model_path='/tmp/proxy.json',
                input_provider=AsyncMock(return_value='approve'),
                poc_root='/tmp/poc',
            )

            ctx = _make_ctx(state='INTENT_ESCALATE')
            ctx.data = {'escalation_file': esc_path}

            captured_bridge = []

            async def capture_input(request: InputRequest) -> str:
                captured_bridge.append(request.bridge_text)
                return 'approve'

            gate.input_provider = capture_input

            with patch.object(gate, '_try_generate_response', return_value=None):
                _run(gate.run(ctx))

            self.assertTrue(len(captured_bridge) > 0)
            bridge = captured_bridge[0]
            # The agent's questions must be visible in the bridge
            self.assertIn('offline mode', bridge.lower())


if __name__ == '__main__':
    unittest.main()
