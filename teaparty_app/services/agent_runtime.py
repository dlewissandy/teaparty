from __future__ import annotations

import logging
import json
import os
import re
import threading
import time
from datetime import timedelta

import anthropic
from sqlmodel import Session, select

from teaparty_app.config import settings
from teaparty_app.services import llm_client
from teaparty_app.models import (
    Agent,
    AgentFollowUpTask,
    AgentLearningEvent,
    Conversation,
    ConversationParticipant,
    CrossGroupTask,
    Message,
    User,
    Workgroup,
    utc_now,
)
from teaparty_app.db import commit_with_retry
from teaparty_app.services.admin_workspace import (
    ADMIN_AGENT_SENTINEL,
    consume_queued_workgroup_deletion,
    delete_workgroup_data,
    handle_admin_message,
    is_admin_agent,
)
from teaparty_app.services.llm_usage import record_llm_usage
from teaparty_app.services.tools import SERVER_SIDE_TOOLS, resolve_custom_tool, run_tool

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


TOOL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:list|show)\s+(?:me\s+)?(?:the\s+|all\s+|workgroup\s+)?files?\b", re.IGNORECASE), "list_files"),
    (re.compile(r"\b(?:add|create)\s+(?:a\s+|an\s+|the\s+)?file\b", re.IGNORECASE), "add_file"),
    (
        re.compile(
            r"(?:\b(?:edit|update|modify|change)\s+(?:the\s+)?file\b"
            r"|\b(?:add|append|insert)\b[\s\S]*\b(?:to|in|into)\b[\s\S]*(?:\bfile\b|[A-Za-z0-9._/\-]+\.[A-Za-z0-9]{1,16}\b))",
            re.IGNORECASE,
        ),
        "edit_file",
    ),
    (re.compile(r"\b(?:rename|move)\s+(?:the\s+)?file\b", re.IGNORECASE), "rename_file"),
    (re.compile(r"\b(?:delete|remove)\s+(?:the\s+)?file\b", re.IGNORECASE), "delete_file"),
    (re.compile(
        r"\b(?:(?:write|generate|create|review|analyze|refactor|debug|fix|implement|build|develop)\s+"
        r"(?:the\s+|a\s+|an\s+|some\s+|this\s+)?(?:code|program|script|function|class|module|feature|test|implementation)"
        r"|code\s+(?:this|that|it|review|analysis))\b",
        re.IGNORECASE,
    ), "claude_code"),
    (re.compile(r"\bclaude[\s_-]?code\b", re.IGNORECASE), "claude_code"),
    (re.compile(r"\b(?:summary|recap)\b", re.IGNORECASE), "summarize_topic"),
    (re.compile(r"\b(?:status|follow[\s-]?up)\b", re.IGNORECASE), "list_open_followups"),
    (re.compile(r"\b(?:next\s+step|decision|blocked)\b", re.IGNORECASE), "suggest_next_step"),
]
FILE_RESULT_TOOL_NAMES = {"list_files", "add_file", "edit_file", "rename_file", "delete_file"}
DIRECT_RETURN_TOOL_NAMES = {"claude_code"}
FILE_TOOL_COMMAND_PATTERNS: dict[str, re.Pattern[str]] = {
    "list_files": re.compile(r"^list\s+files?\s*$", re.IGNORECASE),
    "add_file": re.compile(r"^add\s+file\s+.+\s+content\s*(?:=|:|to)?\s*[\s\S]+$", re.IGNORECASE),
    "edit_file": re.compile(r"^edit\s+file\s+.+\s+content\s*(?:=|:|to)?\s*[\s\S]+$", re.IGNORECASE),
    "rename_file": re.compile(r"^rename\s+file\s+.+\s+to\s+.+$", re.IGNORECASE),
    "delete_file": re.compile(r"^delete\s+file\s+.+$", re.IGNORECASE),
}
FILE_PATH_REFERENCE_RE = re.compile(
    r"(?:^|[\s\"'`])([A-Za-z0-9][A-Za-z0-9._/\-]*\.[A-Za-z0-9]{1,16})(?=$|[\s\"'`.,:;!?])"
)

RELEVANCE_TOKEN_RE = re.compile(r"[a-z][a-z0-9_-]{2,}")
RELEVANCE_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "about",
    "agent",
    "assistant",
    "professional",
    "concise",
    "structured",
    "detailed",
    "brief",
    "team",
    "workgroup",
    "chat",
    "conversation",
}

PERSONALITY_ENGAGED_KEYWORDS = {
    "proactive",
    "collaborative",
    "coach",
    "mentor",
    "helpful",
    "supportive",
    "curious",
    "teaching",
}
PERSONALITY_RESERVED_KEYWORDS = {
    "reserved",
    "minimal",
    "silent",
    "quiet",
    "brief-only",
    "only when asked",
}

MARKDOWN_BULLET_RE = re.compile(r"^(?:[-*]|\d+[.)])\s+")
MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s+")
MARKDOWN_CHECKBOX_RE = re.compile(r"^\[[ xX]\]\s+")


def infer_requires_response(content: str) -> bool:
    text = content.strip().lower()
    if "?" in text:
        return True
    return text.startswith(("can ", "could ", "would ", "please ", "who ", "what ", "when ", "where ", "why ", "how "))


def _is_mentioned(agent: Agent, content: str) -> bool:
    return f"@{agent.name.lower()}" in content.lower()


def _match_custom_tool(session: Session, custom_refs: list[str], content: str) -> str | None:
    lowered_content = content.lower().split()
    content_words = set(lowered_content)
    if not content_words:
        return None

    best_ref: str | None = None
    best_score = 0

    for ref in custom_refs:
        tool_def = resolve_custom_tool(session, ref)
        if not tool_def or not tool_def.enabled:
            continue
        tool_text = f"{tool_def.name} {tool_def.description}".lower().split()
        tool_words = set(tool_text)
        overlap = content_words & tool_words
        score = len(overlap)
        if score > best_score:
            best_score = score
            best_ref = ref

    return best_ref if best_score > 0 else None


def _select_tool(agent: Agent, content: str, session: Session | None = None) -> str | None:
    allowed = set(agent.tool_names or []) - SERVER_SIDE_TOOLS
    for pattern, tool_name in TOOL_PATTERNS:
        if tool_name in allowed and pattern.search(content):
            return tool_name

    lowered = content.lower()
    has_file_path = bool(FILE_PATH_REFERENCE_RE.search(content))
    if has_file_path:
        if "rename_file" in allowed and re.search(r"\b(?:rename|move)\b", lowered):
            return "rename_file"
        if "delete_file" in allowed and re.search(r"\b(?:delete|remove)\b", lowered):
            return "delete_file"
        if "edit_file" in allowed and re.search(r"\b(?:edit|update|modify|change|append|insert|add)\b", lowered):
            return "edit_file"
        if "add_file" in allowed and re.search(r"\b(?:add|create|make)\b", lowered):
            return "add_file"

    if session is not None:
        custom_refs = [name for name in (agent.tool_names or []) if name.startswith("custom:")]
        if custom_refs:
            match = _match_custom_tool(session, custom_refs, content)
            if match:
                return match

    return None


def _is_valid_file_tool_command(tool_name: str, command: str) -> bool:
    pattern = FILE_TOOL_COMMAND_PATTERNS.get(tool_name)
    if not pattern:
        return False
    return bool(pattern.search(command.strip()))


def _extract_file_tool_command(raw_output: str) -> str:
    parsed = _extract_json_object(raw_output)
    if isinstance(parsed, dict):
        command_value = parsed.get("command")
        if isinstance(command_value, str):
            return command_value.strip()

    cleaned = raw_output.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json|text)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    if re.match(r"^(?:add|edit)\s+file\b", cleaned, re.IGNORECASE):
        return cleaned.strip()
    lines = [line.strip() for line in cleaned.splitlines() if line.strip()]
    return lines[0] if lines else ""


def _rewrite_file_tool_trigger(
    session: Session,
    agent: Agent,
    conversation: Conversation,
    trigger: Message,
    tool_name: str,
    triggering_user_id: str | None = None,
) -> Message | None:
    if tool_name not in FILE_RESULT_TOOL_NAMES:
        return None
    if not _runtime_agent_llm_enabled():
        return None

    existing_paths: list[str] = []
    existing_content_by_path: dict[str, str] = {}
    try:
        from teaparty_app.services.tools import _files_for_conversation
        workgroup = session.get(Workgroup, conversation.workgroup_id)
        scoped = _files_for_conversation(workgroup, conversation) if workgroup else []
        for item in scoped:
            path = item.get("path", "")
            content = item.get("content", "")
            if path:
                existing_paths.append(path)
                if content and path not in existing_content_by_path:
                    existing_content_by_path[path] = content
    except Exception:
        existing_paths = []
        existing_content_by_path = {}

    referenced_files: list[dict[str, str]] = []
    lowered_trigger = trigger.content.lower()
    for path in existing_paths:
        if path.lower() not in lowered_trigger:
            continue
        referenced_files.append(
            {
                "path": path,
                "content": existing_content_by_path.get(path, "")[:4000],
            }
        )
        if len(referenced_files) >= 3:
            break

    guidance: dict[str, str] = {
        "list_files": "Output exactly: list files",
        "add_file": (
            "Output: add file <path> content=<text>. If no path is provided, infer a concise kebab-case filename. "
            "Choose extension by requested type (markdown->.md, text->.txt, json->.json, yaml->.yaml). "
            "If the request asks for generated content (for example a joke), generate concrete content."
        ),
        "edit_file": (
            "Output: edit file <path> content=<text>. Preserve requested style/format and include full new content. "
            "If the user asks to add/append and current content is provided, keep the current content and append."
        ),
        "rename_file": "Output: rename file <path> to <new-path>.",
        "delete_file": "Output: delete file <path>.",
    }

    input_text = (
        "Convert the user request into a single canonical file-tool command.\n"
        "Return strict JSON only with one key: command.\n"
        "Do not include explanations.\n"
        f"Target tool: {tool_name}\n"
        f"Rule: {guidance.get(tool_name, '')}\n"
        f"Existing file paths: {json.dumps(existing_paths[:50])}\n"
        f"Referenced files with current content: {json.dumps(referenced_files)}\n"
        f"User request: {trigger.content}\n"
    )

    rewrite_instruction = (
        "You translate natural language into deterministic file commands for a tool parser. "
        "Always output JSON only: {\"command\":\"...\"}. "
        "Pick practical filenames when missing. "
        "For add/edit operations, include explicit content text in the command. "
        "When appending to an existing file and current content is provided, include the merged full content."
    )

    for runtime_model in _runtime_model_candidates(_agent_model(agent)):
        try:
            resolved = llm_client.resolve_model("reply", runtime_model)
            t0 = time.monotonic()
            response = llm_client.create_message(
                model=resolved,
                max_tokens=16384,
                temperature=min(_agent_temperature(agent), 0.4),
                system=rewrite_instruction,
                messages=[{"role": "user", "content": input_text}],
            )
            duration_ms = int((time.monotonic() - t0) * 1000)
            record_llm_usage(
                session, conversation.id, agent.id, resolved,
                response.usage.input_tokens, response.usage.output_tokens,
                "file_rewrite", duration_ms,
                triggering_user_id=triggering_user_id,
            )
            raw = response.content[0].text.strip()
            command = _extract_file_tool_command(raw)
            if not _is_valid_file_tool_command(tool_name, command):
                continue
            return Message(
                conversation_id=trigger.conversation_id,
                sender_type=trigger.sender_type,
                sender_user_id=trigger.sender_user_id,
                sender_agent_id=trigger.sender_agent_id,
                content=command,
                requires_response=trigger.requires_response,
                response_to_message_id=trigger.response_to_message_id,
            )
        except Exception as exc:
            logger.warning("File tool command rewrite failed with model %s: %s", runtime_model, exc)

    return None


