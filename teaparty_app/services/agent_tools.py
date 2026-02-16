"""Anthropic API tool schemas and dispatch for regular agent SDK loop."""

from __future__ import annotations

import json
import logging
import re
import time
from uuid import uuid4

from sqlalchemy import func
from sqlmodel import Session, select

from teaparty_app.models import (
    Agent, AgentTodoItem, Conversation, ConversationParticipant,
    Membership, Message, User, Workgroup, utc_now, new_id,
)
from teaparty_app.services.activity import post_file_change_activity
from teaparty_app.services.tools import (
    _files_for_conversation,
    _normalize_workgroup_files,
    resolve_custom_tool,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Built-in tool schemas (Anthropic `tools` format)
# ---------------------------------------------------------------------------

AGENT_TOOL_SCHEMAS: list[dict] = [
    {
        "name": "summarize_topic",
        "description": "Summarize the recent conversation messages.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "list_open_followups",
        "description": "List the count of open follow-up tasks in this conversation.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "suggest_next_step",
        "description": "Suggest a concrete next step based on context.",
        "input_schema": {
            "type": "object",
            "properties": {
                "context": {
                    "type": "string",
                    "description": "Brief description of what you need a next step for.",
                },
            },
            "required": [],
        },
    },
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
        "name": "search_files",
        "description": "Search workgroup files by description or content. Returns ranked matches with excerpts. Use this to find files when you don't know the exact path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "What to search for — a description, topic, keyword, or question about file contents.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the full content of a file by its path. Always read a file before editing it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to read."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "add_file",
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
    {
        "name": "rename_file",
        "description": "Rename (move) a file from one path to another.",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_path": {"type": "string", "description": "Current file path."},
                "dest_path": {"type": "string", "description": "New file path."},
            },
            "required": ["source_path", "dest_path"],
        },
    },
    {
        "name": "delete_file",
        "description": "Delete a file by its path.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "The file path to delete."},
            },
            "required": ["path"],
        },
    },
    {
        "name": "create_todo",
        "description": "Create a todo item for yourself with an optional signal-based trigger. Use this to track commitments, schedule follow-ups, or react to events like file changes, keyword matches, or other agents completing work.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Short title for the todo (max 200 chars)."},
                "description": {"type": "string", "description": "Detailed description (max 2000 chars)."},
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "urgent"],
                    "description": "Priority level. Default: medium.",
                },
                "trigger_type": {
                    "type": "string",
                    "enum": ["time", "topic_stall", "message_match", "file_changed", "topic_resolved", "todo_completed", "manual"],
                    "description": "When should this todo fire? Default: manual.",
                },
                "trigger_config": {
                    "type": "object",
                    "description": "Signal-specific config. For topic_stall: {stall_minutes: N}. For message_match: {keywords: [...]}. For file_changed: {file_path: '...'}. For todo_completed: {todo_id: '...'}.",
                },
                "conversation_id": {"type": "string", "description": "Scope to a specific conversation. Default: current conversation."},
                "due_at": {"type": "string", "description": "ISO 8601 datetime for time-based triggers (e.g. '2025-01-15T14:00:00Z')."},
            },
            "required": ["title"],
        },
    },
    {
        "name": "list_todos",
        "description": "List your todo items, optionally filtered by status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "done", "cancelled", "all"],
                    "description": "Filter by status. Default: shows pending + in_progress.",
                },
            },
            "required": [],
        },
    },
    {
        "name": "update_todo",
        "description": "Update one of your todo items. Use this to mark todos done, change priority, or update details.",
        "input_schema": {
            "type": "object",
            "properties": {
                "todo_id": {"type": "string", "description": "The ID of the todo to update."},
                "status": {
                    "type": "string",
                    "enum": ["pending", "in_progress", "done", "cancelled"],
                    "description": "New status.",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "urgent"],
                    "description": "New priority.",
                },
                "title": {"type": "string", "description": "New title."},
                "description": {"type": "string", "description": "New description."},
            },
            "required": ["todo_id"],
        },
    },
    {
        "name": "list_workflows",
        "description": "List available workflows (from workflows/*.md files) with their titles and triggers.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "get_workflow_state",
        "description": "Read the current workflow state (_workflow_state.md) for this conversation.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "advance_workflow",
        "description": "Create or update the workflow state file (_workflow_state.md) with new content. Use this to start a workflow, advance to the next step, or mark it complete.",
        "input_schema": {
            "type": "object",
            "properties": {
                "state_content": {
                    "type": "string",
                    "description": "The full markdown content for the _workflow_state.md file.",
                },
            },
            "required": ["state_content"],
        },
    },
    {
        "name": "send_direct_message",
        "description": (
            "Send a private direct message to a human workgroup member. "
            "This opens (or reuses) a sidebar DM conversation between you and the recipient. "
            "Use sparingly — only for off-topic questions, capability inquiries, "
            "private feedback, or discussions that don't belong in the shared topic. "
            "Do NOT use this for things that should be said in the current conversation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "recipient_name": {
                    "type": "string",
                    "description": "The name of the workgroup member to message.",
                },
                "message": {
                    "type": "string",
                    "description": "The message content to send.",
                },
            },
            "required": ["recipient_name", "message"],
        },
    },
]

_SCHEMA_BY_NAME: dict[str, dict] = {s["name"]: s for s in AGENT_TOOL_SCHEMAS}

# Tools that should NOT be included in the SDK tool list (handled separately)
_EXCLUDED_TOOLS = {"claude_code", "web_search"}

# ---------------------------------------------------------------------------
# Build tool list for a specific agent
# ---------------------------------------------------------------------------


