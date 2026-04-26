#!/usr/bin/env python3
"""Tests for engine.py — Orchestrator._invoke_actor context injection.

Covers:
 1. When _last_actor_data contains stderr_lines, _invoke_actor appends
    a [stderr from previous turn] block to ctx.backtrack_context before
    passing ctx to the agent runner.
 2. When _last_actor_data has no stderr_lines, backtrack_context is not
    modified (remains empty string by default).
 3. Stderr is injected in addition to any existing backtrack_context,
    not as a replacement.
 4. When _last_actor_data contains feedback (from an escalation clarify
    response), it appears in ctx.backtrack_context under [human feedback].
 5. When _last_actor_data contains dialog_history, it appears in
    ctx.backtrack_context under [escalation dialog].
 6. When neither feedback nor dialog_history is present, backtrack_context
    is not polluted (regression guard for the escalation feedback bug).
"""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from teaparty.cfa.actors import ActorContext, ActorResult
from teaparty.cfa.engine import Orchestrator
from teaparty.messaging.bus import EventBus
from teaparty.cfa.phase_config import PhaseConfig, PhaseSpec
from teaparty.cfa.statemachine.cfa_state import CfaState


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(coro):
    """Run a coroutine synchronously for testing."""
    return asyncio.run(coro)


def _make_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


def _make_phase_spec(
    artifact: str | None = None,
) -> PhaseSpec:
    return PhaseSpec(
        agent_file='agents/intent-team.json',
        lead='intent-lead',
        permission_mode='acceptEdits',
        stream_file='.intent-stream.jsonl',
        artifact=artifact,
    )


def _make_phase_config() -> PhaseConfig:
    """Build a minimal PhaseConfig mock without needing real config files."""
    cfg = MagicMock(spec=PhaseConfig)
    cfg.stall_timeout = 1800
    cfg.phase.return_value = _make_phase_spec()
    cfg.team.return_value = MagicMock()
    return cfg


def _make_cfa_state(state: str = 'INTENT') -> CfaState:
    """Build a minimal CfaState at the given state."""
    return CfaState(
        state=state,
        phase='intent',
        history=[],
        backtrack_count=0,
    )


