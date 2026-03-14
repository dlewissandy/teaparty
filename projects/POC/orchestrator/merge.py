"""Git merge operations for sessions and dispatches.

Handles squash-merging session/dispatch branches back into their
parent branches.  The merge MUST succeed if work reached
COMPLETED_WORK — we never discard finished work because of a
mechanical merge failure.

Strategy:
  1. Try git merge --squash (fast, preserves history metadata).
  2. On conflict, resolve every conflict by taking the source
     (session) version — the completed work wins.
  3. If --squash fails for structural reasons (branch not reachable,
     detached HEAD), fall back to file-copy: diff the worktree
     against its merge-base and apply those changes to the target.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil

_log = logging.getLogger('orchestrator.merge')


async def squash_merge(
    *,
    source: str,
    target: str,
    message: str,
) -> None:
    """Squash-merge source worktree's branch into target.

    Always gets the work merged.  Falls back through progressively
    more aggressive strategies until the files are on the target.
    """
    # Commit any uncommitted changes in source first
    await _git_try(source, 'add', '-A')
    await _git_try(source, 'commit', '-m', f'WIP: {message}', '--allow-empty')

    # Strategy 1: git merge --squash
    source_branch = (await _git_output(source, 'rev-parse', '--abbrev-ref', 'HEAD')).strip()
    if source_branch and source_branch != 'HEAD':
        rc = await _git_rc(target, 'merge', '--squash', source_branch)
        if rc == 0:
            await _git_try(target, 'commit', '-m', message, '--allow-empty')
            _log.info('Squash-merge succeeded: %s → %s', source_branch, target)
            return

        # Strategy 2: merge had conflicts — resolve them all by taking source
        _log.warning('Squash-merge had conflicts, resolving with source (completed work)')
        await _resolve_conflicts_from_source(source, target)
        rc = await _git_rc(target, 'add', '-A')
        if rc == 0:
            rc = await _git_rc(target, 'commit', '-m', message, '--allow-empty')
            if rc == 0:
                _log.info('Conflict-resolved merge succeeded: %s → %s', source_branch, target)
                return

        # Conflict resolution didn't work — abort and fall through
        await _git_try(target, 'merge', '--abort')

    # Strategy 3: file-copy fallback — diff source against merge-base, copy to target
    _log.warning('Git merge strategies failed, falling back to file-copy')
    await _file_copy_merge(source, target, message)


async def _resolve_conflicts_from_source(source: str, target: str) -> None:
    """For every conflicted file in target, overwrite with source's version."""
    output = await _git_output(target, 'diff', '--name-only', '--diff-filter=U')
    conflicted = [f for f in output.strip().splitlines() if f.strip()]

    for relpath in conflicted:
        src_file = os.path.join(source, relpath)
        dst_file = os.path.join(target, relpath)
        if os.path.exists(src_file):
            os.makedirs(os.path.dirname(dst_file), exist_ok=True)
            shutil.copy2(src_file, dst_file)
        else:
            # File was deleted in source — delete in target too
            if os.path.exists(dst_file):
                os.remove(dst_file)


async def _file_copy_merge(source: str, target: str, message: str) -> None:
    """Last-resort merge: find files that differ between source and its
    merge-base, then copy them directly into target and commit."""
    # Find the merge-base between source HEAD and target HEAD
    source_head = (await _git_output(source, 'rev-parse', 'HEAD')).strip()
    target_head = (await _git_output(target, 'rev-parse', 'HEAD')).strip()
    merge_base = (await _git_output(
        source, 'merge-base', source_head, target_head,
    )).strip()

    if not merge_base:
        # No common ancestor — copy ALL tracked files from source
        _log.warning('No merge-base found, copying all tracked files')
        output = await _git_output(source, 'ls-files')
        changed_files = [f for f in output.strip().splitlines() if f.strip()]
    else:
        # Get files that changed between merge-base and source HEAD
        output = await _git_output(
            source, 'diff', '--name-only', merge_base, 'HEAD',
        )
        changed_files = [f for f in output.strip().splitlines() if f.strip()]

    if not changed_files:
        _log.info('No changed files to copy')
        return

    copied = 0
    for relpath in changed_files:
        src_file = os.path.join(source, relpath)
        dst_file = os.path.join(target, relpath)
        if os.path.exists(src_file):
            os.makedirs(os.path.dirname(dst_file), exist_ok=True)
            shutil.copy2(src_file, dst_file)
            copied += 1
        else:
            # Deleted in source
            if os.path.exists(dst_file):
                os.remove(dst_file)
                copied += 1

    if copied > 0:
        await _git_try(target, 'add', '-A')
        await _git_try(target, 'commit', '-m', message)
        _log.info('File-copy merge succeeded: %d files → %s', copied, target)
    else:
        _log.info('File-copy merge: no files needed copying')


async def commit_deliverables(
    worktree: str,
    message: str,
) -> str | None:
    """Commit all changes in a worktree.  Returns commit hash or None."""
    await _git_try(worktree, 'add', '-A')

    # Check if there's anything to commit
    result = await _git_output(worktree, 'status', '--porcelain')
    if not result.strip():
        return None

    await _git_try(worktree, 'commit', '-m', message)
    sha = (await _git_output(worktree, 'rev-parse', 'HEAD')).strip()
    return sha


async def _git_try(cwd: str, *args: str) -> int:
    """Run a git command, log on failure, return exit code."""
    proc = await asyncio.create_subprocess_exec(
        'git', *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        cmd = ' '.join(['git', *args])
        _log.warning('`%s` failed (rc=%d) in %s: %s',
                      cmd, proc.returncode, cwd, stderr.decode().strip())
    return proc.returncode


async def _git_rc(cwd: str, *args: str) -> int:
    """Run a git command, return exit code silently."""
    proc = await asyncio.create_subprocess_exec(
        'git', *args,
        cwd=cwd,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    return await proc.wait()


async def _git_output(cwd: str, *args: str) -> str:
    """Run a git command, return stdout.  Returns '' on failure."""
    proc = await asyncio.create_subprocess_exec(
        'git', *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        cmd = ' '.join(['git', *args])
        _log.warning('`%s` failed (rc=%d) in %s: %s',
                      cmd, proc.returncode, cwd, stderr.decode().strip())
        return ''
    return stdout.decode()
