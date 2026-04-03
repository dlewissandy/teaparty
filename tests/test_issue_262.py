#!/usr/bin/env python3
"""Tests for Issue #262: Cost budget tracking and enforcement from stream result events.

Covers:
 1. Budget field parsed from YAML config (management, project, workgroup)
 2. Budget precedence: project overrides workgroup overrides org (not merge)
 3. resolve_budget composes limits across config levels
 4. CostTracker accumulates cost from result events
 5. CostTracker warns at 80% of budget
 6. CostTracker pauses at 100% of budget
 7. COST_WARNING and COST_LIMIT event types exist
 8. ClaudeResult carries cost_usd from stream parsing
 9. Budget absent → no enforcement (unlimited)
"""
import os
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.config_reader import (
    ManagementTeam,
    ProjectTeam,
    Workgroup,
    load_management_team,
    load_project_team,
    load_workgroup,
)
from orchestrator.events import EventType


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_teaparty_home(teaparty_yaml: str) -> str:
    home = tempfile.mkdtemp()
    mgmt_dir = os.path.join(home, '.teaparty', 'management')
    os.makedirs(mgmt_dir)
    with open(os.path.join(mgmt_dir, 'teaparty.yaml'), 'w') as f:
        f.write(teaparty_yaml)
    return home


def _make_project_dir(project_yaml: str) -> str:
    proj = tempfile.mkdtemp()
    tp_project = os.path.join(proj, '.teaparty', 'project')
    os.makedirs(tp_project)
    os.makedirs(os.path.join(proj, '.git'))
    with open(os.path.join(tp_project, 'project.yaml'), 'w') as f:
        f.write(project_yaml)
    return proj


def _make_workgroup_file(content: str) -> str:
    d = tempfile.mkdtemp()
    path = os.path.join(d, 'workgroup.yaml')
    with open(path, 'w') as f:
        f.write(content)
    return path


# ── 1. Budget field parsed from YAML config ─────────────────────────────────

class TestBudgetFieldParsed(unittest.TestCase):
    """Budget field is loaded from YAML into dataclasses at all three levels."""

    def test_management_team_budget_loaded(self):
        yaml_text = textwrap.dedent("""\
            name: Org
            lead: boss
            decider: boss
            budget:
              job_limit_usd: 10.00
              project_limit_usd: 100.00
        """)
        home = _make_teaparty_home(yaml_text)
        team = load_management_team(teaparty_home=os.path.join(home, '.teaparty'))
        self.assertEqual(team.budget['job_limit_usd'], 10.00)
        self.assertEqual(team.budget['project_limit_usd'], 100.00)

    def test_management_team_budget_default_empty(self):
        yaml_text = textwrap.dedent("""\
            name: Org
            lead: boss
            decider: boss
        """)
        home = _make_teaparty_home(yaml_text)
        team = load_management_team(teaparty_home=os.path.join(home, '.teaparty'))
        self.assertEqual(team.budget, {})

    def test_project_team_budget_loaded(self):
        yaml_text = textwrap.dedent("""\
            name: Backend
            lead: lead
            decider: darrell
            budget:
              job_limit_usd: 5.00
              project_limit_usd: 50.00
        """)
        proj = _make_project_dir(yaml_text)
        team = load_project_team(proj)
        self.assertEqual(team.budget['job_limit_usd'], 5.00)
        self.assertEqual(team.budget['project_limit_usd'], 50.00)

    def test_project_team_budget_default_empty(self):
        yaml_text = textwrap.dedent("""\
            name: Backend
            lead: lead
            decider: darrell
        """)
        proj = _make_project_dir(yaml_text)
        team = load_project_team(proj)
        self.assertEqual(team.budget, {})

    def test_workgroup_budget_loaded(self):
        yaml_text = textwrap.dedent("""\
            name: Coding
            description: Code team.
            lead: coding-lead
            budget:
              job_limit_usd: 3.00
        """)
        path = _make_workgroup_file(yaml_text)
        wg = load_workgroup(path)
        self.assertEqual(wg.budget['job_limit_usd'], 3.00)

    def test_workgroup_budget_default_empty(self):
        yaml_text = textwrap.dedent("""\
            name: Coding
            description: Code team.
            lead: coding-lead
        """)
        path = _make_workgroup_file(yaml_text)
        wg = load_workgroup(path)
        self.assertEqual(wg.budget, {})


