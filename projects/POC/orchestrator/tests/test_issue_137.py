#!/usr/bin/env python3
"""Tests for issue #137: Intent escalation prompt and cleanup.

Covers:
 1. ApprovalGate passes bridge_text (the agent's actual question) to the
    InputRequest, not a generic label.
 2. Escalation files are cleaned up after the human responds and the CfA
    state transitions past the escalation state.
 3. Repeated escalation cycles don't show stale questions from a previous
    escalation file.
 4. AgentRunner.run() deletes any stale escalation file BEFORE invoking
    the agent, so _interpret_output only sees files from THIS turn.
 5. Escalation files are excluded from merge commits.
"""
import asyncio
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent.parent))

from projects.POC.orchestrator.actors import (
    ActorContext,
    ActorResult,
    AgentRunner,
    ApprovalGate,
)
from projects.POC.orchestrator.events import EventBus, InputRequest
from projects.POC.orchestrator.merge import _is_excluded
from projects.POC.orchestrator.phase_config import PhaseSpec


# ── Helpers ────────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _make_event_bus():
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


def _make_phase_spec(
    escalation_file='.intent-escalation.md',
    artifact='INTENT.md',
):
    return PhaseSpec(
        name='intent',
        agent_file='agents/intent-team.json',
        lead='intent-lead',
        permission_mode='acceptEdits',
        stream_file='.intent-stream.jsonl',
        artifact=artifact,
        approval_state='INTENT_ASSERT',
        escalation_state='INTENT_ESCALATE',
        escalation_file=escalation_file,
        settings_overlay={},
    )


def _make_ctx(tmpdir, state='INTENT_ESCALATE', escalation_content=None):
    """Create an ActorContext with an escalation file if content is provided."""
    spec = _make_phase_spec()
    ctx = ActorContext(
        state=state,
        phase='intent',
        task='Write a book about jokes',
        infra_dir=tmpdir,
        project_workdir=tmpdir,
        session_worktree=tmpdir,
        stream_file='.intent-stream.jsonl',
        phase_spec=spec,
        poc_root=tmpdir,
        event_bus=_make_event_bus(),
        session_id='test-session',
    )
    ctx.env_vars = {'POC_PROJECT': 'default', 'POC_TEAM': ''}

    if escalation_content is not None:
        esc_path = os.path.join(tmpdir, '.intent-escalation.md')
        Path(esc_path).write_text(escalation_content)
        ctx.data = {'escalation_file': esc_path}
    else:
        ctx.data = {}

    return ctx


def _make_gate(tmpdir, human_response='approve'):
    """Create an ApprovalGate with a mock input provider."""
    input_calls = []

    async def _input_provider(req):
        input_calls.append(req)
        return human_response

    gate = ApprovalGate(
        proxy_model_path=os.path.join(tmpdir, '.proxy.json'),
        input_provider=_input_provider,
        poc_root=tmpdir,
    )
    return gate, input_calls


# ── Tests: Bridge text contains the actual question ──────────────────────────

