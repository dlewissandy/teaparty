"""Git worktree management for agent workspaces and artifact commits."""
from __future__ import annotations

import asyncio
import logging
import os
import shutil

log = logging.getLogger(__name__)

# Per-repo locks to serialize concurrent worktree operations.
# git worktree add and remove both modify .git/worktrees/ under an advisory
# lock; two concurrent calls on the same repo will race and one will fail.
_repo_locks: dict[str, asyncio.Lock] = {}


def _repo_lock(repo_root: str) -> asyncio.Lock:
    """Return the per-repo lock for worktree operations (created on first use)."""
    key = os.path.realpath(repo_root)
    if key not in _repo_locks:
        _repo_locks[key] = asyncio.Lock()
    return _repo_locks[key]


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
    if not session_path:
        raise ValueError(
            f'session_path is required for ensure_agent_worktree '
            f'(agent={agent_name}). Session must be created before worktree.'
        )
    worktree_path = os.path.join(session_path, 'worktree')

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


async def default_branch_of(repo_root: str) -> str:
    """Return the repo's default branch name (main/master/trunk).

    Strategy:
      1. ``git symbolic-ref refs/remotes/origin/HEAD`` — authoritative if
         origin is configured.
      2. Fall back to ``main`` if it exists as a local branch.
      3. Fall back to ``master`` if it exists as a local branch.
      4. Final fallback: ``main``.

    Used by chat-tier dispatch to decide where to fork cross-repo
    subchats from, and where to merge their work back to on close.
    """
    try:
        out = await _run_git_output(
            repo_root, 'symbolic-ref', 'refs/remotes/origin/HEAD',
        )
        ref = out.strip()
        if ref.startswith('refs/remotes/origin/'):
            return ref[len('refs/remotes/origin/'):]
    except RuntimeError:
        pass

    for candidate in ('main', 'master'):
        try:
            await _run_git(
                repo_root, 'show-ref', '--verify', '--quiet',
                f'refs/heads/{candidate}',
            )
            return candidate
        except RuntimeError:
            continue
    return 'main'


async def current_branch_of(worktree_path: str) -> str:
    """Return the current branch name of *worktree_path* (empty on detached HEAD)."""
    try:
        out = await _run_git_output(
            worktree_path, 'rev-parse', '--abbrev-ref', 'HEAD',
        )
        branch = out.strip()
        return '' if branch == 'HEAD' else branch
    except RuntimeError:
        return ''


async def head_commit_of(worktree_path: str) -> str:
    """Return the HEAD commit SHA of *worktree_path*."""
    try:
        return (await _run_git_output(
            worktree_path, 'rev-parse', 'HEAD',
        )).strip()
    except RuntimeError:
        return ''


