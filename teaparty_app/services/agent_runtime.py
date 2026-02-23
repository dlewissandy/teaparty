"""Agent runtime — orchestrates agent responses using the ``claude`` CLI.

This module is the entry point for all agent auto-responses.  When a user
posts a message, the conversation router calls ``run_agent_auto_responses``
which:

1.  Determines eligible agents via ``_agents_for_auto_response``.
2.  Routes to the appropriate agent(s) via @mention / @all / default lead.
3.  Builds agent definitions and user messages via the prompt builder.
4.  Shells out to ``claude -p`` via ``claude_runner.run_claude``.
5.  Stores the reply as a ``Message`` and records usage.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
import time
from datetime import timedelta
from sqlmodel import Session, func, select

from teaparty_app.config import settings
from teaparty_app.db import commit_with_retry
from teaparty_app.models import (
    Agent,
    AgentWorkgroup,
    Conversation,
    ConversationParticipant,
    Job,
    Message,
    Organization,
    Project,
    Workgroup,
    utc_now,
)
from teaparty_app.services.admin_workspace import (
    ADMIN_AGENT_SENTINEL,
    ADMIN_TEAM_NAMES,
    consume_queued_workgroup_deletion,
    delete_workgroup_data,
    is_admin_agent,
)
from teaparty_app.services.agent_definition import build_agent_json, slugify
from teaparty_app.services.claude_runner import kill_conversation_process, run_claude
from teaparty_app.services.file_materializer import materialized_files
from teaparty_app.services.llm_usage import record_llm_usage
from teaparty_app.services.prompt_builder import build_user_message

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-memory live activity store (per-conversation agent phase tracking)
# ---------------------------------------------------------------------------
_conversation_activity: dict[str, list[dict]] = {}
_activity_lock = threading.Lock()


def _publish_activity(conversation_id: str) -> None:
    """Push current activity snapshot to SSE subscribers."""
    from teaparty_app.services.event_bus import publish
    from teaparty_app.services.team_registry import get_session as get_team_session

    agents = get_conversation_activity(conversation_id)
    team = get_team_session(conversation_id)
    publish(conversation_id, {
        "type": "activity",
        "agents": agents,
        "stream_active": team is not None and team.is_running,
    })


def _set_activity(conversation_id: str, agent_id: str, agent_name: str, phase: str, detail: str = "") -> None:
    with _activity_lock:
        entries = _conversation_activity.setdefault(conversation_id, [])
        for entry in entries:
            if entry["agent_id"] == agent_id:
                entry.update(agent_name=agent_name, phase=phase, detail=detail, started_at=time.time())
                break
        else:
            entries.append(
                {"agent_id": agent_id, "agent_name": agent_name, "phase": phase, "detail": detail, "started_at": time.time()}
            )
    _publish_activity(conversation_id)


def _clear_activity(conversation_id: str, agent_id: str | None = None) -> None:
    with _activity_lock:
        if agent_id is None:
            _conversation_activity.pop(conversation_id, None)
        else:
            entries = _conversation_activity.get(conversation_id)
            if entries:
                _conversation_activity[conversation_id] = [e for e in entries if e["agent_id"] != agent_id]
                if not _conversation_activity[conversation_id]:
                    del _conversation_activity[conversation_id]
    _publish_activity(conversation_id)


def get_conversation_activity(conversation_id: str) -> list[dict]:
    now = time.time()
    with _activity_lock:
        entries = _conversation_activity.get(conversation_id, [])
        fresh = [e for e in entries if now - e["started_at"] <= 120]
        if entries and not fresh:
            _conversation_activity.pop(conversation_id, None)
        elif len(fresh) != len(entries):
            _conversation_activity[conversation_id] = fresh
        return [
            {"agent_id": e["agent_id"], "agent_name": e["agent_name"], "phase": e["phase"], "detail": e["detail"]}
            for e in fresh
        ]


# ---------------------------------------------------------------------------
# Conversation cancellation
# ---------------------------------------------------------------------------
_cancelled_conversations: set[str] = set()


def cancel_conversation(conversation_id: str) -> None:
    """Mark a conversation as cancelled, kill any running subprocess, and clear activity."""
    _cancelled_conversations.add(conversation_id)
    kill_conversation_process(conversation_id)
    # Stop persistent team session if one exists
    try:
        from teaparty_app.services.team_registry import stop_session
        stop_session(conversation_id)
    except Exception:
        pass
    _clear_activity(conversation_id)
    # Explicit cancellation event (stream_active forced false).
    from teaparty_app.services.event_bus import publish
    publish(conversation_id, {"type": "activity", "agents": [], "stream_active": False})


def is_conversation_cancelled(conversation_id: str) -> bool:
    return conversation_id in _cancelled_conversations


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _is_each_invocation(content: str) -> bool:
    """Return True if the message requests independent fan-out via ``@each``."""
    return bool(re.search(r"@each\b", content, re.IGNORECASE))


def _is_team_invocation(content: str) -> bool:
    """Return True if the message targets all agents via ``@all`` or ``@team``."""
    return bool(re.search(r"@(?:all|team)\b", content, re.IGNORECASE))


def _resolve_mentioned_agent(content: str, agents: list[Agent]) -> Agent | None:
    """Return the first agent whose name is @-mentioned in *content*, or None."""
    text_lower = content.lower()
    for agent in agents:
        if f"@{agent.name.lower()}" in text_lower:
            return agent
    return None


def _select_lead(candidates: list[Agent], session: Session | None = None, workgroup_id: str | None = None) -> Agent:
    """Return the lead agent from candidates, falling back to the first."""
    if session and workgroup_id:
        from teaparty_app.services.agent_workgroups import lead_agent_for_workgroup
        lead = lead_agent_for_workgroup(session, workgroup_id)
        if lead and any(c.id == lead.id for c in candidates):
            return next(c for c in candidates if c.id == lead.id)
    return candidates[0]


def _is_resumable_conversation(conversation: Conversation) -> bool:
    """Return True if this conversation should use persistent Claude sessions."""
    if conversation.kind == "task":
        return True
    if conversation.kind == "direct" and (conversation.topic or "").startswith("dma:"):
        return True
    return False


def infer_requires_response(content: str) -> bool:
    text = content.strip().lower()
    if "?" in text:
        return True
    return text.startswith(("can ", "could ", "would ", "please ", "who ", "what ", "when ", "where ", "why ", "how "))


def _extract_json_object(text: str) -> dict | None:
    """Best-effort extraction of the first ``{…}`` JSON object from *text*."""
    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    start = -1
    return None


# ---------------------------------------------------------------------------
# Agent resolution
# ---------------------------------------------------------------------------

def _conversation_participants(session: Session, conversation_id: str) -> list[ConversationParticipant]:
    return session.exec(
        select(ConversationParticipant).where(ConversationParticipant.conversation_id == conversation_id)
    ).all()


def _agents_for_auto_response(session: Session, conversation: Conversation) -> list[Agent]:
    if conversation.kind == "activity":
        return []

    if conversation.kind == "admin":
        from sqlalchemy import or_
        return session.exec(
            select(Agent)
            .join(AgentWorkgroup, AgentWorkgroup.agent_id == Agent.id)
            .where(
                AgentWorkgroup.workgroup_id == conversation.workgroup_id,
                or_(Agent.description == ADMIN_AGENT_SENTINEL, Agent.name.in_(ADMIN_TEAM_NAMES)),
            )
        ).all()

    if conversation.kind in ("job", "engagement"):
        # If specific agents were assigned as participants, use only those.
        participants = _conversation_participants(session, conversation.id)
        agent_ids = [item.agent_id for item in participants if item.agent_id]
        if agent_ids:
            return session.exec(
                select(Agent)
                .join(AgentWorkgroup, AgentWorkgroup.agent_id == Agent.id)
                .where(
                    Agent.id.in_(agent_ids),
                    AgentWorkgroup.workgroup_id == conversation.workgroup_id,
                    Agent.description != ADMIN_AGENT_SENTINEL,
                )
                .order_by(Agent.created_at.asc())
            ).all()
        # Otherwise, all non-admin agents in the workgroup.
        return session.exec(
            select(Agent)
            .join(AgentWorkgroup, AgentWorkgroup.agent_id == Agent.id)
            .where(
                AgentWorkgroup.workgroup_id == conversation.workgroup_id,
                Agent.description != ADMIN_AGENT_SENTINEL,
            )
            .order_by(Agent.created_at.asc())
        ).all()

    # Direct conversations: only participating agents.
    participants = _conversation_participants(session, conversation.id)
    agent_ids = [item.agent_id for item in participants if item.agent_id]
    if not agent_ids:
        return []

    return session.exec(
        select(Agent)
        .join(AgentWorkgroup, AgentWorkgroup.agent_id == Agent.id)
        .where(Agent.id.in_(agent_ids), AgentWorkgroup.workgroup_id == conversation.workgroup_id)
        .order_by(Agent.created_at.asc())
    ).all()


# ---------------------------------------------------------------------------
# Org files loader
# ---------------------------------------------------------------------------

def _load_org_files(session: Session, workgroup: Workgroup) -> list[dict] | None:
    """Load the organization's files list for a workgroup, or None."""
    if not workgroup.organization_id:
        return None
    org = session.get(Organization, workgroup.organization_id)
    return org.files if org else None


