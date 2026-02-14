from __future__ import annotations

import logging
from collections.abc import Callable
import re
from uuid import uuid4

from sqlmodel import Session, select

from teaparty_app.models import Agent, AgentFollowUpTask, Conversation, Membership, Message, ToolDefinition, ToolGrant, Workgroup
from teaparty_app.services.activity import post_file_change_activity

logger = logging.getLogger(__name__)

ToolHandler = Callable[[Session, Agent, Conversation, Message], str]
FILE_CONTENT_RE = re.compile(
    r"\s+(?:(?:with\s+)?content|containing)(?:\s*(?:=|:|to)\s*|\s+)(\"[^\"]*\"|'[^']*'|.+)$",
    re.IGNORECASE | re.DOTALL,
)
ADD_FILE_RE = re.compile(
    r"\b(?:add|create)\s+(?:a\s+|an\s+|the\s+)?file\s+(.+?)\s*$",
    re.IGNORECASE,
)
EDIT_FILE_RE = re.compile(
    r"\b(?:edit|update|modify|change)\s+(?:the\s+)?file\s+(.+?)\s*$",
    re.IGNORECASE,
)
RENAME_FILE_RE = re.compile(
    r"\b(?:rename|move)\s+(?:the\s+)?file\s+(.+?)\s+(?:to|as)\s+(.+?)\s*$",
    re.IGNORECASE,
)
DELETE_FILE_RE = re.compile(
    r"\b(?:remove|delete)\s+(?:the\s+)?file\s+(.+?)\s*$",
    re.IGNORECASE,
)
LINK_PATH_RE = re.compile(r"^https?://", re.IGNORECASE)
LEADING_POLITE_RE = re.compile(
    r"^\s*(?:(?:please|kindly)\s+)*(?:(?:can|could|would)\s+you\s+)?(?:(?:please|kindly)\s+)*",
    re.IGNORECASE,
)
TRAILING_POLITE_RE = re.compile(r"\s+(?:please|thanks|thank you)\s*$", re.IGNORECASE)
FILE_PATH_PREFIX_RE = re.compile(r"^(?:named|called)\s+", re.IGNORECASE)
AMBIGUOUS_ADD_PATH_RE = re.compile(
    r"\b(?:markdown|md|text|txt|json|yaml|yml)\s+file\b|\bcontaining\b|\bwith\s+content\b",
    re.IGNORECASE,
)


def _unquote(value: str) -> str:
    stripped = value.strip()
    if len(stripped) >= 2 and ((stripped[0] == '"' and stripped[-1] == '"') or (stripped[0] == "'" and stripped[-1] == "'")):
        return stripped[1:-1].strip()
    return stripped


def _normalize_trigger_for_matching(message: str) -> str:
    cleaned = LEADING_POLITE_RE.sub("", message.strip())
    cleaned = TRAILING_POLITE_RE.sub("", cleaned)
    return cleaned.rstrip(" .!?")


def _strip_file_path_prefix(raw_path: str) -> str:
    path = _unquote(raw_path.strip())
    path = FILE_PATH_PREFIX_RE.sub("", path)
    return path.strip()


def _parse_file_payload(raw_payload: str) -> tuple[str, str, bool]:
    payload = _strip_file_path_prefix(raw_payload)
    content = ""
    has_content = False
    match = FILE_CONTENT_RE.search(payload)
    if match:
        content = _unquote(match.group(1))
        payload = payload[: match.start()].strip()
        has_content = True
    return _strip_file_path_prefix(payload), content, has_content


def _is_ambiguous_add_path(path: str) -> bool:
    lowered = path.strip().lower()
    if not lowered:
        return True
    if AMBIGUOUS_ADD_PATH_RE.search(lowered):
        if "/" in lowered or "\\" in lowered or "." in lowered:
            return False
        return True
    return False


