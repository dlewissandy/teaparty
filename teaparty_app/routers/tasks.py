from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session, select

from teaparty_app.db import get_session
from teaparty_app.deps import get_current_user
from teaparty_app.models import (
    Conversation,
    ConversationParticipant,
    CrossGroupTask,
    CrossGroupTaskMessage,
    Membership,
    Message,
    User,
    Workgroup,
    utc_now,
)
from teaparty_app.schemas import (
    CrossGroupTaskCompleteRequest,
    CrossGroupTaskCreateRequest,
    CrossGroupTaskDetailRead,
    CrossGroupTaskMessageRead,
    CrossGroupTaskNegotiateRequest,
    CrossGroupTaskRead,
    CrossGroupTaskRespondRequest,
    CrossGroupTaskSatisfactionRequest,
    WorkgroupDirectoryEntry,
)

router = APIRouter(prefix="/api", tags=["tasks"])

VALID_TASK_STATUSES = {
    "requested",
    "negotiating",
    "accepted",
    "declined",
    "in_progress",
    "completed",
    "satisfied",
    "dissatisfied",
    "cancelled",
}


def _require_task_participant(
    session: Session, task: CrossGroupTask, user_id: str
) -> Membership:
    source_membership = session.exec(
        select(Membership).where(
            Membership.workgroup_id == task.source_workgroup_id,
            Membership.user_id == user_id,
        )
    ).first()
    if source_membership:
        return source_membership

    target_membership = session.exec(
        select(Membership).where(
            Membership.workgroup_id == task.target_workgroup_id,
            Membership.user_id == user_id,
        )
    ).first()
    if target_membership:
        return target_membership

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not a member of source or target workgroup",
    )


def _user_workgroup_side(
    session: Session, task: CrossGroupTask, user_id: str
) -> str:
    source = session.exec(
        select(Membership).where(
            Membership.workgroup_id == task.source_workgroup_id,
            Membership.user_id == user_id,
        )
    ).first()
    if source:
        return "source"

    target = session.exec(
        select(Membership).where(
            Membership.workgroup_id == task.target_workgroup_id,
            Membership.user_id == user_id,
        )
    ).first()
    if target:
        return "target"

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Not a member of source or target workgroup",
    )


def _task_detail(session: Session, task: CrossGroupTask) -> CrossGroupTaskDetailRead:
    messages = session.exec(
        select(CrossGroupTaskMessage)
        .where(CrossGroupTaskMessage.task_id == task.id)
        .order_by(CrossGroupTaskMessage.created_at.asc())
    ).all()

    source_wg = session.get(Workgroup, task.source_workgroup_id)
    target_wg = session.get(Workgroup, task.target_workgroup_id)

    return CrossGroupTaskDetailRead(
        **CrossGroupTaskRead.model_validate(task).model_dump(),
        messages=[CrossGroupTaskMessageRead.model_validate(m) for m in messages],
        source_workgroup_name=source_wg.name if source_wg else "",
        target_workgroup_name=target_wg.name if target_wg else "",
    )


