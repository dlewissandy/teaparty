"""Tests for Issue #216: Fast-fail on degraded CLI in proxy agent.

`run_proxy_agent()` makes up to three sequential `claude -p` calls:
Pass 1 (prior, 60s), Pass 2 (posterior, 60s), surprise extraction (30s).
If the CLI is degraded, a single gate decision takes up to 150 seconds.

These tests verify that:
1. When Pass 1 fails, Pass 2 and surprise extraction are skipped.
2. When Pass 2 fails, surprise extraction is skipped (and prior result used).
3. When all passes succeed, behavior is unchanged.
"""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import patch, AsyncMock


def _make_invoke_result(text: str, confidence: float, action: str):
    """Build a return value for _invoke_claude_proxy."""
    return (text, confidence, action)


def _make_failing_invoke():
    """Build a return value simulating a failed _invoke_claude_proxy call."""
    return ('', 0.0, '')


class TestFastFailOnPass1Failure(unittest.TestCase):
    """When Pass 1 (prior) fails, Pass 2 and surprise extraction are skipped."""

    def test_pass2_not_called_when_pass1_fails(self):
        from projects.POC.orchestrator.proxy_agent import run_proxy_agent

        call_count = 0

        async def mock_invoke(prompt, session_worktree):
            nonlocal call_count
            call_count += 1
            return _make_failing_invoke()

        with patch(
            'projects.POC.orchestrator.proxy_agent._invoke_claude_proxy',
            side_effect=mock_invoke,
        ):
            result = asyncio.run(run_proxy_agent(
                'Review the plan',
                state='PLAN_ASSERT',
            ))

        self.assertEqual(result.text, '')
        self.assertEqual(result.confidence, 0.0)
        # Fast-fail: only Pass 1 should have been called
        self.assertEqual(call_count, 1,
                         f'Expected 1 _invoke_claude_proxy call (Pass 1 only), got {call_count}')

    def test_surprise_extraction_not_called_when_pass1_fails(self):
        from projects.POC.orchestrator.proxy_agent import run_proxy_agent

        with patch(
            'projects.POC.orchestrator.proxy_agent._invoke_claude_proxy',
            new_callable=AsyncMock,
            return_value=_make_failing_invoke(),
        ), patch(
            'projects.POC.orchestrator.proxy_agent._extract_surprise',
            new_callable=AsyncMock,
        ) as mock_surprise:
            asyncio.run(run_proxy_agent(
                'Review the plan',
                state='PLAN_ASSERT',
            ))

        mock_surprise.assert_not_called()


class TestFastFailOnPass2Failure(unittest.TestCase):
    """When Pass 2 (posterior) fails, surprise extraction is skipped and prior is used."""

    def test_returns_prior_result_when_pass2_fails(self):
        from projects.POC.orchestrator.proxy_agent import run_proxy_agent

        call_count = 0

        async def mock_invoke(prompt, session_worktree):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Pass 1 succeeds
                return _make_invoke_result(
                    'I predict approval', 0.8, 'approve',
                )
            # Pass 2 fails
            return _make_failing_invoke()

        with patch(
            'projects.POC.orchestrator.proxy_agent._invoke_claude_proxy',
            side_effect=mock_invoke,
        ):
            result = asyncio.run(run_proxy_agent(
                'Review the plan',
                state='PLAN_ASSERT',
            ))

        # Should fall back to prior result
        self.assertEqual(result.text, 'I predict approval')
        self.assertEqual(result.prior_action, 'approve')
        self.assertEqual(result.prior_confidence, 0.8)
        # Only 2 calls (Pass 1 + Pass 2), no surprise extraction invoke
        self.assertEqual(call_count, 2)

    def test_surprise_extraction_not_called_when_pass2_fails(self):
        from projects.POC.orchestrator.proxy_agent import run_proxy_agent

        call_count = 0

        async def mock_invoke(prompt, session_worktree):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Pass 1 succeeds with action that would trigger surprise
                return _make_invoke_result('Prior text', 0.8, 'approve')
            # Pass 2 fails
            return _make_failing_invoke()

        with patch(
            'projects.POC.orchestrator.proxy_agent._invoke_claude_proxy',
            side_effect=mock_invoke,
        ), patch(
            'projects.POC.orchestrator.proxy_agent._extract_surprise',
            new_callable=AsyncMock,
            return_value=('delta', ['percept']),
        ) as mock_surprise:
            asyncio.run(run_proxy_agent(
                'Review the plan',
                state='PLAN_ASSERT',
            ))

        mock_surprise.assert_not_called()


class TestNormalPathUnchanged(unittest.TestCase):
    """When all passes succeed, the full pipeline runs as before."""

    def test_both_passes_succeed_returns_posterior(self):
        from projects.POC.orchestrator.proxy_agent import run_proxy_agent

        call_count = 0

        async def mock_invoke(prompt, session_worktree):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_invoke_result('Prior text', 0.7, 'approve')
            return _make_invoke_result('Posterior text', 0.9, 'approve')

        with patch(
            'projects.POC.orchestrator.proxy_agent._invoke_claude_proxy',
            side_effect=mock_invoke,
        ):
            result = asyncio.run(run_proxy_agent(
                'Review the plan',
                state='PLAN_ASSERT',
            ))

        self.assertEqual(result.text, 'Posterior text')
        self.assertEqual(result.confidence, 0.9)
        self.assertEqual(result.posterior_action, 'approve')
        self.assertEqual(call_count, 2)

    def test_surprise_extraction_runs_when_action_changes(self):
        from projects.POC.orchestrator.proxy_agent import run_proxy_agent

        call_count = 0

        async def mock_invoke(prompt, session_worktree):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_invoke_result('Prior text', 0.7, 'approve')
            return _make_invoke_result('Posterior text', 0.9, 'correct')

        with patch(
            'projects.POC.orchestrator.proxy_agent._invoke_claude_proxy',
            side_effect=mock_invoke,
        ), patch(
            'projects.POC.orchestrator.proxy_agent._extract_surprise',
            new_callable=AsyncMock,
            return_value=('Something changed', ['feature A']),
        ) as mock_surprise:
            result = asyncio.run(run_proxy_agent(
                'Review the plan',
                state='PLAN_ASSERT',
            ))

        mock_surprise.assert_called_once()
        self.assertEqual(result.prediction_delta, 'Something changed')
        self.assertEqual(result.salient_percepts, ['feature A'])


if __name__ == '__main__':
    unittest.main()
