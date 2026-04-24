"""Orphan recovery for sessions that spawn child worktrees.

A session that dispatches children registers each one in
``{infra_dir}/.children`` (heartbeat path + team name).  If the parent
dies mid-run — bridge restart, kill, crash — those children keep going
with no parent to merge their results back in.  When the parent
restarts (resume), this module reconciles the registry:

- **completed** (status == ``'completed'``/``'withdrawn'`` and CfA state
  ``DONE``): squash-merge the child's worktree into the parent's
  session worktree, log the merge.
- **dead** (heartbeat stale or missing, non-terminal): emit a
  ``recovery_redispatch`` LOG, and if the caller passed a
  ``redispatch_fn``, call it so the caller can re-launch the child.
- **live** (fresh heartbeat or live PID): leave alone.

Then compact ``.children`` so the registry only contains entries that
are still meaningful.

This module is intentionally tier-agnostic.  The re-dispatch step is
the only thing that varies between callers (CfA's ``dispatch()`` helper
vs. a chat-tier spawn_fn), so it's threaded through as a callable
rather than imported here.  Pass ``redispatch_fn=None`` to log + skip.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Awaitable, Callable

_log = logging.getLogger('teaparty.workspace.recovery')


# redispatch_fn signature:
#   async fn(*, child: dict, worktree_path: str, child_infra: str) -> None
# child is the .children registry entry (keys: 'team', 'heartbeat', ...).
RedispatchFn = Callable[..., Awaitable[None]]


def find_dispatch_worktree(child_infra: str) -> str:
    """Return the worktree path for a dispatch given its infra dir.

    In the job-store layout, ``child_infra`` is the task_dir and the
    worktree lives at ``{task_dir}/worktree/``.  Returns ``''`` when
    no worktree directory exists.
    """
    candidate = os.path.join(child_infra, 'worktree')
    if os.path.isdir(candidate):
        return candidate
    return ''


async def recover_orphaned_children(
    *,
    infra_dir: str,
    session_worktree: str,
    task: str,
    session_id: str = '',
    event_bus: Any = None,
    redispatch_fn: RedispatchFn | None = None,
) -> None:
    """Reconcile ``{infra_dir}/.children`` after a parent restart.

    Runs before any new dispatches arrive so the registry is consistent
    when the parent's listeners come up.  Safe to call when the registry
    file doesn't exist (returns immediately).

    Args:
        infra_dir: Parent session's infra dir; the registry lives at
            ``{infra_dir}/.children`` and the parent's heartbeat at
            ``{infra_dir}/.heartbeat``.
        session_worktree: Merge target — the parent's session worktree.
            Completed children's worktrees are squash-merged into this.
        task: Free-form task description, used to build the fallback
            commit message for recovered merges.
        session_id: Parent session id (for tagging LOG events).  May be
            empty if the caller has no event_bus.
        event_bus: Optional event bus for ``recovery_merge`` /
            ``recovery_redispatch`` LOG events.  Pass ``None`` to skip
            event emission (recovery still happens, just silently to
            the bus).
        redispatch_fn: Optional callable invoked for each dead child:
            ``await redispatch_fn(child=..., worktree_path=...,
            child_infra=...)``.  When ``None``, dead children are
            logged but not re-dispatched (the caller takes
            responsibility for whatever happens to that worktree).
    """
    children_path = os.path.join(infra_dir, '.children')
    if not os.path.exists(children_path):
        return

    from teaparty.bridge.state.heartbeat import (
        scan_children, compact_children, create_heartbeat,
    )
    from teaparty.workspace.merge import squash_merge
    from teaparty.cfa.statemachine.cfa_state import load_state

    # Refresh the parent's heartbeat so any still-live child sees a
    # live parent — without this, a child's own watchdog might trip
    # immediately after we adopt it.
    parent_hb = os.path.join(infra_dir, '.heartbeat')
    if not os.path.exists(parent_hb):
        create_heartbeat(parent_hb, role='session')

    scan = scan_children(children_path)

    # ── Merge completed children ─────────────────────────────────────────
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
            # Status said completed but CfA state disagrees — leave it
            # alone, don't merge half-finished work.
            continue

        worktree_path = find_dispatch_worktree(child_infra)
        if not worktree_path or not os.path.isdir(worktree_path):
            _log.warning('Recovery: no worktree found for %s', child_infra)
            continue

        team = child.get('team', '')
        _log.info('Recovery: merging completed child %s', team)
        try:
            from teaparty.scripts.generate_commit_message import (
                build_fallback,
            )
            message = build_fallback(team, task)
            await squash_merge(
                source=worktree_path,
                target=session_worktree,
                message=message,
            )
            await _emit_log(
                event_bus, session_id,
                category='recovery_merge', team=team,
                heartbeat=hb_path, status='merged',
            )
        except Exception as exc:
            _log.warning('Recovery: merge failed for %s: %s', team, exc)

    # ── Re-dispatch dead non-terminal children ───────────────────────────
    for child in scan['dead']:
        hb_path = child.get('heartbeat', '')
        child_infra = os.path.dirname(hb_path) if hb_path else ''
        worktree_path = (
            find_dispatch_worktree(child_infra) if child_infra else ''
        )
        team = child.get('team', '')

        _log.warning('Recovery: re-dispatching dead child %s', team)
        await _emit_log(
            event_bus, session_id,
            category='recovery_redispatch', team=team, heartbeat=hb_path,
        )

        if redispatch_fn is not None and worktree_path and child_infra:
            try:
                await redispatch_fn(
                    child=child,
                    worktree_path=worktree_path,
                    child_infra=child_infra,
                )
            except Exception as exc:
                _log.warning(
                    'Recovery: re-dispatch failed for %s: %s', team, exc,
                )

    # ── Log live children — leave them running ───────────────────────────
    for child in scan['live']:
        _log.info(
            'Recovery: live child %s — leaving alone',
            child.get('team', ''),
        )

    # Compact the registry — drop terminal entries we just handled.
    compact_children(children_path)


async def _emit_log(
    event_bus: Any,
    session_id: str,
    *,
    category: str,
    **data: Any,
) -> None:
    """Publish a LOG event when an event_bus is wired; otherwise no-op."""
    if event_bus is None:
        return
    from teaparty.messaging.bus import Event, EventType
    await event_bus.publish(Event(
        type=EventType.LOG,
        data={'category': category, **data},
        session_id=session_id,
    ))
