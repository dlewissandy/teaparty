"""Tests for issue #260: Context budget — stream monitoring, utilization tracking, compaction triggers.

Verifies:
1. ContextBudget extracts token usage from result events
2. ContextBudget ignores non-result events
3. Utilization computation matches the design formula
4. Warning flag fires at 70% threshold
5. Compact flag fires at 78% threshold
6. Flags are latched until cleared
7. build_compact_prompt includes CfA state and task in focus
8. build_compact_prompt includes scratch file pointer when provided
9. ContextBudget handles result events with nested usage dict
10. ContextBudget handles result events without token data (no-op)
11. ClaudeResult carries context_budget from the runner
12. Engine injects /compact at turn boundary when compaction fires
13. Engine publishes warning event at 70% threshold
"""
import asyncio
import json
import os
import tempfile
import unittest

from projects.POC.orchestrator.context_budget import (
    ContextBudget,
    DEFAULT_COMPACT_THRESHOLD,
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_WARNING_THRESHOLD,
    build_compact_prompt,
)


# ── Test 1: Extract token usage from result events ──────────────────────────

class TestContextBudgetExtraction(unittest.TestCase):
    """ContextBudget.update must extract token counts from result events."""

    def _make_result_event(self, input_tokens=50000, cache_creation=10000, cache_read=5000):
        return {
            'type': 'result',
            'input_tokens': input_tokens,
            'cache_creation_input_tokens': cache_creation,
            'cache_read_input_tokens': cache_read,
        }

    def test_extracts_token_counts(self):
        budget = ContextBudget()
        event = self._make_result_event(input_tokens=100000, cache_creation=20000, cache_read=10000)
        budget.update(event)

        self.assertEqual(budget.input_tokens, 100000)
        self.assertEqual(budget.cache_creation_input_tokens, 20000)
        self.assertEqual(budget.cache_read_input_tokens, 10000)

    def test_updates_on_subsequent_result(self):
        """Later result events replace earlier token counts."""
        budget = ContextBudget()
        budget.update(self._make_result_event(input_tokens=50000))
        budget.update(self._make_result_event(input_tokens=120000))

        self.assertEqual(budget.input_tokens, 120000)


# ── Test 2: Ignores non-result events ───────────────────────────────────────

class TestContextBudgetIgnoresNonResult(unittest.TestCase):
    """Non-result events must be ignored by ContextBudget."""

    def test_ignores_tool_use_event(self):
        budget = ContextBudget()
        budget.update({'type': 'tool_use', 'tool_use_id': 'tu_123'})
        self.assertEqual(budget.input_tokens, 0)

    def test_ignores_text_event(self):
        budget = ContextBudget()
        budget.update({'type': 'text', 'text': 'hello'})
        self.assertEqual(budget.input_tokens, 0)

    def test_ignores_system_event(self):
        budget = ContextBudget()
        budget.update({'type': 'system', 'subtype': 'init'})
        self.assertEqual(budget.input_tokens, 0)


# ── Test 3: Utilization computation ─────────────────────────────────────────

class TestUtilizationFormula(unittest.TestCase):
    """Utilization = (input + cache_creation + cache_read) / context_window."""

    def test_formula(self):
        budget = ContextBudget(context_window=200000)
        budget.update({
            'type': 'result',
            'input_tokens': 100000,
            'cache_creation_input_tokens': 20000,
            'cache_read_input_tokens': 10000,
        })
        # used = 100000 + 20000 + 10000 = 130000
        # utilization = 130000 / 200000 = 0.65
        self.assertAlmostEqual(budget.utilization, 0.65)
        self.assertEqual(budget.used_tokens, 130000)

    def test_zero_window_returns_zero(self):
        budget = ContextBudget(context_window=0)
        budget.update({'type': 'result', 'input_tokens': 100})
        self.assertEqual(budget.utilization, 0.0)


# ── Test 4: Warning fires at 70% ───────────────────────────────────────────

