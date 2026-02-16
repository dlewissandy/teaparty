"""Agent runtime — orchestrates agent responses using the ``claude`` CLI.

This module is the entry point for all agent auto-responses.  When a user
posts a message, the conversation router calls ``run_agent_auto_responses``
which:

1.  Determines eligible agents via ``_agents_for_auto_response``.
2.  Uses the turn policy to decide who responds.
3.  Builds a system prompt and user message via the prompt builder.
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
from datetime import timedelta

from sqlmodel import Session, select

from teaparty_app.config import settings
from teaparty_app.db import commit_with_retry
from teaparty_app.models import (
    Agent,
    AgentFollowUpTask,
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
    handle_admin_message,
    is_admin_agent,
)
from teaparty_app.services.claude_runner import run_claude
from teaparty_app.services.llm_usage import record_llm_usage
from teaparty_app.services.prompt_builder import (
    build_system_prompt,
    build_user_message,
    build_workgroup_files_context,
)
from teaparty_app.services.turn_policy import (
    advance_workflow_state,
    determine_next_turns,
    parse_workflow_state,
)

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
# Small helpers
# ---------------------------------------------------------------------------

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

    if conversation.kind in ("topic", "engagement"):
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
# Follow-up scheduling
# ---------------------------------------------------------------------------

def _pick_follow_up_user_target(
    participants: list[ConversationParticipant],
    sent_by_user_id: str | None,
) -> str | None:
    for participant in participants:
        if participant.user_id and participant.user_id != sent_by_user_id:
            return participant.user_id
    return None


def schedule_follow_up_if_needed(session: Session, conversation: Conversation, agent: Agent, message: Message) -> None:
    if not message.requires_response:
        return

    participants = _conversation_participants(session, conversation.id)
    waiting_user_id = _pick_follow_up_user_target(participants, message.sender_user_id)
    if not waiting_user_id:
        return

    task = AgentFollowUpTask(
        conversation_id=conversation.id,
        agent_id=agent.id,
        origin_message_id=message.id,
        waiting_on_sender_type="user",
        waiting_on_user_id=waiting_user_id,
        reason="agent asked for an update",
        due_at=utc_now() + timedelta(minutes=agent.follow_up_minutes),
    )
    session.add(task)


def close_tasks_satisfied_by_message(session: Session, message: Message) -> None:
    tasks = session.exec(
        select(AgentFollowUpTask).where(
            AgentFollowUpTask.conversation_id == message.conversation_id,
            AgentFollowUpTask.status == "pending",
            AgentFollowUpTask.waiting_on_sender_type == message.sender_type,
        )
    ).all()

    now = utc_now()
    for task in tasks:
        if message.sender_type == "user" and task.waiting_on_user_id and task.waiting_on_user_id != message.sender_user_id:
            continue
        if message.sender_type == "agent" and task.waiting_on_agent_id and task.waiting_on_agent_id != message.sender_agent_id:
            continue

        task.status = "completed"
        task.completed_at = now
        session.add(task)


# ---------------------------------------------------------------------------
# Admin agent (unchanged)
# ---------------------------------------------------------------------------

def build_admin_agent_reply(session: Session, agent: Agent, conversation: Conversation, trigger: Message) -> str:
    if trigger.sender_type != "user" or not trigger.sender_user_id:
        return "I only process admin commands from user messages."
    return handle_admin_message(
        session=session,
        workgroup_id=conversation.workgroup_id,
        requester_user_id=trigger.sender_user_id,
        content=trigger.content,
        conversation_id=conversation.id,
    )


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
        content = build_admin_agent_reply(session, admin_agent, conversation, trigger)
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
        _clear_activity(conversation.id, admin_agent.id)
        queued_delete_workgroup_id = consume_queued_workgroup_deletion(session)
        if queued_delete_workgroup_id and queued_delete_workgroup_id == conversation.workgroup_id:
            delete_workgroup_data(session, queued_delete_workgroup_id)
            return []
        return [agent_message]

    candidates = [agent for agent in agents if not is_admin_agent(agent)]
    if not candidates:
        return []

    # Resolve workgroup and workflow state.
    workgroup = session.get(Workgroup, conversation.workgroup_id)
    workflow_state = parse_workflow_state(workgroup, conversation) if workgroup else None

    # Build workflow context string for prompts.
    workflow_context = ""
    if workflow_state and workflow_state.get("status") == "active":
        step = workflow_state.get("current_step", {})
        workflow_context = (
            f"Active workflow step: {step.get('number', '?')}. {step.get('label', '')}\n"
            f"Your task in this step is described in the workflow definition."
        )

    # Determine who responds.
    directive = determine_next_turns(conversation, trigger, candidates, workflow_state)
    if not directive.agent_ids:
        return []

    # Build file context once (shared by all agents).
    files_context = build_workgroup_files_context(workgroup, conversation) if workgroup else ""

    # Invoke claude for each agent.
    agent_map = {a.id: a for a in candidates}
    created: list[Message] = []

    for agent_id in directive.agent_ids:
        agent = agent_map.get(agent_id)
        if not agent:
            continue

        step_label = directive.workflow_step_label or "thinking"
        _set_activity(conversation.id, agent.id, agent.name, "composing", step_label)

        system_prompt = build_system_prompt(
            agent, conversation,
            workflow_context=workflow_context,
            workgroup_files_context=files_context,
        )
        user_msg = build_user_message(session, conversation, trigger)

        result = asyncio.run(run_claude(
            system_prompt=system_prompt,
            user_message=user_msg,
            model=_resolve_model_alias(agent.model),
            max_turns=1,
        ))

        # Record usage.
        record_llm_usage(
            session, conversation.id, agent.id, result.model or agent.model,
            result.input_tokens, result.output_tokens,
            "reply", result.duration_ms,
        )

        # Store the agent's reply.
        content = result.text if not result.is_error else f"(Agent error: {result.error})"
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

        _clear_activity(conversation.id, agent.id)
        schedule_follow_up_if_needed(session, conversation, agent, agent_message)
        created.append(agent_message)

        # Commit after each agent so frontend sees incremental progress.
        try:
            commit_with_retry(session)
        except Exception as exc:
            logger.warning("Mid-chain commit failed: %s", exc)

    # Advance workflow state if applicable.
    if workflow_state and workgroup and workflow_state.get("status") == "active":
        new_state_md = advance_workflow_state(workgroup, conversation, workflow_state)
        if new_state_md:
            _update_workflow_state_file(workgroup, conversation, new_state_md)
            session.add(workgroup)
            try:
                commit_with_retry(session)
            except Exception as exc:
                logger.warning("Failed to advance workflow state: %s", exc)

    _clear_activity(conversation.id)
    return created


def _update_workflow_state_file(workgroup: Workgroup, conversation: Conversation, content: str) -> None:
    """Write the new workflow state markdown into the workgroup files."""
    topic_id = conversation.id if conversation.kind == "topic" else ""
    files: list[dict] = list(workgroup.files or [])
    for f in files:
        if f.get("path") == "_workflow_state.md" and f.get("topic_id", "") == topic_id:
            f["content"] = content
            workgroup.files = files
            return
    # Shouldn't normally happen, but create if missing.
    files.append({"path": "_workflow_state.md", "content": content, "topic_id": topic_id})
    workgroup.files = files


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

def process_due_followups(
    session: Session,
    allowed_workgroup_ids: set[str],
    limit: int | None = None,
) -> list[Message]:
    if not allowed_workgroup_ids:
        return []

    now = utc_now()
    scan_limit = settings.follow_up_scan_limit if limit is None else min(limit, settings.follow_up_scan_limit)
    rows = session.exec(
        select(AgentFollowUpTask, Conversation)
        .join(Conversation, AgentFollowUpTask.conversation_id == Conversation.id)
        .where(
            AgentFollowUpTask.status == "pending",
            AgentFollowUpTask.due_at <= now,
            Conversation.workgroup_id.in_(allowed_workgroup_ids),
            Conversation.is_archived == False,  # noqa: E712
        )
        .order_by(AgentFollowUpTask.due_at.asc())
        .limit(scan_limit)
    ).all()

    created: list[Message] = []
    for task, conversation in rows:
        if conversation.workgroup_id not in allowed_workgroup_ids:
            continue

        agent = session.get(Agent, task.agent_id)
        if not agent:
            task.status = "cancelled"
            task.completed_at = now
            session.add(task)
            continue

        follow_up_message = Message(
            conversation_id=conversation.id,
            sender_type="agent",
            sender_agent_id=agent.id,
            content=(
                f"{agent.name}: follow-up on my earlier request. "
                "If blocked, share blocker + owner + ETA so I can help."
            ),
            requires_response=False,
            response_to_message_id=task.origin_message_id,
        )
        session.add(follow_up_message)
        task.status = "completed"
        task.completed_at = now
        session.add(task)
        commit_with_retry(session)
        created.append(follow_up_message)
        created.extend(run_agent_auto_responses(session, conversation, follow_up_message))

    return created


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

    # Topic stall: last message older than stall_minutes
    stall_todos = session.exec(
        select(AgentTodoItem).where(
            AgentTodoItem.trigger_type == "topic_stall",
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
                    Conversation.kind == "topic",
                    Conversation.is_archived == False,  # noqa: E712
                ).order_by(Conversation.created_at.desc()).limit(1)
            ).first()
        if not conversation:
            continue

        trigger_desc = {
            "time": "scheduled time reached",
            "topic_stall": f"conversation quiet for {(todo.trigger_config or {}).get('stall_minutes', 30)}+ minutes",
            "message_match": "keyword match in conversation",
            "file_changed": f"file '{(todo.trigger_config or {}).get('file_path', '')}' changed",
            "topic_resolved": "topic archived",
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

        from teaparty_app.services.agent_tools import _materialize_todo_file
        _materialize_todo_file(session, agent, todo.workgroup_id)

        session.commit()
        created.append(proactive_message)
        created.extend(run_agent_auto_responses(session, conversation, proactive_message))

    return created
