#!/usr/bin/env python3
"""Tests for issue #145: TASK_ASSERT routes through proxy, never escalates to human.

The proxy runs at TASK_ASSERT and TASK_ESCALATE — reads deliverables, uses
learned patterns, can dialog — but never asks the human.  If the proxy isn't
confident, it goes with its best guess.

Tests verify:
  1. TASK_ASSERT is routed to approval_gate (not execution_lead)
  2. TASK_ASSERT has a canonical gate question
  3. Proxy at TASK_ASSERT never escalates to human (even at zero confidence)
  4. Proxy at TASK_ASSERT still runs and its text is used
  5. TASK_ASSERT receives upstream context (INTENT.md, PLAN.md)
  6. TASK_ESCALATE also never escalates to human
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.actors import (
    ActorContext,
    ApprovalGate,
    _GATE_QUESTIONS,
    _NEVER_ESCALATE_STATES,
)
from projects.POC.orchestrator.events import EventBus
from projects.POC.orchestrator.phase_config import PhaseSpec
from projects.POC.orchestrator.proxy_agent import ProxyResult


def _run(coro):
    return asyncio.run(coro)


def _make_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


def _make_phase_spec() -> PhaseSpec:
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


def _make_ctx(
    state: str = 'TASK_ASSERT',
    session_worktree: str = '/tmp/worktree',
    infra_dir: str = '/tmp/infra',
) -> ActorContext:
    return ActorContext(
        state=state,
        phase='execution',
        task='Write 58 math jokes',
        infra_dir=infra_dir,
        project_workdir='/tmp/project',
        session_worktree=session_worktree,
        stream_file='.exec-stream.jsonl',
        phase_spec=_make_phase_spec(),
        poc_root='/tmp/poc',
        event_bus=_make_event_bus(),
        session_id='test-session',
    )


# ── CfA state machine routing ───────────────────────────────────────────────

class TestTaskAssertRoutesToApprovalGate(unittest.TestCase):
    """TASK_ASSERT must be routed to approval_gate, not execution_lead."""

    def test_task_assert_actor_is_approval_gate(self):
        """cfa-state-machine.json must have approval_gate as actor for TASK_ASSERT."""
        machine_path = Path(__file__).parent.parent.parent / 'cfa-state-machine.json'
        with open(machine_path) as f:
            machine = json.load(f)
        edges = machine['transitions']['TASK_ASSERT']
        actors = {e['actor'] for e in edges}
        self.assertEqual(actors, {'approval_gate'},
                         f"TASK_ASSERT actors must all be approval_gate, got {actors}")

    def test_task_assert_in_human_actor_states(self):
        """PhaseConfig must recognize TASK_ASSERT as a human/approval_gate state."""
        from projects.POC.orchestrator.phase_config import PhaseConfig
        poc_root = str(Path(__file__).parent.parent.parent)
        config = PhaseConfig(poc_root)
        self.assertIn('TASK_ASSERT', config.human_actor_states,
                       "TASK_ASSERT must be in human_actor_states")


# ── Canonical gate question ─────────────────────────────────────────────────

class TestTaskAssertGateQuestion(unittest.TestCase):
    """TASK_ASSERT must have a canonical gate question."""

    def test_gate_question_exists(self):
        self.assertIn('TASK_ASSERT', _GATE_QUESTIONS,
                       "TASK_ASSERT must have a canonical gate question")

    def test_gate_question_mentions_task(self):
        q = _GATE_QUESTIONS['TASK_ASSERT']
        self.assertIn('task', q.lower(),
                       f"Gate question must mention 'task': {q}")


# ── Never escalates to human ────────────────────────────────────────────────

class TestTaskAssertNeverEscalates(unittest.TestCase):
    """TASK_ASSERT and TASK_ESCALATE must never ask the human."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_task_assert_in_never_escalate_states(self):
        self.assertIn('TASK_ASSERT', _NEVER_ESCALATE_STATES)

    def test_task_escalate_in_never_escalate_states(self):
        self.assertIn('TASK_ESCALATE', _NEVER_ESCALATE_STATES)

    def test_human_never_asked_at_task_assert_even_zero_confidence(self):
        """Even when proxy returns zero confidence, human must NOT be asked."""
        input_calls = []

        async def _input_provider(req):
            input_calls.append(req)
            return 'approve'

        gate = ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=_input_provider,
            poc_root=self.tmpdir,
        )
        ctx = _make_ctx(session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        ctx.data = {}

        with patch('projects.POC.orchestrator.proxy_agent.consult_proxy',
                   new=AsyncMock(return_value=ProxyResult(
                       text='', confidence=0.0, from_agent=False))), \
             patch.object(gate, '_classify_review', return_value=('approve', '')), \
             patch.object(gate, '_proxy_record'):
            result = _run(gate.run(ctx))

        self.assertEqual(len(input_calls), 0,
                         "Human must NEVER be asked at TASK_ASSERT")
        self.assertEqual(result.action, 'approve')

    def test_proxy_text_used_at_task_assert_even_low_confidence(self):
        """When proxy returns text at low confidence, that text is still used."""
        input_calls = []

        async def _input_provider(req):
            input_calls.append(req)
            return 'approve'

        gate = ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=_input_provider,
            poc_root=self.tmpdir,
        )
        ctx = _make_ctx(session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        ctx.data = {}

        proxy_text = 'The jokes look good but joke #14 repeats a punchline.'

        with patch('projects.POC.orchestrator.proxy_agent.consult_proxy',
                   new=AsyncMock(return_value=ProxyResult(
                       text=proxy_text, confidence=0.2, from_agent=True))), \
             patch.object(gate, '_classify_review',
                          return_value=('correct', 'Fix joke #14')) as mock_classify, \
             patch.object(gate, '_proxy_record'):
            result = _run(gate.run(ctx))

        self.assertEqual(len(input_calls), 0, "Human must not be asked")
        # The proxy's text must be what gets classified
        mock_classify.assert_called()
        classified_text = mock_classify.call_args[0][1]
        self.assertEqual(classified_text, proxy_text)

    def test_empty_proxy_defaults_to_approval(self):
        """When proxy returns nothing, default to approval (not escalate)."""
        input_calls = []

        async def _input_provider(req):
            input_calls.append(req)
            return 'approve'

        gate = ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=_input_provider,
            poc_root=self.tmpdir,
        )
        ctx = _make_ctx(session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        ctx.data = {}

        with patch('projects.POC.orchestrator.proxy_agent.consult_proxy',
                   new=AsyncMock(return_value=ProxyResult(
                       text='', confidence=0.0, from_agent=False))), \
             patch.object(gate, '_classify_review',
                          return_value=('approve', '')) as mock_classify, \
             patch.object(gate, '_proxy_record'):
            result = _run(gate.run(ctx))

        self.assertEqual(len(input_calls), 0)
        # The default 'Approved.' text must be classified
        classified_text = mock_classify.call_args[0][1]
        self.assertEqual(classified_text, 'Approved.')


# ── Upstream context ────────────────────────────────────────────────────────

class TestTaskAssertUpstreamContext(unittest.TestCase):
    """Proxy at TASK_ASSERT must receive INTENT.md and PLAN.md."""

    def test_task_assert_gets_intent_and_plan(self):
        """run_proxy_agent includes INTENT.md and PLAN.md for TASK_ASSERT."""
        tmpdir = tempfile.mkdtemp()
        try:
            Path(os.path.join(tmpdir, 'INTENT.md')).write_text('# Intent')
            Path(os.path.join(tmpdir, 'PLAN.md')).write_text('# Plan')
            artifact = os.path.join(tmpdir, 'output.txt')
            Path(artifact).write_text('deliverable')

            with patch('subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout='Looks correct.\nCONFIDENCE: 0.9',
                )
                from projects.POC.orchestrator.proxy_agent import run_proxy_agent
                text, conf = _run(run_proxy_agent(
                    question='Does this look right?',
                    state='TASK_ASSERT',
                    artifact_path=artifact,
                    session_worktree=tmpdir,
                    infra_dir=tmpdir,
                ))

            # The prompt sent to claude must include INTENT.md and PLAN.md paths
            prompt = mock_run.call_args[1].get('input', '') or mock_run.call_args[0][0] if mock_run.call_args[0] else ''
            if not prompt:
                # Check kwargs
                prompt = str(mock_run.call_args)
            self.assertIn('INTENT.md', prompt,
                          "TASK_ASSERT proxy must receive INTENT.md context")
            self.assertIn('PLAN.md', prompt,
                          "TASK_ASSERT proxy must receive PLAN.md context")
        finally:
            import shutil; shutil.rmtree(tmpdir, ignore_errors=True)

    def test_task_escalate_gets_intent_and_plan(self):
        """run_proxy_agent includes INTENT.md and PLAN.md for TASK_ESCALATE."""
        tmpdir = tempfile.mkdtemp()
        try:
            Path(os.path.join(tmpdir, 'INTENT.md')).write_text('# Intent')
            Path(os.path.join(tmpdir, 'PLAN.md')).write_text('# Plan')

            with patch('subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout='Use approach B.\nCONFIDENCE: 0.7',
                )
                from projects.POC.orchestrator.proxy_agent import run_proxy_agent
                _run(run_proxy_agent(
                    question='Should I use approach A or B?',
                    state='TASK_ESCALATE',
                    session_worktree=tmpdir,
                    infra_dir=tmpdir,
                ))

            prompt = str(mock_run.call_args)
            self.assertIn('INTENT.md', prompt)
            self.assertIn('PLAN.md', prompt)
        finally:
            import shutil; shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