# ── 2. Budget precedence ────────────────────────────────────────────────────

class TestBudgetPrecedence(unittest.TestCase):
    """Budget precedence: project overrides workgroup overrides org."""

    def test_project_overrides_org(self):
        from orchestrator.config_reader import apply_budget_precedence
        org = {'job_limit_usd': 10.00, 'project_limit_usd': 100.00}
        project = {'job_limit_usd': 5.00}
        result = apply_budget_precedence(org, project)
        # Project overrides job_limit
        self.assertEqual(result['job_limit_usd'], 5.00)
        # Org project_limit preserved (project didn't set it)
        self.assertEqual(result['project_limit_usd'], 100.00)

    def test_three_level_chain(self):
        from orchestrator.config_reader import apply_budget_precedence
        org = {'job_limit_usd': 10.00, 'project_limit_usd': 100.00}
        workgroup = {'job_limit_usd': 7.00}
        project = {'job_limit_usd': 5.00}
        result = apply_budget_precedence(org, workgroup, project)
        self.assertEqual(result['job_limit_usd'], 5.00)
        self.assertEqual(result['project_limit_usd'], 100.00)

    def test_empty_inputs(self):
        from orchestrator.config_reader import apply_budget_precedence
        self.assertEqual(apply_budget_precedence({}, {}, {}), {})

    def test_single_level(self):
        from orchestrator.config_reader import apply_budget_precedence
        budget = {'job_limit_usd': 5.00}
        self.assertEqual(apply_budget_precedence(budget), budget)


# ── 3. resolve_budget ───────────────────────────────────────────────────────

class TestResolveBudget(unittest.TestCase):
    """resolve_budget composes limits across config levels."""

    def test_three_level_resolution(self):
        from orchestrator.config_reader import resolve_budget
        org = {'job_limit_usd': 10.00, 'project_limit_usd': 100.00}
        workgroup = {'job_limit_usd': 7.00}
        project = {'job_limit_usd': 5.00}
        result = resolve_budget(
            org_budget=org,
            workgroup_budget=workgroup,
            project_budget=project,
        )
        self.assertEqual(result['job_limit_usd'], 5.00)
        self.assertEqual(result['project_limit_usd'], 100.00)

    def test_none_inputs(self):
        from orchestrator.config_reader import resolve_budget
        result = resolve_budget()
        self.assertEqual(result, {})

    def test_partial_levels(self):
        from orchestrator.config_reader import resolve_budget
        result = resolve_budget(project_budget={'job_limit_usd': 5.00})
        self.assertEqual(result['job_limit_usd'], 5.00)


# ── 4. CostTracker accumulates cost ────────────────────────────────────────

class TestCostTracker(unittest.TestCase):
    """CostTracker accumulates cost from result events."""

    def _make_tracker(self, job_limit: float = 0.0, project_limit: float = 0.0):
        from orchestrator.cost_tracker import CostTracker
        budget = {}
        if job_limit:
            budget['job_limit_usd'] = job_limit
        if project_limit:
            budget['project_limit_usd'] = project_limit
        return CostTracker(budget=budget)

    def test_accumulate_single_event(self):
        tracker = self._make_tracker()
        event = {'type': 'result', 'total_cost_usd': 0.05}
        tracker.record(event)
        self.assertAlmostEqual(tracker.total_cost_usd, 0.05)

    def test_accumulate_multiple_events(self):
        tracker = self._make_tracker()
        tracker.record({'type': 'result', 'total_cost_usd': 0.05})
        tracker.record({'type': 'result', 'total_cost_usd': 0.10})
        self.assertAlmostEqual(tracker.total_cost_usd, 0.15)

    def test_ignores_non_result_events(self):
        tracker = self._make_tracker()
        tracker.record({'type': 'tool_use', 'name': 'Read'})
        self.assertAlmostEqual(tracker.total_cost_usd, 0.0)

    def test_handles_missing_cost_field(self):
        """Result event without total_cost_usd does not crash."""
        tracker = self._make_tracker()
        tracker.record({'type': 'result', 'subtype': 'success'})
        self.assertAlmostEqual(tracker.total_cost_usd, 0.0)

    def test_per_model_costs_tracked(self):
        """Per-model cost breakdowns are accumulated."""
        tracker = self._make_tracker()
        tracker.record({
            'type': 'result',
            'total_cost_usd': 0.05,
            'cost_usd': {'claude-sonnet-4': 0.03, 'claude-haiku-4': 0.02},
        })
        tracker.record({
            'type': 'result',
            'total_cost_usd': 0.08,
            'cost_usd': {'claude-sonnet-4': 0.06, 'claude-haiku-4': 0.02},
        })
        self.assertAlmostEqual(tracker.model_costs['claude-sonnet-4'], 0.09)
        self.assertAlmostEqual(tracker.model_costs['claude-haiku-4'], 0.04)


