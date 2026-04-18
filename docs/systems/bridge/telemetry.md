# Telemetry — event-sourced store

_Issue #405._ Reference for the unified telemetry store that replaces the scattered `metrics.db`, session metadata files, and ad-hoc stat aggregations that came before it.

## Design principle

**Capture atomic events, compute aggregates on read, never store aggregates.**

The store is one SQLite database (`{teaparty_home}/telemetry.db`) with one append-only table (`events`). Every telemetry-producing call site in TeaParty routes through `telemetry.record_event`. Every consumer reads through `telemetry.query_events` or one of its aggregation helpers. No SQL lives outside `teaparty/telemetry/`. Adding a new stat is writing a new helper over `query_events`. Fixing a bug in an aggregation is a code change, not a data migration — the underlying events are immutable.

Fragmentation-era assumptions that do not apply here:

- No rollup tables. No precomputed daily totals. `total_cost` sums `turn_complete` events at query time.
- No per-scope files. Org-wide queries are `SELECT ... FROM events WHERE scope = ?`, not a directory walk.
- No ambiguity about "which file has the current data". There is one file.

## API surface

### Write path

```python
from teaparty.telemetry import record_event

record_event(
    'turn_complete',
    scope='comics',
    agent_name='comics-lead',
    session_id='s-42',
    data={'cost_usd': 0.12, 'input_tokens': 800, 'output_tokens': 120},
)
```

- `scope` is mandatory; `agent_name` / `session_id` are nullable.
- `data` is a JSON-serializable dict whose shape is event-type-specific.
- `record_event` never raises. A disk-full condition is logged and swallowed — losing an event is preferable to stalling a live agent.
- After commit the event is fanned out on the bridge WebSocket channel as a `telemetry_event` message, so live consumers update without polling. The broadcast hook is installed at `bridge._on_startup` via `telemetry.set_broadcaster`.

### Read path

```python
from teaparty import telemetry

telemetry.total_cost(scope='comics')
telemetry.turn_count(scope='comics', time_range=(t0, t1))
telemetry.phase_distribution(scope='comics')
telemetry.escalation_stats(scope='management')
telemetry.proxy_answer_rate(scope='management')
telemetry.backtrack_count(kind='plan_to_intent')
telemetry.backtrack_cost()
telemetry.active_sessions()
telemetry.gates_awaiting_input()
telemetry.withdrawal_phase_distribution()
```

Each helper is a thin wrapper over `query_events`. For ad-hoc queries, call `query_events` directly:

```python
for ev in telemetry.query_events(event_type='gate_failed',
                                  scope='comics',
                                  start_ts=week_ago):
    print(ev.ts, ev.session_id, ev.data['reason_len'])
```

### HTTP

- `GET /api/telemetry/events` — raw event query, filtered by the standard fields; 1000-row default limit for admin debugging.
- `GET /api/telemetry/stats/{scope}` — all aggregation helpers for a scope in one JSON response; pass `scope=all` to omit the filter. The stats bar consumer reads from this endpoint.

## Schema

```sql
CREATE TABLE events (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  ts          REAL    NOT NULL,
  scope       TEXT    NOT NULL,
  agent_name  TEXT,
  session_id  TEXT,
  event_type  TEXT    NOT NULL,
  data        TEXT    NOT NULL,
  is_aggregate INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_events_ts       ON events(ts);
CREATE INDEX idx_events_scope_ts ON events(scope, ts);
CREATE INDEX idx_events_agent_ts ON events(agent_name, ts);
CREATE INDEX idx_events_session  ON events(session_id);
CREATE INDEX idx_events_type_ts  ON events(event_type, ts);
```

The `is_aggregate` column is reserved for a future retention pass that may compact old raw events into daily aggregate rows without breaking existing queries. v1 writes only raw events; `is_aggregate=0` for everything.

WAL mode is enabled so concurrent readers do not block writers. Writes are serialized through a module-level lock.

## Event catalog

The full catalog lives in `teaparty/telemetry/events.py`, one constant per type. Each group and its data fields:

### Turn lifecycle
- `turn_start` — `{trigger, claude_session, model, resume_from_phase}`
- `turn_complete` — `{duration_ms, exit_code, cost_usd, input_tokens, output_tokens, cache_read_tokens, cache_create_tokens, response_text_len, tools_called}`

### Session lifecycle
- `session_create` — `{qualifier, parent_session_id, dispatch_message_len, purpose}`
- `session_complete` — `{response_text_len, total_turns, total_cost_usd, final_phase}`
- `session_closed` — `{reason, triggered_by_session_id}`
- `session_withdrawn` — `{phase_at_withdrawal, reason_len, cost_at_withdrawal, duration_at_withdrawal, gate_state_at_withdrawal}`
- `session_timed_out` — `{final_phase, cost_at_timeout}`
- `session_abandoned` — `{idle_duration_s, final_phase}`

### Phase transitions
- `phase_changed` — `{old_phase, new_phase, state_machine}` (also `{old_state, new_state, action, actor}`)
- `phase_backtrack` — `{kind, triggering_gate, cost_of_work_being_discarded}`

### Gates
- `gate_opened`, `gate_passed`, `gate_failed`, `gate_input_requested`, `gate_input_received`

### Escalations (proxy chain)
- `escalation_requested`, `proxy_considered`, `proxy_answered`, `proxy_escalated_to_human`, `human_answered`, `escalation_resolved`, `proxy_answer_overridden`

### Interjections
- `interjection_received`, `interjection_applied`, `interjection_caused_backtrack`

### Corrections
- `correction_received`, `correction_applied`

### Retries and friction
- `tool_call_retry`, `session_retry`, `ratelimit_backoff`

### Stalls
- `stall_detected`, `stall_recovered`

### Context management
- `context_compacted`, `context_cleared`, `context_saturation_warned`

### Work artifacts
- `commit_made`, `commit_reverted`

### Dispatch patterns
- `fan_out_detected`, `dispatch_depth_exceeded`

### Errors and degradation
- `rate_limit`, `mcp_server_failure`, `session_poisoned`, `subprocess_killed`, `turn_error`

### Human operational actions
- `pause_all`, `resume_all`, `close_conversation`, `job_created`, `withdraw_clicked`, `reprioritize_dispatch_clicked`, `chat_blade_opened`, `chat_blade_closed`, `chat_message_sent`
- `config_project_added`, `config_project_removed`, `config_agent_created`, `config_agent_edited`, `config_agent_removed`, `config_skill_*`, `config_workgroup_*`, `config_hook_*`
- `pin_artifact`, `unpin_artifact`

### System and audit
- `server_start`, `server_shutdown`, `config_loaded`, `migration_run`

### Proxy evolution (Tier 4 stubs)
- `proxy_updated`, `proxy_diverged_from_human`

## Migration from per-scope metrics.db

On bridge startup, `telemetry.migrate_metrics_db` walks `{teaparty_home}` for any `*/metrics.db` files, reads each legacy `turn_metrics` row, writes it as a `turn_complete` event with the scope derived from the parent directory, then renames the source file to `metrics.db.migrated` so subsequent runs are no-ops. A `migration_run` audit event records the total.

## Single-codepath invariant

The success criteria forbid direct SQL against the events table outside `teaparty/telemetry/`. A CI test in `tests/telemetry/test_single_codepath.py` greps the tree on every run and fails the build if any file under `teaparty/` (other than the telemetry package) contains `INSERT INTO events`, `FROM events`, `CREATE TABLE turn_metrics`, or the literal string `'metrics.db'`. Adding a new writer means calling `record_event`; adding a new reader means calling `query_events` or a helper.

## Failure tolerance

- Write failure: logged at `WARNING` and swallowed. Caller is unaffected.
- Broadcast handler raising an exception: caught and logged at `DEBUG`. The row has already been committed at that point, so later consumers still see it via query.
- Unconfigured `teaparty_home`: `record_event` returns `None` and `query_events` returns `[]`. The package is safe to import from contexts that have no bridge running (CLI, tests).
