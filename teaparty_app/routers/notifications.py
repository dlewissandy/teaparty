"""REST API for user notifications: list, counts, mark-as-read, and SSE stream."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from teaparty_app.db import commit_with_retry, get_session
from teaparty_app.deps import get_current_user
from teaparty_app.models import Notification, User
from teaparty_app.schemas import NotificationCountsRead, NotificationRead

router = APIRouter(prefix="/api", tags=["notifications"])


@router.get("/notifications", response_model=list[NotificationRead])
def list_notifications(
    type: str | None = None,
    is_read: bool | None = None,
    limit: int = 50,
    offset: int = 0,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[NotificationRead]:
    query = select(Notification).where(Notification.user_id == user.id)
    if type is not None:
        query = query.where(Notification.type == type)
    if is_read is not None:
        query = query.where(Notification.is_read == is_read)
    query = query.order_by(Notification.created_at.desc()).offset(offset).limit(limit)
    notifications = session.exec(query).all()
    return [NotificationRead.model_validate(n) for n in notifications]


@router.get("/notifications/counts", response_model=NotificationCountsRead)
def get_notification_counts(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> NotificationCountsRead:
    unread = session.exec(
        select(Notification).where(
            Notification.user_id == user.id,
            Notification.is_read == False,  # noqa: E712
        )
    ).all()
    return NotificationCountsRead(unread=len(unread))


@router.post("/notifications/{notification_id}/read", response_model=NotificationRead)
def mark_notification_read(
    notification_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> NotificationRead:
    notification = session.get(Notification, notification_id)
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found",
        )
    if notification.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not your notification",
        )
    notification.is_read = True
    session.add(notification)
    commit_with_retry(session)
    session.refresh(notification)
    return NotificationRead.model_validate(notification)


@router.get("/notifications/stream")
async def stream_notifications(
    request: Request,
    token: str = Query(...),
    session: Session = Depends(get_session),
) -> StreamingResponse:
    """SSE stream of real-time notification events for the authenticated user."""
    from teaparty_app.auth import decode_access_token
    from teaparty_app.services.event_bus import subscribe_user, unsubscribe_user

    user_id = decode_access_token(token)

    queue, handle = subscribe_user(user_id)

    async def event_stream():
        try:
            # Send initial keepalive so the client knows the connection is live.
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20)
                    yield f"data: {json.dumps(event, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            unsubscribe_user(user_id, handle)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
