"""Agent tool catalog loaded from ``seeds/toolkits.yaml``.

Agents run exclusively via ``claude -p`` and get these tools natively.
This module provides the canonical list for the toolbar and API.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

_TOOLKITS_PATH = Path(__file__).parent.parent / "seeds" / "toolkits.yaml"

_loaded_tools: list[dict[str, str]] | None = None
_loaded_toolsets: list[dict] | None = None


def _load_toolkits() -> tuple[list[dict[str, str]], list[dict]]:
    """Load tools and toolsets from the YAML seed file."""
    global _loaded_tools, _loaded_toolsets
    if _loaded_tools is not None and _loaded_toolsets is not None:
        return _loaded_tools, _loaded_toolsets

    tools: list[dict[str, str]] = []
    toolsets: list[dict] = []

    try:
        with open(_TOOLKITS_PATH) as fh:
            data = yaml.safe_load(fh)
    except Exception:
        logger.exception("Failed to load toolkits YAML: %s", _TOOLKITS_PATH)
        _loaded_tools, _loaded_toolsets = tools, toolsets
        return tools, toolsets

    if not isinstance(data, dict):
        logger.warning("Toolkits YAML is not a mapping: %s", _TOOLKITS_PATH)
        _loaded_tools, _loaded_toolsets = tools, toolsets
        return tools, toolsets

    # --- tools ---
    raw_tools = data.get("tools", [])
    if isinstance(raw_tools, list):
        seen: set[str] = set()
        for entry in raw_tools:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "")).strip()
            if not name or name in seen:
                continue
            seen.add(name)
            tools.append({
                "name": name,
                "type": str(entry.get("type", "claude")),
                "description": str(entry.get("description", "")),
            })

    # --- toolsets ---
    raw_toolsets = data.get("toolsets", [])
    if isinstance(raw_toolsets, list):
        for entry in raw_toolsets:
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("name", "")).strip()
            if not name:
                continue
            ts_tools = []
            raw_ts_tools = entry.get("tools", [])
            if isinstance(raw_ts_tools, list):
                ts_tools = [str(t).strip() for t in raw_ts_tools if str(t).strip()]
            toolsets.append({
                "name": name,
                "description": str(entry.get("description", "")),
                "tools": ts_tools,
            })

    _loaded_tools, _loaded_toolsets = tools, toolsets
    return tools, toolsets


def get_tools(tool_type: str | None = None) -> list[dict[str, str]]:
    """Return the tool catalog, optionally filtered by type."""
    tools, _ = _load_toolkits()
    if tool_type is None:
        return list(tools)
    return [t for t in tools if t.get("type") == tool_type]


def get_toolsets() -> list[dict]:
    """Return the toolset groupings."""
    _, toolsets = _load_toolkits()
    return list(toolsets)


def all_tool_names() -> list[str]:
    """Return names of every tool in the catalog."""
    tools, _ = _load_toolkits()
    return [t["name"] for t in tools]


def claude_tool_names() -> list[str]:
    """Return names of Claude Code native tools only."""
    return [t["name"] for t in get_tools("claude")]


# Backwards-compatible aliases (Claude native tools only)
CLAUDE_TOOLS = get_tools("claude")
CLAUDE_TOOLSETS = get_toolsets()
