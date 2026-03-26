# Design Readiness Checklist

For a milestone to proceed to sprint planning, the design must be sufficient to guide implementation. This means:

## What to check

1. **Milestone description references design docs.** The description should point to docs in `docs/proposals/`, `docs/conceptual-design/`, or `docs/detailed-design/`. If it doesn't, that's the first gap.

2. **Each major capability has a design doc.** Parse the milestone description for its driving features. Each one should have at least a proposal or conceptual design doc that describes what the system should do and why. Code-level detailed design is not required — that can emerge during implementation — but the conceptual intent must be written down.

3. **Design docs are current.** Read each referenced doc. Check for:
   - Open questions that would block implementation (vs. open questions that can be resolved during implementation)
   - References to code or systems that no longer exist
   - Contradictions between docs (one says X, another says not-X)

4. **No orphan capabilities.** Cross-reference the milestone description against the design docs. Are there capabilities mentioned in the milestone that no doc covers? These are design gaps.

## What constitutes "sufficient"

- Every driving feature has a conceptual design or proposal that describes the intended behavior
- No blocking open questions (questions that must be answered before any work can start)
- The design docs are consistent with each other

## What does NOT block

- Missing detailed design — implementation will produce this
- Open questions about tuning parameters, thresholds, or configuration values
- Open questions explicitly marked as "resolve during Phase 1" or "empirical"
- Missing research docs — research informs design but doesn't block implementation

## Output

If insufficient: list each gap as a concrete action item ("Need proposal for X", "Resolve contradiction between Y and Z", "Open question Q blocks all work on feature F").

If sufficient: summarize the design landscape as a table:

| Capability | Design Doc | Coverage | Open Questions |
|-----------|-----------|----------|---------------|
| Feature A | proposals/foo.md | Full | None blocking |
| Feature B | conceptual-design/bar.md | Partial — missing Z | Q1: resolve before work starts |
