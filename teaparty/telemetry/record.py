"""Single write path for telemetry events (Issue #405).

``record_event`` is the only function that writes to ``telemetry.db``.
Every telemetry-producing call site in the codebase calls it. The
function is fire-and-forget from the caller's perspective: a write
failure is logged and swallowed — losing an event is preferable to
stalling a live agent.

The function also broadcasts a ``telemetry_event`` payload on the
bridge's WebSocket channel after the insert commits, so live consumers
(the stats bar, any dashboard) update in real time without polling. The
broadcast hook is optional: the bridge installs it at startup via
``set_broadcaster``; when the telemetry package is used from a CLI or
test without a running bridge, broadcast is a no-op and only the
SQLite write happens.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any, Awaitable, Callable, Optional

from teaparty.telemetry.schema import apply_schema


_log = logging.getLogger('teaparty.telemetry')

# ── Module state ─────────────────────────────────────────────────────────────
# record_event must work from any call site in the process. Rather than
# threading a database handle through every function signature, the module
# holds a single connection keyed off teaparty_home. The connection is opened
# lazily on first use (or explicitly via set_teaparty_home / configure).
#
# SQLite connections are not safe across threads by default, so we guard with
# a lock and allow cross-thread access via check_same_thread=False. The write
# path is a single INSERT under WAL, so contention is negligible.

_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None
_db_path: Optional[str] = None

# Broadcast hook. Installed by bridge/server.py at startup. Signature:
#
#     broadcaster(payload: dict) -> None | Awaitable
#
# If the hook is an async callable, record_event schedules it on the stored
# event loop via call_soon_threadsafe; otherwise it calls synchronously.
_broadcaster: Optional[Callable[[dict], Any]] = None
_broadcaster_loop: Optional[asyncio.AbstractEventLoop] = None


def set_teaparty_home(teaparty_home: str) -> None:
    """Point the telemetry store at ``{teaparty_home}/telemetry.db``.

    Safe to call more than once; reopens the connection if the path
    changes. Creates the parent directory and applies the schema.
    """
    global _conn, _db_path
    db_path = os.path.join(teaparty_home, 'telemetry.db')
    with _lock:
        if _conn is not None and _db_path == db_path:
            return
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
        os.makedirs(teaparty_home, exist_ok=True)
        _conn = sqlite3.connect(db_path, check_same_thread=False)
        _db_path = db_path
        apply_schema(_conn)


def set_broadcaster(
    broadcaster: Optional[Callable[[dict], Any]],
    loop: Optional[asyncio.AbstractEventLoop] = None,
) -> None:
    """Install (or clear) the WebSocket broadcast hook.

    The bridge server calls this during ``_on_startup`` with the local
    ``broadcast`` closure and the running event loop. ``record_event``
    will schedule broadcasts on that loop so the closure can fan them
    out to every connected WebSocket client.

    Pass ``None`` to clear the hook (tests, CLI teardown).
    """
    global _broadcaster, _broadcaster_loop
    _broadcaster = broadcaster
    _broadcaster_loop = loop


def configure(
    *,
    teaparty_home: str,
    broadcaster: Optional[Callable[[dict], Any]] = None,
    loop: Optional[asyncio.AbstractEventLoop] = None,
) -> None:
    """Convenience: set both the DB path and the broadcaster at once."""
    set_teaparty_home(teaparty_home)
    if broadcaster is not None:
        set_broadcaster(broadcaster, loop)


def reset_for_tests() -> None:
    """Close the connection and clear the broadcaster.

    Tests call this in ``tearDown`` so successive cases do not share a
    connection against a since-deleted temp directory.
    """
    global _conn, _db_path, _broadcaster, _broadcaster_loop
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
        _conn = None
        _db_path = None
    _broadcaster = None
    _broadcaster_loop = None


def _ensure_conn() -> Optional[sqlite3.Connection]:
    """Return the open connection, or ``None`` if unconfigured."""
    if _conn is not None:
        return _conn
    # Fall back to TEAPARTY_HOME env so call sites that run before the
    # bridge explicitly configures us still write to the right file.
    home = os.environ.get('TEAPARTY_HOME')
    if home:
        try:
            set_teaparty_home(home)
        except Exception:
            return None
    return _conn


def record_event(
    event_type: str,
    *,
    scope: str,
    agent_name: Optional[str] = None,
    session_id: Optional[str] = None,
    data: Optional[dict] = None,
    ts: Optional[float] = None,
    turn_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    parent_session_id: Optional[str] = None,
    job_id: Optional[str] = None,
    dispatch_depth: Optional[int] = None,
    cost_source: Optional[str] = None,
) -> Optional[int]:
    """Record a telemetry event. Returns the inserted row id, or ``None``.

    Writes to ``telemetry.db`` and broadcasts the event on the WebSocket
    subscription channel so live consumers can react immediately.
    Fire-and-forget from the caller's perspective — a write failure is
    logged but does not raise. Losing an event is preferable to
    stalling the call site.

    ``scope`` is mandatory — every event belongs to either
    ``'management'`` or a project slug. ``agent_name`` and
    ``session_id`` are nullable for non-agent events (system start,
    cron, human-triggered config edits).

    The dispatch-tree linkage kwargs (``turn_id``, ``conversation_id``,
    ``parent_session_id``, ``job_id``, ``dispatch_depth``, ``cost_source``)
    are persisted as indexed columns on the events table so analyses can
    walk the call tree without joining to the bus.
    """
    if ts is None:
        ts = time.time()
    data_json = json.dumps(data or {}, default=str)

    row_id: Optional[int] = None
    conn = _ensure_conn()
    if conn is None:
        _log.debug(
            'telemetry.record_event: no teaparty_home configured, dropping %s',
            event_type,
        )
    else:
        try:
            with _lock:
                cur = conn.execute(
                    'INSERT INTO events '
                    '(ts, scope, agent_name, session_id, event_type, data, '
                    ' turn_id, conversation_id, parent_session_id, '
                    ' job_id, dispatch_depth, cost_source) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (ts, scope, agent_name, session_id, event_type, data_json,
                     turn_id, conversation_id, parent_session_id,
                     job_id, dispatch_depth, cost_source),
                )
                row_id = cur.lastrowid
                conn.commit()
        except Exception:
            _log.warning(
                'telemetry.record_event: write failed for %s',
                event_type, exc_info=True,
            )

    # Broadcast after commit so any consumer that receives the WS message
    # and turns around to query the DB will actually see the row.
    _broadcast({
        'type': 'telemetry_event',
        'id': row_id,
        'event_type': event_type,
        'scope': scope,
        'agent_name': agent_name,
        'session_id': session_id,
        'ts': ts,
        'data': data or {},
        'turn_id': turn_id,
        'conversation_id': conversation_id,
        'parent_session_id': parent_session_id,
        'job_id': job_id,
        'dispatch_depth': dispatch_depth,
        'cost_source': cost_source,
    })

    return row_id


def record_message(
    *,
    session_id: str,
    message_id: str,
    ts: Optional[float] = None,
    model: Optional[str] = None,
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    cache_read_tokens: Optional[int] = None,
    cache_5m_tokens: Optional[int] = None,
    cache_1h_tokens: Optional[int] = None,
    stop_reason: Optional[str] = None,
) -> bool:
    """Record one assistant message in the dedupe sidecar.

    Returns ``True`` when this call inserted a new row, ``False`` when an
    earlier write already claimed ``(session_id, message_id)``. The
    PRIMARY KEY contract is the dedupe — a single Claude API response
    emits multiple SDK ``assistant`` events sharing one message_id and
    one usage object. First-write-wins; later writes are silently
    discarded by ``INSERT OR IGNORE``.

    The function also emits a ``MESSAGE_RECORDED`` event for the live
    broadcaster (so dashboards see it in real time), but the
    authoritative dedupe contract is the sidecar table.
    """
    if ts is None:
        ts = time.time()
    conn = _ensure_conn()
    inserted = False
    if conn is not None:
        try:
            with _lock:
                cur = conn.execute(
                    'INSERT OR IGNORE INTO session_messages '
                    '(session_id, message_id, ts, model, input_tokens, '
                    ' output_tokens, cache_read_tokens, cache_5m_tokens, '
                    ' cache_1h_tokens, stop_reason) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (session_id, message_id, ts, model, input_tokens,
                     output_tokens, cache_read_tokens, cache_5m_tokens,
                     cache_1h_tokens, stop_reason),
                )
                inserted = cur.rowcount > 0
                conn.commit()
        except Exception:
            _log.warning(
                'telemetry.record_message: write failed for %s/%s',
                session_id, message_id, exc_info=True,
            )

    if inserted:
        # Only emit the event on a fresh insert — repeated writes for
        # the same message_id should not flood the broadcaster. Pull
        # scope / job_id / parent linkage from the launch's contextvars
        # so per-project rollups can filter by scope.
        from teaparty.telemetry.events import MESSAGE_RECORDED
        try:
            from teaparty.mcp.registry import (
                current_scope as _ctx_scope,
                current_job_id as _ctx_job,
                current_parent_session_id as _ctx_parent_sid,
            )
            _scope = _ctx_scope.get('management') or 'management'
            _job_id = _ctx_job.get('') or None
            _parent_sid = _ctx_parent_sid.get('') or None
        except Exception:
            _scope = 'management'
            _job_id = None
            _parent_sid = None
        record_event(
            MESSAGE_RECORDED, scope=_scope,
            session_id=session_id, ts=ts,
            data={
                'message_id': message_id,
                'model': model,
                'input_tokens': input_tokens,
                'output_tokens': output_tokens,
                'cache_read_tokens': cache_read_tokens,
                'cache_5m_tokens': cache_5m_tokens,
                'cache_1h_tokens': cache_1h_tokens,
                'stop_reason': stop_reason,
            },
            parent_session_id=_parent_sid,
            job_id=_job_id,
        )
    return inserted


def record_dispatch_edge(
    *,
    parent_session_id: str,
    child_session_id: str,
    member: Optional[str] = None,
    skill: Optional[str] = None,
    task_summary: Optional[str] = None,
    ts: Optional[float] = None,
    job_id: Optional[str] = None,
) -> Optional[int]:
    """Record a Delegate edge in the dispatch_edges sidecar.

    One row per Delegate call. The companion ``DISPATCH_EDGE`` event in
    the events table carries the same data and lets live broadcasters
    update without polling the sidecar.
    """
    if ts is None:
        ts = time.time()
    conn = _ensure_conn()
    row_id: Optional[int] = None
    if conn is not None:
        try:
            with _lock:
                cur = conn.execute(
                    'INSERT INTO dispatch_edges '
                    '(parent_session_id, child_session_id, member, skill, '
                    ' task_summary, ts, job_id) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?)',
                    (parent_session_id, child_session_id, member, skill,
                     task_summary, ts, job_id),
                )
                row_id = cur.lastrowid
                conn.commit()
        except Exception:
            _log.warning(
                'telemetry.record_dispatch_edge: write failed for %s -> %s',
                parent_session_id, child_session_id, exc_info=True,
            )

    from teaparty.telemetry.events import DISPATCH_EDGE
    record_event(
        DISPATCH_EDGE, scope='management',
        session_id=parent_session_id, ts=ts,
        data={
            'parent_session_id': parent_session_id,
            'child_session_id': child_session_id,
            'member': member,
            'skill': skill,
            'task_summary': task_summary,
            'job_id': job_id,
        },
        parent_session_id=parent_session_id,
        job_id=job_id,
    )
    return row_id


def _broadcast(payload: dict) -> None:
    """Fire the broadcast hook, if one is installed. Never raises."""
    broadcaster = _broadcaster
    if broadcaster is None:
        return
    try:
        result = broadcaster(payload)
        # If the hook is async, schedule it on the stored loop without
        # blocking the caller. Callers on the loop thread can simply
        # await the returned coroutine themselves, but record_event is
        # sync and cannot.
        if asyncio.iscoroutine(result):
            loop = _broadcaster_loop
            if loop is not None and not loop.is_closed():
                try:
                    asyncio.run_coroutine_threadsafe(result, loop)
                except Exception:
                    _log.debug(
                        'telemetry.broadcast: run_coroutine_threadsafe failed',
                        exc_info=True,
                    )
            else:
                # Nothing we can do with the coroutine — close it so it
                # does not trigger "coroutine was never awaited".
                try:
                    result.close()
                except Exception:
                    pass
    except Exception:
        _log.debug('telemetry.broadcast: handler raised', exc_info=True)


def delete_scope(scope: str) -> int:
    """Delete all telemetry events for a scope. Returns the number of rows deleted."""
    conn = _ensure_conn()
    if conn is None:
        return 0
    with _lock:
        try:
            cur = conn.execute('DELETE FROM events WHERE scope = ?', (scope,))
            conn.commit()
            return cur.rowcount
        except Exception:
            _log.warning('telemetry.delete_scope: failed for %s', scope, exc_info=True)
            return 0
