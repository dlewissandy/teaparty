"""Git workspace management: bare repos, worktrees, merge, file I/O."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from threading import Lock

from sqlmodel import Session, select

from teaparty_app.config import settings
from teaparty_app.models import Conversation, Workspace, WorkspaceWorktree, utc_now

logger = logging.getLogger(__name__)

# Per-workgroup locks to prevent concurrent git operations on the same repo.
_workspace_locks: dict[str, Lock] = {}

MAX_FILES = 512
MAX_FILE_SIZE = 200_000


class GitError(Exception):
    def __init__(self, message: str, stderr: str = "", returncode: int = 1):
        super().__init__(message)
        self.stderr = stderr
        self.returncode = returncode


def _get_lock(workgroup_id: str) -> Lock:
    if workgroup_id not in _workspace_locks:
        _workspace_locks[workgroup_id] = Lock()
    return _workspace_locks[workgroup_id]


def _run_git(args: list[str], cwd: str | Path, timeout: int = 30) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {' '.join(args)} timed out after {timeout}s") from exc
    except FileNotFoundError as exc:
        raise GitError("git executable not found") from exc

    if result.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} failed (rc={result.returncode}): {result.stderr.strip()}",
            stderr=result.stderr,
            returncode=result.returncode,
        )
    return result


def _safe_branch_name(topic: str, conversation_id: str) -> str:
    short_id = conversation_id[:8]
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", topic.lower()).strip("-")[:40]
    return f"job/{short_id}-{slug}" if slug else f"job/{short_id}"


def workspace_root_configured() -> bool:
    return bool(settings.workspace_root and settings.workspace_root.strip())


def _workspace_root() -> Path:
    root = settings.workspace_root.strip()
    if not root:
        raise GitError("workspace_root is not configured")
    return Path(root)


# ---------------------------------------------------------------------------
# Workspace lifecycle
# ---------------------------------------------------------------------------


def init_workspace(session: Session, workgroup_id: str) -> Workspace:
    """Idempotent: create bare repo + main worktree, or return existing."""
    existing = session.exec(
        select(Workspace).where(
            Workspace.workgroup_id == workgroup_id,
            Workspace.status == "active",
        )
    ).first()
    if existing:
        return existing

    root = _workspace_root()
    wg_dir = root / workgroup_id
    repo_path = wg_dir / "repo.git"
    main_wt_path = wg_dir / "main"

    lock = _get_lock(workgroup_id)
    with lock:
        try:
            repo_path.mkdir(parents=True, exist_ok=True)

            # Init bare repo
            _run_git(["init", "--bare"], cwd=repo_path)

            # Create main worktree
            main_wt_path.mkdir(parents=True, exist_ok=True)

            # Clone the bare repo into the main worktree directory
            # We need an initial commit first, so create a temp worktree
            _run_git(
                ["worktree", "add", "--orphan", "-b", "main", str(main_wt_path)],
                cwd=repo_path,
            )

            # Write existing workgroup files to disk
            from teaparty_app.models import Workgroup

            workgroup = session.get(Workgroup, workgroup_id)
            files = list(workgroup.files) if workgroup and workgroup.files else []
            _write_files_to_worktree(main_wt_path, files)

            # Make initial commit (even if empty)
            _run_git(["add", "-A"], cwd=main_wt_path)
            _run_git(
                ["commit", "--allow-empty", "-m", "Initial workspace commit"],
                cwd=main_wt_path,
            )

            workspace = Workspace(
                workgroup_id=workgroup_id,
                repo_path=str(repo_path),
                main_worktree_path=str(main_wt_path),
                status="active",
            )
            session.add(workspace)
            session.flush()
            logger.info("Initialized workspace for workgroup %s", workgroup_id)
            return workspace

        except (GitError, OSError) as exc:
            logger.error("Failed to init workspace for %s: %s", workgroup_id, exc)
            # Clean up partial state
            if wg_dir.exists():
                shutil.rmtree(wg_dir, ignore_errors=True)

            workspace = Workspace(
                workgroup_id=workgroup_id,
                repo_path=str(repo_path),
                main_worktree_path=str(main_wt_path),
                status="error",
                error_message=str(exc),
            )
            session.add(workspace)
            session.flush()
            raise


def destroy_workspace(session: Session, workspace: Workspace) -> None:
    """Remove all worktrees, delete directory tree, delete DB records."""
    lock = _get_lock(workspace.workgroup_id)
    with lock:
        # Delete worktree records
        worktrees = session.exec(
            select(WorkspaceWorktree).where(WorkspaceWorktree.workspace_id == workspace.id)
        ).all()
        for wt in worktrees:
            session.delete(wt)

        # Remove filesystem
        wg_dir = Path(workspace.repo_path).parent
        if wg_dir.exists():
            shutil.rmtree(wg_dir, ignore_errors=True)

        session.delete(workspace)
        session.flush()
        logger.info("Destroyed workspace for workgroup %s", workspace.workgroup_id)


# ---------------------------------------------------------------------------
# Worktree lifecycle
# ---------------------------------------------------------------------------


def create_worktree_for_job(
    session: Session, workspace: Workspace, conversation: Conversation
) -> WorkspaceWorktree:
    """Idempotent: create a git worktree for a job conversation."""
    existing = session.exec(
        select(WorkspaceWorktree).where(
            WorkspaceWorktree.workspace_id == workspace.id,
            WorkspaceWorktree.conversation_id == conversation.id,
            WorkspaceWorktree.status == "active",
        )
    ).first()
    if existing:
        return existing

    branch = _safe_branch_name(conversation.topic or conversation.name, conversation.id)
    root = _workspace_root()
    wt_path = root / workspace.workgroup_id / "worktrees" / conversation.id

    lock = _get_lock(workspace.workgroup_id)
    with lock:
        wt_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            _run_git(
                ["worktree", "add", str(wt_path), "-b", branch, "main"],
                cwd=workspace.repo_path,
            )
        except GitError as exc:
            if "already exists" in exc.stderr:
                # Branch exists — re-attach
                try:
                    _run_git(
                        ["worktree", "add", str(wt_path), branch],
                        cwd=workspace.repo_path,
                    )
                except GitError:
                    # Worktree path might already exist too
                    if not wt_path.exists():
                        raise
            else:
                raise

        worktree = WorkspaceWorktree(
            workspace_id=workspace.id,
            conversation_id=conversation.id,
            branch_name=branch,
            worktree_path=str(wt_path),
            status="active",
        )
        session.add(worktree)
        session.flush()
        logger.info("Created worktree for conversation %s on branch %s", conversation.id, branch)
        return worktree


def remove_worktree(session: Session, worktree: WorkspaceWorktree, delete_branch: bool = False) -> None:
    """Remove a git worktree and optionally delete its branch."""
    workspace = session.get(Workspace, worktree.workspace_id)
    if not workspace:
        return

    lock = _get_lock(workspace.workgroup_id)
    with lock:
        wt_path = Path(worktree.worktree_path)
        if wt_path.exists():
            try:
                _run_git(["worktree", "remove", "--force", str(wt_path)], cwd=workspace.repo_path)
            except GitError:
                # Force-remove the directory if git worktree remove fails
                shutil.rmtree(wt_path, ignore_errors=True)

        try:
            _run_git(["worktree", "prune"], cwd=workspace.repo_path)
        except GitError:
            pass

        if delete_branch:
            try:
                _run_git(["branch", "-D", worktree.branch_name], cwd=workspace.repo_path)
            except GitError:
                pass

        worktree.status = "removed"
        worktree.removed_at = utc_now()
        session.add(worktree)
        session.flush()
        logger.info("Removed worktree %s (delete_branch=%s)", worktree.id, delete_branch)


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------


def merge_job_to_main(session: Session, workspace: Workspace, worktree: WorkspaceWorktree) -> dict:
    """Merge a job branch into main. Returns {"merged": True/False, "conflicts": [...]}."""
    lock = _get_lock(workspace.workgroup_id)
    with lock:
        main_path = workspace.main_worktree_path
        branch = worktree.branch_name

        try:
            _run_git(["merge", "--no-ff", branch, "-m", f"Merge {branch}"], cwd=main_path)
        except GitError as exc:
            # Merge conflicts show up in stdout, not stderr — check both
            combined = exc.stderr + str(exc)
            if "CONFLICT" in combined or exc.returncode == 1:
                # Check if we're actually in a conflicted merge state
                try:
                    result = subprocess.run(
                        ["git", "diff", "--name-only", "--diff-filter=U"],
                        cwd=str(main_path),
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    conflicts = [f.strip() for f in result.stdout.strip().splitlines() if f.strip()]
                except Exception:
                    conflicts = []

                if conflicts:
                    # Abort the merge
                    try:
                        _run_git(["merge", "--abort"], cwd=main_path)
                    except GitError:
                        pass

                    return {"merged": False, "conflicts": conflicts, "branch": branch}
            raise

        worktree.status = "merged"
        worktree.merged_at = utc_now()
        session.add(worktree)
        session.flush()
        return {"merged": True, "conflicts": [], "branch": branch}


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def get_git_log(workspace: Workspace, branch: str = "main", limit: int = 20) -> list[dict]:
    """Return recent git log entries."""
    try:
        result = _run_git(
            ["log", f"--max-count={limit}", "--format=%H|%an|%ai|%s", branch],
            cwd=workspace.main_worktree_path,
        )
    except GitError:
        return []

    entries = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("|", 3)
        if len(parts) == 4:
            entries.append({
                "commit_hash": parts[0],
                "author": parts[1],
                "date": parts[2],
                "message": parts[3],
            })
    return entries


def _write_files_to_worktree(path: str | Path, files: list[dict]) -> int:
    """Write file dicts to disk with path-traversal protection. Returns count written."""
    base = Path(path).resolve()
    written = 0
    for file_entry in files[:MAX_FILES]:
        file_path_str = file_entry.get("path", "")
        if not file_path_str:
            continue

        # Skip URLs
        if file_path_str.lower().startswith(("http://", "https://")):
            continue

        target = (base / file_path_str).resolve()
        # Path traversal protection
        if not str(target).startswith(str(base)):
            logger.warning("Path traversal blocked: %s", file_path_str)
            continue

        content = file_entry.get("content", "")
        if len(content) > MAX_FILE_SIZE:
            content = content[:MAX_FILE_SIZE]

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        written += 1
    return written


def sync_worktree_to_files(
    session: Session,
    workgroup_id: str,
    conversation: Conversation,
    worktree_path: str,
) -> list[str]:
    """Walk worktree, update workgroup.files for changed/new/deleted files.

    Returns a list of changed file paths (for message generation).
    """
    from teaparty_app.models import Workgroup
    from teaparty_app.services.tools import _normalize_workgroup_files

    workgroup = session.get(Workgroup, workgroup_id)
    if not workgroup:
        return []

    # Read current files from worktree
    worktree_files = _read_files_from_worktree(worktree_path)
    worktree_by_path = {f["path"]: f["content"] for f in worktree_files}

    # Get current workgroup files
    all_files = _normalize_workgroup_files(workgroup)

    # Track changes
    changed: list[str] = []
    existing_paths = set()

    for entry in all_files:
        path = entry.get("path", "")
        existing_paths.add(path)

        if path in worktree_by_path:
            new_content = worktree_by_path[path]
            if entry.get("content", "") != new_content:
                entry["content"] = new_content
                changed.append(path)
        else:
            # File deleted in worktree — mark for removal
            entry["_deleted"] = True
            changed.append(path)

    # Add new files from worktree
    from uuid import uuid4
    for path, content in worktree_by_path.items():
        if path not in existing_paths:
            all_files.append({
                "id": str(uuid4()),
                "path": path,
                "content": content,
            })
            changed.append(path)

    # Remove deleted entries
    all_files = [f for f in all_files if not f.get("_deleted")]

    if changed:
        workgroup.files = all_files
        session.add(workgroup)

    return changed


def materialize_files_to_worktree(
    workgroup_id: str,
    conversation: Conversation,
    worktree_path: str,
    session: Session | None = None,
) -> int:
    """Write workgroup virtual files to the worktree filesystem.

    Called when a team session starts to give agents access to existing files.
    Returns count of files written.
    """
    from teaparty_app.models import Workgroup

    if session:
        workgroup = session.get(Workgroup, workgroup_id)
    else:
        from teaparty_app.db import engine
        with Session(engine) as s:
            workgroup = s.get(Workgroup, workgroup_id)

    if not workgroup:
        return 0

    files = list(workgroup.files or [])
    # Filter to relevant files (shared + conversation-scoped)
    topic_id = conversation.id if conversation.kind == "job" else ""
    relevant = [
        f for f in files
        if not f.get("topic_id") or f.get("topic_id") == topic_id
    ]

    return _write_files_to_worktree(worktree_path, relevant)


def post_file_change_messages(
    session: Session,
    conversation_id: str,
    changed_paths: list[str],
    agent_name: str = "Agent",
) -> None:
    """Post system messages about file changes to the conversation."""
    from teaparty_app.models import Message as MsgModel

    for path in changed_paths[:10]:  # Cap at 10 messages
        session.add(MsgModel(
            conversation_id=conversation_id,
            sender_type="system",
            content=f"[System] {agent_name} modified {path}",
            requires_response=False,
        ))


def _read_files_from_worktree(path: str | Path) -> list[dict]:
    """Read tracked files from a worktree. Enforces limits, skips binary."""
    base = Path(path).resolve()
    try:
        result = _run_git(["ls-files"], cwd=base)
    except GitError:
        return []

    files = []
    for rel_path in result.stdout.strip().splitlines():
        rel_path = rel_path.strip()
        if not rel_path:
            continue
        if len(files) >= MAX_FILES:
            break

        abs_path = (base / rel_path).resolve()
        if not str(abs_path).startswith(str(base)):
            continue
        if not abs_path.is_file():
            continue

        try:
            content = abs_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            # Skip binary or unreadable files
            continue

        if len(content) > MAX_FILE_SIZE:
            content = content[:MAX_FILE_SIZE]

        files.append({"path": rel_path, "content": content})

    return files