# ---------------------------------------------------------------------------
# Admin agent
# ---------------------------------------------------------------------------

def build_admin_agent_reply(session: Session, agent: Agent, conversation: Conversation, trigger: Message) -> tuple[str, str]:
    """Build an admin agent reply via run_claude. Returns (text, slug).

    Builds the full admin team (lead + sub-agents) so the lead can
    delegate to specialists via the Task tool.
    """
    if trigger.sender_type != "user" or not trigger.sender_user_id:
        return "I only process admin commands from user messages.", ""

    workgroup = session.get(Workgroup, conversation.workgroup_id)
    if not workgroup:
        return "(Admin agent error: workgroup not found.)", ""

    org_files = _load_org_files(session, workgroup)

    # Find all admin agents so the lead can delegate to sub-agents.
    from teaparty_app.services.admin_workspace import find_admin_agents
    all_admin_agents = find_admin_agents(session, workgroup.id)
    sub_agents = [a for a in all_admin_agents if a.id != agent.id]

    with materialized_files(session, workgroup, conversation) as mat_ctx:
        files_context = (
            "Your workgroup's files are in the current working directory. "
            "Use Read, Edit, Write, Glob, and Grep."
        )

        # Build lead definition with team roster.
        lead_def = build_agent_json(
            agent, conversation, workgroup,
            files_context=files_context,
            org_files=org_files,
            teammates=sub_agents,
        )
        lead_slug = slugify(agent.name)

        # Build sub-agent definitions (they get admin CLI docs via their prompts).
        agents_dict = {lead_slug: lead_def}
        for sub in sub_agents:
            sub_def = build_agent_json(
                sub, conversation, workgroup,
                files_context=files_context,
                org_files=org_files,
            )
            agents_dict[slugify(sub.name)] = sub_def

        agents_json = json.dumps(agents_dict)

        user_msg = build_user_message(session, conversation, trigger)

        extra_env: dict[str, str] = {
            "TEAPARTY_USER_ID": trigger.sender_user_id,
            "TEAPARTY_WORKGROUP_ID": conversation.workgroup_id,
        }
        if workgroup.organization_id:
            extra_env["TEAPARTY_ORG_ID"] = workgroup.organization_id

        try:
            result = asyncio.run(run_claude(
                user_message=user_msg,
                agent_name=lead_slug,
                agents_json=agents_json,
                permission_mode="acceptEdits",
                allowed_tools=["Bash", "Read", "Write", "Edit", "Glob", "Grep", "Task"],
                max_turns=25,
                cwd=mat_ctx.dir_path,
                settings_json=mat_ctx.settings_json,
                conversation_id=conversation.id,
                extra_env=extra_env,
            ))
        except Exception:
            logger.exception("Admin agent %s reply failed for conversation %s", agent.name, conversation.id)
            return "(Admin agent encountered an error.)", ""

        record_llm_usage(
            session, conversation.id, agent.id, result.model or agent.model,
            result.input_tokens, result.output_tokens,
            "reply", result.duration_ms,
        )

        if result.is_error:
            logger.warning("Admin agent %s error: %s", agent.name, result.error)
            return "(Admin agent encountered an error.)", ""

        return result.text, result.slug


