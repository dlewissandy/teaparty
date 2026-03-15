"""Tests for issue #99: Contingency logic in plans.

Verifies that:
1. The planning prompt includes structured contingency guidance covering
   the three required categories (assumption invalidation, infrastructure
   limitations, scope changes).
2. The planning prompt specifies the "If [condition], then [action]" format.
3. The execution prompt includes guidance for following plan contingencies
   during dispatch.
4. The _task_for_phase('execution') passes PLAN.md content (which contains
   contingencies) to the execution agent.
"""
import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))


def _load_uber_team_prompt(role='project-lead'):
    """Load a role's prompt from uber-team.json."""
    agents_path = Path(__file__).parent.parent.parent / 'agents' / 'uber-team.json'
    with open(agents_path) as f:
        data = json.load(f)
    return data[role]['prompt']


def _planning_section(prompt):
    """Extract the planning phase section of the prompt."""
    start = prompt.find('PLANNING PHASE')
    end = prompt.find('EXECUTION PHASE')
    if start == -1 or end == -1:
        return ''
    return prompt[start:end]


def _execution_section(prompt):
    """Extract the execution phase section of the prompt."""
    start = prompt.find('EXECUTION PHASE')
    if start == -1:
        return ''
    return prompt[start:]


class TestPlanningPromptContingencyGuidance(unittest.TestCase):
    """The planning prompt must include structured contingency guidance."""

    def setUp(self):
        self.prompt = _load_uber_team_prompt()
        self.planning = _planning_section(self.prompt)

    def test_planning_section_mentions_contingencies(self):
        """The planning section must reference contingencies."""
        self.assertIn('contingenc', self.planning.lower(),
                      "Planning section must mention contingencies")

    def test_planning_specifies_if_then_format(self):
        """The planning prompt must specify the 'If [condition], then [action]' format."""
        # Check for the if/then pattern guidance
        has_if_then = ('if [' in self.planning.lower() or
                       'if [condition]' in self.planning.lower() or
                       '"if ' in self.planning.lower())
        self.assertTrue(has_if_then,
                        "Planning section must specify 'If [condition], then [action]' format")

    def test_planning_covers_assumption_invalidation(self):
        """Contingency guidance must cover assumption invalidation."""
        lower = self.planning.lower()
        has_assumption = ('assumption' in lower and
                          ('invalid' in lower or 'break' in lower or 'wrong' in lower))
        self.assertTrue(has_assumption,
                        "Planning section must cover assumption invalidation contingencies")

    def test_planning_covers_infrastructure_limitations(self):
        """Contingency guidance must cover infrastructure limitations."""
        lower = self.planning.lower()
        has_infra = ('infrastructure' in lower or
                     ('dispatch' in lower and ('fail' in lower or 'limit' in lower)))
        self.assertTrue(has_infra,
                        "Planning section must cover infrastructure limitation contingencies")

    def test_planning_covers_scope_changes(self):
        """Contingency guidance must cover scope changes."""
        lower = self.planning.lower()
        has_scope = ('scope' in lower and
                     ('change' in lower or 'expand' in lower or 'grow' in lower))
        self.assertTrue(has_scope,
                        "Planning section must cover scope change contingencies")


class TestExecutionPromptContingencyFollowing(unittest.TestCase):
    """The execution prompt must include guidance for following contingencies."""

    def setUp(self):
        self.prompt = _load_uber_team_prompt()
        self.execution = _execution_section(self.prompt)

    def test_execution_section_references_contingencies(self):
        """The execution section must reference contingencies from PLAN.md."""
        self.assertIn('contingenc', self.execution.lower(),
                      "Execution section must reference contingencies")

    def test_execution_section_links_contingencies_to_dispatch(self):
        """Execution guidance should connect contingencies to the dispatch workflow."""
        lower = self.execution.lower()
        # The execution prompt should mention checking contingencies
        # as part of the dispatch or phase execution pattern
        has_check = (('check' in lower or 'review' in lower or 'follow' in lower) and
                     'contingenc' in lower)
        self.assertTrue(has_check,
                        "Execution section must include guidance to check/follow contingencies")


class TestTaskForPhasePassesContingencies(unittest.TestCase):
    """_task_for_phase('execution') must pass PLAN.md content to the agent."""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()
        self.session_worktree = self.tmpdir

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_orchestrator(self):
        """Create a minimal Orchestrator for testing _task_for_phase."""
        from projects.POC.scripts.cfa_state import make_initial_state
        from projects.POC.orchestrator.engine import Orchestrator
        from projects.POC.orchestrator.events import EventBus
        from projects.POC.orchestrator.phase_config import PhaseConfig

        cfa = make_initial_state()
        poc_root = str(Path(__file__).parent.parent.parent)
        config = PhaseConfig(poc_root)
        bus = EventBus()

        async def noop_input(req):
            return ''

        return Orchestrator(
            cfa_state=cfa,
            phase_config=config,
            event_bus=bus,
            input_provider=noop_input,
            infra_dir=self.tmpdir,
            project_workdir=self.tmpdir,
            session_worktree=self.session_worktree,
            proxy_model_path='',
            project_slug='test',
            poc_root=poc_root,
            task='test task',
        )

    def test_execution_task_includes_plan_content(self):
        """When PLAN.md exists with contingencies, execution task includes them."""
        plan_content = (
            "## Phase 1: Research\n"
            "Investigate the codebase.\n"
            "Contingency: If the existing implementation is broken, escalate.\n"
        )
        plan_path = os.path.join(self.session_worktree, 'PLAN.md')
        Path(plan_path).write_text(plan_content)

        orch = self._make_orchestrator()
        task = orch._task_for_phase('execution')
        self.assertIn('Contingency', task,
                      "Execution task must include PLAN.md content with contingencies")


if __name__ == '__main__':
    unittest.main()
