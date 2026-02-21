"""LLM usage tracking, cost estimation, and budget enforcement."""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager

from sqlmodel import Session, select

from teaparty_app.db import commit_with_retry
from teaparty_app.models import Conversation, LLMUsageEvent, Membership

logger = logging.getLogger(__name__)


@contextmanager
def track_llm_call():
    """Context manager that yields a dict; caller sets response after API call."""
    ctx = {"start": time.monotonic(), "response": None}
    yield ctx


def record_llm_usage(
    session: Session,
    conversation_id: str,
    agent_id: str | None,
    model: str,
    input_tokens: int,
    output_tokens: int,
    purpose: str,
    duration_ms: int,
    triggering_user_id: str | None = None,
) -> None:
    """Record usage and commit immediately to release the SQLite write lock before the next LLM call."""
    try:
        event = LLMUsageEvent(
            conversation_id=conversation_id,
            agent_id=agent_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            purpose=purpose,
            duration_ms=duration_ms,
        )
        session.add(event)
        if triggering_user_id:
            cost = _estimate_cost(model, input_tokens, output_tokens)
            _increment_member_budget(session, conversation_id, triggering_user_id, cost)
        commit_with_retry(session)
    except Exception:
        logger.warning("Failed to record LLM usage for %s/%s", conversation_id, agent_id, exc_info=True)
        try:
            session.rollback()
        except Exception:
            pass


def _increment_member_budget(
    session: Session, conversation_id: str, user_id: str, cost_usd: float
) -> None:
    conversation = session.get(Conversation, conversation_id)
    if not conversation:
        return
    membership = session.exec(
        select(Membership).where(
            Membership.workgroup_id == conversation.workgroup_id,
            Membership.user_id == user_id,
        )
    ).first()
    if membership and membership.budget_limit_usd is not None:
        membership.budget_used_usd = round((membership.budget_used_usd or 0.0) + cost_usd, 6)
        session.add(membership)


def get_member_usage(session: Session, workgroup_id: str, user_id: str) -> dict:
    membership = session.exec(
        select(Membership).where(
            Membership.workgroup_id == workgroup_id,
            Membership.user_id == user_id,
        )
    ).first()
    return {
        "workgroup_id": workgroup_id,
        "user_id": user_id,
        "budget_limit_usd": membership.budget_limit_usd if membership else None,
        "budget_used_usd": membership.budget_used_usd if membership else 0.0,
    }


# Model pricing (USD per million tokens)
MODEL_PRICING = {
    "sonnet": {"input": 3.0, "output": 15.0, "context": 200_000},
    "haiku": {"input": 0.80, "output": 4.0, "context": 200_000},
    "opus": {"input": 15.0, "output": 75.0, "context": 200_000},
}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        for key in MODEL_PRICING:
            if key in model:
                pricing = MODEL_PRICING[key]
                break
        if not pricing:
            # Unknown models (Ollama, local, etc.) default to zero cost
            return 0.0
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000


def _get_context_window(model: str) -> int:
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        for key in MODEL_PRICING:
            if key in model:
                pricing = MODEL_PRICING[key]
                break
    return pricing.get("context", 0) if pricing else 0


def get_conversation_usage(session: Session, conversation_id: str) -> dict:
    rows = session.exec(
        select(LLMUsageEvent).where(LLMUsageEvent.conversation_id == conversation_id)
    ).all()
    total_input = sum(r.input_tokens for r in rows)
    total_output = sum(r.output_tokens for r in rows)
    total_duration = sum(r.duration_ms for r in rows)
    total_cost = sum(_estimate_cost(r.model, r.input_tokens, r.output_tokens) for r in rows)
    by_model: dict[str, dict] = {}
    for r in rows:
        entry = by_model.setdefault(r.model, {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "calls": 0})
        entry["input_tokens"] += r.input_tokens
        entry["output_tokens"] += r.output_tokens
        entry["cost_usd"] += _estimate_cost(r.model, r.input_tokens, r.output_tokens)
        entry["calls"] += 1
    # Find the most recent row's input tokens and resolve its context window
    last_input_tokens = 0
    context_window = 0
    if rows:
        latest = max(rows, key=lambda r: r.created_at)
        last_input_tokens = latest.input_tokens
        context_window = _get_context_window(latest.model)

    return {
        "conversation_id": conversation_id,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "total_duration_ms": total_duration,
        "estimated_cost_usd": round(total_cost, 6),
        "api_calls": len(rows),
        "by_model": by_model,
        "last_input_tokens": last_input_tokens,
        "context_window": context_window,
    }


def get_workgroup_usage(session: Session, workgroup_id: str) -> dict:
    rows = session.exec(
        select(LLMUsageEvent)
        .join(Conversation, LLMUsageEvent.conversation_id == Conversation.id)
        .where(Conversation.workgroup_id == workgroup_id)
    ).all()
    total_input = sum(r.input_tokens for r in rows)
    total_output = sum(r.output_tokens for r in rows)
    total_duration = sum(r.duration_ms for r in rows)
    total_cost = sum(_estimate_cost(r.model, r.input_tokens, r.output_tokens) for r in rows)
    by_model: dict[str, dict] = {}
    for r in rows:
        entry = by_model.setdefault(r.model, {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "calls": 0})
        entry["input_tokens"] += r.input_tokens
        entry["output_tokens"] += r.output_tokens
        entry["cost_usd"] += _estimate_cost(r.model, r.input_tokens, r.output_tokens)
        entry["calls"] += 1
    return {
        "workgroup_id": workgroup_id,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "total_duration_ms": total_duration,
        "estimated_cost_usd": round(total_cost, 6),
        "api_calls": len(rows),
        "by_model": by_model,
    }
