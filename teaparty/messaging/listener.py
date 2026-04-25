"""Bus event listener: dispatch bookkeeping + human interjection entry point.

All IPC for dispatch is in-process — no Unix sockets.  The MCP ``Send``
tool calls the registered ``spawn_fn`` directly (via the in-process
registry in ``teaparty.mcp.registry``).  Each tier's ``spawn_fn``
manages the child subtree end-to-end and runs shared code through
``teaparty.messaging.child_dispatch``.

This listener owns two things the tier-level ``spawn_fn`` does not:

1. **``schedule_child_task``** — shared by both tiers.  Records the
   dispatch in ``tasks_by_child`` (so the shared ``close_fn`` can
   cancel a subtree), emits ``dispatch_started`` for the accordion,
   wraps the child-lifecycle coroutine in an asyncio task.

2. **``handle_interjection``** — direct-call entry point the bridge
   invokes when a human types a message into an active agent's chat.
   Triggers ``reinvoke_fn`` under a per-context lock so the message
   reaches the agent on its next ``--resume`` turn.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

_log = logging.getLogger('teaparty.messaging.listener')

# reinvoke_fn(context_id, session_id, message) -> None
ReinvokeFn = Callable[[str, str, str], Awaitable[None]]


class BusEventListener:
    """Dispatch-task bookkeeping + interjection entry point.

    The actual ``spawn_fn`` lives in ``MCPRoutes`` (registered by
    ``launch()`` and looked up by the Send tool); this listener owns
    only the per-session bookkeeping that doesn't need to be in the
    spawn function itself — task registry + reinvoke lock for human
    interjections.

    Args:
        bus_db_path:       Path to the SQLite bus database.
        reinvoke_fn:       Async function called when a human interjection
                           arrives for an active conversation — triggers
                           ``--resume`` so the agent sees the message on its
                           next turn.
                           Signature: ``(context_id, session_id, message)``.
        current_context_id: Context ID this agent was spawned into.  May be
                           set after construction.
        initiator_agent_id: Agent ID of the caller (for logging).
    """

    def __init__(
        self,
        *,
        bus_db_path: str = '',
        reinvoke_fn: ReinvokeFn | None = None,
        current_context_id: str = '',
        initiator_agent_id: str = '',
    ) -> None:
        self.bus_db_path = bus_db_path
        self.reinvoke_fn = reinvoke_fn
        self.current_context_id = current_context_id
        self.initiator_agent_id = initiator_agent_id

        # Per-agent re-invocation locks: serializes concurrent --resume
        # calls for the same agent.
        self._reinvoke_locks: dict[str, asyncio.Lock] = {}

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

    async def handle_interjection(self, context_id: str, message: str) -> dict:
        """Entry point for bridge-originated human interjections.

        The bridge and this listener share a process — no IPC needed.
        Called when a human types into an active agent's chat: looks up
        the conversation's session_id, schedules ``reinvoke_fn``
        (``--resume``) so the agent picks up the human's message at
        the next turn.
        """
        if not context_id:
            return {'status': 'error', 'reason': 'context_id is required'}

        session_id = ''
        if self.bus_db_path:
            conv_status = self._get_conversation_status(context_id)
            if conv_status == 'closed':
                return {
                    'status': 'error',
                    'reason': f'Conversation {context_id!r} is closed',
                }
            session_id = self._get_session_id(context_id)

        if self.reinvoke_fn is not None:
            asyncio.create_task(
                self._locked_reinvoke(context_id, session_id, message),
            )

        return {'status': 'ok'}

    async def _locked_reinvoke(
        self, context_id: str, session_id: str, message: str,
    ) -> None:
        """Serialized wrapper for reinvoke_fn — ensures only one
        ``--resume`` call for a given context_id is active at a time.
        A second request for the same agent queues until the first
        completes.
        """
        if context_id not in self._reinvoke_locks:
            self._reinvoke_locks[context_id] = asyncio.Lock()
        lock = self._reinvoke_locks[context_id]
        async with lock:
            if self.reinvoke_fn is not None:
                await self.reinvoke_fn(context_id, session_id, message)

    # ── DB helpers (called from async context) ────────────────────────────

    def _get_conversation_status(self, context_id: str) -> str:
        """Return conversation_status for context_id, or '' if not found."""
        from teaparty.messaging.conversations import SqliteMessageBus
        bus = SqliteMessageBus(self.bus_db_path)
        try:
            ctx = bus.get_agent_context(context_id)
            if ctx is None:
                return ''
            return ctx.get('conversation_status', 'open')
        finally:
            bus.close()

    def _get_session_id(self, context_id: str) -> str:
        """Return session_id for context_id, or '' if not found."""
        from teaparty.messaging.conversations import SqliteMessageBus
        bus = SqliteMessageBus(self.bus_db_path)
        try:
            ctx = bus.get_agent_context(context_id)
            if ctx is None:
                return ''
            return ctx.get('session_id', '')
        finally:
            bus.close()
