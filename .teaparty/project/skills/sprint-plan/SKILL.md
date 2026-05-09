---
name: sprint-plan
description: Bootstrap the local sprint cache for a milestone. Discovers the Projects V2 board, fetches all milestone issues, and writes sprint.yaml, index.md, and per-issue notes. Read-mostly — only writes to the cache; does not mutate the GitHub board.
allowed-tools: Read, Write, Edit, Glob, Grep, mcp__teaparty-config__list_milestones, mcp__teaparty-config__list_milestone_issues, mcp__teaparty-config__read_issue, mcp__teaparty-config__list_project_boards, mcp__teaparty-config__read_board_status
user-invocable: false
argument-hint: <milestone>
---

# sprint-plan

Bootstrap the local sprint cache from a GitHub milestone. After this runs, the project lead and any other agent on the team can read sprint state from `.teaparty/project/sprint/` without re-hitting the GitHub API.

`sprint-plan` is read-mostly: it builds the cache from GitHub, but it does not change Status fields or move items on the board. Tier and wave assignments are filled in later by the project lead through `prioritize`.

## Inputs

- `milestone` — milestone name or number (required).

## Guard

If `.teaparty/project/sprint/sprint.yaml` already exists, refuse to overwrite. Tell the caller to run `archive-sprint` first if they want to start a new sprint, or `refresh-board` if they want to bring an existing sprint up to date.

## Steps

### 1. Resolve the milestone

Call `list_milestones`. Match the input against the `number` and `title` fields. If neither matches, abort with the available options listed.

### 2. Discover the sprint board

Call `list_project_boards`. Pick the board whose Status field carries the canonical option set (`Backlog`, `Approved`, `In Progress`, `Done`, `Won't Do`). The MCP layer already filters to that board; if the response is empty, abort and report — there is no board to plan against.

Capture the board's `id`, `number`, `status_field_id`, and the option ids for the five Status names. These go into `sprint.yaml`.

### 3. Fetch all milestone issues

Call `list_milestone_issues(milestone, state='all')`. The result includes every issue (open and closed) attached to the milestone. For each issue, also call `read_issue(number)` to get its body — `index.md` only stores the title, but per-issue files keep the body for triage.

### 4. Write `sprint.yaml`

Cache directory layout: `.teaparty/project/sprint/{sprint.yaml, index.md, issues/{N}.md}`.

Sprint metadata, written exactly once at planning time:

```yaml
milestone:
  number: 4
  title: "Tier 4: Proxy Evolution"
repo:
  owner: dlewissandy
  name: teaparty
board:
  id: PVT_kwHOAH4OHc4BR81E
  number: 2
  status_field_id: PVTSSF_lAHOAH4OHc4BR81Ezg_oGbs
  options:
    Backlog: a76a90c5
    Approved: 1eb3c52a
    "In Progress": 71f64e69
    Done: 42fb9610
    "Won't Do": e4544388
sprint:
  started: 2026-05-09  # date sprint-plan ran
```

### 5. Write `index.md`

The fast-lookup table. Columns are fixed: **issue #**, **title**, **status**, **tier**, **wave**. Status comes from each issue's current board state (call `read_board_status(number)` for each, or use the data already returned by step 3 if the listing included it). Tier and wave are blank at planning time — they're filled in by `prioritize`.

```markdown
# {milestone title} — Sprint Index

| issue # | title | status | tier | wave |
|---------|-------|--------|------|------|
| #429 | Scrum master agent with local board cache | In Progress | 1 | 1 |
| #430 | ... | Backlog | | |
```

The `tier` and `wave` columns are blank for any issue the project lead has not yet placed.

### 6. Write per-issue files

For each issue, write `.teaparty/project/sprint/issues/{N}.md` with this fixed schema:

```markdown
---
number: 429
title: Scrum master agent with local board cache
state: open
labels: []
status: In Progress
tier:
wave:
---

{full issue body verbatim from GitHub}
```

The frontmatter is what `refresh-board`, `prioritize`, and the mark-* skills read and write. The body is the issue text — never modify it after planning, even on refresh.

### 7. Reply

Print a short summary:

```
Sprint planned: {milestone title}
{N} issues cached at .teaparty/project/sprint/
```

Do not change Status fields on the board. Tier assignment and the matching board moves happen later through `prioritize`.
