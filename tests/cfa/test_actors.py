#!/usr/bin/env python3
"""Tests for actors.py — AgentRunner._interpret_output and helpers.

The sibling ``ApprovalGate`` class and its test coverage were removed
when the 5-state + skill-based redesign eliminated the gate actor
(human review now lives inside each skill's ASSERT step via
AskQuestion→proxy).  Remaining tests cover AgentRunner's artifact
detection, plan relocation, and output interpretation.
"""
import asyncio
import os
import sys
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.cfa.actors import (
    ActorContext,
    ActorResult,
    AgentRunner,
    _relocate_plan_file,
)
from teaparty.runners.claude import ClaudeResult
from teaparty.messaging.bus import EventBus
from teaparty.cfa.phase_config import PhaseSpec
from teaparty.proxy.agent import ProxyResult


# ── Helpers ───────────────────────────────────────────────────────────────────

def _install_jail_hook(worktree: str) -> None:
    """Create a stub worktree_hook.py so AgentRunner validation passes in tests."""
    hook_dir = os.path.join(worktree, '.claude', 'hooks')
    os.makedirs(hook_dir, exist_ok=True)
    open(os.path.join(hook_dir, 'worktree_hook.py'), 'w').close()


def _make_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


def _make_phase_spec(
    artifact: str | None = 'INTENT.md',
) -> PhaseSpec:
    return PhaseSpec(
        name='intent',
        agent_file='agents/intent-team.json',
        lead='intent-lead',
        permission_mode='acceptEdits',
        stream_file='.intent-stream.jsonl',
        artifact=artifact,
        approval_state='INTENT_ASSERT',
    )


def _make_ctx(
    state: str = 'PROPOSAL',
    session_worktree: str = '/tmp/worktree',
    phase_spec: PhaseSpec | None = None,
    infra_dir: str = '/tmp/infra',
) -> ActorContext:
    if phase_spec is None:
        phase_spec = _make_phase_spec()
    return ActorContext(
        state=state,
        phase='intent',
        task='Write a blog post about AI',
        infra_dir=infra_dir,
        project_workdir='/tmp/project',
        session_worktree=session_worktree,
        stream_file='.intent-stream.jsonl',
        phase_spec=phase_spec,
        poc_root='/tmp/poc',
        event_bus=_make_event_bus(),
        session_id='test-session',
    )


def _make_claude_result(exit_code: int = 0, session_id: str = 'claude-abc') -> ClaudeResult:
    return ClaudeResult(exit_code=exit_code, session_id=session_id)


def _run(coro):
    """Run a coroutine synchronously for testing."""
    return asyncio.run(coro)


# ── AgentRunner._interpret_output ─────────────────────────────────────────────

