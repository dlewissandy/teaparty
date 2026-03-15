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
    # Kill session PID
    pid = _read_pid(os.path.join(session.infra_dir, '.running'))
    if pid is not None:
        _kill_pid(pid)

    # Kill dispatch PIDs
    for dispatch in session.dispatches:
        if dispatch.infra_dir:
            dpid = _read_pid(os.path.join(dispatch.infra_dir, '.running'))
            if dpid is not None:
                _kill_pid(dpid)


def _read_pid(running_path: str) -> int | None:
    """Read a PID from a .running sentinel file."""
    try:
        with open(running_path) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError, OSError):
        return None


def _kill_pid(pid: int) -> None:
    """Kill a process and its children via process group, then direct signal."""
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
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
    """Remove sentinel files without touching the worktree."""
    for name in ('.running', '.input-response.fifo', '.input-request.json'):
        try:
            os.unlink(os.path.join(infra_dir, name))
        except FileNotFoundError:
            pass