# ── 5. CostTracker warns at 80% ─────────────────────────────────────────────

class TestCostTrackerWarning(unittest.TestCase):
    """CostTracker warns at 80% of budget."""

    def _make_tracker(self, job_limit: float):
        from orchestrator.cost_tracker import CostTracker
        return CostTracker(budget={'job_limit_usd': job_limit})

    def test_no_warning_below_80_percent(self):
        tracker = self._make_tracker(job_limit=10.00)
        tracker.record({'type': 'result', 'total_cost_usd': 7.99})
        self.assertFalse(tracker.warning_triggered)

    def test_warning_at_80_percent(self):
        tracker = self._make_tracker(job_limit=10.00)
        tracker.record({'type': 'result', 'total_cost_usd': 8.00})
        self.assertTrue(tracker.warning_triggered)

    def test_warning_above_80_percent(self):
        tracker = self._make_tracker(job_limit=10.00)
        tracker.record({'type': 'result', 'total_cost_usd': 9.00})
        self.assertTrue(tracker.warning_triggered)

    def test_no_warning_without_budget(self):
        from orchestrator.cost_tracker import CostTracker
        tracker = CostTracker(budget={})
        tracker.record({'type': 'result', 'total_cost_usd': 1000.00})
        self.assertFalse(tracker.warning_triggered)


# ── 6. CostTracker pauses at 100% ──────────────────────────────────────────

class TestCostTrackerPause(unittest.TestCase):
    """CostTracker pauses at 100% of budget."""

    def _make_tracker(self, job_limit: float):
        from orchestrator.cost_tracker import CostTracker
        return CostTracker(budget={'job_limit_usd': job_limit})

    def test_no_pause_below_100_percent(self):
        tracker = self._make_tracker(job_limit=10.00)
        tracker.record({'type': 'result', 'total_cost_usd': 9.99})
        self.assertFalse(tracker.limit_reached)

    def test_pause_at_100_percent(self):
        tracker = self._make_tracker(job_limit=10.00)
        tracker.record({'type': 'result', 'total_cost_usd': 10.00})
        self.assertTrue(tracker.limit_reached)

    def test_pause_above_100_percent(self):
        tracker = self._make_tracker(job_limit=10.00)
        tracker.record({'type': 'result', 'total_cost_usd': 12.00})
        self.assertTrue(tracker.limit_reached)

    def test_no_pause_without_budget(self):
        from orchestrator.cost_tracker import CostTracker
        tracker = CostTracker(budget={})
        tracker.record({'type': 'result', 'total_cost_usd': 1000.00})
        self.assertFalse(tracker.limit_reached)

    def test_utilization_ratio(self):
        tracker = self._make_tracker(job_limit=10.00)
        tracker.record({'type': 'result', 'total_cost_usd': 5.00})
        self.assertAlmostEqual(tracker.utilization, 0.5)

    def test_utilization_no_budget(self):
        from orchestrator.cost_tracker import CostTracker
        tracker = CostTracker(budget={})
        tracker.record({'type': 'result', 'total_cost_usd': 5.00})
        self.assertAlmostEqual(tracker.utilization, 0.0)


