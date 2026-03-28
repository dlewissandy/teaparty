#!/usr/bin/env python3
"""Failing tests (TDD) for issue #128: Learning pipeline produces almost no output.

9 of 10 extraction scopes are structurally broken.  Each test class below
exposes a specific bug.  The tests are expected to FAIL against the current
codebase; fixes should make them pass.

Bug inventory:
  Bug 1 — extract_human_turns() returns empty for real intent streams where
           ALL user events contain tool_result blocks, not text blocks.
  Bug 2 — session.py never creates team infra subdirs (art/, writing/, etc.)
           so the 'team' rollup scope finds no dispatch MEMORYs.
  Bug 3 — dispatch_cli.py never writes MEMORY.md after dispatch completion,
           so even if team dirs existed they would be empty.
  Bug 4 — extract_learnings() has no event_bus parameter; errors go to stderr
           and never appear in the session log.
  Bug 5 — No summary diagnostic is emitted after all 10 scopes run.
"""
import asyncio
import inspect
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

# Add project root (five levels up from this file) to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.scripts.summarize_session import extract_human_turns, promote
from projects.POC.orchestrator.learnings import extract_learnings
from projects.POC.orchestrator.events import EventBus, EventType, Event


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _write_jsonl(path: str, events: list[dict]) -> None:
    """Write a list of dicts as a JSONL file (one JSON object per line)."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w') as f:
        for ev in events:
            f.write(json.dumps(ev) + '\n')


def _make_assistant_event(text: str = "I will help with that.") -> dict:
    """Create a realistic assistant event."""
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
        "parent_tool_use_id": None,
        "session_id": "sess-001",
    }


def _make_tool_result_user_event(
    content: str,
    tool_use_id: str = "toolu_01ABC",
    parent_tool_use_id: str = None,
) -> dict:
    """Create a user event whose content is a tool_result block.

    This is the format that human approvals and agent feedback arrive in during
    real intent streams.  The current extract_human_turns() only looks for
    type=='text' blocks and will miss these entirely.
    """
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "content": content,
                    "tool_use_id": tool_use_id,
                }
            ],
        },
        "parent_tool_use_id": parent_tool_use_id,
        "session_id": "sess-001",
    }


def _make_text_user_event(text: str, parent_tool_use_id: str = None) -> dict:
    """Create a user event with a text block (the format the current code expects)."""
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": text}],
        },
        "parent_tool_use_id": parent_tool_use_id,
        "session_id": "sess-001",
    }


# ── Bug 1: extract_human_turns() with real stream format ──────────────────────

class TestExtractHumanTurnsWithRealStreamFormat(unittest.TestCase):
    """Bug 1: extract_human_turns() returns empty when user events use tool_result blocks.

    In production intent streams, ALL user events carry tool_result blocks —
    human approvals ("approve"), corrections, and follow-up instructions all
    arrive this way.  The current implementation only checks for type=="text"
    blocks and finds nothing.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _stream(self, name: str = 'stream.jsonl') -> str:
        return os.path.join(self.tmpdir, name)

    def test_extracts_approval_text_from_tool_result(self):
        """Human approval ('approve') arrives as a tool_result block and must be captured.

        Bug: extract_human_turns() looks for type=='text' blocks only.
        A tool_result carrying 'approve' is skipped because it has no text block.
        """
        stream = self._stream()
        _write_jsonl(stream, [
            _make_assistant_event("Here is my plan. Please approve or reject."),
            _make_tool_result_user_event("approve", tool_use_id="toolu_01ABC"),
        ])

        result = extract_human_turns(stream)

        self.assertTrue(
            result.strip(),
            "Expected non-empty output — 'approve' in tool_result should be captured",
        )
        self.assertIn(
            "approve", result,
            "Expected 'approve' text to appear in extracted human turns",
        )

    def test_extracts_human_correction_from_tool_result(self):
        """Human corrections mid-session arrive as tool_result blocks.

        Bug: The correction 'no, use the other approach instead' is delivered
        as a tool_result block and is silently skipped by extract_human_turns().

        This is a distinct scenario from approval — the content is multi-word
        corrective instruction, not a single keyword.  The fix must handle
        both short approvals and longer corrections.
        """
        correction = "no, use the other approach instead"
        stream = self._stream()
        _write_jsonl(stream, [
            _make_assistant_event("I'll write the module now."),
            _make_tool_result_user_event(correction, tool_use_id="toolu_02DEF"),
        ])

        result = extract_human_turns(stream)

        self.assertIn(
            correction, result,
            f"Expected correction text to be captured, got: {result!r}",
        )

    def test_extracts_human_text_from_mixed_stream(self):
        """Short human instruction in a tool_result should be captured; long file content should not.

        The challenge: tool_results carry both agent-to-agent content (large
        file reads) and human instructions.  The function must distinguish
        them.  At minimum, a short human instruction ('use snake_case') must
        appear in output.  This test does NOT require that file content is
        excluded — it just requires that the human turn is present.
        """
        human_instruction = "use snake_case for all variable names"
        stream = self._stream()
        _write_jsonl(stream, [
            _make_assistant_event("Checking the codebase."),
            # Agent-to-agent tool result — large file content
            _make_tool_result_user_event(
                "x" * 5000,  # simulated file read content
                tool_use_id="toolu_03GHI",
                parent_tool_use_id="toolu_03GHI",
            ),
            _make_assistant_event("I found the files."),
            # Human correction arriving as tool_result with no parent_tool_use_id
            _make_tool_result_user_event(
                human_instruction,
                tool_use_id="toolu_04JKL",
                parent_tool_use_id=None,
            ),
        ])

        result = extract_human_turns(stream)

        self.assertIn(
            human_instruction, result,
            f"Expected human instruction to be captured, got: {result!r}",
        )

    def test_returns_empty_for_stream_with_only_agent_traffic(self):
        """A stream with only assistant events and large tool_results should produce empty output.

        Agent-to-agent tool results (file reads, task outputs, etc.) must not
        be captured as human turns.  We identify these by checking
        parent_tool_use_id is non-null (they are responses to tool calls).
        """
        stream = self._stream()
        _write_jsonl(stream, [
            _make_assistant_event("Reading files now."),
            # These are tool results from the agent's own tool calls (parent set)
            _make_tool_result_user_event(
                "file contents here...\n" * 100,
                tool_use_id="toolu_AGENT_1",
                parent_tool_use_id="toolu_AGENT_1",  # non-null → agent traffic
            ),
            _make_assistant_event("Done processing."),
            _make_tool_result_user_event(
                "more agent output " * 50,
                tool_use_id="toolu_AGENT_2",
                parent_tool_use_id="toolu_AGENT_2",  # non-null → agent traffic
            ),
        ])

        result = extract_human_turns(stream)

        # Agent-to-agent traffic should not be captured
        # (The function may still return something for the first 'user' event
        # with no parent, so we check that file-like content isn't present)
        self.assertNotIn(
            "file contents here",
            result,
            "Agent tool result content should not be captured as human speech",
        )
        self.assertNotIn(
            "more agent output",
            result,
            "Agent tool result content should not be captured as human speech",
        )


