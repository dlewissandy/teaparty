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
) -> dict[str, Any]:
    """Close a dispatch conversation, merging the child's work back.

    Args:
        parent_session: The dispatcher's Session (its conversation_map
            holds the child reference we must remove on success).
        conversation_id: The conversation handle (``dispatch:{child_id}``).
        teaparty_home: Path to .teaparty directory.
        scope: 'management' or 'project'.

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

    sessions_dir = os.path.join(teaparty_home, scope, 'sessions')

    # Telemetry: close_conversation + session_closed for the target and
    # every descendant brought down by the recursive cascade (Issue #405).
    # collect_descendants is inclusive — it returns [target, ...descendants].
    try:
        from teaparty.telemetry import record_event
        from teaparty.telemetry import events as _telem_events
        walk = collect_descendants(sessions_dir, child_session_id)
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
    result = await _close_recursive(sessions_dir, child_session_id)
    if result['status'] != 'ok':
        return result

    # All merges succeeded — remove the child from the parent's
    # conversation_map so the dispatcher can reuse the slot.
    request_id = None
    for rid, csid in list(parent_session.conversation_map.items()):
        if csid == child_session_id:
            request_id = rid
            break
    if request_id is not None:
        from teaparty.runners.launcher import remove_child_session
        remove_child_session(parent_session, request_id=request_id)

    return {
        'status': 'ok',
        'message': f'Subchat {child_session_id} closed and merged.',
    }


async def _close_recursive(sessions_dir: str, session_id: str) -> dict[str, Any]:
    """Close *session_id* and all its descendants, merging from leaves up.

    Returns the same status dict shape as ``close_conversation``.
    """
    session_path = os.path.join(sessions_dir, session_id)
    meta_path = os.path.join(session_path, 'metadata.json')

    meta: dict[str, Any] = {}
    if os.path.isfile(meta_path):
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            meta = {}

    # Close grandchildren first so their work is inside the child's
    # worktree by the time we squash-merge the child.
    for grandchild_id in list(meta.get('conversation_map', {}).values()):
        sub = await _close_recursive(sessions_dir, grandchild_id)
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
) -> Callable:
    """Build the close_fn that the CloseConversation MCP tool invokes.

    The returned coroutine closes a ``dispatch:{session_id}`` conversation:
    cancels every in-flight child task in the subtree, records each
    descendant's agent_name for UI events, calls :func:`close_conversation`
    to squash-merge each subtree worktree back into its parent, and emits
    ``dispatch_completed`` through ``on_dispatch`` so the accordion
    re-renders.

    The same function is installed by both the chat-tier session and the
    CfA orchestrator. All state it needs is passed in here at listener
    init time — it does not reference any tier-specific object.

    Parameters
    ----------
    dispatch_session
        Session object whose ``conversation_map`` owns the subtree root.
        Passed to :func:`close_conversation` so the merged-out child is
        removed from the dispatcher's conversation_map.
    teaparty_home, scope
        Root for ``{teaparty_home}/{scope}/sessions/`` — used to locate
        descendant metadata files and as the arg to
        :func:`close_conversation`.
    tasks_by_child
        Registry of in-flight child tasks (``{child_session_id: Task}``).
        Entries for the subtree being closed are popped and cancelled
        before the worktrees are removed, so no task writes into a
        directory that's about to be rmtree'd.
    on_dispatch
        Optional UI callback. On success this is called once per removed
        session, deepest-first, with a ``dispatch_completed`` event.
    agent_name
        Log-only identifier for the calling agent.
    """
    async def close_fn(conversation_id: str):
        subtree: list[tuple[str, str]] = []
        if conversation_id.startswith('dispatch:'):
            root_csid = conversation_id[len('dispatch:'):]
            sessions_dir = os.path.join(teaparty_home, scope, 'sessions')
            subtree = collect_descendants_with_parents(
                sessions_dir, root_csid,
                root_parent=dispatch_session.id)
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

        agent_names: dict[str, str] = {}
        if subtree:
            sessions_dir = os.path.join(teaparty_home, scope, 'sessions')
            for csid, _parent in subtree:
                meta_path = os.path.join(
                    sessions_dir, csid, 'metadata.json')
                try:
                    with open(meta_path) as f:
                        agent_names[csid] = json.load(f).get('agent_name', '')
                except (OSError, json.JSONDecodeError):
                    agent_names[csid] = ''

        close_result = await close_conversation(
            dispatch_session, conversation_id,
            teaparty_home=teaparty_home, scope=scope,
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


def collect_descendants(sessions_dir: str, root_session_id: str) -> list[str]:
    """Walk the conversation tree rooted at root_session_id.

    Returns all session_ids in the subtree (root first, then descendants
    in depth-first order). Reads metadata.json files on disk — does not
    modify anything.
    """
    return [sid for sid, _parent in collect_descendants_with_parents(
        sessions_dir, root_session_id, root_parent='')]


def collect_descendants_with_parents(
    sessions_dir: str,
    root_session_id: str,
    *,
    root_parent: str,
) -> list[tuple[str, str]]:
    """Walk the conversation tree and return (session_id, parent_id) pairs.

    Depth-first, root first.
    """
    result: list[tuple[str, str]] = []

    def _walk(sid: str, parent: str) -> None:
        result.append((sid, parent))
        meta_path = os.path.join(sessions_dir, sid, 'metadata.json')
        if not os.path.isfile(meta_path):
            return
        try:
            with open(meta_path) as f:
                meta = json.load(f)
        except (json.JSONDecodeError, OSError):
            return
        for child_sid in meta.get('conversation_map', {}).values():
            _walk(child_sid, sid)

    _walk(root_session_id, root_parent)
    return result
