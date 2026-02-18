"""In-memory registry of active :class:`TeamSession` instances.

Sessions are keyed by ``conversation_id`` for cancellation support.
"""

from __future__ import annotations

import logging

from teaparty_app.services.team_session import TeamSession

logger = logging.getLogger(__name__)

_sessions: dict[str, TeamSession] = {}


def register_session(conversation_id: str, session: TeamSession) -> None:
    """Track a running session for cancellation."""
    _sessions[conversation_id] = session


def stop_session(conversation_id: str) -> None:
    """Stop and remove a session."""
    session = _sessions.pop(conversation_id, None)
    if session:
        session.stop()
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


def stop_all_sessions() -> None:
    """Stop all active sessions (for graceful shutdown)."""
    for conversation_id in list(_sessions.keys()):
        stop_session(conversation_id)
