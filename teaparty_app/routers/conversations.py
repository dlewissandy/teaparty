"""REST API for conversations: CRUD, messaging, SSE streaming, and history."""

import asyncio
import json
import time

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlmodel import Session, select

from teaparty_app.db import commit_with_retry, engine, get_session
from teaparty_app.deps import get_current_user
from teaparty_app.models import Agent, AgentLearningEvent, Conversation, ConversationParticipant, Membership, Message, OrgMembership, User, Workspace, Workgroup, utc_now
from teaparty_app.schemas import (
    ConversationCreateRequest,
    ConversationHistoryClearResponse,
    ConversationRead,
    ConversationUpdateRequest,
    ConversationUsageRead,
    MessageCreateRequest,
    MessageEnvelope,
    MessageRead,
)
from teaparty_app.services.agent_runtime import (
    get_conversation_activity,
    infer_requires_response,
    run_agent_auto_responses,
)
from teaparty_app.services.activity import ensure_activity_conversation_for_workgroup_id
from teaparty_app.services.admin_workspace import (
    clear_conversation_messages,
    ensure_direct_conversation,
    ensure_direct_conversation_with_agent,
)
from teaparty_app.services.agent_workgroups import agent_in_workgroup
from teaparty_app.services.permissions import check_budget, require_workgroup_editor, require_workgroup_membership, require_workgroup_owner
from teaparty_app.services.sync_events import publish_sync_event

router = APIRouter(prefix="/api", tags=["conversations"])

_IDEMPOTENCY_CACHE: dict[str, tuple[float, MessageEnvelope]] = {}
_IDEMPOTENCY_TTL = 300  # 5 minutes


def _idempotency_check(key: str | None) -> MessageEnvelope | None:
    if not key:
        return None
    now = time.monotonic()
    # Prune expired entries
    expired = [k for k, (ts, _) in _IDEMPOTENCY_CACHE.items() if now - ts > _IDEMPOTENCY_TTL]
    for k in expired:
        del _IDEMPOTENCY_CACHE[k]
    entry = _IDEMPOTENCY_CACHE.get(key)
    if entry:
        return entry[1]
    return None


def _idempotency_store(key: str | None, envelope: MessageEnvelope) -> None:
    if key:
        _IDEMPOTENCY_CACHE[key] = (time.monotonic(), envelope)


def _conversation_for_user(session: Session, conversation_id: str, user_id: str) -> Conversation:
    conversation = session.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if conversation.workgroup_id:
        require_workgroup_membership(session, conversation.workgroup_id, user_id)
    elif conversation.organization_id:
        mem = session.exec(
            select(OrgMembership).where(
                OrgMembership.organization_id == conversation.organization_id,
                OrgMembership.user_id == user_id,
            )
        ).first()
        if not mem:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not an organization member")
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conversation has no scope")
    return conversation


def _process_auto_responses_in_background(conversation_id: str, trigger_message_id: str) -> None:
    import logging

    logger = logging.getLogger(__name__)
    try:
        with Session(engine, autoflush=False) as background_session:
            conversation = background_session.get(Conversation, conversation_id)
            trigger = background_session.get(Message, trigger_message_id)
            if not conversation or not trigger:
                logger.warning(
                    "Background auto-response skipped: conversation=%s trigger=%s (missing)",
                    conversation_id,
                    trigger_message_id,
                )
                return

            run_agent_auto_responses(background_session, conversation, trigger)
            background_session.commit()
    except Exception:
        logger.exception(
            "Background auto-response failed for conversation=%s trigger=%s",
            conversation_id,
            trigger_message_id,
        )


