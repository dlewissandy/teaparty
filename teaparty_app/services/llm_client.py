"""Thin LLM abstraction: routes to Anthropic SDK or LiteLLM based on model.

Call sites pass Anthropic-format inputs. When the resolved model is a Claude model
with an API key available, the Anthropic SDK is used directly (preserving server-side
tools like web_search). For all other providers, LiteLLM handles the translation.

Response objects use SimpleNamespace so existing attribute access
(block.type, block.text, block.name, block.input, block.id) works unchanged.
"""

from __future__ import annotations

import logging
import os
import uuid
from types import SimpleNamespace

import anthropic
import litellm

from teaparty_app.config import settings

logger = logging.getLogger(__name__)

# Suppress litellm's noisy logging
litellm.suppress_debug_info = True
logging.getLogger("LiteLLM").setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------

_ANTHROPIC_PREFIXES = ("claude-",)


def is_anthropic_model(model: str) -> bool:
    """Return True if the model string refers to a Claude/Anthropic model."""
    m = model.strip().lower()
    return any(m.startswith(p) for p in _ANTHROPIC_PREFIXES)


def resolve_model(purpose: str = "reply", explicit_model: str = "") -> str:
    """Pick the model string based on config overrides and purpose.

    Purpose:
        "reply"  — agent replies, file rewrites, claude_code
        "cheap"  — intent probes, selectors, file search, workflow matching, custom tools
        "admin"  — admin workspace SDK loop

    llm_default_model is the universal kill switch — when set, ALL purposes route
    through it (unless llm_cheap_model provides a more specific override for "cheap").
    """
    override = settings.llm_default_model.strip()
    cheap = settings.llm_cheap_model.strip()

    if explicit_model and explicit_model.strip():
        # "cheap" purpose: prefer llm_cheap_model, then llm_default_model, then explicit
        if purpose == "cheap":
            if cheap:
                return cheap
            if override:
                return override
            return explicit_model.strip()
        # "reply" / "admin": prefer llm_default_model, then explicit
        if override:
            return override
        return explicit_model.strip()

    # No explicit model — use config chain
    if purpose == "cheap":
        if cheap:
            return cheap
        if override:
            return override
        return settings.intent_probe_model or "claude-haiku-4-5"

    if purpose == "admin":
        if override:
            return override
        return settings.admin_agent_model or "claude-sonnet-4-5"

    # purpose == "reply"
    if override:
        return override
    return settings.admin_agent_model or "claude-sonnet-4-5"


def llm_enabled() -> bool:
    """Return True if any LLM provider is configured and available."""
    if os.getenv("ANTHROPIC_API_KEY", "").strip():
        return True
    if (settings.anthropic_api_key or "").strip():
        return True
    if settings.llm_default_model.strip():
        return True
    return False


# ---------------------------------------------------------------------------
# Core API — drop-in replacement for client.messages.create()
# ---------------------------------------------------------------------------


