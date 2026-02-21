"""REST API for projects: create and list."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlmodel import Session, select

from teaparty_app.db import commit_with_retry, get_session
from teaparty_app.deps import get_current_user
from teaparty_app.models import (
    Conversation,
    ConversationParticipant,
    Message,
    OrgMembership,
    Project,
    User,
    Workgroup,
)
from teaparty_app.routers.conversations import _process_auto_responses_in_background
from teaparty_app.schemas import ProjectCreateRequest, ProjectRead
from teaparty_app.services.sync_events import publish_sync_event

router = APIRouter(prefix="/api", tags=["projects"])


def _require_org_member(session: Session, org_id: str, user_id: str) -> OrgMembership:
    mem = session.exec(
        select(OrgMembership).where(
            OrgMembership.organization_id == org_id,
            OrgMembership.user_id == user_id,
        )
    ).first()
    if not mem:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not an organization member")
    return mem


@router.post(
    "/organizations/{org_id}/projects",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
)
def create_project(
    org_id: str,
    payload: ProjectCreateRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ProjectRead:
    _require_org_member(session, org_id, user.id)

    # Resolve workgroup IDs — use provided list or all non-Administration workgroups in org.
    wg_ids = payload.workgroup_ids
    if not wg_ids:
        wgs = session.exec(
            select(Workgroup).where(
                Workgroup.organization_id == org_id,
                Workgroup.name != "Administration",
            )
        ).all()
        wg_ids = [wg.id for wg in wgs]

    if not wg_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No workgroups available")

    # Validate all workgroup IDs belong to this org.
    for wg_id in wg_ids:
        wg = session.get(Workgroup, wg_id)
        if not wg or wg.organization_id != org_id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid workgroup: {wg_id}")

    first_wg_id = wg_ids[0]

    # Create the project conversation in the first workgroup.
    conversation = Conversation(
        workgroup_id=first_wg_id,
        created_by_user_id=user.id,
        kind="project",
        topic="Untitled Project",
        name="Untitled Project",
        description=payload.prompt[:200],
    )
    session.add(conversation)
    session.flush()

    # Add the creating user as a participant.
    session.add(ConversationParticipant(conversation_id=conversation.id, user_id=user.id))

    # Create the Project record.
    project = Project(
        organization_id=org_id,
        conversation_id=conversation.id,
        created_by_user_id=user.id,
        prompt=payload.prompt,
        model=payload.model,
        max_turns=payload.max_turns,
        permission_mode=payload.permission_mode,
        max_cost_usd=payload.max_cost_usd,
        max_time_seconds=payload.max_time_seconds,
        max_tokens=payload.max_tokens,
        workgroup_ids=wg_ids,
    )
    session.add(project)

    # Post the initial message with the prompt to trigger agents.
    message = Message(
        conversation_id=conversation.id,
        sender_type="user",
        sender_user_id=user.id,
        content=payload.prompt,
        requires_response=True,
    )
    session.add(message)

    commit_with_retry(session)
    session.refresh(project)
    session.refresh(message)

    publish_sync_event(session, "workgroup", first_wg_id, "sync:tree_changed", {"workgroup_id": first_wg_id})

    background_tasks.add_task(_process_auto_responses_in_background, conversation.id, message.id)

    return ProjectRead.model_validate(project)


@router.get("/organizations/{org_id}/projects", response_model=list[ProjectRead])
def list_projects(
    org_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[ProjectRead]:
    _require_org_member(session, org_id, user.id)

    projects = session.exec(
        select(Project).where(Project.organization_id == org_id).order_by(Project.created_at.desc())
    ).all()

    return [ProjectRead.model_validate(p) for p in projects]
