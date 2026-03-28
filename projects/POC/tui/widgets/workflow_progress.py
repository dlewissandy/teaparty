"""WorkflowProgress widget — CfA phase progress indicator for job dashboards."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

# CfA phases matching dashboard spec: INTENT, PLAN, WORK, WORK_ASSERT, DONE
_CFA_PHASES = ['intent', 'plan', 'work', 'work_assert']

# Map CfA states to their display phase
_STATE_TO_PHASE = {
    'INTENT_ASSERT': 'intent',
    'INTENT_ESCALATE': 'intent',
    'INTENT_QUESTION': 'intent',
    'INTENT_IN_PROGRESS': 'intent',
    'PLAN_ASSERT': 'plan',
    'PLANNING_ESCALATE': 'plan',
    'PLANNING_QUESTION': 'plan',
    'PLANNING_IN_PROGRESS': 'plan',
    'WORK_IN_PROGRESS': 'work',
    'WORK_ASSERT': 'work_assert',
    'TASK_ESCALATE': 'work',
    'TASK_ASSERT': 'work_assert',
    'COMPLETED_WORK': 'done',
    'WITHDRAWN': 'withdrawn',
}

# Map engine phase names to display phases
_ENGINE_PHASE_MAP = {
    'intent': 'intent',
    'planning': 'plan',
    'execution': 'work',
}


class WorkflowProgress(Widget):
    """Visual CfA workflow progress: INTENT -> PLAN -> WORK -> DONE."""

    def __init__(self, cfa_phase: str = '', cfa_state: str = '', **kwargs) -> None:
        super().__init__(**kwargs)
        self._cfa_phase = cfa_phase
        self._cfa_state = cfa_state

    def compose(self) -> ComposeResult:
        yield Static(self._format_text(), id='workflow-progress-text')

    def _format_text(self) -> str:
        current_phase = ''
        if self._cfa_state:
            current_phase = _STATE_TO_PHASE.get(self._cfa_state, '')
        if not current_phase and self._cfa_phase:
            current_phase = _ENGINE_PHASE_MAP.get(self._cfa_phase.lower(), self._cfa_phase.lower())

        is_done = self._cfa_state in ('COMPLETED_WORK', 'WITHDRAWN')

        parts = []
        phase_reached = False
        for phase in _CFA_PHASES:
            if is_done:
                parts.append(f'[green]\u2713 {phase.upper()}[/green]')
            elif phase == current_phase:
                parts.append(f'[bold yellow]\u25b6 {phase.upper()}[/bold yellow]')
                phase_reached = True
            elif not phase_reached:
                parts.append(f'[green]\u2713 {phase.upper()}[/green]')
            else:
                parts.append(f'[dim]\u2591 {phase.upper()}[/dim]')

        if is_done:
            if self._cfa_state == 'WITHDRAWN':
                parts.append('[red]\u2717 WITHDRAWN[/red]')
            else:
                parts.append('[green]\u2713 DONE[/green]')
        else:
            parts.append(f'[dim]\u2591 DONE[/dim]')

        return '  \u2192  '.join(parts)

    def update_progress(self, cfa_phase: str, cfa_state: str) -> None:
        """Update the workflow progress display."""
        self._cfa_phase = cfa_phase
        self._cfa_state = cfa_state
        try:
            self.query_one('#workflow-progress-text', Static).update(self._format_text())
        except Exception:
            pass
