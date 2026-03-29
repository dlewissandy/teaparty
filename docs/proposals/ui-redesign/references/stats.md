[UI Redesign](../proposal.md) >

# Stats Page

Interactive statistical visualizations derived from SQLite queries against the message bus and state files.

Mockup: [mockup/stats.html](../mockup/stats.html)

---

## User Stories

### "How is the org performing overall?"
Summary stats across all projects: jobs done, tasks done, active jobs, backtracks, withdrawals, escalations, proxy accuracy, token usage, skills learned. One row of numbers at the top.

### "How well is the proxy performing?"
Two distinct proxy metrics are displayed as aggregate bars, broken down by CfA state × task type:

- **Action match rate** (`action_match_rate`): fraction of escalated gates where the proxy's posterior prediction matched the human's response. Measures whether the proxy's final answer was right.
- **Prior calibration** (`prior_calibration`): fraction of gates where prior and posterior predictions agreed. Measures whether the proxy changed its mind after seeing the gate outcome.

High calibration with low match rate means the proxy is confidently wrong. Low calibration with high match rate means the proxy self-corrected. These are scientifically distinct and must not be collapsed.

A 7-day trend view is deferred: the `proxy_accuracy` table has one row per (state, task_type) with a `last_updated` timestamp but no per-day history. The time-series variant requires adding dated accuracy snapshots to the schema (future work). *Requires: #221 (evaluation harness), #231 (confidence threshold recalibration).*

### "Where are we spending the most tokens?"
Token usage chart by day. Spikes indicate expensive jobs. Drill down by project (future: scope selector).

### "Which phases generate the most escalations?"
Escalations by phase chart. If WORK_ASSERT dominates, the execution teams may need better self-review. If PLAN_ASSERT dominates, planning quality is the bottleneck.

### "How much work are we getting through?"
Tasks completed per day chart. Shows throughput trends. Combined with the backtrack and withdrawal counts, reveals whether work is progressing cleanly or churning.

---

## Charts

| Chart | X-Axis | Y-Axis | Color |
|-------|--------|--------|-------|
| Tasks Completed (7 days) | Date | Count | Green |
| Cost per Day (7 days) | Date | USD cost | Purple |
| Action Match Rate (per context) | State × task type | Percentage | Green/Yellow/Red (≥70% GO threshold) |
| Prior Calibration (per context) | State × task type | Percentage | Blue |
| Escalations by Phase (active) | Phase name | Count | Red |

All charts are bar charts in the mockup. The production implementation may use a JS charting library for interactivity (hover tooltips, click to filter).

---

## Data Sources

All stats are derived from existing data — no new collection needed:

| Metric | Source |
|--------|--------|
| Jobs/tasks completed | CfA state files (terminal states) |
| Active jobs | CfA state files (non-terminal states) |
| Backtracks | CfA state history (backtrack_count field) |
| Withdrawals | CfA state files (WITHDRAWN terminal state) |
| Escalations | Sessions with `needs_input=True` (CfA HUMAN_ACTOR_STATES or `.input-request.json`); historical message bus data deferred to issue #288 |
| Action match rate (`action_match_rate`) | `proxy_accuracy` table (`posterior_correct / posterior_total` per state × task_type); requires #221, #231 |
| Prior calibration (`prior_calibration`) | `proxy_accuracy` table (`prior_correct / prior_total` per state × task_type); requires #221, #231 |
| Token usage | `.cost` sidecar files per session (stores USD, not tokens — see issue #285) |
| Skills learned | `{project_dir}/skills/` and `{project_dir}/teams/{name}/skills/` (see issue #294) |
