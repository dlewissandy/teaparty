# Workflow Skills: Collective Procedural Learning

**Milestone 4: Proxy Evolution**

The TeaParty learning system already captures declarative knowledge — facts, norms, preferences — across the hierarchy. This proposal adds the procedural dimension: executable workflow patterns that teams acquire through collective experience and invoke directly, bypassing the full CfA negotiation cycle when the pattern is trusted.

---

## The Core Idea

CfA is System 2 thinking: deliberate, expensive, fully negotiated. Every gate fires. Every decision point surfaces to the human or proxy. This is correct for novel work, where the system has no prior pattern to trust.

But organizations learn. After enough sessions producing the same kind of work — research papers, code reviews, deployment procedures — the planning phase converges on the same decomposition, the same gate outcomes, the same exception resolutions. That convergence is information. It means the system has learned how to do this type of work. CfA's full negotiation is no longer earning its cost.

A workflow skill is crystallized System 2 knowledge made executable. When the collective has accumulated enough experience with a task type, that experience compresses into a skill — a navigable graph of phase files that the agent follows directly. The next invocation skips CfA and runs the skill. No planning phase. No multi-round negotiation.

The result is a spectrum:

```
Full CfA ←——————————————————————————→ Direct skill invocation
(novel, expensive, fully negotiated)   (known pattern, cheap, autonomous)
```

Work moves rightward as experience accumulates. It moves left when the skill encounters something it cannot handle — which resolves through a local escalation and extends the graph, so next time it stays right.

---

## Skill Graphs as Executable CfA

A workflow skill is structured as a continuation chain — the same pattern as the `fix-issue` skill. A `SKILL.md` entry point defines the phase sequence. Each phase lives in its own file. Each phase file ends with a `Next:` pointer to the following phase. The agent navigates the graph by following pointers.

```
SKILL.md                  ← entry point, defines the phase sequence
phase-survey.md           ← next: phase-synthesize.md
phase-synthesize.md       ← next: phase-draft.md
phase-draft.md            ← next: phase-validate.md
  → (validation fails)    ← next: phase-validate-fallback.md → phase-draft.md
phase-validate.md         ← next: phase-finalize.md
phase-finalize.md         ← done
```

Sequencing is deterministic — the agent is instructed to follow the `Next:` pointer, not asked to decide where to go. Behavior within each phase is agent-guided and flexible. This is the right division: phases enforce sequence, agents exercise judgment within phases.

The gate mechanism within phases uses the MCP escalation tools: `AskQuestion` for human input, `WithdrawSession` for session-level intervention. These tools are the consistency mechanism — regardless of which workflow skill is running, escalation always goes through the same pathway, producing the same structured signal.

The skill graph IS the crystallized CfA. The phase files are the crystallized phases. The continuation pointers are the crystallized transitions. Exception branches (see below) are the crystallized escalation resolutions. Gate conditions embedded in phase files are the accumulated record of what the proxy has learned to approve autonomously.

---

## Crystallization

Crystallization is the mechanism that produces workflow skills from CfA history. When multiple CfA sessions for the same task category converge on the same decomposition, the learning system extracts that pattern into a reusable skill.

The signal for crystallization is convergence:
- Same phase sequence across N sessions (N ≥ 3 is a candidate threshold)
- Same gate outcomes at the same decision points
- Parameters vary (topic, audience, depth); structure does not (sequencing, review gates, fan-out/fan-in)

A single successful session is an anecdote. Three sessions with the same shape are a crystallization candidate. The Skills Specialist creates the skill; the human approves at the CfA gate before the skill is registered.

Crystallization produces two artifacts:

1. **The skill graph** — the phase file chain encoding the invariant structure
2. **The skill frontmatter** — a description of the task class the skill applies to, the parameters it accepts, and explicit `applies-when` / `does-not-apply-when` conditions encoding the applicability boundary

The `applies-when` / `does-not-apply-when` pair is critical. It encodes not just what the skill does but when it should and should not be invoked — including near-misses that look like matches but aren't. This boundary sharpens over time as the skill accumulates exception history (see below).

---

## Exception Handling and Graph Extension

A skill running autonomously will eventually encounter a case its phase graph does not cover. When this happens, the agent cannot follow its `Next:` pointer. It escalates via `AskQuestion`.

This is a local CfA invocation — System 2 activated at the point where System 1 ran out of pattern. The escalation signal has a precise structure: *at phase X, condition Y, resolution Z*. The MCP tools ensure this structure is consistent across all skill types.

When the same exception recurs at the same phase across multiple sessions, the learning system treats the resolution pattern as an **extension candidate**. Rather than producing a prose corrective learning, it produces a new branch node — a phase file encoding the resolution — and inserts it into the graph at the exception point:

```
phase-survey.md (before extension):
  → (normal) phase-synthesize.md

phase-survey.md (after extension):
  → (normal) phase-synthesize.md
  → (source inaccessible) phase-survey-source-fallback.md → phase-synthesize.md
```

What was a halt becomes a handled case. The skill's coverage of its domain grows through use.

**Extension is a distinct learning operation from refinement:**
- **Refinement** — improving the content of an existing phase node (better instructions, tighter criteria, updated examples)
- **Extension** — inserting a new branch node to cover a previously unhandled case

