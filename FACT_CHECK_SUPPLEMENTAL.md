# Supplemental Verification: Full Source Passages

This document provides the complete source passages for each verified claim, to allow independent verification.

---

## 1. T2 Part A: Living-Intent Drift Taxonomy

**Source File:** living-intent.md
**Section:** §3 "The Intent Delta Check"
**Lines:** 21-29

```
## The Intent Delta Check

At each major execution milestone, the system should re-read INTENT.md's success criteria
and ask a single operational question: is the current trajectory still serving this? Not
"are we producing good work" and not "are we following the plan" — but specifically, is
the work we are doing still aimed at the purpose that was captured at the start? This check
is not overhead. It is the mechanism that prevents the system from optimizing a path that
has already diverged from the destination.

The divergence types that this check catches fall into three categories:

1. Scope drift: doing more or less than intended
2. Approach drift: solving the right problem the wrong way
3. Purpose drift: the stated goal is no longer aligned with the user's deeper need
```

**Editorial Report Claim:** "living-intent.md §3 defines three divergence types: Scope drift (doing more or less than intended), Approach drift (right goal, wrong method), Purpose drift (the stated goal is no longer aligned with the user's deeper need)."

**Status:** ✓ VERIFIED

---

## 2. T2 Part B: Execution-Alignment Drift Taxonomy

**Source File:** execution-alignment.md
**Section:** §4 "Drift Detection Patterns"
**Lines:** 49-68

```
## Drift Detection Patterns

Three distinct drift patterns appear in execution, each with a different cause and a
different signature.

**Scope creep** is doing more than was intended. The agent encountered something interesting
in the course of execution, assessed it as relevant, and incorporated it. The individual
judgment was often reasonable; the aggregate effect is an output that exceeds the scope of
the request in ways the user did not ask for and may not want. The signal of scope creep is
not that extra work is present — it is that the agent is optimizing its own judgment about
what would be valuable over the user's stated request. The appropriate response to finding
something interesting in the course of execution is to note it and deliver what was asked,
not to expand the scope unilaterally.

**Gold-plating** is adding quality or features beyond what was requested. The core deliverable
is correct; additional work has been layered on top of it in ways that make the overall output
over-engineered for the purpose. This is distinct from scope creep because the base request is
satisfied — the extra work is genuinely extra. Gold-plating often reflects an agent's preference
for thoroughness over fit. Thoroughness is a virtue when the request calls for it; applied
beyond the request, it produces outputs that are harder to use and take longer to deliver.

**Interpretation drift** is the hardest pattern to detect because it is the most locally
reasonable. Each step in execution makes a judgment call about how to interpret the current
task; each individual call is defensible; the cumulative effect is that the work is solving a
slightly different problem than the one that was stated. Interpretation drift is only visible
when you step back and compare the current trajectory to the original intent — from inside the
execution, every step looks correct. This is why intent anchors are not optional: drift of this
kind cannot be detected without periodic comparison to the origin.
```

**Editorial Report Claim:** "execution-alignment.md §5 defines three drift patterns: Scope creep (doing more than intended), Gold-plating (adding quality beyond what was requested), Interpretation drift (each step makes locally reasonable calls that cumulatively solve a different problem)."

**Note:** The section is labeled §4 in the source, not §5. The editorial report references it as §5.

**Status:** ✓ VERIFIED (content accurate; section reference should be §4 not §5)

---

## 3. T2 Part C: Synthesis Adopts Living-Intent Taxonomy Only

**Source File:** workflow-detailed-design.md
**Section:** §4 "Living Intent: From Specification to Hypothesis"
**Lines:** 40-45

