# Issue Filing Template

When creating GitHub issues from audit findings, use this structure. The goal is an issue that reads like a problem statement, not a code review comment. Someone should understand what's wrong and why it matters without reading the code.

## Template

```markdown
[Audit finding {ID}]

## Problem

{What is broken or missing, framed in terms of the system's intent — not in terms of code mechanics. Why does this matter? What goes wrong for the user, the agent, or the research results? Reference the design document that describes the intended behavior.}

## What needs to change

{Describe the desired behavior — what the system should do instead. This is the "what", not the "how". Do not prescribe an implementation. If the finding reveals a design ambiguity or contradiction, say so explicitly and frame the issue as a design decision rather than a code fix.}

## References

- [{design doc name}]({path}) — {which section is relevant and why}
- #{related issue number} — {how it relates: blocks, depends on, complements, contradicts}
- [{conceptual design doc}]({path}) — {if applicable}

---
*Found by `/audit` — reviewers: {which reviewers flagged this}*
```

## Rules

- **Problem first, code second.** The Problem section should be understandable without knowing the codebase. Code locations belong in the commit that fixes it, not in the issue.
- **Reference the design.** Every issue MUST reference the relevant design doc (in `docs/detailed-design/`, `docs/conceptual-design/`, or `docs/proposals/`). If no design doc exists for this area, say so — that's itself useful information.
- **Link related tickets.** If the finding relates to, depends on, or contradicts an existing issue, reference it.
- **What and why, not how.** Describe the desired behavior, not the implementation. Let the person fixing it decide how.
- **No hedging.** Don't say "this could potentially cause issues." State what breaks.
- **Design contradictions are design issues.** If the code disagrees with the docs and it's unclear which is right, frame the issue as a design decision, not a bug fix.

## Anti-patterns (do NOT do these)

- Starting with `file.py:123` — that's a code review comment, not an issue
- Prescribing the fix ("should use embedding similarity instead of Jaccard")
- Omitting design doc references
- Framing everything as a bug — some findings are design gaps, doc drift, or missing features
- Labels: always include `audit`, plus one of: `bug`, `documentation`, `enhancement`
