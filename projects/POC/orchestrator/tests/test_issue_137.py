#!/usr/bin/env python3
"""Tests for issue #137: Intent escalation prompt and cleanup.

Covers:
 1. ApprovalGate passes bridge_text (the agent's actual question) to the
    InputRequest, not a generic label.
 2. Escalation files are cleaned up after the human responds and the CfA
    state transitions past the escalation state.
 3. Repeated escalation cycles don't show stale questions from a previous
    escalation file.
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
    ApprovalGate,
)
from projects.POC.orchestrator.events import EventBus, InputRequest
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


if __name__ == '__main__':
    unittest.main()
