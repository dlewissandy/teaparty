#!/usr/bin/env python3
"""Regression tests for issue #121: execution lead must delegate, not do work itself.

Root causes (original):
 1. Execution phase permissions.allow missing SendMessage and Bash —
    the lead can't talk to teammates, teammates can't run commands
 2. Project-lead prompt doesn't mention SendMessage as a delegation tool
 3. Liaison prompts reference nonexistent dispatch.sh instead of dispatch_cli.py

Corrected dispatch mechanism (follow-up fix):
 4. The lead was told to use SendMessage to delegate — but SendMessage only queues
    inbox messages; it doesn't spawn agent processes.  Agents were never started.
    Fix: the lead now uses Task to spawn each agent as a background process, then
    uses SendMessage for follow-up coordination with already-running agents.
    Task and TaskOutput must be in execution phase permissions.allow.

Updated for issue #271: uber-team.json migrated from liaison architecture to
project-lead + qa-reviewer per project.yaml proposal. project-team.json removed.
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
        """SendMessage must be in permissions.allow — the lead uses it to coordinate with teammates."""
        self.assertIn('SendMessage', self.allowed,
                      "Execution lead cannot coordinate without SendMessage permission")

    def test_bash_is_allowed(self):
        """Bash must be in permissions.allow — needed for running commands."""
        self.assertIn('Bash', self.allowed)

    def test_write_is_allowed(self):
        """Write must be in permissions.allow — for checkpoint files and escalation notes."""
        self.assertIn('Write', self.allowed)

    def test_edit_is_allowed(self):
        """Edit must be in permissions.allow."""
        self.assertIn('Edit', self.allowed)

    def test_task_is_allowed(self):
        """Task must be in permissions.allow — the lead uses it to spawn background agents."""
        self.assertIn('Task', self.allowed,
                      "Execution lead cannot spawn agents without Task permission")

    def test_taskoutput_is_allowed(self):
        """TaskOutput must be in permissions.allow — the lead uses it to check agent progress."""
        self.assertIn('TaskOutput', self.allowed,
                      "Execution lead cannot monitor agents without TaskOutput permission")


# ── Test: project-lead prompt mentions SendMessage ────────────────────────────

class TestProjectLeadPrompt(unittest.TestCase):
    """The project-lead prompt must instruct correct delegation."""

    def setUp(self):
        agents = _load_agents_file('uber-team.json')
        self.prompt = agents['project-lead']['prompt']

    def test_prompt_mentions_sendmessage(self):
        """The prompt must tell the lead that SendMessage is available."""
        self.assertIn('SendMessage', self.prompt,
                      "Lead prompt must mention SendMessage so the agent knows how to coordinate")


# ── Test: intent-team research-liaison uses dispatch_cli ─────────────────────

class TestIntentTeamDispatch(unittest.TestCase):
    """The intent-team research-liaison must use dispatch_cli, not dispatch.sh."""

    def test_intent_team_research_liaison(self):
        agents = _load_agents_file('intent-team.json')
        prompt = agents['research-liaison']['prompt']
        self.assertNotIn('dispatch.sh', prompt,
                         "research-liaison prompt references nonexistent dispatch.sh")
        self.assertIn('dispatch_cli', prompt,
                      "research-liaison prompt must reference dispatch_cli for dispatching")


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


if __name__ == '__main__':
    unittest.main()
