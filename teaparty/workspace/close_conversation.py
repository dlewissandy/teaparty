"""Close a dispatch conversation — recursive teardown + merge-back.

Issue #397 model:

- Dispatched subchats run in per-session git worktrees on a
  ``session/{session_id}`` branch.
- ``CloseConversation`` commits any pending work in the child's
  worktree, squash-merges ``session/{id}`` into the merge target
  recorded on the child session, removes the child worktree, and
  deletes the session branch.
- The merge target for a same-repo dispatch is the dispatcher's
  worktree/branch (the dispatcher's working state is the integration
  branch). For the cross-repo exception (OM dispatches a project lead
  whose repo differs) the target is the project repo's default branch,
  in that project's main checkout.
- On merge conflict the function returns a structured
  ``{status: 'conflict', message: ..., conflicts: [...]}`` result and
  leaves the worktree in place so the parent agent can resolve via git
  and re-call ``CloseConversation``.
- Descendants are closed depth-first so grandchildren merge into the
  child before the child merges into its parent.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from typing import Any, Callable

_log = logging.getLogger(__name__)


def close_conversation_sync(
    parent_session,
    conversation_id: str,
    *,
    teaparty_home: str,
    scope: str,
) -> dict[str, Any]:
    """Synchronous wrapper around :func:`close_conversation`.

    Pre-#397 tests (and any other purely synchronous caller) use this
    form. It is a thin ``asyncio.run`` wrapper — callers that are
    already inside an event loop must call the async version directly.
    """
    return asyncio.run(close_conversation(
        parent_session, conversation_id,
        teaparty_home=teaparty_home, scope=scope,
    ))


async def close_conversation(
    parent_session,
    conversation_id: str,
    *,
    teaparty_home: str,
    scope: str,
    bus=None,
    tasks_dir: str = '',
) -> dict[str, Any]:
    """Close a dispatch conversation, merging the child's work back.

    Args:
        parent_session: The dispatcher's Session.  Retained for its
            ``id`` (used in telemetry) and as a legacy handle.
        conversation_id: The conversation handle (``dispatch:{child_id}``).
        teaparty_home: Path to .teaparty directory.
        scope: 'management' or 'project'.
        bus: The ``SqliteMessageBus`` where this conversation lives.
            Required.  The walker traverses children via
            ``bus.children_of(parent_id)`` — the single source of truth
            for the dispatch tree (issue #422).  Left ``None`` for a
            brief transition window while callers are migrated.
        tasks_dir: When set, dispatched-worker sessions live at
            ``{tasks_dir}/<sid>/`` instead of the legacy
            ``{teaparty_home}/<scope>/sessions/<sid>/``.  Mirrors the
            ``parent_dir`` parameter on ``create_session`` /
            ``load_session``.  Empty string keeps the legacy lookup
            for chat-tier dispatchers and back-compat with sessions
            created before the layout change.

    Returns:
        A dict with at least ``status`` and ``message``. Statuses:

        - ``ok``: the subtree closed cleanly.
        - ``conflict``: a merge failed with conflicts; the worktree is
          left on disk, the parent agent must resolve and retry.
        - ``error``: an unexpected error occurred (git failure,
          permission error, etc.).
        - ``noop``: the conversation id was not a dispatch handle or
          the child session was missing; nothing to do.
    """
    if not conversation_id.startswith('dispatch:'):
        return {'status': 'noop', 'message': 'Not a dispatch conversation.'}
    child_session_id = conversation_id[len('dispatch:'):]
    if not child_session_id:
        return {'status': 'noop', 'message': 'Empty child session id.'}

    legacy_sessions_dir = os.path.join(teaparty_home, scope, 'sessions')

    # Telemetry: close_conversation + session_closed for the target and
    # every descendant brought down by the recursive cascade (Issue #405).
    # collect_descendants_from_bus is inclusive — returns [target, ...descendants].
    try:
        from teaparty.telemetry import record_event
        from teaparty.telemetry import events as _telem_events
        walk = collect_descendants_from_bus(bus, conversation_id)
        record_event(
            _telem_events.CLOSE_CONVERSATION,
            scope=scope,
            session_id=parent_session.id if parent_session else None,
            data={
                'conv_id':         conversation_id,
                'triggered_from':  'agent',
                'child_session':   child_session_id,
                'descendants':     max(len(walk) - 1, 0),
            },
        )
        for sid in walk:
            reason = ('explicit_close' if sid == child_session_id
                      else 'recursive_cascade')
            record_event(
                _telem_events.SESSION_CLOSED,
                scope=scope,
                session_id=sid,
                data={
                    'reason':               reason,
                    'triggered_by_session_id': (
                        parent_session.id if parent_session else None
                    ),
                },
            )
    except Exception:
        pass

    # Recursively close child + descendants, merging from the leaves up.
    result = await _close_recursive(
        legacy_sessions_dir, child_session_id, bus, tasks_dir=tasks_dir,
    )
    if result['status'] != 'ok':
        return result

    # Mark the bus record closed — single source of truth (#422).
    if bus is not None:
        try:
            from teaparty.messaging.conversations import ConversationState
            bus.update_conversation_state(
                conversation_id, ConversationState.CLOSED)
        except Exception:
            _log.debug(
                'close_conversation: failed to mark bus state closed for %s',
                conversation_id, exc_info=True,
            )

    return {
        'status': 'ok',
        'message': f'Subchat {child_session_id} closed and merged.',
    }


async def _close_recursive(
    legacy_sessions_dir: str,
    session_id: str,
    bus=None,
    *,
    tasks_dir: str = '',
) -> dict[str, Any]:
    """Close *session_id* and all its descendants, merging from leaves up.

    Returns the same status dict shape as ``close_conversation``.

    When ``bus`` is supplied, children are enumerated via
    ``bus.children_of(f'dispatch:{session_id}')`` — the single source
    of truth for the dispatch tree (issue #422).  Merge metadata
    (worktree path, target branch, etc.) still comes from the child's
    session metadata on disk; that's not tree structure.

    ``tasks_dir`` is checked first when set: dispatched sessions in
    CfA jobs live at ``{tasks_dir}/<sid>/``.  Falls back to
    ``{legacy_sessions_dir}/<sid>/`` so chat-tier and pre-layout-change
    sessions still close cleanly.
    """
    candidates: list[str] = []
    if tasks_dir:
        candidates.append(os.path.join(tasks_dir, session_id))
    candidates.append(os.path.join(legacy_sessions_dir, session_id))
    session_path = ''
    for cand in candidates:
        if os.path.isfile(os.path.join(cand, 'metadata.json')):
            session_path = cand
            break
    if not session_path:
        session_path = candidates[0]
    meta_path = os.path.join(session_path, 'metadata.json')

    meta: dict[str, Any] = {}
    if os.path.isfile(meta_path):
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            meta = {}

    # Close grandchildren first so their work is inside the child's
    # worktree by the time we squash-merge the child.  Bus is the
    # single source of truth for the dispatch tree (#422).
    grandchildren = [
        c.id[len('dispatch:'):]
        for c in bus.children_of(f'dispatch:{session_id}')
        if c.id.startswith('dispatch:')
    ]
    for grandchild_id in grandchildren:
        sub = await _close_recursive(
            legacy_sessions_dir, grandchild_id, bus, tasks_dir=tasks_dir,
        )
        if sub['status'] != 'ok' and sub['status'] != 'noop':
            # Bubble the failure up. The child keeps its worktree,
            # and every ancestor of the failure stays open until the
            # parent agent resolves the conflict and retries.
            return sub

    worktree_path = meta.get('worktree_path') or ''
    worktree_branch = meta.get('worktree_branch') or ''
    merge_target_repo = meta.get('merge_target_repo') or ''
    merge_target_branch = meta.get('merge_target_branch') or ''
    merge_target_worktree = meta.get('merge_target_worktree') or ''
    agent_name = meta.get('agent_name') or session_id

    # If this session never created a worktree (e.g. a legacy session
    # or a privileged top-level that shouldn't be here), fall through
    # to the plain teardown path.
    if worktree_path and os.path.isdir(worktree_path):
        merge_result = await _commit_and_merge(
            worktree_path=worktree_path,
            session_branch=worktree_branch,
            target_worktree=merge_target_worktree,
            target_branch=merge_target_branch,
            source_repo=merge_target_repo,
            agent_name=agent_name,
            session_id=session_id,
        )
        if merge_result['status'] != 'ok':
            return merge_result

    # Remove the session directory (worktree already removed on success).
    if os.path.isdir(session_path):
        shutil.rmtree(session_path, ignore_errors=True)

    return {'status': 'ok', 'message': f'Closed {session_id}.'}


async def _commit_and_merge(
    *,
    worktree_path: str,
    session_branch: str,
    target_worktree: str,
    target_branch: str,
    source_repo: str,
    agent_name: str,
    session_id: str,
) -> dict[str, Any]:
    """Commit pending work, squash-merge, and clean up on success."""
    from teaparty.workspace.worktree import (
        commit_all_pending,
        squash_merge_session_branch,
        remove_session_worktree,
        delete_branch,
    )

    # 1. Commit any uncommitted edits the subchat left behind so the
    #    session branch actually carries the agent's work.
    await commit_all_pending(
        worktree_path,
        message=f'Subchat {session_id} ({agent_name}): snapshot before merge',
    )

    if not target_worktree or not target_branch:
        # Cross-repo with no explicit target — this shouldn't happen
        # because spawn_fn always records one. Fail loud.
        return {
            'status': 'error',
            'message': (
                f'Subchat {session_id}: missing merge target '
                f'(target_worktree={target_worktree!r}, '
                f'target_branch={target_branch!r}). '
                f'Session metadata is incomplete.'
            ),
            'conflicts': [],
        }

    # 2. Squash-merge into the target worktree / branch. On conflict
    #    we return immediately, leaving the worktree + session branch
    #    in place for the parent agent to resolve and retry.
    merge_message = f'Subchat {session_id}: {agent_name} merged'
    result = await squash_merge_session_branch(
        target_worktree=target_worktree,
        source_branch=session_branch,
        message=merge_message,
    )
    if result['status'] != 'ok':
        return {
            'status': result['status'],
            'message': result['message'],
            'conflicts': result.get('conflicts', []),
            'session_id': session_id,
            'agent_name': agent_name,
            'worktree_path': worktree_path,
            'target_worktree': target_worktree,
            'target_branch': target_branch,
        }

    # 3. Clean up the child's worktree and branch now that the squash
    #    commit is on the target branch.
    await remove_session_worktree(source_repo or target_worktree, worktree_path)
    await delete_branch(source_repo or target_worktree, session_branch)

    return {'status': 'ok', 'message': f'Merged {session_branch}.'}


def build_close_fn(
    *,
    dispatch_session,
    teaparty_home: str,
    scope: str,
    tasks_by_child: dict[str, asyncio.Task],
    on_dispatch: Callable[[dict], None] | None,
    agent_name: str = '',
    bus=None,
    tasks_dir: str = '',
) -> Callable:
    """Build the close_fn that the CloseConversation MCP tool invokes.

    The returned coroutine closes a ``dispatch:{session_id}`` conversation:
    cancels every in-flight child task in the subtree, reads each
    descendant's agent_name from the bus (#422) for UI events, calls
    :func:`close_conversation` to squash-merge each subtree worktree back
    into its parent, and emits ``dispatch_completed`` through
    ``on_dispatch`` so the accordion re-renders.

    The same function is installed by both the chat-tier session and the
    CfA orchestrator. All state it needs is passed in here at listener
    init time — it does not reference any tier-specific object.

    ``bus`` is the ``SqliteMessageBus`` where this session's dispatches
    are registered.  When present, the subtree walk and agent_name
    resolution both use the bus — the single source of truth (#422).
    """
    async def close_fn(conversation_id: str):
        subtree: list[tuple[str, str]] = []
        agent_names: dict[str, str] = {}
        if conversation_id.startswith('dispatch:'):
            # Bus walk — single source of truth for tree + name (#422).
            subtree_convs = collect_descendants_with_parents_from_bus(
                bus, conversation_id,
                root_parent_conv_id=f'dispatch:{dispatch_session.id}',
            )
            subtree = []
            for conv, parent_conv in subtree_convs:
                _, _, csid = conv.id.partition(':')
                _, _, parent_sid = parent_conv.partition(':')
                # Top-level parent is the dispatcher's session id,
                # not a 'dispatch:{id}' form.
                if not parent_sid:
                    parent_sid = dispatch_session.id
                subtree.append((csid, parent_sid))
                agent_names[csid] = conv.agent_name

            tasks = []
            for csid, _parent in subtree:
                task = tasks_by_child.pop(csid, None)
                if task is not None and not task.done():
                    task.cancel()
                    tasks.append(task)
            if tasks:
                try:
                    await asyncio.wait_for(
                        asyncio.shield(
                            asyncio.gather(*tasks, return_exceptions=True)),
                        timeout=2.0)
                except asyncio.TimeoutError:
                    _log.warning(
                        '%s close_fn: tasks did not cancel within 2s',
                        agent_name)

        close_result = await close_conversation(
            dispatch_session, conversation_id,
            teaparty_home=teaparty_home, scope=scope, bus=bus,
            tasks_dir=tasks_dir,
        )
        if close_result.get('status') not in ('ok', 'noop'):
            return close_result

        if on_dispatch:
            for csid, parent_sid in reversed(subtree):
                on_dispatch({
                    'type': 'dispatch_completed',
                    'parent_session_id': parent_sid,
                    'child_session_id': csid,
                    'agent_name': agent_names.get(csid, ''),
                })
        return close_result

    return close_fn


def collect_descendants_from_bus(bus, root_conv_id: str) -> list[str]:
    """Walk the dispatch tree via the bus and return session_ids (#422).

    Bus-native replacement for ``collect_descendants``.  Returns session
    ids in depth-first, root-first order.  ``root_conv_id`` follows the
    ``dispatch:{session_id}`` convention.
    """
    pairs = collect_descendants_with_parents_from_bus(
        bus, root_conv_id, root_parent_conv_id='')
    return [_session_id_of(conv.id) for conv, _parent in pairs]


def collect_descendants_with_parents_from_bus(
    bus,
    root_conv_id: str,
    *,
    root_parent_conv_id: str,
) -> list[tuple]:
    """Walk the dispatch tree via ``bus.children_of`` (#422).

    Returns [(Conversation, parent_conv_id), ...] in depth-first,
    root-first order.  The root itself is included with its supplied
    parent; every descendant is attributed to its actual parent_conv_id
    as recorded in the bus.
    """
    result: list[tuple] = []
    visited: set[str] = set()

    def _walk(conv_id: str, parent_conv_id: str) -> None:
        if conv_id in visited:
            return
        visited.add(conv_id)
        conv = bus.get_conversation(conv_id)
        if conv is None:
            return
        result.append((conv, parent_conv_id))
        for child in bus.children_of(conv_id):
            _walk(child.id, conv_id)

    _walk(root_conv_id, root_parent_conv_id)
    return result


def _session_id_of(conv_id: str) -> str:
    """Extract session_id from a ``dispatch:{session_id}`` conv_id."""
    if conv_id.startswith('dispatch:'):
        return conv_id[len('dispatch:'):]
    return conv_id


