"""Git merge operations for sessions and dispatches.

Handles squash-merging session/dispatch branches back into their
parent branches.  The merge MUST succeed if work reached
COMPLETED_WORK — we never discard finished work because of a
mechanical merge failure.

Strategy:
  1. Try git merge --squash (fast, preserves history metadata).
  1b. On conflict, retry with -X theirs (take source on conflict).
  2. On conflict, resolve every conflict by taking the source
     (session) version — the completed work wins.
  3. If --squash fails for structural reasons (branch not reachable,
     detached HEAD), fall back to file-copy: diff the worktree
     against its merge-base and apply those changes to the target.

IMPORTANT: Never use `git add -A` in the target worktree — it picks
up untracked infrastructure files (.DS_Store, .memory.db, etc.) that
have nothing to do with the session's work.  Always stage only the
specific files that were changed.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from typing import Callable, Awaitable

_log = logging.getLogger('orchestrator.merge')


class MergeConflictEscalation(Exception):
    """Raised when merge conflicts require human review.

    Attributes:
        conflicted_files: list of file paths that have conflicts.
        source: path to source worktree.
        target: path to target worktree.
    """
    def __init__(self, conflicted_files: list[str], source: str, target: str):
        self.conflicted_files = conflicted_files
        self.source = source
        self.target = target
        super().__init__(
            f'Merge conflict in {len(conflicted_files)} file(s) requires human review: '
            + ', '.join(conflicted_files[:5])
        )


# Type for the conflict callback:
#   async (conflicted_files, source, target) -> 'theirs' | 'escalate'
ConflictCallback = Callable[[list[str], str, str], Awaitable[str]]

# Files that should never be included in a merge commit.
# These are infrastructure/runtime artifacts, not deliverables.
_MERGE_EXCLUDE = frozenset({
    '.DS_Store',
    '.memory.db',
    '.memory.db-shm',
    '.memory.db-wal',
    '.proxy-confidence.json',
    '.work-summary.md',
    'INTENT.md',
    'PLAN.md',
    'OBSERVATIONS.md',
    'job.json',
    'task.json',
    'jobs.json',
    'tasks.json',
})


def _is_excluded(relpath: str) -> bool:
    """Return True if relpath should be excluded from merge commits."""
    # The .claude/ directory in worktrees is a composed artifact written at
    # dispatch time (from .teaparty/ sources).  It must never merge back —
    # the trunk's .claude/ is the interactive-session config, not the
    # dispatch-composed version.
    if relpath == '.claude' or relpath.startswith('.claude/') or relpath.startswith('.claude\\'):
        return True
    basename = os.path.basename(relpath)
    if basename in _MERGE_EXCLUDE:
        return True
    # Exclude escalation files — these are ephemeral agent-to-orchestrator
    # signals that must never cross session boundaries via merge.
    if 'escalation' in basename:
        return True
    # Exclude hidden infrastructure files at root level
    if basename.startswith('.') and basename.endswith(('.db', '.db-shm', '.db-wal', '.json', '.lock')):
        # But not .gitignore or similar
        if basename not in ('.gitignore', '.gitattributes'):
            return True
    return False


async def squash_merge(
    *,
    source: str,
    target: str,
    message: str,
    conflict_callback: ConflictCallback | None = None,
) -> None:
    """Squash-merge source worktree's branch into target.

    Always gets the work merged.  Falls back through progressively
    more aggressive strategies until the files are on the target.

    If conflict_callback is provided, it is called when merge conflicts
    occur.  The callback receives (conflicted_files, source, target) and
    returns 'theirs' to auto-resolve or 'escalate' to raise
    MergeConflictEscalation for human review.  (Issue #6)
    """
    # Commit any uncommitted changes in source first.
    # Use targeted add to avoid committing infrastructure files.
    await _add_tracked_and_new(source)
    await _git_try(source, 'commit', '-m', f'WIP: {message}', '--allow-empty')

    # Strategy 1: git merge --squash
    source_branch = (await _git_output(source, 'rev-parse', '--abbrev-ref', 'HEAD')).strip()
    if source_branch and source_branch != 'HEAD':
        rc = await _git_rc(target, 'merge', '--squash', source_branch)
        if rc == 0:
            await _git_try(target, 'commit', '-m', message, '--allow-empty')
            _log.info('Squash-merge succeeded: %s -> %s', source_branch, target)
            await _verify_merge(source, target)
            return

        # Conflicts detected — consult callback if provided (Issue #6)
        if conflict_callback:
            conflicted = await _get_conflicted_files(target)
            if conflicted:
                await _git_try(target, 'merge', '--abort')
                decision = await conflict_callback(conflicted, source, target)
                if decision == 'escalate':
                    raise MergeConflictEscalation(conflicted, source, target)
                # 'theirs' — fall through to -X theirs strategy

        # Strategy 1b: retry with -X theirs (auto-resolve conflicts by taking source)
        _log.warning('Squash-merge had conflicts, retrying with -X theirs')
        await _git_try(target, 'merge', '--abort')
        rc = await _git_rc(target, 'merge', '--squash', '-X', 'theirs', source_branch)
        if rc == 0:
            await _git_try(target, 'commit', '-m', message, '--allow-empty')
            _log.info('Squash-merge with -X theirs succeeded: %s -> %s', source_branch, target)
            await _verify_merge(source, target)
            return

        # Strategy 2: merge had conflicts even with -X theirs — resolve manually
        _log.warning('Squash-merge with -X theirs still had conflicts, resolving manually')
        await _resolve_conflicts_from_source(source, target)
        # Stage only the conflicted files we just resolved, not everything
        conflicted = await _get_conflicted_files(target)
        if conflicted:
            for relpath in conflicted:
                await _git_try(target, 'add', os.path.join(target, relpath))
            rc = await _git_rc(target, 'commit', '-m', message, '--allow-empty')
            if rc == 0:
                _log.info('Conflict-resolved merge succeeded: %s -> %s', source_branch, target)
                await _verify_merge(source, target)
                return

        # Conflict resolution didn't work — abort and fall through
        await _git_try(target, 'merge', '--abort')

    # Strategy 3: file-copy fallback — diff source against merge-base, copy to target
    _log.warning('Git merge strategies failed, falling back to file-copy')
    await _file_copy_merge(source, target, message)

    # Post-merge verification: compare source files against what landed.
    # This catches silent data loss where a merge "succeeds" but drops files.
    await _verify_merge(source, target)


async def _verify_merge(source: str, target: str) -> None:
    """Post-merge verification: check that source files exist in target.

    Compares tracked source files against the target working tree.
    Logs warnings for any files present in source but missing or
    different-sized in target.  This catches silent data loss where
    a merge reports success but drops or truncates files.
    """
    # Get list of tracked files in source (these are the deliverables)
    output = await _git_output(source, 'ls-files')
    if not output.strip():
        return

    source_files = [f for f in output.strip().splitlines()
                    if f.strip() and not _is_excluded(f.strip())]

    missing = []
    truncated = []
    for relpath in source_files:
        src_file = os.path.join(source, relpath)
        dst_file = os.path.join(target, relpath)
        if not os.path.exists(src_file):
            continue  # deleted in source, skip
        if not os.path.exists(dst_file):
            missing.append(relpath)
            continue
        # Check for significant size difference (>50% smaller = truncated)
        src_size = os.path.getsize(src_file)
        dst_size = os.path.getsize(dst_file)
        if src_size > 0 and dst_size < src_size * 0.5:
            truncated.append((relpath, src_size, dst_size))

    if missing:
        _log.error(
            'MERGE VERIFICATION FAILED: %d file(s) missing from target after merge: %s',
            len(missing), ', '.join(missing[:10]),
        )
    if truncated:
        details = [f'{f} (src={s}B, dst={d}B)' for f, s, d in truncated[:10]]
        _log.error(
            'MERGE VERIFICATION WARNING: %d file(s) appear truncated after merge: %s',
            len(truncated), ', '.join(details),
        )
    if not missing and not truncated:
        _log.info('Merge verification passed: all %d source files present in target', len(source_files))


async def _get_conflicted_files(worktree: str) -> list[str]:
    """Return list of conflicted file paths in worktree."""
    output = await _git_output(worktree, 'diff', '--name-only', '--diff-filter=U')
    return [f for f in output.strip().splitlines() if f.strip()]


async def _add_tracked_and_new(worktree: str) -> None:
    """Stage tracked-modified and new files, excluding infrastructure artifacts.

    Unlike `git add -A`, this does NOT stage untracked infrastructure files
    (.DS_Store, .memory.db, etc.) that happen to exist in the worktree.
    """
    # Stage all tracked files that have been modified
    await _git_try(worktree, 'add', '-u')

    # Unstage .claude/ — it's a composed artifact written at dispatch time
    # from .teaparty/ sources.  Must not merge back into the trunk.
    await _git_try(worktree, 'reset', 'HEAD', '--', '.claude/')

    # Find untracked files and add only non-excluded ones
    output = await _git_output(worktree, 'ls-files', '--others', '--exclude-standard')
    if output.strip():
        for relpath in output.strip().splitlines():
            relpath = relpath.strip()
            if relpath and not _is_excluded(relpath):
                await _git_try(worktree, 'add', relpath)


async def _resolve_conflicts_from_source(source: str, target: str) -> None:
    """For every conflicted file in target, overwrite with source's version."""
    conflicted = await _get_conflicted_files(target)

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
    merge-base, then copy them directly into target and commit.

    Only stages the specific files that were copied — never uses `git add -A`.
    """
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

    # Filter out infrastructure files
    changed_files = [f for f in changed_files if not _is_excluded(f)]

    if not changed_files:
        _log.info('No changed files to copy')
        return

    copied_files: list[str] = []
    for relpath in changed_files:
        src_file = os.path.join(source, relpath)
        dst_file = os.path.join(target, relpath)
        if os.path.exists(src_file):
            os.makedirs(os.path.dirname(dst_file), exist_ok=True)
            shutil.copy2(src_file, dst_file)
            copied_files.append(relpath)
        else:
            # Deleted in source
            if os.path.exists(dst_file):
                os.remove(dst_file)
                copied_files.append(relpath)

    if copied_files:
        # Stage only the files we just copied — not `git add -A`
        for relpath in copied_files:
            await _git_try(target, 'add', relpath)
        await _git_try(target, 'commit', '-m', message)
        _log.info('File-copy merge succeeded: %d files -> %s', len(copied_files), target)
    else:
        _log.info('File-copy merge: no files needed copying')


async def commit_deliverables(
    worktree: str,
    message: str,
) -> str | None:
    """Commit all changes in a worktree.  Returns commit hash or None.

    Uses targeted add to exclude infrastructure files.
    """
    await _add_tracked_and_new(worktree)

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


# Public alias for use by other modules (dispatch_cli, actors).
git_output = _git_output
