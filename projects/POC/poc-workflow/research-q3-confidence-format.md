# Research: Confidence Reporting Format for Decomposed Dimensional Confidence

**Status:** Design Synthesis — Resolves Open Question 3 from workflow-detailed-design.md Section 9
**Date:** 2026-03-01
**Author:** Research Agent
**Input Documents:** workflow-detailed-design.md, learning-evolution.md, human-dynamics.md

---

## 1. Problem Statement

### 1.1 The Open Question

From workflow-detailed-design.md, Section 9, Open Question 3:

> "If agents are to report confidence decomposed by dimension, what format makes this useful rather than noisy? A domain-confidence pair per key claim — 'technical approach: high; preference alignment: moderate; register: lower' — seems more actionable than a single session-level number, but the format needs to be specified in agent prompts before it can be applied consistently."

### 1.2 Why Decomposed Confidence Is Superior to a Single Number

A single session-level confidence number fails on three grounds simultaneously.

First, it conflates epistemic dimensions that are independently variable. An agent can have high confidence in the technical correctness of a recommended approach (it has strong prior knowledge of the domain), moderate confidence that the recommendation aligns with the user's established risk preferences (prior sessions are ambiguous on this), and low confidence that the current level of detail matches the user's current mode (the session context signals "quick review" but the intent capture assumed "deep design"). These three confidence states are orthogonal. Averaging them into a single number produces a value that is true about none of the three dimensions.

Second, a single number gives the human no basis for targeted correction. "I'm 70% confident" does not tell the human where to focus their attention. "Moderate confidence on preference alignment — your prior sessions are split on this trade-off" immediately identifies the specific dimension requiring human input and provides the reasoning that makes intervention tractable.

Third, a single session-level number suppresses intra-session variation. Within a session, confidence should vary across claims. A uniform session-level number cannot represent this variation and therefore cannot serve as a signal that any particular claim deserves closer scrutiny.

### 1.3 What "Useful vs. Noisy" Means Operationally

A confidence annotation is useful if and only if the receiver can take a different action based on the annotation than they would take without it. Annotations that appear on every claim at "high" for every dimension fail this test: the receiver's behavior does not change based on their presence because the annotations carry no differential information.

Operationally, the useful/noisy distinction maps to three concrete tests:

**Test 1 — Behavioral discriminability:** Does the presence of the annotation cause the human to slow down, reconsider, or redirect? If the annotation is always present and always "high," humans learn to filter it out (the cry-wolf effect), and even genuinely low-confidence annotations stop triggering the appropriate response.

**Test 2 — Retrospective extractability:** Can the annotation be parsed and stored as a structured calibration record? An annotation that says "I'm moderately confident" without specifying the dimension and the reason cannot be used for calibration measurement. A structured annotation that specifies dimension, level, and reason can.

**Test 3 — Calibration measurability:** Can the annotation be validated against outcomes? If agents report MODERATE CONFIDENCE on preference alignment for twenty claims across ten sessions, and the human accepted eighteen of those twenty decisions without correction, the annotations are under-confident. This measurement requires that annotations be consistent in format and linked to claim outcomes.

### 1.4 The Current State

The current spec (workflow-detailed-design.md) calls for "explicit confidence reporting alongside recommendations, decomposed by dimension rather than expressed as a single session-level number" (Section 6). Section 8 lists "agent prompts: explicit confidence reporting alongside recommendations" as a required change. But no format has been specified. As a result:

- Agents generate confidence annotations in inconsistent formats that cannot be aggregated or compared across sessions
- Dimensions vary from session to session, preventing longitudinal calibration measurement
- Absence of a "reason" clause makes annotations unfalsifiable and therefore uninformative
- No baseline exists against which to measure whether agent self-reported confidence is actually calibrated

This document resolves the open question by specifying a concrete format recommendation with exact prompt text.

---

## 2. Research Findings by Domain

### 2.1 Statistics and Calibration Research

**Core research:** Lichtenstein & Fischhoff (1977) established that human probability assessments are systematically miscalibrated, with a strong bias toward overconfidence: people who say they are "90% confident" are correct substantially less than 90% of the time. The miscalibration is not random error — it is a systematic bias. The key methodological insight from this work is that calibration can only be measured if assessments are made in advance of outcomes, are specific enough to be verified, and are collected in sufficient quantity to produce statistically stable estimates.

**Heuristics and biases:** Kahneman & Tversky's heuristics-and-biases research (1970s–1980s, synthesized in Kahneman's "Thinking, Fast and Slow," 2011) identifies the availability heuristic as a primary driver of overconfidence: people rate their confidence based on how easily they can construct supporting arguments, not on base-rate validity. For agents, the parallel mechanism is pattern-matching on superficially similar prior contexts — the Dunning-Kruger trap identified in human-dynamics.md. An agent that has successfully handled several similar requests will pattern-match to those successes and report high confidence, even if the current request differs in a dimension the agent has not identified as relevant.

**LLM metacognitive calibration:** Steyvers & Peters (2025) on LLM metacognitive calibration finds that language models exhibit systematic overconfidence in their own outputs and that this overconfidence is worse in domains where the model has high-fluency but uncertain factual grounding — that is, where the model can produce confident-sounding text easily, regardless of accuracy. The implication for this system is severe: agents trained on large corpora will tend to sound confident even when they should not be. Structural mechanisms — required format fields, required reason clauses — are the only reliable counterweight to this fluency-driven false confidence.

**Key point: a confidence format that cannot be validated against outcomes is noise that sounds like calibration.** The format must support outcome linkage.

**Data requirements per session for calibration measurement:**

Each session must capture the following per confidence annotation:

| Field | Description | Example |
|-------|-------------|---------|
| `claim_id` | Unique identifier for the specific claim or recommendation | `claim_2025-11-15-session042-03` |
| `dimension` | Which of the 5 canonical dimensions (see Section 3) | `preference_alignment` |
| `confidence_level` | MODERATE or LOW (HIGH is the unmarked default) | `MODERATE` |
| `reason` | One sentence explaining what produces the uncertainty | "Prior sessions split on this trade-off" |
| `outcome` | Was the claim accepted, rejected, or corrected by the human? | `accepted` / `rejected` / `corrected` |
| `session_id` | Session reference for longitudinal tracking | `session-20260301-131335` |
| `task_tier` | Tier classification at session open | `Tier 2` |

**Minimum sample size for statistically meaningful calibration estimates:**

At minimum 30 outcome-linked claims per confidence level per dimension before point estimates are statistically meaningful. Rationale: with n=30 and a hypothesized true accuracy rate of 0.70, a 95% confidence interval spans approximately ±0.16 — wide, but sufficient to distinguish "clearly calibrated" from "clearly over-confident." With n=100, the interval narrows to ±0.09, which is actionable. The implication is that calibration data must be accumulated across sessions, not within a single session. A new domain will not have enough data for calibration measurement until approximately 30 annotated claims have been collected and outcomes recorded. Until then, the system should flag calibration estimates as "insufficient data."

### 2.2 Communication Theory — Signal-to-Noise

**Core research:** Shannon & Weaver's channel capacity theorem (1948) provides the formal foundation. Information content (measured in bits) is a function of how much a message reduces uncertainty. A message that a rational receiver could have predicted with certainty carries zero information — it reduces no uncertainty. A message that the receiver could not have predicted carries high information.

Applied to confidence annotations: if an annotation appears on every claim and every annotation reads "high," the receiver can predict each annotation before reading it. The predictable annotation reduces zero uncertainty. It therefore carries zero information, in the strict technical sense. The overhead of parsing and ignoring the annotation is pure noise.

**The key insight:** A confidence annotation that appears only when confidence departs from a calibrated default has much higher information value because its PRESENCE is itself a signal. When the receiver knows the default is "high confidence," seeing an annotation at all communicates "something is different here" before the content of the annotation is read. This is information in the first word.