def _is_human_post(message: Message) -> bool:
    return message.sender_type == "user"


def _agent_role(agent: Agent) -> str:
    role = (agent.role or "").strip()
    if role:
        return role
    description = (agent.description or "").strip()
    if description and description != ADMIN_AGENT_SENTINEL:
        return description
    return ""


def _agent_backstory(agent: Agent) -> str:
    return (agent.backstory or "").strip()


def _agent_profile_description(agent: Agent, max_chars: int = 1200) -> str:
    description = (agent.description or "").strip()
    if not description or description == ADMIN_AGENT_SENTINEL:
        return ""
    collapsed = re.sub(r"\s+", " ", description).strip()
    if len(collapsed) <= max_chars:
        return collapsed
    return collapsed[:max_chars].rstrip() + "..."


def _agent_model(agent: Agent) -> str:
    model_name = (agent.model or "").strip()
    if model_name:
        return model_name
    return settings.admin_agent_model


def _agent_temperature(agent: Agent, default: float = 0.7) -> float:
    value = _safe_float(getattr(agent, "temperature", default), default)
    return round(_clamp(value, 0.0, 2.0), 3)


def _agent_verbosity(agent: Agent, default: float = 0.5) -> float:
    value = _safe_float(getattr(agent, "verbosity", default), default)
    return round(_clamp(value, 0.0, 1.0), 3)


def _agent_learning_state(agent: Agent) -> dict[str, float]:
    if isinstance(agent.learning_state, dict) and agent.learning_state:
        return dict(agent.learning_state)
    return dict(agent.learned_preferences or {})


def _set_agent_learning_state(agent: Agent, state: dict[str, float]) -> None:
    normalized = dict(state or {})
    agent.learning_state = normalized
    # Keep compatibility with legacy code/clients.
    agent.learned_preferences = dict(normalized)


def _agent_sentiment_state(agent: Agent) -> dict[str, float]:
    raw = dict(agent.sentiment_state or {})
    keys = ("valence", "arousal", "confidence")
    state: dict[str, float] = {}
    for key in keys:
        state[key] = round(_clamp(_safe_float(raw.get(key), 0.0)), 3)
    return state


def _set_agent_sentiment_state(agent: Agent, state: dict[str, float]) -> None:
    keys = ("valence", "arousal", "confidence")
    normalized: dict[str, float] = {}
    for key in keys:
        normalized[key] = round(_clamp(_safe_float(state.get(key), 0.0)), 3)
    agent.sentiment_state = normalized


def apply_learning_signal(session: Session, agent: Agent, trigger: Message) -> None:
    if trigger.sender_type != "user":
        return

    text = trigger.content.lower()
    prefs = _agent_learning_state(agent)
    brevity_bias = float(prefs.get("brevity_bias", 0.0))
    engagement_bias = float(prefs.get("engagement_bias", 0.0))
    initiative_bias = float(prefs.get("initiative_bias", 0.0))
    confidence_bias = float(prefs.get("confidence_bias", 0.0))

    if any(key in text for key in ["brief", "concise", "short"]):
        brevity_bias += 0.08
    if any(key in text for key in ["detail", "detailed", "deeper"]):
        brevity_bias -= 0.08
    if _is_mentioned(agent, text) or "?" in text:
        engagement_bias += 0.03
    else:
        engagement_bias -= 0.01

    if any(key in text for key in ["please", "can ", "could ", "would ", "help"]):
        initiative_bias += 0.01
    if any(key in text for key in ["wrong", "incorrect", "not right"]):
        confidence_bias -= 0.03
    if any(key in text for key in ["thanks", "thank you", "great", "good call"]):
        confidence_bias += 0.02

    brevity_bias = max(-1.0, min(1.0, brevity_bias))
    engagement_bias = max(-1.0, min(1.0, engagement_bias))
    initiative_bias = max(-1.0, min(1.0, initiative_bias))
    confidence_bias = max(-1.0, min(1.0, confidence_bias))

    prefs["brevity_bias"] = round(brevity_bias, 3)
    prefs["engagement_bias"] = round(engagement_bias, 3)
    prefs["initiative_bias"] = round(initiative_bias, 3)
    prefs["confidence_bias"] = round(confidence_bias, 3)

    _set_agent_learning_state(agent, prefs)

    sentiment = _agent_sentiment_state(agent)
    if "?" in text:
        sentiment["arousal"] = round(_clamp(sentiment.get("arousal", 0.0) + 0.06), 3)
    else:
        sentiment["arousal"] = round(_clamp(sentiment.get("arousal", 0.0) - 0.02), 3)
    if _is_mentioned(agent, text):
        sentiment["valence"] = round(_clamp(sentiment.get("valence", 0.0) + 0.03), 3)
    sentiment["confidence"] = round(_clamp(confidence_bias), 3)
    _set_agent_sentiment_state(agent, sentiment)
    session.add(agent)

    event = AgentLearningEvent(
        agent_id=agent.id,
        message_id=trigger.id,
        signal_type="message_style_feedback",
        value={
            "brevity_bias": prefs["brevity_bias"],
            "engagement_bias": prefs["engagement_bias"],
            "initiative_bias": prefs["initiative_bias"],
            "confidence_bias": prefs["confidence_bias"],
            "sentiment": dict(agent.sentiment_state or {}),
        },
    )
    session.add(event)


def _is_question_like(text: str | None) -> bool:
    lowered = (text or "").strip().lower()
    if not lowered:
        return False
    if "?" in lowered:
        return True
    return lowered.startswith(
        ("who ", "what ", "when ", "where ", "why ", "how ", "can ", "could ", "would ", "is ", "are ", "do ", "does ")
    )


def _heuristic_response_score(agent: Agent, conversation: Conversation, trigger: Message) -> float:
    if trigger.sender_type == "agent" and trigger.sender_agent_id == agent.id:
        return -1.0

    # In a direct user<->agent chat, the user expects a response each turn.
    if trigger.sender_type == "user" and conversation.kind == "direct":
        return 1.0

    content = trigger.content
    lowered = content.strip().lower()
    score = 0.1
    mentioned = _is_mentioned(agent, content)

    if conversation.kind == "direct":
        score += 0.2
    if mentioned:
        score += 0.6

    if _is_question_like(content):
        score += 0.32 if conversation.kind == "topic" else 0.25

    # In topic chat, unmentioned agents should answer only when the message appears relevant.
    if conversation.kind == "topic" and trigger.sender_type == "user" and not mentioned:
        score -= 0.25
        score += _topic_relevance_bonus(agent, content)
        score += _role_identity_bonus(agent, content)

    score += _personality_engagement_bonus(agent)

    if trigger.sender_type == "agent" and not mentioned:
        score -= 0.15

    engagement_bias = float(_agent_learning_state(agent).get("engagement_bias", 0.0))
    score += engagement_bias * 0.2

    return score


def _get_anthropic_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip() or (settings.anthropic_api_key or "").strip()
    return anthropic.Anthropic(api_key=api_key)


def _runtime_agent_llm_enabled() -> bool:
    return llm_client.llm_enabled()


def _runtime_model_candidates(primary_model: str | None) -> list[str]:
    candidates: list[str] = []
    override = settings.llm_default_model.strip()
    if override:
        candidates.append(override)
    else:
        for model in [primary_model, settings.admin_agent_model, "claude-sonnet-4-5", "claude-haiku-4-5"]:
            normalized = (model or "").strip()
            if normalized and normalized not in candidates:
                candidates.append(normalized)
    return candidates


def _model_supports_temperature(model_name: str) -> bool:
    return True


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _current_disposition(agent: Agent) -> dict[str, float]:
    prefs = _agent_learning_state(agent)
    keys = ("engagement_bias", "initiative_bias", "confidence_bias", "brevity_bias")
    disposition: dict[str, float] = {}
    for key in keys:
        disposition[key] = round(_clamp(_safe_float(prefs.get(key), 0.0)), 3)
    return disposition


