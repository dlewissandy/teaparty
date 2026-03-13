#!/usr/bin/env python3
"""Tests for actors.py — AgentRunner._interpret_output and ApprovalGate.run.

Covers:
 1. Missing artifact triggers approval gate (not auto-approve)
 2. Present artifact goes through normal assert → approval gate flow
 3. No artifact configured → auto-approve (no gate)
 4. ApprovalGate receives artifact_missing=True in context data
 5. ApprovalGate generates missing-artifact bridge text
 6. ApprovalGate does not auto-approve when artifact is missing
    (even when proxy would say auto-approve for the state)
"""
import asyncio
import os
import sys
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.actors import (
    ActorContext,
    ActorResult,
    AgentRunner,
    ApprovalGate,
)
from projects.POC.orchestrator.claude_runner import ClaudeResult
from projects.POC.orchestrator.events import EventBus
from projects.POC.orchestrator.phase_config import PhaseSpec


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


def _make_phase_spec(
    artifact: str | None = 'INTENT.md',
    escalation_file: str = '.intent-escalation.md',
) -> PhaseSpec:
    return PhaseSpec(
        name='intent',
        agent_file='agents/intent-team.json',
        lead='intent-lead',
        permission_mode='acceptEdits',
        stream_file='.intent-stream.jsonl',
        artifact=artifact,
        approval_state='INTENT_ASSERT',
        escalation_state='INTENT_ESCALATE',
        escalation_file=escalation_file,
        settings_overlay={},
    )


def _make_ctx(
    state: str = 'PROPOSAL',
    session_worktree: str = '/tmp/worktree',
    phase_spec: PhaseSpec | None = None,
    infra_dir: str = '/tmp/infra',
) -> ActorContext:
    if phase_spec is None:
        phase_spec = _make_phase_spec()
    return ActorContext(
        state=state,
        phase='intent',
        task='Write a blog post about AI',
        infra_dir=infra_dir,
        project_workdir='/tmp/project',
        session_worktree=session_worktree,
        stream_file='.intent-stream.jsonl',
        phase_spec=phase_spec,
        poc_root='/tmp/poc',
        event_bus=_make_event_bus(),
        session_id='test-session',
    )


def _make_claude_result(exit_code: int = 0, session_id: str = 'claude-abc') -> ClaudeResult:
    return ClaudeResult(exit_code=exit_code, session_id=session_id)


def _run(coro):
    """Run a coroutine synchronously for testing."""
    return asyncio.run(coro)


# ── AgentRunner._interpret_output ─────────────────────────────────────────────

