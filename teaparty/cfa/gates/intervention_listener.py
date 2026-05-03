"""Bus-backed listener for office-manager intervention tools.

Bridges MCP tool calls (WithdrawSession, PauseDispatch, ResumeDispatch,
ReprioritizeDispatch) to the office_manager_tools functions.  The MCP
tool writes a request message onto the intervention conversation; this
listener polls that conversation, resolves session/dispatch IDs to
infra directory paths, calls the appropriate function, and writes the
result back.

(Note: this listener has the same tool-handler-to-listener bus hop
that AskQuestion used to have.  AskQuestion was inlined into the MCP
tool handler in Cut 10; the intervention tools are still on the old
pattern and could be inlined the same way.)

Protocol (JSON in the ``content`` field of each bus message):

  agent → orchestrator:
    {"type": "withdraw_session", "session_id": "abc123"}
    {"type": "pause_dispatch", "dispatch_id": "writing-abc123"}
    {"type": "resume_dispatch", "dispatch_id": "writing-abc123"}
    {"type": "reprioritize_dispatch", "dispatch_id": "writing-abc123", "priority": "high"}

  orchestrator → agent:
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
import time
from typing import Callable, Literal, TypedDict

from teaparty.messaging.conversations import SqliteMessageBus
from teaparty.teams.office_manager_tools import (
    pause_dispatch,
    reprioritize_dispatch,
    resume_dispatch,
    withdraw_session,
)

_log = logging.getLogger('teaparty.cfa.gates.intervention')

# How often the listener polls the bus for new agent messages.
_POLL_INTERVAL = 0.1


# ── Shared wire format ────────────────────────────────────────────────────────
# Defined here, imported by both the bridge and the MCP server to prevent
# protocol drift.

RequestType = Literal[
    'withdraw_session',
    'pause_dispatch',
    'resume_dispatch',
    'reprioritize_dispatch',
]


class InterventionRequest(TypedDict, total=False):
    """Wire format for intervention bus messages.

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
    """Bus consumer that bridges MCP intervention tools to file operations.

    The resolver dict maps session/dispatch IDs to infra directory paths.
    The orchestrator populates this at construction time from its knowledge
    of active sessions and dispatches.

    Lifecycle:
      listener = InterventionListener(
          resolver={'ses-1': '/path/to/infra'},
          bus_db_path='/path/to/messages.db',
          conv_id='intervention:ses-1',
      )
      await listener.start()
      # ... run Claude Code with
      #   INTERVENTION_BUS_DB=bus_db_path
      #   INTERVENTION_CONV_ID=conv_id
      await listener.stop()
    """

    def __init__(
        self,
        resolver: dict[str, str],
        bus_db_path: str,
        conv_id: str,
        on_withdraw: 'Callable[[str], None] | None' = None,
    ):
        self._resolver = resolver
        self.bus_db_path = bus_db_path
        self.conv_id = conv_id
        self._on_withdraw = on_withdraw
        self._task: asyncio.Task | None = None
        self._bus: SqliteMessageBus | None = None

    async def start(self) -> None:
        """Open the bus and start the background polling task.

        ``since`` is captured here (not inside the task body) so messages
        written between create_task() and the task's first tick are not
        silently dropped — deliberate choice, observable once at start.
        """
        self._bus = SqliteMessageBus(self.bus_db_path)
        since = time.time()
        self._task = asyncio.create_task(self._poll_loop(since))
        _log.info(
            'Intervention listener started on bus %s conv %s',
            self.bus_db_path, self.conv_id,
        )

    async def stop(self) -> None:
        """Cancel the polling task."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        self._bus = None

    async def _poll_loop(self, since: float) -> None:
        """Poll the bus for new 'agent' messages and handle each one."""
        while True:
            try:
                if self._bus is None:
                    return
                messages = self._bus.receive(self.conv_id, since_timestamp=since)
                for msg in messages:
                    since = max(since, msg.timestamp)
                    if msg.sender != 'agent':
                        continue
                    self._handle_message(msg.content)
            except asyncio.CancelledError:
                raise
            except Exception:
                _log.exception('Error polling bus for intervention messages')
            await asyncio.sleep(_POLL_INTERVAL)

    def _handle_message(self, raw_content: str) -> None:
        """Parse an agent request, dispatch it, write the reply to the bus."""
        try:
            request = json.loads(raw_content)
        except json.JSONDecodeError:
            _log.warning(
                'Intervention message is not JSON: %r', raw_content[:120],
            )
            return

        response = self._dispatch(request)
        if self._bus is not None:
            self._bus.send(
                self.conv_id, 'orchestrator', json.dumps(response),
            )

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
