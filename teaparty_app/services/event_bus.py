"""Minimal per-conversation pub/sub for SSE push.

Leaf dependency — no teaparty imports.  Each subscriber gets its own
``asyncio.Queue``.  Publishers iterate all subscribers for a conversation
and enqueue.  Thread-safe via ``loop.call_soon_threadsafe``.
"""

from __future__ import annotations

import asyncio
import logging
import threading

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_subscribers: dict[str, dict[int, asyncio.Queue]] = {}
_next_handle = 0


def subscribe(conversation_id: str) -> tuple[asyncio.Queue, int]:
    """Register a new subscriber for *conversation_id*.

    Returns ``(queue, handle)`` — the handle is used to unsubscribe.
    """
    global _next_handle
    q: asyncio.Queue = asyncio.Queue()
    with _lock:
        _next_handle += 1
        handle = _next_handle
        _subscribers.setdefault(conversation_id, {})[handle] = q
    return q, handle


def unsubscribe(conversation_id: str, handle: int) -> None:
    """Remove a subscriber."""
    with _lock:
        subs = _subscribers.get(conversation_id)
        if subs:
            subs.pop(handle, None)
            if not subs:
                del _subscribers[conversation_id]


def publish(conversation_id: str, event: dict) -> None:
    """Enqueue *event* to all subscribers of *conversation_id*.

    Thread-safe: if called from a non-async thread, uses
    ``loop.call_soon_threadsafe`` to schedule the put.
    """
    with _lock:
        subs = _subscribers.get(conversation_id)
        if not subs:
            return
        queues = list(subs.values())

    for q in queues:
        try:
            loop = q._loop  # type: ignore[attr-defined]
        except AttributeError:
            loop = None

        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(q.put_nowait, event)
        else:
            try:
                q.put_nowait(event)
            except Exception:
                logger.debug("Failed to enqueue event for conversation %s", conversation_id)
