"""Agent configuration modal — read-only display of agent config from dashboard.

Shows the full agent configuration as monospace text with box-drawing
section headers, matching the design in agent-config-view.md.
"""
from __future__ import annotations

import os

import yaml

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Static


_SECTION_WIDTH = 35


def read_agent_file(file_path: str) -> dict:
    """Read an agent definition .md file and extract frontmatter + prompt.

    Agent files use YAML frontmatter (between --- delimiters) with the
    system prompt in the body. Returns a dict with extracted fields,
    or empty dict if the file doesn't exist or can't be parsed.

    Recognized frontmatter fields: model, maxTurns, permissionMode,
    allowedTools, disallowedTools, mcpServers.
    """
    if not os.path.isfile(file_path):
        return {}
    try:
        with open(file_path) as f:
            content = f.read()
    except OSError:
        return {}

    # Parse frontmatter
    if not content.startswith('---'):
        # No frontmatter — entire file is the prompt
        return {'prompt': content.strip()} if content.strip() else {}

    parts = content.split('---', 2)
    if len(parts) < 3:
        return {}

    frontmatter_text = parts[1]
    body = parts[2].strip()

    try:
        fm = yaml.safe_load(frontmatter_text)
    except yaml.YAMLError:
        return {}

    if not isinstance(fm, dict):
        return {}

    result: dict = {}
    if 'model' in fm:
        result['model'] = fm['model']
    if 'maxTurns' in fm:
        result['max_turns'] = fm['maxTurns']
    if 'permissionMode' in fm:
        result['permission_mode'] = fm['permissionMode']
    if 'allowedTools' in fm:
        result['tools'] = fm['allowedTools']
    if 'disallowedTools' in fm:
        result['disallowed_tools'] = fm['disallowedTools']
    if 'mcpServers' in fm:
        result['mcp_servers'] = fm['mcpServers']
    if body:
        result['prompt'] = body
    return result


def enrich_agent_config(config: dict, search_dirs: list[str] | None = None) -> dict:
    """Enrich an agent config dict by reading its definition file if available.

    Looks for the agent file in search_dirs (e.g., project .claude/agents/).
    Fields from the file are merged into the config, with existing values
    taking precedence (so workgroup YAML role/model aren't overwritten).
    """
    file_path = config.get('file', '')
    if not file_path:
        return config

    # Try absolute path first
    if os.path.isabs(file_path) and os.path.isfile(file_path):
        file_data = read_agent_file(file_path)
        if file_data:
            merged = dict(file_data)
            merged.update(config)
            return merged

    # Try relative to each search directory
    for d in (search_dirs or []):
        candidate = os.path.join(d, file_path)
        if os.path.isfile(candidate):
            file_data = read_agent_file(candidate)
            if file_data:
                merged = dict(file_data)
                merged.update(config)
                return merged

    return config


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
        height: auto;
        margin-top: 1;
    }

    #agent-config-footer-text {
        color: $text-muted;
    }

    #agent-config-buttons {
        align: right middle;
        height: 3;
    }

    #agent-config-buttons Button {
        margin: 0 1;
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
            Vertical(
                Static(
                    'Read-only. To modify, use the office manager chat.',
                    id='agent-config-footer-text',
                ),
                Horizontal(
                    Button('Modify via Chat', variant='primary', id='agent-config-modify-btn'),
                    Button('Close', variant='default', id='agent-config-close-btn'),
                    id='agent-config-buttons',
                ),
                id='agent-config-footer',
            ),
            id='agent-config-dialog',
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == 'agent-config-modify-btn':
            name = self._agent_config.get('name', 'agent')
            self.dismiss()
            from projects.POC.tui.screens.dashboard_screen import open_chat_window
            open_chat_window(
                self.app,
                conversation='om:new',
                pre_seed=f'I would like to modify the {name} agent',
            )
        elif event.button.id == 'agent-config-close-btn':
            self.dismiss()

    def action_dismiss_modal(self) -> None:
        self.dismiss()
