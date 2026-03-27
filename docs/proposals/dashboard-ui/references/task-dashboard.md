# Task Dashboard

Shows the state of a single task being performed by an agent. Reached by clicking a task on the job or workgroup dashboard.

## Title Bar

Task name and summary of the task request. Buttons to open the worktree in file manager or editor.

## Subtitle

Assignee agent name, status, and link to the workgroup performing this task.

## Progress

Completed/total todo items with percentage.

## Stats

| Stat | What it measures |
|------|-----------------|
| Tokens | Tokens consumed by this task |
| Elapsed | Wall-clock time since task started |

## Actions

| Action | Behavior |
|--------|----------|
| **Chat** | Opens the task's chat. Indicates when an escalation is pending. |
| **Withdraw** | Kills this task. |

## Content Cards

| Card | Content | Action |
|------|---------|--------|
| **Escalations** | Pending escalations for this task | Opens the task's chat |
| **Artifacts** | Files the agent has created or is creating | Opens in editor |
| **Todo List** | The agent's internal checklist. Completed items are marked. | Read-only |

## Breadcrumbs

TeaParty / Project / Job / Task. The workgroup link is in the subtitle for cross-navigation.

## Footer

Same worktree path as the parent job (tasks share the job's worktree).
