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

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.config_reader import (
    ManagementTeam,
    ProjectTeam,
    Workgroup,
    load_management_team,
    load_project_team,
    load_workgroup,
)
from projects.POC.orchestrator.events import EventType


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_teaparty_home(teaparty_yaml: str) -> str:
    home = tempfile.mkdtemp()
    tp_dir = os.path.join(home, '.teaparty')
    os.makedirs(tp_dir)
    with open(os.path.join(tp_dir, 'teaparty.yaml'), 'w') as f:
        f.write(teaparty_yaml)
    return home


def _make_project_dir(project_yaml: str) -> str:
    proj = tempfile.mkdtemp()
    tp_dir = os.path.join(proj, '.teaparty')
    os.makedirs(tp_dir)
    os.makedirs(os.path.join(proj, '.git'))
    os.makedirs(os.path.join(proj, '.claude'))
    with open(os.path.join(tp_dir, 'project.yaml'), 'w') as f:
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
        from projects.POC.orchestrator.config_reader import apply_budget_precedence
        org = {'job_limit_usd': 10.00, 'project_limit_usd': 100.00}
        project = {'job_limit_usd': 5.00}
        result = apply_budget_precedence(org, project)
        # Project overrides job_limit
        self.assertEqual(result['job_limit_usd'], 5.00)
        # Org project_limit preserved (project didn't set it)
        self.assertEqual(result['project_limit_usd'], 100.00)

    def test_three_level_chain(self):
        from projects.POC.orchestrator.config_reader import apply_budget_precedence
        org = {'job_limit_usd': 10.00, 'project_limit_usd': 100.00}
        workgroup = {'job_limit_usd': 7.00}
        project = {'job_limit_usd': 5.00}
        result = apply_budget_precedence(org, workgroup, project)
        self.assertEqual(result['job_limit_usd'], 5.00)
        self.assertEqual(result['project_limit_usd'], 100.00)

    def test_empty_inputs(self):
        from projects.POC.orchestrator.config_reader import apply_budget_precedence
        self.assertEqual(apply_budget_precedence({}, {}, {}), {})

    def test_single_level(self):
        from projects.POC.orchestrator.config_reader import apply_budget_precedence
        budget = {'job_limit_usd': 5.00}
        self.assertEqual(apply_budget_precedence(budget), budget)


# ── 3. resolve_budget ───────────────────────────────────────────────────────

class TestResolveBudget(unittest.TestCase):
    """resolve_budget composes limits across config levels."""

    def test_three_level_resolution(self):
        from projects.POC.orchestrator.config_reader import resolve_budget
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
        from projects.POC.orchestrator.config_reader import resolve_budget
        result = resolve_budget()
        self.assertEqual(result, {})

    def test_partial_levels(self):
        from projects.POC.orchestrator.config_reader import resolve_budget
        result = resolve_budget(project_budget={'job_limit_usd': 5.00})
        self.assertEqual(result['job_limit_usd'], 5.00)


# ── 4. CostTracker accumulates cost ────────────────────────────────────────

class TestCostTracker(unittest.TestCase):
    """CostTracker accumulates cost from result events."""

    def _make_tracker(self, job_limit: float = 0.0, project_limit: float = 0.0):
        from projects.POC.orchestrator.cost_tracker import CostTracker
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
        from projects.POC.orchestrator.cost_tracker import CostTracker
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
        from projects.POC.orchestrator.cost_tracker import CostTracker
        tracker = CostTracker(budget={})
        tracker.record({'type': 'result', 'total_cost_usd': 1000.00})
        self.assertFalse(tracker.warning_triggered)


# ── 6. CostTracker pauses at 100% ──────────────────────────────────────────

class TestCostTrackerPause(unittest.TestCase):
    """CostTracker pauses at 100% of budget."""

    def _make_tracker(self, job_limit: float):
        from projects.POC.orchestrator.cost_tracker import CostTracker
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
        from projects.POC.orchestrator.cost_tracker import CostTracker
        tracker = CostTracker(budget={})
        tracker.record({'type': 'result', 'total_cost_usd': 1000.00})
        self.assertFalse(tracker.limit_reached)

    def test_utilization_ratio(self):
        tracker = self._make_tracker(job_limit=10.00)
        tracker.record({'type': 'result', 'total_cost_usd': 5.00})
        self.assertAlmostEqual(tracker.utilization, 0.5)

    def test_utilization_no_budget(self):
        from projects.POC.orchestrator.cost_tracker import CostTracker
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
        from projects.POC.orchestrator.claude_runner import ClaudeResult
        result = ClaudeResult(exit_code=0, cost_usd=1.23)
        self.assertAlmostEqual(result.cost_usd, 1.23)

    def test_cost_usd_defaults_to_zero(self):
        from projects.POC.orchestrator.claude_runner import ClaudeResult
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


if __name__ == '__main__':
    unittest.main()