# ---------------------------------------------------------------------------
# Core: run_agent_auto_responses
# ---------------------------------------------------------------------------

def run_agent_auto_responses(session: Session, conversation: Conversation, trigger: Message) -> list[Message]:
    """Main entry point: determine which agents respond and invoke ``claude -p`` for each."""

    if conversation.is_archived:
        return []

    # Enforce max_rounds for job conversations and read permission_mode.
    permission_mode = "acceptEdits"
    if conversation.kind == "job":
        job = session.exec(
            select(Job).where(Job.conversation_id == conversation.id)
        ).first()
        if job:
            permission_mode = getattr(job, "permission_mode", "acceptEdits") or "acceptEdits"
            if isinstance(job.max_rounds, int):
                round_count = session.exec(
                    select(func.count()).select_from(Message).where(
                        Message.conversation_id == conversation.id,
                        Message.sender_type == "user",
                    )
                ).one()
                if isinstance(round_count, int) and round_count > job.max_rounds:
                    return []

    # Project conversations: hierarchical team with org lead + liaisons.
    # Checked before _agents_for_auto_response since project teams don't use
    # workgroup agents directly — they build ephemeral liaison definitions.
    if conversation.kind == "project":
        if trigger.sender_type != "user":
            return []
        project = session.exec(
            select(Project).where(Project.conversation_id == conversation.id)
        ).first()
        if project:
            return _run_project_team_response(session, conversation, trigger, project)
        return []

    agents = _agents_for_auto_response(session, conversation)
    if not agents:
        return []

    # Admin agents respond in admin and direct conversations.
    admin_agents = [agent for agent in agents if is_admin_agent(agent)]
    if admin_agents:
        if conversation.kind not in ("admin", "direct") or trigger.sender_type != "user":
            return []

        # For admin conversations, prefer the lead; for DMs, use the participant.
        if conversation.kind == "admin":
            from teaparty_app.services.admin_workspace.bootstrap import _ADMIN_TEAM_LEAD_NAME
            admin_agent = next((a for a in admin_agents if a.name == _ADMIN_TEAM_LEAD_NAME), admin_agents[0])
        else:
            admin_agent = admin_agents[0]
        _set_activity(conversation.id, admin_agent.id, admin_agent.name, "composing")
        session_slug = ""
        try:
            content, session_slug = build_admin_agent_reply(session, admin_agent, conversation, trigger)
        except Exception:
            logger.exception("Admin agent reply failed for conversation %s", conversation.id)
            content = "Something went wrong processing that request. Please try again."
        finally:
            _clear_activity(conversation.id, admin_agent.id)
        agent_message = Message(
            conversation_id=conversation.id,
            sender_type="agent",
            sender_agent_id=admin_agent.id,
            content=content,
            requires_response=False,
            response_to_message_id=trigger.id,
        )
        session.add(agent_message)
        session.flush()
        queued_delete_workgroup_id = consume_queued_workgroup_deletion(session)
        if queued_delete_workgroup_id and queued_delete_workgroup_id == conversation.workgroup_id:
            delete_workgroup_data(session, queued_delete_workgroup_id)
            return []

        # Auto-title admin conversations from the Claude session slug.
        if conversation.kind == "admin" and session_slug:
            _apply_session_title(session, conversation, session_slug)

        return [agent_message]

    candidates = [agent for agent in agents if not is_admin_agent(agent)]
    if not candidates:
        return []

    # Job conversations: @each fans out independently, @mention routes to a
    # specific agent, otherwise default to multi-agent team mode.
    if conversation.kind == "job":
        if trigger.sender_type != "user":
            return []
        if _is_each_invocation(trigger.content):
            return _run_single_agent_responses(session, conversation, trigger, candidates, permission_mode=permission_mode)
        mentioned = _resolve_mentioned_agent(trigger.content, candidates)
        if mentioned:
            return _run_single_agent_responses(session, conversation, trigger, [mentioned], permission_mode=permission_mode)
        # Default: team mode when multiple agents, single-agent otherwise.
        if len(candidates) > 1:
            return _run_team_response(session, conversation, trigger, candidates, permission_mode=permission_mode)
        return _run_single_agent_responses(session, conversation, trigger, candidates, permission_mode=permission_mode)

    # Task conversations: only user messages trigger auto-responses.
    if conversation.kind == "task":
        if trigger.sender_type != "user":
            return []
        return _run_single_agent_responses(session, conversation, trigger, candidates)

    # Engagement conversations: inject orchestration env vars for operations agents.
    if conversation.kind == "engagement":
        extra_env = _build_orchestration_env(session, candidates[0], conversation) if candidates else None
        return _run_single_agent_responses(session, conversation, trigger, candidates, extra_env=extra_env)

    # Direct conversations: single-agent path.
    return _run_single_agent_responses(session, conversation, trigger, candidates)


