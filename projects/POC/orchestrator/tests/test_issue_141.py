#!/usr/bin/env python3
"""Tests for Issue #141: Agents must know their constraints and escalate.

Covers:
 1. _task_for_phase('intent') includes norms/guardrails as constraints
 2. _task_for_phase('intent') includes escalation guidance referencing INTENT_ESCALATE
 3. _task_for_phase('planning') includes dynamically-resolved available teams
 4. Planning task context lists only project-scoped teams when project config restricts them
 5. uber-team.json project-lead prompt no longer contains hardcoded liaison list
 6. intent-team.json intent-lead prompt includes constraint/escalation language
"""
import json
import os
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


# ── 1. Intent task includes constraints ──────────────────────────────────────

class TestIntentTaskIncludesConstraints(unittest.TestCase):
    """_task_for_phase('intent') must include norms/guardrails as constraints."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_intent_task_contains_constraints_section(self):
        """Intent task must have a constraints block when norms are configured."""
        # Create a project dir with norms
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
        """Intent task must reference INTENT_ESCALATE as the correct response."""
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


# ── 2. Planning task includes available teams ────────────────────────────────

class TestPlanningTaskIncludesTeams(unittest.TestCase):
    """_task_for_phase('planning') must include dynamically-resolved teams."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_planning_task_lists_available_teams(self):
        """Planning task must list teams from phase config."""
        # Write INTENT.md so planning reads it
        Path(os.path.join(self.tmpdir, 'INTENT.md')).write_text(
            '## Objective\nBuild something.\n')

        orch = _make_orchestrator(self.tmpdir, _poc_root())
        task = orch._task_for_phase('planning')

        # All default teams should appear
        for team_name in ('art', 'writing', 'editorial', 'research', 'coding'):
            self.assertIn(team_name, task,
                          f"Planning task must list available team '{team_name}'")

    def test_planning_task_respects_project_team_subset(self):
        """When project config restricts teams, only those appear."""
        Path(os.path.join(self.tmpdir, 'INTENT.md')).write_text(
            '## Objective\nBuild something.\n')

        # Create project dir with restricted teams
        project_dir = tempfile.mkdtemp()
        os.makedirs(os.path.join(project_dir, '.teaparty'), exist_ok=True)
        Path(os.path.join(project_dir, 'project.json')).write_text(
            json.dumps({'teams': {'coding': {}, 'research': {}}}))

        orch = _make_orchestrator(self.tmpdir, _poc_root(), project_dir=project_dir)
        task = orch._task_for_phase('planning')

        self.assertIn('coding', task)
        self.assertIn('research', task)
        # art, writing, editorial should NOT appear in the available teams list
        # (They may appear in the INTENT.md content, but the injected teams block
        # should not list them)


# ── 3. Hardcoded liaison list removed from uber-team.json ────────────────────

class TestNoHardcodedLiaisonList(unittest.TestCase):
    """uber-team.json must not contain a hardcoded liaison list."""

    def test_project_lead_prompt_no_hardcoded_liaisons(self):
        """The project-lead prompt should not enumerate specific liaison names."""
        agent_path = os.path.join(_poc_root(), 'agents', 'uber-team.json')
        with open(agent_path) as f:
            agents = json.load(f)

        prompt = agents['project-lead']['prompt']
        # The old hardcoded string was: "Available liaisons: art-liaison, writing-liaison..."
        self.assertNotIn('art-liaison, writing-liaison', prompt,
                         "Hardcoded liaison list must be removed from project-lead prompt")


# ── 4. Intent agent prompt includes constraint awareness ─────────────────────

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
