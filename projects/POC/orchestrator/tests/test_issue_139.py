#!/usr/bin/env python3
"""Tests for issue #139: Proxy agent must be an actual agent, not a statistical heuristic.

There is ONE proxy invocation path (proxy_agent.consult_proxy) used by both
ApprovalGate and EscalationListener.  Every time the system needs the human's
input, it goes through the same flow:

  1. Gather context: learned patterns, similar past interactions
  2. Invoke the proxy agent (Claude CLI with file-read tools) — always
  3. Agent generates text + self-assessed confidence
  4. Statistical calibration adjusts confidence based on historical accuracy
  5. If confident → agent's text IS the answer
  6. If not confident → same question goes to human
  7. Both feed into learning

The proxy agent always runs.  Statistics never gate it.
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.actors import (
    ActorContext,
    ActorResult,
    ApprovalGate,
)
from projects.POC.orchestrator.events import EventBus
from projects.POC.orchestrator.phase_config import PhaseSpec
from projects.POC.orchestrator.proxy_agent import (
    ProxyResult,
    consult_proxy,
    parse_proxy_agent_output,
    run_proxy_agent,
    PROXY_AGENT_CONFIDENCE_THRESHOLD,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


def _make_phase_spec(artifact: str | None = 'INTENT.md') -> PhaseSpec:
    return PhaseSpec(
        name='intent', agent_file='agents/intent-team.json', lead='intent-lead',
        permission_mode='acceptEdits', stream_file='.intent-stream.jsonl',
        artifact=artifact, approval_state='INTENT_ASSERT', settings_overlay={},
    )


def _make_ctx(
    state: str = 'INTENT_ASSERT',
    session_worktree: str = '/tmp/worktree',
    infra_dir: str = '/tmp/infra',
) -> ActorContext:
    return ActorContext(
        state=state, phase='intent', task='Write a blog post about AI',
        infra_dir=infra_dir, project_workdir='/tmp/project',
        session_worktree=session_worktree, stream_file='.intent-stream.jsonl',
        phase_spec=_make_phase_spec(), poc_root='/tmp/poc',
        event_bus=_make_event_bus(), session_id='test-session',
    )


def _make_gate(tmpdir: str, human_response: str = 'approve') -> ApprovalGate:
    async def _input_provider(req):
        return human_response
    return ApprovalGate(
        proxy_model_path=os.path.join(tmpdir, '.proxy.json'),
        input_provider=_input_provider, poc_root=tmpdir,
    )


def _make_warm_model_json(state: str = 'INTENT_ASSERT', task: str = 'default') -> dict:
    key = f'{state}|{task}'
    return {
        'entries': {
            key: {
                'state': state, 'task_type': task,
                'approve_count': 10, 'correct_count': 0, 'reject_count': 0,
                'total_count': 10, 'last_updated': date.today().isoformat(),
                'differentials': [], 'ema_approval_rate': 0.95,
                'artifact_lengths': [], 'question_patterns': [],
                'prediction_correct_count': 0, 'prediction_total_count': 0,
            },
        },
        'global_threshold': 0.8, 'generative_threshold': 0.95,
    }


def _run(coro):
    return asyncio.run(coro)


# ── consult_proxy is the ONE path ───────────────────────────────────────────

class TestConsultProxyIsTheOnePath(unittest.TestCase):
    """Both ApprovalGate and EscalationListener use consult_proxy."""

    def test_approval_gate_uses_consult_proxy(self):
        """ApprovalGate.run() must call consult_proxy from proxy_agent.py."""
        tmpdir = tempfile.mkdtemp()
        try:
            gate = _make_gate(tmpdir)
            ctx = _make_ctx(session_worktree=tmpdir, infra_dir=tmpdir)
            artifact_path = os.path.join(tmpdir, 'INTENT.md')
            Path(artifact_path).write_text('# Intent\nBuild something')
            ctx.data = {'artifact_path': artifact_path}

            with patch('projects.POC.orchestrator.proxy_agent.consult_proxy', new_callable=AsyncMock) as mock_cp, \
                 patch.object(gate, '_classify_review', return_value=('approve', '')), \
                 patch.object(gate, '_proxy_record'):
                mock_cp.return_value = ProxyResult(text='Approved.', confidence=0.95)
                _run(gate.run(ctx))

            mock_cp.assert_called_once()
        finally:
            import shutil; shutil.rmtree(tmpdir, ignore_errors=True)

    def test_escalation_listener_uses_consult_proxy(self):
        """EscalationListener._route_through_proxy must call consult_proxy."""
        from projects.POC.orchestrator.escalation_listener import EscalationListener

        tmpdir = tempfile.mkdtemp()
        try:
            listener = EscalationListener(
                event_bus=_make_event_bus(),
                input_provider=AsyncMock(return_value='human answer'),
                proxy_model_path=os.path.join(tmpdir, '.proxy.json'),
                project_slug='default', cfa_state='INTENT_ESCALATE',
                session_worktree=tmpdir, infra_dir=tmpdir,
            )
            with patch('projects.POC.orchestrator.proxy_agent.consult_proxy', new_callable=AsyncMock) as mock_cp:
                mock_cp.return_value = ProxyResult(text='', confidence=0.0, from_agent=False)
                _run(listener._route_through_proxy('What is the audience?'))

            mock_cp.assert_called_once()
        finally:
            import shutil; shutil.rmtree(tmpdir, ignore_errors=True)


# ── Proxy agent generates text, not categorical decisions ────────────────────

class TestProxyAgentGeneratesText(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_agent_text_used_when_confident(self):
        """When confident, the agent's text is classified — human not asked."""
        input_calls = []

        async def _input_provider(req):
            input_calls.append(req)
            return 'approve'

        gate = ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=_input_provider, poc_root=self.tmpdir,
        )
        ctx = _make_ctx(session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        artifact_path = os.path.join(self.tmpdir, 'INTENT.md')
        Path(artifact_path).write_text('# Intent\nBuild something great')
        ctx.data = {'artifact_path': artifact_path}

        agent_text = 'Yes, this captures my idea completely.'

        with patch('projects.POC.orchestrator.proxy_agent.consult_proxy', new_callable=AsyncMock) as mock_cp, \
             patch.object(gate, '_classify_review', return_value=('approve', '')) as mock_classify, \
             patch.object(gate, '_proxy_record'):
            mock_cp.return_value = ProxyResult(text=agent_text, confidence=0.95)
            _run(gate.run(ctx))

        mock_classify.assert_called()
        classified_text = mock_classify.call_args[0][1]
        self.assertEqual(classified_text, agent_text)
        self.assertEqual(len(input_calls), 0, "Human must not be asked when proxy is confident")

    def test_human_asked_when_not_confident(self):
        """When confidence < threshold, the human is asked."""
        input_calls = []

        async def _input_provider(req):
            input_calls.append(req)
            return 'Looks good, approved.'

        gate = ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=_input_provider, poc_root=self.tmpdir,
        )
        ctx = _make_ctx(session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        artifact_path = os.path.join(self.tmpdir, 'INTENT.md')
        Path(artifact_path).write_text('# Intent')
        ctx.data = {'artifact_path': artifact_path}

        with patch('projects.POC.orchestrator.proxy_agent.consult_proxy', new_callable=AsyncMock) as mock_cp, \
             patch.object(gate, '_classify_review', return_value=('approve', '')), \
             patch.object(gate, '_proxy_record'):
            mock_cp.return_value = ProxyResult(text="Not sure.", confidence=0.3)
            _run(gate.run(ctx))

        self.assertGreaterEqual(len(input_calls), 1)

    def test_stats_escalate_skips_agent(self):
        """When stats say escalate (from_agent=False), go straight to human."""
        input_calls = []

        async def _input_provider(req):
            input_calls.append(req)
            return 'approve'

        gate = ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=_input_provider, poc_root=self.tmpdir,
        )
        ctx = _make_ctx(session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        ctx.data = {'artifact_path': os.path.join(self.tmpdir, 'INTENT.md')}
        Path(ctx.data['artifact_path']).write_text('# Intent')

        with patch('projects.POC.orchestrator.proxy_agent.consult_proxy', new_callable=AsyncMock) as mock_cp, \
             patch.object(gate, '_classify_review', return_value=('approve', '')), \
             patch.object(gate, '_proxy_record'):
            mock_cp.return_value = ProxyResult(text='', confidence=0.0, from_agent=False)
            _run(gate.run(ctx))

        self.assertGreaterEqual(len(input_calls), 1)


# ── Proxy agent dialog ──────────────────────────────────────────────────────

class TestProxyAgentDialog(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_dialog_loops_back_through_proxy(self):
        """When classify returns 'dialog', the loop calls consult_proxy again."""
        gate = ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=AsyncMock(return_value='approve'),
            poc_root=self.tmpdir,
        )
        ctx = _make_ctx(session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        Path(os.path.join(self.tmpdir, 'INTENT.md')).write_text('# Intent')
        ctx.data = {'artifact_path': os.path.join(self.tmpdir, 'INTENT.md')}

        # Two calls to consult_proxy: first returns question, second returns approval.
        proxy_returns = iter([
            ProxyResult(text='Why a monolith?', confidence=0.90),
            ProxyResult(text='OK, approved.', confidence=0.95),
        ])
        classify_returns = iter([
            ('dialog', ''),
            ('approve', ''),
        ])

        with patch('projects.POC.orchestrator.proxy_agent.consult_proxy',
                   new=AsyncMock(side_effect=lambda **kw: next(proxy_returns))), \
             patch.object(gate, '_classify_review', side_effect=lambda *a, **kw: next(classify_returns)), \
             patch.object(gate, '_proxy_record'):
            result = _run(gate.run(ctx))

        # After dialog, "approve" becomes "correct" to feed back to the agent.
        self.assertEqual(result.action, 'correct')

    def test_proxy_loses_confidence_human_asked_on_next_turn(self):
        """If proxy loses confidence, the next loop turn escalates to human."""
        input_calls = []

        async def _input_provider(req):
            input_calls.append(req)
            return 'approved'

        gate = ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=_input_provider, poc_root=self.tmpdir,
        )
        ctx = _make_ctx(session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        Path(os.path.join(self.tmpdir, 'INTENT.md')).write_text('# Intent')
        ctx.data = {'artifact_path': os.path.join(self.tmpdir, 'INTENT.md')}

        # First call: proxy confident (dialog). Second call: proxy not confident (human asked).
        proxy_returns = iter([
            ProxyResult(text='What about rollback?', confidence=0.90),
            ProxyResult(text='', confidence=0.0, from_agent=False),
        ])
        classify_returns = iter([
            ('dialog', ''),
            ('approve', ''),
        ])

        with patch('projects.POC.orchestrator.proxy_agent.consult_proxy',
                   new=AsyncMock(side_effect=lambda **kw: next(proxy_returns))), \
             patch.object(gate, '_classify_review', side_effect=lambda *a, **kw: next(classify_returns)), \
             patch.object(gate, '_proxy_record'):
            _run(gate.run(ctx))

        self.assertGreaterEqual(len(input_calls), 1, "Human must be asked when proxy loses confidence")


# ── consult_proxy internals ─────────────────────────────────────────────────

class TestAgentAlwaysInvoked(unittest.TestCase):
    """The proxy agent is always invoked.  Statistics never gate it."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_model_file(self, model_json=None):
        model_path = os.path.join(self.tmpdir, '.proxy.json')
        data = model_json or {'entries': {}, 'global_threshold': 0.8, 'generative_threshold': 0.95}
        with open(model_path, 'w') as f:
            json.dump(data, f)
        return model_path

    def test_agent_invoked_on_cold_start(self):
        """Cold start (no history) — agent still runs."""
        model_path = self._make_model_file()  # empty entries = cold start
        mock_agent = AsyncMock(return_value=('Looks good to me.', 0.9))

        with patch('projects.POC.orchestrator.proxy_agent.run_proxy_agent', mock_agent):
            result = _run(consult_proxy(
                question='Do you approve?', state='INTENT_ASSERT',
                proxy_model_path=model_path,
            ))

        mock_agent.assert_called_once()
        self.assertTrue(result.from_agent)
        self.assertEqual(result.text, 'Looks good to me.')

    def test_agent_invoked_with_no_model_file(self):
        """No model file at all — agent still runs."""
        model_path = os.path.join(self.tmpdir, 'nonexistent.json')
        mock_agent = AsyncMock(return_value=('Approved.', 0.85))

        with patch('projects.POC.orchestrator.proxy_agent.run_proxy_agent', mock_agent):
            result = _run(consult_proxy(
                question='Do you approve?', state='PLAN_ASSERT',
                proxy_model_path=model_path,
            ))

        mock_agent.assert_called_once()
        self.assertTrue(result.from_agent)
        self.assertEqual(result.text, 'Approved.')

    def test_agent_invoked_with_low_stats_confidence(self):
        """Stats confidence below threshold — agent still runs."""
        # Model with high correction rate → stats would have said "escalate"
        model = _make_warm_model_json()
        entry = model['entries']['INTENT_ASSERT|default']
        entry['approve_count'] = 2
        entry['correct_count'] = 7
        entry['reject_count'] = 1
        entry['total_count'] = 10
        entry['ema_approval_rate'] = 0.2
        model_path = self._make_model_file(model)

        mock_agent = AsyncMock(return_value=('I have concerns about section 3.', 0.7))

        with patch('projects.POC.orchestrator.proxy_agent.run_proxy_agent', mock_agent):
            result = _run(consult_proxy(
                question='Do you approve?', state='INTENT_ASSERT',
                proxy_model_path=model_path,
            ))

        mock_agent.assert_called_once()
        self.assertTrue(result.from_agent)
        self.assertEqual(result.text, 'I have concerns about section 3.')


class TestStatisticalCalibration(unittest.TestCase):
    """Statistics calibrate confidence after the agent responds."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_model_file(self, model_json=None):
        model_path = os.path.join(self.tmpdir, '.proxy.json')
        data = model_json or {'entries': {}, 'global_threshold': 0.8, 'generative_threshold': 0.95}
        with open(model_path, 'w') as f:
            json.dump(data, f)
        return model_path

    def test_cold_start_caps_at_half(self):
        """Cold start caps confidence at 0.5 regardless of agent self-assessment."""
        model_path = self._make_model_file()  # empty = cold start
        mock_agent = AsyncMock(return_value=('Approved.', 0.95))

        with patch('projects.POC.orchestrator.proxy_agent.run_proxy_agent', mock_agent):
            result = _run(consult_proxy(
                question='Do you approve?', state='INTENT_ASSERT',
                proxy_model_path=model_path,
            ))

        self.assertLessEqual(result.confidence, 0.5)

    def test_warm_model_high_approval_preserves_confidence(self):
        """Warm model with high approval rate preserves agent confidence."""
        model = _make_warm_model_json()  # 10/10 approvals
        model_path = self._make_model_file(model)
        mock_agent = AsyncMock(return_value=('Approved.', 0.85))

        with patch('projects.POC.orchestrator.proxy_agent.run_proxy_agent', mock_agent):
            result = _run(consult_proxy(
                question='Do you approve?', state='INTENT_ASSERT',
                proxy_model_path=model_path,
            ))

        # Stats confidence is high (10/10 approvals), so agent's 0.85 should survive
        self.assertGreater(result.confidence, 0.8)

    def test_warm_model_low_approval_reduces_confidence(self):
        """Warm model with low approval rate reduces agent confidence."""
        model = _make_warm_model_json()
        entry = model['entries']['INTENT_ASSERT|default']
        entry['approve_count'] = 2
        entry['correct_count'] = 7
        entry['reject_count'] = 1
        entry['total_count'] = 10
        entry['ema_approval_rate'] = 0.2
        model_path = self._make_model_file(model)
        mock_agent = AsyncMock(return_value=('Approved.', 0.9))

        with patch('projects.POC.orchestrator.proxy_agent.run_proxy_agent', mock_agent):
            result = _run(consult_proxy(
                question='Do you approve?', state='INTENT_ASSERT',
                proxy_model_path=model_path,
            ))

        # Stats show mostly corrections → confidence should be well below agent's 0.9
        self.assertLess(result.confidence, 0.5)

    def test_calibration_never_inflates(self):
        """Calibration can only reduce confidence, never inflate it."""
        model = _make_warm_model_json()  # 10/10 approvals → high stats confidence
        model_path = self._make_model_file(model)
        mock_agent = AsyncMock(return_value=('Looks okay I guess.', 0.3))

        with patch('projects.POC.orchestrator.proxy_agent.run_proxy_agent', mock_agent):
            result = _run(consult_proxy(
                question='Do you approve?', state='INTENT_ASSERT',
                proxy_model_path=model_path,
            ))

        # Agent said 0.3 — stats are high but should not inflate above 0.3
        self.assertLessEqual(result.confidence, 0.3)


# ── parse_proxy_agent_output ────────────────────────────────────────────────

class TestParseProxyAgentOutput(unittest.TestCase):

    def test_standard_format(self):
        text, conf = parse_proxy_agent_output('Yes, looks good.\nCONFIDENCE: 0.85')
        self.assertEqual(text, 'Yes, looks good.')
        self.assertAlmostEqual(conf, 0.85)

    def test_no_marker_returns_zero(self):
        text, conf = parse_proxy_agent_output('I approve this.')
        self.assertEqual(text, 'I approve this.')
        self.assertAlmostEqual(conf, 0.0)

    def test_caps_at_1(self):
        _, conf = parse_proxy_agent_output('Good.\nCONFIDENCE: 1.5')
        self.assertAlmostEqual(conf, 1.0)

    def test_floors_at_0(self):
        _, conf = parse_proxy_agent_output('Hmm.\nCONFIDENCE: -0.3')
        self.assertAlmostEqual(conf, 0.0)

    def test_case_insensitive(self):
        _, conf = parse_proxy_agent_output('Fine.\nconfidence: 0.75')
        self.assertAlmostEqual(conf, 0.75)

    def test_multiline(self):
        text, conf = parse_proxy_agent_output('Line 1.\nLine 2.\nCONFIDENCE: 0.6')
        self.assertIn('Line 2', text)
        self.assertAlmostEqual(conf, 0.6)


# ── Both paths pass context for learning retrieval ──────────────────────────

class TestContextPassedForLearning(unittest.TestCase):
    """consult_proxy receives enough context to retrieve correct learnings."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil; shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_approval_gate_passes_state_and_worktree(self):
        """ApprovalGate passes state, worktree, infra_dir to consult_proxy."""
        gate = _make_gate(self.tmpdir)
        ctx = _make_ctx(session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        Path(os.path.join(self.tmpdir, 'INTENT.md')).write_text('# Intent')
        ctx.data = {'artifact_path': os.path.join(self.tmpdir, 'INTENT.md')}

        with patch('projects.POC.orchestrator.proxy_agent.consult_proxy', new_callable=AsyncMock) as mock_cp, \
             patch.object(gate, '_classify_review', return_value=('approve', '')), \
             patch.object(gate, '_proxy_record'):
            mock_cp.return_value = ProxyResult(text='Approved.', confidence=0.95)
            _run(gate.run(ctx))

        call_kwargs = mock_cp.call_args[1]
        self.assertEqual(call_kwargs['state'], 'INTENT_ASSERT')
        self.assertEqual(call_kwargs['session_worktree'], self.tmpdir)
        self.assertEqual(call_kwargs['infra_dir'], self.tmpdir)

    def test_escalation_listener_passes_state_and_worktree(self):
        """EscalationListener passes state, worktree, infra_dir to consult_proxy."""
        from projects.POC.orchestrator.escalation_listener import EscalationListener

        listener = EscalationListener(
            event_bus=_make_event_bus(),
            input_provider=AsyncMock(return_value='answer'),
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            project_slug='default', cfa_state='TASK_ESCALATE',
            session_worktree=self.tmpdir, infra_dir=self.tmpdir,
        )
        with patch('projects.POC.orchestrator.proxy_agent.consult_proxy', new_callable=AsyncMock) as mock_cp:
            mock_cp.return_value = ProxyResult(text='', confidence=0.0, from_agent=False)
            _run(listener._route_through_proxy('How should I handle errors?'))

        call_kwargs = mock_cp.call_args[1]
        self.assertEqual(call_kwargs['state'], 'TASK_ESCALATE')
        self.assertEqual(call_kwargs['session_worktree'], self.tmpdir)
        self.assertEqual(call_kwargs['infra_dir'], self.tmpdir)


if __name__ == '__main__':
    unittest.main()
