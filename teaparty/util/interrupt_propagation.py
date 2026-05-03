"""Interrupt propagation — cascade intervention decisions to child dispatches.

When a human INTERVENE is delivered to a lead with active child dispatches,
the lead's response (continue/backtrack/withdraw) must cascade to those
children.  This module provides the cascade-withdraw mechanism.

Design: docs/proposals/cfa-extensions/proposal.md — "Interrupt Propagation"
Issue: #247
"""
from __future__ import annotations

import json
import logging
import os
import signal
import time
from datetime import datetime, timezone

_log = logging.getLogger('teaparty.util.interrupt')

# Working-state ordering for backtrack detection.  Terminal states
# (DONE, WITHDRAWN) aren't ordered.
_STATE_ORDER = {'INTENT': 0, 'PLAN': 1, 'EXECUTE': 2}


def is_backtrack(old_state: str, new_state: str) -> bool:
    """Return True if the transition moved to an earlier working state."""
    old_ord = _STATE_ORDER.get(old_state, -1)
    new_ord = _STATE_ORDER.get(new_state, -1)
    return old_ord >= 0 and new_ord >= 0 and new_ord < old_ord


def cascade_withdraw_children(
    infra_dir: str,
) -> list[dict]:
    """Withdraw all active child dispatches.

    Reads the .children registry, kills active PIDs, sets CfA state to
    WITHDRAWN, and finalizes heartbeats.

    Returns a list of dicts describing each child that was withdrawn,
    for event logging.  Skips children that are already terminal.
    """
    from teaparty.bridge.state.heartbeat import (
        read_children,
        read_heartbeat,
        finalize_heartbeat,
    )

    children_path = os.path.join(infra_dir, '.children')
    if not os.path.exists(children_path):
        return []

    children = read_children(children_path)
    withdrawn = []

    for child in children:
        hb_path = child.get('heartbeat', '')
        if not hb_path or not os.path.exists(hb_path):
            continue

        data = read_heartbeat(hb_path)
        status = data.get('status', '')
        if status in ('completed', 'withdrawn'):
            continue

        team = child.get('team', '')
        pid = data.get('pid', 0)

        # Kill the child process
        if pid:
            _kill_pid(pid)

        # Set child CfA state to WITHDRAWN
        child_infra = os.path.dirname(hb_path)
        _set_state_withdrawn(child_infra)

        # Finalize heartbeat
        try:
            finalize_heartbeat(hb_path, 'withdrawn')
        except FileNotFoundError:
            pass

        # Recurse into nested dispatches under this child
        _cascade_nested(child_infra)

        withdrawn.append({
            'team': team,
            'pid': pid,
            'heartbeat': hb_path,
        })
        _log.info(
            'Cascade-withdrew child dispatch: team=%s pid=%s',
            team, pid,
        )

    return withdrawn


def _cascade_nested(
    infra_dir: str,
    depth: int = 0,
) -> None:
    """Recursively withdraw nested dispatches under an infra dir.

    Walks {infra_dir}/{team}/{timestamp}/ looking for .heartbeat files.
    Depth-bounded to 10 levels.
    """
    if depth > 10:
        return

    from teaparty.bridge.state.heartbeat import (
        read_heartbeat,
        finalize_heartbeat,
    )

    from teaparty.cfa.phase_config import get_team_names
    dispatch_teams = get_team_names()

    for team in dispatch_teams:
        team_dir = os.path.join(infra_dir, team)
        if not os.path.isdir(team_dir):
            continue
        try:
            for entry in os.listdir(team_dir):
                dispatch_dir = os.path.join(team_dir, entry)
                if not os.path.isdir(dispatch_dir) or not entry[0].isdigit():
                    continue

                hb_path = os.path.join(dispatch_dir, '.heartbeat')
                if not os.path.exists(hb_path):
                    continue

                data = read_heartbeat(hb_path)
                if data.get('status') in ('completed', 'withdrawn'):
                    continue

                pid = data.get('pid', 0)
                if pid:
                    _kill_pid(pid)

                _set_state_withdrawn(dispatch_dir)

                try:
                    finalize_heartbeat(hb_path, 'withdrawn')
                except FileNotFoundError:
                    pass

                # Recurse deeper
                _cascade_nested(dispatch_dir, depth + 1)
        except OSError:
            continue


def _kill_pid(pid: int) -> None:
    """Kill a process via SIGTERM, with SIGKILL fallback.

    Guards against self-kill.
    """
    if pid == os.getpid():
        return

    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return

    # Brief grace period, then force-kill if still alive
    time.sleep(0.1)
    try:
        os.kill(pid, 0)
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _set_state_withdrawn(infra_dir: str) -> None:
    """Write WITHDRAWN to .cfa-state.json in the given infra dir.

    The phase becomes ``'terminal'`` because WITHDRAWN is a terminal
    state — it has its own phase in the five-state model.
    """
    cfa_path = os.path.join(infra_dir, '.cfa-state.json')
    try:
        with open(cfa_path) as f:
            cfa = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cfa = {}

    cfa['state'] = 'WITHDRAWN'
    cfa['phase'] = 'terminal'
    cfa.setdefault('history', []).append({
        'state': 'WITHDRAWN',
        'action': 'withdraw',
        'timestamp': datetime.now(timezone.utc).isoformat(),
    })

    tmp = cfa_path + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(cfa, f, indent=2)
    os.replace(tmp, cfa_path)
