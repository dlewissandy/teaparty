from __future__ import annotations

import logging
import os
import time

import httpx
from sqlmodel import Session

from teaparty_app.config import settings
from teaparty_app.models import Agent, Conversation, Message, ToolDefinition
from teaparty_app.services.llm_usage import record_llm_usage

logger = logging.getLogger(__name__)

MAX_RESPONSE_CHARS = 10_000
MAX_WEBHOOK_TIMEOUT = 120


def _get_anthropic_api_key() -> str:
    return os.getenv("ANTHROPIC_API_KEY", "").strip() or (settings.anthropic_api_key or "").strip()


def execute_custom_tool(
    tool_def: ToolDefinition,
    session: Session,
    agent: Agent,
    conversation: Conversation,
    trigger: Message,
) -> str:
    if tool_def.tool_type == "prompt":
        return _execute_prompt_tool(tool_def, trigger, session, conversation.id)
    if tool_def.tool_type == "webhook":
        return _execute_webhook_tool(tool_def, agent, conversation, trigger)
    return f"Unknown custom tool type: {tool_def.tool_type}"


def _execute_prompt_tool(
    tool_def: ToolDefinition,
    trigger: Message,
    session: Session | None = None,
    conversation_id: str | None = None,
) -> str:
    template = tool_def.prompt_template or ""
    if not template:
        return "Prompt tool has no template configured."

    prompt_text = template.replace("{{input}}", trigger.content)

    from teaparty_app.services import llm_client

    if not llm_client.llm_enabled():
        return "Custom prompt tool unavailable: no LLM provider configured."

    try:
        model = llm_client.resolve_model("cheap", "claude-haiku-4-5")
        t0 = time.monotonic()
        response = llm_client.create_message(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt_text}],
        )
        duration_ms = int((time.monotonic() - t0) * 1000)
        if session is not None and conversation_id:
            record_llm_usage(
                session, conversation_id, None, model,
                response.usage.input_tokens, response.usage.output_tokens,
                "custom_tool", duration_ms,
            )
        return response.content[0].text.strip()[:MAX_RESPONSE_CHARS]
    except Exception as exc:
        logger.warning("Prompt tool execution failed for tool %s: %s", tool_def.id, exc)
        return f"Prompt tool execution failed: {exc}"


def _execute_webhook_tool(
    tool_def: ToolDefinition,
    agent: Agent,
    conversation: Conversation,
    trigger: Message,
) -> str:
    url = tool_def.webhook_url or ""
    if not url:
        return "Webhook tool has no URL configured."

    timeout = min(tool_def.webhook_timeout_seconds or 30, MAX_WEBHOOK_TIMEOUT)
    method = (tool_def.webhook_method or "POST").upper()

    payload = {
        "tool_name": tool_def.name,
        "tool_id": tool_def.id,
        "agent_id": agent.id,
        "agent_name": agent.name,
        "conversation_id": conversation.id,
        "workgroup_id": conversation.workgroup_id,
        "trigger_content": trigger.content,
        "trigger_sender_type": trigger.sender_type,
    }

    headers = dict(tool_def.webhook_headers or {})
    headers["X-TeaParty-Tool-Id"] = tool_def.id

    try:
        with httpx.Client(timeout=timeout, follow_redirects=False) as client:
            if method == "GET":
                resp = client.get(url, params=payload, headers=headers)
            else:
                resp = client.post(url, json=payload, headers=headers)

        resp.raise_for_status()

        try:
            data = resp.json()
            if isinstance(data, dict) and "result" in data:
                return str(data["result"])[:MAX_RESPONSE_CHARS]
        except Exception:
            pass

        return resp.text[:MAX_RESPONSE_CHARS]

    except httpx.TimeoutException:
        return f"Webhook tool timed out after {timeout}s."
    except Exception as exc:
        logger.warning("Webhook tool execution failed for tool %s: %s", tool_def.id, exc)
        return f"Webhook tool execution failed: {exc}"
