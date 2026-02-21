"""REST API for organization CRUD and admin workspace bootstrapping."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlmodel import Session, select

from teaparty_app.db import get_session
from teaparty_app.deps import get_current_user
from teaparty_app.models import Agent, Engagement, Job, Membership, Message, Organization, OrgMembership, User, Workgroup
from teaparty_app.schemas import OrganizationCreateRequest, OrganizationRead, OrganizationUpdateRequest
from teaparty_app.services.admin_workspace import ensure_admin_workspace
from teaparty_app.services.admin_workspace.bootstrap import ADMINISTRATION_WORKGROUP_NAME
from teaparty_app.services.sync_events import publish_sync_event

router = APIRouter(prefix="/api", tags=["organizations"])


@router.get("/organizations", response_model=list[OrganizationRead])
def list_organizations(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[OrganizationRead]:
    member_org_ids = select(OrgMembership.organization_id).where(OrgMembership.user_id == user.id)

    orgs = session.exec(
        select(Organization)
        .where(Organization.id.in_(member_org_ids))
        .order_by(Organization.created_at.asc())
    ).all()
    return [OrganizationRead.model_validate(o) for o in orgs]


@router.post("/organizations", response_model=OrganizationRead)
def create_organization(
    payload: OrganizationCreateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> OrganizationRead:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organization name cannot be empty")

    org = Organization(name=name, description=payload.description.strip(), owner_id=user.id)
    session.add(org)
    session.flush()
    session.add(OrgMembership(organization_id=org.id, user_id=user.id, role="owner"))

    # Create an Administration workgroup for this organization
    admin_wg = Workgroup(
        name=ADMINISTRATION_WORKGROUP_NAME,
        files=[],
        owner_id=user.id,
        organization_id=org.id,
    )
    session.add(admin_wg)
    session.flush()
    session.add(Membership(workgroup_id=admin_wg.id, user_id=user.id, role="owner"))

    # Create the engagements-lead as the lead agent for the Administration workgroup.
    from teaparty_app.services.claude_tools import claude_tool_names
    engagements_lead = Agent(
        workgroup_id=admin_wg.id,
        created_by_user_id=user.id,
        name="engagements-lead",
        description="",
        role="Engagement coordinator",
        personality="Organized and collaborative engagement coordinator",
        backstory="",
        model="sonnet",
        temperature=0.7,
        tool_names=claude_tool_names(),
        is_lead=True,
        learning_state={},
        sentiment_state={},
        learned_preferences={},
    )
    session.add(engagements_lead)
    session.flush()

    ensure_admin_workspace(session, admin_wg)

    session.commit()
    session.refresh(org)
    return OrganizationRead.model_validate(org)


@router.patch("/organizations/{org_id}", response_model=OrganizationRead)
def update_organization(
    org_id: str,
    payload: OrganizationUpdateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> OrganizationRead:
    org = session.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    if org.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the organization owner can update it")

    if all(v is None for v in (payload.name, payload.description, payload.files, payload.service_description, payload.is_accepting_engagements)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No updates provided")

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Organization name cannot be empty")
        org.name = name

    if payload.description is not None:
        org.description = payload.description.strip()

    if payload.files is not None:
        from teaparty_app.db import _normalize_workgroup_files_payload
        org.files = _normalize_workgroup_files_payload(payload.files)

    if payload.service_description is not None:
        org.service_description = payload.service_description.strip()

    if payload.is_accepting_engagements is not None:
        org.is_accepting_engagements = payload.is_accepting_engagements

    session.add(org)
    session.commit()
    publish_sync_event(session, "org", org.id, "sync:org_updated", {"org_id": org.id})
    session.refresh(org)
    return OrganizationRead.model_validate(org)


@router.post("/organizations/{org_id}/admin-conversation")
def ensure_org_admin_conversation(
    org_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    org = session.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")

    # Find or create the org's Administration workgroup
    admin_wg = session.exec(
        select(Workgroup).where(
            Workgroup.organization_id == org_id,
            Workgroup.name == ADMINISTRATION_WORKGROUP_NAME,
        )
    ).first()

    if not admin_wg:
        admin_wg = Workgroup(
            name=ADMINISTRATION_WORKGROUP_NAME,
            files=[],
            owner_id=org.owner_id,
            organization_id=org.id,
        )
        session.add(admin_wg)
        session.flush()
        session.add(Membership(workgroup_id=admin_wg.id, user_id=org.owner_id, role="owner"))

    # Ensure the requesting user has membership
    membership = session.exec(
        select(Membership).where(
            Membership.workgroup_id == admin_wg.id,
            Membership.user_id == user.id,
        )
    ).first()
    if not membership:
        session.add(Membership(workgroup_id=admin_wg.id, user_id=user.id, role="member"))

    # Ensure admin agent + conversation exist
    _agent, conversation, _changed = ensure_admin_workspace(session, admin_wg)
    session.commit()

    return {
        "workgroup_id": admin_wg.id,
        "conversation_id": conversation.id,
    }


def _require_org_access(session: Session, org_id: str, user_id: str) -> Organization:
    """Return the org if the user has an OrgMembership record for it."""
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


@router.get("/organizations/{org_id}/summary")
def get_org_summary(
    org_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    org = _require_org_access(session, org_id, user.id)

    workgroups = session.exec(
        select(Workgroup).where(Workgroup.organization_id == org_id)
    ).all()
    wg_ids = [wg.id for wg in workgroups]

    workgroup_summaries = []
    total_jobs = 0
    active_jobs = 0

    for wg in workgroups:
        jobs = session.exec(select(Job).where(Job.workgroup_id == wg.id)).all()
        job_count = len(jobs)
        active_job_count = sum(1 for j in jobs if j.status == "in_progress")
        agent_count = session.exec(
            select(Agent).where(Agent.workgroup_id == wg.id)
        ).all()
        workgroup_summaries.append({
            "id": wg.id,
            "name": wg.name,
            "job_count": job_count,
            "active_job_count": active_job_count,
            "agent_count": len(agent_count),
        })
        total_jobs += job_count
        active_jobs += active_job_count

    # Deduplicated member count across all workgroups
    if wg_ids:
        member_user_ids = session.exec(
            select(Membership.user_id).where(Membership.workgroup_id.in_(wg_ids)).distinct()
        ).all()
        member_count = len(set(member_user_ids))
    else:
        member_count = 0

    # Engagements where source or target workgroup belongs to this org
    if wg_ids:
        engagement_count = len(session.exec(
            select(Engagement).where(
                or_(
                    Engagement.source_workgroup_id.in_(wg_ids),
                    Engagement.target_workgroup_id.in_(wg_ids),
                )
            )
        ).all())
    else:
        engagement_count = 0

    return {
        "org_id": org_id,
        "org_name": org.name,
        "workgroups": workgroup_summaries,
        "total_jobs": total_jobs,
        "active_jobs": active_jobs,
        "member_count": member_count,
        "engagement_count": engagement_count,
    }


@router.get("/organizations/{org_id}/activity")
def get_org_activity(
    org_id: str,
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list:
    _require_org_access(session, org_id, user.id)

    workgroups = session.exec(
        select(Workgroup).where(Workgroup.organization_id == org_id)
    ).all()
    wg_ids = [wg.id for wg in workgroups]

    if not wg_ids:
        return []

    from teaparty_app.models import Conversation

    # Gather conversation IDs for all workgroups in this org
    conversations = session.exec(
        select(Conversation).where(Conversation.workgroup_id.in_(wg_ids))
    ).all()
    conv_id_to_wg: dict[str, str] = {c.id: c.workgroup_id for c in conversations}
    conv_ids = list(conv_id_to_wg.keys())

    activity_items = []

    if conv_ids:
        recent_messages = session.exec(
            select(Message)
            .where(Message.conversation_id.in_(conv_ids))
            .order_by(Message.created_at.desc())
            .limit(limit)
        ).all()

        for msg in recent_messages:
            conv = next((c for c in conversations if c.id == msg.conversation_id), None)
            summary = f"New message in {conv.name if conv else msg.conversation_id}"
            activity_items.append({
                "type": "message",
                "timestamp": msg.created_at.isoformat(),
                "summary": summary,
                "workgroup_id": conv_id_to_wg.get(msg.conversation_id),
                "conversation_id": msg.conversation_id,
            })

    # Job status changes (completed/cancelled jobs)
    completed_jobs = session.exec(
        select(Job)
        .where(Job.workgroup_id.in_(wg_ids), Job.status.in_(["completed", "cancelled"]))
        .order_by(Job.completed_at.desc())
        .limit(limit)
    ).all()

    for job in completed_jobs:
        activity_items.append({
            "type": f"job_{job.status}",
            "timestamp": (job.completed_at or job.created_at).isoformat(),
            "summary": f"Job {job.status}: {job.title}",
            "workgroup_id": job.workgroup_id,
            "conversation_id": job.conversation_id,
        })

    # Sort combined list by timestamp descending and trim to limit
    activity_items.sort(key=lambda x: x["timestamp"], reverse=True)
    return activity_items[:limit]


@router.get("/organizations/{org_id}/members")
def get_org_members(
    org_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list:
    _require_org_access(session, org_id, user.id)

    memberships = session.exec(
        select(OrgMembership).where(OrgMembership.organization_id == org_id)
    ).all()

    result = []
    for m in memberships:
        member_user = session.get(User, m.user_id)
        if not member_user:
            continue
        result.append({
            "user_id": m.user_id,
            "name": member_user.name,
            "email": member_user.email,
            "role": m.role,
        })
    return result


@router.get("/organizations/{org_id}/engagements")
def get_org_engagements(
    org_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list:
    _require_org_access(session, org_id, user.id)

    workgroups = session.exec(
        select(Workgroup).where(Workgroup.organization_id == org_id)
    ).all()
    wg_ids = [wg.id for wg in workgroups]
    wg_by_id = {wg.id: wg for wg in workgroups}

    if not wg_ids:
        return []

    engagements = session.exec(
        select(Engagement).where(
            or_(
                Engagement.source_workgroup_id.in_(wg_ids),
                Engagement.target_workgroup_id.in_(wg_ids),
            )
        ).order_by(Engagement.created_at.desc())
    ).all()

    result = []
    for eng in engagements:
        src_wg = wg_by_id.get(eng.source_workgroup_id) or session.get(Workgroup, eng.source_workgroup_id)
        tgt_wg = wg_by_id.get(eng.target_workgroup_id) or session.get(Workgroup, eng.target_workgroup_id)
        result.append({
            "id": eng.id,
            "title": eng.title,
            "status": eng.status,
            "source_workgroup": {"id": eng.source_workgroup_id, "name": src_wg.name if src_wg else ""},
            "target_workgroup": {"id": eng.target_workgroup_id, "name": tgt_wg.name if tgt_wg else ""},
            "created_at": eng.created_at.isoformat(),
        })

    return result


@router.get("/home/summary")
def get_home_summary(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    # Orgs the user belongs to via OrgMembership
    all_org_ids = session.exec(
        select(OrgMembership.organization_id).where(OrgMembership.user_id == user.id)
    ).all()

    if not all_org_ids:
        return {"orgs": [], "total_active_jobs": 0, "total_attention_needed": 0}

    orgs = session.exec(select(Organization).where(Organization.id.in_(all_org_ids))).all()

    total_active_jobs = 0
    total_attention_needed = 0
    org_summaries = []

    for org in orgs:
        workgroups = session.exec(
            select(Workgroup).where(Workgroup.organization_id == org.id)
        ).all()
        wg_ids = [wg.id for wg in workgroups]

        active_jobs = 0
        attention_needed = 0

        if wg_ids:
            jobs = session.exec(
                select(Job).where(Job.workgroup_id.in_(wg_ids), Job.status == "in_progress")
            ).all()
            active_jobs = len(jobs)

            # Attention needed: jobs where the last message is from an agent with requires_response=True
            for job in jobs:
                if job.conversation_id:
                    last_msg = session.exec(
                        select(Message)
                        .where(Message.conversation_id == job.conversation_id)
                        .order_by(Message.created_at.desc())
                    ).first()
                    if last_msg and last_msg.sender_type == "agent" and last_msg.requires_response:
                        attention_needed += 1

            # Also count pending engagement proposals targeting this org's workgroups
            pending_engagements = session.exec(
                select(Engagement).where(
                    Engagement.target_workgroup_id.in_(wg_ids),
                    Engagement.status == "proposed",
                )
            ).all()
            attention_needed += len(pending_engagements)

        total_active_jobs += active_jobs
        total_attention_needed += attention_needed

        org_summaries.append({
            "id": org.id,
            "name": org.name,
            "active_jobs": active_jobs,
            "attention_needed": attention_needed,
            "workgroup_count": len(workgroups),
        })

    return {
        "orgs": org_summaries,
        "total_active_jobs": total_active_jobs,
        "total_attention_needed": total_attention_needed,
    }


@router.delete("/organizations/{org_id}", status_code=204)
def delete_organization(
    org_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    org = session.get(Organization, org_id)
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    if org.owner_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the organization owner can delete it")

    # Cascade-delete all workgroups in this org
    from teaparty_app.services.admin_workspace.tools_common import delete_workgroup_data

    workgroups = session.exec(
        select(Workgroup).where(Workgroup.organization_id == org_id)
    ).all()
    for wg in workgroups:
        delete_workgroup_data(session, wg.id)

    session.delete(org)
    session.commit()
