"""Bridge between team sessions and the TeaParty message store.

Reads :class:`TeamEvent` objects from a :class:`TeamSession` and converts
them to :class:`Message` records in the database so they appear in the
conversation's chat UI.

Events are processed incrementally: each assistant text block, sub-agent
response, and final result is committed to the database as soon as it
arrives so the frontend picks it up via its polling loop.

Key insight: during Task execution, the sub-agent's intermediate
``assistant`` events leak into the parent stream.  If we naively post
them as lead messages, the actual ``tool_result`` (which carries the
correct sub-agent attribution) gets deduplicated away.  So we suppress
``assistant`` text while tasks are pending — only post it when it comes
from the lead's own turn (no pending tasks, or the event itself contains
new Task delegations).
"""

from __future__ import annotations

import json
import logging
import queue
import time

from sqlmodel import Session

from teaparty_app.db import commit_with_retry
from teaparty_app.models import Conversation, Message
from teaparty_app.services.agent_runtime import (
    _clear_activity,
    _set_activity,
    infer_requires_response,
)
from teaparty_app.services.team_output_parser import (
    _extract_tool_result_text,
    _resolve_agent_id,
)
from teaparty_app.services.team_session import TeamSession

logger = logging.getLogger(__name__)

# Maximum time (seconds) to wait for events after sending a message.
_EVENT_TIMEOUT = 300.0

# Maximum time (seconds) of silence before assuming the team is done.
_IDLE_TIMEOUT = 30.0


def _track_task_delegation(
    block_or_raw: dict,
    pending_tasks: dict[str, str],
    slug_to_id: dict[str, str],
    conversation_id: str,
) -> None:
    """Track a Task tool_use and set the sub-agent's activity.

    Works for both inline tool_use blocks (inside assistant events)
    and standalone tool_use events.
    """
    tool_use_id = block_or_raw.get("id", "")
    inp = block_or_raw.get("input") or {}
    sub_agent = (
        inp.get("name")
        or inp.get("subagent_type")
        or inp.get("description")
        or ""
    )
    if not tool_use_id:
        return

    pending_tasks[tool_use_id] = sub_agent

    # Set sub-agent activity to "composing".
    agent_id = _resolve_agent_id(sub_agent, slug_to_id)
    if agent_id:
        agent_name = sub_agent
        for slug, aid in slug_to_id.items():
            if aid == agent_id:
                agent_name = slug
                break
        _set_activity(conversation_id, agent_id, agent_name, "composing", "team")


def process_team_events_sync(
    session: Session,
    team: TeamSession,
    conversation: Conversation,
    trigger: Message,
) -> list[Message]:
    """Drain team events and store agent contributions incrementally.

    Processes events one at a time as they arrive from the team session:

    - **assistant** events: if this is a lead turn (no pending tasks, or
      the event itself contains Task delegations), post text and track
      delegations.  Otherwise suppress — it's a sub-agent intermediate
      event that would steal attribution from the real tool_result.
    - **tool_use** events: backup path for tracking Task delegations.
    - **tool_result** events: post sub-agent responses immediately,
      clear sub-agent activity.
    - **result** event: post lead's final text if not already posted.
    """
    created: list[Message] = []
    deadline = time.monotonic() + _EVENT_TIMEOUT

    slug_to_id = dict(team._agent_slugs)
    lead_id = next(iter(team._agent_slugs.values()), None)

    # Track pending Task delegations: tool_use_id → sub_agent_hint
    pending_tasks: dict[str, str] = {}
    # Track posted content to avoid duplicates.
    posted_texts: set[str] = set()

    def _store_message(agent_id: str | None, content: str) -> Message | None:
        content = content.strip()
        if not content or content in posted_texts:
            return None
        posted_texts.add(content)

        if agent_id is None:
            agent_id = lead_id

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
        created.append(msg)
        return msg

    while time.monotonic() < deadline:
        remaining = min(_IDLE_TIMEOUT, deadline - time.monotonic())
        if remaining <= 0:
            break

        try:
            event = team.event_queue.get(timeout=remaining)
        except queue.Empty:
            if not team.is_running:
                break
            continue

        if event.kind == "eof":
            break

        if event.kind == "error":
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
            return [error_msg]

        # --- assistant: lead text and/or Task delegations ---
        if event.kind == "assistant":
            # Snapshot before processing — if tasks were already pending,
            # this assistant event is an intermediate sub-agent event,
            # not the lead speaking.
            was_pending = bool(pending_tasks)

            raw = event.raw
            message = raw.get("message") or {}
            content_blocks = message.get("content") or []

            text_parts: list[str] = []
            has_new_delegation = False
            for block in content_blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text = (block.get("text") or "").strip()
                    if text:
                        text_parts.append(text)
                elif block.get("type") == "tool_use" and block.get("name") == "Task":
                    has_new_delegation = True
                    _track_task_delegation(
                        block, pending_tasks, slug_to_id, conversation.id,
                    )

            # Post lead text only when this is actually the lead's turn:
            #  - No tasks were pending before (fresh lead turn), or
            #  - This event itself contains Task delegations (lead text
            #    accompanying a delegation, e.g. "Let me ask the team...")
            # Skip intermediate assistant events that leak from sub-agents
            # during Task execution — the tool_result is the authoritative
            # source for sub-agent content.
            if text_parts and (not was_pending or has_new_delegation):
                _store_message(lead_id, "\n\n".join(text_parts))
            elif text_parts and was_pending:
                logger.debug(
                    "Suppressed intermediate assistant text during Task "
                    "execution (likely sub-agent): %.100s…",
                    text_parts[0],
                )

        # --- standalone tool_use: backup path for Task tracking ---
        elif event.kind == "tool_use" and event.tool_name == "Task":
            raw = event.raw
            _track_task_delegation(
                raw, pending_tasks, slug_to_id, conversation.id,
            )

        # --- tool_result: sub-agent response ---
        elif event.kind == "tool_result":
            raw = event.raw
            tool_use_id = raw.get("tool_use_id", "")
            if tool_use_id in pending_tasks:
                sub_agent_hint = pending_tasks.pop(tool_use_id)
                content = _extract_tool_result_text(raw)
                if content:
                    agent_id = _resolve_agent_id(sub_agent_hint, slug_to_id)
                    _store_message(agent_id, content)
                    if agent_id:
                        _clear_activity(conversation.id, agent_id)

        # --- inbox: agent-to-agent message from inbox file ---
        elif event.kind == "inbox":
            from_name = event.raw.get("from", "")
            recipient_name = event.raw.get("recipient", "")
            text = event.content.strip()
            if not text or text in posted_texts:
                continue
            sender_id = _resolve_agent_id(from_name, slug_to_id)
            formatted = f"@{recipient_name} {text}" if recipient_name else text
            msg = _store_message(sender_id, formatted)
            if msg:
                posted_texts.add(text)

        # --- result: final output ---
        elif event.kind == "result":
            if event.content:
                _store_message(lead_id, event.content)
            break

    return created
