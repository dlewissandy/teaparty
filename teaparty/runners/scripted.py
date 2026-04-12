"""Scripted LLM caller for tests.

A scripted caller plays pre-defined stream events for each agent,
simulating claude output without running a real subprocess. Used by
integration tests to exercise the full dispatch pipeline (spawn_fn,
bus writes, resume chain, CloseConversation) without requiring the
claude binary.

Usage:
    def coord_script(message):
        if 'dispatch' in message:
            return [text_event("Starting work..."),
                    tool_use_event("Send", {"member": "worker"})]
        return [text_event("RESULT: done")]

    scripts = {
        'coordinator': coord_script,
        'worker': {'work': [text_event("done")]},
    }
    caller = make_scripted_caller(scripts)
    session = AgentSession(..., llm_caller=caller)
"""
from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from typing import Any, Callable

from teaparty.runners.claude import ClaudeResult


# ── Stream event builders ──────────────────────────────────────────────────

def text_event(text: str) -> dict:
    """Build an assistant text event."""
    return {
        'type': 'assistant',
        'message': {'content': [
            {'type': 'text', 'text': text},
        ]},
    }


def thinking_event(text: str) -> dict:
    """Build an assistant thinking event."""
    return {
        'type': 'assistant',
        'message': {'content': [
            {'type': 'thinking', 'thinking': text},
        ]},
    }


def tool_use_event(name: str, input: dict, tool_id: str | None = None) -> dict:
    """Build an assistant tool_use event."""
    return {
        'type': 'assistant',
        'message': {'content': [
            {'type': 'tool_use',
             'id': tool_id or f'tu_{uuid.uuid4().hex[:8]}',
             'name': name,
             'input': input},
        ]},
    }


def cost_event(cost_usd: float = 0.001, duration_ms: int = 100) -> dict:
    """Build a result event with cost data."""
    return {
        'type': 'result',
        'total_cost_usd': cost_usd,
        'duration_ms': duration_ms,
        'input_tokens': 100,
        'output_tokens': 50,
    }


# ── Tool-use routing ───────────────────────────────────────────────────────

async def _invoke_tool_uses(events: list[dict], *, agent_name: str,
                            session_id: str) -> None:
    """Invoke MCP tool handlers for Send/CloseConversation tool_use events.

    In production, real claude emits tool_use events and the claude
    runtime calls the corresponding MCP tool over HTTP. In scripted
    mode we call the in-process handlers directly, setting the same
    contextvars the MCP server's ASGI middleware sets per request.
    """
    from teaparty.mcp.registry import (
        current_agent_name, current_session_id, get_spawn_fn, get_close_fn,
    )

    agent_tok = current_agent_name.set(agent_name)
    session_tok = current_session_id.set(session_id)
    try:
        for ev in events:
            if ev.get('type') != 'assistant':
                continue
            for block in ev.get('message', {}).get('content', []):
                if block.get('type') != 'tool_use':
                    continue
                name = block.get('name', '')
                inp = block.get('input', {}) or {}
                if name.endswith('Send'):
                    spawn_fn = get_spawn_fn(agent_name)
                    if spawn_fn is None:
                        continue
                    member = inp.get('member', '')
                    message = inp.get('message', '')
                    context_id = inp.get('context_id', '') or f'ctx_{uuid.uuid4().hex[:8]}'
                    await spawn_fn(member, message, context_id)
                elif name.endswith('CloseConversation'):
                    close_fn = get_close_fn(agent_name)
                    if close_fn is None:
                        continue
                    conv_id = inp.get('conversation_id', '')
                    await close_fn(conv_id)
    finally:
        current_agent_name.reset(agent_tok)
        current_session_id.reset(session_tok)


# ── The scripted caller factory ────────────────────────────────────────────

Script = dict | Callable[[str], list[dict]]


def make_scripted_caller(scripts: dict[str, Script]) -> Callable:
    """Create an llm_caller that plays scripted responses per agent.

    scripts is a dict keyed by agent_name. Each value is either:
    - A callable: called with the prompt message, returns stream events
    - A dict: keyed by substring, value is a list of stream events

    For dict scripts, lookup is first-substring-match on keys.
    For callable scripts, the callable owns its own state (useful for
    stateful coordinators that need to track which replies they've seen).
    """
    async def caller(**kwargs) -> ClaudeResult:
        agent_name = kwargs.get('agent_name', '')
        message = kwargs.get('message', '')
        on_stream_event = kwargs.get('on_stream_event')
        stream_file = kwargs.get('stream_file', '')

        script = scripts.get(agent_name)
        if script is None:
            raise RuntimeError(
                f'scripted_caller: no script for agent {agent_name!r}')

        if callable(script):
            result = script(message)
            if inspect.isawaitable(result):
                result = await result
            events = result
        else:
            # Dict script: substring match
            events = []
            for key, resp in script.items():
                if key in message:
                    events = resp
                    break
            if not events:
                raise RuntimeError(
                    f'scripted_caller: no script match for agent '
                    f'{agent_name!r}, message: {message[:100]!r}')

        if on_stream_event:
            for ev in events:
                on_stream_event(ev)

        # Route tool_use events through the real MCP tool handlers so
        # scripted dispatch exercises spawn_fn, the conversation map,
        # slot limits, and the resume chain — same codepath as production.
        await _invoke_tool_uses(
            events, agent_name=agent_name,
            session_id=kwargs.get('session_id', ''),
        )

        if stream_file:
            try:
                with open(stream_file, 'a') as f:
                    for ev in events:
                        f.write(json.dumps(ev) + '\n')
            except OSError:
                pass

        return ClaudeResult(
            exit_code=0,
            session_id=f'scripted-{agent_name}-{uuid.uuid4().hex[:8]}',
        )

    return caller
