"""Command pattern matching, parse/normalize helpers, and help text.

This module has no dependencies on other admin_workspace submodules.
"""

from __future__ import annotations

import re
from uuid import uuid4

ADD_JOB_RE = re.compile(
    r"^(?:add|create)\s+(?:a\s+|an\s+|the\s+)?(?:new\s+)?(?:\w+\s+)?(?:job|topic|conversation|channel)\s+(?:(?:on|about|for|called|named|titled)\s+)?(.+?)\s*$",
    re.IGNORECASE,
)
ARCHIVE_JOB_RE = re.compile(
    r"^archive\s+(?:the\s+)?(?:job|topic|conversation|channel)\s+(.+?)\s*$",
    re.IGNORECASE,
)
UNARCHIVE_JOB_RE = re.compile(
    r"^unarchive\s+(?:the\s+)?(?:job|topic|conversation|channel)\s+(.+?)\s*$",
    re.IGNORECASE,
)
ADD_AGENT_RE = re.compile(
    r"^(?:create|add)\s+(?:a\s+|an\s+|the\s+)?(?:new\s+)?agent\s+(.+?)\s*$",
    re.IGNORECASE,
)
ADD_USER_RE = re.compile(
    r"^(?:add|invite)\s+(?:a\s+|an\s+|the\s+)?(?:new\s+)?user\s+([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\s*$",
    re.IGNORECASE,
)
LIST_JOBS_RE = re.compile(
    r"^list\s+(?:(open|archived|both|all)\s+)?(?:jobs?|topics?|conversations?|channels?)(?:\s+(open|archived|both|all))?\s*$",
    re.IGNORECASE,
)
LIST_MEMBERS_RE = re.compile(r"^list\s+(?:members?|users?|participants?)\s*$", re.IGNORECASE)
LIST_FILES_RE = re.compile(r"^(?:list|show)\s+(?:workgroup\s+)?files?\s*$", re.IGNORECASE)
REMOVE_JOB_RE = re.compile(
    r"^(?:remove|delete)\s+(?:the\s+)?(?:job|topic|conversation|channel)\s+(.+?)\s*$",
    re.IGNORECASE,
)
CLEAR_JOB_MESSAGES_RE = re.compile(
    r"^(?:clear|wipe|purge)\s+(?:the\s+)?(?:messages?\s+(?:in|for)\s+)?(?:job|topic|conversation|channel)\s+(.+?)\s*$",
    re.IGNORECASE,
)
REMOVE_MEMBER_RE = re.compile(
    r"^(?:remove|delete)\s+(?:the\s+)?(?:member|user|participant|agent)\s+(.+?)\s*$",
    re.IGNORECASE,
)
ADD_FILE_RE = re.compile(
    r"^(?:add|create)\s+(?:a\s+|an\s+|the\s+)?file\s+(.+?)\s*$",
    re.IGNORECASE,
)
EDIT_FILE_RE = re.compile(
    r"^(?:edit|update)\s+(?:the\s+)?file\s+(.+?)\s*$",
    re.IGNORECASE,
)
RENAME_FILE_RE = re.compile(
    r"^(?:rename|move)\s+(?:the\s+)?file\s+(.+?)\s+(?:to|as)\s+(.+?)\s*$",
    re.IGNORECASE,
)
DELETE_FILE_RE = re.compile(
    r"^(?:remove|delete)\s+(?:the\s+)?file\s+(.+?)\s*$",
    re.IGNORECASE,
)
DELETE_WORKGROUP_RE = re.compile(
    r"^(?:remove|delete)\s+(?:(?:this|the|a)\s+)?workgroup(?:\s+(confirm|yes|delete))?(?:\s+please)?\s*$",
    re.IGNORECASE,
)
LIST_TASKS_RE = re.compile(
    r"^list\s+(?:(incoming|outgoing|all)\s+)?tasks?\s*$",
    re.IGNORECASE,
)
ACCEPT_TASK_RE = re.compile(
    r"^accept\s+task\s+(.+?)\s*$",
    re.IGNORECASE,
)
DECLINE_TASK_RE = re.compile(
    r"^decline\s+task\s+(.+?)\s*$",
    re.IGNORECASE,
)
COMPLETE_TASK_RE = re.compile(
    r"^complete\s+task\s+(.+?)\s*$",
    re.IGNORECASE,
)
_NAME_INTRODUCER_RE = re.compile(r"\b(?:called|named|titled)\s+", re.IGNORECASE)
LEADING_POLITE_RE = re.compile(r"^\s*(?:please\s+)?(?:(?:can|could|would)\s+you\s+)?", re.IGNORECASE)
PERSONALITY_SPLIT_RE = re.compile(r"\s+(?:with\s+)?personality\s*(?:[:=]\s*|\s+)(.+)$", re.IGNORECASE)
AGENT_OPTION_RE = re.compile(
    r"(?:^|\s)(personality|role|backstory|model|temperature)\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s]+)",
    re.IGNORECASE,
)
AGENT_MODEL_HINT_RE = re.compile(
    r"(?:^|[\s,.;])(?:use|using)?\s*model\s*(?:=|:|\s+)([A-Za-z0-9._\-]+)",
    re.IGNORECASE,
)
AGENT_TEMPERATURE_HINT_RE = re.compile(
    r"(?:^|[\s,.;])(?:at\s+)?temperature\s*(?:=|:|\s+)([0-2](?:\.\d+)?)",
    re.IGNORECASE,
)
JOB_DESCRIPTION_RE = re.compile(
    r"\s+description\s*(?:=|:)\s*(\"[^\"]*\"|'[^']*'|.+)$",
    re.IGNORECASE,
)
FILE_CONTENT_RE = re.compile(
    r"\s+content\s*(?:=|:)\s*(\"[^\"]*\"|'[^']*'|.+)$",
    re.IGNORECASE | re.DOTALL,
)


