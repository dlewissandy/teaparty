"""Scripted input providers for headless experiment runs.

All experiments run without human interaction. These providers simulate
human approval decisions at CfA gates so experiments can test all
combinations automatically.

Each provider implements the InputProvider protocol from
projects.POC.orchestrator.actors — an async callable that takes an
InputRequest and returns a response string.
"""
from __future__ import annotations

import logging
import random

from orchestrator.events import InputRequest

_log = logging.getLogger('experiments.input_providers')


class AlwaysApproveProvider:
    """Auto-approve every gate. Baseline for proxy-free runs."""

    async def __call__(self, request: InputRequest) -> str:
        _log.debug('AlwaysApprove: %s → approve', request.state)
        return 'approve'


class ScriptedProvider:
    """Replay a deterministic sequence of decisions per CfA state.

    Simulates a consistent human whose preferences the proxy can learn.
    Decisions are keyed by state (e.g., INTENT_ASSERT → approve,
    PLAN_ASSERT → correct with feedback).

    When the script for a state is exhausted, the last decision repeats.
    States not in the script default to "approve".

    Example:
        provider = ScriptedProvider({
            "INTENT_ASSERT": ["approve"],
            "PLAN_ASSERT": ["correct: add error handling", "approve"],
            "WORK_ASSERT": ["approve"],
        })
    """

    def __init__(self, script: dict[str, list[str]]):
        self._script = script
        self._cursors: dict[str, int] = {}

    async def __call__(self, request: InputRequest) -> str:
        state = request.state
        if state not in self._script:
            _log.debug('ScriptedProvider: %s (unscripted) → approve', state)
            return 'approve'

        idx = self._cursors.get(state, 0)
        decisions = self._script[state]
        decision = decisions[min(idx, len(decisions) - 1)]
        self._cursors[state] = idx + 1

        _log.debug('ScriptedProvider: %s [%d] → %s', state, idx, decision)
        return decision

    def reset(self) -> None:
        """Reset all cursors for a fresh run."""
        self._cursors.clear()


class PatternProvider:
    """Simulate a human with a fixed approval rate per state.

    For proxy convergence: e.g., 80% approve at PLAN_ASSERT,
    90% at INTENT_ASSERT. Uses a seeded RNG for reproducibility
    across runs.

    When the provider rejects, it returns a correction with the
    configured feedback text. This simulates a human who has
    consistent preferences that the proxy should learn to predict.

    Example:
        provider = PatternProvider(
            rates={"INTENT_ASSERT": 0.95, "PLAN_ASSERT": 0.80, "WORK_ASSERT": 0.85},
            seed=42,
            correction_feedback="Please add error handling and tests",
        )
    """

    def __init__(
        self,
        rates: dict[str, float] | None = None,
        seed: int = 42,
        correction_feedback: str = 'Please add error handling',
        default_rate: float = 0.85,
    ):
        self._rates = rates or {}
        self._default_rate = default_rate
        self._correction_feedback = correction_feedback
        self._rng = random.Random(seed)
        self._decision_log: list[dict] = []

    async def __call__(self, request: InputRequest) -> str:
        rate = self._rates.get(request.state, self._default_rate)
        roll = self._rng.random()
        approved = roll < rate

        decision = 'approve' if approved else f'correct: {self._correction_feedback}'
        self._decision_log.append({
            'state': request.state,
            'rate': rate,
            'roll': round(roll, 4),
            'decision': decision,
        })

        _log.debug(
            'PatternProvider: %s (rate=%.2f, roll=%.4f) → %s',
            request.state, rate, roll, decision,
        )
        return decision

    @property
    def decisions(self) -> list[dict]:
        """Access the full decision log for analysis."""
        return list(self._decision_log)

    def reset(self, seed: int | None = None) -> None:
        """Reset RNG and decision log. Optionally change seed."""
        if seed is not None:
            self._rng = random.Random(seed)
        self._decision_log.clear()


def make_provider(
    mode: str,
    *,
    rates: dict[str, float] | None = None,
    seed: int = 42,
    script: dict[str, list[str]] | None = None,
    correction_feedback: str = 'Please add error handling',
    default_rate: float = 0.85,
):
    """Factory for input providers.

    Args:
        mode: "auto-approve", "scripted", or "pattern"
        rates: approval rates per state (for pattern mode)
        seed: RNG seed (for pattern mode)
        script: decision sequences per state (for scripted mode)
        correction_feedback: text returned on correction
        default_rate: fallback approval rate for unspecified states
    """
    if mode == 'auto-approve':
        return AlwaysApproveProvider()
    elif mode == 'scripted':
        if not script:
            raise ValueError('ScriptedProvider requires a script dict')
        return ScriptedProvider(script)
    elif mode == 'pattern':
        return PatternProvider(
            rates=rates,
            seed=seed,
            correction_feedback=correction_feedback,
            default_rate=default_rate,
        )
    else:
        raise ValueError(f'Unknown input mode: {mode!r}')
