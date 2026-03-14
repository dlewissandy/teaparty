#!/usr/bin/env python3
"""Regression tests for issue #121: execution lead must delegate, not do work itself.

Root causes:
 1. Execution phase permissions.allow missing SendMessage and Bash —
    the lead can't talk to liaisons, liaisons can't run dispatch_cli.py
 2. Project-lead prompt doesn't mention SendMessage as a delegation tool
 3. Liaison prompts reference nonexistent dispatch.sh instead of dispatch_cli.py

These tests verify the configuration is correct at the source-of-truth level
(phase-config.json, agent definition files) so the bug cannot silently regress.
"""
import json
import os
import sys
import unittest
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.phase_config import PhaseConfig


# ── Helpers ───────────────────────────────────────────────────────────────────

def _poc_root() -> str:
    return str(Path(__file__).parent.parent.parent)


def _load_agents_file(filename: str) -> dict:
    path = os.path.join(_poc_root(), 'agents', filename)
    with open(path) as f:
        return json.load(f)


def _phase_config() -> PhaseConfig:
    return PhaseConfig(_poc_root())


# ── Test: execution phase permissions ─────────────────────────────────────────

class TestExecutionPhasePermissions(unittest.TestCase):
    """The execution phase settings_overlay must grant all tools needed for delegation."""

    def setUp(self):
        self.config = _phase_config()
        self.exec_spec = self.config.phase('execution')
        self.allowed = self.exec_spec.settings_overlay.get('permissions', {}).get('allow', [])

    def test_sendmessage_is_allowed(self):
        """SendMessage must be in permissions.allow — the lead uses it to delegate to liaisons."""
        self.assertIn('SendMessage', self.allowed,
                      "Execution lead cannot delegate without SendMessage permission")

    def test_bash_is_allowed(self):
        """Bash must be in permissions.allow — liaisons use it to run dispatch_cli.py."""
        self.assertIn('Bash', self.allowed,
                      "Liaisons cannot run dispatch_cli.py without Bash permission")

    def test_write_is_allowed(self):
        """Write must be in permissions.allow — for checkpoint files and escalation notes."""
        self.assertIn('Write', self.allowed)

    def test_edit_is_allowed(self):
        """Edit must be in permissions.allow."""
        self.assertIn('Edit', self.allowed)


# ── Test: project-lead prompt mentions SendMessage ────────────────────────────

class TestProjectLeadPrompt(unittest.TestCase):
    """The project-lead prompt must instruct delegation via SendMessage."""

    def setUp(self):
        agents = _load_agents_file('uber-team.json')
        self.prompt = agents['project-lead']['prompt']

    def test_prompt_mentions_sendmessage(self):
        """The prompt must tell the lead that SendMessage is available."""
        self.assertIn('SendMessage', self.prompt,
                      "Lead prompt must mention SendMessage so the agent knows how to delegate")

    def test_prompt_instructs_delegation_via_sendmessage(self):
        """The execution phase section must explicitly instruct SendMessage-based delegation."""
        # Find the execution phase section
        exec_idx = self.prompt.find('EXECUTION PHASE')
        self.assertGreater(exec_idx, -1, "Prompt must contain an EXECUTION PHASE section")
        exec_section = self.prompt[exec_idx:]
        self.assertIn('SendMessage', exec_section,
                      "EXECUTION PHASE section must reference SendMessage for delegation")

    def test_prompt_discourages_direct_file_reading(self):
        """The prompt must tell the lead NOT to read source files directly."""
        exec_idx = self.prompt.find('EXECUTION PHASE')
        exec_section = self.prompt[exec_idx:]
        # Should contain guidance against reading source files
        self.assertTrue(
            'NOT read source files' in exec_section or
            'Do not read source files' in exec_section or
            'not read source' in exec_section.lower(),
            "EXECUTION PHASE must discourage direct source file reading"
        )


# ── Test: liaison prompts reference dispatch_cli.py, not dispatch.sh ──────────

