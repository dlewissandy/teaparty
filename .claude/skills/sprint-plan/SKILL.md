---
name: sprint-plan
description: Sprint planning — validate design coverage for a milestone, assign backlog tickets, and create new tickets to cover gaps between design docs, code, and existing tickets.
argument-hint: <milestone-number>
user-invocable: true
---

# Sprint Planning

Plan work for a milestone by delegating each phase to a subagent.

- `$0` — GitHub milestone number (required)
- Each phase runs as a subagent to keep this context lean.
- Pass milestone info and upstream results to each agent via its prompt.

## Phase 0: Load Milestone

```bash
gh api repos/:owner/:repo/milestones/$0 --jq '{number, title, description, state, open_issues, closed_issues}'
```

If the milestone doesn't exist or is closed, stop.

Save the milestone title and description for use in subagent prompts.

## Phase 1: Design Readiness

Launch an **architect** agent. Read `design-readiness.md` in this skill directory for the agent prompt template. Pass the milestone title and description.

Wait for the result. **If design is insufficient, HALT.** Report the gaps and stop.

## Phase 2: Backlog Scan

Launch a **general-purpose** agent. Read `backlog-scan.md` in this skill directory for the agent prompt template. Pass the milestone title, description, and the Phase 1 summary table.

## Phase 3: Gap Analysis

Launch a **general-purpose** agent. Read `gap-analysis.md` in this skill directory for the agent prompt template. Pass the milestone title, description, Phase 1 summary table, and Phase 2 assigned ticket list.

## Phase 4: Summary

Collect results from all three phases and report to the user: milestone scope, design coverage assessment, tickets assigned from backlog, new tickets filed, and any open risks.
