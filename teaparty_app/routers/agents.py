"""REST API for agent CRUD, cloning, learning, and tick endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from teaparty_app.db import get_session
from teaparty_app.deps import get_current_user
from teaparty_app.models import Agent, Membership, User, Workgroup
from teaparty_app.schemas import AgentRead, MessageRead, TickResponse
from teaparty_app.services.agent_runtime import process_triggered_todos
from teaparty_app.services.agent_workgroups import (
    agent_in_workgroup,
    agent_read_with_workgroups,
    lead_agent_for_workgroup,
    link_agent,
    unlink_agent,
    workgroup_ids_for_agent,
)
from teaparty_app.services.engagement_sync import sync_engagement_messages
from teaparty_app.services.permissions import require_workgroup_owner
from teaparty_app.services.sync_events import publish_sync_event
from teaparty_app.services.task_sync import sync_cross_group_messages

router = APIRouter(prefix="/api", tags=["agents"])


@router.get("/agents/{agent_id}", response_model=AgentRead)
def get_agent(
    agent_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AgentRead:
    agent = session.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    agent_workgroup_ids = set(workgroup_ids_for_agent(session, agent_id))
    user_memberships = session.exec(
        select(Membership).where(Membership.user_id == user.id)
    ).all()
    user_workgroup_ids = {m.workgroup_id for m in user_memberships}
    if not agent_workgroup_ids.intersection(user_workgroup_ids):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a workgroup member")

    return AgentRead(**agent_read_with_workgroups(session, agent))


@router.post("/agents/tick", response_model=TickResponse)
def tick_agents(
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TickResponse:
    memberships = session.exec(select(Membership).where(Membership.user_id == user.id)).all()
    allowed_workgroup_ids = {item.workgroup_id for item in memberships}

    created: list = []

    todo_created = process_triggered_todos(session, allowed_workgroup_ids)
    created.extend(todo_created)

    synced = sync_cross_group_messages(session, allowed_workgroup_ids)
    created.extend(synced)

    engagement_synced = sync_engagement_messages(session, allowed_workgroup_ids)
    created.extend(engagement_synced)

    session.commit()
    for message in created:
        session.refresh(message)

    return TickResponse(created_messages=[MessageRead.model_validate(item) for item in created])


@router.post("/agents/{agent_id}/workgroups/{workgroup_id}", response_model=AgentRead)
def link_agent_to_workgroup(
    agent_id: str,
    workgroup_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AgentRead:
    agent = session.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    workgroup = session.get(Workgroup, workgroup_id)
    if not workgroup:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workgroup not found")

    require_workgroup_owner(session, workgroup_id, user.id)

    link_agent(session, agent_id, workgroup_id)
    session.commit()
    session.refresh(agent)
    publish_sync_event(session, "workgroup", workgroup_id, "sync:agents_changed", {"workgroup_id": workgroup_id})
    return AgentRead(**agent_read_with_workgroups(session, agent))


@router.delete("/agents/{agent_id}/workgroups/{workgroup_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_agent_from_workgroup(
    agent_id: str,
    workgroup_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    agent = session.get(Agent, agent_id)
    if not agent or not agent_in_workgroup(session, agent_id, workgroup_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found in workgroup")

    require_workgroup_owner(session, workgroup_id, user.id)

    lead = lead_agent_for_workgroup(session, workgroup_id)
    if lead is not None and lead.id == agent_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot unlink the lead agent")

    unlink_agent(session, agent_id, workgroup_id)
    session.commit()
    publish_sync_event(session, "workgroup", workgroup_id, "sync:agents_changed", {"workgroup_id": workgroup_id})
