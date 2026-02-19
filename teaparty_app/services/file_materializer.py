"""Materialize virtual files to disk for agent invocations, then sync back."""

from __future__ import annotations

import contextlib
import logging
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from sqlmodel import Session, select

from teaparty_app.models import Conversation, Engagement, Job, Workspace, WorkspaceWorktree, Workgroup
from teaparty_app.services.activity import post_file_change_activity
from teaparty_app.services.agent_definition import build_worktree_settings_json
from teaparty_app.services.file_helpers import (
    _files_for_conversation,
    _find_engagement_for_conversation,
    _find_job_for_conversation,
    _normalize_entity_files,
    _normalize_workgroup_files,
    _shared_workgroup_files,
    _topic_id_for_conversation,
)
from teaparty_app.services.workspace_manager import (
    MAX_FILE_SIZE,
    MAX_FILES,
    _write_files_to_worktree,
)

logger = logging.getLogger(__name__)

SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", ".DS_Store", ".teaparty"}


@dataclass
class MaterializedContext:
    dir_path: str
    settings_json: str
    original_file_ids: dict[str, str] = field(default_factory=dict)  # {path: file_id}
    readonly_file_ids: dict[str, str] = field(default_factory=dict)  # {path: file_id} — skip during sync-back
    sync_target: str = "workgroup"  # "workgroup" | "job" | "engagement"
    sync_entity_id: str = ""


def read_files_from_directory(base: Path) -> list[dict]:
    """Walk a directory tree and read text files. No git required."""
    base = base.resolve()
    files: list[dict] = []

    for item in sorted(base.rglob("*")):
        if len(files) >= MAX_FILES:
            break

        # Skip anything inside a directory we want to ignore
        rel = item.relative_to(base)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue

        if not item.is_file():
            continue

        try:
            content = item.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue

        if len(content) > MAX_FILE_SIZE:
            content = content[:MAX_FILE_SIZE]

        files.append({"path": str(rel), "content": content})

    return files


def _sync_to_entity(
    session: Session,
    sync_target: str,
    sync_entity_id: str,
    dir_path: str,
    original_file_ids: dict[str, str],
    readonly_file_ids: dict[str, str],
) -> list[tuple[str, str]]:
    """Sync disk state back to the owning entity (Job or Engagement)."""
    disk_files = read_files_from_directory(Path(dir_path))
    disk_by_path = {f["path"]: f["content"] for f in disk_files}

    if sync_target == "job":
        entity = session.get(Job, sync_entity_id)
    elif sync_target == "engagement":
        entity = session.get(Engagement, sync_entity_id)
    else:
        return []

    if not entity:
        return []

    session.refresh(entity)
    all_files = _normalize_entity_files(entity.files)
    files_by_id: dict[str, dict] = {f["id"]: f for f in all_files}

    changes: list[tuple[str, str]] = []

    # Check originally-materialized writable files for updates and deletions
    for orig_path, orig_id in original_file_ids.items():
        if orig_path in readonly_file_ids:
            continue  # Skip read-only files

        if orig_path in disk_by_path:
            new_content = disk_by_path[orig_path]
            entry = files_by_id.get(orig_id)
            if entry and entry.get("content", "") != new_content:
                entry["content"] = new_content
                changes.append(("modified", orig_path))
        else:
            all_files = [f for f in all_files if f["id"] != orig_id]
            changes.append(("deleted", orig_path))

    # Check for new files on disk (excluding read-only paths)
    for path, content in disk_by_path.items():
        if path not in original_file_ids and path not in readonly_file_ids:
            all_files.append({
                "id": str(uuid4()),
                "path": path,
                "content": content,
            })
            changes.append(("created", path))

    if changes:
        entity.files = all_files
        session.add(entity)

    return changes


