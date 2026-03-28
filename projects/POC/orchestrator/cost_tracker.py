"""Cost budget tracking for orchestrator jobs.

Accumulates cost from stream-json result events and checks against
budget limits.  The orchestrator creates one CostTracker per job,
feeds it result events as they arrive, and checks warning_triggered
and limit_reached at turn boundaries.

Budget enforcement is mechanical (not advisory like norms):
  - Warns at 80% of job_limit_usd
  - Pauses at 100% of job_limit_usd

Project-level aggregation: ProjectCostLedger persists per-turn cost
records to a JSONL file.  The orchestrator checks project_limit_usd
against the aggregate across all jobs.

See docs/proposals/context-budget/references/cost-budget.md for design.
"""
from __future__ import annotations

import json
import os
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
    def project_limit(self) -> float:
        return self._budget.get('project_limit_usd', 0.0)

    @property
    def limit_reached(self) -> bool:
        """True when cost reaches 100% of job_limit_usd."""
        if not self.job_limit:
            return False
        return self._total_cost >= self.job_limit * LIMIT_THRESHOLD


# ── Project-level cost ledger ────────────────────────────────────────────────

_LEDGER_FILENAME = '.cost-ledger.jsonl'


class ProjectCostLedger:
    """Persists per-turn cost records and aggregates across jobs.

    Each record is a JSONL line: {"session_id": ..., "cost_usd": ...}.
    The ledger file lives in the project's .teaparty/ directory.
    """

    def __init__(self, project_dir: str):
        self._dir = os.path.join(project_dir, '.teaparty')
        self._path = os.path.join(self._dir, _LEDGER_FILENAME)

    def record(self, session_id: str, cost_usd: float) -> None:
        """Append a cost record for a session turn."""
        if cost_usd <= 0:
            return
        os.makedirs(self._dir, exist_ok=True)
        entry = json.dumps({'session_id': session_id, 'cost_usd': cost_usd})
        with open(self._path, 'a') as f:
            f.write(entry + '\n')

    def total_cost(self) -> float:
        """Sum all cost records across all sessions."""
        if not os.path.exists(self._path):
            return 0.0
        total = 0.0
        with open(self._path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    total += entry.get('cost_usd', 0.0)
                except json.JSONDecodeError:
                    continue
        return total

    def session_cost(self, session_id: str) -> float:
        """Sum cost records for a specific session."""
        if not os.path.exists(self._path):
            return 0.0
        total = 0.0
        with open(self._path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get('session_id') == session_id:
                        total += entry.get('cost_usd', 0.0)
                except json.JSONDecodeError:
                    continue
        return total
