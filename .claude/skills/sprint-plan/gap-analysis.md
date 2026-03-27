# Phase 3: Gap Analysis

## Agent Setup

Launch as a **general-purpose** agent with this prompt:

> Perform gap analysis for a milestone. Here is the milestone:
>
> **Title:** {title}
> **Description:** {description}
>
> **Design landscape from Phase 1:**
> {paste the Phase 1 summary table}
>
> **Tickets already assigned (from backlog scan):**
> {paste the Phase 2 assigned ticket list}
>
> Read `.claude/skills/sprint-plan/gap-analysis.md` for the full procedure and follow it. Use `.claude/skills/audit/issue-template.md` for the ticket template — replace `[Audit finding]` with `[Sprint planning]` and the footer with `*Found by /sprint-plan*`.
>
> File new tickets for gaps. Return: the coverage summary table from Step 5.

---

## Procedure

### Step 1: Build the capability map

From the Phase 1 summary table, identify each capability and its design doc. Read the proposal for each capability — follow links into references only when you need implementation-level detail. Extract concrete capabilities specific enough to be a ticket — not "support dialog" but "proxy steps aside when human is present and resumes when they leave."

### Step 2: Understand the current system

**Read the code, not just docs.** For each capability area, use Grep/Glob/Read to find implementing code in `projects/POC/orchestrator/`, `projects/POC/tui/`, and `projects/POC/scripts/`. Read key files — entry points, data structures, wiring.

**Read the detailed design docs** in `docs/detailed-design/`. Cross-reference against the code — docs may be stale.

**Read the tests** in `projects/POC/orchestrator/tests/`. Missing test coverage is itself a signal.

**Trace integration points.** For capabilities spanning modules, trace how they connect. Identify where wiring exists and where it doesn't.

Build a picture of:
- What code exists for each capability area
- What that code actually does (not what docs say)
- Where the code stops — the boundary between implemented and not-yet
- What infrastructure exists that new capabilities can build on
- What infrastructure is missing and must be built first

### Step 3: Map coverage

For each capability from Step 1:

1. **Implemented** — code exists and matches design. No ticket needed.
2. **Partial** — code exists but doesn't fully match. Describe what's there and what's missing.
3. **Infrastructure exists** — no implementation yet, but the code it would plug into is in place.
4. **Infrastructure missing** — neither capability nor its plumbing exists. May need multiple tickets.
5. **Gap** — nothing exists.

Check whether an assigned ticket already covers each capability.

### Step 4: File gap tickets

For each gap, partial, or infrastructure-missing capability, create a ticket using the template from `.claude/skills/audit/issue-template.md`.

Each ticket must:
- Reference the design doc and section
- Describe desired behavior (what, not how)
- Describe what exists today (for partial gaps)
- Describe infrastructure dependencies
- Link related tickets and note dependencies

```bash
gh issue create --title "<title>" --body "<body>" --milestone "<milestone title>"
```

Add to project board:

```bash
gh api graphql -f query='mutation {
  addProjectV2ItemById(input: {
    projectId: "PVT_kwHOAH4OHc4BR81E"
    contentId: "<issue node ID from: gh issue view N --json id --jq .id>"
  }) { item { id } }
}'
```

### Step 5: Report

| Capability | Status | What Exists | Ticket | Design Doc |
|-----------|--------|-------------|--------|-----------|
| Feature X | Gap | Nothing | #NNN (filed) | proposals/foo.md §Section |
| Feature Y | Partial | `proxy_agent.py` has retrieval, missing handoff | #NNN (filed) | conceptual-design/bar.md §Section |
| Feature Z | Implemented | `engine.py:120-150` | — | detailed-design/baz.md §Section |
