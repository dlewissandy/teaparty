"""Liaison service for hierarchical agent teams.

Provides functions for creating sub-team jobs, resolving team parameters,
materializing files, and running sub-team claude processes.

See docs/hierarchical-teams.md for the full design.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlmodel import Session, select

from teaparty_app.models import (
    Agent,
    Conversation,
    ConversationParticipant,
    Job,
    Message,
    Project,
    Workgroup,
    utc_now,
)
from teaparty_app.services.agent_definition import (
    build_agent_json,
    build_worktree_settings_json,
    slugify,
)
from teaparty_app.services.file_materializer import (
    read_files_from_directory,
    sync_directory_to_files,
)

logger = logging.getLogger(__name__)


@dataclass
class TeamParams:
    """Merged team configuration from workgroup defaults + project overrides."""

    model: str = "claude-sonnet-4-6"
    permission_mode: str = "acceptEdits"
    max_turns: int = 30
    max_cost_usd: float | None = None
    max_time_seconds: int | None = None


def resolve_team_params(project: Project, workgroup: Workgroup) -> TeamParams:
    """Merge team parameters: project overrides > workgroup defaults."""
    return TeamParams(
        model=project.model if project.model != "claude-sonnet-4-6" else workgroup.team_model,
        permission_mode=(
            project.permission_mode
            if project.permission_mode != "plan"
            else workgroup.team_permission_mode
        ),
        max_turns=project.max_turns if project.max_turns != 30 else workgroup.team_max_turns,
        max_cost_usd=project.max_cost_usd or workgroup.team_max_cost_usd,
        max_time_seconds=project.max_time_seconds or workgroup.team_max_time_seconds,
    )


def create_subteam_job(
    session: Session,
    project_id: str,
    workgroup_id: str,
    message: str,
) -> tuple[Job, Conversation]:
    """Create a Job + Conversation in a workgroup for a project sub-team."""
    workgroup = session.get(Workgroup, workgroup_id)
    if not workgroup:
        raise ValueError(f"Workgroup {workgroup_id} not found")

    project = session.get(Project, project_id)
    if not project:
        raise ValueError(f"Project {project_id} not found")

    # Derive a job title from the message
    title = message[:100].split("\n")[0].strip() or "Sub-team task"

    conversation = Conversation(
        workgroup_id=workgroup_id,
        created_by_user_id=project.created_by_user_id,
        kind="job",
        topic=title,
        name=title,
        description=message[:200],
    )
    session.add(conversation)
    session.flush()

    job = Job(
        title=title,
        scope=message,
        workgroup_id=workgroup_id,
        conversation_id=conversation.id,
        project_id=project_id,
        created_by_agent_id=None,
        permission_mode="acceptEdits",
    )
    session.add(job)

    # Post the initial system message
    initial_msg = Message(
        conversation_id=conversation.id,
        sender_type="system",
        content=f"[Project sub-team task] {title}\n\n{message}",
        requires_response=True,
    )
    session.add(initial_msg)
    session.flush()

    return job, conversation


def materialize_workgroup_files_sync(
    session: Session,
    workgroup: Workgroup,
    conversation: Conversation,
) -> tuple[str, dict[str, str]]:
    """Materialize workgroup files to a temp directory (sync version).

    Returns ``(dir_path, original_file_ids)`` where dir_path is the temp dir
    and original_file_ids maps path -> file ID for sync-back.
    """
    from teaparty_app.services.file_helpers import _files_for_conversation

    conv_files = _files_for_conversation(workgroup, conversation, session=session)

    dir_path = tempfile.mkdtemp(prefix="teaparty_subteam_")
    for f in conv_files:
        file_path = Path(dir_path) / f["path"]
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(f.get("content", ""), encoding="utf-8")

    original_file_ids = {f["path"]: f["id"] for f in conv_files}
    return dir_path, original_file_ids


def run_subteam(
    session: Session,
    job: Job,
    conversation: Conversation,
    workgroup: Workgroup,
    agents: list[Agent],
    message: str,
    params: TeamParams,
    working_dir: str,
    org_files: list[dict] | None = None,
) -> str:
    """Spawn a claude sub-team process and return a summary of the results.

    Blocks until the claude process exits. Stores agent messages in the DB.
    """
    from teaparty_app.services.agent_definition import _resolve_model_alias

    # Build agent definitions
    lead = next((a for a in agents if a.is_lead), agents[0]) if agents else None
    if not lead:
        return '{"error": "No agents in workgroup"}'

    lead_slug = slugify(lead.name)
    others = [a for a in agents if a.id != lead.id]

    # Build a dummy conversation for agent_definition
    dummy_conv = Conversation(
        id=conversation.id,
        workgroup_id=workgroup.id,
        created_by_user_id="",
        kind="job",
        name=conversation.name or "",
        description=conversation.description or "",
    )

    agents_dict: dict[str, dict] = {}
    slug_to_id: dict[str, str] = {}
    for agent in agents:
        slug = slugify(agent.name)
        is_lead = slug == lead_slug
        agents_dict[slug] = build_agent_json(
            agent, dummy_conv, workgroup,
            files_context="Your workgroup's files are in the current working directory. Use Read, Edit, Write, Glob, and Grep.",
            teammates=others if is_lead else None,
            org_files=org_files,
        )
        slug_to_id[slug] = agent.id

    model_alias = _resolve_model_alias(params.model)
    max_turns = max(6, 4 * len(agents), params.max_turns)

    # Build the claude command
    settings_json = build_worktree_settings_json(working_dir)
    cmd: list[str] = [
        "claude",
        "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--max-turns", str(max_turns),
        "--permission-mode", params.permission_mode,
        "--agents", json.dumps(agents_dict),
        "--agent", lead_slug,
        "--settings", settings_json,
    ]

    logger.info(
        "Starting sub-team for job %s: lead=%s, agents=%s, cwd=%s",
        job.id, lead_slug, list(agents_dict.keys()), working_dir,
    )

    # Clean environment
    env = {k: v for k, v in os.environ.items() if not k.startswith("TEAPARTY_")}
    env["HOME"] = os.environ.get("HOME", "")
    env["PATH"] = os.environ.get("PATH", "")

    timeout = params.max_time_seconds or 600  # default 10 min

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=working_dir,
            env=env,
        )

        stdout_bytes, stderr_bytes = proc.communicate(
            input=message.encode(), timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        logger.warning("Sub-team timed out for job %s after %ds", job.id, timeout)
        return json.dumps({"error": f"Sub-team timed out after {timeout}s"})
    except Exception as e:
        logger.exception("Sub-team process failed for job %s", job.id)
        return json.dumps({"error": str(e)})

    # Parse stream-json output
    messages_created: list[Message] = []
    result_text = ""

    for line in stdout_bytes.decode(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_type = event.get("type", "")

        # Extract result text
        if event_type == "result":
            result_text = event.get("result", "")
            if not result_text:
                # Try subresult
                sub = event.get("subResult", "")
                if sub:
                    result_text = sub
            continue

        # Extract assistant messages
        if event_type == "assistant" and event.get("message", {}).get("content"):
            content_blocks = event["message"]["content"]
            text_parts = []
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            if text_parts:
                text = "\n".join(text_parts)
                # Determine which agent
                agent_slug = event.get("agent", lead_slug)
                agent_id = slug_to_id.get(agent_slug, lead.id)
                msg = Message(
                    conversation_id=conversation.id,
                    sender_type="agent",
                    sender_agent_id=agent_id,
                    content=text,
                    requires_response=False,
                )
                session.add(msg)
                messages_created.append(msg)

    session.flush()

    # Build summary from result text or last messages
    if result_text:
        summary = result_text
    elif messages_created:
        summary = messages_created[-1].content
    else:
        summary = "(No output from sub-team)"

    # Truncate summary for relay back to liaison
    if len(summary) > 4000:
        summary = summary[:4000] + "\n... (truncated)"

    return summary
