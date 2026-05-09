---
name: archive-sprint
description: Phase-end sprint cleanup. Warns on still-open Approved items, then archives the local sprint cache. Does not close the milestone — milestone closure is a human decision.
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, mcp__teaparty-config__read_board_status
user-invocable: false
---

# archive-sprint

Wrap up the local sprint cache when the team is done with the milestone. Archives the cache directory so the next `sprint-plan` starts clean. Surfaces any Approved-still-open items to the caller as a warning, but does not block — leaving things behind is a deliberate choice the project lead may make.

This skill **must not close the milestone** on GitHub. Milestone closure is a human decision; the local cache is what archive-sprint owns. Ending the cache and ending the milestone are different events.

## Guard

`.teaparty/project/sprint/sprint.yaml` must exist. If it doesn't, there is nothing to archive — reply that and stop.

## Steps

### 1. Identify still-open Approved items

Read `.teaparty/project/sprint/index.md`. Find every row whose `status` is `Approved` (i.e. tier 1 work that never made it to Done or to Won't Do). For each one, optionally call `read_board_status(number)` if you want to confirm GitHub agrees with the cache — but the cache is the source of truth and a single board call per issue is enough; do not bulk-fetch.

If there are any, surface them in the reply (see step 4). The warning is informational; it does not stop the archive.

### 2. Archive the cache

Move `.teaparty/project/sprint/` to `.teaparty/project/sprint-archive/{milestone}-{YYYY-MM-DD}/`. Use the milestone title (slugified) and today's date for the suffix. Use `Bash` for the rename:

```bash
mv .teaparty/project/sprint .teaparty/project/sprint-archive/{slug}-{date}
```

The cache is preserved on disk (history matters; `git log` in the project will show the archive directory entries) but no longer at the active path, so the next `sprint-plan` finds an empty `.teaparty/project/sprint/` and can proceed.

### 3. Do **not** close the milestone

Explicitly: this skill must not call any milestone-closure tool. The milestone stays open on GitHub regardless of what archive-sprint does. If the human wants the milestone closed, they will do that separately (the `close-milestone` skill at the user level handles that flow).

### 4. Reply

If there were still-open Approved items:

```
Sprint archived: {milestone title}.

Warning — these Approved items were still open when the sprint ended:
  #429  Scrum master agent with local board cache
  #430  ...

The milestone on GitHub is unchanged (closure is a human decision).
```

If everything was Done or Won't Do:

```
Sprint archived: {milestone title}. All Approved items reached Done or Won't Do.

The milestone on GitHub is unchanged (closure is a human decision).
```

## What this skill does not do

- It does not close the GitHub milestone. (Repeat: milestone closure is a human decision.)
- It does not close any individual issues.
- It does not delete history. The cache is moved to `sprint-archive/`, not removed.
