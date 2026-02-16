"""Build system prompts and user messages for agent invocations.

Replaces the massive prompt construction scattered across the old
agent_runtime.py with a focused, readable module.
"""

from __future__ import annotations

from sqlmodel import Session, select

from teaparty_app.models import (
    Agent,
    Conversation,
    Message,
    User,
    Workgroup,
)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def build_system_prompt(
    agent: Agent,
    conversation: Conversation,
    workflow_context: str = "",
    workgroup_files_context: str = "",
) -> str:
    """Assemble the system prompt from agent config and conversation metadata."""

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
        "topic": "a topic discussion",
        "engagement": "an engagement conversation",
    }.get(conversation.kind, f"a {conversation.kind} conversation")
    parts.append(f"You are participating in {kind_label}.")
    if conversation.name and conversation.name != "general":
        parts.append(f"Topic: {conversation.name}")
    if conversation.description:
        parts.append(f"Description: {conversation.description}")

    # Workflow step (if active)
    if workflow_context:
        parts.append("")
        parts.append(workflow_context)

    # Embedded workgroup files (for non-filesystem agents)
    if workgroup_files_context:
        parts.append("")
        parts.append(workgroup_files_context)

    # Minimal guidelines — let claude be claude
    parts.append("")
    parts.append("Guidelines:")
    parts.append("- Respond as this character with your distinct perspective.")
    parts.append("- Do not prefix your response with your name.")
    parts.append("- Be direct and substantive.")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# User message (conversation history + trigger)
# ---------------------------------------------------------------------------

def build_user_message(
    session: Session,
    conversation: Conversation,
    trigger: Message,
    max_messages: int = 40,
    max_chars: int = 12000,
) -> str:
    """Format conversation history and the trigger message as the user prompt."""

    # Fetch recent messages
    rows = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc())
        .limit(max_messages)
    ).all()
    rows = list(reversed(rows))  # oldest first

    # Build sender name maps
    user_names, agent_names = _load_sender_names(session, rows)

    # Format history
    history_lines: list[str] = []
    char_count = 0
    for msg in rows:
        if msg.id == trigger.id:
            continue  # trigger is shown separately
        label = _sender_label(msg, user_names, agent_names)
        line = f"- {label}: {msg.content}"
        char_count += len(line)
        if char_count > max_chars:
            break
        history_lines.append(line)

    parts: list[str] = []
    if history_lines:
        parts.append("Conversation history (oldest to newest):")
        parts.extend(history_lines)
        parts.append("")

    # Trigger message
    trigger_label = _sender_label(trigger, user_names, agent_names)
    parts.append(f"Latest message from {trigger_label}:")
    parts.append(trigger.content)

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Workgroup file context
# ---------------------------------------------------------------------------

def build_workgroup_files_context(workgroup: Workgroup, conversation: Conversation) -> str:
    """Embed relevant workgroup files into the prompt (for agents without filesystem tools)."""
    files: list[dict] = workgroup.files or []
    if not files:
        return ""

    # Filter to conversation-scoped files if any, otherwise all
    topic_id = conversation.id if conversation.kind == "topic" else ""
    scoped = [f for f in files if f.get("topic_id") == topic_id] if topic_id else []
    shared = [f for f in files if not f.get("topic_id")]

    relevant = scoped + shared
    if not relevant:
        return ""

    parts = ["Reference files:"]
    for f in relevant:
        path = f.get("path", "untitled")
        content = f.get("content", "")
        if content:
            parts.append(f"\n--- {path} ---")
            # Truncate very large files
            if len(content) > 3000:
                parts.append(content[:3000] + "\n... (truncated)")
            else:
                parts.append(content)

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_sender_names(
    session: Session, rows: list[Message]
) -> tuple[dict[str, str], dict[str, str]]:
    """Return (user_id→name, agent_id→name) maps for messages."""
    from teaparty_app.models import Agent as AgentModel

    user_ids = {m.sender_user_id for m in rows if m.sender_user_id}
    agent_ids = {m.sender_agent_id for m in rows if m.sender_agent_id}

    user_names: dict[str, str] = {}
    if user_ids:
        users = session.exec(select(User).where(User.id.in_(user_ids))).all()
        user_names = {u.id: (u.name or u.email.split("@")[0]) for u in users}

    agent_names: dict[str, str] = {}
    if agent_ids:
        agents = session.exec(select(AgentModel).where(AgentModel.id.in_(agent_ids))).all()
        agent_names = {a.id: a.name for a in agents}

    return user_names, agent_names


def _sender_label(
    msg: Message,
    user_names: dict[str, str],
    agent_names: dict[str, str],
) -> str:
    if msg.sender_type == "user" and msg.sender_user_id:
        name = user_names.get(msg.sender_user_id, "user")
        return f"user:{name}"
    if msg.sender_type == "agent" and msg.sender_agent_id:
        name = agent_names.get(msg.sender_agent_id, "agent")
        return f"agent:{name}"
    if msg.sender_type == "system":
        return "system"
    return msg.sender_type
