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
12. Engine _check_context_budget injects /compact at turn boundary
13. Engine _check_context_budget publishes CONTEXT_WARNING at 70%
14. Engine _check_context_budget is a no-op below 70%
15. Engine _check_context_budget is a no-op without budget in data
16. Engine compact prompt includes scratch file pointer
17. CONTEXT_WARNING EventType exists
18. ActorResult carries context_budget in data from _interpret_output
19. Custom thresholds are configurable
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
from projects.POC.orchestrator.events import EventType


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


# ── Test 8: build_compact_prompt without scratch file ──────────��────────────

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


# ── Test 12–16: Engine _check_context_budget ────────────────────────────────

class TestEngineCheckContextBudget(unittest.TestCase):
    """Orchestrator._check_context_budget injects /compact at turn boundary."""

    def _make_orchestrator(self):
        """Create a minimal Orchestrator for testing _check_context_budget."""
        from projects.POC.orchestrator.engine import Orchestrator
        from projects.POC.orchestrator.events import EventBus
        from projects.POC.scripts.cfa_state import CfaState

        infra = tempfile.mkdtemp(prefix='test-260-')
        bus = EventBus()
        cfa = CfaState(state='TASK_IN_PROGRESS', phase='execution', actor='agent')

        class FakePhaseConfig:
            stall_timeout = 1800
            max_dispatch_retries = 5
            human_actor_states = frozenset()
            approval_gate_successors = {}
            valid_actions_by_state = {}
            phase_for_state = {}
            poc_root = ''
            def phase_spec(self, name): return None
            def project_config(self): return {}
            def get_project_claude_md(self): return ''

        orch = Orchestrator(
            cfa_state=cfa,
            phase_config=FakePhaseConfig(),
            event_bus=bus,
            input_provider=None,
            infra_dir=infra,
            project_workdir=infra,
            session_worktree=infra,
            proxy_model_path='',
            project_slug='test',
            poc_root='',
            task='implement feature X',
            session_id='test-session',
        )
        return orch, bus

    def _make_actor_result_with_budget(self, utilization_pct):
        """Create an ActorResult with a context budget at given utilization."""
        from projects.POC.orchestrator.actors import ActorResult
        budget = ContextBudget(context_window=200000)
        budget.update({'type': 'result', 'input_tokens': int(200000 * utilization_pct)})
        return ActorResult(action='auto-approve', data={'context_budget': budget}), budget

    def test_compact_threshold_injects_pending_intervention(self):
        """At 78%+, _check_context_budget sets _pending_intervention to /compact."""
        orch, bus = self._make_orchestrator()
        actor_result, budget = self._make_actor_result_with_budget(0.80)

        loop = asyncio.new_event_loop()
        loop.run_until_complete(orch._check_context_budget(actor_result, 'execution'))
        loop.close()

        self.assertIn('/compact', orch._pending_intervention)
        self.assertIn('TASK_IN_PROGRESS', orch._pending_intervention)
        self.assertFalse(budget.should_compact, 'Flag should be cleared after injection')

    def test_warning_threshold_publishes_event(self):
        """At 70%-77%, _check_context_budget publishes CONTEXT_WARNING."""
        orch, bus = self._make_orchestrator()
        actor_result, budget = self._make_actor_result_with_budget(0.72)

        events = []
        loop = asyncio.new_event_loop()

        async def run():
            bus.subscribe(lambda e: events.append(e))
            await orch._check_context_budget(actor_result, 'execution')

        loop.run_until_complete(run())
        loop.close()

        warning_events = [e for e in events if e.type == EventType.CONTEXT_WARNING]
        self.assertEqual(len(warning_events), 1)
        self.assertAlmostEqual(warning_events[0].data['utilization'], 0.72, places=2)
        self.assertFalse(budget.should_warn, 'Warning flag should be cleared')

    def test_below_warning_does_nothing(self):
        """Below 70%, no intervention or event is produced."""
        orch, bus = self._make_orchestrator()
        actor_result, budget = self._make_actor_result_with_budget(0.60)

        events = []
        loop = asyncio.new_event_loop()

        async def run():
            bus.subscribe(lambda e: events.append(e))
            await orch._check_context_budget(actor_result, 'execution')

        loop.run_until_complete(run())
        loop.close()

        self.assertEqual(orch._pending_intervention, '')
        self.assertEqual(len(events), 0)

    def test_no_budget_in_data_is_noop(self):
        """If actor result has no context_budget, nothing happens."""
        from projects.POC.orchestrator.actors import ActorResult
        orch, bus = self._make_orchestrator()
        actor_result = ActorResult(action='auto-approve', data={})

        loop = asyncio.new_event_loop()
        loop.run_until_complete(orch._check_context_budget(actor_result, 'execution'))
        loop.close()

        self.assertEqual(orch._pending_intervention, '')

    def test_compact_prompt_includes_scratch_path(self):
        """The injected compact prompt includes a .context/scratch.md pointer."""
        orch, bus = self._make_orchestrator()
        actor_result, _ = self._make_actor_result_with_budget(0.80)

        loop = asyncio.new_event_loop()
        loop.run_until_complete(orch._check_context_budget(actor_result, 'execution'))
        loop.close()

        self.assertIn('.context/scratch.md', orch._pending_intervention)


# ── Test 17: CONTEXT_WARNING EventType exists ────────────────────────────────

class TestContextWarningEventType(unittest.TestCase):
    """CONTEXT_WARNING must exist on EventType."""

    def test_event_type_exists(self):
        self.assertEqual(EventType.CONTEXT_WARNING.value, 'context_warning')


# ── Test 18: ActorResult carries context_budget in data ─────────────────────

class TestActorResultCarriesBudget(unittest.TestCase):
    """AgentRunner._interpret_output includes context_budget in ActorResult.data."""

    def test_interpret_output_includes_budget(self):
        from projects.POC.orchestrator.claude_runner import ClaudeResult
        from projects.POC.orchestrator.actors import AgentRunner

        budget = ContextBudget(context_window=200000)
        budget.update({'type': 'result', 'input_tokens': 150000})

        result = ClaudeResult(exit_code=0, session_id='sid-1', context_budget=budget)

        class FakePhaseSpec:
            artifact = None
        class FakeCtx:
            state = 'TASK_IN_PROGRESS'
            phase_spec = FakePhaseSpec()
            infra_dir = tempfile.mkdtemp()

        runner = AgentRunner()
        actor_result = runner._interpret_output(FakeCtx(), result)
        self.assertIs(actor_result.data['context_budget'], budget)


# ── Test 19: Custom thresholds ──────────────────────────────────────────────

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