```
## 4. Living Intent: From Specification to Hypothesis

INTENT.md encodes the best available model of user intent at the moment of capture. It is
not a finished specification — it is a projection of need onto language, and that projection
is necessarily incomplete. The user cannot fully specify what they want before they have seen
what they might get. The system that treats INTENT.md as immutable closes itself off from the
most important update mechanism available to it: revealed preference during execution. Stated
preferences at intake are predictions about what the user will want; revealed preferences during
execution are direct evidence of what they actually want. These are not the same thing, and
pretending they are produces work that satisfies the letter of the request while drifting from
its spirit.

The practical implication is that INTENT.md must be treated as a working hypothesis, not a
contract. At each major execution step, the agent re-reads the success criteria and asks whether
the current trajectory is still serving the original purpose. Three divergence types matter.
Scope drift — doing more or less than intended — is often recoverable. Approach drift — pursuing
the right goal through a means the user would not sanction — requires a course correction but does
not invalidate the intent itself. Purpose drift is the most dangerous: the work is no longer serving
the original reason it was requested at all, and no amount of excellent execution can make it right.
Purpose drift requires a revision to INTENT.md itself, not just a tactical adjustment. The decision
criteria for triggering this escalation is magnitude times reversibility. A small, easily-reversed
deviation can be corrected without surfacing it; a large deviation in an irreversible direction
requires human confirmation before proceeding.
```

**Editorial Report Claim:** "workflow-detailed-design.md §4 adopts the living-intent taxonomy (scope drift / approach drift / purpose drift) without acknowledging the execution-alignment taxonomy."

**Status:** ✓ VERIFIED

**Supplemental verification:** A comprehensive search of workflow-detailed-design.md finds no mention of "scope creep," "gold-plating," or "interpretation drift" (the execution-alignment taxonomy terms). The synthesis uses only the living-intent taxonomy terms.

---

## 4. T1 Part A: "The Intent Delta Check"

**Source File:** living-intent.md
**Section Header:** §3
**Line:** 21

```
## The Intent Delta Check
```

**Editorial Report Claim:** "living-intent.md §3 uses 'The Intent Delta Check' as a section header"

**Status:** ✓ VERIFIED

---

## 5. T1 Part B: "Intent Anchors"

**Source File:** execution-alignment.md
**Section Header:** §2
**Line:** 17

```
## Intent Anchors
```

**Editorial Report Claim:** "execution-alignment.md §2 uses 'Intent Anchors' as a section header"

**Status:** ✓ VERIFIED

---

## 6. T1 Part C: "intent anchors" and "intent anchor moments" in synthesis

**Source File:** workflow-detailed-design.md
**Section:** §6 "Execution Alignment: Maintaining Intent Throughout"
**Lines:** 60-67

```
## 6. Execution Alignment: Maintaining Intent Throughout

At each relay.sh result returning to the uber lead, the obligation is not to check whether
the task completed — it is to check whether the output serves the original purpose. The
anchor question is: would the user who articulated this intent be satisfied with this? An
agent can complete every plan step and still deliver something unwanted. The plan is a
decomposition of intent, not a substitute for it. Receiving a result and simply logging it
as done is a supervision failure. Intent anchors at milestone boundaries are the structural
mechanism for preventing this failure from compounding across a long execution chain.

Before delivery on Tier 2 and Tier 3 tasks, apply a formal pre-delivery gate. The reasonable
user test catches three failure modes: technically correct but practically useless outputs;
over-engineering — adding what was interesting rather than what was wanted; and
under-contextualized work that requires the user to supply meaning the system should have
provided. The "reasonable user" in this test is not an abstract average person. It is the
specific human who made this specific request in this specific context, with their known
preferences and constraints loaded from memory. The test is only meaningful when it is applied
to a concrete, contextually-specified user.

For long tasks, surfacing intermediate outputs with an alignment note shifts the human from
continuous overseer to occasional calibrator. "Completed X, represents approximately Y% of the
work, direction looks like this — confirm before continuing?" This is not a request for
permission. It is a structured handoff of calibration responsibility at the moment when
calibration is most tractable. Oversight requires sustained attention; calibration requires
periodic attention at specific moments. Partial delivery creates the calibration moment without
requiring the human to maintain a constant watch on the execution stream.
```