This has direct implications for format design:

- Always-present annotations (Alternative A, Section 4) force the receiver to parse every annotation to determine whether it is informative — high cognitive overhead, habituated filtering
- Departure-only annotations (Alternative B) make presence itself informative — the overhead is zero when confidence is high, which is the majority of claims
- Two-tier annotations (Alternative C) capture both: a session-level posture that provides a baseline, and departure flags that are informative both in presence and in content

**The vocabulary constraint matters for the same reason.** A five-level scale (very high / high / moderate / low / very low) where all assessments cluster in the top two levels carries less information than a three-level scale (high / moderate / low) where agents are required to use all three. Restricting the vocabulary forces genuine discrimination. When agents cannot say "quite high," they must decide between "high" and "moderate," which is a harder and more informative choice.

### 2.3 Metacognition and Self-Monitoring

**Core research:** Nelson & Narens (1990) proposed the influential metacognitive monitoring and control model, which distinguishes two processes: monitoring (assessing current knowledge state — "what do I know?") and control (using the assessment to regulate behavior — "should I continue or stop?"). The model establishes that monitoring and control are separate processes that can dissociate: a person can have accurate monitoring (genuine self-knowledge about what they know) but fail to use it to regulate behavior, or can take regulatory actions based on inaccurate monitoring.

For this system, the design question is whether the proposed confidence dimensions correspond to genuinely separable monitoring processes — whether an agent can independently assess each dimension without conflating it with the others.

**Analysis of the proposed dimensions for genuine separability:**

- **Technical correctness and domain coverage** are closely related but not identical. Technical correctness asks "will this method work?" Domain coverage asks "do I know enough to be sure I haven't missed something?" An agent can have high technical correctness confidence (the approach is sound given the problem as understood) and low domain coverage confidence (the problem statement may not capture all relevant factors the agent is unaware of). These are separable.

- **Technical correctness and preference alignment** are independently variable. An agent can be certain a technical approach is correct while remaining uncertain whether the user would sanction it given their risk tolerance. These are separable.