Both are structural operations on the skill graph, delegated to the Skills Specialist via MCP tools. Both require human approval before the modified graph is registered. Neither happens autonomously.

**The mismatch case.** Not every escalation is an extension candidate. Some exceptions indicate that the task was not a genuine match for the skill — the invocation was a classification error. When resolution indicates mismatch rather than a new case to handle, the `does-not-apply-when` list in the skill frontmatter is updated. The classification boundary sharpens in the other direction: the skill explicitly excludes the near-miss that caused the wrong invocation.

---

## Collective Learning

Workflow skills are collective procedural memory — not one team's workflow but what the organization has learned about how to do a category of work.

The promotion chain from the learning system (`learning-system.md`) already moves declarative knowledge upward: team → project → global. Workflow skills follow the same chain:

- A skill crystallized from one team's CfA history is initially team-scoped
- If the same pattern holds across multiple teams in the same project, it promotes to project scope
- If it holds across projects, it promotes to global scope

A team that inherits a promoted skill gets the exception branches that other teams earned. Their System 1 knowledge base is richer from the first session, without having had to earn it through their own System 2 episodes.

**Division of cognitive labor.** The hierarchy itself is a cognitive architecture. The uber lead does System 2 — decomposition, strategic reasoning, decision authority mapping. Subteam leads execute more System 1 within their domain. Liaisons are almost pure System 1 — status queries follow known patterns. The proxy does System 1 for the human's known preferences, System 2 for novel decisions. Workflow skills are what makes the lower levels of this hierarchy genuinely fast rather than merely lower-context.

**User feedback as learning signal.** Every point of human contact generates a signal:

| Signal | Source | Learning effect |
|--------|--------|----------------|
| Gate approval | Human approves plan or phase gate | Reinforcement — this path was correct |
| Correction | Human edits plan, redirects phase | Refinement — update phase node content |
| Escalation (handled) | Skill extends via new branch | Extension — graph grows to cover the case |
| Escalation (mismatch) | Wrong skill was invoked | Classification boundary update |
| Intervention / backtrack | CfA INTERVENE event | Structural — graph shape itself was wrong |

The proxy is the personalization layer of the collective. As it internalizes the human's judgment patterns, it can approve skill invocations and gate outcomes autonomously — extending the range of work that runs on System 1 without requiring the human's direct participation.

---

## The Virtuous Cycle

The full learning loop:

1. Novel task → full CfA (System 2)
2. Successful CfA episodes accumulate → convergence detected → skill crystallized
3. Subsequent tasks invoke skill directly (System 1)
4. Skill encounters exception → local escalation → resolution
5. Recurring exception → branch node added (graph extension)
6. Skill promoted up hierarchy → other teams inherit branches
7. Proxy internalizes gate patterns → approves autonomously
8. Human attention focused on genuinely novel work

Over time, the organization's System 1 knowledge base expands. CfA is reserved for what it is designed for: work the collective has never done before.

---

## Classification

How a lead determines that an incoming task matches an existing skill — and is confident enough to skip CfA — is an open question deferred until the skill library is large enough to make it a practical problem. At current scale, the lead can read all available skill descriptions in context and decide. When the library outgrows the context window, a dedicated classification mechanism is needed.

The `applies-when` / `does-not-apply-when` frontmatter is designed with this future in mind: it encodes the information a classifier needs, even before the classifier exists. Writing it well during crystallization is an investment that pays off when classification becomes necessary.

---

## Prerequisites

- [Configuration Team](../configuration-team/proposal.md) — Skills Specialist creates and extends workflow skills via MCP tools
- [Self-Improvement](../self-improvement/proposal.md) — agent-initiated proposals for new branches flow through the CfA protocol
- [CfA Extensions](../cfa-extensions/proposal.md) — INTERVENE and WITHDRAW are the structural signals for backtrack-driven learning
- [Team Configuration](../team-configuration/proposal.md) — per-team `workflow_skill` config entry tells the engine which skill to invoke instead of the generic state machine phases

---

## What This Changes

**For the engine.** `phase-config.json` gains a `workflow_skill` field per team. When present, the engine invokes the named skill instead of driving the generic intent/plan/execute phases. When absent, behavior is unchanged. One field, backward compatible.

**For the learning system.** Crystallization and extension are new operations alongside the existing refinement. The post-session pipeline detects convergence and exception patterns, proposes candidates to the Skills Specialist, and awaits human approval before modifying the skill graph.

**For the research story.** A research team running CfA enough times crystallizes a research-paper workflow skill. Subsequent research sessions run directly — survey, synthesize, argue, validate, finalize — with escalation only for genuinely novel methodological questions. The skill's exception branches accumulate from real sessions across all teams that use it. The workflow becomes more capable through collective use.

---

## Relationship to Other Proposals

- [learning-system.md](../../conceptual-design/learning-system.md) — skill crystallization and refinement are the procedural learning mechanisms this proposal extends
- [strategic-planning.md](../../conceptual-design/strategic-planning.md) — warm-start seeding is the planning-phase precursor to direct skill invocation
- [self-improvement](../self-improvement/proposal.md) — agent-initiated workflow change proposals are graph extension proposals
- [cognitive-architecture.md](../cognitive-architecture.md) — Voyager's skill library (procedural memory as executable code) and CLIN's cross-episode causal learning are the closest prior art
