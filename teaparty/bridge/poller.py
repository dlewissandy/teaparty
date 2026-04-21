"""StateReader polling loop, state diffing, and WebSocket event push.

Polls StateReader every second, diffs against previous state, and broadcasts
change events to all connected WebSocket clients.

Push events (see docs/proposals/ui-redesign/references/bridge-api.md):
  state_changed    — CfA phase or state transition
  heartbeat        — alive/stale/dead status change (transitions only)
  session_completed — session reached COMPLETED_WORK or WITHDRAWN

SqliteMessageBus lifecycle:
  One connection opened per new active session (via bus_factory).
  Connection closed when the session reaches a terminal CfA state.
  Addresses issue #284 (bus connection teardown).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

_log = logging.getLogger('teaparty.bridge.poller')

_TERMINAL_STATES = frozenset({'DONE', 'WITHDRAWN'})


class StatePoller:
    """Polls StateReader every second and broadcasts state-change events.

    Args:
        state_reader:  Provides .reload() -> list[ProjectState].
        broadcast:     Async callable that sends an event dict to all WebSocket clients.
        bus_factory:   Optional callable(infra_dir: str) -> SqliteMessageBus.
                       When provided, opens one connection per active session and
                       closes it when the session reaches a terminal state.
        bus_teardown:  Optional callable(bus) -> None called just before the bus
                       connection is closed (after session termination).  Callers
                       that maintain their own registry of the same bus object
                       (e.g. MessageRelay via server._buses) can use this to evict
                       the entry before the underlying connection goes away.
        poll_interval: Seconds between polls (default 1.0).
    """

    def __init__(
        self,
        state_reader,
        broadcast: Callable[[dict], Awaitable[None]],
        bus_factory: Callable[[str], object] | None = None,
        bus_teardown: Callable[[object], None] | None = None,
        poll_interval: float = 1.0,
    ) -> None:
        self._state_reader = state_reader
        self._broadcast = broadcast
        self._bus_factory = bus_factory
        self._bus_teardown = bus_teardown
        self._poll_interval = poll_interval

        # Per-session snapshot keyed by session_id
        self._prev_cfa_state: dict[str, str] = {}
        self._prev_cfa_phase: dict[str, str] = {}
        self._prev_heartbeat: dict[str, str] = {}

        # Open bus connections keyed by session_id
        self._buses: dict[str, object] = {}

    async def poll_once(self) -> None:
        """Run one poll cycle: reload state, diff, broadcast changes."""
        projects = self._state_reader.reload()
        for project in projects:
            for session in project.sessions:
                await self._process_session(session)

    async def run(self) -> None:
        """Poll indefinitely at poll_interval cadence."""
        while True:
            try:
                await self.poll_once()
            except Exception:
                _log.exception('poll_once raised unexpectedly')
            await asyncio.sleep(self._poll_interval)

    async def _process_session(self, session) -> None:
        sid = session.session_id
        is_first = sid not in self._prev_cfa_state
        is_terminal = session.cfa_state in _TERMINAL_STATES

        if not is_first:
            await self._diff_cfa_state(sid, session)
            await self._diff_heartbeat(sid, session)
            await self._diff_completion(sid, session, is_terminal)

        # Update snapshots
        self._prev_cfa_state[sid] = session.cfa_state
        self._prev_cfa_phase[sid] = session.cfa_phase
        self._prev_heartbeat[sid] = session.heartbeat_status

        # Open bus for new non-terminal sessions
        if not is_terminal and sid not in self._buses and self._bus_factory:
            infra_dir = getattr(session, 'infra_dir', '')
            if infra_dir:
                self._buses[sid] = self._bus_factory(infra_dir)

    async def _diff_cfa_state(self, sid: str, session) -> None:
        if (session.cfa_state != self._prev_cfa_state[sid]
                or session.cfa_phase != self._prev_cfa_phase[sid]):
            await self._broadcast({
                'type': 'state_changed',
                'session_id': sid,
                'phase': session.cfa_phase,
                'state': session.cfa_state,
            })

    async def _diff_heartbeat(self, sid: str, session) -> None:
        if session.heartbeat_status != self._prev_heartbeat[sid]:
            await self._broadcast({
                'type': 'heartbeat',
                'session_id': sid,
                'status': session.heartbeat_status,
            })

    async def _diff_completion(self, sid: str, session, is_terminal: bool) -> None:
        prev_terminal = self._prev_cfa_state[sid] in _TERMINAL_STATES
        if is_terminal and not prev_terminal:
            await self._broadcast({
                'type': 'session_completed',
                'session_id': sid,
                'terminal_state': session.cfa_state,
            })
            if sid in self._buses:
                bus = self._buses.pop(sid)
                if self._bus_teardown:
                    self._bus_teardown(bus)
                bus.close()
