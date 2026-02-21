"""Convert Agent database records into Claude ``--agents`` JSON format.

This module replaces ``--system-prompt`` invocations with ``--agent <name>``
by building the agents JSON structure that Claude Code expects.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from sqlmodel import Session, select

from teaparty_app.models import Agent, Conversation, Organization, Project, Workgroup
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
    model = _resolve_model_alias(project.model or workgroup.team_model)
    prompt = _build_liaison_prompt(workgroup, project, org_files)
    return {
        "description": f"Liaison to {workgroup.name}",
        "prompt": prompt,
        "model": model,
        "maxTurns": 10,
    }


def build_project_team_agents(
    session: Session,
    project: Project,
    org_files: list[dict] | None = None,
) -> tuple[dict[str, dict], str, dict[str, str]]:
    """Build the full agents dict for a project team session.

    Returns ``(agents_dict, lead_slug, slug_to_id)`` where:
    - *agents_dict* maps slug -> agent definition (for ``--agents`` JSON)
    - *lead_slug* is the org lead's slug (for ``--agent``)
    - *slug_to_id* maps slug -> agent/entity ID for message attribution
    """
    org = session.get(Organization, project.organization_id)
    if not org or not org.operations_workgroup_id:
        raise ValueError(f"Organization {project.organization_id} has no operations workgroup")

    ops_wg = session.get(Workgroup, org.operations_workgroup_id)
    if not ops_wg:
        raise ValueError(f"Operations workgroup {org.operations_workgroup_id} not found")

    # Find the org lead agent
    org_lead = session.exec(
        select(Agent).where(
            Agent.workgroup_id == ops_wg.id,
            Agent.is_lead == True,  # noqa: E712
        )
    ).first()
    if not org_lead:
        raise ValueError(f"No lead agent in operations workgroup {ops_wg.name}")

    # Collect participating workgroups and build liaison definitions
    workgroups: list[Workgroup] = []
    for wg_id in project.workgroup_ids or []:
        wg = session.get(Workgroup, wg_id)
        if wg:
            workgroups.append(wg)

    # Build liaison teammate descriptors for the lead's roster
    liaison_teammates: list[str] = []
    agents_dict: dict[str, dict] = {}
    slug_to_id: dict[str, str] = {}

    for wg in workgroups:
        liaison_slug = f"liaison-{slugify(wg.name)}"
        agents_dict[liaison_slug] = build_liaison_json(wg, project, org_files)
        slug_to_id[liaison_slug] = f"liaison:{wg.id}"
        liaison_teammates.append(f"- {liaison_slug} — Liaison to {wg.name} workgroup")

    # Build the org lead definition with the liaison roster as teammates context
    # We build a custom Conversation for the project context
    conv = Conversation(
        id="",
        workgroup_id=ops_wg.id,
        created_by_user_id="",
        kind="project",
        name=project.name,
        description=project.prompt[:200] if project.prompt else "",
    )

    lead_json = build_agent_json(org_lead, conv, ops_wg, org_files=org_files)
    # Append the liaison roster to the lead's prompt
    if liaison_teammates:
        lead_json["prompt"] += (
            "\n\nTeammates (engage them using the Task tool):\n"
            + "\n".join(liaison_teammates)
        )
    lead_json["prompt"] += (
        "\n\nYou are leading a project team. Assign tasks to liaison agents, "
        "who will relay them to their workgroup's sub-team. "
        "Synthesize results from all workgroups to fulfill the project."
    )

    lead_slug = slugify(org_lead.name)
    agents_dict[lead_slug] = lead_json
    slug_to_id[lead_slug] = org_lead.id

    return agents_dict, lead_slug, slug_to_id


def _build_liaison_prompt(
    workgroup: Workgroup,
    project: Project,
    org_files: list[dict] | None = None,
) -> str:
    """Build the prompt for a liaison agent."""
    liaison_slug = f"liaison-{slugify(workgroup.name)}"
    env_key = f"TEAPARTY_WORKGROUP_ID_{liaison_slug.upper().replace('-', '_')}"

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


