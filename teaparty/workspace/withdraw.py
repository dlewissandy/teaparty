"""Withdraw a running session — kill agents, set WITHDRAWN, clean up."""
from __future__ import annotations

import asyncio
import json
import os
import signal
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from teaparty.bridge.state.reader import SessionState
    from teaparty.messaging.bus import EventBus


_TERMINAL_STATES = frozenset({'COMPLETED_WORK', 'WITHDRAWN'})

def _dispatch_teams() -> tuple[str, ...]:
    """Team names from phase-config.json (cached in phase_config module)."""
    from teaparty.cfa.phase_config import get_team_names
    return get_team_names()


async def withdraw_session(
    session: SessionState,
    *,
    event_bus: EventBus | None = None,
    in_process_task: asyncio.Task | None = None,
) -> bool:
    """Withdraw a session: kill processes, set WITHDRAWN, clean up.

    Returns True if the session was withdrawn, False if it was already terminal.

    Order of operations (kill-then-write) prevents race conditions:
    1. Cancel in-process task (if any)
    2. Publish WITHDRAW event (formal CfA event)
    3. Kill all subprocess PIDs (session + dispatches, recursively)
    4. Set CfA state to WITHDRAWN (session + nested dispatches)
    5. Clean up sentinel files
    6. Emit learning signal (LOG event)
    7. Emit SESSION_COMPLETED event
    """
    if session.cfa_state in _TERMINAL_STATES:
        return False

    # 1. Cancel in-process orchestrator task
    if in_process_task is not None and not in_process_task.done():
        in_process_task.cancel()

    # 2. Publish WITHDRAW event (before killing, so subscribers see intent)
    if event_bus is not None:
        from teaparty.messaging.bus import Event, EventType
        await event_bus.publish(Event(
            type=EventType.WITHDRAW,
            data={
                'phase': session.cfa_phase or 'execution',
                'state': session.cfa_state or '',
                'task': session.task or '',
            },
            session_id=session.session_id,
        ))

    # 3. Kill all running subprocesses (recursive)
    _kill_session_processes(session)

    # 4. Set CfA state to WITHDRAWN (session + nested dispatches)
    phase = session.cfa_phase or 'execution'
    _set_state_withdrawn(session.infra_dir, phase)
    for dispatch in session.dispatches:
        if dispatch.infra_dir:
            _set_state_withdrawn_recursive(dispatch.infra_dir, phase)

    # 5. Clean up sentinel files (leave worktree intact)
    _cleanup_sentinels(session.infra_dir)

    # 6. Record learning signal (memory chunk + LOG event)
    _record_withdrawal_memory_chunk(session, phase)
    if event_bus is not None:
        from teaparty.messaging.bus import Event, EventType
        await event_bus.publish(Event(
            type=EventType.LOG,
            data={
                'message': (
                    f'Withdrawal learning signal: session withdrawn during '
                    f'{phase} phase, task: {session.task or "(unknown)"}'
                ),
            },
            session_id=session.session_id,
        ))

    # 7. Emit SESSION_COMPLETED
    if event_bus is not None:
        from teaparty.messaging.bus import Event, EventType
        await event_bus.publish(Event(
            type=EventType.SESSION_COMPLETED,
            data={'terminal_state': 'WITHDRAWN'},
            session_id=session.session_id,
        ))

    return True


def _kill_session_processes(session: SessionState) -> None:
    """Kill the session's main process and all dispatch processes (recursive)."""
    # Kill session PID (issue #149: read from .heartbeat, fallback .running)
    pid = _read_pid_from_infra(session.infra_dir)
    if pid is not None:
        _kill_pid(pid)

    # Kill dispatch PIDs (including nested sub-dispatches)
    for dispatch in session.dispatches:
        if dispatch.infra_dir:
            dpid = _read_pid_from_infra(dispatch.infra_dir)
            if dpid is not None:
                _kill_pid(dpid)
            # Recurse into nested dispatches
            _kill_nested_dispatches(dispatch.infra_dir)


def _kill_nested_dispatches(infra_dir: str, depth: int = 0) -> None:
    """Recursively kill processes in nested dispatch directories.

    Walks {infra_dir}/{team}/{timestamp}/ looking for .running or .heartbeat
    files, then recurses into those dirs for further nesting.

    Depth-bounded to 10 levels to guard against symlink cycles.
    """
    if depth > 10:
        return

    for team in _dispatch_teams():
        team_dir = os.path.join(infra_dir, team)
        if not os.path.isdir(team_dir):
            continue
        try:
            for entry in os.listdir(team_dir):
                dispatch_dir = os.path.join(team_dir, entry)
                if not os.path.isdir(dispatch_dir) or not entry[0].isdigit():
                    continue
                pid = _read_pid_from_infra(dispatch_dir)
                if pid is not None:
                    _kill_pid(pid)
                # Recurse deeper
                _kill_nested_dispatches(dispatch_dir, depth + 1)
        except OSError:
            continue


def _set_state_withdrawn_recursive(infra_dir: str, phase: str, depth: int = 0) -> None:
    """Set WITHDRAWN on an infra dir and recurse into nested dispatch dirs."""
    _set_state_withdrawn(infra_dir, phase)
    _cleanup_sentinels(infra_dir)

    if depth > 10:
        return

    for team in _dispatch_teams():
        team_dir = os.path.join(infra_dir, team)
        if not os.path.isdir(team_dir):
            continue
        try:
            for entry in os.listdir(team_dir):
                dispatch_dir = os.path.join(team_dir, entry)
                if not os.path.isdir(dispatch_dir) or not entry[0].isdigit():
                    continue
                _set_state_withdrawn_recursive(dispatch_dir, phase, depth + 1)
        except OSError:
            continue


