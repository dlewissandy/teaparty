#!/usr/bin/env python3
"""Tests for human_proxy.py — content-aware confidence proxy with conversation-learning."""
import dataclasses
import json
import os
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))
from human_proxy import (
    COLD_START_THRESHOLD,
    MAX_ARTIFACT_CHARS,
    MAX_ARTIFACT_LENGTHS_PER_ENTRY,
    MAX_CONVERSATIONS_PER_ENTRY,
    ConfidenceEntry,
    ConfidenceModel,
    ProxyDecision,
    _check_content_novelty,
    _extract_tokens,
    _read_artifact,
    load_model,
    make_model,
    record_outcome,
    save_model,
    should_escalate,
)


# ── Test helpers ──────────────────────────────────────────────────────────────

def _make_model(global_threshold=0.8, generative_threshold=0.95):
    return make_model(global_threshold=global_threshold,
                      generative_threshold=generative_threshold)


def _make_entry(state='PLAN_ASSERT', task_type='proj',
                approve_count=0, total_count=0):
    """Create a ConfidenceEntry with given counts; last_updated = today."""
    correct_count = total_count - approve_count
    return ConfidenceEntry(
        state=state,
        task_type=task_type,
        approve_count=approve_count,
        correct_count=correct_count,
        reject_count=0,
        total_count=total_count,
        last_updated=date.today().isoformat(),
    )


def _model_with_entry(entry: ConfidenceEntry) -> ConfidenceModel:
    """Wrap a ConfidenceEntry in a ConfidenceModel."""
    key = f"{entry.state}|{entry.task_type}"
    return ConfidenceModel(
        entries={key: dataclasses.asdict(entry)},
        global_threshold=0.8,
        generative_threshold=0.95,
    )


class DeterministicProxyTestCase(unittest.TestCase):
    """Base class that seeds random so exploration doesn't interfere."""
    def setUp(self):
        import random
        random.seed(42)


# ── TestContentAwareness ──────────────────────────────────────────────────────

class TestContentAwareness(DeterministicProxyTestCase):

    def test_correction_patterns_trigger_escalation(self):
        """Keywords from past correction differentials found in artifact → escalate."""
        model = _make_model()
        for _ in range(COLD_START_THRESHOLD):
            model = record_outcome(
                model, 'PLAN_ASSERT', 'proj', 'correct',
                differential_summary='missing database rollback handling'
            )
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("Plan: delete the database without a rollback strategy.")
            artifact_path = f.name
        try:
            decision = should_escalate(model, 'PLAN_ASSERT', 'proj',
                                       artifact_path=artifact_path)
            self.assertEqual(decision.action, 'escalate')
            self.assertIn('Content novelty', decision.reasoning)
        finally:
            os.unlink(artifact_path)

    def test_unusually_short_artifact_triggers_escalation(self):
        """Artifact much shorter than historical mean → escalate."""
        entry = _make_entry(state='PLAN_ASSERT', task_type='proj',
                            approve_count=10, total_count=10)
        entry_dict = dataclasses.asdict(entry)
        entry_dict['artifact_lengths'] = [500] * 10
        entry_dict['last_approved_length'] = 500
        model = ConfidenceModel(
            entries={'PLAN_ASSERT|proj': entry_dict},
            global_threshold=0.8,
            generative_threshold=0.95,
        )
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("ok")   # 2 chars — well below 50% of 500
            artifact_path = f.name
        try:
            decision = should_escalate(model, 'PLAN_ASSERT', 'proj',
                                       artifact_path=artifact_path)
            self.assertEqual(decision.action, 'escalate')
            self.assertIn('Content novelty', decision.reasoning)
        finally:
            os.unlink(artifact_path)

    def test_missing_artifact_path_degrades_gracefully(self):
        """Empty artifact_path → proxy falls back to stats-only, no exception."""
        entry = _make_entry(approve_count=10, total_count=10)
        model = _model_with_entry(entry)
        decision = should_escalate(model, 'PLAN_ASSERT', 'proj', artifact_path='')
        self.assertEqual(decision.action, 'auto-approve')

    def test_unreadable_artifact_degrades_gracefully(self):
        """OSError when reading artifact → proxy falls back to stats-only."""
        entry = _make_entry(approve_count=10, total_count=10)
        model = _model_with_entry(entry)
        decision = should_escalate(model, 'PLAN_ASSERT', 'proj',
                                   artifact_path='/nonexistent/no-such-file.md')
        self.assertEqual(decision.action, 'auto-approve')

    def test_content_check_does_not_fire_during_cold_start(self):
        """Cold start takes priority — content checks do not run before COLD_START_THRESHOLD."""
        model = _make_model()
        model = record_outcome(
            model, 'PLAN_ASSERT', 'proj', 'correct',
            differential_summary='missing error handling code'
        )
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("No error handling here.")
            artifact_path = f.name
        try:
            decision = should_escalate(model, 'PLAN_ASSERT', 'proj',
                                       artifact_path=artifact_path)
            self.assertEqual(decision.action, 'escalate')
            self.assertIn('Cold start', decision.reasoning)
            self.assertNotIn('Content novelty', decision.reasoning)
        finally:
            os.unlink(artifact_path)

    def test_content_check_fires_independently_of_confidence_level(self):
        """Content check fires regardless of where confidence sits — not gated on threshold."""
        model = _make_model()
        for _ in range(COLD_START_THRESHOLD):
            model = record_outcome(
                model, 'PLAN_ASSERT', 'proj', 'correct',
                differential_summary='always include rollback plan for database changes'
            )
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("Plan: drop the database tables and rollback nothing.")
            artifact_path = f.name
        try:
            decision = should_escalate(model, 'PLAN_ASSERT', 'proj',
                                       artifact_path=artifact_path)
            self.assertEqual(decision.action, 'escalate')
            self.assertIn('Content novelty', decision.reasoning)
        finally:
            os.unlink(artifact_path)


