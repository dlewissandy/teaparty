---
name: mark-in-progress
description: Move a single issue to In Progress on the GitHub board and in the local cache. Called by the project lead at the moment work begins on the issue.
allowed-tools: Read, Write, Edit, Glob, Grep, mcp__teaparty-config__set_board_status
user-invocable: false
argument-hint: <issue_number>
---

# mark-in-progress

Single board transition: move issue #N from Approved (or wherever it currently sits) to **In Progress**. Called by the project lead when delegating a fix to the software-development lead, so the board reflects active work in real time.

State-change skill. The sync model is **GitHub first, then cache**: write the board, then update the cached row. A failed GitHub call leaves the cache untouched — never the other way around.

## Inputs

- `issue_number` — the issue to transition (required, integer).

## Guard

`.teaparty/project/sprint/sprint.yaml` must exist. The issue number must already appear in `index.md` — if it doesn't, the caller wants `add-to-backlog` first, then this.

## Steps

### 1. Write GitHub first

Call `set_board_status(issue_number, 'In Progress')`. If the MCP tool returns an `error` field, abort and surface that error in the reply. Do not write the cache.

### 2. Then write the cache

After the GitHub call succeeds:

- `.teaparty/project/sprint/issues/{N}.md` — frontmatter `status: In Progress`.
- `.teaparty/project/sprint/index.md` — the row's `status` column → `In Progress`.

### 3. Reply

```
#{N} → In Progress
```

That's all. This skill does no other work — no tier change, no body edit, no comment posting.

## What this skill does not do

- It does not decide whether the issue is ready for In Progress. The caller has already decided.
- It does not assign anyone. It does not create comments. It does not start a worktree.