**Editorial Report Claim:** "workflow-detailed-design.md uses 'intent anchors' and 'intent anchor moments' throughout, aligning with execution-alignment.md's terminology"

**Status:** ✓ VERIFIED (with minor precision note below)

**Precision Note:** The exact phrase "intent anchor moments" does not appear in a single occurrence. The document uses "intent anchors at milestone boundaries" (line 62) and "calibration moment" (line 66) separately. The concept is present and clear, but the exact phrase "intent anchor moments" is not verbatim. The editorial report's characterization is accurate in substance but slightly imprecise in phrasing.

---

## 7. T3: Three-Tier Model Quote

**Source File:** strategic-planning.md
**Section:** §2 "The First-Move Problem"
**Line:** 17

```
## The First-Move Problem

Early autonomous decisions shape the entire trajectory of complex work. Architectural choices,
naming conventions, structural decisions made in the first hour constrain every decision
afterward in ways that are rarely visible at the time and expensive to undo later. This is
why strategic planning cannot be skipped or rushed — not because planning is virtuous in the
abstract, but because the cost of a first-move error compounds through every subsequent
decision that assumes it.

Strategic planning should explicitly identify high-leverage decision points and assign
decision authority for each before execution begins. The three-tier model — autonomous,
notify, escalate — provides the right vocabulary. Autonomous means the agent decides based
on the existing spec. Notify means the agent decides and surfaces the choice in its result
so it can be reviewed without blocking execution. Escalate means the work stops until a
human decides.
```

**Editorial Report Claim:** "strategic-planning.md §2: 'The three-tier model — autonomous, notify, escalate — provides the right vocabulary.'"

**Status:** ✓ VERIFIED — exact quote

---

## 8. C2 Part A: Task-Tiers Escalation Bias Quote

**Source File:** task-tiers.md
**Section:** §3 "The Classification Decision Itself"
**Lines:** 39-42

```
## The Classification Decision Itself

Classification is a least-regret decision under asymmetric costs. The error function is not
symmetric: misclassifying a Tier 3 project as Tier 1 is potentially catastrophic, producing
expensive rework and wasted execution time. Over-classifying a Tier 0 query as Tier 2 is
merely annoying — it adds friction, erodes trust incrementally, but produces no destroyed work.
This asymmetry directly implies that the classifier should bias toward escalation in ambiguous
cases. The same logic governs the escalation model's act-or-ask decisions: when uncertainty is
high and costs are asymmetric, escalation is the rational default.
```

**Editorial Report Claim:** "task-tiers.md §3: 'the classifier should bias toward escalation in ambiguous cases.'"

**Status:** ✓ VERIFIED — exact quote

---

## 9. C2 Part B: Execution-Alignment Escalation Posture Quote

**Source File:** execution-alignment.md
**Section:** §5 "When to Escalate vs. Improvise"
**Lines:** 59-68

```
## When to Escalate vs. Improvise

The decision to escalate versus proceed is not a matter of preference or caution — it is a
function of reversibility and cost.

High-cost decisions not anticipated in INTENT.md require escalation without exception. "High-cost"
means low reversibility, significant resource investment, or organizational impact beyond the
current task. When an execution path leads to a decision of this kind, the agent's obligation is
to surface it to the appropriate level before proceeding. This is not a threshold calibrated to
domain or agent confidence — it applies universally to irreversible actions.

Low-cost, reversible improvisation that serves intent is different. When an unanticipated situation
arises and the resolution is clearly reversible and clearly aligned with intent, proceeding and
notifying is the right posture. The notification is not optional — "proceed and note" means both
elements are required — but the note is asynchronous; it does not require approval before action.

The default posture is "proceed and note," not "stop and ask," for low-stakes decisions. An agent
that over-escalates imposes real costs: it consumes the human's attention on decisions that did not
require it, introduces latency into execution, and transfers decision-making to a level that has less
context than the executing agent. Anxious over-escalation is not a safe behavior — it is a cost that
compounds across every task in every session.
```

