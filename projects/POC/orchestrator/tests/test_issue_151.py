#!/usr/bin/env python3
"""Tests for issue #151: Proxy identity conflation in escalation chain dialog.

When the proxy answers at an approval gate, the dialog history labels the
response as HUMAN: — making it impossible for downstream agents to distinguish
proxy responses from actual human responses.

Tests verify:
  1. When the proxy answers (confident or never-escalate), dialog_history
     labels the response as PROXY:, not HUMAN:
  2. When the actual human answers (proxy not confident, escalated), dialog
     labels the response as HUMAN:
  3. The feedback text in approve-after-dialog uses the correct label
"""
import asyncio
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.actors import (
    ActorContext,
    ApprovalGate,
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
        name='planning',
        agent_file='agents/uber-team.json',
        lead='project-lead',
        permission_mode='acceptEdits',
        stream_file='.plan-stream.jsonl',
        artifact='PLAN.md',
        approval_state='PLAN_ASSERT',
        settings_overlay={},
    )


def _make_ctx(
    state: str = 'PLAN_ASSERT',
    session_worktree: str = '/tmp/worktree',
    infra_dir: str = '/tmp/infra',
) -> ActorContext:
    return ActorContext(
        state=state,
        phase='planning',
        task='Write a plan',
        infra_dir=infra_dir,
        project_workdir='/tmp/project',
        session_worktree=session_worktree,
        stream_file='.plan-stream.jsonl',
        phase_spec=_make_phase_spec(),
        poc_root='/tmp/poc',
        event_bus=_make_event_bus(),
        session_id='test-session',
    )


# ── Proxy responses labeled PROXY: ──────────────────────────────────────


class TestProxyLabelInDialogHistory(unittest.TestCase):
    """Proxy responses must be labeled PROXY:, not HUMAN:."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_proxy_response_labeled_proxy_in_dialog(self):
        """When proxy answers and dialog loops, the dialog_history entry
        must use PROXY:, not HUMAN:."""
        dialog_entries = []
        call_count = 0

        def _classify(state, response, dialog_history='',
                      intent_summary='', plan_summary=''):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ('dialog', 'What approach?')
            return ('approve', '')

        gate = ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=AsyncMock(return_value='approve'),
            poc_root=self.tmpdir,
        )
        ctx = _make_ctx(session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        ctx.data = {}

        # Proxy is confident — answers without escalating to human
        with patch('projects.POC.orchestrator.proxy_agent.consult_proxy',
                   new=AsyncMock(return_value=ProxyResult(
                       text='The plan uses a phased approach.',
                       confidence=0.9, from_agent=True))), \
             patch.object(gate, '_classify_review', side_effect=_classify), \
             patch.object(gate, '_proxy_record'), \
             patch.object(gate, '_generate_dialog_response',
                          return_value='I used phased approach for modularity.'):
            result = _run(gate.run(ctx))

        # The dialog_history in the result must use PROXY:, not HUMAN:
        self.assertIn('PROXY:', result.dialog_history,
                      "Proxy responses must be labeled PROXY: in dialog_history")
        self.assertNotIn('HUMAN:', result.dialog_history,
                         "Proxy responses must NOT be labeled HUMAN:")

    def test_never_escalate_response_labeled_proxy(self):
        """At TASK_ASSERT (_NEVER_ESCALATE), responses are always from
        the proxy and must be labeled PROXY:."""
        call_count = 0

        def _classify(state, response, dialog_history='',
                      intent_summary='', plan_summary=''):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ('dialog', 'checking')
            return ('approve', '')

        gate = ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=AsyncMock(return_value='approve'),
            poc_root=self.tmpdir,
        )

        exec_spec = PhaseSpec(
            name='execution', agent_file='agents/uber-team.json',
            lead='project-lead', permission_mode='acceptEdits',
            stream_file='.exec-stream.jsonl', artifact='.work-summary.md',
            approval_state='WORK_ASSERT', settings_overlay={},
        )
        ctx = _make_ctx(state='TASK_ASSERT',
                        session_worktree=self.tmpdir,
                        infra_dir=self.tmpdir)
        ctx.phase_spec = exec_spec
        ctx.data = {}

        with patch('projects.POC.orchestrator.proxy_agent.consult_proxy',
                   new=AsyncMock(return_value=ProxyResult(
                       text='Task looks complete.',
                       confidence=0.3, from_agent=True))), \
             patch.object(gate, '_classify_review', side_effect=_classify), \
             patch.object(gate, '_proxy_record'), \
             patch.object(gate, '_generate_dialog_response',
                          return_value='Yes, all tests pass.'):
            result = _run(gate.run(ctx))

        self.assertIn('PROXY:', result.dialog_history)
        self.assertNotIn('HUMAN:', result.dialog_history)

    def test_human_response_labeled_human(self):
        """When the proxy is not confident and escalates to the actual
        human, the dialog_history must use HUMAN:."""
        call_count = 0

        def _classify(state, response, dialog_history='',
                      intent_summary='', plan_summary=''):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ('dialog', 'question')
            return ('approve', '')

        human_calls = []

        async def _input_provider(req):
            human_calls.append(req)
            return 'Looks good, approve.'

        gate = ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=_input_provider,
            poc_root=self.tmpdir,
        )
        ctx = _make_ctx(state='PLAN_ASSERT',
                        session_worktree=self.tmpdir,
                        infra_dir=self.tmpdir)
        ctx.data = {}

        # Proxy not confident — will escalate to human
        with patch('projects.POC.orchestrator.proxy_agent.consult_proxy',
                   new=AsyncMock(return_value=ProxyResult(
                       text='', confidence=0.0, from_agent=False))), \
             patch.object(gate, '_classify_review', side_effect=_classify), \
             patch.object(gate, '_proxy_record'), \
             patch.object(gate, '_generate_dialog_response',
                          return_value='Good question.'):
            result = _run(gate.run(ctx))

        self.assertIn('HUMAN:', result.dialog_history,
                      "Human responses must be labeled HUMAN:")
        self.assertNotIn('PROXY:', result.dialog_history,
                         "Human responses must NOT be labeled PROXY:")


if __name__ == '__main__':
    unittest.main()
