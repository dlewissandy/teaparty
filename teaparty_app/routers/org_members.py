"""REST API for org-level membership and invites."""

from __future__ import annotations

from datetime import timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from teaparty_app.db import get_session
from teaparty_app.deps import get_current_user
from teaparty_app.models import Membership, Organization, OrgInvite, OrgMembership, User, Workgroup, utc_now
from teaparty_app.schemas import (
    OrgInviteCreateRequest,
    OrgInviteDetailRead,
    OrgInviteRead,
    OrgMemberRead,
)
from teaparty_app.services.activity import post_activity
from teaparty_app.services.event_bus import publish_user

router = APIRouter(prefix="/api", tags=["org-members"])


def _normalize_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _require_org_owner(session: Session, org_id: str, user_id: str) -> Organization:
    org = session.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    if org.owner_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the organization owner can perform this action")
    return org


def _require_org_access(session: Session, org_id: str, user_id: str) -> Organization:
    org = session.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    if org.owner_id == user_id:
        return org
    membership = session.exec(
        select(OrgMembership).where(
            OrgMembership.organization_id == org_id,
            OrgMembership.user_id == user_id,
        )
    ).first()
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a member of this organization")
    return org


@router.get("/organizations/{org_id}/org-members", response_model=list[OrgMemberRead])
def list_org_members(
    org_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[OrgMemberRead]:
    _require_org_access(session, org_id, user.id)

    memberships = session.exec(
        select(OrgMembership).where(OrgMembership.organization_id == org_id)
    ).all()

    result = []
    for m in memberships:
        member_user = session.get(User, m.user_id)
        if not member_user:
            continue
        result.append(OrgMemberRead(
            user_id=m.user_id,
            email=member_user.email,
            name=member_user.name,
            role=m.role,
            picture=member_user.picture or "",
        ))
    return result


@router.post("/organizations/{org_id}/org-invites", response_model=OrgInviteRead)
def create_org_invite(
    org_id: str,
    payload: OrgInviteCreateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> OrgInviteRead:
    _require_org_owner(session, org_id, user.id)

    invite = OrgInvite(
        organization_id=org_id,
        invited_by_user_id=user.id,
        email=str(payload.email).lower(),
        token=str(uuid4()),
        expires_at=utc_now() + timedelta(days=7),
    )
    session.add(invite)
    session.commit()
    session.refresh(invite)

    # Push SSE event to the invited user (if they exist)
    invited_user = session.exec(
        select(User).where(User.email == invite.email)
    ).first()
    if invited_user:
        org = session.get(Organization, org_id)
        publish_user(invited_user.id, {
            "type": "org_invite_received",
            "organization_id": org_id,
            "organization_name": org.name if org else "",
            "invited_by": user.name or user.email,
        })

    return OrgInviteRead.model_validate(invite)


@router.get("/organizations/{org_id}/org-invites", response_model=list[OrgInviteRead])
def list_org_invites(
    org_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[OrgInviteRead]:
    _require_org_owner(session, org_id, user.id)

    invites = session.exec(
        select(OrgInvite)
        .where(OrgInvite.organization_id == org_id, OrgInvite.status == "pending")
        .order_by(OrgInvite.created_at.desc())
    ).all()
    return [OrgInviteRead.model_validate(inv) for inv in invites]


@router.get("/org-invites/mine", response_model=list[OrgInviteDetailRead])
def list_my_org_invites(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[OrgInviteDetailRead]:
    invites = session.exec(
        select(OrgInvite)
        .where(OrgInvite.email == user.email.lower(), OrgInvite.status == "pending")
        .order_by(OrgInvite.created_at.desc())
    ).all()

    now = utc_now()
    results: list[OrgInvite] = []
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

    org_ids = list({inv.organization_id for inv in results})
    inviter_ids = list({inv.invited_by_user_id for inv in results})

    orgs = session.exec(select(Organization).where(Organization.id.in_(org_ids))).all()
    org_name_map = {o.id: o.name for o in orgs}

    inviters = session.exec(select(User).where(User.id.in_(inviter_ids))).all()
    inviter_name_map = {u.id: (u.name or u.email) for u in inviters}

    return [
        OrgInviteDetailRead(
            id=inv.id,
            organization_id=inv.organization_id,
            organization_name=org_name_map.get(inv.organization_id, ""),
            invited_by_name=inviter_name_map.get(inv.invited_by_user_id, ""),
            email=inv.email,
            token=inv.token,
            status=inv.status,
            created_at=inv.created_at,
        )
        for inv in results
    ]


@router.post("/organizations/{org_id}/org-invites/{token}/accept", response_model=OrgMemberRead)
def accept_org_invite(
    org_id: str,
    token: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> OrgMemberRead:
    invite = session.exec(
        select(OrgInvite).where(
            OrgInvite.organization_id == org_id,
            OrgInvite.token == token,
            OrgInvite.status == "pending",
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

    # Create OrgMembership if not already a member
    existing_org_membership = session.exec(
        select(OrgMembership).where(
            OrgMembership.organization_id == org_id,
            OrgMembership.user_id == user.id,
        )
    ).first()
    if not existing_org_membership:
        session.add(OrgMembership(organization_id=org_id, user_id=user.id, role="member"))

    # Also ensure workgroup-level memberships so permissions checks keep working
    workgroups = session.exec(
        select(Workgroup).where(Workgroup.organization_id == org_id)
    ).all()
    for wg in workgroups:
        existing_wg_membership = session.exec(
            select(Membership).where(
                Membership.workgroup_id == wg.id,
                Membership.user_id == user.id,
            )
        ).first()
        if not existing_wg_membership:
            session.add(Membership(workgroup_id=wg.id, user_id=user.id, role="member"))

    invite.status = "accepted"
    invite.accepted_at = utc_now()
    session.add(invite)

    org = session.get(Organization, org_id)
    display_name = (user.name or "").strip() or user.email
    if org:
        post_activity(session, org.operations_workgroup_id or "", "member_joined", display_name, actor_user_id=user.id)

    # Collect existing member IDs before commit (to notify them)
    existing_members = session.exec(
        select(OrgMembership.user_id).where(
            OrgMembership.organization_id == org_id,
            OrgMembership.user_id != user.id,
        )
    ).all()

    session.commit()

    # Notify existing org members so their member list updates immediately
    for member_user_id in existing_members:
        publish_user(member_user_id, {
            "type": "org_member_joined",
            "organization_id": org_id,
            "user_name": display_name,
        })

    return OrgMemberRead(
        user_id=user.id,
        email=user.email,
        name=user.name,
        role="member",
        picture=user.picture or "",
    )


@router.post("/organizations/{org_id}/org-invites/{token}/decline", status_code=204)
def decline_org_invite(
    org_id: str,
    token: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    invite = session.exec(
        select(OrgInvite).where(
            OrgInvite.organization_id == org_id,
            OrgInvite.token == token,
            OrgInvite.status == "pending",
        )
    ).first()
    if not invite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")

    if invite.email.lower() != user.email.lower():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invite email does not match current user")

    invite.status = "declined"
    session.add(invite)

    org = session.get(Organization, org_id)
    session.commit()

    # Notify org owner so their directory invite state refreshes
    if org:
        publish_user(org.owner_id, {
            "type": "org_invite_declined",
            "organization_id": org_id,
            "email": invite.email,
        })


@router.delete("/organizations/{org_id}/org-invites/{invite_id}", status_code=204)
def cancel_org_invite(
    org_id: str,
    invite_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    _require_org_owner(session, org_id, user.id)

    invite = session.exec(
        select(OrgInvite).where(
            OrgInvite.organization_id == org_id,
            OrgInvite.id == invite_id,
            OrgInvite.status == "pending",
        )
    ).first()
    if not invite:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")

    invite.status = "cancelled"
    session.add(invite)
    session.commit()


@router.delete("/organizations/{org_id}/org-members/{member_user_id}", status_code=204)
def remove_org_member(
    org_id: str,
    member_user_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    org = _require_org_owner(session, org_id, user.id)

    if member_user_id == user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove yourself")

    if org.owner_id == member_user_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove the organization owner")

    org_membership = session.exec(
        select(OrgMembership).where(
            OrgMembership.organization_id == org_id,
            OrgMembership.user_id == member_user_id,
        )
    ).first()
    if not org_membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")

    session.delete(org_membership)

    # Also remove all workgroup-level memberships in this org
    workgroups = session.exec(
        select(Workgroup).where(Workgroup.organization_id == org_id)
    ).all()
    for wg in workgroups:
        wg_membership = session.exec(
            select(Membership).where(
                Membership.workgroup_id == wg.id,
                Membership.user_id == member_user_id,
            )
        ).first()
        if wg_membership:
            session.delete(wg_membership)

    member_user = session.get(User, member_user_id)
    display_name = (member_user.name or "").strip() or (member_user.email if member_user else "Unknown")
    if org.operations_workgroup_id:
        post_activity(session, org.operations_workgroup_id, "member_removed", display_name, actor_user_id=user.id)

    session.commit()

    publish_user(member_user_id, {
        "type": "org_member_removed",
        "organization_id": org_id,
    })
