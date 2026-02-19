"""Cross-group task admin tools."""

from __future__ import annotations

from sqlalchemy import func, or_
from sqlmodel import Session, select

from teaparty_app.models import (
    Conversation,
    ConversationParticipant,
    CrossGroupTask,
    Message,
    Workgroup,
    utc_now,
)
from teaparty_app.services.admin_workspace.parsing import (
    _normalize_task_selector,
)
from teaparty_app.services.admin_workspace.tools_common import _has_role


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