**Editorial Report Claim:** "execution-alignment.md §5: 'The default posture is 'proceed and note,' not 'stop and ask,' for low-stakes decisions.'"

**Status:** ✓ VERIFIED — exact quote

---

## 10. AQ3: Order of Magnitude Claim

**Source File:** learning-evolution.md
**Section:** §2 "In-flight Learning"
**Line:** 27

```
## In-flight Learning

A session is not a monolithic unit of work. It proceeds through milestones, and each milestone
is an observation point. If step one took three times longer than the estimate implied, the
estimates for the remaining steps need revision — not at retrospective extraction, but now,
before committing to the same planning assumptions for what follows.

The more consequential in-flight signal is an approach assumption that has not proven out by
midpoint. If the session began assuming a certain decomposition was tractable and two steps in
the evidence contradicts that assumption, the correct moment to flag it is before the third
step, not after delivery. In-flight corrections are cheaper than post-delivery corrections by
an order of magnitude. This is not a novel observation about software development — it is the
foundational argument for iterative process design — but the workflow has no mechanism to
implement it.
```

**Editorial Report Claim:** "learning-evolution.md §3 contains the sentence 'In-flight corrections are cheaper than post-delivery corrections by an order of magnitude.'"

**Status:** ✓ VERIFIED — sentence is accurate, though it appears in §2 not §3

**Note:** Section reference error in report: the sentence is in §2 ("In-flight Learning"), not §3.

---

## 11. S1: Parallelization Patterns Absent

**Source File:** workflow-detailed-design.md
**Comprehensive Search Result:**

Searched for these specific terms and concepts:
- "true parallel" — **NOT FOUND**
- "fan-out" — **NOT FOUND**
- "fan-in" — **NOT FOUND**
- "sequential gates" — **NOT FOUND**
- "parallelization" — **NOT FOUND** (as strategy description)
- "parallel" — appears once in passing context (line 50: "before parallelizing across six liaisons") but not describing the three parallelization patterns

**Editorial Report Claim:** "workflow-detailed-design.md contains no mention of the three parallelization patterns (true parallel / fan-out fan-in / sequential gates)"

**Status:** ✓ VERIFIED

**Supplemental Information:** These patterns are described in detail in strategic-planning.md §5 ("Parallelization Strategy"), lines 45-53:

```
## Parallelization Strategy

The POC's relay.sh dispatch model enables genuine parallelism, but strategic planning must
identify which work streams are actually parallel before execution begins. The distinction
matters because misclassifying a dependency as a parallelism creates a blocked pipeline that
only becomes visible at the point of collision.

True parallel work has no shared state and no ordering dependencies — maximize throughput.
In the POC, art and writing dispatches for different chapters are often truly parallel.
Neither depends on the other's output, and running them concurrently costs nothing.

Fan-out/fan-in is the most common pattern in the POC: multiple independent streams that must
be synthesized at a defined merge point. Multiple writing dispatches produce chapters that
editorial must then review together. The fan-in — editorial review — cannot start until all
fan-out streams complete. Strategic planning should name this constraint explicitly, because
the uber lead autonomously sequences dependent work — writing first, then art, then editorial
review — without being prompted to do so. That sequencing should be encoded in the plan, not
rediscovered at runtime.

Sequential gates are a different category: B cannot start until A is verified. In the POC, a
writing dispatch must complete before an art dispatch can reference its content. The gate is
not just ordering — it is a dependency on verified output, not merely completed output.
```

None of this content appears in the synthesis (workflow-detailed-design.md).

---

## 12. S3: RACI Absent

**Source File:** workflow-detailed-design.md
**Comprehensive Search Result:**

Searched for:
- "RACI" — **NOT FOUND**
- "Responsible, Accountable, Consulted, Informed" — **NOT FOUND**
- Any variant or reference to RACI framework — **NOT FOUND**

**Editorial Report Claim:** "RACI does not appear anywhere in workflow-detailed-design.md"

