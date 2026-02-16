"""In-memory registry of active :class:`TeamSession` instances.

Sessions are keyed by ``conversation_id``.  The registry is intentionally
*not* persistent — on server restart, sessions are re-created on the next
message to a multi-agent conversation.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from teaparty_app.services.team_session import TeamSession

if TYPE_CHECKING:
    from teaparty_app.models import Agent, Workgroup

logger = logging.getLogger(__name__)

_sessions: dict[str, TeamSession] = {}


async def get_or_create_session(
    conversation_id: str,
    agents: list[Agent],
    workgroup: Workgroup | None = None,
    worktree_path: str | None = None,
    conversation_name: str = "",
    conversation_description: str = "",
) -> TeamSession:
    """Return an existing session or start a new one."""
    session = _sessions.get(conversation_id)
    if session and session.is_running:
        return session

    # Clean up stale entry if present
    if session:
        try:
            await session.stop()
        except Exception:
            pass

    session = TeamSession(conversation_id, worktree_path)
    await session.start(
        agents,
        workgroup=workgroup,
        conversation_name=conversation_name,
        conversation_description=conversation_description,
    )
    _sessions[conversation_id] = session
    logger.info("Started team session for conversation %s with %d agents",
                conversation_id, len(agents))
    return session


async def stop_session(conversation_id: str) -> None:
    """Stop and remove a session."""
    session = _sessions.pop(conversation_id, None)
    if session:
        await session.stop()
        logger.info("Stopped team session for conversation %s", conversation_id)


def get_session(conversation_id: str) -> TeamSession | None:
    """Return the session if active, None otherwise."""
    session = _sessions.get(conversation_id)
    if session and session.is_running:
        return session
    return None


def active_session_count() -> int:
    """Return the number of active team sessions."""
    return sum(1 for s in _sessions.values() if s.is_running)


async def stop_all_sessions() -> None:
    """Stop all active sessions (for graceful shutdown)."""
    for conversation_id in list(_sessions.keys()):
        await stop_session(conversation_id)
