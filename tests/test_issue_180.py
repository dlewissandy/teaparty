#!/usr/bin/env python3
"""Tests for issue #180: blocking subprocess.run() calls starve async event loop.

_classify_review and _generate_dialog_response call subprocess.run() with
30-second timeouts directly from async ApprovalGate.run(). They must be
offloaded to run_in_executor so the event loop stays alive for event bus
publishing, TUI updates, and the stall watchdog.

Behavioral test design:
  The blocking method sets a threading.Event when it starts and clears it
  when it finishes. A concurrent asyncio task polls for the event. If the
  event loop is not starved, the concurrent task sees the event while it
  is still set (during the block). If the loop IS starved, the concurrent
  task never gets scheduled during the block, and can only run after the
  event has been cleared — proving starvation.
"""
import asyncio
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from orchestrator.actors import (
    ActorContext,
    ApprovalGate,
)
from orchestrator.events import EventBus
from orchestrator.phase_config import PhaseSpec
from orchestrator.proxy_agent import ProxyResult


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_event_bus() -> EventBus:
    bus = MagicMock(spec=EventBus)
    bus.publish = AsyncMock()
    return bus


def _make_phase_spec() -> PhaseSpec:
    return PhaseSpec(
        name='intent',
        agent_file='agents/intent-team.json',
        lead='intent-lead',
        permission_mode='acceptEdits',
        stream_file='.intent-stream.jsonl',
        artifact='INTENT.md',
        approval_state='INTENT_ASSERT',
        settings_overlay={},
    )


def _make_ctx(state: str = 'INTENT_ASSERT') -> ActorContext:
    return ActorContext(
        state=state,
        phase='intent',
        task='Write a blog post about AI',
        infra_dir='/tmp/infra',
        project_workdir='/tmp/project',
        session_worktree='/tmp/worktree',
        stream_file='.intent-stream.jsonl',
        phase_spec=_make_phase_spec(),
        poc_root='/tmp/poc',
        event_bus=_make_event_bus(),
        session_id='test-session',
    )


def _make_gate() -> ApprovalGate:
    return ApprovalGate(
        proxy_model_path='/tmp/.proxy.json',
        input_provider=AsyncMock(),
        poc_root='/tmp/poc',
    )


def _run(coro):
    return asyncio.run(coro)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestClassifyReviewNotBlocking(unittest.TestCase):
    """_classify_review must not block the event loop when called from run()."""

    def test_classify_review_does_not_starve_event_loop(self):
        """A concurrent asyncio task must be able to execute DURING
        _classify_review, not just after it returns."""
        gate = _make_gate()
        ctx = _make_ctx()

        # in_progress is True only while the blocking call is executing.
        in_progress = threading.Event()
        saw_in_progress = []  # concurrent task appends here if loop not starved

        def slow_classify(*args, **kwargs):
            in_progress.set()
            time.sleep(0.5)
            in_progress.clear()
            return ('approve', '')

        proxy_result = ProxyResult(
            text='looks good', confidence=0.95, from_agent=True,
        )

        async def run_test():
            async def concurrent_task():
                # Poll until we see the blocking call in progress
                for _ in range(100):  # 100 * 10ms = 1s max
                    if in_progress.is_set():
                        saw_in_progress.append(True)
                        return
                    await asyncio.sleep(0.01)

            with patch('orchestrator.proxy_agent.consult_proxy',
                       new=AsyncMock(return_value=proxy_result)), \
                 patch.object(gate, '_classify_review',
                              side_effect=slow_classify), \
                 patch.object(gate, '_proxy_record'), \
                 patch.object(gate, '_generate_bridge', return_value='Review:'):
                gate_task = asyncio.create_task(gate.run(ctx))
                bg_task = asyncio.create_task(concurrent_task())
                result = await gate_task
                if not bg_task.done():
                    bg_task.cancel()
                    try:
                        await bg_task
                    except asyncio.CancelledError:
                        pass

            return result

        result = _run(run_test())

        self.assertEqual(result.action, 'approve')
        self.assertTrue(
            saw_in_progress,
            '_classify_review blocked the event loop — concurrent task '
            'never ran while classify was in progress. '
            'Wrap the call in asyncio.get_running_loop().run_in_executor().'
        )


class TestGenerateDialogResponseNotBlocking(unittest.TestCase):
    """_generate_dialog_response must not block the event loop."""

    def test_generate_dialog_does_not_starve_event_loop(self):
        """A concurrent asyncio task must be able to execute DURING
        _generate_dialog_response."""
        gate = _make_gate()
        ctx = _make_ctx()

        in_progress = threading.Event()
        saw_in_progress = []
        call_count = [0]

        def slow_dialog(*args, **kwargs):
            in_progress.set()
            time.sleep(0.5)
            in_progress.clear()
            return 'Here is my answer.'

        def classify_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return ('dialog', 'What approach did you use?')
            return ('approve', '')

        proxy_results = iter([
            ProxyResult(text='What approach?', confidence=0.95,
                        from_agent=True),
            ProxyResult(text='looks good', confidence=0.95,
                        from_agent=True),
        ])

        async def run_test():
            async def concurrent_task():
                for _ in range(100):
                    if in_progress.is_set():
                        saw_in_progress.append(True)
                        return
                    await asyncio.sleep(0.01)

            with patch('orchestrator.proxy_agent.consult_proxy',
                       new=AsyncMock(
                           side_effect=lambda **kw: next(proxy_results))), \
                 patch.object(gate, '_classify_review',
                              side_effect=classify_side_effect), \
                 patch.object(gate, '_generate_dialog_response',
                              side_effect=slow_dialog), \
                 patch.object(gate, '_proxy_record'), \
                 patch.object(gate, '_generate_bridge', return_value='Review:'):
                gate_task = asyncio.create_task(gate.run(ctx))
                bg_task = asyncio.create_task(concurrent_task())
                result = await gate_task
                if not bg_task.done():
                    bg_task.cancel()
                    try:
                        await bg_task
                    except asyncio.CancelledError:
                        pass

            return result

        result = _run(run_test())

        # After dialog, approve is converted to correct (line 638 of actors.py)
        self.assertEqual(result.action, 'correct')
        self.assertTrue(
            saw_in_progress,
            '_generate_dialog_response blocked the event loop — concurrent '
            'task never ran while dialog generation was in progress. '
            'Wrap the call in asyncio.get_running_loop().run_in_executor().'
        )


if __name__ == '__main__':
    unittest.main()
