"""Build a dispatch tree from the bus's conversations table (#422).

Single source of truth: ``bus.children_of(parent_conversation_id)``
returns every child this conversation dispatched, with ``agent_name``,
``state``, and ``request_id`` already on the record.  No disk walks,
no metadata resolution, no ``agent_name='unknown'`` stubs.

The signature takes a ``SqliteMessageBus`` and a root ``conv_id``.
Callers that only know the root by session id pass
``f'dispatch:{session_id}'`` — the convention every writer uses
(chat tier's spawn_fn and CfA's ``_bus_spawn_agent``).

For historical root conversations that were created by the bridge's
POST-conversation path (OM, PM, proxy, lead, config), the bus row
exists but may lack ``agent_name`` (bridge auto-create predates the
#422 column set).  In that case we derive the name from the conv_id
prefix — a bounded fallback for a small, closed set of root types,
not a general synthesis point.

Terminal children (state ``closed`` or ``withdrawn``) are elided from
the tree.  The accordion renders one blade per node, so a closed blade
reappearing in the response makes it come back in the UI even after
the user watched it close.  The bus row stays on disk for audit and
recursive close bookkeeping; it just isn't a live blade anymore.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from teaparty.messaging.conversations import ConversationState

if TYPE_CHECKING:
    from teaparty.messaging.conversations import SqliteMessageBus


_ROOT_PREFIX_NAMES = {
    'om': 'office-manager',
    'pm': 'project-manager',
    'proxy': 'proxy',
    'config': 'configuration-lead',
}

# States a conversation must NOT be in to appear in the dispatch tree.
# Closed: work merged back, worktree gone.
# Withdrawn: user explicitly killed it.
# Both are terminal — the blade should not reappear in the accordion.
_TERMINAL_STATES = frozenset({
    ConversationState.CLOSED,
    ConversationState.WITHDRAWN,
})


def agent_name_from_conv_id(conv_id: str) -> str:
    """Derive the agent name for a root conversation from its conv_id.

    Used only when the bus record exists but ``agent_name`` is empty
    (pre-#422 auto-created roots).  For DISPATCH conversations the bus
    always carries the name — don't call this for them.
    """
    if not conv_id:
        return ''
    prefix, _, rest = conv_id.partition(':')
    if prefix in _ROOT_PREFIX_NAMES:
        return _ROOT_PREFIX_NAMES[prefix]
    if prefix == 'lead':
        name, _, _ = rest.partition(':')
        return name
    if prefix == 'job':
        project, _, _ = rest.partition(':')
        return f'{project}-lead' if project else ''
    return ''


def build_dispatch_tree(
    bus: 'SqliteMessageBus',
    root_conv_id: str,
    *,
    root_session_id: str = '',
) -> dict:
    """Build a nested dispatch tree starting from *root_conv_id*.

    The tree reflects the bus's ``conversations`` table.  Each node:

        {
            'conversation_id': str,
            'session_id':      str,
            'agent_name':      str,      # lead of this conversation
            'status':          str,      # bus state: pending|active|paused|closed|withdrawn
            'children':        list[node]
        }

    The root may or may not be registered in the bus itself:
      - Top-level chat roots (om, pm, proxy, lead, config) are
        registered by the bridge's POST handler; agent_name may
        need to be derived from the conv_id prefix.
      - Dispatched roots (CfA job page) are registered by spawn_fn;
        agent_name is on the row.
    """
    return _build_node(bus, root_conv_id, root_session_id, set())


def _build_node(
    bus: 'SqliteMessageBus',
    conv_id: str,
    session_id: str,
    visited: set,
) -> dict:
    if conv_id in visited:
        return _stub(conv_id, session_id)
    visited.add(conv_id)

    conv = bus.get_conversation(conv_id)
    if conv is None:
        # Root that was never registered — fall back to prefix-derived
        # name.  Children are whatever children_of returns (empty if none
        # were dispatched yet).
        agent_name = agent_name_from_conv_id(conv_id)
        status = 'active'
    else:
        agent_name = conv.agent_name or agent_name_from_conv_id(conv_id)
        status = conv.state.value

    children = []
    for child in bus.children_of(conv_id):
        # Terminal children never become accordion blades — otherwise a
        # just-closed blade re-materializes on the next /api/dispatch-tree
        # fetch and the user sees it at the bottom of the list.  The bus
        # row is retained; it just isn't part of the live UI tree.
        if child.state in _TERMINAL_STATES:
            continue
        # Convention: dispatch conv_id is ``dispatch:{session_id}``.
        # Extract session_id from the conv_id for the tree node.
        _, _, child_sid = child.id.partition(':')
        children.append(_build_node(bus, child.id, child_sid, visited))

    return {
        'conversation_id': conv_id,
        'session_id': session_id,
        'agent_name': agent_name,
        'status': status,
        'children': children,
    }


def _stub(conv_id: str, session_id: str) -> dict:
    """Cycle-guard stub.  Only reached via a malformed parent graph."""
    return {
        'conversation_id': conv_id,
        'session_id': session_id,
        'agent_name': agent_name_from_conv_id(conv_id),
        'status': 'unknown',
        'children': [],
    }