@router.get("/workgroup-directory", response_model=list[WorkgroupDirectoryEntry])
def list_workgroup_directory(
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[WorkgroupDirectoryEntry]:
    workgroups = session.exec(
        select(Workgroup)
        .where(Workgroup.is_discoverable == True)  # noqa: E712
        .order_by(Workgroup.name.asc())
    ).all()
    return [
        WorkgroupDirectoryEntry(
            id=wg.id,
            name=wg.name,
            service_description=wg.service_description or "",
        )
        for wg in workgroups
    ]


@router.post("/cross-group-tasks", response_model=CrossGroupTaskDetailRead)
def create_cross_group_task(
    payload: CrossGroupTaskCreateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> CrossGroupTaskDetailRead:
    # User must be a member of at least one workgroup (the source).
    # We pick the first workgroup the user belongs to that isn't the target.
    memberships = session.exec(
        select(Membership).where(Membership.user_id == user.id)
    ).all()
    source_workgroup_id: str | None = None
    for m in memberships:
        if m.workgroup_id != payload.target_workgroup_id:
            source_workgroup_id = m.workgroup_id
            break

    if not source_workgroup_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must belong to a workgroup other than the target to create a task",
        )

    target_wg = session.get(Workgroup, payload.target_workgroup_id)
    if not target_wg:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Target workgroup not found",
        )

    task = CrossGroupTask(
        source_workgroup_id=source_workgroup_id,
        target_workgroup_id=payload.target_workgroup_id,
        requested_by_user_id=user.id,
        status="requested",
        title=payload.title.strip(),
        scope=payload.scope.strip(),
        requirements=payload.requirements.strip(),
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return _task_detail(session, task)


@router.get(
    "/workgroups/{workgroup_id}/cross-group-tasks",
    response_model=list[CrossGroupTaskRead],
)
def list_cross_group_tasks(
    workgroup_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[CrossGroupTaskRead]:
    membership = session.exec(
        select(Membership).where(
            Membership.workgroup_id == workgroup_id,
            Membership.user_id == user.id,
        )
    ).first()
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a workgroup member",
        )

    from sqlalchemy import or_

    tasks = session.exec(
        select(CrossGroupTask)
        .where(
            or_(
                CrossGroupTask.source_workgroup_id == workgroup_id,
                CrossGroupTask.target_workgroup_id == workgroup_id,
            )
        )
        .order_by(CrossGroupTask.created_at.desc())
    ).all()
    return [CrossGroupTaskRead.model_validate(t) for t in tasks]


@router.get(
    "/cross-group-tasks/{task_id}",
    response_model=CrossGroupTaskDetailRead,
)
def get_cross_group_task(
    task_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> CrossGroupTaskDetailRead:
    task = session.get(CrossGroupTask, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )
    _require_task_participant(session, task, user.id)
    return _task_detail(session, task)


@router.post(
    "/cross-group-tasks/{task_id}/messages",
    response_model=CrossGroupTaskMessageRead,
)
def post_negotiation_message(
    task_id: str,
    payload: CrossGroupTaskNegotiateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> CrossGroupTaskMessageRead:
    task = session.get(CrossGroupTask, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    side = _user_workgroup_side(session, task, user.id)
    sender_workgroup_id = (
        task.source_workgroup_id if side == "source" else task.target_workgroup_id
    )

    if task.status not in ("requested", "negotiating"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot negotiate in status '{task.status}'",
        )

    if task.status == "requested":
        task.status = "negotiating"
        session.add(task)

    message = CrossGroupTaskMessage(
        task_id=task.id,
        sender_user_id=user.id,
        sender_workgroup_id=sender_workgroup_id,
        content=payload.content.strip(),
    )
    session.add(message)
    session.commit()
    session.refresh(message)
    return CrossGroupTaskMessageRead.model_validate(message)


@router.post(
    "/cross-group-tasks/{task_id}/respond",
    response_model=CrossGroupTaskDetailRead,
)
def respond_to_task(
    task_id: str,
    payload: CrossGroupTaskRespondRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> CrossGroupTaskDetailRead:
    task = session.get(CrossGroupTask, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    # Only target workgroup owner can accept/decline
    target_membership = session.exec(
        select(Membership).where(
            Membership.workgroup_id == task.target_workgroup_id,
            Membership.user_id == user.id,
        )
    ).first()
    if not target_membership or target_membership.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the target workgroup owner can accept or decline tasks",
        )

    if task.status not in ("requested", "negotiating"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot respond to task in status '{task.status}'",
        )

    now = utc_now()

    if payload.action == "decline":
        task.status = "declined"
        task.declined_at = now
        if payload.terms:
            task.terms = payload.terms.strip()
        session.add(task)
        session.commit()
        session.refresh(task)
        return _task_detail(session, task)

    # Accept flow
    task.status = "accepted"
    task.accepted_at = now
    if payload.terms:
        task.terms = payload.terms.strip()

    # Create job in target workgroup for work
    target_conversation = Conversation(
        workgroup_id=task.target_workgroup_id,
        created_by_user_id=user.id,
        kind="job",
        topic=f"task:{task.id}",
        name=task.title,
        description=f"Cross-group task from source workgroup. Scope: {task.scope}",
        is_archived=False,
    )
    session.add(target_conversation)
    session.flush()
    session.add(
        ConversationParticipant(
            conversation_id=target_conversation.id,
            user_id=user.id,
        )
    )

    # Create mirror job in source workgroup
    source_conversation = Conversation(
        workgroup_id=task.source_workgroup_id,
        created_by_user_id=task.requested_by_user_id,
        kind="job",
        topic=f"task-mirror:{task.id}",
        name=f"[Task] {task.title}",
        description=f"Mirror of cross-group task progress. Scope: {task.scope}",
        is_archived=False,
    )
    session.add(source_conversation)
    session.flush()
    session.add(
        ConversationParticipant(
            conversation_id=source_conversation.id,
            user_id=task.requested_by_user_id,
        )
    )

    task.target_conversation_id = target_conversation.id
    task.source_conversation_id = source_conversation.id

    # Post initial summary message in both conversations
    summary_content = (
        f"Task accepted: {task.title}\n"
        f"Scope: {task.scope}\n"
        f"Requirements: {task.requirements}\n"
        f"Terms: {task.terms or '(none)'}"
    )
    target_msg = Message(
        conversation_id=target_conversation.id,
        sender_type="system",
        content=f"[Cross-group task started] {summary_content}",
        requires_response=False,
    )
    source_msg = Message(
        conversation_id=source_conversation.id,
        sender_type="system",
        content=f"[Cross-group task accepted] {summary_content}",
        requires_response=False,
    )
    session.add(target_msg)
    session.add(source_msg)

    # Transition to in_progress
    task.status = "in_progress"
    session.add(task)
    session.commit()
    session.refresh(task)
    return _task_detail(session, task)


@router.post(
    "/cross-group-tasks/{task_id}/complete",
    response_model=CrossGroupTaskDetailRead,
)
def complete_task(
    task_id: str,
    payload: CrossGroupTaskCompleteRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> CrossGroupTaskDetailRead:
    task = session.get(CrossGroupTask, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    # Must be target workgroup member
    target_membership = session.exec(
        select(Membership).where(
            Membership.workgroup_id == task.target_workgroup_id,
            Membership.user_id == user.id,
        )
    ).first()
    if not target_membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only target workgroup members can mark tasks complete",
        )

    if task.status != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot complete task in status '{task.status}'",
        )

    task.status = "completed"
    task.completed_at = utc_now()
    session.add(task)

    # Post completion message to both conversations
    summary = payload.summary.strip() if payload.summary else "Task marked as completed."
    if task.target_conversation_id:
        session.add(
            Message(
                conversation_id=task.target_conversation_id,
                sender_type="system",
                content=f"[Task completed] {summary}",
                requires_response=False,
            )
        )
    if task.source_conversation_id:
        session.add(
            Message(
                conversation_id=task.source_conversation_id,
                sender_type="system",
                content=f"[Task completed] {summary}",
                requires_response=False,
            )
        )

    session.commit()
    session.refresh(task)
    return _task_detail(session, task)


@router.post(
    "/cross-group-tasks/{task_id}/satisfaction",
    response_model=CrossGroupTaskDetailRead,
)
def rate_task_satisfaction(
    task_id: str,
    payload: CrossGroupTaskSatisfactionRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> CrossGroupTaskDetailRead:
    task = session.get(CrossGroupTask, task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    # Must be source workgroup member
    source_membership = session.exec(
        select(Membership).where(
            Membership.workgroup_id == task.source_workgroup_id,
            Membership.user_id == user.id,
        )
    ).first()
    if not source_membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only source workgroup members can rate satisfaction",
        )

    if task.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot rate satisfaction in status '{task.status}'",
        )

    task.status = payload.action
    task.satisfied_at = utc_now()
    session.add(task)

    feedback = payload.feedback.strip() if payload.feedback else ""
    status_label = "satisfied" if payload.action == "satisfied" else "dissatisfied"
    notification = f"[Task {status_label}]"
    if feedback:
        notification += f" Feedback: {feedback}"

    if task.target_conversation_id:
        session.add(
            Message(
                conversation_id=task.target_conversation_id,
                sender_type="system",
                content=notification,
                requires_response=False,
            )
        )
    if task.source_conversation_id:
        session.add(
            Message(
                conversation_id=task.source_conversation_id,
                sender_type="system",
                content=notification,
                requires_response=False,
            )
        )

    session.commit()
    session.refresh(task)
    return _task_detail(session, task)