def sync_directory_to_files(
    session: Session,
    workgroup: Workgroup,
    conversation: Conversation,
    dir_path: str,
    original_file_ids: dict[str, str],
) -> list[tuple[str, str]]:
    """Sync disk state back to workgroup.files. Returns [(change_type, path), ...]."""
    disk_files = read_files_from_directory(Path(dir_path))
    disk_by_path = {f["path"]: f["content"] for f in disk_files}

    # Refresh to avoid overwriting concurrent changes
    session.refresh(workgroup)
    all_files = _normalize_workgroup_files(workgroup)
    files_by_id: dict[str, dict] = {f["id"]: f for f in all_files}

    changes: list[tuple[str, str]] = []

    # Check originally-materialized files for updates and deletions
    for orig_path, orig_id in original_file_ids.items():
        if orig_path in disk_by_path:
            # File still exists on disk -- check if modified
            new_content = disk_by_path[orig_path]
            entry = files_by_id.get(orig_id)
            if entry and entry.get("content", "") != new_content:
                entry["content"] = new_content
                changes.append(("modified", orig_path))
        else:
            # File deleted from disk
            all_files = [f for f in all_files if f["id"] != orig_id]
            changes.append(("deleted", orig_path))

    # Check for new files on disk
    for path, content in disk_by_path.items():
        if path not in original_file_ids:
            topic_id = _topic_id_for_conversation(conversation)
            all_files.append({
                "id": str(uuid4()),
                "path": path,
                "content": content,
                "topic_id": topic_id,
            })
            changes.append(("created", path))

    if changes:
        workgroup.files = all_files
        session.add(workgroup)

    return changes


@contextlib.contextmanager
def materialized_files(
    session: Session,
    workgroup: Workgroup,
    conversation: Conversation,
):
    """Materialize virtual files to disk, yield context, sync back, clean up."""
    dir_path: str | None = None
    is_temp = True

    # Check for an active worktree (workspace mode)
    if workgroup.workspace_enabled:
        worktree = session.exec(
            select(WorkspaceWorktree).join(Workspace).where(
                Workspace.workgroup_id == workgroup.id,
                WorkspaceWorktree.conversation_id == conversation.id,
                WorkspaceWorktree.status == "active",
            )
        ).first()
        if worktree:
            dir_path = worktree.worktree_path
            is_temp = False
            # Ensure worktree has latest files from DB
            from teaparty_app.services.workspace_manager import materialize_files_to_worktree
            materialize_files_to_worktree(
                workgroup.id, conversation, dir_path, session=session,
            )

    # Fallback: temp directory
    if dir_path is None:
        dir_path = tempfile.mkdtemp(prefix="teaparty_files_")
        conv_files = _files_for_conversation(workgroup, conversation, session=session)
        _write_files_to_worktree(dir_path, conv_files)

    # Build settings JSON with constrain hook
    settings_json = build_worktree_settings_json(dir_path)

    # Record original file IDs for sync-back
    conv_files = _files_for_conversation(workgroup, conversation, session=session)
    original_file_ids = {f["path"]: f["id"] for f in conv_files}

    # Determine sync target and readonly files
    sync_target = "workgroup"
    sync_entity_id = ""
    readonly_file_ids: dict[str, str] = {}

    job = _find_job_for_conversation(session, conversation)
    if job:
        sync_target = "job"
        sync_entity_id = job.id
        # Shared workgroup files are read-only for job conversations
        shared = _shared_workgroup_files(workgroup)
        readonly_file_ids = {f["path"]: f["id"] for f in shared}

    if not job:
        engagement = _find_engagement_for_conversation(session, conversation)
        if engagement:
            sync_target = "engagement"
            sync_entity_id = engagement.id
            shared = _shared_workgroup_files(workgroup)
            readonly_file_ids = {f["path"]: f["id"] for f in shared}

    ctx = MaterializedContext(
        dir_path=dir_path,
        settings_json=settings_json,
        original_file_ids=original_file_ids,
        readonly_file_ids=readonly_file_ids,
        sync_target=sync_target,
        sync_entity_id=sync_entity_id,
    )

    try:
        yield ctx
    finally:
        # Sync changes back to DB
        try:
            if sync_target in ("job", "engagement"):
                changes = _sync_to_entity(
                    session, sync_target, sync_entity_id,
                    dir_path, original_file_ids, readonly_file_ids,
                )
            else:
                changes = sync_directory_to_files(
                    session, workgroup, conversation, dir_path, original_file_ids,
                )
            for change_type, path in changes:
                event_map = {
                    "modified": "file_updated",
                    "created": "file_added",
                    "deleted": "file_deleted",
                }
                post_file_change_activity(
                    session,
                    workgroup.id,
                    event_map.get(change_type, "file_updated"),
                    path,
                )
        except Exception:
            logger.exception("Error syncing files back from %s", dir_path)

        # Clean up temp directory
        if is_temp and dir_path:
            try:
                shutil.rmtree(dir_path)
            except OSError:
                logger.warning("Failed to clean up temp dir: %s", dir_path)
