"""Job store — hierarchical, project-scoped worktree management.

Issue #384: Replaces the flat worktrees.json manifest with a hierarchical
layout under {project_root}/.teaparty/jobs/.

Directory layout:
    {project_root}/.teaparty/
      jobs/
        jobs.json
        job-{short_id}--{slug}/
          worktree/
          job.json
          tasks/
            tasks.json
            task-{short_id}--{slug}/
              worktree/
              task.json
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import signal
import shutil
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def _slugify(text: str, max_len: int = 30) -> str:
    """Convert text to a filesystem-safe slug."""
    slug = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
    return (slug[:max_len].rstrip('-')) or 'task'


def _short_id() -> str:
    """Generate a short unique ID (8 hex chars)."""
    return hashlib.md5(os.urandom(16)).hexdigest()[:8]


def _jobs_dir(project_root: str) -> str:
    return os.path.join(project_root, '.teaparty', 'jobs')


def jobs_dir(project_root: str) -> str:
    """Public accessor for the jobs directory path."""
    return _jobs_dir(project_root)


def project_root_from_job_dir(job_dir: str) -> str:
    """Derive the project root from a job_dir path.

    job_dir = {project_root}/.teaparty/jobs/job-{id}--{slug}/
    """
    # jobs/ → .teaparty/ → {project_root}
    return os.path.dirname(os.path.dirname(os.path.dirname(job_dir.rstrip('/'))))


# ── Index I/O ────────────────────────────────────────────────────────────────

def _load_index(path: str, key: str) -> dict:
    """Load a JSON index file; return empty structure if missing."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {key: []}