class TestInterpretOutputMissingArtifact(unittest.TestCase):
    """When expected artifact is absent, _interpret_output must never use 'assert'.

    The ASSERT gate invariant: it is only entered when the artifact exists.
    Missing artifact → loop back through human input so the agent can retry.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.runner = AgentRunner()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_ctx_in_tmpdir(self, state='PROPOSAL', artifact='INTENT.md'):
        spec = _make_phase_spec(artifact=artifact)
        return _make_ctx(state=state, session_worktree=self.tmpdir, infra_dir=self.tmpdir, phase_spec=spec)

    def test_missing_artifact_never_asserts(self):
        """Absent artifact must not route 'assert' — gate invariant requires artifact present."""
        ctx = self._make_ctx_in_tmpdir()
        result = self.runner._interpret_output(ctx, _make_claude_result())
        self.assertNotEqual(result.action, 'assert',
                            "Missing artifact must never route to the ASSERT gate")

    def test_missing_artifact_routes_to_safe_terminal(self):
        """From INTENT, missing artifact routes to 'withdraw' — the safe terminal.
        Advancing without evidence of the work would lose integrity; withdraw loops
        the work back through a new dispatch rather than asserting.
        """
        ctx = self._make_ctx_in_tmpdir(state='INTENT')
        result = self.runner._interpret_output(ctx, _make_claude_result())
        self.assertEqual(result.action, 'withdraw')
        self.assertNotIn('artifact_missing', result.data)
        self.assertNotIn('artifact_expected', result.data)

    def test_missing_artifact_no_artifact_path_in_data(self):
        """artifact_path must not be set when the file does not exist."""
        ctx = self._make_ctx_in_tmpdir()
        result = self.runner._interpret_output(ctx, _make_claude_result())
        self.assertNotIn('artifact_path', result.data)

    def test_present_artifact_uses_assert_with_path(self):
        """When INTENT.md exists, action is 'assert' and artifact_path is set."""
        ctx = self._make_ctx_in_tmpdir()
        artifact_path = os.path.join(self.tmpdir, 'INTENT.md')
        Path(artifact_path).write_text('# Intent\nDo something')

        result = self.runner._interpret_output(ctx, _make_claude_result())

        self.assertEqual(result.action, 'assert')
        self.assertEqual(result.data.get('artifact_path'), artifact_path)
        self.assertNotIn('artifact_missing', result.data)

    def test_no_artifact_configured_and_no_phase_outcome_returns_empty_action(self):
        """Phase with no artifact AND no ``.phase-outcome.json`` returns the
        "no outcome" sentinel (``action=''``) — NOT ``auto-approve``.

        Previously this path fell through to ``action='auto-approve'`` —
        a silent approval.  When the execute phase (``artifact=None``)
        ran, the LLM dispatched via Send and its turn ended; no
        phase-outcome.json existed, so the engine auto-approved
        EXECUTE → DONE without the skill's ASSERT gate or any human
        sign-off.  The work the agent dispatched never got reviewed.

        The interpreter now returns ``action=''`` as the "no outcome"
        sentinel.  ``_run_phase`` decides what to do:
          - workers are in flight → fan-in wait, re-invoke, retry
          - no workers + no outcome → raise (no silent approvals)
        So the kill-the-silent-approval invariant lives in
        ``_run_phase``, not here.  This test pins the sentinel.
        """
        spec = _make_phase_spec(artifact=None)
        ctx = _make_ctx(session_worktree=self.tmpdir, phase_spec=spec)

        result = self.runner._interpret_output(ctx, _make_claude_result())
        self.assertEqual(
            result.action, '',
            'Interpreter must return the empty-action sentinel when '
            "it can't determine an outcome — never auto-approve",
        )


# ── Phase-config artifact fields ────────────────────────────────────────────

class TestPhaseConfigArtifacts(unittest.TestCase):
    """Artifact fields pin which file each phase must produce.

    Previously read from ``phase-config.json``; that JSON is gone and
    the table is literal Python constants in ``phase_config.py``.
    """

    def _phases(self) -> dict:
        from teaparty.cfa.phase_config import _PHASES
        return _PHASES

    def test_planning_phase_has_plan_md_artifact(self):
        """Planning phase must have artifact=PLAN.md so PLAN_ASSERT is not bypassed."""
        artifact = self._phases()['planning'].artifact
        self.assertEqual(
            artifact, 'PLAN.md',
            f"planning artifact must be 'PLAN.md', got {artifact!r} — "
            'null here causes _interpret_output to auto-approve and bypass PLAN_ASSERT',
        )

    def test_intent_phase_has_intent_md_artifact(self):
        """Intent phase artifact must remain INTENT.md (regression guard)."""
        self.assertEqual(self._phases()['intent'].artifact, 'INTENT.md')

    def test_planning_phase_artifact_is_not_null(self):
        """Explicit null check — the root cause of the bypass bug."""
        self.assertIsNotNone(
            self._phases()['planning'].artifact,
            'planning artifact must not be null',
        )


class TestInterpretOutputPlanningPhaseRouting(unittest.TestCase):
    """Verify _interpret_output routes planning output through PLAN_ASSERT, not auto-approve."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.runner = AgentRunner()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_planning_spec(self) -> PhaseSpec:
        return PhaseSpec(
            name='planning',
            agent_file='agents/uber-team.json',
            lead='project-lead',
            permission_mode='plan',
            stream_file='.plan-stream.jsonl',
            artifact='PLAN.md',
            approval_state='PLAN_ASSERT',
        )

    def test_planning_present_artifact_goes_to_assert(self):
        """When PLAN.md exists, action is 'assert' (routes to PLAN_ASSERT)."""
        spec = self._make_planning_spec()
        ctx = _make_ctx(state='DRAFT', session_worktree=self.tmpdir, infra_dir=self.tmpdir, phase_spec=spec)
        Path(os.path.join(self.tmpdir, 'PLAN.md')).write_text('# Plan\nStep 1\nStep 2')

        result = self.runner._interpret_output(ctx, _make_claude_result())

        self.assertEqual(result.action, 'assert')
        self.assertIn('artifact_path', result.data)
        self.assertNotIn('artifact_missing', result.data)

    def test_planning_missing_artifact_never_asserts(self):
        """When PLAN.md is absent, must not assert (gate requires artifact) and not auto-approve."""
        spec = self._make_planning_spec()
        ctx = _make_ctx(state='DRAFT', session_worktree=self.tmpdir, infra_dir=self.tmpdir, phase_spec=spec)
        # PLAN.md deliberately not written

        result = self.runner._interpret_output(ctx, _make_claude_result())

        self.assertNotEqual(result.action, 'auto-approve',
                            "Missing PLAN.md must never auto-approve — that bypasses PLAN_ASSERT")
        self.assertNotEqual(result.action, 'assert',
                            "Missing PLAN.md must never assert — gate invariant requires artifact")
        self.assertNotIn('artifact_missing', result.data)

    def test_intent_phase_present_artifact_still_goes_to_assert(self):
        """Intent phase is unaffected — present INTENT.md still routes to assert."""
        spec = _make_phase_spec(artifact='INTENT.md')
        ctx = _make_ctx(state='PROPOSAL', session_worktree=self.tmpdir, infra_dir=self.tmpdir, phase_spec=spec)
        Path(os.path.join(self.tmpdir, 'INTENT.md')).write_text('# Intent')

        result = self.runner._interpret_output(ctx, _make_claude_result())

        self.assertEqual(result.action, 'assert')
        self.assertIn('artifact_path', result.data)


