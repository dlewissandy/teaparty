"""REST API for git workspace operations."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session, select

from teaparty_app.db import get_session
from teaparty_app.deps import get_current_user
from teaparty_app.models import User, Workspace, WorkspaceWorktree
from teaparty_app.schemas import (
    WorkspaceGitLogEntry,
    WorkspaceGitLogRead,
    WorkspaceMergeRequest,
    WorkspaceMergeResult,
    WorkspaceRead,
    WorkspaceStatusRead,
    WorkspaceSyncRequest,
    WorkspaceSyncResult,
    WorkspaceWorktreeRead,
)
from teaparty_app.services.permissions import require_workgroup_editor, require_workgroup_owner

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["workspace"])


def _get_active_workspace(session: Session, workgroup_id: str) -> Workspace:
    workspace = session.exec(
        select(Workspace).where(
            Workspace.workgroup_id == workgroup_id,
            Workspace.status == "active",
        )
    ).first()
    if not workspace:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found")
    return workspace


@router.post("/workgroups/{workgroup_id}/workspace", response_model=WorkspaceRead)
def init_workspace_endpoint(
    workgroup_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkspaceRead:
    require_workgroup_owner(session, workgroup_id, user.id)

    from teaparty_app.services.workspace_manager import GitError, init_workspace, workspace_root_configured

    if not workspace_root_configured():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="workspace_root is not configured on the server",
        )

    try:
        workspace = init_workspace(session, workgroup_id)
        session.commit()
        session.refresh(workspace)
        return WorkspaceRead.model_validate(workspace)
    except GitError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))


@router.get("/workgroups/{workgroup_id}/workspace", response_model=WorkspaceStatusRead)
def get_workspace_status(
    workgroup_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkspaceStatusRead:
    require_workgroup_editor(session, workgroup_id, user.id)
    workspace = _get_active_workspace(session, workgroup_id)

    worktrees = session.exec(
        select(WorkspaceWorktree).where(
            WorkspaceWorktree.workspace_id == workspace.id,
            WorkspaceWorktree.status == "active",
        )
    ).all()

    return WorkspaceStatusRead(
        workspace=WorkspaceRead.model_validate(workspace),
        worktrees=[WorkspaceWorktreeRead.model_validate(wt) for wt in worktrees],
    )


@router.delete("/workgroups/{workgroup_id}/workspace", status_code=204)
def destroy_workspace_endpoint(
    workgroup_id: str,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> None:
    require_workgroup_owner(session, workgroup_id, user.id)
    workspace = _get_active_workspace(session, workgroup_id)

    from teaparty_app.services.workspace_manager import destroy_workspace

    destroy_workspace(session, workspace)
    session.commit()


@router.post("/workgroups/{workgroup_id}/workspace/sync", response_model=WorkspaceSyncResult)
def sync_workspace(
    workgroup_id: str,
    payload: WorkspaceSyncRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkspaceSyncResult:
    require_workgroup_editor(session, workgroup_id, user.id)
    workspace = _get_active_workspace(session, workgroup_id)

    from teaparty_app.services.workspace_sync import sync_db_to_filesystem, sync_filesystem_to_db

    if payload.direction == "db_to_fs":
        result = sync_db_to_filesystem(session, workspace, payload.conversation_id)
    else:
        result = sync_filesystem_to_db(session, workspace, payload.conversation_id)

    session.commit()
    return WorkspaceSyncResult(**result)


@router.post("/workgroups/{workgroup_id}/workspace/merge", response_model=WorkspaceMergeResult)
def merge_workspace(
    workgroup_id: str,
    payload: WorkspaceMergeRequest,
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkspaceMergeResult:
    require_workgroup_editor(session, workgroup_id, user.id)
    workspace = _get_active_workspace(session, workgroup_id)

    worktree = session.exec(
        select(WorkspaceWorktree).where(
            WorkspaceWorktree.workspace_id == workspace.id,
            WorkspaceWorktree.conversation_id == payload.conversation_id,
            WorkspaceWorktree.status == "active",
        )
    ).first()
    if not worktree:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worktree not found for this conversation")

    from teaparty_app.services.workspace_manager import merge_job_to_main

    result = merge_job_to_main(session, workspace, worktree)
    session.commit()
    return WorkspaceMergeResult(
        merged=result["merged"],
        branch_name=result.get("branch", ""),
        conflicts=result.get("conflicts", []),
    )


@router.get("/workgroups/{workgroup_id}/workspace/log", response_model=WorkspaceGitLogRead)
def get_workspace_log(
    workgroup_id: str,
    branch: str = Query(default="main"),
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
    user: User = Depends(get_current_user),
) -> WorkspaceGitLogRead:
    require_workgroup_editor(session, workgroup_id, user.id)
    workspace = _get_active_workspace(session, workgroup_id)

    from teaparty_app.services.workspace_manager import get_git_log

    entries = get_git_log(workspace, branch=branch, limit=limit)
    return WorkspaceGitLogRead(
        branch=branch,
        entries=[WorkspaceGitLogEntry(**e) for e in entries],
    )
