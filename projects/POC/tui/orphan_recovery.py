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


def handle_orphan_response(session, response: str) -> str | tuple[str, str]:
    """Interpret user response for orphaned session.

    Returns either:
      - A string message to display, or
      - A tuple ('resume', infra_dir) signalling the TUI should resume the session.
    """
    r = response.strip().lower()
    state = session.cfa_state
    phase = session.cfa_phase or 'execution'

    # Resume — available from any non-terminal orphaned state
    if r in ('resume', 'r'):
        return ('resume', session.infra_dir)

    if state in APPROVAL_GATE_SUCCESSORS:
        # Approval gates require the full ApprovalGate (proxy + human review).
        # 'approve' is not accepted here — it would bypass the CfA transition
        # function, proxy learning, and classification.  Use 'resume' to
        # re-launch the orchestrator which presents the full review UI.
        # Issue #152.
        if r in ('approve', 'yes', 'y', 'ok'):
            return ("Cannot approve from orphan recovery — the review gate "
                    "requires the full orchestrator.  Type 'resume' to "
                    "re-launch the session (you'll get the full review UI), "
                    "or 'abandon' to withdraw.")
        if r in ('abandon', 'withdraw', 'no', 'n'):
            _set_state_direct(session.infra_dir, WITHDRAW_STATE, phase)
            _cleanup_orphan_files(session.infra_dir)
            return 'Session withdrawn and cleaned up.'
        return "Type 'resume' to continue review, or 'abandon' to withdraw."

    # Mid-execution or transition states — resume or abandon
    if r in ('abandon', 'withdraw'):
        _set_state_direct(session.infra_dir, WITHDRAW_STATE, phase)
        _cleanup_orphan_files(session.infra_dir)
        return 'Session withdrawn and cleaned up.'
    return "Type 'resume' to continue or 'abandon' to clean up."


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
