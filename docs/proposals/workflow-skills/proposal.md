[Milestone 4: Proxy Evolution](../milestone-4.md) >

# Workflow Skills — Skill-Graph Execution Framework

> *Scope narrowed 2026-04-18: skill archival and crystallization are implemented. This proposal covers the remaining skill-graph execution framework tracked in issues #336–#340.*

Today's procedural learning pipeline (`teaparty/learning/procedural/learning.py`) archives approved plans as skill candidates, clusters them, and crystallizes them into flat skill templates. The reflection pass refines the templates from gate corrections and friction signals. What is **missing** is the execution framework that would let a crystallized skill run as an autonomous graph — bypassing full CfA — and the structural machinery it depends on:

1. **Cross-session convergence detection** that produces a *graph-shaped* skill (phase-file chain) rather than a single flat template.
2. **An engine dispatch path** that invokes a skill graph in place of CfA phases, with defined pre/post engine states.
3. **A structural similarity measure** over session traces that makes "same decomposition" a computable predicate.
4. **An escalation receiver** that handles `AskQuestion` calls from within skill execution when the CfA state machine is not actively driving.
5. **A classification mechanism** that decides when a task matches an existing skill well enough to skip CfA — with graceful degradation to full CfA on failure.

Until these five pieces exist, a crystallized skill template is a document the planner can warm-start from — not an executable graph the engine can dispatch to.

---

## The Spectrum, Restated

CfA is System 2: deliberate, expensive, negotiated at every gate. A workflow skill, once this framework exists, is crystallized System 2 knowledge — a trusted pattern executed directly.

```
Full CfA ←——————————————————————————→ Direct skill invocation
(novel, expensive, fully negotiated)   (known pattern, cheap, autonomous)
```

Work moves rightward as experience accumulates. It moves left when a skill encounters something it cannot handle — which resolves through local escalation and extends the graph, so next time it stays right.

The existing crystallization pipeline supports the left side (warm-start seeding). This proposal specifies what is needed to reach the right side.

---

## Skill Graphs — The Execution Artifact

A workflow skill is a continuation chain: a `SKILL.md` entry point and a set of phase files, each ending with a `**Next:**` pointer. The agent navigates by following pointers. Sequencing is deterministic; behavior within each phase is agent-guided.

The fix-issue skill in `.teaparty/management/skills/fix-issue/` is the existence proof of the phase-file pattern. A workflow skill uses the same structure at the CfA level — phases instead of issue-resolution steps, escalation via MCP tools instead of `gh` commands.

See [references/skill-graph.md](references/skill-graph.md) for the phase-file format, branching via exception phases, re-entry via `--from-phase`, and the `SKILL.md` frontmatter schema. See [examples/research-workflow.md](examples/research-workflow.md) for an end-to-end walkthrough of crystallization, invocation, and graph extension.

> **Note.** The current crystallization output is a single flat `.md` template suitable for warm-start. Producing a graph-shaped skill (multi-file phase chain with branches) is additional work that depends on the convergence and similarity decisions below.

---

## (1) Cross-Session Convergence Detection — #336

**Problem.** The existing pipeline (`learnings.py`, `learning/procedural/learning.py`) processes a single session for declarative facts and clusters candidate plans for generalization. Detecting *structural* convergence across session histories is a different operation and has no owner.

**Required design decisions:**

