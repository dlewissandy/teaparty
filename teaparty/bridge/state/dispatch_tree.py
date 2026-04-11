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
    return _build_node(sessions_dir, root_session_id, set())


def _build_node(sessions_dir: str, session_id: str, visited: set) -> dict:
    """Recursively build a tree node."""
    # Prevent cycles
    if session_id in visited:
        return _make_stub(session_id)
    visited.add(session_id)

    metadata = _read_metadata(sessions_dir, session_id)
    if metadata is None:
        return _make_stub(session_id)

    conversation_map = metadata.get('conversation_map', {})
    children = []
    for _request_id, child_session_id in sorted(conversation_map.items()):
        # conversation_map values may be session_ids (strings) or
        # claude session ids — only follow those that resolve to a
        # session directory with metadata.json
        child_node = _build_node(sessions_dir, child_session_id, visited)
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