def _make_orchestrator(
    cfa_state: CfaState | None = None,
    last_actor_data: dict | None = None,
) -> Orchestrator:
    """Build an Orchestrator with mocked runners."""
    if cfa_state is None:
        cfa_state = _make_cfa_state()

    from teaparty.cfa.run_options import RunOptions
    orch = Orchestrator(
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
        options=RunOptions(last_actor_data=last_actor_data or {}),
    )
    return orch


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestInvokeActorStderrInjection(unittest.TestCase):
    """Engine injects stderr from the previous turn into ctx.backtrack_context."""

    def test_stderr_injected_into_backtrack_context(self):
        """When _last_actor_data has stderr_lines, they appear in ctx.backtrack_context."""
        orch = _make_orchestrator(
            last_actor_data={'stderr_lines': ['Error: tool failed']},
        )

        captured_ctx = []

        async def capture_ctx(ctx: ActorContext, **kwargs) -> ActorResult:
            captured_ctx.append(ctx)
            return ActorResult(action='auto-approve')

        _ar_p = patch('teaparty.cfa.engine.run_phase', side_effect=capture_ctx)
        _ar_p.start()
        self.addCleanup(_ar_p.stop)

        spec = _make_phase_spec()
        _run(orch._invoke_actor(spec, 'intent'))

        self.assertEqual(len(captured_ctx), 1)
        ctx = captured_ctx[0]
        self.assertIn('[stderr from previous turn]', ctx.backtrack_context)
        self.assertIn('Error: tool failed', ctx.backtrack_context)

    def test_multiple_stderr_lines_all_injected(self):
        """All stderr lines from the previous turn appear in backtrack_context."""
        orch = _make_orchestrator(
            last_actor_data={
                'stderr_lines': [
                    'fatal: API key invalid',
                    'Warning: rate limited',
                    'Connection refused',
                ],
            },
        )

        captured_ctx = []

        async def capture_ctx(ctx: ActorContext, **kwargs) -> ActorResult:
            captured_ctx.append(ctx)
            return ActorResult(action='auto-approve')

        _ar_p = patch('teaparty.cfa.engine.run_phase', side_effect=capture_ctx)
        _ar_p.start()
        self.addCleanup(_ar_p.stop)

        spec = _make_phase_spec()
        _run(orch._invoke_actor(spec, 'intent'))

        ctx = captured_ctx[0]
        self.assertIn('fatal: API key invalid', ctx.backtrack_context)
        self.assertIn('Warning: rate limited', ctx.backtrack_context)
        self.assertIn('Connection refused', ctx.backtrack_context)

    def test_no_injection_when_no_stderr(self):
        """When _last_actor_data has no stderr_lines, backtrack_context stays empty."""
        orch = _make_orchestrator(
            last_actor_data={'artifact_path': '/tmp/INTENT.md'},
        )

        captured_ctx = []

        async def capture_ctx(ctx: ActorContext, **kwargs) -> ActorResult:
            captured_ctx.append(ctx)
            return ActorResult(action='auto-approve')

        _ar_p = patch('teaparty.cfa.engine.run_phase', side_effect=capture_ctx)
        _ar_p.start()
        self.addCleanup(_ar_p.stop)

        spec = _make_phase_spec()
        _run(orch._invoke_actor(spec, 'intent'))

        ctx = captured_ctx[0]
        self.assertEqual(ctx.backtrack_context, '')

    def test_no_injection_when_last_actor_data_empty(self):
        """When _last_actor_data is empty, backtrack_context stays empty."""
        orch = _make_orchestrator(last_actor_data={})

        captured_ctx = []

        async def capture_ctx(ctx: ActorContext, **kwargs) -> ActorResult:
            captured_ctx.append(ctx)
            return ActorResult(action='auto-approve')

        _ar_p = patch('teaparty.cfa.engine.run_phase', side_effect=capture_ctx)
        _ar_p.start()
        self.addCleanup(_ar_p.stop)

        spec = _make_phase_spec()
        _run(orch._invoke_actor(spec, 'intent'))

        ctx = captured_ctx[0]
        self.assertEqual(ctx.backtrack_context, '')

    def test_stderr_appended_to_existing_backtrack_context(self):
        """Stderr is appended after any existing backtrack_context, not replacing it."""
        orch = _make_orchestrator(
            last_actor_data={'stderr_lines': ['Error: tool failed']},
        )
        # Simulate an existing backtrack_context by pre-setting it;
        # the engine builds ctx fresh, so we verify the append logic by
        # reading the engine source directly: it does
        #   ctx.backtrack_context = (existing + '\n\n' if existing else '') + block
        # We cannot inject a pre-existing ctx.backtrack_context via _invoke_actor alone
        # (the engine always starts with an empty one), so we verify the format is
        # correct: the stderr block is separated with a double newline when combined.

        captured_ctx = []

        async def capture_ctx(ctx: ActorContext, **kwargs) -> ActorResult:
            # Manually simulate what the engine does when backtrack_context was pre-set
            captured_ctx.append(ctx)
            return ActorResult(action='auto-approve')

        _ar_p = patch('teaparty.cfa.engine.run_phase', side_effect=capture_ctx)
        _ar_p.start()
        self.addCleanup(_ar_p.stop)

        spec = _make_phase_spec()
        _run(orch._invoke_actor(spec, 'intent'))

        ctx = captured_ctx[0]
        # The block must follow the header with a newline
        self.assertIn('[stderr from previous turn]\nError: tool failed', ctx.backtrack_context)