def build_tool_schemas(
    session: Session,
    agent: Agent,
) -> list[dict]:
    """Return Anthropic API tool schemas for the agent's configured tools."""
    allowed = set(agent.tool_names or []) - _EXCLUDED_TOOLS
    schemas: list[dict] = []

    for tool_name in allowed:
        if tool_name in _SCHEMA_BY_NAME:
            schemas.append(_SCHEMA_BY_NAME[tool_name])
        elif tool_name.startswith("custom:"):
            schema = _custom_tool_to_schema(session, tool_name)
            if schema:
                schemas.append(schema)

    return schemas


def _custom_tool_to_schema(session: Session, tool_ref: str) -> dict | None:
    """Convert a custom tool definition to an Anthropic API tool schema."""
    tool_def = resolve_custom_tool(session, tool_ref)
    if not tool_def or not tool_def.enabled:
        return None

    input_schema = tool_def.input_schema if isinstance(tool_def.input_schema, dict) else {}
    if not input_schema:
        input_schema = {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "Input text for the tool."},
            },
            "required": [],
        }

    return {
        "name": tool_ref.replace(":", "_"),
        "description": tool_def.description or tool_def.name,
        "input_schema": input_schema,
    }


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


def dispatch_agent_tool(
    session: Session,
    agent: Agent,
    conversation: Conversation,
    trigger: Message,
    tool_name: str,
    tool_input: dict,
) -> str:
    """Execute a tool by name with structured input. Returns result text."""
    # Built-in conversation tools
    if tool_name == "summarize_topic":
        return _tool_summarize_topic(session, conversation)

    if tool_name == "list_open_followups":
        return _tool_list_open_followups(session, conversation)

    if tool_name == "suggest_next_step":
        return _tool_suggest_next_step(tool_input)

    # Todo tools
    if tool_name == "create_todo":
        return _tool_create_todo(session, agent, conversation, tool_input)

    if tool_name == "list_todos":
        return _tool_list_todos(session, agent, tool_input)

    if tool_name == "update_todo":
        return _tool_update_todo(session, agent, conversation, tool_input)

    # File tools
    workgroup = session.get(Workgroup, conversation.workgroup_id)
    if not workgroup:
        return "Error: workgroup not found."

    if tool_name == "list_files":
        return _tool_list_files(workgroup, conversation)

    if tool_name == "search_files":
        return _tool_search_files(
            session, workgroup, conversation, agent.id,
            tool_input.get("query", ""),
        )

    if tool_name == "read_file":
        return _tool_read_file(workgroup, conversation, tool_input.get("path", ""))

    if tool_name == "add_file":
        return _tool_add_file(
            session, workgroup, conversation, agent.id,
            tool_input.get("path", ""), tool_input.get("content", ""),
        )

    if tool_name == "edit_file":
        return _tool_edit_file(
            session, workgroup, conversation, agent.id,
            tool_input.get("path", ""), tool_input.get("content", ""),
        )

    if tool_name == "rename_file":
        return _tool_rename_file(
            session, workgroup, conversation, agent.id,
            tool_input.get("source_path", ""), tool_input.get("dest_path", ""),
        )

    if tool_name == "delete_file":
        return _tool_delete_file(
            session, workgroup, conversation, agent.id,
            tool_input.get("path", ""),
        )

    if tool_name == "list_workflows":
        return _tool_list_workflows(workgroup, conversation)

    if tool_name == "get_workflow_state":
        return _tool_get_workflow_state(workgroup, conversation)

    if tool_name == "advance_workflow":
        return _tool_advance_workflow(
            session, workgroup, conversation, agent.id,
            tool_input.get("state_content", ""),
        )

    if tool_name == "send_direct_message":
        return _tool_send_direct_message(
            session, agent, conversation,
            tool_input.get("recipient_name", ""),
            tool_input.get("message", ""),
        )

    # Custom tools (name mangled: "custom_<id>")
    if tool_name.startswith("custom_"):
        return _dispatch_custom_tool(session, agent, conversation, trigger, tool_name, tool_input)

    return f"Error: unknown tool '{tool_name}'."


# ---------------------------------------------------------------------------
# Built-in tool implementations
# ---------------------------------------------------------------------------


def _tool_summarize_topic(session: Session, conversation: Conversation) -> str:
    from sqlmodel import select
    from teaparty_app.models import Message as MsgModel

    recent = session.exec(
        select(MsgModel)
        .where(MsgModel.conversation_id == conversation.id)
        .order_by(MsgModel.created_at.desc())
        .limit(6)
    ).all()
    if not recent:
        return "No messages yet in this topic."

    snippets = []
    for message in reversed(recent):
        label = "user" if message.sender_type == "user" else f"agent:{message.sender_agent_id}"
        snippets.append(f"- {label}: {message.content[:120]}")
    return "Recent summary:\n" + "\n".join(snippets)


def _tool_list_open_followups(session: Session, conversation: Conversation) -> str:
    from sqlmodel import select
    from teaparty_app.models import AgentFollowUpTask

    count = session.exec(
        select(AgentFollowUpTask)
        .where(
            AgentFollowUpTask.conversation_id == conversation.id,
            AgentFollowUpTask.status == "pending",
        )
    ).all()
    return f"Open follow-up tasks in this conversation: {len(count)}"


def _tool_suggest_next_step(tool_input: dict) -> str:
    context = (tool_input.get("context") or "").lower()
    if "blocked" in context or "stuck" in context:
        return "Suggested next step: post blockers, owner, and one unblocking action with ETA."
    if "decision" in context:
        return "Suggested next step: list options, criteria, and owner to finalize in one message."
    return "Suggested next step: clarify owner, deadline, and explicit done condition."


