# Task Dashboard

Shows the state of a single task being performed by an agent. Reached by clicking a task on the job or workgroup dashboard.

## Title Bar

Task name and summary of the task request.

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
| **Artifacts** | First item is the task worktree (opens working directory). Remaining items are files the agent has created or is creating. Each item has `[Finder]` and `[Editor]` buttons on the right. | Worktree opens directory; files open in editor |
| **Todo List** | The agent's internal checklist. Completed items are marked. | Read-only |

## Breadcrumbs

TeaParty / Project / Job / Task. The workgroup link is in the subtitle for cross-navigation.

## Footer

Same worktree path as the parent job (tasks share the job's worktree).
