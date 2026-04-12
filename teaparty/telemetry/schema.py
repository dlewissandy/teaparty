"""DDL for the telemetry ``events`` table (Issue #405).

One append-only table. Indexed columns cover every query dimension the
aggregation helpers use: timestamp, scope, agent, session, event type.
The per-event ``data`` payload is a JSON blob — event types have
different shapes, and the indexed columns are enough for every
identified query.
"""
from __future__ import annotations

import sqlite3


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL    NOT NULL,
    scope       TEXT    NOT NULL,
    agent_name  TEXT,
    session_id  TEXT,
    event_type  TEXT    NOT NULL,
    data        TEXT    NOT NULL,
    is_aggregate INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_events_ts         ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_scope_ts   ON events(scope, ts);
CREATE INDEX IF NOT EXISTS idx_events_agent_ts   ON events(agent_name, ts);
CREATE INDEX IF NOT EXISTS idx_events_session    ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_type_ts    ON events(event_type, ts);
"""


def apply_schema(conn: sqlite3.Connection) -> None:
    """Create the events table and indexes if they do not exist.

    Idempotent — safe to call on every connection open.
    """
    conn.execute('PRAGMA journal_mode=WAL')
    conn.executescript(SCHEMA_SQL)
    conn.commit()