class TestInterpretOutputMissingArtifact(unittest.TestCase):
    """Missing artifact must route to the approval gate, not auto-approve."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.runner = AgentRunner()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_ctx_in_tmpdir(self, state='PROPOSAL', artifact='INTENT.md'):
        spec = _make_phase_spec(artifact=artifact)
        return _make_ctx(state=state, session_worktree=self.tmpdir, phase_spec=spec)

    def test_missing_artifact_uses_assert_not_auto_approve(self):
        """When INTENT.md is expected but absent, action must be 'assert', not 'auto-approve'."""
        ctx = self._make_ctx_in_tmpdir()
        result_obj = _make_claude_result()

        result = self.runner._interpret_output(ctx, result_obj)

        # 'assert' routes to INTENT_ASSERT (the approval gate state)
        # 'auto-approve' would skip the gate and go straight to INTENT
        self.assertEqual(result.action, 'assert',
                         "Missing artifact must trigger 'assert', not 'auto-approve'")

    def test_missing_artifact_sets_artifact_missing_flag(self):
        """data['artifact_missing'] must be True when the artifact is absent."""
        ctx = self._make_ctx_in_tmpdir()
        result_obj = _make_claude_result()

        result = self.runner._interpret_output(ctx, result_obj)

        self.assertTrue(result.data.get('artifact_missing'),
                        "data['artifact_missing'] must be True")

    def test_missing_artifact_records_expected_filename(self):
        """data['artifact_expected'] must name the artifact that was not found."""
        ctx = self._make_ctx_in_tmpdir(artifact='PLAN.md')
        result_obj = _make_claude_result()

        result = self.runner._interpret_output(ctx, result_obj)

        self.assertEqual(result.data.get('artifact_expected'), 'PLAN.md')

    def test_missing_artifact_no_artifact_path_in_data(self):
        """artifact_path must not be set when the file does not exist."""
        ctx = self._make_ctx_in_tmpdir()
        result_obj = _make_claude_result()

        result = self.runner._interpret_output(ctx, result_obj)

        self.assertNotIn('artifact_path', result.data)

    def test_present_artifact_uses_assert_with_path(self):
        """When INTENT.md exists, action is 'assert' and artifact_path is set."""
        ctx = self._make_ctx_in_tmpdir()
        artifact_path = os.path.join(self.tmpdir, 'INTENT.md')
        Path(artifact_path).write_text('# Intent\nDo something')

        result = self.runner._interpret_output(ctx, _make_claude_result())

        self.assertEqual(result.action, 'assert')
        self.assertEqual(result.data.get('artifact_path'), artifact_path)
        self.assertNotIn('artifact_missing', result.data)

    def test_no_artifact_configured_uses_auto_approve(self):
        """When phase_spec.artifact is None, auto-approve is correct (no artifact gate)."""
        spec = _make_phase_spec(artifact=None)
        ctx = _make_ctx(session_worktree=self.tmpdir, phase_spec=spec)

        result = self.runner._interpret_output(ctx, _make_claude_result())

        self.assertEqual(result.action, 'auto-approve')
        self.assertNotIn('artifact_missing', result.data)

    def test_escalation_file_takes_priority_over_missing_artifact(self):
        """If escalation file exists, escalate action wins before artifact check."""
        spec = _make_phase_spec(artifact='INTENT.md', escalation_file='.intent-escalation.md')
        ctx = _make_ctx(session_worktree=self.tmpdir, phase_spec=spec)

        # Write escalation file but NOT artifact
        esc_path = os.path.join(self.tmpdir, '.intent-escalation.md')
        Path(esc_path).write_text('Agent needs clarification')

        result = self.runner._interpret_output(ctx, _make_claude_result())

        self.assertEqual(result.action, 'escalate')
        self.assertNotIn('artifact_missing', result.data)


class TestInterpretOutputMissingArtifactPlanAssert(unittest.TestCase):
    """Verify the bug is fixed for PLAN_ASSERT state (planning phase)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.runner = AgentRunner()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_plan_assert_missing_artifact_does_not_auto_approve(self):
        """In DRAFT state with missing PLAN.md, must not auto-approve."""
        spec = PhaseSpec(
            name='planning',
            agent_file='agents/uber-team.json',
            lead='project-lead',
            permission_mode='plan',
            stream_file='.plan-stream.jsonl',
            artifact='PLAN.md',
            approval_state='PLAN_ASSERT',
            escalation_state='PLANNING_ESCALATE',
            escalation_file='.plan-escalation.md',
            settings_overlay={},
        )
        ctx = _make_ctx(state='DRAFT', session_worktree=self.tmpdir, phase_spec=spec)

        result = self.runner._interpret_output(ctx, _make_claude_result())

        self.assertNotEqual(result.action, 'auto-approve',
                            "Missing PLAN.md must not auto-approve from DRAFT")
        self.assertTrue(result.data.get('artifact_missing'))


# ── ApprovalGate — missing artifact always escalates ─────────────────────────