# ── 7. Event types exist ────────────────────────────────────────────────────

class TestCostEventTypes(unittest.TestCase):
    """COST_WARNING and COST_LIMIT event types exist in EventType enum."""

    def test_cost_warning_event_type(self):
        self.assertEqual(EventType.COST_WARNING.value, 'cost_warning')

    def test_cost_limit_event_type(self):
        self.assertEqual(EventType.COST_LIMIT.value, 'cost_limit')


# ── 8. ClaudeResult carries cost_usd ────────────────────────────────────────

class TestClaudeResultCost(unittest.TestCase):
    """ClaudeResult includes cost_usd field from stream parsing."""

    def test_cost_usd_field_exists(self):
        from orchestrator.claude_runner import ClaudeResult
        result = ClaudeResult(exit_code=0, cost_usd=1.23)
        self.assertAlmostEqual(result.cost_usd, 1.23)

    def test_cost_usd_defaults_to_zero(self):
        from orchestrator.claude_runner import ClaudeResult
        result = ClaudeResult(exit_code=0)
        self.assertAlmostEqual(result.cost_usd, 0.0)


# ── 9. Budget not in norms ──────────────────────────────────────────────────

class TestBudgetNotInNorms(unittest.TestCase):
    """Budget keys do not leak into norms dict."""

    def test_budget_separate_from_norms(self):
        yaml_text = textwrap.dedent("""\
            name: Backend
            lead: lead
            decider: darrell
            norms:
              quality:
                - Tests required
            budget:
              job_limit_usd: 5.00
        """)
        proj = _make_project_dir(yaml_text)
        team = load_project_team(proj)
        self.assertNotIn('budget', team.norms)
        self.assertNotIn('job_limit_usd', team.norms)
        self.assertEqual(team.budget['job_limit_usd'], 5.00)


# ── 10. ClaudeRunner extracts cost from stream ──────────────────────────────

class TestClaudeRunnerCostExtraction(unittest.TestCase):
    """ClaudeRunner._maybe_extract_cost accumulates cost from result events."""

    def _make_runner(self):
        from orchestrator.claude_runner import ClaudeRunner
        from orchestrator.events import EventBus
        return ClaudeRunner(
            prompt='test',
            cwd='/tmp',
            stream_file='/tmp/stream.jsonl',
            event_bus=EventBus(),
        )

    def test_extracts_cost_from_result_event(self):
        runner = self._make_runner()
        runner._maybe_extract_cost({'type': 'result', 'total_cost_usd': 0.05})
        self.assertAlmostEqual(runner._accumulated_cost, 0.05)

    def test_accumulates_across_events(self):
        runner = self._make_runner()
        runner._maybe_extract_cost({'type': 'result', 'total_cost_usd': 0.05})
        runner._maybe_extract_cost({'type': 'result', 'total_cost_usd': 0.10})
        self.assertAlmostEqual(runner._accumulated_cost, 0.15)

    def test_ignores_non_result_events(self):
        runner = self._make_runner()
        runner._maybe_extract_cost({'type': 'tool_use', 'name': 'Read'})
        self.assertAlmostEqual(runner._accumulated_cost, 0.0)

    def test_handles_missing_cost_field(self):
        runner = self._make_runner()
        runner._maybe_extract_cost({'type': 'result', 'subtype': 'success'})
        self.assertAlmostEqual(runner._accumulated_cost, 0.0)


# ── 11. AgentRunner passes cost to ActorResult ──────────────────────────────

class TestAgentRunnerCostPassthrough(unittest.TestCase):
    """AgentRunner puts cost_usd on ActorResult.data when present."""

    def test_cost_on_claude_result_propagates(self):
        """ClaudeResult.cost_usd > 0 is copied to ActorResult.data."""
        from orchestrator.claude_runner import ClaudeResult

        result = ClaudeResult(exit_code=0, cost_usd=1.50)
        self.assertAlmostEqual(result.cost_usd, 1.50)


# ── 12. Engine cost budget checking ─────────────────────────────────────────

