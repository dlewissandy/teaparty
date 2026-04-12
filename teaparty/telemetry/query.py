"""Single read path for telemetry events (Issue #405).

``query_events`` is the only function that runs SELECTs against the
telemetry ``events`` table. Every aggregation helper below is a thin
wrapper that composes filters and walks the returned events — no SQL
lives outside this module.

Adding a new stat is a new helper on top of ``query_events``; removing
one is deleting the helper. The underlying storage never changes.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from teaparty.telemetry import events as E
from teaparty.telemetry import record as _record


@dataclass(frozen=True)
class Event:
    """Materialized event row returned by ``query_events``."""
    id: int
    ts: float
    scope: str
    agent_name: Optional[str]
    session_id: Optional[str]
    event_type: str
    data: dict

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> 'Event':
        try:
            data = json.loads(row['data']) if row['data'] else {}
        except (ValueError, TypeError):
            data = {}
        return cls(
            id=row['id'],
            ts=row['ts'],
            scope=row['scope'],
            agent_name=row['agent_name'],
            session_id=row['session_id'],
            event_type=row['event_type'],
            data=data,
        )


def query_events(
    *,
    scope: Optional[str] = None,
    agent: Optional[str] = None,
    session: Optional[str] = None,
    event_type: Optional[str] = None,
    event_types: Optional[Iterable[str]] = None,
    start_ts: Optional[float] = None,
    end_ts: Optional[float] = None,
    limit: Optional[int] = None,
) -> list[Event]:
    """Return events matching the given filters, ordered by ts ASC.

    Every filter is optional; omitting all of them returns every event.
    ``event_type`` and ``event_types`` are mutually compatible — use the
    plural form when you want an OR over several types.
    """
    conn = _record._ensure_conn()  # noqa: SLF001 — internal helper by design
    if conn is None:
        return []

    conn.row_factory = sqlite3.Row

    where: list[str] = []
    params: list[Any] = []
    if scope is not None:
        where.append('scope = ?')
        params.append(scope)
    if agent is not None:
        where.append('agent_name = ?')
        params.append(agent)
    if session is not None:
        where.append('session_id = ?')
        params.append(session)
    if event_type is not None:
        where.append('event_type = ?')
        params.append(event_type)
    if event_types is not None:
        types = list(event_types)
        if types:
            placeholders = ','.join('?' for _ in types)
            where.append(f'event_type IN ({placeholders})')
            params.extend(types)
    if start_ts is not None:
        where.append('ts >= ?')
        params.append(start_ts)
    if end_ts is not None:
        where.append('ts <= ?')
        params.append(end_ts)

    sql = 'SELECT * FROM events'
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    sql += ' ORDER BY ts ASC, id ASC'
    if limit is not None:
        sql += ' LIMIT ?'
        params.append(limit)

    with _record._lock:  # noqa: SLF001
        rows = conn.execute(sql, params).fetchall()
    return [Event.from_row(r) for r in rows]


# ── Aggregation helpers ─────────────────────────────────────────────────────


def total_cost(
    scope: Optional[str] = None,
    time_range: Optional[tuple[float, float]] = None,
) -> float:
    """Sum ``cost_usd`` across every ``turn_complete`` in range."""
    start, end = (time_range or (None, None))
    events = query_events(
        event_type=E.TURN_COMPLETE, scope=scope,
        start_ts=start, end_ts=end,
    )
    return round(sum(float(e.data.get('cost_usd', 0.0) or 0.0) for e in events), 6)


def turn_count(
    scope: Optional[str] = None,
    agent: Optional[str] = None,
    time_range: Optional[tuple[float, float]] = None,
) -> int:
    """Count ``turn_complete`` events in range."""
    start, end = (time_range or (None, None))
    return len(query_events(
        event_type=E.TURN_COMPLETE, scope=scope, agent=agent,
        start_ts=start, end_ts=end,
    ))


def active_sessions(scope: Optional[str] = None) -> list[str]:
    """Return session ids with a ``session_create`` but no ``session_complete``
    / ``session_closed`` / ``session_withdrawn`` / ``session_timed_out``
    / ``session_abandoned`` event."""
    terminal = {
        E.SESSION_COMPLETE, E.SESSION_CLOSED, E.SESSION_WITHDRAWN,
        E.SESSION_TIMED_OUT, E.SESSION_ABANDONED,
    }
    created = {
        e.session_id for e in query_events(
            event_type=E.SESSION_CREATE, scope=scope,
        )
        if e.session_id
    }
    closed = {
        e.session_id for e in query_events(
            event_types=list(terminal), scope=scope,
        )
        if e.session_id
    }
    return sorted(created - closed)


def gates_awaiting_input(scope: Optional[str] = None) -> list[dict]:
    """Return gates that have a ``gate_input_requested`` without a
    matching later ``gate_input_received`` for the same session."""
    requested = query_events(
        event_type=E.GATE_INPUT_REQUESTED, scope=scope,
    )
    received = query_events(
        event_type=E.GATE_INPUT_RECEIVED, scope=scope,
    )
    # Pair by (session_id, gate_type) in timestamp order.
    open_gates: dict[tuple[str, str], Event] = {}
    for ev in requested:
        key = (ev.session_id or '', str(ev.data.get('gate_type', '')))
        open_gates[key] = ev
    for ev in received:
        key = (ev.session_id or '', str(ev.data.get('gate_type', '')))
        open_gates.pop(key, None)
    return [
        {
            'session_id': ev.session_id,
            'gate_type': ev.data.get('gate_type'),
            'ts': ev.ts,
            'question_len': ev.data.get('question_len', 0),
        }
        for ev in open_gates.values()
    ]


def backtrack_count(
    scope: Optional[str] = None,
    kind: Optional[str] = None,
    time_range: Optional[tuple[float, float]] = None,
) -> int:
    """Count ``phase_backtrack`` events, optionally filtered by kind."""
    start, end = (time_range or (None, None))
    events = query_events(
        event_type=E.PHASE_BACKTRACK, scope=scope,
        start_ts=start, end_ts=end,
    )
    if kind is not None:
        events = [e for e in events if e.data.get('kind') == kind]
    return len(events)


def backtrack_cost(
    scope: Optional[str] = None,
    kind: Optional[str] = None,
    time_range: Optional[tuple[float, float]] = None,
) -> float:
    """Sum ``cost_of_work_being_discarded`` across matching backtracks."""
    start, end = (time_range or (None, None))
    events = query_events(
        event_type=E.PHASE_BACKTRACK, scope=scope,
        start_ts=start, end_ts=end,
    )
    if kind is not None:
        events = [e for e in events if e.data.get('kind') == kind]
    return round(
        sum(float(e.data.get('cost_of_work_being_discarded', 0.0) or 0.0)
            for e in events),
        6,
    )


def phase_distribution(
    scope: Optional[str] = None,
    time_range: Optional[tuple[float, float]] = None,
) -> dict[str, int]:
    """Histogram of entered phases — counts ``new_phase`` over all
    ``phase_changed`` events in range."""
    start, end = (time_range or (None, None))
    events = query_events(
        event_type=E.PHASE_CHANGED, scope=scope,
        start_ts=start, end_ts=end,
    )
    counts: dict[str, int] = {}
    for ev in events:
        phase = str(ev.data.get('new_phase', ''))
        if phase:
            counts[phase] = counts.get(phase, 0) + 1
    return counts


def escalation_stats(
    scope: Optional[str] = None,
    time_range: Optional[tuple[float, float]] = None,
) -> dict:
    """Return counts by stage of the escalation chain."""
    start, end = (time_range or (None, None))
    def n(t: str) -> int:
        return len(query_events(
            event_type=t, scope=scope, start_ts=start, end_ts=end,
        ))
    return {
        'requested':             n(E.ESCALATION_REQUESTED),
        'proxy_considered':      n(E.PROXY_CONSIDERED),
        'proxy_answered':        n(E.PROXY_ANSWERED),
        'escalated_to_human':    n(E.PROXY_ESCALATED_TO_HUMAN),
        'human_answered':        n(E.HUMAN_ANSWERED),
        'resolved':              n(E.ESCALATION_RESOLVED),
    }


def proxy_answer_rate(
    scope: Optional[str] = None,
    time_range: Optional[tuple[float, float]] = None,
) -> dict:
    """Fraction of resolved escalations answered by a proxy vs. a human."""
    start, end = (time_range or (None, None))
    resolved = query_events(
        event_type=E.ESCALATION_RESOLVED, scope=scope,
        start_ts=start, end_ts=end,
    )
    total = len(resolved)
    by_proxy = sum(
        1 for e in resolved
        if e.data.get('final_answer_source') == 'proxy'
    )
    by_human = total - by_proxy
    return {
        'total':      total,
        'by_proxy':   by_proxy,
        'by_human':   by_human,
        'proxy_rate': (by_proxy / total) if total else 0.0,
    }


def withdrawal_phase_distribution(
    scope: Optional[str] = None,
    time_range: Optional[tuple[float, float]] = None,
) -> dict[str, int]:
    """Histogram of ``phase_at_withdrawal`` across ``session_withdrawn``."""
    start, end = (time_range or (None, None))
    events = query_events(
        event_type=E.SESSION_WITHDRAWN, scope=scope,
        start_ts=start, end_ts=end,
    )
    counts: dict[str, int] = {}
    for ev in events:
        phase = str(ev.data.get('phase_at_withdrawal', ''))
        if phase:
            counts[phase] = counts.get(phase, 0) + 1
    return counts
