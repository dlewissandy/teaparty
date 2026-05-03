"""Bus event listener: dispatch task bookkeeping.

All IPC for dispatch is in-process — no Unix sockets.  The MCP ``Send``
tool calls the registered ``spawn_fn`` directly (via the in-process
registry in ``teaparty.mcp.registry``).  Each tier's ``spawn_fn``
manages the child subtree end-to-end and runs shared code through
``teaparty.messaging.child_dispatch``.

This listener owns one thing the tier-level ``spawn_fn`` does not:
**``schedule_child_task``** — shared by both tiers.  Records the
dispatch in ``tasks_by_child`` (so the shared ``close_fn`` can cancel
a subtree), emits ``dispatch_started`` for the accordion, wraps the
child-lifecycle coroutine in an asyncio task.

Cut 27: the previous ``handle_interjection`` / ``reinvoke_fn`` /
``_locked_reinvoke`` machinery was dead.  Chat-tier's ``reinvoke_fn``
was a logging stub; the bridge's ``agent:`` conversation handler
delegated to it and dropped human messages on the floor.  The bridge
now writes ``agent:`` conversation human messages directly to the
bus, same as every other conversation type — agents pick them up
from bus history on their next ``--resume``.  No queue, no lock,
no ping-pong.
"""
from __future__ import annotations

import asyncio
import logging

_log = logging.getLogger('teaparty.messaging.listener')


class BusEventListener:
    """Dispatch-task bookkeeping.

    The actual ``spawn_fn`` lives in ``MCPRoutes`` (registered by
    ``launch()`` and looked up by the Send tool); this listener owns
    only the per-session bookkeeping that doesn't need to be in the
    spawn function itself — the in-flight task registry.

    Args:
        bus_db_path:       Path to the SQLite bus database.
        current_context_id: Context ID this agent was spawned into.  May be
                           set after construction.
        initiator_agent_id: Agent ID of the caller (for logging).
    """

    def __init__(
        self,
        *,
        bus_db_path: str = '',
        current_context_id: str = '',
        initiator_agent_id: str = '',
    ) -> None:
        self.bus_db_path = bus_db_path
        self.current_context_id = current_context_id
        self.initiator_agent_id = initiator_agent_id

        # In-flight child tasks, keyed by child session_id.  Populated
        # by ``schedule_child_task`` below; the shared ``close_fn``
        # reads this to cancel subtrees that are being torn down.
        self.tasks_by_child: dict[str, asyncio.Task] = {}

    def schedule_child_task(
        self,
        *,
        child_session_id: str,
        launch_coro,
        dispatcher_session,
        context_id: str,
        agent_name: str,
        on_dispatch=None,
        background_tasks: set | None = None,
    ) -> asyncio.Task:
        """Record a dispatched child, emit ``dispatch_started``, schedule its task.

        Shared by both tiers.  The caller has already created the child
        session record and stamped it with merge metadata; this method
        performs the rest of the spawn boilerplate:

          1. Emit ``dispatch_started`` so the UI renders the subteam blade.
          2. Wrap the caller's launch coroutine in an asyncio task.
          3. Register that task in ``self.tasks_by_child`` keyed by
             ``child_session_id`` so the shared ``close_fn`` can cancel
             the subtree cleanly.

        ``background_tasks`` is an optional caller-maintained set.  Chat
        passes its set here so tasks are tracked alongside ``tasks_by_child``.
        """
        if on_dispatch is not None:
            try:
                on_dispatch({
                    'type': 'dispatch_started',
                    'parent_session_id': dispatcher_session.id,
                    'child_session_id': child_session_id,
                    'agent_name': agent_name,
                })
            except Exception:
                _log.debug(
                    'on_dispatch raised for dispatch_started',
                    exc_info=True,
                )
        task = asyncio.create_task(launch_coro)
        self.tasks_by_child[child_session_id] = task
        if background_tasks is not None:
            background_tasks.add(task)
            task.add_done_callback(background_tasks.discard)
        return task

    async def start(self) -> None:
        """No-op — kept for lifecycle symmetry with callers."""
        _log.info('BusEventListener started (direct-call, no sockets)')

    async def stop(self) -> None:
        """No-op — kept for lifecycle symmetry with callers."""
        return None
