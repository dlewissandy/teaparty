"""REST API for the directory: the current user's organizations and co-members."""

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlmodel import Session, or_, select

from teaparty_app.db import get_session
from teaparty_app.deps import get_current_user
from teaparty_app.models import Engagement, Membership, Organization, Partnership, User, Workgroup
from teaparty_app.schemas import OrgDirectoryEntry, UserDirectoryEntry

router = APIRouter(prefix="/api", tags=["org-directory"])


def _user_org_ids(session: Session, user: User) -> list[str]:
    """Return org IDs the user belongs to (via workgroup membership or ownership)."""
    member_wg_ids = session.exec(
        select(Membership.workgroup_id).where(Membership.user_id == user.id)
    ).all()
    org_ids_via_membership = set(
        session.exec(
            select(Workgroup.organization_id)
            .where(Workgroup.id.in_(member_wg_ids), Workgroup.organization_id.isnot(None))
        ).all()
    ) if member_wg_ids else set()

    org_ids_via_ownership = set(
        session.exec(
            select(Organization.id).where(Organization.owner_id == user.id)
        ).all()
    )

    return list(org_ids_via_membership | org_ids_via_ownership)


@router.get("/org-directory", response_model=list[OrgDirectoryEntry])
def list_directory(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[OrgDirectoryEntry]:
    org_ids = _user_org_ids(session, user)
    if not org_ids:
        return []

    orgs = session.exec(select(Organization).where(Organization.id.in_(org_ids))).all()

    # Owner names
    owner_ids = list({o.owner_id for o in orgs})
    owners = session.exec(select(User).where(User.id.in_(owner_ids))).all()
    owner_map = {u.id: u.name for u in owners}

    # Partnership counts per org (accepted only)
    partner_counts: dict[str, int] = {}
    for org_id in org_ids:
        count = session.exec(
            select(func.count(Partnership.id)).where(
                or_(Partnership.source_org_id == org_id, Partnership.target_org_id == org_id),
                Partnership.status == "accepted",
            )
        ).one()
        partner_counts[org_id] = count

    # Workgroup IDs per org (for engagement lookups)
    wg_rows = session.exec(
        select(Workgroup.id, Workgroup.organization_id)
        .where(Workgroup.organization_id.in_(org_ids))
    ).all()
    org_wg_ids: dict[str, list[str]] = {}
    for wg_id, o_id in wg_rows:
        org_wg_ids.setdefault(o_id, []).append(wg_id)

    # Engagement counts and average rating per org
    engagement_counts: dict[str, int] = {}
    avg_ratings: dict[str, float | None] = {}
    for org_id in org_ids:
        wg_ids = org_wg_ids.get(org_id, [])
        if not wg_ids:
            engagement_counts[org_id] = 0
            avg_ratings[org_id] = None
            continue

        count = session.exec(
            select(func.count(Engagement.id)).where(
                or_(
                    Engagement.source_workgroup_id.in_(wg_ids),
                    Engagement.target_workgroup_id.in_(wg_ids),
                )
            )
        ).one()
        engagement_counts[org_id] = count

        # Average of numeric review_rating values for completed engagements targeting this org
        ratings = session.exec(
            select(Engagement.review_rating).where(
                Engagement.target_workgroup_id.in_(wg_ids),
                Engagement.review_rating.isnot(None),
            )
        ).all()
        numeric = []
        for r in ratings:
            try:
                numeric.append(float(r))
            except (ValueError, TypeError):
                pass
        avg_ratings[org_id] = round(sum(numeric) / len(numeric), 1) if numeric else None

    return [
        OrgDirectoryEntry(
            id=org.id,
            name=org.name,
            description=org.description,
            icon_url=org.icon_url,
            service_description=org.service_description,
            is_discoverable=org.is_discoverable,
            owner_id=org.owner_id,
            owner_name=owner_map.get(org.owner_id, ""),
            partner_count=partner_counts.get(org.id, 0),
            engagement_count=engagement_counts.get(org.id, 0),
            avg_rating=avg_ratings.get(org.id),
        )
        for org in orgs
    ]


@router.get("/user-directory", response_model=list[UserDirectoryEntry])
def list_users(
    user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list[UserDirectoryEntry]:
    users = session.exec(select(User)).all()
    all_user_ids = {u.id for u in users}

    # Orgs owned per user
    owned_rows = session.exec(
        select(Organization.owner_id, func.count(Organization.id))
        .where(Organization.owner_id.in_(list(all_user_ids)))
        .group_by(Organization.owner_id)
    ).all()
    orgs_owned_map = dict(owned_rows)

    # Distinct orgs each user is a member of (via workgroup membership), excluding owned
    all_memberships = session.exec(
        select(Membership.user_id, Workgroup.organization_id)
        .join(Workgroup, Membership.workgroup_id == Workgroup.id)
        .where(Membership.user_id.in_(list(all_user_ids)), Workgroup.organization_id.isnot(None))
    ).all()
    member_orgs: dict[str, set[str]] = {}
    for uid, oid in all_memberships:
        member_orgs.setdefault(uid, set()).add(oid)

    # Owned org ids per user (to subtract from member count)
    owned_org_ids: dict[str, set[str]] = {}
    all_orgs = session.exec(
        select(Organization.owner_id, Organization.id)
        .where(Organization.owner_id.in_(list(all_user_ids)))
    ).all()
    for uid, oid in all_orgs:
        owned_org_ids.setdefault(uid, set()).add(oid)

    # Average rating per user: ratings on engagements targeting workgroups they belong to
    user_wg_map: dict[str, list[str]] = {}
    for uid, oid in all_memberships:
        pass  # already have memberships, but need wg_ids
    user_wg_rows = session.exec(
        select(Membership.user_id, Membership.workgroup_id)
        .where(Membership.user_id.in_(list(all_user_ids)))
    ).all()
    for uid, wgid in user_wg_rows:
        user_wg_map.setdefault(uid, []).append(wgid)

    # Also include workgroups owned directly (via workgroup.owner_id)
    owned_wg_rows = session.exec(
        select(Workgroup.owner_id, Workgroup.id)
        .where(Workgroup.owner_id.in_(list(all_user_ids)))
    ).all()
    for uid, wgid in owned_wg_rows:
        user_wg_map.setdefault(uid, []).append(wgid)

    avg_rating_map: dict[str, float | None] = {}
    for uid in all_user_ids:
        uwg_ids = user_wg_map.get(uid, [])
        if not uwg_ids:
            avg_rating_map[uid] = None
            continue
        ratings = session.exec(
            select(Engagement.review_rating).where(
                Engagement.target_workgroup_id.in_(uwg_ids),
                Engagement.review_rating.isnot(None),
            )
        ).all()
        numeric = []
        for r in ratings:
            try:
                numeric.append(float(r))
            except (ValueError, TypeError):
                pass
        avg_rating_map[uid] = round(sum(numeric) / len(numeric), 1) if numeric else None

    return [
        UserDirectoryEntry(
            id=u.id,
            name=u.name,
            email=u.email,
            picture=u.picture,
            orgs_owned=orgs_owned_map.get(u.id, 0),
            orgs_member_of=len(member_orgs.get(u.id, set()) - owned_org_ids.get(u.id, set())),
            avg_rating=avg_rating_map.get(u.id),
        )
        for u in users
    ]
