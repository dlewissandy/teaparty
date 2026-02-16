"""Workflow-driven turn management.

Replaces intent probing, LLM responder selection, and chain logic
with a deterministic policy: the workflow definition says who speaks
next, and we follow it.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from sqlmodel import Session

from teaparty_app.models import Agent, Conversation, Message, Workgroup

logger = logging.getLogger(__name__)


@dataclass
class TurnDirective:
    """Instruction for the runtime: which agents respond and in what order."""

    agent_ids: list[str] = field(default_factory=list)
    pause_after: bool = True
    workflow_step_label: str = ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def determine_next_turns(
    conversation: Conversation,
    trigger: Message,
    agents: list[Agent],
    workflow_state: dict | None,
) -> TurnDirective:
    """Return an ordered list of agent IDs that should respond to *trigger*.

    If there is an active workflow, the step definition drives the choice.
    Otherwise fall back to simple heuristics (all agents for topic, single
    agent for direct).
    """

    if not agents:
        return TurnDirective()

    # Direct / 1:1 conversations: the single agent always responds.
    if conversation.kind == "direct" or len(agents) == 1:
        return TurnDirective(
            agent_ids=[agents[0].id],
            pause_after=True,
            workflow_step_label="",
        )

    # If we have a parsed workflow state, use step-driven selection.
    if workflow_state and workflow_state.get("status") == "active":
        return _step_driven_turns(agents, workflow_state)

    # Fallback for topic/engagement conversations without a workflow:
    # all agents respond in creation order, then pause for user.
    return TurnDirective(
        agent_ids=[a.id for a in agents],
        pause_after=True,
        workflow_step_label="",
    )


# ---------------------------------------------------------------------------
# Step-driven selection
# ---------------------------------------------------------------------------

def _step_driven_turns(
    agents: list[Agent],
    workflow_state: dict,
) -> TurnDirective:
    """Use the current workflow step to pick agents."""

    step = workflow_state.get("current_step", {})
    step_agents: list[str] = step.get("agents", [])
    step_label = step.get("label", "")
    pause = step.get("pause_after", True)

    name_to_id = {a.name.lower(): a.id for a in agents}

    agent_ids: list[str] = []
    for name in step_agents:
        aid = name_to_id.get(name.lower())
        if aid:
            agent_ids.append(aid)
        else:
            logger.warning("Workflow step references unknown agent %r", name)

    if not agent_ids:
        # Fallback: first agent
        agent_ids = [agents[0].id]

    return TurnDirective(
        agent_ids=agent_ids,
        pause_after=pause,
        workflow_step_label=step_label,
    )


# ---------------------------------------------------------------------------
# Workflow state parsing
# ---------------------------------------------------------------------------

_STEP_AGENT_RE = re.compile(r"\*\*Agent\*\*:\s*(.+)", re.IGNORECASE)
_STEP_HEADING_RE = re.compile(r"^###\s+(\d+)\.\s+(.*)", re.MULTILINE)


def parse_workflow_state(workgroup: Workgroup, conversation: Conversation) -> dict | None:
    """Parse ``_workflow_state.md`` from workgroup files into a structured dict.

    Returns ``None`` if no active workflow exists.
    """

    files: list[dict] = workgroup.files or []
    topic_id = conversation.id if conversation.kind == "topic" else ""

    # Find the workflow state file
    state_content: str | None = None
    for f in files:
        if f.get("path") == "_workflow_state.md":
            fid = f.get("topic_id", "")
            if fid == topic_id or not fid:
                state_content = f.get("content")
                break

    if not state_content:
        return None

    # Parse current step number from state
    current_step_num = _extract_current_step(state_content)
    status = "active" if "pending" not in state_content.lower().split("status")[0:2][-1] else "active"

    # Check if completed
    if "completed" in state_content.lower():
        status_line = ""
        for line in state_content.splitlines():
            if "status" in line.lower():
                status_line = line.lower()
                break
        if "completed" in status_line:
            return {"status": "completed", "current_step": {}}

    # Find the workflow definition file
    workflow_path = _extract_workflow_path(state_content)
    if not workflow_path:
        return None

    workflow_content: str | None = None
    for f in files:
        if f.get("path") == workflow_path:
            workflow_content = f.get("content")
            break

    if not workflow_content:
        return None

    # Parse steps from the workflow definition
    steps = _parse_workflow_steps(workflow_content)
    if not steps:
        return None

    # Find the current step
    current = None
    for s in steps:
        if s["number"] == current_step_num:
            current = s
            break

    if not current:
        current = steps[0] if steps else {"number": 1, "label": "", "agents": [], "pause_after": True}

    return {
        "status": status,
        "current_step": current,
        "steps": steps,
        "current_step_number": current_step_num,
        "workflow_path": workflow_path,
    }


def advance_workflow_state(
    workgroup: Workgroup,
    conversation: Conversation,
    workflow_state: dict,
) -> str | None:
    """Advance to the next step and return the updated state markdown, or None if done."""

    steps = workflow_state.get("steps", [])
    current_num = workflow_state.get("current_step_number", 1)
    next_num = current_num + 1

    # Find next step
    next_step = None
    for s in steps:
        if s["number"] == next_num:
            next_step = s
            break

    workflow_path = workflow_state.get("workflow_path", "")
    if not next_step:
        # Workflow complete
        return (
            f"# Workflow State\n\n"
            f"- **Workflow**: {workflow_path}\n"
            f"- **Status**: completed\n"
            f"- **Current Step**: (done)\n"
        )

    return (
        f"# Workflow State\n\n"
        f"- **Workflow**: {workflow_path}\n"
        f"- **Status**: active\n"
        f"- **Current Step**: {next_step['number']}. {next_step['label']}\n"
    )


# ---------------------------------------------------------------------------
# Internal parsing helpers
# ---------------------------------------------------------------------------

def _extract_current_step(state_content: str) -> int:
    """Extract the current step number from workflow state markdown."""
    for line in state_content.splitlines():
        if "current step" in line.lower():
            m = re.search(r"(\d+)", line)
            if m:
                return int(m.group(1))
    return 1


def _extract_workflow_path(state_content: str) -> str | None:
    """Extract the workflow file path from the state markdown."""
    for line in state_content.splitlines():
        if "workflow" in line.lower() and "state" not in line.lower():
            m = re.search(r"(workflows/[\w-]+\.md)", line)
            if m:
                return m.group(1)
    return None


def _parse_workflow_steps(workflow_content: str) -> list[dict]:
    """Parse ``### N. Step Name`` blocks from a workflow markdown file."""

    steps: list[dict] = []
    headings = list(_STEP_HEADING_RE.finditer(workflow_content))

    for i, match in enumerate(headings):
        number = int(match.group(1))
        label = match.group(2).strip()

        # Extract the block between this heading and the next
        start = match.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(workflow_content)
        block = workflow_content[start:end]

        # Parse agent names
        agents: list[str] = []
        for agent_match in _STEP_AGENT_RE.finditer(block):
            raw = agent_match.group(1).strip()
            # Handle "Proponent, Opponent" or "Proponent"
            for name in re.split(r"[,;]|\band\b", raw):
                name = name.strip()
                if name:
                    agents.append(name)

        # Check for pause/completion markers
        has_completes = "completes" in block.lower()
        has_loop = "loop" in block.lower()
        pause_after = has_completes or (not has_loop and number > 1)

        steps.append({
            "number": number,
            "label": label,
            "agents": agents,
            "pause_after": pause_after,
            "has_loop": has_loop,
        })

    return steps