def _tool_list_files(workgroup: Workgroup, conversation: Conversation) -> str:
    files = _files_for_conversation(workgroup, conversation)
    if not files:
        return "No files in this workgroup."
    paths = sorted(entry["path"] for entry in files)
    return "Files:\n" + "\n".join(f"- {p}" for p in paths)


def _tool_search_files(
    session: Session,
    workgroup: Workgroup,
    conversation: Conversation,
    agent_id: str,
    query: str,
) -> str:
    """Search workgroup files using LLM ranking, with keyword fallback."""
    if not query:
        return "Error: query is required."

    files = _files_for_conversation(workgroup, conversation)
    if not files:
        return "No files in this workgroup."

    # For ≤3 files, return all with previews (no LLM needed)
    if len(files) <= 3:
        lines = []
        for entry in sorted(files, key=lambda f: f["path"]):
            preview = (entry.get("content") or "")[:200]
            if preview:
                lines.append(f"- {entry['path']}\n  Preview: {preview}")
            else:
                lines.append(f"- {entry['path']}\n  (empty file)")
        return "All files:\n" + "\n".join(lines)

    # Build compact manifest for LLM
    manifest_entries = []
    for entry in sorted(files, key=lambda f: f["path"]):
        preview = (entry.get("content") or "")[:300]
        manifest_entries.append({"path": entry["path"], "preview": preview})

    # Cap total manifest size to ~30k chars
    manifest_json = json.dumps(manifest_entries)
    if len(manifest_json) > 30000:
        # Trim previews progressively
        for max_preview in (150, 75, 0):
            manifest_entries = [
                {"path": e["path"], "preview": (e["preview"])[:max_preview]}
                for e in manifest_entries
            ]
            manifest_json = json.dumps(manifest_entries)
            if len(manifest_json) <= 30000:
                break

    # Call haiku for ranking
    try:
        return _search_files_with_llm(
            session, conversation.id, agent_id, query, manifest_json,
        )
    except Exception:
        logger.warning("search_files LLM call failed, falling back to keyword matching", exc_info=True)
        return _search_files_keyword_fallback(query, files)


def _search_files_with_llm(
    session: Session,
    conversation_id: str,
    agent_id: str,
    query: str,
    manifest_json: str,
) -> str:
    """Call a cheap model to rank files by relevance to the query."""
    from teaparty_app.services import llm_client
    from teaparty_app.services.llm_usage import record_llm_usage

    model = llm_client.resolve_model("cheap", "claude-haiku-4-5")
    start = time.monotonic()

    response = llm_client.create_message(
        model=model,
        max_tokens=1024,
        system="You rank files by relevance to a search query. Return strict JSON only: an array of objects with keys \"path\", \"excerpt\" (a brief relevant snippet from the preview), and \"relevance\" (\"high\", \"medium\", or \"low\"). Return at most 10 results, only include relevant files, and sort by relevance descending.",
        messages=[
            {
                "role": "user",
                "content": f"Search query: {query}\n\nFiles:\n{manifest_json}",
            },
        ],
    )

    duration_ms = int((time.monotonic() - start) * 1000)
    record_llm_usage(
        session,
        conversation_id=conversation_id,
        agent_id=agent_id,
        model=model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        purpose="file_search",
        duration_ms=duration_ms,
    )

    # Extract JSON array from response
    response_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            response_text += block.text

    results = _extract_json_array(response_text)
    if not results:
        return "No matching files found."

    lines = []
    for item in results[:10]:
        path = item.get("path", "")
        excerpt = item.get("excerpt", "")
        relevance = item.get("relevance", "")
        line = f"- [{relevance}] {path}"
        if excerpt:
            line += f"\n  {excerpt}"
        lines.append(line)

    return "Search results:\n" + "\n".join(lines)