- **Preference alignment and register/style** both concern user preferences but at different levels. Preference alignment concerns substantive decision preferences (risk tolerance, trade-off priorities). Register concerns surface presentation preferences (tone, formality, length). An agent can have well-calibrated preference alignment (has learned the user's decision patterns) while having poor register calibration (the user's style preferences shift by context in ways the agent hasn't mapped). These are separable.

- **Scope completeness and domain coverage** are related but not identical. Scope completeness asks "have I identified all the requirements for this task?" Domain coverage asks "do I know enough about this subject area to work the problem?" An agent can have high scope completeness confidence (all requirements are explicit) and low domain coverage confidence (the subject is outside established training), or vice versa. These are separable.

**The key point from Nelson & Narens:** Dimensions must map to genuinely separable aspects of epistemic state. Dimensions that agents cannot actually assess independently will collapse into a single global confidence assessment in practice — agents will pattern-match the dimension labels to their overall feeling of confidence and report correlated values across all dimensions, even when the dimensions should be independent. The test of a well-designed dimension set is that it produces uncorrelated assessments in practice: technical correctness and preference alignment should not always move together.

### 2.4 Human Factors and Situation Awareness

**Core research:** Endsley (1995) proposed the three-level Situation Awareness (SA) model, widely applied in aviation, military, and complex system design:

- **SA Level 1 (Perception):** Detecting relevant elements in the environment — raw data
- **SA Level 2 (Comprehension):** Understanding what the data means for current goals — situational assessment
- **SA Level 3 (Projection):** Predicting future states — anticipation

Decision support systems fail when they overwhelm Level 2 with Level 1 data — presenting raw information faster than comprehension can integrate it. The receiver drowns in data that never becomes understanding.

**Application to confidence reporting:**

A confidence annotation block with all five dimensions present for every claim is a Level 1 data dump. The human receives raw confidence scores and must perform the integration themselves: "OK, technical is high, preference is moderate, register is high, scope is high, domain is moderate — what does this mean? Should I worry about the moderate preferences?"

A session-level confidence posture that synthesizes the most relevant dimensions for this session is Level 2 output — it has already integrated the data into a situational assessment. "Entering this session with established technical confidence in this domain and moderate confidence on preference alignment — we haven't worked through this type of trade-off before" tells the human what the confidence situation means, not just what the confidence numbers are.

Claim-level inline flags that depart significantly from the opening posture are Level 3 outputs — they signal "something has changed from the baseline; this specific claim requires your attention."

**The SA model predicts** that confidence reporting designed at Level 2 — session posture as situational assessment — will be processed and acted upon more reliably than equivalent Level 1 data. This is the primary theoretical argument for Alternative C over Alternative A.

**SA also predicts the failure mode:** if the opening posture becomes boilerplate, it degrades from Level 2 back to Level 1 (raw text to parse). The detection mechanism for this failure is covered in Section 9.

### 2.5 Behavioral Economics and Choice Architecture

**Core research:** Thaler & Sunstein (2008) "Nudge: Improving Decisions About Health, Wealth, and Happiness" establishes that the architecture of a choice — how options are structured, presented, and defaulted — systematically influences the choices made, even among fully rational actors. The key design principle is that defaults matter disproportionately: people tend to accept defaults, and defaults therefore express policy about what behavior the system wants to encourage.

**Application to agent confidence reporting:**

If the confidence format provides blank fields for agents to fill, agents fill them with least-resistance answers. "Technical correctness: [blank]" will be filled with "high" in the majority of cases because "high" is the path of least resistance — it requires no additional reasoning, triggers no additional output, and avoids the risk of appearing incompetent. This is not dishonesty; it is the structural consequence of an unconstrained blank field defaulting to the most common answer.

A format that requires annotation only when departing from a default inverts this dynamic. The default is "high confidence" — the path of least resistance is to say nothing. An agent who annotates MODERATE or LOW is making a positive choice to deviate from the default, which requires a positive reason. This produces higher information density because annotations represent genuine departures, not pattern-matched fill-ins.

**The vocabulary design is choice architecture.** Providing only two departure levels (MODERATE CONFIDENCE, LOW CONFIDENCE) and requiring a mandatory reason clause with each creates a choice architecture that nudges toward accurate self-assessment. Reporting MODERATE CONFIDENCE requires the agent to articulate why. If the agent cannot articulate why, the annotation should not appear. The mandatory reason clause is the mechanism that forces genuine monitoring rather than superficial form-filling.

**The format specification IS the choice architecture for agent self-reporting.** Every structural decision about what fields are required, what values are allowed, and what the default is will shape agent behavior more reliably than any instruction about accurate self-assessment.

### 2.6 Information Design

**Core research:** Tufte ("The Visual Display of Quantitative Information," 1983) establishes two principles that apply directly to confidence format design:

- **Small multiples:** Repeated instances of the same structure (same dimensions, same vocabulary) allow immediate cross-comparison. Variable structures require re-learning on each encounter.
- **Data-ink ratio:** Every element of a display should carry information. Elements that carry no information should be removed.

**Application:**

A fixed set of exactly five dimensions with a small, fixed vocabulary (HIGH / MODERATE / LOW) is a small-multiples design. Engineers and agents reviewing session logs can immediately compare confidence patterns across sessions because the structure is identical. "Preference alignment: MODERATE" in session 15 is directly comparable to "preference alignment: MODERATE" in session 7 because the dimension definition, vocabulary, and format are identical.

A variable dimension set — where agents name whatever dimensions seem relevant per session — precludes this comparison. Two sessions that both mention "alignment" but define it differently cannot be compared.

**Data-ink ratio applied to confidence reporting:** A confidence annotation with five dimensions all reporting "high" has five data elements and zero information (all elements are predictable). The data-ink ratio is zero. Removing the annotation from high-confidence claims and reporting only departures produces a data-ink ratio of 1.0 — every element carries information because every element represents a departure from the default.

**The minimum viable vocabulary is three levels (HIGH / MODERATE / LOW)** because:
- Two levels (HIGH / LOW) does not capture genuine intermediate uncertainty
- Four or more levels exceeds human ability to reliably discriminate in self-assessment and produces false precision

**Five is the right number of dimensions** because:
- Fewer than five misses genuinely separable epistemic dimensions (technical correctness and domain coverage are both necessary and do not reduce to each other)
- More than five exceeds the number of dimensions an agent can genuinely assess independently without collapsing to global confidence

---

## 3. Dimension Taxonomy

The following five canonical confidence dimensions are proposed. These are fixed — agents do not add or remove dimensions per session. All five are always potentially applicable; which ones are most relevant varies by task type.

---

### Dimension 1: Technical Correctness

**Short label:** `technical`

**Operational definition:** The agent asks itself: "If I execute this approach exactly as specified, how confident am I that it will produce a technically correct result — one that will work mechanically, computationally, or logically, independent of whether it matches the user's preferences?"

This dimension concerns the internal validity of the approach. It is not about whether the user will like the result; it is about whether the result will be right in the technical sense. A code snippet that will compile and run correctly. A calculation that will produce the accurate numerical answer. An architectural pattern that will not introduce the class of failure it's intended to prevent.

**When most relevant:** Tier 2 and Tier 3 tasks in technical domains. Code, architecture, data analysis, mathematical reasoning. Less relevant for pure communication tasks (register and preference alignment dominate there).

**What each level means for this dimension:**

| Level | Meaning |
|-------|---------|
| HIGH (default, unmarked) | Agent has strong prior in this specific technical domain; the approach is well-established and the agent has applied it correctly in closely analogous prior contexts. |
| MODERATE | The approach is plausible and likely correct, but the agent is working at or near the edge of established knowledge; a review or verification step is warranted. |
| LOW | The agent is not confident the approach will produce a correct technical result; a qualified review is required before execution. |

---

### Dimension 2: Preference Alignment

**Short label:** `preference`

**Operational definition:** The agent asks itself: "How confident am I that this specific decision — this trade-off, this priority ordering, this choice among alternatives — reflects what this user would choose if explicitly asked, based on their revealed preferences from prior sessions?"

This dimension concerns the match between the agent's decision and the user's established decision patterns. It is about the substance of the choice, not its presentation. Preference alignment is about "would the user make this call?" not "would the user like how I said it?" (that is register). An agent can be confident in preference alignment when it has abundant, consistent prior signal about the user's decisions in similar situations. Confidence drops when the prior is absent, ambiguous, or the current situation introduces a factor not previously observed.

**When most relevant:** Every task type, but especially relevant at decision points involving trade-offs (speed vs. quality, completeness vs. brevity, risk vs. conservatism). Most salient in Tier 2 and Tier 3 tasks where the agent makes consequential decisions autonomously.

**What each level means for this dimension:**

| Level | Meaning |
|-------|---------|
| HIGH (default, unmarked) | Multiple prior sessions have revealed consistent decision patterns for this type of trade-off; agent is confident the current decision reflects established preference. |
| MODERATE | Prior sessions provide some signal but are incomplete or mixed; the current situation introduces a trade-off dimension not previously observed or presents an edge case relative to established patterns. |
| LOW | Little or no prior signal for this type of decision; or prior sessions are explicitly contradictory on this dimension; or the user's stated preferences and revealed behaviors have diverged in ways the agent cannot resolve. |

---

### Dimension 3: Register and Style

**Short label:** `register`

**Operational definition:** The agent asks itself: "How confident am I that the tone, formality level, technical depth, and length of this output match what this user expects in this specific context — not just in general, but given the type of request and the current session mode?"

This dimension concerns presentation preferences: formal vs. colloquial, detailed vs. summarized, technical vs. accessible, brief vs. comprehensive. It is distinct from preference alignment because it concerns surface form rather than substantive content. Register calibration requires understanding not just the user's general style preferences but how those preferences shift by context — the same user may want a brief informal note in one session and a detailed technical document in another.

**When most relevant:** Communication-heavy tasks (writing, documentation, explanation). Tier 0 and Tier 1 tasks where most of the work IS the communication. Also relevant at delivery points in Tier 2 and 3 tasks when presenting outputs to the user.

**What each level means for this dimension:**

| Level | Meaning |
|-------|---------|
| HIGH (default, unmarked) | Prior sessions with similar task types have provided clear, consistent signal on register and style preferences; the current output is in a well-established mode. |
| MODERATE | Prior sessions provide general style signal but the current context type is less frequently observed; or the user's register preferences have shown context-dependence that the agent is not certain about for this context type. |
| LOW | The agent has weak or contradictory signal about the appropriate register for this specific context; or the task is in a format or mode the agent has not handled with this user before. |

---

### Dimension 4: Scope Completeness

**Short label:** `scope`

**Operational definition:** The agent asks itself: "How confident am I that I have identified all of the requirements, constraints, and deliverables that the user intends to be within scope for this task — and that there are no significant gaps in the requirement set that will become apparent during execution or review?"

This dimension concerns whether the task boundary has been accurately defined. Scope completeness is low when requirements are still being refined, when the task is novel enough that edge cases are hard to anticipate, or when prior sessions have revealed a pattern of scope surprises with this user or task type. It is not about whether the work is complete — it is about whether the agent is confident the work being done is the right work.

**When most relevant:** Tier 3 tasks and complex Tier 2 tasks at the intake and planning stages. Scope completeness uncertainty is most dangerous at session open, before significant execution has occurred. Less relevant in late execution when scope has been validated through partial delivery.

**What each level means for this dimension:**

| Level | Meaning |
|-------|---------|
| HIGH (default, unmarked) | Requirements have been explicitly captured, confirmed, and are clear; prior sessions with similar tasks have not revealed scope surprises; scope boundary is well-defined. |
| MODERATE | Requirements are mostly clear but the task type or domain has historically produced scope expansions; or some edge cases remain unresolved that may affect the work scope. |
| LOW | Requirements are still being actively refined; the task is novel enough that the agent cannot confidently anticipate scope boundaries; or prior sessions with this task type have produced significant scope surprises. |

---

### Dimension 5: Domain Coverage

**Short label:** `domain`

**Operational definition:** The agent asks itself: "How confident am I in the breadth and currency of my knowledge in this subject area — that I have not missed relevant approaches, constraints, standards, or developments that an expert in this domain would consider before proceeding?"

This dimension concerns the agent's knowledge base, not the correctness of what the agent knows (that is technical correctness). Domain coverage is about whether the agent knows what it doesn't know. An agent can have high technical correctness confidence (what it knows, it knows well) and low domain coverage confidence (the domain may contain relevant considerations the agent is not aware of). The classic signal of low domain coverage is a novel domain, a rapidly evolving field, or a specialized subfield outside the agent's established training.

**When most relevant:** Tier 2 and Tier 3 tasks in specialized domains. Technical research, legal or regulatory analysis, domain-specific engineering. Less relevant in stable, well-established domains with broad prior coverage.

**What each level means for this dimension:**

| Level | Meaning |
|-------|---------|
| HIGH (default, unmarked) | The domain is within the agent's established training base; the agent is confident it would recognize and incorporate relevant constraints, standards, and alternatives that an expert would consider. |
| MODERATE | The domain is familiar in outline but contains specialized subfields or recent developments the agent may not fully represent; a domain review or external validation is advisable for high-stakes decisions. |
| LOW | The domain is outside the agent's established coverage; the agent may not know what it doesn't know; external domain expertise should be consulted before consequential decisions. |

---

## 4. Three Alternatives

### Alternative A: Fixed Dimension Set, Ordinal Scale, Always Present

**Description:** Every recommendation includes a confidence block containing all five dimensions, always, regardless of whether confidence is uniform or differentiated.

**Format:**

```
Confidence: technical: high | preference: moderate | register: high | scope: high | domain: moderate
```

Or in multi-line block form for readability:

```
Confidence:
  technical:   high
  preference:  moderate
  register:    high
  scope:       high
  domain:      moderate
```

**Advantages:**

- Fully consistent structure across sessions enables retrospective parsing and calibration measurement
- No inference required about whether absence of annotation means "high confidence" or "agent forgot to annotate"
- Establishes a baseline from the first session; no cold-start ambiguity
- Machine-parseable format supports automated calibration record extraction in summarize_session.py
- Aggregate analysis of all five dimensions is immediately available from day one

**Disadvantages:**

- When all dimensions are "high," the block carries zero information (Shannon noise floor). A session in an established domain with a familiar user may produce dozens of confidence blocks, all reading "high | high | high | high | high." Each block consumes attention and carries nothing.
- Risk of agents pattern-matching without genuine monitoring. When agents know a five-field block is required, the path of least resistance is to fill all fields with "high" — especially given Steyvers & Peters (2025) findings on LLM overconfidence. The required format does not guarantee the assessment is genuine.
- Cognitive overhead when unnecessary. Tier 1 and Tier 0 tasks in warm-start conditions have no genuine uncertainty requiring annotation. Mandating confidence blocks on these tasks creates output inflation.

**Failure modes:**

- **Calibration inflation:** Agents learn that "high | high | high | high | high" is the zero-friction path and progressively fill blocks with "high" regardless of actual confidence. Outcome-to-prediction gap widens over time; calibration measurement reveals systematic overconfidence but cannot identify when the drift began.
- **Habituated filtering:** Humans learn to skip confidence blocks because they are never informative. When a genuinely low-confidence annotation appears, it is filtered along with the habitual high-confidence blocks. The format succeeds at producing annotations and fails at producing signal.

---

### Alternative B: Departure-Only Annotation with Contextual Dimensions

**Description:** Confidence annotations appear ONLY when at least one dimension departs from a calibrated default. Absence of annotation means all dimensions are at their default (high confidence). Agents name only the departing dimensions, describe the departure, and provide a reason.

**Format:**

```
[Confidence note: preference alignment MODERATE — uncertain whether you'd prefer formal or colloquial register here based on mixed prior signal.]
```

Or for multiple departing dimensions:

```
[Confidence note: preference alignment MODERATE — trade-off between speed and completeness hasn't come up in prior sessions. scope LOW — requirements for edge case handling still being confirmed.]
```

**Advantages:**

- Every annotation that appears is informative. Presence is itself a signal (Shannon).
- No noise when confidence is high — the majority of claims in established domains produce no annotation overhead.
- Contextual dimension labeling allows agents to name dimensions precisely as they apply, rather than mapping to a fixed taxonomy.
- Behavioral economics advantage: default is silence; annotation requires positive choice and is therefore more likely to represent genuine monitoring.

**Disadvantages:**

- Dimension labels are inconsistent across sessions. "preference alignment" in one session and "user preference" in another cannot be aggregated for calibration measurement. The inconsistency is inherent to free-form dimension naming.
- "Absence = high confidence" is a dangerous structural assumption. If agents forget to annotate (cognitive load, long sessions) or inconsistently apply the threshold for what constitutes a "departure," absence no longer reliably means "high confidence." It may mean "agent didn't notice" or "agent was uncertain but didn't flag it."
- No baseline for calibration. Without a structured baseline, the calibration record is incomplete: we know when agents flagged uncertainty but not when they should have flagged it but didn't.
- Session-to-session comparison is difficult when dimensions vary. The calibration framework in Section 7 requires consistent dimension labels across sessions.

**Failure modes:**

- **Silent mis-calibration:** Agent is low-confidence on multiple dimensions but has learned (through volume of output) to omit annotations under cognitive load. Absence is misread as high confidence. Delivery occurs before misalignment is detected. This is the most dangerous failure mode because it produces no signal before the problem surfaces.
- **Inconsistent threshold drift:** Different agents (or the same agent in different sessions) apply different thresholds for what warrants annotation. One agent annotates MODERATE when it's "slightly uncertain"; another annotates MODERATE only when it's "meaningfully uncertain." Without a shared threshold, annotations are not comparable.

---

### Alternative C: Two-Tier — Session-Level Posture Plus Claim-Level Departure Flags

**Description:** The session OPENS with a session-level confidence posture (1-3 sentences synthesizing the most relevant dimensions for this session, derived from accumulated calibration data). Individual claims are flagged INLINE only when departing significantly from the opening posture. The opening posture is the baseline; inline flags are departures from it.

**Session opening format:**

```
Working model: HIGH confidence in technical approach (established calibration in this domain across 8 prior sessions), MODERATE confidence in preference alignment (this trade-off type is new — haven't seen your risk preference here), UNCERTAIN on scope completeness (requirements still being confirmed, recommend checkpoint at 50%).
```

Or for a warm-start in a fully established domain:

```
Working model: Strong prior in all dimensions for this task type. Will flag any departures inline.
```

**Inline flag format:**

```
[MODERATE CONFIDENCE: preference alignment — this architectural trade-off prioritizes performance over maintainability in a way that hasn't come up in prior sessions; uncertain whether this aligns with your established risk tolerance.]
```

```
[LOW CONFIDENCE: scope — the edge case handling requirements for concurrent users haven't been specified; proceeding on assumption of standard handling but this should be confirmed before production.]
```

**Advantages:**

- SA-Level-2 support (Endsley 1995) via the opening posture: the human receives a synthesized situational assessment at session open, not raw dimension-by-dimension data.
- Machine-parseable inline flags with structured vocabulary (MODERATE CONFIDENCE / LOW CONFIDENCE) support calibration record extraction in summarize_session.py.
- Posture sets expectations upfront. The human knows at session open whether to expect close oversight or routine monitoring.
- Inline flags appear only at genuine departure points, preserving the Shannon advantage (presence = signal) while providing a consistent structural baseline.
- Posture is derived from accumulated calibration data rather than generated fresh, which reduces overconfidence bias: the system is explicitly grounding the posture in prior outcome data.
- The opening posture is legible to the human, which supports the trust model described in human-dynamics.md: "An agent should be able to reason explicitly about why it's operating at a given confidence level, making the trust model legible to the human."

**Disadvantages:**

- Two kinds of output increases prompt complexity. Agents must be prompted to generate both a session-level posture and inline flags, and must understand how they relate.
- Posture may become boilerplate if not grounded in calibration data. An agent that generates posture text without querying prior calibration records will pattern-match to a generic opening statement.
- Warm-start conditions for posture require that calibration data actually exist and be accessible. Cold-start posture must be explicitly flagged as "no prior calibration data."

**Failure modes:**

- **Boilerplate posture drift:** Opening posture text is pattern-matched rather than derived from calibration records. All sessions open with nearly identical posture regardless of actual prior signal. Detectable by checking entropy of posture text across sessions; low entropy indicates boilerplate.
- **Posture-flag gap:** Agent generates an accurate opening posture but fails to generate inline flags when departing from it during execution. Long sessions with high cognitive load are most susceptible.

---

## 5. Comparative Analysis Table

| Dimension | Alt A (Always-Present) | Alt B (Departure-Only) | Alt C (Two-Tier) |
|-----------|----------------------|----------------------|-----------------|
| Signal density | Low (noise when all high) | High | High |
| Calibration measurability | High | Low (inconsistent dims) | High |
| Cognitive load on agent | Low (always fills all fields) | Low (annotates only when needed) | Medium (posture + flags) |
| Retrospective extraction | Excellent (fixed structure) | Partial (variable dims) | Excellent (structured flags) |
| SA-Level-2 support | Weak (no synthesis) | None (no baseline) | Strong (opening posture) |
| Human cognitive overhead | High (parse always) | Low (mostly absent) | Low (posture + sparse flags) |
| Cold-start behavior | Defined (fills all fields) | Ambiguous (no baseline) | Defined (explicit "no prior data") |
| Primary failure mode | Calibration inflation | Silent mis-calibration | Boilerplate posture |
| Behavioral economics alignment | Weak (blanks invite "high") | Strong (default is silence) | Strong (default is silence for flags) |
| Cross-session comparison | Excellent | Poor | Excellent |

---

## 6. Recommendation

**Recommend Alternative C (Two-Tier: Session-Level Posture + Claim-Level Departure Flags)** with the following specific enhancements.

### 6.1 Enhancements to Alternative C

**Enhancement 1: Posture Derived from Calibration Records, Not Generated Fresh**

The session-level posture must not be generated as free text from scratch. It must be derived from the agent's accumulated calibration records in memory. Specifically:

- For each of the five canonical dimensions, the posture statement must cite whether prior calibration data exists for this domain and this user
- If calibration data exists, the posture must derive from it (e.g., "established HIGH confidence in technical dimension across 12 sessions, measured accuracy 89% on MODERATE-flagged claims")
- If no calibration data exists for a dimension, the posture must explicitly state "unestablished" rather than defaulting to "high"
- For tasks in domains covered by ESCALATION.md or similar domain constraint records, the posture may cite established domain-level calibration
- Cold-start domains MUST produce postures that read differently from warm-start domains — this difference is itself informative

**Enhancement 2: Two Departure Levels Only — MODERATE and LOW**

Inline flags use exactly two levels: MODERATE CONFIDENCE and LOW CONFIDENCE. HIGH is the unmarked default and is never annotated. Rationale:

- Annotating "HIGH CONFIDENCE" adds no information (Shannon): the receiver already knows high confidence is the default
- Providing three annotation levels (high / moderate / low) when one is already the default creates a false three-level system; in practice only two choices matter (moderate or low), so the format should reflect the actual choice
- The "high confidence" case is handled by the absence of an inline flag, which is already informative by the presence logic above

**Enhancement 3: Mandatory Reason Clause on Every Inline Flag**

Every inline flag requires a reason clause: one sentence explaining what specific factor produces the departure. No exceptions.

Rationale from two directions:
- From information design: a flag without a reason is structurally equivalent to the bare escalation question the spec prohibits — it transfers uncertainty to the human without adding value
- From behavioral economics: the mandatory reason clause is the enforcement mechanism that separates genuine self-monitoring from form-filling; if the agent cannot articulate why it's MODERATE, the annotation should not appear

A flag without a reason clause SHOULD be treated as a malformed annotation during retrospective review and flagged as a failure mode instance.

### 6.2 Exact Prompt Text

The following prompt text is verbatim specification to be incorporated into agent prompts. It is written for direct inclusion; do not paraphrase or summarize.

---

**Prompt 6.2a — Session-Level Posture (Cold Start):**

```
CONFIDENCE POSTURE (REQUIRED AT SESSION OPEN):

Before beginning work, state your working confidence model for this session in 1-3 sentences. This statement must cover the dimensions most relevant to this task. Use the canonical dimension labels: technical, preference, domain, scope, register.

For cold-start conditions (no prior calibration data for this domain or user):

  Working model: No established calibration data for [domain]. Operating at default uncertainty across all dimensions. Technical approach is [within / at edge of / outside] established knowledge. Preference alignment is unestablished — will flag all consequential trade-off decisions for confirmation. Scope completeness is [clear / partially specified / still being defined]. Treating all MODERATE confidence thresholds conservatively.

Adapt this template to the specific session. Do not copy-paste verbatim; derive each element from the actual state of your knowledge. If a dimension is irrelevant to this task type, you may omit it with a brief note.
```

---

**Prompt 6.2b — Session-Level Posture (Warm Start):**

```
CONFIDENCE POSTURE (REQUIRED AT SESSION OPEN):

Before beginning work, state your working confidence model for this session in 1-3 sentences. Derive this statement from prior calibration records for this domain and user. Use the canonical dimension labels: technical, preference, domain, scope, register.

For warm-start conditions (prior calibration data available):

  Working model: [Summarize established calibration per dimension. Example: HIGH confidence in technical approach — 11 sessions in this domain, consistently validated. MODERATE confidence in preference alignment for trade-offs involving [specific trade-off type] — prior sessions are split; will flag decisions of this type. HIGH confidence in register — established pattern across session types. Note any dimensions where calibration is unestablished despite warm start.]

If calibration history is available, cite it explicitly: "established across N sessions" or "measured accuracy on MODERATE flags: X%." If a dimension has no calibration data despite warm start (novel combination of user + domain), mark it as "unestablished."

Do not generate this statement from scratch. Ground it in what you actually know from prior sessions. A posture that reads identically to other sessions is a failure signal — if everything is the same, explain why.
```

---

**Prompt 6.2c — Claim-Level Departure Flag:**

```
INLINE CONFIDENCE FLAGS:

Flag specific claims or recommendations when your confidence on any canonical dimension departs significantly from the session-level posture stated at open.

VOCABULARY: Use exactly two levels — MODERATE CONFIDENCE and LOW CONFIDENCE. Do not annotate high confidence; high is the default and annotating it adds no information.

FORMAT (required fields in this order):
  [MODERATE CONFIDENCE: {dimension} — {one-sentence reason stating specifically what produces the uncertainty}]
  [LOW CONFIDENCE: {dimension} — {one-sentence reason stating specifically what produces the uncertainty}]

{dimension} must be one of the five canonical labels: technical | preference | register | scope | domain

The reason clause is MANDATORY. A flag without a reason is a malformed annotation. If you cannot state in one sentence why you are departing from your established posture on this dimension, do not include the flag.

THRESHOLD GUIDANCE: Flag when you estimate that an independently calibrated reviewer, knowing what you know, would have at least a 1-in-4 chance of disagreeing with the claim or making a different decision. This is a judgment call, not a calculation — use it to force the question: "Is a reasonable alternative decision plausible here, or am I clearly right?" If a reasonable alternative is clearly plausible, flag.

Do not flag routine claims within well-established operating parameters. Do not over-flag — a session where every claim is flagged has the same information content as a session where no claims are flagged, because no claim is distinguishable from another.
```

---

**Worked example of a correctly-formatted flag:**

```
The appropriate approach here is to use an event-sourced architecture with eventual consistency rather than a synchronous write-through model.

[MODERATE CONFIDENCE: preference — prior sessions favor strong consistency guarantees; this trade-off favors availability over consistency in a way that hasn't been explicitly discussed, and I'm uncertain whether your risk tolerance extends to eventual consistency here.]

Proceeding on this assumption. Please confirm or redirect at the next checkpoint if this trade-off concerns you.
```

---

## 7. Calibration Analysis Framework

### 7.1 Data Capture Requirements per Session

The following data must be captured per confidence annotation to enable calibration measurement. This data is the input to the memory system's calibration record type (see learning-evolution.md) and feeds domain-level confidence calibration for future session postures.

**Per-annotation record:**

```json
{
  "record_type": "confidence_annotation",
  "session_id": "session-20260301-131335",
  "claim_id": "claim-20260301-131335-07",
  "task_tier": 2,
  "domain": "software-architecture",
  "dimension": "preference",
  "confidence_level": "MODERATE",
  "reason": "prior sessions are split on consistency vs. availability trade-off",
  "claim_text": "[first 100 chars of the claim or recommendation]",
  "outcome": null,
  "outcome_recorded_at": null,
  "session_posture_at_open": "HIGH technical, MODERATE preference (trade-off type unestablished), HIGH register"
}
```

**Outcome field values:**

| Value | Meaning |
|-------|---------|
| `accepted` | Human accepted the claim or recommendation without correction |
| `corrected` | Human modified the claim or redirected — the agent's decision was not the right one |
| `rejected` | Human explicitly rejected the claim |
| `no_decision` | Claim was informational; no binary acceptance/rejection is applicable |
| `null` | Outcome not yet recorded (default at annotation time; updated during retrospective) |

Outcome values are recorded during `summarize_session.py` retrospective extraction. The agent identifies which annotated claims were accepted, corrected, or rejected based on session transcript review.

### 7.2 Calibration Score Formula

For each dimension, at each confidence level, compute the empirical accuracy rate across all outcome-linked annotations:

```
accuracy(dimension, level) = count(outcome == "accepted") / count(outcome IN ["accepted", "corrected", "rejected"])
```

Note: `no_decision` outcomes are excluded from the denominator (they are not calibration-informative).

**Expected accuracy targets by confidence level:**

| Reported Level | Expected Accuracy | Over-confident zone | Under-confident zone |
|---------------|------------------|--------------------|--------------------|
| MODERATE | 65-75% | < 50% | > 90% |
| LOW | 40-55% | < 25% | > 75% |
| HIGH (implicit, no flag) | > 90% | < 75% | Not applicable |

Rationale: MODERATE confidence should correspond to roughly 2-in-3 claims being accepted. If MODERATE-flagged claims are accepted >90% of the time, the agent is reporting MODERATE when it should report HIGH (under-confident, wasting signal). If MODERATE-flagged claims are accepted <50% of the time, the agent is reporting MODERATE when it should report LOW (over-confident, providing false reassurance).

**Calibration health check:**

```
calibration_health(dimension, level) = "over-confident"   if accuracy < lower_bound
                                      "calibrated"         if lower_bound <= accuracy <= upper_bound
                                      "under-confident"    if accuracy > upper_bound
```

The calibration health status per dimension feeds the session-level posture derivation for future sessions.

### 7.3 Minimum Sample Size Before Point Estimates Are Meaningful

**Minimum: 30 outcome-linked claims per confidence level per dimension.**

Statistical rationale: With n=30 and a hypothesized true accuracy rate of p=0.70, the 95% confidence interval is approximately:

```
p ± 1.96 * sqrt(p(1-p)/n) = 0.70 ± 1.96 * sqrt(0.70 * 0.30 / 30) = 0.70 ± 0.164
```

This interval (0.54, 0.86) is wide but sufficient to distinguish "clearly over-confident" (accuracy < 0.50) from "calibrated" (0.65-0.75) from "clearly under-confident" (accuracy > 0.90). Finer distinctions require n=100+.

**Practical implication:** A system with 5 dimensions and 2 annotated levels requires at minimum 300 outcome-linked annotations before all cells have statistically meaningful estimates. At an average of 3 annotations per session, this requires approximately 100 sessions. The system should:

1. Track running sample sizes per cell (dimension × level)
2. Flag calibration estimates as "INSUFFICIENT DATA (n=X, minimum 30)" when below threshold
3. Not use calibration estimates to adjust posture until the threshold is reached
4. Use "unestablished" posture language for cells below threshold

### 7.4 How Calibration History Adjusts Future Session-Level Posture

Once a calibration cell reaches n ≥ 30 with a calibration_health determination, it feeds the session-level posture derivation:

**If calibration_health == "calibrated":** Posture states the confidence level as established: "HIGH confidence in [dimension] — calibrated across N sessions."

**If calibration_health == "over-confident":** Posture explicitly states the calibration finding: "MODERATE confidence in [dimension] — prior sessions show calibration drift; agent-reported HIGH has historically overestimated accuracy. Treating all [dimension] assessments at one level lower than reported."

**If calibration_health == "under-confident":** Posture notes the pattern: "ESTABLISHED confidence in [dimension] — prior MODERATE flags have been highly accurate (X%). May be over-flagging; adjusting threshold upward."

This adjustment is not applied by the agent unilaterally — it is included in the session posture text so the human can validate the calibration history. The trust model in human-dynamics.md requires this legibility: the human should be able to see and validate the calibration basis, not just receive the adjusted behavior as an opaque output.

---

## 8. Prompt Specifications (Exact Text)

### 8.1 Session-Level Posture

The following is verbatim prompt language. Insert into agent system prompts at the session initialization section.

---

**Cold-Start Case (no prior calibration data for this domain with this user):**

```
SESSION CONFIDENCE POSTURE — COLD START

At the opening of this session, before any substantive work, state your confidence posture in 2-4 sentences. This posture covers the five canonical confidence dimensions (technical, preference, register, scope, domain) as they apply to this specific session and task.

COLD-START REQUIREMENTS: When no prior calibration data exists for this domain with this user, your posture must:

1. Explicitly state that calibration is unestablished: "No prior calibration data for [domain]."
2. State your technical and domain coverage assessment honestly. If this domain is within established training, say so. If it is at the edge or outside, say so.
3. State that preference alignment is unestablished and that consequential trade-off decisions will be flagged for confirmation.
4. State the scope status: clear, partially specified, or still being defined.
5. Commit to conservative MODERATE thresholds: when uncertain whether to flag MODERATE or not, flag.

TEMPLATE (adapt; do not copy verbatim):
  Working model: No established calibration data for [domain] with this user. Technical approach is [within established knowledge / at the edge of established knowledge / outside established knowledge]. Preference alignment is unestablished — I will flag all consequential trade-off decisions for confirmation rather than assuming alignment with prior patterns. Scope is [well-defined / partially specified / still being clarified — will checkpoint at [milestone]]. Operating conservatively on all thresholds; will flag departures that I would otherwise treat as routine in established domains.

FAILURE CONDITION: A cold-start posture that reads "HIGH confidence across all dimensions" is a malformed posture. Cold-start conditions produce genuine uncertainty on at least preference alignment and scope; a posture that does not reflect this is not derived from the actual epistemic state.
```

---

**Warm-Start Case (established calibration history for this domain with this user):**

```
SESSION CONFIDENCE POSTURE — WARM START

At the opening of this session, before any substantive work, state your confidence posture in 1-3 sentences derived from prior calibration records. Do not generate this statement from scratch; derive it from what accumulated session data establishes about your calibration in this domain with this user.

WARM-START REQUIREMENTS:

1. For each dimension where calibration data exists (n ≥ 30 outcome-linked annotations), state the established calibration level and cite the evidence: "established HIGH confidence in [dimension] across N sessions."
2. For dimensions where calibration data exists but is below the n=30 threshold, note it: "emerging signal on [dimension] (N sessions, insufficient for point estimate)."
3. For dimensions where calibration data does not exist (novel task type or combination), explicitly mark as unestablished.
4. If calibration data reveals over-confidence or under-confidence in prior sessions, state it: "Prior MODERATE flags on [dimension] have been over-conservative (X% accuracy); adjusting threshold upward."
5. Note the most critical uncertainty for this specific session — the dimension most likely to produce a departure from established patterns.

TEMPLATE (adapt; do not copy verbatim):
  Working model: [established/emerging/unestablished] confidence profile. Technical: [level + evidence]. Preference: [level + evidence or "unestablished for this trade-off type"]. Register: [level + evidence]. Scope: [current status]. Domain: [level + evidence]. Key uncertainty for this session: [dimension] — [one sentence on why this session may depart from established pattern].

FAILURE CONDITION: A warm-start posture that is indistinguishable from the prior session's posture without explanation is a boilerplate failure. If the posture is the same as last session, state explicitly why: "No new calibration data since last session; posture unchanged." This makes the absence of change legible rather than hiding it in identical text.
```

### 8.2 Claim-Level Flag

The following is verbatim prompt language. Insert into agent system prompts at the inline output generation section.

---

```
CLAIM-LEVEL CONFIDENCE FLAGS

Flag specific claims or recommendations inline when your confidence on any canonical dimension departs from the session posture established at open.

CANONICAL DIMENSIONS: technical | preference | register | scope | domain
VOCABULARY: MODERATE CONFIDENCE or LOW CONFIDENCE only. Never annotate HIGH CONFIDENCE — high is the default; annotating it adds no information and dilutes the signal of genuine flags.

REQUIRED FORMAT:
  [MODERATE CONFIDENCE: {dimension} — {one-sentence reason}]
  [LOW CONFIDENCE: {dimension} — {one-sentence reason}]

The reason clause is not optional. A flag with no reason clause is a malformed annotation and will be treated as such during retrospective review. If you cannot complete the reason clause, do not include the flag.

THRESHOLD HEURISTIC: Flag when you estimate that a competent independent reviewer, given full knowledge of the situation, would have at least a 1-in-4 chance of making a different decision or identifying the claim as incorrect. Ask yourself: "Is a reasonable alternative clearly plausible here?" If yes, flag. If the claim is clearly within established operating parameters with no plausible alternative, do not flag.

SUPPRESSION RULE: Do not flag claims that are within the confidence profile established at session open unless something in execution has shifted. The posture was established to avoid per-claim overhead in well-calibrated territory. Flag when something changes from the posture, not when something is consistent with it.

OVER-FLAGGING FAILURE MODE: A session where every claim carries a confidence flag has the same information content as a session where no claims carry flags — the human cannot distinguish which flags deserve attention. Reserve flags for genuine departures. If you find yourself flagging more than 30% of substantive claims, reconsider whether your threshold is too low.

WORKED EXAMPLE (correct):

  Claim: The appropriate data retention policy is 90-day rolling deletion with no archival tier.

  [MODERATE CONFIDENCE: preference — your prior sessions on data architecture have prioritized cost minimization, but I haven't seen an explicit signal on your tolerance for permanent data loss in this operational context; this trade-off is consequential and I'd recommend confirming before implementing.]

  Proceeding on this assumption. Flag at the next checkpoint if this needs to change.

WORKED EXAMPLE (malformed — do not do this):

  [MODERATE CONFIDENCE: technical]                          <- missing reason clause
  [HIGH CONFIDENCE: preference — very confident here]       <- annotating default level
  [MODERATE CONFIDENCE: uncertain]                          <- not a canonical dimension
```

---

## 9. Failure Mode Analysis

### 9.1 Calibration Inflation (Always "High")

**What it looks like in practice:** Agent generates session posture with all dimensions at HIGH and generates no inline flags throughout the session. Outcomes data shows that flagged decisions are rare but accepted at low rates when they do occur (indicating the threshold was set too high). Across sessions, preference and scope dimensions show near-zero annotation rates even in novel domains.

**What causes it:** The path-of-least-resistance effect (Thaler & Sunstein 2008 nudge / choice architecture). Agents fill confidence blanks with "high" because that requires no additional reasoning and produces no additional output burden. Steyvers & Peters (2025) fluency-driven overconfidence compounds this — agents produce confident text easily and mistake fluency for accuracy. Absent a mandatory threshold check, the agent's default is to proceed without flagging.

**How to detect during retrospective review:**
- Count inline flags per session. Sessions with zero flags across all substantive claims are suspect unless the task is genuinely simple and well-established.
- Check posture for cold-start vs. warm-start differentiation. If cold-start postures read the same as warm-start postures (all HIGH), posture derivation is not grounded in calibration data.
- Track the ratio of MODERATE/LOW flags to total claims over time. A declining ratio in an expanding domain (where novel claims should produce more uncertainty, not less) is a calibration inflation signal.
- Audit: pick five claims from sessions with no flags and independently assess whether any warranted MODERATE confidence. If independent review finds flags the agent should have generated, calibration inflation is confirmed.

---

### 9.2 Calibration Uniformity (Always "Moderate")

**What it looks like in practice:** Agent generates all five dimensions at MODERATE in the session posture and frequently generates MODERATE CONFIDENCE inline flags. Outcomes data shows that MODERATE-flagged claims are accepted at rates above 90% — the agent is over-flagging, calling things MODERATE that are genuinely HIGH. Signal-to-noise collapses; humans filter MODERATE flags because they have learned MODERATE doesn't predict actual uncertainty.

**What causes it:** Overcorrection from anti-overconfidence prompting. If agents are instructed to "err on the side of flagging," they may flag everything as a defensive move. Also caused by poorly calibrated threshold guidance — if "1-in-4 chance of disagreement" is interpreted very broadly, nearly every claim qualifies. In systems where escalation is disproportionately penalized relative to under-flagging, agents may over-flag to shift responsibility.

**How to detect during retrospective review:**
- Track accuracy rate on MODERATE-flagged claims. If accuracy consistently exceeds 85-90%, MODERATE flags are being over-generated.
- Check flag frequency per session. If more than 25-30% of substantive claims carry MODERATE flags, the threshold is too low.
- Compute the entropy of the confidence annotation set. Low entropy (uniform distribution toward MODERATE) indicates uniformity.
- Compare flag rates in established domains vs. novel domains. If flag rates are similar across both, flags are not calibrated to actual uncertainty.

---

### 9.3 Dimension Misapplication (Wrong Dimension for Claim Type)

**What it looks like in practice:** Agent applies "technical" flags to claims that are actually about preference alignment — for example, flagging MODERATE CONFIDENCE: technical on a claim about document length (which is a register/style decision, not a technical one). Or applying "scope" flags to questions about accuracy (which is a technical or domain dimension). Retrospective analysis reveals that flags on a given dimension do not predict outcomes in the way that dimension's definition would predict.

**What causes it:** Dimension taxonomy is learned, not intuitive. Without sufficient training on the operational definitions, agents use dimension labels that superficially match the surface description of the uncertainty ("I'm uncertain about this technical decision" → MODERATE CONFIDENCE: technical) rather than the epistemic source of the uncertainty (which may actually be about preference alignment — they know the technical answer, but not whether the user would sanction it).

**How to detect during retrospective review:**
- Check calibration scores by dimension against claim types. If "technical" dimension accuracy varies widely by claim type in a way that doesn't track technical content, misapplication is likely.
- Look for systematic patterns: do certain claim types always get flagged under the same dimension regardless of the actual epistemic situation?
- Manual audit: for a sample of claims with dimension flags, apply the operational definition (Section 3) to determine whether the agent asked the right question to assess that dimension. If the answer to the dimension's question would have been "high confidence," but the agent flagged MODERATE, the wrong dimension was used.

---

### 9.4 Abandoned Reporting (Agents Stop Flagging in Long Sessions)

**What it looks like in practice:** Session begins with appropriately generated posture and correctly applied inline flags in the first one-third of the session. Flag frequency drops to near-zero in the final two-thirds of the session, even when claims in that portion warrant flags based on independent assessment. Long Tier 3 sessions show a characteristic "front-loaded" annotation pattern.

**What causes it:** Cognitive load effect — annotation overhead accumulates across a long session. The threshold for "is this different enough from my posture to warrant a flag?" gradually increases as the session extends, because flagging requires additional reasoning and output. This is the agent equivalent of vigilance decrement in human monitoring tasks: sustained attention to a monitoring criterion deteriorates under sustained cognitive load.

**How to detect during retrospective review:**
- Plot flag frequency by position in session (first third / middle third / final third). A declining trend is a vigilance decrement signal.
- Count claims in the final third of long sessions (>50 turns) that retrospective review identifies as warranting MODERATE or LOW flags. If the agent generated none, abandoned reporting is confirmed.
- Track by session length. Short sessions (< 20 turns) and long sessions (> 60 turns) should be compared. If flag rates differ dramatically (not explained by claim type differences), length is a moderating variable.

**Mitigation:** Include a periodic reminder in the prompt for long sessions: "You are now past the 30-turn mark. Reapply the inline flag threshold before each major claim. Sustained sessions can suppress flagging behavior; consciously reassess each substantive recommendation."

---

### 9.5 Posture Boilerplate (Session-Level Posture Copy-Pasted Across Sessions)

**What it looks like in practice:** Session posture text is nearly identical across multiple sessions regardless of domain, task type, or accumulated calibration data. Cold-start postures read the same as warm-start postures. Sessions with novel trade-off types produce the same posture as sessions with well-established patterns. The posture has ceased to function as a genuine situational assessment and has become a ritual opening.

**What causes it:** Boilerplate is generated when the posture derivation is not grounded in calibration data retrieval. If the prompt instructs the agent to "state your working confidence model" without specifying that it must be derived from prior calibration records, the agent generates a plausible-sounding default. The default is stable — it does not change across sessions because it is not derived from session-specific information.

**How to detect during retrospective review:**
- Compute text similarity between posture statements across sessions. Cosine similarity above 0.80 between postures for sessions with different domains or trade-off types is a boilerplate signal.
- Check whether postures for cold-start and warm-start sessions are distinguishable. If cold-start and warm-start postures read identically, posture is not being derived from calibration data.
- Look for calibration citations: warm-start postures should cite "N sessions" or accuracy rates. Postures without citations have not been derived from records.
- Check whether postures for low-confidence domains mention unestablished dimensions. If they don't, they were generated generically.

---

## 10. Cross-References

### 10.1 Connection to Q2 Model-Update Notes (learning-evolution.md)

The in-flight learning mechanism proposed in learning-evolution.md ("milestone completion events include a brief model-update note") is the in-flight upstream mechanism for which confidence flags are the within-claim output. These two mechanisms are complementary at different granularities:

- **Confidence flags** (this document) operate at claim granularity: specific recommendations within a session
- **Model-update notes** (learning-evolution.md) operate at milestone granularity: updates to assumptions at major execution checkpoints

For calibration measurement, Q2 model-update notes should carry two additional fields:

```json
{
  "prior_confidence": {
    "dimension": "preference",
    "level": "MODERATE",
    "as_of": "session-open"
  },
  "updated_confidence": {
    "dimension": "preference",
    "level": "LOW",
    "trigger": "First-milestone output revealed user prefers higher abstraction than I assumed at open"
  }
}
```

These `prior_confidence` and `updated_confidence` fields document intra-session confidence trajectory and enable a second calibration measurement: not just "was the flag accurate at claim time?" but "was the posture accurate at session open?" This is the retrospective validation of the posture itself.

Without these fields, the calibration loop captures only claim-level accuracy. With them, it captures posture-level accuracy — whether the session-opening situational assessment was correct as a whole, not just whether individual claims were correct.

### 10.2 Connection to Memory and Future Session Postures

The calibration data captured by this document's framework (claim, dimension, level, outcome) is the input that memory needs to update domain-level confidence calibration for future sessions. The data flow is:

```
Session → Confidence flags generated (inline)
        → summarize_session.py → extracts (claim, dimension, level) tuples
        → Human outcome review → records accepted/corrected/rejected
        → Calibration records → stored in memory with domain + user key
        → Future session posture → derived from calibration records, not generated fresh
```

The calibration record in memory feeds directly back to the session-level posture (Section 8.1 Warm-Start prompt). This closes the loop: annotations produce calibration data, calibration data updates postures, postures set accurate baselines, baselines make flags informative.

This loop is only closed if:
1. summarize_session.py extracts confidence annotation tuples (per Section 7.1 schema)
2. Outcome recording is completed (not left at `null`)
3. Calibration health checks are run against accumulated records
4. Posture derivation in new sessions explicitly queries these records

If any step in this chain is broken, the calibration measurement system produces garbage silently. The most common break point is step 2: outcome recording requires human review of the session transcript, which may be skipped under time pressure. Outcome recording must be treated as a required step, not optional retrospective work.

---

## 11. Provenance and Sources

### 11.1 Established Research (cited as source material)

The following are established research works, theories, and frameworks cited in this document. These are real published works with established standing in their fields.

| Citation | Year | Field | Application in this document |
|----------|------|-------|------------------------------|
| Lichtenstein, S. & Fischhoff, B., "Do Those Who Know More Also Know More About How Much They Know?" | 1977 | Psychology / Calibration research | Established that human probability assessments are systematically overconfident; defines calibration measurement methodology |
| Kahneman, D. & Tversky, A. | 1970s–1980s | Behavioral psychology | Heuristics-and-biases framework; availability heuristic as mechanism for overconfidence |
| Kahneman, D., "Thinking, Fast and Slow" | 2011 | Behavioral psychology | Synthesizes heuristics-and-biases into practical framework; System 1 / System 2 distinction |
| Steyvers, M. & Peters, M.A.K. (et al.), "The Calibration Gap..." | 2025 | LLM metacognitive calibration | LLMs systematically overconfident especially in high-fluency low-grounding domains; empirical finding directly relevant to agent systems |
| Shannon, C.E. & Weaver, W., "A Mathematical Theory of Communication" | 1948 | Information theory | Channel capacity theorem; information as uncertainty reduction; zero-information messages |
| Nelson, T.O. & Narens, L., "Metamemory: A Theoretical Framework and New Findings" | 1990 | Cognitive psychology / Metacognition | Monitoring vs. control distinction; defines metacognitive monitoring as distinct from metacognitive control |
| Endsley, M.R., "Toward a Theory of Situation Awareness in Dynamic Systems" | 1995 | Human factors engineering | Three-level SA model (perception / comprehension / projection); decision support system design implications |
| Thaler, R.H. & Sunstein, C.R., "Nudge: Improving Decisions About Health, Wealth, and Happiness" | 2008 | Behavioral economics | Choice architecture; default effects; format as policy |
| Tufte, E.R., "The Visual Display of Quantitative Information" | 1983 | Information design | Small multiples; data-ink ratio; fixed structure for cross-comparison |

### 11.2 Design Synthesis (our own application of research to this problem)

The following elements of this document are design synthesis — application of the research above to the specific requirements of the poc-workflow system. These are not established research findings; they are design decisions derived from research principles.

- **The five canonical confidence dimensions** (Section 3): The specific taxonomy of technical, preference, register, scope, and domain is original to this design. The dimensions are grounded in Nelson & Narens (separability requirement) and Information Design (fixed small set principle) but the specific set and operational definitions are design choices.

- **The two-tier format** (Alternative C, Section 4): The specific structure combining session-level posture with claim-level departure flags is original to this design. It is derived from applying Endsley's SA model, Shannon's information theory, and Thaler & Sunstein's choice architecture principles to the problem, but the specific format is not established research.

- **The calibration measurement framework** (Section 7): The specific calibration score formula, accuracy targets by confidence level, and sample size recommendations are design synthesis. The methodology is grounded in Lichtenstein & Fischhoff calibration measurement methodology, but the specific thresholds (n=30, 65-75% accuracy for MODERATE) are design decisions with statistical rationale, not established empirical findings.

- **The exact prompt text** (Section 8): All verbatim prompt text is original specification written for this system. It is grounded in the research principles above but is not itself a research finding.

- **Failure mode analysis** (Section 9): The five failure modes and their detection criteria are grounded in the research literature (calibration inflation in Lichtenstein & Fischhoff, vigilance decrement in human factors literature, boilerplate drift from choice architecture analysis) but the specific application to agent confidence reporting is design synthesis.

- **Cross-reference to Q2 model-update fields** (Section 10.1): The proposed `prior_confidence` and `updated_confidence` JSON fields are original specification, derived from the design goal of closing the calibration loop between in-flight learning (learning-evolution.md) and session posture accuracy measurement.

---

*End of document.*