def _extract_json_object(text: str) -> dict | None:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        return None

    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _probe_agent_intent(
    session: Session,
    agent: Agent,
    conversation: Conversation,
    trigger: Message,
    chain_step: int,
    chain_responded_ids: list[str],
    candidates: list[Agent],
    triggering_user_id: str | None = None,
) -> tuple[str | None, float]:
    """Ask an individual agent whether it has a specific contribution to make.

    Returns (intent_text, urgency).  On abstention or error: (None, 0.0).
    """
    try:
        name = agent.name
        role = _agent_role(agent) or name
        personality_text = _clean_agent_personality_text(agent)
        disposition = _current_disposition(agent)
        voice_hint = _disposition_voice_hint(disposition)
        sentiment = _agent_sentiment_state(agent)
        confidence = sentiment.get("confidence", 0.0)

        system_prompt = (
            f"You are {name}. Role: {role}. Personality: {personality_text}.\n"
            f"Disposition: {voice_hint}. Confidence: {confidence}.\n\n"
            "Decide whether you have a specific, distinct contribution to this conversation. "
            "Return JSON only."
        )

        trigger_sender = "human" if _is_human_post(trigger) else f"agent:{trigger.sender_agent_id or 'unknown'}"

        chain_context_block = ""
        if chain_step > 0:
            names_map = {a.id: a.name for a in candidates}
            responded_names = [names_map.get(aid, aid) for aid in chain_responded_ids]
            chain_context_block = (
                f"Chain step: {chain_step + 1}. Already responded: {', '.join(responded_names)}. "
                "Don't repeat what they said.\n"
            )

        history = _selector_history_context(session, conversation, max_messages=10, max_chars=2000)

        workflow_hint = ""
        try:
            wg = session.get(Workgroup, conversation.workgroup_id)
            if wg:
                workflow_hint = _build_workflow_hint(wg, conversation)
        except Exception:
            pass

        user_prompt = (
            f"Topic: {conversation.topic}\n"
            f"Kind: {conversation.kind}\n"
            f"Trigger from: {trigger_sender}\n"
            f"Trigger: {trigger.content[:400]}\n\n"
            + (f"{chain_context_block}\n" if chain_context_block else "")
            + (f"{workflow_hint}\n\n" if workflow_hint else "")
            + f"Recent messages:\n{history}\n\n"
            "Return strict JSON:\n"
            '{"intent": "<one sentence: your specific point, or null>", "urgency": <0.0 to 1.0>}\n\n'
            "Rules:\n"
            "- 0: nothing to add, would just agree or paraphrase\n"
            "- 0.3-0.5: tangentially related comment\n"
            "- 0.6-0.8: relevant perspective, useful information, or building on others' points\n"
            "- 0.8-1.0: new insight, unique angle, critical disagreement, essential correction, or aha-moment\n"
            "- null intent + 0 urgency if you would just validate, encourage, or restate"
        )

        resolved = llm_client.resolve_model("cheap", settings.intent_probe_model)
        model_candidates = [resolved]
        if not model_candidates:
            return (None, 0.0)

        for runtime_model in model_candidates:
            try:
                t0 = time.monotonic()
                response = llm_client.create_message(
                    model=runtime_model,
                    max_tokens=256,
                    temperature=0.3,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                duration_ms = int((time.monotonic() - t0) * 1000)
                record_llm_usage(
                    session, conversation.id, agent.id, runtime_model,
                    response.usage.input_tokens, response.usage.output_tokens,
                    "intent_probe", duration_ms,
                    triggering_user_id=triggering_user_id,
                )

                raw_text = response.content[0].text if response.content else ""
                parsed = _extract_json_object(raw_text)
                if not parsed:
                    logger.warning("Intent probe for agent %s returned unparseable JSON: %.120s", agent.id, raw_text)
                    return (None, 0.0)

                intent = parsed.get("intent")
                if intent is not None:
                    intent = str(intent).strip()
                    if not intent or intent.lower() == "null":
                        intent = None

                urgency = _clamp(_safe_float(parsed.get("urgency"), 0.0), 0.0, 1.0)
                return (intent, urgency)
            except Exception as exc:
                logger.warning("Intent probe LLM call failed for agent %s with model %s: %s", agent.id, runtime_model, exc)

        return (None, 0.0)
    except Exception as exc:
        logger.warning("Intent probe failed for agent %s: %s", agent.id, exc)
        return (None, 0.0)


def _gather_agent_intents(
    session: Session,
    conversation: Conversation,
    trigger: Message,
    candidates: list[Agent],
    blocked_agent_ids: set[str],
    chain_step: int = 0,
    chain_responded_ids: list[str] | None = None,
    triggering_user_id: str | None = None,
) -> list[tuple[Agent, str | None, float]]:
    """Probe each non-blocked candidate for intent. Return list sorted by urgency descending."""
    results: list[tuple[Agent, str | None, float]] = []
    responded = chain_responded_ids or []

    for agent in candidates:
        if agent.id in blocked_agent_ids:
            continue

        _set_activity(conversation.id, agent.id, agent.name, "probing")

        intent, urgency = _probe_agent_intent(
            session=session,
            agent=agent,
            conversation=conversation,
            trigger=trigger,
            chain_step=chain_step,
            chain_responded_ids=responded,
            candidates=candidates,
            triggering_user_id=triggering_user_id,
        )

        # Record as learning event for observability.
        try:
            event = AgentLearningEvent(
                agent_id=agent.id,
                message_id=trigger.id,
                signal_type="intent_probe",
                value={
                    "intent": intent,
                    "urgency": urgency,
                    "threshold": agent.response_threshold,
                    "chain_step": chain_step,
                },
            )
            session.add(event)
            commit_with_retry(session)
        except Exception as exc:
            logger.warning("Failed to record intent_probe event for agent %s: %s", agent.id, exc)
            try:
                session.rollback()
            except Exception:
                pass

        results.append((agent, intent, urgency))

    results.sort(key=lambda r: r[2], reverse=True)
    return results


def _store_agent_thoughts(
    session: Session,
    agent: Agent,
    message: Message,
    intent: str | None,
    urgency: float,
    tool_name: str | None,
    chain_step: int,
) -> None:
    value: dict = {}
    if intent is not None:
        value["intent"] = intent
    if urgency:
        value["urgency"] = urgency
    if tool_name:
        value["tool_name"] = tool_name
    if chain_step:
        value["chain_step"] = chain_step
    event = AgentLearningEvent(
        agent_id=agent.id,
        message_id=message.id,
        signal_type="agent_thoughts",
        value=value,
    )
    session.add(event)


def _apply_disposition_delta(
    session: Session,
    agent: Agent,
    delta_payload: object,
) -> dict[str, float]:
    if not isinstance(delta_payload, dict):
        return {}

    prefs = _agent_learning_state(agent)
    keys = ("engagement_bias", "initiative_bias", "confidence_bias", "brevity_bias")
    applied: dict[str, float] = {}

    for key in keys:
        if key not in delta_payload:
            continue
        raw_delta = _safe_float(delta_payload.get(key), 0.0)
        delta = _clamp(raw_delta, -0.12, 0.12)
        if delta == 0.0:
            continue
        current = _safe_float(prefs.get(key), 0.0)
        updated = round(_clamp(current + delta), 3)
        prefs[key] = updated
        applied[key] = round(delta, 3)

    if applied:
        _set_agent_learning_state(agent, prefs)
        sentiment = _agent_sentiment_state(agent)
        if "confidence_bias" in applied:
            sentiment["confidence"] = round(_clamp(sentiment.get("confidence", 0.0) + applied["confidence_bias"]), 3)
        if "engagement_bias" in applied:
            sentiment["valence"] = round(_clamp(sentiment.get("valence", 0.0) + 0.25 * applied["engagement_bias"]), 3)
        _set_agent_sentiment_state(agent, sentiment)
        session.add(agent)

    return applied


def _selector_history_context(
    session: Session,
    conversation: Conversation,
    max_messages: int = 18,
    max_chars: int = 3500,
) -> str:
    rows = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.asc())
    ).all()
    if not rows:
        return ""

    if len(rows) > max_messages:
        rows = rows[-max_messages:]

    agent_names = {
        item.id: item.name
        for item in session.exec(select(Agent).where(Agent.workgroup_id == conversation.workgroup_id)).all()
    }

    lines: list[str] = []
    for row in rows:
        if row.sender_type == "user":
            label = "user"
        else:
            label = f"agent:{agent_names.get(row.sender_agent_id or '', 'agent')}"
        content = " ".join(row.content.split())
        if len(content) > 260:
            content = content[:260].rstrip() + "..."
        lines.append(f"- {label}: {content}")

    history = "\n".join(lines)
    if len(history) > max_chars:
        history = "...\n" + history[-max_chars:]
    return history


def _llm_select_responders(
    session: Session,
    conversation: Conversation,
    trigger: Message,
    candidates: list[Agent],
    blocked_agent_ids: set[str],
    min_select: int = 0,
    max_select: int = 1,
    selector_guidance: str = "",
    triggering_user_id: str | None = None,
) -> list[Agent]:
    if not _runtime_agent_llm_enabled() or not candidates:
        return []

    available_agents = [agent for agent in candidates if agent.id not in blocked_agent_ids]
    if not available_agents:
        return []

    max_select = max(1, min(max_select, len(available_agents)))
    min_select = max(0, min(min_select, max_select))

    candidate_payload = [
        {
            "id": agent.id,
            "name": agent.name,
            "role": _agent_role(agent)[:180],
            "personality": (agent.personality or "")[:220],
            "backstory": _agent_backstory(agent)[:260],
            "model": _agent_model(agent),
            "temperature": _agent_temperature(agent),
            "verbosity": _agent_verbosity(agent),
            "tool_names": agent.tool_names or [],
            "response_threshold": agent.response_threshold,
            "disposition": _current_disposition(agent),
            "sentiment": _agent_sentiment_state(agent),
        }
        for agent in available_agents
    ]
    history = _selector_history_context(session, conversation)
    response_rule = (
        f"- You must select between {min_select} and {max_select} agents.\n"
        if min_select > 0
        else f"- You may select between 0 and {max_select} agents.\n"
    )
    input_text = (
        "Select the next responding agents for a multi-agent conversation.\n"
        "Return strict JSON only with keys:\n"
        "selected_agent_ids (array of unique agent ids in preferred order), confidence (0..1), rationale (string <= 220 chars), "
        "disposition_deltas (object keyed by agent id; each value is an object with optional numeric keys: engagement_bias, initiative_bias, confidence_bias, brevity_bias; each in [-0.12, 0.12]).\n"
        "Constraints:\n"
        "- selected_agent_ids must be from candidate_agents.\n"
        "- Never choose an id in blocked_agent_ids.\n"
        "- Select only agents with materially distinct, additive contributions.\n"
        "- Prefer diversity of viewpoint and role fit over agreement.\n"
        "- Avoid dogpiling with redundant responses.\n"
        + (
            "- For agent-triggered turns: apply a higher bar. Only select if the agent has "
            "a materially different viewpoint or new information. Mere agreement or "
            "encouragement does NOT warrant a response. When in doubt, select no one.\n"
            if trigger.sender_type == "agent"
            else ""
        )
        + f"{response_rule}"
        f"{selector_guidance.strip()}\n\n"
        f"Conversation kind: {conversation.kind}\n"
        f"Conversation topic: {conversation.topic}\n"
        f"Trigger sender_type: {trigger.sender_type}\n"
        f"Trigger content: {trigger.content}\n"
        f"blocked_agent_ids: {json.dumps(sorted(blocked_agent_ids))}\n\n"
        f"candidate_agents:\n{json.dumps(candidate_payload, indent=2)}\n\n"
        "Recent conversation history (oldest to newest):\n"
        f"{history or '- user: (no prior messages)'}\n"
    )

    raw = ""
    selector_system = (
        "You are the orchestration policy for a multi-agent chat. "
        "Choose the best next responders from candidates using relevance, role fit, personality fit, "
        "current disposition, and recent dialogue dynamics."
    )
    resolved = llm_client.resolve_model("cheap", settings.admin_agent_model)
    for selector_model in [resolved]:
        try:
            t0 = time.monotonic()
            response = llm_client.create_message(
                model=selector_model,
                max_tokens=1024,
                system=selector_system,
                messages=[{"role": "user", "content": input_text}],
            )
            duration_ms = int((time.monotonic() - t0) * 1000)
            record_llm_usage(
                session, conversation.id, None, selector_model,
                response.usage.input_tokens, response.usage.output_tokens,
                "selector", duration_ms,
                triggering_user_id=triggering_user_id,
            )
            raw = response.content[0].text.strip()
            if raw:
                break
        except Exception as exc:
            logger.warning("LLM selector run failed with model %s: %s", selector_model, exc)

    if not raw:
        return []

    parsed = _extract_json_object(raw)
    if not parsed:
        logger.warning("LLM selector output was not valid JSON: %s", raw[:260])
        return []

    selected_ids_raw = parsed.get("selected_agent_ids")
    if selected_ids_raw is None:
        legacy_id = parsed.get("selected_agent_id")
        selected_ids_raw = [] if legacy_id in (None, "", "null") else [legacy_id]
    if not isinstance(selected_ids_raw, list):
        selected_ids_raw = []

    candidate_by_id = {agent.id: agent for agent in available_agents}
    selected_ids: list[str] = []
    seen: set[str] = set()
    for raw_id in selected_ids_raw:
        if raw_id in (None, "", "null"):
            continue
        selected_id = str(raw_id)
        if selected_id in seen:
            continue
        if selected_id not in candidate_by_id:
            continue
        seen.add(selected_id)
        selected_ids.append(selected_id)
        if len(selected_ids) >= max_select:
            break

    if len(selected_ids) < min_select:
        remaining = [agent for agent in available_agents if agent.id not in seen]
        remaining.sort(
            key=lambda agent: _heuristic_response_score(agent, conversation, trigger) - agent.response_threshold,
            reverse=True,
        )
        for agent in remaining:
            selected_ids.append(agent.id)
            seen.add(agent.id)
            if len(selected_ids) >= min_select:
                break

    confidence = _clamp(_safe_float(parsed.get("confidence"), 0.5), 0.0, 1.0)
    rationale = str(parsed.get("rationale") or "").strip()[:300]
    disposition_deltas = parsed.get("disposition_deltas")
    if not isinstance(disposition_deltas, dict):
        disposition_deltas = {}

    selected_agents: list[Agent] = []
    selected_agent_ids = list(selected_ids)
    for index, selected_id in enumerate(selected_ids):
        agent = candidate_by_id.get(selected_id)
        if not agent:
            continue
        selected_agents.append(agent)
        applied = _apply_disposition_delta(session, agent, disposition_deltas.get(selected_id))
        session.add(
            AgentLearningEvent(
                agent_id=agent.id,
                message_id=trigger.id,
                signal_type="llm_responder_selection",
                value={
                    "selected_agent_id": agent.id,
                    "selected_agent_ids": selected_agent_ids,
                    "selected_rank": index + 1,
                    "confidence": round(confidence, 3),
                    "rationale": rationale,
                    "disposition_delta": applied,
                },
            )
        )

    if not selected_agents and min_select == 0 and available_agents:
        session.add(
            AgentLearningEvent(
                agent_id=available_agents[0].id,
                message_id=trigger.id,
                signal_type="llm_responder_selection",
                value={
                    "selected_agent_id": None,
                    "selected_agent_ids": [],
                    "confidence": round(confidence, 3),
                    "rationale": rationale,
                    "disposition_delta": {},
                },
            )
        )

    return selected_agents


