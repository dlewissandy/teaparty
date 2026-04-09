"""Bus listener registry for MCP Send/Reply routing.

The shared HTTP MCP server runs in the same process as the bridge.
When an agent calls Send, the handler looks up the bus listener by
agent name and calls it directly — no sockets needed.
"""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

_log = logging.getLogger('teaparty.mcp.registry')

# {agent_name: spawn_fn} where spawn_fn(member, composite, context_id) -> (session_id, worktree, result)
_spawn_fns: dict[str, Callable] = {}

# {agent_name: reply_fn} where reply_fn(context_id, session_id, message) -> None
_reply_fns: dict[str, Callable] = {}


def register_spawn_fn(agent_name: str, fn: Callable) -> None:
    """Register a spawn function for an agent's bus listener."""
    _log.info('Registered spawn_fn for %s', agent_name)
    _spawn_fns[agent_name] = fn


def register_reply_fn(agent_name: str, fn: Callable) -> None:
    """Register a reply function for an agent's bus listener."""
    _reply_fns[agent_name] = fn


def get_spawn_fn(agent_name: str) -> Callable | None:
    return _spawn_fns.get(agent_name)


def get_reply_fn(agent_name: str) -> Callable | None:
    return _reply_fns.get(agent_name)


def clear() -> None:
    """Remove all registrations."""
    _spawn_fns.clear()
    _reply_fns.clear()
