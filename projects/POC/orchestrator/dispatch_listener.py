"""Unix socket listener for AskTeam MCP tool IPC.

The orchestrator starts this listener before launching Claude Code.
The MCP server (running as a Claude Code subprocess) connects to
the socket and sends dispatch requests.  The listener calls dispatch()
from dispatch_cli.py for each request.  Concurrent requests each get
their own asyncio task so dispatches run in parallel.

Flow:
  1. Liaison calls AskTeam(team, task) → MCP server connects to this socket
  2. Listener receives {"type": "ask_team", "team": "writing", "task": "..."}
  3. Listener calls dispatch(team, task, ...) with explicit session context
  4. Returns the dispatch result JSON to the MCP server → liaison

Protocol (newline-delimited JSON over Unix socket):

  MCP server → listener:
    {"type": "ask_team", "team": "writing", "task": "Write jokes"}

  listener → MCP server:
    {"status": "completed", "team": "writing", "task": "Write jokes", ...}
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile

from projects.POC.orchestrator.dispatch_cli import dispatch
from projects.POC.orchestrator.events import Event, EventBus, EventType

_log = logging.getLogger('orchestrator.dispatch')


class DispatchListener:
    """Unix socket server that bridges MCP AskTeam calls to dispatch().

    Each incoming ask_team request is handled as an independent asyncio
    task so concurrent dispatches from multiple liaisons run in parallel.

    Lifecycle:
      listener = DispatchListener(event_bus, session_worktree, ...)
      await listener.start()
      # ... run Claude Code with ASK_TEAM_SOCKET=listener.socket_path ...
      await listener.stop()
    """

    def __init__(
        self,
        event_bus: EventBus,
        session_worktree: str,
        infra_dir: str,
        project_slug: str,
        session_id: str = '',
        poc_root: str = '',
        proxy_model_path: str = '',
    ):
        self.event_bus = event_bus
        self.session_worktree = session_worktree
        self.infra_dir = infra_dir
        self.project_slug = project_slug
        self.session_id = session_id
        self.poc_root = poc_root
        self.proxy_model_path = proxy_model_path
        self.socket_path = ''
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> str:
        """Start listening.  Returns the socket path."""
        sock_dir = tempfile.mkdtemp(prefix='teaparty-dispatch-')
        self.socket_path = os.path.join(sock_dir, 'dispatch.sock')

        self._server = await asyncio.start_unix_server(
            self._handle_connection, path=self.socket_path,
        )
        _log.info('Dispatch listener started at %s', self.socket_path)
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
        """Handle a single connection from the MCP server.

        Each connection gets its own task so concurrent dispatches
        run in parallel rather than being serialized by the listener.
        """
        asyncio.ensure_future(self._handle_connection_task(reader, writer))

    async def _handle_connection_task(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Process one ask_team request end-to-end."""
        try:
            line = await reader.readline()
            if not line:
                return
            request = json.loads(line.decode())
            team = request.get('team', '')
            task = request.get('task', '')

            if not team or not task:
                response = {'status': 'failed', 'reason': 'team and task are required'}
            else:
                response = await self._handle_dispatch(team, task)

            writer.write(json.dumps(response).encode() + b'\n')
            await writer.drain()
        except Exception:
            _log.exception('Error handling dispatch connection')
            try:
                writer.write(
                    json.dumps({'status': 'failed', 'reason': 'internal error'}).encode()
                    + b'\n'
                )
                await writer.drain()
            except Exception:
                pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _handle_dispatch(self, team: str, task: str) -> dict:
        """Call dispatch() with the session context passed explicitly."""
        _log.info('Dispatching to team %r: %s', team, task[:80])

        await self.event_bus.publish(Event(
            type=EventType.LOG,
            data={
                'category': 'dispatch_start',
                'team': team,
                'task': task[:200],
            },
            session_id=self.session_id,
        ))

        result = await dispatch(
            team=team,
            task=task,
            session_worktree=self.session_worktree,
            infra_dir=self.infra_dir,
            project_slug=self.project_slug,
        )

        await self.event_bus.publish(Event(
            type=EventType.LOG,
            data={
                'category': 'dispatch_complete',
                'team': team,
                'status': result.get('status', 'unknown'),
                'terminal_state': result.get('terminal_state', ''),
            },
            session_id=self.session_id,
        ))

        _log.info('Dispatch to %r completed: %s', team, result.get('status', '?'))
        return result
