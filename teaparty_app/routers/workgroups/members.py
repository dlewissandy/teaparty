from datetime import timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from teaparty_app.deps import get_current_user
from teaparty_app.db import get_session
from teaparty_app.models import Invite, Membership, User, Workgroup, utc_now
from teaparty_app.schemas import (
    InviteCreateRequest,
    InviteDetailRead,
    InviteRead,
    MemberBudgetUpdateRequest,
    MemberRead,
    MemberRoleUpdateRequest,
    WorkgroupRead,
)
from teaparty_app.services.activity import add_activity_participant, post_activity
from teaparty_app.services.admin_workspace import list_members as list_workgroup_members
from teaparty_app.services.permissions import require_workgroup_membership, require_workgroup_owner

router = APIRouter(prefix="/api", tags=["workgroups"])


def _normalize_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@router.post("/workgroups/{workgroup_id}/invites", response_model=InviteRead)
def create_invite(
    workgroup_id: str,
    payload: InviteCreateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> InviteRead:
    require_workgroup_owner(session, workgroup_id, user.id)

    invite = Invite(
        workgroup_id=workgroup_id,
        invited_by_user_id=user.id,
        email=str(payload.email).lower(),
        token=str(uuid4()),
        expires_at=utc_now() + timedelta(days=7),
    )
    session.add(invite)
    session.commit()
    session.refresh(invite)
    return InviteRead.model_validate(invite)


@router.get("/workgroups/{workgroup_id}/invites", response_model=list[InviteRead])
def list_invites(
    workgroup_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[InviteRead]:
    require_workgroup_owner(session, workgroup_id, user.id)
    invites = session.exec(
        select(Invite)
        .where(Invite.workgroup_id == workgroup_id)
        .order_by(Invite.created_at.desc())
    ).all()
    return [InviteRead.model_validate(item) for item in invites]


@router.get("/invites/mine", response_model=list[InviteDetailRead])
def list_my_invites(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[InviteDetailRead]:
    invites = session.exec(
        select(Invite)
        .where(Invite.email == user.email.lower(), Invite.status == "pending")
        .order_by(Invite.created_at.desc())
    ).all()

    now = utc_now()
    results: list[InviteDetailRead] = []
    for invite in invites:
        expires_at = _normalize_utc(invite.expires_at)
        if expires_at and expires_at < now:
            invite.status = "expired"
            session.add(invite)
            continue
        results.append(invite)

    if len(results) != len(invites):
        session.commit()

    if not results:
        return []

    wg_ids = list({inv.workgroup_id for inv in results})
    inviter_ids = list({inv.invited_by_user_id for inv in results})

    workgroups = session.exec(select(Workgroup).where(Workgroup.id.in_(wg_ids))).all()
    wg_name_map = {wg.id: wg.name for wg in workgroups}

    inviters = session.exec(select(User).where(User.id.in_(inviter_ids))).all()
    inviter_name_map = {u.id: (u.name or u.email) for u in inviters}

    return [
        InviteDetailRead(
            id=inv.id,
            workgroup_id=inv.workgroup_id,
            workgroup_name=wg_name_map.get(inv.workgroup_id, ""),
            invited_by_name=inviter_name_map.get(inv.invited_by_user_id, ""),
            email=inv.email,
            token=inv.token,
            status=inv.status,
            created_at=inv.created_at,
        )
        for inv in results
    ]


@router.post("/workgroups/{workgroup_id}/invites/{token}/accept", response_model=WorkgroupRead)
def accept_invite(
    workgroup_id: str,
    token: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkgroupRead:
    invite = session.exec(
        select(Invite).where(
            Invite.workgroup_id == workgroup_id,
            Invite.token == token,
            Invite.status == "pending",
        )
    ).first()
    if not invite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")

    expires_at = _normalize_utc(invite.expires_at)
    if expires_at and expires_at < utc_now():
        invite.status = "expired"
        session.add(invite)
        session.commit()
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Invite has expired")

    if invite.email.lower() != user.email.lower():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invite email does not match current user")

    existing = session.exec(
        select(Membership).where(Membership.workgroup_id == workgroup_id, Membership.user_id == user.id)
    ).first()
    if not existing:
        session.add(Membership(workgroup_id=workgroup_id, user_id=user.id, role="member"))

    invite.status = "accepted"
    invite.accepted_at = utc_now()
    session.add(invite)

    add_activity_participant(session, workgroup_id, user.id)
    display_name = (user.name or "").strip() or user.email
    post_activity(session, workgroup_id, "member_joined", display_name, actor_user_id=user.id)

    session.commit()

    workgroup = session.get(Workgroup, workgroup_id)
    if not workgroup:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workgroup not found")
    return WorkgroupRead.model_validate(workgroup)


@router.post("/workgroups/{workgroup_id}/invites/{token}/decline", status_code=204)
def decline_invite(
    workgroup_id: str,
    token: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    invite = session.exec(
        select(Invite).where(
            Invite.workgroup_id == workgroup_id,
            Invite.token == token,
            Invite.status == "pending",
        )
    ).first()
    if not invite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")

    if invite.email.lower() != user.email.lower():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invite email does not match current user")

    invite.status = "declined"
    session.add(invite)
    session.commit()


@router.delete("/workgroups/{workgroup_id}/invites/{invite_id}", status_code=204)
def cancel_invite(
    workgroup_id: str,
    invite_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    require_workgroup_owner(session, workgroup_id, user.id)

    invite = session.exec(
        select(Invite).where(
            Invite.workgroup_id == workgroup_id,
            Invite.id == invite_id,
            Invite.status == "pending",
        )
    ).first()
    if not invite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")

    invite.status = "cancelled"
    session.add(invite)
    session.commit()


@router.get("/workgroups/{workgroup_id}/members", response_model=list[MemberRead])
def list_members(
    workgroup_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[MemberRead]:
    require_workgroup_membership(session, workgroup_id, user.id)
    rows = list_workgroup_members(session, workgroup_id)
    return [
        MemberRead(
            user_id=row_user.id,
            email=row_user.email,
            name=row_user.name,
            role=row_membership.role,
            picture=row_user.picture or "",
            budget_limit_usd=row_membership.budget_limit_usd,
            budget_used_usd=row_membership.budget_used_usd or 0.0,
        )
        for row_membership, row_user in rows
    ]


@router.patch("/workgroups/{workgroup_id}/members/{member_user_id}/role", response_model=MemberRead)
def update_member_role(
    workgroup_id: str,
    member_user_id: str,
    payload: MemberRoleUpdateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> MemberRead:
    require_workgroup_owner(session, workgroup_id, user.id)

    if member_user_id == user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot change your own role")

    membership = session.exec(
        select(Membership).where(
            Membership.workgroup_id == workgroup_id,
            Membership.user_id == member_user_id,
        )
    ).first()
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    membership.role = payload.role
    session.add(membership)
    session.commit()
    session.refresh(membership)

    member_user = session.get(User, member_user_id)
    if not member_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return MemberRead(
        user_id=member_user.id,
        email=member_user.email,
        name=member_user.name,
        role=membership.role,
        picture=member_user.picture or "",
        budget_limit_usd=membership.budget_limit_usd,
        budget_used_usd=membership.budget_used_usd or 0.0,
    )


@router.patch("/workgroups/{workgroup_id}/members/{member_user_id}/budget", response_model=MemberRead)
def update_member_budget(
    workgroup_id: str,
    member_user_id: str,
    payload: MemberBudgetUpdateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> MemberRead:
    require_workgroup_owner(session, workgroup_id, user.id)

    membership = session.exec(
        select(Membership).where(
            Membership.workgroup_id == workgroup_id,
            Membership.user_id == member_user_id,
        )
    ).first()
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    membership.budget_limit_usd = payload.budget_limit_usd
    if payload.reset_usage:
        membership.budget_used_usd = 0.0
        membership.budget_refreshed_at = utc_now()
    session.add(membership)
    session.commit()
    session.refresh(membership)

    member_user = session.get(User, member_user_id)
    if not member_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return MemberRead(
        user_id=member_user.id,
        email=member_user.email,
        name=member_user.name,
        role=membership.role,
        picture=member_user.picture or "",
        budget_limit_usd=membership.budget_limit_usd,
        budget_used_usd=membership.budget_used_usd or 0.0,
    )
