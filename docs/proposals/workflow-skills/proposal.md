[Milestone 4: Proxy Evolution](../milestone-4.md) >

# Workflow Skills

Organizations learn. Workflow skills are what that learning looks like as executable structure — CfA patterns that have earned enough collective trust to run directly, without the full negotiation cycle.

---

## The Spectrum

CfA is System 2: deliberate, expensive, negotiated at every gate. It handles anything because it assumes nothing. A workflow skill is crystallized System 2 knowledge — a trusted pattern the collective has executed enough times to run on autopilot.

```
Full CfA ←——————————————————————————→ Direct skill invocation
(novel, expensive, fully negotiated)   (known pattern, cheap, autonomous)
```

Work moves rightward as experience accumulates. It moves left when a skill encounters something it cannot handle — which resolves through local escalation and extends the skill, so next time it stays right.

---

## Skill Graphs

A workflow skill is a continuation chain: a `SKILL.md` entry point and a set of phase files, each ending with a `Next:` pointer. The agent navigates by following pointers. Sequencing is deterministic; behavior within each phase is agent-guided.

The fix-issue skill in `.claude/skills/fix-issue/` is the existence proof of this pattern. A workflow skill uses the same structure at the CfA level — phases instead of issue-resolution steps, escalation via MCP tools instead of `gh` commands.

See [references/skill-graph.md](references/skill-graph.md) for the phase file format and gate mechanics. See [examples/research-workflow.md](examples/research-workflow.md) for an end-to-end walkthrough.

---

## Crystallization

When multiple CfA sessions for the same task category converge on the same decomposition — same phase sequence, same gate outcomes, same exception resolutions — the learning system has enough evidence to propose a skill. The Skills Specialist creates it; the human approves at the gate.

Crystallization produces two artifacts: the skill graph (the phase chain) and the skill frontmatter (the applicability boundary — when to use this skill and, critically, when not to).

See [references/crystallization.md](references/crystallization.md) for the convergence signal, open design questions, and relationship to the existing post-session pipeline.

---

## Exception Handling and Graph Extension

A skill running autonomously will eventually encounter a case it cannot handle. The agent escalates via `AskQuestion` — a local CfA invocation at the exception point. The MCP escalation tools provide the consistent signal shape: *at phase X, condition Y, resolution Z*.

When the same exception recurs at the same phase across multiple sessions, the resolution pattern is an **extension candidate** — a new branch node inserted at that point in the graph:

```
phase-survey.md
  → (normal)               phase-synthesize.md
  → (source inaccessible)  phase-survey-fallback.md → phase-synthesize.md
```

Two operations keep the graph healthy:
- **Refinement** — improving an existing phase node's content
- **Extension** — inserting a new branch to cover a previously unhandled case

When escalation indicates mismatch rather than a new case, the `does-not-apply-when` boundary tightens instead.

The escalation receiver during skill execution is an open design question — see [#340](https://github.com/dlewissandy/teaparty/issues/340).

---

## Collective Learning

Workflow skills are the organization's procedural memory — not one team's workflow but what the collective has learned about a category of work.

The same promotion chain that moves declarative learnings upward (team → project → global) applies to skill graphs. A skill crystallized from one team's sessions promotes when the pattern holds across teams. Other teams inherit both the happy-path graph and the accumulated exception branches — without having to earn them through their own escalations.

User feedback is the signal that drives the whole system:

| Signal | Source | Effect |
|--------|--------|--------|
| Gate approval | Human approves plan or phase gate | Reinforcement — path was correct |
| Correction | Human edits plan, redirects phase | Refinement — update phase node |
| Escalation (handled, recurring) | Same exception at same phase | Extension — graph grows a branch |
| Escalation (mismatch) | Wrong skill invoked | Boundary tightens — `does-not-apply-when` |
| Intervention / backtrack | INTERVENE event | Structural — graph shape was wrong |

---

## Classification

How a lead knows a task matches an existing skill well enough to skip CfA is deferred until the skill library is large enough to make it a practical problem. At current scale, the lead reads all skill descriptions in context and decides. The `applies-when`/`does-not-apply-when` frontmatter is designed with the future classifier in mind — writing it precisely at crystallization time is the investment.

One requirement is non-deferred: classification failure must always degrade gracefully to full CfA, never to best-guess skill invocation. See [#339](https://github.com/dlewissandy/teaparty/issues/339).

---

## Open Design Questions

The audit surfaced four questions requiring resolution before implementation planning:

- [#336](https://github.com/dlewissandy/teaparty/issues/336) — Crystallization detection: no named component, no algorithm
- [#337](https://github.com/dlewissandy/teaparty/issues/337) — Engine dispatch path for skill invocation: unspecified
- [#338](https://github.com/dlewissandy/teaparty/issues/338) — Structural convergence: no defined similarity measure
- [#340](https://github.com/dlewissandy/teaparty/issues/340) — Escalation during skill execution: no defined receiver

---

## Prerequisites

- [Configuration Team](../configuration-team/proposal.md) — Skills Specialist creates and extends workflow skills via MCP tools
- [CfA Extensions](../cfa-extensions/proposal.md) — INTERVENE and WITHDRAW are the structural signals for backtrack-driven learning
- [Self-Improvement](../self-improvement/proposal.md) — agent-initiated workflow change proposals flow through the CfA gate
- [Team Configuration](../team-configuration/proposal.md) — per-team `workflow_skill` config entry (to be defined; see #337)

---

## Relationship to Other Proposals

- [learning-system.md](../../conceptual-design/learning-system.md) — skill crystallization and refinement are the procedural learning mechanisms this proposal extends with graph extension
- [strategic-planning.md](../../conceptual-design/strategic-planning.md) — warm-start skill seeding is the planning-phase precursor to direct skill invocation
- [self-improvement](../self-improvement/proposal.md) — agent-initiated workflow change proposals are graph extension proposals routed through the CfA gate
- [cognitive-architecture.md](../cognitive-architecture.md) — Voyager's skill library and CLIN's cross-episode causal learning are the closest prior art
