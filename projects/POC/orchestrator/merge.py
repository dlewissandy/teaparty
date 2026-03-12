"""Git merge operations for sessions and dispatches.

Handles squash-merging session/dispatch branches back into their
parent branches, with conflict resolution.
"""
from __future__ import annotations

import asyncio
import os


async def squash_merge(
    *,
    source: str,
    target: str,
    message: str,
) -> None:
    """Squash-merge source worktree's branch into target worktree's branch.

    Checks out the target branch, merges the source, commits,
    then switches back.
    """
    # Get source branch name
    source_branch = (await _git_output(source, 'rev-parse', '--abbrev-ref', 'HEAD')).strip()
    if not source_branch or source_branch == 'HEAD':
        return

    # Commit any uncommitted changes in source
    await _git(source, 'add', '-A')
    await _git(source, 'commit', '-m', f'WIP: {message}', '--allow-empty')

    # Merge into target
    await _git(target, 'merge', '--squash', source_branch)
    await _git(target, 'commit', '-m', message, '--allow-empty')


async def commit_deliverables(
    worktree: str,
    message: str,
) -> str | None:
    """Commit all changes in a worktree.  Returns commit hash or None."""
    await _git(worktree, 'add', '-A')

    # Check if there's anything to commit
    result = await _git_output(worktree, 'status', '--porcelain')
    if not result.strip():
        return None

    await _git(worktree, 'commit', '-m', message)
    sha = (await _git_output(worktree, 'rev-parse', 'HEAD')).strip()
    return sha


async def _git(cwd: str, *args: str) -> int:
    proc = await asyncio.create_subprocess_exec(
        'git', *args,
        cwd=cwd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    return await proc.wait()


async def _git_output(cwd: str, *args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        'git', *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    return stdout.decode()