def _normalize_workgroup_files(workgroup: Workgroup) -> list[dict[str, str]]:
    raw_files = workgroup.files if isinstance(workgroup.files, list) else []
    normalized: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for raw in raw_files:
        file_id = ""
        path = ""
        content = ""

        if isinstance(raw, str):
            path = raw.strip()
        elif isinstance(raw, dict):
            file_id = str(raw.get("id") or "").strip()
            path = str(raw.get("path") or "").strip()
            raw_content = raw.get("content", "")
            content = raw_content if isinstance(raw_content, str) else str(raw_content or "")
        else:
            continue

        if not path or path in seen_paths:
            continue
        if len(path) > 512 or len(content) > 200000:
            continue
        normalized.append({"id": file_id or str(uuid4()), "path": path, "content": content})
        seen_paths.add(path)
    return normalized


def _file_tool_workgroup_and_error(
    session: Session,
    conversation: Conversation,
    trigger: Message,
    *,
    require_owner: bool = True,
) -> tuple[Workgroup | None, str | None]:
    if trigger.sender_type != "user" or not trigger.sender_user_id:
        return None, "File tools require a direct user request."

    membership = session.exec(
        select(Membership).where(
            Membership.workgroup_id == conversation.workgroup_id,
            Membership.user_id == trigger.sender_user_id,
        )
    ).first()
    if not membership:
        return None, "User is not a member of this workgroup."
    if require_owner and membership.role != "owner":
        return None, "Only the workgroup owner can modify files."

    workgroup = session.get(Workgroup, conversation.workgroup_id)
    if not workgroup:
        return None, "Workgroup not found."
    return workgroup, None


def add_file(session: Session, agent: Agent, conversation: Conversation, trigger: Message) -> str:
    workgroup, error = _file_tool_workgroup_and_error(session, conversation, trigger)
    if error or not workgroup:
        return error or "Workgroup not found."

    normalized_message = _normalize_trigger_for_matching(trigger.content)
    match = ADD_FILE_RE.search(normalized_message)
    if not match:
        return "Usage: add file <path> [content=<text>] or create a file <path> with content <text>"
    path, content, _has_content = _parse_file_payload(match.group(1))
    if not path:
        return "Usage: add file <path> [content=<text>] or create a file <path> with content <text>"
    if _is_ambiguous_add_path(path):
        return "Couldn't infer file path. Try: add file notes.md content=<text>"
    if len(path) > 512:
        return "File path must be 512 characters or fewer."
    if len(content) > 200000:
        return "File content must be 200000 characters or fewer."

    files = _normalize_workgroup_files(workgroup)
    for entry in files:
        if entry["path"] == path:
            return f"File '{path}' already exists (id={entry['id']})."

    created = {"id": str(uuid4()), "path": path, "content": content}
    files.append(created)
    workgroup.files = files
    session.add(workgroup)
    post_file_change_activity(
        session, conversation.workgroup_id, "file_added", path,
        actor_user_id=trigger.sender_user_id, actor_agent_id=trigger.sender_agent_id,
    )
    return f"Added file '{path}' (id={created['id']})."


def edit_file(session: Session, agent: Agent, conversation: Conversation, trigger: Message) -> str:
    workgroup, error = _file_tool_workgroup_and_error(session, conversation, trigger)
    if error or not workgroup:
        return error or "Workgroup not found."

    normalized_message = _normalize_trigger_for_matching(trigger.content)
    match = EDIT_FILE_RE.search(normalized_message)
    if not match:
        return "Usage: edit file <path> content=<text> (or with content <text>)"
    path, content, has_content = _parse_file_payload(match.group(1))
    if not path or not has_content:
        return "Usage: edit file <path> content=<text> (or with content <text>)"
    if len(path) > 512:
        return "File path must be 512 characters or fewer."
    if len(content) > 200000:
        return "File content must be 200000 characters or fewer."

    files = _normalize_workgroup_files(workgroup)
    for entry in files:
        if entry["path"] != path:
            continue
        if entry["content"] == content:
            return f"File '{path}' is unchanged."
        entry["content"] = content
        workgroup.files = files
        session.add(workgroup)
        post_file_change_activity(
            session, conversation.workgroup_id, "file_updated", path,
            actor_user_id=trigger.sender_user_id, actor_agent_id=trigger.sender_agent_id,
        )
        return f"Updated file '{path}' (id={entry['id']})."
    return f"File '{path}' was not found."