def _extract_json_array(text: str) -> list[dict] | None:
    """Extract a JSON array from LLM response text."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, list):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[.*\]", cleaned, flags=re.DOTALL)
    if not match:
        return None

    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, list) else None
    except json.JSONDecodeError:
        return None


def _search_files_keyword_fallback(query: str, files: list[dict]) -> str:
    """Simple keyword matching fallback when LLM is unavailable."""
    words = set(query.lower().split())
    if not words:
        return "No matching files found."

    scored: list[tuple[int, dict]] = []
    for entry in files:
        text = (entry["path"] + " " + (entry.get("content") or "")).lower()
        score = sum(1 for w in words if w in text)
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return "No matching files found."

    lines = []
    for score, entry in scored[:10]:
        preview = (entry.get("content") or "")[:200]
        line = f"- {entry['path']}"
        if preview:
            line += f"\n  Preview: {preview}"
        lines.append(line)

    return "Search results:\n" + "\n".join(lines)


def _tool_read_file(workgroup: Workgroup, conversation: Conversation, path: str) -> str:
    if not path:
        return "Error: path is required."
    files = _files_for_conversation(workgroup, conversation)
    for entry in files:
        if entry["path"] == path:
            return entry["content"] or "(empty file)"
    return f"Error: file '{path}' not found."


def _tool_add_file(
    session: Session,
    workgroup: Workgroup,
    conversation: Conversation,
    agent_id: str,
    path: str,
    content: str,
) -> str:
    if not path:
        return "Error: path is required."
    if len(path) > 512:
        return "Error: file path must be 512 characters or fewer."
    if len(content) > 200_000:
        return "Error: file content must be 200000 characters or fewer."

    scoped_files = _files_for_conversation(workgroup, conversation)
    for entry in scoped_files:
        if entry["path"] == path:
            return f"Error: file '{path}' already exists."

    topic_id = conversation.id if conversation.kind == "topic" else ""
    all_files = _normalize_workgroup_files(workgroup)
    created = {"id": str(uuid4()), "path": path, "content": content, "topic_id": topic_id}
    all_files.append(created)
    workgroup.files = all_files
    session.add(workgroup)
    post_file_change_activity(
        session, conversation.workgroup_id, "file_added", path,
        actor_agent_id=agent_id,
    )
    return f"Created file '{path}'."


def _tool_edit_file(
    session: Session,
    workgroup: Workgroup,
    conversation: Conversation,
    agent_id: str,
    path: str,
    content: str,
) -> str:
    if not path:
        return "Error: path is required."
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
        session, conversation.workgroup_id, "file_updated", path,
        actor_agent_id=agent_id,
    )
    return f"Updated file '{path}'."


def _tool_rename_file(
    session: Session,
    workgroup: Workgroup,
    conversation: Conversation,
    agent_id: str,
    source_path: str,
    dest_path: str,
) -> str:
    if not source_path or not dest_path:
        return "Error: source_path and dest_path are required."
    if len(source_path) > 512 or len(dest_path) > 512:
        return "Error: file path must be 512 characters or fewer."
    if source_path == dest_path:
        return f"Error: source and destination are the same ('{source_path}')."

    scoped_files = _files_for_conversation(workgroup, conversation)
    source: dict[str, str] | None = None
    for entry in scoped_files:
        if entry["path"] == dest_path:
            return f"Error: file '{dest_path}' already exists."
        if entry["path"] == source_path:
            source = entry
    if not source:
        return f"Error: file '{source_path}' not found."

    all_files = _normalize_workgroup_files(workgroup)
    for entry in all_files:
        if entry["id"] == source["id"]:
            entry["path"] = dest_path
            break
    workgroup.files = all_files
    session.add(workgroup)
    post_file_change_activity(
        session, conversation.workgroup_id, "file_renamed", f"{source_path} -> {dest_path}",
        actor_agent_id=agent_id,
    )
    return f"Renamed file '{source_path}' to '{dest_path}'."


def _tool_delete_file(
    session: Session,
    workgroup: Workgroup,
    conversation: Conversation,
    agent_id: str,
    path: str,
) -> str:
    if not path:
        return "Error: path is required."
    if len(path) > 512:
        return "Error: file path must be 512 characters or fewer."

    scoped_files = _files_for_conversation(workgroup, conversation)
    removed: dict[str, str] | None = None
    for entry in scoped_files:
        if entry["path"] == path:
            removed = entry
            break
    if not removed:
        return f"Error: file '{path}' not found."

    all_files = _normalize_workgroup_files(workgroup)
    retained = [entry for entry in all_files if entry["id"] != removed["id"]]
    workgroup.files = retained
    session.add(workgroup)
    post_file_change_activity(
        session, conversation.workgroup_id, "file_deleted", path,
        actor_agent_id=agent_id,
    )
    return f"Deleted file '{path}'."


# ---------------------------------------------------------------------------
# Workflow tool implementations
# ---------------------------------------------------------------------------

_WORKFLOW_STATE_PATH = "_workflow_state.md"


def _extract_workflow_title_and_trigger(content: str) -> tuple[str, str]:
    """Extract the first ``# Title`` and ``## Trigger`` section from markdown."""
    title = ""
    trigger = ""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") and not title:
            title = stripped[2:].strip()
        if stripped.startswith("## Trigger"):
            idx = content.index(stripped) + len(stripped)
            rest = content[idx:].strip()
            trigger_lines = []
            for tl in rest.splitlines():
                if tl.strip().startswith("## "):
                    break
                if tl.strip():
                    trigger_lines.append(tl.strip())
            trigger = " ".join(trigger_lines)[:200]
            break
    return title, trigger


def _tool_list_workflows(workgroup: Workgroup, conversation: Conversation) -> str:
    files = _files_for_conversation(workgroup, conversation)
    workflows = [
        f for f in files
        if f["path"].startswith("workflows/")
        and f["path"].endswith(".md")
        and f["path"] != "workflows/README.md"
    ]
    if not workflows:
        return "No workflows defined. Add markdown files under workflows/ to create them."

    lines = []
    for wf in sorted(workflows, key=lambda f: f["path"]):
        content = wf.get("content") or ""
        title, trigger = _extract_workflow_title_and_trigger(content)
        title = title or wf["path"]
        entry = f"- **{title}** (`{wf['path']}`)"
        if trigger:
            entry += f"\n  Trigger: {trigger}"
        lines.append(entry)

    return "Available workflows:\n" + "\n".join(lines)


def _tool_get_workflow_state(workgroup: Workgroup, conversation: Conversation) -> str:
    files = _files_for_conversation(workgroup, conversation)
    for f in files:
        if f["path"] == _WORKFLOW_STATE_PATH:
            return f.get("content") or "(empty state file)"
    return "No active workflow."


def _tool_advance_workflow(
    session: Session,
    workgroup: Workgroup,
    conversation: Conversation,
    agent_id: str,
    state_content: str,
) -> str:
    if not state_content.strip():
        return "Error: state_content is required."
    if len(state_content) > 200_000:
        return "Error: state content must be 200000 characters or fewer."

    scoped_files = _files_for_conversation(workgroup, conversation)
    existing = None
    for entry in scoped_files:
        if entry["path"] == _WORKFLOW_STATE_PATH:
            existing = entry
            break

    if existing:
        # Update existing state file
        all_files = _normalize_workgroup_files(workgroup)
        for entry in all_files:
            if entry["id"] == existing["id"]:
                entry["content"] = state_content
                break
        workgroup.files = all_files
        session.add(workgroup)
        post_file_change_activity(
            session, conversation.workgroup_id, "file_updated", _WORKFLOW_STATE_PATH,
            actor_agent_id=agent_id,
        )
        return f"Updated workflow state '{_WORKFLOW_STATE_PATH}'."
    else:
        # Create new state file (topic-scoped)
        topic_id = conversation.id if conversation.kind == "topic" else ""
        all_files = _normalize_workgroup_files(workgroup)
        created = {
            "id": str(uuid4()),
            "path": _WORKFLOW_STATE_PATH,
            "content": state_content,
            "topic_id": topic_id,
        }
        all_files.append(created)
        workgroup.files = all_files
        session.add(workgroup)
        post_file_change_activity(
            session, conversation.workgroup_id, "file_added", _WORKFLOW_STATE_PATH,
            actor_agent_id=agent_id,
        )
        return f"Created workflow state '{_WORKFLOW_STATE_PATH}'."


