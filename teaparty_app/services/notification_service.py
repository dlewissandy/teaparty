"""Service helpers for creating and querying Notification records."""

from __future__ import annotations

from sqlmodel import Session

from teaparty_app.models import Notification
from teaparty_app.services.event_bus import publish_user


def create_notification(
    session: Session,
    user_id: str,
    type: str,
    title: str,
    body: str = "",
    source_conversation_id: str | None = None,
    source_job_id: str | None = None,
    source_engagement_id: str | None = None,
) -> Notification:
    """Create a notification record and return it (caller must commit).

    Also pushes a real-time SSE event to any open user streams.
    """
    notification = Notification(
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        source_conversation_id=source_conversation_id,
        source_job_id=source_job_id,
        source_engagement_id=source_engagement_id,
    )
    session.add(notification)
    session.flush()

    # Push to any open SSE streams for this user.
    publish_user(user_id, {
        "type": "notification",
        "id": notification.id,
        "notification_type": notification.type,
        "title": notification.title,
        "body": notification.body,
        "source_conversation_id": notification.source_conversation_id,
        "source_job_id": notification.source_job_id,
        "source_engagement_id": notification.source_engagement_id,
        "is_read": False,
        "created_at": notification.created_at.isoformat(),
    })

    return notification
