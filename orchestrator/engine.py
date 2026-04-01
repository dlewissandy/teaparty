"""Orchestrator engine — the CfA state loop.

Drives a CfA state machine from its current state to a terminal state
by invoking the appropriate actor at each step.  Handles cross-phase
backtracks, infrastructure failures, and review dialog loops.
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from typing import Any

import logging

from scripts.cfa_state import (
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
from scripts.detect_stage import detect_stage_from_content
from scripts.retire_stage import retire_stage_entries
from orchestrator.skill_lookup import lookup_skill
from orchestrator.actors import (
    ActorContext,
    ActorResult,
    AgentRunner,
    ApprovalGate,
    InputProvider,
)
from orchestrator.gate_queue import GateQueue
from orchestrator.human_presence import HumanPresence
from orchestrator.escalation_listener import EscalationListener
from orchestrator.intervention_listener import InterventionListener
from orchestrator.worktree import commit_artifact
from orchestrator.events import Event, EventBus, EventType, InputRequest
from orchestrator.intervention import InterventionQueue, build_intervention_prompt
from orchestrator.interrupt_propagation import (
    cascade_withdraw_children,
    is_backtrack,
)
from orchestrator.context_budget import ContextBudget, build_compact_prompt
from orchestrator.phase_config import PhaseConfig
from orchestrator.cost_tracker import (
    CostTracker, ProjectCostLedger, WARNING_THRESHOLD, LIMIT_THRESHOLD,
)
from orchestrator.role_enforcer import RoleEnforcer
from orchestrator.scratch import ScratchModel, ScratchWriter, extract_text
from orchestrator.learnings import (
    write_intervention_chunk,
    write_intervention_outcome,
)


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
WORK_ESCALATION_STATES = frozenset({'TASK_ESCALATE'})


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
        suppress_backtracks: bool = False,
        proxy_enabled: bool = True,
        never_escalate: bool = False,
        team_override: str = '',
        phase_session_ids: dict[str, str] | None = None,
        last_actor_data: dict[str, Any] | None = None,
        parent_heartbeat: str = '',
        project_dir: str = '',
        intervention_queue: InterventionQueue | None = None,
        role_enforcer: RoleEnforcer | None = None,
        human_presence: HumanPresence | None = None,
        gate_queue: GateQueue | None = None,
        cost_tracker: CostTracker | None = None,
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
        self.suppress_backtracks = suppress_backtracks
        self.proxy_enabled = proxy_enabled
        self.never_escalate = never_escalate
        self.team_override = team_override
        self._parent_heartbeat = parent_heartbeat
        self.project_dir = project_dir
        self._intervention_queue = intervention_queue
        self._role_enforcer = role_enforcer
        if intervention_queue and role_enforcer:
            intervention_queue.role_enforcer = role_enforcer
        self._pending_intervention: str = ''  # Prompt to inject at next agent turn
        self._intervention_active: bool = False  # True after intervention delivery (Issue #247)
        self.human_presence = human_presence
        self._cost_tracker = cost_tracker
        self._cost_warning_emitted = False  # Only emit once per job
        self._project_cost_warning_emitted = False
        self._project_cost_ledger: ProjectCostLedger | None = (
            ProjectCostLedger(project_workdir) if cost_tracker else None
        )

        # Scratch file lifecycle (Issue #261): working memory for context budget.
        self._scratch_model = ScratchModel(job=task, phase='')
        self._scratch_writer = ScratchWriter(session_worktree)

        # Agent runners
        self._agent_runner = AgentRunner(stall_timeout=phase_config.stall_timeout)
        self._approval_gate = ApprovalGate(
            proxy_model_path=proxy_model_path,
            input_provider=input_provider,
            poc_root=poc_root,
            proxy_enabled=proxy_enabled,
            never_escalate=never_escalate,
            human_presence=human_presence,
            gate_queue=gate_queue,
        )

        # MCP escalation listener — bridges AskQuestion calls to proxy/human
        self._escalation_listener: EscalationListener | None = None
        # MCP dispatch listener — bridges AskTeam calls to dispatch()
        # Type annotation uses string to avoid circular import at module level
        self._dispatch_listener: Any | None = None
        # MCP intervention listener — bridges office manager tools to
        # session/dispatch operations (Issue #249)
        self._intervention_listener: InterventionListener | None = None
        self._intervention_resolver: dict[str, str] = {}
        # Bus event listener — bridges Send/Reply MCP calls to bus-mediated
        # agent dispatch (Issue #351).  Started alongside other MCP listeners.
        self._bus_event_listener: Any | None = None  # BusEventListener
        self._mcp_config: dict | None = None

        # Track resume session IDs per phase (for --resume on corrections).
        # Pre-populated on session resume by parsing stream JSONL files.
        self._phase_session_ids: dict[str, str] = phase_session_ids or {}

        # Track data between actors (e.g., artifact path from agent → approval gate).
        # Pre-populated on session resume from PhaseSpec + worktree.
        self._last_actor_data: dict[str, Any] = last_actor_data or {}

        # Track which skill was used for the current plan (Issue #142).
        # Set by _try_skill_lookup() on match; cleared when System 2
        # fallback produces a new plan.  Used by _mark_false_positives()
        # to archive corrected plans as skill correction candidates.
        self._active_skill: dict[str, str] | None = None

    async def run(self) -> OrchestratorResult:
        """Drive the CfA state machine to a terminal state."""
        # Recovery scan: merge/re-dispatch orphaned children before starting
        # MCP listeners.  This runs at every level of the hierarchy — any
        # dispatching agent might resume into a world with orphaned children.
        # Issue #149.
        await self._recover_orphaned_children()

        # The MCP server runs as a subprocess of Claude Code, whose cwd
        # is the session worktree — not the repo root.  Two fixes:
        # 1. Use the venv Python (system python3 lacks the mcp package)
        # 2. Set PYTHONPATH to repo root so the module path resolves
        repo_root = os.path.dirname(os.path.dirname(self.poc_root))
        venv_python = os.path.join(repo_root, '.venv', 'bin', 'python3')
        if not os.path.isfile(venv_python):
            venv_python = 'python3'  # fallback

        # Start the MCP escalation listener so agents can call AskQuestion
        if self.input_provider:
            self._escalation_listener = EscalationListener(
                event_bus=self.event_bus,
                input_provider=self.input_provider,
                session_id=self.session_id,
                proxy_model_path=self.proxy_model_path,
                project_slug=self.project_slug,
                cfa_state=self.cfa.state,
                session_worktree=self.session_worktree,
                infra_dir=self.infra_dir,
                team=self.team_override,
            )
            ask_question_socket = await self._escalation_listener.start()

            mcp_env = {
                'ASK_QUESTION_SOCKET': ask_question_socket,
                'PYTHONPATH': repo_root,
            }

            # Subteams (never_escalate) don't get AskTeam — only the
            # uber team dispatches.  Subteams get AskQuestion only.
            if not self.never_escalate:
                from orchestrator.dispatch_listener import DispatchListener  # noqa: PLC0415
                self._dispatch_listener = DispatchListener(
                    event_bus=self.event_bus,
                    session_worktree=self.session_worktree,
                    infra_dir=self.infra_dir,
                    project_slug=self.project_slug,
                    session_id=self.session_id,
                    poc_root=self.poc_root,
                    proxy_model_path=self.proxy_model_path,
                    project_dir=self.project_dir,
                )
                ask_team_socket = await self._dispatch_listener.start()
                mcp_env['ASK_TEAM_SOCKET'] = ask_team_socket

            # Start the intervention listener so office manager tools
            # (WithdrawSession, PauseDispatch, etc.) can execute.  The
            # resolver is a mutable dict — the orchestrator adds entries
            # as sessions/dispatches start.  Seeded with this session.
            # Issue #249.
            self._intervention_resolver[self.session_id] = self.infra_dir
            self._intervention_listener = InterventionListener(
                resolver=self._intervention_resolver,
            )
            intervention_socket = await self._intervention_listener.start()
            mcp_env['INTERVENTION_SOCKET'] = intervention_socket

            # Start the bus event listener so agents can use Send/Reply for
            # bus-mediated agent-to-agent dispatch (Issue #351).
            from orchestrator.bus_event_listener import BusEventListener  # noqa: PLC0415
            bus_db_path = os.path.join(self.infra_dir, 'messages.db')
            self._bus_event_listener = BusEventListener(
                bus_db_path=bus_db_path,
                initiator_agent_id=self.project_slug or '',
                spawn_fn=self._bus_spawn_agent,
            )
            send_socket, reply_socket = await self._bus_event_listener.start()
            mcp_env['SEND_SOCKET'] = send_socket
            mcp_env['REPLY_SOCKET'] = reply_socket

            self._mcp_config = {
                'ask-question': {
                    'command': venv_python,
                    'args': ['-m', 'orchestrator.mcp_server'],
                    'env': mcp_env,
                },
            }

        # Subscribe to stream events for scratch file extraction (Issue #261).
        self.event_bus.subscribe(self._on_scratch_event)

        try:
            return await self._run_loop()
        finally:
            self.event_bus.unsubscribe(self._on_scratch_event)
            self._scratch_writer.cleanup()
            if self._escalation_listener:
                await self._escalation_listener.stop()
            if self._dispatch_listener:
                await self._dispatch_listener.stop()
            if self._intervention_listener:
                await self._intervention_listener.stop()
            if self._bus_event_listener:
                await self._bus_event_listener.stop()

    async def _bus_spawn_agent(self, member: str, composite: str, context_id: str) -> str:
        """Spawn a recipient agent for bus-mediated dispatch (Issue #351).

        Creates an isolated directory for the agent, composes its skill set, and
        launches it as an independent claude -p process.  Runs the blocking subprocess
        call in an executor so the event loop is not blocked.

        Returns the session_id captured from claude's --output-format json output,
        or an empty string if capture fails (non-fatal; context record is still created).
        """
        from orchestrator.agent_spawner import AgentSpawner
        spawner = AgentSpawner(teaparty_home=self.poc_root)
        safe_id = context_id.replace(':', '_').replace('/', '_')
        agent_dir = os.path.join(self.infra_dir, 'agents', safe_id)
        os.makedirs(agent_dir, exist_ok=True)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: spawner.spawn(
                composite,
                worktree=agent_dir,
                role=member,
                project_dir=self.project_workdir,
            ),
        )

    async def _run_loop(self) -> OrchestratorResult:
        """Inner loop — separated so the listener cleanup is guaranteed."""
        while True:
            # Phase 1: Intent alignment
            if not self.skip_intent:
                result = await self._run_phase('intent')
                if result.terminal:
                    return self._make_result(result.terminal_state)
                if result.infrastructure_failure:
                    if result.failure_reason == 'api_overloaded':
                        overload_decision = await self._handle_overloaded('intent')
                        if overload_decision == 'retry':
                            continue
                        # 'escalate' — fall through to human dialog
                        # (unless never_escalate, in which case return failure
                        # so the parent dispatch loop can coordinate retries)
                        if self.never_escalate:
                            return self._make_result(self.cfa.state)
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

                # Skill self-correction (Issue #142): after planning
                # completes, check if the plan was corrected from the
                # original skill template.  Handles both human correction
                # at PLAN_ASSERT and System 2 fallback after backtrack.
                if not result.terminal and not result.infrastructure_failure:
                    self._check_skill_correction()

                if result.terminal:
                    return self._make_result(result.terminal_state)
                if result.backtrack_to == 'intent':
                    self._record_dead_end('planning', 'backtracked to intent', result.backtrack_feedback)
                    self._mark_false_positives('planning backtracked to intent')
                    if self.suppress_backtracks:
                        _log.info('Suppressing backtrack to intent (suppress_backtracks=True)')
                    else:
                        self.skip_intent = False
                        continue
                if result.infrastructure_failure:
                    if result.failure_reason == 'api_overloaded':
                        overload_decision = await self._handle_overloaded('planning')
                        if overload_decision == 'retry':
                            continue
                        if self.never_escalate:
                            return self._make_result(self.cfa.state)
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

                # Prospective learning: generate premortem before execution (Issue #199)
                self._write_premortem()
            # else: CfA is already at TASK (set_state_direct in Session.run)

            # Phase 3: Execution
            result = await self._run_phase('execution')
            if result.terminal:
                return self._make_result(result.terminal_state)
            if result.backtrack_to == 'intent':
                self._record_dead_end('execution', 'backtracked to intent', result.backtrack_feedback)
                self._mark_false_positives('execution backtracked to intent')
                if self.suppress_backtracks:
                    _log.info('Suppressing backtrack to intent (suppress_backtracks=True)')
                else:
                    self.skip_intent = False
                    continue
            if result.backtrack_to == 'planning':
                self._record_dead_end('execution', 'backtracked to planning', result.backtrack_feedback)
                self._mark_false_positives('execution backtracked to planning')
                if self.suppress_backtracks:
                    _log.info('Suppressing backtrack to planning (suppress_backtracks=True)')
                else:
                    self.skip_intent = True
                    continue
            if result.infrastructure_failure:
                if result.failure_reason == 'api_overloaded':
                    overload_decision = await self._handle_overloaded('execution')
                    if overload_decision == 'retry':
                        continue
                    if self.never_escalate:
                        return self._make_result(self.cfa.state)
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
        # Build scope-ordered skill directories: narrowest first (Issue #196).
        # Team scope (if team context exists) → project scope.
        skills_dirs: list[tuple[str, str]] = []
        if self.team_override:
            team_skills = os.path.join(
                self.project_workdir, 'teams', self.team_override, 'skills',
            )
            skills_dirs.append(('team', team_skills))
        project_skills = os.path.join(self.project_workdir, 'skills')
        skills_dirs.append(('project', project_skills))

        # Fast exit: if no scope directory exists on disk, skip lookup.
        if not any(os.path.isdir(d) for _, d in skills_dirs):
            return False

        # Read the approved intent from infra_dir (Issue #147)
        intent = ''
        intent_path = os.path.join(self.infra_dir, 'INTENT.md')
        try:
            with open(intent_path) as f:
                intent = f.read()
        except OSError:
            pass

        # Build embed_fn from memory_indexer if available (Issue #215).
        embed_fn = None
        try:
            from scripts.memory_indexer import try_embed, detect_provider
            provider, model = detect_provider()
            if provider != 'none':
                embed_fn = lambda text: try_embed(text, provider=provider, model=model)
        except Exception:
            _log.debug('Embedding provider unavailable for skill lookup')

        try:
            match = lookup_skill(
                task=self.task,
                intent=intent,
                skills_dirs=skills_dirs,
                embed_fn=embed_fn,
            )
        except Exception:
            _log.debug('Skill lookup failed, falling through to cold start')
            return False

        if not match:
            return False

        # Write the skill template as PLAN.md to infra_dir (Issue #147)
        plan_path = os.path.join(self.infra_dir, 'PLAN.md')
        with open(plan_path, 'w') as f:
            f.write(match.template)

        # Track which skill was used (Issue #142 — skill self-correction).
        # Store the original template so we can detect corrections later:
        # after planning completes, if PLAN.md differs from the template,
        # the plan was corrected (by human at PLAN_ASSERT or by System 2
        # after backtrack) and should be archived as a correction candidate.
        self._active_skill = {
            'name': match.name,
            'path': match.path,
            'score': str(match.score),
            'scope': match.scope,
            'template': match.template,
        }

        # Persist active skill to disk so extract_learnings can find it
        # post-session (Issue #146 — gate outcomes as skill reward signal).
        import json as _json
        sidecar_path = os.path.join(self.infra_dir, '.active-skill.json')
        try:
            with open(sidecar_path, 'w') as f:
                _json.dump({
                    'name': match.name,
                    'path': match.path,
                    'score': str(match.score),
                    'scope': match.scope,
                    'session_id': self.session_id,
                }, f)
        except OSError:
            _log.warning('Failed to write .active-skill.json sidecar')

        # Propagate active skill to approval gate for log tagging (Issue #146)
        self._approval_gate._active_skill = self._active_skill

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
                'skill_scope': match.scope,
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
                # In-flight learning: write assumption checkpoint (Issue #199)
                self._write_assumption_checkpoint(phase_name)
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
                if reason in ('stall_timeout', 'nonzero_exit', 'api_overloaded'):
                    return PhaseResult(
                        infrastructure_failure=True,
                        failure_reason=reason,
                    )

            # Accumulate cost from this turn (Issues #262, #341)
            turn_cost = actor_result.data.get('cost_usd', 0.0)
            if turn_cost:
                if self._cost_tracker:
                    cost_event: dict[str, Any] = {
                        'type': 'result',
                        'total_cost_usd': turn_cost,
                    }
                    per_model = actor_result.data.get('cost_per_model')
                    if per_model:
                        cost_event['cost_usd'] = per_model
                    self._cost_tracker.record(cost_event)
                    # Record to project-level ledger for cross-job aggregation
                    if self._project_cost_ledger:
                        self._project_cost_ledger.record(self.session_id, turn_cost)
                    # Write running total for dashboard display
                    self._write_cost_sidecar()
                # Publish turn stats so job chat cost filter receives them (Issue #341)
                turn_stats: dict[str, Any] = {'total_cost_usd': turn_cost}
                for key in ('input_tokens', 'output_tokens', 'duration_ms'):
                    val = actor_result.data.get(key)
                    if val:
                        turn_stats[key] = val
                await self.event_bus.publish(Event(
                    type=EventType.TURN_COST,
                    data=turn_stats,
                    session_id=self.session_id,
                ))

            # Apply the CfA transition
            await self._transition(actor_result.action, actor_result)

            # Turn boundary: check for pending interventions (Issue #246).
            # Only deliver when the next actor is an agent, not a human gate.
            if (self._intervention_queue
                    and self._intervention_queue.has_pending()
                    and self.cfa.state not in self.config.human_actor_states
                    and not is_globally_terminal(self.cfa.state)):
                await self._deliver_intervention()

            # Turn boundary: update scratch file (Issue #261).
            # Must happen BEFORE the compaction check so that
            # .context/scratch.md exists when compaction fires and
            # the compact prompt tells the agent to read it.
            if not is_globally_terminal(self.cfa.state):
                self._update_scratch(phase_name)

            # Turn boundary: check context budget for compaction (Issue #260).
            if not is_globally_terminal(self.cfa.state):
                await self._check_context_budget(actor_result, phase_name)

            # Turn boundary: check cost budget (Issue #262).
            # Warn at 80%, pause at 100%. Pausing means withholding the
            # next prompt until the human responds — same mechanism as
            # compaction triggering.
            if self._cost_tracker and not is_globally_terminal(self.cfa.state):
                await self._check_cost_budget()

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
            mcp_config=self._mcp_config,
            # Heartbeat liveness (issue #149)
            heartbeat_file=os.path.join(self.infra_dir, '.heartbeat'),
            parent_heartbeat=self._parent_heartbeat,
            children_file=os.path.join(self.infra_dir, '.children'),
        )

        if state in self.config.human_actor_states:
            # Human or approval gate — run the approval gate
            ctx.data = self._last_actor_data
            return await self._approval_gate.run(ctx)

        # Inject human feedback from escalation/correction so the agent
        # can see what the human said (feedback + optional dialog transcript).
        prev_feedback = self._last_actor_data.get('feedback', '')
        prev_dialog = self._last_actor_data.get('dialog_history', '')
        if prev_feedback or prev_dialog:
            parts = []
            if prev_dialog:
                parts.append(f'[escalation dialog]\n{prev_dialog}')
            if prev_feedback:
                parts.append(f'[human feedback]\n{prev_feedback}')
            feedback_block = '\n\n'.join(parts)
            ctx.backtrack_context = (
                (ctx.backtrack_context + '\n\n' if ctx.backtrack_context else '')
                + feedback_block
            )

        # Inject stderr from previous turn so the agent can see CLI errors
        prev_stderr = self._last_actor_data.get('stderr_lines', [])
        if prev_stderr:
            stderr_block = '\n'.join(prev_stderr)
            ctx.backtrack_context = (
                (ctx.backtrack_context + '\n\n' if ctx.backtrack_context else '')
                + f'[stderr from previous turn]\n{stderr_block}'
            )

        # Inject pending intervention from the queue (Issue #246).
        # The intervention prompt replaces backtrack_context so the agent
        # receives it as the next --resume prompt at the turn boundary.
        if self._pending_intervention:
            ctx.backtrack_context = (
                (ctx.backtrack_context + '\n\n' if ctx.backtrack_context else '')
                + self._pending_intervention
            )
            self._pending_intervention = ''

        # Agent actor — run agent
        return await self._agent_runner.run(ctx)

    async def _deliver_intervention(self) -> None:
        """Drain the intervention queue, publish INTERVENE, store prompt for injection.

        Called at turn boundaries when the queue has pending messages.
        Stores the intervention prompt in ``_pending_intervention`` so
        ``_invoke_actor()`` injects it as backtrack context on the next
        agent turn (delivered via ``--resume``).

        Issue #246.
        """
        if not self._intervention_queue:
            return

        messages = self._intervention_queue.drain()
        if not messages:
            return

        prompt = build_intervention_prompt(messages, role_enforcer=self._role_enforcer)
        self._pending_intervention = prompt
        self._intervention_active = True  # Issue #247: track for cascade

        # Determine current phase name for the learning chunk context.
        try:
            current_phase = phase_for_state(self.cfa.state)
        except ValueError:
            current_phase = 'unknown'

        # Record as a learning-system chunk for post-session proxy extraction.
        # Issue #276.
        write_intervention_chunk(
            infra_dir=self.infra_dir,
            content=prompt,
            senders=[m.sender for m in messages],
            cfa_state=self.cfa.state,
            phase=current_phase,
        )

        await self.event_bus.publish(Event(
            type=EventType.INTERVENE,
            data={
                'content': prompt,
                'message_count': len(messages),
                'senders': [m.sender for m in messages],
            },
            session_id=self.session_id,
        ))

    async def _check_context_budget(self, actor_result: ActorResult, phase_name: str) -> None:
        """Check context budget and inject /compact at turn boundary (Issue #260).

        Called after every CfA transition.  Inspects the context_budget
        from the actor result and:
        - At warning threshold: publishes CONTEXT_WARNING event
        - At compact threshold: injects /compact as next prompt via --resume
        """
        budget = actor_result.data.get('context_budget')
        if not isinstance(budget, ContextBudget):
            return

        if budget.should_warn and not budget.should_compact:
            await self.event_bus.publish(Event(
                type=EventType.CONTEXT_WARNING,
                data={
                    'utilization': budget.utilization,
                    'used_tokens': budget.used_tokens,
                    'context_window': budget.context_window,
                    'phase': phase_name,
                },
                session_id=self.session_id,
            ))
            budget.clear_warning()

        if budget.should_compact:
            task = self._task_for_phase(phase_name)
            compact_prompt = build_compact_prompt(
                cfa_state=self.cfa.state,
                task=task,
                scratch_path='.context/scratch.md',
            )
            # Inject as pending intervention — same mechanism as Issue #246.
            # Compaction takes priority: overwrite any pending intervention.
            self._pending_intervention = compact_prompt

            await self.event_bus.publish(Event(
                type=EventType.CONTEXT_WARNING,
                data={
                    'utilization': budget.utilization,
                    'used_tokens': budget.used_tokens,
                    'context_window': budget.context_window,
                    'phase': phase_name,
                    'action': 'compact',
                    'compact_prompt': compact_prompt,
                },
                session_id=self.session_id,
            ))
            budget.clear_compact()

    async def _check_cost_budget(self) -> None:
        """Check cost budget thresholds and publish events (Issue #262).

        Called at turn boundaries after each agent turn completes.
        - At 80%: publish COST_WARNING and escalate to human (once per job)
        - At 100%: publish COST_LIMIT, pause the job (withhold next prompt),
          and ask the human "Continue?"
        """
        tracker = self._cost_tracker
        if not tracker:
            return

        # Warn at 80% (once)
        if tracker.warning_triggered and not self._cost_warning_emitted:
            self._cost_warning_emitted = True
            await self.event_bus.publish(Event(
                type=EventType.COST_WARNING,
                data={
                    'total_cost_usd': tracker.total_cost_usd,
                    'job_limit_usd': tracker.job_limit,
                    'utilization': tracker.utilization,
                },
                session_id=self.session_id,
            ))

        # Pause at 100% — withhold the next prompt until the human responds.
        if tracker.limit_reached:
            cost = tracker.total_cost_usd
            limit = tracker.job_limit
            await self.event_bus.publish(Event(
                type=EventType.COST_LIMIT,
                data={
                    'total_cost_usd': cost,
                    'job_limit_usd': limit,
                    'utilization': tracker.utilization,
                },
                session_id=self.session_id,
            ))

            # Ask the human whether to continue — same pause mechanism
            # as infrastructure failure escalation.
            bridge_text = (
                f'This job has used ${cost:.2f} of its ${limit:.2f} budget. '
                f'Continue?'
            )
            await self.event_bus.publish(Event(
                type=EventType.INPUT_REQUESTED,
                data={'state': 'COST_LIMIT', 'bridge_text': bridge_text},
                session_id=self.session_id,
            ))
            response = await self.input_provider(InputRequest(
                type='cost_limit',
                state='COST_LIMIT',
                artifact='',
                bridge_text=bridge_text,
            ))

            # If the human says to continue, let the turn loop proceed.
            # Otherwise inject a wrap-up prompt.
            resp_lower = (response or '').strip().lower()
            if resp_lower in ('no', 'n', 'stop', 'withdraw'):
                self._pending_intervention = (
                    f'[COST BUDGET EXCEEDED] The human declined to continue. '
                    f'Wrap up current work and commit partial progress.'
                )

        # Project-level budget check — aggregates across all jobs.
        await self._check_project_cost_budget()

    async def _check_project_cost_budget(self) -> None:
        """Check project-level cost budget (aggregated across jobs)."""
        tracker = self._cost_tracker
        ledger = self._project_cost_ledger
        if not tracker or not ledger or not tracker.project_limit:
            return

        project_total = ledger.total_cost()
        project_limit = tracker.project_limit
        utilization = project_total / project_limit if project_limit else 0.0

        # Warn at 80% (once)
        if utilization >= WARNING_THRESHOLD and not self._project_cost_warning_emitted:
            self._project_cost_warning_emitted = True
            await self.event_bus.publish(Event(
                type=EventType.COST_WARNING,
                data={
                    'total_cost_usd': project_total,
                    'project_limit_usd': project_limit,
                    'utilization': utilization,
                    'scope': 'project',
                },
                session_id=self.session_id,
            ))

        # Pause at 100%
        if utilization >= LIMIT_THRESHOLD:
            await self.event_bus.publish(Event(
                type=EventType.COST_LIMIT,
                data={
                    'total_cost_usd': project_total,
                    'project_limit_usd': project_limit,
                    'utilization': utilization,
                    'scope': 'project',
                },
                session_id=self.session_id,
            ))

            bridge_text = (
                f'Project has used ${project_total:.2f} of its '
                f'${project_limit:.2f} budget across all jobs. Continue?'
            )
            await self.event_bus.publish(Event(
                type=EventType.INPUT_REQUESTED,
                data={'state': 'COST_LIMIT', 'bridge_text': bridge_text},
                session_id=self.session_id,
            ))
            response = await self.input_provider(InputRequest(
                type='cost_limit',
                state='COST_LIMIT',
                artifact='',
                bridge_text=bridge_text,
            ))
            resp_lower = (response or '').strip().lower()
            if resp_lower in ('no', 'n', 'stop', 'withdraw'):
                self._pending_intervention = (
                    f'[PROJECT BUDGET EXCEEDED] The human declined to continue. '
                    f'Wrap up current work and commit partial progress.'
                )

    def _write_cost_sidecar(self) -> None:
        """Write running cost total to infra_dir for dashboard display."""
        if not self._cost_tracker or not self.infra_dir:
            return
        try:
            path = os.path.join(self.infra_dir, '.cost')
            with open(path, 'w') as f:
                f.write(f'{self._cost_tracker.total_cost_usd:.6f}\n')
        except OSError:
            pass

    async def _on_scratch_event(self, event: Event) -> None:
        """Feed events into the scratch model (Issue #261).

        Subscribed to the event bus in run().  Processes two event types:
        - STREAM_DATA: extracts human input and file modifications
        - STATE_CHANGED: records CfA state transitions

        These are different event sources: STREAM_DATA comes from the
        Claude Code CLI stream, while STATE_CHANGED is published by the
        engine's own _transition method.
        """
        if event.type == EventType.STREAM_DATA:
            data = event.data
            self._scratch_model.extract(data)

            # Append human input to detail file as it arrives.
            if data.get('type') == 'user':
                msg = data.get('message', {})
                raw = msg.get('content', '') if isinstance(msg, dict) else ''
                text = extract_text(raw)
                if text:
                    self._scratch_writer.append_human_input(text)

        elif event.type == EventType.STATE_CHANGED:
            data = event.data
            self._scratch_model.record_state_change(
                previous_state=data.get('previous_state', ''),
                new_state=data.get('state', ''),
            )

    def _update_scratch(self, phase_name: str) -> None:
        """Serialize the scratch model to disk at a turn boundary (Issue #261)."""
        self._scratch_model.phase = phase_name
        self._scratch_writer.write_scratch(self._scratch_model)

    def _record_dead_end(self, phase: str, reason: str, feedback: str = '') -> None:
        """Record a dead end from a backtrack (Issue #261)."""
        desc = f'{phase}: {reason}'
        if feedback:
            desc += f' — {feedback[:200]}'
        self._scratch_model.add_dead_end(desc)
        self._scratch_writer.append_dead_end(desc)

    async def _check_interrupt_propagation(self, old_state: str) -> None:
        """Cascade intervention decisions to active child dispatches (Issue #247).

        Called after every CfA transition.  When an intervention was recently
        delivered (_intervention_active) and the lead's response caused a
        cross-phase backtrack or a withdrawal, cascade-withdraw all active
        child dispatches.

        If the lead continues (same or forward phase), the flag is cleared
        and dispatches are left running.
        """
        if not self._intervention_active:
            return

        new_state = self.cfa.state

        # Withdrawal: cascade immediately
        if new_state == 'WITHDRAWN':
            withdrawn = cascade_withdraw_children(self.infra_dir, self.cfa.phase)
            self._intervention_active = False
            write_intervention_outcome(  # Issue #276
                infra_dir=self.infra_dir,
                outcome='withdraw',
            )
            if withdrawn:
                await self.event_bus.publish(Event(
                    type=EventType.LOG,
                    data={
                        'category': 'interrupt_propagation',
                        'trigger': 'withdrawal',
                        'old_state': old_state,
                        'new_state': new_state,
                        'children_withdrawn': len(withdrawn),
                        'teams': [w['team'] for w in withdrawn],
                    },
                    session_id=self.session_id,
                ))
            return

        # Backtrack: cascade-withdraw if phase moved earlier
        try:
            old_phase = phase_for_state(old_state)
            new_phase = phase_for_state(new_state)
        except ValueError:
            self._intervention_active = False
            write_intervention_outcome(  # Issue #276
                infra_dir=self.infra_dir,
                outcome='continue',
            )
            return

        if is_backtrack(old_phase, new_phase):
            withdrawn = cascade_withdraw_children(self.infra_dir, new_phase)
            self._intervention_active = False
            write_intervention_outcome(  # Issue #276
                infra_dir=self.infra_dir,
                outcome='backtrack',
                backtrack_phase=new_phase,
            )
            if withdrawn:
                await self.event_bus.publish(Event(
                    type=EventType.LOG,
                    data={
                        'category': 'interrupt_propagation',
                        'trigger': 'backtrack',
                        'old_state': old_state,
                        'old_phase': old_phase,
                        'new_state': new_state,
                        'new_phase': new_phase,
                        'children_withdrawn': len(withdrawn),
                        'teams': [w['team'] for w in withdrawn],
                    },
                    session_id=self.session_id,
                ))
            return

        # Continue/adjustment: we reach here only when the transition is
        # same-phase or forward (WITHDRAWN and backtrack both returned above).
        # The lead processed the intervention and chose to continue.
        # Dispatches keep running.
        self._intervention_active = False
        write_intervention_outcome(  # Issue #276
            infra_dir=self.infra_dir,
            outcome='continue',
        )

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

        # Keep the escalation listener's CfA state current
        if self._escalation_listener:
            self._escalation_listener.cfa_state = self.cfa.state

        # Track data from the actor result for the next actor
        self._last_actor_data = actor_result.data
        if actor_result.feedback:
            self._last_actor_data['feedback'] = actor_result.feedback
        if actor_result.dialog_history:
            self._last_actor_data['dialog_history'] = actor_result.dialog_history

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

        # Interrupt propagation: cascade intervention decisions to children (Issue #247)
        await self._check_interrupt_propagation(old_state)

        # Auto-commit artifacts to the session worktree after writes
        await self._commit_artifacts(old_state, action)

        # Post-intent-approval: detect project stage and retire old-stage memory
        if old_state == 'INTENT_ASSERT' and action == 'approve':
            self._detect_and_retire_stage()

    async def _commit_artifacts(self, old_state: str, action: str) -> None:
        """Auto-commit deliverables to the session worktree after writes.

        Only execution deliverables are committed (TASK_ASSERT).  INTENT.md
        and PLAN.md live exclusively in infra_dir — they are not committed
        to the worktree.  Dispatch agents receive context via the task
        string, not git branch inheritance.  Issue #148.
        """
        wt = self.session_worktree
        if not wt:
            return

        new_state = self.cfa.state
        try:
            if new_state == 'TASK_ASSERT':
                await commit_artifact(wt, ['.'], f'Execution: {action}')
        except Exception as exc:
            _log.warning('Artifact commit failed (non-fatal): %s', exc)

    def _detect_and_retire_stage(self) -> None:
        """Detect the project stage from INTENT.md and retire old-stage memory."""
        from pathlib import Path

        intent_path = os.path.join(self.infra_dir, 'INTENT.md')
        if not os.path.exists(intent_path):
            intent_path = os.path.join(self.session_worktree, 'INTENT.md')
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
                    from scripts.memory_entry import (
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

    def _write_assumption_checkpoint(self, phase_name: str) -> None:
        """Write an assumption checkpoint at phase completion (Issue #199).

        Reads the phase's artifact (INTENT.md or PLAN.md) and includes its
        content in the checkpoint, so the downstream in-flight extraction
        pipeline has substantive assumptions to work with — not just metadata.
        """
        from pathlib import Path as _Path

        # Read the artifact that this phase produced
        artifact_names = {
            'intent': 'INTENT.md',
            'planning': 'PLAN.md',
        }
        artifact_name = artifact_names.get(phase_name)
        artifact_content = ''
        if artifact_name:
            artifact_path = os.path.join(self.infra_dir, artifact_name)
            if os.path.isfile(artifact_path):
                try:
                    artifact_content = _Path(artifact_path).read_text(errors='replace')
                except OSError:
                    pass

        summary = artifact_content if artifact_content.strip() else (
            f'{phase_name} phase completed at {self.cfa.state}'
        )

        try:
            from orchestrator.learnings import write_assumption_checkpoint
            write_assumption_checkpoint(
                infra_dir=self.infra_dir,
                phase=phase_name,
                cfa_state=self.cfa.state,
                artifact_summary=summary,
            )
        except Exception as exc:
            _log.warning('Assumption checkpoint failed (non-fatal): %s', exc)

    def _write_premortem(self) -> None:
        """Generate premortem from PLAN.md before execution begins (Issue #199).

        Called at the planning→execution bridge so the post-session
        prospective extraction pipeline has input to work with.
        """
        try:
            from orchestrator.learnings import write_premortem
            write_premortem(
                infra_dir=self.infra_dir,
                task=self.task,
            )
        except Exception as exc:
            _log.warning('Premortem generation failed (non-fatal): %s', exc)

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
            from orchestrator.phase_config import PhaseSpec
            return PhaseSpec(
                name=base.name,
                agent_file=team.agent_file,
                lead=team.lead,
                permission_mode=perm,
                stream_file=base.stream_file,
                artifact=base.artifact,
                approval_state=base.approval_state,
                settings_overlay=base.settings_overlay,
            )

        base = self.config.resolve_phase(phase_name)

        # --flat: swap the project team for a flat team where the lead
        # recruits agents dynamically via the Agent tool.
        # Only affects phases that use uber-team.json (planning, execution).
        if self.flat and 'uber-team' in base.agent_file:
            from orchestrator.phase_config import PhaseSpec
            return PhaseSpec(
                name=base.name,
                agent_file='agents/flat-team.json',
                lead='project-lead',
                permission_mode=base.permission_mode,
                stream_file=base.stream_file,
                artifact=base.artifact,
                approval_state=base.approval_state,
                settings_overlay=base.settings_overlay,
            )

        return base

    def _task_for_phase(self, phase_name: str) -> str:
        """Get the task description for a phase.

        Intent phase: uses the original task description, with constraints
            (resolved norms) and escalation guidance injected.
        Planning phase: reads INTENT.md (the intent phase's output), with
            dynamically-resolved available teams injected.
        Execution phase: reads PLAN.md as the workflow to follow,
            with INTENT.md appended as reference context.

        On cold start (< COLD_START_THRESHOLD observations for the phase's
        approval state), appends context informing the agent that this is a
        first encounter and the proxy has no model of the human's preferences.
        """
        from scripts.approval_gate import COLD_START_THRESHOLD

        base_task = ''
        if phase_name == 'execution':
            plan_path = os.path.join(self.infra_dir, 'PLAN.md')
            intent_path = os.path.join(self.infra_dir, 'INTENT.md')
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
            intent_path = os.path.join(self.infra_dir, 'INTENT.md')
            try:
                with open(intent_path) as f:
                    base_task = f.read()
            except OSError:
                pass

        if not base_task:
            # Intent phase, or artifacts not yet written
            base_task = self.task or self.project_slug

        # Inject phase-specific constraints (Issue #141)
        if phase_name == 'intent':
            constraints = self._resolve_intent_constraints()
            if constraints:
                base_task += constraints
        elif phase_name == 'planning':
            teams_block = self._resolve_available_teams()
            if teams_block:
                base_task += teams_block

        # Append cold-start context for intent and planning phases
        if phase_name in ('intent', 'planning'):
            obs_count = self._get_observation_count(phase_name)
            if obs_count < COLD_START_THRESHOLD:
                cold_start_context = (
                    '\n\n--- Cold Start Context ---\n'
                    f'This is a cold start — the proxy has {obs_count} prior '
                    f'observation(s) for this project and phase (threshold: '
                    f'{COLD_START_THRESHOLD}). The system has no model of the '
                    f"human's preferences yet. Exploring the problem space and "
                    f'engaging the human with what you find before producing '
                    f'the artifact will lead to a better result than a '
                    f'one-shot attempt.\n'
                    '--- end ---'
                )
                base_task += cold_start_context

        return base_task

    def _resolve_intent_constraints(self) -> str:
        """Resolve norms/guardrails as constraints for the intent phase.

        Loads norms from the configuration tree and frames them as constraints
        with escalation guidance. Returns empty string if no constraints exist.

        Issue #141: agents must know their constraints and escalate.
        """
        from orchestrator.config_reader import (
            load_management_team,
            load_project_team,
            resolve_norms,
        )

        org_norms: dict[str, list[str]] = {}
        project_norms: dict[str, list[str]] = {}

        try:
            mgmt = load_management_team()
            org_norms = mgmt.norms
        except (FileNotFoundError, OSError):
            pass

        if self.project_dir:
            try:
                proj = load_project_team(self.project_dir)
                project_norms = proj.norms
            except (FileNotFoundError, OSError):
                pass

        norms_text = resolve_norms(
            org_norms=org_norms, project_norms=project_norms,
        )
        if not norms_text:
            return ''

        return (
            '\n\n--- Constraints ---\n'
            'The following constraints apply to this project. If the request '
            'would violate any of these constraints, escalate — do not accept '
            'the request as-is. Escalation is the correct response when '
            'constraints cannot be met.\n\n'
            f'{norms_text}\n'
            '--- end ---'
        )

    def _resolve_available_teams(self) -> str:
        """Resolve dynamically-available teams and skills for the planning phase.

        Reads the project-scoped team list from PhaseConfig and available
        skills from the project's skills directories.  Formats both for
        injection into the planning task context.

        Issue #141: planning agent must know what teams and skills exist.
        """
        parts = []

        # Teams
        teams = self.config.project_teams
        if teams:
            team_names = sorted(teams.keys())
            parts.append(
                'Available teams for dispatch: '
                + ', '.join(team_names) + '.\n'
                'Only reference these teams in the plan. If the task requires '
                'capabilities not covered by these teams, escalate.'
            )

        # Skills
        skills_summary = self._list_available_skills()
        if skills_summary:
            parts.append(
                'Available skills (learned procedures that can seed the plan):\n'
                + skills_summary
            )

        if not parts:
            return ''

        return (
            '\n\n--- Planning Constraints ---\n'
            + '\n\n'.join(parts)
            + '\n--- end ---'
        )

    def _list_available_skills(self) -> str:
        """List skill names and descriptions from the project's skills directories.

        Returns a formatted summary or empty string if no skills exist.
        """
        from orchestrator.skill_lookup import _parse_frontmatter

        skills_dirs: list[tuple[str, str]] = []
        if self.team_override:
            team_skills = os.path.join(
                self.project_workdir, 'teams', self.team_override, 'skills',
            )
            skills_dirs.append(('team', team_skills))
        project_skills = os.path.join(self.project_workdir, 'skills')
        skills_dirs.append(('project', project_skills))

        seen_names: set[str] = set()
        entries: list[str] = []

        for _scope, dirpath in skills_dirs:
            if not os.path.isdir(dirpath):
                continue
            for filename in sorted(os.listdir(dirpath)):
                if not filename.endswith('.md'):
                    continue
                path = os.path.join(dirpath, filename)
                if not os.path.isfile(path):
                    continue
                try:
                    meta, _ = _parse_frontmatter(path)
                except Exception:
                    continue
                if meta.get('needs_review', '').lower() == 'true':
                    continue
                name = meta.get('name', filename[:-3])
                if name in seen_names:
                    continue
                seen_names.add(name)
                desc = meta.get('description', '')
                entry = f'- {name}'
                if desc:
                    entry += f': {desc}'
                entries.append(entry)

        return '\n'.join(entries)

    # Maximum auto-retries for API overloaded (529) before escalating to human.
    # Each retry adds a flat cooldown — not exponential, since the CLI already
    # did exponential backoff internally.
    _MAX_OVERLOAD_RETRIES = 3
    _OVERLOAD_COOLDOWN_SECONDS = 120

    async def _handle_overloaded(self, phase_name: str) -> str:
        """Handle an API overloaded (529) failure with auto-retry.

        Tracks retry count per phase.  On each retry, emits an API_OVERLOADED
        event and waits a flat cooldown.  After exhausting retries, returns
        'escalate' so the caller falls through to _failure_dialog.

        Returns 'retry' or 'escalate'.
        """
        counter_key = f'_overload_retries_{phase_name}'
        count = getattr(self, counter_key, 0) + 1
        setattr(self, counter_key, count)

        if count > self._MAX_OVERLOAD_RETRIES:
            return 'escalate'

        # Emit event for bridge observability
        await self.event_bus.publish(Event(
            type=EventType.API_OVERLOADED,
            data={
                'phase': phase_name,
                'retry_count': count,
                'max_retries': self._MAX_OVERLOAD_RETRIES,
                'cooldown_seconds': self._OVERLOAD_COOLDOWN_SECONDS,
            },
            session_id=self.session_id,
        ))

        _log.info(
            'API overloaded (529) — auto-retry %d/%d for %s, '
            'cooling down %ds',
            count, self._MAX_OVERLOAD_RETRIES, phase_name,
            self._OVERLOAD_COOLDOWN_SECONDS,
        )

        await asyncio.sleep(self._OVERLOAD_COOLDOWN_SECONDS)
        return 'retry'

    async def _failure_dialog(self, reason: str) -> str:
        """Ask human what to do after infrastructure failure.

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
        try:
            from scripts.classify_review import classify
            raw = classify('FAILURE', response)
            action = raw.split('\t', 1)[0]
        except Exception:
            action = '__fallback__'
        if action in ('backtrack', 'withdraw'):
            return action
        return 'retry'

    def _mark_false_positives(self, reason: str) -> None:
        """Mark prior auto-approvals as false positives on backtrack (#11)."""
        try:
            from scripts.approval_gate import mark_false_positive_approvals
            log_path = os.path.join(
                os.path.dirname(self.proxy_model_path),
                '.proxy-interactions.jsonl',
            )
            count = mark_false_positive_approvals(
                log_path=log_path,
                session_id=self.session_id,
                reason=reason,
            )
            if count > 0:
                _log.info(
                    'Marked %d prior auto-approvals as false positives: %s',
                    count, reason,
                )
        except Exception:
            pass

    def _check_skill_correction(self) -> None:
        """Check if planning corrected a skill-based plan and archive the correction.

        Called after _run_phase('planning') completes normally.  Compares
        the current PLAN.md to the original skill template.  If they differ,
        the plan was corrected — either by the human at PLAN_ASSERT or by
        the planning agent (System 2 fallback after backtrack) — and the
        corrected plan is archived as a skill correction candidate.

        Issue #142: skill self-correction on backtrack.
        """
        if not self._active_skill:
            return

        from pathlib import Path

        plan_path = os.path.join(self.infra_dir, 'PLAN.md')
        if not os.path.isfile(plan_path):
            return

        try:
            with open(plan_path) as f:
                current_plan = f.read()
        except OSError:
            return

        original_template = self._active_skill.get('template', '')
        if current_plan.strip() == original_template.strip():
            # Plan unchanged — skill was approved as-is, no correction needed
            return

        skill_name = self._active_skill['name']
        skill_path = self._active_skill.get('path', '')

        # Read category from the skill file (Issue #239)
        skill_category = ''
        if skill_path and os.path.isfile(skill_path):
            try:
                from orchestrator.procedural_learning import _parse_candidate_frontmatter
                _skill_content = Path(skill_path).read_text(errors='replace')
                _skill_meta, _ = _parse_candidate_frontmatter(_skill_content)
                skill_category = _skill_meta.get('category', '')
            except OSError:
                pass

        try:
            from orchestrator.procedural_learning import archive_skill_candidate
            archived = archive_skill_candidate(
                infra_dir=self.infra_dir,
                project_dir=self.project_workdir,
                task=self.task,
                session_id=f'{self.session_id}-correction',
                corrects_skill=skill_name,
                category=skill_category,
            )
            if archived:
                _log.info(
                    'Archived corrected plan as skill correction candidate '
                    'for skill %s', skill_name,
                )
        except Exception as exc:
            _log.warning('Failed to archive skill correction: %s', exc)

        # Clear active skill — the correction has been recorded
        self._active_skill = None
        self._approval_gate._active_skill = None

    def _get_observation_count(self, phase_name: str = '') -> int:
        """Get the proxy model's observation count for the current phase's approval state.

        Looks up the (approval_state, project_slug) pair — not the current CfA
        state — because observations are recorded at approval gates (INTENT_ASSERT,
        PLAN_ASSERT), not at agent-running states (PROPOSAL, DRAFT).

        Returns 0 if the proxy model doesn't exist or the pair has no entries.
        """
        from scripts.approval_gate import load_model, _entry_key

        if not phase_name:
            phase_name = phase_for_state(self.cfa.state)
        try:
            spec = self.config.phase(phase_name)
        except KeyError:
            return 0

        try:
            model = load_model(self.proxy_model_path)
        except Exception:
            return 0

        key = _entry_key(spec.approval_state, self.project_slug)
        raw = model.entries.get(key)
        if raw is None:
            return 0
        if isinstance(raw, dict):
            return raw.get('total_count', 0)
        return getattr(raw, 'total_count', 0)

    def _build_env_vars(self) -> dict[str, str]:
        obs_count = self._get_observation_count()
        return {
            'POC_PROJECT': self.project_slug,
            'POC_PROJECT_DIR': self.project_workdir,
            'POC_SESSION_DIR': self.infra_dir,
            'POC_SESSION_WORKTREE': self.session_worktree,
            'POC_CFA_STATE': os.path.join(self.infra_dir, '.cfa-state.json'),
            # SCRIPT_DIR and PROJECTS_DIR needed by subprocesses (e.g. dispatch_cli.py)
            'SCRIPT_DIR': self.poc_root,
            'PROJECTS_DIR': os.path.dirname(self.project_workdir),
            'POC_PROXY_OBSERVATIONS': str(obs_count),
        }

    def _build_add_dirs(self) -> list[str]:
        # Issue #150: return empty — agents must not receive --add-dir flags.
        # The worktree (set as cwd) contains everything the agent needs.
        # Extra --add-dir paths leak absolute paths into the agent's context,
        # causing writes to wrong locations.
        return []

    async def _recover_orphaned_children(self) -> None:
        """Scan .children registry and recover orphaned dispatches (issue #149).

        Runs before MCP listeners start so no new dispatches arrive during
        recovery.  Any dispatching agent at any level needs this.

        - Completed children: merge their worktree into session worktree
        - Dead non-terminal: log for re-dispatch (resume path)
        - Live children: leave alone
        """
        children_path = os.path.join(self.infra_dir, '.children')
        if not os.path.exists(children_path):
            return

        from orchestrator.heartbeat import (
            scan_children, compact_children, create_heartbeat, read_heartbeat,
        )
        from orchestrator.merge import squash_merge

        # Write a fresh heartbeat for ourselves so adopted children see a live
        # parent instead of triggering their shutdown sequence (gap 5/12).
        my_hb = os.path.join(self.infra_dir, '.heartbeat')
        if not os.path.exists(my_hb):
            create_heartbeat(my_hb, role='session')

        scan = scan_children(children_path)

        # Merge completed children
        for child in scan['completed']:
            hb_path = child.get('heartbeat', '')
            if not hb_path:
                continue
            child_infra = os.path.dirname(hb_path)
            cfa_path = os.path.join(child_infra, '.cfa-state.json')
            if not os.path.exists(cfa_path):
                continue

            cfa_data = load_state(cfa_path)
            if cfa_data.state != 'COMPLETED_WORK':
                continue

            # Find the worktree path from the manifest
            worktree_path = self._find_dispatch_worktree(child_infra)
            if not worktree_path or not os.path.isdir(worktree_path):
                _log.warning('Recovery: no worktree found for %s', child_infra)
                continue

            _log.info('Recovery: merging completed child %s', child.get('team', ''))
            try:
                from scripts.generate_commit_message import build_fallback
                message = build_fallback(child.get('team', ''), self.task)
                await squash_merge(
                    source=worktree_path,
                    target=self.session_worktree,
                    message=message,
                )
                await self.event_bus.publish(Event(
                    type=EventType.LOG,
                    data={
                        'category': 'recovery_merge',
                        'team': child.get('team', ''),
                        'heartbeat': hb_path,
                        'status': 'merged',
                    },
                    session_id=self.session_id,
                ))
            except Exception as exc:
                _log.warning('Recovery: merge failed for %s: %s', child.get('team', ''), exc)

        # Re-dispatch dead non-terminal children
        for child in scan['dead']:
            hb_path = child.get('heartbeat', '')
            child_infra = os.path.dirname(hb_path) if hb_path else ''
            worktree_path = self._find_dispatch_worktree(child_infra) if child_infra else ''
            team = child.get('team', '')

            _log.warning('Recovery: re-dispatching dead child %s', team)
            await self.event_bus.publish(Event(
                type=EventType.LOG,
                data={
                    'category': 'recovery_redispatch',
                    'team': team,
                    'heartbeat': hb_path,
                },
                session_id=self.session_id,
            ))

            if worktree_path and child_infra:
                try:
                    from orchestrator.dispatch_cli import dispatch
                    await dispatch(
                        team=team,
                        task=self.task,
                        session_worktree=self.session_worktree,
                        infra_dir=self.infra_dir,
                        project_slug=self.project_slug,
                        resume_worktree=worktree_path,
                        resume_infra=child_infra,
                    )
                except Exception as exc:
                    _log.warning('Recovery: re-dispatch failed for %s: %s', team, exc)

        # Log live children
        for child in scan['live']:
            _log.info('Recovery: live child %s — leaving alone', child.get('team', ''))

        # Compact .children to remove terminal entries
        compact_children(children_path)

    def _find_dispatch_worktree(self, child_infra: str) -> str:
        """Find the worktree path for a dispatch given its infra dir.

        Searches worktrees.json manifest for a matching session_id.
        """
        import json
        dispatch_id = os.path.basename(child_infra)

        # Try to find repo root
        try:
            from orchestrator.worktree import _run_git_output
            import asyncio
            git_common = asyncio.get_event_loop().run_until_complete(
                _run_git_output(self.session_worktree, 'rev-parse', '--path-format=absolute', '--git-common-dir')
            ).strip()
            repo_root = os.path.dirname(git_common)
        except Exception:
            return ''

        manifest_path = os.path.join(repo_root, 'worktrees.json')
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
            for entry in manifest.get('worktrees', []):
                if entry.get('session_id') == dispatch_id:
                    return entry.get('path', '')
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return ''