class TestLiaisonDispatchCommand(unittest.TestCase):
    """All liaison prompts must reference dispatch_cli.py, not the defunct dispatch.sh."""

    def _assert_liaison_uses_dispatch_cli(self, agents: dict, liaison_name: str):
        prompt = agents[liaison_name]['prompt']
        self.assertNotIn('dispatch.sh', prompt,
                         f"{liaison_name} prompt references nonexistent dispatch.sh")
        self.assertIn('dispatch_cli', prompt,
                      f"{liaison_name} prompt must reference dispatch_cli for dispatching")

    def test_uber_team_liaisons(self):
        """All liaisons in uber-team.json must use dispatch_cli."""
        agents = _load_agents_file('uber-team.json')
        for name in ['art-liaison', 'writing-liaison', 'editorial-liaison',
                      'research-liaison', 'coding-liaison']:
            with self.subTest(liaison=name):
                self._assert_liaison_uses_dispatch_cli(agents, name)

    def test_project_team_liaisons(self):
        """All liaisons in project-team.json must use dispatch_cli."""
        agents = _load_agents_file('project-team.json')
        for name in ['art-liaison', 'writing-liaison', 'editorial-liaison',
                      'research-liaison', 'coding-liaison']:
            with self.subTest(liaison=name):
                self._assert_liaison_uses_dispatch_cli(agents, name)

    def test_intent_team_research_liaison(self):
        """The intent-team research-liaison must use dispatch_cli."""
        agents = _load_agents_file('intent-team.json')
        self._assert_liaison_uses_dispatch_cli(agents, 'research-liaison')

    def test_uber_team_lead_does_not_reference_dispatch_sh(self):
        """The project-lead prompt must not reference dispatch.sh."""
        agents = _load_agents_file('uber-team.json')
        self.assertNotIn('dispatch.sh', agents['project-lead']['prompt'],
                         "project-lead prompt still references defunct dispatch.sh")


# ── Test: no agent file anywhere references dispatch.sh ───────────────────────

class TestNoDispatchShInAnyAgentFile(unittest.TestCase):
    """Sweep all agent definition files — none may reference dispatch.sh."""

    def test_no_dispatch_sh_in_agents_dir(self):
        agents_dir = os.path.join(_poc_root(), 'agents')
        failures = []
        for filename in os.listdir(agents_dir):
            if not filename.endswith('.json'):
                continue
            filepath = os.path.join(agents_dir, filename)
            with open(filepath) as f:
                content = f.read()
            if 'dispatch.sh' in content:
                failures.append(filename)
        self.assertEqual(failures, [],
                         f"Agent files still reference dispatch.sh: {failures}")


# ── Test: execution phase has correct agent file and lead ─────────────────────

class TestExecutionPhaseWiring(unittest.TestCase):
    """The execution phase must be wired to the uber-team with project-lead."""

    def setUp(self):
        self.config = _phase_config()
        self.exec_spec = self.config.phase('execution')

    def test_execution_uses_uber_team(self):
        self.assertEqual(self.exec_spec.agent_file, 'agents/uber-team.json')

    def test_execution_lead_is_project_lead(self):
        self.assertEqual(self.exec_spec.lead, 'project-lead')

    def test_execution_permission_mode_is_accept_edits(self):
        """acceptEdits auto-approves Read/Glob/Grep + Write/Edit — agent can inspect worktree."""
        self.assertEqual(self.exec_spec.permission_mode, 'acceptEdits')


# ── Test: uber-team.json liaisons have dispatch_cli with correct team names ───

class TestLiaisonDispatchTeamNames(unittest.TestCase):
    """Each liaison's dispatch command must reference the correct team name."""

    def setUp(self):
        self.agents = _load_agents_file('uber-team.json')

    def test_art_liaison_dispatches_to_art(self):
        self.assertIn('--team art', self.agents['art-liaison']['prompt'])

    def test_writing_liaison_dispatches_to_writing(self):
        self.assertIn('--team writing', self.agents['writing-liaison']['prompt'])

    def test_editorial_liaison_dispatches_to_editorial(self):
        self.assertIn('--team editorial', self.agents['editorial-liaison']['prompt'])

    def test_research_liaison_dispatches_to_research(self):
        self.assertIn('--team research', self.agents['research-liaison']['prompt'])

    def test_coding_liaison_dispatches_to_coding(self):
        self.assertIn('--team coding', self.agents['coding-liaison']['prompt'])


if __name__ == '__main__':
    unittest.main()
