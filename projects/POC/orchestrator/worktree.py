"""Git worktree management for sessions and dispatches.

Replaces the worktree creation/cleanup logic from the shell orchestrator.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from datetime import datetime, timezone


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
    for team_name in ('art', 'writing', 'editorial', 'research', 'coding'):
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
    dispatch_id = datetime.now().strftime('%Y%m%d-%H%M%S')
    task_slug = _slugify(task)[:25]
    worktree_name = f'{team}-{dispatch_id[:6]}--{task_slug}'
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

    # Write .running sentinel
    with open(os.path.join(dispatch_infra, '.running'), 'w') as f:
        f.write(str(os.getpid()))

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


async def cleanup_worktree(worktree_path: str) -> None:
    """Remove a worktree and its branch."""
    if not os.path.isdir(worktree_path):
        return
    try:
        repo_root = (await _run_git_output(
            worktree_path, 'rev-parse', '--show-toplevel'
        )).strip()
        branch = (await _run_git_output(
            worktree_path, 'rev-parse', '--abbrev-ref', 'HEAD'
        )).strip()
        await _run_git(repo_root, 'worktree', 'remove', '--force', worktree_path)
        if branch and branch != 'HEAD' and branch != 'main':
            await _run_git(repo_root, 'branch', '-D', branch)
    except Exception:
        pass


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


async def _run_git(cwd: str, *args: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        'git', *args,
        cwd=cwd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()


async def _run_git_output(cwd: str, *args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        'git', *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode()
