"""Shared helpers for tier spawn_fns (CfA engine + chat-tier AgentSession).

Both tiers implement a ``spawn_fn(member, composite, context_id)`` that
``Send`` routes to via the in-process MCP registry.  The prelude of
those functions — thread-continuation detection, slot / pause checks,
child session creation, worktree setup, bus DISPATCH registration —
and the child subtree lifecycle — launch, gather grandchildren,
``--resume`` with integrated replies, repeat — are the same mechanism
across tiers.  This module holds the pieces both sides share.

It also owns ``build_session_dispatcher``, the single place that turns
session config (a project workgroup tree, or the OM's management
roster) into the ``BusDispatcher`` the Send tool authorizes against.
Routing tables key directly on agent names — same identifiers used
everywhere else in the system; an agent's name is its identity.
Routing enforcement at Send-time is the same mechanism for both tiers;
the only thing that differs is which roster the table is derived from,
so that distinction lives here in one function rather than repeated at
each tier boot.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from teaparty.messaging.conversations import (
    ConversationState,
    ConversationType,
    SqliteMessageBus,
)

_log = logging.getLogger('teaparty.messaging.child_dispatch')


def build_session_dispatcher(
    *,
    teaparty_home: str,
    lead_name: str,
    parent_lead: str = '',
) -> Any | None:
    """Build the ``BusDispatcher`` for a session led by ``lead_name``.

    The dispatcher is the single transport-level enforcement point Send
    consults before invoking ``spawn_fn``: an agent whose prompt is
    broken or hostile cannot reach a recipient outside its permitted
    set, because Send refuses the post before it touches the bus.

    A session always has a lead (the agent the session was launched
    for: OM, project lead, workgroup lead).  Leads are in 1:1
    correspondence with their team, so :func:`derive_team_roster`
    looks up that team's roster unambiguously, and
    ``build_routing_table`` consumes it.

    ``parent_lead`` is a property of the *conversation* — the
    dispatcher that initiated this session.  For a top-level session
    (e.g. OM chat) it's empty; for a dispatched child it's the
    dispatcher's agent name.  This lets the same workgroup loaned to
    different projects (matrix loan) carry a different gateway pair
    in each conversation without changing the team itself.

    Returns ``None`` when the lead isn't a known lead or the relevant
    config is missing.  Send treats absent dispatcher as
    "no enforcement".
    """
    from teaparty.messaging.dispatcher import BusDispatcher, build_routing_table
    from teaparty.config.roster import derive_team_roster

    if not lead_name:
        return None

    try:
        roster = derive_team_roster(
            lead_name, teaparty_home, parent_lead=parent_lead,
        )
    except (FileNotFoundError, OSError):
        return None
    except Exception:
        _log.debug(
            'derive_team_roster failed (lead_name=%r)', lead_name,
            exc_info=True,
        )
        return None

    if roster is None or not roster.lead:
        return None

    return BusDispatcher(build_routing_table(roster))


def detect_thread_continuation(
    *,
    context_id: str,
    bus_db_path: str,
    member: str,
    teaparty_home: str,
    scope: str,
) -> Any | None:
    """Return an existing child ``Session`` when ``context_id`` names an
    already-ACTIVE dispatch to *member*, or ``None`` to spawn a fresh one.

    ``Send`` accepts an optional ``context_id`` of the form
    ``dispatch:<child_session_id>``.  When the caller passes one and that
    dispatch is still ACTIVE with the same recipient agent, the tier
    should re-launch that child's on-disk session with ``--resume``
    rather than fork a new worktree and session — the human (or agent)
    is continuing an open conversation.

    This helper is the single place that reads the bus row and loads the
    session.  Caller decides what to do with the result: passing the
    returned ``Session`` into ``launch(resume_session=...)`` keeps the
    child's claude session continuous; passing ``None`` triggers the
    fresh-spawn path.
    """
    if not context_id or not context_id.startswith('dispatch:'):
        return None
    if not bus_db_path:
        return None

    bus = SqliteMessageBus(bus_db_path)
    try:
        conv = bus.get_conversation(context_id)
    finally:
        bus.close()

    if conv is None:
        return None
    if conv.state != ConversationState.ACTIVE:
        return None
    if conv.agent_name != member:
        return None

    from teaparty.runners.launcher import load_session as _load_session
    child_sid = context_id[len('dispatch:'):]
    return _load_session(
        agent_name=member,
        scope=scope,
        teaparty_home=teaparty_home,
        session_id=child_sid,
    )


async def run_subtree_loop(
    *,
    agent_name: str,
    initial_message: str,
    bus: Any,
    conv_id: str,
    session: Any,
    tasks_by_child: dict[str, asyncio.Task],
    results_by_child: dict[str, str],
    launch_fn: Any,
    launch_kwargs_base: dict,
    resume_claude_session: str = '',
    on_phase: Any = None,
) -> tuple[str, list[tuple[str, str]]]:
    """ONE lifecycle, both tiers.

    Drive an agent through claude turns, gather grandchild dispatches
    between turns, re-launch with their replies, fan-in fallback when
    the agent stays silent.  Used by every agent execution path:

      * top-level chat: ``AgentSession.invoke`` calls this with the
        user's chat conversation as ``conv_id``.
      * dispatched children: ``run_child_lifecycle`` calls this with
        the dispatch conversation as ``conv_id``.

    The unified shape kills the asymmetry that produced silent relay
    failures — there is no "top-level path" vs. "dispatched path"
    with their own re-launch mechanisms anymore.

    Returns ``(response_text, events)``:
      * ``response_text`` is the agent's text from the final turn,
        falling back to the most recent grandchild payload when the
        agent contributed nothing on a relay turn.
      * ``events`` is the full ``(sender, content)`` stream — useful
        for poisoned-session detection at the call site.

    ``launch_kwargs_base`` is the static set of kwargs to pass to
    ``launch_fn`` every iteration.  ``message``, ``on_stream_event``,
    and ``resume_session`` are populated by the loop.

    ``on_phase`` (optional) is called with:

      * ``('launching', message)`` — before each launch, with the
        message about to be sent to claude.
      * ``('launched', session)``  — after each successful launch,
        with ``session.claude_session_id`` updated; dispatched
        children persist this to disk so a cross-restart resume can
        pick up the claude session id.
      * ``('awaiting', list_of_gc_ids)`` — before the gather of
        newly-dispatched grandchildren.
      * ``('complete', response_text)`` — at loop exit.

    Top-level chat passes ``None``.
    """
    from teaparty.teams.stream import _classify_event

    t0 = time.monotonic()
    seen_tu: set[str] = set()
    seen_tr: set[str] = set()
    response_parts: list[str] = []
    events: list[tuple[str, str]] = []
    last_gc_payload: str = ''
    current_message = initial_message
    current_claude_session = resume_claude_session or ''

    def on_event(ev: dict) -> None:
        for sender, content in _classify_event(
                ev, agent_name, seen_tu, seen_tr):
            if content:
                bus.send(conv_id, sender, content)
                events.append((sender, content))
            if sender == agent_name and content:
                response_parts.append(content)

    while True:
        before_ids = {
            c.id[len('dispatch:'):]
            for c in bus.children_of(conv_id)
            if c.id.startswith('dispatch:')
        }
        response_parts.clear()

        launch_kwargs = dict(launch_kwargs_base)
        launch_kwargs['message'] = current_message
        launch_kwargs['on_stream_event'] = on_event
        if current_claude_session:
            launch_kwargs['resume_session'] = current_claude_session

        if on_phase is not None:
            try:
                on_phase('launching', current_message)
            except Exception:
                _log.debug(
                    'on_phase(launching) raised', exc_info=True,
                )

        try:
            result = await launch_fn(**launch_kwargs)
            if result.session_id:
                session.claude_session_id = result.session_id
                current_claude_session = result.session_id
                if on_phase is not None:
                    try:
                        on_phase('launched', session)
                    except Exception:
                        _log.debug(
                            'on_phase(launched) raised', exc_info=True,
                        )
        except Exception:
            _log.exception('%s subtree loop launch failed', agent_name)
            break

        after_ids = {
            c.id[len('dispatch:'):]
            for c in bus.children_of(conv_id)
            if c.id.startswith('dispatch:')
        }
        new_gc_ids = after_ids - before_ids
        if not new_gc_ids:
            break

        # Resolve each new grandchild into either a still-running
        # task (await it) or an already-known result (pluck from
        # results_by_child).  A subtree can run to completion while
        # the parent's launch is still streaming claude events; the
        # completed task pops itself from tasks_by_child but stores
        # its response in results_by_child, so we never lose it.
        new_gc_list = sorted(new_gc_ids)
        pending_tasks: list[asyncio.Task] = []
        pending_ids: list[str] = []
        gc_replies: list[str] = []
        for g in new_gc_list:
            if g in tasks_by_child:
                pending_tasks.append(tasks_by_child[g])
                pending_ids.append(g)
            elif g in results_by_child:
                r = results_by_child[g]
                if r:
                    gc_replies.append(f'[dispatch:{g}] {r}')

        if not pending_tasks and not gc_replies:
            break

        if on_phase is not None:
            try:
                on_phase('awaiting', list(new_gc_ids))
            except Exception:
                _log.debug(
                    'on_phase(awaiting) raised', exc_info=True,
                )

        if pending_tasks:
            gc_results = await asyncio.gather(
                *pending_tasks, return_exceptions=True,
            )
            for gid, r in zip(pending_ids, gc_results):
                if isinstance(r, str) and r:
                    gc_replies.append(f'[dispatch:{gid}] {r}')
                elif isinstance(r, Exception) and not isinstance(
                        r, asyncio.CancelledError):
                    _log.warning('Grandchild %s raised: %s', gid, r)

        if not gc_replies:
            break
        last_gc_payload = '\n'.join(gc_replies)
        current_message = last_gc_payload

    _log.info(
        '%s subtree completed in %.2fs', agent_name, time.monotonic() - t0,
    )

    # Fan-in fallback: an agent that contributed no text on a resume
    # turn is exercising autonomy ("nothing to add"); the chain must
    # not lose the children's contribution because of it.  When
    # ``response_parts`` is empty, surface ``last_gc_payload`` as
    # the agent's response — and write it to the bus too, so a silent
    # agent's relay appears in the user's chat blade rather than
    # propagating only as a function return value.
    if response_parts:
        response_text = '\n'.join(response_parts)
    elif last_gc_payload:
        response_text = last_gc_payload
        bus.send(conv_id, agent_name, response_text)
        events.append((agent_name, response_text))
    else:
        response_text = ''
    if on_phase is not None:
        try:
            on_phase('complete', response_text)
        except Exception:
            _log.debug('on_phase(complete) raised', exc_info=True)
    return response_text, events


async def run_child_lifecycle(
    *,
    member: str,
    child_session: Any,
    worktree_path: str,
    composite: str,
    child_conv_id: str,
    bus: Any,
    tasks_by_child: dict[str, asyncio.Task],
    results_by_child: dict[str, str],
    launch_fn: Any,
    mcp_routes: Any = None,
    llm_caller: Any = None,
    member_scope: str = '',
    member_teaparty_home: str = '',
    telemetry_scope: str = '',
    start_at_phase: str = 'launching',
    initial_gc_task_ids: list[str] | None = None,
    resume_claude_session: str = '',
) -> str:
    """Drive a dispatched child through its subtree.

    Thin wrapper over :func:`run_subtree_loop` that adds the
    dispatched-child specifics: phase markers (so the pause walker
    can reconstruct from disk), session-metadata persistence, and
    the cross-restart resume path (``start_at_phase='awaiting'``)
    that skips an already-completed initial launch.

    The actual loop — launch / gather / re-launch / fan-in — lives
    in :func:`run_subtree_loop` and is shared with the top-level
    chat path.

    ``launch_fn`` is the ``launcher.launch`` coroutine captured by
    the caller before spawning so tests can monkeypatch
    ``launcher.launch`` at the spawn call site without racing the
    background task's import.
    """
    from teaparty.runners.launcher import (
        _save_session_metadata as _save_meta,
        mark_launching as _mark_launching,
        mark_awaiting as _mark_awaiting,
        mark_complete as _mark_complete,
    )

    mcp_port = int(os.environ.get('TEAPARTY_BRIDGE_PORT', '9000'))

    # Cross-restart resume: a previous run had already kicked off
    # grandchildren and exited (e.g. bridge restart).  Skip the
    # initial launch and enter at the gather; transform the
    # grandchildren's eventual replies into the loop's first
    # ``initial_message``.  Same race as the in-loop gather: a
    # grandchild may already be done and live in ``results_by_child``
    # rather than ``tasks_by_child``.
    initial_message = composite
    if start_at_phase == 'awaiting':
        ids = list(initial_gc_task_ids or [])
        pending_tasks: list[asyncio.Task] = []
        pending_ids: list[str] = []
        gc_replies: list[str] = []
        for g in ids:
            if g in tasks_by_child:
                pending_tasks.append(tasks_by_child[g])
                pending_ids.append(g)
            elif g in results_by_child:
                r = results_by_child[g]
                if r:
                    gc_replies.append(f'[dispatch:{g}] {r}')
        if pending_tasks or gc_replies:
            _mark_awaiting(child_session, ids)
            if pending_tasks:
                gc_results = await asyncio.gather(
                    *pending_tasks, return_exceptions=True,
                )
                for gid, r in zip(pending_ids, gc_results):
                    if isinstance(r, str) and r:
                        gc_replies.append(f'[dispatch:{gid}] {r}')
            if gc_replies:
                initial_message = '\n'.join(gc_replies)

    if worktree_path:
        # Same-repo dispatch: child runs inside its own worktree.
        launch_kwargs_base = dict(
            agent_name=member,
            scope=member_scope, teaparty_home=member_teaparty_home,
            telemetry_scope=telemetry_scope,
            worktree=worktree_path,
            mcp_port=mcp_port,
            session_id=child_session.id,
            stream_file=os.path.join(child_session.path, 'stream.jsonl'),
        )
    else:
        # Cross-repo dispatch: child is a project lead running
        # directly at its own repo root.  Config files live under
        # the member's teaparty home.
        from teaparty.runners.launcher import chat_config_dir as _chat_cfg_dir
        child_config_dir = _chat_cfg_dir(
            member_teaparty_home, member_scope,
            member, child_session.id,
        )
        launch_kwargs_base = dict(
            agent_name=member,
            scope=member_scope, teaparty_home=member_teaparty_home,
            telemetry_scope=telemetry_scope,
            tier='chat',
            launch_cwd=child_session.launch_cwd,
            config_dir=child_config_dir,
            mcp_port=mcp_port,
            session_id=child_session.id,
            stream_file=os.path.join(child_session.path, 'stream.jsonl'),
        )
    if llm_caller is not None:
        launch_kwargs_base['llm_caller'] = llm_caller
    launch_kwargs_base['mcp_routes'] = mcp_routes
    launch_kwargs_base['caller_conversation_id'] = child_conv_id

    def _on_phase(phase: str, payload: Any) -> None:
        if phase == 'launching':
            _mark_launching(child_session, payload)
        elif phase == 'launched':
            # Persist the updated claude_session_id so a cross-restart
            # resume can pick up the same claude session id and
            # re-attach via --resume.
            _save_meta(child_session)
        elif phase == 'awaiting':
            _mark_awaiting(child_session, payload)
        elif phase == 'complete':
            _mark_complete(child_session, payload)

    response_text, _events = await run_subtree_loop(
        agent_name=member,
        initial_message=initial_message,
        bus=bus,
        conv_id=child_conv_id,
        session=child_session,
        tasks_by_child=tasks_by_child,
        results_by_child=results_by_child,
        launch_fn=launch_fn,
        launch_kwargs_base=launch_kwargs_base,
        resume_claude_session=resume_claude_session,
        on_phase=_on_phase,
    )
    return response_text


# ── Unified spawn_fn prelude (Cut 24) ─────────────────────────────────────
#
# Both tiers (CfA engine + chat-tier AgentSession) used to implement a
# ~250-line spawn_fn each that did the same nine prelude steps in the
# same order: resolve dispatcher, detect thread continuation, slot
# check, paused check, validate member, read parent_conv_id, branch on
# existing_child (reuse vs. create+worktree), write DISPATCH row, send
# parent's request to bus, schedule the lifecycle task.  Cut 17 already
# extracted ``run_child_lifecycle`` (the loop that runs after spawn);
# this is the matching extraction for the prelude.
#
# Tier-specific behavior is parameterized through ``ChildDispatchContext``
# and a small set of optional callbacks; the unified prelude itself has
# no tier-specific branches except where they're genuinely necessary
# (cross-repo dispatch is chat-tier only; fan-in delivery uses
# different mechanisms in CfA vs. chat).


@dataclass
class ChildDispatchContext:
    """Per-session state both tiers share to spawn dispatched children.

    Built once at session boot.  ``make_spawn_fn(ctx)`` returns the
    ``spawn_fn(member, composite, context_id)`` callable suitable for
    registration in the MCP registry via ``MCPRoutes.spawn_fn``.

    The dataclass collects the dispatcher's identity, the per-session
    registries the spawn function mutates, configuration that varies
    per session, and a small number of tier-specific behavior knobs
    (``fixed_scope``, ``cross_repo_supported``).  Tier-specific
    post-lifecycle behavior (CfA's reply-injection vs. chat-tier's
    re-invoke-the-lead) is plumbed through ``on_child_complete``.
    """

    # ── Dispatcher identity + bus ───────────────────────────────────────
    dispatcher_session: Any
    bus: SqliteMessageBus
    bus_listener: Any

    # ── Per-session registries (mutated by the spawn function) ─────────
    session_registry: dict[str, Any]
    tasks_by_child: dict[str, Any]
    # ``results_by_child`` persists each child's response_text after
    # the child task completes and pops itself from
    # ``tasks_by_child``.  Without this persistence, a parent whose
    # claude was still streaming when the child task ran to completion
    # and popped would later read ``g in tasks_by_child`` → False and
    # break its loop early — losing the child's contribution.  This
    # was the cause of the intermittent "joke didn't come back"
    # failures: deep, fast subchains can fully complete while the
    # parent's launch is still awaiting claude's stream events.
    results_by_child: dict[str, str] = field(default_factory=dict)
    factory_registry: dict[str, Any] | None = None  # chat tier only

    # ── Configuration ──────────────────────────────────────────────────
    teaparty_home: str = ''
    project_slug: str = ''
    repo_root: str = ''
    telemetry_scope: str = ''

    # ── Tier-specific behavior knobs ───────────────────────────────────
    # ``fixed_scope`` set → spawn_fn always uses that scope (CfA's
    # 'management').  None → spawn_fn calls resolve_launch_placement to
    # pick the recipient's natural scope (chat tier).
    fixed_scope: str | None = None
    # ``cross_repo_supported`` True → recipient can dispatch into a
    # different repo than the dispatcher (chat tier).  False → all
    # children fork from the dispatcher's worktree (CfA).
    cross_repo_supported: bool = False
    # Static label identifying the spawn_fn site for log messages.
    log_tag: str = 'spawn_fn'

    # ── Optional injected dependencies ─────────────────────────────────
    paused_check: Callable[[], bool] | None = None
    mcp_routes: Any = None
    on_dispatch: Callable[[dict], Any] | None = None
    background_tasks: set | None = None
    llm_caller: Any = None

    # ── Tier-specific hooks ────────────────────────────────────────────
    # Called AFTER ``run_child_lifecycle`` returns (success or failure),
    # inside the child task's ``finally``.  Tier supplies its own:
    # CfA injects the reply into the lead's claude session and signals
    # its fan_in_event; chat tier re-invokes the lead via ``invoke``.
    # Signature: ``async (child_session, response_text) -> None``.
    on_child_complete: Callable[..., Awaitable[None]] | None = None


def make_spawn_fn(
    ctx: ChildDispatchContext,
) -> Callable[[str, str, str], Awaitable[tuple[str, str, str]]]:
    """Build a tier-agnostic ``spawn_fn`` from a ``ChildDispatchContext``.

    The returned callable has the signature ``Send`` expects:
    ``async fn(member, composite, context_id) -> (session_id, worktree, refusal_reason)``.
    Both tiers register the result via ``MCPRoutes.spawn_fn``.
    """
    async def spawn_fn(
        member: str, composite: str, context_id: str,
    ) -> tuple[str, str, str]:
        return await schedule_child_dispatch(
            member, composite, context_id, ctx=ctx,
        )
    return spawn_fn


async def schedule_child_dispatch(
    member: str,
    composite: str,
    context_id: str,
    *,
    ctx: ChildDispatchContext,
) -> tuple[str, str, str]:
    """Run the unified spawn_fn prelude for both tiers.

    This is what every dispatched child goes through, regardless of
    tier.  Returns ``(child_session_id, worktree_path, refusal_reason)``
    matching the Send tool's contract: empty session_id signals refusal
    with ``refusal_reason`` carrying the cause code.
    """
    from teaparty.runners.launcher import (
        create_session as _create_session,
        check_slot_available as _check_slot,
        load_session as _load_session,
        _save_session_metadata as _save_meta,
        launch as _spawn_launch,
    )
    from teaparty.workspace.worktree import (
        default_branch_of, current_branch_of, head_commit_of,
        create_subchat_worktree,
    )
    from teaparty.config.roster import (
        resolve_launch_placement, LaunchCwdNotResolved,
    )
    from teaparty.mcp.registry import (
        current_session_id as _current_session_var,
        current_conversation_id as _current_conv_var,
    )

    # ── 1. Resolve which session is dispatching ─────────────────────────
    # Grandchildren attach under their own session, not the root's.  The
    # MCP middleware sets current_session_id per-request from the URL.
    caller_sid = _current_session_var.get('')
    dispatcher_session = ctx.session_registry.get(
        caller_sid, ctx.dispatcher_session,
    )

    # ── 2. Thread continuation ──────────────────────────────────────────
    bus_db_path = ctx.bus_listener.bus_db_path if ctx.bus_listener else ''
    existing_child = detect_thread_continuation(
        context_id=context_id,
        bus_db_path=bus_db_path,
        member=member,
        teaparty_home=ctx.teaparty_home,
        scope=ctx.fixed_scope or 'management',
    )

    # ── 3. Paused-check refusal (skipped on resume) ─────────────────────
    if existing_child is None and ctx.paused_check is not None and ctx.paused_check():
        _log.warning(
            '%s: project %s paused, dispatch to %s refused',
            ctx.log_tag, ctx.project_slug, member,
        )
        return ('', '', 'paused')

    # ── 4. Validate member via the registry ─────────────────────────────
    try:
        member_natural_repo, member_resolved_scope = resolve_launch_placement(
            member, ctx.teaparty_home,
        )
    except LaunchCwdNotResolved as exc:
        _log.warning(
            '%s: refusing dispatch to %r — %s',
            ctx.log_tag, member, exc,
        )
        return ('', '', f'unresolved_member:{member}')

    member_scope = ctx.fixed_scope or member_resolved_scope
    member_teaparty_home = (
        ctx.teaparty_home if ctx.fixed_scope
        else os.path.join(member_natural_repo, '.teaparty')
    )

    # ── 5. Read parent_conv_id from contextvar (no derivation fallback) ─
    parent_conv_id = _current_conv_var.get('')
    if not parent_conv_id:
        raise RuntimeError(
            f'{ctx.log_tag}: current_conversation_id is empty.  '
            f'``launch()`` must pass ``caller_conversation_id=`` so the '
            f'MCP middleware can set the contextvar; an empty value means '
            f'the launch site forgot it.  Refusing rather than silently '
            f'parenting under the wrong conv_id.',
        )

    # ── 6. Slot-limit check (skipped on resume) ─────────────────────────
    if existing_child is None:
        if not _check_slot(
            dispatcher_session, bus=ctx.bus, conv_id=parent_conv_id,
        ):
            _log.warning(
                '%s: at conversation limit (parent %s); dispatch to %s blocked',
                ctx.log_tag, parent_conv_id, member,
            )
            return ('', '', 'slot_limit')

    # ── 7. Branch on existing_child: reuse vs. create+worktree ──────────
    if existing_child is not None:
        child_session = existing_child
        worktree_path = child_session.worktree_path
        member_launch_cwd = child_session.launch_cwd or member_natural_repo
    else:
        # Source repo + merge target: derived from the dispatcher's
        # current state.  Both tiers reduce to the same expression once
        # ``dispatcher_session`` is unified — its ``worktree_path`` is
        # set when the dispatcher is itself a dispatched child.
        if dispatcher_session.worktree_path:
            dispatcher_worktree = dispatcher_session.worktree_path
            dispatcher_repo = (
                dispatcher_session.merge_target_repo or ctx.repo_root
            )
        else:
            dispatcher_worktree = (
                dispatcher_session.launch_cwd or ctx.repo_root
            )
            dispatcher_repo = dispatcher_worktree

        is_cross_repo = ctx.cross_repo_supported and (
            os.path.realpath(member_natural_repo)
            != os.path.realpath(dispatcher_repo)
        )

        if is_cross_repo:
            source_repo = member_natural_repo
            source_ref = await default_branch_of(source_repo)
            merge_target_repo = source_repo
            merge_target_branch = source_ref
            merge_target_worktree = source_repo
        else:
            source_repo = dispatcher_worktree
            try:
                source_ref = await head_commit_of(dispatcher_worktree) or 'HEAD'
            except Exception:
                source_ref = 'HEAD'
            merge_target_repo = dispatcher_repo
            merge_target_worktree = dispatcher_worktree
            try:
                merge_target_branch = (
                    await current_branch_of(dispatcher_worktree)
                )
            except Exception:
                merge_target_branch = ''

        child_session = _create_session(
            agent_name=member, scope=member_scope,
            teaparty_home=ctx.teaparty_home,
        )

        if is_cross_repo:
            worktree_path = ''
            member_launch_cwd = member_natural_repo
        else:
            worktree_path = os.path.join(child_session.path, 'worktree')
            member_launch_cwd = worktree_path

        # ── 8. Write DISPATCH row in bus FIRST (single source of truth) ─
        # Recording intent before attempting the worktree creation
        # means a failed worktree leaves an ACTIVE row recovery can
        # see — better than silently dropping the dispatch record.
        # Recovery later closes ACTIVE rows whose process is dead.
        ctx.bus.create_conversation(
            ConversationType.DISPATCH, child_session.id,
            agent_name=member,
            parent_conversation_id=parent_conv_id,
            request_id=context_id,
            project_slug=ctx.project_slug or '',
            state=ConversationState.ACTIVE,
            worktree_path=worktree_path,
        )

        if is_cross_repo:
            # Cross-repo: child works directly at its repo root, no worktree.
            child_session.launch_cwd = member_natural_repo
            child_session.worktree_path = ''
            child_session.worktree_branch = ''
            child_session.merge_target_repo = ''
            child_session.merge_target_branch = ''
            child_session.merge_target_worktree = ''
        else:
            session_branch = f'session/{child_session.id}'
            try:
                await create_subchat_worktree(
                    source_repo=source_repo,
                    source_ref=source_ref,
                    dest_path=worktree_path,
                    branch_name=session_branch,
                    parent_worktree=dispatcher_worktree,
                )
            except Exception:
                _log.exception(
                    '%s: create_subchat_worktree failed for %s',
                    ctx.log_tag, member,
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
        child_session.project_slug = ctx.project_slug or ''
        _save_meta(child_session)

    child_session.initial_message = composite
    _save_meta(child_session)

    # Track the child so its own Send calls resolve to the right
    # dispatcher_session via current_session_id.
    ctx.session_registry[child_session.id] = child_session

    child_conv_id = f'dispatch:{child_session.id}'

    # Write the parent's request to the bus (visible in child chat).
    ctx.bus.send(child_conv_id, dispatcher_session.agent_name or 'parent', composite)

    # ── 9. Build the child's MCPRoutes ──────────────────────────────────
    # Routing scope is a property of THIS dispatch — set here, where
    # the dispatcher's identity and config tree are known, then carried
    # into the child's launch.  The launcher just registers what it's
    # given; it does not re-derive a roster from a config tree at the
    # receiving end (that produced "which teaparty_home?" ambiguities
    # for cross-repo dispatches and couldn't model matrix-loan
    # parent_leads).
    #
    # ``parent_lead`` = the dispatcher itself: comics-lead loaning the
    # Coding workgroup sets parent_lead=comics-lead; joke-book-lead
    # loaning the same workgroup sets parent_lead=joke-book-lead.
    # ``teaparty_home`` = the dispatcher's tp: that is the org tree
    # where the recipient is registered (a project's local tp is for
    # execution artifacts; routing is an org-level concern).
    from teaparty.mcp.registry import MCPRoutes
    parent_lead = dispatcher_session.agent_name or ''
    child_dispatcher = build_session_dispatcher(
        teaparty_home=ctx.teaparty_home,
        lead_name=member,
        parent_lead=parent_lead,
    )
    if child_dispatcher is None and ctx.mcp_routes is not None:
        # Non-lead recipient (e.g. a workgroup-agent leaf): no team of
        # their own.  Inherit the dispatcher's scope — that's the team
        # this leaf is operating in, and the (leaf↔dispatcher) gateway
        # pair already exists there.
        child_dispatcher = ctx.mcp_routes.dispatcher
    base_routes = ctx.mcp_routes
    child_mcp_routes = MCPRoutes(
        spawn_fn=base_routes.spawn_fn if base_routes else None,
        close_fn=base_routes.close_fn if base_routes else None,
        ask_question_runner=(
            base_routes.ask_question_runner if base_routes else None
        ),
        dispatcher=child_dispatcher,
    )

    initial_resume_sid = (
        child_session.claude_session_id or ''
        if existing_child is not None else ''
    )

    async def _run_child(
        start_at_phase: str = 'launching',
        initial_gc_task_ids: list[str] | None = None,
        resume_claude_session: str = initial_resume_sid,
    ) -> str:
        """Wrap run_child_lifecycle with shared cleanup + tier hook."""
        response_text = ''
        try:
            response_text = await run_child_lifecycle(
                member=member,
                child_session=child_session,
                worktree_path=worktree_path,
                composite=composite,
                child_conv_id=child_conv_id,
                bus=ctx.bus,
                tasks_by_child=ctx.tasks_by_child,
                results_by_child=ctx.results_by_child,
                launch_fn=_spawn_launch,
                mcp_routes=child_mcp_routes,
                llm_caller=ctx.llm_caller,
                member_scope=member_scope,
                member_teaparty_home=member_teaparty_home,
                telemetry_scope=ctx.telemetry_scope,
                start_at_phase=start_at_phase,
                initial_gc_task_ids=initial_gc_task_ids,
                resume_claude_session=resume_claude_session,
            )
        except Exception:
            _log.exception(
                '%s: child task failed for %s', ctx.log_tag, member,
            )
            response_text = ''
        finally:
            # Persist the result BEFORE popping from tasks_by_child.
            # The parent's gather may run after our pop; without
            # ``results_by_child`` it would lose the child's
            # contribution.
            ctx.results_by_child[child_session.id] = response_text
            # Remove this child from the in-flight set — both tiers
            # used to do this independently with slightly different
            # bookkeeping; one place now.
            ctx.tasks_by_child.pop(child_session.id, None)
            if ctx.on_child_complete is not None:
                try:
                    await ctx.on_child_complete(child_session, response_text)
                except Exception:
                    _log.exception(
                        '%s: on_child_complete hook raised for %s',
                        ctx.log_tag, member,
                    )
        return response_text

    # Chat tier records pause/resume factories; CfA passes None.
    if ctx.factory_registry is not None:
        ctx.factory_registry[child_session.id] = _run_child

    ctx.bus_listener.schedule_child_task(
        child_session_id=child_session.id,
        launch_coro=_run_child(),
        dispatcher_session=dispatcher_session,
        context_id=context_id,
        agent_name=member,
        on_dispatch=ctx.on_dispatch,
        background_tasks=ctx.background_tasks,
    )

    _log.info(
        '%s: dispatched to %s (async)', ctx.log_tag, member,
    )
    return (child_session.id, member_launch_cwd, '')
