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
from sqlmodel import Session, select

from teaparty_app.config import settings
from teaparty_app.db import commit_with_retry
from teaparty_app.models import (
    Agent,
    Conversation,
    ConversationParticipant,
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
            return _run_single_agent_responses(session, conversation, trigger, candidates)
        mentioned = _resolve_mentioned_agent(trigger.content, candidates)
        if mentioned:
            return _run_single_agent_responses(session, conversation, trigger, [mentioned])
        # Default: team mode when multiple agents, single-agent otherwise.
        if len(candidates) > 1:
            return _run_job_team_response(session, conversation, trigger, candidates)
        return _run_single_agent_responses(session, conversation, trigger, candidates)

    # Task conversations: only user messages trigger auto-responses.
    if conversation.kind == "task":
        if trigger.sender_type != "user":
            return []
        return _run_single_agent_responses(session, conversation, trigger, candidates)

    # Direct and engagement conversations: single-agent path.
    return _run_single_agent_responses(session, conversation, trigger, candidates)


def _run_single_agent_responses(
    session: Session,
    conversation: Conversation,
    trigger: Message,
    candidates: list[Agent],
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

                result = asyncio.run(run_claude(
                    user_message=user_msg,
                    agent_name=slug,
                    agents_json=agents_json,
                    max_turns=agent_def.get("maxTurns", 3),
                    cwd=mat_ctx.dir_path,
                    settings_json=mat_ctx.settings_json,
                    conversation_id=conversation.id,
                    resume_session_id=resume_id,
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
                        max_turns=agent_def.get("maxTurns", 3),
                        cwd=mat_ctx.dir_path,
                        settings_json=mat_ctx.settings_json,
                        conversation_id=conversation.id,
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


def _run_job_team_response(
    session: Session,
    conversation: Conversation,
    trigger: Message,
    candidates: list[Agent],
) -> list[Message]:
    """Route job conversations through Claude's multi-agent team feature.

    All candidate agents are passed via ``--agents``.  The first agent is
    designated as the lead (``--agent``).  The ``stream-json --verbose``
    output contains structured events showing all inter-agent communication
    — no text parsing needed.
    """
    from teaparty_app.services.team_output_parser import parse_team_output

    workgroup = session.get(Workgroup, conversation.workgroup_id)
    if not workgroup:
        return []

    lead = _select_lead(candidates)
    others = [a for a in candidates if a.id != lead.id]

    # Set activity for all candidates.
    for agent in candidates:
        _set_activity(conversation.id, agent.id, agent.name, "composing", "team")

    try:
        with materialized_files(session, workgroup, conversation) as mat_ctx:
            files_context = (
                "Your workgroup's files are in the current working directory. "
                "Use Read, Edit, Write, Glob, and Grep."
            )

            user_msg = build_user_message(session, conversation, trigger)

            # Build agent definitions.  The lead gets a teammates roster.
            # Use display names as keys so the lead's prompt matches --agents keys.
            name_to_id: dict[str, str] = {}
            agents_dict: dict[str, dict] = {}

            lead_key = lead.name
            name_to_id[lead_key] = lead.id
            agents_dict[lead_key] = build_agent_json(
                lead, conversation, workgroup,
                files_context=files_context,
                teammates=others if others else None,
            )

            for agent in others:
                key = agent.name
                # Handle duplicate names by appending a suffix.
                if key in agents_dict:
                    key = f"{key}-{agent.id[:6]}"
                name_to_id[key] = agent.id
                agents_dict[key] = build_agent_json(
                    agent, conversation, workgroup,
                    files_context=files_context,
                )

            agents_json = json.dumps(agents_dict)
            agent_names = [a.name for a in candidates]

            # Determine max turns: lead needs turns for delegation + discussion.
            max_turns = max(6, 4 * len(candidates))

            result = asyncio.run(run_claude(
                user_message=user_msg,
                agent_name=lead_key,
                agents_json=agents_json,
                max_turns=max_turns,
                timeout_seconds=max(180, 90 * len(candidates)),
                cwd=mat_ctx.dir_path,
                settings_json=mat_ctx.settings_json,
            ))

        # Record usage against the lead agent.
        record_llm_usage(
            session, conversation.id, lead.id, result.model or lead.model,
            result.input_tokens, result.output_tokens,
            "reply", result.duration_ms,
        )

        if result.is_error:
            logger.warning("Job team claude CLI failed: %s", result.error)
            error_msg = Message(
                conversation_id=conversation.id,
                sender_type="agent",
                sender_agent_id=lead.id,
                content=f"(Agent error: {result.error})",
                requires_response=False,
                response_to_message_id=trigger.id,
            )
            session.add(error_msg)
            session.flush()
            _clear_activity(conversation.id)
            return [error_msg]

        # Extract per-agent contributions from stream-json events.
        contributions = parse_team_output(result.events, name_to_id, agent_names)

        # Fallback: attribute everything to the lead.
        if not contributions and result.text:
            contributions = [(lead.id, result.text)]

        # Store each contribution as a separate Message.
        created: list[Message] = []
        for agent_id, content in contributions:
            if not content.strip():
                continue
            msg = Message(
                conversation_id=conversation.id,
                sender_type="agent",
                sender_agent_id=agent_id or lead.id,
                content=content,
                requires_response=infer_requires_response(content),
                response_to_message_id=trigger.id,
            )
            session.add(msg)
            session.flush()

            created.append(msg)

            try:
                commit_with_retry(session)
            except Exception as exc:
                logger.warning("Mid-chain commit failed: %s", exc)

    except Exception:
        logger.exception("Job team response failed for conversation %s", conversation.id)
        # Fall back to single-agent sequential responses.
        _clear_activity(conversation.id)
        return _run_single_agent_responses(session, conversation, trigger, candidates)

    _clear_activity(conversation.id)
    return created


def _run_team_response(
    session: Session,
    conversation: Conversation,
    trigger: Message,
    candidates: list[Agent],
) -> list[Message]:
    """Route multi-agent conversations through a persistent team session.

    The team session runs a long-lived ``claude`` process.  Messages are
    forwarded via stdin and agent responses are captured from stdout by
    the team bridge (Phase 3).
    """
    from teaparty_app.services.team_bridge import process_team_events_sync
    from teaparty_app.services.team_registry import get_or_create_session

    workgroup = session.get(Workgroup, conversation.workgroup_id)

    # Resolve worktree path for workspace-enabled workgroups.
    worktree_path: str | None = None
    if workgroup and workgroup.workspace_enabled:
        from teaparty_app.services.todo_helpers import _resolve_worktree
        wt, _ = _resolve_worktree(session, conversation)
        worktree_path = wt

    # Set activity for all candidates.
    for agent in candidates:
        _set_activity(conversation.id, agent.id, agent.name, "composing", "team session")

    try:
        # Start or reuse the team session.
        team = asyncio.run(get_or_create_session(
            conversation_id=conversation.id,
            agents=candidates,
            workgroup=workgroup,
            worktree_path=worktree_path,
            conversation_name=conversation.name or "",
            conversation_description=conversation.description or "",
        ))

        # Build user message from conversation history + trigger.
        user_msg = build_user_message(session, conversation, trigger)

        # Send the message to the team session.
        asyncio.run(team.send_message(user_msg))

        # Process events from the team session and convert to Messages.
        created = process_team_events_sync(session, team, conversation, trigger)

    except Exception:
        logger.exception("Team session failed for conversation %s", conversation.id)
        # Fall back to single-agent sequential responses.
        created = _run_single_agent_responses(session, conversation, trigger, candidates)

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