def rename_file(session: Session, agent: Agent, conversation: Conversation, trigger: Message) -> str:
    workgroup, error = _file_tool_workgroup_and_error(session, conversation, trigger)
    if error or not workgroup:
        return error or "Workgroup not found."

    normalized_message = _normalize_trigger_for_matching(trigger.content)
    match = RENAME_FILE_RE.search(normalized_message)
    if not match:
        return "Usage: rename file <path> to <new-path>"
    source_path = _strip_file_path_prefix(match.group(1))
    destination_path = _strip_file_path_prefix(match.group(2))
    if not source_path or not destination_path:
        return "Usage: rename file <path> to <new-path>"
    if len(source_path) > 512 or len(destination_path) > 512:
        return "File path must be 512 characters or fewer."
    if source_path == destination_path:
        return f"File path is already '{source_path}'."

    files = _normalize_workgroup_files(workgroup)
    source: dict[str, str] | None = None
    for entry in files:
        if entry["path"] == destination_path:
            return f"File '{destination_path}' already exists."
        if entry["path"] == source_path:
            source = entry
    if not source:
        return f"File '{source_path}' was not found."

    source["path"] = destination_path
    workgroup.files = files
    session.add(workgroup)
    post_file_change_activity(
        session, conversation.workgroup_id, "file_renamed", f"{source_path} -> {destination_path}",
        actor_user_id=trigger.sender_user_id, actor_agent_id=trigger.sender_agent_id,
    )
    return f"Renamed file '{source_path}' to '{destination_path}' (id={source['id']})."


def delete_file(session: Session, agent: Agent, conversation: Conversation, trigger: Message) -> str:
    workgroup, error = _file_tool_workgroup_and_error(session, conversation, trigger)
    if error or not workgroup:
        return error or "Workgroup not found."

    normalized_message = _normalize_trigger_for_matching(trigger.content)
    match = DELETE_FILE_RE.search(normalized_message)
    if not match:
        return "Usage: delete file <path>"
    path = _strip_file_path_prefix(match.group(1))
    if not path:
        return "Usage: delete file <path>"
    if len(path) > 512:
        return "File path must be 512 characters or fewer."

    files = _normalize_workgroup_files(workgroup)
    retained: list[dict[str, str]] = []
    removed: dict[str, str] | None = None
    for entry in files:
        if removed is None and entry["path"] == path:
            removed = entry
            continue
        retained.append(entry)

    if not removed:
        return f"File '{path}' was not found."

    workgroup.files = retained
    session.add(workgroup)
    post_file_change_activity(
        session, conversation.workgroup_id, "file_deleted", path,
        actor_user_id=trigger.sender_user_id, actor_agent_id=trigger.sender_agent_id,
    )
    return f"Deleted file '{path}' (id={removed['id']})."


def list_files(session: Session, agent: Agent, conversation: Conversation, trigger: Message) -> str:
    workgroup, error = _file_tool_workgroup_and_error(session, conversation, trigger, require_owner=False)
    if error or not workgroup:
        return error or "Workgroup not found."

    files = _normalize_workgroup_files(workgroup)
    if not files:
        return "No files in this workgroup."

    rows = sorted(files, key=lambda item: item["path"].lower())
    lines = [f"Files (count={len(rows)}):"]
    for entry in rows:
        kind = "link" if LINK_PATH_RE.match(entry["path"]) else "file"
        lines.append(f"- [{kind}] {entry['path']}")
    return "\n".join(lines)


def summarize_topic(session: Session, agent: Agent, conversation: Conversation, trigger: Message) -> str:
    recent = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc())
        .limit(6)
    ).all()
    if not recent:
        return "No messages yet in this topic."

    snippets = []
    for message in reversed(recent):
        label = "user" if message.sender_type == "user" else f"agent:{message.sender_agent_id}"
        snippets.append(f"- {label}: {message.content[:120]}")
    return "Recent summary:\n" + "\n".join(snippets)


