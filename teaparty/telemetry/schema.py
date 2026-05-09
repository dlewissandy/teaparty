"""DDL for the telemetry store.

The events table is the append-only log; sidecar tables hold data with
non-trivial dedupe contracts (per-message tokens, dispatch edges) and
the model-pricing reference table used to derive cost when the SDK does
not return ``cost_usd`` directly.

Issue #405 introduced the events table. Issue #431 added:
- six indexed columns on events (turn_id, conversation_id,
  parent_session_id, job_id, dispatch_depth, cost_source) and the
  matching indexes
- ``session_messages`` sidecar (PRIMARY KEY on (session_id, message_id))
- ``dispatch_edges`` sidecar
- ``model_pricing`` sidecar with seed rows for the current model lineup
"""
from __future__ import annotations

import sqlite3


# The events-table DDL is intentionally split from the index DDL: a
# pre-existing telemetry.db has the old shape and needs ALTER TABLE
# migrations to run BEFORE we create indexes that reference the new
# columns. Running the index CREATE before the migration would fail on
# upgrade with "no such column: conversation_id".
_EVENTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL    NOT NULL,
    scope       TEXT    NOT NULL,
    agent_name  TEXT,
    session_id  TEXT,
    event_type  TEXT    NOT NULL,
    data        TEXT    NOT NULL,
    is_aggregate INTEGER NOT NULL DEFAULT 0,
    turn_id            TEXT,
    conversation_id    TEXT,
    parent_session_id  TEXT,
    job_id             TEXT,
    dispatch_depth     INTEGER,
    cost_source        TEXT
);
"""

_EVENTS_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_events_ts             ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_scope_ts       ON events(scope, ts);
CREATE INDEX IF NOT EXISTS idx_events_agent_ts       ON events(agent_name, ts);
CREATE INDEX IF NOT EXISTS idx_events_session        ON events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_type_ts        ON events(event_type, ts);
CREATE INDEX IF NOT EXISTS idx_events_conversation   ON events(conversation_id);
CREATE INDEX IF NOT EXISTS idx_events_parent_session ON events(parent_session_id);
CREATE INDEX IF NOT EXISTS idx_events_job            ON events(job_id);
CREATE INDEX IF NOT EXISTS idx_events_turn_id        ON events(turn_id);
"""

_SIDECAR_SQL = """
-- Per-assistant-message dedupe (Issue #431).
-- One Claude API response emits multiple SDK 'assistant' events sharing
-- one message_id and one usage object. The PRIMARY KEY enforces
-- first-write-wins; INSERT OR IGNORE makes repeated writes a no-op.
CREATE TABLE IF NOT EXISTS session_messages (
    session_id        TEXT NOT NULL,
    message_id        TEXT NOT NULL,
    ts                REAL,
    model             TEXT,
    input_tokens      INTEGER,
    output_tokens     INTEGER,
    cache_read_tokens INTEGER,
    cache_5m_tokens   INTEGER,
    cache_1h_tokens   INTEGER,
    stop_reason       TEXT,
    PRIMARY KEY (session_id, message_id)
);
CREATE INDEX IF NOT EXISTS idx_session_messages_session ON session_messages(session_id);

-- Dispatch edges (Issue #431). One row per Delegate call.
CREATE TABLE IF NOT EXISTS dispatch_edges (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    parent_session_id  TEXT NOT NULL,
    child_session_id   TEXT NOT NULL,
    member             TEXT,
    skill              TEXT,
    task_summary       TEXT,
    ts                 REAL NOT NULL,
    job_id             TEXT
);
CREATE INDEX IF NOT EXISTS idx_dispatch_edges_parent ON dispatch_edges(parent_session_id);
CREATE INDEX IF NOT EXISTS idx_dispatch_edges_child  ON dispatch_edges(child_session_id);
CREATE INDEX IF NOT EXISTS idx_dispatch_edges_job    ON dispatch_edges(job_id);

-- Model pricing reference (Issue #431). Per-1M-token rates in USD.
-- Used to derive cost_usd when the SDK result does not carry it.
CREATE TABLE IF NOT EXISTS model_pricing (
    model             TEXT PRIMARY KEY,
    price_input       REAL NOT NULL,
    price_output      REAL NOT NULL,
    price_cache_read  REAL NOT NULL,
    price_cache_5m    REAL NOT NULL,
    price_cache_1h    REAL NOT NULL,
    notes             TEXT
);
"""


# Per-1M-token rates in USD as of 2026-Q1. Update when Anthropic adjusts
# pricing; analyses that derive cost_usd from tokens will pick up the
# new rate on the next aggregation pass.
_MODEL_PRICING_SEED = [
    ('claude-opus-4-7',    15.00, 75.00, 1.50, 18.75, 30.00,
     'Opus 4.7 published rates'),
    ('claude-sonnet-4-6',   3.00, 15.00, 0.30,  3.75,  6.00,
     'Sonnet 4.6 published rates'),
    ('claude-haiku-4-5',    1.00,  5.00, 0.10,  1.25,  2.00,
     'Haiku 4.5 published rates'),
    # Common short-form aliases the orchestrator emits in agent.json.
    ('opus',               15.00, 75.00, 1.50, 18.75, 30.00,
     'alias for the latest Opus'),
    ('sonnet',              3.00, 15.00, 0.30,  3.75,  6.00,
     'alias for the latest Sonnet'),
    ('haiku',               1.00,  5.00, 0.10,  1.25,  2.00,
     'alias for the latest Haiku'),
]


# Columns added to the events table after the original Issue #405 schema.
# Stored as a tuple so the migration loop and CREATE TABLE statement stay
# in lockstep — the same names appear in both places.
_EVENTS_ADDITIVE_COLUMNS = (
    ('turn_id',           'TEXT'),
    ('conversation_id',   'TEXT'),
    ('parent_session_id', 'TEXT'),
    ('job_id',            'TEXT'),
    ('dispatch_depth',    'INTEGER'),
    ('cost_source',       'TEXT'),
)


def apply_schema(conn: sqlite3.Connection) -> None:
    """Create / migrate the telemetry schema. Idempotent.

    Pre-existing telemetry.db files (Issue #405 schema) get the new
    columns and sidecar tables added without losing data; fresh
    databases get the full schema in one pass.
    """
    conn.execute('PRAGMA journal_mode=WAL')
    # 1. Create the events table at its current shape (no-op if it
    #    already exists with the old shape).
    conn.executescript(_EVENTS_TABLE_SQL)
    # 2. Migrate existing events tables that predate the Issue #431
    #    columns. ALTER TABLE ADD COLUMN is the idiomatic SQLite
    #    migration; OperationalError means the column already exists.
    for name, sql_type in _EVENTS_ADDITIVE_COLUMNS:
        try:
            conn.execute(f'ALTER TABLE events ADD COLUMN {name} {sql_type}')
        except sqlite3.OperationalError:
            pass
    # 3. Create indexes (now that all referenced columns exist).
    conn.executescript(_EVENTS_INDEX_SQL)
    # 4. Sidecar tables.
    conn.executescript(_SIDECAR_SQL)
    # 5. Seed model_pricing if empty. INSERT OR IGNORE preserves any
    #    operator overrides that may already be in the table.
    conn.executemany(
        'INSERT OR IGNORE INTO model_pricing '
        '(model, price_input, price_output, price_cache_read, '
        'price_cache_5m, price_cache_1h, notes) '
        'VALUES (?, ?, ?, ?, ?, ?, ?)',
        _MODEL_PRICING_SEED,
    )
    conn.commit()
