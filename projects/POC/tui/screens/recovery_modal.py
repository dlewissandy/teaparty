"""Recovery modal — shown when an orphaned session is detected on drilldown."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class RecoveryModal(ModalScreen[str]):
    """Modal overlay: 'Session interrupted — Resume?'

    Returns 'resume' or 'cancel' to the caller via dismiss().
    """

    DEFAULT_CSS = """
    RecoveryModal {
        align: center middle;
    }

    #recovery-dialog {
        width: 50;
        height: auto;
        padding: 1 2;
        background: $surface;
        border: thick $error;
    }

    #recovery-title {
        text-align: center;
        text-style: bold;
        color: $error;
        margin-bottom: 1;
    }

    #recovery-state {
        text-align: center;
        margin-bottom: 1;
    }

    #recovery-buttons {
        align: center middle;
        height: 3;
    }

    #recovery-buttons Button {
        margin: 0 1;
    }
    """

    def __init__(self, cfa_state: str) -> None:
        super().__init__()
        self._cfa_state = cfa_state

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static('Session interrupted', id='recovery-title'),
            Static(f'State: {self._cfa_state}', id='recovery-state'),
            Center(
                Horizontal(
                    Button('Resume', variant='success', id='recovery-resume'),
                    Button('Cancel', variant='default', id='recovery-cancel'),
                    id='recovery-buttons',
                ),
            ),
            id='recovery-dialog',
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'recovery-resume':
            self.dismiss('resume')
        elif event.button.id == 'recovery-cancel':
            self.dismiss('cancel')
