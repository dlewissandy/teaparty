#!/usr/bin/env python3
"""Tests for Issue #141: Agents must know their constraints and escalate.

Covers:
 1. _task_for_phase('intent') includes norms/guardrails as constraints
 2. _task_for_phase('intent') includes escalation guidance
 3. _task_for_phase('intent') has no constraints block when no norms configured
 4. _task_for_phase('planning') includes dynamically-resolved available teams
 5. Planning task context excludes teams not in project config
 6. _task_for_phase('planning') lists available skills from project skills dir
 7. uber-team.json project-lead prompt no longer contains hardcoded liaison list
 8. intent-team.json intent-lead prompt includes constraint/escalation language
"""
import json
import os
import shutil
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.scripts.cfa_state import make_initial_state
from projects.POC.orchestrator.engine import Orchestrator
from projects.POC.orchestrator.events import EventBus
from projects.POC.orchestrator.phase_config import PhaseConfig


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_orchestrator(tmpdir, poc_root, task='test task', project_dir=None):
    """Create a minimal Orchestrator for testing _task_for_phase."""
    cfa = make_initial_state()
    config = PhaseConfig(poc_root, project_dir=project_dir)
    bus = EventBus()

    async def noop_input(req):
        return ''

    return Orchestrator(
        cfa_state=cfa,
        phase_config=config,
        event_bus=bus,
        input_provider=noop_input,
        infra_dir=tmpdir,
        project_workdir=tmpdir,
        session_worktree=tmpdir,
        proxy_model_path='',
        project_slug='test',
        poc_root=poc_root,
        task=task,
        project_dir=project_dir or '',
    )


def _poc_root():
    return str(Path(__file__).parent.parent.parent)


def _make_skill(skills_dir, name, description):
    """Write a minimal skill markdown file to skills_dir."""
    os.makedirs(skills_dir, exist_ok=True)
    Path(os.path.join(skills_dir, f'{name}.md')).write_text(textwrap.dedent(f"""\
        ---
        name: {name}
        description: {description}
        category: test
        ---
        ## Phase 1
        Do the thing.
    """))


# ── 1. Intent task includes constraints ──────────────────────────────────────

class TestIntentTaskIncludesConstraints(unittest.TestCase):
    """_task_for_phase('intent') must include norms/guardrails as constraints."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_intent_task_contains_constraints_section(self):
        """Intent task must have a constraints block when norms are configured."""
        project_dir = tempfile.mkdtemp()
        tp_dir = os.path.join(project_dir, '.teaparty')
        os.makedirs(tp_dir)
        Path(os.path.join(tp_dir, 'project.yaml')).write_text(textwrap.dedent("""\
            name: test-project
            norms:
              safety:
                - Never produce harmful content
              scope:
                - Only modify files in the project directory
        """))

        orch = _make_orchestrator(self.tmpdir, _poc_root(), project_dir=project_dir)
        task = orch._task_for_phase('intent')

        self.assertIn('Never produce harmful content', task)
        self.assertIn('Only modify files in the project directory', task)

    def test_intent_task_contains_escalation_guidance(self):
        """Intent task must mention escalation when constraints are present."""
        project_dir = tempfile.mkdtemp()
        tp_dir = os.path.join(project_dir, '.teaparty')
        os.makedirs(tp_dir)
        Path(os.path.join(tp_dir, 'project.yaml')).write_text(textwrap.dedent("""\
            name: test-project
            norms:
              safety:
                - Never produce harmful content
        """))

        orch = _make_orchestrator(self.tmpdir, _poc_root(), project_dir=project_dir)
        task = orch._task_for_phase('intent')

        self.assertIn('escalat', task.lower(),
                      "Intent task must mention escalation when constraints are present")

    def test_intent_task_no_constraints_when_no_norms(self):
        """Intent task must NOT have a constraints block when no norms exist."""
        orch = _make_orchestrator(self.tmpdir, _poc_root())
        task = orch._task_for_phase('intent')

        self.assertNotIn('--- Constraints ---', task,
                         "No constraints block when no norms are configured")


# ── 2. Planning task includes available teams ────────────────────────────────

class TestPlanningTaskIncludesTeams(unittest.TestCase):
    """_task_for_phase('planning') must include dynamically-resolved teams."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_planning_task_lists_available_teams(self):
        """Planning task must list teams from phase config."""
        Path(os.path.join(self.tmpdir, 'INTENT.md')).write_text(
            '## Objective\nBuild something.\n')

        orch = _make_orchestrator(self.tmpdir, _poc_root())
        task = orch._task_for_phase('planning')

        for team_name in ('art', 'writing', 'editorial', 'research', 'coding'):
            self.assertIn(team_name, task,
                          f"Planning task must list available team '{team_name}'")

    def test_planning_task_respects_project_team_subset(self):
        """When project config restricts teams, excluded teams must not appear
        in the Planning Constraints block."""
        Path(os.path.join(self.tmpdir, 'INTENT.md')).write_text(
            '## Objective\nBuild something.\n')

        project_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(project_dir, '.teaparty'), exist_ok=True)
        Path(os.path.join(project_dir, 'project.json')).write_text(
            json.dumps({'teams': {'coding': {}, 'research': {}}}))

        orch = _make_orchestrator(self.tmpdir, _poc_root(), project_dir=project_dir)
        task = orch._task_for_phase('planning')

        # Extract the Planning Constraints block
        start = task.find('--- Planning Constraints ---')
        end = task.find('--- end ---', start) if start != -1 else -1
        self.assertGreater(start, -1, "Planning Constraints block must exist")
        constraints_block = task[start:end]

        self.assertIn('coding', constraints_block)
        self.assertIn('research', constraints_block)
        # Excluded teams must NOT be in the constraints block
        self.assertNotIn('art', constraints_block,
                         "'art' team must not appear when project restricts to coding+research")
        self.assertNotIn('writing', constraints_block,
                         "'writing' team must not appear when project restricts to coding+research")
        self.assertNotIn('editorial', constraints_block,
                         "'editorial' team must not appear when project restricts to coding+research")


