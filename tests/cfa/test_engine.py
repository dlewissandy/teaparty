#!/usr/bin/env python3
"""Tests for engine.py — initial-message construction and transition bookkeeping.

Covers:
 1. ``_build_initial_message`` injects ``[stderr from previous turn]`` /
    ``[human feedback]`` / ``[escalation dialog]`` headers when the
    engine is resuming with feedback from a downstream phase.
 2. ``_build_initial_message`` adds the ``[SESSION RESUMED — STALE TASK
    HANDLES]`` header when ``--resume`` will reattach to a Claude
    session whose task handles are now stale.
 3. ``_transition`` clears ``feedback`` / ``dialog_history`` from
    ``_last_actor_data`` when the state actually changes (otherwise
    the next phase's first turn would carry a stale header).
"""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.cfa.engine import Orchestrator
from teaparty.cfa.statemachine.cfa_state import Action, State
from teaparty.messaging.bus import EventBus
from teaparty.cfa.phase_config import PhaseConfig, PhaseSpec
from teaparty.cfa.statemachine.cfa_state import CfaState


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    return asyncio.run(coro)


def _make_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


def _make_phase_spec(artifact: str | None = None) -> PhaseSpec:
    return PhaseSpec(
        agent_file='agents/intent-team.json',
        lead='intent-lead',
        permission_mode='acceptEdits',
        stream_file='.intent-stream.jsonl',
        artifact=artifact,
    )


def _make_phase_config() -> PhaseConfig:
    cfg = MagicMock(spec=PhaseConfig)
    cfg.stall_timeout = 1800
    cfg.phase.return_value = _make_phase_spec()
    cfg.team.return_value = MagicMock()
    return cfg


def _make_cfa_state(state: str = 'INTENT') -> CfaState:
    return CfaState(state=state, history=[], backtrack_count=0)


