# digest

A standard skill carried by every agent on every team. Agents write their findings to a shared scratch hierarchy as they work; the team lead reads from it at consolidation time. No agent passes large outputs as context to another — the scratch is the handoff medium.

---

## File structure

The scratch is a directory of files, not a single document. Files are organized broad-to-specific:

- `index.md` — top-level summary and pointers to subtopic files; the first file any reader opens
- `<subtopic>.md` — one level deeper; linked from the index
- Further nesting only if a subtopic would otherwise exceed the line limit

**Hard limit: no file exceeds 200 lines.** If a write would push a file past 200 lines, split it: move the detail into a subtopic file and replace it with a one-line pointer in the parent.

Within each file, structure findings broad-to-specific: lead with the conclusion or summary, follow with supporting detail. A reader should be able to stop as soon as they have what they need.

---

## How agents use it

When an agent completes a subtask, it writes its findings to the appropriate file in the scratch hierarchy before signaling completion to the lead. The agent:

1. Reads the index to find the right section or confirm none exists yet
2. Writes findings under a clearly labeled heading (role or subtask name, with a `done` marker)
3. Creates a subtopic file and links it from the index if detail would push the target file over 200 lines

In-progress work may be marked `in-progress`; completed sections are marked `done`. Agents do not modify sections owned by other agents.

---

## How the lead uses it

At consolidation, the lead reads the index first, drills into subtopic files only as needed, and resolves any conflicts — overlapping findings, contradictions, or structural collisions — before producing the final deliverable. Conflict resolution is a judgment call, not a mechanical merge: the lead decides which finding is correct or how to reconcile them.

The lead also maintains the index: adding pointers when subagents create new files, removing stale entries, and keeping the index under 200 lines.

---

## Scratch location

The scratch directory lives in the job worktree at `scratch/`. Agents reference it by relative path. The directory is created on first write if it does not exist.
