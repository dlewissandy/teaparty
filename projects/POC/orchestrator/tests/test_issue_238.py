"""Tests for Issue #238: LLM conflict classifier failures must be observable.

Silent fallbacks in the LLM conflict classifier violate the "no silent
fallbacks" principle.  When _classify_conflict_llm() fails, the system must:

1. Log at WARNING level (not just DEBUG).
2. Track fallback count in _ActrRetrievalResult.
3. Append a degradation note to the conflict context so the proxy knows
   classification is operating in heuristic-only mode.
"""
from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

from projects.POC.orchestrator.proxy_memory import (
    ConflictClassification,
    MemoryChunk,
    format_conflict_context,
)


def _make_chunk(
    chunk_id: str = 'test-chunk',
    state: str = 'PLAN_ASSERT',
    task_type: str = 'security',
    outcome: str = 'approve',
    traces: list[int] | None = None,
    **kwargs,
) -> MemoryChunk:
    defaults = dict(
        id=chunk_id,
        type='gate_outcome',
        state=state,
        task_type=task_type,
        outcome=outcome,
        content='test interaction content',
        traces=traces or [1],
        embedding_model='test/test',
    )
    defaults.update(kwargs)
    return MemoryChunk(**defaults)


def _make_classification(
    cause: str = 'context_sensitivity',
    chunk_a_id: str = 'aaaa',
    chunk_b_id: str = 'bbbb',
) -> ConflictClassification:
    return ConflictClassification(
        chunk_a_id=chunk_a_id,
        chunk_b_id=chunk_b_id,
        cause=cause,
        action='Preserve both with scope annotations.',
    )


class TestLlmClassifierFallbackCount(unittest.TestCase):
    """_ActrRetrievalResult must carry llm_classifier_fallback_count."""

    def test_retrieval_result_has_fallback_count_field(self):
        from projects.POC.orchestrator.proxy_agent import _ActrRetrievalResult
        result = _ActrRetrievalResult(
            serialized='', chunk_ids=[], db_path='', interaction_counter=0,
        )
        self.assertEqual(result.llm_classifier_fallback_count, 0)

    def test_empty_retrieval_has_zero_fallback_count(self):
        from projects.POC.orchestrator.proxy_agent import _EMPTY_RETRIEVAL
        self.assertEqual(_EMPTY_RETRIEVAL.llm_classifier_fallback_count, 0)


class TestLlmClassifierWarningLog(unittest.TestCase):
    """LLM classifier failures must log at WARNING, not DEBUG."""

    def test_classify_conflict_llm_logs_warning_on_timeout(self):
        """When subprocess times out, a WARNING is logged."""
        import subprocess
        from projects.POC.orchestrator.proxy_agent import _classify_conflict_llm

        with patch('projects.POC.orchestrator.proxy_agent.subprocess.run',
                   side_effect=subprocess.TimeoutExpired('claude', 30)):
            with self.assertLogs('orchestrator.proxy_agent', level='WARNING') as cm:
                result = _classify_conflict_llm(
                    _make_chunk(chunk_id='a', content='chunk a'),
                    _make_chunk(chunk_id='b', content='chunk b'),
                )

        self.assertIsNone(result)
        self.assertTrue(any('LLM conflict classification' in msg for msg in cm.output))

    def test_classify_conflict_llm_logs_warning_on_nonzero_exit(self):
        """When subprocess returns non-zero, a WARNING is logged."""
        from unittest.mock import MagicMock
        from projects.POC.orchestrator.proxy_agent import _classify_conflict_llm

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ''
        with patch('projects.POC.orchestrator.proxy_agent.subprocess.run',
                   return_value=mock_result):
            with self.assertLogs('orchestrator.proxy_agent', level='WARNING') as cm:
                result = _classify_conflict_llm(
                    _make_chunk(chunk_id='a', content='chunk a'),
                    _make_chunk(chunk_id='b', content='chunk b'),
                )

        self.assertIsNone(result)
        self.assertTrue(any('LLM conflict classification' in msg for msg in cm.output))


class TestDegradationNoteInConflictContext(unittest.TestCase):
    """format_conflict_context must include a degradation note when fallbacks occurred."""

    def test_no_note_when_zero_fallbacks(self):
        classifications = [_make_classification()]
        text = format_conflict_context(classifications, llm_fallback_count=0)
        self.assertNotIn('heuristic', text.lower())
        self.assertNotIn('degraded', text.lower())

    def test_note_present_when_fallbacks_occurred(self):
        classifications = [_make_classification()]
        text = format_conflict_context(classifications, llm_fallback_count=2)
        self.assertIn('heuristic', text.lower())

    def test_backward_compat_no_fallback_count_arg(self):
        """format_conflict_context still works without llm_fallback_count (default 0)."""
        classifications = [_make_classification()]
        text = format_conflict_context(classifications)
        self.assertIn('Conflict 1', text)
        self.assertNotIn('heuristic', text.lower())


if __name__ == '__main__':
    unittest.main()