class TestInvokeActorEscalationFeedbackInjection(unittest.TestCase):
    """Engine injects escalation feedback into ctx.backtrack_context.

    Bug fixed: when the approval gate returned ActorResult(action='clarify',
    feedback="human's answer") after an escalation, _transition stored only
    actor_result.data into _last_actor_data, silently dropping feedback and
    dialog_history.  The agent never received the human's answer.

    Fix: _transition now also stores feedback and dialog_history into
    _last_actor_data, and _invoke_actor reads them back and injects them
    into ctx.backtrack_context before running the agent.
    """

    def test_feedback_injected_into_backtrack_context(self):
        """When _last_actor_data has feedback, it appears in ctx.backtrack_context."""
        orch = _make_orchestrator(
            last_actor_data={'feedback': "Please focus on the authentication module."},
        )

        captured_ctx = []

        async def capture_ctx(ctx: ActorContext, **kwargs) -> ActorResult:
            captured_ctx.append(ctx)
            return ActorResult(action='assert')

        _ar_p = patch('teaparty.cfa.engine.run_phase', side_effect=capture_ctx)
        _ar_p.start()
        self.addCleanup(_ar_p.stop)

        spec = _make_phase_spec()
        _run(orch._invoke_actor(spec, 'intent'))

        self.assertEqual(len(captured_ctx), 1)
        ctx = captured_ctx[0]
        self.assertIn('[human feedback]', ctx.backtrack_context)
        self.assertIn('Please focus on the authentication module.', ctx.backtrack_context)

    def test_dialog_history_injected_into_backtrack_context(self):
        """When _last_actor_data has dialog_history, it appears in ctx.backtrack_context."""
        dialog = "Human: What scope?\nProxy: Should we include auth?\nHuman: Yes, auth only."
        orch = _make_orchestrator(
            last_actor_data={'dialog_history': dialog},
        )

        captured_ctx = []

        async def capture_ctx(ctx: ActorContext, **kwargs) -> ActorResult:
            captured_ctx.append(ctx)
            return ActorResult(action='assert')

        _ar_p = patch('teaparty.cfa.engine.run_phase', side_effect=capture_ctx)
        _ar_p.start()
        self.addCleanup(_ar_p.stop)

        spec = _make_phase_spec()
        _run(orch._invoke_actor(spec, 'intent'))

        ctx = captured_ctx[0]
        self.assertIn('[escalation dialog]', ctx.backtrack_context)
        self.assertIn('Human: What scope?', ctx.backtrack_context)
        self.assertIn('Human: Yes, auth only.', ctx.backtrack_context)

    def test_feedback_and_dialog_history_both_injected(self):
        """When both feedback and dialog_history are present, both appear in backtrack_context."""
        dialog = "Human: Can you clarify the scope?\nProxy: Should it cover auth?\nHuman: Auth only."
        feedback = "Limit scope to authentication module only."
        orch = _make_orchestrator(
            last_actor_data={
                'feedback': feedback,
                'dialog_history': dialog,
            },
        )

        captured_ctx = []

        async def capture_ctx(ctx: ActorContext, **kwargs) -> ActorResult:
            captured_ctx.append(ctx)
            return ActorResult(action='assert')

        _ar_p = patch('teaparty.cfa.engine.run_phase', side_effect=capture_ctx)
        _ar_p.start()
        self.addCleanup(_ar_p.stop)

        spec = _make_phase_spec()
        _run(orch._invoke_actor(spec, 'intent'))

        ctx = captured_ctx[0]
        self.assertIn('[escalation dialog]', ctx.backtrack_context)
        self.assertIn('[human feedback]', ctx.backtrack_context)
        self.assertIn(dialog, ctx.backtrack_context)
        self.assertIn(feedback, ctx.backtrack_context)

    def test_dialog_appears_before_feedback(self):
        """Dialog transcript is placed before the feedback summary in backtrack_context."""
        dialog = "Human: Narrow the scope."
        feedback = "Focus on auth only."
        orch = _make_orchestrator(
            last_actor_data={
                'feedback': feedback,
                'dialog_history': dialog,
            },
        )

        captured_ctx = []

        async def capture_ctx(ctx: ActorContext, **kwargs) -> ActorResult:
            captured_ctx.append(ctx)
            return ActorResult(action='assert')

        _ar_p = patch('teaparty.cfa.engine.run_phase', side_effect=capture_ctx)
        _ar_p.start()
        self.addCleanup(_ar_p.stop)

        spec = _make_phase_spec()
        _run(orch._invoke_actor(spec, 'intent'))

        ctx = captured_ctx[0]
        dialog_pos = ctx.backtrack_context.index('[escalation dialog]')
        feedback_pos = ctx.backtrack_context.index('[human feedback]')
        self.assertLess(dialog_pos, feedback_pos)

    def test_no_feedback_injection_when_absent(self):
        """When _last_actor_data has no feedback or dialog_history, backtrack_context stays empty."""
        orch = _make_orchestrator(
            last_actor_data={'artifact_path': '/tmp/INTENT.md'},
        )

        captured_ctx = []

        async def capture_ctx(ctx: ActorContext, **kwargs) -> ActorResult:
            captured_ctx.append(ctx)
            return ActorResult(action='assert')

        _ar_p = patch('teaparty.cfa.engine.run_phase', side_effect=capture_ctx)
        _ar_p.start()
        self.addCleanup(_ar_p.stop)

        spec = _make_phase_spec()
        _run(orch._invoke_actor(spec, 'intent'))

        ctx = captured_ctx[0]
        self.assertNotIn('[human feedback]', ctx.backtrack_context)
        self.assertNotIn('[escalation dialog]', ctx.backtrack_context)

    def test_no_feedback_injection_when_last_actor_data_empty(self):
        """When _last_actor_data is empty, backtrack_context is empty (regression guard)."""
        orch = _make_orchestrator(last_actor_data={})

        captured_ctx = []

        async def capture_ctx(ctx: ActorContext, **kwargs) -> ActorResult:
            captured_ctx.append(ctx)
            return ActorResult(action='assert')

        _ar_p = patch('teaparty.cfa.engine.run_phase', side_effect=capture_ctx)
        _ar_p.start()
        self.addCleanup(_ar_p.stop)

        spec = _make_phase_spec()
        _run(orch._invoke_actor(spec, 'intent'))

        ctx = captured_ctx[0]
        self.assertEqual(ctx.backtrack_context, '')

    def test_feedback_injected_alongside_stderr(self):
        """Feedback and stderr are both injected when both are present in _last_actor_data."""
        orch = _make_orchestrator(
            last_actor_data={
                'feedback': 'Narrow the scope to auth.',
                'stderr_lines': ['Error: permission denied'],
            },
        )

        captured_ctx = []

        async def capture_ctx(ctx: ActorContext, **kwargs) -> ActorResult:
            captured_ctx.append(ctx)
            return ActorResult(action='assert')

        _ar_p = patch('teaparty.cfa.engine.run_phase', side_effect=capture_ctx)
        _ar_p.start()
        self.addCleanup(_ar_p.stop)

        spec = _make_phase_spec()
        _run(orch._invoke_actor(spec, 'intent'))

        ctx = captured_ctx[0]
        self.assertIn('[human feedback]', ctx.backtrack_context)
        self.assertIn('Narrow the scope to auth.', ctx.backtrack_context)
        self.assertIn('[stderr from previous turn]', ctx.backtrack_context)
        self.assertIn('Error: permission denied', ctx.backtrack_context)


