"""Orchestrator engine — the CfA state loop.

Drives a CfA state machine from its current state to a terminal state
by invoking the appropriate actor at each step.  Handles cross-phase
backtracks, infrastructure failures, and review dialog loops.

Replaces the control flow of run.sh (backtrack loop), intent.sh (intent
review cycle), and plan-execute.sh (planning/execution review cycles).
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any

import logging

from projects.POC.scripts.cfa_state import (
    CfaState,
    InvalidTransition,
    TRANSITIONS,
    is_globally_terminal,
    is_phase_terminal,
    phase_for_state,
    save_state,
    transition,
    set_state_direct,
)

_log = logging.getLogger('orchestrator')
from projects.POC.scripts.detect_stage import detect_stage_from_content
from projects.POC.scripts.retire_stage import retire_stage_entries
from projects.POC.orchestrator.skill_lookup import lookup_skill
from projects.POC.orchestrator.actors import (
    ActorContext,
    ActorResult,
    AgentRunner,
    ApprovalGate,
    InputProvider,
)
from projects.POC.orchestrator.events import Event, EventBus, EventType, InputRequest
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


PLAN_ESCALATION_STATES = frozenset({'INTENT_ESCALATE', 'PLANNING_ESCALATE'})
WORK_ESCALATION_STATES = frozenset({'TASK_REVIEW_ESCALATE'})


@dataclass
class OrchestratorResult:
    """Final outcome of the full session orchestration."""
    terminal_state: str             # COMPLETED_WORK or WITHDRAWN
    backtrack_count: int = 0
    escalation_type: str = ''      # 'plan', 'work', or '' (no escalation)


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
        intent_only: bool = False,
        plan_only: bool = False,
        execute_only: bool = False,
        flat: bool = False,
        team_override: str = '',
        phase_session_ids: dict[str, str] | None = None,
        last_actor_data: dict[str, Any] | None = None,
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
        self.intent_only = intent_only
        self.plan_only = plan_only
        self.execute_only = execute_only
        self.flat = flat
        self.team_override = team_override

        # Agent runners
        self._agent_runner = AgentRunner(stall_timeout=phase_config.stall_timeout)
        self._approval_gate = ApprovalGate(
            proxy_model_path=proxy_model_path,
            input_provider=input_provider,
            poc_root=poc_root,
        )

        # Track resume session IDs per phase (for --resume on corrections).
        # Pre-populated on session resume by parsing stream JSONL files.
        self._phase_session_ids: dict[str, str] = phase_session_ids or {}

        # Track data between actors (e.g., artifact path from agent → approval gate).
        # Pre-populated on session resume from PhaseSpec + worktree.
        self._last_actor_data: dict[str, Any] = last_actor_data or {}

    async def run(self) -> OrchestratorResult:
        """Drive the CfA state machine to a terminal state."""
        while True:
            # Phase 1: Intent alignment
            if not self.skip_intent:
                result = await self._run_phase('intent')
                if result.terminal:
                    return self._make_result(result.terminal_state)
                if result.infrastructure_failure:
                    decision = await self._failure_dialog(result.failure_reason)
                    if decision == 'withdraw':
                        self.cfa = set_state_direct(self.cfa, 'WITHDRAWN')
                        save_state(self.cfa, os.path.join(self.infra_dir, '.cfa-state.json'))
                        return self._make_result('WITHDRAWN')
                    continue  # retry intent

            # Stop here if intent-only
            if self.intent_only:
                return self._make_result('COMPLETED_WORK')

            # Phase 2: Planning (skip if execute-only)
            if not self.execute_only:
                # Bridge intent → planning (INTENT has one edge: plan → DRAFT)
                await self._auto_bridge()

                # System 1 fast path: if a learned skill covers this task,
                # write it as PLAN.md and advance to PLAN_ASSERT.  The
                # planning agent never runs — the skill IS the plan.
                # _run_phase('planning') picks up at PLAN_ASSERT (human review).
                # If the human corrects, it falls back to System 2 (planning agent).
                await self._try_skill_lookup()

                result = await self._run_phase('planning')
                if result.terminal:
                    return self._make_result(result.terminal_state)
                if result.backtrack_to == 'intent':
                    self.skip_intent = False
                    continue
                if result.infrastructure_failure:
                    decision = await self._failure_dialog(result.failure_reason)
                    if decision == 'backtrack':
                        self.skip_intent = False
                        continue
                    if decision == 'withdraw':
                        self.cfa = set_state_direct(self.cfa, 'WITHDRAWN')
                        save_state(self.cfa, os.path.join(self.infra_dir, '.cfa-state.json'))
                        return self._make_result('WITHDRAWN')
                    continue  # retry planning

                # Stop here if plan-only
                if self.plan_only:
                    return self._make_result('COMPLETED_WORK')

                # Bridge planning → execution (PLAN has one edge: delegate → TASK)
                await self._auto_bridge()
            # else: CfA is already at TASK (set_state_direct in Session.run)

            # Phase 3: Execution
            result = await self._run_phase('execution')
            if result.terminal:
                return self._make_result(result.terminal_state)
            if result.backtrack_to == 'intent':
                self.skip_intent = False
                continue
            if result.backtrack_to == 'planning':
                self.skip_intent = True
                continue
            if result.infrastructure_failure:
                decision = await self._failure_dialog(result.failure_reason)
                if decision == 'backtrack':
                    self.skip_intent = False
                    continue
                if decision == 'withdraw':
                    self.cfa = set_state_direct(self.cfa, 'WITHDRAWN')
                    save_state(self.cfa, os.path.join(self.infra_dir, '.cfa-state.json'))
                    return self._make_result('WITHDRAWN')
                continue  # retry execution

            # Should not reach here — but treat as completion
            return self._make_result(self.cfa.state)

    async def _auto_bridge(self) -> None:
        """Apply deterministic transition at a phase-terminal state to enter the next phase.

        Phase-terminal states with exactly one outgoing edge (INTENT → DRAFT,
        PLAN → TASK) are structural bridges, not agent decisions.  Apply them
        automatically so _run_phase for the next phase starts inside its own
        phase's state space.
        """
        edges = TRANSITIONS.get(self.cfa.state, [])
        if len(edges) == 1:
            action = edges[0][0]
            await self.event_bus.publish(Event(
                type=EventType.LOG,
                data={
                    'category': 'auto_bridge',
                    'state': self.cfa.state,
                    'action': action,
                },
                session_id=self.session_id,
            ))
            await self._transition(action, ActorResult(action=action))

    async def _try_skill_lookup(self) -> bool:
        """System 1 fast path: check the skill library for a matching skill.

        If a match is found:
          1. Writes the skill template as PLAN.md (the skill IS the plan)
          2. Advances CfA state to PLAN_ASSERT for human review
          3. Returns True — the caller skips cold-start planning

        If no match or any error: returns False (fall through to System 2).

        The human still reviews the skill-as-plan at PLAN_ASSERT.  If they
        correct it, the correction goes to PLANNING_RESPONSE → DRAFT and the
        planning agent runs (System 2 fallback).
        """
        skills_dir = os.path.join(self.project_workdir, 'skills')
        if not os.path.isdir(skills_dir):
            return False

        # Read the approved intent
        intent = ''
        intent_path = os.path.join(self.session_worktree, 'INTENT.md')
        try:
            with open(intent_path) as f:
                intent = f.read()
        except OSError:
            pass

        try:
            match = lookup_skill(
                task=self.task,
                intent=intent,
                skills_dir=skills_dir,
            )
        except Exception:
            _log.debug('Skill lookup failed, falling through to cold start')
            return False

        if not match:
            return False

        # Write the skill template as PLAN.md — the skill IS the plan
        plan_path = os.path.join(self.session_worktree, 'PLAN.md')
        with open(plan_path, 'w') as f:
            f.write(match.template)

        # Advance CfA: DRAFT → assert → PLAN_ASSERT
        # This bypasses the planning agent entirely — the skill is the plan,
        # presented directly to the human for approval.
        await self._transition('assert', ActorResult(
            action='assert',
            data={'artifact_path': plan_path, 'skill_name': match.name},
        ))

        await self.event_bus.publish(Event(
            type=EventType.LOG,
            data={
                'category': 'skill_lookup',
                'result': 'matched',
                'skill_name': match.name,
                'skill_score': match.score,
                'skill_path': match.path,
            },
            session_id=self.session_id,
        ))

        return True

    def _make_result(self, terminal_state: str) -> OrchestratorResult:
        """Build OrchestratorResult with escalation_type derived from CfA state."""
        escalation_type = ''
        if self.cfa.state in PLAN_ESCALATION_STATES:
            escalation_type = 'plan'
        elif self.cfa.state in WORK_ESCALATION_STATES:
            escalation_type = 'work'
        return OrchestratorResult(
            terminal_state=terminal_state,
            backtrack_count=self.cfa.backtrack_count,
            escalation_type=escalation_type,
        )

    async def _run_phase(self, phase_name: str) -> PhaseResult:
        """Run a single CfA phase to completion or backtrack."""
        spec = self._phase_spec(phase_name)
        phase_start_time = time.monotonic()

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

            # Phase-terminal: this phase reached its terminal state
            # (e.g., INTENT for intent phase, PLAN for planning phase).
            if is_phase_terminal(self.cfa.state) and phase_for_state(self.cfa.state) == phase_name:
                await self.event_bus.publish(Event(
                    type=EventType.PHASE_COMPLETED,
                    data={'phase': phase_name, 'state': self.cfa.state},
                    session_id=self.session_id,
                ))
                return PhaseResult()

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
            actor_result = await self._invoke_actor(spec, phase_name, phase_start_time)

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

    async def _invoke_actor(self, spec: 'PhaseSpec', phase_name: str,
                             phase_start_time: float = 0.0) -> ActorResult:
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
            phase_start_time=phase_start_time,
        )

        if state in self.config.human_actor_states:
            # Human or approval gate — run the approval gate
            ctx.data = self._last_actor_data
            return await self._approval_gate.run(ctx)

        # Inject stderr from previous turn so the agent can see CLI errors
        prev_stderr = self._last_actor_data.get('stderr_lines', [])
        if prev_stderr:
            stderr_block = '\n'.join(prev_stderr)
            ctx.backtrack_context = (
                (ctx.backtrack_context + '\n\n' if ctx.backtrack_context else '')
                + f'[stderr from previous turn]\n{stderr_block}'
            )

        # Agent actor — run agent
        return await self._agent_runner.run(ctx)

    async def _transition(self, action: str, actor_result: ActorResult) -> None:
        """Apply a CfA transition and persist state."""
        old_state = self.cfa.state

        try:
            self.cfa = transition(self.cfa, action)
        except InvalidTransition as exc:
            _log.error(
                'Invalid CfA transition: action=%r from state=%r: %s',
                action, old_state, exc,
            )
            raise

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

        # Post-intent-approval: detect project stage and retire old-stage memory
        if old_state == 'INTENT_ASSERT' and action == 'approve':
            self._detect_and_retire_stage()

    def _detect_and_retire_stage(self) -> None:
        """Detect the project stage from INTENT.md and retire old-stage memory."""
        from pathlib import Path

        intent_path = os.path.join(self.session_worktree, 'INTENT.md')
        if not os.path.exists(intent_path):
            intent_path = os.path.join(self.infra_dir, 'INTENT.md')
        if not os.path.exists(intent_path):
            return

        try:
            content = Path(intent_path).read_text(errors='replace')
        except OSError:
            return

        new_stage = detect_stage_from_content(content)

        # Track stage in infra dir
        stage_file = os.path.join(self.infra_dir, '.current-stage')
        old_stage = ''
        if os.path.exists(stage_file):
            try:
                old_stage = Path(stage_file).read_text().strip()
            except OSError:
                pass
        Path(stage_file).write_text(new_stage + '\n')

        _log.info('Stage detection: %s → %s', old_stage or '(none)', new_stage)

        # Retire old-stage task-domain memory entries on transition
        if old_stage and old_stage != new_stage and old_stage != 'unknown':
            institutional = os.path.join(self.project_workdir, 'institutional.md')
            if os.path.exists(institutional):
                try:
                    from projects.POC.scripts.memory_entry import (
                        parse_memory_file, serialize_memory_file,
                    )
                    text = Path(institutional).read_text(errors='replace')
                    entries = parse_memory_file(text)
                    if entries:
                        # Use module-level retire_stage_entries for testability
                        updated, count = retire_stage_entries(entries, old_stage)
                        if count > 0:
                            Path(institutional).write_text(
                                serialize_memory_file(updated),
                            )
                            _log.info(
                                'Retired %d task-domain "%s" entries from %s',
                                count, old_stage, institutional,
                            )
                except Exception as exc:
                    _log.warning('Stage retirement failed: %s', exc)

    def _phase_spec(self, phase_name: str) -> 'PhaseSpec':
        """Get the phase spec, accounting for team and flat overrides."""
        if self.team_override:
            team = self.config.team(self.team_override)
            base = self.config.phase(phase_name)
            # Override agent file and lead from team config.
            # Teams can specify their own planning permission mode
            # (e.g., subteams use 'plan' for tactical planning).
            perm = base.permission_mode
            if phase_name == 'planning' and team.planning_permission_mode:
                perm = team.planning_permission_mode
            from projects.POC.orchestrator.phase_config import PhaseSpec
            return PhaseSpec(
                name=base.name,
                agent_file=team.agent_file,
                lead=team.lead,
                permission_mode=perm,
                stream_file=base.stream_file,
                artifact=base.artifact,
                approval_state=base.approval_state,
                escalation_state=base.escalation_state,
                escalation_file=base.escalation_file,
                settings_overlay=base.settings_overlay,
            )

        base = self.config.phase(phase_name)

        # --flat: swap hierarchical team (uber-team with liaisons) for a flat
        # team where the lead recruits agents dynamically via the Agent tool.
        # Only affects phases that use uber-team.json (planning, execution).
        if self.flat and 'uber-team' in base.agent_file:
            from projects.POC.orchestrator.phase_config import PhaseSpec
            return PhaseSpec(
                name=base.name,
                agent_file='agents/flat-team.json',
                lead='project-lead',
                permission_mode=base.permission_mode,
                stream_file=base.stream_file,
                artifact=base.artifact,
                approval_state=base.approval_state,
                escalation_state=base.escalation_state,
                escalation_file=base.escalation_file,
                settings_overlay=base.settings_overlay,
            )

        return base

    def _task_for_phase(self, phase_name: str) -> str:
        """Get the task description for a phase.

        Intent phase: uses the original task description.
        Planning phase: reads INTENT.md (the intent phase's output).
        Execution phase: reads PLAN.md as the workflow to follow,
            with INTENT.md appended as reference context.
        """
        if phase_name == 'execution':
            plan_path = os.path.join(self.session_worktree, 'PLAN.md')
            intent_path = os.path.join(self.session_worktree, 'INTENT.md')
            parts = []
            try:
                with open(plan_path) as f:
                    parts.append(f.read())
            except OSError:
                pass
            try:
                with open(intent_path) as f:
                    parts.append(
                        '---\nReference: INTENT.md (for success criteria and constraints)\n---\n'
                        + f.read()
                    )
            except OSError:
                pass
            if parts:
                return '\n\n'.join(parts)
        elif phase_name == 'planning':
            intent_path = os.path.join(self.session_worktree, 'INTENT.md')
            try:
                with open(intent_path) as f:
                    return f.read()
            except OSError:
                pass
        # Intent phase, or artifacts not yet written
        return self.task or self.project_slug

    async def _failure_dialog(self, reason: str) -> str:
        """Gap 30: Ask human what to do after infrastructure failure.

        Returns 'retry' | 'backtrack' | 'withdraw'.
        """
        bridge_text = (
            f'Infrastructure failure: {reason}\n\n'
            'Options:\n'
            '  retry — try the execution phase again\n'
            '  backtrack — return to planning with feedback\n'
            '  withdraw — mark this session as withdrawn\n'
        )
        await self.event_bus.publish(Event(
            type=EventType.INPUT_REQUESTED,
            data={'state': 'INFRASTRUCTURE_FAILURE', 'bridge_text': bridge_text},
            session_id=self.session_id,
        ))
        response = await self.input_provider(InputRequest(
            type='failure_decision',
            state='INFRASTRUCTURE_FAILURE',
            artifact='',
            bridge_text=bridge_text,
        ))
        r = response.strip().lower()
        if 'backtrack' in r:
            return 'backtrack'
        if 'withdraw' in r:
            return 'withdraw'
        return 'retry'

    def _build_env_vars(self) -> dict[str, str]:
        return {
            'POC_PROJECT': self.project_slug,
            'POC_PROJECT_DIR': self.project_workdir,
            'POC_SESSION_DIR': self.infra_dir,
            'POC_SESSION_WORKTREE': self.session_worktree,
            'POC_CFA_STATE': os.path.join(self.infra_dir, '.cfa-state.json'),
            # Gap 3: SCRIPT_DIR and PROJECTS_DIR needed by subprocesses (e.g. dispatch_cli.py)
            'SCRIPT_DIR': self.poc_root,
            'PROJECTS_DIR': os.path.dirname(self.project_workdir),
        }

    def _build_add_dirs(self) -> list[str]:
        dirs = []
        if self.session_worktree:
            dirs.append(self.session_worktree)
        if self.project_workdir and self.project_workdir != self.session_worktree:
            dirs.append(self.project_workdir)
        return dirs
