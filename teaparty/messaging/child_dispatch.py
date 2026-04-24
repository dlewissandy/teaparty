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
roster) into the ``(BusDispatcher, agent_id_map)`` pair the Send tool
authorizes against.  Routing enforcement at Send-time is the same
mechanism for both tiers; the only thing that differs is which roster
the table is derived from, so that distinction lives here in one
function rather than repeated at each tier boot.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from teaparty.messaging.conversations import (
    ConversationState,
    SqliteMessageBus,
)

_log = logging.getLogger('teaparty.messaging.child_dispatch')


def build_session_dispatcher(
    *,
    teaparty_home: str,
    project_dir: str = '',
    project_slug: str = '',
) -> tuple[Any | None, dict[str, str]]:
    """Build the ``(BusDispatcher, agent_id_map)`` pair for a session.

    The dispatcher is the single transport-level enforcement point Send
    consults before invoking ``spawn_fn``: an agent whose prompt is
    broken or hostile cannot reach a recipient outside its permitted
    set, because Send refuses the post before it touches the bus.

    The matching ``agent_id_map`` translates the names agents use in
    their roster (what Send sees as ``member``) into the scoped
    ``{project}/{workgroup}/{role}``-style agent IDs the routing table
    keys on.  The Send handler resolves both sender and recipient
    through this map before authorizing.

    ``project_dir`` empty → **OM session**.  Builds the routing table
    from the OM's management roster (``OM ↔ each project-lead`` and
    ``OM ↔ each management agent``) plus the matching name → id map at
    the ``om`` level.

    ``project_dir`` set → **project-lead session**.  Builds the routing
    table from the project's resolved workgroups
    (``OM ↔ project-lead``, ``project-lead ↔ each workgroup lead``,
    full mesh within each workgroup) plus the matching name → id map at
    the ``project`` level.

    Returns ``(None, {})`` when the relevant config is missing or empty
    — bootstrap state, scripted tests, projects without YAML.  Send
    treats absent dispatcher as "no enforcement", which preserves the
    pre-#422 default.
    """
    from teaparty.messaging.dispatcher import BusDispatcher, RoutingTable
    from teaparty.config.roster import (
        derive_om_roster,
        agent_id_map as build_agent_id_map,
    )

    if project_dir:
        from teaparty.config.config_reader import (
            resolve_workgroups, load_project_team,
        )

        try:
            proj = load_project_team(project_dir)
        except (FileNotFoundError, OSError):
            return (None, {})

        try:
            workgroups = resolve_workgroups(
                proj.workgroups,
                project_dir=project_dir,
                teaparty_home=teaparty_home,
            )
        except Exception:
            _log.debug(
                'resolve_workgroups failed for %s', project_dir,
                exc_info=True,
            )
            return (None, {})

        if not workgroups:
            return (None, {})

        wg_dicts = [
            {
                'name': wg.name,
                'lead': wg.lead,
                'agents': [{'role': a} for a in wg.members_agents],
            }
            for wg in workgroups
        ]
        proj_name = project_slug or os.path.basename(project_dir)
        table = RoutingTable.from_workgroups(
            wg_dicts, project_name=proj_name,
        )

        # name → scoped id at the project level: workgroup lead names
        # ('coding-lead' → '{proj}/coding/lead') and the OM name
        # itself (so a project lead can Send back to OM).
        roster_names: dict[str, dict[str, Any]] = {}
        for wg in workgroups:
            if wg.lead:
                roster_names[wg.lead] = {}
        id_map = build_agent_id_map(
            roster_names, 'project', project_name=proj_name,
        )
        id_map['om'] = 'om'
        return (BusDispatcher(table), id_map)

    # OM session: management roster.
    try:
        roster = derive_om_roster(teaparty_home)
    except Exception:
        _log.debug(
            'derive_om_roster failed for %s', teaparty_home,
            exc_info=True,
        )
        return (None, {})

    if not roster:
        return (None, {})

    id_map = build_agent_id_map(roster, 'om')
    table = RoutingTable.from_management_roster(roster, id_map)
    return (BusDispatcher(table), id_map)


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