def _is_confirmed_word(raw_value: str | None) -> bool:
    return (raw_value or "").strip().lower() in {"confirm", "yes", "delete"}


def _help_text() -> str:
    return (
        "Available admin tools: `add job <name> [description=<text>]`, `archive job <name|id>`, "
        "`unarchive job <name|id>`, `clear job <name|id>`, `remove job <name|id>`, "
        "`add agent <name> [role=<text>] [personality=<text>] [backstory=<text>] [model=<name>] [temperature=<0..2>]`, "
        "`add user <email>`, "
        "`add file <path> [content=<text>]`, `edit file <path> content=<text>`, "
        "`rename file <path> to <new-path>`, `delete file <path>`, "
        "`remove member <id|email|name>`, `list jobs [open|archived|both]`, "
        "`list members`, `list files`, `delete workgroup confirm`, "
        "`list tasks [incoming|outgoing|all]`, `accept task <id|title>`, "
        "`decline task <id|title>`, `complete task <id|title>`."
    )


def _normalize_list_jobs_status(raw_status: str | None) -> tuple[str | None, str | None]:
    status_value = (raw_status or "open").strip().lower()
    if status_value == "all":
        status_value = "both"

    if status_value not in {"open", "archived", "both"}:
        return None, "Status must be one of: open, archived, both."

    return status_value, None


def _normalize_admin_message_for_matching(message: str) -> str:
    cleaned = LEADING_POLITE_RE.sub("", message.strip())
    return cleaned.rstrip(" .!?")


