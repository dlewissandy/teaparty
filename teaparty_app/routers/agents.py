from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from teaparty_app.db import get_session
from teaparty_app.deps import get_current_user
from teaparty_app.models import Agent, Membership, User
from teaparty_app.schemas import AgentRead, MessageRead, TickResponse
from teaparty_app.services.agent_runtime import process_due_followups
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

    membership = session.exec(
        select(Membership).where(Membership.workgroup_id == agent.workgroup_id, Membership.user_id == user.id)
    ).first()
    if not membership:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a workgroup member")

    return AgentRead.model_validate(agent)


@router.post("/agents/tick", response_model=TickResponse)
def tick_agents(
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> TickResponse:
    memberships = session.exec(select(Membership).where(Membership.user_id == user.id)).all()
    allowed_workgroup_ids = {item.workgroup_id for item in memberships}

    created = process_due_followups(session, allowed_workgroup_ids, limit=limit)

    synced = sync_cross_group_messages(session, allowed_workgroup_ids)
    created.extend(synced)

    session.commit()
    for message in created:
        session.refresh(message)

    return TickResponse(created_messages=[MessageRead.model_validate(item) for item in created])
