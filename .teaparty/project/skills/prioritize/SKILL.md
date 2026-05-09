---
name: prioritize
description: Apply tier assignments from the project lead to the sprint board and the local cache. Tier 1 → Approved, all other tiers → Backlog, Won't-Do → Won't Do. Mechanical mapping only — does not decide tiers, only applies them.
allowed-tools: Read, Write, Edit, Glob, Grep, mcp__teaparty-config__set_board_status
user-invocable: false
argument-hint: <tier_assignments>
---

# prioritize

Apply a batch of tier decisions to the sprint board and the cache. The project lead (or a future planning workgroup) decides what tier each issue belongs to; this skill is the mechanical mapping from those decisions to GitHub Status fields and to `index.md` / per-issue frontmatter.

This is a state-change skill. The sync model is **GitHub first, then cache**: every `set_board_status` call must succeed before the matching cache write happens. If GitHub rejects a call, abort the whole batch and report — partial application leaves cache and board diverged.

## Inputs

- `tier_assignments` — a mapping of issue number to tier, e.g.:

  ```yaml
  - { number: 429, tier: 1, wave: 1 }
  - { number: 430, tier: 2, wave: 1 }
  - { number: 431, tier: ~, wave: ~, status: "Won't Do" }
  ```

  An entry with `status: "Won't Do"` overrides the tier→status mapping; everything else uses the rule below.

## Tier → Status mapping

| tier | status |
|------|--------|
| 1 | Approved |
| 2 or higher | Backlog |
| `~` (no tier) with `status: "Won't Do"` | Won't Do |

## Guard

`.teaparty/project/sprint/sprint.yaml` must exist. If it doesn't, abort: there is no sprint to prioritize.

## Steps

### 1. Validate the input

Every `number` in the input must already appear in `index.md`. If a number is unknown, abort and report — `add-to-backlog` is how new issues join the board, not `prioritize`.

### 2. For each assignment, write to GitHub first

For each entry, call `set_board_status(number, status)` where `status` is derived from the table above. If any call fails (the MCP tool returns an `error` field), stop processing and report which assignment failed and what state the rest of the batch is in. Do **not** attempt to retry or partially apply.

### 3. Then write to the cache

After every GitHub call in the batch succeeds, update the cache. Two writes per issue:

- `.teaparty/project/sprint/issues/{N}.md` — frontmatter `tier`, `wave`, and `status`.
- `.teaparty/project/sprint/index.md` — the row for that issue, columns `status`, `tier`, `wave`.

Cache writes always come **after** the matching GitHub write succeeds.

### 4. Reply

```
Prioritized {N} issues:
  Tier 1 → Approved: {count}
  Tier 2+ → Backlog: {count}
  Won't Do: {count}
```

If any GitHub call failed in step 2, the reply is the failure report, not a success summary.

## What this skill does not do

- It does not decide tiers. The caller passes them in.
- It does not analyze dependencies, read issue bodies, or revise the cache's notes section.
- It does not move issues to In Progress or Done — those transitions are owned by `mark-in-progress` and `mark-done`.
