"""Formats JSONL stream events as Rich Text for the activity log.

Ports the logic from stream/display_filter.py to produce Rich Text objects
instead of ANSI-colored stdout. Reuses stream/_common.py utilities.
"""
from __future__ import annotations

import re

from rich.text import Text

# Import shared utilities from the existing stream package
try:
    from stream._common import (
        agent_label,
        register_lead_session,
        register_task_agent,
        shorten_worktree_path,
        parse_dispatch_command,
    )
except ImportError:
    # Fallback stubs if import path isn't available
    def agent_label(ev):
        parent = ev.get('parent_tool_use_id')
        sid = ev.get('session_id', '')
        return sid[:8] if sid else 'agent'

    def register_lead_session(ev):
        pass

    def register_task_agent(tool_id, tool_input):
        pass

    def shorten_worktree_path(path):
        return re.sub(r'.*/\.worktrees/[^/]+/', '...//', path)

    def parse_dispatch_command(cmd):
        team_match = re.search(r'--team\s+(\S+)', cmd)
        task_match = re.search(r'--task\s+"([^"]*)"', cmd)
        team = team_match.group(1) if team_match else '?'
        task = task_match.group(1) if task_match else cmd[:200]
        return team, task


THINK_MAX = 120


class EventParser:
    """Parse JSONL events and produce Rich Text for the activity log."""

    def __init__(self, show_progress: bool = False):
        self.show_progress = show_progress
        self.prev_todos: dict[str, str] = {}

    def format_event(self, event: dict) -> Text | None:
        """Process one JSONL event. Returns Rich Text or None to skip."""
        t = event.get('type', '')
        sub = event.get('subtype', '')
        label = agent_label(event)

        # System events — capture lead session_id
        if t == 'system':
            if sub == 'init':
                register_lead_session(event)
                agents = event.get('agents', [])
                if agents:
                    text = Text()
                    text.append(f'[init] agents: {", ".join(agents)}', style='dim')
                    return text
            return None

        # Assistant messages
        if t == 'assistant':
            content = event.get('message', {}).get('content', [])
            # Check if this event has a SendMessage or Task — if so, prefer
            # those over raw text blocks (which are internal reasoning that
            # gets repeated in the broadcast).  Issue #174.
            has_communication = any(
                isinstance(b, dict)
                and b.get('type') == 'tool_use'
                and b.get('name') in ('SendMessage', 'Task')
                for b in content
            )
            results = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                bt = block.get('type', '')
                # Suppress text blocks when a SendMessage/Task follows
                if bt == 'text' and has_communication:
                    continue
                result = self._format_block(bt, block, label)
                if result is not None:
                    results.append(result)
            # Return the first non-None result (one event usually has one display line)
            return results[0] if results else None

        # Tool results — only show errors
        if t == 'tool_result':
            if event.get('is_error', False):
                tool = event.get('tool', '')
                output = event.get('output', '')[:200]
                text = Text()
                text.append(f'  [error] ', style='bold red')
                text.append(f'{tool}: {output}')
                return text
            return None

        # Final result
        if t == 'result':
            result = event.get('result', '')[:500]
            text = Text()
            text.append('\n\u2500\u2500 done \u2500\u2500\n', style='dim')
            text.append(result)
            return text

        return None

    def _format_block(self, bt: str, block: dict, label: str) -> Text | None:
        """Format a single content block from an assistant message."""

        # Thinking blocks
        if bt == 'thinking' and self.show_progress:
            thinking = block.get('thinking', '').strip()
            if thinking:
                excerpt = thinking[:THINK_MAX].replace('\n', ' ')
                if len(thinking) > THINK_MAX:
                    excerpt += '...'
                text = Text()
                text.append(f'  \u2bf7 {excerpt}', style='dim')
                return text
            return None

        # Tool use
        if bt == 'tool_use':
            return self._format_tool_use(block, label)

        # Text blocks (agent output text)
        if bt == 'text':
            content = block.get('text', '').strip()
            if content:
                text = Text()
                text.append(f'[{label}] ', style='bold cyan')
                # Only show first few lines
                lines = content.split('\n')
                if len(lines) > 3:
                    text.append('\n'.join(lines[:3]) + '...')
                else:
                    text.append(content)
                return text
            return None

        return None

    def _format_tool_use(self, block: dict, label: str) -> Text | None:
        """Format a tool_use block."""
        tool_name = block.get('name', '')
        tool_input = block.get('input', {})
        tool_id = block.get('id', '')
        text = Text()

        # Task dispatch — always shown
        if tool_name == 'Task':
            register_task_agent(tool_id, tool_input)
            agent_type = tool_input.get('subagent_type', '')
            name = tool_input.get('name', '')
            desc = tool_input.get('description', '')
            prompt = tool_input.get('prompt', '')
            recipient = name or agent_type or 'subagent'
            body = desc or ''
            if prompt:
                first_line = prompt.strip().split('\n')[0][:200]
                body = f'{body} \u2014 {first_line}' if body else first_line
            text.append(f'[{label}]', style='bold cyan')
            text.append(f' @{recipient}: {body}')
            return text

        # SendMessage — always shown
        if tool_name == 'SendMessage':
            msg_type = tool_input.get('type', 'message')
            recipient = tool_input.get('recipient', '')
            content = tool_input.get('content', '')
            text.append(f'[{label}]', style='bold cyan')
            if msg_type == 'broadcast':
                text.append(f' @all: {content}')
            elif msg_type == 'shutdown_request':
                text.append(f' @{recipient}: shutdown')
            elif msg_type == 'shutdown_response':
                approve = tool_input.get('approve', False)
                text.append(f' shutdown {"approved" if approve else "rejected"}')
            else:
                text.append(f' @{recipient}: {content}')
            return text

        # Bash dispatch.sh — always shown
        if tool_name == 'Bash':
            cmd = tool_input.get('command', '')
            if 'dispatch.sh' in cmd or 'relay.sh' in cmd:
                team, task = parse_dispatch_command(cmd)
                text.append(f'[{label}]', style='bold cyan')
                text.append(f' @{team}-team: {task}')
                return text
            elif self.show_progress:
                desc = tool_input.get('description', '')
                short = desc or cmd.split('\n')[0][:120]
                text.append(f'  \u2192 Bash: {short}', style='dim')
                return text
            return None

        # TodoWrite — show progress changes
        if tool_name == 'TodoWrite' and self.show_progress:
            return self._format_todos(tool_input)

        # Other tools (--show-progress only)
        if self.show_progress:
            if tool_name == 'Write':
                path = shorten_worktree_path(tool_input.get('file_path', ''))
                text.append(f'  \u2713 Write {path}', style='dim')
                return text
            if tool_name == 'Edit':
                path = shorten_worktree_path(tool_input.get('file_path', ''))
                text.append(f'  \u2192 Edit {path}', style='dim')
                return text
            if tool_name == 'WebSearch':
                query = tool_input.get('query', '')[:120]
                text.append(f'  \u2192 WebSearch "{query}"', style='dim')
                return text
            if tool_name == 'WebFetch':
                url = tool_input.get('url', '')[:120]
                text.append(f'  \u2192 WebFetch {url}', style='dim')
                return text
            if tool_name == 'Read':
                path = shorten_worktree_path(tool_input.get('file_path', ''))
                text.append(f'  \u25b6 Read {path}', style='dim')
                return text
            if tool_name == 'Glob':
                pattern = tool_input.get('pattern', '')
                text.append(f'  \u25b6 Glob {pattern}', style='dim')
                return text
            if tool_name == 'Grep':
                pattern = tool_input.get('pattern', '')[:80]
                text.append(f'  \u25b6 Grep "{pattern}"', style='dim')
                return text

        return None

    def _format_todos(self, tool_input: dict) -> Text | None:
        """Format TodoWrite showing differential changes."""
        todos = tool_input.get('todos', [])
        lines = []
        for item in todos:
            content = item.get('content', '')
            status = item.get('status', '')
            active = item.get('activeForm', '')
            old_status = self.prev_todos.get(content)

            if status == 'in_progress' and old_status != 'in_progress':
                display = active or content
                line = Text()
                line.append('  \u25b6 ', style='cyan')
                line.append(display)
                lines.append(line)
            elif status == 'completed' and old_status != 'completed':
                line = Text()
                line.append(f'  \u2713 {content}', style='dim')
                lines.append(line)

        # Update prev state
        self.prev_todos.clear()
        for item in todos:
            self.prev_todos[item.get('content', '')] = item.get('status', '')

        if lines:
            return lines[0]  # Return first change
        return None
