# Phase 1: Design Readiness

## Agent Setup

Launch as an **architect** agent with this prompt:

> Assess design readiness for a milestone. Here is the milestone:
>
> **Title:** {title}
> **Description:** {description}
>
> Read `.claude/skills/sprint-plan/design-readiness.md` for the full procedure and follow it.
>
> Return a structured assessment: a table of capabilities with their design doc, coverage level, and blocking open questions. End with a clear verdict: SUFFICIENT or INSUFFICIENT with specific gaps listed.

---

## Procedure

### Step 1: Find the entry point

The milestone description references a design document (e.g., `docs/proposals/milestone-3.md`). Read that document. It is the entry point to the design — a landing page with a proposals table and links to sub-documents.

Do NOT read every linked document upfront. Use progressive disclosure:
1. Read the landing page to understand the scope and identify the proposals.
2. For each proposal, read only the `proposal.md` to understand the feature.
3. Only follow links into `references/` or `examples/` when you need detail to assess a specific coverage question.

### Step 2: Check design coverage

For each major capability in the milestone description:
- Does a proposal describe the intended behavior?
- Are there blocking open questions in the proposal? (Questions that must be answered before work can start)

### Step 3: Targeted code review

For capabilities that claim to extend existing code, verify the claims:
- Use Grep/Glob to find the code referenced in the proposal (e.g., `proxy_memory.py`, `engine.py`, `actors.py`)
- Read the relevant sections to confirm the code is as described
- Flag contradictions between the proposal and the actual code

This is not a full code audit. Only check code when a proposal makes a specific claim about existing infrastructure ("the orchestrator already parses stream-json", "the proxy records learnings immediately").

### Step 4: Assess sufficiency

**Sufficient** means:
- Every driving feature has a proposal describing intended behavior
- No blocking open questions
- Proposals are consistent with each other and with the codebase

**Does NOT block:**
- Missing detailed design — implementation produces this
- Open questions about tuning parameters, thresholds, or configuration
- Open questions marked "empirical" or "resolve during implementation"

### Step 5: Return verdict

If **insufficient**, list each gap as a concrete action item ("Need proposal for X", "Resolve contradiction between Y and Z", "Open question Q blocks all work on feature F").

If **sufficient**, return a summary table:

| Capability | Design Doc | Coverage | Open Questions |
|-----------|-----------|----------|---------------|
| Feature A | proposals/foo/proposal.md | Full | None blocking |
| Feature B | proposals/bar/proposal.md | Partial — missing Z | Q1: resolve before work starts |
