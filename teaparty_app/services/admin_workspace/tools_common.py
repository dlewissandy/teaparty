"""Shared infrastructure: deletion helpers, role checks, member resolution."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, or_
from sqlmodel import Session, select

from teaparty_app.models import (
    Agent,
    AgentLearningEvent,
    AgentMemory,
    AgentTodoItem,
    AgentWorkgroup,
    Conversation,
    ConversationParticipant,
    CrossGroupTask,
    CrossGroupTaskMessage,
    Engagement,
    EngagementSyncedMessage,
    Invite,
    LLMUsageEvent,
    Membership,
    Message,
    SyncedMessage,
    User,
    Workgroup,
)
from teaparty_app.services.admin_workspace.bootstrap import (
    ADMIN_AGENT_SENTINEL,
    SESSION_DELETE_WORKGROUP_KEY,
)
from teaparty_app.services.admin_workspace.parsing import (
    _normalize_member_selector,
)
from teaparty_app.services.agent_workgroups import lead_agent_for_workgroup


@dataclass
class ResolvedMemberTarget:
    kind: str  # "human" | "agent"
    display: str
    membership: Membership | None = None
    user: User | None = None
    agent: Agent | None = None


_ROLE_RANK = {"owner": 3, "editor": 2, "member": 1}


def _has_role(session: Session, workgroup_id: str, user_id: str, min_role: str = "owner") -> bool:
    membership = session.exec(
        select(Membership).where(Membership.workgroup_id == workgroup_id, Membership.user_id == user_id)
    ).first()
    if not membership:
        return False
    return _ROLE_RANK.get(membership.role, 0) >= _ROLE_RANK.get(min_role, 3)


def queue_workgroup_deletion(session: Session, workgroup_id: str) -> None:
    session.info[SESSION_DELETE_WORKGROUP_KEY] = workgroup_id


def consume_queued_workgroup_deletion(session: Session) -> str | None:
    pending = session.info.pop(SESSION_DELETE_WORKGROUP_KEY, None)
    return str(pending) if pending else None


def _iter_chunks(items: list[str], size: int = 300):
    if size <= 0:
        size = 300
    for index in range(0, len(items), size):
        yield items[index : index + size]


def _delete_messages_and_dependents(session: Session, messages: list[Message]) -> dict[str, int]:
    if not messages:
        return {
            "messages": 0,
            "learning_events": 0,
            "response_links_cleared": 0,
        }

    message_ids = [row.id for row in messages]
    learning_deleted = 0
    response_links_cleared = 0

    for chunk in _iter_chunks(message_ids):
        # Clean up synced message links that reference these messages
        synced_rows = session.exec(
            select(SyncedMessage).where(
                or_(SyncedMessage.source_message_id.in_(chunk), SyncedMessage.mirror_message_id.in_(chunk))
            )
        ).all()
        for row in synced_rows:
            session.delete(row)

        eng_synced_rows = session.exec(
            select(EngagementSyncedMessage).where(
                or_(
                    EngagementSyncedMessage.origin_message_id.in_(chunk),
                    EngagementSyncedMessage.synced_message_id.in_(chunk),
                )
            )
        ).all()
        for row in eng_synced_rows:
            session.delete(row)

        response_rows = session.exec(select(Message).where(Message.response_to_message_id.in_(chunk))).all()
        for row in response_rows:
            if row.response_to_message_id is None:
                continue
            row.response_to_message_id = None
            session.add(row)
            response_links_cleared += 1

        learning_rows = session.exec(select(AgentLearningEvent).where(AgentLearningEvent.message_id.in_(chunk))).all()
        for row in learning_rows:
            session.delete(row)
            learning_deleted += 1

    for row in messages:
        session.delete(row)

    return {
        "messages": len(messages),
        "learning_events": learning_deleted,
        "response_links_cleared": response_links_cleared,
    }


def clear_conversation_messages(session: Session, conversation_id: str) -> dict[str, int]:
    message_rows = session.exec(select(Message).where(Message.conversation_id == conversation_id)).all()
    return _delete_messages_and_dependents(session, message_rows)


def _merge_counts(total: dict[str, int], delta: dict[str, int]) -> None:
    for key, value in delta.items():
        total[key] = total.get(key, 0) + value


def _delete_conversation_tree(session: Session, conversation_id: str) -> dict[str, int]:
    conversation = session.get(Conversation, conversation_id)
    if not conversation:
        return {
            "conversations": 0,
            "participants": 0,
            "messages": 0,
            "learning_events": 0,
            "response_links_cleared": 0,
        }

    counts = {
        "conversations": 0,
        "participants": 0,
        "messages": 0,
        "learning_events": 0,
        "response_links_cleared": 0,
    }
    # Delete LLM usage events for this conversation
    usage_rows = session.exec(select(LLMUsageEvent).where(LLMUsageEvent.conversation_id == conversation_id)).all()
    for row in usage_rows:
        session.delete(row)

    message_rows = session.exec(select(Message).where(Message.conversation_id == conversation_id)).all()
    _merge_counts(counts, _delete_messages_and_dependents(session, message_rows))

    participant_rows = session.exec(
        select(ConversationParticipant).where(ConversationParticipant.conversation_id == conversation_id)
    ).all()
    for row in participant_rows:
        session.delete(row)
    counts["participants"] += len(participant_rows)

    session.delete(conversation)
    counts["conversations"] += 1
    return counts


def _workgroup_conversation_ids(session: Session, workgroup_id: str) -> list[str]:
    rows = session.exec(select(Conversation.id).where(Conversation.workgroup_id == workgroup_id)).all()
    return [row for row in rows if row]


def _direct_conversation_ids_for_user(session: Session, workgroup_id: str, user_id: str) -> list[str]:
    rows = session.exec(
        select(Conversation.id)
        .join(ConversationParticipant, ConversationParticipant.conversation_id == Conversation.id)
        .where(
            Conversation.workgroup_id == workgroup_id,
            Conversation.kind == "direct",
            ConversationParticipant.user_id == user_id,
        )
    ).all()
    return sorted({row for row in rows if row})


def _direct_conversation_ids_for_agent(session: Session, workgroup_id: str, agent_id: str) -> list[str]:
    rows = session.exec(
        select(Conversation.id)
        .join(ConversationParticipant, ConversationParticipant.conversation_id == Conversation.id)
        .where(
            Conversation.workgroup_id == workgroup_id,
            Conversation.kind == "direct",
            ConversationParticipant.agent_id == agent_id,
        )
    ).all()
    return sorted({row for row in rows if row})


def delete_workgroup_data(session: Session, workgroup_id: str) -> dict[str, int]:
    workgroup = session.get(Workgroup, workgroup_id)
    if not workgroup:
        return {
            "workgroups": 0,
            "conversations": 0,
            "participants": 0,
            "messages": 0,
            "learning_events": 0,
            "response_links_cleared": 0,
            "agents": 0,
            "memberships": 0,
            "invites": 0,
        }

    counts = {
        "workgroups": 0,
        "conversations": 0,
        "participants": 0,
        "messages": 0,
        "learning_events": 0,
        "response_links_cleared": 0,
        "agents": 0,
        "memberships": 0,
        "invites": 0,
    }

    # Destroy workspace if it exists
    try:
        from teaparty_app.services.workspace_manager import destroy_workspace, workspace_root_configured

        if workspace_root_configured():
            from teaparty_app.models import Workspace as WS

            ws = session.exec(select(WS).where(WS.workgroup_id == workgroup_id)).first()
            if ws:
                destroy_workspace(session, ws)
    except Exception:
        import logging

        logging.getLogger(__name__).warning("Failed to destroy workspace for workgroup %s", workgroup_id, exc_info=True)

    # Delete SyncedMessage -> CrossGroupTask -> CrossGroupTask
    tasks = session.exec(
        select(CrossGroupTask).where(
            or_(
                CrossGroupTask.source_workgroup_id == workgroup_id,
                CrossGroupTask.target_workgroup_id == workgroup_id,
            )
        )
    ).all()
    task_ids = [t.id for t in tasks]
    for chunk in _iter_chunks(task_ids):
        synced = session.exec(select(SyncedMessage).where(SyncedMessage.task_id.in_(chunk))).all()
        for s in synced:
            session.delete(s)
        task_msgs = session.exec(select(CrossGroupTaskMessage).where(CrossGroupTaskMessage.task_id.in_(chunk))).all()
        for m in task_msgs:
            session.delete(m)
    for t in tasks:
        session.delete(t)

    # Delete EngagementSyncedMessage -> Engagement
    engagements = session.exec(
        select(Engagement).where(
            or_(
                Engagement.source_workgroup_id == workgroup_id,
                Engagement.target_workgroup_id == workgroup_id,
            )
        )
    ).all()
    engagement_ids = [e.id for e in engagements]
    for chunk in _iter_chunks(engagement_ids):
        eng_synced = session.exec(
            select(EngagementSyncedMessage).where(EngagementSyncedMessage.engagement_id.in_(chunk))
        ).all()
        for s in eng_synced:
            session.delete(s)
    for e in engagements:
        session.delete(e)

    # Delete AgentTodoItem by workgroup_id
    todos = session.exec(select(AgentTodoItem).where(AgentTodoItem.workgroup_id == workgroup_id)).all()
    for t in todos:
        session.delete(t)

    for conversation_id in _workgroup_conversation_ids(session, workgroup_id):
        _merge_counts(counts, _delete_conversation_tree(session, conversation_id))

    invites = session.exec(select(Invite).where(Invite.workgroup_id == workgroup_id)).all()
    for invite in invites:
        session.delete(invite)
    counts["invites"] += len(invites)

    memberships = session.exec(select(Membership).where(Membership.workgroup_id == workgroup_id)).all()
    for membership in memberships:
        session.delete(membership)
    counts["memberships"] += len(memberships)

    # Find the lead agent before removing links (only the lead is deleted)
    lead_agent = lead_agent_for_workgroup(session, workgroup_id)

    # Delete all AgentWorkgroup links for this workgroup
    aw_links = session.exec(select(AgentWorkgroup).where(AgentWorkgroup.workgroup_id == workgroup_id)).all()
    for link in aw_links:
        session.delete(link)

    # Delete only the lead agent (non-lead agents survive workgroup deletion)
    if lead_agent:
        learning_rows = session.exec(
            select(AgentLearningEvent).where(AgentLearningEvent.agent_id == lead_agent.id)
        ).all()
        for row in learning_rows:
            session.delete(row)
        counts["learning_events"] += len(learning_rows)

        memory_rows = session.exec(select(AgentMemory).where(AgentMemory.agent_id == lead_agent.id)).all()
        for row in memory_rows:
            session.delete(row)

        session.delete(lead_agent)
        counts["agents"] += 1

    session.delete(workgroup)
    counts["workgroups"] += 1
    return counts


def _resolve_member_targets(session: Session, workgroup_id: str, selector: str) -> list[ResolvedMemberTarget]:
    normalized = _normalize_member_selector(selector)
    if not normalized:
        return []

    lowered = normalized.lower()
    targets: list[ResolvedMemberTarget] = []
    seen: set[tuple[str, str]] = set()

    def add_human(membership: Membership, user: User | None) -> None:
        if not user:
            return
        key = ("human", user.id)
        if key in seen:
            return
        seen.add(key)
        display_name = (user.name or "").strip() or user.email
        targets.append(
            ResolvedMemberTarget(
                kind="human",
                display=f"[human] {display_name} <{user.email}> (id={user.id})",
                membership=membership,
                user=user,
            )
        )

    membership_by_id = session.exec(
        select(Membership).where(
            Membership.workgroup_id == workgroup_id,
            Membership.user_id == normalized,
        )
    ).first()
    if membership_by_id:
        add_human(membership_by_id, session.get(User, membership_by_id.user_id))

    human_rows = session.exec(
        select(Membership, User)
        .join(User, Membership.user_id == User.id)
        .where(
            Membership.workgroup_id == workgroup_id,
            or_(
                func.lower(User.email) == lowered,
                func.lower(User.name) == lowered,
            ),
        )
    ).all()
    for membership, user in human_rows:
        add_human(membership, user)

    agent_rows = session.exec(
        select(Agent)
        .join(AgentWorkgroup, AgentWorkgroup.agent_id == Agent.id)
        .where(
            AgentWorkgroup.workgroup_id == workgroup_id,
            Agent.description != ADMIN_AGENT_SENTINEL,
            or_(
                Agent.id == normalized,
                func.lower(Agent.name) == lowered,
            ),
        )
    ).all()
    for agent in agent_rows:
        key = ("agent", agent.id)
        if key in seen:
            continue
        seen.add(key)
        targets.append(
            ResolvedMemberTarget(
                kind="agent",
                display=f"[agent] {agent.name} (id={agent.id})",
                agent=agent,
            )
        )

    return targets
