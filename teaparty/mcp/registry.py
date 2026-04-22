"""Bus listener registry for MCP Send/Reply routing.

The shared HTTP MCP server runs in the same process as the bridge.
When an agent calls Send, the handler looks up the bus listener by
agent name and calls it directly — no sockets needed.

Agent scope is passed per-request via contextvars (set by the ASGI
middleware, read by the tool handlers).
"""
from __future__ import annotations

import contextvars
import logging
from typing import Any, Awaitable, Callable

_log = logging.getLogger('teaparty.mcp.registry')

# Per-request context: which agent is making this MCP call.
# Set by the ASGI filtering middleware, read by Send/Reply handlers.
current_agent_name: contextvars.ContextVar[str] = contextvars.ContextVar(
    'current_agent_name', default='',
)
current_session_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    'current_session_id', default='',
)

# {agent_name: spawn_fn}
# spawn_fn(member, composite, context_id) -> (session_id, worktree, result)
_spawn_fns: dict[str, Callable] = {}

# {agent_name: reply_fn}
# reply_fn(context_id, session_id, message) -> None
_reply_fns: dict[str, Callable] = {}

# {agent_name: close_fn}
# close_fn(conversation_id) -> None
_close_fns: dict[str, Callable] = {}

# {agent_name: (bus_db_path, conv_id)}
# Escalation routing — the MCP tool in-process reads this to find the
# EscalationListener's bus conversation for the calling agent.  Set by
# the AgentSession at _ensure_bus_listener time; read by the AskQuestion
# tool via current_agent_name contextvar.
_escalation_routes: dict[str, tuple[str, str]] = {}


def register_spawn_fn(agent_name: str, fn: Callable) -> None:
    """Register a spawn function for an agent's bus listener."""
    _log.info('Registered spawn_fn for %s', agent_name)
    _spawn_fns[agent_name] = fn


def register_reply_fn(agent_name: str, fn: Callable) -> None:
    """Register a reply function for an agent's bus listener."""
    _log.info('Registered reply_fn for %s', agent_name)
    _reply_fns[agent_name] = fn


def get_spawn_fn(agent_name: str = '') -> Callable | None:
    """Get the spawn function for an agent. Defaults to current_agent_name."""
    name = agent_name or current_agent_name.get('')
    return _spawn_fns.get(name)


def get_reply_fn(agent_name: str = '') -> Callable | None:
    """Get the reply function for an agent. Defaults to current_agent_name."""
    name = agent_name or current_agent_name.get('')
    return _reply_fns.get(name)


def register_close_fn(agent_name: str, fn: Callable) -> None:
    """Register a close function for an agent's dispatch conversations."""
    _log.info('Registered close_fn for %s', agent_name)
    _close_fns[agent_name] = fn


def get_close_fn(agent_name: str = '') -> Callable | None:
    """Get the close function for an agent. Defaults to current_agent_name."""
    name = agent_name or current_agent_name.get('')
    return _close_fns.get(name)


def register_escalation_route(
    agent_name: str, bus_db_path: str, conv_id: str,
) -> None:
    """Register the AskQuestion bus conversation for an agent's MCP calls.

    The in-process MCP tool handler looks this up via ``current_agent_name``
    to locate the EscalationListener's bus.  Env vars don't work here —
    the MCP server runs in the bridge process, not in the agent's
    subprocess, so the tool handler can't read per-subprocess environment.
    """
    _log.info('Registered escalation route for %s: conv=%s', agent_name, conv_id)
    _escalation_routes[agent_name] = (bus_db_path, conv_id)


def get_escalation_route(agent_name: str = '') -> tuple[str, str] | None:
    """Return (bus_db_path, conv_id) for an agent's AskQuestion, or None."""
    name = agent_name or current_agent_name.get('')
    return _escalation_routes.get(name)


def clear() -> None:
    """Remove all registrations."""
    _spawn_fns.clear()
    _reply_fns.clear()
    _close_fns.clear()
    _escalation_routes.clear()
