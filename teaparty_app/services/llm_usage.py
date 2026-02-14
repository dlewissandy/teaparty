from __future__ import annotations

import time
from contextlib import contextmanager

from sqlmodel import Session, select

from teaparty_app.models import LLMUsageEvent


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
) -> None:
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


# Model pricing (USD per million tokens)
MODEL_PRICING = {
    "claude-sonnet-4-5": {"input": 3.0, "output": 15.0},
    "claude-haiku-4-5": {"input": 0.80, "output": 4.0},
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model)
    if not pricing:
        for key in MODEL_PRICING:
            if key in model:
                pricing = MODEL_PRICING[key]
                break
        if not pricing:
            pricing = MODEL_PRICING["claude-sonnet-4-5"]
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1_000_000


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
    return {
        "conversation_id": conversation_id,
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "total_duration_ms": total_duration,
        "estimated_cost_usd": round(total_cost, 6),
        "api_calls": len(rows),
        "by_model": by_model,
    }
