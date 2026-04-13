# Stats Bar

**Issue:** #406  
**Status:** Implemented

## Pattern

Every non-excluded page mounts the same stats-bar component with a scope config. There is one implementation (`stats-bar.js`), one mount point per page (`<div id="stats-bar-slot">`), and no per-page variants.

```
StatsBar.mount(container, { scope, label, agent_filter?, session_filter? });
StatsBar.unmount(container);
```

## Scope configs per page

| Page | Config |
|---|---|
| Home | `{ scope: null, label: 'Organization' }` |
| Management Team config | `{ scope: 'management', label: 'Management' }` |
| Project Team config | `{ scope: projectSlug, label: team.name }` |
| Agent detail | `{ scope: parentScope, agent_filter: name, label: name }` |
| Workgroup detail | `{ scope: parentScope, workgroup_filter: name, label: name }` |

Excluded pages: artifacts page, stats graph page.

## Data flow

1. **Mount**: `StatsBar.mount` renders a placeholder bar immediately.
2. **Baseline**: Fetches `GET /api/telemetry/stats/{scope}?agent=...&session=...` to populate cells with current values.
3. **Live updates**: Subscribes to `window._teapartyWS` for `telemetry_event` messages. Each matching event updates the relevant cells in-place — no backend round-trip.

## Cells

Always shown: **Cost** (USD), **Turns**, **Active** (sessions), **Gates Waiting**.  
Shown when non-zero: **Backtracks**, **Escalations**, **Proxy Ans %**.

## API endpoints

- `GET /api/telemetry/stats/{scope}` — Returns aggregated stats. Query params: `agent`, `session`, `time_range` (`today` | `7d` | `30d` | `all`).
- `GET /api/telemetry/chart/{chart_type}` — Returns time-series or histogram data for the stats graph page. Chart types: `cost_over_time`, `turns_per_day`, `active_sessions_timeline`, `phase_distribution`, `backtrack_cost`, `escalation_outcomes`, `withdrawal_phases`, `gate_pass_rate`. Query params: `scope`, `agent`, `session`, `time_range`.

Both endpoints read from the event-sourced telemetry store introduced in #405 (`teaparty/telemetry/`).

## Structural invariant

`_cellDefs(cells)` — not `_cellDefs(cells, config)` — generates the DOM cell structure. Config only affects the scope label and URL params. Two pages with different scopes produce structurally identical markup. A test in `tests/bridge/test_issue_406_stats_bar.py::StructuralDOMEquivalenceTests` verifies this invariant.

## WebSocket integration

Pages that already had a WS (`index.html`) expose it as `window._teapartyWS`. Pages that did not (`config.html`) got a lightweight WS connection added. The stats bar reads `window._teapartyWS` at subscribe time.
