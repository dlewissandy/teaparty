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

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.approval_gate import (
    ConfidenceEntry,
    ConfidenceModel,
    GenerativeResponse,
    generate_response,
    record_outcome,
    load_model,
    save_model,
)
from orchestrator.actors import (
    ActorContext,
    ApprovalGate,
)
from orchestrator.events import EventBus
from orchestrator.phase_config import PhaseSpec


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



# TestEscalationFlowStoresPrediction removed — file-based escalation flow
# replaced by AskQuestion MCP tool. Differential recording is now tested
# in test_mcp_ask_question.py.


if __name__ == '__main__':
    unittest.main()
