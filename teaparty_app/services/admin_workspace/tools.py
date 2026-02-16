"""Admin tool implementations, deletion helpers, and member resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlmodel import Session, select

from teaparty_app.models import (
    Agent,
    AgentFollowUpTask,
    AgentLearningEvent,
    AgentMemory,
    AgentTodoItem,
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
    ToolDefinition,
    ToolGrant,
    User,
    Workgroup,
    utc_now,
)
from teaparty_app.services.activity import post_file_change_activity
from teaparty_app.services.admin_workspace.bootstrap import (
    ADMIN_AGENT_SENTINEL,
    SESSION_DELETE_WORKGROUP_KEY,
    is_admin_agent,
    list_members as _list_members_query,
)
from teaparty_app.services.admin_workspace.parsing import (
    _normalize_file_content,
    _normalize_file_path,
    _normalize_list_jobs_status,
    _normalize_member_selector,
    _normalize_task_selector,
    _normalize_job_selector,
    _normalize_workgroup_files_for_tool,
    _parse_add_agent_payload,
    _parse_temperature,
)


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
            "followup_tasks": 0,
            "response_links_cleared": 0,
        }

    message_ids = [row.id for row in messages]
    learning_deleted = 0
    followups_deleted = 0
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

        followup_rows = session.exec(select(AgentFollowUpTask).where(AgentFollowUpTask.origin_message_id.in_(chunk))).all()
        for row in followup_rows:
            session.delete(row)
            followups_deleted += 1

    for row in messages:
        session.delete(row)

    return {
        "messages": len(messages),
        "learning_events": learning_deleted,
        "followup_tasks": followups_deleted,
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
            "followup_tasks": 0,
            "response_links_cleared": 0,
        }

    counts = {
        "conversations": 0,
        "participants": 0,
        "messages": 0,
        "learning_events": 0,
        "followup_tasks": 0,
        "response_links_cleared": 0,
    }
    # Delete LLM usage events for this conversation
    usage_rows = session.exec(select(LLMUsageEvent).where(LLMUsageEvent.conversation_id == conversation_id)).all()
    for row in usage_rows:
        session.delete(row)

    message_rows = session.exec(select(Message).where(Message.conversation_id == conversation_id)).all()
    _merge_counts(counts, _delete_messages_and_dependents(session, message_rows))

    task_rows = session.exec(select(AgentFollowUpTask).where(AgentFollowUpTask.conversation_id == conversation_id)).all()
    for row in task_rows:
        session.delete(row)
    counts["followup_tasks"] += len(task_rows)

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
            "followup_tasks": 0,
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
        "followup_tasks": 0,
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

    # Delete ToolGrant → ToolDefinition
    tool_defs = session.exec(select(ToolDefinition).where(ToolDefinition.workgroup_id == workgroup_id)).all()
    tool_def_ids = [td.id for td in tool_defs]
    for chunk in _iter_chunks(tool_def_ids):
        grants = session.exec(select(ToolGrant).where(ToolGrant.tool_definition_id.in_(chunk))).all()
        for g in grants:
            session.delete(g)
    grants_to = session.exec(select(ToolGrant).where(ToolGrant.grantee_workgroup_id == workgroup_id)).all()
    for g in grants_to:
        session.delete(g)
    for td in tool_defs:
        session.delete(td)

    # Delete SyncedMessage → CrossGroupTaskMessage → CrossGroupTask
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

    # Delete EngagementSyncedMessage → Engagement
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

    agents = session.exec(select(Agent).where(Agent.workgroup_id == workgroup_id)).all()
    for agent in agents:
        learning_rows = session.exec(select(AgentLearningEvent).where(AgentLearningEvent.agent_id == agent.id)).all()
        for row in learning_rows:
            session.delete(row)
        counts["learning_events"] += len(learning_rows)

        memory_rows = session.exec(select(AgentMemory).where(AgentMemory.agent_id == agent.id)).all()
        for row in memory_rows:
            session.delete(row)

        followup_rows = session.exec(
            select(AgentFollowUpTask).where(
                or_(
                    AgentFollowUpTask.agent_id == agent.id,
                    AgentFollowUpTask.waiting_on_agent_id == agent.id,
                )
            )
        ).all()
        for row in followup_rows:
            session.delete(row)
        counts["followup_tasks"] += len(followup_rows)

        session.delete(agent)
    counts["agents"] += len(agents)

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
        select(Agent).where(
            Agent.workgroup_id == workgroup_id,
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


def _resolve_job_conversation(
    session: Session,
    workgroup_id: str,
    selector: str,
) -> tuple[Conversation | None, str | None]:
    normalized = _normalize_job_selector(selector)
    if not normalized:
        return None, "Job selector is empty."

    by_id = session.get(Conversation, normalized)
    if by_id and by_id.workgroup_id == workgroup_id and by_id.kind == "job":
        return by_id, None

    rows = session.exec(
        select(Conversation).where(
            Conversation.workgroup_id == workgroup_id,
            Conversation.kind == "job",
            or_(
                func.lower(Conversation.topic) == normalized.lower(),
                func.lower(Conversation.name) == normalized.lower(),
            ),
        )
    ).all()
    if not rows:
        return None, f"Job '{normalized}' was not found."
    if len(rows) > 1:
        ids = ", ".join(row.id for row in rows)
        return None, f"Multiple jobs named '{normalized}'. Use job id. Matching ids: {ids}"

    return rows[0], None


def admin_tool_add_job(
    session: Session,
    workgroup_id: str,
    requester_user_id: str,
    topic_name: str,
    description: str = "",
) -> str:
    if not _has_role(session, workgroup_id, requester_user_id, min_role="editor"):
        return "Editor permissions required to add jobs."
    topic = _normalize_job_selector(topic_name)
    if not topic:
        return "Usage: add job <name> [description=<text>]"
    topic_description = description.strip()

    existing_rows = session.exec(
        select(Conversation).where(
            Conversation.workgroup_id == workgroup_id,
            Conversation.kind == "job",
            func.lower(Conversation.topic) == topic.lower(),
        )
    ).all()

    if existing_rows:
        existing = existing_rows[0]
        was_archived = existing.is_archived
        updated = False
        if (existing.name or "").strip() != topic:
            existing.name = topic
            updated = True
        if topic_description and (existing.description or "").strip() != topic_description:
            existing.description = topic_description
            updated = True
        if was_archived:
            existing.is_archived = False
            existing.archived_at = None
            updated = True
        if updated:
            session.add(existing)
        if was_archived:
            return f"Job '{existing.topic}' was unarchived (id={existing.id})."
        if updated:
            return f"Updated job '{existing.topic}' (id={existing.id})."
        return f"Job '{existing.topic}' already exists (id={existing.id})."

    conversation = Conversation(
        workgroup_id=workgroup_id,
        created_by_user_id=requester_user_id,
        kind="job",
        topic=topic,
        name=topic,
        description=topic_description,
        is_archived=False,
    )
    session.add(conversation)
    session.flush()

    workgroup = session.get(Workgroup, workgroup_id)
    if workgroup:
        from teaparty_app.services.agent_tools import auto_select_workflow

        auto_select_workflow(session, workgroup, conversation)

    session.add(ConversationParticipant(conversation_id=conversation.id, user_id=requester_user_id))

    return f"Created job '{conversation.topic}' with id={conversation.id}."


def admin_tool_archive_job(
    session: Session,
    workgroup_id: str,
    requester_user_id: str,
    selector: str,
) -> str:
    if not _has_role(session, workgroup_id, requester_user_id, min_role="editor"):
        return "Editor permissions required to archive jobs."
    conversation, error = _resolve_job_conversation(session, workgroup_id, selector)
    if not conversation:
        return error or "Job not found."

    if conversation.is_archived:
        return f"Job '{conversation.topic}' is already archived."

    conversation.is_archived = True
    conversation.archived_at = utc_now()
    session.add(conversation)

    # Remove worktree but keep branch for history
    try:
        from teaparty_app.services.workspace_manager import remove_worktree, workspace_root_configured

        if workspace_root_configured():
            from teaparty_app.models import Workspace, WorkspaceWorktree

            ws = session.exec(
                select(Workspace).where(Workspace.workgroup_id == workgroup_id, Workspace.status == "active")
            ).first()
            if ws:
                wt = session.exec(
                    select(WorkspaceWorktree).where(
                        WorkspaceWorktree.workspace_id == ws.id,
                        WorkspaceWorktree.conversation_id == conversation.id,
                        WorkspaceWorktree.status == "active",
                    )
                ).first()
                if wt:
                    remove_worktree(session, wt, delete_branch=False)
    except Exception:
        import logging

        logging.getLogger(__name__).warning("Failed to remove worktree on archive for %s", conversation.id, exc_info=True)

    from teaparty_app.services.agent_tools import evaluate_job_resolved_todos
    evaluate_job_resolved_todos(session, conversation.id)

    memory_note = ""
    try:
        from teaparty_app.services.agent_learning import synthesize_long_term_memories

        memory_counts = synthesize_long_term_memories(session, conversation)
        total = sum(memory_counts.values())
        if total:
            memory_note = f" Synthesized {total} memories for {len(memory_counts)} agent(s)."
    except Exception:
        pass

    return f"Archived job '{conversation.topic}' (id={conversation.id}).{memory_note}"


def admin_tool_unarchive_job(
    session: Session,
    workgroup_id: str,
    requester_user_id: str,
    selector: str,
) -> str:
    if not _has_role(session, workgroup_id, requester_user_id, min_role="editor"):
        return "Editor permissions required to unarchive jobs."
    conversation, error = _resolve_job_conversation(session, workgroup_id, selector)
    if not conversation:
        return error or "Job not found."

    if not conversation.is_archived:
        return f"Job '{conversation.topic}' is already active."

    conversation.is_archived = False
    conversation.archived_at = None
    session.add(conversation)
    return f"Unarchived job '{conversation.topic}' (id={conversation.id})."


def admin_tool_remove_job(
    session: Session,
    workgroup_id: str,
    requester_user_id: str,
    selector: str,
) -> str:
    if not _has_role(session, workgroup_id, requester_user_id, min_role="owner"):
        return "Owner permissions required to remove jobs."

    conversation, error = _resolve_job_conversation(session, workgroup_id, selector)
    if not conversation:
        return error or "Job not found."

    # Remove worktree and delete branch before deleting the conversation
    try:
        from teaparty_app.services.workspace_manager import remove_worktree, workspace_root_configured

        if workspace_root_configured():
            from teaparty_app.models import Workspace, WorkspaceWorktree

            ws = session.exec(
                select(Workspace).where(Workspace.workgroup_id == workgroup_id, Workspace.status == "active")
            ).first()
            if ws:
                wt = session.exec(
                    select(WorkspaceWorktree).where(
                        WorkspaceWorktree.workspace_id == ws.id,
                        WorkspaceWorktree.conversation_id == conversation.id,
                        WorkspaceWorktree.status == "active",
                    )
                ).first()
                if wt:
                    remove_worktree(session, wt, delete_branch=True)
    except Exception:
        import logging

        logging.getLogger(__name__).warning("Failed to remove worktree on delete for %s", conversation.id, exc_info=True)

    counts = _delete_conversation_tree(session, conversation.id)
    return (
        f"Removed job '{conversation.topic}' (id={conversation.id}). "
        f"Deleted conversations={counts['conversations']}, messages={counts['messages']}."
    )


def admin_tool_clear_job_messages(
    session: Session,
    workgroup_id: str,
    requester_user_id: str,
    selector: str,
) -> str:
    if not _has_role(session, workgroup_id, requester_user_id, min_role="owner"):
        return "Owner permissions required to clear job messages."

    conversation, error = _resolve_job_conversation(session, workgroup_id, selector)
    if not conversation:
        return error or "Job not found."

    counts = clear_conversation_messages(session, conversation.id)
    if counts["messages"] == 0:
        return f"Job '{conversation.topic}' has no messages to clear."

    return (
        f"Cleared messages for job '{conversation.topic}' (id={conversation.id}). "
        f"Deleted messages={counts['messages']}."
    )


def admin_tool_list_jobs(
    session: Session,
    workgroup_id: str,
    status: str = "open",
) -> str:
    normalized_status, error = _normalize_list_jobs_status(status)
    if error:
        return f"Usage: list jobs <open|archived|both>. {error}"

    query = select(Conversation).where(
        Conversation.workgroup_id == workgroup_id,
        Conversation.kind == "job",
    )
    if normalized_status == "open":
        query = query.where(Conversation.is_archived == False)  # noqa: E712
    elif normalized_status == "archived":
        query = query.where(Conversation.is_archived == True)  # noqa: E712

    jobs = session.exec(
        query.order_by(
            func.lower(func.coalesce(Conversation.name, Conversation.topic)).asc(),
            Conversation.created_at.asc(),
        )
    ).all()
    if not jobs:
        if normalized_status == "both":
            return "No job conversations found."
        return f"No {normalized_status} job conversations found."

    lines = [f"Jobs ({normalized_status}, count={len(jobs)}):"]
    for job in jobs:
        job_status = "archived" if job.is_archived else "open"
        title = (job.name or job.topic).strip() or job.topic
        description = (job.description or "").strip()
        if description:
            lines.append(f"- [{job_status}] {title} (id={job.id}) :: {description}")
        else:
            lines.append(f"- [{job_status}] {title} (id={job.id})")
    return "\n".join(lines)


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


def admin_tool_list_files(
    session: Session,
    workgroup_id: str,
) -> str:
    workgroup = session.get(Workgroup, workgroup_id)
    if not workgroup:
        return "Workgroup not found."

    files = _normalize_workgroup_files_for_tool(workgroup)
    if not files:
        return "No files in this workgroup."

    lines = [f"Files (count={len(files)}):"]
    for file_entry in sorted(files, key=lambda item: item["path"].lower()):
        kind = "link" if file_entry["path"].lower().startswith(("http://", "https://")) else "file"
        lines.append(f"- [{kind}] {file_entry['path']} (id={file_entry['id']})")
    return "\n".join(lines)


def admin_tool_add_file(
    session: Session,
    workgroup_id: str,
    requester_user_id: str,
    path: str,
    content: str = "",
) -> str:
    if not _has_role(session, workgroup_id, requester_user_id, min_role="editor"):
        return "Editor permissions required to add files."

    normalized_path = _normalize_file_path(path)
    if not normalized_path:
        return "Usage: add file <path> [content=<text>]"
    if len(normalized_path) > 512:
        return "File path must be 512 characters or fewer."

    normalized_content, content_error = _normalize_file_content(content)
    if content_error:
        return content_error

    workgroup = session.get(Workgroup, workgroup_id)
    if not workgroup:
        return "Workgroup not found."

    files = _normalize_workgroup_files_for_tool(workgroup)
    for file_entry in files:
        if file_entry["path"] == normalized_path:
            return f"File '{normalized_path}' already exists (id={file_entry['id']})."

    created = {"id": str(uuid4()), "path": normalized_path, "content": normalized_content}
    files.append(created)
    workgroup.files = files
    session.add(workgroup)
    post_file_change_activity(session, workgroup_id, "file_added", normalized_path, actor_user_id=requester_user_id)
    return f"Added file '{normalized_path}' (id={created['id']})."


def admin_tool_edit_file(
    session: Session,
    workgroup_id: str,
    requester_user_id: str,
    path: str,
    content: str,
) -> str:
    if not _has_role(session, workgroup_id, requester_user_id, min_role="editor"):
        return "Editor permissions required to edit files."

    normalized_path = _normalize_file_path(path)
    if not normalized_path:
        return "Usage: edit file <path> content=<text>"
    if len(normalized_path) > 512:
        return "File path must be 512 characters or fewer."

    normalized_content, content_error = _normalize_file_content(content)
    if content_error:
        return content_error

    workgroup = session.get(Workgroup, workgroup_id)
    if not workgroup:
        return "Workgroup not found."

    files = _normalize_workgroup_files_for_tool(workgroup)
    for file_entry in files:
        if file_entry["path"] != normalized_path:
            continue
        if file_entry["content"] == normalized_content:
            return f"File '{normalized_path}' is unchanged."
        file_entry["content"] = normalized_content
        workgroup.files = files
        session.add(workgroup)
        post_file_change_activity(session, workgroup_id, "file_updated", normalized_path, actor_user_id=requester_user_id)
        return f"Updated file '{normalized_path}' (id={file_entry['id']})."

    return f"File '{normalized_path}' was not found."


def admin_tool_rename_file(
    session: Session,
    workgroup_id: str,
    requester_user_id: str,
    source_path: str,
    destination_path: str,
) -> str:
    if not _has_role(session, workgroup_id, requester_user_id, min_role="editor"):
        return "Editor permissions required to rename files."

    old_path = _normalize_file_path(source_path)
    new_path = _normalize_file_path(destination_path)
    if not old_path or not new_path:
        return "Usage: rename file <path> to <new-path>"
    if len(old_path) > 512 or len(new_path) > 512:
        return "File path must be 512 characters or fewer."
    if old_path == new_path:
        return f"File path is already '{old_path}'."

    workgroup = session.get(Workgroup, workgroup_id)
    if not workgroup:
        return "Workgroup not found."

    files = _normalize_workgroup_files_for_tool(workgroup)
    source_entry: dict[str, str] | None = None
    for file_entry in files:
        if file_entry["path"] == new_path:
            return f"File '{new_path}' already exists."
        if file_entry["path"] == old_path:
            source_entry = file_entry

    if not source_entry:
        return f"File '{old_path}' was not found."

    source_entry["path"] = new_path
    workgroup.files = files
    session.add(workgroup)
    post_file_change_activity(session, workgroup_id, "file_renamed", f"{old_path} -> {new_path}", actor_user_id=requester_user_id)
    return f"Renamed file '{old_path}' to '{new_path}' (id={source_entry['id']})."


def admin_tool_delete_file(
    session: Session,
    workgroup_id: str,
    requester_user_id: str,
    path: str,
) -> str:
    if not _has_role(session, workgroup_id, requester_user_id, min_role="editor"):
        return "Editor permissions required to delete files."

    normalized_path = _normalize_file_path(path)
    if not normalized_path:
        return "Usage: delete file <path>"
    if len(normalized_path) > 512:
        return "File path must be 512 characters or fewer."

    workgroup = session.get(Workgroup, workgroup_id)
    if not workgroup:
        return "Workgroup not found."

    files = _normalize_workgroup_files_for_tool(workgroup)
    kept: list[dict[str, str]] = []
    removed: dict[str, str] | None = None
    for file_entry in files:
        if removed is None and file_entry["path"] == normalized_path:
            removed = file_entry
            continue
        kept.append(file_entry)

    if not removed:
        return f"File '{normalized_path}' was not found."

    workgroup.files = kept
    session.add(workgroup)
    post_file_change_activity(session, workgroup_id, "file_deleted", normalized_path, actor_user_id=requester_user_id)
    return f"Deleted file '{normalized_path}' (id={removed['id']})."


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
        and (not model.strip() or model.strip() == "claude-sonnet-4-5")
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
    model_name = model.strip() or "claude-sonnet-4-5"
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
        follow_up_minutes=60,
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
            "followup_tasks": 0,
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

        task_rows = session.exec(
            select(AgentFollowUpTask)
            .join(Conversation, AgentFollowUpTask.conversation_id == Conversation.id)
            .where(
                Conversation.workgroup_id == workgroup_id,
                AgentFollowUpTask.waiting_on_user_id == user.id,
            )
        ).all()
        for row in task_rows:
            session.delete(row)
        counts["followup_tasks"] += len(task_rows)

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

    counts = {
        "conversations": 0,
        "participants": 0,
        "messages": 0,
        "learning_events": 0,
        "followup_tasks": 0,
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

    task_rows = session.exec(
        select(AgentFollowUpTask)
        .join(Conversation, AgentFollowUpTask.conversation_id == Conversation.id)
        .where(
            Conversation.workgroup_id == workgroup_id,
            or_(
                AgentFollowUpTask.agent_id == agent.id,
                AgentFollowUpTask.waiting_on_agent_id == agent.id,
            ),
        )
    ).all()
    for row in task_rows:
        session.delete(row)
    counts["followup_tasks"] += len(task_rows)

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


def _resolve_cross_group_task(
    session: Session,
    workgroup_id: str,
    selector: str,
) -> tuple[CrossGroupTask | None, str | None]:
    normalized = _normalize_task_selector(selector)
    if not normalized:
        return None, "Task selector is empty."

    # Try by ID first
    by_id = session.get(CrossGroupTask, normalized)
    if by_id and (
        by_id.source_workgroup_id == workgroup_id
        or by_id.target_workgroup_id == workgroup_id
    ):
        return by_id, None

    # Try by title
    rows = session.exec(
        select(CrossGroupTask).where(
            or_(
                CrossGroupTask.source_workgroup_id == workgroup_id,
                CrossGroupTask.target_workgroup_id == workgroup_id,
            ),
            func.lower(CrossGroupTask.title) == normalized.lower(),
        )
    ).all()
    if not rows:
        return None, f"Task '{normalized}' was not found."
    if len(rows) > 1:
        ids = ", ".join(row.id for row in rows)
        return None, f"Multiple tasks named '{normalized}'. Use task id. Matching ids: {ids}"
    return rows[0], None


def admin_tool_list_tasks(
    session: Session,
    workgroup_id: str,
    direction: str = "all",
) -> str:
    normalized = (direction or "all").strip().lower()
    if normalized not in ("incoming", "outgoing", "all"):
        return "Usage: list tasks [incoming|outgoing|all]"

    query = select(CrossGroupTask)
    if normalized == "incoming":
        query = query.where(CrossGroupTask.target_workgroup_id == workgroup_id)
    elif normalized == "outgoing":
        query = query.where(CrossGroupTask.source_workgroup_id == workgroup_id)
    else:
        query = query.where(
            or_(
                CrossGroupTask.source_workgroup_id == workgroup_id,
                CrossGroupTask.target_workgroup_id == workgroup_id,
            )
        )

    tasks = session.exec(query.order_by(CrossGroupTask.created_at.desc())).all()
    if not tasks:
        return f"No {normalized} cross-group tasks found."

    lines = [f"Cross-group tasks ({normalized}, count={len(tasks)}):"]
    for task in tasks:
        direction_label = (
            "incoming"
            if task.target_workgroup_id == workgroup_id
            else "outgoing"
        )
        source_wg = session.get(Workgroup, task.source_workgroup_id)
        target_wg = session.get(Workgroup, task.target_workgroup_id)
        source_name = source_wg.name if source_wg else task.source_workgroup_id
        target_name = target_wg.name if target_wg else task.target_workgroup_id
        lines.append(
            f"- [{direction_label}] [{task.status}] {task.title} "
            f"(id={task.id}, from={source_name}, to={target_name})"
        )
    return "\n".join(lines)


def admin_tool_accept_task(
    session: Session,
    workgroup_id: str,
    requester_user_id: str,
    selector: str,
) -> str:
    if not _has_role(session, workgroup_id, requester_user_id, min_role="owner"):
        return "Owner permissions required to accept tasks."

    task, error = _resolve_cross_group_task(session, workgroup_id, selector)
    if not task:
        return error or "Task not found."

    if task.target_workgroup_id != workgroup_id:
        return "You can only accept tasks directed to your workgroup."

    if task.status not in ("requested", "negotiating"):
        return f"Cannot accept task in status '{task.status}'."

    now = utc_now()
    task.status = "accepted"
    task.accepted_at = now

    target_conversation = Conversation(
        workgroup_id=task.target_workgroup_id,
        created_by_user_id=requester_user_id,
        kind="job",
        topic=f"task:{task.id}",
        name=task.title,
        description=f"Cross-group task. Scope: {task.scope}",
        is_archived=False,
    )
    session.add(target_conversation)
    session.flush()
    session.add(
        ConversationParticipant(
            conversation_id=target_conversation.id,
            user_id=requester_user_id,
        )
    )

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

    summary = (
        f"Task accepted: {task.title}\n"
        f"Scope: {task.scope}\n"
        f"Requirements: {task.requirements}\n"
        f"Terms: {task.terms or '(none)'}"
    )
    session.add(
        Message(
            conversation_id=target_conversation.id,
            sender_type="system",
            content=f"[Cross-group task started] {summary}",
            requires_response=False,
        )
    )
    session.add(
        Message(
            conversation_id=source_conversation.id,
            sender_type="system",
            content=f"[Cross-group task accepted] {summary}",
            requires_response=False,
        )
    )

    task.status = "in_progress"
    session.add(task)
    return f"Accepted task '{task.title}' (id={task.id}). Work job and mirror job created."


def admin_tool_decline_task(
    session: Session,
    workgroup_id: str,
    requester_user_id: str,
    selector: str,
) -> str:
    if not _has_role(session, workgroup_id, requester_user_id, min_role="owner"):
        return "Owner permissions required to decline tasks."

    task, error = _resolve_cross_group_task(session, workgroup_id, selector)
    if not task:
        return error or "Task not found."

    if task.target_workgroup_id != workgroup_id:
        return "You can only decline tasks directed to your workgroup."

    if task.status not in ("requested", "negotiating"):
        return f"Cannot decline task in status '{task.status}'."

    task.status = "declined"
    task.declined_at = utc_now()
    session.add(task)
    return f"Declined task '{task.title}' (id={task.id})."


def admin_tool_complete_task(
    session: Session,
    workgroup_id: str,
    requester_user_id: str,
    selector: str,
) -> str:
    task, error = _resolve_cross_group_task(session, workgroup_id, selector)
    if not task:
        return error or "Task not found."

    if task.target_workgroup_id != workgroup_id:
        return "You can only complete tasks directed to your workgroup."

    if task.status != "in_progress":
        return f"Cannot complete task in status '{task.status}'."

    task.status = "completed"
    task.completed_at = utc_now()
    session.add(task)

    summary = "Task marked as completed."
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

    return f"Completed task '{task.title}' (id={task.id})."
