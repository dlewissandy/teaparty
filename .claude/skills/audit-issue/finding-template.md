# Finding Template

Each finding is posted as an intent statement — not a bug report, not a code review comment. It states what the system should be doing and isn't, using the same structure as INTENT.md.

## Template

```markdown
### {finding title}

**Objective:** {What capability, behavior, or property should exist after this issue is resolved? Frame in terms of the system's intent, not code mechanics.}

**Success Criteria:** {How would you know this is done? Observable, testable conditions — not "the code is correct" but "when X happens, Y is the result."}

**Decision Boundaries:** {What is in scope for this finding and what is not? Where does this finding's concern end and another's begin?}

**Constraints:** {Design docs, specs, or existing architecture that bound how this should be addressed. Reference specific doc paths and sections.}

**Open Questions:** {Ambiguities in the design docs or issue that make it unclear what the right answer is. If none, omit this section.}
```

## Rules

- **Intent first, code second.** The Objective should be understandable without reading the codebase.
- **Reference the design.** Every finding MUST cite the relevant design doc. If none exists, say so.
- **What and why, not how.** Describe what should exist, not how to implement it.
- **No hedging.** Don't say "this might be incomplete." State what is missing.
- **Ambiguities are findings.** If the design doc is unclear about what the code should do, that is itself a finding worth stating.
