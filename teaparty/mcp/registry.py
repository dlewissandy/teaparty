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
from dataclasses import dataclass
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

# {proxy qualifier}
# Escalation ownership — the EscalationListener drives its own proxy
# invocation loop (fires, parses, DIALOG→wait→re-fire).  The bridge's
# HTTP /api/send handler auto-invokes the proxy on any new message to
# ``proxy:{qualifier}``.  When an escalation is in flight those two
# paths would race and the proxy would double-respond per human turn.
# The listener registers the qualifier here while the loop is running;
# the HTTP handler skips auto-invoke for any qualifier in this set.
_active_escalations: set[str] = set()


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


def mark_escalation_active(qualifier: str) -> None:
    """Mark a proxy qualifier as owned by an in-flight escalation.

    While marked, the bridge's HTTP handler must not auto-invoke the
    proxy for this qualifier — the EscalationListener drives the loop
    and a parallel auto-invoke would cause a double-response.
    """
    _active_escalations.add(qualifier)


def mark_escalation_done(qualifier: str) -> None:
    """Remove a proxy qualifier from the active-escalation set."""
    _active_escalations.discard(qualifier)


def is_escalation_active(qualifier: str) -> bool:
    """Return True when an escalation currently owns ``qualifier``."""
    return qualifier in _active_escalations


def session_has_active_escalation(caller_session_id: str) -> bool:
    """Return True if any escalation is in flight for ``caller_session_id``.

    The active-escalation registry stores qualifiers in the form
    ``{caller_session_id}:{escalation_id}``.  The caller session id
    prefix on that set answers the per-session question directly; no
    disk walk, no registry lookup.
    """
    if not caller_session_id:
        return False
    prefix = f'{caller_session_id}:'
    return any(q.startswith(prefix) for q in _active_escalations)


def active_escalation_qualifier(caller_session_id: str) -> str:
    """Return the in-flight escalation qualifier for ``caller_session_id``.

    There is at most one active escalation per caller at a time
    (AskQuestion is blocking), so this returns the single qualifier
    or ``''`` if none is active.  Callers use this to construct the
    proxy conversation id for click-through.
    """
    if not caller_session_id:
        return ''
    prefix = f'{caller_session_id}:'
    for q in _active_escalations:
        if q.startswith(prefix):
            return q
    return ''


@dataclass
class MCPRoutes:
    """Bundle of MCP handler routes for a launched agent.

    The MCP handler (in the bridge process) can't read per-subprocess env
    vars, so Send / CloseConversation / AskQuestion all route through an
    in-process registry keyed by agent_name. This bundle collects the
    routes an agent needs; ``launch()`` installs them before spawning
    the subprocess, giving the handler everything it needs in one place.

    Fields are optional: a leaf worker that neither dispatches nor
    closes conversations just leaves ``spawn_fn`` / ``close_fn`` unset.
    """
    spawn_fn: Callable | None = None
    close_fn: Callable | None = None
    escalation_bus_db: str = ''
    escalation_conv_id: str = ''


def register_agent_mcp_routes(agent_name: str, routes: MCPRoutes | None) -> None:
    """Install an agent's MCP routes in the in-process registry.

    Called by ``launch()`` before each agent subprocess spawns. A None
    or empty bundle is a no-op (not every launch needs routes — e.g.
    a scripted test caller, or a leaf that doesn't dispatch).
    """
    if routes is None:
        return
    if routes.spawn_fn is not None:
        register_spawn_fn(agent_name, routes.spawn_fn)
    if routes.close_fn is not None:
        register_close_fn(agent_name, routes.close_fn)
    if routes.escalation_bus_db and routes.escalation_conv_id:
        register_escalation_route(
            agent_name, routes.escalation_bus_db, routes.escalation_conv_id,
        )


def clear() -> None:
    """Remove all registrations."""
    _spawn_fns.clear()
    _reply_fns.clear()
    _close_fns.clear()
    _escalation_routes.clear()
    _active_escalations.clear()
