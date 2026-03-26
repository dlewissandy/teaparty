"""Withdraw a running session — kill agents, set WITHDRAWN, clean up."""
from __future__ import annotations

import asyncio
import json
import os
import signal
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from projects.POC.tui.state_reader import SessionState
    from projects.POC.orchestrator.events import EventBus


_TERMINAL_STATES = frozenset({'COMPLETED_WORK', 'WITHDRAWN'})


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
    2. Kill all subprocess PIDs (session + dispatches)
    3. Set CfA state to WITHDRAWN
    4. Clean up sentinel files
    5. Emit SESSION_COMPLETED event
    """
    if session.cfa_state in _TERMINAL_STATES:
        return False

    # 1. Cancel in-process orchestrator task
    if in_process_task is not None and not in_process_task.done():
        in_process_task.cancel()

    # 2. Kill all running subprocesses
    _kill_session_processes(session)

    # 3. Set CfA state to WITHDRAWN
    _set_state_withdrawn(session.infra_dir, session.cfa_phase or 'execution')

    # 4. Clean up sentinel files (leave worktree intact)
    _cleanup_sentinels(session.infra_dir)

    # 5. Emit SESSION_COMPLETED
    if event_bus is not None:
        from projects.POC.orchestrator.events import Event, EventType
        await event_bus.publish(Event(
            type=EventType.SESSION_COMPLETED,
            data={'terminal_state': 'WITHDRAWN'},
            session_id=session.session_id,
        ))

    return True


def _kill_session_processes(session: SessionState) -> None:
    """Kill the session's main process and all dispatch processes."""
    # Kill session PID (issue #149: read from .heartbeat, fallback .running)
    pid = _read_pid_from_infra(session.infra_dir)
    if pid is not None:
        _kill_pid(pid)

    # Kill dispatch PIDs
    for dispatch in session.dispatches:
        if dispatch.infra_dir:
            dpid = _read_pid_from_infra(dispatch.infra_dir)
            if dpid is not None:
                _kill_pid(dpid)


def _read_pid_from_infra(infra_dir: str) -> int | None:
    """Read a PID from .heartbeat or .running sentinel in an infra dir.

    Issue #149: prefers .heartbeat (structured JSON), falls back to .running
    (flat PID file) for backward compatibility.
    """
    hb_path = os.path.join(infra_dir, '.heartbeat')
    if os.path.exists(hb_path):
        try:
            from projects.POC.orchestrator.heartbeat import read_heartbeat
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
    """Kill a process and its children via process group, then direct signal.

    Guards against self-kill: when a session runs in-process, .heartbeat
    contains the TUI's own PID.  Killing our own process group would
    crash the TUI (issue #159).
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
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass
        return

    try:
        os.killpg(target_pgid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            pass


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
        'actor': 'tui-withdraw',
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
            from projects.POC.orchestrator.heartbeat import finalize_heartbeat
            finalize_heartbeat(hb_path, 'withdrawn')
        except Exception:
            pass

    # Remove legacy .running and IPC files
    for name in ('.running', '.input-response.fifo', '.input-request.json'):
        try:
            os.unlink(os.path.join(infra_dir, name))
        except FileNotFoundError:
            pass
