from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from teaparty_app.db import get_session
from teaparty_app.deps import get_current_user
from teaparty_app.models import (
    Conversation,
    ConversationParticipant,
    Engagement,
    Membership,
    Message,
    User,
    Workgroup,
    utc_now,
)
from teaparty_app.schemas import (
    EngagementCancelRequest,
    EngagementCompleteRequest,
    EngagementCreateRequest,
    EngagementDetailRead,
    EngagementRead,
    EngagementRespondRequest,
    EngagementReviewRequest,
)
from teaparty_app.services.activity import post_activity
from teaparty_app.services.engagement_files import (
    create_engagement_files,
    update_engagement_files,
)

router = APIRouter(prefix="/api", tags=["engagements"])

ACTIVE_ENGAGEMENT_STATUSES = {"proposed", "negotiating", "in_progress", "completed"}


def _engagement_detail(session: Session, engagement: Engagement) -> EngagementDetailRead:
    source_wg = session.get(Workgroup, engagement.source_workgroup_id)
    target_wg = session.get(Workgroup, engagement.target_workgroup_id)
    return EngagementDetailRead(
        **EngagementRead.model_validate(engagement).model_dump(),
        source_workgroup_name=source_wg.name if source_wg else "",
        target_workgroup_name=target_wg.name if target_wg else "",
    )


def _post_system_message(session: Session, conversation_id: str | None, content: str) -> None:
    if not conversation_id:
        return
    session.add(
        Message(
            conversation_id=conversation_id,
            sender_type="system",
            content=content,
            requires_response=False,
        )
    )


def _require_engagement_participant(
    session: Session, engagement: Engagement, user_id: str
) -> Membership:
    for wg_id in (engagement.source_workgroup_id, engagement.target_workgroup_id):
        membership = session.exec(
            select(Membership).where(
                Membership.workgroup_id == wg_id,
                Membership.user_id == user_id,
            )
        ).first()
        if membership:
            return membership
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not a member of source or target workgroup",
    )


@router.post("/engagements", response_model=EngagementDetailRead)
def create_engagement(
    payload: EngagementCreateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> EngagementDetailRead:
    # Determine source workgroup
    source_workgroup_id = payload.source_workgroup_id
    if not source_workgroup_id:
        memberships = session.exec(
            select(Membership).where(Membership.user_id == user.id)
        ).all()
        for m in memberships:
            if m.workgroup_id != payload.target_workgroup_id:
                source_workgroup_id = m.workgroup_id
                break

    if not source_workgroup_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must belong to a workgroup other than the target to create an engagement",
        )

    # Verify membership in source
    source_membership = session.exec(
        select(Membership).where(
            Membership.workgroup_id == source_workgroup_id,
            Membership.user_id == user.id,
        )
    ).first()
    if not source_membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of the source workgroup",
        )

    target_wg = session.get(Workgroup, payload.target_workgroup_id)
    if not target_wg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target workgroup not found",
        )

    engagement = Engagement(
        source_workgroup_id=source_workgroup_id,
        target_workgroup_id=payload.target_workgroup_id,
        proposed_by_user_id=user.id,
        status="proposed",
        title=payload.title.strip(),
        scope=payload.scope.strip(),
        requirements=payload.requirements.strip(),
    )
    session.add(engagement)
    session.flush()

    # Create source conversation
    source_conversation = Conversation(
        workgroup_id=source_workgroup_id,
        created_by_user_id=user.id,
        kind="engagement",
        topic=f"engagement:{engagement.id}",
        name=engagement.title,
        description=f"Engagement with {target_wg.name}",
    )
    session.add(source_conversation)
    session.flush()
    session.add(
        ConversationParticipant(conversation_id=source_conversation.id, user_id=user.id)
    )

    # Create target conversation
    target_conversation = Conversation(
        workgroup_id=payload.target_workgroup_id,
        created_by_user_id=user.id,
        kind="engagement",
        topic=f"engagement:{engagement.id}",
        name=engagement.title,
        description=f"Engagement from {session.get(Workgroup, source_workgroup_id).name}",
    )
    session.add(target_conversation)
    session.flush()
    session.add(
        ConversationParticipant(conversation_id=target_conversation.id, user_id=user.id)
    )

    engagement.source_conversation_id = source_conversation.id
    engagement.target_conversation_id = target_conversation.id
    session.add(engagement)

    # Post system messages to both conversations
    proposal_msg = (
        f"[Engagement proposed] {engagement.title}\n"
        f"Scope: {engagement.scope or '(none)'}\n"
        f"Requirements: {engagement.requirements or '(none)'}"
    )
    _post_system_message(session, source_conversation.id, proposal_msg)
    _post_system_message(session, target_conversation.id, proposal_msg)

    # Post activity in both workgroups
    post_activity(session, source_workgroup_id, "engagement_proposed",
                  f"Proposed engagement: {engagement.title}", actor_user_id=user.id)
    post_activity(session, payload.target_workgroup_id, "engagement_proposed",
                  f"New engagement proposal: {engagement.title}", actor_user_id=user.id)

    session.commit()
    session.refresh(engagement)
    return _engagement_detail(session, engagement)


