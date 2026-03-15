#!/usr/bin/env python3
"""Tests for issue #137: Stream-based escalation detection.

The escalation handshake must be race-free:
- Detection is based on the agent's stream output, not filesystem state.
- Only Write events from THIS turn are considered (stream offset boundary).
- Stale escalation files from prior turns or sessions are ignored.
- Escalation files are excluded from merge commits.
"""
import asyncio
import json
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
    _find_write_path_in_stream_after,
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


def _write_stream_event(stream_path, file_path):
    """Append a Write tool-use event to a stream JSONL file."""
    evt = {
        'type': 'assistant',
        'message': {
            'content': [{
                'type': 'tool_use',
                'name': 'Write',
                'input': {'file_path': file_path},
            }],
        },
    }
    with open(stream_path, 'a') as f:
        f.write(json.dumps(evt) + '\n')


# ── Tests: _find_write_path_in_stream_after (the core primitive) ─────────────

class TestStreamOffsetDetection(unittest.TestCase):
    """_find_write_path_in_stream_after only sees events after the offset."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.stream = os.path.join(self.tmpdir, '.intent-stream.jsonl')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_detects_write_after_offset(self):
        """A Write event after the offset IS detected."""
        _write_stream_event(self.stream, '/old/path/.intent-escalation.md')
        offset = os.path.getsize(self.stream)
        _write_stream_event(self.stream, '/new/path/.intent-escalation.md')

        result = _find_write_path_in_stream_after(
            self.stream, '.intent-escalation.md', offset,
        )
        self.assertEqual(result, '/new/path/.intent-escalation.md')

    def test_ignores_write_before_offset(self):
        """A Write event before the offset is NOT detected."""
        _write_stream_event(self.stream, '/old/path/.intent-escalation.md')
        offset = os.path.getsize(self.stream)

        result = _find_write_path_in_stream_after(
            self.stream, '.intent-escalation.md', offset,
        )
        self.assertEqual(result, '')

    def test_empty_stream_returns_empty(self):
        result = _find_write_path_in_stream_after(
            '/nonexistent/stream.jsonl', '.intent-escalation.md', 0,
        )
        self.assertEqual(result, '')

    def test_no_matching_write_returns_empty(self):
        _write_stream_event(self.stream, '/path/INTENT.md')
        result = _find_write_path_in_stream_after(
            self.stream, '.intent-escalation.md', 0,
        )
        self.assertEqual(result, '')


# ── Tests: AgentRunner uses stream-based detection ───────────────────────────

class TestAgentRunnerStreamDetection(unittest.TestCase):
    """AgentRunner._interpret_output uses stream offset, not os.path.exists."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.runner = AgentRunner()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_stale_file_on_disk_does_not_trigger_escalation(self):
        """A stale .intent-escalation.md on disk must NOT trigger escalation
        if the agent didn't write it this turn (no Write in stream)."""
        ctx = _make_ctx(self.tmpdir, state='PROPOSAL')

        # Plant a stale file on disk — from a previous session or merge
        esc_path = os.path.join(self.tmpdir, '.intent-escalation.md')
        Path(esc_path).write_text('# Stale from previous session')

        from projects.POC.orchestrator.claude_runner import ClaudeResult
        mock_result = ClaudeResult(exit_code=0, session_id='s1')

        with patch('projects.POC.orchestrator.actors.ClaudeRunner') as MockRunner:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value=mock_result)
            MockRunner.return_value = mock_instance

            result = _run(self.runner.run(ctx))

        self.assertNotEqual(result.action, 'escalate',
                            "Stale file on disk must not trigger escalation")

    def test_agent_write_in_stream_triggers_escalation(self):
        """If the agent writes the escalation file THIS turn, it IS detected."""
        ctx = _make_ctx(self.tmpdir, state='PROPOSAL')
        stream_path = os.path.join(self.tmpdir, '.intent-stream.jsonl')
        esc_path = os.path.join(self.tmpdir, '.intent-escalation.md')

        from projects.POC.orchestrator.claude_runner import ClaudeResult
        mock_result = ClaudeResult(exit_code=0, session_id='s1')

        async def fake_run(*args, **kwargs):
            Path(esc_path).write_text('# New escalation\n\n1. What format?\n')
            _write_stream_event(stream_path, str(esc_path))
            return mock_result

        with patch('projects.POC.orchestrator.actors.ClaudeRunner') as MockRunner:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(side_effect=fake_run)
            MockRunner.return_value = mock_instance

            result = _run(self.runner.run(ctx))

        self.assertEqual(result.action, 'escalate',
                         "Agent-written escalation file must be detected via stream")

    def test_prior_turn_write_in_stream_ignored(self):
        """A Write event from a PRIOR turn must not trigger escalation."""
        stream_path = os.path.join(self.tmpdir, '.intent-stream.jsonl')
        esc_path = os.path.join(self.tmpdir, '.intent-escalation.md')

        # Prior turn: Write event in stream + file on disk
        Path(esc_path).write_text('# Old escalation')
        _write_stream_event(stream_path, str(esc_path))

        # Current turn starts — stream offset is AFTER the prior Write
        ctx = _make_ctx(self.tmpdir, state='PROPOSAL')

        from projects.POC.orchestrator.claude_runner import ClaudeResult
        mock_result = ClaudeResult(exit_code=0, session_id='s1')

        with patch('projects.POC.orchestrator.actors.ClaudeRunner') as MockRunner:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(return_value=mock_result)
            MockRunner.return_value = mock_instance

            result = _run(self.runner.run(ctx))

        self.assertNotEqual(result.action, 'escalate',
                            "Prior-turn Write event must not trigger escalation")

    def test_misplaced_write_to_wrong_path_detected(self):
        """Agent writes to /home/user/.intent-escalation.md — still detected."""
        ctx = _make_ctx(self.tmpdir, state='PROPOSAL')
        stream_path = os.path.join(self.tmpdir, '.intent-stream.jsonl')
        wrong_path = os.path.join(self.tmpdir, 'wrong', '.intent-escalation.md')
        os.makedirs(os.path.dirname(wrong_path), exist_ok=True)

        from projects.POC.orchestrator.claude_runner import ClaudeResult
        mock_result = ClaudeResult(exit_code=0, session_id='s1')

        async def fake_run(*args, **kwargs):
            Path(wrong_path).write_text('# Escalation at wrong path')
            _write_stream_event(stream_path, str(wrong_path))
            return mock_result

        with patch('projects.POC.orchestrator.actors.ClaudeRunner') as MockRunner:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(side_effect=fake_run)
            MockRunner.return_value = mock_instance

            result = _run(self.runner.run(ctx))

        self.assertEqual(result.action, 'escalate',
                         "Misplaced escalation file must be detected via stream")

    def test_concurrent_stale_file_and_new_write(self):
        """Stale file on disk from another agent + new Write this turn = escalate
        based on the new Write, not the stale file."""
        ctx = _make_ctx(self.tmpdir, state='PROPOSAL')
        stream_path = os.path.join(self.tmpdir, '.intent-stream.jsonl')
        esc_path = os.path.join(self.tmpdir, '.intent-escalation.md')

        # Stale file from another agent/session already on disk
        Path(esc_path).write_text('# STALE CONTENT')

        # Stale Write event from prior turn in stream
        _write_stream_event(stream_path, '/old/stale/.intent-escalation.md')

        from projects.POC.orchestrator.claude_runner import ClaudeResult
        mock_result = ClaudeResult(exit_code=0, session_id='s1')

        async def fake_run(*args, **kwargs):
            # Agent writes NEW content this turn
            Path(esc_path).write_text('# FRESH QUESTION\n\n1. New question?\n')
            _write_stream_event(stream_path, str(esc_path))
            return mock_result

        with patch('projects.POC.orchestrator.actors.ClaudeRunner') as MockRunner:
            mock_instance = MagicMock()
            mock_instance.run = AsyncMock(side_effect=fake_run)
            MockRunner.return_value = mock_instance

            result = _run(self.runner.run(ctx))

        self.assertEqual(result.action, 'escalate')
        # The escalation file should have FRESH content, not stale
        with open(result.data['escalation_file']) as f:
            content = f.read()
        self.assertIn('FRESH QUESTION', content)


