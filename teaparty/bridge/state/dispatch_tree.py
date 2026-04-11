"""Build a dispatch tree from session metadata conversation_maps.

The dispatch tree shows which agents are running and their parent-child
relationships, derived by walking conversation_map entries in metadata.json
files starting from a root session.
"""
from __future__ import annotations

import json
import os


def build_dispatch_tree(sessions_dir: str, root_session_id: str) -> dict:
    """Build a nested dispatch tree starting from root_session_id.

    Each node contains:
        session_id: str
        agent_name: str
        conversation_id: str
        status: str  ('active' or 'completed')
        children: list[dict]  (recursive)

    If a child session_id in a conversation_map cannot be resolved
    (no metadata.json), it appears as a stub with agent_name='unknown'.
    """
    # Build a reverse index: claude_session_id → directory name.
    # conversation_map values are Claude session UUIDs, but session
    # directories use short hex IDs or named IDs.
    claude_id_to_dir = _build_claude_id_index(sessions_dir)

    # The dispatch session that holds conversation_map entries may be
    # a different session directory than the named root (the bridge
    # creates a separate dispatch session each restart). Merge all
    # conversation_maps from sessions with the same agent_name.
    root_meta = _read_metadata(sessions_dir, root_session_id)
    if root_meta is not None:
        agent_name = root_meta.get('agent_name', '')
        merged_map = _merge_conversation_maps(
            sessions_dir, agent_name, claude_id_to_dir)
        if merged_map:
            root_meta['conversation_map'] = merged_map
            # Write merged map back so we don't re-scan every time
            # (optional optimization — skip if it causes issues)

    return _build_node(sessions_dir, root_session_id, claude_id_to_dir,
                       set(), override_meta=root_meta)


def _merge_conversation_maps(
    sessions_dir: str, agent_name: str,
    claude_id_to_dir: dict[str, str],
) -> dict[str, str]:
    """Merge conversation_maps from all sessions for a given agent.

    The bridge creates a new dispatch session on each restart, so
    conversation_map entries are scattered across multiple session dirs.
    Merge them, keeping only entries whose child sessions still exist.
    """
    merged: dict[str, str] = {}
    if not os.path.isdir(sessions_dir):
        return merged
    try:
        for name in os.listdir(sessions_dir):
            meta = _read_metadata(sessions_dir, name)
            if meta is None:
                continue
            if meta.get('agent_name') != agent_name:
                continue
            for req_id, child_ref in meta.get('conversation_map', {}).items():
                # Resolve UUID to directory, check it exists
                child_dir = claude_id_to_dir.get(child_ref, child_ref)
                child_path = os.path.join(sessions_dir, child_dir)
                if os.path.isdir(child_path):
                    merged[req_id or child_ref] = child_ref
    except OSError:
        pass
    return merged


def _build_claude_id_index(sessions_dir: str) -> dict[str, str]:
    """Scan all session dirs and map claude_session_id → directory name."""
    index: dict[str, str] = {}
    if not os.path.isdir(sessions_dir):
        return index
    try:
        for name in os.listdir(sessions_dir):
            meta_path = os.path.join(sessions_dir, name, 'metadata.json')
            if not os.path.isfile(meta_path):
                continue
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                claude_sid = meta.get('claude_session_id', '')
                if claude_sid:
                    index[claude_sid] = name
            except (json.JSONDecodeError, OSError):
                continue
    except OSError:
        pass
    return index


def _build_node(sessions_dir: str, session_id: str,
                claude_id_to_dir: dict[str, str], visited: set,
                override_meta: dict | None = None) -> dict:
    """Recursively build a tree node."""
    # Prevent cycles
    if session_id in visited:
        return _make_stub(session_id)
    visited.add(session_id)

    metadata = override_meta or _read_metadata(sessions_dir, session_id)
    if metadata is None:
        return _make_stub(session_id)

    conversation_map = metadata.get('conversation_map', {})
    children = []
    for _request_id, child_ref in sorted(conversation_map.items()):
        # child_ref is a Claude session UUID. Resolve it to a directory name
        # via the reverse index. Fall back to direct lookup (if someone
        # stored a directory name directly).
        child_dir = claude_id_to_dir.get(child_ref, child_ref)
        child_node = _build_node(
            sessions_dir, child_dir, claude_id_to_dir, visited)
        children.append(child_node)

    return {
        'session_id': session_id,
        'agent_name': metadata.get('agent_name', 'unknown'),
        'conversation_id': metadata.get('conversation_id', ''),
        'status': _derive_status(sessions_dir, session_id),
        'children': children,
    }


def _read_metadata(sessions_dir: str, session_id: str) -> dict | None:
    """Read metadata.json for a session, returning None if not found."""
    meta_path = os.path.join(sessions_dir, session_id, 'metadata.json')
    if not os.path.isfile(meta_path):
        return None
    try:
        with open(meta_path) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _derive_status(sessions_dir: str, session_id: str) -> str:
    """Derive session status from heartbeat or metadata."""
    # Check for heartbeat file
    heartbeat_path = os.path.join(sessions_dir, session_id, '.heartbeat')
    if os.path.isfile(heartbeat_path):
        try:
            with open(heartbeat_path) as f:
                hb = json.load(f)
            status = hb.get('status', 'active')
            if status in ('completed', 'withdrawn'):
                return 'completed'
        except (json.JSONDecodeError, OSError):
            pass
    return 'active'


def _make_stub(session_id: str) -> dict:
    """Create a stub node for an unresolvable session."""
    return {
        'session_id': session_id,
        'agent_name': 'unknown',
        'conversation_id': '',
        'status': 'unknown',
        'children': [],
    }
