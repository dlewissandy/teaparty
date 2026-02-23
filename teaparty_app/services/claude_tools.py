"""Claude Code native tool catalog.

Agents run exclusively via ``claude -p`` and get these tools natively.
This module provides the canonical list for the toolbar and API.
"""

from __future__ import annotations

CLAUDE_TOOLS: list[dict[str, str]] = [
    {"name": "Read", "description": "Read files from the workspace."},
    {"name": "Write", "description": "Create or overwrite files."},
    {"name": "Edit", "description": "Make targeted edits to existing files."},
    {"name": "Glob", "description": "Find files by pattern matching."},
    {"name": "Grep", "description": "Search file contents with regex."},
    {"name": "Bash", "description": "Run shell commands."},
    {"name": "Task", "description": "Delegate work to sub-agents."},
    {"name": "WebSearch", "description": "Search the web for information."},
    {"name": "WebFetch", "description": "Fetch and analyze web pages."},
]

CLAUDE_TOOLSETS: list[dict] = [
    {
        "name": "File tools",
        "description": "Read, write, edit, and search files.",
        "tools": ["Read", "Write", "Edit", "Glob", "Grep"],
    },
    {
        "name": "System",
        "description": "Shell commands and sub-agent delegation.",
        "tools": ["Bash", "Task"],
    },
    {
        "name": "Web",
        "description": "Search the web and fetch pages.",
        "tools": ["WebSearch", "WebFetch"],
    },
]


def claude_tool_names() -> list[str]:
    """Return the list of Claude native tool names."""
    return [t["name"] for t in CLAUDE_TOOLS]