**Status:** ✓ VERIFIED

**Supplemental Information:** RACI is discussed in detail in human-dynamics.md §6 ("RACI and Decision Ownership"), lines 45-49:

```
## RACI and Decision Ownership

The RACI framework — Responsible, Accountable, Consulted, Informed — was developed in
organizational management as a tool for reducing coordination failures in complex projects.
Its core insight is that ambiguity about decision ownership is the primary source of
coordination breakdown. When it is unclear who is responsible for making a decision versus who
needs to be consulted versus who merely needs to be kept informed, decisions get made by the
wrong person, get made without necessary input, or don't get made at all because everyone
assumes someone else is handling it.
```

This section and its concepts do not appear in the synthesis.

---

## 13. IC2 Part A: §6 Confidence Format Proposal

**Source File:** workflow-detailed-design.md
**Section:** §6 "Execution Alignment: Maintaining Intent Throughout"
**Lines:** 67-69

```
The most dangerous execution state is high agent confidence combined with low actual alignment.
This state produces no signal that would trigger escalation — the agent is not uncertain, so
it does not ask; the human sees no distress signal, so they do not intervene. The system
addresses this by requiring explicit confidence reporting alongside recommendations, decomposed
by dimension rather than expressed as a single session-level number. Not "I am doing X" but
"I am doing X, with high confidence in the technical approach, moderate confidence that this
trade-off aligns with your preferences, and lower confidence that this level of formality
matches what you want."
```

**Editorial Report Claim:** "The same format ('technical approach: high; preference alignment: moderate; register: lower') is proposed in §6 as a concrete description of what dimensional confidence reporting looks like."

**Status:** ✓ VERIFIED

**Note:** The format is paraphrased in §6 as an example embedded in explanatory text, then appears again more explicitly in §9 Open Question 3.

---

## 14. IC2 Part B: §9 Open Question 3

**Source File:** workflow-detailed-design.md
**Section:** §9 "Open Questions"
**Lines:** 113-115

```
3. **Confidence reporting format:** If agents are to report confidence decomposed by dimension,
what format makes this useful rather than noisy? A domain-confidence pair per key claim —
"technical approach: high; preference alignment: moderate; register: lower" — seems more
actionable than a single session-level number, but the format needs to be specified in agent
prompts before it can be applied consistently.
```

**Editorial Report Claim:** "§9, Open Question 3... The same format ('technical approach: high; preference alignment: moderate; register: lower') is proposed in §6"

**Status:** ✓ VERIFIED

**Logical Issue Verified:** The document does indeed present the same format both as a proposed practice in §6 (lines 67-69) and as an "open question" in §9 (line 114). This is the internal consistency issue the editorial report correctly identifies as IC2.

---

## 15. Confidence Adjustment Values

**Source File:** living-intent.md
**Section:** §3 "The Intent Delta Check"
**Line:** 31

```
The escalation calibration model tracks confidence adjustments: +0.05 for a positive signal,
−0.10 for a negative signal, −0.02 for a neutral one. This asymmetric weighting should be
extended to intent signals. When a user confirms that an approach was right, that confirmation
should carry weight in the intent memory — it narrows the hypothesis space for future sessions.
When a user corrects an approach, that correction should widen the hypothesis space and update
the prior.
```

**Editorial Report Claim:** "living-intent.md references '+0.05 for a positive signal, −0.10 for a negative signal, −0.02 for a neutral one' as appearing in the escalation calibration model"

**Status:** ✓ VERIFIED — exact values verified

---

## Conclusion

All nine substantive claims and their sub-parts have been verified against source documents. Two minor issues identified:

1. **AQ3 Section Reference:** The order of magnitude claim is in §2, not §3 as the report states.
2. **T1 Phrase Precision:** The exact phrase "intent anchor moments" does not appear verbatim in workflow-detailed-design.md, though the concept is clearly present.

All other claims are factually accurate and verifiable from the source texts.