def _llm_select_responder(
    session: Session,
    conversation: Conversation,
    trigger: Message,
    candidates: list[Agent],
    blocked_agent_ids: set[str],
    must_respond: bool | None = None,
    selector_guidance: str = "",
    triggering_user_id: str | None = None,
) -> Agent | None:
    required = _is_human_post(trigger) if must_respond is None else must_respond
    selected = _llm_select_responders(
        session=session,
        conversation=conversation,
        trigger=trigger,
        candidates=candidates,
        blocked_agent_ids=blocked_agent_ids,
        min_select=1 if required else 0,
        max_select=1,
        selector_guidance=selector_guidance,
        triggering_user_id=triggering_user_id,
    )
    return selected[0] if selected else None


def _heuristic_select_responder(
    conversation: Conversation,
    trigger: Message,
    candidates: list[Agent],
    blocked_agent_ids: set[str],
    must_respond: bool | None = None,
) -> Agent | None:
    best_agent: Agent | None = None
    best_margin = -999.0
    for agent in candidates:
        if agent.id in blocked_agent_ids:
            continue
        score = _heuristic_response_score(agent, conversation, trigger)
        margin = score - agent.response_threshold
        if margin > best_margin:
            best_margin = margin
            best_agent = agent

    if best_agent is None:
        return None
    if best_margin < 0:
        required = _is_human_post(trigger) if must_respond is None else must_respond
        if required:
            return best_agent
        return None
    return best_agent


def _select_responder(
    session: Session,
    conversation: Conversation,
    trigger: Message,
    candidates: list[Agent],
    blocked_agent_ids: set[str],
    must_respond: bool | None = None,
    chain_step: int = 0,
    chain_responded_ids: list[str] | None = None,
    triggering_user_id: str | None = None,
) -> tuple[Agent, str | None, float] | None:
    if not candidates:
        return None

    # Direct conversations with a single candidate skip probing entirely.
    eligible = [a for a in candidates if a.id not in blocked_agent_ids]
    if conversation.kind == "direct" and len(eligible) == 1:
        return (eligible[0], None, 0.0)

    try:
        intents = _gather_agent_intents(
            session=session,
            conversation=conversation,
            trigger=trigger,
            candidates=candidates,
            blocked_agent_ids=blocked_agent_ids,
            chain_step=chain_step,
            chain_responded_ids=chain_responded_ids,
            triggering_user_id=triggering_user_id,
        )

        # Filter to agents with declared intent above their response_threshold.
        above_threshold = [
            (agent, intent, urgency)
            for agent, intent, urgency in intents
            if intent is not None and urgency >= agent.response_threshold
        ]

        if above_threshold:
            best_agent, best_intent, best_urgency = above_threshold[0]  # already sorted by urgency desc
            return (best_agent, best_intent, best_urgency)

        # Human triggered: force best candidate (must_respond behavior).
        required = _is_human_post(trigger) if must_respond is None else must_respond
        if required and intents:
            best_agent = intents[0][0]
            best_intent = intents[0][1]
            return (best_agent, best_intent, intents[0][2])

        # Agent triggered and no one above threshold → natural pause.
        return None

    except Exception as exc:
        logger.warning("Intent-probe selection failed, falling back to heuristic: %s", exc)

    fallback = _heuristic_select_responder(
        conversation=conversation,
        trigger=trigger,
        candidates=candidates,
        blocked_agent_ids=blocked_agent_ids,
        must_respond=must_respond,
    )
    return (fallback, None, 0.0) if fallback else None


def _relevance_tokens(text: str) -> set[str]:
    return {
        token
        for token in RELEVANCE_TOKEN_RE.findall(text.lower())
        if token not in RELEVANCE_STOPWORDS
    }


def _agent_profile_text(agent: Agent) -> str:
    parts = [agent.name, agent.personality]
    role = _agent_role(agent)
    if role:
        parts.append(role)
    backstory = _agent_backstory(agent)
    if backstory:
        parts.append(backstory)
    if agent.tool_names:
        parts.extend(tool.replace("_", " ") for tool in agent.tool_names)
    return " ".join(part for part in parts if part)


def _personality_engagement_bonus(agent: Agent) -> float:
    text = f"{agent.name} {agent.personality} {_agent_role(agent)} {_agent_backstory(agent)}".lower()
    bonus = 0.0
    if any(keyword in text for keyword in PERSONALITY_ENGAGED_KEYWORDS):
        bonus += 0.08
    if any(keyword in text for keyword in PERSONALITY_RESERVED_KEYWORDS):
        bonus -= 0.08
    return bonus


def _is_role_or_identity_query(content: str) -> bool:
    lowered = content.strip().lower()
    return (
        "who is in this chat" in lowered
        or "who's in this chat" in lowered
        or "who are you" in lowered
        or "what do you do" in lowered
        or "which agent" in lowered
        or "who can help" in lowered
    )


def _role_identity_bonus(agent: Agent, content: str) -> float:
    if not _is_role_or_identity_query(content):
        return 0.0

    profile_tokens = _relevance_tokens(_agent_profile_text(agent))
    if not profile_tokens:
        return 0.0

    # Role/identity questions should draw responses from agents with a clear role profile.
    return 0.22


def _topic_relevance_bonus(agent: Agent, content: str) -> float:
    message_tokens = _relevance_tokens(content)
    if not message_tokens:
        return 0.0

    profile_tokens = _relevance_tokens(_agent_profile_text(agent))
    if not profile_tokens:
        return 0.0

    overlap = message_tokens & profile_tokens
    if not overlap:
        return 0.0

    # One meaningful overlap should usually clear default thresholds for topic questions.
    return min(0.4, 0.28 + 0.06 * (len(overlap) - 1))


def _user_display_name(user: User) -> str:
    name = (user.name or "").strip()
    if name:
        return name
    email = (user.email or "").strip()
    if email:
        return email.split("@", 1)[0]
    return "user"


def _load_sender_name_maps(session: Session, rows: list[Message]) -> tuple[dict[str, str], dict[str, str]]:
    user_ids = {row.sender_user_id for row in rows if row.sender_user_id}
    agent_ids = {row.sender_agent_id for row in rows if row.sender_agent_id}

    user_names: dict[str, str] = {}
    if user_ids:
        users = session.exec(select(User).where(User.id.in_(user_ids))).all()
        user_names = {user.id: _user_display_name(user) for user in users}

    agent_names: dict[str, str] = {}
    if agent_ids:
        agents = session.exec(select(Agent).where(Agent.id.in_(agent_ids))).all()
        agent_names = {agent.id: agent.name for agent in agents}

    return user_names, agent_names


def _message_sender_label(
    message: Message,
    assistant_agent_id: str,
    user_names: dict[str, str],
    agent_names: dict[str, str],
) -> str:
    if message.sender_type == "user":
        return f"user:{user_names.get(message.sender_user_id or '', 'user')}"
    agent_name = agent_names.get(message.sender_agent_id or "", "agent")
    if message.sender_agent_id == assistant_agent_id:
        return f"assistant:{agent_name}"
    return f"agent:{agent_name}"


def _conversation_history_context(
    session: Session,
    conversation_id: str,
    agent_id: str,
    rows: list[Message] | None = None,
    max_messages: int = 45,
    max_chars: int = 12000,
) -> str:
    if rows is None:
        rows = session.exec(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
        ).all()
    if not rows:
        return ""

    if len(rows) > max_messages:
        rows = rows[-max_messages:]

    user_names, agent_names = _load_sender_name_maps(session, rows)

    lines: list[str] = []
    for row in rows:
        content = " ".join(row.content.split())
        if len(content) > 320:
            content = content[:320].rstrip() + "..."
        lines.append(f"- {_message_sender_label(row, agent_id, user_names, agent_names)}: {content}")

    history = "\n".join(lines)
    if len(history) > max_chars:
        history = "...\n" + history[-max_chars:]
    return history


def _latest_user_message(rows: list[Message], before_message_id: str | None = None) -> Message | None:
    if not rows:
        return None

    end_index = len(rows) - 1
    if before_message_id:
        for index, row in enumerate(rows):
            if row.id == before_message_id:
                end_index = index
                break

    for index in range(end_index, -1, -1):
        if rows[index].sender_type == "user":
            return rows[index]
    return None


def _trim_to_words(text: str, limit: int) -> str:
    words = text.split()
    if len(words) <= limit:
        return text
    shortened = " ".join(words[:limit]).rstrip(" ,;:.")
    return f"{shortened}..."