def _record_withdrawal_memory_chunk(session: SessionState, phase: str) -> None:
    """Record the withdrawal as a memory chunk in the proxy memory DB.

    Per the CfA extensions design, both INTERVENE and WITHDRAW are recorded
    as memory chunks — they capture moments where the human overrode agent
    behavior, which is what the proxy needs to learn from.

    Derives the proxy DB path from infra_dir (two levels up = project dir).
    Fails silently if the DB doesn't exist or isn't writable.
    """
    try:
        import uuid
        from teaparty.proxy.memory import (
            MemoryChunk, open_proxy_db, store_chunk,
        )

        # infra_dir = {project_root}/.teaparty/jobs/job-{id}--{slug}/
        # project_root is 3 levels up from job_dir
        from teaparty.workspace.job_store import project_root_from_job_dir
        project_dir = project_root_from_job_dir(session.infra_dir)
        db_path = os.path.join(project_dir, '.proxy-memory.db')
        if not os.path.isfile(db_path):
            return

        conn = open_proxy_db(db_path)
        try:
            chunk = MemoryChunk(
                id=str(uuid.uuid4()),
                type='withdrawal',
                state=session.cfa_state or 'UNKNOWN',
                task_type=session.project or '',
                outcome='withdrawn',
                content=(
                    f'Human withdrew session during {phase} phase. '
                    f'Task: {session.task or "(unknown)"}. '
                    f'CfA state at withdrawal: {session.cfa_state or "unknown"}.'
                ),
            )
            store_chunk(conn, chunk)
        finally:
            conn.close()
    except Exception:
        pass  # Best-effort — don't let DB failure block withdrawal


def _read_pid_from_infra(infra_dir: str) -> int | None:
    """Read a PID from .heartbeat or .running sentinel in an infra dir.

    Issue #149: prefers .heartbeat (structured JSON), falls back to .running
    (flat PID file) for backward compatibility.
    """
    hb_path = os.path.join(infra_dir, '.heartbeat')
    if os.path.exists(hb_path):
        try:
            from teaparty.bridge.state.heartbeat import read_heartbeat
            data = read_heartbeat(hb_path)
            pid = data.get('pid')
            if pid:
                return int(pid)
        except Exception:
            pass

    # Fallback to .running
    running_path = os.path.join(infra_dir, '.running')
    try:
        with open(running_path) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError, OSError):
        return None


def _kill_pid(pid: int) -> None:
    """Kill a process via SIGTERM, falling back to SIGKILL.

    Per the CfA extensions spec: "sends SIGTERM down the tree, falling
    back to SIGKILL."

    Guards against self-kill: when a session runs in-process, .heartbeat
    contains the orchestrator's own PID.  Killing our own process group would
    terminate the caller (issue #159).
    """
    if pid == os.getpid():
        return

    try:
        target_pgid = os.getpgid(pid)
    except (ProcessLookupError, PermissionError, OSError):
        return

    # If the target shares our process group, skip killpg (it would
    # kill us too) and fall back to direct signal on just the PID.
    if target_pgid == os.getpgid(os.getpid()):
        _sigterm_then_sigkill(pid)
        return

    try:
        os.killpg(target_pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        _sigterm_then_sigkill(pid)
        return

    # SIGKILL fallback: if process survived SIGTERM, force-kill
    _sigkill_if_alive(pid)


def _sigterm_then_sigkill(pid: int) -> None:
    """Send SIGTERM to a single PID, then SIGKILL if it survives."""
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return
    _sigkill_if_alive(pid)


def _sigkill_if_alive(pid: int) -> None:
    """If pid is still alive after a short grace period, send SIGKILL."""
    import time
    time.sleep(0.1)
    try:
        os.kill(pid, 0)  # Check if still alive
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass  # Already dead or inaccessible


def _set_state_withdrawn(infra_dir: str, phase: str) -> None:
    """Write WITHDRAWN to .cfa-state.json."""
    cfa_path = os.path.join(infra_dir, '.cfa-state.json')
    try:
        with open(cfa_path) as f:
            cfa = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cfa = {}
    cfa['state'] = 'WITHDRAWN'
    cfa['phase'] = phase
    cfa['actor'] = 'system'
    cfa.setdefault('history', []).append({
        'state': 'WITHDRAWN',
        'action': 'withdraw',
        'actor': 'orchestrator-withdraw',
        'timestamp': datetime.now(timezone.utc).isoformat(),
    })
    with open(cfa_path, 'w') as f:
        json.dump(cfa, f, indent=2)


def _cleanup_sentinels(infra_dir: str) -> None:
    """Finalize heartbeat and remove sentinel files (issue #149)."""
    # Finalize heartbeat as withdrawn
    hb_path = os.path.join(infra_dir, '.heartbeat')
    if os.path.exists(hb_path):
        try:
            from teaparty.bridge.state.heartbeat import finalize_heartbeat
            finalize_heartbeat(hb_path, 'withdrawn')
        except Exception:
            pass

    # Remove legacy .running and IPC files
    for name in ('.running', '.input-response.fifo', '.input-request.json'):
        try:
            os.unlink(os.path.join(infra_dir, name))
        except FileNotFoundError:
            pass
