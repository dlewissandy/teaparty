"""Member and agent management admin tools."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import func, or_
from sqlmodel import Session, select

from teaparty_app.models import (
    Agent,
    AgentLearningEvent,
    AgentMemory,
    Conversation,
    ConversationParticipant,
    Invite,
    Membership,
    Message,
    User,
    Workgroup,
    utc_now,
)
from teaparty_app.services.admin_workspace.bootstrap import (
    ADMIN_AGENT_SENTINEL,
    is_admin_agent,
    list_members as _list_members_query,
)
from teaparty_app.services.admin_workspace.parsing import (
    _normalize_member_selector,
    _parse_add_agent_payload,
    _parse_temperature,
)
from teaparty_app.services.admin_workspace.tools_common import (
    ResolvedMemberTarget,
    _delete_messages_and_dependents,
    _direct_conversation_ids_for_agent,
    _direct_conversation_ids_for_user,
    _delete_conversation_tree,
    _has_role,
    _merge_counts,
    _resolve_member_targets,
    queue_workgroup_deletion,
)


def admin_tool_list_members(
    session: Session,
    workgroup_id: str,
) -> str:
    human_members = _list_members_query(session, workgroup_id)
    agent_members = session.exec(
        select(Agent)
        .where(Agent.workgroup_id == workgroup_id)
        .order_by(func.lower(Agent.name).asc(), Agent.created_at.asc())
    ).all()

    if not human_members and not agent_members:
        return "No members found."

    lines = [f"Members (humans={len(human_members)}, agents={len(agent_members)}):"]

    for membership, user in human_members:
        display_name = (user.name or "").strip() or user.email
        lines.append(f"- [human] {display_name} <{user.email}> (role={membership.role}, id={user.id})")

    for agent in agent_members:
        lines.append(f"- [agent] {agent.name}")

    return "\n".join(lines)


def admin_tool_add_agent(
    session: Session,
    workgroup_id: str,
    requester_user_id: str,
    name: str,
    personality: str,
    role: str = "",
    backstory: str = "",
    model: str = "",
    temperature: float | str | None = None,
) -> str:
    if not _has_role(session, workgroup_id, requester_user_id, min_role="owner"):
        return "Owner permissions required to add agents."

    inferred_temperature, _ = _parse_temperature(temperature, default=0.7)

    # Safety net for SDK calls that pass a full free-form profile in `agent_name`.
    if (
        name
        and (len(name) > 48 or " is " in name.lower() or " model " in name.lower() or "." in name)
        and personality.strip() == "Professional and concise"
        and not role.strip()
        and not backstory.strip()
        and (not model.strip() or model.strip() == "sonnet")
        and abs(inferred_temperature - 0.7) <= 1e-9
    ):
        parsed_name, parsed = _parse_add_agent_payload(name)
        if parsed_name:
            name = parsed_name
            personality = parsed.get("personality") or personality
            role = parsed.get("role") or role
            backstory = parsed.get("backstory") or backstory
            model = parsed.get("model") or model
            temperature = parsed.get("temperature") or temperature

    cleaned_name = name.strip()
    if not cleaned_name:
        return "Usage: add agent <name> [role=<text>] [personality=<text>] [backstory=<text>] [model=<name>] [temperature=<0..2>]"

    parsed_temperature, temp_error = _parse_temperature(temperature, default=0.7)
    if temp_error:
        return temp_error

    existing = session.exec(
        select(Agent).where(
            Agent.workgroup_id == workgroup_id,
            func.lower(Agent.name) == cleaned_name.lower(),
            Agent.description != ADMIN_AGENT_SENTINEL,
        )
    ).first()
    if existing:
        return f"Agent '{existing.name}' already exists (id={existing.id})."

    role_text = role.strip()
    backstory_text = backstory.strip()
    personality_text = personality.strip() or "Professional and concise"
    model_name = model.strip() or "sonnet"
    learning_state = {"engagement_bias": 0.0, "initiative_bias": 0.0, "confidence_bias": 0.0, "brevity_bias": 0.0}
    sentiment_state = {"valence": 0.0, "arousal": 0.0, "confidence": 0.0}

    agent = Agent(
        workgroup_id=workgroup_id,
        created_by_user_id=requester_user_id,
        name=cleaned_name,
        description=role_text,
        role=role_text,
        personality=personality_text,
        backstory=backstory_text,
        model=model_name,
        temperature=parsed_temperature,
        tool_names=[],
        response_threshold=0.55,
        learning_state=learning_state,
        sentiment_state=sentiment_state,
        learned_preferences=dict(learning_state),
    )
    session.add(agent)
    session.flush()

    return (
        f"Created agent '{agent.name}' with id={agent.id}. "
        f"model={agent.model}, temperature={agent.temperature}, role={agent.role or '(none)'}."
    )


def admin_tool_add_user(
    session: Session,
    workgroup_id: str,
    requester_user_id: str,
    email: str,
) -> str:
    if not _has_role(session, workgroup_id, requester_user_id, min_role="owner"):
        return "Owner permissions required to add users."

    normalized = email.lower().strip()
    user = session.exec(select(User).where(User.email == normalized)).first()
    if user:
        existing_membership = session.exec(
            select(Membership).where(
                Membership.workgroup_id == workgroup_id,
                Membership.user_id == user.id,
            )
        ).first()
        if existing_membership:
            return f"{normalized} is already a user in this workgroup."

        session.add(
            Membership(
                workgroup_id=workgroup_id,
                user_id=user.id,
                role="member",
            )
        )
        return f"Added existing user {normalized} to the workgroup."

    pending_invite = session.exec(
        select(Invite).where(
            Invite.workgroup_id == workgroup_id,
            Invite.email == normalized,
            Invite.status == "pending",
        )
    ).first()
    if pending_invite:
        return f"Pending invite already exists for {normalized}. Token={pending_invite.token}"

    invite = Invite(
        workgroup_id=workgroup_id,
        invited_by_user_id=requester_user_id,
        email=normalized,
        token=str(uuid4()),
        expires_at=utc_now() + timedelta(days=7),
    )
    session.add(invite)
    return f"Created invite for {normalized}. Token={invite.token}"


def admin_tool_remove_member(
    session: Session,
    workgroup_id: str,
    requester_user_id: str,
    member_selector: str,
) -> str:
    if not _has_role(session, workgroup_id, requester_user_id, min_role="owner"):
        return "Owner permissions required to remove members."

    selector = _normalize_member_selector(member_selector)
    if not selector:
        return "Usage: remove member <id|email|name>"

    targets = _resolve_member_targets(session, workgroup_id, selector)
    if not targets:
        return f"Member '{selector}' was not found in this workgroup."

    if len(targets) > 1:
        lines = [f"Multiple members match '{selector}'. Use id:"]
        for target in targets:
            lines.append(f"- {target.display}")
        return "\n".join(lines)

    target = targets[0]
    if target.kind == "human":
        membership = target.membership
        user = target.user
        if not membership or not user:
            return "Unable to resolve member details."
        if membership.role == "owner":
            return "Cannot remove the workgroup owner."

        counts = {
            "conversations": 0,
            "participants": 0,
            "messages": 0,
            "learning_events": 0,
            "response_links_cleared": 0,
            "memberships": 0,
        }
        direct_ids = _direct_conversation_ids_for_user(session, workgroup_id, user.id)
        for conversation_id in direct_ids:
            _merge_counts(counts, _delete_conversation_tree(session, conversation_id))

        participant_rows = session.exec(
            select(ConversationParticipant)
            .join(Conversation, ConversationParticipant.conversation_id == Conversation.id)
            .where(
                Conversation.workgroup_id == workgroup_id,
                ConversationParticipant.user_id == user.id,
            )
        ).all()
        for row in participant_rows:
            session.delete(row)
        counts["participants"] += len(participant_rows)

        session.delete(membership)
        counts["memberships"] += 1
        display_name = (user.name or "").strip() or user.email
        return (
            f"Removed member [human] {display_name} <{user.email}> (id={user.id}). "
            f"Deleted direct conversations={len(direct_ids)}, messages={counts['messages']}."
        )

    agent = target.agent
    if not agent:
        return "Unable to resolve member details."
    if is_admin_agent(agent):
        return "Cannot remove the hidden admin agent."
    if agent.is_lead:
        return "Cannot remove the workgroup lead agent."

    counts = {
        "conversations": 0,
        "participants": 0,
        "messages": 0,
        "learning_events": 0,
        "response_links_cleared": 0,
        "agents": 0,
    }
    direct_ids = _direct_conversation_ids_for_agent(session, workgroup_id, agent.id)
    for conversation_id in direct_ids:
        _merge_counts(counts, _delete_conversation_tree(session, conversation_id))

    message_rows = session.exec(
        select(Message)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Conversation.workgroup_id == workgroup_id,
            Message.sender_agent_id == agent.id,
        )
    ).all()
    _merge_counts(counts, _delete_messages_and_dependents(session, message_rows))

    participant_rows = session.exec(
        select(ConversationParticipant)
        .join(Conversation, ConversationParticipant.conversation_id == Conversation.id)
        .where(
            Conversation.workgroup_id == workgroup_id,
            ConversationParticipant.agent_id == agent.id,
        )
    ).all()
    for row in participant_rows:
        session.delete(row)
    counts["participants"] += len(participant_rows)

    learning_rows = session.exec(select(AgentLearningEvent).where(AgentLearningEvent.agent_id == agent.id)).all()
    for row in learning_rows:
        session.delete(row)
    counts["learning_events"] += len(learning_rows)

    memory_rows = session.exec(select(AgentMemory).where(AgentMemory.agent_id == agent.id)).all()
    for row in memory_rows:
        session.delete(row)

    session.delete(agent)
    counts["agents"] += 1
    return (
        f"Removed member [agent] {agent.name} (id={agent.id}). "
        f"Deleted direct conversations={len(direct_ids)}, messages={counts['messages']}."
    )


def admin_tool_delete_workgroup(
    session: Session,
    workgroup_id: str,
    requester_user_id: str,
    confirmed: bool = False,
) -> str:
    if not _has_role(session, workgroup_id, requester_user_id, min_role="owner"):
        return "Owner permissions required to delete the workgroup."

    workgroup = session.get(Workgroup, workgroup_id)
    if not workgroup:
        return "Workgroup not found."

    if not confirmed:
        return (
            f"This will permanently delete workgroup '{workgroup.name}' (id={workgroup.id}) "
            "and all its conversations. Re-run: `delete workgroup confirm`."
        )

    queue_workgroup_deletion(session, workgroup_id)
    return f"Confirmed. Deleting workgroup '{workgroup.name}' (id={workgroup.id})."
