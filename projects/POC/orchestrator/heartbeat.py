"""Bidirectional heartbeat liveness for dispatch subteams.

Replaces the flat .running PID sentinel with structured .heartbeat files
that carry lifecycle state, parent linkage, and mtime-based liveness.

Design: docs/detailed-design/heartbeat.md
Issue: #149
"""
from __future__ import annotations

import json
import os
import time


def create_heartbeat(
    path: str,
    role: str,
    parent_heartbeat: str = '',
) -> None:
    """Create a heartbeat file in 'starting' state with the orchestrator's PID.

    The file has two phases: created with the orchestrator PID and status
    'starting', then updated to the subprocess PID and status 'running'
    via activate_heartbeat() once the subprocess launches.
    """
    data = {
        'pid': os.getpid(),
        'parent_heartbeat': parent_heartbeat,
        'role': role,
        'started': _process_create_time(os.getpid()),
        'status': 'starting',
    }
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f)
    os.replace(tmp, path)


def activate_heartbeat(path: str, subprocess_pid: int) -> None:
    """Transition heartbeat from 'starting' to 'running' with the subprocess PID."""
    data = read_heartbeat(path)
    data['pid'] = subprocess_pid
    data['status'] = 'running'
    data['started'] = _process_create_time(subprocess_pid)
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f)
    os.replace(tmp, path)


def touch_heartbeat(path: str) -> None:
    """Update the heartbeat mtime without rewriting contents."""
    os.utime(path)


def finalize_heartbeat(path: str, status: str) -> None:
    """Write terminal status ('completed' or 'withdrawn') to the heartbeat.

    The file remains on disk so the recovery scan can distinguish
    'finished' from 'never existed'.
    """
    data = read_heartbeat(path)
    data['status'] = status
    tmp = path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(data, f)
    os.replace(tmp, path)


def read_heartbeat(path: str) -> dict:
    """Read and parse a heartbeat file. Returns empty dict if missing/corrupt."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def is_heartbeat_stale(path: str, threshold: int = 120) -> bool:
    """Return True if the heartbeat is stale (dead process, not terminal).

    A heartbeat is stale when:
      - mtime is older than threshold seconds, AND
      - the PID in the file is no longer alive

    Terminal heartbeats (completed/withdrawn) are never stale.
    Missing files are not stale (they never existed).
    """
    data = read_heartbeat(path)
    if not data:
        return False

    if data.get('status') in ('completed', 'withdrawn'):
        return False

    age = time.time() - os.path.getmtime(path)
    if age < threshold:
        return False

    pid = data.get('pid', 0)
    if not pid:
        return True

    return not _is_pid_alive(pid)


# ── Children registry ─────────────────────────────────────────────────────────

def register_child(
    children_path: str,
    heartbeat: str,
    team: str,
    task_id: str | None = None,
) -> None:
    """Append a child entry to the .children JSONL registry."""
    entry = {
        'heartbeat': heartbeat,
        'team': team,
        'task_id': task_id,
        'status': 'active',
    }
    with open(children_path, 'a') as f:
        f.write(json.dumps(entry) + '\n')


def read_children(children_path: str) -> list[dict]:
    """Read all entries from the .children JSONL registry."""
    try:
        with open(children_path) as f:
            return [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        return []


def compact_children(children_path: str) -> None:
    """Rewrite .children, removing entries whose heartbeats are terminal."""
    children = read_children(children_path)
    if not children:
        return

    keep = []
    for child in children:
        hb_path = child.get('heartbeat', '')
        if not hb_path:
            continue
        data = read_heartbeat(hb_path)
        if data.get('status') in ('completed', 'withdrawn'):
            continue
        keep.append(child)

    tmp = children_path + '.tmp'
    with open(tmp, 'w') as f:
        for entry in keep:
            f.write(json.dumps(entry) + '\n')
    os.replace(tmp, children_path)


def scan_children(children_path: str) -> dict[str, list[dict]]:
    """Scan .children registry and classify each child's state.

    Returns dict with three lists:
      - completed: terminal-success heartbeats (ready to merge)
      - dead: non-terminal heartbeats with stale mtime and dead PID
      - live: heartbeats that are still fresh or have a live PID
    """
    result: dict[str, list[dict]] = {'completed': [], 'dead': [], 'live': []}
    children = read_children(children_path)

    for child in children:
        hb_path = child.get('heartbeat', '')
        if not hb_path or not os.path.exists(hb_path):
            result['dead'].append(child)
            continue

        data = read_heartbeat(hb_path)
        status = data.get('status', '')

        if status in ('completed', 'withdrawn'):
            result['completed'].append(child)
        elif is_heartbeat_stale(hb_path):
            result['dead'].append(child)
        else:
            result['live'].append(child)

    return result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _process_create_time(pid: int) -> float:
    """Return the process creation time, or current time as fallback."""
    try:
        import psutil
        return psutil.Process(pid).create_time()
    except Exception:
        return time.time()


def _is_pid_alive(pid: int) -> bool:
    """Check if a PID is alive."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False
