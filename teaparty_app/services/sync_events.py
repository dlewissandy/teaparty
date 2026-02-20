"""Cross-member sync events via SSE push.

Publishes typed events to affected users so their UIs can make
targeted re-fetches.  Always call publish_sync_event() AFTER
session.commit() so the re-fetch reads committed data.
"""

from __future__ import annotations

import logging

from sqlmodel import Session, select

from teaparty_app.models import Engagement, Membership, OrgMembership
from teaparty_app.services import event_bus

logger = logging.getLogger(__name__)


def _workgroup_user_ids(session: Session, workgroup_id: str) -> list[str]:
    """All user_ids with membership in the given workgroup."""
    stmt = select(Membership.user_id).where(Membership.workgroup_id == workgroup_id)
    return list(session.exec(stmt).all())


def _org_user_ids(session: Session, org_id: str) -> list[str]:
    """All user_ids with membership in the given organization."""
    stmt = select(OrgMembership.user_id).where(OrgMembership.organization_id == org_id)
    return list(session.exec(stmt).all())


def _engagement_user_ids(session: Session, engagement_id: str) -> list[str]:
    """Union of both workgroups' members for an engagement."""
    eng = session.get(Engagement, engagement_id)
    if not eng:
        return []
    src = set(_workgroup_user_ids(session, eng.source_workgroup_id))
    tgt = set(_workgroup_user_ids(session, eng.target_workgroup_id))
    return list(src | tgt)


def publish_sync_event(
    session: Session,
    scope: str,
    scope_id: str,
    event_type: str,
    payload: dict | None = None,
) -> None:
    """Resolve affected user_ids and publish an SSE event to each.

    scope: "workgroup" | "org" | "engagement"
    """
    if scope == "workgroup":
        user_ids = _workgroup_user_ids(session, scope_id)
    elif scope == "org":
        user_ids = _org_user_ids(session, scope_id)
    elif scope == "engagement":
        user_ids = _engagement_user_ids(session, scope_id)
    else:
        logger.warning("Unknown sync scope: %s", scope)
        return

    event = {"type": event_type, **(payload or {})}

    for uid in user_ids:
        event_bus.publish_user(uid, event)
