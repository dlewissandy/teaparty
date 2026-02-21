"""Convert Agent database records into Claude ``--agents`` JSON format.

This module replaces ``--system-prompt`` invocations with ``--agent <name>``
by building the agents JSON structure that Claude Code expects.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from sqlmodel import Session, select

from teaparty_app.models import Agent, Conversation, Project, Workgroup
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
        "model": agent.model,
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
# Liaison agent definitions (hierarchical teams)
# ---------------------------------------------------------------------------


def build_liaison_json(
    workgroup: Workgroup,
    project: Project,
    org_files: list[dict] | None = None,
) -> dict:
    """Build an ephemeral liaison agent definition for a project team.

    The liaison bridges the project team to a single workgroup.  It has
    one tool (``relay-to-subteam`` via Bash) and strict behavioral
    constraints: relay only, no code, no decisions.
    """
    model = project.model or workgroup.team_model
    prompt = _build_liaison_prompt(workgroup, project, org_files)
    return {
        "description": f"{workgroup.name} workgroup liaison",
        "prompt": prompt,
        "model": model,
        "maxTurns": 10,
    }


def build_project_lead_json(
    project: Project,
    liaison_roster: list[str],
    org_files: list[dict] | None = None,
) -> dict:
    """Build an ephemeral project lead agent definition.

    The project lead coordinates the project team.  It assigns tasks to
    liaison agents and synthesizes results across workgroups.  Like liaisons,
    the project lead is an ephemeral definition — not a persistent Agent record.
    """
    parts: list[str] = [
        f"You are the project lead for: {project.name}",
        "",
    ]
    if project.prompt:
        parts.append(f"Project scope: {project.prompt[:500]}")
        parts.append("")

    # Organization-level CLAUDE.md
    org_claude_md = extract_claude_md(org_files)
    if org_claude_md:
        parts.append("## Organization Instructions")
        parts.append(org_claude_md)
        parts.append("")

    if liaison_roster:
        parts.append("## Your Team")
        parts.append("")
        parts.append(
            "You have the following teammates registered as custom agent types. "
            "Delegate work to them using the Task tool with their name as the "
            "`subagent_type` parameter. Example:"
        )
        parts.append("")
        # Show a concrete example using the first liaison's slug
        example_slug = liaison_roster[0].split(" — ")[0].lstrip("- ").strip()
        parts.append("```")
        parts.append(f'Task(subagent_type="{example_slug}", prompt="Your task description", description="Short label")')
        parts.append("```")
        parts.append("")
        parts.append("Available teammates:")
        parts.extend(liaison_roster)
        parts.append("")
        parts.append(
            "Assign tasks to your teammates in parallel when possible. "
            "Each teammate relays work to their workgroup's sub-team. "
            "Synthesize their results to fulfill the project."
        )

    return {
        "description": "Project lead — coordinates workgroup liaisons",
        "prompt": "\n".join(parts),
        "model": project.model,
        "maxTurns": project.max_turns or 30,
    }


def build_project_team_agents(
    session: Session,
    project: Project,
    org_files: list[dict] | None = None,
) -> tuple[dict[str, dict], str, dict[str, str]]:
    """Build the full agents dict for a project team session.

    The project team consists of:
    - **Project lead**: ephemeral, coordinates the team.
    - **Liaisons**: one per workgroup selected in the project.

    Returns ``(agents_dict, lead_slug, slug_to_id)`` where:
    - *agents_dict* maps slug -> agent definition (for ``--agents`` JSON)
    - *lead_slug* is the project lead's slug (for ``--agent``)
    - *slug_to_id* maps slug -> agent/entity ID for message attribution
    """
    # One liaison per workgroup selected in the project.
    workgroups = [
        session.get(Workgroup, wg_id)
        for wg_id in (project.workgroup_ids or [])
    ]
    workgroups = [wg for wg in workgroups if wg is not None]

    # Build liaison definitions and teammate roster for the project lead.
    liaison_roster: list[str] = []
    agents_dict: dict[str, dict] = {}
    slug_to_id: dict[str, str] = {}

    # Build the project lead first so it's the first entry in slug_to_id.
    lead_slug = "project-lead"

    for wg in workgroups:
        wg_slug = f"{slugify(wg.name)}-liaison"
        agents_dict[wg_slug] = build_liaison_json(wg, project, org_files)
        slug_to_id[wg_slug] = f"liaison:{wg.id}"
        liaison_roster.append(f"- {wg_slug} — {wg.name} workgroup liaison")

    agents_dict[lead_slug] = build_project_lead_json(project, liaison_roster, org_files)
    slug_to_id[lead_slug] = f"project:{project.id}"

    return agents_dict, lead_slug, slug_to_id


def _build_liaison_prompt(
    workgroup: Workgroup,
    project: Project,
    org_files: list[dict] | None = None,
) -> str:
    """Build the prompt for a liaison agent."""
    wg_slug = f"{slugify(workgroup.name)}-liaison"
    env_key = f"TEAPARTY_WORKGROUP_ID_{wg_slug.upper().replace('-', '_')}"

    parts: list[str] = [
        f"You are a liaison agent bridging the project team to the {workgroup.name} workgroup.",
        f"You do not write code or make architectural decisions. "
        f"Your sole responsibility is communication relay.",
        "",
        f"Project: {project.name}",
    ]
    if project.prompt:
        parts.append(f"Project scope: {project.prompt[:500]}")

    parts.append("")
    parts.append(
        "You MUST use the relay-to-subteam command via Bash for ALL communication "
        "with your sub-team. This is your only tool. Do not attempt to do the work yourself."
    )
    parts.append("")
    parts.append(f"Your workgroup ID is available in ${env_key}.")
    parts.append(_build_liaison_tool_docs(env_key))

    parts.append("")
    parts.append("Workflow:")
    parts.append("1. Receive a task assignment from the team lead.")
    parts.append("2. Call relay-to-subteam with the task description.")
    parts.append("3. Report the sub-team's results back to the team lead.")
    parts.append("4. If the team lead has follow-ups, relay them the same way.")

    return "\n".join(parts)


def _build_liaison_tool_docs(env_key: str) -> str:
    """Build relay-to-subteam command docs with the correct env var reference."""
    return f"""\
## relay-to-subteam Command

```bash
# First call: creates a job and runs the sub-team
TEAPARTY_WORKGROUP_ID=${env_key} python -m teaparty_app.cli.liaison relay-to-subteam \\
  --message "Your task description here"

# Follow-up call: sends a message to the existing sub-team
TEAPARTY_WORKGROUP_ID=${env_key} python -m teaparty_app.cli.liaison relay-to-subteam \\
  --message "Follow-up message" --job-id <JOB_ID>
```

Environment variables TEAPARTY_PROJECT_ID and TEAPARTY_ORG_ID are set for you. \
You must set TEAPARTY_WORKGROUP_ID from ${env_key} as shown above.

The command outputs JSON with job_id, status, and a summary of the sub-team's work."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

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


