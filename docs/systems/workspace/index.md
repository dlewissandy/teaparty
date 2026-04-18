# Workspace

The Workspace system owns filesystem and process isolation for every agent session. It combines three concerns into one layer: git worktree management, the job and task lifecycle, and the unified launcher that assembles an agent's runtime configuration and invokes `claude -p`. The guarantee it provides to the rest of the platform is simple and absolute: **session = worktree = branch, 1:1:1, without exception.**

## Why it exists

Parallel dispatches on a shared checkout corrupt each other. Two agents editing the same files in the same directory produce interleaved writes, mixed branches, and unreproducible state. Every lead in the hierarchy — the office manager, project leads, workgroup leads — routinely fans work out in parallel, so a shared checkout is a non-starter.

Isolation at the process boundary (one `claude -p` invocation per session) is only half the answer. Without a matching filesystem boundary, two agent processes still collide on the working tree, `.git/index`, and any scratch files. The worktree is the filesystem counterpart to the process: each session gets its own checkout, its own branch, its own `.claude/` configuration composed for exactly that agent.

Durability follows from the same choice. Agents use a write-then-exit-then-resume pattern — the process exits between turns, and state is reconstructed from disk via `claude -p --resume` plus the session's `metadata.json`. That only works if every session has a stable, private location on disk. The worktree is that location.

## How it works

**Session = worktree = branch.** The `Session` dataclass in `teaparty/runners/launcher.py` carries all three identifiers (`id`, `path`, `claude_session_id`). `create_session()` allocates the session directory and creates a git worktree inside it. `load_session()` restores it. `CloseConversation` tears both down together. There is no codepath that creates one without the others.

**Hierarchical, project-scoped layout.** Jobs live in the project repo they affect, not in the TeaParty repo. Each job owns its worktree and a `tasks/` subtree; each task owns a worktree branched from the job's branch. Cleanup is strictly hierarchical — removing a job directory removes every task it owns.

```
{project}/.teaparty/
  jobs/
    jobs.json
    job-{id}--{slug}/
      worktree/          -- job's git worktree
      job.json           -- job state
      tasks/
        task-{id}--{slug}/
          worktree/      -- task's git worktree (branched from job)
          task.json      -- task state
```

**Branch from parent, squash-merge back.** A task worktree is a branch off its job's branch. When the task completes, `teaparty/workspace/merge.py::squash_merge` merges the task branch back into the job branch with a four-tier conflict escalation: (1) plain `git merge --squash`; if conflicts, (2) `--squash -X theirs` taking the task's side; if still unresolved, (3) manual `_resolve_conflicts_from_source` which walks the conflict list and resolves each from the task-side file; as a last resort, (4) `_file_copy_merge` which copies the task's files verbatim into the job branch. An optional `conflict_callback` can raise `MergeConflictEscalation` at tier 2 to route to a human before auto-resolution. The default stance is completed work wins, because the task ran to `COMPLETED_WORK` and we do not discard finished work over mechanical merge failures. The job branch, in turn, merges back to the integration branch when the job completes. Per-repo locks in `worktree.py` serialize concurrent `git worktree add`/`remove` calls so parallel dispatches cannot race the `.git/worktrees/` advisory lock.

**Unified launcher assembles the prompt.** Every agent — office manager, project lead, workgroup agent, proxy — launches through a single function: `launch()` in `teaparty/runners/launcher.py`. The launcher reads `.teaparty/` configuration, composes `.claude/` into the worktree (agent definition, filtered skills, merged settings, generated `.mcp.json`), builds the subprocess arguments, and invokes `claude -p`. There are no alternative codepaths. Job-tier launches run inside a worktree; chat-tier launches (management chat, project lead conversations) run in the real repo because those agents dispatch rather than mutate code — see [unified-launch](unified-launch.md) for the split.

**State lives on disk.** `job_store.py` owns `.teaparty/jobs/` — job and task records, slug generation, index files written atomically. Combined with the worktree and the Claude session ID in `metadata.json`, restart after a crash is just `load_session()` plus `--resume`.

## Status

Operational. Every agent type runs through the unified launcher; the session/worktree/branch invariant is enforced structurally by `Session` and `create_session()`; job and task worktrees merge back cleanly via `merge.py` with conflict-resolution-by-source and post-merge verification (`MergeVerificationError`) catching silent data loss.

Remaining gaps are around cleanup ergonomics (orphaned worktrees after abnormal termination need a reaper) and cross-repo job coordination (the [cfa](../cfa-orchestration/index.md) engine currently assumes jobs and tasks share a repo, which is true in practice but not enforced).

## Deeper topics

- [unified-launch](unified-launch.md) — the launcher's two-tier model (chat vs job), one-shot launch with `--resume`, and the rules that keep `.teaparty/` config the single source of truth.
- [agent-runtime](agent-runtime.md) — the `claude -p` invocation shape, `AgentSession`, stream processing, session health detection, and Max SLA constraints.

For upstream consumers, see [cfa](../cfa-orchestration/index.md) (which drives job and task lifecycle), [messaging](../messaging/index.md) (which routes Send/Reply across sessions), and the [execution](../../case-study/execution.md) case study for an end-to-end walkthrough.
