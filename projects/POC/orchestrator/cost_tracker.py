"""Cost budget tracking for orchestrator jobs.

Accumulates cost from stream-json result events and checks against
budget limits.  The orchestrator creates one CostTracker per job,
feeds it result events as they arrive, and checks warning_triggered
and limit_reached at turn boundaries.

Budget enforcement is mechanical (not advisory like norms):
  - Warns at 80% of job_limit_usd
  - Pauses at 100% of job_limit_usd

See docs/proposals/context-budget/references/cost-budget.md for design.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

WARNING_THRESHOLD = 0.8
LIMIT_THRESHOLD = 1.0


class CostTracker:
    """Tracks cumulative cost for a single job against budget limits."""

    def __init__(self, budget: dict[str, float] | None = None):
        self._budget = budget or {}
        self._total_cost: float = 0.0
        self._model_costs: dict[str, float] = defaultdict(float)

    def record(self, event: dict[str, Any]) -> None:
        """Record cost from a stream-json event.

        Only processes events with type 'result' that include cost data.
        Silently ignores events without cost fields.
        """
        if event.get('type') != 'result':
            return

        cost = event.get('total_cost_usd', 0.0)
        if cost:
            self._total_cost += cost

        per_model = event.get('cost_usd', {})
        if isinstance(per_model, dict):
            for model, model_cost in per_model.items():
                self._model_costs[model] += model_cost

    @property
    def total_cost_usd(self) -> float:
        return self._total_cost

    @property
    def model_costs(self) -> dict[str, float]:
        return dict(self._model_costs)

    @property
    def job_limit(self) -> float:
        return self._budget.get('job_limit_usd', 0.0)

    @property
    def utilization(self) -> float:
        """Cost as a fraction of job_limit_usd. Returns 0.0 if no limit set."""
        if not self.job_limit:
            return 0.0
        return self._total_cost / self.job_limit

    @property
    def warning_triggered(self) -> bool:
        """True when cost reaches 80% of job_limit_usd."""
        if not self.job_limit:
            return False
        return self._total_cost >= self.job_limit * WARNING_THRESHOLD

    @property
    def limit_reached(self) -> bool:
        """True when cost reaches 100% of job_limit_usd."""
        if not self.job_limit:
            return False
        return self._total_cost >= self.job_limit * LIMIT_THRESHOLD
