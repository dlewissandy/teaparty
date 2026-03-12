"""Orchestrator engine — the CfA state loop.

Drives a CfA state machine from its current state to a terminal state
by invoking the appropriate actor at each step.  Handles cross-phase
backtracks, infrastructure failures, and review dialog loops.

Replaces the control flow of run.sh (backtrack loop), intent.sh (intent
review cycle), and plan-execute.sh (planning/execution review cycles).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from projects.POC.scripts.cfa_state import (
    CfaState,
    is_globally_terminal,
    phase_for_state,
    save_state,
    transition,
    set_state_direct,
)
from projects.POC.orchestrator.actors import (
    ActorContext,
    ActorResult,
    AgentRunner,
    ApprovalGate,
    InputProvider,
)
from projects.POC.orchestrator.events import Event, EventBus, EventType
from projects.POC.orchestrator.phase_config import PhaseConfig


@dataclass
class PhaseResult:
    """Outcome of running a single CfA phase."""
    terminal: bool = False          # Reached a globally terminal state
    terminal_state: str = ''        # COMPLETED_WORK or WITHDRAWN
    backtrack_to: str = ''          # 'intent' or 'planning' (empty = no backtrack)
    backtrack_feedback: str = ''    # Human feedback for backtrack
    infrastructure_failure: bool = False
    failure_reason: str = ''


@dataclass
class OrchestratorResult:
    """Final outcome of the full session orchestration."""
    terminal_state: str             # COMPLETED_WORK or WITHDRAWN
    backtrack_count: int = 0


class Orchestrator:
    """Drives a CfA state machine to completion.

    The main loop:
      1. Check if intent phase is needed
      2. Run planning phase
      3. Run execution phase
      4. Handle backtracks by restarting the appropriate phase
    """

    def __init__(
        self,
        cfa_state: CfaState,
        phase_config: PhaseConfig,
        event_bus: EventBus,
        input_provider: InputProvider,
        infra_dir: str,
        project_workdir: str,
        session_worktree: str,
        proxy_model_path: str,
        project_slug: str,
        poc_root: str,
        task: str = '',
        session_id: str = '',
        skip_intent: bool = False,
        team_override: str = '',
    ):
        self.cfa = cfa_state
        self.config = phase_config
        self.event_bus = event_bus
        self.input_provider = input_provider
        self.infra_dir = infra_dir
        self.project_workdir = project_workdir
        self.session_worktree = session_worktree
        self.proxy_model_path = proxy_model_path
        self.project_slug = project_slug
        self.poc_root = poc_root
        self.task = task
        self.session_id = session_id
        self.skip_intent = skip_intent
        self.team_override = team_override

        # Agent runners
        self._agent_runner = AgentRunner(stall_timeout=phase_config.stall_timeout)
        self._approval_gate = ApprovalGate(
            proxy_model_path=proxy_model_path,
            input_provider=input_provider,
            poc_root=poc_root,
        )

        # Track resume session IDs per phase (for --resume on corrections)
        self._phase_session_ids: dict[str, str] = {}

    async def run(self) -> OrchestratorResult:
        """Drive the CfA state machine to a terminal state."""
        while True:
            # Phase 1: Intent alignment
            if not self.skip_intent:
                result = await self._run_phase('intent')
                if result.terminal:
                    return OrchestratorResult(
                        terminal_state=result.terminal_state,
                        backtrack_count=self.cfa.backtrack_count,
                    )

            # Phase 2: Planning
            result = await self._run_phase('planning')
            if result.terminal:
                return OrchestratorResult(
                    terminal_state=result.terminal_state,
                    backtrack_count=self.cfa.backtrack_count,
                )
            if result.backtrack_to == 'intent':
                self.skip_intent = False
                continue

            # Phase 3: Execution
            result = await self._run_phase('execution')
            if result.terminal:
                return OrchestratorResult(
                    terminal_state=result.terminal_state,
                    backtrack_count=self.cfa.backtrack_count,
                )
            if result.backtrack_to == 'intent':
                self.skip_intent = False
                continue
            if result.backtrack_to == 'planning':
                self.skip_intent = True
                continue
            if result.infrastructure_failure:
                # Retry execution
                continue

            # Should not reach here — but treat as completion
            return OrchestratorResult(
                terminal_state=self.cfa.state,
                backtrack_count=self.cfa.backtrack_count,
            )

    async def _run_phase(self, phase_name: str) -> PhaseResult:
        """Run a single CfA phase to completion or backtrack."""
        spec = self._phase_spec(phase_name)

        await self.event_bus.publish(Event(
            type=EventType.PHASE_STARTED,
            data={'phase': phase_name, 'stream_file': spec.stream_file},
            session_id=self.session_id,
        ))

        # Initialize stream file
        stream_path = os.path.join(self.infra_dir, spec.stream_file)
        if not os.path.exists(stream_path):
            open(stream_path, 'w').close()

        # CfA micro-loop: advance state within this phase until phase is
        # done (terminal, backtrack, or phase-exit state reached).
        while True:
            if is_globally_terminal(self.cfa.state):
                await self.event_bus.publish(Event(
                    type=EventType.PHASE_COMPLETED,
                    data={'phase': phase_name, 'state': self.cfa.state},
                    session_id=self.session_id,
                ))
                return PhaseResult(terminal=True, terminal_state=self.cfa.state)

            # Check for phase exit (e.g., INTENT → planning, PLAN → execution)
            current_phase = phase_for_state(self.cfa.state)
            if current_phase != phase_name and self.cfa.state not in (
                'INTENT_RESPONSE', 'PLANNING_RESPONSE', 'TASK_RESPONSE',
            ):
                # We've transitioned out of this phase
                await self.event_bus.publish(Event(
                    type=EventType.PHASE_COMPLETED,
                    data={'phase': phase_name, 'state': self.cfa.state},
                    session_id=self.session_id,
                ))
                # Check for backtracks
                if current_phase == 'intent' and phase_name != 'intent':
                    return PhaseResult(backtrack_to='intent')
                if current_phase == 'planning' and phase_name == 'execution':
                    return PhaseResult(backtrack_to='planning')
                return PhaseResult()

            # Determine which actor should run
            actor_result = await self._invoke_actor(spec, phase_name)

            # Handle the actor result
            if actor_result.action == 'failed':
                reason = actor_result.data.get('reason', 'unknown')
                if reason in ('stall_timeout', 'nonzero_exit'):
                    return PhaseResult(
                        infrastructure_failure=True,
                        failure_reason=reason,
                    )

            # Apply the CfA transition
            await self._transition(actor_result.action, actor_result)

    async def _invoke_actor(self, spec: 'PhaseSpec', phase_name: str) -> ActorResult:
        """Dispatch to the correct actor based on current state."""
        state = self.cfa.state
        actor = self.cfa.actor

        ctx = ActorContext(
            state=state,
            phase=phase_name,
            task=self._task_for_phase(phase_name),
            infra_dir=self.infra_dir,
            project_workdir=self.project_workdir,
            session_worktree=self.session_worktree,
            stream_file=spec.stream_file,
            phase_spec=spec,
            poc_root=self.poc_root,
            event_bus=self.event_bus,
            session_id=self.session_id,
            resume_session=self._phase_session_ids.get(phase_name),
            env_vars=self._build_env_vars(),
            add_dirs=self._build_add_dirs(),
        )

        if state in self.config.human_actor_states:
            # Human or approval gate — run the approval gate
            ctx.data = self._last_actor_data
            return await self._approval_gate.run(ctx)

        # Agent actor — run agent
        return await self._agent_runner.run(ctx)

    async def _transition(self, action: str, actor_result: ActorResult) -> None:
        """Apply a CfA transition and persist state."""
        old_state = self.cfa.state

        try:
            self.cfa = transition(self.cfa, action)
        except Exception:
            # Fallback: direct set if transition validation fails
            # (some orchestration paths bypass strict transitions)
            pass

        # Track data from the actor result for the next actor
        self._last_actor_data = actor_result.data

        # Track claude session ID for --resume
        claude_sid = actor_result.data.get('claude_session_id', '')
        if claude_sid:
            phase = phase_for_state(self.cfa.state)
            self._phase_session_ids[phase] = claude_sid

        # Persist and emit
        state_path = os.path.join(self.infra_dir, '.cfa-state.json')
        save_state(self.cfa, state_path)

        await self.event_bus.publish(Event(
            type=EventType.STATE_CHANGED,
            data={
                'phase': self.cfa.phase,
                'state': self.cfa.state,
                'actor': self.cfa.actor,
                'previous_state': old_state,
                'action': action,
                'history': self.cfa.history,
                'backtrack_count': self.cfa.backtrack_count,
            },
            session_id=self.session_id,
        ))

    def _phase_spec(self, phase_name: str) -> 'PhaseSpec':
        """Get the phase spec, accounting for team overrides."""
        if self.team_override:
            team = self.config.team(self.team_override)
            base = self.config.phase(phase_name)
            # Override agent file and lead from team config
            from projects.POC.orchestrator.phase_config import PhaseSpec
            return PhaseSpec(
                name=base.name,
                agent_file=team.agent_file,
                lead=team.lead,
                permission_mode=base.permission_mode,
                stream_file=base.stream_file,
                artifact=base.artifact,
                approval_state=base.approval_state,
                escalation_state=base.escalation_state,
                escalation_file=base.escalation_file,
                settings_overlay=base.settings_overlay,
            )
        return self.config.phase(phase_name)

    def _task_for_phase(self, phase_name: str) -> str:
        """Get the task description for a phase.

        Intent phase: uses the original task description.
        Planning/execution: reads INTENT.md (the intent phase's output).
        """
        if phase_name != 'intent':
            intent_path = os.path.join(self.session_worktree, 'INTENT.md')
            if os.path.exists(intent_path):
                try:
                    with open(intent_path) as f:
                        return f.read()
                except OSError:
                    pass
        # Intent phase, or INTENT.md not yet written
        return self.task or self.project_slug

    def _build_env_vars(self) -> dict[str, str]:
        return {
            'POC_PROJECT': self.project_slug,
            'POC_PROJECT_DIR': self.project_workdir,
            'POC_SESSION_DIR': self.infra_dir,
            'POC_SESSION_WORKTREE': self.session_worktree,
            'POC_CFA_STATE': os.path.join(self.infra_dir, '.cfa-state.json'),
        }

    def _build_add_dirs(self) -> list[str]:
        dirs = []
        if self.session_worktree:
            dirs.append(self.session_worktree)
        return dirs

    # Track data between actors (e.g., artifact path from agent → approval gate)
    _last_actor_data: dict[str, Any] = {}