def _trim_to_sentences(text: str, max_sentences: int) -> str:
    parts = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    if len(parts) <= max_sentences:
        return text
    return " ".join(parts[:max_sentences]).strip()


def _is_introduction_request(text: str | None) -> bool:
    lowered = (text or "").strip().lower()
    if not lowered:
        return False
    return bool(
        re.search(
            r"\b(introduce yourself|say a few words about yourself|tell us about yourself|start with introductions|introduction)\b",
            lowered,
        )
    )


def _effective_verbosity(agent: Agent) -> float:
    configured = _agent_verbosity(agent)
    brevity_bias = _safe_float(_agent_learning_state(agent).get("brevity_bias"), 0.0)
    adjusted = configured - (0.35 * brevity_bias)
    return round(_clamp(adjusted, 0.0, 1.0), 3)


def _verbosity_style_profile(verbosity: float) -> tuple[str, str]:
    if verbosity <= 0.2:
        return ("ultra-brief", "Keep response to 1-2 short sentences (<=55 words).")
    if verbosity <= 0.4:
        return ("brief", "Keep response to 2-4 sentences (<=90 words).")
    if verbosity <= 0.65:
        return ("balanced", "Keep response to one short paragraph (<=140 words).")
    if verbosity <= 0.82:
        return ("detailed", "Use up to two short paragraphs (<=220 words).")
    return ("very-detailed", "Use at most three short paragraphs (<=320 words), only when needed.")


