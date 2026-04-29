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
# The caller's bus conversation_id.  Set by the MCP middleware from the
# URL's ``?conv=`` query param (which ``launch()`` writes at spawn time
# from the caller's own conv_id).  Read by every spawn_fn that needs to
# stamp ``parent_conversation_id`` on a new dispatch row — the caller's
# conv_id is the parent.
#
# This is the single source of truth for "what conv_id is making this
# MCP call?"  Before this existed, three different sites (chat tier,
# CfA engine, escalation listener) independently derived the caller's
# conv_id from ``session.id`` — and at least one was always wrong for
# some tier (job leads ended up parented to ``dispatch:{sid}`` instead
# of ``job:{slug}:{sid}`` and their children's blades never rendered).
# Derivation is the bug.  Propagation — one write at launch, one read
# at spawn — is the fix.
current_conversation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    'current_conversation_id', default='',
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

# {agent_name: AskQuestionRunner}
# The MCP AskQuestion tool handler looks up the caller's runner here.
# Same-process direct call — no bus ping-pong.  Set by the agent
# session at boot (engine.py / teams/session.py); read via
# ``current_agent_name`` contextvar.
_ask_question_runners: dict[str, Any] = {}

# {agent_name: bus_db_path}
# The Delegate MCP tool checks an open-thread precondition by walking
# the caller's bus.  The bus path is registered with the agent's MCP
# routes at launch time (see ``MCPRoutes.bus_db_path``); the Delegate
# handler reads it via ``get_bus_db_path`` keyed by ``current_agent_name``.
# Empty when the launch context did not install a bus (chat-tier
# bootstrap, scripted tests) — Delegate skips the precondition in that
# case, matching Send's "no enforcement without a registered authority."
_bus_db_paths: dict[str, str] = {}

# {agent_name: BusDispatcher}
# The Send MCP tool calls ``dispatcher.authorize(sender, recipient)``
# before invoking ``spawn_fn``.  This is the single enforcement point that
# makes routing correctness independent of agent-definition trust: an agent
# whose prompt is broken or hostile cannot reach a recipient outside its
# permitted set, because Send refuses the post before it reaches the bus.
# Both tiers register the same dispatcher for every agent they launch —
# the per-session routing table is shared across the whole subtree, so an
# arbitrarily nested team structure all enforces against one bundle.
#
# Routing tables key directly on agent names; there is no parallel
# scoped-id namespace and no translation map.  An agent's name is its
# identity.
_dispatchers: dict[str, Any] = {}

# {proxy qualifier}
# Escalation ownership — ``AskQuestionRunner.run`` drives its own
# proxy invocation loop (fires, parses, DIALOG→wait→re-fire).  The
# bridge's HTTP /api/send handler auto-invokes the proxy on any new
# message to ``proxy:{qualifier}``.  When an escalation is in flight
# those two paths would race and the proxy would double-respond per
# human turn.  The runner registers the qualifier here while the loop
# is running; the HTTP handler skips auto-invoke for any qualifier in
# this set.
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


def register_ask_question_runner(agent_name: str, runner: Any) -> None:
    """Register the AskQuestion runner for an agent's MCP calls.

    The in-process MCP tool handler looks this up via
    ``current_agent_name`` and calls ``runner.run(question, context)``
    directly — no bus hop.  Env vars don't work here because the MCP
    server runs in the bridge process, not in the agent's subprocess.
    """
    _log.info('Registered AskQuestionRunner for %s', agent_name)
    _ask_question_runners[agent_name] = runner


def get_ask_question_runner(agent_name: str = '') -> Any | None:
    """Return the AskQuestionRunner for an agent, or None."""
    name = agent_name or current_agent_name.get('')
    return _ask_question_runners.get(name)


def register_dispatcher(agent_name: str, dispatcher: Any) -> None:
    """Register the BusDispatcher the Send tool consults for ``agent_name``."""
    _log.info('Registered BusDispatcher for %s', agent_name)
    _dispatchers[agent_name] = dispatcher


def get_dispatcher(agent_name: str = '') -> Any | None:
    """Return the BusDispatcher for an agent, or None for no enforcement."""
    name = agent_name or current_agent_name.get('')
    return _dispatchers.get(name)


def register_bus_db_path(agent_name: str, bus_db_path: str) -> None:
    """Register the bus DB path for an agent's MCP calls (issue #423).

    The Delegate handler queries this for its open-thread precondition
    check.  Set at launch time via ``MCPRoutes.bus_db_path``.
    """
    if not bus_db_path:
        return
    _bus_db_paths[agent_name] = bus_db_path


def get_bus_db_path(agent_name: str = '') -> str:
    """Return the bus DB path for an agent, or '' if unregistered."""
    name = agent_name or current_agent_name.get('')
    return _bus_db_paths.get(name, '')


def mark_escalation_active(qualifier: str) -> None:
    """Mark a proxy qualifier as owned by an in-flight escalation.

    While marked, the bridge's HTTP handler must not auto-invoke the
    proxy for this qualifier — the AskQuestionRunner drives the loop
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

    The ``dispatcher`` is the routing-enforcement point Send consults
    before spawning the recipient — derived once at session setup from
    the workgroup roster, then threaded through every ``launch()`` call
    in that session's subtree.  An arbitrarily nested team enforces
    against one dispatcher: parent and grandchild authorize against the
    same routing table.  Routing tables key directly on agent names; an
    agent's name is its identity.

    Fields are optional: a leaf worker that neither dispatches nor
    closes conversations just leaves ``spawn_fn`` / ``close_fn`` unset.
    A session that has no workgroup config (bootstrap, scripted tests)
    leaves ``dispatcher`` unset — Send treats absent dispatcher as "no
    enforcement", same as the pre-#422 default.
    """
    spawn_fn: Callable | None = None
    close_fn: Callable | None = None
    ask_question_runner: Any | None = None
    dispatcher: Any | None = None
    bus_db_path: str = ''


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
    if routes.ask_question_runner is not None:
        register_ask_question_runner(agent_name, routes.ask_question_runner)
    if routes.dispatcher is not None:
        register_dispatcher(agent_name, routes.dispatcher)
    if routes.bus_db_path:
        register_bus_db_path(agent_name, routes.bus_db_path)


def clear() -> None:
    """Remove all registrations."""
    _spawn_fns.clear()
    _reply_fns.clear()
    _close_fns.clear()
    _ask_question_runners.clear()
    _dispatchers.clear()
    _bus_db_paths.clear()
    _active_escalations.clear()
