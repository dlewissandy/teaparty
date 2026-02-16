"""Claude Code built-in tool: multi-turn coding assistant scoped to workgroup files."""

from __future__ import annotations

import logging
import os
from uuid import uuid4

from sqlmodel import Session, select

from teaparty_app.config import settings
from teaparty_app.models import Agent, Conversation, Membership, Message, Workgroup
from teaparty_app.services import llm_client
from teaparty_app.services.activity import post_file_change_activity
from teaparty_app.services.tools import _files_for_conversation, _normalize_workgroup_files

logger = logging.getLogger(__name__)

_MAX_TOOL_TURNS = 12
_MAX_TOKENS = 4096
_MAX_RESPONSE_CHARS = 20_000

_CLAUDE_CODE_TOOLS = [
    {
        "name": "list_files",
        "description": "List all file paths in the workgroup.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "read_file",
        "description": "Read the full content of a file by its path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to read."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "create_file",
        "description": "Create a new file with the given path and content. Fails if the file already exists.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to create."},
                "content": {"type": "string", "description": "The file content."},
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_file",
        "description": "Replace the entire content of an existing file. Fails if the file does not exist.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to edit."},
                "content": {"type": "string", "description": "The new file content."},
            },
            "required": ["path", "content"],
        },
    },
]


def _get_api_key() -> str:
    return os.getenv("ANTHROPIC_API_KEY", "").strip() or (settings.anthropic_api_key or "").strip()


def _tool_list_files(workgroup: Workgroup, conversation: Conversation) -> str:
    files = _files_for_conversation(workgroup, conversation)
    if not files:
        return "No files in this workgroup."
    paths = sorted(entry["path"] for entry in files)
    return "\n".join(paths)


def _tool_read_file(workgroup: Workgroup, conversation: Conversation, path: str) -> str:
    files = _files_for_conversation(workgroup, conversation)
    for entry in files:
        if entry["path"] == path:
            return entry["content"] or "(empty file)"
    return f"Error: file '{path}' not found."


def _tool_create_file(
    session: Session,
    workgroup: Workgroup,
    conversation: Conversation,
    wg_id: str,
    agent_id: str,
    path: str,
    content: str,
) -> str:
    if len(path) > 512:
        return "Error: file path must be 512 characters or fewer."
    if len(content) > 200_000:
        return "Error: file content must be 200000 characters or fewer."

    scoped_files = _files_for_conversation(workgroup, conversation)
    for entry in scoped_files:
        if entry["path"] == path:
            return f"Error: file '{path}' already exists."

    topic_id = conversation.id if conversation.kind == "job" else ""
    all_files = _normalize_workgroup_files(workgroup)
    created = {"id": str(uuid4()), "path": path, "content": content, "topic_id": topic_id}
    all_files.append(created)
    workgroup.files = all_files
    session.add(workgroup)
    post_file_change_activity(
        session, wg_id, "file_added", path, actor_agent_id=agent_id,
    )
    return f"Created file '{path}'."


def _tool_edit_file(
    session: Session,
    workgroup: Workgroup,
    conversation: Conversation,
    wg_id: str,
    agent_id: str,
    path: str,
    content: str,
) -> str:
    if len(path) > 512:
        return "Error: file path must be 512 characters or fewer."
    if len(content) > 200_000:
        return "Error: file content must be 200000 characters or fewer."

    scoped_files = _files_for_conversation(workgroup, conversation)
    target: dict[str, str] | None = None
    for entry in scoped_files:
        if entry["path"] == path:
            target = entry
            break
    if not target:
        return f"Error: file '{path}' not found."

    all_files = _normalize_workgroup_files(workgroup)
    for entry in all_files:
        if entry["id"] == target["id"]:
            entry["content"] = content
            break
    workgroup.files = all_files
    session.add(workgroup)
    post_file_change_activity(
        session, wg_id, "file_updated", path, actor_agent_id=agent_id,
    )
    return f"Updated file '{path}'."


def _dispatch_tool(
    tool_name: str,
    tool_input: dict,
    session: Session,
    workgroup: Workgroup,
    conversation: Conversation,
    wg_id: str,
    agent_id: str,
) -> str:
    if tool_name == "list_files":
        return _tool_list_files(workgroup, conversation)
    if tool_name == "read_file":
        return _tool_read_file(workgroup, conversation, tool_input.get("path", ""))
    if tool_name == "create_file":
        return _tool_create_file(
            session, workgroup, conversation, wg_id, agent_id,
            tool_input.get("path", ""), tool_input.get("content", ""),
        )
    if tool_name == "edit_file":
        return _tool_edit_file(
            session, workgroup, conversation, wg_id, agent_id,
            tool_input.get("path", ""), tool_input.get("content", ""),
        )
    return f"Error: unknown tool '{tool_name}'."


