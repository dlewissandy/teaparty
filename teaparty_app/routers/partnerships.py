"""REST API for org-level partnerships: propose, accept, decline, revoke, withdraw."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlmodel import Session, select

from teaparty_app.db import commit_with_retry, get_session
from teaparty_app.deps import get_current_user
from teaparty_app.models import Organization, Partnership, User, utc_now
from teaparty_app.schemas import PartnershipDetailRead, PartnershipProposeRequest, PartnershipRead

router = APIRouter(prefix="/api", tags=["partnerships"])

VALID_DIRECTIONS = {"bidirectional", "source_to_target", "target_to_source"}
ACTIVE_STATUSES = {"proposed", "accepted"}


def _partnership_detail(session: Session, p: Partnership) -> PartnershipDetailRead:
    src = session.get(Organization, p.source_org_id)
    tgt = session.get(Organization, p.target_org_id)
    return PartnershipDetailRead(
        **PartnershipRead.model_validate(p).model_dump(),
        source_org_name=src.name if src else "",
        target_org_name=tgt.name if tgt else "",
    )


def _require_org_owner(session: Session, org_id: str, user_id: str) -> Organization:
    org = session.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    if org.owner_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the organization owner can perform this action",
        )
    return org


@router.post("/partnerships", response_model=PartnershipDetailRead, status_code=status.HTTP_201_CREATED)
def propose_partnership(
    payload: PartnershipProposeRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PartnershipDetailRead:
    if payload.source_org_id == payload.target_org_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source and target organizations must be different",
        )

    if payload.direction not in VALID_DIRECTIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid direction. Must be one of: {', '.join(sorted(VALID_DIRECTIONS))}",
        )

    _require_org_owner(session, payload.source_org_id, user.id)

    target_org = session.get(Organization, payload.target_org_id)
    if not target_org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target organization not found")

    # Check for existing active/proposed partnership between this pair (in either direction)
    existing = session.exec(
        select(Partnership).where(
            or_(
                (Partnership.source_org_id == payload.source_org_id)
                & (Partnership.target_org_id == payload.target_org_id),
                (Partnership.source_org_id == payload.target_org_id)
                & (Partnership.target_org_id == payload.source_org_id),
            ),
            Partnership.status.in_(list(ACTIVE_STATUSES)),
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"An active or proposed partnership already exists between these organizations (status: {existing.status})",
        )

    partnership = Partnership(
        source_org_id=payload.source_org_id,
        target_org_id=payload.target_org_id,
        proposed_by_user_id=user.id,
        direction=payload.direction,
    )
    session.add(partnership)
    commit_with_retry(session)
    session.refresh(partnership)
    return _partnership_detail(session, partnership)


@router.get("/organizations/{org_id}/partnerships", response_model=list[PartnershipDetailRead])
def list_partnerships(
    org_id: str,
    status_filter: str | None = None,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[PartnershipDetailRead]:
    org = session.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    if org.owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the organization owner can view partnerships",
        )

    query = select(Partnership).where(
        or_(
            Partnership.source_org_id == org_id,
            Partnership.target_org_id == org_id,
        )
    )
    if status_filter:
        query = query.where(Partnership.status == status_filter)

    partnerships = session.exec(query.order_by(Partnership.created_at.desc())).all()
    return [_partnership_detail(session, p) for p in partnerships]


@router.post("/partnerships/{partnership_id}/accept", response_model=PartnershipDetailRead)
def accept_partnership(
    partnership_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PartnershipDetailRead:
    partnership = session.get(Partnership, partnership_id)
    if not partnership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Partnership not found")

    if partnership.status != "proposed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot accept partnership in status '{partnership.status}'",
        )

    # Only the target org owner can accept
    _require_org_owner(session, partnership.target_org_id, user.id)

    partnership.status = "accepted"
    partnership.accepted_at = utc_now()
    session.add(partnership)
    commit_with_retry(session)
    session.refresh(partnership)
    return _partnership_detail(session, partnership)


@router.post("/partnerships/{partnership_id}/decline", response_model=PartnershipDetailRead)
def decline_partnership(
    partnership_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PartnershipDetailRead:
    partnership = session.get(Partnership, partnership_id)
    if not partnership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Partnership not found")

    if partnership.status != "proposed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot decline partnership in status '{partnership.status}'",
        )

    # Only the target org owner can decline
    _require_org_owner(session, partnership.target_org_id, user.id)

    partnership.status = "declined"
    session.add(partnership)
    commit_with_retry(session)
    session.refresh(partnership)
    return _partnership_detail(session, partnership)


@router.post("/partnerships/{partnership_id}/revoke", response_model=PartnershipDetailRead)
def revoke_partnership(
    partnership_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PartnershipDetailRead:
    partnership = session.get(Partnership, partnership_id)
    if not partnership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Partnership not found")

    if partnership.status != "accepted":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot revoke partnership in status '{partnership.status}'",
        )

    # Either org owner can revoke
    src_org = session.get(Organization, partnership.source_org_id)
    tgt_org = session.get(Organization, partnership.target_org_id)
    if not (
        (src_org and src_org.owner_id == user.id)
        or (tgt_org and tgt_org.owner_id == user.id)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only an owner of a partner organization can revoke this partnership",
        )

    partnership.status = "revoked"
    partnership.revoked_at = utc_now()
    session.add(partnership)
    commit_with_retry(session)
    session.refresh(partnership)
    return _partnership_detail(session, partnership)


@router.post("/partnerships/{partnership_id}/withdraw", response_model=PartnershipDetailRead)
def withdraw_partnership(
    partnership_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PartnershipDetailRead:
    partnership = session.get(Partnership, partnership_id)
    if not partnership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Partnership not found")

    if partnership.status != "proposed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot withdraw partnership in status '{partnership.status}'",
        )

    # Only the source org owner (proposer's org) can withdraw
    _require_org_owner(session, partnership.source_org_id, user.id)

    partnership.status = "withdrawn"
    session.add(partnership)
    commit_with_retry(session)
    session.refresh(partnership)
    return _partnership_detail(session, partnership)
