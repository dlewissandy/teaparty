"""Cost + context-budget monitoring for the CfA orchestrator.

Three subsystems lived inline in ``Orchestrator`` (``engine.py``):

  - **Context budget** — at every turn boundary the actor's
    ``ClaudeResult.context_budget`` is inspected; at the warning
    threshold we publish ``CONTEXT_WARNING``, at the compact
    threshold we inject a ``/compact`` intervention prompt.

  - **Cost budget (job)** — the ``CostTracker`` accumulates
    ``total_cost_usd``.  At 80 % we publish ``COST_WARNING`` (once);
    at 100 % we publish ``COST_LIMIT`` and block the next turn on a
    human decision (continue / stop).

  - **Cost budget (project)** — aggregate across all jobs via the
    ``ProjectCostLedger``.  Same warning / limit behaviour.

All three are stateless in their logic but carry "once-per-job"
flags (``_cost_warning_emitted`` etc.).  Bundled into one
``BudgetMonitor`` that the orchestrator constructs once and calls at
the relevant hook points.  Replaces ~180 lines of inline engine
methods whose only connection to the CfA loop was timing.
"""
from __future__ import annotations

from typing import Any, Callable

from teaparty.messaging.bus import Event, EventBus, EventType, InputRequest
from teaparty.util.context_budget import ContextBudget, build_compact_prompt
from teaparty.util.cost_tracker import (
    CostTracker, ProjectCostLedger, WARNING_THRESHOLD, LIMIT_THRESHOLD,
)