async def run_child_lifecycle(
    *,
    member: str,
    child_session: Any,
    worktree_path: str,
    composite: str,
    child_conv_id: str,
    bus: Any,
    tasks_by_child: dict[str, asyncio.Task],
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
    """Drive a dispatched child through its full subtree lifecycle.

    Launch the child with ``composite``.  If the turn produced new
    grandchild dispatches, gather on their tasks, integrate their
    replies, and re-launch the child with ``--resume``.  Repeat until
    a turn produces no new dispatches.  Returns the child's final
    response text (concatenation of agent-sender content from its last
    turn).

    Also writes the child's stream events to the bus under
    ``child_conv_id`` so the accordion blade renders them in real time,
    and advances the child's on-disk phase markers
    (``launching`` / ``awaiting`` / ``complete``) so the pause walker
    can reconstruct the tree from disk alone.

    Callers handle the final "propagate reply up" step with their own
    mechanism (chat invokes the session lead; CfA injects into the CfA
    lead's backtrack context).

    ``start_at_phase='awaiting'`` skips the initial launch and enters
    directly at the grandchild gather — the cross-restart resume path
    that avoids re-running an already-completed turn.

    ``launch_fn`` is the ``launcher.launch`` coroutine captured by the
    caller before spawning — passing it in instead of importing inside
    this function lets tests monkeypatch ``launcher.launch`` at the
    spawn call site without racing against the background task's
    import.
    """
    from teaparty.teams.stream import _classify_event
    from teaparty.runners.launcher import (
        _save_session_metadata as _save_meta,
        mark_launching as _mark_launching,
        mark_awaiting as _mark_awaiting,
        mark_complete as _mark_complete,
    )

    t0 = time.monotonic()
    seen_tu: set[str] = set()
    seen_tr: set[str] = set()
    response_parts: list[str] = []

    def on_event(ev: dict) -> None:
        for sender, content in _classify_event(ev, member, seen_tu, seen_tr):
            if content and sender != 'tool_result':
                bus.send(child_conv_id, sender, content)
            if sender == member and content:
                response_parts.append(content)

    mcp_port = int(os.environ.get('TEAPARTY_BRIDGE_PORT', '9000'))
    current_claude_session = resume_claude_session or ''
    current_message = composite

    if start_at_phase == 'awaiting':
        gc_tasks = [
            tasks_by_child[g]
            for g in (initial_gc_task_ids or [])
            if g in tasks_by_child
        ]
        if gc_tasks:
            _mark_awaiting(child_session, list(initial_gc_task_ids or []))
            gc_results = await asyncio.gather(
                *gc_tasks, return_exceptions=True,
            )
            gc_replies: list[str] = []
            for gid, r in zip(initial_gc_task_ids or [], gc_results):
                if isinstance(r, str) and r:
                    gc_replies.append(f'[dispatch:{gid}] {r}')
            if gc_replies:
                current_message = '\n'.join(gc_replies)

    while True:
        # Fan-in tracking: bus is the single source of truth for
        # "what has this child dispatched?"  Diffing before/after
        # identifies new grandchildren to gather replies from.
        child_conv_id = f'dispatch:{child_session.id}'
        before_ids = {
            c.id[len('dispatch:'):]
            for c in bus.children_of(child_conv_id)
            if c.id.startswith('dispatch:')
        }
        response_parts.clear()

        if worktree_path:
            # Same-repo dispatch: child runs inside its own worktree.
            launch_kwargs = dict(
                agent_name=member, message=current_message,
                scope=member_scope, teaparty_home=member_teaparty_home,
                telemetry_scope=telemetry_scope,
                worktree=worktree_path,
                mcp_port=mcp_port,
                session_id=child_session.id,
                stream_file=os.path.join(child_session.path, 'stream.jsonl'),
                on_stream_event=on_event,
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
            launch_kwargs = dict(
                agent_name=member, message=current_message,
                scope=member_scope, teaparty_home=member_teaparty_home,
                telemetry_scope=telemetry_scope,
                tier='chat',
                launch_cwd=child_session.launch_cwd,
                config_dir=child_config_dir,
                mcp_port=mcp_port,
                session_id=child_session.id,
                stream_file=os.path.join(child_session.path, 'stream.jsonl'),
                on_stream_event=on_event,
            )
        if current_claude_session:
            launch_kwargs['resume_session'] = current_claude_session
        if llm_caller is not None:
            launch_kwargs['llm_caller'] = llm_caller
        launch_kwargs['mcp_routes'] = mcp_routes
        # The child's own conv_id — parent of any dispatches it makes.
        launch_kwargs['caller_conversation_id'] = child_conv_id

        try:
            _mark_launching(child_session, current_message)
            result = await launch_fn(**launch_kwargs)
            if result.session_id:
                child_session.claude_session_id = result.session_id
                current_claude_session = result.session_id
                _save_meta(child_session)
        except Exception:
            _log.exception('Child %s failed', member)
            break

        after_ids = {
            c.id[len('dispatch:'):]
            for c in bus.children_of(child_conv_id)
            if c.id.startswith('dispatch:')
        }
        new_gc_ids = after_ids - before_ids
        if not new_gc_ids:
            break

        gc_tasks = [
            tasks_by_child[g] for g in new_gc_ids
            if g in tasks_by_child
        ]
        if not gc_tasks:
            break
        _mark_awaiting(child_session, list(new_gc_ids))
        gc_results = await asyncio.gather(*gc_tasks, return_exceptions=True)
        gc_replies = []
        for gid, r in zip(new_gc_ids, gc_results):
            if isinstance(r, str) and r:
                gc_replies.append(f'[dispatch:{gid}] {r}')
            elif isinstance(r, Exception) and not isinstance(
                    r, asyncio.CancelledError):
                _log.warning('Grandchild %s raised: %s', gid, r)
        if not gc_replies:
            break
        current_message = '\n'.join(gc_replies)

    _log.info(
        '%s subtree completed in %.2fs', member, time.monotonic() - t0,
    )

    response_text = '\n'.join(response_parts)
    _mark_complete(child_session, response_text)
    return response_text
