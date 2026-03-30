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
sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.engine import Orchestrator
from orchestrator.events import EventBus
from orchestrator.phase_config import PhaseConfig, PhaseSpec
from scripts.approval_gate import (
    COLD_START_THRESHOLD,
    ConfidenceModel,
    make_model,
    record_outcome,
    save_model,
)
from scripts.cfa_state import CfaState


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
    approval_state: str = 'INTENT_ASSERT',
) -> PhaseSpec:
    return PhaseSpec(
        name=name,
        agent_file='agents/intent-team.json',
        lead='intent-lead',
        permission_mode='acceptEdits',
        stream_file='.intent-stream.jsonl',
        artifact=artifact,
        approval_state=approval_state,
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


# ── Test 3: Agent prompts modified for cold-start engagement ─────────────────

class TestAgentPromptsModifiedForColdStart(unittest.TestCase):
    """Agent prompts must support exploration + engagement on cold start."""

    def _load_agent_prompt(self, filename: str, agent_name: str) -> str:
        """Load an agent prompt from the agents JSON file."""
        agents_dir = Path(__file__).parent.parent / 'agents'
        with open(agents_dir / filename) as f:
            agents = json.load(f)
        return agents[agent_name]['prompt']

    def test_intent_lead_does_not_say_prefer_assert(self):
        """The intent-lead prompt must not say 'Prefer this over escalating.'

        This phrase actively suppresses the intake dialog pattern by biasing
        the agent toward one-shot artifact production even on cold start.
        """
        prompt = self._load_agent_prompt('intent-team.json', 'intent-lead')
        self.assertNotIn('Prefer this over escalating', prompt)

    def test_intent_lead_does_not_say_single_autonomous_pass(self):
        """The intent-lead prompt must not mandate a single autonomous pass.

        On cold start, the agent should explore and engage before producing
        the artifact. 'Single autonomous pass' contradicts this.
        """
        prompt = self._load_agent_prompt('intent-team.json', 'intent-lead')
        self.assertNotIn('single autonomous pass', prompt)

    def test_intent_lead_references_cold_start(self):
        """The intent-lead prompt must reference cold start context."""
        prompt = self._load_agent_prompt('intent-team.json', 'intent-lead')
        self.assertIn('cold start', prompt.lower())

    def test_intent_lead_frames_escalation_as_engagement(self):
        """The intent-lead prompt must frame escalation as engagement on cold start."""
        prompt = self._load_agent_prompt('intent-team.json', 'intent-lead')
        lower = prompt.lower()
        # Must contain engagement framing language in the escalation section
        self.assertTrue(
            'engagement' in lower or 'colleague' in lower or 'checking' in lower,
            'Intent-lead prompt must frame cold-start escalation as engagement',
        )

    def test_project_lead_does_not_say_single_autonomous_pass(self):
        """The project-lead prompt must not mandate a single autonomous pass."""
        prompt = self._load_agent_prompt('uber-team.json', 'project-lead')
        self.assertNotIn('single autonomous pass', prompt)

    def test_project_lead_references_cold_start(self):
        """The project-lead prompt must reference cold start context."""
        prompt = self._load_agent_prompt('uber-team.json', 'project-lead')
        self.assertIn('cold start', prompt.lower())

    def test_project_lead_frames_escalation_as_engagement(self):
        """The project-lead prompt must frame escalation as engagement on cold start."""
        prompt = self._load_agent_prompt('uber-team.json', 'project-lead')
        lower = prompt.lower()
        self.assertTrue(
            'engagement' in lower or 'colleague' in lower or 'checking' in lower,
            'Project-lead prompt must frame cold-start escalation as engagement',
        )


if __name__ == '__main__':
    unittest.main()
