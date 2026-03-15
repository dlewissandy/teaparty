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
        """Call dispatch() with the session context, then run post-dispatch lifecycle.

        After dispatch completes:
        1. Roll up team learnings (dispatch MEMORY.md → team institutional + tasks)
        2. Compact accumulated memory files
        3. Merge child events into parent event stream
        """
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

        # Note: AskTeam calls block for the duration of the dispatch (minutes).
        # The parent Claude process produces no stdout during this time.
        # The stall watchdog (default 1800s) must be longer than the longest
        # expected dispatch.  If this becomes a problem, the watchdog needs
        # to be made aware of pending MCP tool calls.
        result = await dispatch(
            team=team,
            task=task,
            session_worktree=self.session_worktree,
            infra_dir=self.infra_dir,
            project_slug=self.project_slug,
        )

        # Post-dispatch lifecycle: learning rollup and compaction.
        # These run in the orchestrator process with full access to the
        # session context — no subprocess, no env var issues.
        if result.get('status') == 'completed':
            await self._post_dispatch_lifecycle(team)

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

    async def _post_dispatch_lifecycle(self, team: str) -> None:
        """Run learning rollup and compaction after a successful dispatch.

        1. promote('team') — rolls dispatch MEMORY.md files into team-level
           institutional.md and tasks/ files
        2. compact_file() — compresses accumulated team memory

        Errors are logged but don't fail the dispatch — the deliverables
        are already merged; learning is best-effort.
        """
        try:
            from projects.POC.scripts.summarize_session import promote

            # Determine the project directory (parent of infra_dir)
            project_dir = os.path.dirname(self.infra_dir)

            promote(
                scope='team',
                session_dir=self.infra_dir,
                project_dir=project_dir,
                output_dir=project_dir,
            )
            _log.info('Learning rollup completed for team %r', team)

            await self.event_bus.publish(Event(
                type=EventType.LOG,
                data={
                    'category': 'learning_rollup',
                    'team': team,
                    'scope': 'team',
                },
                session_id=self.session_id,
            ))
        except Exception:
            _log.debug('Learning rollup failed for team %r', team, exc_info=True)

        # Compact team memory files
        try:
            from projects.POC.scripts.compact_memory import compact_file

            team_dir = os.path.join(self.infra_dir, team)
            institutional_path = os.path.join(team_dir, 'institutional.md')
            if os.path.isfile(institutional_path):
                before, after = compact_file(institutional_path)
                if before > after:
                    _log.info(
                        'Compacted %s: %d → %d entries', institutional_path,
                        before, after,
                    )
                    await self.event_bus.publish(Event(
                        type=EventType.LOG,
                        data={
                            'category': 'memory_compaction',
                            'team': team,
                            'file': institutional_path,
                            'before': before,
                            'after': after,
                        },
                        session_id=self.session_id,
                    ))
        except Exception:
            _log.debug('Memory compaction failed for team %r', team, exc_info=True)

        # Merge child events into parent event stream
        try:
            team_dir = os.path.join(self.infra_dir, team)
            if os.path.isdir(team_dir):
                for entry in os.scandir(team_dir):
                    if not entry.is_dir():
                        continue
                    events_path = os.path.join(entry.path, 'events.jsonl')
                    if not os.path.isfile(events_path):
                        continue
                    with open(events_path) as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                child_event = json.loads(line)
                                await self.event_bus.publish(Event(
                                    type=EventType.LOG,
                                    data={
                                        'category': 'child_event',
                                        'team': team,
                                        'source': os.path.basename(entry.path),
                                        **child_event,
                                    },
                                    session_id=self.session_id,
                                ))
                            except (json.JSONDecodeError, Exception):
                                pass
        except Exception:
            _log.debug('Child event merge failed for team %r', team, exc_info=True)
