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
import re
import threading
import time
from sqlmodel import Session, func, select

from teaparty_app.config import settings
from teaparty_app.db import commit_with_retry
from teaparty_app.models import (
    Agent,
    Conversation,
    ConversationParticipant,
    Job,
    Message,
    Workgroup,
    utc_now,
)
from teaparty_app.services.admin_workspace import (
    ADMIN_AGENT_SENTINEL,
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


def _set_activity(conversation_id: str, agent_id: str, agent_name: str, phase: str, detail: str = "") -> None:
    with _activity_lock:
        entries = _conversation_activity.setdefault(conversation_id, [])
        for entry in entries:
            if entry["agent_id"] == agent_id:
                entry.update(agent_name=agent_name, phase=phase, detail=detail, started_at=time.time())
                return
        entries.append(
            {"agent_id": agent_id, "agent_name": agent_name, "phase": phase, "detail": detail, "started_at": time.time()}
        )


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


def _select_lead(candidates: list[Agent]) -> Agent:
    """Return the lead agent from candidates, falling back to the first."""
    return next((a for a in candidates if a.is_lead), candidates[0])


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
        return session.exec(
            select(Agent).where(
                Agent.workgroup_id == conversation.workgroup_id,
                Agent.description == ADMIN_AGENT_SENTINEL,
            )
        ).all()

    if conversation.kind in ("job", "engagement"):
        # If specific agents were assigned as participants, use only those.
        participants = _conversation_participants(session, conversation.id)
        agent_ids = [item.agent_id for item in participants if item.agent_id]
        if agent_ids:
            return session.exec(
                select(Agent)
                .where(
                    Agent.id.in_(agent_ids),
                    Agent.workgroup_id == conversation.workgroup_id,
                    Agent.description != ADMIN_AGENT_SENTINEL,
                )
                .order_by(Agent.created_at.asc())
            ).all()
        # Otherwise, all non-admin agents in the workgroup.
        return session.exec(
            select(Agent)
            .where(
                Agent.workgroup_id == conversation.workgroup_id,
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
        .where(Agent.id.in_(agent_ids), Agent.workgroup_id == conversation.workgroup_id)
        .order_by(Agent.created_at.asc())
    ).all()


# ---------------------------------------------------------------------------
# Admin agent (unchanged)
# ---------------------------------------------------------------------------

def build_admin_agent_reply(session: Session, agent: Agent, conversation: Conversation, trigger: Message) -> str:
    if trigger.sender_type != "user" or not trigger.sender_user_id:
        return "I only process admin commands from user messages."

    # Fast path: deterministic regex for structured commands (no LLM needed).
    from teaparty_app.services.admin_workspace import _handle_admin_message_deterministic
    deterministic = _handle_admin_message_deterministic(
        session=session,
        workgroup_id=conversation.workgroup_id,
        requester_user_id=trigger.sender_user_id,
        content=trigger.content,
    )
    if deterministic is not None:
        return deterministic

    # Conversational path: use claude CLI like every other agent.
    workgroup = session.get(Workgroup, conversation.workgroup_id)
    if not workgroup:
        return "Workgroup not found."

    with materialized_files(session, workgroup, conversation) as mat_ctx:
        files_context = (
            "Your workgroup's files are in the current working directory. "
            "Use Read, Edit, Write, Glob, and Grep."
        )

        user_msg = build_user_message(session, conversation, trigger)

        agent_def = build_agent_json(agent, conversation, workgroup, files_context=files_context)
        slug = slugify(agent.name)
        agents_json_str = json.dumps({slug: agent_def})

        result = asyncio.run(run_claude(
            user_message=user_msg,
            agent_name=slug,
            agents_json=agents_json_str,
            max_turns=1,
            cwd=mat_ctx.dir_path,
            settings_json=mat_ctx.settings_json,
        ))

    if result.is_error:
        logger.warning("Admin agent claude CLI failed: %s", result.error)
        from teaparty_app.services.admin_workspace.parsing import _help_text
        return f"I wasn't able to process that. {_help_text()}"

    # Record usage.
    record_llm_usage(
        session, conversation.id, agent.id, result.model or agent.model,
        result.input_tokens, result.output_tokens,
        "admin", result.duration_ms,
    )

    return result.text


# ---------------------------------------------------------------------------
# Claude model alias mapping
# ---------------------------------------------------------------------------

_MODEL_ALIASES: dict[str, str] = {
    "claude-sonnet-4-5": "sonnet",
    "claude-haiku-4-5": "haiku",
    "claude-opus-4-6": "opus",
}


def _resolve_model_alias(model: str) -> str:
    """Map an Anthropic model ID to a claude CLI alias (sonnet, haiku, opus)."""
    return _MODEL_ALIASES.get(model, model)


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

    agents = _agents_for_auto_response(session, conversation)
    if not agents:
        return []

    # Admin conversations are still single-agent command handlers.
    admin_agents = [agent for agent in agents if is_admin_agent(agent)]
    if admin_agents:
        if conversation.kind != "admin" or trigger.sender_type != "user":
            return []

        admin_agent = admin_agents[0]
        _set_activity(conversation.id, admin_agent.id, admin_agent.name, "composing")
        try:
            content = build_admin_agent_reply(session, admin_agent, conversation, trigger)
        except Exception:
            logger.exception("Admin agent reply failed for conversation %s", conversation.id)
            from teaparty_app.services.admin_workspace.parsing import _help_text
            content = f"I wasn't able to process that. {_help_text()}"
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
        extra_env = _build_orchestration_env(session, candidates[0]) if candidates else None
        return _run_single_agent_responses(session, conversation, trigger, candidates, extra_env=extra_env)

    # Direct conversations: single-agent path.
    return _run_single_agent_responses(session, conversation, trigger, candidates)


def _build_orchestration_env(session: Session, agent: Agent) -> dict[str, str] | None:
    """Build env vars for coordinator agents in operations workgroups."""
    workgroup = session.get(Workgroup, agent.workgroup_id)
    if not workgroup or not workgroup.organization_id:
        return None
    return {
        "TEAPARTY_AGENT_ID": agent.id,
        "TEAPARTY_WORKGROUP_ID": agent.workgroup_id,
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
                    max_turns=agent_def.get("maxTurns", 3),
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
                        max_turns=agent_def.get("maxTurns", 3),
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

    lead = _select_lead(candidates)
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
