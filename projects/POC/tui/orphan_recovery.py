"""Recovery for orphaned sessions.

Orphan recovery offers two actions:
  - Resume: relaunch the orchestrator, which re-enters at the persisted CfA state.
    If at an approval gate, the gate naturally asks for input.
  - Withdraw: mark the session as withdrawn and clean up sentinel files.

The TUI never manipulates CfA state directly — only the orchestrator advances
the state machine. This prevents gate-bypass bugs where 'approve' would jump
past an approval gate without collecting the human's corrections.
"""
import json
import os
from datetime import datetime, timezone

WITHDRAW_STATE = 'WITHDRAWN'


def handle_orphan_response(session, response: str) -> str | tuple[str, str]:
    """Interpret user response for orphaned session.

    Returns either:
      - A string message to display, or
      - A tuple ('resume', infra_dir) signalling the TUI should resume the session.
    """
    r = response.strip().lower()
    phase = session.cfa_phase or 'execution'

    if r in ('resume', 'r'):
        return ('resume', session.infra_dir)

    if r in ('abandon', 'withdraw', 'no', 'n'):
        _withdraw_session(session.infra_dir, phase)
        return 'Session withdrawn and cleaned up.'

    return "Type 'resume' to continue or 'abandon' to withdraw."


def _withdraw_session(infra_dir: str, phase: str) -> None:
    """Mark session as withdrawn and clean up sentinel files."""
    cfa_path = os.path.join(infra_dir, '.cfa-state.json')
    try:
        with open(cfa_path) as f:
            cfa = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cfa = {}
    cfa['state'] = WITHDRAW_STATE
    cfa['phase'] = phase
    cfa['actor'] = 'system'
    cfa.setdefault('history', []).append({
        'state': WITHDRAW_STATE,
        'action': 'orphan-recovery',
        'actor': 'tui-recovery',
        'timestamp': datetime.now(timezone.utc).isoformat(),
    })
    with open(cfa_path, 'w') as f:
        json.dump(cfa, f, indent=2)

    for name in ('.running', '.input-response.fifo', '.input-request.json'):
        try:
            os.unlink(os.path.join(infra_dir, name))
        except FileNotFoundError:
            pass