def _apply_session_title(
    session: Session,
    conversation: Conversation,
    slug: str,
) -> None:
    """Update an admin conversation's name from the Claude session slug."""
    from teaparty_app.services.sync_events import publish_sync_event

    # Only auto-title conversations that still have a generic/placeholder name.
    name = (conversation.name or "").strip()
    if name and name != "Administration" and not name.startswith("Admin session") and name != "New session":
        return

    conversation.name = slug
    session.add(conversation)
    try:
        commit_with_retry(session)
    except Exception:
        logger.debug("Failed to persist session slug as conversation title", exc_info=True)
        return

    if conversation.workgroup_id:
        publish_sync_event(
            session, "workgroup", conversation.workgroup_id,
            "sync:tree_changed", {"workgroup_id": conversation.workgroup_id},
        )


def _build_orchestration_env(session: Session, agent: Agent, conversation: Conversation) -> dict[str, str] | None:
    """Build env vars for coordinator agents in operations workgroups."""
    workgroup_id = conversation.workgroup_id
    if not workgroup_id:
        return None
    workgroup = session.get(Workgroup, workgroup_id)
    if not workgroup or not workgroup.organization_id:
        return None
    return {
        "TEAPARTY_AGENT_ID": agent.id,
        "TEAPARTY_WORKGROUP_ID": workgroup_id,
        "TEAPARTY_ORG_ID": workgroup.organization_id,
    }