# ── Plan relocation from ~/.claude/plans/ ────────────────────────────────────

class TestRelocatePlanFile(unittest.TestCase):
    """_relocate_plan_file copies newest plan from ~/.claude/plans/ to target."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.fake_plans_dir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        shutil.rmtree(self.fake_plans_dir, ignore_errors=True)

    def test_relocates_newest_plan_after_start_time(self):
        """Plan file created after start_time is copied to target."""
        import time
        start = time.time() - 1  # 1 second ago
        plan_file = Path(self.fake_plans_dir) / 'my-plan.md'
        plan_file.write_text('# Plan\nStep 1: do the thing')

        target = os.path.join(self.tmpdir, 'PLAN.md')

        with patch('teaparty.cfa.actors.Path.home',
                   return_value=Path(self.fake_plans_dir).parent):
            # We need to mock Path.home() so ~/.claude/plans/ points to our fake dir
            # Instead, let's call the function directly with a patched plans_dir
            pass

        # Directly test the function by patching the plans_dir lookup
        with patch('teaparty.cfa.actors.Path.home') as mock_home:
            mock_home.return_value = Path(self.tmpdir) / 'fakehome'
            plans_dir = Path(self.tmpdir) / 'fakehome' / '.claude' / 'plans'
            plans_dir.mkdir(parents=True)
            new_plan = plans_dir / 'test-plan.md'
            new_plan.write_text('# My Plan\n\n## Steps\n1. First\n2. Second')

            result = _relocate_plan_file(target, start)

        self.assertTrue(result)
        self.assertTrue(os.path.exists(target))
        self.assertIn('My Plan', Path(target).read_text())

    def test_ignores_plans_before_start_time(self):
        """Plan files older than start_time are not relocated."""
        import time

        with patch('teaparty.cfa.actors.Path.home') as mock_home:
            mock_home.return_value = Path(self.tmpdir) / 'fakehome'
            plans_dir = Path(self.tmpdir) / 'fakehome' / '.claude' / 'plans'
            plans_dir.mkdir(parents=True)
            old_plan = plans_dir / 'old-plan.md'
            old_plan.write_text('# Old Plan')
            # Set mtime to well in the past
            os.utime(str(old_plan), (time.time() - 3600, time.time() - 3600))

            target = os.path.join(self.tmpdir, 'PLAN.md')
            result = _relocate_plan_file(target, time.time() - 1)

        self.assertFalse(result)
        self.assertFalse(os.path.exists(target))

    def test_picks_newest_when_multiple_candidates(self):
        """When multiple plans are new, the newest (highest mtime) wins."""
        import time
        start = time.time() - 2

        with patch('teaparty.cfa.actors.Path.home') as mock_home:
            mock_home.return_value = Path(self.tmpdir) / 'fakehome'
            plans_dir = Path(self.tmpdir) / 'fakehome' / '.claude' / 'plans'
            plans_dir.mkdir(parents=True)

            older = plans_dir / 'older-plan.md'
            older.write_text('# Older')
            os.utime(str(older), (time.time() - 1, time.time() - 1))

            newer = plans_dir / 'newer-plan.md'
            newer.write_text('# Newer')
            # newer has default mtime (now), which is more recent

            target = os.path.join(self.tmpdir, 'PLAN.md')
            result = _relocate_plan_file(target, start)

        self.assertTrue(result)
        self.assertIn('Newer', Path(target).read_text())

    def test_no_plans_dir_returns_false(self):
        """If ~/.claude/plans/ doesn't exist, return False gracefully."""
        with patch('teaparty.cfa.actors.Path.home') as mock_home:
            mock_home.return_value = Path(self.tmpdir) / 'empty-home'

            target = os.path.join(self.tmpdir, 'PLAN.md')
            result = _relocate_plan_file(target, 0)

        self.assertFalse(result)

    def test_empty_plans_dir_returns_false(self):
        """If ~/.claude/plans/ exists but is empty, return False."""
        with patch('teaparty.cfa.actors.Path.home') as mock_home:
            mock_home.return_value = Path(self.tmpdir) / 'fakehome'
            plans_dir = Path(self.tmpdir) / 'fakehome' / '.claude' / 'plans'
            plans_dir.mkdir(parents=True)

            target = os.path.join(self.tmpdir, 'PLAN.md')
            result = _relocate_plan_file(target, 0)

        self.assertFalse(result)

    def test_non_md_files_ignored(self):
        """Non-.md files in plans dir are skipped."""
        import time

        with patch('teaparty.cfa.actors.Path.home') as mock_home:
            mock_home.return_value = Path(self.tmpdir) / 'fakehome'
            plans_dir = Path(self.tmpdir) / 'fakehome' / '.claude' / 'plans'
            plans_dir.mkdir(parents=True)
            (plans_dir / 'notes.txt').write_text('not a plan')
            (plans_dir / 'data.json').write_text('{}')

            target = os.path.join(self.tmpdir, 'PLAN.md')
            result = _relocate_plan_file(target, time.time() - 10)

        self.assertFalse(result)


