"""MCP intervention tools for the office manager.

Team-lead authority tools that operate on session infrastructure files.
These are distinct from gate authority (which belongs to the proxy).

Tools:
  withdraw_session      — set CfA state to WITHDRAWN, finalize heartbeat
  pause_dispatch        — pause an active dispatch (heartbeat → paused)
  resume_dispatch       — resume a paused dispatch (heartbeat → running)
  reprioritize_dispatch — change dispatch priority (heartbeat priority field)

Issues #201, #249.
"""
from __future__ import annotations

import json
import os

from teaparty.cfa.statemachine.cfa_state import TERMINAL_STATES


def withdraw_session(infra_dir: str) -> dict:
    """Withdraw a session by setting CfA state to WITHDRAWN.

    Also finalizes the heartbeat to 'withdrawn' so the watchdog
    treats it as terminal.

    Returns a status dict: {status: 'withdrawn' | 'already_terminal' | 'error', ...}
    """
    cfa_path = os.path.join(infra_dir, '.cfa-state.json')
    hb_path = os.path.join(infra_dir, '.heartbeat')

    # Check current state
    try:
        with open(cfa_path) as f:
            cfa = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {'status': 'error', 'reason': f'CfA state not found: {cfa_path}'}

    # Already terminal — no-op
    if cfa.get('state') in TERMINAL_STATES:
        return {'status': 'already_terminal', 'state': cfa['state']}

    # Record pre-transition state, then set to WITHDRAWN
    prior_state = cfa.get('state', '')
    cfa['state'] = 'WITHDRAWN'
    cfa['phase'] = 'terminal'
    history_entry = {
        'state': prior_state,
        'action': 'withdraw',
        'actor': 'office-manager',
    }
    cfa.setdefault('history', []).append(history_entry)

    tmp = cfa_path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(cfa, f)
    os.replace(tmp, cfa_path)

    # Finalize heartbeat
    _set_heartbeat_status(hb_path, 'withdrawn')

    return {'status': 'withdrawn'}


def pause_dispatch(infra_dir: str) -> dict:
    """Pause an active dispatch by setting heartbeat status to 'paused'.

    A paused dispatch won't launch new phases. Work already in progress
    completes but no new work starts.

    Returns a status dict: {status: 'paused' | 'not_running' | 'error', ...}
    """
    hb_path = os.path.join(infra_dir, '.heartbeat')

    try:
        with open(hb_path) as f:
            hb = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {'status': 'error', 'reason': f'Heartbeat not found: {hb_path}'}

    if hb.get('status') not in ('running', 'starting'):
        return {'status': 'not_running', 'current_status': hb.get('status', 'unknown')}

    _set_heartbeat_status(hb_path, 'paused')
    return {'status': 'paused'}


def resume_dispatch(infra_dir: str) -> dict:
    """Resume a paused dispatch by setting heartbeat status back to 'running'.

    Returns a status dict: {status: 'resumed' | 'not_paused' | 'error', ...}
    """
    hb_path = os.path.join(infra_dir, '.heartbeat')

    try:
        with open(hb_path) as f:
            hb = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {'status': 'error', 'reason': f'Heartbeat not found: {hb_path}'}

    if hb.get('status') != 'paused':
        return {'status': 'not_paused', 'current_status': hb.get('status', 'unknown')}

    _set_heartbeat_status(hb_path, 'running')
    return {'status': 'resumed'}


def reprioritize_dispatch(infra_dir: str, priority: str) -> dict:
    """Change the priority of a dispatch by updating the heartbeat.

    Only running or paused dispatches can be reprioritized.

    Returns a status dict: {status: 'reprioritized' | 'not_running' | 'error', ...}
    """
    hb_path = os.path.join(infra_dir, '.heartbeat')

    try:
        with open(hb_path) as f:
            hb = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {'status': 'error', 'reason': f'Heartbeat not found: {hb_path}'}

    if hb.get('status') not in ('running', 'starting', 'paused'):
        return {'status': 'not_running', 'current_status': hb.get('status', 'unknown')}

    old_priority = hb.get('priority', 'normal')
    hb['priority'] = priority
    tmp = hb_path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(hb, f)
    os.replace(tmp, hb_path)

    return {
        'status': 'reprioritized',
        'old_priority': old_priority,
        'new_priority': priority,
    }


def _set_heartbeat_status(hb_path: str, status: str) -> None:
    """Atomically update the heartbeat status field."""
    try:
        with open(hb_path) as f:
            hb = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return

    hb['status'] = status
    tmp = hb_path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(hb, f)
    os.replace(tmp, hb_path)