@router.get(
    "/workgroups/{workgroup_id}/engagements",
    response_model=list[EngagementRead],
)
def list_engagements(
    workgroup_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[EngagementRead]:
    membership = session.exec(
        select(Membership).where(
            Membership.workgroup_id == workgroup_id,
            Membership.user_id == user.id,
        )
    ).first()
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a workgroup member",
        )

    from sqlalchemy import or_

    engagements = session.exec(
        select(Engagement)
        .where(
            or_(
                Engagement.source_workgroup_id == workgroup_id,
                Engagement.target_workgroup_id == workgroup_id,
            )
        )
        .order_by(Engagement.created_at.desc())
    ).all()
    return [EngagementRead.model_validate(e) for e in engagements]


@router.get("/engagements/{engagement_id}", response_model=EngagementDetailRead)
def get_engagement(
    engagement_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> EngagementDetailRead:
    engagement = session.get(Engagement, engagement_id)
    if not engagement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Engagement not found",
        )
    _require_engagement_participant(session, engagement, user.id)
    return _engagement_detail(session, engagement)


@router.post("/engagements/{engagement_id}/respond", response_model=EngagementDetailRead)
def respond_to_engagement(
    engagement_id: str,
    payload: EngagementRespondRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> EngagementDetailRead:
    engagement = session.get(Engagement, engagement_id)
    if not engagement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Engagement not found",
        )

    # Only target workgroup owner can accept/decline
    target_membership = session.exec(
        select(Membership).where(
            Membership.workgroup_id == engagement.target_workgroup_id,
            Membership.user_id == user.id,
        )
    ).first()
    if not target_membership or target_membership.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the target workgroup owner can accept or decline engagements",
        )

    if engagement.status not in ("proposed", "negotiating"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot respond to engagement in status '{engagement.status}'",
        )

    now = utc_now()

    if payload.action == "decline":
        engagement.status = "declined"
        engagement.declined_at = now
        if payload.terms:
            engagement.terms = payload.terms.strip()
        session.add(engagement)

        _post_system_message(session, engagement.source_conversation_id,
                             f"[Engagement declined] {engagement.title}")
        _post_system_message(session, engagement.target_conversation_id,
                             f"[Engagement declined] {engagement.title}")

        post_activity(session, engagement.source_workgroup_id, "engagement_declined",
                      f"Engagement declined: {engagement.title}", actor_user_id=user.id)
        post_activity(session, engagement.target_workgroup_id, "engagement_declined",
                      f"Engagement declined: {engagement.title}", actor_user_id=user.id)

        session.commit()
        session.refresh(engagement)
        return _engagement_detail(session, engagement)

    # Accept flow
    engagement.status = "in_progress"
    engagement.accepted_at = now
    if payload.terms:
        engagement.terms = payload.terms.strip()
    session.add(engagement)

    terms_note = f"\nTerms: {engagement.terms}" if engagement.terms else ""
    _post_system_message(session, engagement.source_conversation_id,
                         f"[Engagement accepted] {engagement.title}{terms_note}")
    _post_system_message(session, engagement.target_conversation_id,
                         f"[Engagement accepted] {engagement.title}{terms_note}")

    # Create engagement files
    source_wg = session.get(Workgroup, engagement.source_workgroup_id)
    target_wg = session.get(Workgroup, engagement.target_workgroup_id)
    if source_wg and target_wg:
        create_engagement_files(session, engagement, source_wg, target_wg)

    post_activity(session, engagement.source_workgroup_id, "engagement_accepted",
                  f"Engagement accepted: {engagement.title}", actor_user_id=user.id)
    post_activity(session, engagement.target_workgroup_id, "engagement_accepted",
                  f"Engagement accepted: {engagement.title}", actor_user_id=user.id)

    session.commit()
    session.refresh(engagement)
    return _engagement_detail(session, engagement)


