# Gap Analysis Procedure

Compare design docs against code and assigned tickets to find uncovered work.

## Step 1: Build the capability map

From the design docs read in Phase 1, extract a list of concrete capabilities the milestone requires. Each capability should be specific enough to be a ticket — not "support dialog" but "proxy steps aside when human is present and resumes when they leave."

## Step 2: Map existing coverage

For each capability, check:

1. **Is there an assigned ticket?** Search the milestone's issues for one that covers this capability.
2. **Is it already implemented?** Search the codebase (`projects/POC/orchestrator/`, `projects/POC/tui/`) for code that implements it. Use Grep and Glob.
3. **Is it partially implemented?** Code exists but doesn't match the design — this is a gap ticket, not a skip.

Mark each capability as: **covered** (ticket exists), **implemented** (code exists, no ticket needed), **partial** (code exists but incomplete — needs ticket), or **gap** (nothing exists — needs ticket).

## Step 3: File gap tickets

For each gap or partial capability, create a ticket. Read `.claude/skills/audit/issue-template.md` for the template format.

Each ticket must:
- Reference the design doc and section that describes the capability
- Describe the desired behavior (what, not how)
- Note what exists today (for partial gaps)
- Link to related tickets if applicable

```bash
gh issue create --title "<title>" --body "<body>" --milestone "<milestone title>"
```

Add to the project board:

```bash
# Add to project
gh api graphql -f query='mutation {
  addProjectV2ItemById(input: {
    projectId: "PVT_kwHOAH4OHc4BR81E"
    contentId: "<issue node ID>"
  }) { item { id } }
}'
```

Get the issue node ID from `gh issue view <number> --json id --jq .id` (note: this returns the node_id needed for the GraphQL mutation).

## Step 4: Report

Summary table:

| Capability | Status | Ticket | Design Doc |
|-----------|--------|--------|-----------|
| Feature X behavior | Gap — filed | #NNN | proposals/foo.md §Section |
| Feature Y wiring | Covered | #NNN | conceptual-design/bar.md §Section |
| Feature Z | Implemented | — | detailed-design/baz.md §Section |
