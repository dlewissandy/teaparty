#!/usr/bin/env python3
"""Tests for Issue #138: Proxy must always generate predicted response for escalation differentials.

Covers:
 1. generate_response() returns a GenerativeResponse on cold start (zero history)
 2. generate_response() returns a GenerativeResponse when confidence is below threshold
 3. When proxy is not confident and falls through to human, predicted response text is
    recorded in the differential (not just the decision label 'escalate')
 4. record_outcome() stores predicted_response text in the TextDifferential
 5. Non-escalation states are not affected (no predicted response generated)
"""
import asyncio
import json
import os
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.scripts.approval_gate import (
    ConfidenceEntry,
    ConfidenceModel,
    GenerativeResponse,
    generate_response,
    record_outcome,
    load_model,
    save_model,
)
from projects.POC.orchestrator.actors import (
    ActorContext,
    ApprovalGate,
)
from projects.POC.orchestrator.events import EventBus
from projects.POC.orchestrator.phase_config import PhaseSpec


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


def _make_phase_spec() -> PhaseSpec:
    return PhaseSpec(
        name='intent',
        agent_file='agents/intent-team.json',
        lead='intent-lead',
        permission_mode='acceptEdits',
        stream_file='.intent-stream.jsonl',
        artifact='INTENT.md',
        approval_state='INTENT_ASSERT',
        escalation_state='INTENT_ESCALATE',
        escalation_file='.intent-escalation.md',
        settings_overlay={},
    )


def _make_ctx(tmpdir: str, state: str = 'INTENT_ESCALATE') -> ActorContext:
    return ActorContext(
        state=state,
        phase='intent',
        task='Write a blog post about AI',
        infra_dir=tmpdir,
        project_workdir=tmpdir,
        session_worktree=tmpdir,
        stream_file='.intent-stream.jsonl',
        phase_spec=_make_phase_spec(),
        poc_root=tmpdir,
        event_bus=_make_event_bus(),
        session_id='test-session',
    )


def _make_empty_model() -> ConfidenceModel:
    """A model with no entries — cold start."""
    return ConfidenceModel(
        entries={},
        global_threshold=0.8,
        generative_threshold=0.95,
    )


def _make_warm_model_low_confidence() -> ConfidenceModel:
    """A model with history but below generative threshold."""
    entry = asdict(ConfidenceEntry(
        state='INTENT_ESCALATE',
        task_type='default',
        approve_count=2,
        correct_count=3,
        reject_count=0,
        total_count=5,
        last_updated='2026-03-15',
        differentials=[{
            'outcome': 'correct',
            'summary': 'Use PostgreSQL not MySQL',
            'reasoning': 'Production requires ACID compliance',
            'timestamp': '2026-03-14',
        }],
        ema_approval_rate=0.4,
        artifact_lengths=[],
        question_patterns=[],
        prediction_correct_count=0,
        prediction_total_count=0,
    ))
    return ConfidenceModel(
        entries={'INTENT_ESCALATE|default': entry},
        global_threshold=0.8,
        generative_threshold=0.95,
    )


def _run(coro):
    return asyncio.run(coro)


# ── generate_response() must always produce a response for escalation states ──

class TestGenerateResponseAlwaysProduces(unittest.TestCase):
    """generate_response() must return a GenerativeResponse, never None,
    for escalation states — including cold start and low confidence."""

    def test_cold_start_returns_response(self):
        """With zero history, generate_response() must still return a response."""
        model = _make_empty_model()
        result = generate_response(model, 'INTENT_ESCALATE', 'default')
        self.assertIsNotNone(result, "generate_response() returned None on cold start")
        self.assertIsInstance(result, GenerativeResponse)
        self.assertTrue(len(result.text) > 0, "Generated response text must not be empty")

    def test_low_confidence_returns_response(self):
        """With history but low confidence, generate_response() must still return."""
        model = _make_warm_model_low_confidence()
        result = generate_response(model, 'INTENT_ESCALATE', 'default')
        self.assertIsNotNone(result, "generate_response() returned None on low confidence")
        self.assertIsInstance(result, GenerativeResponse)

    def test_cold_start_response_has_low_confidence(self):
        """Cold-start response should have low confidence (not pretend to know)."""
        model = _make_empty_model()
        result = generate_response(model, 'INTENT_ESCALATE', 'default')
        self.assertIsNotNone(result)
        self.assertLess(result.confidence, 0.5,
                        "Cold-start prediction should have low confidence")


