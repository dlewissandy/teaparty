"""Job lifecycle admin tools."""

from __future__ import annotations

from sqlalchemy import func, or_
from sqlmodel import Session, select

from teaparty_app.models import (
    Conversation,
    ConversationParticipant,
    Workgroup,
    utc_now,
)
from teaparty_app.services.admin_workspace.parsing import (
    _normalize_job_selector,
    _normalize_list_jobs_status,
)
from teaparty_app.services.admin_workspace.tools_common import (
    _delete_conversation_tree,
    _has_role,
    clear_conversation_messages,
)


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
        from teaparty_app.services.workflow_helpers import auto_select_workflow

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

    from teaparty_app.services.todo_helpers import evaluate_job_resolved_todos
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
