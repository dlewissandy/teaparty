"""Workgroup file helpers — normalize, scope, and query virtual files."""

from __future__ import annotations

from uuid import uuid4

from teaparty_app.models import Conversation, Workgroup


def _normalize_workgroup_files(workgroup: Workgroup) -> list[dict[str, str]]:
    raw_files = workgroup.files if isinstance(workgroup.files, list) else []
    normalized: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for raw in raw_files:
        file_id = ""
        path = ""
        content = ""

        if isinstance(raw, str):
            path = raw.strip()
        elif isinstance(raw, dict):
            file_id = str(raw.get("id") or "").strip()
            path = str(raw.get("path") or "").strip()
            raw_content = raw.get("content", "")
            content = raw_content if isinstance(raw_content, str) else str(raw_content or "")
        else:
            continue

        if not path or path in seen_paths:
            continue
        if len(path) > 512 or len(content) > 200000:
            continue
        topic_id = ""
        if isinstance(raw, dict):
            topic_id = str(raw.get("topic_id", "")).strip()
        normalized.append({"id": file_id or str(uuid4()), "path": path, "content": content, "topic_id": topic_id})
        seen_paths.add(path)
    return normalized


def _topic_id_for_conversation(conversation: Conversation) -> str:
    """Return the topic_id scope for files in this conversation.

    - Job conversations: scoped by conversation.id
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


def _files_for_conversation(workgroup: Workgroup, conversation: Conversation) -> list[dict[str, str]]:
    all_files = _normalize_workgroup_files(workgroup)
    if conversation.kind == "admin":
        return all_files
    scope_id = _topic_id_for_conversation(conversation)
    if conversation.kind == "direct" and scope_id:
        return [f for f in all_files if f.get("topic_id") == scope_id]
    if scope_id:
        return [f for f in all_files if not f.get("topic_id") or f["topic_id"] == scope_id]
    return [f for f in all_files if not f.get("topic_id")]
