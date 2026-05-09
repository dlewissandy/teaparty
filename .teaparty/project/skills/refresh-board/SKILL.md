---
name: refresh-board
description: Reconcile the local sprint cache against current GitHub state. Adds new milestone issues to the cache and the board, marks externally-closed issues as Done, and updates per-issue frontmatter to match GitHub.
allowed-tools: Read, Write, Edit, Glob, Grep, mcp__teaparty-config__list_milestone_issues, mcp__teaparty-config__read_issue, mcp__teaparty-config__add_issue_to_board, mcp__teaparty-config__set_board_status, mcp__teaparty-config__read_board_status
user-invocable: false
---

# refresh-board

Pull external GitHub changes into the cache. The cache is the source of truth for read paths, but GitHub is where issues actually live — when someone files a new issue against the milestone, or closes an issue from the GitHub UI, this skill is how those changes reach the cache and the board.

State-change skill. The sync model is **GitHub first, then cache**: any board mutation (adding a new issue, marking an externally-closed one Done) writes to GitHub before the cache row is updated. The reverse order would let a transient GitHub error silently desynchronize.

## Guard

`.teaparty/project/sprint/sprint.yaml` must exist. If it doesn't, abort.

## Steps

### 1. Fetch current GitHub state

Read `sprint.yaml` to get the milestone. Call `list_milestone_issues(milestone, state='all')`. Compare the result to the per-issue files in `.teaparty/project/sprint/issues/`.

Bucket the differences:

- **New on GitHub, missing from cache** — issues created or attached to the milestone after the cache was built.
- **Externally closed** — issues whose GitHub state went from `open` to `closed` since the cache was last refreshed (and whose cached `status` is not already `Done` or `Won't Do`).
- **Body changes** — title or body edited on GitHub. Frontmatter `title` is updated; the body in the per-issue file is left as-is unless the title changed (per-issue body is the planning-time snapshot).

### 2. New issues — add to GitHub board, then cache

For each new issue:

1. Call `read_issue(number)` to fetch the body (the listing only includes summary fields).
2. Call `add_issue_to_board(number)`. The MCP tool is idempotent — if the issue is already on the board, it returns the existing item id.
3. Call `set_board_status(number, 'Backlog')` so the new issue lands in the Backlog column. (`prioritize` is what later moves it to Approved if the project lead chooses to.)
4. **Only after both GitHub calls succeed**, write the per-issue file at `.teaparty/project/sprint/issues/{N}.md` with the frontmatter schema sprint-plan defined, and add a row to `index.md` with status `Backlog` and blank tier/wave.

### 3. Externally closed — mark Done on GitHub board, then cache

For each externally-closed issue whose cached status is not already `Done` or `Won't Do`:

1. Call `read_board_status(number)`. If the issue isn't on the board (e.g. created and closed entirely outside the sprint), skip it and log a note.
2. If it is on the board, call `set_board_status(number, 'Done')`.
3. **Only after that GitHub call succeeds**, update the cache: per-issue frontmatter `status: Done` and `state: closed`, plus the `index.md` row.

### 4. Body / title edits

Update `title` in the per-issue frontmatter and in `index.md` when GitHub's title changed. Do not rewrite the body section of the per-issue file — that is the planning-time snapshot, not a live mirror.

### 5. Reply

```
Refreshed sprint cache against GitHub:
  New on board: {count}      ({list of #N})
  Externally closed: {count} ({list of #N})
  Title edits applied: {count}
```

If any GitHub mutation failed, abort and report the in-progress state. The cache reflects only assignments where the matching GitHub call succeeded.

## What this skill does not do

- It does not re-tier or re-prioritize. New issues go to Backlog; the project lead decides where they belong via `prioritize`.
- It does not promote anything to Approved.
- It does not close or reopen issues on GitHub. It only reads GitHub state and reflects it in the cache.
