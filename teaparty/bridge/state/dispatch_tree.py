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
    claude_id_to_dir = _build_claude_id_index(sessions_dir)
    return _build_node(sessions_dir, root_session_id, claude_id_to_dir, set())


def _build_claude_id_index(sessions_dir: str) -> dict[str, str]:
    """Scan all session dirs and map claude_session_id -> directory name."""
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
                claude_id_to_dir: dict[str, str], visited: set) -> dict:
    """Recursively build a tree node."""
    if session_id in visited:
        return _make_stub(session_id)
    visited.add(session_id)

    metadata = _read_metadata(sessions_dir, session_id)
    if metadata is None:
        return _make_stub(session_id)

    conversation_map = metadata.get('conversation_map', {})
    children = []
    for _request_id, child_ref in sorted(conversation_map.items()):
        child_dir = claude_id_to_dir.get(child_ref, child_ref)
        child_node = _build_node(
            sessions_dir, child_dir, claude_id_to_dir, visited)
        children.append(child_node)

    # Child sessions use dispatch:{session_id} as conversation_id — this
    # is where the parent writes stream events for the child's chat section.
    conv_id = metadata.get('conversation_id', '') or f'dispatch:{session_id}'

    return {
        'session_id': session_id,
        'agent_name': metadata.get('agent_name', 'unknown'),
        'conversation_id': conv_id,
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