# ── Bug 2: Session lifecycle must create team infrastructure dirs ──────────────

class TestSessionCreatesTeamInfraDirs(unittest.TestCase):
    """Bug 2: create_session_worktree() creates infra_dir but not team subdirs.

    promote('team') in summarize_session.py scans infra_dir for team subdirs
    (art/, writing/, coding/, editorial/, research/) to find dispatch MEMORY.md
    files.  Since create_session_worktree() never creates these dirs, the scan
    always finds nothing and all 4 rollup scopes produce zero output.
    """

    TEAM_NAMES = ['art', 'writing', 'coding', 'editorial', 'research', 'configuration']

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.projects_dir = os.path.join(self.tmpdir, 'projects')
        os.makedirs(os.path.join(self.projects_dir, 'test-project'), exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_session_creates_team_dirs_in_infra(self):
        """create_session_worktree() must create team subdirs in infra_dir.

        Bug: worktree.py line 41-42 creates infra_dir via os.makedirs() but
        does not create team subdirs inside it.  The fix should add team dir
        creation to create_session_worktree() (or to session.py after the
        call returns).

        We call create_session_worktree() with git mocked out and verify
        the returned infra_dir contains team subdirectories.
        """
        from projects.POC.orchestrator.worktree import create_session_worktree

        async def _test():
            with patch('projects.POC.orchestrator.worktree._run_git',
                       new=AsyncMock()), \
                 patch('projects.POC.orchestrator.worktree._register_worktree'):
                result = await create_session_worktree(
                    project_slug='test-project',
                    task='test task',
                    repo_root=self.tmpdir,
                    projects_dir=self.projects_dir,
                    session_id='20260314-120000',
                )
            return result

        result = _run(_test())
        infra_dir = result['infra_dir']

        self.assertTrue(
            os.path.isdir(infra_dir),
            f"infra_dir {infra_dir!r} should exist",
        )
        for team in self.TEAM_NAMES:
            team_dir = os.path.join(infra_dir, team)
            self.assertTrue(
                os.path.isdir(team_dir),
                f"Expected team dir {team_dir!r} to exist after "
                f"create_session_worktree() — needed for dispatch MEMORY.md "
                f"rollup chain",
            )


# ── Bug 3: dispatch_cli.py never writes MEMORY.md ─────────────────────────────

class TestDispatchWritesMemory(unittest.TestCase):
    """Bug 3: dispatch_cli.dispatch() never writes a MEMORY.md file.

    The rollup chain expects: infra_dir/{team}/{dispatch_id}/MEMORY.md
    dispatch_cli.py runs the dispatch, merges results, and returns a JSON
    status dict — but never writes MEMORY.md.  Even if the team dirs existed,
    the rollup would find nothing to roll up.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_dispatch_writes_memory_md_after_completion(self):
        """After a successful dispatch, MEMORY.md must exist in the dispatch infra dir.

        Bug: dispatch_cli.py runs the orchestrator, merges results, cleans up
        the worktree, and returns — but never writes MEMORY.md to the dispatch
        infra dir.  The fix should write one before returning.

        Approach: we mock the minimal set of dependencies at the boundaries
        (worktree creation, orchestrator, git operations) and let dispatch()
        drive the flow.  The dispatch infra dir is created by
        create_dispatch_worktree() — we provide a real temp dir for it so the
        MEMORY.md write (when fixed) has a real filesystem to target.
        """
        from projects.POC.orchestrator.dispatch_cli import dispatch
        from projects.POC.orchestrator.engine import OrchestratorResult

        # The dispatch infra dir where MEMORY.md should be written
        session_infra = os.path.join(self.tmpdir, 'session-infra')
        dispatch_infra = os.path.join(session_infra, 'coding', '20260314-120000')
        worktree_path = os.path.join(self.tmpdir, 'worktree')
        os.makedirs(dispatch_infra)
        os.makedirs(worktree_path)

        # Create a CfA state file so dispatch() doesn't bail at the exists() check
        cfa_path = os.path.join(session_infra, '.cfa-state.json')
        os.makedirs(session_infra, exist_ok=True)
        Path(cfa_path).write_text(json.dumps({
            'state': 'TASK', 'task_id': 'parent', 'history': [],
            'phase': 'execution', 'backtrack_count': 0,
        }))

        # Minimal mock returns
        fake_dispatch_info = {
            'worktree_path': worktree_path,
            'infra_dir': dispatch_infra,
            'dispatch_id': '20260314-120000',
            'worktree_name': 'coding-120000--test-task',
            'branch_name': 'coding-120000--test-task',
        }
        completed = OrchestratorResult(
            terminal_state='COMPLETED_WORK',
            backtrack_count=0,
            escalation_type='',
        )
        mock_orch = MagicMock()
        mock_orch.run = AsyncMock(return_value=completed)

        with patch.dict(os.environ, {
            'POC_SESSION_WORKTREE': self.tmpdir,
            'POC_SESSION_DIR': session_infra,
            'POC_PROJECT': 'test-project',
        }), \
            patch('projects.POC.orchestrator.dispatch_cli.create_dispatch_worktree',
                  new=AsyncMock(return_value=fake_dispatch_info)), \
            patch('projects.POC.orchestrator.dispatch_cli.load_state',
                  return_value={'state': 'TASK', 'task_id': 'p', 'history': [],
                                'phase': 'execution', 'backtrack_count': 0}), \
            patch('projects.POC.orchestrator.dispatch_cli.make_child_state',
                  return_value={'state': 'TASK', 'task_id': 'c', 'history': [],
                                'phase': 'execution', 'backtrack_count': 0}), \
            patch('projects.POC.orchestrator.dispatch_cli.save_state'), \
            patch('projects.POC.orchestrator.dispatch_cli.Orchestrator',
                  return_value=mock_orch), \
            patch('projects.POC.orchestrator.dispatch_cli.squash_merge',
                  new=AsyncMock()), \
            patch('projects.POC.orchestrator.dispatch_cli.git_output',
                  new=AsyncMock(return_value='')), \
            patch('projects.POC.orchestrator.dispatch_cli.generate_async',
                  new=AsyncMock(return_value='test commit')), \
            patch('projects.POC.orchestrator.dispatch_cli.cleanup_worktree',
                  new=AsyncMock()):
            result = _run(dispatch(team='coding', task='Test task'))

        self.assertEqual(result.get('status'), 'completed')

        memory_path = os.path.join(dispatch_infra, 'MEMORY.md')
        self.assertTrue(
            os.path.isfile(memory_path),
            f"Expected MEMORY.md at {memory_path!r} after successful dispatch — "
            f"dispatch_cli.py must write this file for the rollup chain to work. "
            f"Contents of dispatch infra: {os.listdir(dispatch_infra)}",
        )


# ── Bug 4: extract_learnings() has no event_bus parameter ─────────────────────

class TestExtractLearningsObservability(unittest.TestCase):
    """Bug 4 & 5: extract_learnings() has no event_bus and emits no diagnostics.

    Bug 4: The function signature is missing an event_bus parameter.
           session.py has self.event_bus at the call site (line 252-259)
           but doesn't pass it.  Learning errors go to stderr only.

    Bug 5: No "N/10 scopes succeeded, M failed" summary is emitted anywhere
           after all scopes run.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.infra_dir = os.path.join(self.tmpdir, 'infra')
        self.project_dir = os.path.join(self.tmpdir, 'project')
        self.poc_root = self.tmpdir
        os.makedirs(self.infra_dir)
        os.makedirs(self.project_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_extract_learnings_accepts_event_bus(self):
        """extract_learnings() must accept an event_bus keyword argument.

        Bug: The current signature is:
            async def extract_learnings(*, infra_dir, project_dir,
                                        session_worktree, task, poc_root)

        There is no event_bus parameter.  The fix must add it so session.py
        can pass self.event_bus.
        """
        sig = inspect.signature(extract_learnings)
        self.assertIn(
            'event_bus',
            sig.parameters,
            "extract_learnings() must accept an 'event_bus' keyword argument — "
            "session.py needs to pass self.event_bus so learning errors appear "
            "in the session log rather than going silently to stderr",
        )

    def test_extract_learnings_emits_scope_events(self):
        """With an event_bus provided, scope success/failure events must be emitted.

        Bug: Even if event_bus were accepted, no events are published.
        The fix should publish an event for each scope's outcome.
        """
        event_bus = EventBus()
        received_events = []

        async def _capture(event: Event) -> None:
            received_events.append(event)

        event_bus.subscribe(_capture)

        with patch('projects.POC.orchestrator.learnings._run_summarize'), \
             patch('projects.POC.orchestrator.learnings._call_promote'):
            _run(extract_learnings(
                infra_dir=self.infra_dir,
                project_dir=self.project_dir,
                session_worktree=self.tmpdir,
                task='Test task',
                poc_root=self.poc_root,
                event_bus=event_bus,
            ))

        # At least one event should have been published relating to learnings
        learning_events = [
            e for e in received_events
            if 'learning' in str(e.type).lower() or 'learning' in str(e.data).lower()
               or e.type == EventType.LOG
        ]
        self.assertTrue(
            len(learning_events) > 0,
            f"Expected learning-related events to be emitted through EventBus, "
            f"got {len(received_events)} total events: "
            f"{[str(e.type) for e in received_events]}",
        )

    def test_extract_learnings_emits_summary_diagnostic(self):
        """After all 10 scopes, a summary event with success/failure counts must be emitted.

        Bug 5: No summary diagnostic exists anywhere in the current code.
        After all scopes run, users have no visibility into how many succeeded
        or failed.  The fix should emit a summary event like:
            '10/10 learning scopes completed (8 succeeded, 2 failed)'
        """
        event_bus = EventBus()
        received_events = []

        async def _capture(event: Event) -> None:
            received_events.append(event)

        event_bus.subscribe(_capture)

        with patch('projects.POC.orchestrator.learnings._run_summarize'), \
             patch('projects.POC.orchestrator.learnings._call_promote'):
            _run(extract_learnings(
                infra_dir=self.infra_dir,
                project_dir=self.project_dir,
                session_worktree=self.tmpdir,
                task='Test task',
                poc_root=self.poc_root,
                event_bus=event_bus,
            ))

        # Look for a summary event that mentions scope counts
        summary_events = []
        for e in received_events:
            data_str = json.dumps(e.data)
            if ('scope' in data_str and ('success' in data_str or 'fail' in data_str)) \
               or ('10' in data_str and 'learning' in data_str.lower()):
                summary_events.append(e)

        self.assertTrue(
            len(summary_events) > 0,
            f"Expected a summary event with scope success/failure counts — "
            f"'N/10 scopes succeeded, M failed' — but got no matching events. "
            f"Events received: {[e.data for e in received_events]}",
        )


# ── Bug integration: rollup chain end-to-end ──────────────────────────────────

class TestRollupChainEndToEnd(unittest.TestCase):
    """Integration test: the full rollup chain produces output when inputs exist.

    This test wires up all the pieces: team dirs with dispatch MEMORY.md files,
    mocked summarize() returning formatted output, and the full promote() chain.
    It verifies that output files are written at each level.

    This test exposes bugs 2 and 3 simultaneously: without team dirs and
    without MEMORY.md files, the entire rollup chain produces nothing.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.session_dir = os.path.join(self.tmpdir, 'session')
        self.project_dir = os.path.join(self.tmpdir, 'project')
        self.projects_dir = self.tmpdir
        os.makedirs(self.session_dir)
        os.makedirs(self.project_dir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_dispatch_memory(self, team: str, dispatch: str = 'dispatch-001') -> str:
        """Create a realistic dispatch MEMORY.md in the team dir."""
        path = os.path.join(self.session_dir, team, dispatch, 'MEMORY.md')
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(
            "## [2026-01-01] Dispatch Learning\n"
            "**Context:** Dispatch executed coding task\n"
            "**Learning:** File writes should be batched\n"
            "**Action:** Prefer batching writes in future dispatches\n"
        )
        return path

    def _fake_summarize_with_output(self, stream, output, ctx, scope, **kw):
        """Fake summarize that actually writes the output file."""
        content = (
            f"## [2026-01-01] {scope} Learning\n"
            f"**Context:** Rollup test\n"
            f"**Learning:** Test learning\n"
            f"**Action:** Test action\n"
        )
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        with open(output, 'a') as f:
            f.write('\n\n' + content + '\n')
        return 0

    def test_rollup_chain_produces_output_with_dispatch_memories(self):
        """The full team→session→project→global rollup chain must produce output files.

        Setup:
          - session_dir/coding/dispatch-001/MEMORY.md  (exists)
          - session_dir/art/dispatch-001/MEMORY.md     (exists)

        Expected after promote('team', ...):
          - session_dir/coding/institutional.md        (created)
          - session_dir/art/institutional.md           (created)

        Expected after promote('session', ...):
          - session_dir/institutional.md               (created)

        Expected after promote('project', ...):
          - project_dir/institutional.md               (created)

        These currently fail because:
          Bug 2: session.py never creates the team dirs, so dispatch_cli
                 writes MEMORY.md into non-existent locations.
          Bug 3: dispatch_cli never writes MEMORY.md even if dirs existed.
        """
        # Create team dirs AND dispatch MEMORYs (simulating both bugs fixed)
        self._make_dispatch_memory('coding')
        self._make_dispatch_memory('art')

        # Team scope: dispatch MEMORYs → team institutional.md files
        with patch('projects.POC.scripts.summarize_session.summarize',
                   side_effect=self._fake_summarize_with_output):
            team_result = promote('team', self.session_dir, '', '')

        self.assertEqual(team_result, 0, "promote('team') should return 0")

        coding_inst = os.path.join(self.session_dir, 'coding', 'institutional.md')
        art_inst = os.path.join(self.session_dir, 'art', 'institutional.md')

        self.assertTrue(
            os.path.isfile(coding_inst),
            f"Expected coding/institutional.md to be created by team rollup at {coding_inst}",
        )
        self.assertTrue(
            os.path.isfile(art_inst),
            f"Expected art/institutional.md to be created by team rollup at {art_inst}",
        )

        # Session scope: team institutional.md files → session institutional.md
        with patch('projects.POC.scripts.summarize_session.summarize',
                   side_effect=self._fake_summarize_with_output):
            with patch('projects.POC.scripts.summarize_session._try_compact'):
                session_result = promote('session', self.session_dir, '', '')

        self.assertEqual(session_result, 0, "promote('session') should return 0")

        session_inst = os.path.join(self.session_dir, 'institutional.md')
        self.assertTrue(
            os.path.isfile(session_inst),
            f"Expected session/institutional.md to be created by session rollup at {session_inst}",
        )

        # Project scope: session institutional.md → project institutional.md
        with patch('projects.POC.scripts.summarize_session.summarize',
                   side_effect=self._fake_summarize_with_output):
            with patch('projects.POC.scripts.summarize_session._try_compact'):
                project_result = promote(
                    'project', self.session_dir, self.project_dir, ''
                )

        self.assertEqual(project_result, 0, "promote('project') should return 0")

        project_inst = os.path.join(self.project_dir, 'institutional.md')
        self.assertTrue(
            os.path.isfile(project_inst),
            f"Expected project/institutional.md to be created by project rollup at {project_inst}",
        )


if __name__ == '__main__':
    unittest.main()