class TestApprovalGateMissingArtifact(unittest.TestCase):
    """ApprovalGate must always escalate to the human when artifact_missing=True."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._input_calls: list[Any] = []

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_gate(self, human_response: str = 'correct') -> ApprovalGate:
        async def _input_provider(req):
            self._input_calls.append(req)
            return human_response

        return ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=_input_provider,
            poc_root=self.tmpdir,
        )

    def _make_approval_ctx(self, state: str = 'INTENT_ASSERT') -> ActorContext:
        ctx = _make_ctx(state=state, session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        ctx.data = {
            'artifact_missing': True,
            'artifact_expected': 'INTENT.md',
        }
        return ctx

    def test_missing_artifact_always_escalates_to_human(self):
        """Proxy is never consulted when artifact_missing=True — human always asked."""
        gate = self._make_gate(human_response='correct')
        ctx = self._make_approval_ctx('INTENT_ASSERT')

        with patch.object(gate, '_proxy_decide') as mock_proxy, \
             patch.object(gate, '_classify_review', return_value=('correct', 'Please produce INTENT.md')):
            mock_proxy.return_value = 'auto-approve'  # proxy would say auto-approve...
            _run(gate.run(ctx))

        # Proxy should not have been consulted at all
        mock_proxy.assert_not_called()
        # Human input was requested
        self.assertEqual(len(self._input_calls), 1)

    def test_missing_artifact_bridge_text_explains_problem(self):
        """Bridge text presented to human must mention the missing artifact."""
        gate = self._make_gate(human_response='correct')
        ctx = self._make_approval_ctx('INTENT_ASSERT')

        captured_requests: list[Any] = []

        async def capturing_input(req):
            captured_requests.append(req)
            return 'correct'

        gate.input_provider = capturing_input

        with patch.object(gate, '_classify_review', return_value=('correct', '')):
            _run(gate.run(ctx))

        self.assertEqual(len(captured_requests), 1)
        bridge = captured_requests[0].bridge_text
        # Must not just say "Ready for review" — it must explain the artifact is missing
        self.assertNotEqual(bridge, 'Ready for review at INTENT_ASSERT.')
        self.assertIn('artifact', bridge.lower(),
                      f"Bridge text should mention artifact, got: {bridge!r}")

    def test_missing_artifact_gate_returns_correct_action(self):
        """When human says 'correct', gate returns correct action."""
        gate = self._make_gate(human_response='correct')
        ctx = self._make_approval_ctx('INTENT_ASSERT')

        with patch.object(gate, '_classify_review', return_value=('correct', 'Produce INTENT.md')):
            result = _run(gate.run(ctx))

        self.assertEqual(result.action, 'correct')

    def test_missing_artifact_gate_returns_withdraw(self):
        """When human says 'withdraw', gate returns withdraw action."""
        gate = self._make_gate(human_response='withdraw')
        ctx = self._make_approval_ctx('INTENT_ASSERT')

        with patch.object(gate, '_classify_review', return_value=('withdraw', '')):
            result = _run(gate.run(ctx))

        self.assertEqual(result.action, 'withdraw')

    def test_present_artifact_still_consults_proxy(self):
        """Normal flow (artifact present) still consults proxy model."""
        gate = self._make_gate(human_response='approve')
        ctx = _make_ctx(state='INTENT_ASSERT', session_worktree=self.tmpdir, infra_dir=self.tmpdir)

        # Write the artifact
        artifact_path = os.path.join(self.tmpdir, 'INTENT.md')
        Path(artifact_path).write_text('# Intent\nBuild something')
        ctx.data = {'artifact_path': artifact_path}

        with patch.object(gate, '_proxy_decide', return_value='auto-approve') as mock_proxy, \
             patch.object(gate, '_proxy_record'):
            result = _run(gate.run(ctx))

        mock_proxy.assert_called_once()
        self.assertEqual(result.action, 'approve')


# ── ApprovalGate._generate_bridge — missing artifact message ─────────────────

class TestGenerateBridgeMissingArtifact(unittest.TestCase):
    """_generate_bridge must return a useful message when artifact_missing=True."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_gate(self) -> ApprovalGate:
        return ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=AsyncMock(),
            poc_root=self.tmpdir,
        )

    def test_missing_artifact_returns_descriptive_message(self):
        gate = self._make_gate()
        text = gate._generate_bridge('', 'INTENT_ASSERT', 'some task', artifact_missing=True)
        self.assertIn('artifact', text.lower())
        # Must not be the generic fallback
        self.assertNotEqual(text, 'Ready for review at INTENT_ASSERT.')

    def test_present_artifact_path_returns_normal_flow(self):
        """_generate_bridge with artifact_missing=False calls through normally."""
        gate = self._make_gate()
        artifact_path = os.path.join(self.tmpdir, 'INTENT.md')
        Path(artifact_path).write_text('# Intent')

        with patch('projects.POC.scripts.generate_review_bridge.generate', return_value='Bridge summary') as mock_gen:
            text = gate._generate_bridge(artifact_path, 'INTENT_ASSERT', 'task')

        mock_gen.assert_called_once()
        self.assertEqual(text, 'Bridge summary')

    def test_no_artifact_path_returns_generic_fallback(self):
        """When artifact_missing is not set and no path given, generic message returned."""
        gate = self._make_gate()
        text = gate._generate_bridge('', 'INTENT_ASSERT', 'task')
        self.assertEqual(text, 'Ready for review at INTENT_ASSERT.')


if __name__ == '__main__':
    unittest.main()