# ---------------------------------------------------------------------------
# Auto-select workflow on topic creation
# ---------------------------------------------------------------------------


def auto_select_workflow(
    session: Session,
    workgroup: Workgroup,
    conversation: Conversation,
) -> str | None:
    """Match a new topic against available workflows and bootstrap state.

    Returns the selected workflow path, or None if no match.
    """
    # Only shared (non-topic-scoped) files — no topic files exist yet
    all_files = _normalize_workgroup_files(workgroup)
    shared_files = [f for f in all_files if not f.get("topic_id")]
    workflows = [
        f for f in shared_files
        if f["path"].startswith("workflows/")
        and f["path"].endswith(".md")
        and f["path"] != "workflows/README.md"
    ]

    if not workflows:
        return None

    # Build manifest of {path, title, trigger} for each workflow
    manifest: list[dict[str, str]] = []
    for wf in workflows:
        content = wf.get("content") or ""
        title, trigger = _extract_workflow_title_and_trigger(content)
        manifest.append({
            "path": wf["path"],
            "title": title or wf["path"],
            "trigger": trigger,
        })

    if len(workflows) == 1:
        selected_path = manifest[0]["path"]
        selected_title = manifest[0]["title"]
    else:
        # Multiple workflows — ask Haiku to pick the best match
        topic_text = (conversation.name or conversation.topic or "").strip()
        description = (conversation.description or "").strip()
        selected_path = _match_workflow_to_topic(
            session, conversation.id, topic_text, description, manifest,
        )
        if not selected_path:
            return None
        selected_title = next(
            (m["title"] for m in manifest if m["path"] == selected_path),
            selected_path,
        )

    # Build and persist the initial state file
    topic_text = (conversation.name or conversation.topic or "").strip()
    state_content = _build_initial_workflow_state(selected_path, selected_title, topic_text)

    topic_id = conversation.id if conversation.kind == "topic" else ""
    all_files = _normalize_workgroup_files(workgroup)
    created = {
        "id": str(uuid4()),
        "path": _WORKFLOW_STATE_PATH,
        "content": state_content,
        "topic_id": topic_id,
    }
    all_files.append(created)
    workgroup.files = all_files
    session.add(workgroup)

    return selected_path


def _match_workflow_to_topic(
    session: Session,
    conversation_id: str,
    topic: str,
    description: str,
    workflows: list[dict[str, str]],
) -> str | None:
    """Use a cheap model to match a topic name/description against workflow triggers."""
    from teaparty_app.services import llm_client
    from teaparty_app.services.llm_usage import record_llm_usage

    manifest_json = json.dumps(workflows)
    topic_text = topic
    if description:
        topic_text += f" — {description}"

    try:
        model = llm_client.resolve_model("cheap", "claude-haiku-4-5")
        start = time.monotonic()

        response = llm_client.create_message(
            model=model,
            max_tokens=256,
            system=(
                "You match a conversation topic against available workflow triggers. "
                "Return strict JSON only: {\"path\": \"<workflow path>\", \"confidence\": <0.0-1.0>}. "
                "If no workflow is a good match, return {\"path\": null, \"confidence\": 0.0}."
            ),
            messages=[
                {
                    "role": "user",
                    "content": f"Topic: {topic_text}\n\nWorkflows:\n{manifest_json}",
                },
            ],
        )

        duration_ms = int((time.monotonic() - start) * 1000)
        record_llm_usage(
            session,
            conversation_id=conversation_id,
            agent_id=None,
            model=model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            purpose="workflow_selection",
            duration_ms=duration_ms,
        )

        raw_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                raw_text += block.text

        from teaparty_app.services.agent_runtime import _extract_json_object

        parsed = _extract_json_object(raw_text)
        if not parsed:
            return None

        path = parsed.get("path")
        confidence = float(parsed.get("confidence", 0.0))
        if path and confidence >= 0.5:
            return path
        return None

    except Exception:
        logger.warning("workflow auto-selection LLM call failed", exc_info=True)
        return None


def _build_initial_workflow_state(workflow_path: str, workflow_title: str, topic: str) -> str:
    """Return the initial ``_workflow_state.md`` content for a newly selected workflow."""
    return (
        f"# Workflow State\n"
        f"\n"
        f"- **Workflow**: {workflow_path}\n"
        f"- **Status**: pending\n"
        f"- **Current Step**: 1\n"
        f"\n"
        f"## Step Log\n"
        f"- [ ] 1. (pending)\n"
        f"\n"
        f"## Notes\n"
        f"- Auto-selected for topic \"{topic}\"\n"
    )


# ---------------------------------------------------------------------------
# Todo tool implementations
# ---------------------------------------------------------------------------

_VALID_TODO_STATUSES = {"pending", "in_progress", "done", "cancelled"}
_VALID_TODO_PRIORITIES = {"low", "medium", "high", "urgent"}
_VALID_TRIGGER_TYPES = {"time", "topic_stall", "message_match", "file_changed", "topic_resolved", "todo_completed", "manual"}


