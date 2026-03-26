---
name: close-milestone
description: Close a GitHub milestone — validate, promote develop to main via rebase+squash, tag, and clean up stragglers.
argument-hint: <milestone-number> [--dry-run]
user-invocable: true
---

# Close Milestone

Promote develop to main for a completed milestone. Rebase, squash, tag, close the milestone, and move any stragglers to unassigned.

- `$0` — GitHub milestone number (required)
- `--dry-run` — show what would happen without doing it

## Tool Usage

Use **Read**, **Write**, **Edit**, **Grep**, **Glob** for file operations. Reserve Bash for `git`, `gh`, and shell commands only.

## Phase 0: Pre-flight

```bash
MILESTONE=$(gh api repos/:owner/:repo/milestones/$0 --jq '{number, title, state, open_issues, closed_issues}')
```

Verify:
1. Milestone exists and is **open**
2. `develop` is ahead of `main` (`git rev-list --count main..develop`)
3. **develop is clean.** `git checkout develop && git status` — if there are uncommitted changes, commit them with a descriptive multiline message using the `Issue #NNN:` template (or a general `Milestone <title>:` prefix if not issue-specific).
4. **Tests pass.** `uv run pytest projects/POC/orchestrator/tests/ --tb=short -q` — if ANY tests fail: create a GitHub issue for each failure (`gh issue create --title "Test failure: <test_name>" --body "<traceback and context>" --milestone "<title>"`), report the failures, and **HALT. Do not proceed.** A milestone cannot close with failing tests.
5. No merge conflicts: `git merge-tree $(git merge-base main develop) main develop` has no conflicts

If any check fails, report clearly and stop.

## Phase 1: Resolve Worktrees and Open Issues

**First, check for outstanding worktrees** with unmerged work for this milestone's issues:

```bash
git worktree list
gh issue list --milestone "<title>" --state all --json number,title,state
```

For each worktree that corresponds to a milestone issue (e.g. `teaparty-issue-NNN` or branch `fix/issue-NNN`):
1. **Check for uncommitted changes** in the worktree: `git -C <worktree-path> status`
2. If there are uncommitted changes, **commit them** using the template: `Issue #NNN: <description>`
3. If the branch is not merged to develop, **merge it**:
   ```bash
   git checkout develop
   git merge --no-ff fix/issue-NNN -m "Merge fix/issue-NNN: <description>"
   ```
4. If the issue has no closing comment describing the work, **post one** via `gh issue view NNN` to check, then `gh issue comment NNN -b "<summary>"` if needed.
5. If the issue is still open, **close it**: `gh issue close NNN`
6. **Remove the worktree**: `git worktree remove <worktree-path>`

**Then handle remaining open issues** (not associated with worktrees):

```bash
gh issue list --milestone "<title>" --state open --json number,title
```

If there are open issues with no worktree:
1. **List them** with number and title
2. **Move each to unassigned milestone:**
   ```bash
   gh issue edit <number> --milestone ""
   ```
3. **Report** what was moved

If `--dry-run`, print what would be done but don't do it.

## Phase 2: Build Commit Message

Fetch the milestone description (preserved here since the milestone will be archived/deleted):

```bash
gh api repos/:owner/:repo/milestones/$0 --jq '.description'
```

Fetch all closed issues in the milestone:

```bash
gh issue list --milestone "<title>" --state closed --json number,title --jq 'sort_by(.number) | .[] | "#\(.number)  \(.title)"'
```

Compose the squash commit message following this format:

```
<Milestone title>

<1-3 sentence summary of what this milestone achieved as a whole>

Issues resolved:

  #NNN  <issue title>
        <2-3 line summary of what changed — the substance, not "fixed it">

  #NNN  <issue title>
        <2-3 line summary>

  ...

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

To write the per-issue summaries: for each closed issue, read its body and comments (`gh issue view <number>`) to understand what was actually done. The summary should describe the change in concrete terms — what was added, removed, or rewired — not just restate the issue title.

### Example (from Tier 1)

```
Tier 1: Infrastructure Stabilization — complete milestone

Squash merge of develop branch containing all 11 issues in the
Tier 1: Infrastructure Stabilization milestone. This establishes
the foundational infrastructure for durable, scalable agent
coordination: formal state machines, resilient dispatch, crash
recovery, and sandbox hardening.

Issues resolved:

  #92   Replace bespoke state management with python-statemachine
        CfAMachine with hooks, guards, and tested transition semantics
        replaces ad-hoc dict manipulation.

  #149  Dispatch subteams survive lead process death
        Bidirectional heartbeat liveness system: .heartbeat files with
        JSON lifecycle state, .children JSONL registry, watchdog priority
        cascade (tool calls > lead events > child events > disk heartbeats),
        parent death detection with graceful shutdown.

  #210  CfA state file write is atomic (write-to-temp + os.replace)
        Prevents corruption from mid-write crashes during state transitions.

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
```

**Write the full commit message to `audit/milestone-commit.md`** for review before proceeding. If `--dry-run`, show the message and stop here.

## Phase 3: Rebase and Squash

```bash
# Ensure we're on develop and up to date
git checkout develop
git pull --rebase origin develop

# Rebase onto main
git rebase main

# Switch to main and squash-merge
git checkout main
git pull --rebase origin main
git merge --squash develop

# Commit with the prepared message
git commit -F audit/milestone-commit.md
```

If the rebase has conflicts, stop and report. Do NOT force through.

## Phase 4: Tag

```bash
# Tag with milestone title, slugified
TAG=$(echo "<milestone-title>" | tr '[:upper:]' '[:lower:]' | tr ' :' '-' | tr -cd 'a-z0-9-')
git tag -a "$TAG" -m "<Milestone title>"
```

## Phase 5: Push

**Ask the user for confirmation before pushing.** Show:
- The squash commit (subject + diffstat)
- The tag name
- Number of open issues moved to unassigned

Then:

```bash
git push origin main --follow-tags
```

After push, check CI status:

```bash
gh run list --branch main --limit 1 --json status,conclusion,name
```

If CI fails: create an issue (`gh issue create --title "CI failure on milestone close: <run name>" --body "<failure details>" --milestone "<title>"`), report the failure, and **HALT. Do not proceed to close the milestone.** The push landed but the milestone stays open until CI is green.

## Phase 6: Close and Archive Milestone

Close the milestone, then delete it to archive. The milestone's title and description are preserved in the squash commit message; the issue list is preserved in both the commit and the individual issues' milestone history.

```bash
# Close first (required before delete)
gh api repos/:owner/:repo/milestones/$0 -X PATCH -f state=closed

# Archive (delete) — removes from milestone list entirely
gh api repos/:owner/:repo/milestones/$0 -X DELETE
```

## Phase 7: Update Project Board

For each issue that was moved to unassigned in Phase 1, update its project board status back to **Backlog** if it was previously In Progress.

## Completion

```
## Milestone Closed

**Milestone:** <title>
**Issues resolved:** <count>
**Tag:** <tag name>
**Commit:** <short sha> <first line>

### Stragglers (moved to unassigned)
- #NNN: <title>
...
(or "None")
```
