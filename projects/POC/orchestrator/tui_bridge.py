"""Bridge between the Python orchestrator and the Textual TUI.

Provides TUIInputProvider (InputProvider backed by asyncio.Future)
and InProcessSession (bundles everything the TUI needs for a live session).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from projects.POC.orchestrator.events import EventBus, InputRequest


class TUIInputProvider:
    """InputProvider that awaits an asyncio.Future for each input request.

    The orchestrator calls ``await provider(request)`` which creates a
    Future and blocks.  The TUI resolves the Future when the user submits
    text via the Input widget.
    """

    def __init__(self) -> None:
        self._pending: asyncio.Future[str] | None = None
        self._current_request: InputRequest | None = None

    @property
    def is_waiting(self) -> bool:
        """True when the orchestrator is blocked waiting for input."""
        return self._pending is not None and not self._pending.done()

    @property
    def current_request(self) -> InputRequest | None:
        """The InputRequest the orchestrator is waiting on, or None."""
        return self._current_request if self.is_waiting else None

    async def __call__(self, request: InputRequest) -> str:
        """Called by the orchestrator — blocks until the TUI provides input."""
        loop = asyncio.get_running_loop()
        self._pending = loop.create_future()
        self._current_request = request
        try:
            return await self._pending
        finally:
            self._pending = None
            self._current_request = None

    def provide_response(self, text: str) -> bool:
        """Called by the TUI when the user submits input.

        Returns True if a pending request was resolved, False if nothing
        was waiting.
        """
        if self._pending is not None and not self._pending.done():
            self._pending.set_result(text)
            return True
        return False


@dataclass
class InProcessSession:
    """Everything the TUI needs for a session running in-process."""
    session_id: str
    project: str
    task: str
    event_bus: EventBus
    input_provider: TUIInputProvider
    run_task: asyncio.Task | None = None