- **Named component.** Assign cross-session convergence detection to a specific module (new file under `teaparty/learning/procedural/`, or a clearly named function-level entry point). Specify its inputs, outputs, and invocation trigger.
- **Input representation.** Sessions must be represented in a form suitable for structural comparison. Candidates: the CfA state-machine trace (ordered events), a reduced phase-sequence vector, or a DAG derived from gate outcomes.
- **Algorithm or judgment procedure.** Either an algorithm (with similarity measure — see #338) or a human-in-the-loop review procedure. If the answer is human judgment, state it explicitly; do not imply automation by omission.
- **Output format.** A crystallization candidate needs a defined shape: proposed phase sequence, contributing session ids, observed gate outcomes, observed exception resolutions, proposed `applies-when`/`does-not-apply-when` boundary.

**Non-goal.** This component does not produce the final skill graph — it produces a *candidate* that the Skills Specialist and human operator promote. The Specialist's `CreateSkill` tool performs structural validation.

---

## (2) Structural Similarity Measure — #338

**Problem.** "Same phase sequence" and "same gate outcomes at the same decision points" are not operationalized. Phase names vary across sessions for identical underlying work. Sessions sharing phase names may differ in fan-out, parallelism, or gating logic. Two independent implementations would produce different crystallization candidates from the same session history.

**Required design decisions:**

- **Unit of comparison.** One of: linear phase sequence, full DAG structure, gate condition sequence, or some composition. State which and why.
- **Similarity measure.** One of: exact name match, semantic embedding similarity, graph isomorphism, or edit distance over a canonical form. Prior art: CLIN uses causal abstractions; Voyager uses embedding similarity on executable functions. Adopt, adapt, or justify deviation.
- **Threshold.** The point at which similarity → convergence. Must be stated as a number or a judgment predicate.
- **Automation boundary.** Whether threshold evaluation is automated, partially automated (shortlist → human confirmation), or fully human-reviewed.

**Acceptance criterion.** Given a fixed corpus of session traces, two independent runs of the detector must produce the same candidate set. This rules out undefined tie-breaking.

---

## (3) Engine Dispatch Path — #337

**Problem.** The CfA engine has no hook for skill invocation. `TeamSpec` in `phase_config.py` has no `workflow_skill` field. Even if the field were added, the engine would not know what to do with it. "One field, backward compatible" significantly understates the change — this is a new execution mode.

**Required design decisions:**

- **Field home and schema.** Where `workflow_skill` lives (team spec, phase-config.json, agent definition), its value shape (skill name, skill path, versioned reference), and how it is resolved at dispatch time.
- **CfA state during skill execution.** The engine must occupy *some* defined state while a skill runs. Candidates: a new `SKILL_EXECUTING` state, a parked `EXECUTE` state with a skill-context annotation, or a detached mode that suspends the state machine entirely.
- **Transition sequence.** What state the engine enters before skill invocation, what it enters on normal completion, and what it enters on skill failure mid-chain.
- **Gate interaction.** How approval gates embedded inside phase files route through (or bypass) the engine's approval-gate machinery. Whether `AskQuestion` calls from skill phases are routed identically to CfA-phase `AskQuestion` calls or through a distinct receiver (see #340).
- **Failure semantics.** A skill that fails mid-chain must leave the engine in a recoverable state. Define: what "failure" means (explicit `WithdrawSession`, unhandled exception, timeout), what cleanup occurs, and whether the session returns to full CfA or terminates.

**Non-goal.** Replacing CfA. Full CfA remains the fallback path for every failure mode here.

---

## (4) Escalation Receiver During Skill Execution — #340

**Problem.** The engine's escalation routing uses the current CfA state to determine the approval gate actor and valid transitions. When no state machine is active, `AskQuestion` calls from within a skill phase have no defined receiver. This is a potential silent-hang or silent-corruption path on every exception during skill execution — the central mechanism the proposal relies on for graceful degradation.

**Required design decisions:**

- **Receiver component.** Which component handles `AskQuestion` when the engine is in skill-execution mode. Either:
  - A **minimal CfA context** remains active during skill execution and acts as the gate handler, or
  - A **dedicated skill-escalation receiver** in the engine routes the call to the appropriate actor (lead, proxy) without a full CfA state machine.
- **Gate routing without an active state.** How the actor for a gate is determined when the call originates from a skill phase. Candidates: skill frontmatter names the default gate actor; the invoking team's lead is always the default; the phase file itself declares the actor.
- **Pre- and post-escalation state.** The engine state before the call, during await, and after resolution. The resolution must return control to the *exact* phase position (re-entry via `--from-phase` is the existing mechanism; state that this applies or specify an alternative).
- **Silent-failure prevention.** An `AskQuestion` that cannot be routed must raise an error, not time out silently. Define the error path and how it surfaces to the human.

**Relationship to graph extension.** When the same exception recurs at the same phase across sessions and is resolved consistently, the resolution pattern is an extension candidate — a new branch node inserted at that point:

```
phase-survey.md
  → (normal)               phase-synthesize.md
  → (source inaccessible)  phase-survey-fallback.md → phase-synthesize.md
```

The escalation receiver produces the signal (*at phase X, condition Y, resolution Z*) that feeds back into the convergence detector (#336) as extension evidence. The receiver is therefore not only a runtime mechanism but a source of learning signal.

---

## (5) Classification Mechanism — #339

**Problem.** The invocation decision — whether to skip CfA and run a skill directly — is the central bet of the proposal. At current scale the lead "reads all skill descriptions in context and decides." This is not a mechanism; it is the absence of one. As the library grows, older skill descriptions are silently truncated, misclassification rises monotonically, and nothing signals the degradation.

**Required design decisions:**

- **Present mechanism.** Specify how classification works *today*, at small-library scale — not just its eventual replacement. This includes the exact prompt surface (are `applies-when`/`does-not-apply-when` passed verbatim, summarized, or embedded?) and the actor (team lead, planning agent, router).
- **Mandatory graceful degradation.** Classification failure *must* fall back to full CfA, never to best-guess skill invocation. This is non-negotiable and must be encoded as a gate on the dispatch path (#337), not a convention.
- **`applies-when` / `does-not-apply-when` at crystallization time.** These are **required** fields, produced at crystallization, not deferred. The `does-not-apply-when` list is as important as `applies-when` — it encodes the near-miss cases the graph was extended to exclude. Without it, near-miss misclassification accumulates silently.
- **Monitoring signal.** A defined trigger for migrating from informal (read-all-in-context) to formal (retrieval / classifier) mode. Candidate signals: total skill count, total description token budget exceeding context fraction, observed misclassification rate, or a scheduled review cadence.
- **Failure-mode specification.** State what classification failure looks like (no match above threshold, multiple matches with no clear winner, ambiguous `does-not-apply-when` hit). Each failure mode routes to full CfA.

**Acceptance criterion.** A test that adds enough dummy skills to push older descriptions out of the context window must not produce silent misclassification — either fall back to CfA or raise a defined error.

---

## Learning Signals — Framework Integration

Once the five pieces above exist, the feedback loop that drives skill evolution runs end-to-end:

| Signal | Source | Effect |
|--------|--------|--------|
| Gate approval | Human approves plan or phase gate | Reinforcement — path was correct |
| Correction | Human edits plan, redirects phase | Refinement — update phase node |
| Escalation (handled, recurring) | Same exception at same phase (#340 signal) | Extension — graph grows a branch (via #336 detector) |
| Escalation (mismatch) | Wrong skill invoked (#339 failure) | Boundary tightens — `does-not-apply-when` |
| Intervention / backtrack | INTERVENE event | Structural — graph shape was wrong |

The existing `reflect_on_skill` / `update_skill_stats` machinery in `learning/procedural/learning.py` handles the *refinement* column for flat templates today. The *extension* column depends on #336 + #340 being in place; the *boundary-tightening* column depends on #339.

---

## Prerequisites

- [Configuration Team](../../reference/team-configuration.md) — Skills Specialist creates and extends workflow skills via MCP tools (`CreateSkill` performs structural validation of the graph artifact).
- [CfA Extensions](../../systems/cfa-orchestration/state-machine.md) — INTERVENE and WITHDRAW are the structural signals for backtrack-driven learning.
- [Self-Improvement](../self-improvement/proposal.md) — agent-initiated workflow change proposals flow through the CfA gate.
- [Team Configuration](../../reference/team-configuration.md) — per-team `workflow_skill` config entry (schema to be defined under #337; prerequisite does not yet define the field).

---

## Relationship to Other Proposals

- [learning-system.md](../../systems/learning/index.md) — skill crystallization and refinement are the procedural learning mechanisms this proposal extends with graph execution and graph-shaped crystallization output.
- [strategic-planning.md](../../systems/cfa-orchestration/planning.md) — warm-start skill seeding (already implemented) is the planning-phase precursor to direct skill invocation (this proposal).
- [self-improvement](../self-improvement/proposal.md) — agent-initiated workflow change proposals are graph extension proposals routed through the CfA gate.
- [cognitive-architecture.md](../cognitive-architecture.md) — Voyager's skill library and CLIN's cross-episode causal learning are the closest prior art; the structural similarity decision (#338) is where adoption or deviation must be declared.

---

## Open Issues Tracked

- [#336](https://github.com/dlewissandy/teaparty/issues/336) — Cross-session convergence detection (named component, inputs, algorithm, output)
- [#337](https://github.com/dlewissandy/teaparty/issues/337) — Engine dispatch path for skill invocation (field home, state model, transitions, failure semantics)
- [#338](https://github.com/dlewissandy/teaparty/issues/338) — Structural similarity measure (unit, measure, threshold, automation boundary)
- [#339](https://github.com/dlewissandy/teaparty/issues/339) — Classification mechanism (present mechanism, graceful degradation, required frontmatter, monitoring signal)
- [#340](https://github.com/dlewissandy/teaparty/issues/340) — Escalation receiver during skill execution (receiver component, gate routing, silent-failure prevention)