def _normalize_agent_reply_text(agent: Agent, content: str) -> str:
    text = str(content or "").strip()
    if not text:
        return ""

    if text.startswith("```"):
        text = re.sub(r"^```(?:[a-zA-Z0-9_-]+)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    text = re.sub(rf"^\s*{re.escape(agent.name)}\s*:\s*", "", text, flags=re.IGNORECASE)
    text = text.strip()
    return text


def _disposition_voice_hint(disposition: dict[str, float]) -> str:
    confidence = _safe_float(disposition.get("confidence_bias"), 0.0)
    initiative = _safe_float(disposition.get("initiative_bias"), 0.0)
    engagement = _safe_float(disposition.get("engagement_bias"), 0.0)
    brevity = _safe_float(disposition.get("brevity_bias"), 0.0)

    confidence_tone = "decisive" if confidence >= 0.25 else "cautious" if confidence <= -0.25 else "balanced"
    initiative_tone = "proactive" if initiative >= 0.25 else "reactive" if initiative <= -0.25 else "situational"
    engagement_tone = "engaged" if engagement >= 0.25 else "reserved" if engagement <= -0.25 else "neutral"
    brevity_tone = "concise" if brevity >= 0.2 else "elaborative" if brevity <= -0.2 else "moderate detail"
    return (
        f"{confidence_tone} stance, {initiative_tone} initiative, "
        f"{engagement_tone} social tone, {brevity_tone}"
    )


def _agent_experience_context(
    session: Session,
    agent: Agent,
    conversation_id: str,
    max_messages: int = 8,
    max_events: int = 8,
    max_chars: int = 2500,
) -> str:
    prior_messages = session.exec(
        select(Message)
        .where(
            Message.conversation_id == conversation_id,
            Message.sender_type == "agent",
            Message.sender_agent_id == agent.id,
        )
        .order_by(Message.created_at.desc())
        .limit(max_messages)
    ).all()
    prior_messages = list(reversed(prior_messages))

    event_rows = session.exec(
        select(AgentLearningEvent)
        .join(Message, AgentLearningEvent.message_id == Message.id)
        .where(
            AgentLearningEvent.agent_id == agent.id,
            Message.conversation_id == conversation_id,
        )
        .order_by(AgentLearningEvent.created_at.desc())
        .limit(max_events)
    ).all()
    event_rows = list(reversed(event_rows))

    lines: list[str] = []
    lines.append(f"Current learning state: {_agent_learning_state(agent)}")
    lines.append(f"Current sentiment state: {_agent_sentiment_state(agent)}")
    if prior_messages:
        lines.append("Your prior statements in this conversation:")
        for row in prior_messages:
            content = " ".join(row.content.split())
            if len(content) > 220:
                content = content[:220].rstrip() + "..."
            lines.append(f"- {content}")
    else:
        lines.append("Your prior statements in this conversation: none yet.")

    if event_rows:
        lines.append("Recent internal learning signals:")
        for event in event_rows:
            value = event.value or {}
            if event.signal_type == "message_style_feedback":
                brevity = _safe_float(value.get("brevity_bias"), 0.0)
                engagement = _safe_float(value.get("engagement_bias"), 0.0)
                lines.append(
                    f"- style feedback -> brevity_bias={round(brevity, 3)}, engagement_bias={round(engagement, 3)}"
                )
                continue

            if event.signal_type == "llm_responder_selection":
                selected_agent_id = value.get("selected_agent_id")
                confidence = _safe_float(value.get("confidence"), 0.0)
                rationale = str(value.get("rationale") or "").strip()
                if len(rationale) > 140:
                    rationale = rationale[:140].rstrip() + "..."
                lines.append(
                    f"- responder selection -> selected_agent_id={selected_agent_id}, "
                    f"confidence={round(confidence, 3)}, rationale={rationale or '(none)'}"
                )
                continue

            lines.append(f"- {event.signal_type}")

    summary = "\n".join(lines)
    if len(summary) > max_chars:
        summary = summary[-max_chars:]
    return summary


def _load_task_context(session: Session, conversation: Conversation) -> str:
    topic = (conversation.topic or "").strip()
    if not topic.startswith("task:"):
        return ""
    task_id = topic[len("task:"):]
    task = session.get(CrossGroupTask, task_id)
    if not task:
        return ""
    source_wg = session.get(Workgroup, task.source_workgroup_id)
    source_name = source_wg.name if source_wg else task.source_workgroup_id
    return (
        f"This conversation is for a cross-group task requested by workgroup '{source_name}'.\n"
        f"Task title: {task.title}\n"
        f"Scope: {task.scope}\n"
        f"Requirements: {task.requirements}\n"
        f"Agreed terms: {task.terms or '(none)'}\n"
        f"Task status: {task.status}\n"
    )


def _build_engagement_context(session: Session, conversation: Conversation) -> str:
    from teaparty_app.models import Engagement

    topic = (conversation.topic or "").strip()
    if not topic.startswith("engagement:"):
        return ""
    engagement_id = topic[len("engagement:"):]
    engagement = session.get(Engagement, engagement_id)
    if not engagement:
        return ""
    source_wg = session.get(Workgroup, engagement.source_workgroup_id)
    target_wg = session.get(Workgroup, engagement.target_workgroup_id)
    source_name = source_wg.name if source_wg else engagement.source_workgroup_id
    target_name = target_wg.name if target_wg else engagement.target_workgroup_id
    is_source_side = conversation.workgroup_id == engagement.source_workgroup_id
    role = "requester (source)" if is_source_side else "provider (target)"
    return (
        f"This conversation is an engagement between workgroups.\n"
        f"Your workgroup's role: {role}\n"
        f"Source workgroup: {source_name}\n"
        f"Target workgroup: {target_name}\n"
        f"Engagement title: {engagement.title}\n"
        f"Scope: {engagement.scope or '(none)'}\n"
        f"Requirements: {engagement.requirements or '(none)'}\n"
        f"Terms: {engagement.terms or '(none)'}\n"
        f"Engagement status: {engagement.status}\n"
        f"Messages from the other side appear with [synced from ...] attribution.\n"
    )


def _build_cross_topic_activity_context(
    session: Session, agent: Agent, conversation: Conversation
) -> str:
    """Summarize agent's recent messages across topic/engagement convos for DM awareness."""
    if conversation.kind != "direct":
        return ""

    # Fetch the agent's messages from non-archived topic/engagement convos in this workgroup
    rows = session.exec(
        select(Message, Conversation)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(
            Message.sender_agent_id == agent.id,
            Conversation.workgroup_id == conversation.workgroup_id,
            Conversation.kind.in_(["topic", "engagement"]),
            Conversation.is_archived == False,
        )
        .order_by(Message.created_at.desc())
    ).all()

    if not rows:
        return ""

    # Group by conversation, keeping insertion order (most recent first)
    from collections import OrderedDict

    by_convo: OrderedDict[str, list[tuple]] = OrderedDict()
    for msg, convo in rows:
        by_convo.setdefault(convo.id, []).append((msg, convo))

    lines: list[str] = []
    total_chars = 0
    max_chars = 2500
    max_topics = 8
    max_per_topic = 3

    for _convo_id, entries in list(by_convo.items())[:max_topics]:
        convo_obj = entries[0][1]
        label = convo_obj.name or convo_obj.topic or convo_obj.id
        lines.append(f"- Topic '{label}':")
        for msg, _ in entries[:max_per_topic]:
            snippet = msg.content[:300].replace("\n", " ").strip()
            if len(msg.content) > 300:
                snippet += "..."
            line = f"  - {snippet}"
            total_chars += len(line)
            if total_chars > max_chars:
                break
            lines.append(line)
        if total_chars > max_chars:
            break

    if not lines:
        return ""

    header = (
        "Your recent activity across topic conversations in this workgroup\n"
        "(use this to answer questions about what you've been working on):\n"
    )
    return header + "\n".join(lines)


def _build_workflow_context(workgroup: Workgroup, conversation: Conversation) -> str:
    """Build workflow context string for agent prompts.

    Returns formatted string with workflow list + active state, or "" if no workflows.
    """
    from teaparty_app.services.tools import _files_for_conversation

    files = _files_for_conversation(workgroup, conversation)

    # Find workflow files
    workflows = [
        f for f in files
        if f["path"].startswith("workflows/")
        and f["path"].endswith(".md")
        and f["path"] != "workflows/README.md"
    ]
    if not workflows:
        return ""

    # Extract titles and triggers
    wf_summaries = []
    for wf in sorted(workflows, key=lambda f: f["path"]):
        content = wf.get("content") or ""
        title = wf["path"]
        trigger = ""
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("# ") and title == wf["path"]:
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
        entry = f"- {title} ({wf['path']})"
        if trigger:
            entry += f" — {trigger}"
        wf_summaries.append(entry)

    parts = ["Available workflows:\n" + "\n".join(wf_summaries)]

    # Find active workflow state
    for f in files:
        if f["path"] == "_workflow_state.md":
            state_content = (f.get("content") or "").strip()
            if state_content:
                if len(state_content) > 2000:
                    state_content = state_content[:2000] + "\n... (truncated)"
                parts.append(f"Active workflow state:\n{state_content}")
            break

    parts.append(
        "Workflow instructions: If a workflow is active, follow the current step. "
        "Use advance_workflow to update state after completing a step. "
        "Cap loops at 5 iterations. Cap sub-workflow depth at 3."
    )

    return "\n\n".join(parts)


def _build_workflow_hint(workgroup: Workgroup, conversation: Conversation) -> str:
    """Lightweight workflow hint for intent probes — just current step and status."""
    from teaparty_app.services.tools import _files_for_conversation

    if conversation.kind != "topic":
        return ""

    files = _files_for_conversation(workgroup, conversation)
    for f in files:
        if f["path"] == "_workflow_state.md":
            content = f.get("content") or ""
            current_step = ""
            status = ""
            for line in content.splitlines():
                stripped = line.strip()
                if stripped.startswith("- **Current Step**:"):
                    current_step = stripped
                elif stripped.startswith("- **Status**:"):
                    status = stripped
            if current_step or status:
                parts = [p for p in [current_step, status] if p]
                return "Active workflow: " + "; ".join(parts)
            break
    return ""


def _build_todo_context(session: Session, agent: Agent) -> str:
    """Build a summary of the agent's pending/in-progress todos for system prompt injection."""
    from teaparty_app.models import AgentTodoItem

    todos = session.exec(
        select(AgentTodoItem).where(
            AgentTodoItem.agent_id == agent.id,
            AgentTodoItem.status.in_(["pending", "in_progress"]),
        ).order_by(AgentTodoItem.created_at.asc())
    ).all()

    if not todos:
        return ""

    pending = [t for t in todos if t.status == "pending"]
    in_progress = [t for t in todos if t.status == "in_progress"]

    lines = [f"Your active todos ({len(pending)} pending, {len(in_progress)} in progress):"]
    for t in todos:
        trigger_desc = ""
        if t.trigger_type != "manual":
            trigger_desc = f" [{t.trigger_type}]"
        lines.append(f"- [{t.priority.upper()}] ({t.status}) {t.title}{trigger_desc}")

    result = "\n".join(lines)
    if len(result) > 1500:
        result = result[:1500] + "\n... (truncated)"
    return result


def _runtime_reply_system_instructions(
    agent: Agent,
    conversation: Conversation,
    role: str,
    personality_text: str,
    backstory: str,
    profile_description: str,
) -> str:
    topic_name = (conversation.name or "").strip()
    topic_key = (conversation.topic or "").strip()
    topic_label = topic_name or topic_key or "(unspecified)"
    return (
        f"You are {agent.name}, an AI teammate in a workgroup chat. "
        f"Role: {role}. "
        f"Personality: {personality_text or '(none provided)'}. "
        f"Backstory: {backstory or 'None provided'}. "
        f"Profile: {profile_description or 'None provided'}. "
        f"Conversation kind: {conversation.kind}. "
        f"Conversation topic: {topic_label}. "
        f"Conversation topic key: {topic_key or '(none provided)'}. "
        "Treat role/personality/backstory/profile as background behavioral constraints, not as script text. "
        "Use persona text as guidance; do not quote or recite it unless explicitly asked. "
        "Keep your response anchored to the current conversation topic unless the user explicitly asks to switch topics. "
        "When asked to introduce yourself, use 1-2 natural sentences with plain language: name, role, and one practical focus area. "
        "Write like a real colleague in a live conversation: natural phrasing, contractions, and context-sensitive tone. "
        "Use brief acknowledgments when appropriate, then move to substance. "
        "Be practical, accurate, and concise. "
        "Use the supplied conversation history to maintain continuity and avoid contradictions. "
        "Contribute something useful and specific, but stay conversational. "
        "You are an independent participant with your own judgments and priorities. "
        "Assume everyone can read the thread; avoid repeating what others just said unless needed for clarity. "
        "Use your long-term memories to inform your responses but do not explicitly reference having memories. "
        "Do not prefix your output with your name."
    )


def _extract_web_search_reply(response: anthropic.types.Message) -> str:
    text_parts: list[str] = []
    sources: list[tuple[str, str]] = []
    for block in response.content:
        if hasattr(block, "text"):
            text_parts.append(block.text)
            if hasattr(block, "citations") and block.citations:
                for cite in block.citations:
                    if hasattr(cite, "url") and hasattr(cite, "title"):
                        sources.append((cite.title, cite.url))
        # Also collect URLs from web_search_tool_result blocks as fallback
        if getattr(block, "type", None) == "web_search_tool_result":
            result_content = getattr(block, "content", None)
            if isinstance(result_content, list):
                for result in result_content:
                    url = getattr(result, "url", None)
                    title = getattr(result, "title", None)
                    if url and title:
                        sources.append((title, url))
    combined = " ".join(text_parts).strip()
    # Strip any model-generated Sources section to avoid duplication
    combined = re.split(r"\n\s*\*?\*?Sources\*?\*?\s*:?\s*\n", combined, maxsplit=1)[0].rstrip()
    if sources:
        seen: set[str] = set()
        unique: list[str] = []
        for title, url in sources:
            if url not in seen:
                seen.add(url)
                unique.append(f"- {title}: {url}")
        combined += "\n\nSources:\n" + "\n".join(unique)
    return combined


def _build_agent_reply_with_llm(
    session: Session,
    agent: Agent,
    conversation: Conversation,
    trigger: Message,
    style: str,
    length_rule: str,
    configured_verbosity: float,
    effective_verbosity: float,
    tool_name: str | None,
    tool_output: str | None,
    triggering_user_id: str | None = None,
    intent: str | None = None,
) -> str | None:
    if not _runtime_agent_llm_enabled():
        return None

    history_rows = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.asc())
    ).all()
    user_names, agent_names = _load_sender_name_maps(session, history_rows)
    trigger_label = _message_sender_label(trigger, agent.id, user_names, agent_names)
    trigger_kind = "human" if _is_human_post(trigger) else "agent"
    user_anchor = _latest_user_message(history_rows, before_message_id=trigger.id)
    user_anchor_label = (
        _message_sender_label(user_anchor, agent.id, user_names, agent_names)
        if user_anchor is not None
        else "(none)"
    )
    user_anchor_content = user_anchor.content if user_anchor is not None else "(none)"
    intro_turn = _is_introduction_request(user_anchor_content) or _is_introduction_request(trigger.content)
    role = _agent_role(agent)
    if not role:
        role = agent.name
    personality_text = _clean_agent_personality_text(agent)
    backstory = _agent_backstory(agent)
    profile_description = _agent_profile_description(agent)
    guardrails = _persona_guardrails(agent)
    model_name = _agent_model(agent)
    temperature = _agent_temperature(agent)
    disposition = _current_disposition(agent)
    sentiment = _agent_sentiment_state(agent)
    voice_hint = _disposition_voice_hint(disposition)
    experience = _agent_experience_context(session, agent, conversation.id)
    try:
        from teaparty_app.services.agent_learning import get_agent_memory_context

        memory_context = get_agent_memory_context(session, agent)
    except Exception:
        memory_context = ""
    system_instructions = _runtime_reply_system_instructions(
        agent=agent,
        conversation=conversation,
        role=role,
        personality_text=personality_text,
        backstory=backstory,
        profile_description=profile_description,
    )
    task_context = _load_task_context(session, conversation)
    if task_context:
        system_instructions += f"\n\nCross-group task context:\n{task_context}"
    engagement_context = _build_engagement_context(session, conversation)
    if engagement_context:
        system_instructions += f"\n\nEngagement context:\n{engagement_context}"

    cross_topic_context = _build_cross_topic_activity_context(session, agent, conversation)

    history = _conversation_history_context(session, conversation.id, agent.id, rows=history_rows)
    tool_context = ""
    if tool_name and tool_output:
        tool_context = f"\nTool hint ({tool_name}):\n{tool_output}\n"

    workgroup = session.get(Workgroup, conversation.workgroup_id)
    workflow_context = _build_workflow_context(workgroup, conversation) if workgroup else ""
    todo_context = _build_todo_context(session, agent)

    input_text = (
        f"Conversation kind: {conversation.kind}\n"
        f"Conversation topic: {conversation.topic}\n"
        f"Your identity: {agent.name}\n"
        f"Your role: {role}\n"
        f"Your personality: {personality_text or '(none provided)'}\n"
        f"Your backstory: {backstory or '(none provided)'}\n"
        f"Your profile description: {profile_description or '(none provided)'}\n"
        f"Your configured model: {model_name}\n"
        f"Your configured temperature: {temperature}\n"
        f"Your configured verbosity: {configured_verbosity}\n"
        f"Your effective verbosity (after learning adjustments): {effective_verbosity}\n"
        f"Your disposition: {json.dumps(disposition)}\n"
        f"Your sentiment: {json.dumps(sentiment)}\n"
        f"Voice guidance from disposition: {voice_hint}\n"
        f"Preferred response style: {style}\n"
        f"Response length rule: {length_rule}\n"
        f"Latest trigger type: {trigger_kind}\n"
        f"Latest trigger sender: {trigger_label}\n"
        f"Primary user anchor sender: {user_anchor_label}\n"
        f"{tool_context}"
        "Persona guardrails (treat as hard constraints):\n"
        + "\n".join(f"- {rule}" for rule in guardrails)
        + "\n\n"
        "Recent conversation history (oldest to newest):\n"
        f"{history or '- user: (no prior messages)'}\n\n"
        "Your personal experience context:\n"
        f"{experience}\n\n"
        + (f"Your long-term memories from past conversations:\n{memory_context}\n\n" if memory_context else "")
        + (f"{cross_topic_context}\n\n" if cross_topic_context else "")
        + (f"Workflow context:\n{workflow_context}\n\n" if workflow_context else "")
        + (f"{todo_context}\n\n" if todo_context else "")
        + "Primary user anchor message (treat this as the main question/request):\n"
        f"{user_anchor_content}\n\n"
        "Latest trigger message:\n"
        f"{trigger.content}\n\n"
        + (f"Your intended contribution (follow through on this point):\n{intent}\n\n" if intent else "")
        + "Output rules:\n"
        "- Speak in first person as this specific agent with a distinct point of view.\n"
        "- Keep wording and argumentative style aligned with the persona guardrails.\n"
        "- Sound like a human teammate in a live discussion, not a profile card.\n"
        "- Avoid generic positivity or encouragement unless the user explicitly asks for it.\n"
        "- Address the primary user anchor message unless a newer user message supersedes it.\n"
        "- Do not default to asking the human moderator a follow-up question; only ask when a missing fact blocks progress.\n"
        + (
            "- This is an introduction turn: keep it to 1-2 natural sentences, use plain language, "
            "and avoid repeating persona/profile text verbatim.\n"
            if intro_turn
            else ""
        )
    )

    model_candidates = _runtime_model_candidates(model_name)
    if not model_candidates:
        logger.warning("No LLM model candidates for agent %s (primary model: %s)", agent.id, model_name)
        return None

    for runtime_model in model_candidates:
        try:
            resolved = llm_client.resolve_model("reply", runtime_model)
            # web_search is Anthropic-only — only include for Claude models
            has_web_search = "web_search" in (agent.tool_names or []) and llm_client.is_anthropic_model(resolved)

            # Build system as a list of content blocks so tool instructions stand out
            system_blocks: list[dict] = [{"type": "text", "text": system_instructions}]
            if has_web_search:
                system_blocks.append({
                    "type": "text",
                    "text": (
                        "You have a web_search tool. When a claim needs verification or you need current data, "
                        "call the tool — do not generate search results or citations from memory."
                    ),
                })

            api_tools = None
            if has_web_search:
                api_tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]

            t0 = time.monotonic()
            api_kwargs: dict = {}
            if api_tools:
                api_kwargs["tools"] = api_tools
                api_kwargs["tool_choice"] = {"type": "any"}
            response = llm_client.create_message(
                model=resolved,
                max_tokens=16384,
                temperature=temperature,
                system=system_blocks,
                messages=[{"role": "user", "content": input_text}],
                **api_kwargs,
            )
            duration_ms = int((time.monotonic() - t0) * 1000)
            record_llm_usage(
                session, conversation.id, agent.id, resolved,
                response.usage.input_tokens, response.usage.output_tokens,
                "reply", duration_ms,
                triggering_user_id=triggering_user_id,
            )
            if has_web_search:
                block_types = [getattr(b, "type", "unknown") for b in response.content]
                used_search = any(t == "web_search_tool_result" for t in block_types)
                logger.info(
                    "web_search agent %s: stop_reason=%s, blocks=%s, used_search=%s",
                    agent.id, response.stop_reason, block_types, used_search,
                )
                raw_text = _extract_web_search_reply(response)
            else:
                raw_text = response.content[0].text if response.content else ""
            output = _normalize_agent_reply_text(agent, raw_text)
            if output:
                return output
            logger.warning(
                "LLM reply for agent %s normalized to empty (model=%s, raw_len=%d, raw_preview=%.120s)",
                agent.id, resolved, len(raw_text), raw_text[:120],
            )
        except Exception as exc:
            logger.warning("LLM runtime reply failed for agent %s with model %s: %s", agent.id, runtime_model, exc)
    return None


