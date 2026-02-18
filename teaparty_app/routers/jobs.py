from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlmodel import Session, select

from teaparty_app.db import commit_with_retry, get_session
from teaparty_app.deps import get_current_user
from teaparty_app.models import (
    Conversation,
    ConversationParticipant,
    Engagement,
    Job,
    Message,
    User,
    Workgroup,
    utc_now,
)
from teaparty_app.routers.conversations import _process_auto_responses_in_background
from teaparty_app.schemas import JobCreateRequest, JobDetailRead, JobRead, JobUpdateRequest
from teaparty_app.services.permissions import require_workgroup_membership

router = APIRouter(prefix="/api", tags=["jobs"])


@router.post(
    "/workgroups/{workgroup_id}/jobs",
    response_model=JobRead,
    status_code=status.HTTP_201_CREATED,
)
def create_job(
    workgroup_id: str,
    payload: JobCreateRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> JobRead:
    require_workgroup_membership(session, workgroup_id, user.id)

    workgroup = session.get(Workgroup, workgroup_id)
    if not workgroup:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workgroup not found")

    title = payload.title.strip()
    description = payload.description.strip()

    # Create the job conversation.
    conversation = Conversation(
        workgroup_id=workgroup_id,
        created_by_user_id=user.id,
        kind="job",
        topic=title,
        name=title,
        description=description,
    )
    session.add(conversation)
    session.flush()

    # Workflow auto-selection + workspace worktree (same as create_conversation).
    from teaparty_app.services.workflow_helpers import auto_select_workflow
    auto_select_workflow(session, workgroup, conversation)

    if getattr(workgroup, "workspace_enabled", False):
        try:
            from teaparty_app.models import Workspace
            from teaparty_app.services.workspace_manager import create_worktree_for_job, workspace_root_configured
            if workspace_root_configured():
                ws = session.exec(
                    select(Workspace).where(
                        Workspace.workgroup_id == workgroup_id,
                        Workspace.status == "active",
                    )
                ).first()
                if ws:
                    create_worktree_for_job(session, ws, conversation)
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                "Failed to create worktree for job %s", conversation.id, exc_info=True
            )

    # Add the creating user as a participant.
    session.add(ConversationParticipant(conversation_id=conversation.id, user_id=user.id))

    # Add selected agents as participants (if specific agents were requested).
    if payload.agent_ids:
        for aid in payload.agent_ids:
            session.add(ConversationParticipant(conversation_id=conversation.id, agent_id=aid))

    # Create the Job record.
    job = Job(
        title=title,
        scope=description,
        workgroup_id=workgroup_id,
        conversation_id=conversation.id,
        max_rounds=payload.max_rounds,
    )
    session.add(job)

    # Post the initial user message so agents auto-fire.
    content = title
    if description:
        content = f"{title}\n\n{description}"
    message = Message(
        conversation_id=conversation.id,
        sender_type="user",
        sender_user_id=user.id,
        content=content,
        requires_response=True,
    )
    session.add(message)

    commit_with_retry(session)
    session.refresh(job)
    session.refresh(message)

    background_tasks.add_task(_process_auto_responses_in_background, conversation.id, message.id)

    return JobRead.model_validate(job)


@router.get("/workgroups/{workgroup_id}/jobs", response_model=list[JobRead])
def list_jobs(
    workgroup_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[JobRead]:
    require_workgroup_membership(session, workgroup_id, user.id)

    jobs = session.exec(
        select(Job)
        .where(Job.workgroup_id == workgroup_id)
        .order_by(Job.created_at.desc())
    ).all()
    return [JobRead.model_validate(j) for j in jobs]


@router.get("/jobs/{job_id}", response_model=JobDetailRead)
def get_job(
    job_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> JobDetailRead:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    require_workgroup_membership(session, job.workgroup_id, user.id)

    workgroup = session.get(Workgroup, job.workgroup_id)
    engagement = session.get(Engagement, job.engagement_id) if job.engagement_id else None

    return JobDetailRead(
        **JobRead.model_validate(job).model_dump(),
        workgroup_name=workgroup.name if workgroup else "",
        engagement_title=engagement.title if engagement else "",
    )


@router.patch(
    "/jobs/{job_id}",
    response_model=JobRead,
)
def update_job(
    job_id: str,
    payload: JobUpdateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> JobRead:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    require_workgroup_membership(session, job.workgroup_id, user.id)

    if payload.title is not None:
        title = payload.title.strip()
        if not title:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Title cannot be empty")
        job.title = title

    if payload.status is not None:
        job.status = payload.status
        if payload.status in ("completed", "cancelled"):
            job.completed_at = utc_now()
            if job.conversation_id:
                from teaparty_app.services.agent_runtime import cancel_conversation
                cancel_conversation(job.conversation_id)

    session.add(job)
    commit_with_retry(session)
    session.refresh(job)
    return JobRead.model_validate(job)


@router.delete(
    "/jobs/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_job(
    job_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    job = session.get(Job, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    require_workgroup_membership(session, job.workgroup_id, user.id)

    # Cancel any running agent process.
    if job.conversation_id:
        from teaparty_app.services.agent_runtime import cancel_conversation
        cancel_conversation(job.conversation_id)

        # Delete messages and participants for the job conversation.
        conv = session.get(Conversation, job.conversation_id)
        if conv:
            for msg in session.exec(select(Message).where(Message.conversation_id == conv.id)).all():
                session.delete(msg)
            for cp in session.exec(select(ConversationParticipant).where(ConversationParticipant.conversation_id == conv.id)).all():
                session.delete(cp)
            session.delete(conv)

    session.delete(job)
    commit_with_retry(session)