class BudgetMonitor:
    """Owns cost + context budget checks and their once-per-job flags."""

    def __init__(
        self,
        *,
        event_bus: EventBus,
        session_id: str,
        input_provider: Callable[[InputRequest], Any],
        cost_tracker: CostTracker | None,
        project_cost_ledger: ProjectCostLedger | None,
    ) -> None:
        self._event_bus = event_bus
        self._session_id = session_id
        self._input_provider = input_provider
        self._cost_tracker = cost_tracker
        self._project_cost_ledger = project_cost_ledger
        self._cost_warning_emitted = False
        self._project_cost_warning_emitted = False

    @property
    def cost_tracker(self) -> CostTracker | None:
        return self._cost_tracker

    @property
    def project_cost_ledger(self) -> ProjectCostLedger | None:
        return self._project_cost_ledger

    # ── Context budget ────────────────────────────────────────────────

    async def check_context(
        self,
        *,
        budget: Any,
        phase_name: str,
        task: str,
    ) -> str:
        """Publish warnings / emit compact intervention.

        Returns a compact-prompt string when the context window crosses
        the compact threshold and an intervention should be injected
        at the next turn; empty string otherwise.  The caller stores
        the returned prompt in its pending-intervention slot.
        """
        if not isinstance(budget, ContextBudget):
            return ''

        if budget.should_warn and not budget.should_compact:
            await self._event_bus.publish(Event(
                type=EventType.CONTEXT_WARNING,
                data={
                    'utilization': budget.utilization,
                    'used_tokens': budget.used_tokens,
                    'context_window': budget.context_window,
                    'phase': phase_name,
                },
                session_id=self._session_id,
            ))
            budget.clear_warning()

        if budget.should_compact:
            compact_prompt = build_compact_prompt(
                cfa_state='',  # not used by build_compact_prompt today
                task=task,
                scratch_path='.context/scratch.md',
            )
            await self._event_bus.publish(Event(
                type=EventType.CONTEXT_WARNING,
                data={
                    'utilization': budget.utilization,
                    'used_tokens': budget.used_tokens,
                    'context_window': budget.context_window,
                    'phase': phase_name,
                    'action': 'compact',
                    'compact_prompt': compact_prompt,
                },
                session_id=self._session_id,
            ))
            budget.clear_compact()
            return compact_prompt
        return ''

    # ── Cost budget (job + project) ───────────────────────────────────

    async def record_turn_cost(self, actor_data: dict, session_id: str) -> None:
        """Feed one turn's cost into the tracker and ledger."""
        if not self._cost_tracker:
            return
        turn_cost = actor_data.get('cost_usd', 0.0)
        if not turn_cost:
            return
        cost_event: dict[str, Any] = {
            'type': 'result',
            'total_cost_usd': turn_cost,
        }
        per_model = actor_data.get('cost_per_model')
        if per_model:
            cost_event['cost_usd'] = per_model
        self._cost_tracker.record(cost_event)
        if self._project_cost_ledger:
            self._project_cost_ledger.record(session_id, turn_cost)

    async def check_costs(self) -> str:
        """Check job + project cost budgets.

        Returns a wrap-up prompt to inject as an intervention when the
        human declines to continue past 100 % (job or project); empty
        string otherwise.
        """
        intervention = await self._check_job_budget()
        if not intervention:
            intervention = await self._check_project_budget()
        return intervention

    async def _check_job_budget(self) -> str:
        tracker = self._cost_tracker
        if not tracker:
            return ''

        if tracker.warning_triggered and not self._cost_warning_emitted:
            self._cost_warning_emitted = True
            await self._event_bus.publish(Event(
                type=EventType.COST_WARNING,
                data={
                    'total_cost_usd': tracker.total_cost_usd,
                    'job_limit_usd': tracker.job_limit,
                    'utilization': tracker.utilization,
                },
                session_id=self._session_id,
            ))

        if not tracker.limit_reached:
            return ''

        cost = tracker.total_cost_usd
        limit = tracker.job_limit
        await self._event_bus.publish(Event(
            type=EventType.COST_LIMIT,
            data={
                'total_cost_usd': cost,
                'job_limit_usd': limit,
                'utilization': tracker.utilization,
            },
            session_id=self._session_id,
        ))
        response = await self._input_provider(InputRequest(
            type='cost_limit',
            state='COST_LIMIT',
            artifact='',
            bridge_text=(
                f'This job has used ${cost:.2f} of its ${limit:.2f} budget. '
                f'Continue?'
            ),
        ))
        if (response or '').strip().lower() in ('no', 'n', 'stop', 'withdraw'):
            return (
                '[COST BUDGET EXCEEDED] The human declined to continue. '
                'Wrap up current work and commit partial progress.'
            )
        return ''

    async def _check_project_budget(self) -> str:
        tracker = self._cost_tracker
        ledger = self._project_cost_ledger
        if not tracker or not ledger or not tracker.project_limit:
            return ''

        project_total = ledger.total_cost()
        project_limit = tracker.project_limit
        utilization = project_total / project_limit if project_limit else 0.0

        if (utilization >= WARNING_THRESHOLD
                and not self._project_cost_warning_emitted):
            self._project_cost_warning_emitted = True
            await self._event_bus.publish(Event(
                type=EventType.COST_WARNING,
                data={
                    'total_cost_usd': project_total,
                    'project_limit_usd': project_limit,
                    'utilization': utilization,
                    'scope': 'project',
                },
                session_id=self._session_id,
            ))

        if utilization < LIMIT_THRESHOLD:
            return ''

        await self._event_bus.publish(Event(
            type=EventType.COST_LIMIT,
            data={
                'total_cost_usd': project_total,
                'project_limit_usd': project_limit,
                'utilization': utilization,
                'scope': 'project',
            },
            session_id=self._session_id,
        ))
        response = await self._input_provider(InputRequest(
            type='cost_limit',
            state='COST_LIMIT',
            artifact='',
            bridge_text=(
                f'Project has used ${project_total:.2f} of its '
                f'${project_limit:.2f} budget across all jobs. Continue?'
            ),
        ))
        if (response or '').strip().lower() in ('no', 'n', 'stop', 'withdraw'):
            return (
                '[PROJECT BUDGET EXCEEDED] The human declined to continue. '
                'Wrap up current work and commit partial progress.'
            )
        return ''

    # ── Cost sidecar ──────────────────────────────────────────────────

    def write_sidecar(self, infra_dir: str) -> None:
        """Write a running cost total to ``{infra_dir}/.cost``."""
        if not self._cost_tracker or not infra_dir:
            return
        import os
        try:
            with open(os.path.join(infra_dir, '.cost'), 'w') as f:
                f.write(f'{self._cost_tracker.total_cost_usd:.6f}\n')
        except OSError:
            pass
