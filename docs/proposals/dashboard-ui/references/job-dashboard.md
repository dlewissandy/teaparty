# Job Dashboard

Shows the state of a single CfA job. Reached by clicking a job on the project dashboard.

## Title Bar

Job name and summary of the request being worked on.

## CfA Status Bar

Positioned below the stats bar, spanning full screen width. Shows the complete happy path:

`IDEA  INTENT  INTENT ASSERT  PLAN  PLAN ASSERT  WORK  WORK ASSERT  DONE`

No icons. Each phase cell fills its share of the row as a solid color block:

| State | Text | Background |
|-------|------|------------|
| Completed | white | dim green |
| Current | black | yellow |
| Future | black | grey |

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
| **Artifacts** | First item is the job worktree (opens working directory). Remaining items are CfA artifacts: INTENT.md, PLAN.md, WORK_ASSERT.md. Each item has `[Finder]` and `[Editor]` buttons on the right. | Worktree opens directory; artifacts open in editor |
| **Tasks** | Task list with liveness indicators and status | Navigates to task dashboard |

## Navigation

- Chat and escalation clicks open the same chat — one chat per job
- Clicking an artifact opens it in the editor
- Clicking a task navigates to the task dashboard

## Footer

Displays the job's git worktree path.
