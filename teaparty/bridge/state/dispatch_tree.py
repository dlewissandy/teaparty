"""Build a dispatch tree from session metadata conversation_maps.

The dispatch tree shows which agents are running and their parent-child
relationships, derived by walking conversation_map entries in metadata.json
files starting from a root session.

The walker accepts multiple candidate ``sessions_dirs``.  A dispatch can
cross scopes — e.g. a project-scope session's ``conversation_map`` may
reference a management-scope proxy session created for an escalation.
The walker tries every candidate when resolving each session id, so the
tree reflects the true parent→child relationship regardless of where the
child's metadata lives on disk.
"""
from __future__ import annotations

import json
import os


def agent_name_from_conv_id(conv_id: str) -> str:
    """Derive the agent name from a conversation ID.

    Conversation IDs have a predictable structure:
        om:{qualifier}       → office-manager
        pm:{qualifier}       → project-manager
        proxy:{qualifier}    → proxy
        config:{qualifier}   → configuration-lead
        lead:{name}:{rest}   → {name}
    """
    if not conv_id:
        return 'unknown'
    prefix, _, rest = conv_id.partition(':')
    if prefix == 'om':
        return 'office-manager'
    if prefix == 'pm':
        return 'project-manager'
    if prefix == 'proxy':
        return 'proxy'
    if prefix == 'config':
        return 'configuration-lead'
    if prefix == 'lead':
        name, _, _ = rest.partition(':')
        return name or 'unknown'
    if prefix == 'job':
        # job:{project}:{session_id} — derive from project slug + '-lead'
        project, _, _ = rest.partition(':')
        return (project + '-lead') if project else 'unknown'
    return 'unknown'


def build_dispatch_tree(sessions_dirs: str | list[str], root_session_id: str,
                        conv_id: str = '') -> dict:
    """Build a nested dispatch tree starting from root_session_id.

    Each node contains:
        session_id: str
        agent_name: str
        conversation_id: str
        status: str  ('active' or 'completed')
        children: list[dict]  (recursive)

    ``sessions_dirs`` may be a single path (back-compat) or a list.  The
    walker tries every directory when resolving a session id — so a
    conversation_map entry in one scope can point at a session in
    another (e.g. a project-scope caller linking to a management-scope
    proxy escalation).

    If a child session_id in a conversation_map cannot be resolved in
    any candidate directory, it appears as a stub with
    agent_name='unknown'.

    All open conversations are returned — completed-but-not-closed
    dispatches stay in the tree with status='completed' until the
    caller explicitly invokes CloseConversation. The tree walks
    conversation_map, which is only cleared by close_fn; anything
    else is a still-open conversation whose parent owns the
    lifecycle.
    """
    if isinstance(sessions_dirs, str):
        sessions_dirs = [sessions_dirs]
    claude_id_to_dir = _build_claude_id_index(sessions_dirs)
    tree = _build_node(sessions_dirs, root_session_id, claude_id_to_dir, set())
    # When the root session has no metadata yet, derive agent_name from conv_id.
    if conv_id and tree.get('agent_name') == 'unknown':
        tree['agent_name'] = agent_name_from_conv_id(conv_id)
    if conv_id and not tree.get('conversation_id'):
        tree['conversation_id'] = conv_id
    return tree


def _build_claude_id_index(sessions_dirs: list[str]) -> dict[str, str]:
    """Scan all session dirs and map claude_session_id → '{dir}/{name}'.

    The value is a path-qualified dir name so callers can recover which
    sessions_dir a claude id resolved to.  Unambiguous because session
    directory names are uuids (no collisions across scopes).
    """
    index: dict[str, str] = {}
    for sessions_dir in sessions_dirs:
        if not os.path.isdir(sessions_dir):
            continue
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
            continue
    return index


def _build_node(sessions_dirs: list[str], session_id: str,
                claude_id_to_dir: dict[str, str], visited: set) -> dict:
    """Recursively build a tree node, crossing sessions_dirs as needed."""
    if session_id in visited:
        return _make_stub(session_id)
    visited.add(session_id)

    metadata, host_dir = _read_metadata(sessions_dirs, session_id)
    if metadata is None:
        return _make_stub(session_id)

    conversation_map = metadata.get('conversation_map', {})
    children = []
    for _request_id, child_ref in sorted(conversation_map.items()):
        child_dir = claude_id_to_dir.get(child_ref, child_ref)
        child_node = _build_node(
            sessions_dirs, child_dir, claude_id_to_dir, visited)
        children.append(child_node)

    # Child sessions use dispatch:{session_id} as conversation_id — this
    # is where the parent writes stream events for the child's chat section.
    conv_id = metadata.get('conversation_id', '') or f'dispatch:{session_id}'

    return {
        'session_id': session_id,
        'agent_name': metadata.get('agent_name', 'unknown'),
        'conversation_id': conv_id,
        'status': _derive_status(host_dir, session_id),
        'children': children,
    }


def _read_metadata(
    sessions_dirs: list[str], session_id: str,
) -> tuple[dict | None, str]:
    """Read metadata.json for a session from whichever candidate holds it.

    Returns (metadata_dict, host_sessions_dir) or (None, '') if not found.
    """
    for sessions_dir in sessions_dirs:
        meta_path = os.path.join(sessions_dir, session_id, 'metadata.json')
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path) as f:
                return json.load(f), sessions_dir
        except (json.JSONDecodeError, OSError):
            return None, ''
    return None, ''


def _derive_status(sessions_dir: str, session_id: str) -> str:
    """Derive session status from heartbeat or metadata."""
    if not sessions_dir:
        return 'active'
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
