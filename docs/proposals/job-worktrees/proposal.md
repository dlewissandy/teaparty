[Milestone 3: Human Interaction Layer](../milestone-3.md) >

# Job Worktrees

A **job** is a top-level unit of work — typically tied to a GitHub issue — that a project lead accepts and coordinates. A **task** is a sub-unit of work within a job that the lead dispatches to an agent (e.g., "implement the fix," "write tests," "review the diff"). Leads routinely dispatch multiple tasks in parallel to different agents.

Every job gets its own git worktree. Every task gets its own git worktree. Parallel tasks on a shared checkout corrupt each other — this is not a theoretical risk but the reason task worktrees are unconditional. Worktrees are scoped to the project that owns the work, not stored in a flat pool at repo root.

This proposal replaces the current worktree layout with a hierarchical structure that mirrors the job/task relationship.

---

## Problem

### Scattered storage with no project boundary

Worktree data currently lives in three unrelated locations:

- `.worktrees/` at repo root — created by the orchestrator for issue branches
- `.claude/worktrees/` at repo root — created by Claude Code for its own sessions
- `worktrees.json` at repo root — a flat registry referencing both

None of these are project-scoped. TeaParty manages multiple projects (TeaParty, pybayes, Jainai, comics), each with its own repo. A pybayes job's worktree should live in the pybayes repo, not in TeaParty's repo root. The current layout stores everything in the TeaParty repo regardless of which project owns the work.

### No job/task hierarchy

Jobs and tasks are entries in a flat list (`worktrees.json`). There is no structural relationship between a job and the tasks dispatched within it. Cleaning up a completed job requires scanning the entire flat list to find and remove its tasks. Orphaned task entries accumulate when jobs are removed without finding all their children.

### No enforced parallel isolation

When a lead dispatches three tasks in parallel, each task agent runs `git` operations concurrently. If two agents share a worktree, they corrupt each other's index, staging area, and working tree. The current layout relies on naming conventions to avoid collisions rather than giving each task its own checkout.

---

## Design

### Directory Layout

```
{project_root}/.teaparty/
  jobs/
    jobs.json
    job-{short_id}--{slug}/
      worktree/
      job.json
      tasks/
        tasks.json
        task-{short_id}--{slug}/
          worktree/
          task.json
```

The structure is uniform: every job directory contains a worktree, a state file, and a tasks container. Every task directory contains a worktree and a state file. There are no optional components.

### Project Scoping

Each project's jobs live under that project's `.teaparty/jobs/` directory:

```
teaparty/.teaparty/jobs/       # TeaParty project jobs
pybayes/.teaparty/jobs/        # pybayes project jobs
jainai/.teaparty/jobs/         # Jainai project jobs
```

The project lead creates jobs in its own project. Cross-project coordination is mediated by the office manager, which delegates to the appropriate project lead — it does not create worktrees in other projects directly.

### Job State (`job.json`)

```json
{
  "job_id": "job-a1b2c3d4",
  "slug": "fix-session-write-scope",
  "issue": 355,
  "branch": "job-a1b2c3d4--fix-session-write-scope",
  "status": "active",
  "created_at": "2026-04-07T10:00:00Z",
  "updated_at": "2026-04-07T12:30:00Z"
}
```

### Task State (`task.json`)

```json
{
  "task_id": "task-e5f6g7h8",
  "slug": "make-targeted-edits",
  "team": "coding",
  "agent": "developer",
  "branch": "task-e5f6g7h8--make-targeted-edits",
  "status": "complete",
  "created_at": "2026-04-07T10:05:00Z",
  "updated_at": "2026-04-07T11:45:00Z"
}
```

### Index Files

`jobs.json` and `tasks.json` are lightweight indexes for fast listing without walking the directory tree. They are derived, not authoritative — each `job.json` and `task.json` owns its own state. If an index diverges from the individual state files, the individual files win and the index is rebuilt.

### Worktree Lifecycle

1. **Job creation.** The project lead creates `job-{id}--{slug}/` and runs `git worktree add` to check out the job's branch into `worktree/`. This is the "main" checkout for the issue.

2. **Task creation.** When the lead dispatches a task, it creates `tasks/task-{id}--{slug}/` and runs `git worktree add` to branch off the job's branch into the task's `worktree/`. The task agent works exclusively in this checkout.

3. **Task completion.** The lead merges the task's branch back into the job's branch (in the job worktree). If multiple tasks complete, the lead merges them sequentially. Merge conflicts are resolved by the lead, not automatically — the lead has the context to make judgment calls about conflicting changes.

4. **Job completion.** The job's branch is merged back to the integration branch (e.g., `develop`). The entire `job-{id}--{slug}/` directory is removed as a unit — worktree, state, all task worktrees, all task state. `git worktree remove` is called for each worktree before directory removal.

### Cleanup

Cleanup is hierarchical. Removing a job directory removes everything owned by that job. A GC pass walks `jobs/`, checks each `job.json` status, and removes completed or failed jobs older than a threshold. There are no external references to chase — all state is colocated.

---

## Relationship to Agent Dispatch

[Agent Dispatch](../agent-dispatch/proposal.md) defines how agents are spawned: the invocation model, skill composition, worktree composition (`.claude/` layering), and bus-mediated communication. This proposal defines *where* those agents' worktrees live and how they are organized.

Agent Dispatch creates the agent. This proposal creates the directory the agent works in. The two are complementary — Agent Dispatch does not prescribe worktree storage layout, and this proposal does not prescribe agent invocation mechanics.

---

## Migration

The current layout is replaced, not extended:

1. `.worktrees/` at repo root is retired. Active worktrees are migrated to the appropriate project's `.teaparty/jobs/` structure.
2. `worktrees.json` at repo root is retired. Job and task state moves to per-job and per-task state files.
3. `.claude/worktrees/` is not touched — it belongs to Claude Code, not TeaParty.

---

## What This Does Not Cover

- **Agent session data** (message DBs, spawned agent contexts in `.teaparty/management/agents/`). That is agent memory and conversation history, not worktree management.
- **Branch strategy.** This proposal defines where worktrees live, not how branches are named or merged. The existing gitflow model is unchanged.
- **Worktree composition** (skill isolation, `.claude/` layering at spawn time). That is defined in [Agent Dispatch](../agent-dispatch/proposal.md).