def _clean_agent_personality_text(agent: Agent) -> str:
    text = " ".join((agent.personality or "").split())
    text = re.sub(r"\buse model\s+[A-Za-z0-9._\-]+\b", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\buse\s+gpt-[A-Za-z0-9._\-]+\b", "", text, flags=re.IGNORECASE)
    text = " ".join(text.split()).strip(" .")
    return text


def _persona_guardrails(agent: Agent) -> list[str]:
    personality_text = _clean_agent_personality_text(agent).lower()
    profile_text = f"{_agent_role(agent)} {_agent_backstory(agent)} {_agent_profile_description(agent, max_chars=600)}".lower()
    combined = f"{personality_text} {profile_text}"
    rules: list[str] = []

    if any(keyword in combined for keyword in ["short sentence", "economical", "concise", "brief", "minimal"]):
        rules.append("Use short, compact sentences unless the user explicitly asks for a deep dive.")
    if "define" in combined and "term" in combined:
        rules.append("Define ambiguous technical terms before arguing from them.")
    if any(keyword in combined for keyword in ["does not hedge", "no hedge", "direct", "blunt", "impatient with imprecision"]):
        rules.append("State agreement or disagreement directly and avoid hedging language.")
    if "dry sense of humor" in combined:
        rules.append("Use dry humor sparingly and only when it supports the technical point.")

    if not rules:
        rules.append("Match the configured role, personality, and backstory exactly in tone and stance.")
    return rules


def _fallback_agent_reply(agent: Agent, conversation: Conversation, trigger: Message, tool_output: str | None) -> str:
    role = _agent_role(agent).strip()
    lowered = (trigger.content or "").lower()
    trigger_preview = " ".join((trigger.content or "").split())
    if len(trigger_preview) > 100:
        trigger_preview = trigger_preview[:100].rstrip() + "..."

    if _is_introduction_request(lowered):
        if role:
            return f"I'm {agent.name}, {role}. I'm here to keep the discussion concrete and useful."
        return f"I'm {agent.name}. I'm here to keep the discussion concrete and useful."

    if tool_output:
        snippet = " ".join(tool_output.split())
        if len(snippet) > 180:
            snippet = snippet[:180].rstrip() + "..."
        return f"Here's what I found: {snippet}"

    # For direct conversations, acknowledge the user's message rather than
    # reciting role boilerplate.  The fallback is intentionally brief so it
    # doesn't pretend to have LLM-quality answers.
    if _is_question_like(trigger.content):
        if role:
            return f"That's a good question. I'd like to think through it carefully from my perspective as {role}, but I'm having trouble formulating a full response right now. Could you try again in a moment?"
        return "That's a good question. I'd like to think through it carefully, but I'm having trouble formulating a full response right now. Could you try again in a moment?"

    if role:
        return f"I hear you. Let me think about that from my perspective as {role} and get back to you."
    return "I hear you. Let me think about that and get back to you."


def _should_use_sdk(agent: Agent) -> bool:
    """Return True if agent should use the multi-turn SDK tool loop."""
    if is_admin_agent(agent):
        return False
    allowed = set(agent.tool_names or []) - SERVER_SIDE_TOOLS
    # Exclude claude_code — it has its own dedicated loop
    allowed.discard("claude_code")
    return bool(allowed)


def _build_agent_reply_with_sdk(
    session: Session,
    agent: Agent,
    conversation: Conversation,
    trigger: Message,
    triggering_user_id: str | None = None,
    intent: str | None = None,
) -> str | None:
    """Multi-turn tool loop: LLM autonomously decides which tools to call."""
    if not _runtime_agent_llm_enabled():
        return None

    from teaparty_app.services.agent_tools import build_tool_schemas, dispatch_agent_tool

    tool_schemas = build_tool_schemas(session, agent)
    if not tool_schemas:
        return None

    # --- Assemble system prompt ---
    role = _agent_role(agent) or agent.name
    personality_text = _clean_agent_personality_text(agent)
    backstory = _agent_backstory(agent)
    profile_description = _agent_profile_description(agent)
    system_instructions = _runtime_reply_system_instructions(
        agent=agent,
        conversation=conversation,
        role=role,
        personality_text=personality_text,
        backstory=backstory,
        profile_description=profile_description,
    )

    task_context = _load_task_context(session, conversation)
    if task_context:
        system_instructions += f"\n\nCross-group task context:\n{task_context}"
    engagement_context = _build_engagement_context(session, conversation)
    if engagement_context:
        system_instructions += f"\n\nEngagement context:\n{engagement_context}"

    cross_topic_context = _build_cross_topic_activity_context(session, agent, conversation)

    # Build system as a list of content blocks so tool instructions stand out.
    system_blocks: list[dict] = [{"type": "text", "text": system_instructions}]
    system_blocks.append({
        "type": "text",
        "text": (
            "You have access to tools. Use them when appropriate to fulfill the user's request. "
            "You may call multiple tools in sequence. Always read a file before editing it. "
            "When you have enough information, respond directly without using tools."
        ),
    })

    # Add web_search as a server-side tool if the agent has it (Anthropic-only, resolved below)
    _agent_wants_web_search = "web_search" in (agent.tool_names or [])
    api_tools: list[dict] = list(tool_schemas)
    if _agent_wants_web_search:
        api_tools.append({"type": "web_search_20250305", "name": "web_search", "max_uses": 5})
        system_blocks.append({
            "type": "text",
            "text": (
                "You have a web_search tool. When a claim needs verification or you need current data, "
                "call the tool — do not generate search results or citations from memory. "
                "Never fabricate URLs or sources. Only include URLs that appear in actual search results."
            ),
        })

    # --- Assemble user prompt ---
    configured_verbosity = _agent_verbosity(agent)
    effective_verbosity = _effective_verbosity(agent)
    style, length_rule = _verbosity_style_profile(effective_verbosity)
    disposition = _current_disposition(agent)
    sentiment = _agent_sentiment_state(agent)
    voice_hint = _disposition_voice_hint(disposition)
    guardrails = _persona_guardrails(agent)

    history_rows = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.asc())
    ).all()
    user_names, agent_names = _load_sender_name_maps(session, history_rows)
    trigger_label = _message_sender_label(trigger, agent.id, user_names, agent_names)
    trigger_kind = "human" if _is_human_post(trigger) else "agent"
    user_anchor = _latest_user_message(history_rows, before_message_id=trigger.id)
    user_anchor_content = user_anchor.content if user_anchor is not None else "(none)"
    history = _conversation_history_context(session, conversation.id, agent.id, rows=history_rows)
    experience = _agent_experience_context(session, agent, conversation.id)
    try:
        from teaparty_app.services.agent_learning import get_agent_memory_context
        memory_context = get_agent_memory_context(session, agent)
    except Exception:
        memory_context = ""

    workgroup = session.get(Workgroup, conversation.workgroup_id)
    workflow_context = _build_workflow_context(workgroup, conversation) if workgroup else ""
    todo_context = _build_todo_context(session, agent)

    user_prompt = (
        f"Conversation kind: {conversation.kind}\n"
        f"Conversation topic: {conversation.topic}\n"
        f"Your identity: {agent.name}\n"
        f"Your role: {role}\n"
        f"Your personality: {personality_text or '(none provided)'}\n"
        f"Preferred response style: {style}\n"
        f"Response length rule: {length_rule}\n"
        f"Disposition: {voice_hint}\n"
        f"Latest trigger type: {trigger_kind}\n"
        f"Latest trigger sender: {trigger_label}\n"
        "Persona guardrails (treat as hard constraints):\n"
        + "\n".join(f"- {rule}" for rule in guardrails)
        + "\n\n"
        "Recent conversation history (oldest to newest):\n"
        f"{history or '- user: (no prior messages)'}\n\n"
        f"Your personal experience context:\n{experience}\n\n"
        + (f"Your long-term memories from past conversations:\n{memory_context}\n\n" if memory_context else "")
        + (f"{cross_topic_context}\n\n" if cross_topic_context else "")
        + (f"Workflow context:\n{workflow_context}\n\n" if workflow_context else "")
        + (f"{todo_context}\n\n" if todo_context else "")
        + (f"Your intended contribution (follow through on this point):\n{intent}\n\n" if intent else "")
        + f"Primary user anchor message:\n{user_anchor_content}\n\n"
        f"Latest trigger message:\n{trigger.content}\n"
    )

    # --- Multi-turn loop ---
    model_name = _agent_model(agent)
    temperature = _agent_temperature(agent)
    resolved_model = llm_client.resolve_model("reply", model_name)
    # web_search is Anthropic-only — strip it for non-Claude models
    has_web_search = _agent_wants_web_search and llm_client.is_anthropic_model(resolved_model)
    if not has_web_search and _agent_wants_web_search:
        # Remove web_search tool from api_tools for non-Anthropic providers
        api_tools = [t for t in api_tools if not t.get("type", "").startswith("web_search")]

    messages: list[dict] = [{"role": "user", "content": user_prompt}]
    max_turns = settings.agent_sdk_max_turns
    last_response = None

    for _turn in range(max_turns):
        _set_activity(conversation.id, agent.id, agent.name, "thinking")

        response = None
        try:
            t0 = time.monotonic()
            # On first turn for web_search agents, pass ONLY
            # web_search so tool_choice forces actual search.
            turn_tools = api_tools
            extra_kwargs: dict = {}
            if _turn == 0 and has_web_search:
                turn_tools = [t for t in api_tools if t.get("type", "").startswith("web_search")]
                extra_kwargs["tool_choice"] = {"type": "any"}
            response = llm_client.create_message(
                model=resolved_model,
                max_tokens=16384,
                temperature=temperature,
                system=system_blocks,
                tools=turn_tools,
                messages=messages,
                **extra_kwargs,
            )
            duration_ms = int((time.monotonic() - t0) * 1000)
            record_llm_usage(
                session, conversation.id, agent.id, resolved_model,
                response.usage.input_tokens, response.usage.output_tokens,
                "sdk_reply", duration_ms,
                triggering_user_id=triggering_user_id,
            )
        except Exception as exc:
            logger.warning("SDK loop LLM call failed for agent %s with model %s: %s", agent.id, resolved_model, exc)

        if response is None:
            break

        last_response = response

        if has_web_search:
            block_types = [getattr(b, "type", "unknown") for b in response.content]
            used_search = any(t == "web_search_tool_result" for t in block_types)
            logger.info(
                "SDK web_search agent %s turn %d: stop_reason=%s, blocks=%s, used_search=%s",
                agent.id, _turn, response.stop_reason, block_types, used_search,
            )

        # Check for tool use blocks (client-side only; server_tool_use is handled by API)
        tool_uses = [block for block in response.content if block.type == "tool_use"]

        if not tool_uses or response.stop_reason == "end_turn":
            # No client-side tools called or model decided to stop — extract text
            break

        # Append assistant message
        messages.append({"role": "assistant", "content": response.content})

        # Execute tools and collect results
        tool_results = []
        for tool_use in tool_uses:
            _set_activity(conversation.id, agent.id, agent.name, "tool", tool_use.name)
            result = dispatch_agent_tool(
                session, agent, conversation, trigger,
                tool_use.name, tool_use.input,
            )
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": result,
            })

        messages.append({"role": "user", "content": tool_results})
        # Release write lock before the next turn's LLM call.
        try:
            commit_with_retry(session)
        except Exception as exc:
            logger.warning("SDK mid-turn commit failed for agent %s: %s", agent.id, exc)

    # Extract text from the final response
    if last_response is None:
        return None

    if has_web_search:
        return _extract_web_search_reply(last_response)

    text_parts = [block.text for block in last_response.content if hasattr(block, "text")]
    return "\n".join(text_parts).strip() if text_parts else None


