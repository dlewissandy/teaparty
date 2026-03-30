"""Filesystem state persistence for crash recovery and external monitoring.

Subscribes to the EventBus and writes state files that the bridge's
StateReader can poll for sessions it didn't start in-process.

Note: .cfa-state.json is written by engine._transition() via cfa_state.save_state(),
not by this writer (to preserve the full CfaState schema).

Files written:
  .heartbeat        — created on SESSION_STARTED, finalized on SESSION_COMPLETED (issue #149)
  session.log       — appended on state transitions, LOG events, and input events
  .stream-file      — pointer to current active stream file
"""
from __future__ import annotations

import os
from datetime import datetime

from orchestrator.events import Event, EventBus, EventType


class StateWriter:
    """Passive EventBus subscriber that writes filesystem state."""

    def __init__(self, infra_dir: str, event_bus: EventBus):
        self.infra_dir = infra_dir
        self.event_bus = event_bus
        self._session_log_path = os.path.join(infra_dir, 'session.log')

    async def start(self) -> None:
        os.makedirs(self.infra_dir, exist_ok=True)
        self.event_bus.subscribe(self._on_event)

    async def stop(self) -> None:
        self.event_bus.unsubscribe(self._on_event)

    async def _on_event(self, event: Event) -> None:
        if event.type == EventType.STATE_CHANGED:
            # engine._transition() already calls save_state() with the full
            # CfaState before publishing this event — don't overwrite it here
            # with the (incomplete) event data.
            self._log('STATE', f"{event.data.get('previous_state','')} → {event.data.get('state','')} [{event.data.get('action','')}]")
            # Clear overload sentinel — the phase is advancing again
            self._clear_overload_sentinel()
        elif event.type == EventType.SESSION_STARTED:
            self._write_running()
            self._log('SESSION', f"Started -- {event.data.get('task', '')}")
        elif event.type == EventType.SESSION_COMPLETED:
            self._remove_running()
            self._log('SESSION', f"Completed -- {event.data.get('terminal_state', '')}")
        elif event.type == EventType.PHASE_STARTED:
            phase = event.data.get('phase', '')
            self._write_stream_pointer(event.data.get('stream_file', ''))
            self._log('STATE', f"Phase started: {phase}")
        elif event.type == EventType.PHASE_COMPLETED:
            phase = event.data.get('phase', '')
            self._log('STATE', f"Phase completed: {phase}")
        elif event.type == EventType.LOG:
            category = event.data.get('category', 'INFO')
            message = event.data.get('message', '')
            self._log(category, message)
        elif event.type == EventType.INPUT_REQUESTED:
            self._log('STATE', f"Input requested: {event.data.get('state', '')}")
        elif event.type == EventType.INPUT_RECEIVED:
            self._log('HUMAN', event.data.get('response', '')[:200])
        elif event.type == EventType.API_OVERLOADED:
            retry = event.data.get('retry_count', '?')
            max_r = event.data.get('max_retries', '?')
            cooldown = event.data.get('cooldown_seconds', '?')
            phase = event.data.get('phase', '')
            self._log('OVERLOAD', f"API overloaded (529) — retry {retry}/{max_r} for {phase}, cooling down {cooldown}s")
            self._write_overload_sentinel(event.data)
        elif event.type == EventType.FAILURE:
            self._log('STATE', f"Failure: {event.data.get('reason', '')[:200]}")

    def _write_running(self) -> None:
        from orchestrator.heartbeat import create_heartbeat
        create_heartbeat(
            os.path.join(self.infra_dir, '.heartbeat'),
            role='session',
        )

    def _remove_running(self) -> None:
        from orchestrator.heartbeat import finalize_heartbeat
        hb_path = os.path.join(self.infra_dir, '.heartbeat')
        try:
            finalize_heartbeat(hb_path, 'completed')
        except FileNotFoundError:
            pass

    def _write_stream_pointer(self, stream_file: str) -> None:
        if stream_file:
            path = os.path.join(self.infra_dir, '.stream-file')
            with open(path, 'w') as f:
                f.write(stream_file)

    def _clear_overload_sentinel(self) -> None:
        """Remove .api-overloaded sentinel when the session advances."""
        path = os.path.join(self.infra_dir, '.api-overloaded')
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass

    def _write_overload_sentinel(self, data: dict) -> None:
        """Write .api-overloaded sentinel for bridge status display."""
        import json
        path = os.path.join(self.infra_dir, '.api-overloaded')
        try:
            with open(path, 'w') as f:
                json.dump(data, f)
        except OSError:
            pass

    def _log(self, category: str, message: str) -> None:
        timestamp = datetime.now().strftime('%H:%M:%S')
        line = f'[{timestamp}] {category:<8} | {message}\n'
        with open(self._session_log_path, 'a') as f:
            f.write(line)