def list_open_followups(session: Session, agent: Agent, conversation: Conversation, trigger: Message) -> str:
    count = session.exec(
        select(AgentFollowUpTask)
        .where(
            AgentFollowUpTask.conversation_id == conversation.id,
            AgentFollowUpTask.status == "pending",
        )
    ).all()
    return f"Open follow-up tasks in this conversation: {len(count)}"


def suggest_next_step(session: Session, agent: Agent, conversation: Conversation, trigger: Message) -> str:
    text = trigger.content.lower()
    if "blocked" in text or "stuck" in text:
        return "Suggested next step: post blockers, owner, and one unblocking action with ETA."
    if "decision" in text:
        return "Suggested next step: list options, criteria, and owner to finalize in one message."
    return "Suggested next step: clarify owner, deadline, and explicit done condition."


TOOL_REGISTRY: dict[str, ToolHandler] = {
    "summarize_topic": summarize_topic,
    "list_open_followups": list_open_followups,
    "suggest_next_step": suggest_next_step,
    "list_files": list_files,
    "add_file": add_file,
    "edit_file": edit_file,
    "rename_file": rename_file,
    "delete_file": delete_file,
}


def available_tools() -> list[str]:
    return sorted(list(TOOL_REGISTRY.keys()) + ["claude_code"])


def available_tools_for_workgroup(session: Session, workgroup_id: str) -> list[str]:
    builtin = list(TOOL_REGISTRY.keys())

    own_tools = session.exec(
        select(ToolDefinition).where(
            ToolDefinition.workgroup_id == workgroup_id,
            ToolDefinition.enabled == True,  # noqa: E712
        )
    ).all()
    custom = [f"custom:{td.id}" for td in own_tools]

    granted_tool_ids = session.exec(
        select(ToolGrant.tool_definition_id).where(
            ToolGrant.grantee_workgroup_id == workgroup_id,
        )
    ).all()
    for tool_def_id in granted_tool_ids:
        td = session.get(ToolDefinition, tool_def_id)
        if td and td.enabled:
            ref = f"custom:{td.id}"
            if ref not in custom:
                custom.append(ref)

    return sorted(builtin + custom)


def resolve_custom_tool(session: Session, tool_ref: str) -> ToolDefinition | None:
    if not tool_ref.startswith("custom:"):
        return None
    tool_id = tool_ref[len("custom:"):]
    return session.get(ToolDefinition, tool_id)


def _has_custom_tool_access(session: Session, tool_def: ToolDefinition, workgroup_id: str) -> bool:
    if tool_def.workgroup_id == workgroup_id:
        return True
    grant = session.exec(
        select(ToolGrant).where(
            ToolGrant.tool_definition_id == tool_def.id,
            ToolGrant.grantee_workgroup_id == workgroup_id,
        )
    ).first()
    return grant is not None


def run_tool(name: str, session: Session, agent: Agent, conversation: Conversation, trigger: Message) -> str:
    if name == "claude_code":
        from teaparty_app.services.claude_code import claude_code as claude_code_handler
        return claude_code_handler(session, agent, conversation, trigger)

    if name.startswith("custom:"):
        tool_def = resolve_custom_tool(session, name)
        if not tool_def:
            return f"Custom tool '{name}' not found."
        if not tool_def.enabled:
            return f"Custom tool '{tool_def.name}' is disabled."
        if not _has_custom_tool_access(session, tool_def, conversation.workgroup_id):
            return f"Custom tool '{tool_def.name}' is not available to this workgroup."
        from teaparty_app.services.custom_tool_executor import execute_custom_tool
        return execute_custom_tool(tool_def, session, agent, conversation, trigger)

    handler = TOOL_REGISTRY.get(name)
    if not handler:
        return f"Tool '{name}' is not available."
    return handler(session, agent, conversation, trigger)
