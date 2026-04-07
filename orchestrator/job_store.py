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


# ── Job operations ───────────────────────────────────────────────────────────

async def create_job(
    *,
    project_root: str,
    task: str,
    issue: int | None = None,
) -> dict:
    """Create a new job with a git worktree under {project_root}/.teaparty/jobs/.

    Returns dict with: job_id, job_dir, worktree_path, branch_name.
    """
    job_id = f'job-{_short_id()}'
    slug = _slugify(task)
    dir_name = f'{job_id}--{slug}'
    job_dir = os.path.join(_jobs_dir(project_root), dir_name)
    worktree_path = os.path.join(job_dir, 'worktree')
    branch_name = dir_name

    os.makedirs(job_dir, exist_ok=True)

    # Create git worktree
    await _run_git(project_root, 'worktree', 'add', '-b', branch_name, worktree_path)

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
) -> dict:
    """Create a new task with a git worktree under the parent job.

    Returns dict with: task_id, task_dir, worktree_path, branch_name.
    """
    task_id = f'task-{_short_id()}'
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


# ── Cleanup ──────────────────────────────────────────────────────────────────

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
