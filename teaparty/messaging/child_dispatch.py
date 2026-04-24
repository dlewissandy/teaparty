"""Shared helpers for tier spawn_fns (CfA engine + chat-tier AgentSession).

Both tiers implement a ``spawn_fn(member, composite, context_id)`` that
``Send`` routes to via the in-process MCP registry.  The prelude of
those functions — thread-continuation detection, slot / pause checks,
child session creation, worktree setup, bus DISPATCH registration — is
the same mechanism across tiers.  This module holds the pieces both
sides agreed to share.
"""
from __future__ import annotations

import logging
from typing import Any

from teaparty.messaging.conversations import (
    ConversationState,
    SqliteMessageBus,
)

_log = logging.getLogger('teaparty.messaging.child_dispatch')


def detect_thread_continuation(
    *,
    context_id: str,
    bus_db_path: str,
    member: str,
    teaparty_home: str,
    scope: str,
) -> Any | None:
    """Return an existing child ``Session`` when ``context_id`` names an
    already-ACTIVE dispatch to *member*, or ``None`` to spawn a fresh one.

    ``Send`` accepts an optional ``context_id`` of the form
    ``dispatch:<child_session_id>``.  When the caller passes one and that
    dispatch is still ACTIVE with the same recipient agent, the tier
    should re-launch that child's on-disk session with ``--resume``
    rather than fork a new worktree and session — the human (or agent)
    is continuing an open conversation.

    This helper is the single place that reads the bus row and loads the
    session.  Caller decides what to do with the result: passing the
    returned ``Session`` into ``launch(resume_session=...)`` keeps the
    child's claude session continuous; passing ``None`` triggers the
    fresh-spawn path.
    """
    if not context_id or not context_id.startswith('dispatch:'):
        return None
    if not bus_db_path:
        return None

    bus = SqliteMessageBus(bus_db_path)
    try:
        conv = bus.get_conversation(context_id)
    finally:
        bus.close()

    if conv is None:
        return None
    if conv.state != ConversationState.ACTIVE:
        return None
    if conv.agent_name != member:
        return None

    from teaparty.runners.launcher import load_session as _load_session
    child_sid = context_id[len('dispatch:'):]
    return _load_session(
        agent_name=member,
        scope=scope,
        teaparty_home=teaparty_home,
        session_id=child_sid,
    )