def _unquote(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and ((value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'")):
        return value[1:-1].strip()
    return value


def _strip_name_filler(payload: str) -> str:
    """Extract the actual entity name from a captured payload.

    When a regex capture includes contextual filler before a name-introducing
    keyword (called/named/titled), strip everything up to and including the
    keyword so only the real name remains.

    Examples:
        "to this workgroup called Disrupting Technology" → "Disrupting Technology"
        "called Bob"                                     → "Bob"
        "Disrupting Technology"                          → "Disrupting Technology"
    """
    matches = list(_NAME_INTRODUCER_RE.finditer(payload))
    if not matches:
        return payload
    last = matches[-1]
    remainder = payload[last.end():].strip()
    if remainder:
        return _unquote(remainder)
    return payload


def _extract_agent_options(payload: str) -> tuple[str, dict[str, str]]:
    extracted: dict[str, str] = {}

    def repl(match: re.Match[str]) -> str:
        key = match.group(1).lower().strip()
        value = _unquote(match.group(2))
        extracted[key] = value
        return " "

    stripped = AGENT_OPTION_RE.sub(repl, payload)
    cleaned = " ".join(stripped.split())
    return cleaned, extracted


def _extract_inline_option(payload: str, pattern: re.Pattern[str]) -> tuple[str, str | None]:
    match = pattern.search(payload)
    if not match:
        return payload, None
    value = _unquote(match.group(1)).strip()
    cleaned = f"{payload[:match.start()]} {payload[match.end():]}".strip()
    cleaned = " ".join(cleaned.split())
    return cleaned, value


def _normalize_agent_name(raw_name: str) -> str:
    name = raw_name.strip()
    name = _unquote(name)
    if name.startswith("@"):
        name = name[1:].strip()
    name = _unquote(name)
    return name.strip(" \t\r\n.,;:-")


def _split_agent_name_and_narrative(payload: str) -> tuple[str, str]:
    text = payload.strip()
    if not text:
        return "", ""

    quoted = re.match(r"^@?(?:\"([^\"]+)\"|'([^']+)')\s*(?:[.,:;\-]+\s*)?(.*)$", text)
    if quoted:
        name = quoted.group(1) or quoted.group(2) or ""
        return name.strip(), quoted.group(3).strip()

    punctuated = re.match(r"^@?([A-Za-z0-9][A-Za-z0-9 _\-]{0,47})\s*[.,:;\-]+\s+(.+)$", text)
    if punctuated:
        name = punctuated.group(1).strip()
        if name and len(name.split()) <= 5 and " is " not in name.lower():
            return name, punctuated.group(2).strip()

    lowered = text.lower()
    index = lowered.find(" is ")
    if index > 0:
        candidate = text[:index].strip(" \t\r\n.,;:-")
        if candidate and len(candidate) <= 48 and len(candidate.split()) <= 5:
            return candidate, text[index + 1 :].strip()

    return text, ""


def _parse_add_agent_payload(raw_payload: str) -> tuple[str, dict[str, str]]:
    payload = _strip_name_filler(_unquote(raw_payload.strip()))

    payload, options = _extract_agent_options(payload)
    if "model" not in options:
        payload, hinted_model = _extract_inline_option(payload, AGENT_MODEL_HINT_RE)
        if hinted_model:
            options["model"] = hinted_model
    if "temperature" not in options:
        payload, hinted_temperature = _extract_inline_option(payload, AGENT_TEMPERATURE_HINT_RE)
        if hinted_temperature:
            options["temperature"] = hinted_temperature

    personality = options.get("personality")
    if not personality:
        personality_match = PERSONALITY_SPLIT_RE.search(payload)
        if personality_match:
            personality = personality_match.group(1).strip()
            payload = payload[: personality_match.start()].strip()

    candidate_name, narrative = _split_agent_name_and_narrative(payload)
    normalized_name = _normalize_agent_name(candidate_name)
    narrative_text = narrative.strip()
    if normalized_name and narrative_text.lower().startswith(normalized_name.lower() + " "):
        narrative_text = narrative_text[len(normalized_name) :].strip(" \t\r\n.,;:-")
    if not personality and narrative_text:
        personality = narrative_text

    parsed = {
        "personality": (personality or "Professional and concise").strip() or "Professional and concise",
        "role": (options.get("role") or "").strip(),
        "backstory": (options.get("backstory") or "").strip(),
        "model": (options.get("model") or "").strip(),
        "temperature": (options.get("temperature") or "").strip(),
    }
    return normalized_name, parsed


def _parse_temperature(raw: str | float | None, default: float = 0.7) -> tuple[float, str | None]:
    if raw is None:
        return default, None
    if isinstance(raw, float):
        temperature = raw
    else:
        value = str(raw).strip()
        if not value:
            return default, None
        try:
            temperature = float(value)
        except ValueError:
            return default, "Temperature must be a number between 0.0 and 2.0."

    if temperature < 0.0 or temperature > 2.0:
        return default, "Temperature must be between 0.0 and 2.0."
    return round(temperature, 3), None


def _parse_add_job_payload(raw_payload: str) -> tuple[str, str]:
    payload = _unquote(raw_payload.strip())
    description = ""
    match = JOB_DESCRIPTION_RE.search(payload)
    if match:
        description = _unquote(match.group(1)).strip()
        payload = payload[: match.start()].strip()
    payload = _strip_name_filler(payload)
    return payload, description


def _normalize_file_path(raw_path: str) -> str:
    return _unquote(raw_path.strip())


def _normalize_file_content(raw_content: str) -> tuple[str, str | None]:
    content = raw_content if isinstance(raw_content, str) else str(raw_content or "")
    if len(content) > 200000:
        return "", "File content must be 200000 characters or fewer."
    return content, None


def _parse_file_payload(raw_payload: str) -> tuple[str, str, bool]:
    payload = _unquote(raw_payload.strip())
    content = ""
    has_content = False
    match = FILE_CONTENT_RE.search(payload)
    if match:
        content = _unquote(match.group(1))
        payload = payload[: match.start()].strip()
        has_content = True
    return _normalize_file_path(payload), content, has_content


def _normalize_workgroup_files_for_tool(workgroup) -> list[dict[str, str]]:
    raw_files = workgroup.files if isinstance(workgroup.files, list) else []
    normalized: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for raw in raw_files:
        file_id = ""
        path = ""
        content = ""

        if isinstance(raw, str):
            path = raw.strip()
            file_id = str(uuid4())
        elif isinstance(raw, dict):
            file_id = str(raw.get("id") or "").strip()
            path = str(raw.get("path") or "").strip()
            raw_content = raw.get("content", "")
            content = raw_content if isinstance(raw_content, str) else str(raw_content or "")
        else:
            continue

        if not path or path in seen_paths:
            continue
        if len(path) > 512:
            continue
        if len(content) > 200000:
            continue

        topic_id = ""
        if isinstance(raw, dict):
            topic_id = str(raw.get("topic_id", "")).strip()
        normalized.append({"id": file_id or str(uuid4()), "path": path, "content": content, "topic_id": topic_id})
        seen_paths.add(path)
    return normalized


def _normalize_job_selector(raw_selector: str) -> str:
    selector = _unquote(raw_selector.strip())
    if selector.startswith("#"):
        selector = selector[1:].strip()
    return selector


def _normalize_task_selector(raw_selector: str) -> str:
    return _unquote(raw_selector.strip())


def _normalize_member_selector(raw_selector: str) -> str:
    selector = raw_selector.strip().strip("\"").strip("'")
    if selector.startswith("@"):
        selector = selector[1:].strip()
    return selector