@router.post("/workgroups/{workgroup_id}/conversations", response_model=ConversationRead)
def create_conversation(
    workgroup_id: str,
    payload: ConversationCreateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ConversationRead:
    require_workgroup_membership(session, workgroup_id, user.id)

    if payload.kind == "direct" and not payload.participant_user_ids and not payload.participant_agent_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Direct conversations require participants")

    for participant_user_id in payload.participant_user_ids:
        member = session.exec(
            select(Membership).where(
                Membership.workgroup_id == workgroup_id,
                Membership.user_id == participant_user_id,
            )
        ).first()
        if not member:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User {participant_user_id} is not in this workgroup",
            )

    for participant_agent_id in payload.participant_agent_ids:
        agent = session.get(Agent, participant_agent_id)
        if not agent or not agent_in_workgroup(session, participant_agent_id, workgroup_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Agent {participant_agent_id} is not in this workgroup",
            )

    topic = payload.topic.strip() or "general"
    display_name = payload.name.strip() or topic
    description = payload.description.strip()

    conversation = Conversation(
        workgroup_id=workgroup_id,
        created_by_user_id=user.id,
        kind=payload.kind,
        topic=topic,
        name=display_name,
        description=description,
    )
    session.add(conversation)
    session.flush()

    if payload.kind == "job":
        from teaparty_app.services.workflow_helpers import auto_select_workflow

        workgroup = session.get(Workgroup, workgroup_id)
        if workgroup:
            auto_select_workflow(session, workgroup, conversation)

            if getattr(workgroup, "workspace_enabled", False):
                try:
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

    all_user_ids = set(payload.participant_user_ids)
    all_user_ids.add(user.id)
    for participant_user_id in all_user_ids:
        session.add(
            ConversationParticipant(
                conversation_id=conversation.id,
                user_id=participant_user_id,
            )
        )

    for participant_agent_id in set(payload.participant_agent_ids):
        session.add(
            ConversationParticipant(
                conversation_id=conversation.id,
                agent_id=participant_agent_id,
            )
        )

    session.commit()
    publish_sync_event(session, "workgroup", conversation.workgroup_id, "sync:tree_changed", {"workgroup_id": conversation.workgroup_id})
    session.refresh(conversation)
    return ConversationRead.model_validate(conversation)