def build_agent_reply(
    session: Session, agent: Agent, conversation: Conversation, trigger: Message,
    triggering_user_id: str | None = None,
    intent: str | None = None,
) -> str:
    configured_verbosity = _agent_verbosity(agent)
    effective_verbosity = _effective_verbosity(agent)
    style, length_rule = _verbosity_style_profile(effective_verbosity)

    # --- SDK multi-turn tool loop (preferred for agents with tools) ---
    if _should_use_sdk(agent):
        try:
            sdk_reply = _build_agent_reply_with_sdk(
                session=session,
                agent=agent,
                conversation=conversation,
                trigger=trigger,
                triggering_user_id=triggering_user_id,
                intent=intent,
            )
            if sdk_reply:
                normalized = _normalize_agent_reply_text(agent, sdk_reply)
                if normalized:
                    return normalized
        except Exception as exc:
            logger.warning("SDK loop failed for agent %s, falling back: %s", agent.id, exc)

    # --- Legacy one-shot path (fallback or agents without tools) ---
    tool_name = _select_tool(agent, trigger.content, session=session)
    tool_output = None
    if tool_name:
        _set_activity(conversation.id, agent.id, agent.name, "tool", tool_name)
        tool_trigger = trigger
        if tool_name in FILE_RESULT_TOOL_NAMES:
            rewritten_trigger = _rewrite_file_tool_trigger(
                session=session,
                agent=agent,
                conversation=conversation,
                trigger=trigger,
                tool_name=tool_name,
                triggering_user_id=triggering_user_id,
            )
            if rewritten_trigger is not None:
                tool_trigger = rewritten_trigger
        tool_output = run_tool(tool_name, session, agent, conversation, tool_trigger)
        if tool_name in FILE_RESULT_TOOL_NAMES:
            return tool_output
        if tool_name in DIRECT_RETURN_TOOL_NAMES:
            return tool_output

    _set_activity(conversation.id, agent.id, agent.name, "composing")

    try:
        llm_reply = _build_agent_reply_with_llm(
            session=session,
            agent=agent,
            conversation=conversation,
            trigger=trigger,
            style=style,
            length_rule=length_rule,
            configured_verbosity=configured_verbosity,
            effective_verbosity=effective_verbosity,
            tool_name=tool_name,
            tool_output=tool_output,
            triggering_user_id=triggering_user_id,
            intent=intent,
        )
        if llm_reply:
            normalized = _normalize_agent_reply_text(agent, llm_reply)
            if normalized:
                return normalized
    except Exception as exc:
        logger.warning("LLM runtime reply failed for agent %s: %s", agent.id, exc)

    logger.warning(
        "Agent %s (%s) using fallback reply for trigger %.80s",
        agent.id, agent.name, (trigger.content or "")[:80],
    )
    fallback = _fallback_agent_reply(agent=agent, conversation=conversation, trigger=trigger, tool_output=tool_output)
    return _normalize_agent_reply_text(agent, fallback)


def build_admin_agent_reply(session: Session, agent: Agent, conversation: Conversation, trigger: Message) -> str:
    if trigger.sender_type != "user" or not trigger.sender_user_id:
        return "I only process admin commands from user messages."
    output = handle_admin_message(
        session=session,
        workgroup_id=conversation.workgroup_id,
        requester_user_id=trigger.sender_user_id,
        content=trigger.content,
        conversation_id=conversation.id,
    )
    return output


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

    participants = _conversation_participants(session, conversation.id)
    agent_ids = [item.agent_id for item in participants if item.agent_id]
    if not agent_ids:
        return []

    return session.exec(
        select(Agent)
        .where(Agent.id.in_(agent_ids), Agent.workgroup_id == conversation.workgroup_id)
        .order_by(Agent.created_at.asc())
    ).all()


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


def run_agent_auto_responses(session: Session, conversation: Conversation, trigger: Message) -> list[Message]:
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

    max_chain = 1 if len(candidates) == 1 else min(settings.agent_chain_max, 2 * len(candidates))
    created: list[Message] = []
    chain_trigger = trigger
    thread_anchor = trigger if trigger.sender_type == "user" else None
    chain_responded_ids: list[str] = []

    # Derive the triggering user ID for budget accounting.
    _triggering_user_id = (
        thread_anchor.sender_user_id if thread_anchor and thread_anchor.sender_user_id
        else trigger.sender_user_id
    )

    for chain_step in range(max_chain):
        blocked_agent_ids: set[str] = set()
        if len(candidates) > 1 and chain_trigger.sender_type == "agent" and chain_trigger.sender_agent_id:
            blocked_agent_ids.add(chain_trigger.sender_agent_id)

        result = _select_responder(
            session=session,
            conversation=conversation,
            trigger=chain_trigger,
            candidates=candidates,
            blocked_agent_ids=blocked_agent_ids,
            chain_step=chain_step,
            chain_responded_ids=chain_responded_ids,
            triggering_user_id=_triggering_user_id,
        )
        if not result:
            break
        selected, intent_text, urgency = result

        reply_trigger = thread_anchor or chain_trigger
        content = build_agent_reply(
            session, selected, conversation, reply_trigger,
            triggering_user_id=_triggering_user_id,
            intent=intent_text,
        )
        agent_message = Message(
            conversation_id=conversation.id,
            sender_type="agent",
            sender_agent_id=selected.id,
            content=content,
            requires_response=infer_requires_response(content),
            response_to_message_id=(thread_anchor.id if thread_anchor else chain_trigger.id),
        )
        session.add(agent_message)
        session.flush()

        _clear_activity(conversation.id, selected.id)

        try:
            _store_agent_thoughts(session, selected, agent_message, intent_text, urgency, None, chain_step)
        except Exception as exc:
            logger.warning("Failed to store agent thoughts: %s", exc)

        try:
            from teaparty_app.services.agent_learning import apply_short_term_learning

            apply_short_term_learning(session, selected, conversation, reply_trigger, agent_message)
        except Exception as exc:
            logger.warning("Short-term learning failed for agent %s: %s", selected.id, exc)

        schedule_follow_up_if_needed(session, conversation, selected, agent_message)
        chain_responded_ids.append(selected.id)
        created.append(agent_message)
        chain_trigger = agent_message

        # Commit after each chain step so the frontend sees messages
        # incrementally instead of all at once when the chain finishes.
        try:
            commit_with_retry(session)
        except Exception as exc:
            logger.warning("Mid-chain commit failed at step %d: %s", chain_step, exc)

    _clear_activity(conversation.id)
    return created


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
        if allowed_workgroup_ids and conversation.workgroup_id not in allowed_workgroup_ids:
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
    """Phase 2: evaluate poll-based triggers, then process all triggered todos."""
    if not allowed_workgroup_ids:
        return []

    from teaparty_app.models import AgentTodoItem

    now = utc_now()

    # --- Evaluate poll-based triggers ---

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

    # Topic stall: last message in conversation older than stall_minutes
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
            from datetime import timedelta as _td
            threshold = last_msg.created_at + _td(minutes=stall_minutes)
            if now >= threshold:
                todo.triggered_at = now
                todo.updated_at = now
                session.add(todo)

    session.flush()

    # --- Process all triggered todos ---
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

        # Determine conversation
        conversation = None
        if todo.conversation_id:
            conversation = session.get(Conversation, todo.conversation_id)
            if conversation and conversation.is_archived:
                conversation = None
        if not conversation:
            # Fallback: most recent non-archived topic in workgroup
            conversation = session.exec(
                select(Conversation).where(
                    Conversation.workgroup_id == todo.workgroup_id,
                    Conversation.kind == "topic",
                    Conversation.is_archived == False,  # noqa: E712
                ).order_by(Conversation.created_at.desc()).limit(1)
            ).first()
        if not conversation:
            continue

        # Build trigger description
        trigger_desc = todo.trigger_type
        if todo.trigger_type == "time":
            trigger_desc = "scheduled time reached"
        elif todo.trigger_type == "topic_stall":
            mins = (todo.trigger_config or {}).get("stall_minutes", 30)
            trigger_desc = f"conversation quiet for {mins}+ minutes"
        elif todo.trigger_type == "message_match":
            trigger_desc = "keyword match in conversation"
        elif todo.trigger_type == "file_changed":
            fp = (todo.trigger_config or {}).get("file_path", "")
            trigger_desc = f"file '{fp}' changed"
        elif todo.trigger_type == "topic_resolved":
            trigger_desc = "topic archived"
        elif todo.trigger_type == "todo_completed":
            trigger_desc = "dependent todo completed"

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
