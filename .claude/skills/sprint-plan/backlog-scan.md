# Backlog Scan Procedure

Scan unassigned issues for tickets that belong in this milestone.

## Step 1: Fetch unassigned issues

```bash
gh issue list --no-milestone --state open --json number,title,body,labels --limit 200
```

Also check issues assigned to other open milestones that might be misplaced:

```bash
gh issue list --state open --json number,title,body,labels,milestone --limit 200
```

## Step 2: Score relevance

For each unassigned issue, assess whether it falls within the milestone's scope. Use the milestone description and design docs as the reference — not intuition about what "sounds related."

A ticket belongs in this milestone if:
- It implements a capability described in the milestone description or referenced design docs
- It fixes a bug in code that this milestone will build on or modify
- It resolves a design question that blocks milestone work
- It is explicitly referenced as a dependency in a design doc

A ticket does NOT belong if:
- It's about a system area this milestone doesn't touch
- It's a nice-to-have improvement unrelated to the milestone's driving features
- It depends on work from a future milestone

## Step 3: Assign

For each ticket that belongs:

```bash
gh issue edit <number> --milestone "<milestone title>"
```

## Step 4: Report

List assigned tickets grouped by which driving feature they support:

```
### Feature 1: <name>
- #NNN <title> — <why it belongs>
- #NNN <title> — <why it belongs>

### Feature 2: <name>
...

### Cross-cutting
- #NNN <title> — <why it belongs>
```
