"""Confirmation modal for session withdrawal."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.screen import ModalScreen
from textual.widgets import Static


class ConfirmWithdrawScreen(ModalScreen[bool]):
    """Simple y/n confirmation for withdrawing a session."""

    BINDINGS = [
        Binding('y', 'confirm', 'Yes', show=True),
        Binding('n', 'cancel', 'No', show=True),
        Binding('escape', 'cancel', 'Cancel', show=False),
    ]

    def __init__(self, session_id: str):
        super().__init__()
        self.session_id = session_id

    def compose(self) -> ComposeResult:
        yield Center(
            Vertical(
                Static(
                    f'[bold]Withdraw session {self.session_id}?[/bold]\n\n'
                    'This will stop all agents. The worktree will be preserved.\n\n'
                    '[y] Yes  [n] No',
                    id='confirm-text',
                ),
                id='confirm-dialog',
            ),
        )

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
