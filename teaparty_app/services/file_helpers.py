"""Workgroup file helpers — normalize, scope, and query virtual files."""

from __future__ import annotations

from uuid import uuid4

from sqlmodel import Session, select

from teaparty_app.models import Conversation, Engagement, Job, Workgroup


def _normalize_files(raw_files: list | None) -> list[dict[str, str]]:
    """Normalize a raw file list into clean dicts. Works for any entity's files."""
    if not isinstance(raw_files, list):
        return []
    normalized: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for raw in raw_files:
        file_id = ""
        path = ""
        content = ""
        topic_id = ""

        if isinstance(raw, str):
            path = raw.strip()
        elif isinstance(raw, dict):
            file_id = str(raw.get("id") or "").strip()
            path = str(raw.get("path") or "").strip()
            raw_content = raw.get("content", "")
            content = raw_content if isinstance(raw_content, str) else str(raw_content or "")
            topic_id = str(raw.get("topic_id", "")).strip()
        else:
            continue

        if not path or path in seen_paths:
            continue
        if len(path) > 512 or len(content) > 200000:
            continue
        normalized.append({"id": file_id or str(uuid4()), "path": path, "content": content, "topic_id": topic_id})
        seen_paths.add(path)
    return normalized


def _normalize_workgroup_files(workgroup: Workgroup) -> list[dict[str, str]]:
    return _normalize_files(workgroup.files)


def _normalize_entity_files(raw_files: list | None) -> list[dict[str, str]]:
    """Normalize files for Job/Engagement (no topic_id)."""
    if not isinstance(raw_files, list):
        return []
    normalized: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for raw in raw_files:
        if not isinstance(raw, dict):
            continue
        file_id = str(raw.get("id") or "").strip()
        path = str(raw.get("path") or "").strip()
        raw_content = raw.get("content", "")
        content = raw_content if isinstance(raw_content, str) else str(raw_content or "")

        if not path or path in seen_paths:
            continue
        if len(path) > 512 or len(content) > 200000:
            continue
        normalized.append({"id": file_id or str(uuid4()), "path": path, "content": content})
        seen_paths.add(path)
    return normalized


def _topic_id_for_conversation(conversation: Conversation) -> str:
    """Return the topic_id scope for files in this conversation.

    - Job conversations: scoped by conversation.id (for workflow state files on workgroup)
    - Task conversations: scoped by conversation.id
    - Agent DMs (topic "dma:..."): scoped by "agent:{agent_id}"
    - User DMs (topic "dm:..."): scoped by the topic itself (unique per pair)
    - Everything else: empty string (shared files only)
    """
    if conversation.kind == "task":
        return conversation.id
    if conversation.kind == "job":
        return conversation.id
    if conversation.kind == "direct" and conversation.topic:
        if conversation.topic.startswith("dma:"):
            parts = conversation.topic.split(":")
            if len(parts) >= 3:
                return f"agent:{parts[2]}"
        if conversation.topic.startswith("dm:"):
            return conversation.topic
    return ""


def _find_job_for_conversation(session: Session, conversation: Conversation) -> Job | None:
    """Find the Job that owns this conversation, if any."""
    if conversation.kind != "job":
        return None
    return session.exec(
        select(Job).where(Job.conversation_id == conversation.id)
    ).first()


def _find_engagement_for_conversation(session: Session, conversation: Conversation) -> Engagement | None:
    """Find the Engagement that owns this conversation, if any."""
    if conversation.kind != "engagement":
        return None
    from sqlalchemy import or_
    return session.exec(
        select(Engagement).where(
            or_(
                Engagement.source_conversation_id == conversation.id,
                Engagement.target_conversation_id == conversation.id,
            )
        )
    ).first()


def _shared_workgroup_files(workgroup: Workgroup) -> list[dict[str, str]]:
    """Return workgroup files that are NOT scoped to any topic (shared/team files)."""
    all_files = _normalize_workgroup_files(workgroup)
    return [f for f in all_files if not f.get("topic_id")]


def _files_for_conversation(
    workgroup: Workgroup,
    conversation: Conversation,
    session: Session | None = None,
) -> list[dict[str, str]]:
    """Return the files visible for a conversation.

    For job conversations with a session:
        Job.files (writable) + workgroup files visible to this conversation (includes shared + topic-scoped)
    For engagement conversations with a session:
        Engagement.files (writable) + shared workgroup files (read-only)
    For other conversations:
        workgroup files scoped by topic_id (legacy behavior)
    """
    # Job conversations → entity files + workgroup-scoped files
    if session and conversation.kind == "job":
        job = _find_job_for_conversation(session, conversation)
        if job:
            job_files = _normalize_entity_files(job.files)
            # Include workgroup files visible to this conversation (shared + topic-scoped)
            all_wg_files = _normalize_workgroup_files(workgroup)
            scope_id = _topic_id_for_conversation(conversation)
            wg_files = [f for f in all_wg_files if not f.get("topic_id") or f["topic_id"] == scope_id]
            # Merge: job files first, then workgroup files (skip path conflicts)
            seen_paths = {f["path"] for f in job_files}
            for f in wg_files:
                if f["path"] not in seen_paths:
                    job_files.append(f)
                    seen_paths.add(f["path"])
            return job_files

    # Engagement conversations → entity files + shared workgroup files
    if session and conversation.kind == "engagement":
        engagement = _find_engagement_for_conversation(session, conversation)
        if engagement:
            eng_files = _normalize_entity_files(engagement.files)
            shared = _shared_workgroup_files(workgroup)
            seen_paths = {f["path"] for f in eng_files}
            for f in shared:
                if f["path"] not in seen_paths:
                    eng_files.append(f)
                    seen_paths.add(f["path"])
            return eng_files

    # Fallback: legacy workgroup-scoped file behavior
    all_files = _normalize_workgroup_files(workgroup)
    if conversation.kind == "admin":
        return all_files
    scope_id = _topic_id_for_conversation(conversation)
    if conversation.kind == "direct" and scope_id:
        return [f for f in all_files if f.get("topic_id") == scope_id]
    if scope_id:
        return [f for f in all_files if not f.get("topic_id") or f["topic_id"] == scope_id]
    return [f for f in all_files if not f.get("topic_id")]