@router.post("/engagements/{engagement_id}/complete", response_model=EngagementDetailRead)
def complete_engagement(
    engagement_id: str,
    payload: EngagementCompleteRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> EngagementDetailRead:
    engagement = session.get(Engagement, engagement_id)
    if not engagement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Engagement not found",
        )

    target_membership = session.exec(
        select(Membership).where(
            Membership.workgroup_id == engagement.target_workgroup_id,
            Membership.user_id == user.id,
        )
    ).first()
    if not target_membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only target workgroup members can mark engagements complete",
        )

    if engagement.status != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot complete engagement in status '{engagement.status}'",
        )

    engagement.status = "completed"
    engagement.completed_at = utc_now()
    session.add(engagement)

    summary = payload.summary.strip() if payload.summary else "Engagement marked as completed."
    _post_system_message(session, engagement.source_conversation_id,
                         f"[Engagement completed] {summary}")
    _post_system_message(session, engagement.target_conversation_id,
                         f"[Engagement completed] {summary}")

    source_wg = session.get(Workgroup, engagement.source_workgroup_id)
    target_wg = session.get(Workgroup, engagement.target_workgroup_id)
    if source_wg and target_wg:
        update_engagement_files(session, engagement, source_wg, target_wg,
                                "Engagement completed", summary)

    post_activity(session, engagement.source_workgroup_id, "engagement_completed",
                  f"Engagement completed: {engagement.title}", actor_user_id=user.id)
    post_activity(session, engagement.target_workgroup_id, "engagement_completed",
                  f"Engagement completed: {engagement.title}", actor_user_id=user.id)

    session.commit()
    session.refresh(engagement)
    return _engagement_detail(session, engagement)


@router.post("/engagements/{engagement_id}/review", response_model=EngagementDetailRead)
def review_engagement(
    engagement_id: str,
    payload: EngagementReviewRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> EngagementDetailRead:
    engagement = session.get(Engagement, engagement_id)
    if not engagement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Engagement not found",
        )

    source_membership = session.exec(
        select(Membership).where(
            Membership.workgroup_id == engagement.source_workgroup_id,
            Membership.user_id == user.id,
        )
    ).first()
    if not source_membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only source workgroup members can review engagements",
        )

    if engagement.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot review engagement in status '{engagement.status}'",
        )

    engagement.status = "reviewed"
    engagement.reviewed_at = utc_now()
    engagement.review_rating = payload.rating
    engagement.review_feedback = payload.feedback.strip() if payload.feedback else ""
    session.add(engagement)

    notification = f"[Engagement reviewed: {payload.rating}]"
    if engagement.review_feedback:
        notification += f" Feedback: {engagement.review_feedback}"
    _post_system_message(session, engagement.source_conversation_id, notification)
    _post_system_message(session, engagement.target_conversation_id, notification)

    source_wg = session.get(Workgroup, engagement.source_workgroup_id)
    target_wg = session.get(Workgroup, engagement.target_workgroup_id)
    if source_wg and target_wg:
        update_engagement_files(session, engagement, source_wg, target_wg,
                                f"Reviewed: {payload.rating}",
                                engagement.review_feedback)

    post_activity(session, engagement.source_workgroup_id, "engagement_reviewed",
                  f"Engagement reviewed ({payload.rating}): {engagement.title}", actor_user_id=user.id)
    post_activity(session, engagement.target_workgroup_id, "engagement_reviewed",
                  f"Engagement reviewed ({payload.rating}): {engagement.title}", actor_user_id=user.id)

    session.commit()
    session.refresh(engagement)
    return _engagement_detail(session, engagement)


@router.post("/engagements/{engagement_id}/cancel", response_model=EngagementDetailRead)
def cancel_engagement(
    engagement_id: str,
    payload: EngagementCancelRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> EngagementDetailRead:
    engagement = session.get(Engagement, engagement_id)
    if not engagement:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Engagement not found",
        )

    _require_engagement_participant(session, engagement, user.id)

    if engagement.status not in ACTIVE_ENGAGEMENT_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel engagement in status '{engagement.status}'",
        )

    engagement.status = "cancelled"
    engagement.cancelled_at = utc_now()
    session.add(engagement)

    reason = payload.reason.strip() if payload.reason else ""
    cancel_msg = "[Engagement cancelled]"
    if reason:
        cancel_msg += f" Reason: {reason}"
    _post_system_message(session, engagement.source_conversation_id, cancel_msg)
    _post_system_message(session, engagement.target_conversation_id, cancel_msg)

    source_wg = session.get(Workgroup, engagement.source_workgroup_id)
    target_wg = session.get(Workgroup, engagement.target_workgroup_id)
    if source_wg and target_wg:
        update_engagement_files(session, engagement, source_wg, target_wg,
                                "Engagement cancelled", reason)

    post_activity(session, engagement.source_workgroup_id, "engagement_cancelled",
                  f"Engagement cancelled: {engagement.title}", actor_user_id=user.id)
    post_activity(session, engagement.target_workgroup_id, "engagement_cancelled",
                  f"Engagement cancelled: {engagement.title}", actor_user_id=user.id)

    session.commit()
    session.refresh(engagement)
    return _engagement_detail(session, engagement)
