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
    InputProvider,
)
from teaparty.cfa.gates.escalation import AskQuestionRunner
from teaparty.cfa.gates.intervention_listener import InterventionListener
from teaparty.workspace.worktree import commit_artifact
from teaparty.runners.dispatch_env import cfa_dispatch_env_vars
from teaparty.messaging.bus import Event, EventBus, EventType, InputRequest
from teaparty.cfa.gates.intervention import InterventionQueue, build_intervention_prompt
from teaparty.util.interrupt_propagation import (
    cascade_withdraw_children,
    is_backtrack,
)
from teaparty.util.context_budget import ContextBudget, build_compact_prompt
from teaparty.cfa.phase_config import PhaseConfig
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
        llm_backend: str = 'claude',
        llm_caller: Any = None,
        proxy_invoker_fn: Callable[..., Awaitable[None]] | None = None,
        on_dispatch: Callable[[dict], Any] | None = None,
        paused_check: Callable[[], bool] | None = None,
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
        self._pending_intervention: str = ''
        self._intervention_active: bool = False
        self._proxy_invoker_fn = proxy_invoker_fn
        self._on_dispatch = on_dispatch
        # Optional zero-arg callable returning True when the project is
        # paused; new dispatches get refused in that state.  Matches the
        # chat-tier AgentSession.paused_check hook.
        self._paused_check = paused_check
        # Map session_id → Session for nested dispatch: when a child
        # agent calls Send, its current_session_id (set by the MCP
        # middleware) picks the right dispatcher out of this registry.
        # Without it, every Send would parent-attach to the root
        # orchestrator's session — wrong for grandchild spawns.
        self._session_registry: dict[str, Any] = {}
        # Running cost total for this session (telemetry only — no limits).
        # Written to infra_dir/.cost after each turn so the bridge dashboard
        # and stats bar can surface per-session USD spend.
        self._total_cost_usd: float = 0.0

        self._scratch_model = ScratchModel(job=task, phase='')
        self._scratch_writer = ScratchWriter(session_worktree)

        self._stream_bus: Any = None
        self._stream_conv_id = ''
        bus_path = os.path.join(infra_dir, 'messages.db')
        if os.path.exists(bus_path) and project_slug and session_id:
            from teaparty.messaging.conversations import SqliteMessageBus as _StreamBus
            self._stream_bus = _StreamBus(bus_path)
            self._stream_conv_id = f'job:{project_slug}:{session_id}'

        _agent_sender = self.config.project_lead or 'agent'
        if self._stream_bus:
            from teaparty.teams.stream import _make_live_stream_relay
            _on_stream_event, _ = _make_live_stream_relay(
                self._stream_bus, self._stream_conv_id, _agent_sender,
            )
        else:
            _on_stream_event = None

        self._agent_runner = AgentRunner(
            stall_timeout=phase_config.stall_timeout,
            llm_backend=llm_backend,
            on_stream_event=_on_stream_event,
            llm_caller=llm_caller,
        )

        self._ask_question_runner: AskQuestionRunner | None = None
        self._intervention_listener: InterventionListener | None = None
        self._intervention_resolver: dict[str, str] = {}
        self._bus_event_listener: Any | None = None
        self._fan_in_event: asyncio.Event | None = None
        self._bus_lead_context_id: str = ''

        self._phase_session_ids: dict[str, str] = phase_session_ids or {}

        self._last_actor_data: dict[str, Any] = last_actor_data or {}

        self._active_skill: dict[str, str] | None = None

        self._tasks_by_child: dict[str, asyncio.Task] = {}

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
                from teaparty.cfa.dispatch import dispatch
                # Job-store layout: child_infra is the worktree's parent.
                child_infra = (
                    os.path.dirname(worktree_path) if worktree_path else ''
                )
                await dispatch(
                    team=conversation.agent_name,
                    task=self.task,
                    session_worktree=self.session_worktree,
                    infra_dir=self.infra_dir,
                    project_slug=self.project_slug,
                    resume_worktree=worktree_path,
                    resume_infra=child_infra,
                )

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
                spawn_fn=self._bus_spawn_agent,
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
            )
            from teaparty.messaging.child_dispatch import (
                build_session_dispatcher,
            )
            dispatcher, agent_id_map = build_session_dispatcher(
                teaparty_home=self.teaparty_home,
                project_dir=self.project_dir,
                project_slug=self.project_slug,
            )
            self._mcp_routes = MCPRoutes(
                spawn_fn=self._bus_spawn_agent,
                close_fn=close_fn,
                ask_question_runner=self._ask_question_runner,
                dispatcher=dispatcher,
                agent_id_map=agent_id_map,
            )
            register_agent_mcp_routes(
                self.config.project_lead or 'project-lead',
                self._mcp_routes,
            )

        self.event_bus.subscribe(self._on_scratch_event)

        try:
            return await self._run_loop()
        finally:
            self.event_bus.unsubscribe(self._on_scratch_event)
            self._scratch_writer.cleanup()
            if self._intervention_listener:
                await self._intervention_listener.stop()
            if self._bus_event_listener:
                await self._bus_event_listener.stop()

    async def _bus_spawn_agent(self, member: str, composite: str, context_id: str) -> tuple[str, str, str]:
        """Spawn a recipient agent for bus-mediated dispatch.

        Sets up the child's session record and worktree synchronously,
        hands off to ``BusEventListener.schedule_child_task`` which
        records the child in the dispatcher's conversation_map, emits
        ``dispatch_started``, creates the asyncio.Task that runs the
        subprocess, and registers the task in ``tasks_by_child``.  Send
        returns immediately; the child runs concurrently with siblings
        and is cancelled cleanly by the shared ``close_fn``.

        Returns ``(child_session.id, worktree_path, refusal_reason)``.
        """
        from teaparty.runners.launcher import (
            launch as _launch,
            create_session as _create_session,
            _save_session_metadata as _save_meta,
        )
        from teaparty.workspace.worktree import (
            create_subchat_worktree, current_branch_of, head_commit_of,
        )
        from teaparty.config.roster import (
            resolve_launch_placement, LaunchCwdNotResolved,
        )

        # Refuse new dispatches while the project is paused.
        if self._paused_check is not None and self._paused_check():
            _log.warning(
                '_bus_spawn_agent: project %s paused, dispatch to %s refused',
                self.project_slug, member,
            )
            return ('', '', 'paused')

        # Validate member against the registry before creating any session state.
        try:
            resolve_launch_placement(member, self.teaparty_home)
        except LaunchCwdNotResolved as exc:
            _log.warning(
                '_bus_spawn_agent: refusing dispatch to %r — %s',
                member, exc,
            )
            return ('', '', f'unresolved_member:{member}')

        # Determine which session is dispatching: a grandchild Send
        # should attach under its own session, not the root
        # orchestrator's.  The MCP middleware sets
        # ``current_session_id`` per-request.
        from teaparty.mcp.registry import (
            current_session_id as _current_session_var,
        )
        caller_sid = _current_session_var.get('')
        dispatcher_session = self._session_registry.get(
            caller_sid, self._dispatcher_session,
        )

        # Thread continuation: if the caller passed an ACTIVE dispatch
        # handle with the same lead, re-launch that existing child with
        # --resume and the new composite as the next message.
        from teaparty.messaging.child_dispatch import (
            detect_thread_continuation,
        )
        from teaparty.messaging.conversations import (
            ConversationState as _ConvState,
            ConversationType as _ConvType,
            SqliteMessageBus as _Bus,
        )
        bus_db_path = (
            self._bus_event_listener.bus_db_path
            if self._bus_event_listener is not None else ''
        )
        existing_child = detect_thread_continuation(
            context_id=context_id,
            bus_db_path=bus_db_path,
            member=member,
            teaparty_home=self.teaparty_home,
            scope='management',
        )

        from teaparty.mcp.registry import (
            current_conversation_id as _current_conv_var,
        )
        parent_conv_id = _current_conv_var.get('')
        if not parent_conv_id:
            raise RuntimeError(
                '_bus_spawn_agent: current_conversation_id is empty. '
                "The caller's conv_id must reach the spawn_fn via the "
                'MCP URL ``?conv=`` (set by ``launch(caller_conversation_id=...)``) '
                'and the middleware.  An empty contextvar means the '
                'launch site forgot the argument or the middleware did '
                'not parse it — either way we cannot stamp a correct '
                'parent_conversation_id and must refuse rather than '
                'silently produce the wrong tree.',
            )

        # Slot limit: the caller cannot hold more than
        # MAX_CONVERSATIONS_PER_AGENT live dispatches at once.  Skip the
        # check on the resume path — re-entering an existing dispatch
        # reuses a slot.
        if existing_child is None:
            from teaparty.runners.launcher import check_slot_available
            _slot_bus = _Bus(self._bus_event_listener.bus_db_path)
            try:
                _ok = check_slot_available(
                    dispatcher_session,
                    bus=_slot_bus,
                    conv_id=parent_conv_id,
                )
            finally:
                _slot_bus.close()
            if not _ok:
                _log.warning(
                    '_bus_spawn_agent: at conversation limit '
                    '(parent %s); dispatch to %s blocked',
                    parent_conv_id, member,
                )
                return ('', '', 'slot_limit')

        if existing_child is not None:
            child_session = existing_child
            worktree_path = child_session.worktree_path
            session_branch = child_session.worktree_branch
        else:
            child_session = _create_session(
                agent_name=member, scope='management',
                teaparty_home=self.teaparty_home,
            )
            worktree_path = os.path.join(child_session.path, 'worktree')
            session_branch = f'session/{child_session.id}'

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
                        worktree_path=worktree_path,
                    )
                finally:
                    _bus.close()

            # Fork source + merge target = the lead's session worktree,
            # falling back to the project repo root for bootstrap paths.
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
                dispatcher_session.id if dispatcher_session else ''
            )
        child_session.initial_message = composite
        _save_meta(child_session)

        # Track the child so its own Send calls resolve to the right
        # dispatcher_session via ``current_session_id``.
        self._session_registry[child_session.id] = child_session

        child_conv_id = f'dispatch:{child_session.id}'
        child_bus = _Bus(self._bus_event_listener.bus_db_path)
        # Capture launch at spawn time so tests that monkeypatch
        # ``launcher.launch`` see the stub even if the background
        # task runs after the test's teardown restores the original.
        from teaparty.runners.launcher import launch as _spawn_launch

        async def _run_child() -> str:
            from teaparty.messaging.child_dispatch import run_child_lifecycle
            response_text = ''
            try:
                response_text = await run_child_lifecycle(
                    member=member,
                    child_session=child_session,
                    worktree_path=worktree_path,
                    composite=composite,
                    child_conv_id=child_conv_id,
                    bus=child_bus,
                    tasks_by_child=self._tasks_by_child,
                    launch_fn=_spawn_launch,
                    mcp_routes=self._mcp_routes,
                    llm_caller=None,
                    member_scope='management',
                    member_teaparty_home=self.teaparty_home,
                    telemetry_scope=self.project_slug,
                    resume_claude_session=child_session.claude_session_id or '',
                )
            except Exception:
                _log.exception(
                    '_bus_spawn_agent task failed for %s', member,
                )
                response_text = ''
            finally:
                # Fan-in bookkeeping: remove this child from the in-flight
                # set and wake the lead's fan-in waiter when the set drains.
                self._tasks_by_child.pop(child_session.id, None)
                lead_sid = self._phase_session_ids.get(
                    phase_for_state(self.cfa.state), ''
                )
                if lead_sid and response_text:
                    try:
                        await self._bus_inject_reply(
                            context_id='',
                            session_id=lead_sid,
                            message=response_text,
                        )
                    except Exception:
                        _log.exception(
                            '_run_child: inject reply failed for %s',
                            member,
                        )
                if not self._tasks_by_child and self._fan_in_event:
                    self._fan_in_event.set()
                try:
                    child_bus.close()
                except Exception:
                    pass
            return response_text

        self._bus_event_listener.schedule_child_task(
            child_session_id=child_session.id,
            launch_coro=_run_child(),
            dispatcher_session=dispatcher_session,
            context_id=context_id,
            agent_name=member,
            on_dispatch=self._on_dispatch,
        )

        return (child_session.id, worktree_path, '')

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
        if not self._tasks_by_child:
            _log.info(
                'Fan-in wait: no workers in flight; re-invoking lead '
                'immediately',
            )
            return await self._invoke_actor(
                spec, phase_name, phase_start_time,
            )
        # Arm the event before re-checking _tasks_by_child to avoid a
        # race where a child completion fires between check and arm.
        self._fan_in_event = asyncio.Event()
        try:
            if self._tasks_by_child:
                _log.info(
                    'Fan-in wait: blocking until all dispatched workers '
                    'reply',
                )
                await self._fan_in_event.wait()
        finally:
            self._fan_in_event = None
        _log.info('Fan-in complete: resuming lead via --resume for synthesis')
        return await self._invoke_actor(spec, phase_name, phase_start_time)

    # Sentinel values returned by _classify_phase_result to _run_loop.
    _ACTION_NEXT_PHASE = 'next'
    _ACTION_RETRY_SEQUENCE = 'retry'
    _ACTION_TERMINAL = 'terminal'
    _ACTION_WITHDRAW = 'withdraw'
    _ACTION_RETURN_CURRENT = 'return'

    def _phase_sequence(self) -> list[str]:
        """The phases to run, honoring ``skip_intent`` / ``*_only`` flags."""
        seq: list[str] = []
        if not self.skip_intent:
            seq.append('intent')
        if self.intent_only:
            return seq
        if not self.execute_only:
            seq.append('planning')
        if self.plan_only:
            return seq
        seq.append('execution')
        return seq

    async def _run_loop(self) -> OrchestratorResult:
        """Run each phase in sequence, handle its result, retry or return.

        Every phase follows the same shape — run, classify the result
        (terminal / backtrack / infrastructure_failure / normal), and
        either continue, retry the sequence, or return.
        ``_classify_phase_result`` owns the policy.
        """
        while True:
            outcome = await self._run_sequence_once()
            if outcome == self._ACTION_RETRY_SEQUENCE:
                continue
            if outcome == self._ACTION_WITHDRAW:
                self.cfa = set_state_direct(self.cfa, 'WITHDRAWN')
                save_state(
                    self.cfa,
                    os.path.join(self.infra_dir, '.cfa-state.json'),
                )
                return self._make_result('WITHDRAWN')
            if outcome == self._ACTION_RETURN_CURRENT:
                return self._make_result(self.cfa.state)
            if isinstance(outcome, OrchestratorResult):
                return outcome
            return self._make_result(self.cfa.state)

    async def _run_sequence_once(self) -> 'OrchestratorResult | str':
        """One pass through the phase sequence.  See ``_run_loop``."""
        for phase in self._phase_sequence():
            if phase == 'planning':
                await self._try_skill_lookup()

            result = await self._run_phase(phase)

            # Post-phase hooks run only on normal completion.
            if (phase == 'planning'
                    and not result.terminal
                    and not result.infrastructure_failure):
                from teaparty.learning.phase_hooks import (
                    archive_skill_correction,
                )
                if archive_skill_correction(
                    active_skill=self._active_skill,
                    session_worktree=self.session_worktree,
                    infra_dir=self.infra_dir,
                    project_workdir=self.project_workdir,
                    task=self.task,
                    session_id=self.session_id,
                ):
                    self._active_skill = None

            outcome = await self._classify_phase_result(phase, result)
            if outcome == self._ACTION_NEXT_PHASE:
                if phase == 'planning':
                    from teaparty.learning.phase_hooks import (
                        try_write_premortem,
                    )
                    try_write_premortem(
                        infra_dir=self.infra_dir, task=self.task,
                    )
                continue
            return outcome

        # Sequence finished — plan-only / intent-only / end of execution
        # without a terminal state.  Let ``_run_loop`` decide (returning
        # ``next`` is equivalent to "done").
        if self.plan_only or self.intent_only:
            return self._make_result('DONE')
        return self._ACTION_NEXT_PHASE

    async def _classify_phase_result(
        self, phase: str, result: PhaseResult,
    ) -> 'OrchestratorResult | str':
        """Map a PhaseResult to a control-flow action.

        Returns one of the ``_ACTION_*`` sentinels or an
        ``OrchestratorResult`` that the outer loop returns as-is.
        Mutates ``self.skip_intent`` / ``self.execute_only`` on
        backtracks so the next sequence pass starts at the right
        phase.
        """
        if result.terminal:
            return self._make_result(result.terminal_state)

        if result.backtrack_to:
            return self._handle_backtrack(phase, result)

        if result.infrastructure_failure:
            return await self._handle_infra_failure(phase, result)

        return self._ACTION_NEXT_PHASE

    def _handle_backtrack(self, phase: str, result: PhaseResult) -> str:
        """Apply a backtrack: record the dead end, rewind phase flags."""
        target = result.backtrack_to or ''
        reason = f'{phase} backtracked to {target}'
        self._record_dead_end(phase, reason, result.backtrack_feedback)
        if self.suppress_backtracks:
            _log.info(
                'Suppressing backtrack to %s (suppress_backtracks=True)',
                target,
            )
            return self._ACTION_NEXT_PHASE
        if target == 'intent':
            self.skip_intent = False
            if phase == 'execution':
                self.execute_only = False
        elif target == 'planning':
            self.skip_intent = True
            self.execute_only = False
        return self._ACTION_RETRY_SEQUENCE

    async def _handle_infra_failure(
        self, phase: str, result: PhaseResult,
    ) -> str:
        """Handle api_overloaded / stall / nonzero-exit from the agent."""
        if result.failure_reason == 'api_overloaded':
            if await self._handle_overloaded(phase) == 'retry':
                return self._ACTION_RETRY_SEQUENCE
            if self.never_escalate:
                return self._ACTION_RETURN_CURRENT
        decision = await self._failure_dialog(result.failure_reason)
        if decision == 'withdraw':
            return self._ACTION_WITHDRAW
        if decision == 'backtrack':
            self.skip_intent = False
        return self._ACTION_RETRY_SEQUENCE

    async def _try_skill_lookup(self) -> bool:
        """System 1 fast path: check the skill library for a matching skill.

        If a match is found, pre-seeds PLAN.md with the skill template so
        the planning skill runs ALIGN rather than DRAFT on its first turn
        and proposes the skill-as-plan via its own ASSERT dialog with the
        human (routed through the proxy). Returns True on match.

        If no match or any error: returns False (the planning skill cold-
        starts in DRAFT).

        If the human corrects the skill-as-plan during the skill's
        ASSERT/REVISE dialog, ``learning.phase_hooks.archive_skill_correction``
        archives the correction as a candidate after planning completes.
        """
        # Build scope-ordered skill directories: narrowest first.
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

        # Track which skill was used, storing the original template so
        # we can detect corrections later when PLAN.md diverges from it.
        self._active_skill = {
            'name': match.name,
            'path': match.path,
            'score': str(match.score),
            'scope': match.scope,
            'template': match.template,
        }

        # Persist active skill to disk so extract_learnings can find it post-session.
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
        """Build the final OrchestratorResult."""
        return OrchestratorResult(
            terminal_state=terminal_state,
            backtrack_count=self.cfa.backtrack_count,
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

            turn_cost = actor_result.data.get('cost_usd', 0.0)
            if turn_cost:
                self._total_cost_usd += turn_cost
                self._write_cost_sidecar()
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

            # action='' is the "skill turn ended without declaring an outcome"
            # sentinel.  If workers are open, wait for fan-in and re-invoke.
            # If no workers remain, raise — never silently approve.
            while actor_result.action == '':
                if self._tasks_by_child:
                    actor_result = await self._await_fan_in_and_reinvoke(
                        spec, phase_name, phase_start_time,
                    )
                    continue
                raise RuntimeError(
                    f'CfA phase {self.cfa.state!r}: skill turn ended '
                    'without writing ``.phase-outcome.json`` and no '
                    'workers are in flight.  Nothing to wait for; the '
                    'skill is incomplete.  Engine refuses to silently '
                    'approve.',
                )

            # Fan-in wait: if the lead dispatched workers via Send, hold the
            # CfA transition until all workers have replied.  The lead is then
            # re-invoked (--resume) so it can synthesize before the gate sees it.
            # Checked BEFORE _transition so the CfA state does not advance until
            # the synthesis turn returns.
            if (actor_result.action != 'failed'
                    and not is_globally_terminal(self.cfa.state)
                    and self._tasks_by_child):
                actor_result = await self._await_fan_in_and_reinvoke(
                    spec, phase_name, phase_start_time,
                )

            # Apply the CfA transition
            await self._transition(actor_result.action, actor_result)

            if (self._intervention_queue
                    and self._intervention_queue.has_pending()
                    and not is_globally_terminal(self.cfa.state)):
                await self._deliver_intervention()

            # Update scratch file BEFORE the compaction check so
            # .context/scratch.md exists when compaction fires.
            if not is_globally_terminal(self.cfa.state):
                self._update_scratch(phase_name)

            if not is_globally_terminal(self.cfa.state):
                compact_prompt = self._maybe_compact(
                    actor_result.data.get('context_budget'),
                    phase_name,
                )
                if compact_prompt:
                    self._pending_intervention = compact_prompt

    def _write_cost_sidecar(self) -> None:
        """Write the running cost total to ``{infra_dir}/.cost``.

        Consumed by the bridge dashboard (``bridge/stats.py``,
        ``bridge/state/reader.py``) and by ``cfa/dispatch.py`` as a
        fallback when per-turn events are unavailable.
        """
        if not self.infra_dir:
            return
        try:
            with open(os.path.join(self.infra_dir, '.cost'), 'w') as f:
                f.write(f'{self._total_cost_usd:.6f}\n')
        except OSError:
            pass

    def _maybe_compact(self, budget: Any, phase_name: str) -> str:
        """Return a ``/compact`` prompt when context utilization crosses
        the compact threshold; empty string otherwise.

        The caller stores the returned prompt in ``_pending_intervention``
        so ``_invoke_actor`` injects it as ``--resume`` backtrack context
        on the next turn, keeping the agent under Claude's 200k window.
        """
        if not isinstance(budget, ContextBudget) or not budget.should_compact:
            return ''
        compact_prompt = build_compact_prompt(
            cfa_state='',
            task=self._task_for_phase(phase_name),
            scratch_path='.context/scratch.md',
        )
        budget.clear_compact()
        return compact_prompt

    async def _invoke_actor(self, spec: 'PhaseSpec', phase_name: str,
                             phase_start_time: float = 0.0) -> ActorResult:
        """Dispatch to the actor for the current phase.

        In the 5-state model there is one actor — the project lead
        running the phase's skill.
        """
        state = self.cfa.state

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
            env_vars=cfa_dispatch_env_vars(
                project_slug=self.project_slug,
                project_workdir=self.project_workdir,
                infra_dir=self.infra_dir,
                session_worktree=self.session_worktree,
            ),
            add_dirs=self._build_add_dirs(),
            project_slug=self.project_slug,
            phase_start_time=phase_start_time,
            mcp_routes=self._mcp_routes,
            heartbeat_file=os.path.join(self.infra_dir, '.heartbeat'),
            parent_heartbeat=self._parent_heartbeat,
            children_file=os.path.join(self.infra_dir, '.children'),
        )

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

        # The intervention prompt replaces backtrack_context so the agent
        # receives it as the next --resume prompt at the turn boundary.
        if self._pending_intervention:
            ctx.backtrack_context = (
                (ctx.backtrack_context + '\n\n' if ctx.backtrack_context else '')
                + self._pending_intervention
            )
            self._pending_intervention = ''

        return await self._agent_runner.run(ctx)

    async def _deliver_intervention(self) -> None:
        """Drain the intervention queue, publish INTERVENE, store prompt for injection.

        Called at turn boundaries when the queue has pending messages.
        Stores the intervention prompt in ``_pending_intervention`` so
        ``_invoke_actor()`` injects it as backtrack context on the next
        agent turn (delivered via ``--resume``).
        """
        if not self._intervention_queue:
            return

        messages = self._intervention_queue.drain()
        if not messages:
            return

        prompt = build_intervention_prompt(messages, role_enforcer=self._role_enforcer)
        self._pending_intervention = prompt
        self._intervention_active = True

        try:
            current_phase = phase_for_state(self.cfa.state)
        except ValueError:
            current_phase = 'unknown'

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
        written by withdraw_session().
        """
        _log.info('External withdrawal received for session %s', session_id)
        self.cfa = set_state_direct(self.cfa, 'WITHDRAWN')


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

    def _update_scratch(self, phase_name: str) -> None:
        """Serialize the scratch model to disk at a turn boundary."""
        self._scratch_model.phase = phase_name
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
        if new_state == 'WITHDRAWN':
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

        # Backtrack: cascade-withdraw if phase moved earlier
        try:
            old_phase = phase_for_state(old_state)
            new_phase = phase_for_state(new_state)
        except ValueError:
            self._intervention_active = False
            write_intervention_outcome(
                infra_dir=self.infra_dir,
                outcome='continue',
            )
            return

        if is_backtrack(old_phase, new_phase):
            withdrawn = cascade_withdraw_children(self.infra_dir)
            self._intervention_active = False
            write_intervention_outcome(
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

        # Continue/adjustment: same-phase or forward transition.
        self._intervention_active = False
        write_intervention_outcome(
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

        if self._ask_question_runner:
            self._ask_question_runner.cfa_state = self.cfa.state

        self._last_actor_data = actor_result.data
        if actor_result.feedback:
            self._last_actor_data['feedback'] = actor_result.feedback
        if actor_result.dialog_history:
            self._last_actor_data['dialog_history'] = actor_result.dialog_history

        claude_sid = actor_result.data.get('claude_session_id', '')
        if claude_sid:
            phase = phase_for_state(self.cfa.state)
            self._phase_session_ids[phase] = claude_sid
            self._update_lead_bus_session(claude_sid)

        state_path = os.path.join(self.infra_dir, '.cfa-state.json')
        save_state(self.cfa, state_path)

        try:
            from teaparty.telemetry import record_event
            from teaparty.telemetry import events as _telem_events
            _scope = self.project_slug or 'management'
            old_phase = phase_for_state(old_state)
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
                    'old_phase':     old_phase,
                    'new_phase':     self.cfa.phase,
                    'action':        action,
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
                'previous_state': old_state,
                'action': action,
                'history': self.cfa.history,
                'backtrack_count': self.cfa.backtrack_count,
            },
            session_id=self.session_id,
        ))

        await self._check_interrupt_propagation(old_state)

        await self._commit_artifacts(old_state, action)

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

    def _phase_spec(self, phase_name: str) -> 'PhaseSpec':
        """Get the phase spec, accounting for team and flat overrides."""
        from dataclasses import replace
        if self.team_override:
            team = self.config.team(self.team_override)
            base = self.config.phase(phase_name)
            # Teams can specify their own planning permission mode
            # (e.g., subteams use 'plan' for tactical planning).
            perm = (
                team.planning_permission_mode
                if phase_name == 'planning' and team.planning_permission_mode
                else base.permission_mode
            )
            return replace(
                base,
                agent_file=team.agent_file,
                lead=team.lead,
                permission_mode=perm,
            )

        base = self.config.resolve_phase(phase_name)

        # --flat: swap the project team for a flat team where the lead
        # recruits agents dynamically via the Agent tool.  Only affects
        # phases that use uber-team.json (planning, execution).
        if self.flat and base.agent_file == 'uber':
            return replace(base, agent_file='flat')

        return base

    def _task_for_phase(self, phase_name: str) -> str:
        """Get the task description for a phase.

        Intent phase: uses the original task description, with constraints
            (resolved norms) and escalation guidance injected.
        Planning phase: reads INTENT.md (the intent phase's output), with
            dynamically-resolved available teams injected.
        Execution phase: reads PLAN.md as the workflow to follow,
            with INTENT.md appended as reference context.
        """
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
            base_task = self.task or self.project_slug

        # Prepend CfA phase framing.  agent.md is role-only; this layer
        # supplies deliverable, boundary, and re-entry rule per phase.
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

        if phase_name == 'intent':
            from teaparty.config.phase_context import intent_constraints_block
            constraints = intent_constraints_block(
                project_dir=self.project_dir,
                teaparty_home=self.teaparty_home,
            )
            if constraints:
                base_task += constraints
        elif phase_name == 'planning':
            from teaparty.config.phase_context import available_teams_block
            teams_block = available_teams_block(
                project_teams=self.config.project_teams,
                project_workdir=self.project_workdir,
                team_override=self.team_override,
            )
            if teams_block:
                base_task += teams_block

        return base_task

    # Maximum auto-retries for API overloaded (529) before escalating to human.
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

    def _build_add_dirs(self) -> list[str]:
        # Agents must not receive --add-dir flags; the worktree (set as cwd)
        # contains everything they need.
        return []