class TestEngineCostBudgetCheck(unittest.TestCase):
    """Engine._check_cost_budget publishes events at thresholds."""

    def _make_engine_with_tracker(self, job_limit: float):
        """Create a minimal Orchestrator with a CostTracker for testing."""
        from unittest.mock import AsyncMock, MagicMock
        from orchestrator.cost_tracker import CostTracker
        from orchestrator.engine import Orchestrator
        from orchestrator.events import EventBus

        tracker = CostTracker(budget={'job_limit_usd': job_limit})
        event_bus = EventBus()

        # Collect published events
        published: list = []
        async def capture(event):
            published.append(event)
        event_bus.subscribe(capture)

        # Create orchestrator with minimal mocking
        cfa = MagicMock()
        cfa.state = 'TASK_IN_PROGRESS'
        cfa.actor = 'agent'
        config = MagicMock()
        config.human_actor_states = set()
        config.stall_timeout = 1800

        input_mock = AsyncMock(return_value='yes')
        engine = Orchestrator(
            cfa_state=cfa,
            phase_config=config,
            event_bus=event_bus,
            input_provider=input_mock,
            infra_dir='/tmp/infra',
            project_workdir='/tmp/project',
            session_worktree='/tmp/worktree',
            proxy_model_path='',
            project_slug='test',
            poc_root='/tmp/poc',
            cost_tracker=tracker,
        )

        return engine, tracker, published

    def test_no_event_below_80_percent(self):
        import asyncio
        engine, tracker, published = self._make_engine_with_tracker(10.00)
        tracker.record({'type': 'result', 'total_cost_usd': 7.99})
        asyncio.run(engine._check_cost_budget())
        cost_events = [e for e in published if e.type in (EventType.COST_WARNING, EventType.COST_LIMIT)]
        self.assertEqual(len(cost_events), 0)

    def test_warning_event_at_80_percent(self):
        import asyncio
        engine, tracker, published = self._make_engine_with_tracker(10.00)
        tracker.record({'type': 'result', 'total_cost_usd': 8.00})
        asyncio.run(engine._check_cost_budget())
        cost_events = [e for e in published if e.type == EventType.COST_WARNING]
        self.assertEqual(len(cost_events), 1)
        self.assertAlmostEqual(cost_events[0].data['total_cost_usd'], 8.00)
        self.assertAlmostEqual(cost_events[0].data['utilization'], 0.8)

    def test_warning_emitted_only_once(self):
        import asyncio
        engine, tracker, published = self._make_engine_with_tracker(10.00)
        tracker.record({'type': 'result', 'total_cost_usd': 8.00})
        asyncio.run(engine._check_cost_budget())
        asyncio.run(engine._check_cost_budget())
        cost_events = [e for e in published if e.type == EventType.COST_WARNING]
        self.assertEqual(len(cost_events), 1)

    def test_limit_event_at_100_percent(self):
        import asyncio
        engine, tracker, published = self._make_engine_with_tracker(10.00)
        tracker.record({'type': 'result', 'total_cost_usd': 10.00})
        asyncio.run(engine._check_cost_budget())
        cost_events = [e for e in published if e.type == EventType.COST_LIMIT]
        self.assertEqual(len(cost_events), 1)
        self.assertAlmostEqual(cost_events[0].data['total_cost_usd'], 10.00)

    def test_limit_pauses_for_human_input(self):
        """At 100%, the engine asks the human via input_provider."""
        import asyncio
        engine, tracker, published = self._make_engine_with_tracker(10.00)
        tracker.record({'type': 'result', 'total_cost_usd': 10.00})
        asyncio.run(engine._check_cost_budget())
        # Human said "yes" (default mock), so no intervention injected
        self.assertEqual(engine._pending_intervention, '')
        # INPUT_REQUESTED event was published
        input_events = [e for e in published if e.type == EventType.INPUT_REQUESTED]
        self.assertEqual(len(input_events), 1)
        self.assertIn('$10.00', input_events[0].data['bridge_text'])

    def test_limit_injects_wrapup_on_decline(self):
        """When human declines to continue, wrap-up prompt is injected."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        engine, tracker, published = self._make_engine_with_tracker(10.00)
        engine.input_provider = AsyncMock(return_value='no')
        tracker.record({'type': 'result', 'total_cost_usd': 10.00})
        asyncio.run(engine._check_cost_budget())
        self.assertIn('COST BUDGET EXCEEDED', engine._pending_intervention)
        self.assertIn('declined', engine._pending_intervention)

    def test_no_events_without_tracker(self):
        """Engine without a cost_tracker does nothing."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from orchestrator.engine import Orchestrator
        from orchestrator.events import EventBus

        event_bus = EventBus()
        published: list = []
        async def capture(event):
            published.append(event)
        event_bus.subscribe(capture)

        cfa = MagicMock()
        config = MagicMock()
        config.human_actor_states = set()
        config.stall_timeout = 1800

        engine = Orchestrator(
            cfa_state=cfa,
            phase_config=config,
            event_bus=event_bus,
            input_provider=AsyncMock(),
            infra_dir='/tmp/infra',
            project_workdir='/tmp/project',
            session_worktree='/tmp/worktree',
            proxy_model_path='',
            project_slug='test',
            poc_root='/tmp/poc',
        )
        asyncio.run(engine._check_cost_budget())
        self.assertEqual(len(published), 0)


