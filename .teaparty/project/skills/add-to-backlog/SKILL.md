---
name: add-to-backlog
description: Add a new issue to the sprint board and the local cache with status Backlog. Used when an issue is filed mid-sprint and needs to be tracked.
allowed-tools: Read, Write, Edit, Glob, Grep, mcp__teaparty-config__read_issue, mcp__teaparty-config__add_issue_to_board, mcp__teaparty-config__set_board_status
user-invocable: false
argument-hint: <issue_number>
---

# add-to-backlog

Bring a new issue under sprint tracking. Used when someone files an issue mid-sprint that should be on the board even if no decision has been made about its tier yet. The issue lands in Backlog; `prioritize` is what later places it.

State-change skill. The sync model is **GitHub first, then cache**: the board mutations succeed before any per-issue file is written.

## Inputs

- `issue_number` — the issue to add (required, integer).

## Guard

`.teaparty/project/sprint/sprint.yaml` must exist. If the issue is already in `index.md`, abort and report — `mark-*` is the right skill for state transitions on existing entries.

## Steps

### 1. Fetch the issue from GitHub

Call `read_issue(issue_number)` to get title, body, state, labels, milestone, assignees. If the call fails (issue does not exist, or is not accessible), abort.

### 2. Add to the board on GitHub first

Call `add_issue_to_board(issue_number)`. The MCP tool is idempotent; if the issue is already on the board with no cache entry, the call returns the existing item id without error.

Then call `set_board_status(issue_number, 'Backlog')` so the new item lands in the Backlog column. If either call fails, abort and report — do not write the cache.

### 3. Then write the cache

After both GitHub calls succeed:

- `.teaparty/project/sprint/issues/{N}.md` — new file, with the full frontmatter schema sprint-plan defined and the issue body. `status: Backlog`, `tier:` blank, `wave:` blank.
- `.teaparty/project/sprint/index.md` — append a row with the issue number, title, status `Backlog`, blank tier, blank wave.

### 4. Reply

```
#{N} added to Backlog: {title}
```

## What this skill does not do

- It does not assign a tier. The new issue waits for a `prioritize` call from the project lead.
- It does not promote the issue to Approved.
- It does not file the issue — issue creation happens elsewhere; this skill only reflects an existing GitHub issue onto the sprint board.
