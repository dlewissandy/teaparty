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


# ── Phase config artifact values ──────────────────────────────────────────────

class TestPhaseConfigArtifacts(unittest.TestCase):
    """Verify phase-config.json artifact fields are correctly set for approval gates."""

    def _load_config(self) -> dict:
        config_path = Path(__file__).parent.parent / 'phase-config.json'
        with open(config_path) as f:
            import json
            return json.load(f)

    def test_planning_phase_has_plan_md_artifact(self):
        """Planning phase must have artifact=PLAN.md so PLAN_ASSERT is not bypassed."""
        config = self._load_config()
        artifact = config['phases']['planning']['artifact']
        self.assertEqual(
            artifact, 'PLAN.md',
            f"planning artifact must be 'PLAN.md', got {artifact!r} — "
            "null here causes _interpret_output to auto-approve and bypass PLAN_ASSERT",
        )

    def test_intent_phase_has_intent_md_artifact(self):
        """Intent phase artifact must remain INTENT.md (regression guard)."""
        config = self._load_config()
        artifact = config['phases']['intent']['artifact']
        self.assertEqual(artifact, 'INTENT.md')

    def test_planning_phase_artifact_is_not_null(self):
        """Explicit null check — the root cause of the bypass bug."""
        config = self._load_config()
        self.assertIsNotNone(
            config['phases']['planning']['artifact'],
            "planning artifact must not be null",
        )