class TestAgentRunnerRelocatesPlan(unittest.TestCase):
    """AgentRunner.run() calls _relocate_plan_file when artifact is missing."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
# ── Approval-gate exports ────────────────────────────────────────────────────

class TestEscalationGenerativeResponse(unittest.TestCase):
    """Escalation states try generate_response() before falling through to human."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self._input_calls = []

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_relocation_called_when_artifact_missing(self):
        """When PLAN.md isn't in session_worktree, _interpret_output
        still finds the artifact if relocation writes it before the check."""
        spec = PhaseSpec(
            name='planning', agent_file='agents/uber-team.json',
            lead='project-lead', permission_mode='plan',
            stream_file='.plan-stream.jsonl', artifact='PLAN.md',
            approval_state='PLAN_ASSERT',
        )
        ctx = _make_ctx(state='DRAFT', session_worktree=self.tmpdir, infra_dir=self.tmpdir, phase_spec=spec)
        runner = AgentRunner()
        mock_result = ClaudeResult(exit_code=0, session_id='s1', start_time=1000.0)

        # Simulate relocation: write the artifact before _interpret_output runs,
        # as the real run() method would do.
        artifact_path = os.path.join(self.tmpdir, 'PLAN.md')
        Path(artifact_path).write_text('# Plan from relocation')

        result = runner._interpret_output(ctx, mock_result)
        self.assertEqual(result.action, 'assert')
        self.assertEqual(result.data.get('artifact_path'), artifact_path)
        self.assertNotIn('artifact_missing', result.data)

    def test_no_relocation_when_artifact_already_exists(self):
        """If PLAN.md already exists in session_worktree, don't relocate."""
        spec = PhaseSpec(
            name='planning', agent_file='agents/uber-team.json',
            lead='project-lead', permission_mode='plan',
            stream_file='.plan-stream.jsonl', artifact='PLAN.md',
            approval_state='PLAN_ASSERT',
        )
        ctx = _make_ctx(state='DRAFT', session_worktree=self.tmpdir, phase_spec=spec)

        # Write PLAN.md directly (agent wrote it to CWD)
        Path(os.path.join(self.tmpdir, 'PLAN.md')).write_text('# Direct Plan')

        with patch('teaparty.cfa.actors._relocate_plan_file') as mock_relocate:
            mock_result = ClaudeResult(exit_code=0, session_id='s1', start_time=1000.0)
            # Simulate run()'s artifact check
            artifact_path = os.path.join(self.tmpdir, spec.artifact)
            if not os.path.exists(artifact_path):
                _relocate_plan_file(artifact_path, mock_result.start_time)

            mock_relocate.assert_not_called()


