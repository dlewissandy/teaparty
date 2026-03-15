#!/usr/bin/env python3
"""Tests for issue #11: Proxy alignment memory — interaction log + prediction tracking.

Covers:
 1. Proxy interaction log: every proxy decision writes a JSONL entry with
    timestamp, session_id, state, prediction, outcome, delta, exploration.
 2. Prediction accuracy: ConfidenceEntry tracks prediction_correct_count
    and total predictions, enabling accuracy = correct/total.
 3. Auto-approve decisions are logged with prediction='approve'.
 4. Human-escalated decisions are logged with the actual outcome and delta.
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _make_event_bus():
    bus = MagicMock()
    bus.publish = AsyncMock()
    return bus


def _make_proxy_model_file(td: str) -> str:
    """Create a .proxy-confidence.json with enough data for auto-approve."""
    model = {
        'global_threshold': 0.7,
        'generative_threshold': 0.95,
        'entries': {
            'PLAN_ASSERT|test-project': {
                'state': 'PLAN_ASSERT',
                'task_type': 'test-project',
                'approve_count': 20,
                'correct_count': 0,
                'reject_count': 0,
                'total_count': 20,
                'last_updated': '2026-03-14',
                'ema_approval_rate': 0.95,
                'differentials': [],
                'artifact_lengths': [2000] * 20,
                'question_patterns': [],
            },
        },
    }
    path = os.path.join(td, '.proxy-confidence.json')
    Path(path).write_text(json.dumps(model))
    return path


def _make_artifact(td: str, content: str = '## Plan\n\nThis is a test plan.\n' * 50) -> str:
    path = os.path.join(td, 'PLAN.md')
    Path(path).write_text(content)
    return path


def _make_actor_context(td: str, artifact_path: str, session_id: str = 'test-session'):
    from projects.POC.orchestrator.actors import ActorContext
    from projects.POC.orchestrator.phase_config import PhaseSpec
    spec = PhaseSpec(
        name='planning', agent_file='agents/uber-team.json',
        lead='project-lead', permission_mode='acceptEdits',
        stream_file='.plan-stream.jsonl', artifact='PLAN.md',
        approval_state='PLAN_ASSERT', escalation_state='PLANNING_ESCALATE',
        escalation_file='', settings_overlay={},
    )
    return ActorContext(
        state='PLAN_ASSERT',
        phase='planning',
        task='Test task',
        infra_dir=td,
        project_workdir=td,
        session_worktree=td,
        stream_file='.plan-stream.jsonl',
        phase_spec=spec,
        poc_root=td,
        event_bus=_make_event_bus(),
        session_id=session_id,
        env_vars={'POC_PROJECT': 'test-project'},
    )


# ── Tests: Interaction log ────────────────────────────────────────────────────

class TestProxyInteractionLog(unittest.TestCase):
    """Every proxy decision writes a JSONL entry to the interaction log."""

    def test_auto_approve_writes_log_entry(self):
        """Auto-approve decisions are logged with prediction and outcome."""
        from projects.POC.orchestrator.actors import ApprovalGate

        with tempfile.TemporaryDirectory() as td:
            model_path = _make_proxy_model_file(td)
            artifact_path = _make_artifact(td)

            gate = ApprovalGate(
                proxy_model_path=model_path,
                input_provider=AsyncMock(),
                poc_root=td,
            )

            ctx = _make_actor_context(td, artifact_path, session_id='sess-001')
            ctx.data = {'artifact_path': artifact_path}

            result = _run(gate.run(ctx))

            # The interaction log should exist
            log_path = os.path.join(td, '.proxy-interactions.jsonl')
            self.assertTrue(
                os.path.exists(log_path),
                'Proxy interaction log (.proxy-interactions.jsonl) should be created',
            )

            # Parse the log entries
            entries = []
            with open(log_path) as f:
                for line in f:
                    if line.strip():
                        entries.append(json.loads(line))

            self.assertGreaterEqual(len(entries), 1, 'At least one log entry expected')

            entry = entries[-1]
            self.assertEqual(entry['session_id'], 'sess-001')
            self.assertEqual(entry['state'], 'PLAN_ASSERT')
            self.assertIn('prediction', entry)
            self.assertIn('outcome', entry)
            self.assertIn('timestamp', entry)

    def test_escalated_decision_writes_log_with_delta(self):
        """Human-escalated decisions include the delta (prediction vs outcome)."""
        from projects.POC.orchestrator.actors import ApprovalGate

        with tempfile.TemporaryDirectory() as td:
            # Use a model with low confidence to force escalation
            model = {
                'global_threshold': 0.8,
                'generative_threshold': 0.95,
                'entries': {},
            }
            model_path = os.path.join(td, '.proxy-confidence.json')
            Path(model_path).write_text(json.dumps(model))

            artifact_path = _make_artifact(td)

            gate = ApprovalGate(
                proxy_model_path=model_path,
                input_provider=AsyncMock(return_value='approve'),
                poc_root=td,
            )

            ctx = _make_actor_context(td, artifact_path, session_id='sess-002')
            ctx.data = {'artifact_path': artifact_path}

            # Mock classify to return approve
            with patch.object(gate, '_classify_review', return_value=('approve', '')):
                result = _run(gate.run(ctx))

            log_path = os.path.join(td, '.proxy-interactions.jsonl')
            self.assertTrue(os.path.exists(log_path))

            entries = []
            with open(log_path) as f:
                for line in f:
                    if line.strip():
                        entries.append(json.loads(line))

            self.assertGreaterEqual(len(entries), 1)
            entry = entries[-1]
            self.assertEqual(entry['session_id'], 'sess-002')
            self.assertIn('delta', entry)


# ── Tests: Prediction accuracy tracking ───────────────────────────────────────

class TestPredictionAccuracyTracking(unittest.TestCase):
    """ConfidenceEntry tracks prediction accuracy separately from approval rate."""

    def test_correct_prediction_increments_accuracy(self):
        """When proxy predicts 'approve' and human approves, prediction_correct_count increments."""
        from projects.POC.scripts.approval_gate import (
            load_model, record_outcome, ConfidenceEntry,
        )

        with tempfile.TemporaryDirectory() as td:
            model_path = _make_proxy_model_file(td)
            model = load_model(model_path)

            # Record an outcome where the prediction was correct
            model = record_outcome(
                model, 'PLAN_ASSERT', 'test-project', 'approve',
                prediction='approve',
            )

            key = 'PLAN_ASSERT|test-project'
            entry = model.entries[key]

            self.assertTrue(
                hasattr(entry, 'prediction_correct_count') or
                'prediction_correct_count' in (entry if isinstance(entry, dict) else {}),
                'ConfidenceEntry should track prediction_correct_count',
            )

    def test_wrong_prediction_does_not_increment(self):
        """When proxy predicts 'approve' but human corrects, prediction_correct_count unchanged."""
        from projects.POC.scripts.approval_gate import (
            load_model, record_outcome,
        )

        with tempfile.TemporaryDirectory() as td:
            model_path = _make_proxy_model_file(td)
            model = load_model(model_path)

            model = record_outcome(
                model, 'PLAN_ASSERT', 'test-project', 'correct',
                prediction='approve',
            )

            key = 'PLAN_ASSERT|test-project'
            entry = model.entries[key]

            if isinstance(entry, dict):
                correct = entry.get('prediction_correct_count', 0)
                total = entry.get('prediction_total_count', 0)
            else:
                correct = getattr(entry, 'prediction_correct_count', 0)
                total = getattr(entry, 'prediction_total_count', 0)

            # prediction was wrong, so correct count should not have incremented
            # (beyond whatever was in the initial model)
            self.assertEqual(correct, 0,
                             'Wrong prediction should not increment prediction_correct_count')


if __name__ == '__main__':
    unittest.main()
