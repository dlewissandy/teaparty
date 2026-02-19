"""File CRUD admin tools."""

from __future__ import annotations

from uuid import uuid4

from sqlmodel import Session

from teaparty_app.models import Workgroup
from teaparty_app.services.activity import post_file_change_activity
from teaparty_app.services.admin_workspace.parsing import (
    _normalize_file_content,
    _normalize_file_path,
    _normalize_workgroup_files_for_tool,
)
from teaparty_app.services.admin_workspace.tools_common import _has_role


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