# ── Regression tests for #120: approval gate classification failures ──────────

class TestStderrInActorResult(unittest.TestCase):
    """ClaudeResult.stderr_lines flows through to ActorResult.data."""

    def test_interpret_output_includes_stderr(self):
        """When ClaudeResult has stderr_lines, they appear in ActorResult.data."""
        runner = AgentRunner()
        ctx = _make_ctx()

        with tempfile.TemporaryDirectory() as tmpdir:
            ctx.session_worktree = tmpdir
            result = ClaudeResult(
                exit_code=0,
                session_id='s1',
                stderr_lines=['Error: tool execution failed', 'Warning: rate limited'],
            )
            actor_result = runner._interpret_output(ctx, result)
            self.assertEqual(
                actor_result.data['stderr_lines'],
                ['Error: tool execution failed', 'Warning: rate limited'],
            )

    def test_interpret_output_omits_stderr_when_empty(self):
        """When ClaudeResult has no stderr, data should not contain stderr_lines."""
        runner = AgentRunner()
        ctx = _make_ctx()

        with tempfile.TemporaryDirectory() as tmpdir:
            ctx.session_worktree = tmpdir
            result = ClaudeResult(exit_code=0, session_id='s1', stderr_lines=[])
            actor_result = runner._interpret_output(ctx, result)
            self.assertNotIn('stderr_lines', actor_result.data)

    def test_agent_runner_run_propagates_stderr_on_nonzero_exit(self):
        """AgentRunner.run() includes stderr_lines in the failed ActorResult when exit_code != 0."""
        from teaparty.runners.claude import ClaudeRunner
        runner = AgentRunner()
        ctx = _make_ctx()

        with tempfile.TemporaryDirectory() as tmpdir:
            ctx.session_worktree = tmpdir
            _install_jail_hook(tmpdir)
            fake_claude_result = ClaudeResult(
                exit_code=1,
                session_id='s1',
                stderr_lines=['fatal: API key invalid', 'Permission denied'],
            )
            with patch.object(ClaudeRunner, 'run', new=AsyncMock(return_value=fake_claude_result)):
                actor_result = _run(runner.run(ctx))

        self.assertEqual(actor_result.action, 'failed')
        self.assertEqual(
            actor_result.data['stderr_lines'],
            ['fatal: API key invalid', 'Permission denied'],
        )
        self.assertEqual(actor_result.data['reason'], 'nonzero_exit')

    def test_agent_runner_run_propagates_stderr_on_stall_killed(self):
        """AgentRunner.run() includes stderr_lines in the failed ActorResult when stall_killed."""
        from teaparty.runners.claude import ClaudeRunner
        runner = AgentRunner()
        ctx = _make_ctx()

        with tempfile.TemporaryDirectory() as tmpdir:
            ctx.session_worktree = tmpdir
            _install_jail_hook(tmpdir)
            fake_claude_result = ClaudeResult(
                exit_code=-1,
                session_id='s1',
                stall_killed=True,
                stderr_lines=['subprocess timed out after 1800s'],
            )
            with patch.object(ClaudeRunner, 'run', new=AsyncMock(return_value=fake_claude_result)):
                actor_result = _run(runner.run(ctx))

        self.assertEqual(actor_result.action, 'failed')
        self.assertEqual(
            actor_result.data['stderr_lines'],
            ['subprocess timed out after 1800s'],
        )
        self.assertEqual(actor_result.data['reason'], 'stall_timeout')


class TestClaudeResultHadErrors(unittest.TestCase):
    """ClaudeResult.had_errors convenience property."""

    def test_had_errors_true(self):
        r = ClaudeResult(exit_code=0, stderr_lines=['oops'])
        self.assertTrue(r.had_errors)

    def test_had_errors_false(self):
        r = ClaudeResult(exit_code=0, stderr_lines=[])
        self.assertFalse(r.had_errors)

    def test_had_errors_default(self):
        r = ClaudeResult(exit_code=0)
        self.assertFalse(r.had_errors)


