from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from teaparty_app.deps import get_current_user
from teaparty_app.db import get_session
from teaparty_app.models import Agent, AgentLearningEvent, AgentMemory, Conversation, Membership, User, Workgroup, utc_now
from teaparty_app.schemas import (
    AgentCloneRequest,
    AgentConversationClearRead,
    AgentCreateRequest,
    AgentLearningSignalRead,
    AgentLearningsRead,
    AgentMemoryRead,
    AgentRead,
    AgentUpdateRequest,
)
from teaparty_app.services.activity import post_activity
from teaparty_app.services.admin_workspace import (
    clear_conversation_messages,
    direct_conversation_key_user_agent,
)
from teaparty_app.services.agent_workgroups import (
    agent_in_workgroup,
    agent_is_lead,
    agent_read_with_workgroups,
    agents_for_workgroup,
    lead_agent_for_workgroup,
    link_agent,
)
from teaparty_app.services.permissions import require_workgroup_membership, require_workgroup_owner
from teaparty_app.services.sync_events import publish_sync_event

from .core import _sync_workgroup_storage_for_user

router = APIRouter(prefix="/api", tags=["workgroups"])


@router.post("/workgroups/{workgroup_id}/agents", response_model=AgentRead)
def create_agent(
    workgroup_id: str,
    payload: AgentCreateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AgentRead:
    require_workgroup_owner(session, workgroup_id, user.id)

    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent name cannot be empty")
    if not payload.description.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent description cannot be empty")

    workgroup = session.get(Workgroup, workgroup_id)
    if not workgroup:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workgroup not found")

    agent = Agent(
        organization_id=workgroup.organization_id,
        created_by_user_id=user.id,
        name=name,
        description=payload.description.strip(),
        prompt=payload.prompt.strip(),
        model=payload.model.strip() or "sonnet",
        tools=payload.tools,
        image=payload.image or "",
        permission_mode=payload.permission_mode,
        hooks=payload.hooks,
        memory=payload.memory,
        background=payload.background,
        isolation=payload.isolation,
    )
    session.add(agent)
    session.flush()
    link_agent(session, agent.id, workgroup_id)
    post_activity(session, workgroup_id, "agent_created", agent.name, actor_user_id=user.id)
    session.commit()
    publish_sync_event(session, "workgroup", workgroup_id, "sync:agents_changed", {"workgroup_id": workgroup_id})
    _sync_workgroup_storage_for_user(session, user)
    session.refresh(agent)
    return AgentRead(**agent_read_with_workgroups(session, agent))


@router.get("/workgroups/{workgroup_id}/agents", response_model=list[AgentRead])
def list_agents(
    workgroup_id: str,
    include_hidden: bool = False,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[AgentRead]:
    require_workgroup_membership(session, workgroup_id, user.id)
    agents = sorted(agents_for_workgroup(session, workgroup_id), key=lambda a: a.created_at)
    return [AgentRead(**agent_read_with_workgroups(session, agent)) for agent in agents]


@router.patch("/workgroups/{workgroup_id}/agents/{agent_id}", response_model=AgentRead)
def update_agent(
    workgroup_id: str,
    agent_id: str,
    payload: AgentUpdateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AgentRead:
    require_workgroup_owner(session, workgroup_id, user.id)

    agent = session.get(Agent, agent_id)
    if not agent or not agent_in_workgroup(session, agent_id, workgroup_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    is_lead = lead_agent_for_workgroup(session, workgroup_id)
    agent_is_lead = is_lead is not None and is_lead.id == agent_id

    if payload.tools is not None:
        agent.tools = payload.tools

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent name cannot be empty")
        if agent_is_lead:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot rename the lead agent")
        agent.name = name

    if payload.description is not None:
        desc = payload.description.strip()
        if not desc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent description cannot be empty")
        agent.description = desc
    if payload.prompt is not None:
        agent.prompt = payload.prompt.strip()

    if payload.model is not None:
        model = payload.model.strip()
        if not model:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent model cannot be empty")
        agent.model = model

    if payload.image is not None:
        agent.image = payload.image
    if payload.permission_mode is not None:
        agent.permission_mode = payload.permission_mode
    if payload.hooks is not None:
        agent.hooks = payload.hooks
    if payload.memory is not None:
        agent.memory = payload.memory
    if payload.background is not None:
        agent.background = payload.background
    if payload.isolation is not None:
        agent.isolation = payload.isolation

    session.add(agent)
    post_activity(session, workgroup_id, "agent_updated", agent.name, actor_user_id=user.id)
    session.commit()
    publish_sync_event(session, "workgroup", workgroup_id, "sync:agents_changed", {"workgroup_id": workgroup_id})
    _sync_workgroup_storage_for_user(session, user)
    session.refresh(agent)
    return AgentRead(**agent_read_with_workgroups(session, agent))


@router.delete("/workgroups/{workgroup_id}/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_agent_from_workgroup(
    workgroup_id: str,
    agent_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    """Remove an agent from a workgroup (unlink only, does not delete the agent)."""
    from teaparty_app.models import AgentWorkgroup

    require_workgroup_owner(session, workgroup_id, user.id)

    agent = session.get(Agent, agent_id)
    if not agent or not agent_in_workgroup(session, agent_id, workgroup_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    if agent_is_lead(session, agent_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot remove a lead agent")

    link = session.exec(
        select(AgentWorkgroup).where(
            AgentWorkgroup.agent_id == agent_id,
            AgentWorkgroup.workgroup_id == workgroup_id,
        )
    ).first()
    if link:
        session.delete(link)

    post_activity(session, workgroup_id, "agent_removed", agent.name, actor_user_id=user.id)
    session.commit()
    publish_sync_event(session, "workgroup", workgroup_id, "sync:agents_changed", {"workgroup_id": workgroup_id})


@router.post("/workgroups/{workgroup_id}/agents/{agent_id}/clear-conversation", response_model=AgentConversationClearRead)
def clear_agent_conversation(
    workgroup_id: str,
    agent_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AgentConversationClearRead:
    require_workgroup_owner(session, workgroup_id, user.id)

    agent = session.get(Agent, agent_id)
    if not agent or not agent_in_workgroup(session, agent_id, workgroup_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    conversation = session.exec(
        select(Conversation).where(
            Conversation.workgroup_id == workgroup_id,
            Conversation.kind == "direct",
            Conversation.topic == direct_conversation_key_user_agent(user.id, agent_id),
        )
    ).first()

    if not conversation:
        return AgentConversationClearRead(conversation_id=None, deleted_messages=0)

    counts = clear_conversation_messages(session, conversation.id)
    session.commit()
    return AgentConversationClearRead(
        conversation_id=conversation.id,
        deleted_messages=counts.get("messages", 0),
    )


@router.post("/workgroups/{workgroup_id}/agents/{agent_id}/clone", response_model=AgentRead)
def clone_agent(
    workgroup_id: str,
    agent_id: str,
    payload: AgentCloneRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AgentRead:
    require_workgroup_owner(session, workgroup_id, user.id)

    agent = session.get(Agent, agent_id)
    if not agent or not agent_in_workgroup(session, agent_id, workgroup_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    lead = lead_agent_for_workgroup(session, workgroup_id)
    if lead is not None and lead.id == agent_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot clone the lead agent")

    target_workgroup_id = payload.target_workgroup_id or workgroup_id
    if target_workgroup_id != workgroup_id:
        require_workgroup_owner(session, target_workgroup_id, user.id)
        target_workgroup = session.get(Workgroup, target_workgroup_id)
        if not target_workgroup:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target workgroup not found")
        clone_org_id = target_workgroup.organization_id
    else:
        source_workgroup = session.get(Workgroup, workgroup_id)
        clone_org_id = source_workgroup.organization_id if source_workgroup else agent.organization_id

    name = payload.name.strip() if payload.name else f"{agent.name} (copy)"
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent name cannot be empty")

    cloned = Agent(
        organization_id=clone_org_id,
        created_by_user_id=user.id,
        name=name,
        description=agent.description,
        prompt=agent.prompt,
        model=agent.model,
        tools=list(agent.tools or []),
        image=agent.image or "",
        permission_mode=agent.permission_mode,
        hooks=agent.hooks,
        memory=agent.memory,
        background=agent.background,
        isolation=agent.isolation,
    )
    session.add(cloned)
    session.flush()
    link_agent(session, cloned.id, target_workgroup_id)
    post_activity(session, target_workgroup_id, "agent_cloned", cloned.name, actor_user_id=user.id)
    session.commit()
    publish_sync_event(session, "workgroup", target_workgroup_id, "sync:agents_changed", {"workgroup_id": target_workgroup_id})
    _sync_workgroup_storage_for_user(session, user)
    session.refresh(cloned)
    return AgentRead(**agent_read_with_workgroups(session, cloned))


@router.get("/workgroups/{workgroup_id}/agents/{agent_id}/learnings", response_model=AgentLearningsRead)
def get_agent_learnings(
    workgroup_id: str,
    agent_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AgentLearningsRead:
    require_workgroup_membership(session, workgroup_id, user.id)

    agent = session.get(Agent, agent_id)
    if not agent or not agent_in_workgroup(session, agent_id, workgroup_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    memories = session.exec(
        select(AgentMemory)
        .where(AgentMemory.agent_id == agent_id)
        .order_by(AgentMemory.created_at.desc())
        .limit(20)
    ).all()

    signals = session.exec(
        select(AgentLearningEvent)
        .where(AgentLearningEvent.agent_id == agent_id)
        .order_by(AgentLearningEvent.created_at.desc())
        .limit(15)
    ).all()

    return AgentLearningsRead(
        memories=[AgentMemoryRead.model_validate(m) for m in memories],
        recent_signals=[
            AgentLearningSignalRead(
                signal_type=s.signal_type,
                value=dict(s.value or {}),
                created_at=s.created_at,
            )
            for s in signals
        ],
    )
