[UI Redesign](../proposal.md) >

# Stats Page

Interactive statistical visualizations derived from SQLite queries against the message bus and state files.

Mockup: [mockup/stats.html](../mockup/stats.html)

---

## User Stories

### "How is the org performing overall?"
Summary stats across all projects: jobs done, tasks done, active jobs, backtracks, withdrawals, escalations, proxy accuracy, token usage, skills learned. One row of numbers at the top.

### "Is the proxy getting better over time?"
Proxy accuracy trend chart shows accuracy percentage over the last 7 days. Color-coded: green ≥ 80%, yellow ≥ 70%, red < 70%. Helps decide whether to adjust the proxy's escalation rate.

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
| Proxy Accuracy Trend | Date | Percentage | Green/Yellow/Red (threshold) |
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
| Proxy accuracy | Proxy memory chunks (prediction vs. outcome) |
| Token usage | `.cost` sidecar files per session (stores USD, not tokens — see issue #285) |
| Skills learned | `{project_dir}/skills/` and `{project_dir}/teams/{name}/skills/` (see issue #294) |