class TestInterpretOutputPlanningPhaseRouting(unittest.TestCase):
    """Verify _interpret_output routes planning output through PLAN_ASSERT, not auto-approve."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.runner = AgentRunner()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_planning_spec(self) -> PhaseSpec:
        return PhaseSpec(
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

    def test_planning_present_artifact_goes_to_assert(self):
        """When PLAN.md exists, action is 'assert' (routes to PLAN_ASSERT)."""
        spec = self._make_planning_spec()
        ctx = _make_ctx(state='DRAFT', session_worktree=self.tmpdir, phase_spec=spec)
        Path(os.path.join(self.tmpdir, 'PLAN.md')).write_text('# Plan\nStep 1\nStep 2')

        result = self.runner._interpret_output(ctx, _make_claude_result())

        self.assertEqual(result.action, 'assert')
        self.assertIn('artifact_path', result.data)
        self.assertNotIn('artifact_missing', result.data)

    def test_planning_missing_artifact_goes_to_assert_not_auto_approve(self):
        """When PLAN.md is absent, must assert (not auto-approve), so human can review."""
        spec = self._make_planning_spec()
        ctx = _make_ctx(state='DRAFT', session_worktree=self.tmpdir, phase_spec=spec)
        # PLAN.md deliberately not written

        result = self.runner._interpret_output(ctx, _make_claude_result())

        self.assertNotEqual(result.action, 'auto-approve',
                            "Missing PLAN.md must never auto-approve — that bypasses PLAN_ASSERT")
        self.assertEqual(result.action, 'assert')
        self.assertTrue(result.data.get('artifact_missing'))
        self.assertEqual(result.data.get('artifact_expected'), 'PLAN.md')

    def test_intent_phase_present_artifact_still_goes_to_assert(self):
        """Intent phase is unaffected — present INTENT.md still routes to assert."""
        spec = _make_phase_spec(artifact='INTENT.md')
        ctx = _make_ctx(state='PROPOSAL', session_worktree=self.tmpdir, phase_spec=spec)
        Path(os.path.join(self.tmpdir, 'INTENT.md')).write_text('# Intent')

        result = self.runner._interpret_output(ctx, _make_claude_result())

        self.assertEqual(result.action, 'assert')
        self.assertIn('artifact_path', result.data)


# ── Artifact path resolution: session_worktree for both phases ────────────────

class TestArtifactPathResolution(unittest.TestCase):
    """Both intent and planning phases must look for artifacts in session_worktree.

    This guards against CWD confusion: the agent's cwd IS session_worktree, so
    writing PLAN.md / INTENT.md in cwd is the same as session_worktree/PLAN.md.
    _interpret_output must resolve the same way.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.runner = AgentRunner()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_intent_spec(self) -> PhaseSpec:
        return _make_phase_spec(artifact='INTENT.md')

    def _make_planning_spec(self) -> PhaseSpec:
        return PhaseSpec(
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

    def test_intent_artifact_resolved_from_session_worktree(self):
        """INTENT.md written to session_worktree is found by _interpret_output."""
        spec = self._make_intent_spec()
        ctx = _make_ctx(state='PROPOSAL', session_worktree=self.tmpdir, phase_spec=spec)
        artifact_path = os.path.join(self.tmpdir, 'INTENT.md')
        Path(artifact_path).write_text('# Intent\nObjective: test')

        result = self.runner._interpret_output(ctx, _make_claude_result())

        self.assertEqual(result.action, 'assert')
        self.assertEqual(result.data['artifact_path'], artifact_path)

    def test_plan_artifact_resolved_from_session_worktree(self):
        """PLAN.md written to session_worktree is found by _interpret_output."""
        spec = self._make_planning_spec()
        ctx = _make_ctx(state='DRAFT', session_worktree=self.tmpdir, phase_spec=spec)
        artifact_path = os.path.join(self.tmpdir, 'PLAN.md')
        Path(artifact_path).write_text('# Plan\n1. Research\n2. Write')

        result = self.runner._interpret_output(ctx, _make_claude_result())

        self.assertEqual(result.action, 'assert')
        self.assertEqual(result.data['artifact_path'], artifact_path)

    def test_plan_and_intent_resolve_to_same_directory(self):
        """Intent and planning phases use the same session_worktree as artifact root."""
        intent_spec = self._make_intent_spec()
        plan_spec = self._make_planning_spec()

        intent_ctx = _make_ctx(state='PROPOSAL', session_worktree=self.tmpdir, phase_spec=intent_spec)
        plan_ctx = _make_ctx(state='DRAFT', session_worktree=self.tmpdir, phase_spec=plan_spec)

        # Write both artifacts
        Path(os.path.join(self.tmpdir, 'INTENT.md')).write_text('# Intent')
        Path(os.path.join(self.tmpdir, 'PLAN.md')).write_text('# Plan')

        intent_result = self.runner._interpret_output(intent_ctx, _make_claude_result())
        plan_result = self.runner._interpret_output(plan_ctx, _make_claude_result())

        # Both must resolve to files within the same session_worktree
        intent_dir = os.path.dirname(intent_result.data['artifact_path'])
        plan_dir = os.path.dirname(plan_result.data['artifact_path'])
        self.assertEqual(intent_dir, plan_dir,
                         "INTENT.md and PLAN.md must resolve to the same directory")
        self.assertEqual(intent_dir, self.tmpdir)

    def test_plan_in_wrong_directory_is_not_found(self):
        """PLAN.md in a different directory (not session_worktree) is not found."""
        spec = self._make_planning_spec()
        ctx = _make_ctx(state='DRAFT', session_worktree=self.tmpdir, phase_spec=spec)

        # Write PLAN.md in a sibling directory (simulates wrong CWD)
        other_dir = tempfile.mkdtemp()
        try:
            Path(os.path.join(other_dir, 'PLAN.md')).write_text('# Plan in wrong dir')
            # session_worktree does NOT have PLAN.md

            result = self.runner._interpret_output(ctx, _make_claude_result())

            # Should be missing, not found
            self.assertTrue(result.data.get('artifact_missing'),
                            "PLAN.md in wrong directory must not be detected")
        finally:
            import shutil
            shutil.rmtree(other_dir, ignore_errors=True)


# ── Import source: approval_gate.py, not human_proxy.py ──────────────────────

class TestApprovalGateImports(unittest.TestCase):
    """actors.py must import from approval_gate.py, not human_proxy.py."""

    def test_generate_response_importable(self):
        from projects.POC.scripts.approval_gate import generate_response
        self.assertTrue(callable(generate_response))

    def test_resolve_team_model_path_importable(self):
        from projects.POC.scripts.approval_gate import resolve_team_model_path
        self.assertTrue(callable(resolve_team_model_path))

    def test_extract_question_patterns_importable(self):
        from projects.POC.scripts.approval_gate import _extract_question_patterns
        self.assertTrue(callable(_extract_question_patterns))

    def test_generative_response_importable(self):
        from projects.POC.scripts.approval_gate import GenerativeResponse
        self.assertTrue(GenerativeResponse is not None)


# ── Team-scoped proxy model paths ────────────────────────────────────────────

class TestTeamScopedProxyModel(unittest.TestCase):
    """_proxy_decide and _proxy_record must use resolve_team_model_path."""

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

    @patch('projects.POC.orchestrator.actors.load_model')
    @patch('projects.POC.orchestrator.actors.should_escalate')
    @patch('projects.POC.orchestrator.actors.resolve_team_model_path')
    def test_proxy_decide_resolves_team_path(self, mock_resolve, mock_escalate, mock_load):
        gate = self._make_gate()
        mock_resolve.return_value = '/tmp/scoped.json'
        mock_escalate.return_value = MagicMock(action='escalate')

        gate._proxy_decide('INTENT_ASSERT', 'default', '', team='coding')

        mock_resolve.assert_called_once_with(gate.proxy_model_path, 'coding')
        mock_load.assert_called_once_with('/tmp/scoped.json')

    @patch('projects.POC.orchestrator.actors.save_model')
    @patch('projects.POC.orchestrator.actors.record_outcome')
    @patch('projects.POC.orchestrator.actors.load_model')
    @patch('projects.POC.orchestrator.actors.resolve_team_model_path')
    def test_proxy_record_resolves_team_path(self, mock_resolve, mock_load, mock_record, mock_save):
        gate = self._make_gate()
        mock_resolve.return_value = '/tmp/scoped.json'
        mock_record.return_value = MagicMock()

        gate._proxy_record('INTENT_ASSERT', 'default', 'approve', team='coding')

        mock_resolve.assert_called_once_with(gate.proxy_model_path, 'coding')
        mock_save.assert_called_once()
        # save_model should use the resolved path, not the base path
        self.assertEqual(mock_save.call_args[0][1], '/tmp/scoped.json')


# ── Question patterns instead of conversation_text ───────────────────────────

class TestQuestionPatternExtraction(unittest.TestCase):
    """_proxy_record must pass question_patterns, not conversation_text."""

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

    @patch('projects.POC.orchestrator.actors.save_model')
    @patch('projects.POC.orchestrator.actors.record_outcome')
    @patch('projects.POC.orchestrator.actors.load_model')
    @patch('projects.POC.orchestrator.actors.resolve_team_model_path', side_effect=lambda b, t: b)
    @patch('projects.POC.orchestrator.actors._extract_question_patterns')
    def test_record_passes_question_patterns(self, mock_extract, mock_resolve, mock_load, mock_record, mock_save):
        gate = self._make_gate()
        mock_extract.return_value = [{'question': 'Why?', 'concern': 'scope'}]
        mock_record.return_value = MagicMock()

        gate._proxy_record('INTENT_ASSERT', 'default', 'correct',
                           conversation='Why did you do it that way?')

        mock_extract.assert_called_once_with('Why did you do it that way?', 'correct')
        # record_outcome should receive question_patterns, NOT conversation_text
        call_kwargs = mock_record.call_args
        self.assertIn('question_patterns', call_kwargs.kwargs or dict(zip(
            ['model', 'state', 'task_type', 'outcome'], call_kwargs.args)))


# ── Generative response for escalation states ────────────────────────────────

class TestEscalationGenerativeResponse(unittest.TestCase):
    """Escalation states try generate_response() before falling through to human."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._input_calls = []

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_gate(self, human_response: str = 'clarify') -> ApprovalGate:
        async def _input_provider(req):
            self._input_calls.append(req)
            return human_response

        return ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=_input_provider,
            poc_root=self.tmpdir,
        )

    def _make_escalation_ctx(self, state: str = 'INTENT_ESCALATE') -> ActorContext:
        ctx = _make_ctx(state=state, session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        esc_path = os.path.join(self.tmpdir, '.intent-escalation.md')
        Path(esc_path).write_text('What database should I use?')
        ctx.data = {'escalation_file': esc_path}
        ctx.env_vars = {'POC_PROJECT': 'default', 'POC_TEAM': 'coding'}
        return ctx

    @patch('projects.POC.orchestrator.actors.generate_response')
    @patch('projects.POC.orchestrator.actors.load_model')
    @patch('projects.POC.orchestrator.actors.resolve_team_model_path', side_effect=lambda b, t: b)
    def test_confident_proxy_returns_generative_response(self, mock_resolve, mock_load, mock_gen):
        from projects.POC.scripts.approval_gate import GenerativeResponse
        gate = self._make_gate()
        ctx = self._make_escalation_ctx()
        mock_gen.return_value = GenerativeResponse(action='clarify', text='Use PostgreSQL', confidence=0.92)

        result = _run(gate.run(ctx))

        self.assertEqual(result.action, 'clarify')
        self.assertEqual(result.feedback, 'Use PostgreSQL')
        self.assertTrue(result.data.get('generative'))
        # Human should NOT have been prompted
        self.assertEqual(len(self._input_calls), 0)

    @patch('projects.POC.orchestrator.actors.generate_response')
    @patch('projects.POC.orchestrator.actors.load_model')
    @patch('projects.POC.orchestrator.actors.resolve_team_model_path', side_effect=lambda b, t: b)
    def test_low_confidence_falls_through_to_human(self, mock_resolve, mock_load, mock_gen):
        gate = self._make_gate(human_response='Use MySQL')
        ctx = self._make_escalation_ctx()
        mock_gen.return_value = None  # Not confident enough

        with patch.object(gate, '_classify_review', return_value=('clarify', 'Use MySQL')):
            result = _run(gate.run(ctx))

        self.assertEqual(result.action, 'clarify')
        # Human WAS prompted
        self.assertEqual(len(self._input_calls), 1)

    @patch('projects.POC.orchestrator.actors.generate_response')
    @patch('projects.POC.orchestrator.actors.load_model')
    @patch('projects.POC.orchestrator.actors.resolve_team_model_path', side_effect=lambda b, t: b)
    def test_generate_exception_falls_through_to_human(self, mock_resolve, mock_load, mock_gen):
        gate = self._make_gate(human_response='Use SQLite')
        ctx = self._make_escalation_ctx()
        mock_gen.side_effect = RuntimeError('model corrupt')

        with patch.object(gate, '_classify_review', return_value=('clarify', 'Use SQLite')):
            result = _run(gate.run(ctx))

        self.assertEqual(result.action, 'clarify')
        self.assertEqual(len(self._input_calls), 1)

    def test_non_escalation_state_does_not_try_generative(self):
        """INTENT_ASSERT (not an escalation state) must never call generate_response."""
        gate = self._make_gate(human_response='approve')
        ctx = _make_ctx(state='INTENT_ASSERT', session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        artifact_path = os.path.join(self.tmpdir, 'INTENT.md')
        Path(artifact_path).write_text('# Intent')
        ctx.data = {'artifact_path': artifact_path}

        with patch.object(gate, '_proxy_decide', return_value='auto-approve'), \
             patch.object(gate, '_proxy_record'), \
             patch('projects.POC.orchestrator.actors.generate_response') as mock_gen:
            _run(gate.run(ctx))

        mock_gen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