class TestBridgeTextContainsQuestion(unittest.TestCase):
    """The human should see the agent's actual question, not a generic label."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch('projects.POC.orchestrator.actors.generate_response', return_value=None)
    @patch('projects.POC.orchestrator.actors.load_model')
    @patch('projects.POC.orchestrator.actors.resolve_team_model_path', side_effect=lambda b, t: b)
    def test_bridge_text_is_the_question_not_generic(self, mock_resolve, mock_load, mock_gen):
        """InputRequest.bridge_text must contain the extracted question from the escalation file."""
        escalation_content = (
            '# Intent Escalation\n\n'
            '## Questions\n\n'
            '1. Who is the target audience for this book?\n'
            '2. What format should the output be in?\n'
        )
        ctx = _make_ctx(self.tmpdir, escalation_content=escalation_content)
        gate, input_calls = _make_gate(self.tmpdir, human_response='ages 5-8')

        with patch.object(gate, '_classify_review', return_value=('clarify', 'ages 5-8')):
            _run(gate.run(ctx))

        self.assertGreater(len(input_calls), 0, "Human should have been prompted")
        req = input_calls[0]
        # The bridge_text should contain the actual question, not a generic string
        self.assertIn('target audience', req.bridge_text,
                      f"bridge_text should contain the actual question, got: {req.bridge_text!r}")
        self.assertNotEqual(req.bridge_text, 'The agent has a question for you.',
                            "bridge_text must not be the generic fallback")

    @patch('projects.POC.orchestrator.actors.generate_response', return_value=None)
    @patch('projects.POC.orchestrator.actors.load_model')
    @patch('projects.POC.orchestrator.actors.resolve_team_model_path', side_effect=lambda b, t: b)
    def test_no_escalation_file_still_works(self, mock_resolve, mock_load, mock_gen):
        """When there's no escalation file, a fallback bridge_text is used (not a crash)."""
        ctx = _make_ctx(self.tmpdir, escalation_content=None)
        gate, input_calls = _make_gate(self.tmpdir, human_response='approve')

        with patch.object(gate, '_classify_review', return_value=('clarify', 'ok')):
            _run(gate.run(ctx))

        self.assertGreater(len(input_calls), 0)
        # Should have some bridge_text, even if generic
        self.assertTrue(input_calls[0].bridge_text)


# ── Tests: Escalation file cleanup ───────────────────────────────────────────

class TestEscalationFileCleanup(unittest.TestCase):
    """Escalation files must be removed after the human responds."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch('projects.POC.orchestrator.actors.generate_response', return_value=None)
    @patch('projects.POC.orchestrator.actors.load_model')
    @patch('projects.POC.orchestrator.actors.resolve_team_model_path', side_effect=lambda b, t: b)
    def test_escalation_file_removed_after_human_responds(self, mock_resolve, mock_load, mock_gen):
        """After the approval gate processes the human response, the escalation file should be gone."""
        escalation_content = '# Escalation\n\n1. What database?\n'
        ctx = _make_ctx(self.tmpdir, escalation_content=escalation_content)
        esc_path = os.path.join(self.tmpdir, '.intent-escalation.md')

        self.assertTrue(os.path.exists(esc_path), "Escalation file should exist before gate")

        gate, _ = _make_gate(self.tmpdir, human_response='Use PostgreSQL')
        with patch.object(gate, '_classify_review', return_value=('clarify', 'Use PostgreSQL')):
            _run(gate.run(ctx))

        self.assertFalse(os.path.exists(esc_path),
                         "Escalation file should be removed after human responds")

    @patch('projects.POC.orchestrator.actors.generate_response', return_value=None)
    @patch('projects.POC.orchestrator.actors.load_model')
    @patch('projects.POC.orchestrator.actors.resolve_team_model_path', side_effect=lambda b, t: b)
    def test_stale_escalation_not_shown_on_second_cycle(self, mock_resolve, mock_load, mock_gen):
        """If escalation file is cleaned up, a second escalation cycle won't show stale questions."""
        # First cycle: write escalation, human responds
        esc_path = os.path.join(self.tmpdir, '.intent-escalation.md')
        Path(esc_path).write_text('# Escalation\n\n1. What database?\n')

        ctx1 = _make_ctx(self.tmpdir, escalation_content=None)
        ctx1.data = {'escalation_file': esc_path}

        gate, input_calls = _make_gate(self.tmpdir, human_response='PostgreSQL')
        with patch.object(gate, '_classify_review', return_value=('clarify', 'PostgreSQL')):
            _run(gate.run(ctx1))

        # Second cycle: agent escalates again with a NEW question
        # (simulates the agent writing a new escalation file)
        Path(esc_path).write_text('# Escalation\n\n1. What schema version?\n')
        ctx2 = _make_ctx(self.tmpdir, escalation_content=None)
        ctx2.data = {'escalation_file': esc_path}

        input_calls.clear()
        with patch.object(gate, '_classify_review', return_value=('clarify', 'v2')):
            _run(gate.run(ctx2))

        # The second prompt should show the NEW question, not the old one
        self.assertGreater(len(input_calls), 0)
        self.assertIn('schema version', input_calls[0].bridge_text,
                      f"Second cycle should show new question, got: {input_calls[0].bridge_text!r}")
        self.assertNotIn('database', input_calls[0].bridge_text,
                         "Stale question from first cycle should not appear")