async def create_subchat_worktree(
    source_repo: str,
    source_ref: str,
    dest_path: str,
    branch_name: str,
    parent_worktree: str = '',
) -> None:
    """Create a per-session worktree at *dest_path* on a new branch.

    ``git -C source_repo worktree add -b branch_name dest_path source_ref``

    *source_repo* is the main repo where the new worktree is registered.
    *source_ref* is what the new branch is rooted at (a commit SHA, a
    branch name, or ``HEAD``).

    After creation, writes a ``.gitignore`` that excludes per-launch
    infrastructure files (``.mcp.json``, ``.claude/``, ``stream.jsonl``,
    ``.scratch/``) so that parallel subchats forked from the same parent
    HEAD do not conflict on those files during squash-merge.

    When *parent_worktree* is given and contains a ``.scratch/`` directory,
    its contents are copied into the new worktree's ``.scratch/``.  This
    is how inter-agent scratch notes propagate across Send boundaries:
    the parent writes ``.scratch/<name>.md``, Send fires, the child's
    worktree boots with a snapshot of those notes.  The copy is one-way
    and point-in-time; the parent's later writes do not reach the
    already-running child.
    """
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    async with _repo_lock(source_repo):
        await _run_git(
            source_repo, 'worktree', 'add', '-b', branch_name,
            dest_path, source_ref,
        )
    gitignore = os.path.join(dest_path, '.gitignore')
    with open(gitignore, 'a') as f:
        f.write(
            '# Per-launch infrastructure — not agent work product\n'
            '.mcp.json\n'
            '.claude/\n'
            'stream.jsonl\n'
            '# Inter-agent scratch — copied at spawn, never committed\n'
            '.scratch/\n'
        )
    await _run_git(dest_path, 'add', '.gitignore')
    proc = await asyncio.create_subprocess_exec(
        'git', 'commit', '-m', 'chore: add subchat .gitignore',
        cwd=dest_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()

    # Seed .scratch/ from the parent's snapshot (if any) before the child
    # agent starts reading.  The directory always exists afterwards so
    # agents can reference `.scratch/<name>.md` without creating it.
    scratch_dst = os.path.join(dest_path, '.scratch')
    os.makedirs(scratch_dst, exist_ok=True)
    if parent_worktree:
        scratch_src = os.path.join(parent_worktree, '.scratch')
        if os.path.isdir(scratch_src):
            for entry in os.listdir(scratch_src):
                src = os.path.join(scratch_src, entry)
                dst = os.path.join(scratch_dst, entry)
                try:
                    if os.path.isdir(src):
                        shutil.copytree(src, dst, dirs_exist_ok=True)
                    else:
                        shutil.copy2(src, dst)
                except OSError as exc:
                    log.warning(
                        'scratch copy failed for %s → %s: %s',
                        src, dst, exc,
                    )


async def commit_all_pending(worktree_path: str, message: str) -> bool:
    """Stage and commit everything under *worktree_path*.

    Returns True if a commit was made, False if there was nothing to
    commit. Callers use this right before a merge-back to ensure the
    session branch carries the agent's work.
    """
    try:
        await _run_git(worktree_path, 'add', '-A')
    except RuntimeError:
        return False
    # Unstage harness artifacts — .claude/ is a composed artifact written at
    # dispatch time and .mcp.json is per-session config.  Neither should
    # appear in the session branch's commits.
    for artifact in ('.claude/', '.mcp.json'):
        proc = await asyncio.create_subprocess_exec(
            'git', 'reset', 'HEAD', '--', artifact,
            cwd=worktree_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
    status = await _run_git_output(worktree_path, 'status', '--porcelain')
    if not status.strip():
        return False
    proc = await asyncio.create_subprocess_exec(
        'git', 'commit', '-m', message, '--allow-empty-message',
        cwd=worktree_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    return proc.returncode == 0


async def squash_merge_session_branch(
    *,
    target_worktree: str,
    source_branch: str,
    message: str,
) -> dict:
    """Squash-merge *source_branch* into *target_worktree*'s current branch.

    Returns a dict with:
        status: 'ok' | 'conflict' | 'error'
        message: human-readable summary
        conflicts: list of conflicted file paths (conflict only)

    On success the target worktree has one new commit with *message*.
    On conflict the target worktree is left mid-merge so the parent
    agent can resolve via ``git`` and retry CloseConversation.
    """
    merge_proc = await asyncio.create_subprocess_exec(
        'git', 'merge', '--squash', source_branch,
        cwd=target_worktree,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    merge_stdout, merge_stderr = await merge_proc.communicate()
    if merge_proc.returncode != 0:
        # Identify conflicted files for the message.
        conflicts: list[str] = []
        try:
            status = await _run_git_output(
                target_worktree, 'diff', '--name-only', '--diff-filter=U',
            )
            conflicts = [
                line for line in status.splitlines() if line.strip()
            ]
        except RuntimeError:
            pass
        return {
            'status': 'conflict',
            'conflicts': conflicts,
            'message': (
                f'git merge --squash {source_branch} failed in '
                f'{target_worktree}. Conflicts: '
                f'{", ".join(conflicts) if conflicts else "(see git status)"}. '
                f'Resolve the conflicts with git, commit, and retry '
                f'CloseConversation. '
                f'{merge_stderr.decode(errors="replace").strip()}'
            ),
        }

    # Squash staged but not committed — commit now.
    commit_proc = await asyncio.create_subprocess_exec(
        'git', 'commit', '-m', message, '--allow-empty',
        cwd=target_worktree,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, commit_stderr = await commit_proc.communicate()
    if commit_proc.returncode != 0:
        return {
            'status': 'error',
            'conflicts': [],
            'message': (
                f'git commit of squash-merge failed in {target_worktree}: '
                f'{commit_stderr.decode(errors="replace").strip()}'
            ),
        }
    return {'status': 'ok', 'conflicts': [], 'message': f'Merged {source_branch}.'}


async def remove_session_worktree(source_repo: str, worktree_path: str) -> None:
    """Remove a per-session worktree and its branch.

    Best-effort: silent on failure (the session cleanup path can still
    rmtree the session directory).
    """
    if worktree_path and os.path.isdir(worktree_path):
        try:
            await _run_git(
                source_repo, 'worktree', 'remove', '--force', worktree_path,
            )
        except RuntimeError:
            pass


async def delete_branch(repo: str, branch: str) -> None:
    """Delete *branch* from *repo* (best-effort)."""
    if not branch:
        return
    try:
        await _run_git(repo, 'branch', '-D', branch)
    except RuntimeError:
        pass


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