def _make_orchestrator(
    cfa_state: CfaState | None = None,
    last_actor_data: dict | None = None,
    phase_session_ids: dict | None = None,
) -> Orchestrator:
    if cfa_state is None:
        cfa_state = _make_cfa_state()

    from teaparty.cfa.run_options import RunOptions
    return Orchestrator(
        cfa_state=cfa_state,
        phase_config=_make_phase_config(),
        event_bus=_make_event_bus(),
        input_provider=AsyncMock(return_value='approve'),
        infra_dir='/tmp/infra',
        project_workdir='/tmp/project',
        session_worktree='/tmp/worktree',
        proxy_model_path='/tmp/proxy.json',
        project_slug='test-project',
        poc_root='/tmp/poc',
        task='Do the thing',
        session_id='test-session',
        options=RunOptions(
            last_actor_data=last_actor_data or {},
            phase_session_ids=phase_session_ids or {},
        ),
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestBuildInitialMessageBacktrackInjection(unittest.TestCase):
    """First-turn prompt picks up feedback / dialog / stderr from the
    prior phase via ``_last_actor_data``.  The engine carries the same
    invariants the old ``_invoke_actor`` did, but now the injection
    happens once at state entry rather than every turn."""

    def test_stderr_injected(self):
        orch = _make_orchestrator(
            last_actor_data={'stderr_lines': ['Error: tool failed']},
        )
        with patch.object(orch, '_task_for_phase', return_value='do work'):
            prompt = orch._build_initial_message(State.INTENT)
        self.assertIn('[stderr from previous turn]', prompt)
        self.assertIn('Error: tool failed', prompt)

    def test_multiple_stderr_lines_all_injected(self):
        orch = _make_orchestrator(
            last_actor_data={
                'stderr_lines': [
                    'fatal: API key invalid',
                    'Warning: rate limited',
                    'Connection refused',
                ],
            },
        )
        with patch.object(orch, '_task_for_phase', return_value='do work'):
            prompt = orch._build_initial_message(State.INTENT)
        self.assertIn('fatal: API key invalid', prompt)
        self.assertIn('Warning: rate limited', prompt)
        self.assertIn('Connection refused', prompt)

    def test_feedback_injected(self):
        orch = _make_orchestrator(
            last_actor_data={'feedback': 'Focus on auth only.'},
        )
        with patch.object(orch, '_task_for_phase', return_value='do work'):
            prompt = orch._build_initial_message(State.INTENT)
        self.assertIn('[human feedback]', prompt)
        self.assertIn('Focus on auth only.', prompt)
        self.assertIn(
            '[CfA RESPONSE: The human has responded to your escalation.]',
            prompt,
        )

    def test_dialog_history_injected(self):
        dialog = 'Human: What scope?\nProxy: Auth only?\nHuman: Yes.'
        orch = _make_orchestrator(
            last_actor_data={'dialog_history': dialog},
        )
        with patch.object(orch, '_task_for_phase', return_value='do work'):
            prompt = orch._build_initial_message(State.INTENT)
        self.assertIn('[escalation dialog]', prompt)
        self.assertIn('Human: What scope?', prompt)
        self.assertIn('[CfA BACKTRACK: Re-entering from a downstream phase.]', prompt)

    def test_dialog_appears_before_feedback(self):
        orch = _make_orchestrator(
            last_actor_data={
                'feedback': 'Focus on auth only.',
                'dialog_history': 'Human: Narrow the scope.',
            },
        )
        with patch.object(orch, '_task_for_phase', return_value='do work'):
            prompt = orch._build_initial_message(State.INTENT)
        dialog_pos = prompt.index('[escalation dialog]')
        feedback_pos = prompt.index('[human feedback]')
        self.assertLess(dialog_pos, feedback_pos)

    def test_no_injection_when_last_actor_data_empty(self):
        orch = _make_orchestrator(last_actor_data={})
        with patch.object(orch, '_task_for_phase', return_value='do work'):
            prompt = orch._build_initial_message(State.INTENT)
        self.assertNotIn('[human feedback]', prompt)
        self.assertNotIn('[escalation dialog]', prompt)
        self.assertNotIn('[stderr from previous turn]', prompt)
        self.assertNotIn('[CfA BACKTRACK', prompt)
        self.assertNotIn('[CfA RESPONSE', prompt)


class TestBuildInitialMessageResumeHeader(unittest.TestCase):
    """When the engine is about to ``--resume`` an existing claude
    session for this state, the stale-handles header tells the agent
    not to poll the dead task IDs from the previous run."""

    def test_resume_header_present_when_state_has_session_id(self):
        orch = _make_orchestrator(
            phase_session_ids={State.INTENT: 'sid-1'},
        )
        with patch.object(orch, '_task_for_phase', return_value='do work'):
            prompt = orch._build_initial_message(State.INTENT)
        self.assertIn('[SESSION RESUMED — STALE TASK HANDLES]', prompt)

    def test_resume_header_absent_for_fresh_state(self):
        orch = _make_orchestrator(phase_session_ids={})
        with patch.object(orch, '_task_for_phase', return_value='do work'):
            prompt = orch._build_initial_message(State.INTENT)
        self.assertNotIn('[SESSION RESUMED', prompt)


class TestTransitionClearsBacktrackContext(unittest.TestCase):
    """``_transition`` must clear ``feedback`` / ``dialog_history`` on
    cross-state moves so the next state's first turn doesn't pick up
    stale headers."""

    def test_cross_state_transition_clears_feedback(self):
        orch = _make_orchestrator(
            cfa_state=_make_cfa_state(state='INTENT'),
            last_actor_data={'feedback': 'Focus on auth only.'},
        )
        with patch('teaparty.cfa.engine.save_state'), \
             patch.object(orch, '_commit_artifacts', new=AsyncMock()), \
             patch.object(orch, '_detect_and_retire_stage'):
            _run(orch._transition(Action.APPROVED_INTENT))

        self.assertNotIn('feedback', orch._last_actor_data)

    def test_cross_state_transition_clears_dialog_history(self):
        orch = _make_orchestrator(
            cfa_state=_make_cfa_state(state='INTENT'),
            last_actor_data={
                'dialog_history': 'Human: Narrow scope.\nProxy: Auth only?',
            },
        )
        with patch('teaparty.cfa.engine.save_state'), \
             patch.object(orch, '_commit_artifacts', new=AsyncMock()), \
             patch.object(orch, '_detect_and_retire_stage'):
            _run(orch._transition(Action.APPROVED_INTENT))

        self.assertNotIn('dialog_history', orch._last_actor_data)

    def test_cross_state_transition_preserves_other_data(self):
        orch = _make_orchestrator(
            cfa_state=_make_cfa_state(state='INTENT'),
            last_actor_data={
                'feedback': 'cleared',
                'artifact_path': '/tmp/INTENT.md',
                'version': 2,
            },
        )
        with patch('teaparty.cfa.engine.save_state'), \
             patch.object(orch, '_commit_artifacts', new=AsyncMock()), \
             patch.object(orch, '_detect_and_retire_stage'):
            _run(orch._transition(Action.APPROVED_INTENT))

        self.assertNotIn('feedback', orch._last_actor_data)
        self.assertEqual(
            orch._last_actor_data.get('artifact_path'), '/tmp/INTENT.md',
        )
        self.assertEqual(orch._last_actor_data.get('version'), 2)

    def test_transition_keys_session_id_under_old_state(self):
        """The claude_session_id from the turn that just ran is keyed
        under the state we're leaving, not the state we're entering —
        otherwise the next state's ``--resume`` reattaches to the
        wrong claude session."""
        orch = _make_orchestrator(
            cfa_state=_make_cfa_state(state='INTENT'),
        )
        with patch('teaparty.cfa.engine.save_state'), \
             patch.object(orch, '_commit_artifacts', new=AsyncMock()), \
             patch.object(orch, '_detect_and_retire_stage'), \
             patch.object(orch, '_update_lead_bus_session'):
            _run(orch._transition(
                Action.APPROVED_INTENT, claude_session_id='claude-1',
            ))
        self.assertEqual(orch._phase_session_ids[State.INTENT], 'claude-1')


if __name__ == '__main__':
    unittest.main()
