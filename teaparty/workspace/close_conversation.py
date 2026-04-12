"""Close a dispatch conversation — recursive teardown of child sessions.

The parent owns the conversation lifecycle. CloseConversation:
1. Recursively closes any conversations the child opened
2. Removes the child's session directory (worktree + metadata)
3. Removes the child from the parent's conversation_map (frees the slot)
"""
from __future__ import annotations

import json
import os
import shutil


def close_conversation(
    parent_session,
    conversation_id: str,
    *,
    teaparty_home: str,
    scope: str,
) -> None:
    """Close a dispatch conversation and clean up the child session.

    Args:
        parent_session: The parent's Session object (has conversation_map).
        conversation_id: The conversation handle (dispatch:{child_session_id}).
        teaparty_home: Path to .teaparty directory.
        scope: 'management' or 'project'.
    """
    # Extract child session_id from conversation_id
    if not conversation_id.startswith('dispatch:'):
        return
    child_session_id = conversation_id[len('dispatch:'):]
    if not child_session_id:
        return

    sessions_dir = os.path.join(teaparty_home, scope, 'sessions')

    # Recursively close the child and all its descendants
    _close_recursive(sessions_dir, child_session_id)

    # Remove from parent's conversation_map to free the slot.
    # Find the request_id that maps to this child.
    request_id = None
    for rid, csid in list(parent_session.conversation_map.items()):
        if csid == child_session_id:
            request_id = rid
            break
    if request_id is not None:
        from teaparty.runners.launcher import remove_child_session
        remove_child_session(parent_session, request_id=request_id)


def collect_descendants(sessions_dir: str, root_session_id: str) -> list[str]:
    """Walk the conversation tree rooted at root_session_id.

    Returns all session_ids in the subtree (root first, then descendants
    in depth-first order). Reads metadata.json files on disk — does not
    modify anything.

    Used by close_fn to find in-flight tasks that must be cancelled
    before close_conversation tears down the session directories.
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

    Depth-first, root first. ``root_parent`` is the parent of the root
    of the walk (typically the dispatcher session that owns the
    conversation being closed). Used by close_fn to emit per-descendant
    dispatch_completed events with the correct parent → child pairing.
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


def _close_recursive(sessions_dir: str, session_id: str) -> None:
    """Recursively close a session and all its children."""
    session_path = os.path.join(sessions_dir, session_id)
    meta_path = os.path.join(session_path, 'metadata.json')

    # Read the child's conversation_map to find grandchildren
    conversation_map = {}
    if os.path.isfile(meta_path):
        try:
            with open(meta_path) as f:
                meta = json.load(f)
            conversation_map = meta.get('conversation_map', {})
        except (json.JSONDecodeError, OSError):
            pass

    # Recursively close grandchildren first (depth-first)
    for _request_id, grandchild_id in list(conversation_map.items()):
        _close_recursive(sessions_dir, grandchild_id)

    # Remove this session's directory (worktree + metadata)
    if os.path.isdir(session_path):
        shutil.rmtree(session_path, ignore_errors=True)
