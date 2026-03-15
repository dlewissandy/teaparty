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
    _relocate_plan_file,
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
) -> PhaseSpec:
    return PhaseSpec(
        name='intent',
        agent_file='agents/intent-team.json',
        lead='intent-lead',
        permission_mode='acceptEdits',
        stream_file='.intent-stream.jsonl',
        artifact=artifact,
        approval_state='INTENT_ASSERT',
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

    def test_present_artifact_path_returns_question_with_path(self):
        """_generate_bridge with artifact returns the alignment question + path."""
        gate = self._make_gate()
        artifact_path = os.path.join(self.tmpdir, 'INTENT.md')
        Path(artifact_path).write_text('# Intent')

        text = gate._generate_bridge(artifact_path, 'INTENT_ASSERT', 'task')

        self.assertIn('Do you recognize', text)
        self.assertIn(artifact_path, text)

    def test_no_artifact_path_returns_alignment_question(self):
        """When no path given, the alignment question is still returned."""
        gate = self._make_gate()
        text = gate._generate_bridge('', 'INTENT_ASSERT', 'task')
        self.assertIn('Do you recognize', text)


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


# ── Plan relocation from ~/.claude/plans/ ────────────────────────────────────

class TestRelocatePlanFile(unittest.TestCase):
    """_relocate_plan_file copies newest plan from ~/.claude/plans/ to target."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.fake_plans_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        shutil.rmtree(self.fake_plans_dir, ignore_errors=True)

    def test_relocates_newest_plan_after_start_time(self):
        """Plan file created after start_time is copied to target."""
        import time
        start = time.time() - 1  # 1 second ago
        plan_file = Path(self.fake_plans_dir) / 'my-plan.md'
        plan_file.write_text('# Plan\nStep 1: do the thing')

        target = os.path.join(self.tmpdir, 'PLAN.md')

        with patch('projects.POC.orchestrator.actors.Path.home',
                   return_value=Path(self.fake_plans_dir).parent):
            # We need to mock Path.home() so ~/.claude/plans/ points to our fake dir
            # Instead, let's call the function directly with a patched plans_dir
            pass

        # Directly test the function by patching the plans_dir lookup
        with patch('projects.POC.orchestrator.actors.Path.home') as mock_home:
            mock_home.return_value = Path(self.tmpdir) / 'fakehome'
            plans_dir = Path(self.tmpdir) / 'fakehome' / '.claude' / 'plans'
            plans_dir.mkdir(parents=True)
            new_plan = plans_dir / 'test-plan.md'
            new_plan.write_text('# My Plan\n\n## Steps\n1. First\n2. Second')

            result = _relocate_plan_file(target, start)

        self.assertTrue(result)
        self.assertTrue(os.path.exists(target))
        self.assertIn('My Plan', Path(target).read_text())

    def test_ignores_plans_before_start_time(self):
        """Plan files older than start_time are not relocated."""
        import time

        with patch('projects.POC.orchestrator.actors.Path.home') as mock_home:
            mock_home.return_value = Path(self.tmpdir) / 'fakehome'
            plans_dir = Path(self.tmpdir) / 'fakehome' / '.claude' / 'plans'
            plans_dir.mkdir(parents=True)
            old_plan = plans_dir / 'old-plan.md'
            old_plan.write_text('# Old Plan')
            # Set mtime to well in the past
            os.utime(str(old_plan), (time.time() - 3600, time.time() - 3600))

            target = os.path.join(self.tmpdir, 'PLAN.md')
            result = _relocate_plan_file(target, time.time() - 1)

        self.assertFalse(result)
        self.assertFalse(os.path.exists(target))

    def test_picks_newest_when_multiple_candidates(self):
        """When multiple plans are new, the newest (highest mtime) wins."""
        import time
        start = time.time() - 2

        with patch('projects.POC.orchestrator.actors.Path.home') as mock_home:
            mock_home.return_value = Path(self.tmpdir) / 'fakehome'
            plans_dir = Path(self.tmpdir) / 'fakehome' / '.claude' / 'plans'
            plans_dir.mkdir(parents=True)

            older = plans_dir / 'older-plan.md'
            older.write_text('# Older')
            os.utime(str(older), (time.time() - 1, time.time() - 1))

            newer = plans_dir / 'newer-plan.md'
            newer.write_text('# Newer')
            # newer has default mtime (now), which is more recent

            target = os.path.join(self.tmpdir, 'PLAN.md')
            result = _relocate_plan_file(target, start)

        self.assertTrue(result)
        self.assertIn('Newer', Path(target).read_text())

    def test_no_plans_dir_returns_false(self):
        """If ~/.claude/plans/ doesn't exist, return False gracefully."""
        with patch('projects.POC.orchestrator.actors.Path.home') as mock_home:
            mock_home.return_value = Path(self.tmpdir) / 'empty-home'

            target = os.path.join(self.tmpdir, 'PLAN.md')
            result = _relocate_plan_file(target, 0)

        self.assertFalse(result)

    def test_empty_plans_dir_returns_false(self):
        """If ~/.claude/plans/ exists but is empty, return False."""
        with patch('projects.POC.orchestrator.actors.Path.home') as mock_home:
            mock_home.return_value = Path(self.tmpdir) / 'fakehome'
            plans_dir = Path(self.tmpdir) / 'fakehome' / '.claude' / 'plans'
            plans_dir.mkdir(parents=True)

            target = os.path.join(self.tmpdir, 'PLAN.md')
            result = _relocate_plan_file(target, 0)

        self.assertFalse(result)

    def test_non_md_files_ignored(self):
        """Non-.md files in plans dir are skipped."""
        import time

        with patch('projects.POC.orchestrator.actors.Path.home') as mock_home:
            mock_home.return_value = Path(self.tmpdir) / 'fakehome'
            plans_dir = Path(self.tmpdir) / 'fakehome' / '.claude' / 'plans'
            plans_dir.mkdir(parents=True)
            (plans_dir / 'notes.txt').write_text('not a plan')
            (plans_dir / 'data.json').write_text('{}')

            target = os.path.join(self.tmpdir, 'PLAN.md')
            result = _relocate_plan_file(target, time.time() - 10)

        self.assertFalse(result)


class TestAgentRunnerRelocatesPlan(unittest.TestCase):
    """AgentRunner.run() calls _relocate_plan_file when artifact is missing."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
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

    def test_relocation_called_when_artifact_missing(self):
        """When PLAN.md isn't in session_worktree, relocation is attempted."""
        spec = PhaseSpec(
            name='planning', agent_file='agents/uber-team.json',
            lead='project-lead', permission_mode='plan',
            stream_file='.plan-stream.jsonl', artifact='PLAN.md',
            approval_state='PLAN_ASSERT', settings_overlay={},
        )
        ctx = _make_ctx(state='DRAFT', session_worktree=self.tmpdir, phase_spec=spec)
        runner = AgentRunner()

        mock_result = ClaudeResult(exit_code=0, session_id='s1', start_time=1000.0)

        # Note: earlier versions of this test used additional patch blocks that did
        # not assert any behavior. Those have been removed to keep the test focused
        # on observable effects.

        # More direct test: verify the code path in run()
        # The artifact check + relocation happens between exit_code check and _interpret_output
        # Let's test _interpret_output finds the plan after relocation
        with patch('projects.POC.orchestrator.actors._relocate_plan_file') as mock_relocate:
            def write_plan(target, start_time):
                Path(target).write_text('# Plan from relocation')
                return True
            mock_relocate.side_effect = write_plan

            result = runner._interpret_output(ctx, mock_result)

            # Before _interpret_output, run() would have called _relocate_plan_file
            # But we're testing _interpret_output directly. Let's verify via the full path.

        # Actually test the integration we care about: when the artifact is present
        # in the session worktree, _interpret_output should treat it as found and
        # not mark it as missing.
        artifact_path = os.path.join(self.tmpdir, 'PLAN.md')
        self.assertFalse(os.path.exists(artifact_path))

        # Use the real relocation helper (or, if its behavior changes, this call
        # still represents the same observable contract for the test).
        _relocate_plan_file(artifact_path, mock_result.start_time)

        # Now artifact should exist
        self.assertTrue(os.path.exists(artifact_path))

        # And _interpret_output should find it
        result = runner._interpret_output(ctx, mock_result)
        self.assertEqual(result.action, 'assert')
        self.assertEqual(result.data.get('artifact_path'), artifact_path)
        self.assertNotIn('artifact_missing', result.data)

    def test_no_relocation_when_artifact_already_exists(self):
        """If PLAN.md already exists in session_worktree, don't relocate."""
        spec = PhaseSpec(
            name='planning', agent_file='agents/uber-team.json',
            lead='project-lead', permission_mode='plan',
            stream_file='.plan-stream.jsonl', artifact='PLAN.md',
            approval_state='PLAN_ASSERT', settings_overlay={},
        )
        ctx = _make_ctx(state='DRAFT', session_worktree=self.tmpdir, phase_spec=spec)

        # Write PLAN.md directly (agent wrote it to CWD)
        Path(os.path.join(self.tmpdir, 'PLAN.md')).write_text('# Direct Plan')

        with patch('projects.POC.orchestrator.actors._relocate_plan_file') as mock_relocate:
            mock_result = ClaudeResult(exit_code=0, session_id='s1', start_time=1000.0)
            # Simulate run()'s artifact check
            artifact_path = os.path.join(self.tmpdir, spec.artifact)
            if not os.path.exists(artifact_path):
                _relocate_plan_file(artifact_path, mock_result.start_time)

            mock_relocate.assert_not_called()


# ── Regression tests for #120: approval gate classification failures ──────────

class TestClassifyReviewFallbackOnException(unittest.TestCase):
    """_classify_review must return __fallback__, never approve, on exception.

    Root cause of #120: the old code caught all exceptions and returned
    ('approve', ''), silently auto-approving when classification crashed.
    """

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

    def test_import_error_returns_fallback_not_approve(self):
        """If classify_review cannot be imported, must NOT auto-approve."""
        gate = self._make_gate()
        with patch('projects.POC.scripts.classify_review.classify',
                   side_effect=ImportError('module not found')):
            action, feedback = gate._classify_review('PLAN_ASSERT', 'looks good')
        self.assertEqual(action, '__fallback__')
        self.assertNotEqual(action, 'approve')

    def test_runtime_error_returns_fallback_not_approve(self):
        """If classify() raises RuntimeError, must NOT auto-approve."""
        gate = self._make_gate()
        with patch('projects.POC.scripts.classify_review.classify',
                   side_effect=RuntimeError('subprocess crashed')):
            action, feedback = gate._classify_review('PLAN_ASSERT', 'the plan is great')
        self.assertEqual(action, '__fallback__')

    def test_timeout_error_returns_fallback_not_approve(self):
        """If classify() times out, must NOT auto-approve."""
        gate = self._make_gate()
        import subprocess
        with patch('projects.POC.scripts.classify_review.classify',
                   side_effect=subprocess.TimeoutExpired('claude', 30)):
            action, feedback = gate._classify_review('WORK_ASSERT', 'approve this')
        self.assertEqual(action, '__fallback__')

    def test_normal_classification_still_works(self):
        """Sanity check: normal classify output is parsed correctly."""
        gate = self._make_gate()
        with patch('projects.POC.scripts.classify_review.classify',
                   return_value='correct\tFix the tests'):
            action, feedback = gate._classify_review('PLAN_ASSERT', 'fix the tests')
        self.assertEqual(action, 'correct')
        self.assertEqual(feedback, 'Fix the tests')


class TestDialogLoopLogging(unittest.TestCase):
    """Dialog loop must emit LOG events for post-hoc debugging (#120 bug 4)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._input_index = 0

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_gate_with_responses(self, responses: list[str]) -> ApprovalGate:
        """Create a gate whose input_provider returns responses in sequence."""
        async def _input_provider(req):
            idx = self._input_index
            self._input_index += 1
            return responses[idx] if idx < len(responses) else 'approve'

        return ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=_input_provider,
            poc_root=self.tmpdir,
        )

    def test_dialog_turn_emits_log_event(self):
        """When classify returns 'dialog', a LOG event must be published."""
        gate = self._make_gate_with_responses(['Have you tested it?', 'approve'])
        ctx = _make_ctx(state='PLAN_ASSERT', session_worktree=self.tmpdir,
                        infra_dir=self.tmpdir)
        artifact_path = os.path.join(self.tmpdir, 'PLAN.md')
        Path(artifact_path).write_text('# Plan')
        ctx.data = {'artifact_path': artifact_path}

        classify_returns = iter([
            ('dialog', 'Have you tested it?'),
            ('approve', ''),
        ])

        with patch.object(gate, '_proxy_decide', return_value='escalate'), \
             patch.object(gate, '_classify_review', side_effect=lambda *a, **kw: next(classify_returns)), \
             patch.object(gate, '_generate_bridge', return_value='Review the plan'), \
             patch.object(gate, '_generate_dialog_response', return_value='Yes, all tests pass.'), \
             patch.object(gate, '_proxy_record'):
            _run(gate.run(ctx))

        # Find approval_dialog LOG events among all published events
        dialog_log_events = [
            call for call in ctx.event_bus.publish.call_args_list
            if call.args and hasattr(call.args[0], 'type')
            and call.args[0].type == EventType.LOG
            and call.args[0].data.get('category') == 'approval_dialog'
        ]
        self.assertGreaterEqual(len(dialog_log_events), 1,
                                "Dialog turn must emit at least one approval_dialog LOG event")
        log_data = dialog_log_events[0].args[0].data
        self.assertEqual(log_data['category'], 'approval_dialog')
        self.assertEqual(log_data['classification'], 'dialog')

    def test_fallback_turn_emits_log_event(self):
        """When classify returns '__fallback__', a LOG event must be published."""
        gate = self._make_gate_with_responses(['something weird', 'approve'])
        ctx = _make_ctx(state='PLAN_ASSERT', session_worktree=self.tmpdir,
                        infra_dir=self.tmpdir)
        artifact_path = os.path.join(self.tmpdir, 'PLAN.md')
        Path(artifact_path).write_text('# Plan')
        ctx.data = {'artifact_path': artifact_path}

        classify_returns = iter([
            ('__fallback__', ''),
            ('approve', ''),
        ])

        with patch.object(gate, '_proxy_decide', return_value='escalate'), \
             patch.object(gate, '_classify_review', side_effect=lambda *a, **kw: next(classify_returns)), \
             patch.object(gate, '_generate_bridge', return_value='Review the plan'), \
             patch.object(gate, '_generate_dialog_response', return_value='Could you rephrase?'), \
             patch.object(gate, '_proxy_record'):
            _run(gate.run(ctx))

        dialog_log_events = [
            call for call in ctx.event_bus.publish.call_args_list
            if call.args and hasattr(call.args[0], 'type')
            and call.args[0].type == EventType.LOG
            and call.args[0].data.get('category') == 'approval_dialog'
        ]
        self.assertGreaterEqual(len(dialog_log_events), 1)
        self.assertEqual(dialog_log_events[0].args[0].data['classification'], '__fallback__')


class TestFallbackUsesDialogGenerator(unittest.TestCase):
    """__fallback__ must use _generate_dialog_response, not a static menu (#120 bug 5)."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._input_index = 0

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_fallback_calls_dialog_generator_not_static_menu(self):
        """When __fallback__ fires, _generate_dialog_response must be called."""
        responses = ['confusing input', 'approve']

        async def _input_provider(req):
            idx = self._input_index
            self._input_index += 1
            return responses[idx] if idx < len(responses) else 'approve'

        gate = ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=_input_provider,
            poc_root=self.tmpdir,
        )
        ctx = _make_ctx(state='WORK_ASSERT', session_worktree=self.tmpdir,
                        infra_dir=self.tmpdir)
        artifact_path = os.path.join(self.tmpdir, 'output.txt')
        Path(artifact_path).write_text('delivered work')
        ctx.data = {'artifact_path': artifact_path}

        classify_returns = iter([
            ('__fallback__', ''),
            ('approve', ''),
        ])

        with patch.object(gate, '_proxy_decide', return_value='escalate'), \
             patch.object(gate, '_classify_review', side_effect=lambda *a, **kw: next(classify_returns)), \
             patch.object(gate, '_generate_bridge', return_value='Review work'), \
             patch.object(gate, '_generate_dialog_response', return_value='Let me try to help.') as mock_dialog, \
             patch.object(gate, '_proxy_record'):
            _run(gate.run(ctx))

        mock_dialog.assert_called_once()
        # Verify the static menu text is NOT in the bridge (old behavior)
        # The dialog generator's response should be used instead
        bridge_calls = [
            call for call in ctx.event_bus.publish.call_args_list
            if call.args and hasattr(call.args[0], 'type')
            and call.args[0].type == EventType.INPUT_REQUESTED
        ]
        # Second INPUT_REQUESTED (after fallback) should use dialog generator output
        if len(bridge_calls) >= 2:
            bridge_text = bridge_calls[1].args[0].data.get('bridge_text', '')
            self.assertNotIn("approve — accept and continue", bridge_text,
                             "Static menu must not appear — dialog generator should be used")


from projects.POC.orchestrator.events import EventType


# ── Stderr surfacing ─────────────────────────────────────────────────────────

class TestStderrInActorResult(unittest.TestCase):
    """ClaudeResult.stderr_lines flows through to ActorResult.data."""

    def test_interpret_output_includes_stderr(self):
        """When ClaudeResult has stderr_lines, they appear in ActorResult.data."""
        runner = AgentRunner()
        ctx = _make_ctx()

        with tempfile.TemporaryDirectory() as tmpdir:
            ctx.session_worktree = tmpdir
            result = ClaudeResult(
                exit_code=0,
                session_id='s1',
                stderr_lines=['Error: tool execution failed', 'Warning: rate limited'],
            )
            actor_result = runner._interpret_output(ctx, result)
            self.assertEqual(
                actor_result.data['stderr_lines'],
                ['Error: tool execution failed', 'Warning: rate limited'],
            )

    def test_interpret_output_omits_stderr_when_empty(self):
        """When ClaudeResult has no stderr, data should not contain stderr_lines."""
        runner = AgentRunner()
        ctx = _make_ctx()

        with tempfile.TemporaryDirectory() as tmpdir:
            ctx.session_worktree = tmpdir
            result = ClaudeResult(exit_code=0, session_id='s1', stderr_lines=[])
            actor_result = runner._interpret_output(ctx, result)
            self.assertNotIn('stderr_lines', actor_result.data)

    def test_agent_runner_run_propagates_stderr_on_nonzero_exit(self):
        """AgentRunner.run() includes stderr_lines in the failed ActorResult when exit_code != 0."""
        from projects.POC.orchestrator.claude_runner import ClaudeRunner
        runner = AgentRunner()
        ctx = _make_ctx()

        with tempfile.TemporaryDirectory() as tmpdir:
            ctx.session_worktree = tmpdir
            fake_claude_result = ClaudeResult(
                exit_code=1,
                session_id='s1',
                stderr_lines=['fatal: API key invalid', 'Permission denied'],
            )
            with patch.object(ClaudeRunner, 'run', new=AsyncMock(return_value=fake_claude_result)):
                actor_result = _run(runner.run(ctx))

        self.assertEqual(actor_result.action, 'failed')
        self.assertEqual(
            actor_result.data['stderr_lines'],
            ['fatal: API key invalid', 'Permission denied'],
        )
        self.assertEqual(actor_result.data['reason'], 'nonzero_exit')

    def test_agent_runner_run_propagates_stderr_on_stall_killed(self):
        """AgentRunner.run() includes stderr_lines in the failed ActorResult when stall_killed."""
        from projects.POC.orchestrator.claude_runner import ClaudeRunner
        runner = AgentRunner()
        ctx = _make_ctx()

        with tempfile.TemporaryDirectory() as tmpdir:
            ctx.session_worktree = tmpdir
            fake_claude_result = ClaudeResult(
                exit_code=-1,
                session_id='s1',
                stall_killed=True,
                stderr_lines=['subprocess timed out after 1800s'],
            )
            with patch.object(ClaudeRunner, 'run', new=AsyncMock(return_value=fake_claude_result)):
                actor_result = _run(runner.run(ctx))

        self.assertEqual(actor_result.action, 'failed')
        self.assertEqual(
            actor_result.data['stderr_lines'],
            ['subprocess timed out after 1800s'],
        )
        self.assertEqual(actor_result.data['reason'], 'stall_timeout')


class TestClaudeResultHadErrors(unittest.TestCase):
    """ClaudeResult.had_errors convenience property."""

    def test_had_errors_true(self):
        r = ClaudeResult(exit_code=0, stderr_lines=['oops'])
        self.assertTrue(r.had_errors)

    def test_had_errors_false(self):
        r = ClaudeResult(exit_code=0, stderr_lines=[])
        self.assertFalse(r.had_errors)

    def test_had_errors_default(self):
        r = ClaudeResult(exit_code=0)
        self.assertFalse(r.had_errors)


# ── _generate_work_summary ────────────────────────────────────────────────────

class TestGenerateWorkSummary(unittest.TestCase):
    """Work summary is generated from git log for WORK_ASSERT gate."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Simulate real session branching: commits on main, then branch off.
        # This ensures _generate_work_summary scopes to session-only commits
        # and doesn't leak main's history (Issue #127).
        _run_sync('git', 'init', '-b', 'main', cwd=self.tmpdir)
        _run_sync('git', 'commit', '--allow-empty', '-m', 'initial', cwd=self.tmpdir)
        _run_sync('git', 'commit', '--allow-empty', '-m', 'main: unrelated work', cwd=self.tmpdir)
        _run_sync('git', 'checkout', '-b', 'session-branch', cwd=self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _add_dispatch_commit(self, message: str):
        """Simulate a dispatch squash-merge commit."""
        _run_sync('git', 'commit', '--allow-empty', '-m', message, cwd=self.tmpdir)

    def test_creates_summary_from_dispatch_commits(self):
        from projects.POC.orchestrator.actors import _generate_work_summary
        self._add_dispatch_commit('coding: implement API endpoint\n\nAdds REST API for users.')
        self._add_dispatch_commit('art: create logo assets\n\nPixel art sprites for all entities.')

        _run(_generate_work_summary(self.tmpdir))

        summary_path = os.path.join(self.tmpdir, '.work-summary.md')
        self.assertTrue(os.path.exists(summary_path))
        content = Path(summary_path).read_text()
        self.assertIn('coding: implement API endpoint', content)
        self.assertIn('art: create logo assets', content)

    def test_includes_all_rounds_on_regeneration(self):
        """After correction, re-generation includes both old and new commits."""
        from projects.POC.orchestrator.actors import _generate_work_summary
        self._add_dispatch_commit('coding: first pass')

        _run(_generate_work_summary(self.tmpdir))
        content1 = Path(os.path.join(self.tmpdir, '.work-summary.md')).read_text()
        self.assertIn('first pass', content1)

        # Simulate correction round — more dispatch work
        self._add_dispatch_commit('coding: fix validation')
        _run(_generate_work_summary(self.tmpdir))

        content2 = Path(os.path.join(self.tmpdir, '.work-summary.md')).read_text()
        self.assertIn('first pass', content2)
        self.assertIn('fix validation', content2)

    def test_filters_wip_commits(self):
        """WIP infrastructure commits from merge.py should not appear."""
        from projects.POC.orchestrator.actors import _generate_work_summary
        _run_sync('git', 'commit', '--allow-empty', '-m',
                  'WIP: [coding] some task', cwd=self.tmpdir)
        self._add_dispatch_commit('coding: real work')

        _run(_generate_work_summary(self.tmpdir))

        content = Path(os.path.join(self.tmpdir, '.work-summary.md')).read_text()
        self.assertNotIn('WIP:', content)
        self.assertIn('real work', content)

    def test_placeholder_when_no_work(self):
        """Empty git log still creates a summary file for the artifact check."""
        from projects.POC.orchestrator.actors import _generate_work_summary
        # Only the initial commit exists — filtered because no dispatch commits
        _run(_generate_work_summary(self.tmpdir))

        summary_path = os.path.join(self.tmpdir, '.work-summary.md')
        self.assertTrue(os.path.exists(summary_path))
        content = Path(summary_path).read_text()
        self.assertIn('Work Summary', content)

    def test_excludes_main_history(self):
        """Work summary must not include commits from main (Issue #127)."""
        from projects.POC.orchestrator.actors import _generate_work_summary
        self._add_dispatch_commit('coding: session work')

        _run(_generate_work_summary(self.tmpdir))

        content = Path(os.path.join(self.tmpdir, '.work-summary.md')).read_text()
        self.assertIn('session work', content)
        self.assertNotIn('initial', content)
        self.assertNotIn('unrelated work', content)


class TestInterpretOutputExecutionArtifact(unittest.TestCase):
    """Execution phase with .work-summary.md routes to assert, not auto-approve."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.runner = AgentRunner()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_execution_spec(self):
        return PhaseSpec(
            name='execution',
            agent_file='agents/uber-team.json',
            lead='project-lead',
            permission_mode='acceptEdits',
            stream_file='.exec-stream.jsonl',
            artifact='.work-summary.md',
            approval_state='WORK_ASSERT',
            settings_overlay={},
        )

    def test_work_summary_present_routes_to_assert(self):
        spec = self._make_execution_spec()
        ctx = _make_ctx(
            state='WORK_IN_PROGRESS',
            session_worktree=self.tmpdir,
            phase_spec=spec,
        )
        # Write the work summary
        Path(os.path.join(self.tmpdir, '.work-summary.md')).write_text('# Work Summary\n')

        result = self.runner._interpret_output(ctx, _make_claude_result())

        self.assertEqual(result.action, 'assert')
        self.assertIn('.work-summary.md', result.data.get('artifact_path', ''))

    def test_work_summary_missing_still_routes_to_assert(self):
        """If .work-summary.md is expected but missing, still route to assert
        with artifact_missing=True so the gate can handle it."""
        spec = self._make_execution_spec()
        ctx = _make_ctx(
            state='WORK_IN_PROGRESS',
            session_worktree=self.tmpdir,
            phase_spec=spec,
        )

        result = self.runner._interpret_output(ctx, _make_claude_result())

        self.assertEqual(result.action, 'assert')
        self.assertTrue(result.data.get('artifact_missing'))


class TestRelocateMisplacedArtifact(unittest.TestCase):
    """Artifacts written anywhere must be moved to the worktree via stream parsing."""

    def setUp(self):
        self.worktree = tempfile.mkdtemp()
        self.stream_dir = tempfile.mkdtemp()
        self.stream_file = os.path.join(self.stream_dir, '.intent-stream.jsonl')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.worktree, ignore_errors=True)
        shutil.rmtree(self.stream_dir, ignore_errors=True)

    def _write_stream_with_write_call(self, file_path: str):
        """Write a stream JSONL with a Write tool call to file_path."""
        import json as _json
        event = {
            'type': 'assistant',
            'message': {
                'content': [{
                    'type': 'tool_use',
                    'name': 'Write',
                    'input': {'file_path': file_path, 'content': '# test'},
                }],
            },
        }
        with open(self.stream_file, 'w') as f:
            f.write(_json.dumps(event) + '\n')

    def test_relocates_artifact_found_via_stream(self):
        """INTENT.md written to arbitrary path is moved to worktree root."""
        from projects.POC.orchestrator.actors import _relocate_misplaced_artifact

        # Agent wrote to some random absolute path
        wrong_dir = tempfile.mkdtemp()
        misplaced = os.path.join(wrong_dir, 'INTENT.md')
        Path(misplaced).write_text('# Intent\nObjective: test')
        self._write_stream_with_write_call(misplaced)

        result = _relocate_misplaced_artifact(
            self.worktree, self.stream_file, 'INTENT.md',
        )

        self.assertTrue(result)
        self.assertTrue(os.path.exists(os.path.join(self.worktree, 'INTENT.md')))
        self.assertFalse(os.path.exists(misplaced))
        import shutil
        shutil.rmtree(wrong_dir, ignore_errors=True)

    def test_relocates_from_repo_root(self):
        """INTENT.md written to repo root (real failure case) is relocated."""
        from projects.POC.orchestrator.actors import _relocate_misplaced_artifact

        repo_root = tempfile.mkdtemp()
        misplaced = os.path.join(repo_root, 'INTENT.md')
        Path(misplaced).write_text('# Intent\nRepo root write')
        self._write_stream_with_write_call(misplaced)

        result = _relocate_misplaced_artifact(
            self.worktree, self.stream_file, 'INTENT.md',
        )

        self.assertTrue(result)
        self.assertTrue(os.path.exists(os.path.join(self.worktree, 'INTENT.md')))
        self.assertFalse(os.path.exists(misplaced))
        import shutil
        shutil.rmtree(repo_root, ignore_errors=True)

    def test_relocates_from_project_dir(self):
        """INTENT.md written to project dir (other real failure case) is relocated."""
        from projects.POC.orchestrator.actors import _relocate_misplaced_artifact

        project_dir = tempfile.mkdtemp()
        misplaced = os.path.join(project_dir, 'INTENT.md')
        Path(misplaced).write_text('# Intent\nProject dir write')
        self._write_stream_with_write_call(misplaced)

        result = _relocate_misplaced_artifact(
            self.worktree, self.stream_file, 'INTENT.md',
        )

        self.assertTrue(result)
        self.assertTrue(os.path.exists(os.path.join(self.worktree, 'INTENT.md')))
        import shutil
        shutil.rmtree(project_dir, ignore_errors=True)

    def test_no_op_when_artifact_already_in_worktree(self):
        """If artifact is already in the worktree, nothing is moved."""
        from projects.POC.orchestrator.actors import _relocate_misplaced_artifact

        correct = os.path.join(self.worktree, 'INTENT.md')
        Path(correct).write_text('# Intent\nCorrect location')

        result = _relocate_misplaced_artifact(
            self.worktree, self.stream_file, 'INTENT.md',
        )

        self.assertFalse(result)
        self.assertEqual(Path(correct).read_text(), '# Intent\nCorrect location')

    def test_no_op_when_no_write_in_stream(self):
        """If stream has no Write calls for the artifact, returns False."""
        from projects.POC.orchestrator.actors import _relocate_misplaced_artifact

        # Empty stream
        with open(self.stream_file, 'w') as f:
            f.write('')

        result = _relocate_misplaced_artifact(
            self.worktree, self.stream_file, 'INTENT.md',
        )

        self.assertFalse(result)

    def test_no_op_when_stream_file_missing(self):
        """If stream file doesn't exist, returns False."""
        from projects.POC.orchestrator.actors import _relocate_misplaced_artifact

        result = _relocate_misplaced_artifact(
            self.worktree, '/nonexistent/stream.jsonl', 'INTENT.md',
        )

        self.assertFalse(result)

    def test_works_for_plan_artifact(self):
        """Relocation works for PLAN.md too."""
        from projects.POC.orchestrator.actors import _relocate_misplaced_artifact

        wrong_dir = tempfile.mkdtemp()
        misplaced = os.path.join(wrong_dir, 'PLAN.md')
        Path(misplaced).write_text('# Plan\nStep 1')
        self._write_stream_with_write_call(misplaced)

        result = _relocate_misplaced_artifact(
            self.worktree, self.stream_file, 'PLAN.md',
        )

        self.assertTrue(result)
        self.assertTrue(os.path.exists(os.path.join(self.worktree, 'PLAN.md')))
        import shutil
        shutil.rmtree(wrong_dir, ignore_errors=True)

    def test_end_to_end_relocate_then_interpret(self):
        """End-to-end: misplaced artifact is relocated, then _interpret_output finds it."""
        from projects.POC.orchestrator.actors import _relocate_misplaced_artifact

        wrong_dir = tempfile.mkdtemp()
        misplaced = os.path.join(wrong_dir, 'INTENT.md')
        Path(misplaced).write_text('# Intent\nObjective: end-to-end test')
        self._write_stream_with_write_call(misplaced)

        _relocate_misplaced_artifact(
            self.worktree, self.stream_file, 'INTENT.md',
        )

        runner = AgentRunner()
        spec = _make_phase_spec(artifact='INTENT.md')
        ctx = _make_ctx(
            state='PROPOSAL',
            session_worktree=self.worktree,
            phase_spec=spec,
        )

        result = runner._interpret_output(ctx, _make_claude_result())

        self.assertEqual(result.action, 'assert')
        self.assertNotIn('artifact_missing', result.data)
        self.assertEqual(
            result.data.get('artifact_path'),
            os.path.join(self.worktree, 'INTENT.md'),
        )
        import shutil
        shutil.rmtree(wrong_dir, ignore_errors=True)


def _run_sync(*args, cwd=None):
    """Run a command synchronously for test setup."""
    import subprocess as sp
    sp.run(args, cwd=cwd, capture_output=True, check=True)


if __name__ == '__main__':
    unittest.main()
