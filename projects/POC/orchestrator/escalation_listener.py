"""Unix socket listener for AskQuestion MCP tool IPC.

The orchestrator starts this listener before launching Claude Code.
The MCP server (running as a Claude Code subprocess) connects to
the socket and sends questions.  The listener routes through the
proxy and, if needed, the human input_provider.

Protocol (newline-delimited JSON over Unix socket):

  MCP server → listener:
    {"type": "ask_human", "question": "Who is the audience?"}

  listener → MCP server:
    {"answer": "Ages 5-8"}
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from typing import Any, Awaitable, Callable

from projects.POC.orchestrator.events import (
    Event, EventBus, EventType, InputRequest,
)

_log = logging.getLogger('orchestrator.escalation')

# Type for the input provider (same as actors.InputProvider)
InputProvider = Callable[[InputRequest], Awaitable[str]]


class EscalationListener:
    """Unix socket server that bridges MCP AskQuestion to the orchestrator.

    Lifecycle:
      listener = EscalationListener(event_bus, input_provider, session_id)
      await listener.start()
      # ... run Claude Code with ASK_QUESTION_SOCKET=listener.socket_path ...
      await listener.stop()
    """

    def __init__(
        self,
        event_bus: EventBus,
        input_provider: InputProvider,
        session_id: str = '',
    ):
        self.event_bus = event_bus
        self.input_provider = input_provider
        self.session_id = session_id
        self.socket_path = ''
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> str:
        """Start listening.  Returns the socket path."""
        # Create socket in a temp directory
        sock_dir = tempfile.mkdtemp(prefix='teaparty-mcp-')
        self.socket_path = os.path.join(sock_dir, 'ask.sock')

        self._server = await asyncio.start_unix_server(
            self._handle_connection, path=self.socket_path,
        )
        _log.info('Escalation listener started at %s', self.socket_path)
        return self.socket_path

    async def stop(self) -> None:
        """Stop listening and clean up."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        if self.socket_path:
            try:
                os.unlink(self.socket_path)
                os.rmdir(os.path.dirname(self.socket_path))
            except OSError:
                pass
            self.socket_path = ''

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle a single connection from the MCP server."""
        try:
            line = await reader.readline()
            if not line:
                return
            request = json.loads(line.decode())
            question = request.get('question', '')

            if not question:
                response = {'answer': ''}
            else:
                answer = await self._ask_human(question)
                response = {'answer': answer}

            writer.write(json.dumps(response).encode() + b'\n')
            await writer.drain()
        except Exception:
            _log.exception('Error handling escalation connection')
            try:
                writer.write(json.dumps({'answer': ''}).encode() + b'\n')
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _ask_human(self, question: str) -> str:
        """Route a question to the human via the input_provider."""
        await self.event_bus.publish(Event(
            type=EventType.INPUT_REQUESTED,
            data={
                'state': 'AGENT_QUESTION',
                'bridge_text': question,
            },
            session_id=self.session_id,
        ))

        response = await self.input_provider(InputRequest(
            type='agent_question',
            state='AGENT_QUESTION',
            artifact='',
            bridge_text=question,
        ))

        await self.event_bus.publish(Event(
            type=EventType.INPUT_RECEIVED,
            data={'response': response},
            session_id=self.session_id,
        ))

        return response
