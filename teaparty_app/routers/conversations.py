from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from teaparty_app.db import engine, get_session
from teaparty_app.deps import get_current_user
from teaparty_app.models import Agent, Conversation, ConversationParticipant, Membership, Message, User
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
    close_tasks_satisfied_by_message,
    infer_requires_response,
    run_agent_auto_responses,
)
from teaparty_app.services.activity import ensure_activity_conversation_for_workgroup_id
from teaparty_app.services.admin_workspace import (
    clear_conversation_messages,
    ensure_admin_workspace_for_workgroup_id,
    ensure_direct_conversation,
    ensure_direct_conversation_with_agent,
)
from teaparty_app.services.permissions import require_workgroup_membership, require_workgroup_owner

router = APIRouter(prefix="/api", tags=["conversations"])


def _conversation_for_user(session: Session, conversation_id: str, user_id: str) -> Conversation:
    conversation = session.get(Conversation, conversation_id)
    if not conversation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    require_workgroup_membership(session, conversation.workgroup_id, user_id)
    return conversation


def _process_auto_responses_in_background(conversation_id: str, trigger_message_id: str) -> None:
    with Session(engine) as background_session:
        conversation = background_session.get(Conversation, conversation_id)
        trigger = background_session.get(Message, trigger_message_id)
        if not conversation or not trigger:
            return

        run_agent_auto_responses(background_session, conversation, trigger)
        background_session.commit()


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
        if not agent or agent.workgroup_id != workgroup_id:
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
    session.refresh(conversation)
    return ConversationRead.model_validate(conversation)


@router.get("/workgroups/{workgroup_id}/conversations", response_model=list[ConversationRead])
def list_conversations(
    workgroup_id: str,
    include_archived: bool = Query(default=False),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[ConversationRead]:
    require_workgroup_membership(session, workgroup_id, user.id)
    _agent, _conversation, admin_changed = ensure_admin_workspace_for_workgroup_id(session, workgroup_id)
    _activity_conversation, activity_changed = ensure_activity_conversation_for_workgroup_id(session, workgroup_id)
    if admin_changed or activity_changed:
        session.commit()
    query = select(Conversation).where(Conversation.workgroup_id == workgroup_id)
    if not include_archived:
        query = query.where(Conversation.is_archived == False)  # noqa: E712
    conversations = session.exec(query.order_by(Conversation.created_at.desc())).all()
    return [ConversationRead.model_validate(item) for item in conversations]


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
    if conversation.kind != "topic":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only topic conversations can be updated by this endpoint",
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

    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return ConversationRead.model_validate(conversation)


@router.delete(
    "/workgroups/{workgroup_id}/conversations/{conversation_id}/messages",
    response_model=ConversationHistoryClearResponse,
)
def clear_topic_conversation_history(
    workgroup_id: str,
    conversation_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> ConversationHistoryClearResponse:
    require_workgroup_owner(session, workgroup_id, user.id)

    conversation = session.get(Conversation, conversation_id)
    if not conversation or conversation.workgroup_id != workgroup_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if conversation.kind != "topic":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only topic conversation history can be cleared by this endpoint",
        )

    counts = clear_conversation_messages(session, conversation_id)
    session.commit()
    return ConversationHistoryClearResponse(
        conversation_id=conversation_id,
        deleted_messages=counts["messages"],
        deleted_learning_events=counts["learning_events"],
        deleted_followup_tasks=counts["followup_tasks"],
        cleared_response_links=counts["response_links_cleared"],
    )


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageRead])
def list_messages(
    conversation_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> list[MessageRead]:
    _conversation_for_user(session, conversation_id, user.id)
    rows = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    ).all()
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
) -> MessageEnvelope:
    conversation = _conversation_for_user(session, conversation_id, user.id)
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

    close_tasks_satisfied_by_message(session, message)
    session.commit()
    session.refresh(message)

    background_tasks.add_task(_process_auto_responses_in_background, conversation.id, message.id)

    return MessageEnvelope(
        posted=MessageRead.model_validate(message),
        agent_replies=[],
    )
