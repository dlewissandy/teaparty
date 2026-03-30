"""FIFO gate queue for concurrent proxy gate processing.

When dispatches run in parallel, multiple gates may arrive concurrently.
The proxy processes them one at a time (one brain, serial attention).
This queue provides FIFO ordering with thread-safe enqueue/dequeue.

Issue #202.
"""
from __future__ import annotations

import collections
import threading
from dataclasses import dataclass


@dataclass
class GateRequest:
    """A gate request waiting to be processed by the proxy."""
    state: str
    team: str
    priority: int = 0


class GateQueue:
    """Thread-safe FIFO queue for pending gate requests.

    Enqueue from any thread (dispatch workers). Dequeue from the proxy's
    processing loop. The proxy processes one gate at a time — what it
    learns from dispatch A is available when it processes dispatch B.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queue: collections.deque[GateRequest] = collections.deque()

    def enqueue(self, request: GateRequest) -> None:
        """Add a gate request to the queue."""
        with self._lock:
            self._queue.append(request)

    def dequeue(self) -> GateRequest | None:
        """Remove and return the next gate request, or None if empty."""
        with self._lock:
            if self._queue:
                return self._queue.popleft()
            return None

    def has_pending(self) -> bool:
        """Check whether any gates are waiting."""
        with self._lock:
            return len(self._queue) > 0

    def size(self) -> int:
        """Return the number of pending gates."""
        with self._lock:
            return len(self._queue)
