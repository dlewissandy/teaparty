"""Agent learning service: short-term signals and long-term memory synthesis."""

from __future__ import annotations

import json
import logging
import re
import time

from sqlmodel import Session, select

from teaparty_app.models import (
    Agent,
    AgentMemory,
    Conversation,
    Message,
    utc_now,
)
from teaparty_app.services.llm_usage import record_llm_usage

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Eligibility guard
# ---------------------------------------------------------------------------

def is_learning_eligible(conversation: Conversation) -> bool:
    """Return False for conversations that should not produce learning signals."""
    topic = (conversation.topic or "").strip()
    if topic.startswith("task:") or topic.startswith("task-mirror:") or topic.startswith("engagement:"):
        return False
    if conversation.kind in ("activity", "admin", "engagement"):
        return False
    return True


# ---------------------------------------------------------------------------
# Long-term memory synthesis (called on topic archival)
# ---------------------------------------------------------------------------

def _build_transcript(messages: list[Message], max_chars: int = 8000) -> str:
    """Build a truncated transcript preserving beginning and end."""
    lines: list[str] = []
    for msg in messages:
        sender = msg.sender_type
        if msg.sender_agent_id:
            sender = f"agent:{msg.sender_agent_id}"
        elif msg.sender_user_id:
            sender = f"user:{msg.sender_user_id}"
        content = " ".join((msg.content or "").split())
        if len(content) > 300:
            content = content[:300] + "..."
        lines.append(f"[{sender}] {content}")

    full = "\n".join(lines)
    if len(full) <= max_chars:
        return full

    # Keep beginning + end
    half = max_chars // 2
    return full[:half] + "\n...[truncated]...\n" + full[-half:]


def _runtime_model_candidates() -> list[str]:
    from teaparty_app.config import settings

    override = settings.llm_default_model.strip()
    if override:
        return [override]
    candidates: list[str] = []
    for model in [settings.admin_agent_model, "claude-sonnet-4-5", "claude-haiku-4-5"]:
        normalized = (model or "").strip()
        if normalized and normalized not in candidates:
            candidates.append(normalized)
    return candidates