def _tool_create_todo(
    session: Session,
    agent: Agent,
    conversation: Conversation,
    tool_input: dict,
) -> str:
    title = (tool_input.get("title") or "").strip()
    if not title:
        return "Error: title is required."
    if len(title) > 200:
        return "Error: title must be 200 characters or fewer."

    description = (tool_input.get("description") or "").strip()
    if len(description) > 2000:
        return "Error: description must be 2000 characters or fewer."

    priority = (tool_input.get("priority") or "medium").strip().lower()
    if priority not in _VALID_TODO_PRIORITIES:
        return f"Error: priority must be one of {sorted(_VALID_TODO_PRIORITIES)}."

    trigger_type = (tool_input.get("trigger_type") or "manual").strip().lower()
    if trigger_type not in _VALID_TRIGGER_TYPES:
        return f"Error: trigger_type must be one of {sorted(_VALID_TRIGGER_TYPES)}."

    trigger_config = tool_input.get("trigger_config") or {}
    if not isinstance(trigger_config, dict):
        return "Error: trigger_config must be an object."

    conv_id = (tool_input.get("conversation_id") or "").strip() or conversation.id

    # Parse due_at
    due_at = None
    if tool_input.get("due_at"):
        from datetime import datetime, timezone
        try:
            raw = tool_input["due_at"].strip()
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            due_at = datetime.fromisoformat(raw)
            if due_at.tzinfo is None:
                due_at = due_at.replace(tzinfo=timezone.utc)
        except (ValueError, AttributeError):
            return "Error: due_at must be a valid ISO 8601 datetime."

    if trigger_type == "time" and not due_at:
        return "Error: due_at is required for time-based triggers."

    if trigger_type == "topic_stall" and "stall_minutes" not in trigger_config:
        trigger_config["stall_minutes"] = 30

    todo = AgentTodoItem(
        id=new_id(),
        agent_id=agent.id,
        workgroup_id=conversation.workgroup_id,
        conversation_id=conv_id,
        title=title,
        description=description,
        priority=priority,
        trigger_type=trigger_type,
        trigger_config=trigger_config,
        due_at=due_at,
    )
    session.add(todo)
    session.flush()

    _materialize_todo_file(session, agent, conversation.workgroup_id)

    trigger_desc = f", trigger={trigger_type}" if trigger_type != "manual" else ""
    return f"Created todo '{title}' (id={todo.id}, priority={priority}{trigger_desc})."


def _tool_list_todos(
    session: Session,
    agent: Agent,
    tool_input: dict,
) -> str:
    status_filter = (tool_input.get("status") or "").strip().lower()

    query = select(AgentTodoItem).where(AgentTodoItem.agent_id == agent.id)
    if status_filter and status_filter != "all":
        if status_filter not in _VALID_TODO_STATUSES:
            return f"Error: status must be one of {sorted(_VALID_TODO_STATUSES)} or 'all'."
        query = query.where(AgentTodoItem.status == status_filter)
    elif not status_filter:
        query = query.where(AgentTodoItem.status.in_(["pending", "in_progress"]))

    query = query.order_by(AgentTodoItem.created_at.asc())
    todos = session.exec(query).all()

    if not todos:
        label = status_filter if status_filter and status_filter != "all" else "pending/in_progress"
        return f"No {label} todos."

    lines = []
    for todo in todos:
        trigger_desc = ""
        if todo.trigger_type != "manual":
            trigger_desc = f" · trigger: {todo.trigger_type}"
            if todo.trigger_type == "time" and todo.due_at:
                trigger_desc += f" (due: {todo.due_at.isoformat()})"
            elif todo.trigger_type == "topic_stall":
                mins = (todo.trigger_config or {}).get("stall_minutes", 30)
                trigger_desc += f" ({mins}min)"
            elif todo.trigger_type == "message_match":
                keywords = (todo.trigger_config or {}).get("keywords", [])
                trigger_desc += f" ({', '.join(keywords[:3])})"
            elif todo.trigger_type == "file_changed":
                fp = (todo.trigger_config or {}).get("file_path", "")
                trigger_desc += f" ({fp})"
            elif todo.trigger_type == "todo_completed":
                ref = (todo.trigger_config or {}).get("todo_id", "")
                trigger_desc += f" (todo: {ref[:8]}...)"

        lines.append(
            f"- [{todo.priority.upper()}] {todo.title} "
            f"(id={todo.id}, status={todo.status}{trigger_desc})"
        )

    return f"Todos ({len(todos)}):\n" + "\n".join(lines)


def _tool_update_todo(
    session: Session,
    agent: Agent,
    conversation: Conversation,
    tool_input: dict,
) -> str:
    todo_id = (tool_input.get("todo_id") or "").strip()
    if not todo_id:
        return "Error: todo_id is required."

    todo = session.get(AgentTodoItem, todo_id)
    if not todo:
        return f"Error: todo '{todo_id}' not found."
    if todo.agent_id != agent.id:
        return "Error: you can only update your own todos."

    changes = []
    now = utc_now()

    new_status = (tool_input.get("status") or "").strip().lower()
    if new_status:
        if new_status not in _VALID_TODO_STATUSES:
            return f"Error: status must be one of {sorted(_VALID_TODO_STATUSES)}."
        if new_status != todo.status:
            todo.status = new_status
            if new_status in ("done", "cancelled"):
                todo.completed_at = now
            changes.append(f"status={new_status}")

    new_priority = (tool_input.get("priority") or "").strip().lower()
    if new_priority:
        if new_priority not in _VALID_TODO_PRIORITIES:
            return f"Error: priority must be one of {sorted(_VALID_TODO_PRIORITIES)}."
        if new_priority != todo.priority:
            todo.priority = new_priority
            changes.append(f"priority={new_priority}")

    new_title = (tool_input.get("title") or "").strip()
    if new_title:
        if len(new_title) > 200:
            return "Error: title must be 200 characters or fewer."
        if new_title != todo.title:
            todo.title = new_title
            changes.append("title updated")

    new_description = tool_input.get("description")
    if new_description is not None:
        new_description = new_description.strip()
        if len(new_description) > 2000:
            return "Error: description must be 2000 characters or fewer."
        if new_description != todo.description:
            todo.description = new_description
            changes.append("description updated")

    if not changes:
        return f"No changes to todo '{todo.title}'."

    todo.updated_at = now
    session.add(todo)
    session.flush()

    # Cascade: if marked done, check for todo_completed triggers
    if new_status == "done":
        _cascade_todo_completed(session, todo)

    _materialize_todo_file(session, agent, conversation.workgroup_id)

    return f"Updated todo '{todo.title}': {', '.join(changes)}."


