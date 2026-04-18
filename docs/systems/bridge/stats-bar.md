# Stats Bar

**Issue:** #406  
**Status:** Implemented

## Pattern

Every non-excluded page mounts the same stats-bar component with a scope config. There is one implementation (`stats-bar.js`), one mount point per page (`<div id="stats-bar-slot">`), and no per-page variants.

```javascript
StatsBar.mount(container, { scope, label, agent_filter?, session_filter? });
StatsBar.unmount(container);
```

## Paged ticker

The strip shows `PAGE_SIZE` (5) stats at a time, cycling pages every `PAGE_INTERVAL_MS` (10 000 ms) with a fade transition. Page position is indicated by dots on the right. Clicking anywhere on the strip navigates to the scoped stats graph page.

## Scope configs per page

| Page | Config |
|---|---|
| Home | `{ scope: null, label: 'Organization' }` |
| Management Team config | `{ scope: 'management', label: 'Management' }` |
| Project Team config | `{ scope: projectSlug, label: team.name }` |
| Agent detail | `{ scope: parentScope, agent_filter: name, label: name }` |
| Workgroup detail | `{ scope: parentScope, workgroup_filter: name, label: name }` |
| Job screen | `{ scope: projectSlug, label: projectSlug }` |

Excluded pages: artifacts page, stats graph page itself.

Note on workgroup_filter: telemetry events are keyed by scope and agent_name; there is no workgroup field. The stats bar shows parent-scope stats for workgroup pages.

Note on job session_filter: `job.html` does not carry a root session ID in its URL params, so the job page shows project-scoped stats (not session-scoped). Session-scoped stats would require #402's job launch to encode the root session ID in the URL.

## Stats shown (STAT_DEFS order)

24 stats, grouped into three semantic pages that cycle every `PAGE_INTERVAL_MS`:

**Page 1 — Throughput** (9 stats):

| Key | Label | Source |
|---|---|---|
| turns | Turns | count of `turn_complete` events |
| cost | Cost | sum of `turn_complete.cost_usd` |
| tokens | Tokens | sum of `input_tokens + output_tokens + cache_read_tokens` per turn |
| proc_ms | Proc Time | sum of `turn_complete.duration_ms` |
| commits | Commits | count of git-commit events |
| jobs_started | Jobs Started | count of `job_created` events |
| sess_closed | Completed | count of `session_complete` + `session_closed` events |
| conv_started | Conv Started | count of `session_create` events |
| conv_closed | Conv Closed | count of `close_conversation` events |

**Page 2 — Friction** (8 stats):

| Key | Label | Source |
|---|---|---|
| backtracks | Backtracks | count of `phase_backtrack` events (all kinds) |
| stalls | Stalls | count of stall-watchdog events |
| ratelimits | Rate Limits | count of API rate-limit events |
| ctx_compacted | Compacted | count of context-compaction events |
| ctx_warnings | Ctx Warnings | count of `CONTEXT_WARNING` events |
| tool_retries | Tool Retries | count of `tool_call_retry` events (no TOOL_CALL event type exists) |
| errors | Errors | count of `turn_error` events |
| mcp_failures | MCP Failures | count of MCP-server failure events |

**Page 3 — Human involvement** (7 stats):

| Key | Label | Source |
|---|---|---|
| interjections | Interjections | count of human interjection events |
| corrections | Corrections | count of gate-correction events |
| esc_proxy | Esc→Proxy | count of `proxy_answered` events |
| esc_human | Esc→Human | count of `proxy_escalated_to_human` events |
| withdrawals | Withdrawals | count of `session_withdrawn` events |
| sess_timed_out | Timed Out | count of session-timeout events |
| sess_abandoned | Abandoned | count of session-abandoned events |

Pages are **semantic groups**, not fixed-size slices of a flat list — `STAT_PAGE_KEYS` in `stats-bar.js` enumerates them explicitly.

## Data flow

1. **Mount**: `StatsBar.mount` renders a placeholder bar with zero values immediately.
2. **Baseline**: Fetches `GET /api/telemetry/stats/{scope}?agent=...&session=...` and populates all cells.
3. **Live updates**: Subscribes to `window._teapartyWS` for `telemetry_event` messages. Each matching event updates the relevant cell values in `state.cells`; only the currently visible page is re-rendered.
4. **Page advance**: `setInterval` calls `_advancePage` every 10 s. On advance, the ticker fades out, the page index increments (wrapping), and the new page renders.

## API endpoints

- `GET /api/telemetry/stats/{scope}` — Aggregated stats for a scope. Query params: `agent`, `session`, `time_range` (`today` | `7d` | `30d` | `all`). Returns all paged-ticker fields plus chart-page breakdowns.
- `GET /api/telemetry/chart/{chart_type}` — Time-series / histogram data for the stats graph page. Chart types: `cost_over_time`, `turns_per_day`, `active_sessions_timeline`, `phase_distribution`, `backtrack_cost`, `escalation_outcomes`, `withdrawal_phases`, `gate_pass_rate`. Query params: `scope`, `agent`, `session`, `time_range`.

Both endpoints read from the event-sourced telemetry store introduced in #405 (`teaparty/telemetry/`).

## Structural invariant

`STAT_DEFS` is a module-level constant array — not derived from config. All scopes get the same 24 stats in the same order, grouped into the same three semantic pages. Config only affects the scope label and the API filter params. Two pages with different scopes produce structurally identical markup. A test in `tests/bridge/test_issue_406_stats_bar.py::StructuralDOMEquivalenceTests` verifies this invariant.

## WebSocket integration

Pages expose their WebSocket as `window._teapartyWS`. `index.html`, `config.html`, and `job.html` all open a WS connection; the stats bar attaches a listener to receive live `telemetry_event` updates on all three.
