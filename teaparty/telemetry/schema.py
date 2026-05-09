"""DDL for the telemetry store.

The events table is the append-only log; sidecar tables hold data with
non-trivial dedupe contracts (per-message tokens, dispatch edges) and
the model-pricing reference table used to derive cost when the SDK does
not return ``cost_usd`` directly. Spec-aligned views expose the
analysis-shape queries (agent_sessions catalog, phase_intervals,
session_summary, job_cost_summary, prompt_groups) directly over the
events log so dashboards and plot scripts can run against telemetry.db
without a separate analysis.db build step.

Issue #405 introduced the events table. Issue #431 added:
- six indexed columns on events (turn_id, conversation_id,
  parent_session_id, job_id, dispatch_depth, cost_source) and the
  matching indexes
- ``session_messages`` sidecar (PRIMARY KEY on (session_id, message_id))
- ``dispatch_edges`` sidecar
- ``model_pricing`` sidecar with seed rows for the current model lineup
- ``jobs``, ``session_turns``, ``agent_sessions``, ``phase_intervals``,
  ``session_summary``, ``job_phase_summary``, ``job_cost_summary``,
  ``prompt_groups`` as SQL views over the above
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


_VIEWS_SQL = """
-- ─────────────────────────────────────────────────────────────────────
-- Spec-aligned views (Issue #431).
--
-- Each view extracts a flat shape from the events log + JSON data
-- payload so dashboards and plot scripts can query telemetry.db with
-- the same SQL the canonical spec's analysis.db expects. SQLite views
-- are virtual — no storage cost, no migration cost, no
-- duplication. Replacing or extending a view is DROP + CREATE.
--
-- Naming follows the canonical spec at
-- ~/git/dlewissandy.github.io/site/blog/early-dialog-matters/
-- build_analysis_db.py::init_schema(). The plot scripts run
-- unchanged against these views.
-- ─────────────────────────────────────────────────────────────────────

DROP VIEW IF EXISTS jobs;
DROP VIEW IF EXISTS session_turns;
DROP VIEW IF EXISTS agent_sessions;
DROP VIEW IF EXISTS phase_intervals;
DROP VIEW IF EXISTS session_summary;
DROP VIEW IF EXISTS job_phase_summary;
DROP VIEW IF EXISTS job_cost_summary;
DROP VIEW IF EXISTS prompt_groups;
DROP VIEW IF EXISTS gates;
DROP VIEW IF EXISTS gate_dialog_summary;

-- One row per job, drawn from JOB_CREATED events. The plot scripts
-- use prompt_hash to group byte-identical reruns; first_ts / last_ts
-- come from the messages sidecar's per-job timestamp range.
CREATE VIEW jobs AS
SELECT
    json_extract(data, '$.job_id')          AS job_id,
    json_extract(data, '$.project')         AS project,
    json_extract(data, '$.slug')            AS slug,
    json_extract(data, '$.classification')  AS classification,
    json_extract(data, '$.prompt_text')     AS prompt_text,
    json_extract(data, '$.prompt_hash')     AS prompt_hash,
    json_extract(data, '$.prompt_bytes')    AS prompt_bytes,
    json_extract(data, '$.branch')          AS branch,
    json_extract(data, '$.status')          AS status,
    json_extract(data, '$.created_at')      AS created_at,
    json_extract(data, '$.issue')           AS issue,
    ts                                      AS ts,
    session_id                              AS session_id
FROM events
WHERE event_type = 'job_created';

-- One row per teaparty turn (i.e., per launch). This is the canonical
-- per-turn record. Source priority:
--   stream_result = orchestrator-side (authoritative)
--   bridge_turn   = bridge-side (authoritative for hex dispatch ids)
--   computed      = derived from tokens × pricing when neither exists
-- ``cost_source`` is the indexed column attribution.
CREATE VIEW session_turns AS
SELECT
    id,
    session_id,
    ts,
    scope,
    agent_name,
    turn_id,
    conversation_id,
    parent_session_id,
    job_id,
    dispatch_depth,
    cost_source,
    CAST(json_extract(data, '$.cost_usd')        AS REAL)    AS cost_usd,
    CAST(json_extract(data, '$.duration_ms')     AS INTEGER) AS duration_ms,
    CAST(json_extract(data, '$.duration_api_ms') AS INTEGER) AS duration_api_ms,
    CAST(json_extract(data, '$.wall_duration_ms')AS INTEGER) AS wall_duration_ms,
    CAST(json_extract(data, '$.num_turns')       AS INTEGER) AS num_turns,
    CAST(json_extract(data, '$.input_tokens')    AS INTEGER) AS input_tokens,
    CAST(json_extract(data, '$.output_tokens')   AS INTEGER) AS output_tokens,
    CAST(json_extract(data, '$.cache_read_tokens')   AS INTEGER) AS cache_read_tokens,
    CAST(json_extract(data, '$.cache_create_tokens') AS INTEGER) AS cache_create_tokens,
    CAST(json_extract(data, '$.cache_5m_tokens') AS INTEGER) AS cache_5m_tokens,
    CAST(json_extract(data, '$.cache_1h_tokens') AS INTEGER) AS cache_1h_tokens,
    json_extract(data, '$.model')               AS model,
    json_extract(data, '$.claude_session_uuid') AS claude_session_uuid,
    json_extract(data, '$.stop_reason')         AS stop_reason,
    json_extract(data, '$.is_error')            AS is_error,
    json_extract(data, '$.api_error_status')    AS api_error_status,
    CAST(json_extract(data, '$.exit_code')       AS INTEGER) AS exit_code,
    CAST(json_extract(data, '$.response_text_len') AS INTEGER) AS response_text_len,
    json_extract(data, '$.tools_called')        AS tools_called
FROM events
WHERE event_type = 'turn_complete';

-- Catalog of distinct sessions, derived from the events log. Role is
-- inferred from agent_name and dispatch_depth: depth 0 leads are
-- project_lead, depth 1 leads are team_lead, the proxy and
-- office-manager are special. Specialists are everything else.
CREATE VIEW agent_sessions AS
SELECT
    e.session_id,
    MAX(e.scope)             AS scope,
    MAX(e.agent_name)        AS agent_name,
    MAX(e.parent_session_id) AS parent_session_id,
    MAX(e.job_id)            AS job_id,
    MAX(e.dispatch_depth)    AS dispatch_depth,
    MAX(e.conversation_id)   AS conversation_id,
    MIN(e.ts)                AS first_ts,
    MAX(e.ts)                AS last_ts,
    -- Role inference. Lead agent names ending in '-lead' or matching
    -- known leads count as leads at their dispatch depth; proxy and
    -- management agents have explicit roles.
    CASE
        WHEN MAX(e.agent_name) = 'proxy'                      THEN 'proxy'
        WHEN MAX(e.agent_name) IN ('office-manager','human')  THEN 'management'
        WHEN MAX(e.dispatch_depth) IS NULL                    THEN 'unknown'
        WHEN MAX(e.dispatch_depth) = 0                        THEN 'project_lead'
        WHEN MAX(e.dispatch_depth) = 1
             AND (MAX(e.agent_name) LIKE '%-lead'
                  OR MAX(e.agent_name) LIKE '%-manager')      THEN 'team_lead'
        WHEN MAX(e.agent_name) LIKE '%-lead'                  THEN 'team_lead'
        ELSE 'specialist'
    END AS role,
    -- Pull model and SDK uuid from the most recent TURN_COMPLETE.
    (SELECT json_extract(t.data, '$.model')
       FROM events t
       WHERE t.session_id = e.session_id
         AND t.event_type = 'turn_complete'
       ORDER BY t.ts DESC LIMIT 1) AS model,
    (SELECT json_extract(t.data, '$.claude_session_uuid')
       FROM events t
       WHERE t.session_id = e.session_id
         AND t.event_type = 'turn_complete'
       ORDER BY t.ts DESC LIMIT 1) AS claude_session_uuid
FROM events e
WHERE e.session_id IS NOT NULL
GROUP BY e.session_id;

-- Phase intervals via the LEAD window function: each PHASE_CHANGED
-- event opens a phase; the next PHASE_CHANGED on the same session
-- closes it. The spec needs ~60 lines of Python to derive this from
-- a four-source merge — telemetry's single canonical event log
-- collapses it to one window.
CREATE VIEW phase_intervals AS
SELECT
    id                                            AS source_event_id,
    session_id,
    scope,
    ts                                            AS start_ts,
    LEAD(ts) OVER (PARTITION BY session_id ORDER BY ts, id) AS end_ts,
    json_extract(data, '$.new_phase')             AS phase,
    json_extract(data, '$.new_state')             AS new_state,
    json_extract(data, '$.old_state')             AS old_state,
    json_extract(data, '$.target_state')          AS target_state,
    json_extract(data, '$.action')                AS action,
    json_extract(data, '$.actor')                 AS actor
FROM events
WHERE event_type = 'phase_changed';

-- Per-session token / cost / duration rollup.
CREATE VIEW session_summary AS
SELECT
    a.session_id,
    a.job_id,
    a.parent_session_id,
    a.agent_name,
    a.role,
    a.dispatch_depth                          AS depth,
    a.model,
    a.scope,
    COUNT(t.id)                               AS n_turns_recorded,
    COALESCE(SUM(t.cost_usd), 0)              AS cost_usd,
    COALESCE(SUM(t.duration_ms), 0)           AS duration_ms,
    COALESCE(SUM(t.duration_api_ms), 0)       AS duration_api_ms,
    COALESCE(SUM(t.num_turns), 0)             AS sdk_num_turns,
    COALESCE(SUM(t.input_tokens), 0)          AS input_tokens,
    COALESCE(SUM(t.output_tokens), 0)         AS output_tokens,
    COALESCE(SUM(t.cache_read_tokens), 0)     AS cache_read_tokens,
    COALESCE(SUM(t.cache_5m_tokens), 0)       AS cache_5m_tokens,
    COALESCE(SUM(t.cache_1h_tokens), 0)       AS cache_1h_tokens
FROM agent_sessions a
LEFT JOIN session_turns t ON t.session_id = a.session_id
GROUP BY a.session_id;

-- Per-job per-phase rollup. The phase column is best-effort: it
-- comes from the agent's session phase derived in agent_sessions
-- (NULL for sessions whose phase isn't decidable from the events log).
CREATE VIEW job_phase_summary AS
SELECT
    a.job_id,
    j.slug,
    j.classification,
    a.role,
    COUNT(DISTINCT a.session_id)              AS sessions,
    COUNT(t.id)                               AS turns,
    COALESCE(SUM(t.cost_usd), 0)              AS cost_usd,
    COALESCE(SUM(t.duration_ms), 0)           AS duration_ms,
    COALESCE(SUM(t.input_tokens), 0)          AS input_tokens,
    COALESCE(SUM(t.output_tokens), 0)         AS output_tokens,
    COALESCE(SUM(t.cache_read_tokens), 0)     AS cache_read_tokens,
    COALESCE(SUM(t.cache_5m_tokens), 0)       AS cache_5m_tokens,
    COALESCE(SUM(t.cache_1h_tokens), 0)       AS cache_1h_tokens
FROM agent_sessions a
LEFT JOIN jobs j         ON j.job_id = a.job_id
LEFT JOIN session_turns t ON t.session_id = a.session_id
WHERE a.job_id IS NOT NULL
GROUP BY a.job_id, a.role;

-- Per-job per-role per-agent cost rollup — the motivating cost-per-job
-- query from the issue body.
CREATE VIEW job_cost_summary AS
SELECT
    a.job_id,
    j.slug,
    j.classification,
    a.role,
    a.agent_name,
    COUNT(DISTINCT a.session_id)              AS sessions,
    COALESCE(SUM(t.cost_usd), 0)              AS cost_usd,
    COALESCE(SUM(t.duration_ms), 0)           AS duration_ms,
    COALESCE(SUM(t.input_tokens), 0)          AS input_tokens,
    COALESCE(SUM(t.output_tokens), 0)         AS output_tokens
FROM agent_sessions a
LEFT JOIN jobs j         ON j.job_id = a.job_id
LEFT JOIN session_turns t ON t.session_id = a.session_id
WHERE a.job_id IS NOT NULL
GROUP BY a.job_id, a.role, a.agent_name;

-- Gate spans, paired via LEAD over GATE_OPENED → first matching
-- GATE_PASSED / GATE_FAILED. Each gate gets one row whose
-- ``wall_seconds`` is the time it was open. Powers the gate-friction
-- analyses the canonical spec exposes via gate_dialog_summary.
CREATE VIEW gates AS
WITH opens AS (
    SELECT
        e.id                                  AS opened_id,
        e.session_id                          AS session_id,
        e.scope                               AS scope,
        e.ts                                  AS opened_ts,
        json_extract(e.data, '$.gate_type')   AS gate_type,
        json_extract(e.data, '$.phase_entering') AS phase_entering
    FROM events e
    WHERE e.event_type = 'gate_opened'
),
closes AS (
    SELECT
        e.session_id                          AS session_id,
        e.ts                                  AS closed_ts,
        json_extract(e.data, '$.gate_type')   AS gate_type,
        CASE
            WHEN e.event_type = 'gate_passed' THEN 'passed'
            WHEN e.event_type = 'gate_failed' THEN 'failed'
            ELSE 'unknown'
        END                                   AS outcome
    FROM events e
    WHERE e.event_type IN ('gate_passed', 'gate_failed')
),
paired AS (
    SELECT
        o.opened_id, o.session_id, o.scope, o.opened_ts, o.gate_type,
        o.phase_entering,
        (SELECT c.closed_ts FROM closes c
            WHERE c.session_id = o.session_id
              AND c.gate_type = o.gate_type
              AND c.closed_ts > o.opened_ts
            ORDER BY c.closed_ts ASC LIMIT 1) AS closed_ts,
        (SELECT c.outcome    FROM closes c
            WHERE c.session_id = o.session_id
              AND c.gate_type = o.gate_type
              AND c.closed_ts > o.opened_ts
            ORDER BY c.closed_ts ASC LIMIT 1) AS outcome
    FROM opens o
)
SELECT
    opened_id, session_id, scope, gate_type, phase_entering,
    opened_ts, closed_ts,
    COALESCE(outcome, 'open') AS outcome,
    CASE WHEN closed_ts IS NOT NULL
         THEN closed_ts - opened_ts
         ELSE NULL
    END AS wall_seconds
FROM paired;

-- gate_dialog_summary joins the gates view to jobs to expose the
-- spec's per-gate friction analysis: outcome × dialog turns × wall
-- seconds. ``dialog_turns`` is approximated as the count of
-- gate_input_received events for the gate's session in the open
-- window — operators can refine this query if they want a stricter
-- definition.
CREATE VIEW gate_dialog_summary AS
SELECT
    g.session_id,
    j.slug,
    j.classification,
    g.gate_type,
    g.outcome,
    (SELECT COUNT(*) FROM events e
        WHERE e.event_type = 'gate_input_received'
          AND e.session_id = g.session_id
          AND e.ts >= g.opened_ts
          AND (g.closed_ts IS NULL OR e.ts <= g.closed_ts))
        AS dialog_turns,
    g.wall_seconds
FROM gates g
LEFT JOIN jobs j ON j.session_id = g.session_id;

-- Byte-identical prompt grouping (the prompt_groups view from the
-- spec). Counts how many jobs share a prompt_hash so reruns of an
-- identical prompt are visible at a glance.
CREATE VIEW prompt_groups AS
SELECT
    project,
    prompt_hash,
    COUNT(*)                                  AS jobs,
    MIN(slug)                                 AS sample_slug,
    MIN(prompt_bytes)                         AS prompt_bytes,
    GROUP_CONCAT(job_id, ',')                 AS job_ids,
    MIN(created_at)                           AS first_attempt,
    MAX(created_at)                           AS last_attempt
FROM jobs
WHERE prompt_hash IS NOT NULL
GROUP BY project, prompt_hash
ORDER BY jobs DESC;
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
    # 6. Spec-aligned views. Recreated on every apply so view
    #    definitions track the schema; views are virtual so this is a
    #    no-cost operation.
    conn.executescript(_VIEWS_SQL)
    conn.commit()