def _run_single_agent_responses(
    session: Session,
    conversation: Conversation,
    trigger: Message,
    candidates: list[Agent],
    extra_env: dict[str, str] | None = None,
    permission_mode: str = "acceptEdits",
) -> list[Message]:
    """Single-shot claude -p invocation for each candidate agent."""

    workgroup = session.get(Workgroup, conversation.workgroup_id)
    if not workgroup:
        return []

    org_files = _load_org_files(session, workgroup)
    resumable = _is_resumable_conversation(conversation)

    # Materialize files once for all agents; sync back after the loop.
    with materialized_files(session, workgroup, conversation) as mat_ctx:
        files_context = (
            "Your workgroup's files are in the current working directory. "
            "Use Read, Edit, Write, Glob, and Grep."
        )

        created: list[Message] = []

        for agent in candidates:
            if is_conversation_cancelled(conversation.id):
                _cancelled_conversations.discard(conversation.id)
                break

            _set_activity(conversation.id, agent.id, agent.name, "composing", "thinking")

            try:
                agent_def = build_agent_json(
                    agent, conversation, workgroup,
                    files_context=files_context,
                    org_files=org_files,
                )
                slug = slugify(agent.name)
                agents_json = json.dumps({slug: agent_def})

                # Determine whether to resume an existing Claude session.
                resume_id = conversation.claude_session_id if resumable else None

                if resume_id:
                    # Resume: send only the trigger content (Claude has full prior context).
                    user_msg = trigger.content
                else:
                    # Fresh: reconstruct history via prompt builder.
                    user_msg = build_user_message(session, conversation, trigger)

                # Build per-agent env if engagement context applies
                agent_extra_env = extra_env
                if extra_env and agent.id != candidates[0].id:
                    # Update TEAPARTY_AGENT_ID for the specific agent
                    agent_extra_env = {**extra_env, "TEAPARTY_AGENT_ID": agent.id}

                result = asyncio.run(run_claude(
                    user_message=user_msg,
                    agent_name=slug,
                    agents_json=agents_json,
                    permission_mode=permission_mode,
                    max_turns=getattr(workgroup, "team_max_turns", 30) or 30,
                    cwd=mat_ctx.dir_path,
                    settings_json=mat_ctx.settings_json,
                    conversation_id=conversation.id,
                    resume_session_id=resume_id,
                    extra_env=agent_extra_env,
                ))

                # If resume failed, clear session and retry fresh.
                if resume_id and result.is_error:
                    logger.warning(
                        "Session resume failed for conversation %s, retrying fresh: %s",
                        conversation.id, result.error,
                    )
                    conversation.claude_session_id = None
                    session.add(conversation)
                    user_msg = build_user_message(session, conversation, trigger)
                    result = asyncio.run(run_claude(
                        user_message=user_msg,
                        agent_name=slug,
                        agents_json=agents_json,
                        permission_mode=permission_mode,
                        max_turns=getattr(workgroup, "team_max_turns", 30) or 30,
                        cwd=mat_ctx.dir_path,
                        settings_json=mat_ctx.settings_json,
                        conversation_id=conversation.id,
                        extra_env=agent_extra_env,
                    ))

                # Persist session ID on success for resumable conversations.
                if resumable and not result.is_error and result.session_id:
                    conversation.claude_session_id = result.session_id
                    session.add(conversation)

                record_llm_usage(
                    session, conversation.id, agent.id, result.model or agent.model,
                    result.input_tokens, result.output_tokens,
                    "reply", result.duration_ms,
                )

                content = result.text if not result.is_error else f"(Agent error: {result.error})"
            except Exception:
                logger.exception("Agent %s reply failed for conversation %s", agent.name, conversation.id)
                content = "(Agent encountered an error while composing a reply.)"
            finally:
                _clear_activity(conversation.id, agent.id)

            agent_message = Message(
                conversation_id=conversation.id,
                sender_type="agent",
                sender_agent_id=agent.id,
                content=content,
                requires_response=infer_requires_response(content),
                response_to_message_id=trigger.id,
            )
            session.add(agent_message)
            session.flush()
            created.append(agent_message)

            # Commit after each agent so frontend sees incremental progress.
            try:
                commit_with_retry(session)
            except Exception as exc:
                logger.warning("Mid-chain commit failed: %s", exc)

            # Push new message to SSE subscribers.
            from teaparty_app.services.event_bus import publish
            publish(conversation.id, {
                "type": "message",
                "id": agent_message.id,
                "conversation_id": agent_message.conversation_id,
                "sender_type": agent_message.sender_type,
                "sender_agent_id": agent_message.sender_agent_id,
                "sender_user_id": None,
                "content": agent_message.content,
                "requires_response": agent_message.requires_response,
                "response_to_message_id": agent_message.response_to_message_id,
                "created_at": agent_message.created_at.isoformat() if agent_message.created_at else None,
            })

    _clear_activity(conversation.id)
    return created