def _cascade_todo_completed(session: Session, completed_todo: AgentTodoItem) -> None:
    """Mark todos with todo_completed triggers referencing this todo as triggered."""
    dependents = session.exec(
        select(AgentTodoItem).where(
            AgentTodoItem.trigger_type == "todo_completed",
            AgentTodoItem.status == "pending",
        )
    ).all()

    now = utc_now()
    for dep in dependents:
        ref_id = (dep.trigger_config or {}).get("todo_id", "")
        if ref_id == completed_todo.id:
            dep.triggered_at = now
            dep.updated_at = now
            session.add(dep)


def _materialize_todo_file(
    session: Session,
    agent: Agent,
    workgroup_id: str,
) -> None:
    """Write/update the _todos/{agent_name}.md file in workgroup.files."""
    workgroup = session.get(Workgroup, workgroup_id)
    if not workgroup:
        return

    todos = session.exec(
        select(AgentTodoItem).where(
            AgentTodoItem.agent_id == agent.id,
            AgentTodoItem.workgroup_id == workgroup_id,
        ).order_by(AgentTodoItem.created_at.asc())
    ).all()

    # Build markdown
    pending = [t for t in todos if t.status == "pending"]
    in_progress = [t for t in todos if t.status == "in_progress"]
    done = [t for t in todos if t.status == "done"]

    lines = [f"# Todos — {agent.name}", ""]

    if pending:
        lines.append("## Pending")
        for t in pending:
            trigger_desc = ""
            if t.trigger_type != "manual":
                trigger_desc = f" · Trigger: {t.trigger_type}"
                if t.trigger_type == "time" and t.due_at:
                    trigger_desc += f" (due: {t.due_at.strftime('%b %d %H:%M')})"
                elif t.trigger_type == "message_match":
                    kw = (t.trigger_config or {}).get("keywords", [])
                    trigger_desc += f" ({', '.join(kw[:3])})"
                elif t.trigger_type == "file_changed":
                    trigger_desc += f" ({(t.trigger_config or {}).get('file_path', '')})"
                elif t.trigger_type == "topic_stall":
                    trigger_desc += f" ({(t.trigger_config or {}).get('stall_minutes', 30)}min)"
            lines.append(
                f"- **[{t.priority.upper()}]** {t.title}"
                f"{trigger_desc} · Created: {t.created_at.strftime('%b %d')}"
            )
        lines.append("")

    if in_progress:
        lines.append("## In Progress")
        for t in in_progress:
            started = t.updated_at.strftime("%b %d") if t.updated_at else t.created_at.strftime("%b %d")
            lines.append(f"- **[{t.priority.upper()}]** {t.title} · Started: {started}")
        lines.append("")

    if done:
        recent_done = sorted(done, key=lambda x: x.completed_at or x.created_at, reverse=True)[:5]
        lines.append("## Recently Done")
        for t in recent_done:
            completed = t.completed_at.strftime("%b %d") if t.completed_at else "?"
            lines.append(f"- ~~**[{t.priority.upper()}]** {t.title}~~ · Completed: {completed}")
        lines.append("")

    content = "\n".join(lines)
    file_path = f"_todos/{agent.name}.md"

    all_files = _normalize_workgroup_files(workgroup)
    existing = None
    for entry in all_files:
        if entry["path"] == file_path:
            existing = entry
            break

    if existing:
        existing["content"] = content
    else:
        all_files.append({
            "id": str(uuid4()),
            "path": file_path,
            "content": content,
            "topic_id": "",
        })

    workgroup.files = all_files
    session.add(workgroup)


# ---------------------------------------------------------------------------
# Signal evaluation functions (Phase 1 — Detection)
# ---------------------------------------------------------------------------


def evaluate_message_match_todos(session: Session, message: Message) -> None:
    """Check pending message_match todos against a new message's content."""
    conversation = session.get(Conversation, message.conversation_id)
    if not conversation:
        return

    todos = session.exec(
        select(AgentTodoItem).where(
            AgentTodoItem.trigger_type == "message_match",
            AgentTodoItem.status == "pending",
            AgentTodoItem.triggered_at.is_(None),
            AgentTodoItem.workgroup_id == conversation.workgroup_id,
        )
    ).all()

    if not todos:
        return

    content_lower = message.content.lower()
    now = utc_now()
    for todo in todos:
        # Only match in the todo's conversation scope
        if todo.conversation_id and todo.conversation_id != message.conversation_id:
            continue
        keywords = (todo.trigger_config or {}).get("keywords", [])
        if any(kw.lower() in content_lower for kw in keywords):
            todo.triggered_at = now
            todo.updated_at = now
            session.add(todo)


