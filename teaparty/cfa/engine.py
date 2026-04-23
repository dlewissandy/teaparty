"""Orchestrator engine — the CfA state loop.

Drives a CfA state machine from its current state to a terminal state
by invoking the appropriate actor at each step.  Handles cross-phase
backtracks, infrastructure failures, and review dialog loops.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import logging

from teaparty.cfa.statemachine.cfa_state import (
    CfaState,
    InvalidTransition,
    is_globally_terminal,
    is_phase_terminal,
    phase_for_state,
    save_state,
    transition,
    set_state_direct,
)

_log = logging.getLogger('teaparty')
from teaparty.learning.episodic.detect_stage import detect_stage_from_content
from teaparty.learning.episodic.retire_stage import retire_stage_entries
from teaparty.util.skill_lookup import lookup_skill
from teaparty.cfa.actors import (
    ActorContext,
    ActorResult,
    AgentRunner,
    ApprovalGate,
    InputProvider,
)
from teaparty.cfa.gates.queue import GateQueue
from teaparty.cfa.gates.escalation import EscalationListener
from teaparty.cfa.gates.intervention_listener import InterventionListener
from teaparty.workspace.worktree import commit_artifact
from teaparty.messaging.bus import Event, EventBus, EventType, InputRequest
from teaparty.cfa.gates.intervention import InterventionQueue, build_intervention_prompt
from teaparty.util.interrupt_propagation import (
    cascade_withdraw_children,
    is_backtrack,
)
from teaparty.util.context_budget import ContextBudget, build_compact_prompt
from teaparty.cfa.phase_config import PhaseConfig
from teaparty.util.cost_tracker import (
    CostTracker, ProjectCostLedger, WARNING_THRESHOLD, LIMIT_THRESHOLD,
)
from teaparty.util.role_enforcer import RoleEnforcer
from teaparty.util.scratch import ScratchModel, ScratchWriter, extract_text
from teaparty.learning.extract import (
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


PLAN_ESCALATION_STATES: frozenset[str] = frozenset()
WORK_ESCALATION_STATES: frozenset[str] = frozenset()


def _make_stream_event_handler(bus: Any, conv_id: str, agent_sender: str = 'agent'):
    """Return a callback that relays Claude CLI stream events to the message bus.

    Each event type maps to a sender value that the chat.html filter bar
    can match:

      assistant (text blocks)    → agent_sender (default: 'agent', or project lead name)
      assistant (thinking)       → 'thinking'
      assistant (tool_use block) → 'tool_use'
      tool_use (top-level)       → 'tool_use'
      tool_result (top-level)    → 'tool_result'
      user (tool_result blocks)  → 'tool_result'
      system                     → 'system'
      result                     → agent_sender

    tool_use and tool_result can appear both as content blocks within
    assistant/user events and as top-level events.  Deduplicates by
    tool_use_id to avoid showing the same tool call twice.
    """
    seen_tool_use: set[str] = set()
    seen_tool_result: set[str] = set()
    wrote_text: list[bool] = [False]  # True once any agent text has been streamed

    def _send_tool_result(content: Any) -> None:
        """Normalize tool_result content (string or block array) and send."""
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict):
                    parts.append(block.get('text', ''))
                elif isinstance(block, str):
                    parts.append(block)
            content = '\n'.join(p for p in parts if p)
        if isinstance(content, str) and content:
            bus.send(conv_id, 'tool_result', content)

    def handler(event: dict) -> None:
        etype = event.get('type', '')

        if etype == 'assistant':
            message = event.get('message', {})
            content = message.get('content', '') if isinstance(message, dict) else ''
            if isinstance(content, str) and content:
                bus.send(conv_id, agent_sender, content)
                wrote_text[0] = True
            elif isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get('type', '')
                    if btype == 'text':
                        text = block.get('text', '')
                        if text:
                            bus.send(conv_id, agent_sender, text)
                            wrote_text[0] = True
                    elif btype == 'thinking':
                        thinking = block.get('thinking', '')
                        if thinking:
                            bus.send(conv_id, 'thinking', thinking)
                    elif btype == 'tool_use':
                        tid = block.get('id', '')
                        if tid and tid not in seen_tool_use:
                            seen_tool_use.add(tid)
                            name = block.get('name', 'tool')
                            bus.send(conv_id, 'tool_use', name)

        elif etype == 'tool_use':
            tid = event.get('tool_use_id', '')
            if not tid or tid not in seen_tool_use:
                if tid:
                    seen_tool_use.add(tid)
                name = event.get('name', 'tool')
                bus.send(conv_id, 'tool_use', name)

        elif etype == 'tool_result':
            tid = event.get('tool_use_id', '')
            if not tid or tid not in seen_tool_result:
                if tid:
                    seen_tool_result.add(tid)
                _send_tool_result(event.get('content', ''))

        elif etype == 'user':
            content = event.get('message', {}).get('content', [])
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get('type') == 'tool_result':
                        tid = block.get('tool_use_id', '')
                        if not tid or tid not in seen_tool_result:
                            if tid:
                                seen_tool_result.add(tid)
                            _send_tool_result(block.get('content', ''))

        elif etype == 'system':
            subtype = event.get('subtype', '')
            session = event.get('session_id', '')
            msg = subtype
            if session:
                msg += f': {session}'
            if msg:
                bus.send(conv_id, 'system', msg)

        elif etype == 'result':
            # Only write the result event if no streaming text was captured —
            # in streaming mode the content blocks already cover the full output,
            # and a second write would produce a visible duplicate.
            result_text = event.get('result', '')
            if result_text and not wrote_text[0]:
                bus.send(conv_id, agent_sender, result_text)

    return handler


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
        escalation_modes: dict[str, str] | None = None,
        gate_queue: GateQueue | None = None,
        cost_tracker: CostTracker | None = None,
        llm_backend: str = 'claude',
        llm_caller: Any = None,
        proxy_invoker_fn: Callable[..., Awaitable[None]] | None = None,
        on_dispatch: Callable[[dict], Any] | None = None,
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
        # Management-scope .teaparty/ directory.  ``poc_root`` is the
        # repo root (from ``find_poc_root()``); session records, agent
        # configs, and everything the bridge's session walker reads
        # live inside ``{repo_root}/.teaparty/``.  Stash this once so
        # every spawn/resume/launch call uses a single source of
        # truth — forgetting to append ``/.teaparty`` to poc_root was
        # the recurring ``agent_name='unknown'`` regression trap.
        self.teaparty_home = os.path.join(poc_root, '.teaparty')
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
        self._cost_tracker = cost_tracker
        self._cost_warning_emitted = False  # Only emit once per job
        self._project_cost_warning_emitted = False
        # Hooks wired from the bridge so EscalationListener can use the
        # same proxy-skill mechanism as chat-tier AgentSession.  When
        # supplied, escalations route through the /escalation skill and
        # render as nested accordion blades.
        self._proxy_invoker_fn = proxy_invoker_fn
        self._on_dispatch = on_dispatch
        self._project_cost_ledger: ProjectCostLedger | None = (
            ProjectCostLedger(project_workdir) if cost_tracker else None
        )

        # Scratch file lifecycle (Issue #261): working memory for context budget.
        self._scratch_model = ScratchModel(job=task, phase='')
        self._scratch_writer = ScratchWriter(session_worktree)

        # Stream-to-bus callback: write agent output events to the job
        # conversation so the chat UI can display them in real time.
        self._stream_bus: Any = None
        self._stream_conv_id = ''
        bus_path = os.path.join(infra_dir, 'messages.db')
        if os.path.exists(bus_path) and project_slug and session_id:
            from teaparty.messaging.conversations import SqliteMessageBus as _StreamBus
            self._stream_bus = _StreamBus(bus_path)
            self._stream_conv_id = f'job:{project_slug}:{session_id}'

        _agent_sender = self.config.project_lead or 'agent'
        _on_stream_event = (
            _make_stream_event_handler(self._stream_bus, self._stream_conv_id, _agent_sender)
            if self._stream_bus
            else None
        )

        # Agent runners
        self._agent_runner = AgentRunner(
            stall_timeout=phase_config.stall_timeout,
            llm_backend=llm_backend,
            on_stream_event=_on_stream_event,
            llm_caller=llm_caller,
        )
        self._approval_gate = ApprovalGate(
            proxy_model_path=proxy_model_path,
            input_provider=input_provider,
            poc_root=poc_root,
            proxy_enabled=proxy_enabled,
            never_escalate=never_escalate,
            escalation_modes=escalation_modes,
            gate_queue=gate_queue,
        )

        # MCP escalation listener — bridges AskQuestion calls to proxy/human
        self._escalation_listener: EscalationListener | None = None
        # MCP intervention listener — bridges office manager tools to
        # session/dispatch operations (Issue #249)
        self._intervention_listener: InterventionListener | None = None
        self._intervention_resolver: dict[str, str] = {}
        # Bus event listener — bridges Send/Reply MCP calls to bus-mediated
        # agent dispatch (Issue #351).  Started alongside other MCP listeners.
        self._bus_event_listener: Any | None = None  # BusEventListener
        # Fan-in synchronization: set when the turn loop is waiting for all
        # dispatched workers to complete; cleared and set by _bus_reinvoke_agent.
        self._fan_in_event: asyncio.Event | None = None
        # Context ID of the orchestrator's own bus context record.
        # Workers spawned via Send have this as their parent_context_id.
        self._bus_lead_context_id: str = ''

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

        # In-flight child tasks keyed by child session_id — same shape
        # and semantics as chat tier's AgentSession._tasks_by_child
        # (issue #422).  Aliased onto the BusEventListener on start so
        # the shared close_fn reads this dict through the listener.
        self._tasks_by_child: dict[str, asyncio.Task] = {}

        # MCP routes bundle installed at every launch in this engine's
        # tree (lead phase, dispatched children via Send, resumed
        # children via --resume).  Built right after the BusEventListener
        # starts, used by launch() to register handler routes per
        # agent_name before the subprocess spawns.
        self._mcp_routes = None

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

        # Start the MCP escalation listener so agents can call AskQuestion.
        # Single route: every agent's AskQuestion spawns a proxy child
        # session via the /escalation skill, same mechanism chat-tier
        # uses.  The proxy is a management-level participant — its
        # session always lives under management scope, regardless of
        # who asked.  The caller's dispatcher session (project or
        # management) records the proxy child in its conversation_map;
        # the dispatch-tree walker crosses scopes to resolve it.
        if self.input_provider:
            from teaparty.runners.launcher import (
                create_session as _create_session,
                load_session as _load_session,
            )
            ask_question_bus_db = os.path.join(self.infra_dir, 'messages.db')
            ask_question_conv_id = f'escalation:{self.session_id}'
            self._ask_question_bus_db = ask_question_bus_db
            self._ask_question_conv_id = ask_question_conv_id

            # The CfA job's coordination state lives at the bridge's
            # management scope — the job is orchestrated by the bridge,
            # not by the target project.  The project itself owns its
            # work under .teaparty/jobs/{job}/; the launcher.Session
            # created here is only a conversation_map holder for the
            # dispatch-tree walker.  Putting it at management scope
            # means the walker's first candidate (management/sessions)
            # always finds it — no registry lookup or project-scope
            # handling needed, including for projects not registered
            # in the bridge's teaparty.yaml.
            dispatcher = _load_session(
                agent_name=self.config.project_lead or 'project-lead',
                scope='management',
                teaparty_home=self.teaparty_home,
                session_id=self.session_id,
            )
            if dispatcher is None:
                dispatcher = _create_session(
                    agent_name=self.config.project_lead or 'project-lead',
                    scope='management',
                    teaparty_home=self.teaparty_home,
                    session_id=self.session_id,
                )
            # Stash the dispatcher session so the Send spawn_fn adapter
            # (registered in _run_phase) can record_child_session and emit
            # dispatch_started events against it — same wiring chat-tier
            # spawn_fn uses to surface a dispatched child as an accordion
            # node.
            self._dispatcher_session = dispatcher

            # The proxy's home — where the listener creates its session
            # and where the proxy agent.md resolves.  Same management
            # home; same invariant.
            proxy_teaparty_home = self.teaparty_home

            self._escalation_listener = EscalationListener(
                event_bus=self.event_bus,
                input_provider=self.input_provider,
                bus_db_path=ask_question_bus_db,
                conv_id=ask_question_conv_id,
                session_id=self.session_id,
                proxy_model_path=self.proxy_model_path,
                project_slug=self.project_slug,
                cfa_state=self.cfa.state,
                session_worktree=self.session_worktree,
                infra_dir=self.infra_dir,
                team=self.team_override,
                proxy_invoker_fn=self._proxy_invoker_fn,
                on_dispatch=self._on_dispatch,
                dispatcher_session=dispatcher,
                # The dispatcher's bus conv_id is the JOB conv
                # ``job:{project_slug}:{session_id}`` — what the job
                # page's dispatch-tree walker starts at.  Without this,
                # the escalation attaches under ``dispatch:{sid}`` and
                # never appears in the accordion.
                dispatcher_conv_id=self._stream_conv_id,
                teaparty_home=proxy_teaparty_home,
                scope='management',
            )
            await self._escalation_listener.start()

            # Start the intervention listener so office manager tools
            # (WithdrawSession, PauseDispatch, etc.) can execute.  The
            # resolver is a mutable dict — the orchestrator adds entries
            # as sessions/dispatches start.  Seeded with this session.
            # Issue #249.
            self._intervention_resolver[self.session_id] = self.infra_dir
            intervention_conv_id = f'intervention:{self.session_id}'
            self._intervention_listener = InterventionListener(
                resolver=self._intervention_resolver,
                bus_db_path=ask_question_bus_db,
                conv_id=intervention_conv_id,
                on_withdraw=self._on_external_withdraw,
            )
            await self._intervention_listener.start()

            # Start the bus event listener so agents can use Send/Reply for
            # bus-mediated agent-to-agent dispatch (Issue #351, #358).
            from teaparty.messaging.listener import BusEventListener  # noqa: PLC0415
            bus_db_path = os.path.join(self.infra_dir, 'messages.db')
            # Project lead agent ID: {project}/lead per routing.md Agent Identity spec
            lead_agent_id = f'{self.project_slug}/lead' if self.project_slug else 'om'
            # Create the orchestrator's own context record so workers spawned
            # via Send have a valid parent_context_id to decrement pending_count against.
            self._bus_lead_context_id = (
                f'agent:{lead_agent_id}:lead:{self.session_id}'
                if self.session_id
                else ''
            )
            if self._bus_lead_context_id:
                from teaparty.messaging.conversations import SqliteMessageBus  # noqa: PLC0415
                _bus = SqliteMessageBus(bus_db_path)
                try:
                    _bus.create_agent_context(
                        self._bus_lead_context_id,
                        initiator_agent_id=lead_agent_id,
                        recipient_agent_id=lead_agent_id,
                    )
                except Exception:
                    pass  # Already exists from prior run — idempotent
                finally:
                    _bus.close()
            self._bus_event_listener = BusEventListener(
                bus_db_path=bus_db_path,
                initiator_agent_id=lead_agent_id,
                current_context_id=self._bus_lead_context_id,
                spawn_fn=self._bus_spawn_agent,
                resume_fn=self._bus_resume_agent,
                reply_fn=self._bus_inject_reply,
                reinvoke_fn=self._bus_reinvoke_agent,
                dispatcher=self._build_bus_dispatcher(),
            )
            # Alias the engine's tasks_by_child onto the listener so the
            # shared close_fn (workspace/close_conversation.py::build_close_fn)
            # reads the same dict — issue #422.  Same mechanism chat tier uses.
            self._bus_event_listener.tasks_by_child = self._tasks_by_child
            await self._bus_event_listener.start()

            # Build the MCPRoutes bundle this engine installs at every
            # launch in its tree — the phase lead, dispatched children,
            # resumed children.  Same pattern chat tier uses in
            # AgentSession._ensure_bus_listener (issue #422).  The
            # spawn_fn in the bundle is the adapter that records child
            # sessions into the dispatcher's conversation_map and emits
            # dispatch_started events; close_fn is the tier-neutral
            # function that merges the subteam's worktree back and
            # emits dispatch_completed per removed session.
            from teaparty.mcp.registry import MCPRoutes, register_agent_mcp_routes
            from teaparty.workspace.close_conversation import build_close_fn
            # The CfA engine's dispatch bus — same db the MCPRoutes
            # spawn_fn writes to and the accordion walker reads from
            # (#422).  Passing it here is what makes close_fn walk the
            # bus's children_of instead of session metadata on disk.
            from teaparty.messaging.conversations import (
                SqliteMessageBus as _CloseBus,
            )
            _close_bus = _CloseBus(self._bus_event_listener.bus_db_path)
            close_fn = build_close_fn(
                dispatch_session=self._dispatcher_session,
                teaparty_home=self.teaparty_home,
                scope='management',
                tasks_by_child=self._tasks_by_child,
                on_dispatch=self._on_dispatch,
                agent_name=lead_agent_id,
                bus=_close_bus,
            )
            self._mcp_routes = MCPRoutes(
                spawn_fn=self._bus_spawn_agent,
                close_fn=close_fn,
                escalation_bus_db=self._ask_question_bus_db,
                escalation_conv_id=self._ask_question_conv_id,
            )
            # Install routes for the lead itself.  Dispatched children
            # are registered by launch() when their subprocess spawns.
            register_agent_mcp_routes(
                self.config.project_lead or 'project-lead',
                self._mcp_routes,
            )

        # Subscribe to stream events for scratch file extraction (Issue #261).
        self.event_bus.subscribe(self._on_scratch_event)

        try:
            return await self._run_loop()
        finally:
            self.event_bus.unsubscribe(self._on_scratch_event)
            self._scratch_writer.cleanup()
            if self._escalation_listener:
                await self._escalation_listener.stop()
            if self._intervention_listener:
                await self._intervention_listener.stop()
            if self._bus_event_listener:
                await self._bus_event_listener.stop()

    def _build_bus_dispatcher(self) -> object | None:
        """Build a BusDispatcher from project workgroup config, or None if not available.

        Attempts to load workgroup definitions from project.yaml and derive the
        routing table.  Returns None (no enforcement) when config is missing — this
        is expected during bootstrap before workgroup YAML is present.
        """
        from teaparty.messaging.dispatcher import BusDispatcher, RoutingTable
        from teaparty.config.config_reader import resolve_workgroups, load_project_team

        if not self.project_dir:
            return None
        try:
            proj = load_project_team(self.project_dir)
        except (FileNotFoundError, OSError):
            return None

        try:
            workgroups = resolve_workgroups(
                proj.workgroups,
                project_dir=self.project_dir,
                teaparty_home=self.teaparty_home,
            )
        except Exception:
            return None

        if not workgroups:
            return None

        wg_dicts = [
            {'name': wg.name, 'lead': wg.lead, 'agents': [{'role': a} for a in wg.members_agents]}
            for wg in workgroups
        ]
        project_name = self.project_slug or os.path.basename(self.project_dir)
        routing_table = RoutingTable.from_workgroups(wg_dicts, project_name=project_name)
        return BusDispatcher(routing_table)

    async def _bus_spawn_agent(self, member: str, composite: str, context_id: str) -> tuple[str, str, str]:
        """Spawn a recipient agent for bus-mediated dispatch (#351, #422).

        Follows the same shape as chat tier's ``spawn_fn``: set up the
        child's session record and worktree synchronously, hand off to
        ``BusEventListener.schedule_child_task`` which records the child
        in the dispatcher's conversation_map, emits ``dispatch_started``,
        creates the asyncio.Task that runs the subprocess, and registers
        the task in ``tasks_by_child``.  Send returns immediately; the
        child runs concurrently with siblings and is cancelled cleanly
        by the shared ``close_fn``.

        Returns ``(child_session.id, worktree_path, refusal_reason)`` —
        the session-record id, so ``dispatch:{sid}`` maps 1:1 to the
        on-disk session directory the close_conversation walker reads.
        """
        from teaparty.runners.launcher import (
            launch as _launch,
            create_session as _create_session,
            _save_session_metadata as _save_meta,
        )
        from teaparty.workspace.worktree import (
            create_subchat_worktree, current_branch_of, head_commit_of,
        )

        # Session record first so the worktree lives under it (1:1).
        child_session = _create_session(
            agent_name=member, scope='management',
            teaparty_home=self.teaparty_home,
        )
        worktree_path = os.path.join(child_session.path, 'worktree')
        session_branch = f'session/{child_session.id}'

        # Register the dispatch in the bus — the single source of truth
        # for tree / lead / parent (issue #422).  The accordion walker
        # reads this record; no disk lookup for the blade caption.
        # Parent conv_id comes from the MCP caller's session_id contextvar
        # (set by the MCP middleware from the URL), falling back to the
        # dispatcher session for non-MCP callers (tests, etc.).
        from teaparty.mcp.registry import (
            current_session_id as _current_session_var,
        )
        from teaparty.messaging.conversations import (
            ConversationState as _ConvState,
            ConversationType as _ConvType,
            SqliteMessageBus as _Bus,
        )
        caller_sid = _current_session_var.get('')
        if not caller_sid and self._dispatcher_session is not None:
            caller_sid = self._dispatcher_session.id
        parent_conv_id = f'dispatch:{caller_sid}' if caller_sid else ''
        if self._bus_event_listener is not None and self._bus_event_listener.bus_db_path:
            _bus = _Bus(self._bus_event_listener.bus_db_path)
            try:
                _bus.create_conversation(
                    _ConvType.DISPATCH, child_session.id,
                    agent_name=member,
                    parent_conversation_id=parent_conv_id,
                    request_id=context_id,
                    project_slug=self.project_slug or '',
                    state=_ConvState.ACTIVE,
                )
            finally:
                _bus.close()

        # Fork source + merge target = the lead's session worktree, falling
        # back to the project repo root for bootstrap paths that don't yet
        # have a session worktree.  Matches chat tier's same-repo branch.
        source_repo = self.session_worktree or self.project_workdir
        merge_target_worktree = source_repo
        merge_target_repo = self.project_workdir
        try:
            source_ref = await head_commit_of(source_repo) or 'HEAD'
        except Exception:
            source_ref = 'HEAD'
        try:
            merge_target_branch = await current_branch_of(source_repo)
        except Exception:
            merge_target_branch = ''

        try:
            await create_subchat_worktree(
                source_repo=source_repo,
                source_ref=source_ref,
                dest_path=worktree_path,
                branch_name=session_branch,
                parent_worktree=source_repo,
            )
        except Exception:
            _log.exception(
                '_bus_spawn_agent: create_subchat_worktree failed for %s',
                member,
            )
            return ('', '', 'worktree_failed')

        child_session.launch_cwd = worktree_path
        child_session.worktree_path = worktree_path
        child_session.worktree_branch = session_branch
        child_session.merge_target_repo = merge_target_repo
        child_session.merge_target_branch = merge_target_branch
        child_session.merge_target_worktree = merge_target_worktree
        child_session.parent_session_id = (
            self._dispatcher_session.id if self._dispatcher_session else ''
        )
        child_session.initial_message = composite
        _save_meta(child_session)

        # Child bus listener for recipients with a sub-roster — scheduled
        # for the lifetime of the child's task.
        child_listener = None
        try:
            from teaparty.config.roster import has_sub_roster
            if has_sub_roster(member, self.teaparty_home,
                              project_dir=self.project_workdir):
                child_listener, _ = await self._make_child_listener(
                    member, context_id, worktree_path,
                )
        except Exception:
            _log.debug(
                'Sub-roster check failed for %s — spawning as leaf worker',
                member, exc_info=True,
            )

        mcp_port = int(os.environ.get('TEAPARTY_BRIDGE_PORT', '9000'))

        async def _run_child() -> str:
            try:
                result = await _launch(
                    agent_name=member,
                    message=composite,
                    scope='management',
                    teaparty_home=self.teaparty_home,
                    worktree=worktree_path,
                    mcp_port=mcp_port,
                    session_id=child_session.id,
                    mcp_routes=self._mcp_routes,
                )
                return getattr(result, 'response_text', '') or ''
            except Exception:
                _log.exception(
                    '_bus_spawn_agent task failed for %s', member,
                )
                return ''
            finally:
                if child_listener:
                    try:
                        await child_listener.stop()
                    except Exception:
                        _log.debug(
                            'child_listener.stop raised', exc_info=True,
                        )

        # Shared with chat tier (#422): same helper records the child,
        # emits dispatch_started, creates + registers the task.
        self._bus_event_listener.schedule_child_task(
            child_session_id=child_session.id,
            launch_coro=_run_child(),
            dispatcher_session=self._dispatcher_session,
            context_id=context_id,
            agent_name=member,
            on_dispatch=self._on_dispatch,
        )

        return (child_session.id, worktree_path, '')

    async def _make_child_listener(
        self,
        member: str,
        context_id: str,
        agent_dir: str,
    ) -> tuple[Any, dict]:
        """Create a child BusEventListener for an agent with a sub-roster.

        Returns (listener, mcp_config) where mcp_config contains the child
        listener's socket paths for the spawned agent's MCP server.
        """
        import sys
        from teaparty.messaging.listener import BusEventListener
        from teaparty.runners.launcher import launch as _launch
        from teaparty.config.roster import (
            derive_project_roster,
            derive_workgroup_roster,
            agent_id_map as build_agent_id_map,
        )
        from teaparty.messaging.dispatcher import BusDispatcher, RoutingTable

        bus_db_path = os.path.join(self.infra_dir, 'messages.db')

        # Determine the child's agent_id
        project_name = self.project_slug or os.path.basename(self.project_workdir)
        if member.endswith('-lead'):
            child_agent_id = f'{member[:-5]}/lead'
        else:
            child_agent_id = f'{project_name}/{member}'

        child_context_id = f'agent:{child_agent_id}:{context_id}'

        # Build child's routing table from its roster
        # For now, derive roster based on the member's level
        child_roster: dict = {}
        child_id_map: dict[str, str] = {}
        try:
            child_roster = derive_project_roster(
                self.project_workdir, self.teaparty_home,
            )
            child_id_map = build_agent_id_map(
                child_roster, 'project', project_name=project_name,
            )
        except Exception:
            _log.debug('Project roster derivation failed for %s', member, exc_info=True)

        if child_roster and child_id_map:
            routing_table = RoutingTable()
            for name in child_roster:
                agent_id = child_id_map.get(name, name)
                routing_table.add_pair(child_agent_id, agent_id)
                routing_table.add_pair(agent_id, child_agent_id)
            dispatcher = BusDispatcher(routing_table)
        else:
            dispatcher = None

        # Build child spawn/resume/reinvoke closures
        async def child_spawn_fn(
            child_member: str, composite: str, child_ctx_id: str,
        ) -> tuple[str, str, str]:
            from teaparty.runners.launcher import (
                create_session as _cs,
                _save_session_metadata as _save_meta,
            )
            from teaparty.workspace.worktree import (
                create_subchat_worktree, current_branch_of, head_commit_of,
            )
            # Session = worktree (1:1).  Set merge metadata like
            # _bus_spawn_agent does so close_fn can squash-merge
            # recursive subteam work back into the lead (#422).
            child_session = _cs(
                agent_name=child_member, scope='management',
                teaparty_home=self.teaparty_home,
            )
            child_wt = os.path.join(child_session.path, 'worktree')
            session_branch = f'session/{child_session.id}'
            source_repo = self.session_worktree or self.project_workdir
            try:
                source_ref = await head_commit_of(source_repo) or 'HEAD'
            except Exception:
                source_ref = 'HEAD'
            try:
                target_branch = await current_branch_of(source_repo)
            except Exception:
                target_branch = ''
            try:
                await create_subchat_worktree(
                    source_repo=source_repo,
                    source_ref=source_ref,
                    dest_path=child_wt,
                    branch_name=session_branch,
                    parent_worktree=source_repo,
                )
            except Exception:
                _log.exception(
                    'child_spawn_fn: create_subchat_worktree failed for %s',
                    child_member,
                )
                return ('', '', 'worktree_failed')
            child_session.launch_cwd = child_wt
            child_session.worktree_path = child_wt
            child_session.worktree_branch = session_branch
            child_session.merge_target_repo = self.project_workdir
            child_session.merge_target_branch = target_branch
            child_session.merge_target_worktree = source_repo
            child_session.parent_session_id = (
                self._dispatcher_session.id if self._dispatcher_session else ''
            )
            child_session.initial_message = composite
            _save_meta(child_session)

            mcp_port = int(os.environ.get('TEAPARTY_BRIDGE_PORT', '9000'))
            await _launch(
                agent_name=child_member,
                message=composite,
                scope='management',
                teaparty_home=self.teaparty_home,
                worktree=child_wt,
                mcp_port=mcp_port,
                session_id=child_session.id,
                mcp_routes=self._mcp_routes,
            )
            return (child_session.id, child_wt, '')

        async def child_resume_fn(
            child_member: str, composite: str, session_id: str, child_ctx_id: str,
        ) -> str:
            from teaparty.messaging.conversations import SqliteMessageBus
            child_agent_dir = ''
            if os.path.exists(bus_db_path) and child_ctx_id:
                bus = SqliteMessageBus(bus_db_path)
                try:
                    ctx = bus.get_agent_context(child_ctx_id)
                    if ctx:
                        child_agent_dir = ctx.get('agent_worktree_path', '')
                finally:
                    bus.close()
            if not child_agent_dir:
                child_agent_dir = self.project_workdir
            mcp_port = int(os.environ.get('TEAPARTY_BRIDGE_PORT', '9000'))
            result = await _launch(
                agent_name=child_member,
                message=composite,
                scope='management',
                teaparty_home=self.teaparty_home,
                worktree=child_agent_dir,
                resume_session=session_id,
                mcp_port=mcp_port,
                mcp_routes=self._mcp_routes,
            )
            return result.session_id

        async def child_reinvoke_fn(
            child_ctx_id: str, session_id: str, message: str,
        ) -> None:
            _log.debug(
                'Child reinvoke for context %s — fan-in complete',
                child_ctx_id,
            )

        listener = BusEventListener(
            bus_db_path=bus_db_path,
            initiator_agent_id=child_agent_id,
            current_context_id=child_context_id,
            spawn_fn=child_spawn_fn,
            resume_fn=child_resume_fn,
            reinvoke_fn=child_reinvoke_fn,
            dispatcher=dispatcher,
        )

        await listener.start()

        # Build MCP config for the child; Send/Close now go through the
        # dispatch bus (DISPATCH_BUS_PATH + DISPATCH_CONV_ID), not sockets.
        venv_python = sys.executable
        mcp_config = {
            'ask-question': {
                'command': venv_python,
                'args': ['-m', 'teaparty.mcp.server.main'],
                'env': {
                    'AGENT_ID': child_agent_id,
                    'CONTEXT_ID': child_context_id,
                    'BUS_DB_PATH': bus_db_path,
                },
            },
        }

        return (listener, mcp_config)

    async def _bus_resume_agent(
        self, member: str, composite: str, session_id: str, context_id: str,
    ) -> str:
        """Resume a recipient agent for a follow-up to an open conversation (Issue #383).

        Injects the composite into the recipient's existing session file and
        re-invokes via --resume session_id in the agent's original spawn worktree.
        The agent receives the follow-up message in its conversation history without
        starting a fresh session.

        Returns the session_id (unchanged — --resume reuses the existing session).
        """
        from teaparty.runners.launcher import launch as _launch
        from teaparty.messaging.conversations import SqliteMessageBus

        if not session_id:
            _log.warning(
                '_bus_resume_agent called without session_id for member %s; '
                'cannot resume — no-op',
                member,
            )
            return ''

        agent_dir: str = ''
        bus_db_path = os.path.join(self.infra_dir, 'messages.db')
        if os.path.exists(bus_db_path) and context_id:
            bus = SqliteMessageBus(bus_db_path)
            try:
                ctx = bus.get_agent_context(context_id)
                if ctx:
                    agent_dir = ctx.get('agent_worktree_path', '')
            finally:
                bus.close()

        if not agent_dir:
            _log.warning(
                '_bus_resume_agent: no stored worktree for context %s; '
                'falling back to session worktree',
                context_id,
            )
            agent_dir = self.session_worktree or self.project_workdir

        mcp_port = int(os.environ.get('TEAPARTY_BRIDGE_PORT', '9000'))
        result = await _launch(
            agent_name=member,
            message=composite,
            scope='management',
            teaparty_home=self.teaparty_home,
            worktree=agent_dir,
            resume_session=session_id,
            mcp_port=mcp_port,
            mcp_routes=self._mcp_routes,
        )
        return result.session_id

    async def _bus_inject_reply(
        self, context_id: str, session_id: str, message: str,
    ) -> None:
        """Inject a worker reply into the lead's conversation history.

        Called by BusEventListener for EVERY Reply, including those from
        workers that complete before the final one (fan-out N > 1).  This
        ensures all worker replies are in the lead's JSONL history before
        _await_fan_in_and_reinvoke triggers the --resume invocation.

        session_id is the PARENT context's session_id (the lead's latest
        claude session ID), kept current by _update_lead_bus_session.
        """
        if session_id and self.session_worktree:
            cwd = self.session_worktree
            project_hash = cwd.replace('/', '-')
            lead_session_file = os.path.join(
                os.path.expanduser('~'), '.claude', 'projects',
                project_hash, f'{session_id}.jsonl',
            )
            from teaparty.messaging.conversations import inject_composite_into_history  # noqa: PLC0415
            inject_composite_into_history(lead_session_file, message, session_id, cwd)

    async def _bus_reinvoke_agent(
        self, context_id: str, session_id: str, message: str,
    ) -> None:
        """Signal fan-in completion when all dispatched workers have replied.

        Called by BusEventListener (via _locked_reinvoke) when pending_count
        reaches zero — all workers have replied.  By this point all replies are
        already in the lead's history (injected by _bus_inject_reply on each
        individual Reply).  Sets _fan_in_event to unblock
        _await_fan_in_and_reinvoke, which resumes the lead via --resume.
        """
        if self._fan_in_event:
            self._fan_in_event.set()

    def _has_open_agent_contexts(self) -> bool:
        """True if any bus agent contexts are still open (workers not yet replied)."""
        if not self._bus_event_listener:
            return False
        from teaparty.messaging.conversations import SqliteMessageBus  # noqa: PLC0415
        bus_db_path = os.path.join(self.infra_dir, 'messages.db')
        if not os.path.exists(bus_db_path):
            return False
        bus = SqliteMessageBus(bus_db_path)
        try:
            contexts = bus.open_agent_contexts()
            # Exclude the lead's own context — it's always open and is not a worker.
            return any(
                c['context_id'] != self._bus_lead_context_id
                for c in contexts
            )
        finally:
            bus.close()

    def _update_lead_bus_session(self, session_id: str) -> None:
        """Update the orchestrator's bus context record with the latest lead session_id.

        Called after each agent turn so BusEventListener.trigger_reply (run at
        child subprocess exit) can retrieve the session_id needed to call
        reinvoke_fn when all workers have replied (Issue #358).
        """
        if not self._bus_lead_context_id:
            return
        from teaparty.messaging.conversations import SqliteMessageBus  # noqa: PLC0415
        bus_db_path = os.path.join(self.infra_dir, 'messages.db')
        if not os.path.exists(bus_db_path):
            return
        bus = SqliteMessageBus(bus_db_path)
        try:
            bus.set_agent_context_session_id(self._bus_lead_context_id, session_id)
        finally:
            bus.close()

    async def _await_fan_in_and_reinvoke(
        self,
        spec: 'PhaseSpec',
        phase_name: str,
        phase_start_time: float,
    ) -> 'ActorResult':
        """Block the lead until all dispatched workers reply, then resume it.

        Fan-in is a framework-level turn-boundary concern, not a state-machine
        transition.  When the lead's turn completes with open worker contexts
        on the bus, this coroutine waits for BusEventListener.trigger_reply
        to signal _fan_in_event (fired when every open child context has
        replied), then re-invokes the lead via --resume so it can synthesize
        the workers' replies before advancing the CfA.
        """
        self._fan_in_event = asyncio.Event()
        _log.info('Fan-in wait: blocking until all dispatched workers reply')
        await self._fan_in_event.wait()
        self._fan_in_event = None
        _log.info('Fan-in complete: resuming lead via --resume for synthesis')
        return await self._invoke_actor(spec, phase_name, phase_start_time)

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
                return self._make_result('DONE')

            # Phase 2: Planning (skip if execute-only)
            if not self.execute_only:
                # System 1 fast path: if a learned skill covers this task,
                # pre-seed PLAN.md with the skill template so the planning
                # skill runs ALIGN instead of DRAFT on its first turn and
                # proposes the skill-as-plan via its own ASSERT dialog.
                # If the human corrects it during that dialog, the correction
                # flows through the skill's REVISE step (System 2 fallback).
                await self._try_skill_lookup()

                result = await self._run_phase('planning')

                # Skill self-correction (Issue #142): after planning
                # completes, check if the plan was corrected from the
                # original skill template.  Handles both human correction
                # during the planning skill's ASSERT/REVISE dialog and
                # System 2 fallback after backtrack.
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
                    return self._make_result('DONE')

                # Prospective learning: generate premortem before execution (Issue #199)
                self._write_premortem()
            # else: CfA is already at EXECUTE (set_state_direct in Session.run)

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
                    self.execute_only = False  # must re-plan after backtracking to intent
                    continue
            if result.backtrack_to == 'planning':
                self._record_dead_end('execution', 'backtracked to planning', result.backtrack_feedback)
                self._mark_false_positives('execution backtracked to planning')
                if self.suppress_backtracks:
                    _log.info('Suppressing backtrack to planning (suppress_backtracks=True)')
                else:
                    self.skip_intent = True
                    self.execute_only = False  # must re-plan; no valid plan after backtrack
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

    async def _try_skill_lookup(self) -> bool:
        """System 1 fast path: check the skill library for a matching skill.

        If a match is found, pre-seeds PLAN.md with the skill template so
        the planning skill runs ALIGN rather than DRAFT on its first turn
        and proposes the skill-as-plan via its own ASSERT dialog with the
        human (routed through the proxy). Returns True on match.

        If no match or any error: returns False (the planning skill cold-
        starts in DRAFT).

        If the human corrects the skill-as-plan during the skill's
        ASSERT/REVISE dialog, _check_skill_correction archives the
        correction as a candidate (Issue #142).
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

        # Read the approved intent from the session worktree
        intent = ''
        intent_path = os.path.join(self.session_worktree, 'INTENT.md')
        try:
            with open(intent_path) as f:
                intent = f.read()
        except OSError:
            pass

        # Build embed_fn from memory_indexer if available (Issue #215).
        embed_fn = None
        try:
            from teaparty.learning.episodic.indexer import try_embed, detect_provider
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

        # Write the skill template as PLAN.md to the session worktree
        plan_path = os.path.join(self.session_worktree, 'PLAN.md')
        with open(plan_path, 'w') as f:
            f.write(match.template)

        # Track which skill was used (Issue #142 — skill self-correction).
        # Store the original template so we can detect corrections later:
        # after planning completes, if PLAN.md differs from the template,
        # the plan was corrected (by the human during the planning skill's
        # ASSERT/REVISE dialog, or by System 2 after backtrack) and should
        # be archived as a correction candidate.
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

        # Pre-seed PLAN.md with the matched skill template; the planning
        # skill will pick it up in ALIGN on the next turn and propose it
        # for approval via its own ASSERT dialog, rather than bypassing
        # the planning phase entirely.
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

        # MCP routes (spawn_fn, close_fn, escalation route) are
        # registered by launch() for each agent it spawns — the phase
        # lead here, every Send-dispatched child inside this engine's
        # tree.  The bundle is built once in Orchestrator.run (issue
        # #422) and threaded through every launch call site.

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

            # Check for phase exit (e.g., INTENT → PLAN, PLAN → EXECUTE)
            current_phase = phase_for_state(self.cfa.state)
            if current_phase != phase_name:
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

            # Fan-in wait: if the lead dispatched workers via Send, hold the
            # CfA transition until all workers have replied.  The lead is then
            # re-invoked (--resume) so it can synthesize before the gate sees it.
            # Checked BEFORE _transition so the CfA state does not advance until
            # the synthesis turn returns.
            if (actor_result.action != 'failed'
                    and not is_globally_terminal(self.cfa.state)
                    and self._has_open_agent_contexts()):
                actor_result = await self._await_fan_in_and_reinvoke(
                    spec, phase_name, phase_start_time,
                )

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
            mcp_routes=self._mcp_routes,
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

    def _on_external_withdraw(self, session_id: str) -> None:
        """Called by InterventionListener when a withdrawal succeeds.

        Updates the in-memory CfA state so the engine's turn-boundary
        check sees WITHDRAWN and exits.  The file has already been
        written by withdraw_session().  Issue #386.
        """
        _log.info('External withdrawal received for session %s', session_id)
        self.cfa = set_state_direct(self.cfa, 'WITHDRAWN')

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
            # Keep the orchestrator's bus context record up to date so
            # BusEventListener.trigger_reply (run at child subprocess exit)
            # can retrieve the latest session_id when all workers reply
            # (Issue #358).
            self._update_lead_bus_session(claude_sid)

        # Persist and emit
        state_path = os.path.join(self.infra_dir, '.cfa-state.json')
        save_state(self.cfa, state_path)

        # Telemetry — phase_changed on every transition, phase_backtrack
        # when the machine counted one (Issue #405).
        try:
            from teaparty.telemetry import record_event
            from teaparty.telemetry import events as _telem_events
            _scope = self.project_slug or 'management'
            old_phase = phase_for_state(old_state)
            # Save the previous phase-entry timestamp before overwriting —
            # the backtrack cost query needs the window from when the prior
            # phase was entered until now.
            _prev_phase_entry = getattr(self, '_phase_entry_ts', 0.0)
            self._phase_entry_ts = time.time()
            record_event(
                _telem_events.PHASE_CHANGED,
                scope=_scope,
                agent_name=None,
                session_id=self.session_id,
                data={
                    'old_state':     old_state,
                    'new_state':     self.cfa.state,
                    'old_phase':     old_phase,
                    'new_phase':     self.cfa.phase,
                    'action':        action,
                    'actor':         self.cfa.actor,
                    'state_machine': 'cfa',
                },
            )
            # The CfA machine increments backtrack_count when a backtrack
            # edge fires — emit phase_backtrack for those transitions.
            if self.cfa.backtrack_count > (
                getattr(self, '_last_backtrack_count', 0)
            ):
                # Estimate cost being discarded by summing turn_complete
                # costs for this session recorded since the backtracked
                # phase was entered. Scoped to session_id so concurrent
                # sessions in the same scope are excluded.
                _discarded = 0.0
                try:
                    from teaparty.telemetry import query as _tq
                    _cost_events = _tq.query_events(
                        event_type=_telem_events.TURN_COMPLETE,
                        scope=_scope,
                        session=self.session_id,
                        start_ts=_prev_phase_entry,
                        end_ts=time.time(),
                    )
                    _discarded = round(sum(
                        float(e.data.get('cost_usd', 0.0) or 0.0)
                        for e in _cost_events
                    ), 6)
                except Exception:
                    pass

                record_event(
                    _telem_events.PHASE_BACKTRACK,
                    scope=_scope,
                    session_id=self.session_id,
                    data={
                        'kind':            f'{old_phase}_to_{self.cfa.phase}',
                        'triggering_gate': old_state,
                        'action':          action,
                        'backtrack_count': self.cfa.backtrack_count,
                        'cost_of_work_being_discarded': _discarded,
                    },
                )
                self._last_backtrack_count = self.cfa.backtrack_count
        except Exception:
            _log.debug('telemetry emit failed in _transition', exc_info=True)

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
        if old_state == 'INTENT' and action == 'approve':
            self._detect_and_retire_stage()

    async def _commit_artifacts(self, old_state: str, action: str) -> None:
        """Auto-commit deliverables to the session worktree after writes.

        Commits on every EXECUTE transition so per-dispatch deliverables are
        checkpointed as they land. INTENT.md and PLAN.md live in the worktree
        root but are gitignored so they never reach main.
        """
        wt = self.session_worktree
        if not wt:
            return

        try:
            if old_state == 'EXECUTE':
                await commit_artifact(wt, ['.'], f'Execution: {action}')
        except Exception as exc:
            _log.warning('Artifact commit failed (non-fatal): %s', exc)

    def _detect_and_retire_stage(self) -> None:
        """Detect the project stage from INTENT.md and retire old-stage memory."""
        from pathlib import Path

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
                    from teaparty.learning.episodic.entry import (
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
            artifact_path = os.path.join(self.session_worktree, artifact_name)
            if os.path.isfile(artifact_path):
                try:
                    artifact_content = _Path(artifact_path).read_text(errors='replace')
                except OSError:
                    pass

        summary = artifact_content if artifact_content.strip() else (
            f'{phase_name} phase completed at {self.cfa.state}'
        )

        try:
            from teaparty.learning.extract import write_assumption_checkpoint
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
            from teaparty.learning.extract import write_premortem
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
            from teaparty.cfa.phase_config import PhaseSpec
            return PhaseSpec(
                name=base.name,
                agent_file=team.agent_file,
                lead=team.lead,
                permission_mode=perm,
                stream_file=base.stream_file,
                artifact=base.artifact,
                approval_state=base.approval_state,
            )

        base = self.config.resolve_phase(phase_name)

        # --flat: swap the project team for a flat team where the lead
        # recruits agents dynamically via the Agent tool.
        # Only affects phases that use uber-team.json (planning, execution).
        # Use the already-resolved base.lead so the project lead from project.yaml
        # is preserved rather than re-hardcoding 'project-lead' (Issue #408).
        if self.flat and base.agent_file == 'uber':
            from teaparty.cfa.phase_config import PhaseSpec
            return PhaseSpec(
                name=base.name,
                agent_file='flat',
                lead=base.lead,
                permission_mode=base.permission_mode,
                stream_file=base.stream_file,
                artifact=base.artifact,
                approval_state=base.approval_state,
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
        from teaparty.proxy.approval_gate import COLD_START_THRESHOLD

        base_task = ''
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
                base_task = '\n\n'.join(parts)
        elif phase_name == 'planning':
            intent_path = os.path.join(self.session_worktree, 'INTENT.md')
            try:
                with open(intent_path) as f:
                    base_task = f.read()
            except OSError:
                pass

        if not base_task:
            # Intent phase, or artifacts not yet written
            base_task = self.task or self.project_slug

        # Prepend CfA phase framing.  agent.md is role-only; this layer
        # supplies deliverable, boundary, and re-entry rule per phase.
        # Working scope — same for every phase. Your current directory is a
        # self-contained worktree that holds everything this phase needs.
        # Absolute paths outside cwd are outside the sandbox and will fail.
        scope = (
            '--- Working scope ---\n'
            'Your current directory is the worktree for this job. Every file '
            'this phase reads or writes lives here. Use relative paths (./file) '
            'for all file operations. Do not reference paths outside your cwd — '
            'they are outside your allowed scope and attempting to access them '
            'will fail.\n'
            '--- end ---\n\n'
        )

        if phase_name == 'intent':
            base_task = (
                scope
                + '--- CfA: Intent Alignment Phase ---\n'
                'Run the /intent-alignment skill to completion. Do not do the work described in the idea — that belongs to later phases. The skill will traverse DRAFT/ALIGN/ASK/REVISE/ASSERT internally and terminate by writing ./.phase-outcome.json with APPROVE or WITHDRAW.\n'
                '--- end ---\n\n'
                + base_task
            )
        elif phase_name == 'planning':
            base_task = (
                scope
                + '--- CfA: Planning Phase ---\n'
                'Run the /planning skill to completion. Do not execute or dispatch — planning is a separate act from doing. The skill will traverse DRAFT/ALIGN/ASK/REVISE/ASSERT internally and terminate by writing ./.phase-outcome.json with APPROVE, REALIGN, or WITHDRAW.\n'
                '--- end ---\n\n'
                + base_task
            )
        elif phase_name == 'execution':
            base_task = (
                scope
                + '--- CfA: Execution Phase ---\n'
                'Run the /execute skill to completion. You are the manager — delegate to the teams named in ./PLAN.md via Send; inspect their output against ./PLAN.md and ./INTENT.md; CloseConversation only when satisfied. The skill will traverse START/EXECUTE/ASK/ASSERT internally and terminate by writing ./.phase-outcome.json with APPROVE, REALIGN, REPLAN, or WITHDRAW.\n'
                '--- end ---\n\n'
                + base_task
            )

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
                    f"human's preferences yet. Exploring within your cwd and "
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
        from teaparty.config.config_reader import (
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
        from teaparty.util.skill_lookup import _parse_frontmatter

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
        response = await self.input_provider(InputRequest(
            type='failure_decision',
            state='INFRASTRUCTURE_FAILURE',
            artifact='',
            bridge_text=bridge_text,
        ))
        try:
            from teaparty.scripts.classify_review import classify
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
            from teaparty.proxy.approval_gate import mark_false_positive_approvals
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
        the plan was corrected — either by the human during the planning
        skill's ASSERT/REVISE dialog, or by the planning skill's System 2
        fallback after backtrack — and the corrected plan is archived as a
        skill correction candidate.

        Issue #142: skill self-correction on backtrack.
        """
        if not self._active_skill:
            return

        from pathlib import Path

        plan_path = os.path.join(self.session_worktree, 'PLAN.md')
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
                from teaparty.learning.procedural.learning import _parse_candidate_frontmatter
                _skill_content = Path(skill_path).read_text(errors='replace')
                _skill_meta, _ = _parse_candidate_frontmatter(_skill_content)
                skill_category = _skill_meta.get('category', '')
            except OSError:
                pass

        try:
            from teaparty.learning.procedural.learning import archive_skill_candidate
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

        Looks up the (approval_state, project_slug) pair — one per phase
        (INTENT, PLAN, EXECUTE) — so proxy observations cluster by phase
        identity rather than by whichever internal state the skill happens
        to be in.

        Returns 0 if the proxy model doesn't exist or the pair has no entries.
        """
        from teaparty.proxy.approval_gate import load_model, _entry_key

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

        from teaparty.bridge.state.heartbeat import (
            scan_children, compact_children, create_heartbeat, read_heartbeat,
        )
        from teaparty.workspace.merge import squash_merge

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
            if cfa_data.state != 'DONE':
                continue

            # Find the worktree path from the manifest
            worktree_path = self._find_dispatch_worktree(child_infra)
            if not worktree_path or not os.path.isdir(worktree_path):
                _log.warning('Recovery: no worktree found for %s', child_infra)
                continue

            _log.info('Recovery: merging completed child %s', child.get('team', ''))
            try:
                from teaparty.scripts.generate_commit_message import build_fallback
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
                    from teaparty.cfa.dispatch import dispatch
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

        In the job store layout, child_infra is the task_dir and the
        worktree is at {task_dir}/worktree/.
        """
        # New layout: task_dir/worktree/
        candidate = os.path.join(child_infra, 'worktree')
        if os.path.isdir(candidate):
            return candidate
        return ''