def _run_team_response(
    session: Session,
    conversation: Conversation,
    trigger: Message,
    candidates: list[Agent],
    permission_mode: str = "acceptEdits",
) -> list[Message]:
    """Route multi-agent conversations through a streaming ``claude -p`` invocation.

    Spawns a single ``claude -p`` subprocess with all agents via ``--agents``
    and the lead designated via ``--agent``.  Events are read from stdout
    line-by-line in a background thread and stored as Messages incrementally
    so the frontend picks them up via polling.
    """
    from teaparty_app.services.team_bridge import process_team_events_sync
    from teaparty_app.services.team_registry import register_session
    from teaparty_app.services.team_session import TeamSession

    workgroup = session.get(Workgroup, conversation.workgroup_id)
    if not workgroup:
        return []

    org_files = _load_org_files(session, workgroup)
    lead = _select_lead(candidates, session=session, workgroup_id=conversation.workgroup_id)
    others = [a for a in candidates if a.id != lead.id]
    lead_slug = slugify(lead.name)

    # Materialize files so agents can use Read/Write/Glob/Grep.
    with materialized_files(session, workgroup, conversation) as mat_ctx:
        files_context = (
            "Your workgroup's files are in the current working directory. "
            "Use Read, Edit, Write, Glob, and Grep."
        )

        # Only lead shows as composing initially; sub-agents are set
        # when the lead delegates to them via Task tool_use events.
        _set_activity(conversation.id, lead.id, lead.name, "composing", "team")

        try:
            user_msg = build_user_message(session, conversation, trigger)

            # Create and run the team session.
            team = TeamSession(conversation.id, worktree_path=mat_ctx.dir_path)
            register_session(conversation.id, team)

            team.run(
                agents=candidates,
                user_message=user_msg,
                workgroup=workgroup,
                conversation_name=conversation.name or "",
                conversation_description=conversation.description or "",
                lead_slug=lead_slug,
                files_context=files_context,
                teammates=others or None,
                settings_json=mat_ctx.settings_json,
                permission_mode=permission_mode,
                org_files=org_files,
            )

            # Drain events and store as Messages.
            created = process_team_events_sync(session, team, conversation, trigger)

            if not created:
                logger.warning(
                    "Team session for conversation %s produced no messages. "
                    "Falling back to single-agent responses.",
                    conversation.id,
                )
                _clear_activity(conversation.id)
                return _run_single_agent_responses(session, conversation, trigger, candidates, permission_mode=permission_mode)

            # Record usage against the lead agent.
            record_llm_usage(
                session, conversation.id, lead.id, lead.model,
                0, 0, "reply", int((time.time() - team.started_at) * 1000),
            )

        except Exception:
            logger.exception("Team session failed for conversation %s", conversation.id)
            _clear_activity(conversation.id)
            # Fall back to single-agent sequential responses.
            return _run_single_agent_responses(session, conversation, trigger, candidates, permission_mode=permission_mode)

    _clear_activity(conversation.id)
    return created


