#!/usr/bin/env python3
"""Regression tests for issue #121: execution lead must delegate, not do work itself.

Root causes (original):
 1. Execution phase permissions.allow missing SendMessage and Bash —
    the lead can't talk to liaisons, liaisons can't run dispatch_cli.py
 2. Project-lead prompt doesn't mention SendMessage as a delegation tool
 3. Liaison prompts reference nonexistent dispatch.sh instead of dispatch_cli.py

Corrected dispatch mechanism (follow-up fix):
 4. The lead was told to use SendMessage to delegate — but SendMessage only queues
    inbox messages; it doesn't spawn agent processes.  Liaisons were never started.
    Fix: the lead now uses Task to spawn each liaison as a background agent, then
    uses SendMessage for follow-up coordination with already-running agents.
    Task and TaskOutput must be in execution phase permissions.allow.

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
        """SendMessage must be in permissions.allow — the lead uses it to coordinate with running liaisons."""
        self.assertIn('SendMessage', self.allowed,
                      "Execution lead cannot coordinate without SendMessage permission")

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

    def test_task_is_allowed(self):
        """Task must be in permissions.allow — the lead uses it to spawn liaison background agents."""
        self.assertIn('Task', self.allowed,
                      "Execution lead cannot spawn liaisons without Task permission")

    def test_taskoutput_is_allowed(self):
        """TaskOutput must be in permissions.allow — the lead uses it to check liaison progress."""
        self.assertIn('TaskOutput', self.allowed,
                      "Execution lead cannot monitor liaisons without TaskOutput permission")


# ── Test: project-lead prompt mentions SendMessage ────────────────────────────

class TestProjectLeadPrompt(unittest.TestCase):
    """The project-lead prompt must instruct correct delegation: Task to spawn, SendMessage to coordinate."""

    def setUp(self):
        agents = _load_agents_file('uber-team.json')
        self.prompt = agents['project-lead']['prompt']
        exec_idx = self.prompt.find('EXECUTION PHASE')
        self.assertGreater(exec_idx, -1, "Prompt must contain an EXECUTION PHASE section")
        self.exec_section = self.prompt[exec_idx:]

    def test_prompt_mentions_sendmessage(self):
        """The prompt must tell the lead that SendMessage is available."""
        self.assertIn('SendMessage', self.prompt,
                      "Lead prompt must mention SendMessage so the agent knows how to coordinate")

    def test_prompt_instructs_delegation_via_sendmessage(self):
        """The execution phase section must reference SendMessage (for follow-up coordination)."""
        self.assertIn('SendMessage', self.exec_section,
                      "EXECUTION PHASE section must reference SendMessage for coordination")

    def test_prompt_discourages_direct_file_reading(self):
        """The prompt must tell the lead NOT to read source files directly."""
        self.assertTrue(
            'NOT read source files' in self.exec_section or
            'Do not read source files' in self.exec_section or
            'not read source' in self.exec_section.lower(),
            "EXECUTION PHASE must discourage direct source file reading"
        )

    def test_prompt_mentions_task_tool_in_execution_phase(self):
        """The execution phase section must mention the Task tool for spawning liaisons."""
        self.assertIn('Task', self.exec_section,
                      "EXECUTION PHASE must mention Task tool for spawning liaison agents")

    def test_prompt_mentions_taskoutput_in_execution_phase(self):
        """The execution phase section must mention TaskOutput for monitoring liaison progress."""
        self.assertIn('TaskOutput', self.exec_section,
                      "EXECUTION PHASE must mention TaskOutput to monitor liaison progress")


# ── Test: project-lead prompt — correct spawn/coordination split ──────────────

class TestProjectLeadSpawnsLiaisons(unittest.TestCase):
    """The project-lead prompt must use Task to spawn liaisons, not SendMessage."""

    def setUp(self):
        agents = _load_agents_file('uber-team.json')
        self.prompt = agents['project-lead']['prompt']
        exec_idx = self.prompt.find('EXECUTION PHASE')
        self.assertGreater(exec_idx, -1, "Prompt must contain an EXECUTION PHASE section")
        self.exec_section = self.prompt[exec_idx:]

    def test_execution_phase_has_spawning_liaisons_section(self):
        """The execution phase must have a SPAWNING LIAISONS section."""
        self.assertIn('SPAWNING LIAISONS', self.exec_section,
                      "EXECUTION PHASE must contain a SPAWNING LIAISONS section")

    def test_task_is_spawn_mechanism(self):
        """The SPAWNING LIAISONS section must identify Task as the tool used to spawn liaisons."""
        spawn_idx = self.exec_section.find('SPAWNING LIAISONS')
        self.assertGreater(spawn_idx, -1)
        # Grab text from that section heading forward
        spawn_section = self.exec_section[spawn_idx:]
        self.assertTrue(
            'Task tool' in spawn_section or
            'Task(' in spawn_section or
            'spawn' in spawn_section,
            "SPAWNING LIAISONS section must describe the Task tool as the spawn mechanism"
        )

    def test_taskoutput_mentioned_for_monitoring(self):
        """The prompt must tell the lead to use TaskOutput to check liaison progress."""
        self.assertTrue(
            'TaskOutput' in self.exec_section,
            "EXECUTION PHASE must tell the lead to use TaskOutput to monitor liaison progress"
        )

    def test_task_is_not_cfa_task(self):
        """The prompt must distinguish the Task tool from a CfA (Commit for Approval) task."""
        # The prompt should contain language clarifying Task-tool vs CfA task
        self.assertTrue(
            'NOT a CfA task' in self.exec_section or
            'not a CfA task' in self.exec_section or
            'background agent' in self.exec_section or
            'runs independently' in self.exec_section,
            "EXECUTION PHASE must clarify that Task spawns a background agent, not a CfA task"
        )

    def test_sendmessage_not_used_to_start_work(self):
        """The prompt must warn against using SendMessage alone to start work."""
        self.assertTrue(
            'do NOT use SendMessage to start' in self.exec_section or
            'do not use SendMessage to start' in self.exec_section.lower() or
            'not running, nobody reads it' in self.exec_section or
            'SendMessage to start work' in self.exec_section,
            "EXECUTION PHASE must warn that SendMessage cannot start work on its own"
        )

    def test_coordination_section_present(self):
        """The execution phase must have a COORDINATION section."""
        self.assertIn('COORDINATION', self.exec_section,
                      "EXECUTION PHASE must contain a COORDINATION section")

    def test_dispatch_pattern_section_present(self):
        """The execution phase must have a DISPATCH PATTERN section."""
        self.assertIn('DISPATCH PATTERN', self.exec_section,
                      "EXECUTION PHASE must contain a DISPATCH PATTERN section")

    def test_dispatch_pattern_starts_with_task(self):
        """The DISPATCH PATTERN section must instruct spawning via Task as the first step."""
        pattern_idx = self.exec_section.find('DISPATCH PATTERN')
        self.assertGreater(pattern_idx, -1)
        pattern_section = self.exec_section[pattern_idx:]
        # The first substantive action step should mention Task or spawn
        self.assertTrue(
            'Task' in pattern_section,
            "DISPATCH PATTERN must include the Task tool in its step-by-step instructions"
        )

    def test_dispatch_pattern_includes_taskoutput_step(self):
        """The DISPATCH PATTERN section must include a TaskOutput monitoring step."""
        pattern_idx = self.exec_section.find('DISPATCH PATTERN')
        self.assertGreater(pattern_idx, -1)
        pattern_section = self.exec_section[pattern_idx:]
        self.assertIn('TaskOutput', pattern_section,
                      "DISPATCH PATTERN must include a TaskOutput step for monitoring progress")

    def test_prompt_references_available_teams(self):
        """Project-lead prompt must reference Available Teams for dynamic injection.

        Issue #141: liaison list is now dynamically injected via the
        Available Teams context block, not hardcoded in the prompt.
        """
        self.assertIn('Available Teams', self.prompt,
                      "project-lead prompt must reference 'Available Teams' for dynamic injection")


# ── Test: liaison prompts reference dispatch mechanism, not dispatch.sh ───────

class TestLiaisonDispatchCommand(unittest.TestCase):
    """All liaison prompts must reference a dispatch mechanism, not the defunct dispatch.sh.

    Note: uber-team.json liaisons were updated in issue #144 to use the AskTeam
    MCP tool instead of dispatch_cli subprocess calls.  project-team.json and
    intent-team.json still use dispatch_cli directly.
    """

    def _assert_liaison_uses_dispatch_cli(self, agents: dict, liaison_name: str):
        prompt = agents[liaison_name]['prompt']
        self.assertNotIn('dispatch.sh', prompt,
                         f"{liaison_name} prompt references nonexistent dispatch.sh")
        self.assertIn('dispatch_cli', prompt,
                      f"{liaison_name} prompt must reference dispatch_cli for dispatching")

    def _assert_liaison_uses_ask_team(self, agents: dict, liaison_name: str):
        """uber-team liaisons use AskTeam MCP tool (issue #144)."""
        prompt = agents[liaison_name]['prompt']
        self.assertNotIn('dispatch.sh', prompt,
                         f"{liaison_name} prompt references nonexistent dispatch.sh")
        self.assertIn('AskTeam', prompt,
                      f"{liaison_name} prompt must reference AskTeam for dispatching")

    def test_uber_team_liaisons(self):
        """All liaisons in uber-team.json must use AskTeam (issue #144 migration)."""
        agents = _load_agents_file('uber-team.json')
        for name in ['art-liaison', 'writing-liaison', 'editorial-liaison',
                      'research-liaison', 'coding-liaison']:
            with self.subTest(liaison=name):
                self._assert_liaison_uses_ask_team(agents, name)

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


# ── Test: uber-team.json liaisons dispatch to the correct team name ───────────

class TestLiaisonDispatchTeamNames(unittest.TestCase):
    """Each liaison must dispatch to the correct team.

    After issue #144 migration, uber-team liaisons use AskTeam(team="X", ...)
    instead of dispatch_cli --team X.
    """

    def setUp(self):
        self.agents = _load_agents_file('uber-team.json')

    def test_art_liaison_dispatches_to_art(self):
        self.assertIn('team="art"', self.agents['art-liaison']['prompt'])

    def test_writing_liaison_dispatches_to_writing(self):
        self.assertIn('team="writing"', self.agents['writing-liaison']['prompt'])

    def test_editorial_liaison_dispatches_to_editorial(self):
        self.assertIn('team="editorial"', self.agents['editorial-liaison']['prompt'])

    def test_research_liaison_dispatches_to_research(self):
        self.assertIn('team="research"', self.agents['research-liaison']['prompt'])

    def test_coding_liaison_dispatches_to_coding(self):
        self.assertIn('team="coding"', self.agents['coding-liaison']['prompt'])


if __name__ == '__main__':
    unittest.main()
