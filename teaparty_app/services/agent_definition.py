"""Convert Agent database records into Claude ``--agents`` JSON format.

This module replaces ``--system-prompt`` invocations with ``--agent <name>``
by building the agents JSON structure that Claude Code expects.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from teaparty_app.models import Agent, Conversation, Workgroup


def build_agent_json(
    agent: Agent,
    conversation: Conversation,
    workgroup: Workgroup | None = None,
    workflow_context: str = "",
    files_context: str = "",
) -> dict:
    """Convert an Agent record to a dict suitable for ``--agents`` JSON.

    The returned dict matches the Claude Code agent definition schema::

        {
            "description": "...",
            "prompt": "...",
            "model": "sonnet",
            "maxTurns": 3,
        }
    """
    return {
        "description": agent.description or agent.role or agent.name,
        "prompt": _build_prompt_body(
            agent, conversation, workgroup, workflow_context, files_context,
        ),
        "model": _resolve_model_alias(agent.model),
        "maxTurns": getattr(agent, "max_turns", 3) or 3,
    }


def build_worktree_settings_json(worktree_path: str) -> str:
    """Build a ``--settings`` JSON string with file-safety hooks for workspace agents.

    The PreToolUse hook constrains file operations to stay within the worktree.
    """
    hook_script = str(Path(__file__).parent.parent / "hooks" / "constrain_to_worktree.sh")
    settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Edit|Write|Read",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"{hook_script} {worktree_path}",
                        }
                    ],
                }
            ],
        },
    }
    return json.dumps(settings)


def slugify(name: str) -> str:
    """Convert an agent name to a CLI-safe slug."""
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-") or "agent"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_MODEL_ALIASES: dict[str, str] = {
    "claude-sonnet-4-5": "sonnet",
    "claude-haiku-4-5": "haiku",
    "claude-opus-4-6": "opus",
}


def _resolve_model_alias(model: str) -> str:
    """Map an Anthropic model ID to a claude CLI alias (sonnet, haiku, opus)."""
    return _MODEL_ALIASES.get(model, model)


def _build_prompt_body(
    agent: Agent,
    conversation: Conversation,
    workgroup: Workgroup | None = None,
    workflow_context: str = "",
    files_context: str = "",
) -> str:
    """Build the agent's prompt body — same content as build_system_prompt()."""
    parts: list[str] = []

    # Identity
    parts.append(f"You are {agent.name}.")
    if agent.role:
        parts.append(f"Role: {agent.role}")
    if agent.personality:
        parts.append(f"Personality: {agent.personality}")
    if agent.backstory:
        parts.append(f"Backstory: {agent.backstory}")

    # Conversation context
    parts.append("")
    kind_label = {
        "direct": "a direct conversation",
        "job": "a job discussion",
        "engagement": "an engagement conversation",
    }.get(conversation.kind, f"a {conversation.kind} conversation")
    parts.append(f"You are participating in {kind_label}.")
    if conversation.name and conversation.name != "general":
        parts.append(f"Job: {conversation.name}")
    if conversation.description:
        parts.append(f"Description: {conversation.description}")

    # Workflow / skills context
    if workflow_context:
        parts.append("")
        parts.append(workflow_context)

    # Skill-like workflow embedding (Phase 5)
    if workgroup and not workflow_context:
        skill_block = _build_skill_context(agent, workgroup, conversation)
        if skill_block:
            parts.append("")
            parts.append(skill_block)

    # Embedded workgroup files (for non-filesystem agents)
    if files_context:
        parts.append("")
        parts.append(files_context)

    # Minimal guidelines — let claude be claude
    parts.append("")
    parts.append("Guidelines:")
    parts.append("- Respond as this character with your distinct perspective.")
    parts.append("- Do not prefix your response with your name.")
    parts.append("- Be direct and substantive.")

    return "\n".join(parts)


def _build_skill_context(
    agent: Agent,
    workgroup: Workgroup,
    conversation: Conversation,
) -> str:
    """Embed workflow definitions as skill-like instruction blocks.

    Scans the workgroup's workflow files and includes any that reference
    this agent by name, giving the agent awareness of its role in workflows.
    """
    files: list[dict] = workgroup.files or []
    if not files:
        return ""

    # Find workflow files relevant to this agent
    agent_name_lower = agent.name.lower()
    relevant: list[tuple[str, str]] = []

    for f in files:
        path = f.get("path", "")
        content = f.get("content", "")
        if not path.startswith("workflows/") or not path.endswith(".md"):
            continue
        if path == "workflows/README.md":
            continue
        # Include if agent name appears in the workflow
        if agent_name_lower in content.lower():
            title = ""
            for line in content.splitlines():
                if line.strip().startswith("# "):
                    title = line.strip()[2:].strip()
                    break
            relevant.append((title or path, content))

    if not relevant:
        return ""

    parts = ["## Available Skills"]
    for title, content in relevant[:3]:  # Cap at 3 workflows
        # Trim to reasonable size
        trimmed = content[:2000] if len(content) > 2000 else content
        parts.append(f"\n### {title}\n{trimmed}")

    return "\n".join(parts)
