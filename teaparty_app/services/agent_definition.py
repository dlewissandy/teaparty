"""Convert Agent database records into Claude ``--agents`` JSON format.

This module replaces ``--system-prompt`` invocations with ``--agent <name>``
by building the agents JSON structure that Claude Code expects.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from teaparty_app.models import Agent, Conversation, Workgroup
from teaparty_app.services.convention_resolver import extract_claude_md


def build_agent_json(
    agent: Agent,
    conversation: Conversation,
    workgroup: Workgroup | None = None,
    files_context: str = "",
    teammates: list[Agent] | None = None,
    org_files: list[dict] | None = None,
) -> dict:
    """Convert an Agent record to a dict suitable for ``--agents`` JSON.

    The returned dict matches the Claude Code agent definition schema::

        {
            "description": "...",
            "prompt": "...",
            "model": "sonnet",
            "maxTurns": 3,
        }

    When *teammates* is provided (for the lead agent in a multi-agent job),
    a team roster is appended to the prompt so the lead knows who's available.
    """
    return {
        "description": agent.description or agent.role or agent.name,
        "prompt": _build_prompt_body(
            agent, conversation, workgroup, files_context,
            teammates=teammates, org_files=org_files,
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
                    "matcher": "Edit|Write|Read|Glob|Grep",
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
    files_context: str = "",
    teammates: list[Agent] | None = None,
    org_files: list[dict] | None = None,
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

    # Organization-level CLAUDE.md (broadest scope)
    org_claude_md = extract_claude_md(org_files)
    if org_claude_md:
        parts.append("")
        parts.append("## Organization Instructions")
        parts.append(org_claude_md)

    # Workgroup-level CLAUDE.md (narrower scope)
    wg_claude_md = extract_claude_md(workgroup.files if workgroup else None)
    if wg_claude_md:
        parts.append("")
        parts.append("## Workgroup Instructions")
        parts.append(wg_claude_md)

    # Team roster (for lead agent in multi-agent jobs)
    if teammates:
        parts.append("")
        parts.append("Teammates (engage them using the Task tool):")
        for t in teammates:
            desc = t.role or t.description or t.personality or ""
            parts.append(f"- {t.name}" + (f" — {desc}" if desc else ""))

    # Orchestration tools for coordinator agents in operations workgroups
    if _is_operations_coordinator(agent, workgroup):
        parts.append("")
        parts.append(_ORCHESTRATION_DOCS)

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


def _is_operations_coordinator(agent: Agent, workgroup: Workgroup | None) -> bool:
    """Return True if agent is a coordinator in an operations workgroup."""
    if not workgroup or not workgroup.organization_id:
        return False
    # Check if Bash is in the agent's tools (coordinator needs it for CLI)
    has_bash = "Bash" in (agent.tool_names or [])
    if not has_bash:
        return False
    # Check if agent role or description mentions coordination/engagement
    role_lower = (agent.role or "").lower() + " " + (agent.description or "").lower()
    return "coordinator" in role_lower or "engagement" in role_lower


_ORCHESTRATION_DOCS = """\
## Orchestration Tools

You have access to orchestration commands via Bash. These are available because \
environment variables TEAPARTY_AGENT_ID, TEAPARTY_WORKGROUP_ID, and TEAPARTY_ORG_ID \
are set for you.

### Available Commands

```bash
# Browse organizations accepting engagements
python -m teaparty_app.cli.orchestrate browse-directory

# Check your org's credit balance
python -m teaparty_app.cli.orchestrate check-balance

# Propose a new engagement to another org
python -m teaparty_app.cli.orchestrate propose-engagement \\
  --target-org-id <ORG_ID> --title "Title" --scope "Scope" --requirements "Reqs"

# Accept or decline an engagement
python -m teaparty_app.cli.orchestrate respond-engagement \\
  --engagement-id <ID> --action accept --terms "Terms"

# Set the agreed price for an engagement
python -m teaparty_app.cli.orchestrate set-price \\
  --engagement-id <ID> --price 100.0

# Create a job for a team in your org
python -m teaparty_app.cli.orchestrate create-job \\
  --team "Design" --title "UI mockups" --scope "Create mockups" --engagement-id <ID>

# List jobs in a team
python -m teaparty_app.cli.orchestrate list-team-jobs --team "Design"

# Check job status and recent messages
python -m teaparty_app.cli.orchestrate read-job-status --job-id <ID>

# Post a message to a job conversation
python -m teaparty_app.cli.orchestrate post-to-job --job-id <ID> --message "Update needed"

# Mark an engagement as completed
python -m teaparty_app.cli.orchestrate complete-engagement \\
  --engagement-id <ID> --summary "All deliverables ready"
```

All commands output JSON. Use these tools to manage engagements and dispatch work.\
"""