# ── Tests: Pre-run cleanup (the handshake) ───────────────────────────────────

class TestPreRunEscalationCleanup(unittest.TestCase):
    """AgentRunner.run() must delete stale escalation files before invoking the agent."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.runner = AgentRunner()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_stale_escalation_file_deleted_before_agent_runs(self):
        """A pre-existing escalation file must be removed before the agent runs."""
        spec = _make_phase_spec()
        ctx = _make_ctx(self.tmpdir, state='PROPOSAL')

        # Plant a stale escalation file (from a previous turn/session)
        esc_path = os.path.join(self.tmpdir, '.intent-escalation.md')
        Path(esc_path).write_text('# Stale escalation from previous turn')

        self.assertTrue(os.path.exists(esc_path))

        # Mock ClaudeRunner so no actual subprocess runs.
        # The agent does NOT write a new escalation file this turn.
        from projects.POC.orchestrator.claude_runner import ClaudeResult
        mock_result = ClaudeResult(exit_code=0, session_id='s1')

        with patch('projects.POC.orchestrator.actors.ClaudeRunner') as MockRunner:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value=mock_result)
            MockRunner.return_value = mock_instance

            result = _run(self.runner.run(ctx))

        # The stale file should be gone — agent didn't write a new one
        self.assertFalse(os.path.exists(esc_path),
                         "Stale escalation file must be deleted before agent runs")
        # And since there's no escalation file, the action should NOT be 'escalate'
        self.assertNotEqual(result.action, 'escalate',
                            "Stale file should not trigger escalation")

    def test_agent_written_escalation_file_is_detected(self):
        """If the agent writes a NEW escalation file during its turn, it IS detected."""
        spec = _make_phase_spec()
        ctx = _make_ctx(self.tmpdir, state='PROPOSAL')

        # Plant a stale file — will be cleaned up pre-run
        esc_path = os.path.join(self.tmpdir, '.intent-escalation.md')
        Path(esc_path).write_text('# Stale')

        from projects.POC.orchestrator.claude_runner import ClaudeResult
        mock_result = ClaudeResult(exit_code=0, session_id='s1')

        async def fake_run(*args, **kwargs):
            # Simulate agent writing a NEW escalation file during its turn
            Path(esc_path).write_text('# New escalation\n\n1. What format?\n')
            return mock_result

        with patch('projects.POC.orchestrator.actors.ClaudeRunner') as MockRunner:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(side_effect=fake_run)
            MockRunner.return_value = mock_instance

            result = _run(self.runner.run(ctx))

        # The new file should trigger escalation
        self.assertEqual(result.action, 'escalate',
                         "Agent-written escalation file must be detected")


# ── Tests: Escalation files excluded from merge ──────────────────────────────

class TestEscalationFileMergeExclusion(unittest.TestCase):
    """Escalation files must never be included in merge commits."""

    def test_intent_escalation_excluded(self):
        self.assertTrue(_is_excluded('.intent-escalation.md'))

    def test_plan_escalation_excluded(self):
        self.assertTrue(_is_excluded('.plan-escalation.md'))

    def test_task_escalation_excluded(self):
        self.assertTrue(_is_excluded('.task-escalation.md'))

    def test_regular_md_not_excluded(self):
        self.assertFalse(_is_excluded('INTENT.md'))

    def test_regular_file_not_excluded(self):
        self.assertFalse(_is_excluded('chapter-01.md'))


if __name__ == '__main__':
    unittest.main()
