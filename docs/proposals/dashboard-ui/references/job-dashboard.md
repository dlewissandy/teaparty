# Job Dashboard

Shows the state of a single CfA job. Reached by clicking a job on the project dashboard.

## Title Bar

Job name and summary of the request being worked on. Buttons to open the job's worktree in file manager or editor.

## Workflow Progress

Shows CfA phases (INTENT, PLAN, WORK, WORK_ASSERT, DONE) with completed/current/future state.

## Stats

| Stat | What it measures |
|------|-----------------|
| Tasks | Completed/total |
| Backtracks | Number of backtracks in this job |
| Escalations | Number of escalations in this job |
| Tokens | Tokens consumed by this job |
| Elapsed | Wall-clock time since job started |

## Actions

| Action | Behavior |
|--------|----------|
| **Chat** | Opens the job's chat. Indicates when an escalation is pending. |
| **Withdraw** | Kills the job and all its tasks. Cascading. Immediate. |

## Content Cards

| Card | Content | Action |
|------|---------|--------|
| **Escalations** | Pending escalations for this job | Opens the job's chat |
| **Artifacts** | CfA artifacts: INTENT.md, PLAN.md, WORK_ASSERT.md. Shows existence state. | Opens artifact in editor |
| **Tasks** | Task list with liveness indicators and status | Navigates to task dashboard |

## Navigation

- Chat and escalation clicks open the same chat — one chat per job
- Clicking an artifact opens it in the editor
- Clicking a task navigates to the task dashboard

## Footer

Displays the job's git worktree path.
