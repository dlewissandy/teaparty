"""Async event bus for orchestrator ↔ bridge communication.

The orchestrator publishes events; the bridge (or CLI) subscribes.
Replaces filesystem polling for sessions started in-process.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable

_log = logging.getLogger('teaparty.messaging.bus')


class EventType(Enum):
    STATE_CHANGED = 'state_changed'
    STREAM_DATA = 'stream_data'
    INPUT_REQUESTED = 'input_requested'
    INPUT_RECEIVED = 'input_received'
    PHASE_STARTED = 'phase_started'
    PHASE_COMPLETED = 'phase_completed'
    DISPATCH_STARTED = 'dispatch_started'
    DISPATCH_COMPLETED = 'dispatch_completed'
    SESSION_STARTED = 'session_started'
    SESSION_COMPLETED = 'session_completed'
    WITHDRAW = 'withdraw'
    INTERVENE = 'intervene'
    STREAM_ERROR = 'stream_error'
    FAILURE = 'failure'
    LOG = 'log'
    API_OVERLOADED = 'api_overloaded'
    COST_WARNING = 'cost_warning'
    COST_LIMIT = 'cost_limit'
    CONTEXT_WARNING = 'context_warning'
    TURN_COST = 'turn_cost'  # Per-actor-turn stats: total_cost_usd, input_tokens, output_tokens, duration_ms


@dataclass
class Event:
    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    session_id: str = ''
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()


@dataclass
class InputRequest:
    """Describes what the orchestrator needs from the human."""
    type: str          # 'approval', 'prompt', 'dialog', 'failure'
    state: str         # CfA state name (e.g. 'INTENT_ASSERT')
    artifact: str = '' # path to artifact being reviewed
    bridge_text: str = ''  # conversational summary for the human
    options: str = ''  # human-readable options string


class EventBus:
    """In-process async pub/sub.  Thread-safe for Textual's worker model."""

    def __init__(self):
        self._subscribers: list[Callable[[Event], Awaitable[None]]] = []

    def subscribe(self, callback: Callable[[Event], Awaitable[None]]) -> None:
        if callback not in self._subscribers:
            self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[Event], Awaitable[None]]) -> None:
        try:
            self._subscribers.remove(callback)
        except ValueError:
            pass

    async def publish(self, event: Event) -> None:
        for cb in list(self._subscribers):
            try:
                await cb(event)
            except Exception:
                _log.warning('EventBus subscriber %r failed', cb, exc_info=True)