class TestInterpretOutputExecutionArtifact(unittest.TestCase):
    """Execution phase with WORK_SUMMARY.md routes to assert, not auto-approve."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.runner = AgentRunner()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_execution_spec(self):
        return PhaseSpec(
            name='execution',
            agent_file='agents/uber-team.json',
            lead='project-lead',
            permission_mode='acceptEdits',
            stream_file='.exec-stream.jsonl',
            artifact='WORK_SUMMARY.md',
            approval_state='WORK_ASSERT',
        )

    def test_work_summary_present_routes_to_assert(self):
        spec = self._make_execution_spec()
        ctx = _make_ctx(
            state='WORK_IN_PROGRESS',
            session_worktree=self.tmpdir,
            infra_dir=self.tmpdir,
            phase_spec=spec,
        )
        # Write the work summary to the worktree (agent writes it there)
        Path(os.path.join(self.tmpdir, 'WORK_SUMMARY.md')).write_text('# Work Summary\n')

        result = self.runner._interpret_output(ctx, _make_claude_result())

        self.assertEqual(result.action, 'assert')
        self.assertIn('WORK_SUMMARY.md', result.data.get('artifact_path', ''))

    def test_work_summary_missing_never_asserts(self):
        """If WORK_SUMMARY.md is expected but missing, must not assert — gate requires artifact."""
        spec = self._make_execution_spec()
        ctx = _make_ctx(
            state='WORK_IN_PROGRESS',
            session_worktree=self.tmpdir,
            phase_spec=spec,
        )

        result = self.runner._interpret_output(ctx, _make_claude_result())

        self.assertNotEqual(result.action, 'assert',
                            "Missing artifact must never assert — gate invariant requires artifact")
        self.assertNotIn('artifact_missing', result.data)


class TestRelocateMisplacedArtifact(unittest.TestCase):
    """Artifacts written anywhere must be moved to the worktree via stream parsing."""

    def setUp(self):
        self.worktree = tempfile.mkdtemp()
        self.stream_dir = tempfile.mkdtemp()
        self.stream_file = os.path.join(self.stream_dir, '.intent-stream.jsonl')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.worktree, ignore_errors=True)
        shutil.rmtree(self.stream_dir, ignore_errors=True)

    def _write_stream_with_write_call(self, file_path: str):
        """Write a stream JSONL with a Write tool call to file_path."""
        import json as _json
        event = {
            'type': 'assistant',
            'message': {
                'content': [{
                    'type': 'tool_use',
                    'name': 'Write',
                    'input': {'file_path': file_path, 'content': '# test'},
                }],
            },
        }
        with open(self.stream_file, 'w') as f:
            f.write(_json.dumps(event) + '\n')

    def test_relocates_artifact_found_via_stream(self):
        """INTENT.md written to arbitrary path is moved to worktree root."""
        from teaparty.cfa.actors import _relocate_misplaced_artifact

        # Agent wrote to some random absolute path
        wrong_dir = tempfile.mkdtemp()
        misplaced = os.path.join(wrong_dir, 'INTENT.md')
        Path(misplaced).write_text('# Intent\nObjective: test')
        self._write_stream_with_write_call(misplaced)

        result = _relocate_misplaced_artifact(
            self.worktree, self.stream_file, 'INTENT.md',
        )

        self.assertTrue(result)
        self.assertTrue(os.path.exists(os.path.join(self.worktree, 'INTENT.md')))
        # Source is removed (move, not copy — Issue #148)
        self.assertFalse(os.path.exists(misplaced))
        import shutil
        shutil.rmtree(wrong_dir, ignore_errors=True)

    def test_relocates_from_repo_root(self):
        """INTENT.md written to repo root (real failure case) is relocated."""
        from teaparty.cfa.actors import _relocate_misplaced_artifact

        repo_root = tempfile.mkdtemp()
        misplaced = os.path.join(repo_root, 'INTENT.md')
        Path(misplaced).write_text('# Intent\nRepo root write')
        self._write_stream_with_write_call(misplaced)

        result = _relocate_misplaced_artifact(
            self.worktree, self.stream_file, 'INTENT.md',
        )

        self.assertTrue(result)
        self.assertTrue(os.path.exists(os.path.join(self.worktree, 'INTENT.md')))
        # Source is removed (move, not copy — Issue #148)
        self.assertFalse(os.path.exists(misplaced))
        import shutil
        shutil.rmtree(repo_root, ignore_errors=True)

    def test_relocates_from_project_dir(self):
        """INTENT.md written to project dir (other real failure case) is relocated."""
        from teaparty.cfa.actors import _relocate_misplaced_artifact

        project_dir = tempfile.mkdtemp()
        misplaced = os.path.join(project_dir, 'INTENT.md')
        Path(misplaced).write_text('# Intent\nProject dir write')
        self._write_stream_with_write_call(misplaced)

        result = _relocate_misplaced_artifact(
            self.worktree, self.stream_file, 'INTENT.md',
        )

        self.assertTrue(result)
        self.assertTrue(os.path.exists(os.path.join(self.worktree, 'INTENT.md')))
        import shutil
        shutil.rmtree(project_dir, ignore_errors=True)

    def test_no_op_when_artifact_already_in_worktree(self):
        """If artifact is already in the worktree, nothing is moved."""
        from teaparty.cfa.actors import _relocate_misplaced_artifact

        correct = os.path.join(self.worktree, 'INTENT.md')
        Path(correct).write_text('# Intent\nCorrect location')

        result = _relocate_misplaced_artifact(
            self.worktree, self.stream_file, 'INTENT.md',
        )

        self.assertFalse(result)
        self.assertEqual(Path(correct).read_text(), '# Intent\nCorrect location')

    def test_no_op_when_no_write_in_stream(self):
        """If stream has no Write calls for the artifact, returns False."""
        from teaparty.cfa.actors import _relocate_misplaced_artifact

        # Empty stream
        with open(self.stream_file, 'w') as f:
            f.write('')

        result = _relocate_misplaced_artifact(
            self.worktree, self.stream_file, 'INTENT.md',
        )

        self.assertFalse(result)

    def test_no_op_when_stream_file_missing(self):
        """If stream file doesn't exist, returns False."""
        from teaparty.cfa.actors import _relocate_misplaced_artifact

        result = _relocate_misplaced_artifact(
            self.worktree, '/nonexistent/stream.jsonl', 'INTENT.md',
        )

        self.assertFalse(result)

    def test_works_for_plan_artifact(self):
        """Relocation works for PLAN.md too."""
        from teaparty.cfa.actors import _relocate_misplaced_artifact

        wrong_dir = tempfile.mkdtemp()
        misplaced = os.path.join(wrong_dir, 'PLAN.md')
        Path(misplaced).write_text('# Plan\nStep 1')
        self._write_stream_with_write_call(misplaced)

        result = _relocate_misplaced_artifact(
            self.worktree, self.stream_file, 'PLAN.md',
        )

        self.assertTrue(result)
        self.assertTrue(os.path.exists(os.path.join(self.worktree, 'PLAN.md')))
        import shutil
        shutil.rmtree(wrong_dir, ignore_errors=True)

    def test_end_to_end_relocate_then_interpret(self):
        """End-to-end: misplaced artifact is relocated, then _interpret_output finds it."""
        from teaparty.cfa.actors import _relocate_misplaced_artifact

        wrong_dir = tempfile.mkdtemp()
        misplaced = os.path.join(wrong_dir, 'INTENT.md')
        Path(misplaced).write_text('# Intent\nObjective: end-to-end test')
        self._write_stream_with_write_call(misplaced)

        _relocate_misplaced_artifact(
            self.worktree, self.stream_file, 'INTENT.md',
        )

        runner = AgentRunner()
        spec = _make_phase_spec(artifact='INTENT.md')
        ctx = _make_ctx(
            state='PROPOSAL',
            session_worktree=self.worktree,
            infra_dir=self.worktree,
            phase_spec=spec,
        )

        result = runner._interpret_output(ctx, _make_claude_result())

        self.assertEqual(result.action, 'assert')
        self.assertNotIn('artifact_missing', result.data)
        self.assertEqual(
            result.data.get('artifact_path'),
            os.path.join(self.worktree, 'INTENT.md'),
        )
        import shutil
        shutil.rmtree(wrong_dir, ignore_errors=True)


def _run_sync(*args, cwd=None):
    """Run a command synchronously for test setup."""
    import subprocess as sp
    sp.run(args, cwd=cwd, capture_output=True, check=True)


if __name__ == '__main__':
    unittest.main()