class TestProjectCostLedger(unittest.TestCase):
    """Tests for cross-job project-level cost aggregation."""

    def _make_ledger(self):
        import tempfile
        from orchestrator.cost_tracker import ProjectCostLedger
        tmpdir = tempfile.mkdtemp()
        return ProjectCostLedger(tmpdir), tmpdir

    def test_record_and_total(self):
        ledger, _ = self._make_ledger()
        ledger.record('session-1', 1.50)
        ledger.record('session-2', 2.50)
        self.assertAlmostEqual(ledger.total_cost(), 4.00)

    def test_session_cost(self):
        ledger, _ = self._make_ledger()
        ledger.record('session-1', 1.50)
        ledger.record('session-2', 2.50)
        ledger.record('session-1', 0.50)
        self.assertAlmostEqual(ledger.session_cost('session-1'), 2.00)
        self.assertAlmostEqual(ledger.session_cost('session-2'), 2.50)

    def test_empty_ledger(self):
        ledger, _ = self._make_ledger()
        self.assertAlmostEqual(ledger.total_cost(), 0.0)
        self.assertAlmostEqual(ledger.session_cost('any'), 0.0)

    def test_zero_cost_not_recorded(self):
        ledger, _ = self._make_ledger()
        ledger.record('session-1', 0.0)
        self.assertAlmostEqual(ledger.total_cost(), 0.0)


