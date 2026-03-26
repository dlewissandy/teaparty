"""Tests for Issue #220: EMA decoupled from proxy confidence scoring.

The design doc (act-r-proxy-memory.md) says EMA should be a health monitor,
not a decision gate.  _calibrate_confidence() should return the agent's own
confidence when ACT-R memory depth is sufficient, and cap it when memory is
shallow — without blending EMA into the score via geometric mean.
"""
from __future__ import annotations

import sqlite3
import unittest
from unittest.mock import patch, MagicMock

from projects.POC.orchestrator.proxy_agent import _calibrate_confidence
from projects.POC.orchestrator.proxy_memory import (
    open_proxy_db,
    store_chunk,
)
from projects.POC.orchestrator.tests.test_issue_179 import _make_chunk


def _make_memory_db(
    num_chunks: int = 0,
    distinct_states: int = 1,
    distinct_task_types: int = 1,
) -> sqlite3.Connection:
    """Create an in-memory proxy DB with N chunks spread across states/types."""
    conn = open_proxy_db(':memory:')
    states = [f'STATE_{i}' for i in range(distinct_states)]
    types = [f'type_{i}' for i in range(distinct_task_types)]
    for i in range(num_chunks):
        store_chunk(conn, _make_chunk(
            chunk_id=f'c{i}',
            state=states[i % distinct_states],
            task_type=types[i % distinct_task_types],
            traces=[i + 1],
        ))
    return conn


def _make_mock_entry(total_count=10, ema=0.8):
    """Create a mock ConfidenceEntry."""
    entry = MagicMock()
    entry.total_count = total_count
    entry.ema_approval_rate = ema
    return entry


def _calibrate_with_mocks(
    agent_conf: float,
    *,
    laplace: float = 0.8,
    ema: float = 0.8,
    total_count: int = 10,
    memory_depth: int = 10,
) -> float:
    """Call _calibrate_confidence with mocked internals.

    Mocks both the approval_gate functions (for tests that verify EMA is not
    used) and the memory depth query (for cold-start tests).
    """
    mock_entry = _make_mock_entry(total_count=total_count, ema=ema)
    mock_model = MagicMock()
    mock_model.entries = {'PLAN_ASSERT::test': mock_entry}

    with patch('projects.POC.scripts.approval_gate.resolve_team_model_path',
               return_value='/tmp/test.json'), \
         patch('projects.POC.scripts.approval_gate.load_model',
               return_value=mock_model), \
         patch('projects.POC.scripts.approval_gate._entry_key',
               return_value='PLAN_ASSERT::test'), \
         patch('projects.POC.scripts.approval_gate._make_entry',
               return_value=mock_entry), \
         patch('projects.POC.scripts.approval_gate.compute_confidence_components',
               return_value=(laplace, ema)), \
         patch('projects.POC.orchestrator.proxy_agent._get_memory_depth',
               return_value=memory_depth):
        return _calibrate_confidence(
            agent_conf, 'PLAN_ASSERT', 'test', '/tmp/test.json', '',
            _random=0.99,
        )


class TestEMANotInConfidence(unittest.TestCase):
    """EMA must not influence the confidence score returned by _calibrate_confidence."""

    def test_high_ema_does_not_lift_low_agent_confidence(self):
        """Agent says 0.5, EMA says 0.95 — confidence should stay at 0.5,
        not be lifted to ~0.69 by the geometric mean."""
        result = _calibrate_with_mocks(0.5, ema=0.95, laplace=0.95)
        # Old code: sqrt(0.5 * 0.95) ≈ 0.69 — lifted.
        # New code: agent confidence passes through.
        self.assertAlmostEqual(result, 0.5, places=2,
                               msg='EMA should not lift agent confidence')

    def test_low_ema_does_not_drag_down_high_agent_confidence(self):
        """Agent says 0.9, EMA says 0.4 — confidence should stay at 0.9,
        not be dragged to ~0.60 by the geometric mean."""
        result = _calibrate_with_mocks(0.9, ema=0.4, laplace=0.4)
        # Old code: sqrt(0.9 * 0.4) ≈ 0.60 — dragged down.
        # New code: agent confidence passes through.
        self.assertAlmostEqual(result, 0.9, places=2,
                               msg='EMA should not drag down agent confidence')

    def test_varying_ema_does_not_change_result(self):
        """Changing EMA from 0.3 to 0.9 should produce the same confidence."""
        result_low = _calibrate_with_mocks(0.7, ema=0.3, laplace=0.3)
        result_high = _calibrate_with_mocks(0.7, ema=0.9, laplace=0.9)
        self.assertAlmostEqual(result_low, result_high, places=2,
                               msg='EMA value should not affect confidence')


class TestColdStartUsesMemoryDepth(unittest.TestCase):
    """Cold-start guard should be based on ACT-R memory depth, not EMA sample count.

    These tests verify the new behavior by checking that _calibrate_confidence
    accepts an optional memory_depth parameter (or queries the memory DB)
    to determine cold-start status.
    """

    def test_shallow_memory_caps_confidence(self):
        """Memory depth below threshold caps confidence at 0.5."""
        result = _calibrate_with_mocks(0.95, memory_depth=1)
        self.assertLessEqual(result, 0.5)

    def test_zero_memory_caps_confidence(self):
        """No memory at all caps confidence at 0.5."""
        result = _calibrate_with_mocks(0.95, memory_depth=0)
        self.assertLessEqual(result, 0.5)

    def test_high_ema_count_does_not_bypass_cold_start(self):
        """Even with 100+ EMA observations, shallow memory still caps.

        The old cold-start guard checked entry.total_count < COLD_START_THRESHOLD.
        The new code uses memory_depth instead.
        """
        result = _calibrate_with_mocks(
            0.9, ema=0.4, laplace=0.4, total_count=100, memory_depth=1,
        )
        self.assertLessEqual(result, 0.5,
                             msg='High EMA count should not bypass memory-based cold start')

    def test_deep_memory_passes_through(self):
        """Memory depth at threshold allows agent confidence through."""
        result = _calibrate_with_mocks(0.9, memory_depth=5)
        self.assertAlmostEqual(result, 0.9, places=2)


class TestAgentConfidencePassthrough(unittest.TestCase):
    """When past cold start, agent confidence is the decision signal."""

    def test_passthrough_at_various_levels(self):
        """Agent confidence value is returned unchanged (with enough history)."""
        for agent_conf in (0.1, 0.5, 0.7, 0.85, 0.95):
            with self.subTest(agent_conf=agent_conf):
                result = _calibrate_with_mocks(agent_conf)
                self.assertAlmostEqual(result, agent_conf, places=2,
                                       msg='Agent confidence should pass through')


if __name__ == '__main__':
    unittest.main()
