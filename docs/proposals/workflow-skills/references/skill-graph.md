[Workflow Skills](../proposal.md) >

# Skill Graph Structure

## Phase File Format

Each phase file is a markdown document containing:
- Instructions for what the agent does in this phase
- Any gate conditions (calls to `AskQuestion` if criteria aren't met)
- A `**Next:**` pointer to the following phase file

```markdown
# Phase: Survey

1. Search the literature. Cover at least three research traditions.
2. Record sources with sufficient provenance for citation.
3. If fewer than five credible sources are found → call `AskQuestion` to clarify scope before proceeding.

**Next:** Read `phase-synthesize.md` in this skill directory.
```

The `**Next:**` pointer is the continuation. The agent is instructed to follow it — sequencing is deterministic. Judgment is exercised within the phase, not about which phase comes next.

---

## Branching

Exception branches extend the graph at a specific phase:

```markdown
# Phase: Survey

1. Search the literature...
2. If sources are inaccessible (paywall, retracted, unavailable) →
   Read `phase-survey-source-fallback.md` in this skill directory.

**Next:** Read `phase-synthesize.md` in this skill directory.
```

The fallback file is a full phase file. It ends with its own `**Next:**` pointer, which typically rejoins the main chain:

```markdown
# Phase: Survey — Source Fallback

Handle the inaccessible source case...

**Next:** Read `phase-synthesize.md` in this skill directory.
```

---

## Gate Mechanics During Skill Execution

Gates within phase files use the MCP escalation tools — the same tools available in any CfA context:

- `AskQuestion` — surface a decision to the human or proxy
- `WithdrawSession` — terminate the session if the skill cannot proceed

**Open question:** When the CfA engine is not actively driving the state machine (because the skill bypassed it), `AskQuestion` has no defined state-machine receiver. The engine's approval gate routing depends on an active CfA state. This must be resolved before implementation. See [#340](https://github.com/dlewissandy/teaparty/issues/340).

---

## Re-entry

The `--from-phase <name>` pattern (demonstrated in fix-issue) applies to workflow skills. An interrupted or partially-executed skill can be resumed from any named phase without replaying from the start. This is the recovery path for INTERVENE-triggered backtracks.

---

## SKILL.md Entry Point

```yaml
---
name: research-paper
description: Write a research paper. Systematic investigation of a question, documented sources, structured written artifact.
applies-when:
  - systematic investigation of a question with documented sources
  - output is a structured written artifact
does-not-apply-when:
  - task requires original empirical data collection
  - scope is a single-source summary
  - audience is non-academic and citation formality is not required
argument-hint: "<topic> [--from-phase <phase-name>]"
user-invocable: false
model-invocable: true
crystallized-from: 4 sessions
---

# Research Paper

[entry point instructions and phase sequence]

**Phase sequence:** phase-survey.md → phase-synthesize.md → phase-draft.md → phase-validate.md → phase-finalize.md
```

The `applies-when` / `does-not-apply-when` pair encodes the applicability boundary. It is required at crystallization time — not optional — because it is the input a future classifier will use. See [crystallization.md](crystallization.md).