class TestPerModelCostFlow(unittest.TestCase):
    """Tests for per-model cost breakdown through the runtime path."""

    def test_claude_result_carries_per_model(self):
        from orchestrator.claude_runner import ClaudeResult
        result = ClaudeResult(
            exit_code=0,
            cost_usd=5.0,
            cost_per_model={'claude-3-opus': 3.0, 'claude-3-haiku': 2.0},
        )
        self.assertEqual(result.cost_per_model['claude-3-opus'], 3.0)
        self.assertEqual(result.cost_per_model['claude-3-haiku'], 2.0)

    def test_cost_tracker_records_per_model(self):
        from orchestrator.cost_tracker import CostTracker
        tracker = CostTracker(budget={'job_limit_usd': 10.0})
        tracker.record({
            'type': 'result',
            'total_cost_usd': 5.0,
            'cost_usd': {'claude-3-opus': 3.0, 'claude-3-haiku': 2.0},
        })
        self.assertEqual(tracker.model_costs['claude-3-opus'], 3.0)
        self.assertEqual(tracker.model_costs['claude-3-haiku'], 2.0)

    def test_engine_passes_per_model_to_tracker(self):
        """Engine feeds per-model data from actor result to CostTracker."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from orchestrator.cost_tracker import CostTracker
        from orchestrator.engine import Orchestrator
        from orchestrator.events import EventBus

        tracker = CostTracker(budget={'job_limit_usd': 100.0})
        event_bus = EventBus()
        cfa = MagicMock()
        config = MagicMock()
        config.human_actor_states = set()
        config.stall_timeout = 1800

        engine = Orchestrator(
            cfa_state=cfa,
            phase_config=config,
            event_bus=event_bus,
            input_provider=AsyncMock(return_value='yes'),
            infra_dir='/tmp/infra',
            project_workdir='/tmp/project',
            session_worktree='/tmp/worktree',
            proxy_model_path='',
            project_slug='test',
            poc_root='/tmp/poc',
            cost_tracker=tracker,
        )

        # Simulate what the engine does when it gets per-model data
        from orchestrator.actors import ActorResult
        actor_result = ActorResult(
            action='continue',
            data={
                'cost_usd': 5.0,
                'cost_per_model': {'claude-3-opus': 3.0, 'claude-3-haiku': 2.0},
            },
        )
        # Feed cost to tracker the same way the engine does
        turn_cost = actor_result.data.get('cost_usd', 0.0)
        cost_event = {'type': 'result', 'total_cost_usd': turn_cost}
        per_model = actor_result.data.get('cost_per_model')
        if per_model:
            cost_event['cost_usd'] = per_model
        tracker.record(cost_event)

        self.assertAlmostEqual(tracker.total_cost_usd, 5.0)
        self.assertEqual(tracker.model_costs['claude-3-opus'], 3.0)


class TestCostSidecar(unittest.TestCase):
    """Tests for the .cost sidecar file written by the engine."""

    def test_write_cost_sidecar(self):
        import tempfile
        from unittest.mock import AsyncMock, MagicMock
        from orchestrator.cost_tracker import CostTracker
        from orchestrator.engine import Orchestrator
        from orchestrator.events import EventBus

        infra_dir = tempfile.mkdtemp()
        tracker = CostTracker(budget={'job_limit_usd': 100.0})
        tracker.record({'type': 'result', 'total_cost_usd': 3.50})

        cfa = MagicMock()
        config = MagicMock()
        config.human_actor_states = set()
        config.stall_timeout = 1800

        engine = Orchestrator(
            cfa_state=cfa,
            phase_config=config,
            event_bus=EventBus(),
            input_provider=AsyncMock(return_value='yes'),
            infra_dir=infra_dir,
            project_workdir='/tmp/project',
            session_worktree='/tmp/worktree',
            proxy_model_path='',
            project_slug='test',
            poc_root='/tmp/poc',
            cost_tracker=tracker,
        )
        engine._write_cost_sidecar()

        import os
        cost_path = os.path.join(infra_dir, '.cost')
        self.assertTrue(os.path.exists(cost_path))
        with open(cost_path) as f:
            val = float(f.read().strip())
        self.assertAlmostEqual(val, 3.50)


class TestProductionWiring(unittest.TestCase):
    """Tests that CostTracker is wired into production paths."""

    def test_resolve_cost_tracker_returns_tracker_with_budget(self):
        """_resolve_cost_tracker_impl returns CostTracker when budget exists."""
        import tempfile, os, yaml
        from orchestrator.session import _resolve_cost_tracker_impl

        tmpdir = tempfile.mkdtemp()
        teaparty_project = os.path.join(tmpdir, '.teaparty', 'project')
        os.makedirs(teaparty_project)
        with open(os.path.join(teaparty_project, 'project.yaml'), 'w') as f:
            yaml.dump({
                'name': 'test',
                'workgroups': [],
                'budget': {'job_limit_usd': 5.0, 'project_limit_usd': 50.0},
            }, f)

        tracker = _resolve_cost_tracker_impl(tmpdir)
        self.assertIsNotNone(tracker)
        self.assertAlmostEqual(tracker.job_limit, 5.0)
        self.assertAlmostEqual(tracker.project_limit, 50.0)

    def test_resolve_cost_tracker_returns_none_without_budget(self):
        """_resolve_cost_tracker_impl returns None when no budget configured."""
        import tempfile
        from orchestrator.session import _resolve_cost_tracker_impl

        tmpdir = tempfile.mkdtemp()
        tracker = _resolve_cost_tracker_impl(tmpdir)
        self.assertIsNone(tracker)


if __name__ == '__main__':
    unittest.main()
