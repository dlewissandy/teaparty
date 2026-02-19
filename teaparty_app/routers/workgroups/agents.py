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
    ADMIN_AGENT_SENTINEL,
    clear_conversation_messages,
    direct_conversation_key_user_agent,
)
from teaparty_app.services.permissions import require_workgroup_membership, require_workgroup_owner

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

    agent = Agent(
        workgroup_id=workgroup_id,
        created_by_user_id=user.id,
        name=name,
        description=payload.description.strip(),
        role=(payload.role.strip() or payload.description.strip()),
        personality=payload.personality.strip(),
        backstory=payload.backstory.strip(),
        model=payload.model.strip() or "claude-sonnet-4-5",
        temperature=payload.temperature,
        verbosity=payload.verbosity,
        tool_names=payload.tool_names,
        response_threshold=payload.response_threshold,
        learning_state=dict(payload.learning_state or {}),
        sentiment_state=dict(payload.sentiment_state or {}),
        learned_preferences=dict(payload.learning_state or {}),
        icon=payload.icon or "",
    )
    session.add(agent)
    session.flush()
    post_activity(session, workgroup_id, "agent_created", agent.name, actor_user_id=user.id)
    session.commit()
    _sync_workgroup_storage_for_user(session, user)
    session.refresh(agent)
    return AgentRead.model_validate(agent)


@router.get("/workgroups/{workgroup_id}/agents", response_model=list[AgentRead])
def list_agents(
    workgroup_id: str,
    include_hidden: bool = False,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[AgentRead]:
    require_workgroup_membership(session, workgroup_id, user.id)
    query = select(Agent).where(Agent.workgroup_id == workgroup_id)
    if not include_hidden:
        query = query.where(Agent.description != ADMIN_AGENT_SENTINEL)
    agents = session.exec(query.order_by(Agent.created_at.asc())).all()
    return [AgentRead.model_validate(agent) for agent in agents]


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
    if not agent or agent.workgroup_id != workgroup_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

    if payload.tool_names is not None:
        agent.tool_names = payload.tool_names

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent name cannot be empty")
        if agent.is_lead:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot rename the lead agent")
        agent.name = name

    if payload.description is not None:
        agent.description = payload.description.strip()
    if payload.role is not None:
        agent.role = payload.role.strip()
    if payload.personality is not None:
        agent.personality = payload.personality.strip()
    if payload.backstory is not None:
        agent.backstory = payload.backstory.strip()

    if payload.model is not None:
        model = payload.model.strip()
        if not model:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent model cannot be empty")
        agent.model = model

    if payload.temperature is not None:
        agent.temperature = payload.temperature
    if payload.verbosity is not None:
        agent.verbosity = payload.verbosity
    if payload.response_threshold is not None:
        agent.response_threshold = payload.response_threshold
    if payload.icon is not None:
        agent.icon = payload.icon

    session.add(agent)
    post_activity(session, workgroup_id, "agent_updated", agent.name, actor_user_id=user.id)
    session.commit()
    _sync_workgroup_storage_for_user(session, user)
    session.refresh(agent)
    return AgentRead.model_validate(agent)


@router.post("/workgroups/{workgroup_id}/agents/{agent_id}/clear-conversation", response_model=AgentConversationClearRead)
def clear_agent_conversation(
    workgroup_id: str,
    agent_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AgentConversationClearRead:
    require_workgroup_owner(session, workgroup_id, user.id)

    agent = session.get(Agent, agent_id)
    if not agent or agent.workgroup_id != workgroup_id:
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
    if not agent or agent.workgroup_id != workgroup_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    if agent.description == ADMIN_AGENT_SENTINEL:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot clone the admin agent")
    if agent.is_lead:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot clone the lead agent")

    target_workgroup_id = payload.target_workgroup_id or workgroup_id
    if target_workgroup_id != workgroup_id:
        require_workgroup_owner(session, target_workgroup_id, user.id)
        target_workgroup = session.get(Workgroup, target_workgroup_id)
        if not target_workgroup:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Target workgroup not found")

    name = payload.name.strip() if payload.name else f"{agent.name} (copy)"
    if not name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Agent name cannot be empty")

    cloned = Agent(
        workgroup_id=target_workgroup_id,
        created_by_user_id=user.id,
        name=name,
        description=agent.description,
        role=agent.role,
        personality=agent.personality,
        backstory=agent.backstory,
        model=agent.model,
        temperature=agent.temperature,
        verbosity=agent.verbosity,
        tool_names=list(agent.tool_names or []),
        response_threshold=agent.response_threshold,
        learning_state=dict(agent.learning_state) if payload.include_learned_state else {},
        sentiment_state=dict(agent.sentiment_state) if payload.include_learned_state else {},
        learned_preferences=dict(agent.learned_preferences) if payload.include_learned_state else {},
        icon=agent.icon or "",
    )
    session.add(cloned)
    session.flush()
    post_activity(session, target_workgroup_id, "agent_cloned", cloned.name, actor_user_id=user.id)
    session.commit()
    _sync_workgroup_storage_for_user(session, user)
    session.refresh(cloned)
    return AgentRead.model_validate(cloned)


@router.get("/workgroups/{workgroup_id}/agents/{agent_id}/learnings", response_model=AgentLearningsRead)
def get_agent_learnings(
    workgroup_id: str,
    agent_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AgentLearningsRead:
    require_workgroup_membership(session, workgroup_id, user.id)

    agent = session.get(Agent, agent_id)
    if not agent or agent.workgroup_id != workgroup_id:
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
        learning_state=dict(agent.learning_state or {}),
        sentiment_state=dict(agent.sentiment_state or {}),
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
