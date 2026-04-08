"""Bus event listener: Unix socket servers for Send and Reply MCP tool IPC.

The orchestrator starts two sockets before launching Claude Code:
  SEND_SOCKET  — receives Send(member, composite, context_id) calls
  REPLY_SOCKET — receives Reply(message) calls

Send flow:
  1. Agent calls Send → MCP server connects to SEND_SOCKET
  2. Listener receives {type: send, member, composite, context_id}
  3. Listener creates an agent context record in the bus
  4. Listener calls spawn_fn(member, composite, context_id) asynchronously
  5. Listener returns {status: queued, context_id} immediately (non-blocking)
  6. spawn_fn runs in a background task; result (session_id) is stored in the record

Reply flow:
  1. Agent calls Reply → MCP server connects to REPLY_SOCKET
  2. Listener receives {type: reply, message}
  3. Listener closes the agent context record for current_context_id
  4. Listener calls reinvoke_fn(context_id, session_id, message) to resume the caller
  5. Returns {status: ok}

The caller is not blocked for recipient execution — Send returns as soon as the
context record is created and the spawn task is enqueued.  This is the non-blocking
property required by the agent-dispatch design.

Context ID format: agent:{initiator_agent_id}:{recipient_agent_id}:{uuid4}
See docs/proposals/agent-dispatch/references/conversation-model.md.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
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
# cleanup_fn(worktree_path) -> None
CleanupFn = Callable[[str], Awaitable[None]]


def make_agent_context_id(initiator_agent_id: str, recipient_agent_id: str) -> str:
    """Create a stable, unique context ID for an agent-to-agent exchange.

    Format: agent:{initiator_agent_id}:{recipient_agent_id}:{uuid4}

    The UUID4 suffix ensures two parallel Send calls to the same recipient
    produce distinct context IDs, as required for parallel dispatch (fan-out).
    """
    token = str(uuid.uuid4())
    return f'agent:{initiator_agent_id}:{recipient_agent_id}:{token}'


class BusEventListener:
    """Unix socket server that bridges Send and Reply MCP tool calls to bus operations.

    Lifecycle:
      listener = BusEventListener(bus_db_path=..., spawn_fn=..., ...)
      send_path, reply_path = await listener.start()
      # Set SEND_SOCKET=send_path, REPLY_SOCKET=reply_path in mcp_env
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
        cleanup_fn: CleanupFn | None = None,
        current_context_id: str = '',
        initiator_agent_id: str = '',
        dispatcher: object | None = None,
    ) -> None:
        self.bus_db_path = bus_db_path
        self.spawn_fn = spawn_fn
        self.resume_fn = resume_fn
        self.reply_fn = reply_fn
        self.reinvoke_fn = reinvoke_fn
        self.cleanup_fn = cleanup_fn
        self.current_context_id = current_context_id
        self.initiator_agent_id = initiator_agent_id
        self.dispatcher = dispatcher  # BusDispatcher | None

        self._send_server: asyncio.AbstractServer | None = None
        self._reply_server: asyncio.AbstractServer | None = None
        self._close_server: asyncio.AbstractServer | None = None
        self._interjection_server: asyncio.AbstractServer | None = None
        self._send_socket_path = ''
        self._reply_socket_path = ''
        self._close_socket_path = ''
        self._interjection_socket_path = ''
        self._sock_dir = ''
        # Per-agent re-invocation locks: serializes concurrent --resume calls for
        # the same agent (see conversation-model.md — Fan-In vs. Mid-Task Clarification).
        self._reinvoke_locks: dict[str, asyncio.Lock] = {}

    @property
    def interjection_socket_path(self) -> str:
        """Path to the interjection Unix socket for bridge-triggered --resume."""
        return self._interjection_socket_path

    async def start(self) -> tuple[str, str, str]:
        """Start all socket servers.

        Returns:
            (send_socket_path, reply_socket_path, close_socket_path)

        The interjection socket path is available via ``self.interjection_socket_path``.
        """
        self._sock_dir = tempfile.mkdtemp(prefix='teaparty-bus-')
        self._send_socket_path = os.path.join(self._sock_dir, 'send.sock')
        self._reply_socket_path = os.path.join(self._sock_dir, 'reply.sock')
        self._close_socket_path = os.path.join(self._sock_dir, 'close.sock')
        self._interjection_socket_path = os.path.join(self._sock_dir, 'interject.sock')

        self._send_server = await asyncio.start_unix_server(
            self._handle_send_connection,
            path=self._send_socket_path,
        )
        self._reply_server = await asyncio.start_unix_server(
            self._handle_reply_connection,
            path=self._reply_socket_path,
        )
        self._close_server = await asyncio.start_unix_server(
            self._handle_close_connection,
            path=self._close_socket_path,
        )
        self._interjection_server = await asyncio.start_unix_server(
            self._handle_interjection_connection,
            path=self._interjection_socket_path,
        )
        _log.info(
            'BusEventListener started: send=%s reply=%s close=%s interject=%s',
            self._send_socket_path, self._reply_socket_path,
            self._close_socket_path, self._interjection_socket_path,
        )
        return self._send_socket_path, self._reply_socket_path, self._close_socket_path

    async def stop(self) -> None:
        """Stop all servers and clean up socket files."""
        for server in (
            self._send_server, self._reply_server,
            self._close_server, self._interjection_server,
        ):
            if server is not None:
                server.close()
                await server.wait_closed()
        self._send_server = None
        self._reply_server = None
        self._close_server = None
        self._interjection_server = None

        for path in (
            self._send_socket_path, self._reply_socket_path,
            self._close_socket_path, self._interjection_socket_path,
        ):
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass

        if self._sock_dir:
            try:
                os.rmdir(self._sock_dir)
            except OSError:
                pass

        self._send_socket_path = ''
        self._reply_socket_path = ''
        self._close_socket_path = ''
        self._interjection_socket_path = ''
        self._sock_dir = ''

    async def _handle_send_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a Send MCP tool call.

        Protocol (newline-delimited JSON):
          MCP → listener: {type: "send", member: str, composite: str, context_id: str}
          listener → MCP: {status: "queued", context_id: str}

        The response is sent before the spawn_fn completes so the caller is not blocked.
        """
        import time as _time
        try:
            t_recv = _time.monotonic()
            line = await reader.readline()
            if not line:
                return
            request = json.loads(line.decode())
            member = request.get('member', '')
            composite = request.get('composite', '')
            context_id = request.get('context_id', '')
            _log.info(
                'Send received: member=%r context_id=%r composite_len=%d',
                member, context_id, len(composite),
            )

            # Transport-level routing check — reject before touching the bus
            if self.dispatcher is not None:
                try:
                    self.dispatcher.authorize(
                        self.initiator_agent_id or 'unknown', member,
                    )
                except Exception as exc:
                    err_response = {'status': 'error', 'reason': str(exc)}
                    writer.write(json.dumps(err_response).encode() + b'\n')
                    await writer.drain()
                    return

            # Follow-up to an existing conversation: resume or reject
            if context_id and self.bus_db_path:
                conv_status = self._get_conversation_status(context_id)
                if conv_status == 'closed':
                    err_response = {
                        'status': 'error',
                        'reason': f'Conversation {context_id!r} is closed; '
                                  'originator must open a new conversation',
                    }
                    writer.write(json.dumps(err_response).encode() + b'\n')
                    await writer.drain()
                    return
                if conv_status == 'open':
                    # Resume the recipient's prior session instead of spawning fresh
                    session_id = self._get_session_id(context_id)
                    response = {'status': 'queued', 'context_id': context_id}
                    writer.write(json.dumps(response).encode() + b'\n')
                    await writer.drain()
                    if self.resume_fn is not None and session_id:
                        asyncio.create_task(
                            self._resume_and_record(member, composite, context_id, session_id)
                        )
                    return

            # New conversation: create the context record synchronously so
            # the caller has a context_id immediately
            if not context_id:
                context_id = make_agent_context_id(
                    self.initiator_agent_id or 'unknown',
                    member,
                )

            if self.bus_db_path:
                self._create_context_record(context_id, member)

            # Spawn synchronously and return the result inline so the
            # caller's Send tool call receives the agent's response.
            if self.spawn_fn is not None:
                _log.info('Spawning agent for member=%r context_id=%r', member, context_id)
                result_text = await self._spawn_and_record(
                    member, composite, context_id,
                )
                response = {
                    'status': 'ok',
                    'context_id': context_id,
                    'result': result_text,
                }
            else:
                _log.warning('No spawn_fn — cannot spawn agent for member=%r', member)
                response = {'status': 'queued', 'context_id': context_id}

            writer.write(json.dumps(response).encode() + b'\n')
            await writer.drain()
            t_done = _time.monotonic()
            _log.info('Send complete: context_id=%r member=%r result_len=%d e2e=%.2fs',
                       context_id, member, len(response.get('result', '')),
                       t_done - t_recv)

        except Exception:
            _log.exception('Error handling Send connection')
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _spawn_and_record(
        self, member: str, composite: str, context_id: str,
    ) -> str:
        """Spawn recipient, record metadata, return result text.

        Returns the agent's result_text (from --output-format json) so the
        caller's Send tool call can return it inline.
        """
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

    async def _handle_reply_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a Reply MCP tool call.

        Protocol:
          MCP → listener: {type: "reply", message: str}
          listener → MCP: {status: "ok"}
        """
        try:
            line = await reader.readline()
            if not line:
                return
            request = json.loads(line.decode())
            message = request.get('message', '')

            # Workers include their own context_id in the Reply socket message
            # (set via the CONTEXT_ID env var injected at spawn time).
            # Fall back to current_context_id for callers that predate this field.
            context_id = request.get('context_id', '') or self.current_context_id
            _log.info(
                'Reply received: context_id=%r message_len=%d',
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
                # Decrement the parent's pending_count.  When it reaches zero all
                # workers in this fan-out have replied and the caller can be resumed.
                if parent_context_id:
                    new_count = self._decrement_parent_pending_count(parent_context_id)
                    if new_count == 0:
                        parent_ctx = self._get_context(parent_context_id)
                        if parent_ctx:
                            parent_session_id = parent_ctx.get('session_id', '')
                        should_reinvoke = True

            response = {'status': 'ok'}
            writer.write(json.dumps(response).encode() + b'\n')
            await writer.drain()

            # Inject this worker's reply into the caller's history on EVERY reply
            # (regardless of pending_count) so that in fan-out scenarios all N
            # worker replies are in the history before the caller resumes.
            # conversation-model.md: "appends it to the caller's local conversation
            # history file" — per Reply, not just the last.
            if self.reply_fn is not None and parent_context_id:
                asyncio.create_task(
                    self.reply_fn(parent_context_id, parent_session_id, message)
                )

            # Re-invoke the caller only when all fan-out workers have replied
            # (pending_count reached zero).  Use a per-agent lock so only one
            # --resume per caller is active at a time
            # (conversation-model.md — per-agent re-invocation lock).
            if self.reinvoke_fn is not None and should_reinvoke:
                asyncio.create_task(
                    self._locked_reinvoke(parent_context_id, parent_session_id, message)
                )

        except Exception:
            _log.exception('Error handling Reply connection')
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

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

    async def _handle_close_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a CloseConversation MCP tool call.

        Protocol:
          MCP → listener: {type: "close_conversation", context_id: str,
                           caller_agent_id: str}
          listener → MCP: {status: "ok"} | {status: "error", reason: str}

        Sets conversation_status='closed' so subsequent follow-up Sends are
        rejected.  When caller_agent_id is provided, only the context's
        initiator may close it; a non-initiator caller receives an error.
        Triggers worktree cleanup via cleanup_fn after the response is sent.
        """
        try:
            line = await reader.readline()
            if not line:
                return
            request = json.loads(line.decode())
            context_id = request.get('context_id', '')
            caller_agent_id = request.get('caller_agent_id', '')
            if not context_id:
                err = {'status': 'error', 'reason': 'context_id is required'}
                writer.write(json.dumps(err).encode() + b'\n')
                await writer.drain()
                return

            worktree_path = ''
            if self.bus_db_path:
                # Enforce originator-only close when the caller identifies itself.
                if caller_agent_id:
                    initiator = self._get_initiator_agent_id(context_id)
                    if initiator and initiator != caller_agent_id:
                        err = {
                            'status': 'error',
                            'reason': (
                                f'Only the originator ({initiator!r}) may close '
                                f'this conversation'
                            ),
                        }
                        writer.write(json.dumps(err).encode() + b'\n')
                        await writer.drain()
                        return
                worktree_path = self._get_worktree_path(context_id)
                self._close_conversation(context_id)

            response = {'status': 'ok'}
            writer.write(json.dumps(response).encode() + b'\n')
            await writer.drain()

            if worktree_path and self.cleanup_fn is not None:
                asyncio.create_task(self.cleanup_fn(worktree_path))

        except Exception:
            _log.exception('Error handling CloseConversation connection')
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _handle_interjection_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a human interjection from the bridge.

        Protocol:
          bridge → listener: {type: "interject", context_id: str, message: str}
          listener → bridge: {status: "ok"} | {status: "error", reason: str}

        Looks up the active session_id for the conversation and calls reinvoke_fn
        (--resume) so the agent receives the human's message.  Rejected if the
        conversation is closed.
        """
        try:
            line = await reader.readline()
            if not line:
                return
            request = json.loads(line.decode())
            context_id = request.get('context_id', '')
            message = request.get('message', '')

            if not context_id:
                err = {'status': 'error', 'reason': 'context_id is required'}
                writer.write(json.dumps(err).encode() + b'\n')
                await writer.drain()
                return

            if self.bus_db_path:
                conv_status = self._get_conversation_status(context_id)
                if conv_status == 'closed':
                    err = {
                        'status': 'error',
                        'reason': f'Conversation {context_id!r} is closed',
                    }
                    writer.write(json.dumps(err).encode() + b'\n')
                    await writer.drain()
                    return
                session_id = self._get_session_id(context_id)
            else:
                session_id = ''

            response = {'status': 'ok'}
            writer.write(json.dumps(response).encode() + b'\n')
            await writer.drain()

            if self.reinvoke_fn is not None:
                asyncio.create_task(
                    self._locked_reinvoke(context_id, session_id, message)
                )

        except Exception:
            _log.exception('Error handling interjection connection')
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

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
