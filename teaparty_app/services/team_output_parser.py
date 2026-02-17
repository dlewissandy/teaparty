"""Parse ``stream-json --verbose`` output to extract per-agent contributions.

When a job conversation uses Claude's multi-agent team feature
(``--output-format stream-json --verbose``), the structured events contain
``Task`` tool_use / tool_result pairs that attribute each contribution to
a specific sub-agent.  No text parsing is needed — the events are the
source of truth.
"""

from __future__ import annotations


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