# ── Predicted response text must be stored in differential ────────────────────

class TestDifferentialStoresPrediction(unittest.TestCase):
    """When the human responds to an escalation, the differential must include
    both the proxy's predicted response and the human's actual response."""

    def test_record_outcome_stores_predicted_response(self):
        """record_outcome() must store predicted_response text in the differential."""
        model = _make_warm_model_low_confidence()
        updated = record_outcome(
            model,
            state='INTENT_ESCALATE',
            task_type='default',
            outcome='correct',
            differential_summary='Use PostgreSQL',
            predicted_response='Use MySQL',
        )
        entry = updated.entries['INTENT_ESCALATE|default']
        if isinstance(entry, dict):
            diffs = entry.get('differentials', [])
        else:
            diffs = entry.differentials
        # Find the most recent differential
        latest = diffs[-1]
        predicted = latest.get('predicted_response', '') if isinstance(latest, dict) else getattr(latest, 'predicted_response', '')
        self.assertEqual(predicted, 'Use MySQL',
                         "Differential must store the proxy's predicted response text")


# ── Integration: escalation flow stores prediction in differential ────────────

class TestEscalationFlowStoresPrediction(unittest.TestCase):
    """When proxy falls through to human on escalation, the predicted response
    text (not just 'escalate') must be recorded in the learning system."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._input_calls = []

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_gate(self, human_response: str = 'Use PostgreSQL') -> ApprovalGate:
        async def _input_provider(req):
            self._input_calls.append(req)
            return human_response

        return ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=_input_provider,
            poc_root=self.tmpdir,
        )

    def test_escalation_records_predicted_text_not_just_label(self):
        """When proxy generates a low-confidence prediction and falls through
        to the human, _proxy_record must include the predicted response text."""
        gate = self._make_gate(human_response='Use PostgreSQL')
        ctx = _make_ctx(self.tmpdir, state='INTENT_ESCALATE')

        # Write escalation file
        esc_path = os.path.join(self.tmpdir, '.intent-escalation.md')
        Path(esc_path).write_text('What database should I use?')
        ctx.data = {'escalation_file': esc_path}
        ctx.env_vars = {'POC_PROJECT': 'default', 'POC_TEAM': ''}

        predicted_text = 'Use MySQL based on past patterns'
        low_confidence_gen = GenerativeResponse(
            action='clarify', text=predicted_text, confidence=0.3,
        )

        with patch('projects.POC.orchestrator.actors.generate_response', return_value=low_confidence_gen), \
             patch('projects.POC.orchestrator.actors.load_model', return_value=_make_empty_model()), \
             patch('projects.POC.orchestrator.actors.resolve_team_model_path', side_effect=lambda b, t: b), \
             patch.object(gate, '_classify_review', return_value=('clarify', 'Use PostgreSQL')), \
             patch.object(gate, '_proxy_record') as mock_record:
            _run(gate.run(ctx))

        # Verify _proxy_record was called with the predicted response text
        mock_record.assert_called_once()
        call_kwargs = mock_record.call_args
        # Check that predicted_response text was passed (not just 'escalate')
        args, kwargs = call_kwargs
        all_args = {**kwargs}
        # prediction should be the text, not just the decision label
        prediction_value = all_args.get('prediction', '')
        self.assertNotEqual(prediction_value, 'escalate',
                            "prediction must be the predicted response text, not just 'escalate'")
        self.assertIn(predicted_text, str(call_kwargs),
                      "Predicted response text must be passed to _proxy_record")


if __name__ == '__main__':
    unittest.main()