def _run_project_team_response(
    session: Session,
    conversation: Conversation,
    trigger: Message,
    project: Project,
) -> list[Message]:
    """Run a hierarchical project team: org lead + liaison agents.

    Builds the project team agents (org lead + one liaison per workgroup),
    then runs them as a standard TeamSession.  Liaisons relay tasks to
    workgroup sub-teams via the ``relay-to-subteam`` CLI command.

    Project conversations belong to the organization — no workgroup files
    are materialized here.  The project team is coordination-only; actual
    file work happens in the sub-teams (job teams in workgroups).
    """
    import tempfile

    from teaparty_app.services.agent_definition import build_project_team_agents
    from teaparty_app.services.team_bridge import process_team_events_sync
    from teaparty_app.services.team_registry import register_session
    from teaparty_app.services.team_session import TeamSession

    org = session.get(Organization, project.organization_id)
    if not org:
        logger.warning("Organization %s not found for project %s", project.organization_id, project.id)
        return []

    org_files = org.files if org else None

    try:
        agents_dict, lead_slug, slug_to_id = build_project_team_agents(
            session, project, org_files=org_files,
        )
    except ValueError as e:
        logger.warning("Cannot build project team for %s: %s", project.id, e)
        return []

    # Build env vars that liaison agents need for the relay CLI.
    extra_env: dict[str, str] = {
        "TEAPARTY_PROJECT_ID": project.id,
        "TEAPARTY_ORG_ID": project.organization_id,
    }
    # Each liaison needs its own TEAPARTY_WORKGROUP_ID, but since all liaisons
    # share the same process, we set it per-workgroup in the liaison prompt's
    # Bash command template.  The CLI reads it from the environment at runtime.
    wg_id_map: dict[str, str] = {}
    for slug, entity_id in slug_to_id.items():
        if entity_id.startswith("liaison:"):
            wg_id = entity_id.split(":", 1)[1]
            wg_id_map[slug] = wg_id

    for slug, wg_id in wg_id_map.items():
        env_key = f"TEAPARTY_WORKGROUP_ID_{slug.upper().replace('-', '_')}"
        extra_env[env_key] = wg_id
    # Also set a default for single-workgroup projects.
    if len(wg_id_map) == 1:
        extra_env["TEAPARTY_WORKGROUP_ID"] = next(iter(wg_id_map.values()))

    # Resolve permission mode and max turns from project config.
    permission_mode = project.permission_mode or "plan"
    max_turns = project.max_turns or 30

    # Project team is coordination-only — use a temp dir as working directory.
    with tempfile.TemporaryDirectory(prefix="teaparty-project-") as tmpdir:
        _set_activity(conversation.id, "project-lead", "Project Lead", "composing", "team")

        try:
            user_msg = build_user_message(session, conversation, trigger)

            team = TeamSession(conversation.id, worktree_path=tmpdir)
            register_session(conversation.id, team)

            team.run(
                agents_dict=agents_dict,
                slug_to_id=slug_to_id,
                user_message=user_msg,
                lead_slug=lead_slug,
                permission_mode=permission_mode,
                extra_env=extra_env,
                max_turns_override=max(10, max_turns),
            )

            created = process_team_events_sync(session, team, conversation, trigger)

            if not created:
                logger.warning(
                    "Project team session for conversation %s produced no messages.",
                    conversation.id,
                )

            # Record usage against the project lead.
            record_llm_usage(
                session, conversation.id, "project-lead", project.model or "sonnet",
                0, 0, "reply", int((time.time() - team.started_at) * 1000),
            )

        except Exception:
            logger.exception("Project team session failed for conversation %s", conversation.id)
            _clear_activity(conversation.id)
            return []

    _clear_activity(conversation.id)
    return created


# ---------------------------------------------------------------------------
# Background auto-response trigger (for orchestration tools)
# ---------------------------------------------------------------------------

def _process_auto_responses_in_background(conversation_id: str, trigger_message_id: str) -> None:
    """Schedule agent auto-responses for a conversation in a background thread.

    Used by orchestration tools (create_job, post_to_job) to trigger
    the target team's agents to respond to new messages.
    """
    def _run() -> None:
        from teaparty_app.db import engine
        try:
            with Session(engine) as bg_session:
                conv = bg_session.get(Conversation, conversation_id)
                trigger = bg_session.get(Message, trigger_message_id)
                if conv and trigger:
                    run_agent_auto_responses(bg_session, conv, trigger)
                    commit_with_retry(bg_session)
        except Exception:
            logger.exception("Background auto-response failed for conversation %s", conversation_id)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()