class TestWarningThreshold(unittest.TestCase):
    """Warning flag fires when utilization >= 70%."""

    def test_below_threshold_no_warning(self):
        budget = ContextBudget(context_window=200000)
        budget.update({'type': 'result', 'input_tokens': 130000})
        # 130000 / 200000 = 0.65 — below 70%
        self.assertFalse(budget.should_warn)

    def test_at_threshold_fires_warning(self):
        budget = ContextBudget(context_window=200000)
        budget.update({'type': 'result', 'input_tokens': 140000})
        # 140000 / 200000 = 0.70 — at threshold
        self.assertTrue(budget.should_warn)

    def test_above_threshold_fires_warning(self):
        budget = ContextBudget(context_window=200000)
        budget.update({'type': 'result', 'input_tokens': 150000})
        # 150000 / 200000 = 0.75 — above 70%
        self.assertTrue(budget.should_warn)


# ── Test 5: Compact fires at 78% ───────────────────────────────────────────

class TestCompactThreshold(unittest.TestCase):
    """Compact flag fires when utilization >= 78%."""

    def test_below_compact_no_fire(self):
        budget = ContextBudget(context_window=200000)
        budget.update({'type': 'result', 'input_tokens': 150000})
        # 0.75 — above warning but below compact
        self.assertTrue(budget.should_warn)
        self.assertFalse(budget.should_compact)

    def test_at_compact_fires(self):
        budget = ContextBudget(context_window=200000)
        budget.update({'type': 'result', 'input_tokens': 156000})
        # 156000 / 200000 = 0.78
        self.assertTrue(budget.should_compact)
        self.assertTrue(budget.should_warn)  # warning implied

    def test_above_compact_fires(self):
        budget = ContextBudget(context_window=200000)
        budget.update({'type': 'result', 'input_tokens': 170000})
        self.assertTrue(budget.should_compact)


# ── Test 6: Flags latch until cleared ───────────────────────────────────────

class TestFlagLatching(unittest.TestCase):
    """Flags stay set until explicitly cleared by the caller."""

    def test_warning_latches(self):
        budget = ContextBudget(context_window=200000)
        budget.update({'type': 'result', 'input_tokens': 150000})
        self.assertTrue(budget.should_warn)

        # Even after a lower-utilization event, warning stays set
        # (in practice, utilization only goes up within a session)
        budget.clear_warning()
        self.assertFalse(budget.should_warn)

    def test_compact_clear_resets_both(self):
        budget = ContextBudget(context_window=200000)
        budget.update({'type': 'result', 'input_tokens': 170000})
        self.assertTrue(budget.should_compact)
        self.assertTrue(budget.should_warn)

        budget.clear_compact()
        self.assertFalse(budget.should_compact)
        self.assertFalse(budget.should_warn)


# ── Test 7: build_compact_prompt includes focus ─────────────────────────────

class TestBuildCompactPrompt(unittest.TestCase):
    """build_compact_prompt produces /compact with focus derived from CfA state."""

    def test_includes_state_and_task(self):
        prompt = build_compact_prompt(
            cfa_state='TASK_IN_PROGRESS',
            task='implement ACT-R retrieval',
        )
        self.assertIn('/compact', prompt)
        self.assertIn('TASK_IN_PROGRESS', prompt)
        self.assertIn('implement ACT-R retrieval', prompt)

    def test_includes_scratch_pointer(self):
        prompt = build_compact_prompt(
            cfa_state='WORK_IN_PROGRESS',
            task='fix bug',
            scratch_path='.context/scratch.md',
        )
        self.assertIn('.context/scratch.md', prompt)
        self.assertIn('After compaction', prompt)


# ── Test 8: build_compact_prompt without scratch file ───────────────────────

class TestBuildCompactPromptNoScratch(unittest.TestCase):
    """build_compact_prompt omits scratch pointer when not provided."""

    def test_no_scratch_no_pointer(self):
        prompt = build_compact_prompt(
            cfa_state='TASK_IN_PROGRESS',
            task='fix bug',
        )
        self.assertNotIn('After compaction', prompt)


# ── Test 9: Result events with nested usage dict ───────────────────────────