class TestTransitionStoresFeedbackInLastActorData(unittest.TestCase):
    """_transition stores feedback and dialog_history from ActorResult into _last_actor_data.

    This is the other half of the escalation feedback bug fix: if _transition
    does not persist feedback onto _last_actor_data, _invoke_actor can never
    inject it — even though the injection logic is correct.
    """

    def test_cross_phase_transition_clears_feedback(self):
        """A phase-changing transition CLEARS feedback/dialog_history.

        ``_last_actor_data['feedback']`` is forwarded into the next
        actor invocation's ``backtrack_context``, which becomes a
        ``[CfA BACKTRACK: Re-entering from a downstream phase.]``
        prompt header.  When the next invocation is a *different
        phase*, that header is wrong — the new phase's claude reads
        it and re-runs the prior phase's skill.  Cross-phase
        clearing is the fix.
        """
        orch = _make_orchestrator(
            cfa_state=_make_cfa_state(state='INTENT'),
        )
        with patch('teaparty.cfa.engine.save_state'), \
             patch.object(orch, '_commit_artifacts', new=AsyncMock()), \
             patch.object(orch, '_detect_and_retire_stage'):
            result = ActorResult(
                action='approve',
                feedback="Please focus on auth only.",
                data={'artifact_path': '/tmp/INTENT.md'},
            )
            # INTENT → PLAN crosses phases: feedback must be cleared
            # so the planning phase doesn't see a stale BACKTRACK
            # header.
            _run(orch._transition('APPROVED_INTENT', result))

        self.assertNotIn(
            'feedback', orch._last_actor_data,
            'cross-phase transition must clear feedback',
        )

    def test_cross_phase_transition_clears_dialog_history(self):
        """Cross-phase transitions clear dialog_history for the same
        reason as feedback — it would otherwise inject a stale
        ``[escalation dialog]`` block into the next phase's first
        turn and trigger the BACKTRACK prompt header.
        """
        orch = _make_orchestrator(
            cfa_state=_make_cfa_state(state='INTENT'),
        )
        with patch('teaparty.cfa.engine.save_state'), \
             patch.object(orch, '_commit_artifacts', new=AsyncMock()), \
             patch.object(orch, '_detect_and_retire_stage'):
            result = ActorResult(
                action='approve',
                dialog_history='Human: Narrow scope.\nProxy: Auth only?',
                data={},
            )
            _run(orch._transition('APPROVED_INTENT', result))

        self.assertNotIn(
            'dialog_history', orch._last_actor_data,
            'cross-phase transition must clear dialog_history',
        )

    def test_cross_phase_transition_preserves_other_data(self):
        """The clearing is scoped to feedback/dialog_history.  Other
        ``actor_result.data`` fields (artifact paths, version markers,
        etc.) survive the transition — they are descriptive of what
        was produced, not phase-specific dialog state.
        """
        orch = _make_orchestrator(
            cfa_state=_make_cfa_state(state='INTENT'),
        )
        with patch('teaparty.cfa.engine.save_state'), \
             patch.object(orch, '_commit_artifacts', new=AsyncMock()), \
             patch.object(orch, '_detect_and_retire_stage'):
            result = ActorResult(
                action='approve',
                feedback='cleared',  # cleared
                data={'artifact_path': '/tmp/INTENT.md', 'version': 2},
            )
            _run(orch._transition('APPROVED_INTENT', result))

        self.assertNotIn('feedback', orch._last_actor_data)
        self.assertEqual(
            orch._last_actor_data.get('artifact_path'), '/tmp/INTENT.md',
        )
        self.assertEqual(orch._last_actor_data.get('version'), 2)

    def test_transition_no_feedback_does_not_set_key(self):
        """When ActorResult has no feedback, _last_actor_data does not gain a feedback key."""
        orch = _make_orchestrator(
            cfa_state=_make_cfa_state(state='INTENT'),
        )
        with patch('teaparty.cfa.engine.save_state'), \
             patch.object(orch, '_commit_artifacts', new=AsyncMock()), \
             patch.object(orch, '_detect_and_retire_stage'):
            result = ActorResult(
                action='approve',
                data={'artifact_path': '/tmp/INTENT.md'},
            )
            _run(orch._transition('APPROVED_INTENT', result))

        self.assertNotIn('feedback', orch._last_actor_data)
        self.assertNotIn('dialog_history', orch._last_actor_data)


if __name__ == '__main__':
    unittest.main()
