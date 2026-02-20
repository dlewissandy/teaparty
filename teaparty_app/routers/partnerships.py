"""REST API for org-level partnerships: add and revoke.

Partnerships are asymmetric — if org A adds org B as a partner, B appears in
A's partner list but A does NOT appear in B's.  There is no invite/proposal
lifecycle; adding a partner takes effect immediately.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from teaparty_app.db import commit_with_retry, get_session
from teaparty_app.deps import get_current_user
from teaparty_app.models import Organization, Partnership, User, utc_now
from teaparty_app.schemas import (
    PartnershipDetailRead,
    PartnershipProposeRequest,
    PartnershipRead,
)

router = APIRouter(prefix="/api", tags=["partnerships"])

VALID_DIRECTIONS = {"bidirectional", "source_to_target", "target_to_source"}


def _partnership_detail(session: Session, p: Partnership) -> PartnershipDetailRead:
    src = session.get(Organization, p.source_org_id)
    tgt = session.get(Organization, p.target_org_id)
    proposer = session.get(User, p.proposed_by_user_id)
    return PartnershipDetailRead(
        **PartnershipRead.model_validate(p).model_dump(),
        source_org_name=src.name if src else "",
        target_org_name=tgt.name if tgt else "",
        proposed_by_user_name=proposer.name if proposer else "",
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

    # Duplicate check — only same direction (A→B and B→A are independent)
    existing = session.exec(
        select(Partnership).where(
            Partnership.source_org_id == payload.source_org_id,
            Partnership.target_org_id == payload.target_org_id,
            Partnership.status == "accepted",
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This partnership already exists",
        )

    partnership = Partnership(
        source_org_id=payload.source_org_id,
        target_org_id=payload.target_org_id,
        proposed_by_user_id=user.id,
        direction=payload.direction,
        message=payload.message,
        status="accepted",
        accepted_at=utc_now(),
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

    # Asymmetric: only return partnerships where this org is the source
    query = select(Partnership).where(Partnership.source_org_id == org_id)
    if status_filter:
        query = query.where(Partnership.status == status_filter)

    partnerships = session.exec(query.order_by(Partnership.created_at.desc())).all()
    return [_partnership_detail(session, p) for p in partnerships]


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

    # Only the source org owner can revoke (they're the one who added the partner)
    _require_org_owner(session, partnership.source_org_id, user.id)

    partnership.status = "revoked"
    partnership.revoked_at = utc_now()
    session.add(partnership)
    commit_with_retry(session)
    session.refresh(partnership)
    return _partnership_detail(session, partnership)
