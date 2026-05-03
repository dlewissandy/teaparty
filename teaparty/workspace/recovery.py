"""Bus-based orphan recovery — one codepath, both tiers (Cut 19).

A session that dispatches children records each one as a ``DISPATCH``
conversation in the SQLite bus.  The conversation row carries:

- ``state``           — ACTIVE / PAUSED / CLOSED / WITHDRAWN
- ``worktree_path``   — the child's worktree (merge source)
- ``pid``             — the spawned subprocess PID
- ``pid_started``     — OS create_time at spawn (defeats PID reuse)

If the parent dies mid-run — bridge restart, kill, crash — those rows
persist in the bus.  When the parent restarts, this module reconciles
them by asking three questions:

1. **Is the conversation in a terminal state?**  ``CLOSED`` /
   ``WITHDRAWN`` were already finished cleanly; nothing to do.
2. **Is the child's worktree merged?**  If the conversation is still
   ``ACTIVE`` but the subprocess is gone *and* the worktree exists,
   we squash-merge it into the parent's session worktree.
3. **Is the child still running?**  If the OS says yes (PID alive,
   create_time matches), leave it.  If no, optionally re-dispatch via
   a caller-supplied callable.

This is the **only** recovery codepath.  Both tiers — CfA's
``Orchestrator.run()`` and chat tier's ``AgentSession`` — call this
function with their parent conv_id and bus.  No ``.children`` JSONL
walks, no heartbeat-file reads, no per-tier divergence.

The heartbeat-file machinery in ``teaparty/bridge/state/heartbeat.py``
is not gone — it still serves parent-death detection in
``runners/claude.py`` (a child polls its parent's heartbeat to commit
suicide if the parent dies).  But it is no longer in the recovery
path: liveness is asked of the OS at recovery time, not derived from
file mtimes.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Awaitable, Callable

_log = logging.getLogger('teaparty.workspace.recovery')


# redispatch_fn signature:
#   async fn(*, conversation, worktree_path) -> None
# conversation is the bus Conversation dataclass.
RedispatchFn = Callable[..., Awaitable[None]]


def _is_pid_dead(pid: int, started: float) -> bool:
    """Return True when the PID is dead OR was reused by a different process.

    A bus row records ``(pid, started)`` at spawn.  Recovery later asks
    the OS: does that PID still exist, and if so, is it the same
    process (matching create_time within tolerance)?  Any divergence —
    process gone, or PID recycled by an unrelated process — counts as
    dead.

    PID 0 means "no process was ever recorded" (the bus row was
    created but ``set_conversation_process`` never ran — e.g. the
    subprocess failed to spawn).  Treat that as dead so recovery can
    redispatch or merge what's there.
    """
    if pid <= 0:
        return True

    # Identical to bridge.state.heartbeat._is_pid_dead_or_reused, but
    # consulted at recovery time against the bus's recorded values
    # rather than a heartbeat file's contents.  Same OS calls, same
    # tolerance — different source of truth.
    try:
        import psutil
        proc = psutil.Process(pid)
        if started and abs(proc.create_time() - started) > 2.0:
            return True   # different process reused this PID
        return False
    except Exception:
        pass

    try:
        os.kill(pid, 0)
        return False  # PID exists; can't verify create_time, assume same
    except (ProcessLookupError, OSError):
        return True
    except PermissionError:
        return False


async def recover_orphaned_children(
    *,
    parent_conversation_id: str,
    bus: Any,
    session_worktree: str,
    task: str,
    session_id: str = '',
    event_bus: Any = None,
    redispatch_fn: RedispatchFn | None = None,
) -> None:
    """Reconcile a parent conversation's dispatched children on restart.

    Args:
        parent_conversation_id: The parent's bus conv_id.  Recovery
            scans ``bus.children_of(parent_conversation_id)``.
        bus: An open ``SqliteMessageBus`` for the relevant tier.
        session_worktree: Merge target — completed children's worktrees
            squash-merge into this.
        task: Free-form description used when synthesizing a fallback
            commit message for recovered merges.
        session_id: Parent session id (for tagging LOG events).  Empty
            when the caller has no event_bus.
        event_bus: Optional event bus for ``recovery_merge`` /
            ``recovery_redispatch`` LOG events.  ``None`` → silent.
        redispatch_fn: Optional callable invoked once per dead child:
            ``await redispatch_fn(conversation=..., worktree_path=...)``.
            ``None`` means "log + leave the worktree alone."  The CfA
            engine wires an inline resume helper (load child CfA →
            run a fresh ``Orchestrator`` → squash-merge); chat tier
            passes ``None`` because the child's bus row already
            records everything needed for the user to resume manually.
    """
    from teaparty.messaging.conversations import (
        ConversationState, ConversationType,
    )
    from teaparty.workspace.merge import squash_merge

    children = bus.children_of(parent_conversation_id)
    for conv in children:
        # Recovery only applies to dispatched subprocesses — root
        # conversations and other types have no worktree to merge.
        if conv.type != ConversationType.DISPATCH:
            continue
        if conv.state in (
            ConversationState.CLOSED, ConversationState.WITHDRAWN,
        ):
            continue   # already finished cleanly

        wt = conv.worktree_path
        process_dead = _is_pid_dead(conv.pid, conv.pid_started)

        if not process_dead:
            # Still running — leave alone.  Parent's listeners will
            # hear from it via the existing channels.
            _log.info('Recovery: live child %s — leaving alone', conv.agent_name)
            continue

        # Process is dead.  If a worktree exists, squash-merge it; the
        # child did real work that the parent never got to absorb.
        merged = False
        if wt and os.path.isdir(wt):
            _log.info('Recovery: merging dead child %s', conv.agent_name)
            try:
                from teaparty.scripts.generate_commit_message import (
                    build_fallback,
                )
                message = build_fallback(conv.agent_name, task)
                await squash_merge(
                    source=wt, target=session_worktree, message=message,
                )
                merged = True
                await _emit_log(
                    event_bus, session_id,
                    category='recovery_merge', team=conv.agent_name,
                    conversation_id=conv.id, status='merged',
                )
            except Exception as exc:
                _log.warning(
                    'Recovery: merge failed for %s: %s',
                    conv.agent_name, exc,
                )

        # Mark the conversation closed regardless of merge outcome —
        # the subprocess is gone; the row should not stay ACTIVE.
        # (A failed merge surfaces in the LOG; the user can deal with
        # the worktree manually.)
        try:
            bus.close_conversation(conv.id)
        except Exception:
            _log.debug(
                'close_conversation raised during recovery',
                exc_info=True,
            )

        if not merged and redispatch_fn is not None:
            _log.warning(
                'Recovery: re-dispatching dead child %s', conv.agent_name,
            )
            await _emit_log(
                event_bus, session_id,
                category='recovery_redispatch',
                team=conv.agent_name, conversation_id=conv.id,
            )
            try:
                await redispatch_fn(conversation=conv, worktree_path=wt)
            except Exception as exc:
                _log.warning(
                    'Recovery: re-dispatch failed for %s: %s',
                    conv.agent_name, exc,
                )


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
