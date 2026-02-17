"""Todo signal evaluation and materialization helpers.

Extracted from the former agent_tools.py. These functions evaluate
signal-based triggers on AgentTodoItem rows and materialize the
todo list as a virtual file in workgroup.files.
"""

from __future__ import annotations

import logging
from uuid import uuid4

from sqlmodel import Session, select

from teaparty_app.models import (
    Agent,
    AgentTodoItem,
    Conversation,
    Message,
    Workspace,
    WorkspaceWorktree,
    Workgroup,
    utc_now,
)
from teaparty_app.services.file_helpers import _normalize_workgroup_files

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Todo materialization
# ---------------------------------------------------------------------------


def _materialize_todo_file(
    session: Session,
    agent: Agent,
    workgroup_id: str,
) -> None:
    """Write/update the _todos/{agent_name}.md file in workgroup.files."""
    workgroup = session.get(Workgroup, workgroup_id)
    if not workgroup:
        return

    todos = session.exec(
        select(AgentTodoItem).where(
            AgentTodoItem.agent_id == agent.id,
            AgentTodoItem.workgroup_id == workgroup_id,
        ).order_by(AgentTodoItem.created_at.asc())
    ).all()

    # Build markdown
    pending = [t for t in todos if t.status == "pending"]
    in_progress = [t for t in todos if t.status == "in_progress"]
    done = [t for t in todos if t.status == "done"]

    lines = [f"# Todos -- {agent.name}", ""]

    if pending:
        lines.append("## Pending")
        for t in pending:
            trigger_desc = ""
            if t.trigger_type != "manual":
                trigger_desc = f" · Trigger: {t.trigger_type}"
                if t.trigger_type == "time" and t.due_at:
                    trigger_desc += f" (due: {t.due_at.strftime('%b %d %H:%M')})"
                elif t.trigger_type == "message_match":
                    kw = (t.trigger_config or {}).get("keywords", [])
                    trigger_desc += f" ({', '.join(kw[:3])})"
                elif t.trigger_type == "file_changed":
                    trigger_desc += f" ({(t.trigger_config or {}).get('file_path', '')})"
                elif t.trigger_type == "job_stall":
                    trigger_desc += f" ({(t.trigger_config or {}).get('stall_minutes', 30)}min)"
            lines.append(
                f"- **[{t.priority.upper()}]** {t.title}"
                f"{trigger_desc} · Created: {t.created_at.strftime('%b %d')}"
            )
        lines.append("")

    if in_progress:
        lines.append("## In Progress")
        for t in in_progress:
            started = t.updated_at.strftime("%b %d") if t.updated_at else t.created_at.strftime("%b %d")
            lines.append(f"- **[{t.priority.upper()}]** {t.title} · Started: {started}")
        lines.append("")

    if done:
        recent_done = sorted(done, key=lambda x: x.completed_at or x.created_at, reverse=True)[:5]
        lines.append("## Recently Done")
        for t in recent_done:
            completed = t.completed_at.strftime("%b %d") if t.completed_at else "?"
            lines.append(f"- ~~**[{t.priority.upper()}]** {t.title}~~ · Completed: {completed}")
        lines.append("")

    content = "\n".join(lines)
    file_path = f"_todos/{agent.name}.md"

    all_files = _normalize_workgroup_files(workgroup)
    existing = None
    for entry in all_files:
        if entry["path"] == file_path:
            existing = entry
            break

    if existing:
        existing["content"] = content
    else:
        all_files.append({
            "id": str(uuid4()),
            "path": file_path,
            "content": content,
            "topic_id": "",
        })

    workgroup.files = all_files
    session.add(workgroup)


# ---------------------------------------------------------------------------
# Signal evaluation functions
# ---------------------------------------------------------------------------


def evaluate_message_match_todos(session: Session, message: Message) -> None:
    """Check pending message_match todos against a new message's content."""
    conversation = session.get(Conversation, message.conversation_id)
    if not conversation:
        return

    todos = session.exec(
        select(AgentTodoItem).where(
            AgentTodoItem.trigger_type == "message_match",
            AgentTodoItem.status == "pending",
            AgentTodoItem.triggered_at.is_(None),
            AgentTodoItem.workgroup_id == conversation.workgroup_id,
        )
    ).all()

    if not todos:
        return

    content_lower = message.content.lower()
    now = utc_now()
    for todo in todos:
        if todo.conversation_id and todo.conversation_id != message.conversation_id:
            continue
        keywords = (todo.trigger_config or {}).get("keywords", [])
        if any(kw.lower() in content_lower for kw in keywords):
            todo.triggered_at = now
            todo.updated_at = now
            session.add(todo)


def evaluate_file_changed_todos(
    session: Session,
    workgroup_id: str,
    file_path: str,
) -> None:
    """Check pending file_changed todos when a file is added/updated/deleted."""
    todos = session.exec(
        select(AgentTodoItem).where(
            AgentTodoItem.trigger_type == "file_changed",
            AgentTodoItem.status == "pending",
            AgentTodoItem.triggered_at.is_(None),
            AgentTodoItem.workgroup_id == workgroup_id,
        )
    ).all()

    now = utc_now()
    for todo in todos:
        watched = (todo.trigger_config or {}).get("file_path", "")
        if watched and watched == file_path:
            todo.triggered_at = now
            todo.updated_at = now
            session.add(todo)


def evaluate_job_resolved_todos(session: Session, conversation_id: str) -> None:
    """Check pending job_resolved todos when a conversation is archived."""
    todos = session.exec(
        select(AgentTodoItem).where(
            AgentTodoItem.trigger_type == "job_resolved",
            AgentTodoItem.status == "pending",
            AgentTodoItem.triggered_at.is_(None),
            AgentTodoItem.conversation_id == conversation_id,
        )
    ).all()

    now = utc_now()
    for todo in todos:
        todo.triggered_at = now
        todo.updated_at = now
        session.add(todo)


# ---------------------------------------------------------------------------
# Worktree resolution (used by agent_runtime.py)
# ---------------------------------------------------------------------------


def _resolve_worktree(
    session: Session, conversation: Conversation,
) -> tuple[str | None, str | None]:
    """Return (worktree_path, None) or (None, error_message)."""
    workspace = session.exec(
        select(Workspace).where(
            Workspace.workgroup_id == conversation.workgroup_id,
            Workspace.status == "active",
        )
    ).first()
    if not workspace:
        return None, "No workspace configured for this workgroup."

    worktree = session.exec(
        select(WorkspaceWorktree).where(
            WorkspaceWorktree.workspace_id == workspace.id,
            WorkspaceWorktree.conversation_id == conversation.id,
            WorkspaceWorktree.status == "active",
        )
    ).first()
    if not worktree:
        return None, "No worktree for this conversation. A workspace admin needs to create one."

    return worktree.worktree_path, None
