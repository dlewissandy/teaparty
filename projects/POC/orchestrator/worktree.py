"""Git worktree management for sessions and dispatches."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timezone

log = logging.getLogger(__name__)


async def create_session_worktree(
    *,
    project_slug: str,
    task: str,
    repo_root: str,
    projects_dir: str,
    session_id: str,
) -> dict:
    """Create a session worktree and infra directory.

    Returns dict with: worktree_path, infra_dir, branch_name, session_id.
    """
    # Generate short ID and task slug
    short_id = session_id[-6:]
    task_slug = _slugify(task)[:30]
    worktree_name = f'session-{short_id}--{task_slug}'
    branch_name = worktree_name

    # Worktree path under project
    project_dir = os.path.join(projects_dir, project_slug)
    worktree_path = os.path.join(project_dir, '.worktrees', worktree_name)

    # Create worktree
    os.makedirs(os.path.dirname(worktree_path), exist_ok=True)
    await _run_git(repo_root, 'worktree', 'add', '-b', branch_name, worktree_path)

    # Create infra directory and team subdirs for dispatch MEMORY.md rollup
    infra_dir = os.path.join(project_dir, '.sessions', session_id)
    os.makedirs(infra_dir, exist_ok=True)
    from projects.POC.orchestrator.phase_config import get_team_names
    for team_name in get_team_names():
        os.makedirs(os.path.join(infra_dir, team_name), exist_ok=True)

    # Register in manifest
    _register_worktree(repo_root, {
        'name': worktree_name,
        'path': worktree_path,
        'type': 'session',
        'team': '',
        'task': task,
        'session_id': session_id,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'status': 'active',
    })

    return {
        'worktree_path': worktree_path,
        'infra_dir': infra_dir,
        'branch_name': branch_name,
        'session_id': session_id,
        'worktree_name': worktree_name,
    }


async def create_dispatch_worktree(
    *,
    team: str,
    task: str,
    session_worktree: str,
    infra_dir: str,
    repo_root: str = '',
) -> dict:
    """Create a dispatch worktree branched from the session.

    Returns dict with: worktree_path, infra_dir, branch_name, dispatch_id.

    Args:
        repo_root: Main repository root for manifest registration.  If empty,
            falls back to ``git rev-parse --path-format=absolute --git-common-dir``
            which returns the shared .git dir even from inside a worktree.
    """
    import hashlib
    base_dispatch_id = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    task_slug = _slugify(task)[:25]

    # Collision detection: if the infra dir already exists, append a counter.
    # Handles parallel dispatches that land in the same microsecond.
    dispatch_id = base_dispatch_id
    for attempt in range(1, 100):
        dispatch_infra_candidate = os.path.join(infra_dir, team, dispatch_id)
        if not os.path.exists(dispatch_infra_candidate):
            break
        dispatch_id = f'{base_dispatch_id}-{attempt}'

    # Derive 8-char unique hash from dispatch_id for the worktree name.
    # 8-char deterministic hash from dispatch_id for the worktree name.
    short_hash = hashlib.md5(dispatch_id.encode()).hexdigest()[:8]
    worktree_name = f'{team}-{short_hash}--{task_slug}'
    branch_name = worktree_name

    # Dispatch worktree is a sibling of the session worktree
    parent = os.path.dirname(session_worktree)
    worktree_path = os.path.join(parent, worktree_name)

    # Resolve the true repo root for manifest registration.
    # git rev-parse --show-toplevel returns the *worktree* root (wrong).
    # --git-common-dir returns the shared .git directory; its parent is the
    # actual repo root.
    if not repo_root:
        git_common = (await _run_git_output(
            session_worktree, 'rev-parse', '--path-format=absolute', '--git-common-dir'
        )).strip()
        # git_common is e.g. /path/to/repo/.git → parent is the repo root
        repo_root = os.path.dirname(git_common)

    await _run_git(session_worktree, 'worktree', 'add', '-b', branch_name, worktree_path)

    # Dispatch infra is nested under the session infra
    dispatch_infra = os.path.join(infra_dir, team, dispatch_id)
    os.makedirs(dispatch_infra, exist_ok=True)

    # Write .heartbeat (replaces .running sentinel — issue #149)
    from projects.POC.orchestrator.heartbeat import create_heartbeat
    create_heartbeat(
        os.path.join(dispatch_infra, '.heartbeat'),
        role=team,
    )

    # Register in manifest
    _register_worktree(repo_root, {
        'name': worktree_name,
        'path': worktree_path,
        'type': 'dispatch',
        'team': team,
        'task': task,
        'session_id': dispatch_id,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'status': 'active',
    })

    return {
        'worktree_path': worktree_path,
        'infra_dir': dispatch_infra,
        'branch_name': branch_name,
        'dispatch_id': dispatch_id,
        'worktree_name': worktree_name,
    }


async def commit_artifact(worktree: str, paths: list[str], message: str) -> None:
    """Stage and commit artifact files in the session worktree.

    Uses --allow-empty-message as a safety net, but callers should always
    provide a meaningful message.  No-ops silently if nothing changed
    (git commit exits 1 when there's nothing to commit).
    """
    await _run_git(worktree, 'add', '--', *paths)
    # git commit exits 1 if nothing to commit — that's fine, not an error.
    proc = await asyncio.create_subprocess_exec(
        'git', 'commit', '-m', message, '--allow-empty-message',
        cwd=worktree,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()


async def artifact_version(worktree: str, path: str) -> int:
    """Return the next version number for an artifact file.

    Counts existing commits that touched ``path`` and adds 1.
    """
    output = await _run_git_output(worktree, 'rev-list', '--count', 'HEAD', '--', path)
    try:
        return int(output.strip()) + 1
    except (ValueError, TypeError):
        return 1


async def cleanup_worktree(worktree_path: str) -> None:
    """Remove a worktree, its branch, and its manifest entry.

    Each step is independent so that failure in one does not prevent the
    others from executing.  Failures are logged as warnings rather than
    silently swallowed.
    """
    if not os.path.isdir(worktree_path):
        return

    # Resolve the true repo root via --git-common-dir (not --show-toplevel,
    # which returns the worktree root when called from inside a worktree).
    try:
        git_common = (await _run_git_output(
            worktree_path, 'rev-parse', '--path-format=absolute', '--git-common-dir'
        )).strip()
        repo_root = os.path.dirname(git_common)
    except Exception:
        log.warning("cleanup_worktree: failed to resolve repo root for %s", worktree_path)
        return

    # Read the branch name before removing the worktree (afterwards the
    # worktree directory is gone and we can't query it).
    branch = ''
    try:
        branch = (await _run_git_output(
            worktree_path, 'rev-parse', '--abbrev-ref', 'HEAD'
        )).strip()
    except Exception:
        log.warning("cleanup_worktree: failed to read branch for %s", worktree_path)

    # Step 1: remove the worktree directory
    try:
        await _run_git(repo_root, 'worktree', 'remove', '--force', worktree_path)
    except Exception:
        log.warning("cleanup_worktree: failed to remove worktree %s", worktree_path)

    # Step 2: delete the branch
    if branch and branch != 'HEAD' and branch != 'main':
        try:
            await _run_git(repo_root, 'branch', '-D', branch)
        except Exception:
            log.warning("cleanup_worktree: failed to delete branch %s", branch)

    # Step 3: remove from manifest
    try:
        _unregister_worktree(repo_root, worktree_path)
    except Exception:
        log.warning("cleanup_worktree: failed to unregister %s from manifest", worktree_path)


def _slugify(text: str) -> str:
    """Convert text to a URL-safe slug."""
    slug = re.sub(r'[^a-zA-Z0-9]+', '-', text.lower()).strip('-')
    return slug or 'task'


def _register_worktree(repo_root: str, entry: dict) -> None:
    """Add an entry to worktrees.json manifest under file lock."""
    from filelock import FileLock

    manifest_path = os.path.join(repo_root, 'worktrees.json')
    lock = FileLock(manifest_path + '.lock', timeout=30)

    with lock:
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            manifest = {'worktrees': []}

        manifest['worktrees'].append(entry)
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)


def _unregister_worktree(repo_root: str, worktree_path: str) -> None:
    """Remove the entry for worktree_path from worktrees.json under file lock."""
    from filelock import FileLock

    manifest_path = os.path.join(repo_root, 'worktrees.json')
    lock = FileLock(manifest_path + '.lock', timeout=30)

    with lock:
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return

        # Normalize for comparison
        norm = os.path.normpath(worktree_path)
        manifest['worktrees'] = [
            e for e in manifest.get('worktrees', [])
            if os.path.normpath(e.get('path', '')) != norm
        ]
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)


def find_orphaned_worktrees(repo_root: str) -> list[dict]:
    """Find manifest entries whose worktrees are orphaned.

    A worktree is considered orphaned if:
    - Its path no longer exists on disk, OR
    - Its heartbeat is stale (non-terminal, old mtime, dead PID), OR
    - It has no heartbeat and no .running sentinel

    Checks the infra_dir for .heartbeat (issue #149), falling back to
    .running in the worktree path for backward compatibility.
    """
    from projects.POC.orchestrator.heartbeat import is_heartbeat_stale, read_heartbeat

    manifest_path = os.path.join(repo_root, 'worktrees.json')
    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

    orphans = []
    for entry in manifest.get('worktrees', []):
        path = entry.get('path', '')
        if not path or not os.path.isdir(path):
            orphans.append(entry)
            continue

        # Check .heartbeat in infra_dir (issue #149)
        infra_dir = entry.get('infra_dir', '')
        if infra_dir:
            hb_path = os.path.join(infra_dir, '.heartbeat')
            if os.path.exists(hb_path):
                data = read_heartbeat(hb_path)
                if data.get('status') in ('completed', 'withdrawn'):
                    continue  # Terminal — not orphaned
                if is_heartbeat_stale(hb_path):
                    orphans.append(entry)
                continue  # Fresh heartbeat — not orphaned

        # Fallback: check .running in worktree path (backward compat)
        running_path = os.path.join(path, '.running')
        if not os.path.exists(running_path):
            orphans.append(entry)
            continue

        try:
            with open(running_path) as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
        except (ValueError, ProcessLookupError, PermissionError, OSError):
            orphans.append(entry)

    return orphans


async def _run_git(cwd: str, *args: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        'git', *args,
        cwd=cwd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode:
        raise RuntimeError(
            f"git {' '.join(args)} failed (rc={proc.returncode}): "
            f"{stderr.decode().strip()}"
        )


async def _run_git_output(cwd: str, *args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        'git', *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode()