def _save_index(path: str, data: dict) -> None:
    """Atomically write an index file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    replaced = False
    try:
        with open(tmp, 'w') as f:
            json.dump(data, f, indent=2)
            f.write('\n')
        os.replace(tmp, path)
        replaced = True
    finally:
        if not replaced:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass


# ── Git helpers ──────────────────────────────────────────────────────────────

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


async def _write_artifact_gitignore(worktree_path: str) -> None:
    """Write and commit a .gitignore to *worktree_path* that excludes process artifacts.

    INTENT.md, PLAN.md, and WORK_SUMMARY.md live in the worktree root for
    visibility (reviewer can navigate to them) but must never reach main — they
    are planning scaffolding, not deliverables.  The .gitignore is the belt;
    _MERGE_EXCLUDE in merge.py is the suspenders.

    .scratch/ holds inter-agent working notes referenced from Send/Reply/
    AskQuestion messages — ephemeral, never committed, never merged.
    """
    gitignore_path = os.path.join(worktree_path, '.gitignore')
    with open(gitignore_path, 'a') as f:
        f.write(
            '# Process artifacts — planning scaffolding, not deliverables\n'
            'INTENT.md\n'
            'PLAN.md\n'
            'WORK_SUMMARY.md\n'
            '# Per-launch infrastructure\n'
            '.mcp.json\n'
            '.claude/\n'
            'stream.jsonl\n'
            '# Inter-agent scratch — copied at spawn, never committed\n'
            '.scratch/\n'
        )
    await _run_git(worktree_path, 'add', '.gitignore')
    proc = await asyncio.create_subprocess_exec(
        'git', 'commit', '-m', 'chore: add worktree .gitignore',
        cwd=worktree_path,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    await proc.wait()
    # Ensure the scratch dir always exists so agents can reference
    # `.scratch/<name>.md` without having to create it.
    os.makedirs(os.path.join(worktree_path, '.scratch'), exist_ok=True)


# ── Job operations ───────────────────────────────────────────────────────────

async def create_job(
    *,
    project_root: str,
    task: str,
    issue: int | None = None,
    session_id: str = '',
) -> dict:
    """Create a new job with a git worktree under {project_root}/.teaparty/jobs/.

    The job_dir serves as the infra directory — CfA state, message bus,
    heartbeat, and artifacts all live here alongside the worktree and tasks.

    Args:
        session_id: Optional caller-provided ID (e.g., timestamp-based).
            If empty, a random short ID is generated.

    Returns dict with: job_id, job_dir, worktree_path, branch_name.
    """
    short = session_id or _short_id()
    job_id = f'job-{short}'
    slug = _slugify(task)
    dir_name = f'{job_id}--{slug}'
    job_dir = os.path.join(_jobs_dir(project_root), dir_name)
    worktree_path = os.path.join(job_dir, 'worktree')
    branch_name = dir_name

    os.makedirs(job_dir, exist_ok=True)

    # Create git worktree
    await _run_git(project_root, 'worktree', 'add', '-b', branch_name, worktree_path)

    # Gitignore for process artifacts — belt: agents cannot accidentally commit them.
    # These files live in the worktree root for visibility but must never reach main.
    await _write_artifact_gitignore(worktree_path)

    # Write job state
    now = datetime.now(timezone.utc).isoformat()
    job_state = {
        'job_id': job_id,
        'slug': slug,
        'issue': issue,
        'branch': branch_name,
        'status': 'active',
        'created_at': now,
        'updated_at': now,
    }
    with open(os.path.join(job_dir, 'job.json'), 'w') as f:
        json.dump(job_state, f, indent=2)
        f.write('\n')

    # Initialize empty tasks directory and index
    tasks_dir = os.path.join(job_dir, 'tasks')
    os.makedirs(tasks_dir, exist_ok=True)
    _save_index(os.path.join(tasks_dir, 'tasks.json'), {'tasks': []})

    # Update jobs index
    index_path = os.path.join(_jobs_dir(project_root), 'jobs.json')
    index = _load_index(index_path, 'jobs')
    index['jobs'].append({
        'job_id': job_id,
        'dir': dir_name,
        'status': 'active',
    })
    _save_index(index_path, index)

    return {
        'job_id': job_id,
        'job_dir': job_dir,
        'worktree_path': worktree_path,
        'branch_name': branch_name,
    }


# ── Task operations ──────────────────────────────────────────────────────────

async def create_task(
    *,
    job_dir: str,
    task: str,
    team: str,
    agent: str = '',
    dispatch_id: str = '',
) -> dict:
    """Create a new task with a git worktree under the parent job.

    The task_dir serves as the dispatch infra directory — CfA state,
    heartbeat, and events all live here alongside the task worktree.

    Args:
        dispatch_id: Optional caller-provided ID.  If empty, generated.

    Returns dict with: task_id, task_dir, worktree_path, branch_name.
    """
    short = dispatch_id or _short_id()
    task_id = f'task-{short}'
    slug = _slugify(task)
    dir_name = f'{task_id}--{slug}'
    tasks_dir = os.path.join(job_dir, 'tasks')
    task_dir = os.path.join(tasks_dir, dir_name)
    worktree_path = os.path.join(task_dir, 'worktree')
    branch_name = dir_name

    os.makedirs(task_dir, exist_ok=True)

    # Read the job's branch from job.json so the task branches from it
    with open(os.path.join(job_dir, 'job.json')) as f:
        job_state = json.load(f)
    job_branch = job_state['branch']

    # Resolve repo root from the job's worktree
    job_worktree = os.path.join(job_dir, 'worktree')
    proc = await asyncio.create_subprocess_exec(
        'git', 'rev-parse', '--path-format=absolute', '--git-common-dir',
        cwd=job_worktree,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    stdout, _ = await proc.communicate()
    repo_root = os.path.dirname(stdout.decode().strip())

    # Create git worktree branching from the job's branch
    await _run_git(repo_root, 'worktree', 'add', '-b', branch_name, worktree_path, job_branch)

    # Gitignore for process artifacts — same as job worktree.
    await _write_artifact_gitignore(worktree_path)

    # Copy planning artifacts from parent job worktree so the subagent has
    # the same context without relying on the task string alone.
    for name in ('INTENT.md', 'PLAN.md'):
        src = os.path.join(job_worktree, name)
        dst = os.path.join(worktree_path, name)
        if os.path.isfile(src):
            shutil.copy2(src, dst)

    # Write task state
    now = datetime.now(timezone.utc).isoformat()
    task_state = {
        'task_id': task_id,
        'slug': slug,
        'team': team,
        'agent': agent,
        'branch': branch_name,
        'status': 'active',
        'created_at': now,
        'updated_at': now,
    }
    with open(os.path.join(task_dir, 'task.json'), 'w') as f:
        json.dump(task_state, f, indent=2)
        f.write('\n')

    # Update tasks index
    index_path = os.path.join(tasks_dir, 'tasks.json')
    index = _load_index(index_path, 'tasks')
    index['tasks'].append({
        'task_id': task_id,
        'dir': dir_name,
        'status': 'active',
    })
    _save_index(index_path, index)

    return {
        'task_id': task_id,
        'task_dir': task_dir,
        'worktree_path': worktree_path,
        'branch_name': branch_name,
    }


# ── Withdrawal ──────────────────────────────────────────────────────────────

def _kill_pid(pid: int) -> None:
    """Kill a process by PID. SIGTERM with SIGKILL fallback."""
    import time
    if pid <= 0 or pid == os.getpid():
        return
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except PermissionError:
        log.warning('No permission to kill PID %d', pid)
        return
    # Grace period, then SIGKILL if still alive
    for _ in range(5):
        time.sleep(0.1)
        try:
            os.kill(pid, 0)  # probe
        except ProcessLookupError:
            return  # dead
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _read_heartbeat_pid(infra_dir: str) -> int:
    """Read PID from .heartbeat file. Returns -1 if unavailable."""
    hb_path = os.path.join(infra_dir, '.heartbeat')
    try:
        with open(hb_path) as f:
            data = json.load(f)
        return data.get('pid', -1)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return -1


def _set_cfa_withdrawn(infra_dir: str) -> None:
    """Set CfA state to WITHDRAWN, preserving history."""
    cfa_path = os.path.join(infra_dir, '.cfa-state.json')
    try:
        with open(cfa_path) as f:
            cfa = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return

    if cfa.get('state') in ('COMPLETED_WORK', 'WITHDRAWN'):
        return

    cfa['state'] = 'WITHDRAWN'
    cfa['actor'] = 'bridge'
    history = cfa.get('history', [])
    history.append({
        'state': 'WITHDRAWN',
        'action': 'withdraw',
        'actor': 'bridge',
        'timestamp': datetime.now(timezone.utc).isoformat(),
    })
    cfa['history'] = history

    tmp = cfa_path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(cfa, f, indent=2)
        f.write('\n')
    os.replace(tmp, cfa_path)


def _finalize_heartbeat(infra_dir: str) -> None:
    """Set heartbeat status to 'withdrawn'."""
    hb_path = os.path.join(infra_dir, '.heartbeat')
    try:
        with open(hb_path) as f:
            data = json.load(f)
        data['status'] = 'withdrawn'
        tmp = hb_path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(data, f)
        os.replace(tmp, hb_path)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass


async def withdraw_job(*, project_root: str, job_dir: str) -> dict:
    """Withdraw a job: kill processes, remove worktrees, preserve stats.

    1. Kill all processes (job + tasks) via heartbeat PIDs
    2. Set CfA state to WITHDRAWN (preserving history for stats)
    3. Remove git worktrees (job + all tasks)
    4. Update job.json status to 'withdrawn'
    5. Remove from jobs.json index

    The job directory itself is kept (with .cfa-state.json and job.json)
    so the stats pipeline can still discover historical data.
    """
    # Read current CfA state to check if already terminal
    cfa_path = os.path.join(job_dir, '.cfa-state.json')
    try:
        with open(cfa_path) as f:
            cfa = json.load(f)
        if cfa.get('state') in ('COMPLETED_WORK', 'WITHDRAWN'):
            return {'status': 'already_terminal', 'state': cfa['state']}
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # 1. Kill processes — job first, then tasks
    pid = _read_heartbeat_pid(job_dir)
    if pid > 0:
        _kill_pid(pid)

    tasks_dir = os.path.join(job_dir, 'tasks')
    if os.path.isdir(tasks_dir):
        for entry in os.listdir(tasks_dir):
            task_dir = os.path.join(tasks_dir, entry)
            if not os.path.isdir(task_dir):
                continue
            task_pid = _read_heartbeat_pid(task_dir)
            if task_pid > 0:
                _kill_pid(task_pid)
            _set_cfa_withdrawn(task_dir)
            _finalize_heartbeat(task_dir)

    # 2. Set CfA state to WITHDRAWN
    _set_cfa_withdrawn(job_dir)
    _finalize_heartbeat(job_dir)

    # 3. Remove git worktrees (tasks first, then job)
    worktree_paths = []
    if os.path.isdir(tasks_dir):
        for entry in os.listdir(tasks_dir):
            task_wt = os.path.join(tasks_dir, entry, 'worktree')
            if os.path.isdir(task_wt):
                worktree_paths.append(task_wt)
    job_wt = os.path.join(job_dir, 'worktree')
    if os.path.isdir(job_wt):
        worktree_paths.append(job_wt)

    for wt_path in worktree_paths:
        try:
            await _run_git(project_root, 'worktree', 'remove', '--force', wt_path)
        except RuntimeError:
            log.warning('Failed to remove worktree %s', wt_path)

    # 4. Update job.json status
    job_json_path = os.path.join(job_dir, 'job.json')
    try:
        with open(job_json_path) as f:
            job_state = json.load(f)
        job_state['status'] = 'withdrawn'
        job_state['updated_at'] = datetime.now(timezone.utc).isoformat()
        tmp = job_json_path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(job_state, f, indent=2)
            f.write('\n')
        os.replace(tmp, job_json_path)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass

    # 5. Remove from jobs index
    index_path = os.path.join(_jobs_dir(project_root), 'jobs.json')
    index = _load_index(index_path, 'jobs')
    dir_name = os.path.basename(job_dir)
    index['jobs'] = [j for j in index['jobs'] if j.get('dir') != dir_name]
    _save_index(index_path, index)

    return {'status': 'withdrawn'}


# ── Cleanup ──────────────────────────────────────────────────────────────────

async def release_worktree(worktree_path: str) -> None:
    """Remove a git worktree without deleting the parent directory.

    Used at session/dispatch completion to free the git checkout while
    preserving the job/task directory for the dashboard and GC.
    """
    if not os.path.isdir(worktree_path):
        return
    try:
        proc = await asyncio.create_subprocess_exec(
            'git', 'rev-parse', '--path-format=absolute', '--git-common-dir',
            cwd=worktree_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        repo_root = os.path.dirname(stdout.decode().strip())
        await _run_git(repo_root, 'worktree', 'remove', '--force', worktree_path)
    except Exception:
        log.warning('release_worktree: failed to remove %s', worktree_path)


async def cleanup_job(
    *,
    project_root: str,
    job_dir: str,
) -> None:
    """Remove a job and all its tasks — worktrees, state files, and indexes.

    Removes git worktrees first (tasks, then job), then deletes the
    directory tree, then updates the jobs index.
    """
    # Collect all worktree paths to remove (tasks first, then job)
    worktree_paths = []
    tasks_dir = os.path.join(job_dir, 'tasks')
    if os.path.isdir(tasks_dir):
        for entry in os.listdir(tasks_dir):
            task_wt = os.path.join(tasks_dir, entry, 'worktree')
            if os.path.isdir(task_wt):
                worktree_paths.append(task_wt)

    job_wt = os.path.join(job_dir, 'worktree')
    if os.path.isdir(job_wt):
        worktree_paths.append(job_wt)

    # Remove git worktrees
    for wt_path in worktree_paths:
        try:
            await _run_git(project_root, 'worktree', 'remove', '--force', wt_path)
        except RuntimeError:
            log.warning('Failed to remove worktree %s', wt_path)

    # Delete the entire job directory
    if os.path.isdir(job_dir):
        shutil.rmtree(job_dir)

    # Update jobs index
    index_path = os.path.join(_jobs_dir(project_root), 'jobs.json')
    index = _load_index(index_path, 'jobs')
    dir_name = os.path.basename(job_dir)
    index['jobs'] = [j for j in index['jobs'] if j.get('dir') != dir_name]
    _save_index(index_path, index)


# ── GC ───────────────────────────────────────────────────────────────────────

def list_jobs(project_root: str) -> list[dict]:
    """List all jobs for a project by reading their individual job.json files.

    Returns a list of (job_state, job_dir) dicts.  Does not rely on the
    jobs.json index — walks the directory tree directly.
    """
    jobs = []
    base = _jobs_dir(project_root)
    if not os.path.isdir(base):
        return jobs
    for entry in sorted(os.listdir(base)):
        job_dir = os.path.join(base, entry)
        state_path = os.path.join(job_dir, 'job.json')
        if os.path.isfile(state_path):
            try:
                with open(state_path) as f:
                    state = json.load(f)
                state['_job_dir'] = job_dir
                jobs.append(state)
            except (json.JSONDecodeError, OSError):
                log.warning('Failed to read %s', state_path)
    return jobs


def find_job(project_root: str, *, job_id: str | None = None, issue: int | None = None) -> dict | None:
    """Find a job by job_id or issue number. Returns the job state dict or None."""
    for job in list_jobs(project_root):
        if job_id and job.get('job_id') == job_id:
            return job
        if issue is not None and job.get('issue') == issue:
            return job
    return None


def _migrate_one_session(project_root: str, sessions_dir: str,
                         session_id: str) -> None:
    """Migrate a single legacy session into .teaparty/jobs/.

    Legacy sessions may contain empty team subdirectories (research/,
    coding/, etc.) which are moved as-is. These have no state files
    and are not recognized as tasks by _find_job_tasks — which is
    correct, since legacy dispatches predated the task state model.
    """
    session_dir = os.path.join(sessions_dir, session_id)

    # Read task from PROMPT.txt if available
    task = ''
    prompt_path = os.path.join(session_dir, 'PROMPT.txt')
    try:
        with open(prompt_path) as f:
            task = f.read().strip()
    except (FileNotFoundError, OSError):
        pass

    slug = _slugify(task) if task else 'migrated'
    job_id = f'job-{session_id}'
    dir_name = f'{job_id}--{slug}'
    job_dir = os.path.join(_jobs_dir(project_root), dir_name)

    # Move session dir contents into the new job dir
    os.makedirs(os.path.dirname(job_dir), exist_ok=True)
    shutil.move(session_dir, job_dir)

    # Determine terminal status from CfA state
    status = 'active'
    cfa_path = os.path.join(job_dir, '.cfa-state.json')
    try:
        with open(cfa_path) as f:
            cfa = json.load(f)
        cfa_state = cfa.get('state', '')
        if cfa_state in ('COMPLETED_WORK', 'WITHDRAWN'):
            status = 'complete'
    except (OSError, ValueError):
        pass

    # Write job.json
    now = datetime.now(timezone.utc).isoformat()
    job_state = {
        'job_id': job_id,
        'slug': slug,
        'issue': None,
        'branch': '',
        'status': status,
        'created_at': now,
        'updated_at': now,
        'migrated_from': f'.sessions/{session_id}',
    }
    with open(os.path.join(job_dir, 'job.json'), 'w') as f:
        json.dump(job_state, f, indent=2)
        f.write('\n')

    # Update jobs index
    index_path = os.path.join(_jobs_dir(project_root), 'jobs.json')
    index = _load_index(index_path, 'jobs')
    index['jobs'].append({
        'job_id': job_id,
        'dir': dir_name,
        'status': status,
    })
    _save_index(index_path, index)

    log.info('Migrated legacy session %s → %s', session_id, dir_name)


def migrate_legacy_sessions(project_root: str) -> list[str]:
    """Migrate .sessions/ data into .teaparty/jobs/ format.

    For each session directory in {project_root}/.sessions/, creates a
    corresponding job entry under .teaparty/jobs/ and moves the state
    files. Skips sessions that already have a job entry. Removes
    .sessions/ when empty.

    Returns list of migrated session IDs.
    """
    sessions_dir = os.path.join(project_root, '.sessions')
    if not os.path.isdir(sessions_dir):
        return []

    migrated = []
    for session_id in sorted(os.listdir(sessions_dir)):
        session_dir = os.path.join(sessions_dir, session_id)
        if not os.path.isdir(session_dir):
            continue
        # Skip if no CfA state (not a valid session)
        if not os.path.isfile(os.path.join(session_dir, '.cfa-state.json')):
            continue
        # Skip if already migrated
        if find_job(project_root, job_id=f'job-{session_id}'):
            continue

        try:
            _migrate_one_session(project_root, sessions_dir, session_id)
            migrated.append(session_id)
        except Exception:
            log.warning('Failed to migrate session %s', session_id,
                        exc_info=True)

    # Remove .sessions/ if empty
    try:
        if os.path.isdir(sessions_dir) and not os.listdir(sessions_dir):
            os.rmdir(sessions_dir)
    except OSError:
        pass

    return migrated


async def gc_jobs(project_root: str, terminal_statuses: set[str] | None = None) -> list[str]:
    """Remove jobs in terminal states. Returns list of removed job_ids.

    A job is eligible for GC if its status is in terminal_statuses
    (default: {'complete', 'failed'}).
    """
    if terminal_statuses is None:
        terminal_statuses = {'complete', 'failed'}

    removed = []
    for job in list_jobs(project_root):
        if job.get('status') in terminal_statuses:
            job_dir = job['_job_dir']
            job_id = job.get('job_id', os.path.basename(job_dir))
            try:
                await cleanup_job(project_root=project_root, job_dir=job_dir)
                removed.append(job_id)
            except Exception:
                log.warning('GC failed for %s', job_id)
    return removed
