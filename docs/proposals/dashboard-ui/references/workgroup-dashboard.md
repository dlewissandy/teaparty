# Workgroup Dashboard

Shows the state of a single workgroup. Reached by clicking a workgroup on the project or management dashboard.

## Title Bar

Workgroup name and description.

## Stats

Same pattern, scoped to this workgroup.

## Content Cards

| Card | Content | Action |
|------|---------|--------|
| **Escalations** | Pending escalations for jobs this workgroup is working on | Opens the job's chat |
| **Sessions** | Office manager sessions scoped to this workgroup. "+ New" | Opens session chat with implicit workgroup context |
| **Active Tasks** | Tasks this workgroup is currently performing, with liveness indicators | Navigates to task dashboard |
| **Agents** | Workgroup agents. "+ New" | Opens read-only agent config modal |
| **Skills** | Workgroup-scoped skills. "+ New" | Opens skill in editor |

Sessions carry implicit workgroup context — the scope narrows as you drill down.

## What's NOT here

- **Jobs.** The workgroup doesn't own jobs — it participates in them via tasks.
- **Scheduled Tasks / Hooks.** Configured at the project or management level, not per-workgroup.

## Navigation

- Clicking a task navigates to the task dashboard (or parent job if no task data)
- Clicking a session opens the office manager chat with workgroup context
- Clicking an escalation opens the relevant job's chat
- Each task shows which job it belongs to
