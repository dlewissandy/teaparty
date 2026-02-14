"""Sync messages from target task conversations into source mirror topics."""

from __future__ import annotations

import logging

from sqlmodel import Session, select

from teaparty_app.models import (
    Agent,
    CrossGroupTask,
    Message,
    SyncedMessage,
    User,
    utc_now,
)

logger = logging.getLogger(__name__)


def _sender_attribution(session: Session, message: Message) -> str:
    if message.sender_type == "user" and message.sender_user_id:
        user = session.get(User, message.sender_user_id)
        name = (user.name or user.email) if user else "unknown"
        return f"[synced from {name}]"
    if message.sender_type == "agent" and message.sender_agent_id:
        agent = session.get(Agent, message.sender_agent_id)
        name = agent.name if agent else "agent"
        return f"[synced from agent {name}]"
    if message.sender_type == "system":
        return "[synced system message]"
    return "[synced]"


def sync_cross_group_messages(
    session: Session,
    allowed_workgroup_ids: set[str],
) -> list[Message]:
    if not allowed_workgroup_ids:
        return []

    # Find all in_progress or completed tasks where source workgroup is in scope
    tasks = session.exec(
        select(CrossGroupTask).where(
            CrossGroupTask.source_workgroup_id.in_(allowed_workgroup_ids),
            CrossGroupTask.status.in_(["in_progress", "completed"]),
            CrossGroupTask.target_conversation_id.isnot(None),
            CrossGroupTask.source_conversation_id.isnot(None),
        )
    ).all()

    if not tasks:
        return []

    created: list[Message] = []

    for task in tasks:
        # Get all messages in the target conversation
        target_messages = session.exec(
            select(Message)
            .where(Message.conversation_id == task.target_conversation_id)
            .order_by(Message.created_at.asc())
        ).all()

        if not target_messages:
            continue

        # Get already synced source message IDs for this task
        already_synced = session.exec(
            select(SyncedMessage.source_message_id).where(
                SyncedMessage.task_id == task.id
            )
        ).all()
        synced_ids = set(already_synced)

        for message in target_messages:
            if message.id in synced_ids:
                continue

            # Skip system messages that were posted by the accept/complete flow
            # (they already exist in the source conversation)
            if message.sender_type == "system" and message.content.startswith(
                ("[Cross-group task started]", "[Task completed]", "[Task satisfied]", "[Task dissatisfied]")
            ):
                continue

            attribution = _sender_attribution(session, message)
            mirror_content = f"{attribution} {message.content}"

            mirror_msg = Message(
                conversation_id=task.source_conversation_id,
                sender_type="system",
                content=mirror_content,
                requires_response=False,
            )
            session.add(mirror_msg)
            session.flush()

            synced = SyncedMessage(
                task_id=task.id,
                source_message_id=message.id,
                mirror_message_id=mirror_msg.id,
            )
            session.add(synced)
            created.append(mirror_msg)

    return created