def create_message(
    *,
    model: str,
    messages: list[dict],
    system: str | list | None = None,
    tools: list[dict] | None = None,
    tool_choice: dict | None = None,
    temperature: float | None = None,
    max_tokens: int = 4096,
) -> SimpleNamespace:
    """Create a chat completion.

    Accepts Anthropic-format inputs. Returns an Anthropic-compatible response
    with .content (list of blocks), .stop_reason, and .usage.
    """
    if is_anthropic_model(model) and _has_anthropic_key():
        return _call_anthropic(
            model=model,
            messages=messages,
            system=system,
            tools=tools,
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    return _call_litellm(
        model=model,
        messages=messages,
        system=system,
        tools=tools,
        tool_choice=tool_choice,
        temperature=temperature,
        max_tokens=max_tokens,
    )


# ---------------------------------------------------------------------------
# Anthropic passthrough (full compatibility)
# ---------------------------------------------------------------------------


def _has_anthropic_key() -> bool:
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if key:
        return True
    return bool((settings.anthropic_api_key or "").strip())


def _get_anthropic_client() -> anthropic.Anthropic:
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip() or (settings.anthropic_api_key or "").strip()
    return anthropic.Anthropic(api_key=api_key)


def _call_anthropic(
    *,
    model: str,
    messages: list[dict],
    system: str | list | None = None,
    tools: list[dict] | None = None,
    tool_choice: dict | None = None,
    temperature: float | None = None,
    max_tokens: int = 4096,
) -> anthropic.types.Message:
    """Call the Anthropic SDK directly. Returns the native response object."""
    client = _get_anthropic_client()
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if system is not None:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools
    if tool_choice:
        kwargs["tool_choice"] = tool_choice
    if temperature is not None:
        kwargs["temperature"] = temperature
    return client.messages.create(**kwargs)


# ---------------------------------------------------------------------------
# LiteLLM path (Ollama, OpenAI, etc.)
# ---------------------------------------------------------------------------


def _call_litellm(
    *,
    model: str,
    messages: list[dict],
    system: str | list | None = None,
    tools: list[dict] | None = None,
    tool_choice: dict | None = None,
    temperature: float | None = None,
    max_tokens: int = 4096,
) -> SimpleNamespace:
    """Call LiteLLM and convert the response to Anthropic-compatible format."""
    openai_messages = _messages_to_openai(messages, system)

    # Filter out server-side tools (web_search etc.) — they're Anthropic-only
    openai_tools = None
    if tools:
        converted = _tools_to_openai(tools)
        if converted:
            openai_tools = converted

    kwargs: dict = {
        "model": model,
        "messages": openai_messages,
        "max_tokens": max_tokens,
    }

    # Set Ollama base URL if this is an Ollama model
    if model.startswith("ollama/") or model.startswith("ollama_chat/"):
        kwargs["api_base"] = settings.ollama_base_url

    if openai_tools:
        kwargs["tools"] = openai_tools
        if tool_choice:
            kwargs["tool_choice"] = _tool_choice_to_openai(tool_choice)
    if temperature is not None:
        kwargs["temperature"] = temperature

    response = litellm.completion(**kwargs)
    return _response_to_anthropic(response)


# ---------------------------------------------------------------------------
# Format conversion: Anthropic → OpenAI
# ---------------------------------------------------------------------------


def _tools_to_openai(tools: list[dict]) -> list[dict]:
    """Convert Anthropic tool schemas to OpenAI function-calling format.

    Filters out server-side tools (like web_search_20250305) that have no
    equivalent in other providers.
    """
    result = []
    for tool in tools:
        # Skip server-side tools
        if tool.get("type", "").startswith("web_search"):
            continue
        name = tool.get("name", "")
        if not name:
            continue
        parameters = tool.get("input_schema", {})
        result.append({
            "type": "function",
            "function": {
                "name": name,
                "description": tool.get("description", ""),
                "parameters": parameters,
            },
        })
    return result


def _tool_choice_to_openai(tool_choice: dict) -> str | dict:
    """Convert Anthropic tool_choice to OpenAI format."""
    tc_type = tool_choice.get("type", "auto")
    if tc_type == "any":
        return "required"
    if tc_type == "auto":
        return "auto"
    if tc_type == "none":
        return "none"
    if tc_type == "tool":
        return {"type": "function", "function": {"name": tool_choice.get("name", "")}}
    return "auto"


def _messages_to_openai(messages: list[dict], system: str | list | None = None) -> list[dict]:
    """Convert Anthropic-format messages to OpenAI format.

    Handles:
    - System prompt (string or list of content blocks)
    - Content blocks (text, tool_use, tool_result)
    - String content
    """
    result: list[dict] = []

    # System message
    if system:
        if isinstance(system, str):
            result.append({"role": "system", "content": system})
        elif isinstance(system, list):
            # List of content blocks — extract text
            texts = []
            for block in system:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", ""))
                elif isinstance(block, str):
                    texts.append(block)
            if texts:
                result.append({"role": "system", "content": "\n\n".join(texts)})

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content")

        if isinstance(content, str):
            result.append({"role": role, "content": content})
            continue

        if isinstance(content, list):
            if role == "assistant":
                # Assistant message with content blocks — may contain tool_use
                text_parts = []
                tool_calls = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            tool_calls.append({
                                "id": block.get("id", str(uuid.uuid4())),
                                "type": "function",
                                "function": {
                                    "name": block.get("name", ""),
                                    "arguments": _json_dumps(block.get("input", {})),
                                },
                            })
                    elif hasattr(block, "type"):
                        # Anthropic SDK response objects
                        if block.type == "text":
                            text_parts.append(block.text)
                        elif block.type == "tool_use":
                            tool_calls.append({
                                "id": block.id,
                                "type": "function",
                                "function": {
                                    "name": block.name,
                                    "arguments": _json_dumps(block.input),
                                },
                            })

                msg_dict: dict = {"role": "assistant"}
                if text_parts:
                    msg_dict["content"] = "\n".join(text_parts)
                if tool_calls:
                    msg_dict["tool_calls"] = tool_calls
                    if "content" not in msg_dict:
                        msg_dict["content"] = ""
                result.append(msg_dict)

            elif role == "user":
                # User message with content blocks — may contain tool_result
                text_parts = []
                tool_results = []
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "tool_result":
                            tool_results.append(block)
                        elif block.get("type") == "text":
                            text_parts.append(block.get("text", ""))
                        else:
                            text_parts.append(str(block))
                    elif isinstance(block, str):
                        text_parts.append(block)

                if tool_results:
                    for tr in tool_results:
                        result.append({
                            "role": "tool",
                            "tool_call_id": tr.get("tool_use_id", ""),
                            "content": str(tr.get("content", "")),
                        })
                if text_parts:
                    result.append({"role": "user", "content": "\n".join(text_parts)})
            else:
                # Unknown role with list content
                texts = []
                for block in content:
                    if isinstance(block, dict) and "text" in block:
                        texts.append(block["text"])
                    elif isinstance(block, str):
                        texts.append(block)
                if texts:
                    result.append({"role": role, "content": "\n".join(texts)})
        else:
            result.append({"role": role, "content": str(content) if content else ""})

    return result


def _json_dumps(obj: object) -> str:
    import json
    if isinstance(obj, str):
        return obj
    return json.dumps(obj)


# ---------------------------------------------------------------------------
# Format conversion: OpenAI response → Anthropic-compatible
# ---------------------------------------------------------------------------


def _response_to_anthropic(response) -> SimpleNamespace:
    """Convert a LiteLLM/OpenAI response to Anthropic-compatible SimpleNamespace."""
    choice = response.choices[0] if response.choices else None
    message = choice.message if choice else None

    content_blocks = []

    if message:
        # Text content
        if message.content:
            content_blocks.append(SimpleNamespace(
                type="text",
                text=message.content,
            ))

        # Tool calls
        if message.tool_calls:
            import json
            for tc in message.tool_calls:
                try:
                    input_data = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, AttributeError):
                    input_data = {}
                content_blocks.append(SimpleNamespace(
                    type="tool_use",
                    id=tc.id or str(uuid.uuid4()),
                    name=tc.function.name,
                    input=input_data,
                ))

    if not content_blocks:
        content_blocks.append(SimpleNamespace(type="text", text=""))

    # Map finish_reason to Anthropic stop_reason
    finish_reason = choice.finish_reason if choice else "end_turn"
    if finish_reason == "stop":
        stop_reason = "end_turn"
    elif finish_reason == "tool_calls":
        stop_reason = "tool_use"
    elif finish_reason == "length":
        stop_reason = "max_tokens"
    else:
        stop_reason = "end_turn"

    usage = SimpleNamespace(
        input_tokens=getattr(response.usage, "prompt_tokens", 0) or 0,
        output_tokens=getattr(response.usage, "completion_tokens", 0) or 0,
    )

    return SimpleNamespace(
        content=content_blocks,
        stop_reason=stop_reason,
        usage=usage,
    )
