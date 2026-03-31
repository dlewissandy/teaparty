[Workflow Skills](../proposal.md) >

# Crystallization

## What Triggers It

Crystallization is proposed — not automatic — when the post-session pipeline observes that multiple sessions for the same task category converged on the same structure. The signal is convergence across N sessions (N ≥ 3 as a starting candidate; empirical tuning needed).

"Same structure" means:
- The phase sequence is consistent across sessions (same phases, same ordering)
- Gate outcomes at the same decision points are consistent (same approvals, same escalation patterns)
- Exception resolutions at the same phases are consistent

Parameters vary across sessions (topic, audience, depth). Structure does not (sequencing, review gates, fan-out/fan-in). Crystallization extracts what is invariant and parameterizes what varies.

**Open question:** Neither "same phase sequence" nor "same gate outcomes" is currently operationalized as a computable predicate. The comparison unit, similarity measure, and threshold are undefined. See [#336](https://github.com/dlewissandy/teaparty/issues/336) and [#338](https://github.com/dlewissandy/teaparty/issues/338).

---

## What It Produces

Two artifacts:

**The skill graph** — the phase file chain. Each phase file encodes what the agent does, any gate conditions, and the `Next:` pointer. Branch nodes for known exception cases are included if the contributing sessions resolved them consistently.

**The skill frontmatter** — the applicability boundary. Required fields:
- `applies-when` — task shapes this skill covers (positive examples)
- `does-not-apply-when` — near-misses that look like matches but aren't (negative examples)
- `crystallized-from` — count of contributing sessions (provenance)

The `does-not-apply-when` list is as important as `applies-when`. It encodes the boundary cases where the skill was invoked incorrectly and the graph was extended to say "not this one." Without it, near-miss misclassification accumulates silently.

---

## Who Does the Work

The Skills Specialist creates the skill. The convergence signal is surfaced by the post-session pipeline; whether that detection is automated or requires human review of session histories is an open question (see [#336](https://github.com/dlewissandy/teaparty/issues/336)). The human approves at the CfA gate before the skill is registered in the team's configuration.

The Skills Specialist tool (`CreateSkill`) handles structural validation. The Configuration Lead coordinates if a new skill requires agent definition changes (e.g., adding the skill to a team lead's `skills:` allowlist).

---

## Relationship to the Existing Pipeline

The current post-session pipeline (`learnings.py`) extracts declarative knowledge: task learnings, institutional learnings, proxy learnings. Crystallization is a different operation: structural comparison of session traces to detect convergent decomposition patterns.

These are not the same pipeline. The existing pipeline processes one session. Crystallization requires cross-session data. Designing crystallization detection as a new pipeline component — with defined inputs (session history representation), algorithm, and output format — is the open work in [#336](https://github.com/dlewissandy/teaparty/issues/336).

---

## Refinement and Extension After Crystallization

Once a skill exists, two operations modify it:

**Refinement** — improving the content of an existing phase node. Triggered by corrective learnings that trace back to a specific phase: the phase produced work that required correction, the skill structure didn't anticipate the issue, and the fix is a content change (better instructions, tighter criteria, additional context).

**Extension** — inserting a new branch node at a recurring exception point. Triggered when the same exception occurs at the same phase across multiple skill executions, and the resolution is consistent. The new branch becomes part of the skill graph; future executions follow it autonomously.

The decision between refinement and extension is itself an open design question — the learning system needs a procedure for distinguishing "this phase needs better instructions" from "this phase needs a new branch." See the parking lot note in `audit/triage.md` (A-011).