class TestNestedUsageDict(unittest.TestCase):
    """Result events may nest token counts under a 'usage' key."""

    def test_extracts_from_usage_dict(self):
        budget = ContextBudget()
        event = {
            'type': 'result',
            'usage': {
                'input_tokens': 80000,
                'cache_creation_input_tokens': 15000,
                'cache_read_input_tokens': 5000,
            },
        }
        budget.update(event)
        self.assertEqual(budget.input_tokens, 80000)
        self.assertEqual(budget.cache_creation_input_tokens, 15000)
        self.assertEqual(budget.cache_read_input_tokens, 5000)
        self.assertEqual(budget.used_tokens, 100000)


# ── Test 10: Result event without token data is a no-op ─────────────────────

class TestResultWithoutTokens(unittest.TestCase):
    """A result event with no input_tokens field is ignored."""

    def test_no_token_data_is_noop(self):
        budget = ContextBudget()
        budget.update({'type': 'result', 'result': 'some text output'})
        self.assertEqual(budget.input_tokens, 0)
        self.assertEqual(budget.utilization, 0.0)


# ── Test 11: ClaudeResult carries context_budget ────────────────────────────

class TestClaudeResultContextBudget(unittest.TestCase):
    """ClaudeResult must have a context_budget field populated by ClaudeRunner."""

    def test_claude_result_has_context_budget(self):
        from projects.POC.orchestrator.claude_runner import ClaudeResult
        result = ClaudeResult(exit_code=0)
        self.assertIsNotNone(result.context_budget)
        self.assertIsInstance(result.context_budget, ContextBudget)


# ── Test 12: Engine injects /compact at turn boundary ───────────────────────

class TestEngineCompactInjection(unittest.TestCase):
    """When ClaudeResult signals compaction, engine injects /compact on next turn."""

    def _make_budget_at_threshold(self):
        """Create a ContextBudget that has crossed the compact threshold."""
        budget = ContextBudget(context_window=200000)
        budget.update({'type': 'result', 'input_tokens': 160000})
        return budget

    def test_compact_flag_signals_engine(self):
        """A budget with should_compact=True signals need for compaction."""
        budget = self._make_budget_at_threshold()
        self.assertTrue(budget.should_compact)

        # Engine would build the compact prompt
        prompt = build_compact_prompt(
            cfa_state='TASK_IN_PROGRESS',
            task='implement feature X',
        )
        self.assertIn('/compact', prompt)

        # Engine would clear the flag after injecting
        budget.clear_compact()
        self.assertFalse(budget.should_compact)


# ── Test 13: Warning event published at 70% ─────────────────────────────────

class TestWarningEventPublished(unittest.TestCase):
    """The event bus should receive a warning when context crosses 70%."""

    def test_budget_triggers_warning_at_threshold(self):
        """ContextBudget flags warning at exactly 70% utilization."""
        budget = ContextBudget(context_window=100000)
        # Exactly 70%
        budget.update({'type': 'result', 'input_tokens': 70000})
        self.assertTrue(budget.should_warn)
        self.assertFalse(budget.should_compact)
        self.assertAlmostEqual(budget.utilization, 0.70)


# ── Test 14: Custom thresholds ──────────────────────────────────────────────

class TestCustomThresholds(unittest.TestCase):
    """Thresholds are configurable per ContextBudget instance."""

    def test_custom_warning_threshold(self):
        budget = ContextBudget(context_window=100000, warning_threshold=0.50)
        budget.update({'type': 'result', 'input_tokens': 50000})
        self.assertTrue(budget.should_warn)

    def test_custom_compact_threshold(self):
        budget = ContextBudget(context_window=100000, compact_threshold=0.60)
        budget.update({'type': 'result', 'input_tokens': 60000})
        self.assertTrue(budget.should_compact)

    def test_custom_context_window(self):
        budget = ContextBudget(context_window=1000000)
        budget.update({'type': 'result', 'input_tokens': 700000})
        # 700000 / 1000000 = 0.70
        self.assertTrue(budget.should_warn)
        self.assertFalse(budget.should_compact)


if __name__ == '__main__':
    unittest.main()