def _build_user_message(
    session: Session,
    conversation: Conversation,
    trigger: Message,
) -> str:
    rows = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.asc())
    ).all()

    max_messages = 40
    max_chars = 12_000
    if len(rows) > max_messages:
        rows = rows[-max_messages:]

    lines: list[str] = []
    for row in rows:
        if row.id == trigger.id:
            continue
        label = "user" if row.sender_type == "user" else "agent"
        content = " ".join(row.content.split())
        if len(content) > 300:
            content = content[:300].rstrip() + "..."
        lines.append(f"- {label}: {content}")

    history = "\n".join(lines)
    if len(history) > max_chars:
        history = "...\n" + history[-max_chars:]

    parts: list[str] = []
    if history:
        parts.append(f"Recent conversation context:\n{history}\n")
    parts.append(f"User request:\n{trigger.content}")
    return "\n".join(parts)


def _build_system_prompt(
    agent: Agent,
    conversation: Conversation,
    workgroup: Workgroup,
) -> str:
    topic = (conversation.topic or conversation.name or "general").strip()
    role = (agent.role or agent.description or "").strip()
    return (
        f"You are a coding assistant operating within the workgroup '{workgroup.name}'. "
        f"Agent name: {agent.name}. "
        f"Agent role: {role or 'general coding assistant'}. "
        f"Conversation topic: {topic}. "
        "You have access to the workgroup's files via tools: list_files, read_file, create_file, edit_file. "
        "Always read a file before editing it so you understand the current content. "
        "When creating or editing files, provide the complete file content. "
        "File paths must be 512 characters or fewer. File content must be 200000 characters or fewer. "
        "Be concise in your explanations but thorough in your code."
    )


def _run_loop(
    session: Session,
    agent: Agent,
    conversation: Conversation,
    trigger: Message,
    workgroup: Workgroup,
) -> str:
    system_prompt = _build_system_prompt(agent, conversation, workgroup)
    user_message = _build_user_message(session, conversation, trigger)

    model = llm_client.resolve_model("reply", (agent.model or "").strip())
    messages: list[dict] = [{"role": "user", "content": user_message}]
    wg_id = workgroup.id
    agent_id = agent.id

    for _turn in range(_MAX_TOOL_TURNS):
        response = llm_client.create_message(
            model=model,
            max_tokens=_MAX_TOKENS,
            system=system_prompt,
            tools=_CLAUDE_CODE_TOOLS,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            text_parts = [block.text for block in response.content if hasattr(block, "text")]
            return "\n".join(text_parts) if text_parts else "(no response)"

        # Collect tool uses and text from this turn
        tool_uses = []
        for block in response.content:
            if block.type == "tool_use":
                tool_uses.append(block)

        if not tool_uses:
            text_parts = [block.text for block in response.content if hasattr(block, "text")]
            return "\n".join(text_parts) if text_parts else "(no response)"

        # Append assistant message, then tool results
        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for tool_use in tool_uses:
            result = _dispatch_tool(
                tool_use.name,
                tool_use.input,
                session, workgroup, conversation, wg_id, agent_id,
            )
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})

    # Exhausted turns — extract any text from the last response
    text_parts = [block.text for block in response.content if hasattr(block, "text")]
    return "\n".join(text_parts) if text_parts else "(max tool turns reached)"


def claude_code(
    session: Session,
    agent: Agent,
    conversation: Conversation,
    trigger: Message,
) -> str:
    if trigger.sender_type != "user" or not trigger.sender_user_id:
        return "claude_code requires a direct user request."

    membership = session.exec(
        select(Membership).where(
            Membership.workgroup_id == conversation.workgroup_id,
            Membership.user_id == trigger.sender_user_id,
        )
    ).first()
    if not membership:
        return "User is not a member of this workgroup."
    if membership.role != "owner":
        return "Only the workgroup owner can use claude_code."

    workgroup = session.get(Workgroup, conversation.workgroup_id)
    if not workgroup:
        return "Workgroup not found."

    if not llm_client.llm_enabled():
        return "claude_code unavailable: no LLM provider configured."

    try:
        result = _run_loop(session, agent, conversation, trigger, workgroup)
    except Exception as exc:
        logger.warning("claude_code loop failed for agent %s: %s", agent.id, exc)
        return f"claude_code encountered an error: {exc}"

    if len(result) > _MAX_RESPONSE_CHARS:
        result = result[:_MAX_RESPONSE_CHARS] + "\n...(truncated)"
    return result
