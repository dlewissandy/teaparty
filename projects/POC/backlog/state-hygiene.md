# POC State Hygiene

The POC works. The orchestration is sound, the CfA lifecycle is proven, the team hierarchy does what it should. What's missing is **state hygiene** — the ability to inspect, resume, and understand what happened at any level of the hierarchy.

Four principles:

---

## 1. All state lives in files

Every piece of meaningful state — CfA phase, intent, plan, task list, approval decisions — must be a named file that a human or agent can read. If it's only in stream JSONL or in-memory, it doesn't count.

**What works today:** CfA state, intent, and plan are already files at the session level. Claude Code natively persists session transcripts (`~/.claude/projects/`), task lists (`~/.claude/tasks/` via `CLAUDE_CODE_TASK_LIST_ID`), auto memory (`~/.claude/projects/{project}/memory/`), and subagent memory (`~/.claude/agent-memory/`).

**What's broken:** At the dispatch level, the plan sometimes exists but the intent doesn't. Approval decisions are buried in stream events. `.result.json` often has `"summary": ""` — the work outcome is invisible without parsing megabytes of JSONL. Infrastructure noise (lock files, sentinels, PID files, session-id markers) is mixed in with meaningful state. Task lists are ephemeral because `CLAUDE_CODE_TASK_LIST_ID` isn't set.

**The fix:** Every session and every dispatch produces the same named state file set:

```
state.json          # CfA state with transition history, task_list_id, dispatch index
intent.md           # What we set out to do
plan.md             # How we planned to do it
approvals.jsonl     # Every approval/rejection and why
summary.md          # Final outcome — what was accomplished, what files changed
```

Task lists are persisted by setting `CLAUDE_CODE_TASK_LIST_ID` per process — the uber team gets one ID, each dispatch gets its own:

```
~/.claude/tasks/
    session-<id>/                  # uber team's task list
    dispatch-coding-<id>/          # coding subteam's task list
    dispatch-writing-<id>/         # writing subteam's task list
```

Each process's `state.json` records its `task_list_id` so the task list can be found.

Streams (`.exec-stream.jsonl`, `.plan-stream.jsonl`) remain as raw audit logs but are not the source of truth. The named state files are. Infrastructure files go elsewhere or are eliminated.

---

## 2. State is written at the moment it changes

State files must be durable against catastrophic failure — power loss, kill -9, OOM. The only state you can trust after a crash is what was already on disk at the moment of failure.

This means: **write state at the moment it changes, not at the end.** Never batch. Never defer to session completion. Never rely on graceful shutdown.

- `state.json` — written on every CfA transition and every dispatch status change
- `approvals.jsonl` — appended on every approval/rejection decision
- `intent.md` — written when intent is established
- `plan.md` — written when plan is established
- Task list — written continuously by Claude via `CLAUDE_CODE_TASK_LIST_ID` (already write-through)
- Auto memory — written continuously by Claude (already write-through)
- Subagent memory — written continuously by Claude (already write-through)
- Session transcripts — written continuously by Claude (already write-through)

The only file that's legitimately written at completion is `summary.md`. Everything else must be current at all times.

---

## 3. State is resumable

Any session or dispatch that was interrupted — including by catastrophic failure — can be resumed from its state files. The state file set from principles 1 and 2 is not just for inspection — it's the checkpoint from which work continues.

**What works today:** CfA state tracks the current phase. `claude --resume` picks up a session from its transcript. Task lists survive if `CLAUDE_CODE_TASK_LIST_ID` was set. Auto memory and subagent memory survive across sessions natively.

**What's broken:** Resumption is fragile. The session ID is stashed in a dot file. If the parent session is interrupted mid-dispatch, there's no way to know which dispatches completed, which were in progress, and what phase each was in without parsing streams. A resumed session has to re-discover the world.

**The fix:** A resumed session reads the state files and knows exactly where it is:
- `state.json` says which CfA phase we're in, where to find the task list, and the status of every dispatch
- Each dispatch's own `state.json` says where *it* was interrupted
- `plan.md` is the work plan — no need to re-plan
- `approvals.jsonl` shows what was already approved — no need to re-ask
- The task list shows what's done, what's in progress, what's pending
- `claude --resume` restores the conversation context
- Auto memory and subagent memory carry forward learnings from before the interruption

Resumption becomes: read the files, assess what's done and what's not, continue.

---

## 4. Thread/process isolation

Each dispatch runs in its own process with its own worktree, its own state directory, and its own task list. The parent session and sibling dispatches cannot see each other's working state during execution. Results flow up only through explicit handoff — the summary file and the merged worktree.

**What works today:** Dispatches get separate `claude -p` processes and separate git worktrees. Context isolation between team levels is the core architectural win. Claude Code natively isolates session transcripts and task lists per process.

**What's broken:** The isolation is incomplete in two ways:

- **State leaks up.** Dispatch state directories live inside the parent session directory (`.sessions/<session>/<team>/<dispatch>/`). The parent can peek at dispatch internals. This isn't harmful, but it blurs the boundary.
- **Work output is invisible.** Worktrees exist but are opaque — named by timestamp, no manifest linking them to dispatches, no lifecycle management. 44 worktrees accumulate in `.worktrees/` with no way to tell which are active, completed, or abandoned.

**The fix:**

**State isolation.** Each dispatch's state directory is self-contained — the same file set as the parent (principle 1), the same write-through durability (principle 2), the same resumability contract (principle 3). The parent knows about a dispatch through the dispatch index in its own `state.json` (team, status, pointer to state directory, task list ID), not by reaching into the dispatch's internals.

**Work output visibility.** Worktrees get self-describing names (`<team>-<short-id>--<task-slug>`) and a manifest (`worktrees.json`) linking them to dispatches with explicit lifecycle states:

- **active** — dispatch in progress
- **completed** — merged back to parent branch
- **failed** — dispatch errored or exhausted retries (preserved for debugging)
- **abandoned** — human chose to stop (preserved for salvaging partial work)

A simple status command reads the manifest and prints a table — enough to answer "what's happening right now?"