# ── TestConversationLearning ──────────────────────────────────────────────────

class TestConversationLearning(DeterministicProxyTestCase):

    def test_conversation_text_contributes_to_pattern_matching(self):
        """Conversation text stored in entry feeds correction pattern matching."""
        model = _make_model()
        for _ in range(COLD_START_THRESHOLD):
            model = record_outcome(
                model, 'PLAN_ASSERT', 'proj', 'correct',
                conversation_text='Human: where is the database rollback? Agent: not included. Human: that is wrong'
            )
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("Plan: update the database without rollback.")
            artifact_path = f.name
        try:
            decision = should_escalate(model, 'PLAN_ASSERT', 'proj',
                                       artifact_path=artifact_path)
            self.assertEqual(decision.action, 'escalate')
            self.assertIn('Content novelty', decision.reasoning)
        finally:
            os.unlink(artifact_path)

    def test_conversation_text_co_equal_with_differentials(self):
        """Conversations are co-equal with differentials — pattern matching fires even with no differential_summary."""
        model = _make_model()
        for _ in range(COLD_START_THRESHOLD):
            model = record_outcome(
                model, 'PLAN_ASSERT', 'proj', 'correct',
                differential_summary='',
                conversation_text='missing error handling in the rollback section'
            )
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("This plan has no error handling.")
            artifact_path = f.name
        try:
            decision = should_escalate(model, 'PLAN_ASSERT', 'proj',
                                       artifact_path=artifact_path)
            self.assertEqual(decision.action, 'escalate')
            self.assertIn('Content novelty', decision.reasoning)
        finally:
            os.unlink(artifact_path)

    def test_empty_conversation_text_degrades_gracefully(self):
        """Empty conversation_text → no entry added to conversations list."""
        model = _make_model()
        model = record_outcome(
            model, 'PLAN_ASSERT', 'proj', 'correct',
            conversation_text=''
        )
        key = 'PLAN_ASSERT|proj'
        entry_dict = model.entries.get(key, {})
        self.assertEqual(entry_dict.get('conversations', []), [])

    def test_old_model_without_conversations_field_loads_correctly(self):
        """Old model JSON without 'conversations' field loads without error."""
        old_model_data = {
            'global_threshold': 0.8,
            'generative_threshold': 0.95,
            'entries': {
                'PLAN_ASSERT|test': {
                    'state': 'PLAN_ASSERT',
                    'task_type': 'test',
                    'approve_count': 10,
                    'correct_count': 0,
                    'reject_count': 0,
                    'total_count': 10,
                    'last_updated': date.today().isoformat(),
                    'differentials': [],
                    'ema_approval_rate': 0.9,
                    # deliberately omit: artifact_lengths, last_approved_length, conversations
                }
            }
        }
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(old_model_data, f)
            model_path = f.name
        try:
            model = load_model(model_path)
            # Should not raise; result should be a valid decision
            decision = should_escalate(model, 'PLAN_ASSERT', 'test')
            self.assertIn(decision.action, ('auto-approve', 'escalate'))
        finally:
            os.unlink(model_path)


if __name__ == '__main__':
    unittest.main()