def synthesize_long_term_memories(
    session: Session,
    conversation: Conversation,
) -> dict[str, int]:
    """Synthesize long-term memories from a conversation being archived.

    Returns a dict mapping agent_id -> number of memories created.
    """
    if not is_learning_eligible(conversation):
        return {}

    messages = session.exec(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.asc())
    ).all()

    if len(messages) < 3:
        return {}

    # Identify agents who sent messages
    agent_ids = {
        msg.sender_agent_id
        for msg in messages
        if msg.sender_type == "agent" and msg.sender_agent_id
    }
    if not agent_ids:
        return {}

    agents = session.exec(select(Agent).where(Agent.id.in_(agent_ids))).all()
    agent_map = {a.id: a for a in agents}
    if not agent_map:
        return {}

    transcript = _build_transcript(messages)

    # Load existing memories for dedup guidance
    existing_by_agent: dict[str, list[str]] = {}
    for agent_id in agent_map:
        existing = session.exec(
            select(AgentMemory)
            .where(AgentMemory.agent_id == agent_id)
            .order_by(AgentMemory.created_at.desc())
            .limit(20)
        ).all()
        existing_by_agent[agent_id] = [m.content for m in existing]

    agent_info = {
        aid: {
            "name": a.name,
            "role": (a.role or a.description or "").strip()[:200],
            "existing_memories": existing_by_agent.get(aid, [])[:10],
        }
        for aid, a in agent_map.items()
    }

    system_prompt = (
        "You analyze conversation transcripts and extract durable memories for AI agents. "
        "Output strict JSON only. The JSON must be an object keyed by agent_id. "
        "Each value is an array of memory objects with keys: type (one of: insight, correction, pattern, domain_knowledge), "
        "content (concrete memory text, max 200 chars), source (brief source summary, max 100 chars), confidence (0.0 to 1.0). "
        "Extract only genuinely useful learnings. Avoid generic observations. "
        "Do not duplicate existing memories listed below. Max 5 memories per agent."
    )

    input_text = (
        f"Conversation topic: {conversation.topic}\n"
        f"Conversation name: {conversation.name}\n\n"
        f"Agents in conversation:\n{json.dumps(agent_info, indent=2)}\n\n"
        f"Transcript:\n{transcript}\n\n"
        "Extract durable memories for each agent. Return JSON only."
    )

    try:
        from teaparty_app.services import llm_client

        raw = ""
        for model in _runtime_model_candidates():
            try:
                resolved = llm_client.resolve_model("cheap", model)
                t0 = time.monotonic()
                response = llm_client.create_message(
                    model=resolved,
                    max_tokens=2048,
                    temperature=0.3,
                    system=system_prompt,
                    messages=[{"role": "user", "content": input_text}],
                )
                duration_ms = int((time.monotonic() - t0) * 1000)
                record_llm_usage(
                    session, conversation.id, None, resolved,
                    response.usage.input_tokens, response.usage.output_tokens,
                    "memory_synthesis", duration_ms,
                )
                raw = response.content[0].text.strip()
                if raw:
                    break
            except Exception as exc:
                logger.warning("Memory synthesis LLM call failed with model %s: %s", model, exc)

        if not raw:
            return {}

        parsed = _parse_json_response(raw)
        if not isinstance(parsed, dict):
            logger.warning("Memory synthesis returned non-dict: %s", raw[:200])
            return {}

        counts: dict[str, int] = {}
        now = utc_now()

        for agent_id, memories_raw in parsed.items():
            if agent_id not in agent_map:
                continue
            if not isinstance(memories_raw, list):
                continue

            created = 0
            for mem in memories_raw[:5]:  # Cap at 5 per agent
                if not isinstance(mem, dict):
                    continue
                memory_type = str(mem.get("type", "insight")).strip()
                if memory_type not in ("insight", "correction", "pattern", "domain_knowledge"):
                    memory_type = "insight"
                content = str(mem.get("content", "")).strip()
                if not content:
                    continue
                content = content[:200]
                source = str(mem.get("source", "")).strip()[:100]
                confidence = min(1.0, max(0.0, float(mem.get("confidence", 0.7))))

                session.add(
                    AgentMemory(
                        agent_id=agent_id,
                        conversation_id=conversation.id,
                        memory_type=memory_type,
                        content=content,
                        source_summary=source,
                        confidence=confidence,
                        created_at=now,
                    )
                )
                created += 1

            if created:
                counts[agent_id] = created

        return counts

    except Exception as exc:
        logger.warning("Memory synthesis failed: %s", exc)
        return {}


def _parse_json_response(text: str) -> dict | None:
    """Extract a JSON object from an LLM response."""
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
    if match:
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass
    return None


# ---------------------------------------------------------------------------
# Memory context for prompt injection
# ---------------------------------------------------------------------------

def get_agent_memory_context(
    session: Session,
    agent: Agent,
    max_memories: int = 10,
    max_chars: int = 1500,
) -> str:
    """Format stored memories for inclusion in agent prompts."""
    memories = session.exec(
        select(AgentMemory)
        .where(AgentMemory.agent_id == agent.id)
        .order_by(AgentMemory.confidence.desc(), AgentMemory.created_at.desc())
        .limit(max_memories)
    ).all()

    if not memories:
        return ""

    lines: list[str] = []
    total_chars = 0
    for mem in memories:
        line = f"- [{mem.memory_type}] {mem.content}"
        if total_chars + len(line) > max_chars:
            break
        lines.append(line)
        total_chars += len(line) + 1  # +1 for newline

    if not lines:
        return ""

    return "Long-term memories from past conversations:\n" + "\n".join(lines)
