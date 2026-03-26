# Gap Analysis Procedure

Compare design docs against the actual codebase and assigned tickets to find uncovered work.

## Step 1: Build the capability map

From the design docs read in Phase 1, extract a list of concrete capabilities the milestone requires. Each capability should be specific enough to be a ticket — not "support dialog" but "proxy steps aside when human is present and resumes when they leave."

## Step 2: Understand the current system

Before assessing gaps, build a grounded understanding of what exists. Do not rely on doc descriptions of the code — read the code itself.

**Read the relevant source files.** For each capability area, use Grep and Glob to find the implementing code in `projects/POC/orchestrator/`, `projects/POC/tui/`, and `projects/POC/scripts/`. Read the key files — entry points, data structures, wiring.

**Read the relevant detailed design docs** in `docs/detailed-design/`. These describe what the code does today and where it falls short. Cross-reference against what you see in the code — the docs may be stale.

**Read the tests** in `projects/POC/orchestrator/tests/`. Tests reveal what behaviors are verified and what edge cases are covered. Missing test coverage for a capability is itself a signal.

**Trace the integration points.** For capabilities that span multiple modules (e.g., "proxy handoff when human arrives" touches the TUI, the approval gate, and the proxy agent), trace how the modules connect. Identify where wiring exists and where it doesn't.

Build a picture of:
- What code exists for each capability area
- What that code actually does (not what docs say it does)
- Where the code stops — the boundary between "implemented" and "not yet"
- What infrastructure exists that new capabilities can build on
- What infrastructure is missing and must be built first

## Step 3: Map coverage

For each capability from Step 1, assess against what you found in Step 2:

1. **Implemented** — code exists and matches the design. No ticket needed.
2. **Partial** — code exists but doesn't match the design, or implements a subset. Describe specifically what's there and what's missing. Needs a ticket.
3. **Infrastructure exists** — no implementation yet, but the code it would plug into is in place. The ticket can focus on the capability itself, not plumbing.
4. **Infrastructure missing** — neither the capability nor the code it would plug into exists. May need multiple tickets: one for infrastructure, one for the capability.
5. **Gap** — nothing exists. Needs a ticket.

Also check assigned tickets: does an existing ticket already cover this capability?

## Step 4: File gap tickets

For each gap, partial, or infrastructure-missing capability, create a ticket. Read `.claude/skills/audit/issue-template.md` for the template format.

Each ticket must:
- Reference the design doc and section that describes the capability
- Describe the desired behavior (what, not how)
- Describe what exists today (for partial gaps — be specific about what code is there)
- Describe what infrastructure the capability depends on (for infrastructure-missing gaps)
- Link to related tickets and note dependencies

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

## Step 5: Report

Summary table:

| Capability | Status | What Exists | Ticket | Design Doc |
|-----------|--------|-------------|--------|-----------|
| Feature X | Gap | Nothing | #NNN (filed) | proposals/foo.md §Section |
| Feature Y | Partial — wired but no Z | `proxy_agent.py` has retrieval, missing handoff | #NNN (filed) | conceptual-design/bar.md §Section |
| Feature Z | Implemented | `engine.py:120-150` | — | detailed-design/baz.md §Section |
| Feature W | Infra missing | No messaging layer exists | #NNN (infra), #NNN (capability) | proposals/qux.md §Section |
