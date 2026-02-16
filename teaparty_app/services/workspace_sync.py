"""Bidirectional file sync between the database (workgroup.files) and git worktrees."""

from __future__ import annotations

import logging
from uuid import uuid4

from sqlmodel import Session, select

from teaparty_app.models import Workspace, WorkspaceWorktree, Workgroup, utc_now
from teaparty_app.services.workspace_manager import (
    GitError,
    _get_lock,
    _read_files_from_worktree,
    _run_git,
    _write_files_to_worktree,
)

logger = logging.getLogger(__name__)


def sync_db_to_filesystem(
    session: Session, workspace: Workspace, conversation_id: str | None = None
) -> dict:
    """Write workgroup.files to the main worktree (or topic worktree), then commit."""
    workgroup = session.get(Workgroup, workspace.workgroup_id)
    if not workgroup:
        return {"direction": "db_to_fs", "files_written": 0, "committed": False}

    files = list(workgroup.files) if workgroup.files else []

    if conversation_id:
        worktree = session.exec(
            select(WorkspaceWorktree).where(
                WorkspaceWorktree.workspace_id == workspace.id,
                WorkspaceWorktree.conversation_id == conversation_id,
                WorkspaceWorktree.status == "active",
            )
        ).first()
        if not worktree:
            return {"direction": "db_to_fs", "files_written": 0, "committed": False}
        target_path = worktree.worktree_path
    else:
        target_path = workspace.main_worktree_path

    lock = _get_lock(workspace.workgroup_id)
    with lock:
        written = _write_files_to_worktree(target_path, files)

        committed = False
        try:
            _run_git(["add", "-A"], cwd=target_path)
            # Check if there are changes to commit
            result = _run_git(["status", "--porcelain"], cwd=target_path)
            if result.stdout.strip():
                _run_git(["commit", "-m", "Sync from database"], cwd=target_path)
                committed = True
        except GitError as exc:
            logger.warning("Failed to commit after db_to_fs sync: %s", exc)

        workspace.last_synced_at = utc_now()
        session.add(workspace)

    return {"direction": "db_to_fs", "files_written": written, "committed": committed}


def sync_filesystem_to_db(
    session: Session, workspace: Workspace, conversation_id: str | None = None
) -> dict:
    """Read tracked files from worktree and merge into workgroup.files."""
    workgroup = session.get(Workgroup, workspace.workgroup_id)
    if not workgroup:
        return {"direction": "fs_to_db", "files_read": 0, "committed": False}

    if conversation_id:
        worktree = session.exec(
            select(WorkspaceWorktree).where(
                WorkspaceWorktree.workspace_id == workspace.id,
                WorkspaceWorktree.conversation_id == conversation_id,
                WorkspaceWorktree.status == "active",
            )
        ).first()
        if not worktree:
            return {"direction": "fs_to_db", "files_read": 0, "committed": False}
        source_path = worktree.worktree_path
    else:
        source_path = workspace.main_worktree_path

    lock = _get_lock(workspace.workgroup_id)
    with lock:
        fs_files = _read_files_from_worktree(source_path)

    if not fs_files:
        return {"direction": "fs_to_db", "files_read": 0, "committed": False}

    # Merge into existing workgroup.files, preserving IDs for matching paths
    existing_files = list(workgroup.files) if workgroup.files else []
    existing_by_path: dict[str, dict] = {}
    for f in existing_files:
        if isinstance(f, dict) and f.get("path"):
            existing_by_path[f["path"]] = f

    merged: list[dict] = []
    seen_paths: set[str] = set()

    # First, add all files from the filesystem
    for fs_file in fs_files:
        path = fs_file["path"]
        if path in seen_paths:
            continue
        seen_paths.add(path)

        existing = existing_by_path.get(path)
        file_id = existing.get("id", str(uuid4())) if existing else str(uuid4())
        merged.append({
            "id": file_id,
            "path": path,
            "content": fs_file["content"],
        })

    # Keep DB-only files that aren't on the filesystem (e.g., URLs, files from other topics)
    for f in existing_files:
        if isinstance(f, dict) and f.get("path") and f["path"] not in seen_paths:
            merged.append(dict(f))
            seen_paths.add(f["path"])

    workgroup.files = merged
    workspace.last_synced_at = utc_now()
    session.add(workgroup)
    session.add(workspace)

    return {"direction": "fs_to_db", "files_read": len(fs_files), "committed": False}
