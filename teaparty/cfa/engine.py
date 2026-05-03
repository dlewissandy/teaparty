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
    ACTION_TO_STATE,
    Action,
    CfaState,
    State,
    apply_response,
    is_globally_terminal,
    save_state,
    set_state_direct,
)

_log = logging.getLogger('teaparty')
from teaparty.learning.episodic.detect_stage import detect_stage_from_content
from teaparty.learning.episodic.retire_stage import retire_stage_entries
from teaparty.cfa.actors import InputProvider
from teaparty.cfa.gates.escalation import AskQuestionRunner
from teaparty.cfa.gates.intervention_listener import InterventionListener
from teaparty.workspace.worktree import commit_artifact
from teaparty.cfa.run_options import RunOptions
from teaparty.messaging.bus import Event, EventBus, EventType, InputRequest
from teaparty.cfa.gates.intervention import build_intervention_prompt
from teaparty.util.interrupt_propagation import (
    cascade_withdraw_children,
    is_backtrack,
)
from teaparty.util.context_budget import ContextBudget, build_compact_prompt
from teaparty.cfa.phase_config import PhaseConfig
from teaparty.util.scratch import ScratchModel, ScratchWriter, extract_text
from teaparty.learning.extract import (
    write_intervention_chunk,
    write_intervention_outcome,
)


@dataclass
class PhaseResult:
    """The action that ended the phase.

    ``action`` is one of the skill-outcome constants in
    ``cfa_state`` (``APPROVED_INTENT`` / ``APPROVED_PLAN`` /
    ``APPROVED_WORK`` / ``REALIGN`` / ``REPLAN`` / ``WITHDRAW``) or
    the engine's own ``FAILURE`` for infra failures.  The loop uses
    ``ACTION_TO_STATE`` to pick the next state to run.
    """
    action: str
    failure_reason: str = ''


