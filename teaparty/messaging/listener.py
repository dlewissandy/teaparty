"""Bus event listener: context/worktree bookkeeping for agent dispatch.

All IPC for dispatch is in-process — no Unix sockets.  Send and
CloseConversation from agents route through the in-process registry
(``teaparty.mcp.registry``) which calls spawn_fn / close_fn; those
closures delegate to the worker methods on this listener
(``_spawn_and_record``, ``_close_context``, etc.).  Human interjections
from the bridge arrive via a direct call to ``handle_interjection``.

Send flow:
  1. Agent calls Send → MCP tool looks up spawn_fn in the registry
  2. Registry calls the engine/AgentSession spawn_fn, which delegates
     to ``_spawn_and_record`` on this listener
  3. ``_spawn_and_record`` creates an agent context record, calls the
     configured ``spawn_fn`` (engine-specific), and returns the child's
     result_text to the caller.

Reply flow (automatic, no agent tool):
  When the spawned child subprocess exits, ``_spawn_and_record`` calls
  ``trigger_reply(context_id, result_text)``. ``trigger_reply`` closes
  the child's context, decrements the parent's pending_count, injects
  the reply into the parent's history, and re-invokes the parent when
  the fan-out completes.  Agents do not call Reply themselves — turn-
  end is the signal.

Context ID format: agent:{initiator_agent_id}:{recipient_agent_id}:{uuid4}
See docs/proposals/agent-dispatch/references/conversation-model.md.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Awaitable, Callable

_log = logging.getLogger('teaparty.messaging.listener')

# Type aliases for the pluggable spawn and re-invocation functions.
# spawn_fn(member, composite, context_id) -> (session_id, worktree_path, result_text)
SpawnFn = Callable[[str, str, str], Awaitable[tuple[str, str, str]]]
# resume_fn(member, composite, session_id, context_id) -> session_id
ResumeFn = Callable[[str, str, str, str], Awaitable[str]]
# reinvoke_fn(context_id, session_id, message) -> None
ReinvokeFn = Callable[[str, str, str], Awaitable[None]]


def make_agent_context_id(initiator_agent_id: str, recipient_agent_id: str) -> str:
    """Create a stable, unique context ID for an agent-to-agent exchange.

    Format: agent:{initiator_agent_id}:{recipient_agent_id}:{uuid4}

    The UUID4 suffix ensures two parallel Send calls to the same recipient
    produce distinct context IDs, as required for parallel dispatch (fan-out).
    """
    token = str(uuid.uuid4())
    return f'agent:{initiator_agent_id}:{recipient_agent_id}:{token}'


class BusEventListener:
    """Dispatch-context bookkeeping + interjection socket server.

    Send and CloseConversation route directly through the registry's
    spawn_fn / close_fn; this class exposes the worker functions those
    spawn_fns call (``_spawn_and_record``, ``_close_context``, etc.).
    The only socket this class still owns is the interjection socket
    that the bridge uses to wake a running agent with a human message.

    Lifecycle:
      listener = BusEventListener(bus_db_path=..., spawn_fn=..., ...)
      await listener.start()
      # bridge calls listener.handle_interjection(...) directly for
      # human-typed messages during an active dispatch.
      await listener.stop()

    Args:
        bus_db_path:       Path to the SQLite bus database.
        spawn_fn:          Async function called to spawn the recipient agent.
                           Signature: (member, composite, context_id) -> session_id.
                           Called as a background task — Send returns before it completes.
        reply_fn:          Async function called for EVERY Reply — injects the worker's
                           message into the caller's conversation history.
                           Signature: (context_id, session_id, message).
                           Called before reinvoke_fn so all replies are in history
                           before the caller resumes.
        reinvoke_fn:       Async function called when ALL workers have replied
                           (pending_count reaches zero) — triggers caller re-invocation.
                           Signature: (context_id, session_id, message).
        current_context_id: The context ID this agent was spawned into (used by Reply
                           to know which context to close).  May be set after construction.
        initiator_agent_id: The agent ID of the caller (stored in context records).
    """

    def __init__(
        self,
        *,
        bus_db_path: str = '',
        spawn_fn: SpawnFn | None = None,
        resume_fn: ResumeFn | None = None,
        reply_fn: ReinvokeFn | None = None,
        reinvoke_fn: ReinvokeFn | None = None,
        current_context_id: str = '',
        initiator_agent_id: str = '',
        dispatcher: object | None = None,
    ) -> None:
        self.bus_db_path = bus_db_path
        self.spawn_fn = spawn_fn
        self.resume_fn = resume_fn
        self.reply_fn = reply_fn
        self.reinvoke_fn = reinvoke_fn
        self.current_context_id = current_context_id
        self.initiator_agent_id = initiator_agent_id
        self.dispatcher = dispatcher  # BusDispatcher | None

        # Per-agent re-invocation locks: serializes concurrent --resume calls for
        # the same agent (see conversation-model.md — Fan-In vs. Mid-Task Clarification).
        self._reinvoke_locks: dict[str, asyncio.Lock] = {}

        # In-flight child tasks, keyed by child session_id.  Both tiers
        # populate this from their spawn_fn: the close_fn cancels any
        # entry whose session is inside the subtree being torn down so
        # no task writes into a directory that close_conversation is
        # about to rmtree.  Issue #422 moved this to the listener so
        # chat and CfA share one registry.
        self.tasks_by_child: dict[str, asyncio.Task] = {}

    async def start(self) -> None:
        """No-op — kept for lifecycle symmetry with earlier callers.

        BusEventListener used to run three Unix socket servers (send,
        close, interject). Send/Close migrated to the in-process registry
        and the dispatch bus; interjection migrated to a direct-call
        method (``handle_interjection``). No sockets remain.
        """
        _log.info('BusEventListener started (direct-call, no sockets)')

    async def stop(self) -> None:
        """No-op — kept for lifecycle symmetry with earlier callers."""
        return None

    async def _spawn_and_record(
        self, member: str, composite: str, context_id: str,
    ) -> str:
        """Spawn recipient, record metadata, return result text.

        When the child subprocess exits, treat its last agent message
        (``result_text``) as the implicit reply and run the same bookkeeping
        the old Reply bus message triggered — close context, decrement
        parent pending_count, inject into parent history, re-invoke parent
        on fan-in completion.

        Transport-level routing enforcement: when a dispatcher is
        configured, authorize the (initiator, member) pair before
        spawning. This is the convergence point for all Send paths
        (registry call from the MCP tool, dispatch-bus poll) so the
        routing check runs exactly once regardless of how Send arrived.
        """
        if self.dispatcher is not None:
            try:
                self.dispatcher.authorize(
                    self.initiator_agent_id or 'unknown', member,
                )
            except Exception as exc:
                _log.warning(
                    '_spawn_and_record: routing denied %r→%r: %s',
                    self.initiator_agent_id, member, exc,
                )
                return f'[routing error] {exc}'

        try:
            _log.info('_spawn_and_record: starting spawn for member=%r context=%s', member, context_id)
            session_id, worktree_path, result_text = await self.spawn_fn(member, composite, context_id)
            _log.info(
                '_spawn_and_record: spawn complete for context=%s session_id=%r '
                'worktree=%r result_len=%d',
                context_id, session_id, worktree_path, len(result_text),
            )
            if self.bus_db_path:
                if session_id:
                    self._set_session_id(context_id, session_id)
                if worktree_path:
                    self._set_worktree_path(context_id, worktree_path)

            # Turn-end is the reply signal. Run the listener-side bookkeeping
            # now that the child's work is done.
            await self.trigger_reply(context_id, result_text)

            return result_text

        except Exception:
            _log.exception('Error spawning agent for context %s', context_id)
            return ''

    async def _resume_and_record(
        self, member: str, composite: str, context_id: str, session_id: str,
    ) -> None:
        """Background task: resume recipient with prior session_id."""
        try:
            new_session_id = await self.resume_fn(member, composite, session_id, context_id)
            if new_session_id and new_session_id != session_id and self.bus_db_path:
                self._set_session_id(context_id, new_session_id)
        except Exception:
            _log.exception('Error resuming agent for context %s', context_id)

    async def trigger_reply(self, context_id: str, message: str) -> None:
        """Signal that a worker's turn has ended with *message* as its reply.

        Called automatically when a spawned child subprocess exits — the
        engine treats turn-end as the reply signal so agents do not have
        to remember to issue one. The bookkeeping is identical to the
        old Reply bus-message path: close the child's context, decrement
        the parent's pending_count, inject the reply into the parent's
        history, and re-invoke the parent when the fan-out is fully in.
        """
        context_id = context_id or self.current_context_id
        _log.info(
            'trigger_reply: context_id=%r message_len=%d',
            context_id, len(message),
        )
        parent_context_id = ''
        parent_session_id = ''
        should_reinvoke = False

        if context_id and self.bus_db_path:
            ctx = self._get_context(context_id)
            if ctx:
                parent_context_id = ctx.get('parent_context_id', '')
            self._close_context(context_id)
            if parent_context_id:
                new_count = self._decrement_parent_pending_count(parent_context_id)
                if new_count == 0:
                    parent_ctx = self._get_context(parent_context_id)
                    if parent_ctx:
                        parent_session_id = parent_ctx.get('session_id', '')
                    should_reinvoke = True

        # Inject the reply into the caller's history on every reply
        # (regardless of pending_count) so fan-out scenarios get all N
        # replies in the history before the caller resumes.
        if self.reply_fn is not None and parent_context_id:
            asyncio.create_task(
                self.reply_fn(parent_context_id, parent_session_id, message)
            )

        # Re-invoke the caller only when all fan-out workers have landed
        # (pending_count reached zero). Per-agent lock serializes --resume
        # calls for the same caller.
        if self.reinvoke_fn is not None and should_reinvoke:
            asyncio.create_task(
                self._locked_reinvoke(parent_context_id, parent_session_id, message)
            )

    async def _locked_reinvoke(
        self, context_id: str, session_id: str, message: str,
    ) -> None:
        """Serialized wrapper for reinvoke_fn — enforces the per-agent re-invocation lock.

        Ensures only one --resume call for a given context_id is active at a time.
        A second re-invocation request for the same agent queues until the first
        completes (conversation-model.md — Fan-In vs. Mid-Task Clarification).
        """
        if context_id not in self._reinvoke_locks:
            self._reinvoke_locks[context_id] = asyncio.Lock()
        lock = self._reinvoke_locks[context_id]
        async with lock:
            if self.reinvoke_fn is not None:
                await self.reinvoke_fn(context_id, session_id, message)

    async def handle_interjection(self, context_id: str, message: str) -> dict:
        """Direct-call entry point for bridge-originated human interjections.

        The bridge and this listener share a process — no IPC needed. The
        bridge calls this method on the relevant AgentSession's listener
        when a human types into an active agent's chat.

        Looks up the active session_id for the conversation and schedules
        reinvoke_fn (--resume) so the agent receives the human's message.
        Returns a status dict; raises no exception on a closed conversation
        — returns ``{'status':'error', 'reason': ...}`` instead.
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

    # ── Synchronous DB helpers (called from async context) ────────────────────

    def _create_context_record(self, context_id: str, recipient_agent_id: str) -> None:
        from teaparty.messaging.conversations import SqliteMessageBus
        bus = SqliteMessageBus(self.bus_db_path)
        try:
            parent = self.current_context_id
            if parent:
                # Atomic two-record write: create child + increment parent's pending_count
                try:
                    bus.create_agent_context_and_increment_parent(
                        context_id,
                        initiator_agent_id=self.initiator_agent_id or 'unknown',
                        recipient_agent_id=recipient_agent_id,
                        parent_context_id=parent,
                    )
                    return
                except ValueError:
                    # Parent does not exist in this DB — fall through to simple create
                    pass
            bus.create_agent_context(
                context_id,
                initiator_agent_id=self.initiator_agent_id or 'unknown',
                recipient_agent_id=recipient_agent_id,
            )
        finally:
            bus.close()

    def _set_session_id(self, context_id: str, session_id: str) -> None:
        from teaparty.messaging.conversations import SqliteMessageBus
        bus = SqliteMessageBus(self.bus_db_path)
        try:
            bus.set_agent_context_session_id(context_id, session_id)
        finally:
            bus.close()

    def _get_context(self, context_id: str) -> dict | None:
        from teaparty.messaging.conversations import SqliteMessageBus
        bus = SqliteMessageBus(self.bus_db_path)
        try:
            return bus.get_agent_context(context_id)
        finally:
            bus.close()

    def _close_context(self, context_id: str) -> None:
        from teaparty.messaging.conversations import SqliteMessageBus
        bus = SqliteMessageBus(self.bus_db_path)
        try:
            bus.close_agent_context(context_id)
        finally:
            bus.close()

    def _decrement_parent_pending_count(self, parent_context_id: str) -> int:
        """Decrement the parent context's pending_count and return the new count."""
        from teaparty.messaging.conversations import SqliteMessageBus
        bus = SqliteMessageBus(self.bus_db_path)
        try:
            return bus.decrement_pending_count(parent_context_id)
        finally:
            bus.close()

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

    def _set_worktree_path(self, context_id: str, worktree_path: str) -> None:
        """Store the agent's worktree path for use on follow-up resume."""
        from teaparty.messaging.conversations import SqliteMessageBus
        bus = SqliteMessageBus(self.bus_db_path)
        try:
            bus.set_agent_context_worktree_path(context_id, worktree_path)
        finally:
            bus.close()

    def _get_worktree_path(self, context_id: str) -> str:
        """Return the agent's stored worktree path, or '' if not set."""
        from teaparty.messaging.conversations import SqliteMessageBus
        bus = SqliteMessageBus(self.bus_db_path)
        try:
            ctx = bus.get_agent_context(context_id)
            if ctx is None:
                return ''
            return ctx.get('agent_worktree_path', '')
        finally:
            bus.close()

    def _get_initiator_agent_id(self, context_id: str) -> str:
        """Return initiator_agent_id for context_id, or '' if not found."""
        from teaparty.messaging.conversations import SqliteMessageBus
        bus = SqliteMessageBus(self.bus_db_path)
        try:
            ctx = bus.get_agent_context(context_id)
            if ctx is None:
                return ''
            return ctx.get('initiator_agent_id', '')
        finally:
            bus.close()

    def _close_conversation(self, context_id: str) -> None:
        """Set conversation_status='closed' for context_id."""
        from teaparty.messaging.conversations import SqliteMessageBus
        bus = SqliteMessageBus(self.bus_db_path)
        try:
            bus.close_agent_conversation(context_id)
        finally:
            bus.close()
