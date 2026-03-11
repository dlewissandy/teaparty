"""Extract the latest TodoWrite state from JSONL stream files."""
from __future__ import annotations

import json
import os


def read_todos_from_streams(stream_files: list[str]) -> list[dict]:
    """Scan stream files and return the most recent TodoWrite todo list.

    Each TodoWrite event replaces the full list, so we just want the last one.
    Returns list of dicts with 'content', 'status', 'activeForm' keys.
    """
    latest_todos = []

    for path in stream_files:
        if not os.path.exists(path):
            continue
        try:
            with open(path) as f:
                for line in f:
                    try:
                        ev = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if ev.get('type') != 'assistant':
                        continue
                    for block in ev.get('message', {}).get('content', []):
                        if not isinstance(block, dict):
                            continue
                        if block.get('type') == 'tool_use' and block.get('name') == 'TodoWrite':
                            todos = block.get('input', {}).get('todos', [])
                            if todos:
                                latest_todos = todos
        except OSError:
            continue

    return latest_todos


def format_todo_list(todos: list[dict]) -> str:
    """Format todos as Rich markup with strikethrough for completed items."""
    if not todos:
        return '  [dim](no tasks)[/dim]'

    lines = []
    for item in todos:
        content = item.get('content', '')
        status = item.get('status', '')
        active = item.get('activeForm', '')

        if status == 'completed':
            lines.append(f'  [dim]\u2713 [strike]{content}[/strike][/dim]')
        elif status == 'in_progress':
            display = active or content
            lines.append(f'  [cyan]\u25b6[/cyan] {display}')
        else:  # pending
            lines.append(f'  \u2022 {content}')

    return '\n'.join(lines)