@dataclass
class OrchestratorResult:
    """Final outcome of the full session orchestration."""
    terminal_state: str             # DONE or WITHDRAWN
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
        *,
        # Required core dependencies — the infrastructure the state
        # machine cannot run without.  Optional knobs and injected
        # dependencies live on ``RunOptions`` (Cut 23).
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
        options: RunOptions | None = None,
    ):
        opts = options if options is not None else RunOptions()

        # ── Required core deps ──────────────────────────────────────────────
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
        self.teaparty_home = os.path.join(poc_root, '.teaparty')
        self.task = task
        self.session_id = session_id

        # ── Run-mode flags ──────────────────────────────────────────────────
        self.flat = opts.flat
        self.proxy_enabled = opts.proxy_enabled
        self.never_escalate = opts.never_escalate
        self.team_override = opts.team_override

        # ── Resume context ──────────────────────────────────────────────────
        self._parent_heartbeat = opts.parent_heartbeat
        self._phase_session_ids: dict[str, str] = (
            opts.phase_session_ids or {}
        )
        self._last_actor_data: dict[str, Any] = opts.last_actor_data or {}

        # ── Injected dependencies ───────────────────────────────────────────
        self.project_dir = opts.project_dir
        self._role_enforcer = opts.role_enforcer
        self._proxy_invoker_fn = opts.proxy_invoker_fn
        self._on_dispatch = opts.on_dispatch
        # Optional zero-arg callable returning True when the project is
        # paused; new dispatches get refused in that state.  Matches the
        # chat-tier AgentSession.paused_check hook.
        self._paused_check = opts.paused_check

        # ── Internal state ──────────────────────────────────────────────────
        # Two intervention slots, distinguished by scope:
        #
        # ``_pending_state_prompt`` is ephemeral — set by per-claude-session
        # concerns (``/compact`` triggers, infrastructure-failure retry
        # guidance) that are meaningful only inside the current state's
        # claude session.  Cleared on cross-state transition so the
        # downstream state's fresh claude session doesn't get a leaked
        # ``/compact`` prefix or a stale failure note.
        #
        # ``_pending_job_prompt`` is durable — set by ``_deliver_intervention``
        # when a human (or advisory sender) drops a message on the bus.
        # The human's directive applies to the job, not just the state
        # that happened to be running, so this slot survives state
        # transitions and gets prepended on the next turn regardless of
        # which state's skill is running.
        self._pending_state_prompt: str = ''
        self._pending_job_prompt: str = ''
        self._intervention_active: bool = False
        # Map session_id → Session for nested dispatch: when a child
        # agent calls Send, its current_session_id (set by the MCP
        # middleware) picks the right dispatcher out of this registry.
        # Without it, every Send would parent-attach to the root
        # orchestrator's session — wrong for grandchild spawns.
        self._session_registry: dict[str, Any] = {}
        self._scratch_model = ScratchModel(job=task, phase='')
        self._scratch_writer = ScratchWriter(session_worktree)

        self._stream_bus: Any = None
        self._stream_conv_id = ''
        # Cut 29: watermark for bus-based intervention delivery.
        # Messages with ``timestamp <= _last_intervention_ts`` have
        # already been delivered to the agent (or were sent by an
        # agent and don't need delivery).  Initialize to the timestamp
        # of the latest non-human bus message — anything human after
        # that is "trailing" and gets delivered on the first turn.
        self._last_intervention_ts: float = 0.0
        bus_path = os.path.join(infra_dir, 'messages.db')
        if os.path.exists(bus_path) and project_slug and session_id:
            from teaparty.messaging.conversations import SqliteMessageBus as _StreamBus
            self._stream_bus = _StreamBus(bus_path)
            self._stream_conv_id = f'job:{project_slug}:{session_id}'
            try:
                _all = self._stream_bus.receive(self._stream_conv_id)
                self._last_intervention_ts = max(
                    (m.timestamp for m in _all if m.sender != 'human'),
                    default=0.0,
                )
            except Exception:
                pass

        _agent_sender = self.config.project_lead or 'agent'
        if self._stream_bus:
            from teaparty.teams.stream import _make_live_stream_relay
            self._on_stream_event, _ = _make_live_stream_relay(
                self._stream_bus, self._stream_conv_id, _agent_sender,
            )
        else:
            self._on_stream_event = None

        # Per-state launch config: ``_llm_caller`` lets tests override
        # the subprocess; ``_stall_timeout`` rides into ``launch()``
        # via ``_build_launch_kwargs_base``.  ``_llm_backend`` is unused
        # in the unified loop path (the chat-tier launcher resolves
        # backends internally).
        self._llm_caller = opts.llm_caller
        self._llm_backend = opts.llm_backend
        self._stall_timeout = phase_config.stall_timeout

        self._ask_question_runner: AskQuestionRunner | None = None
        self._intervention_listener: InterventionListener | None = None
        self._intervention_resolver: dict[str, str] = {}
        self._bus_event_listener: Any | None = None
        self._bus_lead_context_id: str = ''

        self._tasks_by_child: dict[str, asyncio.Task] = {}
        self._results_by_child: dict[str, str] = {}

        self._mcp_routes = None

    async def run(self) -> OrchestratorResult:
        """Drive the CfA state machine to a terminal state."""
        from teaparty.workspace.recovery import recover_orphaned_children
        from teaparty.messaging.conversations import SqliteMessageBus

        # Bus-based recovery (Cut 19): the bus is the single source of
        # truth for "what children did I dispatch, where are they, are
        # they still running?"  Only run when this session has a bus
        # (project + session_id give us a stream conv_id; the bus DB
        # may exist on disk from a prior run).
        bus_db_path = os.path.join(self.infra_dir, 'messages.db')
        if (
            self._stream_conv_id and os.path.exists(bus_db_path)
        ):
            async def _redispatch(*, conversation, worktree_path):
                """Resume an orphaned dispatched child by re-running its
                CfA from where it left off, then squash-merging back."""
                from teaparty.bridge.state.heartbeat import (
                    create_heartbeat, finalize_heartbeat,
                )
                from teaparty.cfa.statemachine.cfa_state import (
                    load_state as _load_cfa,
                )
                from teaparty.workspace.merge import squash_merge

                child_infra = (
                    os.path.dirname(worktree_path) if worktree_path else ''
                )
                child_state_path = os.path.join(
                    child_infra, '.cfa-state.json',
                )
                if not child_infra or not os.path.isfile(child_state_path):
                    _log.warning(
                        'Recovery: cannot resume %s — missing infra / cfa-state',
                        conversation.agent_name,
                    )
                    return

                hb_path = os.path.join(child_infra, '.heartbeat')
                create_heartbeat(hb_path, role=conversation.agent_name)

                child_cfa = _load_cfa(child_state_path)
                child_session_id = os.path.basename(child_infra)

                async def _unreachable_input(request):
                    raise RuntimeError(
                        'never_escalate=True but input_provider was called',
                    )

                child_orch = Orchestrator(
                    cfa_state=child_cfa,
                    phase_config=self.config,
                    event_bus=EventBus(),
                    input_provider=_unreachable_input,
                    infra_dir=child_infra,
                    project_workdir=worktree_path,
                    session_worktree=worktree_path,
                    proxy_model_path=self.proxy_model_path,
                    project_slug=self.project_slug,
                    poc_root=self.poc_root,
                    task=self.task,
                    session_id=child_session_id,
                    options=RunOptions(
                        never_escalate=True,
                        team_override=conversation.agent_name,
                        parent_heartbeat=os.path.join(
                            self.infra_dir, '.heartbeat',
                        ),
                        llm_backend=self._llm_backend,
                    ),
                )

                result = None
                try:
                    result = await child_orch.run()
                except Exception as exc:
                    _log.warning(
                        'Recovery: resume of %s raised: %s',
                        conversation.agent_name, exc,
                    )

                if result and result.terminal_state == 'DONE':
                    try:
                        await squash_merge(
                            source=worktree_path,
                            target=self.session_worktree,
                            message=(
                                f'Recovery: resumed {conversation.agent_name} dispatch'
                            ),
                        )
                    except Exception as exc:
                        _log.warning(
                            'Recovery: merge after resume failed: %s', exc,
                        )

                try:
                    finalize_heartbeat(
                        hb_path,
                        'completed' if (
                            result and result.terminal_state == 'DONE'
                        ) else 'withdrawn',
                    )
                except FileNotFoundError:
                    pass

            recovery_bus = SqliteMessageBus(bus_db_path)
            try:
                await recover_orphaned_children(
                    parent_conversation_id=self._stream_conv_id,
                    bus=recovery_bus,
                    session_worktree=self.session_worktree,
                    task=self.task,
                    session_id=self.session_id,
                    event_bus=self.event_bus,
                    redispatch_fn=_redispatch,
                )
            finally:
                recovery_bus.close()

        repo_root = os.path.dirname(os.path.dirname(self.poc_root))
        venv_python = os.path.join(repo_root, '.venv', 'bin', 'python3')
        if not os.path.isfile(venv_python):
            venv_python = 'python3'

        if self.input_provider:
            from teaparty.runners.launcher import (
                create_session as _create_session,
                load_session as _load_session,
            )
            ask_question_bus_db = os.path.join(self.infra_dir, 'messages.db')

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
            self._dispatcher_session = dispatcher

            self._ask_question_runner = AskQuestionRunner(
                bus_db_path=ask_question_bus_db,
                session_id=self.session_id,
                project_slug=self.project_slug,
                cfa_state=self.cfa.state,
                infra_dir=self.infra_dir,
                team=self.team_override,
                proxy_invoker_fn=self._proxy_invoker_fn,
                on_dispatch=self._on_dispatch,
                dispatcher_session=dispatcher,
                dispatcher_conv_id=self._stream_conv_id,
                teaparty_home=self.teaparty_home,
                scope='management',
            )
            self._ask_question_runner.rehydrate()

            self._intervention_resolver[self.session_id] = self.infra_dir
            intervention_conv_id = f'intervention:{self.session_id}'
            self._intervention_listener = InterventionListener(
                resolver=self._intervention_resolver,
                bus_db_path=ask_question_bus_db,
                conv_id=intervention_conv_id,
                on_withdraw=self._on_external_withdraw,
            )
            await self._intervention_listener.start()

            from teaparty.messaging.listener import BusEventListener  # noqa: PLC0415
            bus_db_path = os.path.join(self.infra_dir, 'messages.db')
            lead_agent_id = f'{self.project_slug}/lead' if self.project_slug else 'om'
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
                    pass
                finally:
                    _bus.close()
            self._bus_event_listener = BusEventListener(
                bus_db_path=bus_db_path,
                initiator_agent_id=lead_agent_id,
                current_context_id=self._bus_lead_context_id,
            )
            self._bus_event_listener.tasks_by_child = self._tasks_by_child
            await self._bus_event_listener.start()

            from teaparty.mcp.registry import MCPRoutes, register_agent_mcp_routes
            from teaparty.workspace.close_conversation import build_close_fn
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
                # Match the dispatch ctx: workers live at
                # ``{infra_dir}/tasks/<sid>/``, so close_conversation
                # has to look there to find their metadata.json.
                tasks_dir=os.path.join(self.infra_dir, 'tasks'),
            )
            from teaparty.messaging.child_dispatch import (
                build_session_dispatcher,
                ChildDispatchContext,
                make_spawn_fn,
            )
            dispatcher = build_session_dispatcher(
                teaparty_home=self.teaparty_home,
                lead_name=lead_agent_id,
            )

            # Cut 24: unified spawn_fn prelude across tiers.  CfA's
            # dispatcher session conceptually owns its session_worktree
            # — populate worktree_path/merge_target_repo so the shared
            # prelude derives source_repo correctly.  This mirrors a
            # chat-tier nested dispatcher whose worktree_path is set
            # from a prior subchat creation.
            self._dispatcher_session.worktree_path = self.session_worktree
            self._dispatcher_session.merge_target_repo = self.project_workdir
            self._dispatcher_session.merge_target_worktree = (
                self.session_worktree
            )
            self._dispatcher_session.agent_name = lead_agent_id

            spawn_bus = _CloseBus(self._bus_event_listener.bus_db_path)
            self._spawn_bus = spawn_bus  # keep alive; closed at run() finally

            async def _on_child_complete(child_session, response_text):
                """CfA fan-in: inject reply into lead's claude history,
                signal fan_in_event when last child completes."""
                lead_sid = self._phase_session_ids.get(self.cfa.state, '')
                if lead_sid and response_text:
                    try:
                        await self._bus_inject_reply(
                            context_id='', session_id=lead_sid,
                            message=response_text,
                        )
                    except Exception:
                        _log.exception(
                            '_on_child_complete: inject reply failed',
                        )

            self._dispatch_ctx = ChildDispatchContext(
                dispatcher_session=self._dispatcher_session,
                bus=spawn_bus,
                bus_listener=self._bus_event_listener,
                session_registry=self._session_registry,
                tasks_by_child=self._tasks_by_child,
                results_by_child=self._results_by_child,
                factory_registry=None,
                teaparty_home=self.teaparty_home,
                project_slug=self.project_slug,
                repo_root=self.project_workdir,
                telemetry_scope=self.project_slug,
                # Workers dispatched from this job land at
                # ``{infra_dir}/tasks/<sid>/`` rather than under the
                # catalog's ``management/sessions/`` — the worker's
                # filesystem location matches its operational owner.
                tasks_dir=os.path.join(self.infra_dir, 'tasks'),
                fixed_scope='management',
                cross_repo_supported=False,
                log_tag='cfa._bus_spawn_agent',
                paused_check=self._paused_check,
                on_dispatch=self._on_dispatch,
                on_child_complete=_on_child_complete,
            )
            self._mcp_routes = MCPRoutes(
                spawn_fn=make_spawn_fn(self._dispatch_ctx),
                close_fn=close_fn,
                ask_question_runner=self._ask_question_runner,
                dispatcher=dispatcher,
            )
            # mcp_routes must be on the dispatch ctx so children inherit it.
            self._dispatch_ctx.mcp_routes = self._mcp_routes
            register_agent_mcp_routes(
                self.config.project_lead or 'project-lead',
                self._mcp_routes,
            )

        self.event_bus.subscribe(self._on_scratch_event)

        try:
            return await self._run_job()
        finally:
            self.event_bus.unsubscribe(self._on_scratch_event)
            self._scratch_writer.cleanup()
            if self._intervention_listener:
                await self._intervention_listener.stop()
            if self._bus_event_listener:
                await self._bus_event_listener.stop()

    async def _bus_inject_reply(
        self, context_id: str, session_id: str, message: str,
    ) -> None:
        """Inject a worker reply into the lead's conversation history.

        Called by BusEventListener for EVERY Reply, including those from
        workers that complete before the final one (fan-out N > 1).  This
        ensures all worker replies are in the lead's JSONL history before
        run_agent_loop's gather step triggers the --resume invocation.

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

    def _update_lead_bus_session(self, session_id: str) -> None:
        """Update the orchestrator's bus context record with the latest lead session_id.

        Called after each agent turn so BusEventListener.trigger_reply (run at
        child subprocess exit) can retrieve the session_id needed to call
        reinvoke_fn when all workers have replied.
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

    async def _run_job(self) -> OrchestratorResult:
        """Drive the CfA to a terminal state.

        Each iteration runs the skill for ``next_state`` and receives
        back the ``action`` that ended it.  ``ACTION_TO_STATE`` names
        the next state; reaching ``DONE`` / ``WITHDRAWN`` exits the loop.

        Initial state comes from the caller's CfaState
        (``cfa/session.py`` sets it based on which artifacts are
        already present).
        """
        next_state = self.cfa.state

        while True:
            result = await self._run_state(next_state)
            action = result.action

            # ``_run_state`` handles all recoverable failures internally
            # (overload retries, human-guided resume).  FAILURE here
            # only bubbles up when ``never_escalate`` is set: there is
            # no human to ask, so we exit with whatever state we're in.
            if action == Action.FAILURE:
                return self._make_result(self.cfa.state)

            if action in (Action.REALIGN, Action.REPLAN):
                self._record_dead_end(
                    next_state,
                    f'{next_state} backtracked via {action}',
                    '',
                )

            # Premortem at the PLAN→EXECUTE boundary feeds the
            # prospective-extraction pipeline.  Skill selection /
            # reconciliation is owned by the planning skill itself.
            if next_state == State.PLAN:
                from teaparty.learning.phase_hooks import try_write_premortem
                try_write_premortem(infra_dir=self.infra_dir, task=self.task)

            next_state = ACTION_TO_STATE[action]
            if is_globally_terminal(next_state):
                break

        return self._make_result(self.cfa.state)

    def _make_result(self, terminal_state: str) -> OrchestratorResult:
        """Build the final OrchestratorResult."""
        return OrchestratorResult(
            terminal_state=terminal_state,
            backtrack_count=self.cfa.backtrack_count,
        )

    async def _run_state(self, state: State) -> PhaseResult:
        """Run a single CfA state until the skill emits an action.

        Layered on top of the unified ``run_agent_loop`` — same primitive
        the chat tier uses, with CfA-specific concerns plugged in via
        callbacks (intervention pump, infra-failure dialog, outcome
        reading).  Returns ``PhaseResult(action=...)`` with the action
        the loop terminated on.
        """
        from teaparty.messaging.child_dispatch import run_agent_loop
        from teaparty.runners.launcher import launch
        from types import SimpleNamespace

        spec = self._phase_spec(state)

        await self.event_bus.publish(Event(
            type=EventType.PHASE_STARTED,
            data={'state': state, 'stream_file': spec.stream_file},
            session_id=self.session_id,
        ))

        stream_path = os.path.join(self.infra_dir, spec.stream_file)
        if not os.path.exists(stream_path):
            open(stream_path, 'w').close()

        # ── Static launch kwargs (built once per state) ────────────────
        launch_kwargs_base = self._build_launch_kwargs_base(state, spec)

        # ── First-turn prompt: task body + optional resume / backtrack
        #    headers.  Subsequent turns receive grandchild replies as
        #    their message; the engine only contributes intervention
        #    text via ``on_pre_turn``.
        initial_message = self._build_initial_message(state)

        # ── Per-state state held by the closures below ─────────────────
        terminal_outcome: dict[str, Any] = {}  # written by on_failure when it forces an exit

        # ── Hooks ──────────────────────────────────────────────────────
        async def on_pre_turn(msg: str) -> str:
            """Prepend any pending intervention (job-scoped human input,
            then state-scoped failure-guidance / compaction) onto the
            outgoing turn message.  Job-scoped first so the human's
            directive sits at the front of the conversation history
            even when ``/compact`` follows behind it."""
            await self._deliver_intervention()
            parts: list[str] = []
            if self._pending_job_prompt:
                parts.append(self._pending_job_prompt)
                self._pending_job_prompt = ''
            if self._pending_state_prompt:
                parts.append(self._pending_state_prompt)
                self._pending_state_prompt = ''
            if parts:
                msg = '\n\n'.join(parts) + '\n\n' + msg
            return msg

        async def on_post_turn(result: Any) -> None:
            """Telemetry, artifact relocation, scratch update,
            compaction prep — runs after every successful turn."""
            await self._post_turn_bookkeeping(state, spec, result)

        async def on_failure(result: Any) -> str:
            """Recoverable failures retry inline; unrecoverable ones
            either land in ``State.FAILURE`` (autonomous) or surface
            a withdraw / resume-with-guidance dialog."""
            reason = (
                'stall_timeout' if getattr(result, 'stall_killed', False)
                else 'api_overloaded' if getattr(result, 'api_overloaded', False)
                else 'nonzero_exit'
            )
            if reason == 'api_overloaded':
                if await self._handle_overloaded(state) == 'retry':
                    return 'retry'
            if self.never_escalate:
                self.cfa = set_state_direct(self.cfa, State.FAILURE)
                save_state(
                    self.cfa,
                    os.path.join(self.infra_dir, '.cfa-state.json'),
                )
                terminal_outcome['action'] = Action.FAILURE
                terminal_outcome['failure_reason'] = reason
                return 'abort'
            decision, response = await self._failure_dialog(reason)
            if decision == 'withdraw':
                self.cfa = set_state_direct(self.cfa, State.WITHDRAWN)
                save_state(
                    self.cfa,
                    os.path.join(self.infra_dir, '.cfa-state.json'),
                )
                terminal_outcome['action'] = Action.WITHDRAW
                return 'abort'
            # Retry: queue the human's response as the next turn's
            # intervention text.  ``--resume`` keeps the same Claude
            # session so the agent picks up where it left off.  This
            # is state-scoped: a ``retry`` decision re-launches the
            # same state, never a different one.
            self._pending_state_prompt = (
                f'[infrastructure failure: {reason}]\n'
                f'[human guidance]\n{response}'
            )
            return 'retry'

        async def on_terminate() -> Any:
            """Read ``./.phase-outcome.json``.  Present and parseable
            → return the ``Action``.  Absent → ``None`` (loop falls
            through to its natural exit, engine raises if there's
            nothing to wait for either)."""
            return self._read_phase_outcome_action()

        # ── Run the unified loop ───────────────────────────────────────
        loop_session = SimpleNamespace(
            claude_session_id=self._phase_session_ids.get(state, ''),
        )

        if self._stream_bus is None or not self._stream_conv_id:
            raise RuntimeError(
                'CfA engine requires a stream bus and conv_id to drive '
                'run_agent_loop; this Orchestrator was constructed '
                'without project_slug + session_id wiring.',
            )

        loop_result = await run_agent_loop(
            agent_name=spec.lead,
            initial_message=initial_message,
            bus=self._stream_bus,
            conv_id=self._stream_conv_id,
            session=loop_session,
            tasks_by_child=self._tasks_by_child,
            results_by_child=self._results_by_child,
            launch_fn=launch,
            launch_kwargs_base=launch_kwargs_base,
            resume_claude_session=self._phase_session_ids.get(state, ''),
            on_pre_turn=on_pre_turn,
            on_post_turn=on_post_turn,
            on_failure=on_failure,
            on_terminate=on_terminate,
        )

        await self.event_bus.publish(Event(
            type=EventType.PHASE_COMPLETED,
            data={'state': self.cfa.state},
            session_id=self.session_id,
        ))

        # ── Resolve final action ───────────────────────────────────────
        if 'action' in terminal_outcome:
            # on_failure forced an exit (FAILURE or WITHDRAW).  CfaState
            # was already moved by the failure handler; nothing left to
            # transition.
            action = terminal_outcome['action']
            if action == Action.FAILURE:
                return PhaseResult(
                    action=Action.FAILURE,
                    failure_reason=terminal_outcome.get('failure_reason', ''),
                )
            return PhaseResult(action=action)

        action = loop_result.terminal
        if action is None:
            raise RuntimeError(
                f'CfA state {self.cfa.state!r}: skill turn ended '
                'without writing ``.phase-outcome.json`` and no '
                'workers are in flight.  Nothing to wait for; the '
                'skill is incomplete.  Engine refuses to silently '
                'approve.',
            )

        # ── Apply transition with the claude_session_id the loop tracked ─
        await self._transition(
            action,
            claude_session_id=loop_session.claude_session_id,
        )

        return PhaseResult(action=action)

    def _build_initial_message(self, state: State) -> str:
        """Construct the first-turn prompt for *state*.

        Adds the ``[CfA RESPONSE / BACKTRACK]`` header when the engine
        is resuming with feedback / dialog from a downstream phase, and
        the ``[SESSION RESUMED]`` header when ``--resume`` will reattach
        to a Claude session whose task handles are now stale.
        """
        task = self._task_for_phase(state)

        prev_feedback = self._last_actor_data.get('feedback', '')
        prev_dialog = self._last_actor_data.get('dialog_history', '')
        prev_stderr = self._last_actor_data.get('stderr_lines', [])

        backtrack_parts: list[str] = []
        if prev_dialog:
            backtrack_parts.append(f'[escalation dialog]\n{prev_dialog}')
        if prev_feedback:
            backtrack_parts.append(f'[human feedback]\n{prev_feedback}')
        if prev_stderr:
            backtrack_parts.append(
                '[stderr from previous turn]\n' + '\n'.join(prev_stderr),
            )

        prompt = task
        if backtrack_parts:
            has_human = any(
                p.startswith('[human feedback]') for p in backtrack_parts
            )
            header = (
                '[CfA RESPONSE: The human has responded to your escalation.]'
                if has_human else
                '[CfA BACKTRACK: Re-entering from a downstream phase.]'
            )
            prompt = (
                f'{header}\n\n'
                f'Feedback:\n' + '\n\n'.join(backtrack_parts) + '\n\n'
                f'Original task: {task}'
            )

        if self._phase_session_ids.get(state):
            prompt = (
                '[SESSION RESUMED — STALE TASK HANDLES]\n'
                'This conversation is being resumed after a restart. '
                'All background task and agent handles from the previous '
                'run are dead — calling TaskOutput or checking on prior '
                'task IDs will fail with "No task found". Do not poll '
                'them. Instead, assess progress from what is on disk '
                '(files already written) and re-dispatch any incomplete '
                'work.\n\n'
                + prompt
            )
        return prompt

    def _build_launch_kwargs_base(self, state: State, spec: 'PhaseSpec') -> dict:
        """Build the static launch kwargs for ``run_agent_loop``.

        Settings construction (jail hook, agent file resolution,
        permission mode) used to live in ``actors.run_phase`` and ran
        per turn.  The values are state-scoped, not turn-scoped, so
        the loop builds them once and threads them through every
        iteration via ``launch_kwargs_base``.
        """
        from teaparty.cfa.phase_config import PhaseConfig
        from teaparty.cfa.actors import _stage_jail_hook, _check_jail_hook
        from teaparty.runners.launcher import _merge_settings as _lm

        teaparty_home_for_agent = os.path.join(
            self.project_workdir, '.teaparty',
        )

        # Resolve agent definitions (workgroup YAML preferred over the
        # legacy single-file path).
        agents_json = ''
        agents_path = ''
        wg_name = spec.agent_file
        wg_yaml = os.path.join(
            teaparty_home_for_agent, 'project',
            'workgroups', f'{wg_name}.yaml',
        )
        if os.path.isfile(wg_yaml):
            cfg = PhaseConfig(self.poc_root)
            agents_json = cfg.resolve_agents_json(wg_name)
        if not agents_json:
            agents_path = os.path.join(self.poc_root, spec.agent_file)

        # Build settings.  Stage the worktree jail script into the
        # session worktree (Issue #150) so the launcher's universal
        # PreToolUse hook registration can find it; the launcher
        # injects the matcher entry itself, no per-engine wiring.
        try:
            settings = _lm(spec.lead, 'project', teaparty_home_for_agent)
        except Exception:
            settings = {}
        _JAIL = '.claude/hooks/worktree_hook.py'
        _stage_jail_hook(self.session_worktree, _JAIL)
        _check_jail_hook(self.session_worktree, _JAIL)

        mcp_port = int(os.environ.get('TEAPARTY_BRIDGE_PORT', '9000'))
        base = dict(
            agent_name=spec.lead,
            scope='project',
            telemetry_scope=self.project_slug or 'project',
            mcp_port=mcp_port,
            teaparty_home=teaparty_home_for_agent,
            org_home=self.teaparty_home,
            worktree=self.session_worktree,
            event_bus=self.event_bus,
            session_id=self.session_id,
            heartbeat_file=os.path.join(self.infra_dir, '.heartbeat'),
            parent_heartbeat=self._parent_heartbeat,
            children_file=os.path.join(self.infra_dir, '.children'),
            stall_timeout=self._stall_timeout,
            settings_override=settings,
            agents_json=agents_json or None,
            agents_file=agents_path or None,
            stream_file=os.path.join(self.infra_dir, spec.stream_file),
            permission_mode_override=spec.permission_mode,
            mcp_routes=self._mcp_routes,
            caller_conversation_id=(
                f'job:{self.project_slug}:{self.session_id}'
                if self.project_slug and self.session_id else ''
            ),
        )
        if self._llm_caller is not None:
            base['llm_caller'] = self._llm_caller
        return base

    def _read_phase_outcome_action(self) -> Action | None:
        """Return the ``Action`` written by the skill, or ``None``.

        The ``.phase-outcome.json`` file is consumed (deleted) on read
        so the next turn can't pick up a stale outcome.  Unknown
        outcomes are treated as absent.
        """
        path = os.path.join(self.session_worktree, '.phase-outcome.json')
        if not os.path.isfile(path):
            return None
        try:
            with open(path) as f:
                payload = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
        try:
            os.unlink(path)
        except OSError:
            pass
        outcome = str(payload.get('outcome', '')).upper()
        try:
            return Action(outcome)
        except ValueError:
            return None

    async def _post_turn_bookkeeping(
        self,
        state: State,
        spec: 'PhaseSpec',
        result: Any,
    ) -> None:
        """Run the per-turn bookkeeping the engine cares about.

        Publishes turn-cost telemetry, relocates artifacts the agent
        wrote outside the worktree, updates the scratch model, and
        queues a ``/compact`` intervention when the context budget
        crosses the threshold.
        """
        from teaparty.cfa.actors import (
            _relocate_plan_file, _relocate_misplaced_artifact,
        )

        cost = getattr(result, 'cost_usd', 0.0)
        if cost:
            stats: dict[str, Any] = {'total_cost_usd': cost}
            for key in ('input_tokens', 'output_tokens', 'duration_ms'):
                val = getattr(result, key, None)
                if val:
                    stats[key] = val
            await self.event_bus.publish(Event(
                type=EventType.TURN_COST,
                data=stats,
                session_id=self.session_id,
            ))

        # Plan-file relocation: claude stores plans in ~/.claude/plans/
        # when running with --permission-mode plan; copy the newest one
        # into the worktree if the artifact isn't already there.
        if (spec.artifact
                and getattr(spec, 'permission_mode', None) == 'plan'):
            artifact_path = os.path.join(self.session_worktree, spec.artifact)
            if not os.path.exists(artifact_path):
                _relocate_plan_file(
                    artifact_path, getattr(result, 'start_time', 0.0),
                )

        # Misplaced-artifact relocation: agents sometimes write to an
        # absolute path outside the worktree.  Parse the stream JSONL
        # to find the actual write target and move the file in.
        stream_path = os.path.join(self.infra_dir, spec.stream_file)
        if spec.artifact:
            _relocate_misplaced_artifact(
                self.session_worktree, stream_path, spec.artifact,
            )

        self._update_scratch(state)

        # Orchestrator-driven ``/compact`` is disabled — see issue #260.
        #
        # The earlier strategy queued ``_pending_state_prompt =
        # '/compact <focus>'`` and ``on_pre_turn`` prepended it onto the
        # next user message.  Two structural defects make this unsafe:
        #
        # 1. ``ContextBudget`` hardcodes a 200K context window
        #    (``util/context_budget.py:15``).  The project-lead runs on
        #    ``claude-opus-4-7[1m]`` (1M context).  ``should_compact``
        #    fires at ~43% real utilization, an order of magnitude
        #    earlier than the 78% threshold the design targets.
        #
        # 2. Claude CLI's slash-command dispatcher treats a user
        #    message that begins with ``/compact`` as the slash command
        #    plus its focus argument.  The actual content the engine
        #    intended for the agent (e.g. a worker's Reply) is consumed
        #    as part of the focus and never delivered as a turn the
        #    agent answers.  ``result.result`` comes back empty,
        #    ``run_agent_loop`` exits naturally with no terminal, and
        #    ``_run_state`` raises ``RuntimeError("skill is
        #    incomplete")``.
        #
        # Both defects are reproducible in the live joke-book exec
        # streams (``compact_boundary trigger='manual'``).  The fix
        # path discussed at the time #260 was opened — and explicitly
        # reopened against Tier 4 — is **agent-controlled** compaction
        # (the agent calls a ``compact_context`` tool when it judges
        # context pressure to be high), not orchestrator-injected
        # slash commands.  Until that lands, the gate is unconditional:
        # observe tokens (the budget keeps tracking for telemetry), but
        # never queue ``/compact``.
        budget = getattr(result, 'context_budget', None)
        if isinstance(budget, ContextBudget) and budget.should_compact:
            budget.clear_compact()  # observe-only; no prompt queued

    async def _deliver_intervention(self) -> None:
        """Drain pending bus messages, publish INTERVENE, store prompt for injection.

        Cut 29: the bus is the source of truth for human messages.  At
        turn boundaries, read messages with ``timestamp >
        _last_intervention_ts``, filter for human/advisory senders,
        and queue them for injection on the next agent turn.  The
        previous separate ``InterventionQueue`` was redundant — the
        bridge already wrote messages to the bus before triggering
        resume; the queue was just an in-memory copy of bus state.

        Called at turn boundaries.  No-ops when there are no new
        deliverable messages.
        """
        if not self._stream_bus or not self._stream_conv_id:
            return

        try:
            all_msgs = self._stream_bus.receive(
                self._stream_conv_id,
                since_timestamp=self._last_intervention_ts,
            )
        except Exception:
            return

        # Deliverable: human messages plus any role_enforcer-recognized
        # advisory senders.  Informed senders (per role_enforcer) are
        # filtered via ``check_send`` — same semantics InterventionQueue
        # used to enforce on enqueue.
        pending = []
        for m in all_msgs:
            if m.sender == 'human' or (
                self._role_enforcer is not None
                and self._role_enforcer.is_advisory(m.sender)
            ):
                if self._role_enforcer is not None:
                    try:
                        self._role_enforcer.check_send(m.sender)
                    except Exception:
                        continue
                pending.append(m)

        if not pending:
            return

        # Watermark: don't re-deliver these on the next call.
        self._last_intervention_ts = max(m.timestamp for m in pending)

        prompt = build_intervention_prompt(
            pending, role_enforcer=self._role_enforcer,
        )
        # Human-driven interventions are job-scoped — the human's
        # directive applies regardless of which state happens to be
        # running when it gets consumed.  Survives cross-state.
        self._pending_job_prompt = prompt
        self._intervention_active = True

        write_intervention_chunk(
            infra_dir=self.infra_dir,
            content=prompt,
            senders=[m.sender for m in pending],
            cfa_state=self.cfa.state,
            phase=self.cfa.state,
        )

        await self.event_bus.publish(Event(
            type=EventType.INTERVENE,
            data={
                'content': prompt,
                'message_count': len(pending),
                'senders': [m.sender for m in pending],
            },
            session_id=self.session_id,
        ))

    def _on_external_withdraw(self, session_id: str) -> None:
        """Called by InterventionListener when a withdrawal succeeds.

        Updates the in-memory CfA state so the engine's turn-boundary
        check sees WITHDRAWN and exits.  The file has already been
        written by withdraw_session().
        """
        _log.info('External withdrawal received for session %s', session_id)
        self.cfa = set_state_direct(self.cfa, State.WITHDRAWN)


    async def _on_scratch_event(self, event: Event) -> None:
        """Feed events into the scratch model.

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

    def _update_scratch(self, state: State) -> None:
        """Serialize the scratch model to disk at a turn boundary."""
        self._scratch_model.phase = state
        self._scratch_writer.write_scratch(self._scratch_model)

    def _record_dead_end(self, phase: str, reason: str, feedback: str = '') -> None:
        """Record a dead end from a backtrack."""
        desc = f'{phase}: {reason}'
        if feedback:
            desc += f' — {feedback[:200]}'
        self._scratch_model.add_dead_end(desc)
        self._scratch_writer.append_dead_end(desc)

    async def _check_interrupt_propagation(self, old_state: str) -> None:
        """Cascade intervention decisions to active child dispatches.

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
        if new_state == State.WITHDRAWN:
            withdrawn = cascade_withdraw_children(self.infra_dir)
            self._intervention_active = False
            write_intervention_outcome(
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

        # Backtrack: cascade-withdraw if state moved earlier
        if is_backtrack(old_state, new_state):
            withdrawn = cascade_withdraw_children(self.infra_dir)
            self._intervention_active = False
            write_intervention_outcome(
                infra_dir=self.infra_dir,
                outcome='backtrack',
                backtrack_phase=new_state,
            )
            if withdrawn:
                await self.event_bus.publish(Event(
                    type=EventType.LOG,
                    data={
                        'category': 'interrupt_propagation',
                        'trigger': 'backtrack',
                        'old_state': old_state,
                        'new_state': new_state,
                        'children_withdrawn': len(withdrawn),
                        'teams': [w['team'] for w in withdrawn],
                    },
                    session_id=self.session_id,
                ))
            return

        # Continue/adjustment: same-state or forward transition.
        self._intervention_active = False
        write_intervention_outcome(
            infra_dir=self.infra_dir,
            outcome='continue',
        )

    async def _transition(
        self, action: Action, *, claude_session_id: str = '',
    ) -> None:
        """Apply a skill action and persist state.

        ``action`` is the skill's outcome (an ``Action`` enum member
        present in ``ACTION_TO_STATE``).  No ``(state, action)`` edge
        validation: the outcome is unambiguous because only that
        skill emits it.  ``apply_response`` handles backtrack-count
        bookkeeping.

        ``claude_session_id`` is the agent's Claude session id from
        the loop's last turn — keyed under the state that just ran so
        re-entries (e.g. EXECUTE → PLAN via REPLAN, then PLAN →
        EXECUTE again) can ``--resume`` the right session per state.
        """
        target_state = ACTION_TO_STATE[action]
        old_state = self.cfa.state

        self.cfa = apply_response(self.cfa, target_state)

        if self._ask_question_runner:
            self._ask_question_runner.cfa_state = self.cfa.state

        # ``feedback`` / ``dialog_history`` are intra-state concerns: a
        # downstream escalation seeded them so the next turn within the
        # SAME state could see the human's response.  When the state
        # changes, they're stale and must not propagate.
        # Same logic for ``_pending_state_prompt``: ``/compact`` operates
        # on the current claude session, and failure-retry guidance
        # was scoped to the failure that just happened.  Both are
        # meaningless to the new state's fresh claude session.
        # ``_pending_job_prompt`` (human bus messages) is job-scoped
        # and intentionally survives the transition.
        if self.cfa.state != old_state:
            self._last_actor_data.pop('dialog_history', None)
            self._last_actor_data.pop('feedback', None)
            self._pending_state_prompt = ''

        if claude_session_id:
            # Key the session id by the state that JUST RAN, not the
            # state we transitioned INTO.  Otherwise the next state
            # ``--resume``s the prior state's claude session and the
            # agent re-runs the prior skill.
            self._phase_session_ids[old_state] = claude_session_id
            self._update_lead_bus_session(claude_session_id)

        state_path = os.path.join(self.infra_dir, '.cfa-state.json')
        save_state(self.cfa, state_path)

        try:
            from teaparty.telemetry import record_event
            from teaparty.telemetry import events as _telem_events
            _scope = self.project_slug or 'management'
            # Save the previous phase-entry timestamp before overwriting —
            # the backtrack cost query needs the window from prior phase entry until now.
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
                    'target_state':  target_state,
                    'state_machine': 'cfa',
                },
            )
            if self.cfa.backtrack_count > (
                getattr(self, '_last_backtrack_count', 0)
            ):
                # Estimate discarded cost by summing turn_complete costs
                # since the backtracked phase was entered, scoped to session_id.
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
                        'kind':            f'{old_state}_to_{self.cfa.state}',
                        'triggering_gate': old_state,
                        'target_state':    target_state,
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
                'state': self.cfa.state,
                'previous_state': old_state,
                'target_state': target_state,
                'history': self.cfa.history,
                'backtrack_count': self.cfa.backtrack_count,
            },
            session_id=self.session_id,
        ))

        await self._check_interrupt_propagation(old_state)

        await self._commit_artifacts(old_state, target_state)

        # Stage detection runs when the intent skill approved
        # (INTENT → PLAN, i.e. target_state=='PLAN' coming from
        # old_state=='INTENT').
        if old_state == 'INTENT' and target_state == 'PLAN':
            self._detect_and_retire_stage()

    async def _commit_artifacts(self, old_state: str, target_state: str) -> None:
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
                await commit_artifact(
                    wt, ['.'], f'Execution: → {target_state}',
                )
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

    def _phase_spec(self, state: State) -> 'PhaseSpec':
        """Get the phase spec for *state*, with team / flat overrides."""
        from dataclasses import replace
        if self.team_override:
            team = self.config.team(self.team_override)
            base = self.config.phase(state)
            # Teams can specify their own planning permission mode
            # (e.g., subteams use 'plan' for tactical planning).
            perm = (
                team.planning_permission_mode
                if state == State.PLAN and team.planning_permission_mode
                else base.permission_mode
            )
            return replace(
                base,
                agent_file=team.agent_file,
                lead=team.lead,
                permission_mode=perm,
            )

        base = self.config.resolve_phase(state)

        # --flat: swap the project team for a flat team where the lead
        # recruits agents dynamically via the Agent tool.  Only affects
        # states that use uber-team.json (PLAN, EXECUTE).
        if self.flat and base.agent_file == 'uber':
            return replace(base, agent_file='flat')

        return base

    _SKILL_FOR_STATE: dict[State, str] = {
        State.INTENT:  '/intent-alignment',
        State.PLAN:    '/planning',
        State.EXECUTE: '/execute',
    }

    def _task_for_phase(self, state: State) -> str:
        """Build the first-turn message for *state*.

        The engine's only orchestration job here is naming which skill
        runs and pointing at its on-disk inputs.  Reading those inputs
        is the skill's job; constraints / available-teams resolution
        is also the skill's job.

        Wording matters: a bare ``/planning`` message is treated by
        Claude Code as a slash command, looked up against the
        registered list, and silently rejected when not found
        (project skills are ``Skill``-tool-resolved, not registered
        as slash commands).  Embedding the slash in prose
        (``Run the /planning skill...``) routes the message to the
        model, which then invokes the skill via the ``Skill`` tool.

        Per state:
          * INTENT: directive + the user's original task text (the
            only input that isn't on disk yet).
          * PLAN: directive + pointer to ``./INTENT.md``.
          * EXECUTE: directive + pointer to ``./PLAN.md`` and
            ``./INTENT.md``.
        """
        skill = self._SKILL_FOR_STATE[state]
        directive = f'Run the {skill} skill to completion.'
        if state == State.INTENT:
            return f'{directive}\n\n{self.task or self.project_slug}'
        if state == State.PLAN:
            return (
                f'{directive}\n\n'
                f'The approved intent is at ./INTENT.md.'
            )
        # EXECUTE
        return (
            f'{directive}\n\n'
            f'The approved plan is at ./PLAN.md '
            f'(with ./INTENT.md as reference).'
        )

    # Maximum auto-retries for API overloaded (529) before escalating to human.
    _MAX_OVERLOAD_RETRIES = 3
    _OVERLOAD_COOLDOWN_SECONDS = 120

    async def _handle_overloaded(self, state: State) -> str:
        """Handle an API overloaded (529) failure with auto-retry.

        Tracks retry count per state.  On each retry, emits an API_OVERLOADED
        event and waits a flat cooldown.  After exhausting retries, returns
        'escalate' so the caller falls through to _failure_dialog.

        Returns 'retry' or 'escalate'.
        """
        counter_key = f'_overload_retries_{state}'
        count = getattr(self, counter_key, 0) + 1
        setattr(self, counter_key, count)

        if count > self._MAX_OVERLOAD_RETRIES:
            return 'escalate'

        await self.event_bus.publish(Event(
            type=EventType.API_OVERLOADED,
            data={
                'state': state,
                'retry_count': count,
                'max_retries': self._MAX_OVERLOAD_RETRIES,
                'cooldown_seconds': self._OVERLOAD_COOLDOWN_SECONDS,
            },
            session_id=self.session_id,
        ))

        _log.info(
            'API overloaded (529) — auto-retry %d/%d for %s, '
            'cooling down %ds',
            count, self._MAX_OVERLOAD_RETRIES, state,
            self._OVERLOAD_COOLDOWN_SECONDS,
        )

        await asyncio.sleep(self._OVERLOAD_COOLDOWN_SECONDS)
        return 'retry'

    async def _failure_dialog(self, reason: str) -> tuple[str, str]:
        """Ask human what to do after infrastructure failure.

        Returns ``(decision, response_text)`` where decision is
        ``'retry'`` or ``'withdraw'``.  The raw response text is
        returned so the caller can inject it as a turn-boundary
        intervention when the agent is resumed.
        """
        bridge_text = (
            f'Infrastructure failure: {reason}\n\n'
            'Options:\n'
            '  retry — resume the agent with your guidance\n'
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
            decision = raw.split('\t', 1)[0]
        except Exception:
            decision = '__fallback__'
        if decision == 'withdraw':
            return 'withdraw', response
        return 'retry', response

