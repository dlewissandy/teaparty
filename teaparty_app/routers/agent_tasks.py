"""REST API for agent task CRUD and lifecycle (create, update, cancel)."""

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlmodel import Session, select

from teaparty_app.db import commit_with_retry, get_session
from teaparty_app.deps import get_current_user
from teaparty_app.models import (
    Agent,
    AgentTask,
    Conversation,
    ConversationParticipant,
    Message,
    User,
    Workgroup,
    utc_now,
)
from teaparty_app.routers.conversations import _process_auto_responses_in_background
from teaparty_app.schemas import (
    AgentTaskCreateRequest,
    AgentTaskDetailRead,
    AgentTaskRead,
    AgentTaskUpdateRequest,
)
from teaparty_app.services.agent_runtime import get_conversation_activity
from teaparty_app.services.permissions import require_workgroup_membership

router = APIRouter(prefix="/api", tags=["agent-tasks"])


def _derive_task_status(session: Session, task: AgentTask) -> str:
    """Derive a display status from live conversation state."""
    if task.status in ("completed", "cancelled"):
        return task.status
    if task.conversation_id and get_conversation_activity(task.conversation_id):
        return "working"
    if task.conversation_id:
        last_msg = session.exec(
            select(Message)
            .where(Message.conversation_id == task.conversation_id)
            .order_by(Message.created_at.desc())
        ).first()
        if last_msg and last_msg.sender_type == "agent":
            return "waiting" if last_msg.requires_response else "idle"
    return "idle"


@router.post(
    "/workgroups/{workgroup_id}/agents/{agent_id}/tasks",
    response_model=AgentTaskRead,
    status_code=status.HTTP_201_CREATED,
)
def create_agent_task(
    workgroup_id: str,
    agent_id: str,
    payload: AgentTaskCreateRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AgentTaskRead:
    require_workgroup_membership(session, workgroup_id, user.id)

    agent = session.get(Agent, agent_id)
    if not agent or agent.workgroup_id != workgroup_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found in this workgroup",
        )
    if agent.description == "__system_admin_agent__":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot create tasks for admin agents",
        )

    task = AgentTask(
        title=payload.title.strip(),
        description=payload.description.strip(),
        agent_id=agent_id,
        workgroup_id=workgroup_id,
        created_by_user_id=user.id,
    )

    conversation = Conversation(
        workgroup_id=workgroup_id,
        created_by_user_id=user.id,
        kind="task",
        topic=f"task:{agent_id}:{task.id}",
        name=payload.title.strip(),
    )
    session.add(conversation)
    session.flush()

    session.add(ConversationParticipant(conversation_id=conversation.id, user_id=user.id))
    session.add(ConversationParticipant(conversation_id=conversation.id, agent_id=agent_id))

    task.conversation_id = conversation.id
    session.add(task)

    # Post an initial user message so the agent auto-fires.
    content = task.title
    if task.description:
        content = f"{task.title}\n\n{task.description}"
    message = Message(
        conversation_id=conversation.id,
        sender_type="user",
        sender_user_id=user.id,
        content=content,
        requires_response=True,
    )
    session.add(message)

    commit_with_retry(session)
    session.refresh(task)
    session.refresh(message)

    background_tasks.add_task(_process_auto_responses_in_background, conversation.id, message.id)

    result = AgentTaskRead.model_validate(task)
    result.derived_status = _derive_task_status(session, task)
    return result


@router.get(
    "/workgroups/{workgroup_id}/agents/{agent_id}/tasks",
    response_model=list[AgentTaskRead],
)
def list_agent_tasks(
    workgroup_id: str,
    agent_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[AgentTaskRead]:
    require_workgroup_membership(session, workgroup_id, user.id)

    agent = session.get(Agent, agent_id)
    if not agent or agent.workgroup_id != workgroup_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found in this workgroup",
        )

    tasks = session.exec(
        select(AgentTask)
        .where(AgentTask.agent_id == agent_id, AgentTask.workgroup_id == workgroup_id)
        .order_by(AgentTask.created_at.desc())
    ).all()
    results = []
    for t in tasks:
        r = AgentTaskRead.model_validate(t)
        r.derived_status = _derive_task_status(session, t)
        results.append(r)
    return results


@router.get(
    "/workgroups/{workgroup_id}/agent-tasks",
    response_model=list[AgentTaskRead],
)
def list_workgroup_agent_tasks(
    workgroup_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[AgentTaskRead]:
    require_workgroup_membership(session, workgroup_id, user.id)

    tasks = session.exec(
        select(AgentTask)
        .where(AgentTask.workgroup_id == workgroup_id)
        .order_by(AgentTask.created_at.desc())
    ).all()
    results = []
    for t in tasks:
        r = AgentTaskRead.model_validate(t)
        r.derived_status = _derive_task_status(session, t)
        results.append(r)
    return results


@router.patch(
    "/agent-tasks/{task_id}",
    response_model=AgentTaskRead,
)
def update_agent_task(
    task_id: str,
    payload: AgentTaskUpdateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> AgentTaskRead:
    task = session.get(AgentTask, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent task not found",
        )

    require_workgroup_membership(session, task.workgroup_id, user.id)

    if payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Title cannot be empty",
            )
        task.title = title

    if payload.description is not None:
        task.description = payload.description.strip()

    if payload.status is not None:
        task.status = payload.status
        if payload.status in ("completed", "cancelled"):
            task.completed_at = utc_now()
            if task.conversation_id:
                from teaparty_app.services.agent_runtime import cancel_conversation
                cancel_conversation(task.conversation_id)

    session.add(task)
    commit_with_retry(session)
    session.refresh(task)
    result = AgentTaskRead.model_validate(task)
    result.derived_status = _derive_task_status(session, task)
    return result


@router.delete(
    "/agent-tasks/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_agent_task(
    task_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    task = session.get(AgentTask, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent task not found",
        )

    require_workgroup_membership(session, task.workgroup_id, user.id)

    # Cancel any running agent process.
    if task.conversation_id:
        from teaparty_app.services.agent_runtime import cancel_conversation
        cancel_conversation(task.conversation_id)

        # Delete messages and participants for the task conversation.
        conv = session.get(Conversation, task.conversation_id)
        if conv:
            for msg in session.exec(select(Message).where(Message.conversation_id == conv.id)).all():
                session.delete(msg)
            for cp in session.exec(select(ConversationParticipant).where(ConversationParticipant.conversation_id == conv.id)).all():
                session.delete(cp)
            session.delete(conv)

    session.delete(task)
    commit_with_retry(session)
