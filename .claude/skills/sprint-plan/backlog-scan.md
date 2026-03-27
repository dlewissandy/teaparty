# Phase 2: Backlog Scan

## Agent Setup

Launch as a **general-purpose** agent with this prompt:

> Scan the issue backlog for tickets that belong in a milestone. Here is the milestone:
>
> **Title:** {title}
> **Description:** {description}
>
> **Design landscape from Phase 1:**
> {paste the Phase 1 summary table}
>
> Read `.claude/skills/sprint-plan/backlog-scan.md` for the full procedure and follow it.
>
> Assign matching tickets with `gh issue edit <number> --milestone "{title}"`.
>
> Return: the list of assigned tickets grouped by driving feature, and any tickets you considered but rejected (with reasons).

---

## Procedure

### Step 1: Fetch issues

```bash
gh issue list --no-milestone --state open --json number,title,body,labels --limit 200
```

Also check issues assigned to other open milestones that might be misplaced:

```bash
gh issue list --state open --json number,title,body,labels,milestone --limit 200
```

### Step 2: Score relevance

For each unassigned issue, assess whether it falls within the milestone's scope. Use the Phase 1 summary table as the reference — it lists the capabilities and their design docs. Only read a design doc if you need to check whether a specific issue falls within its scope.

**Belongs** if it:
- Implements a capability described in the milestone description or design docs
- Fixes a bug in code this milestone will build on or modify
- Resolves a design question that blocks milestone work
- Is explicitly referenced as a dependency in a design doc

**Does NOT belong** if it:
- Is about a system area this milestone doesn't touch
- Is a nice-to-have improvement unrelated to the driving features
- Depends on work from a future milestone

### Step 3: Assign

```bash
gh issue edit <number> --milestone "<milestone title>"
```

### Step 4: Report

Group assigned tickets by driving feature:

```
### Feature 1: <name>
- #NNN <title> — <why it belongs>

### Cross-cutting
- #NNN <title> — <why it belongs>
```
