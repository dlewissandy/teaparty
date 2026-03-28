"""Agent configuration modal — read-only display of agent config from dashboard.

Shows the full agent configuration as monospace text with box-drawing
section headers, matching the design in agent-config-view.md.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static


_SECTION_WIDTH = 35


def _section_header(title: str) -> str:
    """Build a box-drawing section header like: ── Model ──────────────────────────"""
    prefix = f'── {title} '
    return prefix + '─' * max(0, _SECTION_WIDTH - len(prefix))


def format_agent_config(config: dict) -> str:
    """Format an agent config dict as monospace text per agent-config-view.md.

    Handles both full configs (all fields) and minimal configs (name only).
    Missing fields show appropriate defaults or (none).
    """
    lines: list[str] = []

    # Header
    lines.append(f"Agent:  {config.get('name', '?')}")
    lines.append(f"Role:   {config.get('role', '—')}")
    lines.append(f"File:   {config.get('file', '—')}")
    lines.append(f"Status: {config.get('status', '—')}")
    lines.append('')

    # Model
    lines.append(_section_header('Model'))
    lines.append(f"Model:           {config.get('model', '—')}")
    lines.append(f"Max turns:       {config.get('max_turns', '—')}")
    lines.append(f"Permission mode: {config.get('permission_mode', '—')}")
    lines.append('')

    # Tools
    lines.append(_section_header('Tools'))
    tools = config.get('tools', [])
    lines.append('Allowed:')
    if tools:
        for t in tools:
            lines.append(f'  {t}')
    else:
        lines.append('  (none)')
    lines.append('')
    disallowed = config.get('disallowed_tools', [])
    lines.append('Disallowed:')
    if disallowed:
        for t in disallowed:
            lines.append(f'  {t}')
    else:
        lines.append('  (none)')
    lines.append('')

    # MCP Servers
    lines.append(_section_header('MCP Servers'))
    mcp_servers = config.get('mcp_servers', [])
    mcp_tools = config.get('mcp_tools', [])
    if mcp_servers:
        for s in mcp_servers:
            lines.append(f'  {s}')
        lines.append('')
        lines.append('MCP Tools:')
        for t in mcp_tools:
            lines.append(f'  {t}')
    else:
        lines.append('  (none)')
    lines.append('')

    # Hooks
    lines.append(_section_header('Hooks'))
    hooks = config.get('hooks', [])
    if hooks:
        for h in hooks:
            event = h.get('event', '?')
            htype = h.get('type', '?')
            detail = h.get('detail', '')
            lines.append(f'  {event} [{htype}]')
            if detail:
                lines.append(f'    {detail}')
    else:
        lines.append('  (none)')
    lines.append('')

    # System Prompt
    lines.append(_section_header('System Prompt'))
    prompt = config.get('prompt', '')
    if prompt:
        lines.append(prompt)
    else:
        lines.append('(none)')

    return '\n'.join(lines)


class AgentConfigModal(ModalScreen):
    """Read-only modal showing agent configuration as monospace text.

    To modify an agent's configuration, the human uses the office manager
    chat — the Configuration Team handles changes.
    """

    DEFAULT_CSS = """
    AgentConfigModal {
        align: center middle;
    }

    #agent-config-dialog {
        width: 70;
        max-height: 80%;
        padding: 1 2;
        background: $surface;
        border: thick $accent;
    }

    #agent-config-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }

    #agent-config-body {
        height: auto;
        max-height: 100%;
    }

    #agent-config-footer {
        text-align: center;
        color: $text-muted;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding('escape', 'dismiss_modal', 'Close', show=True),
    ]

    def __init__(self, agent_config: dict) -> None:
        super().__init__()
        self._agent_config = agent_config
        self._formatted_text = format_agent_config(agent_config)

    def compose(self) -> ComposeResult:
        name = self._agent_config.get('name', 'Agent')
        yield Vertical(
            Static(f'[bold]{name}[/bold]', id='agent-config-title'),
            VerticalScroll(
                Static(self._formatted_text, id='agent-config-body'),
            ),
            Static(
                'Read-only. To modify, use the office manager chat.',
                id='agent-config-footer',
            ),
            id='agent-config-dialog',
        )

    def action_dismiss_modal(self) -> None:
        self.dismiss()
