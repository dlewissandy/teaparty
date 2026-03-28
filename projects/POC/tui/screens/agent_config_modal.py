"""Agent configuration modal — placeholder for issue #256."""
from __future__ import annotations

from textual.screen import ModalScreen


def format_agent_config(config: dict) -> str:
    """Format agent config as monospace text. Not yet implemented."""
    raise NotImplementedError


class AgentConfigModal(ModalScreen):
    """Read-only modal showing agent configuration. Not yet implemented."""

    BINDINGS = []

    def __init__(self, agent_config: dict) -> None:
        super().__init__()
        self._agent_config = agent_config
        self._formatted_text = ''
