---
name: mark-done
description: Move a single issue to Done on the GitHub board and in the local cache. Called when the software-development lead reports the fix is complete and merged.
allowed-tools: Read, Write, Edit, Glob, Grep, mcp__teaparty-config__set_board_status
user-invocable: false
argument-hint: <issue_number>
---

# mark-done

Single board transition: move issue #N to **Done**. Called when the software-development lead reports completion of a fix, so the board reflects the new state immediately.

State-change skill. The sync model is **GitHub first, then cache**: write the board, then update the cached row. If the GitHub call fails, the cache stays at its prior status — better stale than divergent.

## Inputs

- `issue_number` — the issue to transition (required, integer).

## Guard

`.teaparty/project/sprint/sprint.yaml` must exist. The issue number must already appear in `index.md`.

## Steps

### 1. Write GitHub first

Call `set_board_status(issue_number, 'Done')`. If the MCP tool returns an `error` field, abort and surface the error. Do not write the cache.

### 2. Then write the cache

After the GitHub call succeeds:

- `.teaparty/project/sprint/issues/{N}.md` — frontmatter `status: Done`. Leave `state` (open/closed) alone — closing the issue itself is a separate action and not this skill's job.
- `.teaparty/project/sprint/index.md` — the row's `status` column → `Done`.

### 3. Reply

```
#{N} → Done
```

## What this skill does not do

- It does not close the GitHub issue. Marking the board column Done is a sprint-board state, not an issue-state change. The issue is closed by the merge or by a separate `gh issue close` action.
- It does not move the issue to a different milestone, edit comments, or change labels.