# ── 3. Planning task includes available skills ───────────────────────────────

class TestPlanningTaskIncludesSkills(unittest.TestCase):
    """_task_for_phase('planning') must list available skills."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_planning_task_lists_skills(self):
        """When skills exist, planning task must list their names and descriptions."""
        Path(os.path.join(self.tmpdir, 'INTENT.md')).write_text(
            '## Objective\nBuild something.\n')

        skills_dir = os.path.join(self.tmpdir, 'skills')
        _make_skill(skills_dir, 'deploy-web', 'Standard web deployment procedure')
        _make_skill(skills_dir, 'code-review', 'Structured code review workflow')

        orch = _make_orchestrator(self.tmpdir, _poc_root())
        task = orch._task_for_phase('planning')

        self.assertIn('deploy-web', task)
        self.assertIn('Standard web deployment procedure', task)
        self.assertIn('code-review', task)
        self.assertIn('Structured code review workflow', task)

    def test_planning_task_no_skills_section_when_none_exist(self):
        """When no skills directory exists, planning task has no skills listing."""
        Path(os.path.join(self.tmpdir, 'INTENT.md')).write_text(
            '## Objective\nBuild something.\n')

        orch = _make_orchestrator(self.tmpdir, _poc_root())
        task = orch._task_for_phase('planning')

        self.assertNotIn('Available skills', task,
                         "No skills section when no skills exist")

    def test_planning_task_skips_degraded_skills(self):
        """Skills with needs_review=true must not appear in planning context."""
        Path(os.path.join(self.tmpdir, 'INTENT.md')).write_text(
            '## Objective\nBuild something.\n')

        skills_dir = os.path.join(self.tmpdir, 'skills')
        _make_skill(skills_dir, 'good-skill', 'Works fine')
        # Write a degraded skill
        os.makedirs(skills_dir, exist_ok=True)
        Path(os.path.join(skills_dir, 'broken-skill.md')).write_text(textwrap.dedent("""\
            ---
            name: broken-skill
            description: This skill is broken
            needs_review: true
            ---
            ## Phase 1
            Broken.
        """))

        orch = _make_orchestrator(self.tmpdir, _poc_root())
        task = orch._task_for_phase('planning')

        self.assertIn('good-skill', task)
        self.assertNotIn('broken-skill', task,
                         "Degraded skills (needs_review=true) must not appear in planning context")


# ── 4. Hardcoded liaison list removed from uber-team.json ────────────────────

class TestNoHardcodedLiaisonList(unittest.TestCase):
    """uber-team.json must not contain a hardcoded liaison list."""

    def test_project_lead_prompt_no_hardcoded_liaisons(self):
        """The project-lead prompt should not enumerate specific liaison names."""
        agent_path = os.path.join(_poc_root(), 'agents', 'uber-team.json')
        with open(agent_path) as f:
            agents = json.load(f)

        prompt = agents['project-lead']['prompt']
        self.assertNotIn('art-liaison, writing-liaison', prompt,
                         "Hardcoded liaison list must be removed from project-lead prompt")


# ── 5. Intent agent prompt includes constraint awareness ─────────────────────

class TestIntentAgentConstraintAwareness(unittest.TestCase):
    """intent-team.json must include constraint/escalation language."""

    def test_intent_lead_prompt_mentions_escalation(self):
        """The intent-lead prompt should mention escalation for constraint violations."""
        agent_path = os.path.join(_poc_root(), 'agents', 'intent-team.json')
        with open(agent_path) as f:
            agents = json.load(f)

        prompt = agents['intent-lead']['prompt']
        self.assertIn('constraint', prompt.lower(),
                      "Intent-lead prompt must mention constraints")


if __name__ == '__main__':
    unittest.main()
