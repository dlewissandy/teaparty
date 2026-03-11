"""Recovery for orphaned sessions — direct .cfa-state.json transitions."""
import json
import os
from datetime import datetime, timezone

APPROVAL_GATE_SUCCESSORS = {
    'WORK_ASSERT':   ('COMPLETED_WORK', 'execution'),
    'PLAN_ASSERT':   ('PLAN', 'planning'),
    'INTENT_ASSERT': ('INTENT', 'intent'),
}
WITHDRAW_STATE = 'WITHDRAWN'


def handle_orphan_response(session, response: str) -> str:
    """Interpret user response for orphaned session. Returns message to show."""
    r = response.strip().lower()
    state = session.cfa_state
    phase = session.cfa_phase or 'execution'

    if state in APPROVAL_GATE_SUCCESSORS:
        if r in ('approve', 'yes', 'y', 'ok'):
            successor, succ_phase = APPROVAL_GATE_SUCCESSORS[state]
            _set_state_direct(session.infra_dir, successor, succ_phase)
            _cleanup_orphan_files(session.infra_dir)
            if state == 'WORK_ASSERT':
                return f'Session completed. Advanced to {successor}.'
            return (f'Session advanced to {successor}. '
                    'No orchestrator is running — start a new session to continue.')
        if r in ('abandon', 'withdraw', 'no', 'n'):
            _set_state_direct(session.infra_dir, WITHDRAW_STATE, phase)
            _cleanup_orphan_files(session.infra_dir)
            return 'Session withdrawn and cleaned up.'
        return "Type 'approve' to advance or 'abandon' to withdraw."

    # Mid-execution or transition states — abandon only
    if r in ('abandon', 'withdraw'):
        _set_state_direct(session.infra_dir, WITHDRAW_STATE, phase)
        _cleanup_orphan_files(session.infra_dir)
        return 'Session withdrawn and cleaned up.'
    return "Type 'abandon' to clean up this interrupted session."


def _set_state_direct(infra_dir: str, new_state: str, phase: str) -> None:
    cfa_path = os.path.join(infra_dir, '.cfa-state.json')
    try:
        with open(cfa_path) as f:
            cfa = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        cfa = {}
    cfa['state'] = new_state
    cfa['phase'] = phase
    cfa['actor'] = 'system'
    cfa.setdefault('history', []).append({
        'state': new_state,
        'action': 'orphan-recovery',
        'actor': 'tui-recovery',
        'timestamp': datetime.now(timezone.utc).isoformat(),
    })
    with open(cfa_path, 'w') as f:
        json.dump(cfa, f, indent=2)


def _cleanup_orphan_files(infra_dir: str) -> None:
    for name in ('.running', '.input-response.fifo', '.input-request.json'):
        try:
            os.unlink(os.path.join(infra_dir, name))
        except FileNotFoundError:
            pass
