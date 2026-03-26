---
name: sprint-plan
description: Sprint planning — validate design coverage for a milestone, assign backlog tickets, and create new tickets to cover gaps between design docs, code, and existing tickets.
argument-hint: <milestone-number>
user-invocable: true
---

# Sprint Planning

Plan work for a milestone by ensuring design coverage, assigning relevant backlog tickets, and filing gap tickets.

- `$0` — GitHub milestone number (required)
- Use **Read**, **Grep**, **Glob** for file operations. Reserve Bash for `git`, `gh`, and shell commands.

## Phase 0: Load Milestone

```bash
gh api repos/:owner/:repo/milestones/$0 --jq '{number, title, description, state, open_issues, closed_issues}'
```

If the milestone doesn't exist or is closed, stop.

## Phase 1: Design Readiness

Read `design-readiness.md` in this skill directory for the full checklist.

Determine whether the milestone description references design or proposal documents. For each referenced doc, read it. Then assess: is there enough design to guide implementation?

**If design is insufficient:** Report what's missing and **HALT**. List the specific design gaps — missing proposals, unresolved open questions, areas with no design coverage. Do not proceed to ticket creation without design.

**If design is sufficient:** Summarize the design landscape — which docs cover which capabilities, and any open questions that are acknowledged but not blocking.

## Phase 2: Assign Backlog Tickets

Read `backlog-scan.md` in this skill directory for the scan procedure.

Scan the unassigned backlog for tickets that belong in this milestone. For each candidate, check whether it fits within the milestone's scope as described in the milestone description and design docs.

Assign matching tickets: `gh issue edit <number> --milestone "<title>"`

Report what was assigned and why.

## Phase 3: Gap Analysis

Read `gap-analysis.md` in this skill directory for the analysis procedure.

Compare the design docs against the current code and the assigned tickets. Identify capabilities described in the design that are not covered by any existing ticket.

For each gap, file a new ticket. Read `.claude/skills/audit/issue-template.md` for the template. File with: `gh issue create --title "<title>" --body "<body>" --milestone "<title>"`

Report what was filed.

## Phase 4: Summary

Post a status update to the GitHub project board summarizing the sprint plan:

```bash
gh api graphql -f query='mutation {
  createProjectV2StatusUpdate(input: {
    projectId: "PVT_kwHOAH4OHc4BR81E"
    status: ON_TRACK
    body: "<summary>"
  }) { statusUpdate { id } }
}'
```

Include: milestone scope, design coverage assessment, tickets assigned from backlog, new tickets filed, and any open risks.