# ---------------------------------------------------------------------------
# Periodic tick handlers
# ---------------------------------------------------------------------------

def process_triggered_todos(
    session: Session,
    allowed_workgroup_ids: set[str],
    limit: int = 50,
) -> list[Message]:
    """Evaluate poll-based triggers, then process all triggered todos."""
    if not allowed_workgroup_ids:
        return []

    from teaparty_app.models import AgentTodoItem

    now = utc_now()

    # Time-based: due_at <= now
    time_todos = session.exec(
        select(AgentTodoItem).where(
            AgentTodoItem.trigger_type == "time",
            AgentTodoItem.status == "pending",
            AgentTodoItem.triggered_at.is_(None),
            AgentTodoItem.due_at <= now,
            AgentTodoItem.workgroup_id.in_(allowed_workgroup_ids),
        )
    ).all()
    for todo in time_todos:
        todo.triggered_at = now
        todo.updated_at = now
        session.add(todo)

    # Job stall: last message older than stall_minutes
    stall_todos = session.exec(
        select(AgentTodoItem).where(
            AgentTodoItem.trigger_type == "job_stall",
            AgentTodoItem.status == "pending",
            AgentTodoItem.triggered_at.is_(None),
            AgentTodoItem.workgroup_id.in_(allowed_workgroup_ids),
        )
    ).all()
    for todo in stall_todos:
        if not todo.conversation_id:
            continue
        conv = session.get(Conversation, todo.conversation_id)
        if not conv or conv.is_archived:
            continue
        stall_minutes = (todo.trigger_config or {}).get("stall_minutes", 30)
        last_msg = session.exec(
            select(Message)
            .where(Message.conversation_id == todo.conversation_id)
            .order_by(Message.created_at.desc())
            .limit(1)
        ).first()
        if last_msg:
            threshold = last_msg.created_at + timedelta(minutes=stall_minutes)
            if now >= threshold:
                todo.triggered_at = now
                todo.updated_at = now
                session.add(todo)

    session.flush()

    # Process all triggered todos.
    triggered = session.exec(
        select(AgentTodoItem).where(
            AgentTodoItem.triggered_at.isnot(None),
            AgentTodoItem.status == "pending",
            AgentTodoItem.workgroup_id.in_(allowed_workgroup_ids),
        ).limit(limit)
    ).all()

    created: list[Message] = []
    for todo in triggered:
        agent = session.get(Agent, todo.agent_id)
        if not agent:
            todo.status = "cancelled"
            todo.completed_at = now
            todo.triggered_at = None
            session.add(todo)
            continue

        # Determine conversation.
        conversation = None
        if todo.conversation_id:
            conversation = session.get(Conversation, todo.conversation_id)
            if conversation and conversation.is_archived:
                conversation = None
        if not conversation:
            conversation = session.exec(
                select(Conversation).where(
                    Conversation.workgroup_id == todo.workgroup_id,
                    Conversation.kind == "job",
                    Conversation.is_archived == False,  # noqa: E712
                ).order_by(Conversation.created_at.desc()).limit(1)
            ).first()
        if not conversation:
            continue

        trigger_desc = {
            "time": "scheduled time reached",
            "job_stall": f"conversation quiet for {(todo.trigger_config or {}).get('stall_minutes', 30)}+ minutes",
            "message_match": "keyword match in conversation",
            "file_changed": f"file '{(todo.trigger_config or {}).get('file_path', '')}' changed",
            "job_resolved": "job archived",
            "todo_completed": "dependent todo completed",
        }.get(todo.trigger_type, todo.trigger_type)

        proactive_message = Message(
            conversation_id=conversation.id,
            sender_type="agent",
            sender_agent_id=agent.id,
            content=(
                f"{agent.name}: My task '{todo.title}' has been triggered "
                f"({trigger_desc}). Let me follow up."
            ),
            requires_response=False,
        )
        session.add(proactive_message)

        todo.status = "in_progress"
        todo.triggered_at = None
        todo.updated_at = now
        session.add(todo)

        from teaparty_app.services.todo_helpers import _materialize_todo_file
        _materialize_todo_file(session, agent, todo.workgroup_id)

        session.commit()
        created.append(proactive_message)
        created.extend(run_agent_auto_responses(session, conversation, proactive_message))

    return created
