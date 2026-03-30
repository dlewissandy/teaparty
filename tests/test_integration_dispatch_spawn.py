#!/usr/bin/env python3
"""Integration test: project-lead MUST spawn teammates via Agent/Task, not just SendMessage.

This is not a unit test — it runs a real Claude CLI invocation with the
uber-team agents config and a minimal execution task, then parses the
stream JSONL to verify the lead actually spawned a teammate agent.

Proves:
  1. The project-lead uses Agent/Task to spawn a teammate
  2. The spawned teammate actually starts (async launch confirmed)
  3. SendMessage alone is NOT the dispatch mechanism

Note: The CLI's init lists the tool as "Task" but ToolSearch resolves
it to "Agent". Both names are accepted.

Run:
  RUN_INTEGRATION_TESTS=1 PYTHONPATH=. python -m pytest projects/POC/orchestrator/tests/test_integration_dispatch_spawn.py -v -s

Requires: Claude CLI authenticated (claude.ai or API key).
"""
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


def _poc_root() -> str:
    return str(Path(__file__).parent.parent)


def _load_agents_json() -> str:
    """Load uber-team.json as a string for --agents flag."""
    path = os.path.join(_poc_root(), 'agents', 'uber-team.json')
    with open(path) as f:
        return f.read()


def _parse_stream(stream_path: str) -> list[dict]:
    """Parse a stream JSONL file into a list of events."""
    events = []
    with open(stream_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return events


def _extract_tool_calls(events: list[dict]) -> list[dict]:
    """Extract all tool_use blocks from assistant messages in stream events."""
    tool_calls = []
    for evt in events:
        if evt.get('type') != 'assistant':
            continue
        msg = evt.get('message', {})
        for block in msg.get('content', []):
            if isinstance(block, dict) and block.get('type') == 'tool_use':
                tool_calls.append(block)
    return tool_calls


def _extract_tool_results(events: list[dict]) -> list[dict]:
    """Extract all tool_result blocks from user messages in stream events."""
    results = []
    for evt in events:
        if evt.get('type') != 'user':
            continue
        msg = evt.get('message', {})
        for block in msg.get('content', []):
            if isinstance(block, dict) and block.get('type') == 'tool_result':
                results.append(block)
    return results


# Agent-spawning tool names: CLI init lists "Task" but ToolSearch resolves to "Agent"
SPAWN_TOOL_NAMES = frozenset({'Task', 'Agent'})
TEAMMATE_NAMES = frozenset({
    'qa-reviewer',
})
TEAMMATE_KEYWORDS = frozenset({'qa', 'review', 'test', 'verify'})


@unittest.skipUnless(
    os.environ.get('RUN_INTEGRATION_TESTS'),
    'Set RUN_INTEGRATION_TESTS=1 to run live Claude integration tests',
)
class TestProjectLeadSpawnsTeammateViaTask(unittest.TestCase):
    """Run a real Claude session and prove the lead spawns teammates via Task/Agent."""

    TIMEOUT = 120  # seconds

    def setUp(self):
        self.workdir = tempfile.mkdtemp(prefix='dispatch-test-')
        self.stream_file = os.path.join(self.workdir, 'exec-stream.jsonl')

        plan = textwrap.dedent("""\
            # Plan

            ## Objective
            Create a single file called hello.txt containing "hello world".

            ## Phase 1: Production
            Dispatch to the research-liaison to create the file.
            Done when hello.txt exists in the worktree.
        """)
        with open(os.path.join(self.workdir, 'PLAN.md'), 'w') as f:
            f.write(plan)

        intent = textwrap.dedent("""\
            # Intent
            Create hello.txt with "hello world".
            ## Success Criteria
            - hello.txt exists with the text "hello world"
        """)
        with open(os.path.join(self.workdir, 'INTENT.md'), 'w') as f:
            f.write(intent)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.workdir, ignore_errors=True)

    def _run_lead(self) -> list[dict]:
        """Run the project-lead with uber-team agents and return stream events."""
        agents_json = _load_agents_json()
        prompt = (
            "You are in the EXECUTION PHASE. Read PLAN.md and INTENT.md in your "
            "working directory, then execute the plan by delegating to your "
            "teammate(s) via the Task tool. Do NOT do the work yourself."
        )

        args = [
            'claude', '-p',
            '--output-format', 'stream-json',
            '--verbose',
            '--setting-sources', 'user',
            '--agents', agents_json,
            '--agent', 'project-lead',
            '--permission-mode', 'acceptEdits',
            '--max-turns', '5',
        ]

        env = dict(os.environ)
        env['CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS'] = '1'
        env['CLAUDE_CODE_MAX_OUTPUT_TOKENS'] = '16000'

        proc = subprocess.run(
            args,
            input=prompt,
            capture_output=True,
            text=True,
            cwd=self.workdir,
            env=env,
            timeout=self.TIMEOUT,
        )

        with open(self.stream_file, 'w') as f:
            f.write(proc.stdout)

        # Accept exit 0 (success) or max-turns (the lead may not finish
        # in 5 turns, but we only need to see the spawn call)
        self.assertIn(proc.returncode, (0, 1),
                      f"Claude CLI crashed (exit {proc.returncode}): "
                      f"{proc.stderr[:500]}")

        return _parse_stream(self.stream_file)

    def test_lead_spawns_teammate_via_agent_tool(self):
        """The project-lead MUST use Agent/Task tool to spawn at least one teammate.

        This is the core proof: the lead reads the plan, recognizes it needs
        to delegate to a teammate, and uses the agent-spawning tool (Agent or
        Task) — NOT just SendMessage.
        """
        events = self._run_lead()
        tool_calls = _extract_tool_calls(events)
        tool_results = _extract_tool_results(events)

        all_names = [tc['name'] for tc in tool_calls]

        # Find spawn calls (Agent or Task)
        spawn_calls = [tc for tc in tool_calls if tc['name'] in SPAWN_TOOL_NAMES]

        # Find SendMessage-only calls (the old broken pattern)
        send_calls = [tc for tc in tool_calls if tc['name'] == 'SendMessage']

        # ASSERTION 1: The lead used the spawn tool
        self.assertGreater(
            len(spawn_calls), 0,
            f"Lead never spawned a teammate! "
            f"Tools used: {all_names}. "
            f"SendMessage-only calls: {len(send_calls)}. "
            f"This means teammates were never started as processes."
        )

        # ASSERTION 2: The spawn call targets a teammate agent
        spawned_teammate = False
        for tc in spawn_calls:
            inp = tc.get('input', {})
            agent_type = inp.get('subagent_type', '')
            if agent_type in TEAMMATE_NAMES:
                spawned_teammate = True
                break
            # Fallback: check description/prompt for teammate keywords
            text = (inp.get('description', '') + ' ' + inp.get('prompt', '')).lower()
            if any(kw in text for kw in TEAMMATE_KEYWORDS):
                spawned_teammate = True
                break

        self.assertTrue(
            spawned_teammate,
            f"Spawn tool was called but not targeting a teammate. "
            f"Spawn inputs: {json.dumps([tc.get('input',{}) for tc in spawn_calls], indent=2)[:500]}"
        )

        # ASSERTION 3: The spawn call got a result (teammate actually started)
        spawn_ids = {tc['id'] for tc in spawn_calls}
        spawn_results = [
            tr for tr in tool_results
            if tr.get('tool_use_id') in spawn_ids
        ]
        self.assertGreater(
            len(spawn_results), 0,
            "Spawn call was made but no result received — teammate may not have started."
        )

        # ASSERTION 4: The result indicates async launch (not an error)
        for sr in spawn_results:
            content = str(sr.get('content', ''))
            self.assertNotIn(
                'error', content.lower().split('agent')[0] if 'agent' in content.lower() else content.lower(),
                f"Teammate spawn returned an error: {content[:200]}"
            )


if __name__ == '__main__':
    unittest.main()