def evaluate_file_changed_todos(
    session: Session,
    workgroup_id: str,
    file_path: str,
) -> None:
    """Check pending file_changed todos when a file is added/updated/deleted."""
    todos = session.exec(
        select(AgentTodoItem).where(
            AgentTodoItem.trigger_type == "file_changed",
            AgentTodoItem.status == "pending",
            AgentTodoItem.triggered_at.is_(None),
            AgentTodoItem.workgroup_id == workgroup_id,
        )
    ).all()

    now = utc_now()
    for todo in todos:
        watched = (todo.trigger_config or {}).get("file_path", "")
        if watched and watched == file_path:
            todo.triggered_at = now
            todo.updated_at = now
            session.add(todo)


def evaluate_topic_resolved_todos(session: Session, conversation_id: str) -> None:
    """Check pending topic_resolved todos when a conversation is archived."""
    todos = session.exec(
        select(AgentTodoItem).where(
            AgentTodoItem.trigger_type == "topic_resolved",
            AgentTodoItem.status == "pending",
            AgentTodoItem.triggered_at.is_(None),
            AgentTodoItem.conversation_id == conversation_id,
        )
    ).all()

    now = utc_now()
    for todo in todos:
        todo.triggered_at = now
        todo.updated_at = now
        session.add(todo)


# ---------------------------------------------------------------------------
# Direct message tool
# ---------------------------------------------------------------------------


def _resolve_dm_recipient(
    session: Session, workgroup_id: str, name: str,
) -> tuple[User | None, str | None]:
    """Resolve a human workgroup member by name or email.

    Returns (user, None) on success or (None, error_message) on failure.
    """
    # Get all human members of this workgroup
    members = session.exec(
        select(User)
        .join(Membership, Membership.user_id == User.id)
        .where(Membership.workgroup_id == workgroup_id)
    ).all()

    if not members:
        return None, "No human members in this workgroup."

    name_lower = name.strip().lower()

    # Exact name match (case-insensitive)
    for user in members:
        if (user.name or "").lower() == name_lower:
            return user, None

    # Exact email match
    for user in members:
        if user.email.lower() == name_lower:
            return user, None

    # Substring match on name or email
    matches = [
        user for user in members
        if name_lower in (user.name or "").lower() or name_lower in user.email.lower()
    ]
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        names = ", ".join(
            f"{u.name or u.email}" for u in matches
        )
        return None, f"Ambiguous recipient '{name}'. Matches: {names}"

    return None, f"No workgroup member matching '{name}'."


def _ensure_agent_dm(
    session: Session,
    workgroup_id: str,
    user_id: str,
    agent_id: str,
) -> Conversation:
    """Get or create a DM conversation between a user and an agent."""
    from teaparty_app.services.admin_workspace.bootstrap import direct_topic_key_user_agent

    topic_key = direct_topic_key_user_agent(user_id, agent_id)
    existing = session.exec(
        select(Conversation).where(
            Conversation.workgroup_id == workgroup_id,
            Conversation.kind == "direct",
            Conversation.topic == topic_key,
        )
    ).first()
    if existing:
        return existing

    conversation = Conversation(
        workgroup_id=workgroup_id,
        created_by_user_id=user_id,
        kind="direct",
        topic=topic_key,
        name=topic_key,
        description="",
        is_archived=False,
    )
    session.add(conversation)
    session.flush()

    session.add(ConversationParticipant(
        conversation_id=conversation.id,
        user_id=user_id,
    ))
    session.add(ConversationParticipant(
        conversation_id=conversation.id,
        agent_id=agent_id,
    ))

    return conversation


def _tool_send_direct_message(
    session: Session,
    agent: Agent,
    conversation: Conversation,
    recipient_name: str,
    message: str,
) -> str:
    """Send a DM from an agent to a human workgroup member."""
    recipient_name = (recipient_name or "").strip()
    message = (message or "").strip()

    if not recipient_name:
        return "Error: recipient_name is required."
    if not message:
        return "Error: message is required."
    if len(message) > 10_000:
        return "Error: message must be 10000 characters or fewer."

    user, error = _resolve_dm_recipient(session, conversation.workgroup_id, recipient_name)
    if error:
        return f"Error: {error}"

    dm_conversation = _ensure_agent_dm(session, conversation.workgroup_id, user.id, agent.id)

    dm_message = Message(
        id=new_id(),
        conversation_id=dm_conversation.id,
        sender_type="agent",
        sender_agent_id=agent.id,
        content=message,
        requires_response=False,
    )
    session.add(dm_message)

    return f"Sent DM to {user.name or user.email}."


# ---------------------------------------------------------------------------
# Custom tool dispatch
# ---------------------------------------------------------------------------


def _dispatch_custom_tool(
    session: Session,
    agent: Agent,
    conversation: Conversation,
    trigger: Message,
    mangled_name: str,
    tool_input: dict,
) -> str:
    """Dispatch a custom tool call. The name was mangled from 'custom:<id>' to 'custom_<id>'."""
    tool_ref = mangled_name.replace("custom_", "custom:", 1)
    tool_def = resolve_custom_tool(session, tool_ref)
    if not tool_def:
        return f"Error: custom tool '{tool_ref}' not found."
    if not tool_def.enabled:
        return f"Error: custom tool '{tool_def.name}' is disabled."

    from teaparty_app.services.custom_tool_executor import execute_custom_tool

    # For SDK dispatch, construct a synthetic trigger with the tool input as content
    input_text = tool_input.get("input", "") or trigger.content
    synthetic_trigger = Message(
        id=trigger.id,
        conversation_id=trigger.conversation_id,
        sender_type=trigger.sender_type,
        sender_user_id=trigger.sender_user_id,
        sender_agent_id=trigger.sender_agent_id,
        content=input_text,
        requires_response=trigger.requires_response,
    )
    return execute_custom_tool(tool_def, session, agent, conversation, synthetic_trigger)
