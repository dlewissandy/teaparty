"""Bidirectional sync of messages between engagement conversation pairs."""

from __future__ import annotations

import logging

from sqlmodel import Session, select

from teaparty_app.models import (
    Agent,
    Engagement,
    EngagementSyncedMessage,
    Message,
    User,
    utc_now,
)

logger = logging.getLogger(__name__)

# System messages posted by lifecycle transitions — already in both conversations
LIFECYCLE_PREFIXES = (
    "[Engagement proposed]",
    "[Engagement accepted]",
    "[Engagement declined]",
    "[Engagement completed]",
    "[Engagement reviewed",
    "[Engagement cancelled]",
)


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


def sync_engagement_messages(
    session: Session,
    allowed_workgroup_ids: set[str],
) -> list[Message]:
    if not allowed_workgroup_ids:
        return []

    from sqlalchemy import or_

    # Find engagements where at least one side is in scope and status allows sync
    engagements = session.exec(
        select(Engagement).where(
            or_(
                Engagement.source_workgroup_id.in_(allowed_workgroup_ids),
                Engagement.target_workgroup_id.in_(allowed_workgroup_ids),
            ),
            Engagement.status.in_(["proposed", "negotiating", "in_progress", "completed"]),
            Engagement.source_conversation_id.isnot(None),
            Engagement.target_conversation_id.isnot(None),
        )
    ).all()

    if not engagements:
        return []

    created: list[Message] = []

    for engagement in engagements:
        # Build the set of all synced_message_ids (copies) for this engagement
        existing_synced = session.exec(
            select(EngagementSyncedMessage).where(
                EngagementSyncedMessage.engagement_id == engagement.id
            )
        ).all()
        copy_ids = {rec.synced_message_id for rec in existing_synced}
        origin_ids = {rec.origin_message_id for rec in existing_synced}

        # Sync source → target
        created.extend(
            _sync_direction(
                session,
                engagement,
                from_conversation_id=engagement.source_conversation_id,
                to_conversation_id=engagement.target_conversation_id,
                direction="source_to_target",
                copy_ids=copy_ids,
                origin_ids=origin_ids,
            )
        )

        # Sync target → source
        created.extend(
            _sync_direction(
                session,
                engagement,
                from_conversation_id=engagement.target_conversation_id,
                to_conversation_id=engagement.source_conversation_id,
                direction="target_to_source",
                copy_ids=copy_ids,
                origin_ids=origin_ids,
            )
        )

    return created


def _sync_direction(
    session: Session,
    engagement: Engagement,
    from_conversation_id: str,
    to_conversation_id: str,
    direction: str,
    copy_ids: set[str],
    origin_ids: set[str],
) -> list[Message]:
    messages = session.exec(
        select(Message)
        .where(Message.conversation_id == from_conversation_id)
        .order_by(Message.created_at.asc())
    ).all()

    created: list[Message] = []

    for message in messages:
        # Skip if this message is itself a copy
        if message.id in copy_ids:
            continue

        # Skip if already synced as an origin
        if message.id in origin_ids:
            continue

        # Skip lifecycle system messages (posted to both sides directly)
        if message.sender_type == "system" and message.content.startswith(LIFECYCLE_PREFIXES):
            continue

        attribution = _sender_attribution(session, message)
        synced_content = f"{attribution} {message.content}"

        synced_msg = Message(
            conversation_id=to_conversation_id,
            sender_type="system",
            content=synced_content,
            requires_response=False,
        )
        session.add(synced_msg)
        session.flush()

        record = EngagementSyncedMessage(
            engagement_id=engagement.id,
            origin_message_id=message.id,
            synced_message_id=synced_msg.id,
            direction=direction,
        )
        session.add(record)

        # Update tracking sets to prevent re-syncing in this pass
        copy_ids.add(synced_msg.id)
        origin_ids.add(message.id)

        created.append(synced_msg)

    return created
