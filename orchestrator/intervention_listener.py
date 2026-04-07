"""Unix socket listener for office manager intervention tools.

Bridges MCP tool calls (WithdrawSession, PauseDispatch, ResumeDispatch,
ReprioritizeDispatch) to the office_manager_tools functions.  The MCP
server sends requests over INTERVENTION_SOCKET; this listener resolves
session/dispatch IDs to infra directory paths and calls the functions.

Same pattern as EscalationListener.

Protocol (newline-delimited JSON over Unix socket):

  MCP server -> listener:
    {"type": "withdraw_session", "session_id": "abc123"}
    {"type": "pause_dispatch", "dispatch_id": "writing-abc123"}
    {"type": "resume_dispatch", "dispatch_id": "writing-abc123"}
    {"type": "reprioritize_dispatch", "dispatch_id": "writing-abc123", "priority": "high"}

  listener -> MCP server:
    {"status": "withdrawn"}
    {"status": "paused"}
    {"status": "resumed"}
    {"status": "reprioritized", "old_priority": "normal", "new_priority": "high"}

Issue #249.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from typing import Callable, Literal, TypedDict

from orchestrator.office_manager_tools import (
    pause_dispatch,
    reprioritize_dispatch,
    resume_dispatch,
    withdraw_session,
)

_log = logging.getLogger('orchestrator.intervention')


# ── Shared wire format ────────────────────────────────────────────────────────
# Defined here, imported by both the bridge and the MCP server to prevent
# protocol drift.  See cfa-extensions proposal and bridge-api.md.

RequestType = Literal[
    'withdraw_session',
    'pause_dispatch',
    'resume_dispatch',
    'reprioritize_dispatch',
]


class InterventionRequest(TypedDict, total=False):
    """Wire format for intervention socket messages.

    Required: ``type`` plus the relevant ID field (``session_id`` or
    ``dispatch_id``).  Optional: ``priority`` (for reprioritize only).
    """
    type: RequestType
    session_id: str
    dispatch_id: str
    priority: str


def make_intervention_request(
    request_type: RequestType,
    **kwargs: str,
) -> InterventionRequest:
    """Build an InterventionRequest dict, ready for JSON serialization."""
    return InterventionRequest(type=request_type, **kwargs)


# Maps request type to the ID field name used in the request
_ID_FIELD: dict[RequestType, str] = {
    'withdraw_session': 'session_id',
    'pause_dispatch': 'dispatch_id',
    'resume_dispatch': 'dispatch_id',
    'reprioritize_dispatch': 'dispatch_id',
}


class InterventionListener:
    """Unix socket server bridging MCP intervention tools to file operations.

    The resolver dict maps session/dispatch IDs to infra directory paths.
    The orchestrator populates this at construction time from its knowledge
    of active sessions and dispatches.

    When ``teaparty_home`` is provided, the listener binds directly at the
    well-known path ``{teaparty_home}/sockets/{session_id}.sock`` so the
    bridge can reach it.  Uses unlink-before-bind to handle stale sockets
    from crashed sessions.  Issue #386, per cfa-extensions proposal.

    Lifecycle:
      listener = InterventionListener(
          resolver={'ses-1': '/path/to/infra'},
          teaparty_home='~/.teaparty',
      )
      await listener.start()
      # ... run office manager with INTERVENTION_SOCKET=listener.socket_path ...
      await listener.stop()
    """

    def __init__(
        self,
        resolver: dict[str, str],
        teaparty_home: str = '',
        on_withdraw: 'Callable[[str], None] | None' = None,
    ):
        self._resolver = resolver
        self._teaparty_home = os.path.expanduser(teaparty_home) if teaparty_home else ''
        self._on_withdraw = on_withdraw
        self.socket_path = ''
        self._server: asyncio.AbstractServer | None = None
        self._well_known_paths: list[str] = []

    async def start(self) -> str:
        """Start listening. Returns the socket path.

        When teaparty_home is set, binds at the well-known per-session path
        so the bridge can find the socket by session ID alone.  Falls back
        to a temp directory when teaparty_home is not provided.
        """
        if self._teaparty_home and self._resolver:
            # Bind at the well-known path per the cfa-extensions spec.
            # Use the first session ID (one session per engine run).
            session_id = next(iter(self._resolver))
            sockets_dir = os.path.join(self._teaparty_home, 'sockets')
            os.makedirs(sockets_dir, exist_ok=True)
            self.socket_path = os.path.join(sockets_dir, f'{session_id}.sock')
            self._well_known_paths.append(self.socket_path)
            # Unlink-before-bind: remove stale socket from crashed session.
            try:
                os.unlink(self.socket_path)
            except FileNotFoundError:
                pass
        else:
            sock_dir = tempfile.mkdtemp(prefix='teaparty-intervention-')
            self.socket_path = os.path.join(sock_dir, 'intervention.sock')

        self._server = await asyncio.start_unix_server(
            self._handle_connection, path=self.socket_path,
        )
        _log.info('Intervention listener started at %s', self.socket_path)
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
            except OSError:
                pass
            # Only remove parent dir if we created a temp directory.
            if self.socket_path not in self._well_known_paths:
                try:
                    os.rmdir(os.path.dirname(self.socket_path))
                except OSError:
                    pass
            self.socket_path = ''
        self._well_known_paths.clear()

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
            response = self._dispatch(request)
            writer.write(json.dumps(response).encode() + b'\n')
            await writer.drain()
        except Exception:
            _log.exception('Error handling intervention connection')
            try:
                writer.write(
                    json.dumps({'status': 'error', 'reason': 'internal error'}).encode()
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

    def _dispatch(self, request: dict) -> dict:
        """Route a request to the appropriate tool function."""
        req_type = request.get('type', '')

        if req_type not in _ID_FIELD:
            return {'status': 'error', 'reason': f'unknown request type: {req_type}'}

        id_field = _ID_FIELD[req_type]
        target_id = request.get(id_field, '')
        infra_dir = self._resolver.get(target_id, '')

        if not infra_dir:
            return {'status': 'error', 'reason': f'unknown {id_field}: {target_id}'}

        if req_type == 'withdraw_session':
            result = withdraw_session(infra_dir)
            if result.get('status') == 'withdrawn' and self._on_withdraw:
                self._on_withdraw(target_id)
            return result
        elif req_type == 'pause_dispatch':
            return pause_dispatch(infra_dir)
        elif req_type == 'resume_dispatch':
            return resume_dispatch(infra_dir)
        elif req_type == 'reprioritize_dispatch':
            priority = request.get('priority', 'normal')
            return reprioritize_dispatch(infra_dir, priority)

        return {'status': 'error', 'reason': f'unhandled type: {req_type}'}
