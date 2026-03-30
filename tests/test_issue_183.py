#!/usr/bin/env python3
"""Tests for issue #183: failure_dialog() uses string matching instead of LLM classifier.

Both ApprovalGate.failure_dialog() and Orchestrator._failure_dialog() classify
human responses using substring matching ("backtrack" in response, "withdraw"
in response).  classify_review.py already provides a FAILURE_PROMPT with
nuanced LLM classification that handles natural language.

These tests verify that:
1. Natural language responses (not containing exact keywords) are classified
   correctly by routing through the LLM classifier.
2. The classifier is actually called (not bypassed by string matching).
3. Fallback behavior maps correctly when the classifier returns __fallback__.
"""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.actors import ApprovalGate
from orchestrator.engine import Orchestrator
from orchestrator.events import EventBus, EventType


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    """Run a coroutine synchronously for testing."""
    return asyncio.run(coro)


def _make_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


def _make_approval_gate(input_response: str) -> ApprovalGate:
    """Build a minimal ApprovalGate with a canned input_provider."""
    gate = ApprovalGate.__new__(ApprovalGate)
    gate.input_provider = AsyncMock(return_value=input_response)
    return gate


def _make_actor_context(event_bus=None) -> MagicMock:
    ctx = MagicMock()
    ctx.event_bus = event_bus or _make_event_bus()
    ctx.session_id = 'test-session'
    return ctx


def _make_orchestrator(input_response: str) -> Orchestrator:
    """Build a minimal Orchestrator with a canned input_provider."""
    orch = Orchestrator.__new__(Orchestrator)
    orch.event_bus = _make_event_bus()
    orch.session_id = 'test-session'
    orch.input_provider = AsyncMock(return_value=input_response)
    return orch


# ── ApprovalGate.failure_dialog tests ─────────────────────────────────────────

class TestApprovalGateFailureDialogClassifier(unittest.TestCase):
    """Verify ApprovalGate.failure_dialog uses the LLM classifier."""

    def test_natural_language_backtrack_is_classified(self):
        """'let's rethink the approach' should classify as backtrack,
        but contains neither 'backtrack' nor 'withdraw' as substrings."""
        gate = _make_approval_gate("let's rethink the approach")
        ctx = _make_actor_context()

        with patch.object(gate, '_classify_review', return_value=('backtrack', '')) as mock_cls:
            result = _run(gate.failure_dialog('stall_timeout', ctx))

        mock_cls.assert_called_once()
        self.assertEqual(result, 'backtrack')

    def test_natural_language_withdraw_is_classified(self):
        """'forget it, just cancel everything' should classify as withdraw."""
        gate = _make_approval_gate("forget it, just cancel everything")
        ctx = _make_actor_context()

        with patch.object(gate, '_classify_review', return_value=('withdraw', '')) as mock_cls:
            result = _run(gate.failure_dialog('nonzero_exit', ctx))

        mock_cls.assert_called_once()
        self.assertEqual(result, 'withdraw')

    def test_natural_language_retry_is_classified(self):
        """'yeah give it another shot' should classify as retry."""
        gate = _make_approval_gate("yeah give it another shot")
        ctx = _make_actor_context()

        with patch.object(gate, '_classify_review', return_value=('retry', '')) as mock_cls:
            result = _run(gate.failure_dialog('nonzero_exit', ctx))

        mock_cls.assert_called_once()
        self.assertEqual(result, 'retry')

    def test_classifier_fallback_defaults_to_retry(self):
        """If the classifier returns __fallback__, failure_dialog defaults to retry."""
        gate = _make_approval_gate("I dunno")
        ctx = _make_actor_context()

        with patch.object(gate, '_classify_review', return_value=('__fallback__', '')):
            result = _run(gate.failure_dialog('nonzero_exit', ctx))

        self.assertEqual(result, 'retry')

    def test_classifier_escalate_defaults_to_retry(self):
        """If the classifier returns 'escalate', failure_dialog defaults to retry
        (escalate is not one of the three valid return values)."""
        gate = _make_approval_gate("let me look into it")
        ctx = _make_actor_context()

        with patch.object(gate, '_classify_review', return_value=('escalate', '')):
            result = _run(gate.failure_dialog('nonzero_exit', ctx))

        self.assertEqual(result, 'retry')

    def test_classifier_receives_failure_state(self):
        """The classifier must be called with 'FAILURE' as the state."""
        gate = _make_approval_gate("retry")
        ctx = _make_actor_context()

        with patch.object(gate, '_classify_review', return_value=('retry', '')) as mock_cls:
            _run(gate.failure_dialog('nonzero_exit', ctx))

        args = mock_cls.call_args
        self.assertEqual(args[0][0], 'FAILURE')


# ── Orchestrator._failure_dialog tests ────────────────────────────────────────

class TestOrchestratorFailureDialogClassifier(unittest.TestCase):
    """Verify Orchestrator._failure_dialog uses the LLM classifier."""

    @patch('scripts.classify_review.classify')
    def test_natural_language_backtrack(self, mock_classify):
        """Natural language backtrack routed through classifier."""
        mock_classify.return_value = "backtrack\t"
        orch = _make_orchestrator("the plan is wrong, try a different way")

        result = _run(orch._failure_dialog('nonzero_exit'))

        mock_classify.assert_called_once()
        self.assertEqual(result, 'backtrack')

    @patch('scripts.classify_review.classify')
    def test_natural_language_withdraw(self, mock_classify):
        """Natural language withdraw routed through classifier."""
        mock_classify.return_value = "withdraw\t"
        orch = _make_orchestrator("just stop, forget about it")

        result = _run(orch._failure_dialog('stall_timeout'))

        mock_classify.assert_called_once()
        self.assertEqual(result, 'withdraw')

    @patch('scripts.classify_review.classify')
    def test_classifier_fallback_defaults_to_retry(self, mock_classify):
        """Classifier __fallback__ maps to retry."""
        mock_classify.return_value = "__fallback__\t"
        orch = _make_orchestrator("hmm not sure")

        result = _run(orch._failure_dialog('nonzero_exit'))

        self.assertEqual(result, 'retry')

    @patch('scripts.classify_review.classify')
    def test_classifier_called_with_failure_state(self, mock_classify):
        """The classifier must be called with 'FAILURE' as the state."""
        mock_classify.return_value = "retry\t"
        orch = _make_orchestrator("try again")

        _run(orch._failure_dialog('nonzero_exit'))

        args = mock_classify.call_args
        self.assertEqual(args[0][0], 'FAILURE')


if __name__ == '__main__':
    unittest.main()
