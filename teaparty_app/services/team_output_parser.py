"""Parse verbose ``claude`` CLI output to extract per-agent contributions.

When a job conversation uses Claude's multi-agent team feature, the lead
agent delegates to sub-agents via the ``Task`` tool.  The verbose JSON
output contains ``tool_use`` / ``tool_result`` events that let us attribute
each contribution to a specific agent.

Two parsing strategies are provided:

1. **Event-based** (``parse_team_output``) — walks the verbose event array
   looking for Task tool_use/tool_result pairs.
2. **Text-based** (``unpack_agent_text``) — splits formatted text by known
   agent name prefixes as a fallback.
"""

from __future__ import annotations

import re


def parse_team_output(
    events: list[dict],
    slug_to_id: dict[str, str],
    agent_names: list[str],
) -> list[tuple[str | None, str]]:
    """Extract per-agent contributions from verbose CLI events.

    Returns a list of ``(agent_id, content)`` tuples.  *agent_id* is
    ``None`` when the contribution can't be attributed to a specific agent.

    *slug_to_id* maps agent slugs/names to their database IDs.
    *agent_names* is the list of known agent display names (used by the
    text fallback).
    """
    if not events:
        return []

    contributions: list[tuple[str | None, str]] = []

    # Build a lookup for pending Task tool_use events keyed by tool_use id.
    # Each entry records the sub-agent slug so we can attribute the result.
    pending_tasks: dict[str, str] = {}

    # Also collect assistant text blocks that aren't tool delegations.
    lead_text_parts: list[str] = []

    for event in events:
        if not isinstance(event, dict):
            continue

        etype = event.get("type")

        # --- assistant message: may contain text and/or tool_use blocks ---
        if etype == "assistant":
            message = event.get("message") or {}
            content_blocks = message.get("content") or []
            for block in content_blocks:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    text = (block.get("text") or "").strip()
                    if text:
                        lead_text_parts.append(text)
                elif block.get("type") == "tool_use" and block.get("name") == "Task":
                    tool_use_id = block.get("id", "")
                    inp = block.get("input") or {}
                    # Try to identify the sub-agent from various fields.
                    sub_agent = (
                        inp.get("name")
                        or inp.get("subagent_type")
                        or inp.get("description")
                        or ""
                    )
                    if tool_use_id:
                        pending_tasks[tool_use_id] = sub_agent

        # --- tool_result: the sub-agent's response ---
        elif etype == "tool_result":
            tool_use_id = event.get("tool_use_id", "")
            if tool_use_id not in pending_tasks:
                continue  # Not a Task tool result — skip.
            sub_agent_hint = pending_tasks.pop(tool_use_id)
            content = _extract_tool_result_text(event)
            if not content:
                continue

            # Resolve sub-agent to an agent_id.
            agent_id = _resolve_agent_id(sub_agent_hint, slug_to_id)
            contributions.append((agent_id, content))

    # Prepend any lead-agent text that preceded delegations.
    if lead_text_parts:
        lead_text = "\n\n".join(lead_text_parts)
        contributions.insert(0, (None, lead_text))

    return contributions


def unpack_agent_text(
    text: str,
    agent_names: list[str],
) -> list[tuple[str, str]]:
    """Split formatted text into per-agent sections.

    Recognises patterns like ``**Name**: ...``, ``[Name]: ...``, or
    ``Name: ...`` at line starts, where *Name* is a known agent name.

    Returns ``[(name, content), ...]``.  If no patterns are found, returns
    the entire text attributed to an empty string.
    """
    if not text or not agent_names:
        return [("", text)] if text else []

    # Build a regex that matches any known agent name at a line start.
    # Patterns: **Name**:, [Name]:, Name:
    escaped = [re.escape(n) for n in agent_names]
    names_alt = "|".join(escaped)
    pattern = re.compile(
        rf"^(?:\*\*({names_alt})\*\*|\[({names_alt})\]|({names_alt}))\s*:",
        re.MULTILINE | re.IGNORECASE,
    )

    matches = list(pattern.finditer(text))
    if not matches:
        return [("", text)]

    # Map case-insensitive name → canonical name.
    name_lower = {n.lower(): n for n in agent_names}

    sections: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        # Which capture group matched?
        raw_name = m.group(1) or m.group(2) or m.group(3) or ""
        canonical = name_lower.get(raw_name.lower(), raw_name)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        section_text = text[start:end].strip()
        if section_text:
            sections.append((canonical, section_text))

    # If there's text before the first match, include it unattributed.
    if matches and matches[0].start() > 0:
        prefix = text[: matches[0].start()].strip()
        if prefix:
            sections.insert(0, ("", prefix))

    return sections if sections else [("", text)]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_tool_result_text(event: dict) -> str:
    """Pull text content from a tool_result event."""
    content = event.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append((block.get("text") or "").strip())
            elif isinstance(block, str):
                parts.append(block.strip())
        return "\n".join(p for p in parts if p)
    return ""


def _resolve_agent_id(hint: str, slug_to_id: dict[str, str]) -> str | None:
    """Try to match a sub-agent hint to a known agent ID."""
    if not hint:
        return None
    # Direct slug match.
    if hint in slug_to_id:
        return slug_to_id[hint]
    # Case-insensitive / normalized match.
    hint_lower = hint.lower().strip()
    for slug, aid in slug_to_id.items():
        if slug.lower() == hint_lower:
            return aid
    # Partial match: hint may be a description like "research specialist".
    # Try matching against slug substrings.
    for slug, aid in slug_to_id.items():
        if slug.lower() in hint_lower or hint_lower in slug.lower():
            return aid
    return None