# ── Tests: ApprovalGate bridge_text and cleanup ──────────────────────────────

class TestBridgeTextContainsQuestion(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch('projects.POC.orchestrator.actors.generate_response', return_value=None)
    @patch('projects.POC.orchestrator.actors.load_model')
    @patch('projects.POC.orchestrator.actors.resolve_team_model_path', side_effect=lambda b, t: b)
    def test_bridge_text_is_the_question_not_generic(self, mock_resolve, mock_load, mock_gen):
        escalation_content = (
            '# Intent Escalation\n\n'
            '## Questions\n\n'
            '1. Who is the target audience for this book?\n'
        )
        ctx = _make_ctx(self.tmpdir, escalation_content=escalation_content)
        gate, input_calls = _make_gate(self.tmpdir, human_response='ages 5-8')

        with patch.object(gate, '_classify_review', return_value=('clarify', 'ages 5-8')):
            _run(gate.run(ctx))

        self.assertGreater(len(input_calls), 0)
        self.assertIn('target audience', input_calls[0].bridge_text)


class TestEscalationFileCleanup(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch('projects.POC.orchestrator.actors.generate_response', return_value=None)
    @patch('projects.POC.orchestrator.actors.load_model')
    @patch('projects.POC.orchestrator.actors.resolve_team_model_path', side_effect=lambda b, t: b)
    def test_escalation_file_removed_after_human_responds(self, mock_resolve, mock_load, mock_gen):
        escalation_content = '# Escalation\n\n1. What database?\n'
        ctx = _make_ctx(self.tmpdir, escalation_content=escalation_content)
        esc_path = os.path.join(self.tmpdir, '.intent-escalation.md')

        gate, _ = _make_gate(self.tmpdir, human_response='PostgreSQL')
        with patch.object(gate, '_classify_review', return_value=('clarify', 'PostgreSQL')):
            _run(gate.run(ctx))

        self.assertFalse(os.path.exists(esc_path),
                         "Escalation file should be removed after human responds")


# ── Tests: Merge exclusion ───────────────────────────────────────────────────

class TestEscalationFileMergeExclusion(unittest.TestCase):

    def test_intent_escalation_excluded(self):
        self.assertTrue(_is_excluded('.intent-escalation.md'))

    def test_plan_escalation_excluded(self):
        self.assertTrue(_is_excluded('.plan-escalation.md'))

    def test_regular_md_not_excluded(self):
        self.assertFalse(_is_excluded('INTENT.md'))


if __name__ == '__main__':
    unittest.main()