@router.get("/workgroups/{workgroup_id}/conversations", response_model=list[ConversationRead])
def list_conversations(
    workgroup_id: str,
    include_archived: bool = Query(default=False),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[ConversationRead]:
    membership = require_workgroup_membership(session, workgroup_id, user.id)
    is_owner = membership.role == "owner"
    _activity_conversation, activity_changed = ensure_activity_conversation_for_workgroup_id(session, workgroup_id)
    if activity_changed:
        session.commit()
    query = select(Conversation).where(Conversation.workgroup_id == workgroup_id)
    if not include_archived:
        query = query.where(Conversation.is_archived == False)  # noqa: E712
    if not is_owner:
        query = query.where(Conversation.kind != "admin")
    conversations = session.exec(query.order_by(Conversation.created_at.desc())).all()

    conv_ids = [c.id for c in conversations]
    if conv_ids:
        latest_stmt = (
            select(Message.conversation_id, func.max(Message.created_at).label("latest"))
            .where(
                Message.conversation_id.in_(conv_ids),
                (Message.sender_user_id != user.id) | (Message.sender_user_id == None),  # noqa: E711
            )
            .group_by(Message.conversation_id)
        )
        latest_map = {row.conversation_id: row.latest for row in session.exec(latest_stmt).all()}
    else:
        latest_map = {}

    return [
        ConversationRead(**{**ConversationRead.model_validate(c).model_dump(), "latest_message_at": latest_map.get(c.id)})
        for c in conversations
    ]


@router.post("/workgroups/{workgroup_id}/members/{member_user_id}/direct-conversation", response_model=ConversationRead)
def open_direct_conversation_for_member(
    workgroup_id: str,
    member_user_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ConversationRead:
    conversation = ensure_direct_conversation(
        session=session,
        workgroup_id=workgroup_id,
        requester_user_id=user.id,
        other_user_id=member_user_id,
    )
    session.commit()
    session.refresh(conversation)
    return ConversationRead.model_validate(conversation)


@router.post("/workgroups/{workgroup_id}/agents/{agent_id}/direct-conversation", response_model=ConversationRead)
def open_direct_conversation_for_agent(
    workgroup_id: str,
    agent_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ConversationRead:
    conversation = ensure_direct_conversation_with_agent(
        session=session,
        workgroup_id=workgroup_id,
        requester_user_id=user.id,
        agent_id=agent_id,
    )
    session.commit()
    session.refresh(conversation)
    return ConversationRead.model_validate(conversation)


@router.patch("/workgroups/{workgroup_id}/conversations/{conversation_id}", response_model=ConversationRead)
def update_topic_conversation(
    workgroup_id: str,
    conversation_id: str,
    payload: ConversationUpdateRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ConversationRead:
    require_workgroup_membership(session, workgroup_id, user.id)

    conversation = session.get(Conversation, conversation_id)
    if not conversation or conversation.workgroup_id != workgroup_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if conversation.kind not in ("job", "task"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only job and task conversations can be updated by this endpoint",
        )

    if payload.topic is not None:
        topic = payload.topic.strip()
        if not topic:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Topic key cannot be empty")
        conversation.topic = topic

    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Topic name cannot be empty")
        conversation.name = name

    if payload.description is not None:
        conversation.description = payload.description.strip()

    if payload.is_archived is not None:
        require_workgroup_editor(session, workgroup_id, user.id)
        conversation.is_archived = payload.is_archived
        conversation.archived_at = utc_now() if payload.is_archived else None

    session.add(conversation)
    session.commit()
    publish_sync_event(session, "workgroup", conversation.workgroup_id, "sync:tree_changed", {"workgroup_id": conversation.workgroup_id})
    session.refresh(conversation)
    return ConversationRead.model_validate(conversation)


def _cleanup_claude_session(session_id: str) -> None:
    """Remove Claude CLI session files for the given session ID."""
    import glob
    import os
    home = os.path.expanduser("~")
    for path in glob.glob(f"{home}/.claude/projects/*/{session_id}.jsonl"):
        try:
            os.remove(path)
        except OSError:
            pass


@router.delete(
    "/workgroups/{workgroup_id}/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_conversation(
    workgroup_id: str,
    conversation_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    """Delete a conversation and all its data, including Claude session files."""
    require_workgroup_membership(session, workgroup_id, user.id)

    conversation = session.get(Conversation, conversation_id)
    if not conversation or conversation.workgroup_id != workgroup_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

    from teaparty_app.services.agent_runtime import cancel_conversation
    cancel_conversation(conversation_id)

    # Clean up Claude session file
    if conversation.claude_session_id:
        _cleanup_claude_session(conversation.claude_session_id)

    # Delete messages, participants, learning events
    clear_conversation_messages(session, conversation_id)
    for cp in session.exec(
        select(ConversationParticipant).where(ConversationParticipant.conversation_id == conversation_id)
    ).all():
        session.delete(cp)

    session.delete(conversation)
    commit_with_retry(session)
    publish_sync_event(session, "workgroup", workgroup_id, "sync:tree_changed", {"workgroup_id": workgroup_id})


@router.delete(
    "/workgroups/{workgroup_id}/conversations/{conversation_id}/messages",
    response_model=ConversationHistoryClearResponse,
)
def clear_job_conversation_history(
    workgroup_id: str,
    conversation_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ConversationHistoryClearResponse:
    require_workgroup_owner(session, workgroup_id, user.id)

    conversation = session.get(Conversation, conversation_id)
    if not conversation or conversation.workgroup_id != workgroup_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if conversation.kind not in ("job", "task"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only job and task conversation history can be cleared by this endpoint",
        )

    counts = clear_conversation_messages(session, conversation_id)
    conversation.claude_session_id = None
    session.add(conversation)
    session.commit()
    publish_sync_event(session, "workgroup", conversation.workgroup_id, "sync:tree_changed", {"workgroup_id": conversation.workgroup_id})
    return ConversationHistoryClearResponse(
        conversation_id=conversation_id,
        deleted_messages=counts["messages"],
        deleted_learning_events=counts["learning_events"],
        cleared_response_links=counts["response_links_cleared"],
    )


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageRead])
def list_messages(
    conversation_id: str,
    since_id: str | None = Query(default=None),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[MessageRead]:
    _conversation_for_user(session, conversation_id, user.id)
    query = select(Message).where(Message.conversation_id == conversation_id)
    if since_id:
        anchor = session.get(Message, since_id)
        if anchor and anchor.conversation_id == conversation_id:
            query = query.where(Message.created_at > anchor.created_at)
    rows = session.exec(query.order_by(Message.created_at.asc())).all()
    return [MessageRead.model_validate(item) for item in rows]


@router.get("/conversations/{conversation_id}/usage", response_model=ConversationUsageRead)
def get_conversation_usage_endpoint(
    conversation_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ConversationUsageRead:
    _conversation_for_user(session, conversation_id, user.id)
    from teaparty_app.services.llm_usage import get_conversation_usage

    data = get_conversation_usage(session, conversation_id)
    return ConversationUsageRead(**data)


@router.post("/conversations/{conversation_id}/messages", response_model=MessageEnvelope)
def post_message(
    conversation_id: str,
    payload: MessageCreateRequest,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
    x_idempotency_key: str | None = Header(default=None),
) -> MessageEnvelope:
    cached = _idempotency_check(x_idempotency_key)
    if cached is not None:
        return cached

    conversation = _conversation_for_user(session, conversation_id, user.id)
    if conversation.is_archived:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot post to an archived conversation")
    # Org-level conversations (projects) don't have workgroup membership or budget.
    if conversation.workgroup_id:
        membership = require_workgroup_membership(session, conversation.workgroup_id, user.id)
        if conversation.kind == "admin" and membership.role != "owner":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Owner permissions required")
        check_budget(membership)
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message content cannot be empty")

    message = Message(
        conversation_id=conversation_id,
        sender_type="user",
        sender_user_id=user.id,
        content=content,
        requires_response=payload.requires_response
        if payload.requires_response is not None
        else infer_requires_response(content),
        response_to_message_id=payload.response_to_message_id,
    )
    session.add(message)
    session.flush()

    from teaparty_app.services.todo_helpers import evaluate_message_match_todos
    evaluate_message_match_todos(session, message)

    session.commit()
    if conversation.workgroup_id:
        publish_sync_event(session, "workgroup", conversation.workgroup_id, "sync:message_posted", {"workgroup_id": conversation.workgroup_id, "conversation_id": conversation.id})
    elif conversation.organization_id:
        publish_sync_event(session, "organization", conversation.organization_id, "sync:message_posted", {"organization_id": conversation.organization_id, "conversation_id": conversation.id})
    session.refresh(message)

    background_tasks.add_task(_process_auto_responses_in_background, conversation.id, message.id)

    envelope = MessageEnvelope(
        posted=MessageRead.model_validate(message),
        agent_replies=[],
    )
    _idempotency_store(x_idempotency_key, envelope)
    return envelope


@router.get("/conversations/{conversation_id}/activity")
def get_activity(
    conversation_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    from teaparty_app.services.team_registry import get_session as get_team_session
    _conversation_for_user(session, conversation_id, user.id)
    agents = get_conversation_activity(conversation_id)
    team = get_team_session(conversation_id)
    return {
        "agents": agents,
        "stream_active": team is not None and team.is_running,
    }


@router.get("/conversations/{conversation_id}/events")
async def stream_events(
    conversation_id: str,
    request: Request,
    token: str = Query(...),
    session: Session = Depends(get_session),
) -> StreamingResponse:
    from teaparty_app.auth import decode_access_token
    from teaparty_app.services.event_bus import get_shutdown_event, subscribe, unsubscribe

    user_id = decode_access_token(token)
    _conversation_for_user(session, conversation_id, user_id)

    queue, handle = subscribe(conversation_id)
    shutdown = get_shutdown_event()

    async def event_stream():
        try:
            from teaparty_app.services.team_registry import get_session as get_team_session
            agents = get_conversation_activity(conversation_id)
            team = get_team_session(conversation_id)
            initial = {
                "type": "activity",
                "agents": agents,
                "stream_active": team is not None and team.is_running,
            }
            yield f"data: {json.dumps(initial)}\n\n"

            while not shutdown.is_set():
                if await request.is_disconnected():
                    break
                get_task = asyncio.ensure_future(queue.get())
                shut_task = asyncio.ensure_future(shutdown.wait())
                done, pending = await asyncio.wait(
                    {get_task, shut_task},
                    timeout=15,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for t in pending:
                    t.cancel()
                if shut_task in done:
                    break
                if get_task in done:
                    yield f"data: {json.dumps(get_task.result(), default=str)}\n\n"
                else:
                    yield ": heartbeat\n\n"
        finally:
            unsubscribe(conversation_id, handle)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations/{conversation_id}/participants")
def get_conversation_participants(
    conversation_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    conversation = _conversation_for_user(session, conversation_id, user.id)

    participants = session.exec(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == conversation_id
        )
    ).all()

    users_out = []
    agents_out = []

    for p in participants:
        if p.user_id:
            member = session.get(User, p.user_id)
            if member:
                users_out.append({"id": member.id, "name": member.name, "email": member.email})
        elif p.agent_id:
            agent = session.get(Agent, p.agent_id)
            if agent:
                from teaparty_app.models import AgentWorkgroup
                is_lead = session.exec(
                    select(AgentWorkgroup).where(
                        AgentWorkgroup.agent_id == agent.id,
                        AgentWorkgroup.workgroup_id == conversation.workgroup_id,
                        AgentWorkgroup.is_lead == True,  # noqa: E712
                    )
                ).first() is not None
                agents_out.append({"id": agent.id, "name": agent.name, "description": agent.description, "is_lead": is_lead})

    return {"users": users_out, "agents": agents_out}


@router.get("/conversations/{conversation_id}/workflow-state")
def get_conversation_workflow_state(
    conversation_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    conversation = _conversation_for_user(session, conversation_id, user.id)

    workgroup = session.get(Workgroup, conversation.workgroup_id)
    if not workgroup:
        return {"steps": [], "current_step": None}

    # Find the _workflow_state.md file scoped to this conversation
    all_files = workgroup.files or []
    state_file = next(
        (
            f for f in all_files
            if isinstance(f, dict)
            and f.get("path") == "_workflow_state.md"
            and f.get("topic_id") == conversation_id
        ),
        None,
    )

    if not state_file:
        return {"steps": [], "current_step": None}

    return _parse_workflow_state(state_file.get("content", ""))


def _parse_workflow_state(content: str) -> dict:
    """Parse a _workflow_state.md file into structured step data."""
    import re

    steps = []
    current_step = None

    for line in content.splitlines():
        # Parse current step: "- **Current Step**: 2"
        m = re.match(r"-\s+\*\*Current Step\*\*:\s*(\d+)", line.strip())
        if m:
            current_step = int(m.group(1))

        # Parse step log entries: "- [x] 1. Scope (completed)" or "- [ ] 2. Analyze (in_progress)"
        m = re.match(r"-\s+\[([x ])\]\s+(\d+)\.\s+(.+)", line.strip())
        if m:
            checked = m.group(1) == "x"
            number = int(m.group(2))
            rest = m.group(3).strip()

            # Extract status from parentheses at the end
            status_match = re.search(r"\((\w+)\)\s*$", rest)
            if status_match:
                raw_status = status_match.group(1)
                name = rest[: status_match.start()].strip().rstrip(".-").strip()
            else:
                raw_status = "completed" if checked else "pending"
                name = rest.strip()

            # Normalize status
            if raw_status in ("done", "complete", "completed"):
                step_status = "completed"
            elif raw_status in ("active", "in_progress", "in-progress", "current"):
                step_status = "in_progress"
            else:
                step_status = "pending" if not checked else "completed"

            steps.append({
                "number": number,
                "name": name,
                "status": step_status,
                "description": "",
            })

    return {"steps": steps, "current_step": current_step}


@router.get("/conversations/{conversation_id}/thoughts")
def get_thoughts(
    conversation_id: str,
    message_ids: str = Query(default=""),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> dict:
    _conversation_for_user(session, conversation_id, user.id)

    if message_ids.strip():
        target_ids = [mid.strip() for mid in message_ids.split(",") if mid.strip()]
    else:
        # Fall back to last 50 agent messages in this conversation.
        rows = session.exec(
            select(Message.id)
            .where(
                Message.conversation_id == conversation_id,
                Message.sender_type == "agent",
            )
            .order_by(Message.created_at.desc())
            .limit(50)
        ).all()
        target_ids = list(rows)

    if not target_ids:
        return {}

    events = session.exec(
        select(AgentLearningEvent).where(
            AgentLearningEvent.message_id.in_(target_ids),
            AgentLearningEvent.signal_type == "agent_thoughts",
        )
    ).all()

    result: dict[str, dict] = {}
    for event in events:
        result[event.message_id] = event.value
    return result
