"""Git worktree management for agent workspaces and artifact commits."""
from __future__ import annotations

import asyncio
import logging
import os

log = logging.getLogger(__name__)


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


async def ensure_agent_worktree(
    agent_name: str,
    repo_root: str,
    parent_dir: str,
    *,
    is_management: bool = True,
    session_path: str = '',
) -> str:
    """Ensure a git worktree exists for an agent session.

    When *session_path* is provided, the worktree is created at
    ``{session_path}/worktree/`` — enforcing the 1:1 session/worktree
    binding from the design.  Without *session_path*, falls back to
    ``{parent_dir}/{agent_name}-workspace`` for compatibility.

    Creates a detached-HEAD worktree on first call.  On subsequent calls,
    fast-forwards to the current HEAD of *repo_root* so the agent sees
    up-to-date files.

    Returns:
        Absolute path to the worktree, for use as ``cwd``.
    """
    if session_path:
        worktree_path = os.path.join(session_path, 'worktree')
    else:
        worktree_path = os.path.join(parent_dir, f'{agent_name}-workspace')

    if not os.path.isdir(worktree_path):
        os.makedirs(os.path.dirname(worktree_path), exist_ok=True)
        await _run_git(repo_root, 'worktree', 'add', '--detach', worktree_path)
    else:
        # Fast-forward to current HEAD so the agent sees latest files.
        head = (await _run_git_output(repo_root, 'rev-parse', 'HEAD')).strip()
        try:
            await _run_git(worktree_path, 'checkout', '--detach', head)
        except RuntimeError:
            log.warning('ensure_agent_worktree: checkout failed for %s, recreating', agent_name)
            await _run_git(repo_root, 'worktree', 'remove', '--force', worktree_path)
            await _run_git(repo_root, 'worktree', 'add', '--detach', worktree_path)

    return worktree_path


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
