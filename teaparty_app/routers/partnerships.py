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
from sqlalchemy import or_

from teaparty_app.models import (
    Engagement,
    Organization,
    OrgMembership,
    Partnership,
    PaymentTransaction,
    User,
    Workgroup,
    utc_now,
)
from teaparty_app.schemas import (
    PartnerEngagementRead,
    PartnerEngagementSummaryRead,
    PartnerOrgProfileRead,
    PartnerTransactionRead,
    PartnershipDetailRead,
    PartnershipProposeRequest,
    PartnershipRead,
)
from teaparty_app.services.sync_events import publish_sync_event

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

    publish_sync_event(session, "org", payload.source_org_id, "sync:partnerships_changed", {"org_id": payload.source_org_id})

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

    # Any org member can view partnerships
    if org.owner_id != user.id:
        membership = session.exec(
            select(OrgMembership).where(
                OrgMembership.organization_id == org_id,
                OrgMembership.user_id == user.id,
            )
        ).first()
        if not membership:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a member of this organization",
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

    publish_sync_event(session, "org", partnership.source_org_id, "sync:partnerships_changed", {"org_id": partnership.source_org_id})

    return _partnership_detail(session, partnership)


@router.get("/organizations/{org_id}/partner-profile", response_model=PartnerOrgProfileRead)
def get_partner_profile(
    org_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PartnerOrgProfileRead:
    _require_partner_auth(session, org_id, user)
    org = session.get(Organization, org_id)
    return PartnerOrgProfileRead.model_validate(org)


@router.get("/organizations/{org_id}/partner-transactions", response_model=list[PartnerTransactionRead])
def get_partner_transactions(
    org_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[PartnerTransactionRead]:
    authorized = _require_partner_auth(session, org_id, user)

    source_org_id = authorized.source_org_id
    txns = session.exec(
        select(PaymentTransaction).where(
            PaymentTransaction.organization_id == source_org_id,
            PaymentTransaction.counterparty_org_id == org_id,
        ).order_by(PaymentTransaction.created_at.desc())
    ).all()

    return [PartnerTransactionRead.model_validate(t) for t in txns]


def _require_partner_auth(session: Session, org_id: str, user: User) -> Partnership:
    """Check that org_id exists and the caller has an accepted partnership targeting it."""
    org = session.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    owned = session.exec(
        select(Organization.id).where(Organization.owner_id == user.id)
    ).all()
    memberships = session.exec(
        select(OrgMembership.organization_id).where(OrgMembership.user_id == user.id)
    ).all()
    caller_org_ids = set(owned) | set(memberships)

    authorized = session.exec(
        select(Partnership).where(
            Partnership.source_org_id.in_(caller_org_ids),
            Partnership.target_org_id == org_id,
            Partnership.status == "accepted",
        )
    ).first()

    if not authorized:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No accepted partnership with this organization",
        )
    return authorized


@router.get("/organizations/{org_id}/partner-engagements", response_model=PartnerEngagementSummaryRead)
def get_partner_engagements(
    org_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> PartnerEngagementSummaryRead:
    authorized = _require_partner_auth(session, org_id, user)
    source_org_id = authorized.source_org_id

    # Get workgroup IDs for both orgs
    caller_wg_ids = set(session.exec(
        select(Workgroup.id).where(Workgroup.organization_id == source_org_id)
    ).all())
    partner_wg_ids = set(session.exec(
        select(Workgroup.id).where(Workgroup.organization_id == org_id)
    ).all())

    if not caller_wg_ids or not partner_wg_ids:
        return PartnerEngagementSummaryRead()

    # Engagements between the two orgs (either direction)
    engagements = session.exec(
        select(Engagement).where(
            or_(
                (Engagement.source_workgroup_id.in_(caller_wg_ids))
                & (Engagement.target_workgroup_id.in_(partner_wg_ids)),
                (Engagement.source_workgroup_id.in_(partner_wg_ids))
                & (Engagement.target_workgroup_id.in_(caller_wg_ids)),
            )
        ).order_by(Engagement.created_at.desc())
    ).all()

    completed = 0
    reviewed = 0
    satisfied = 0
    total_spend = 0.0
    total_earned = 0.0
    items: list[PartnerEngagementRead] = []

    for eng in engagements:
        is_outbound = eng.source_workgroup_id in caller_wg_ids
        direction = "outbound" if is_outbound else "inbound"

        if eng.status in ("completed", "reviewed"):
            completed += 1
        if eng.review_rating:
            reviewed += 1
            if eng.review_rating == "satisfied":
                satisfied += 1

        price = eng.agreed_price_credits or 0.0
        if price and eng.payment_status in ("escrowed", "paid"):
            if is_outbound:
                total_spend += price
            else:
                total_earned += price

        items.append(PartnerEngagementRead(
            id=eng.id,
            title=eng.title,
            status=eng.status,
            review_rating=eng.review_rating,
            agreed_price_credits=eng.agreed_price_credits,
            payment_status=eng.payment_status,
            created_at=eng.created_at,
            completed_at=eng.completed_at,
            direction=direction,
        ))

    return PartnerEngagementSummaryRead(
        total=len(engagements),
        completed=completed,
        reviewed=reviewed,
        satisfied=satisfied,
        total_spend_credits=total_spend,
        total_earned_credits=total_earned,
        engagements=items,
    )
