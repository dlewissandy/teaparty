"""Bridge between team sessions and the TeaParty message store.

Reads :class:`TeamEvent` objects from a :class:`TeamSession` and converts
them to :class:`Message` records in the database so they appear in the
conversation's chat UI.
"""

from __future__ import annotations

import asyncio
import logging
import time

from sqlmodel import Session

from teaparty_app.db import commit_with_retry
from teaparty_app.models import Conversation, Message, utc_now
from teaparty_app.services.agent_runtime import infer_requires_response
from teaparty_app.services.team_session import TeamEvent, TeamSession

logger = logging.getLogger(__name__)

# Maximum time (seconds) to wait for events after sending a message.
_EVENT_TIMEOUT = 120.0

# Maximum time (seconds) of silence before assuming the team is done.
_IDLE_TIMEOUT = 10.0


def process_team_events_sync(
    session: Session,
    team: TeamSession,
    conversation: Conversation,
    trigger: Message,
) -> list[Message]:
    """Synchronous wrapper: drain team events and store as Messages.

    Blocks until the team goes idle (no events for ``_IDLE_TIMEOUT`` seconds)
    or the overall ``_EVENT_TIMEOUT`` is exceeded.
    """
    return asyncio.run(_process_team_events(session, team, conversation, trigger))


async def _process_team_events(
    session: Session,
    team: TeamSession,
    conversation: Conversation,
    trigger: Message,
) -> list[Message]:
    """Read events from the team session and convert to TeaParty Messages."""
    created: list[Message] = []
    deadline = time.monotonic() + _EVENT_TIMEOUT
    # Buffer for accumulating text deltas into complete messages
    text_buffer: str = ""
    current_agent_slug: str = ""

    while time.monotonic() < deadline:
        remaining = min(_IDLE_TIMEOUT, deadline - time.monotonic())
        if remaining <= 0:
            break

        try:
            event = await asyncio.wait_for(team.event_queue.get(), timeout=remaining)
        except asyncio.TimeoutError:
            # No events for _IDLE_TIMEOUT — flush buffer and stop
            if text_buffer.strip():
                msg = _store_text_message(
                    session, conversation, trigger, team, current_agent_slug, text_buffer,
                )
                if msg:
                    created.append(msg)
                text_buffer = ""
            break

        if event.kind == "assistant":
            # Complete assistant message — flush any buffered text first
            if text_buffer.strip():
                msg = _store_text_message(
                    session, conversation, trigger, team, current_agent_slug, text_buffer,
                )
                if msg:
                    created.append(msg)
                text_buffer = ""

            if event.content.strip():
                msg = _store_text_message(
                    session, conversation, trigger, team, event.agent_slug, event.content,
                )
                if msg:
                    created.append(msg)

        elif event.kind == "text_delta":
            text_buffer += event.content
            current_agent_slug = event.agent_slug or current_agent_slug

        elif event.kind == "tool_use":
            # Store a system message noting the tool invocation
            tool_msg = Message(
                conversation_id=conversation.id,
                sender_type="system",
                content=f"[Tool] {event.tool_name}",
            )
            session.add(tool_msg)
            session.flush()
            try:
                commit_with_retry(session)
            except Exception as exc:
                logger.warning("Failed to commit tool_use message: %s", exc)

        elif event.kind == "result":
            # Final result from the team session — flush and store
            if text_buffer.strip():
                msg = _store_text_message(
                    session, conversation, trigger, team, current_agent_slug, text_buffer,
                )
                if msg:
                    created.append(msg)
                text_buffer = ""

            if event.content.strip():
                msg = _store_text_message(
                    session, conversation, trigger, team, "", event.content,
                )
                if msg:
                    created.append(msg)
            break

        elif event.kind == "error":
            error_msg = Message(
                conversation_id=conversation.id,
                sender_type="system",
                content=f"(Team error: {event.content})",
            )
            session.add(error_msg)
            session.flush()
            try:
                commit_with_retry(session)
            except Exception as exc:
                logger.warning("Failed to commit error message: %s", exc)
            break

    # Final flush
    if text_buffer.strip():
        msg = _store_text_message(
            session, conversation, trigger, team, current_agent_slug, text_buffer,
        )
        if msg:
            created.append(msg)

    return created


def _store_text_message(
    session: Session,
    conversation: Conversation,
    trigger: Message,
    team: TeamSession,
    agent_slug: str,
    content: str,
) -> Message | None:
    """Store text content as an agent Message, mapping slug to agent_id."""
    content = content.strip()
    if not content:
        return None

    agent_id = team.get_agent_id(agent_slug) if agent_slug else None

    msg = Message(
        conversation_id=conversation.id,
        sender_type="agent" if agent_id else "system",
        sender_agent_id=agent_id,
        content=content,
        requires_response=infer_requires_response(content),
        response_to_message_id=trigger.id,
    )
    session.add(msg)
    session.flush()

    try:
        commit_with_retry(session)
    except Exception as exc:
        logger.warning("Failed to commit team message: %s", exc)

    return msg
