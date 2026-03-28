"""Stream content filter for chat windows.

Classifies stream-json events into display categories and provides
per-conversation toggle controls so the human can choose their detail
level — from conversation-only to full agent activity.

Design spec: docs/proposals/dashboard-ui/references/chat-windows.md
Issue #264.
"""
from __future__ import annotations

from enum import Enum


class StreamCategory(Enum):
    AGENT = 'agent'
    HUMAN = 'human'
    THINKING = 'thinking'
    TOOLS = 'tools'
    RESULTS = 'results'
    SYSTEM = 'system'
    STATE = 'state'
    COST = 'cost'
    LOG = 'log'


# Default: agent and human ON, everything else OFF
_DEFAULTS: dict[StreamCategory, bool] = {
    StreamCategory.AGENT: True,
    StreamCategory.HUMAN: True,
    StreamCategory.THINKING: False,
    StreamCategory.TOOLS: False,
    StreamCategory.RESULTS: False,
    StreamCategory.SYSTEM: False,
    StreamCategory.STATE: False,
    StreamCategory.COST: False,
    StreamCategory.LOG: False,
}


def classify_event(event: dict) -> StreamCategory | None:
    """Map a stream-json event to its display category.

    Returns None for events that don't map to any known category.
    """
    etype = event.get('type', '')

    if etype == 'human':
        return StreamCategory.HUMAN

    if etype == 'state':
        return StreamCategory.STATE

    if etype == 'log':
        return StreamCategory.LOG

    if etype == 'system':
        return StreamCategory.SYSTEM

    if etype == 'tool_result':
        return StreamCategory.RESULTS

    if etype == 'result':
        return StreamCategory.COST

    if etype == 'assistant':
        return _classify_assistant(event)

    return None


def _classify_assistant(event: dict) -> StreamCategory:
    """Classify an assistant event by its content blocks.

    Priority: text (AGENT) > tool_use (TOOLS) > thinking (THINKING).
    """
    content = event.get('message', {}).get('content', [])
    has_text = False
    has_tool = False
    has_thinking = False

    for block in content:
        if not isinstance(block, dict):
            continue
        bt = block.get('type', '')
        if bt == 'text' and block.get('text', '').strip():
            has_text = True
        elif bt == 'tool_use':
            has_tool = True
        elif bt == 'thinking':
            has_thinking = True

    if has_text:
        return StreamCategory.AGENT
    if has_tool:
        return StreamCategory.TOOLS
    if has_thinking:
        return StreamCategory.THINKING
    return StreamCategory.AGENT


class StreamFilter:
    """Per-conversation stream content filter with toggleable categories."""

    def __init__(self):
        self._state: dict[StreamCategory, bool] = dict(_DEFAULTS)

    def is_enabled(self, category: StreamCategory) -> bool:
        return self._state.get(category, False)

    def enable(self, category: StreamCategory) -> None:
        self._state[category] = True

    def disable(self, category: StreamCategory) -> None:
        self._state[category] = False

    def toggle(self, category: StreamCategory) -> None:
        self._state[category] = not self._state.get(category, False)

    def should_show(self, event: dict) -> bool:
        """Return True if the event should be displayed given current filter state."""
        category = classify_event(event)
        if category is None:
            return False
        return self._state.get(category, False)

    def should_show_sender(self, sender: str) -> bool:
        """Return True if messages from this sender should be displayed.

        Maps message-bus sender names to filter categories:
        - 'human' → HUMAN
        - 'orchestrator' → AGENT
        - anything else → AGENT (treat as agent output)
        """
        if sender == 'human':
            return self._state.get(StreamCategory.HUMAN, False)
        return self._state.get(StreamCategory.AGENT, False)

    def enabled_categories(self) -> set[StreamCategory]:
        return {cat for cat, on in self._state.items() if on}
