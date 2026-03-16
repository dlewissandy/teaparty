#!/usr/bin/env python3
"""Tests for issue #155: Proxy at TASK_ASSERT has no artifact — returns empty.

When artifact_path is empty at TASK_ASSERT, the proxy has nothing to review
and returns empty text. Because TASK_ASSERT is in _NEVER_ESCALATE_STATES,
the empty text is returned directly to _classify_review, which maps it to
__fallback__, creating an infinite retry loop.

Tests verify:
  1. When proxy returns empty at a _NEVER_ESCALATE state, the gate auto-approves
     after a bounded number of retries (not infinite loop)
  2. The proxy prompt includes session_worktree context when artifact_path is empty
  3. The fallback limit only applies to _NEVER_ESCALATE_STATES, not human-facing gates
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
    ApprovalGate,
    _NEVER_ESCALATE_STATES,
)
from projects.POC.orchestrator.events import EventBus
from projects.POC.orchestrator.phase_config import PhaseSpec
from projects.POC.orchestrator.proxy_agent import ProxyResult


def _run(coro):
    return asyncio.run(coro)


def _make_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


def _make_phase_spec() -> PhaseSpec:
    return PhaseSpec(
        name='execution',
        agent_file='agents/uber-team.json',
        lead='project-lead',
        permission_mode='acceptEdits',
        stream_file='.exec-stream.jsonl',
        artifact='.work-summary.md',
        approval_state='WORK_ASSERT',
        settings_overlay={},
    )


def _make_ctx(
    state: str = 'TASK_ASSERT',
    session_worktree: str = '/tmp/worktree',
    infra_dir: str = '/tmp/infra',
) -> ActorContext:
    return ActorContext(
        state=state,
        phase='execution',
        task='Write 58 math jokes',
        infra_dir=infra_dir,
        project_workdir='/tmp/project',
        session_worktree=session_worktree,
        stream_file='.exec-stream.jsonl',
        phase_spec=_make_phase_spec(),
        poc_root='/tmp/poc',
        event_bus=_make_event_bus(),
        session_id='test-session',
    )


# ── Fallback limit at _NEVER_ESCALATE states ────────────────────────────


class TestFallbackLimitAtNeverEscalateStates(unittest.TestCase):
    """Empty proxy responses must not produce infinite retry loops."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_proxy_does_not_loop_forever(self):
        """When proxy consistently returns empty at TASK_ASSERT, gate must
        terminate (auto-approve) rather than loop infinitely."""
        MAX_ACCEPTABLE_RETRIES = 5
        classify_calls = []

        gate = ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=AsyncMock(return_value='approve'),
            poc_root=self.tmpdir,
        )
        ctx = _make_ctx(session_worktree=self.tmpdir, infra_dir=self.tmpdir)
        ctx.data = {}

        class _TooManyRetries(Exception):
            pass

        def _counting_classify(state, response, dialog_history='',
                               intent_summary='', plan_summary=''):
            classify_calls.append(response)
            if len(classify_calls) > MAX_ACCEPTABLE_RETRIES:
                raise _TooManyRetries(
                    f'Gate looped {len(classify_calls)} times — infinite loop')
            return ('__fallback__', '')

        with patch('projects.POC.orchestrator.proxy_agent.consult_proxy',
                   new=AsyncMock(return_value=ProxyResult(
                       text='', confidence=0.0, from_agent=False))), \
             patch.object(gate, '_classify_review', side_effect=_counting_classify), \
             patch.object(gate, '_proxy_record'):
            try:
                result = _run(gate.run(ctx))
            except _TooManyRetries:
                self.fail(
                    f'Gate retried __fallback__ {len(classify_calls)} times '
                    f'at TASK_ASSERT — infinite loop. Must terminate with '
                    f'auto-approve after bounded retries.')

        # If we get here, the gate terminated. Verify it auto-approved.
        self.assertLessEqual(len(classify_calls), MAX_ACCEPTABLE_RETRIES)
        self.assertEqual(result.action, 'approve',
                         "At _NEVER_ESCALATE states, fallback should auto-approve")

    def test_fallback_limit_does_not_apply_to_human_facing_gates(self):
        """At INTENT_ASSERT (human-facing), __fallback__ should re-prompt
        the human, not auto-approve after a limit."""
        classify_call_count = 0
        classify_results = iter([
            ('__fallback__', ''),
            ('__fallback__', ''),
            ('approve', ''),
        ])

        async def _input_provider(req):
            return 'approve'

        gate = ApprovalGate(
            proxy_model_path=os.path.join(self.tmpdir, '.proxy.json'),
            input_provider=_input_provider,
            poc_root=self.tmpdir,
        )
        ctx = _make_ctx(state='INTENT_ASSERT',
                        session_worktree=self.tmpdir,
                        infra_dir=self.tmpdir)
        ctx.data = {}

        def _classify(*a, **kw):
            nonlocal classify_call_count
            classify_call_count += 1
            return next(classify_results)

        with patch('projects.POC.orchestrator.proxy_agent.consult_proxy',
                   new=AsyncMock(return_value=ProxyResult(
                       text='looks good', confidence=0.0, from_agent=False))), \
             patch.object(gate, '_classify_review', side_effect=_classify), \
             patch.object(gate, '_proxy_record'):
            result = _run(gate.run(ctx))

        # At human-facing gates, fallback retries until classifier succeeds.
        # Must have called classify 3 times (2 fallbacks + 1 approve).
        self.assertEqual(classify_call_count, 3,
                         "Human-facing gates must retry on __fallback__, not limit")


# ── Proxy receives worktree context when artifact_path is empty ──────────


class TestProxyReceivesWorktreeContext(unittest.TestCase):
    """When artifact_path is empty, proxy prompt must reference session_worktree."""

    def test_proxy_prompt_directs_review_of_worktree_when_no_artifact(self):
        """run_proxy_agent at TASK_ASSERT with empty artifact_path must direct
        the proxy to review deliverables in the session worktree."""
        tmpdir = tempfile.mkdtemp()
        try:
            Path(os.path.join(tmpdir, 'output.txt')).write_text('deliverable')
            Path(os.path.join(tmpdir, 'INTENT.md')).write_text('# Intent')

            with patch('subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(
                    returncode=0,
                    stdout='Looks correct.\nCONFIDENCE: 0.9',
                )
                from projects.POC.orchestrator.proxy_agent import run_proxy_agent
                _run(run_proxy_agent(
                    question='Does this work look like your task?',
                    state='TASK_ASSERT',
                    artifact_path='',  # empty — the bug
                    session_worktree=tmpdir,
                    infra_dir=tmpdir,
                ))

            # The prompt must explicitly tell the proxy to review the worktree
            # deliverables, not just happen to include the worktree path via
            # upstream context.
            prompt = mock_run.call_args[1].get('input', '')
            self.assertIn('deliverables', prompt.lower(),
                          "Proxy prompt must direct review of worktree "
                          "deliverables when artifact_path is empty")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == '__main__':
    unittest.main()
