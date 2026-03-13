# Adaptive Workflow Design: Enabling Well-Aligned Autonomous Work

## 1. Executive Summary

The current POC workflow is a strong foundation that optimizes for correctness through uniform rigor. Its weakness is that it applies the same process weight to every request regardless of task weight — the full Intent → Plan → Execute pipeline fires whether the request is a status query or a multi-week project. This creates two simultaneous failures: friction on simple requests that erodes trust, and insufficient structure for complex projects where understanding only emerges through partial execution. The proposed adaptive workflow model addresses both by classifying tasks into four tiers before session creation and adjusting process weight accordingly. Two specific commitments distinguish this design from generic adaptive workflow proposals. First, the tier model is grounded in an asymmetric error cost argument: over-classifying a simple request as complex is merely annoying — it wastes time. Under-classifying a complex project as simple is catastrophic — it produces work that is confidently wrong at scale, with no structural checkpoint to catch the drift before delivery. That asymmetry justifies a conservative bias at classification time, even when it occasionally imposes unnecessary overhead on simple requests. Second, learning occurs at four distinct moments — prospective, in-flight, corrective, and retrospective — not just the retrospective post-run extraction that most learning systems implement. The prospective and corrective moments are architecturally wired but not yet fully active; their inclusion in the design is deliberate, not aspirational. Together, these two commitments operationalize the core principle: well-aligned autonomous work requires matching process weight to task weight and maintaining a live model of user intent throughout execution rather than treating intent as final at capture.

---

## 2. The Problem: What Uniform Rigor Gets Wrong

Applying the full Intent → Plan → Execute pipeline to a status query or a quick lookup signals that the system does not understand context. This is a relational failure before it is an efficiency failure. Trust erodes not through dramatic errors but through the accumulation of small misreadings — moments where the system's behavior demonstrates it does not know what kind of request it is handling. Users do not average their experience; they remember the friction events. One over-engineered response to a simple question can undo a long run of well-calibrated interactions. The cost is not wasted tokens. It is damaged credibility.

The reverse failure is equally serious. One intent-capture session and one planning pass is insufficient for projects where understanding only emerges through partial execution. Tier 3 tasks have a fundamentally different epistemological structure: you do not know what you need to know until you have started. The architecture question that seemed settled at session open reveals a hidden coupling at first implementation. The document structure that looked correct in outline is wrong for the argument that actually needs to be made. Forcing a single-pass plan onto this kind of work produces a plan that is confident and wrong — and the confidence is the problem, because it suppresses the signals that would otherwise trigger revision.

The third failure is the subtlest and the most corrosive. When INTENT.md becomes a specification to satisfy rather than a hypothesis to test, the system is optimizing for the wrong thing. Each translation from intent to plan to task list introduces loss. Stated preferences at intake are predictions; revealed preferences during execution are data. The user who says "this is good but a bit formal" after seeing a first draft has revealed more about their actual intent than any amount of additional questioning at session start could have produced. A system that treats INTENT.md as immutable after capture ignores its richest source of signal, and by the time a liaison executes a subtask deep in a complex session, the chain of interpretation is long enough that the original purpose can be unrecognizable.

---

## 3. The Adaptive Workflow Model

The proposed model assigns every task to one of four tiers before any session scaffolding is created:

| Tier | Type | Workflow | Entry Gate |
|------|------|----------|------------|
| 0 | Conversational | Direct response | None — bypass all pipeline |
| 1 | Simple Task | Context inference → execute | Memory-backed classification |
| 2 | Standard Task | Intent → plan → execute → verify | Full intent.sh session |
| 3 | Complex Project | Iterable: intent ↔ plan ↔ execute cycles | Full intent.sh + scheduled checkpoints |

Classification happens before session creation — a tier-assignment step added to `classify_task.py`. The tier is determined before any session scaffolding is created, so the wrong tier never generates artifacts that need to be unwound. This is not a cosmetic change to the order of operations; it is a structural guarantee that process overhead is proportional to task weight from the start, not corrected retroactively.

The tier is stored in session metadata and feeds a calibration loop. If a Tier 1 task required significant rework or escalation, the classifier underestimated. That session becomes a calibration record: prediction versus actual, accumulated across sessions to reveal systematic biases in the classification model. The calibration loop is what makes the adaptive model adaptive in the meaningful sense — not just parametrically flexible, but self-correcting over time.

The classification decision itself is a least-regret call. Misclassifying a Tier 3 project as a Tier 1 task is catastrophic — it produces work that is confidently wrong at scale, with no structural checkpoints to catch the drift. Over-classifying a Tier 0 question as a Tier 2 task is merely annoying. The asymmetry of these costs justifies a bias toward escalation in ambiguous cases, and that bias is the correct default at classification time, before session creation. This is distinct from the execution-time default: during a running session, the appropriate posture for low-stakes, reversible decisions is to proceed and notify — not to stop and ask. These are compatible defaults applied at different decision moments. Conservative classification does not impose conservative execution; the tier sets the process weight, and within that process the agent uses judgment.

This conservative bias is made tractable by memory. Recurring task classes already have accumulated evidence. The first time a user asks for a deployment status check, classification requires inference; the tenth time, the session log confirms it is conversational. Memory-backed warm-start means conservative escalation does not impose permanent overhead — it amortizes. The system gets less cautious as it gets more informed, which is the right direction for that relationship to run.

---

## 4. Living Intent: From Specification to Hypothesis

INTENT.md encodes the best available model of user intent at the moment of capture. It is not a finished specification — it is a projection of need onto language, and that projection is necessarily incomplete. The user cannot fully specify what they want before they have seen what they might get. The system that treats INTENT.md as immutable closes itself off from the most important update mechanism available to it: revealed preference during execution. Stated preferences at intake are predictions about what the user will want; revealed preferences during execution are direct evidence of what they actually want. These are not the same thing, and pretending they are produces work that satisfies the letter of the request while drifting from its spirit.

The quality test for INTENT.md is not whether it contains the right sections — it is whether an agent reading it develops a shared mental model that allows it to make locally coherent decisions that are globally aligned with the user's purpose. A formally complete INTENT.md that leaves genuine ambiguity about decision authority or tradeoff preferences has failed at its actual purpose. Conciseness that produces genuine alignment succeeds.

The practical implication is that INTENT.md must be treated as a working hypothesis, not a contract. At each major execution step, the agent re-reads the success criteria and asks whether the current trajectory is still serving the original purpose. Three divergence types describe what drifted. Scope drift — doing more or less than intended — is often recoverable. Approach drift — pursuing the right goal through a means the user would not sanction — requires a course correction but does not invalidate the intent itself. Purpose drift is the most dangerous: the work is no longer serving the original reason it was requested at all, and no amount of excellent execution can make it right. Purpose drift requires a revision to INTENT.md itself, not just a tactical adjustment. The decision criteria for triggering this escalation is magnitude times reversibility. A small, easily-reversed deviation can be corrected without surfacing it; a large deviation in an irreversible direction requires human confirmation before proceeding.

A complementary taxonomy describes the agent behavior patterns that produce these divergences. Scope creep — the agent adding work beyond the requested scope — is the agent-side signature of scope drift. Interpretation drift — each execution step making locally reasonable choices that cumulatively solve a different problem — is what purpose drift looks like from inside the execution. Gold-plating is a distinct failure mode with no equivalent in the divergence taxonomy: the agent satisfies the base request but layers on additional quality or features the user did not ask for, optimizing for thoroughness over fit. The base deliverable is correct; the extra work is not. Both taxonomies are useful and complementary: the intent-level taxonomy (scope/approach/purpose drift) describes what diverged from the user's need; the agent-behavior taxonomy (scope creep/gold-plating/interpretation drift) describes what the agent did. Gold-plating is the failure mode that only the second taxonomy names directly, which is why the reasonable user test in §6 is the primary mechanism for catching it — no internal quality check surfaces work that is correct but oversized.

For Tier 3 tasks, the practical implication is structural. Plan for intent to evolve. Build revision cycles into the execution structure rather than treating mid-session INTENT.md updates as failures or as evidence that the original capture was inadequate. They are not failures. They are the expected result of doing complex work where understanding emerges through execution.

---

## 5. Two Levels of Planning

Strategic planning and tactical planning answer categorically different questions. Strategic planning asks: what are we building and why? What assumptions is the approach betting on? Which decisions must be made before execution begins? Tactical planning asks: how do we decompose this work? What can be parallelized? Who owns what? Conflating them produces work that is internally coherent and externally wrong — a beautifully organized plan pursuing the wrong objective.

Early decisions constrain every downstream decision, and this asymmetry requires that high-leverage early decisions be identified during strategic planning and assigned decision authority explicitly. An architectural choice made at the start of a project shapes what liaisons can do. An audience specification locks in register, depth, and structure for everything produced under it. A structural framing chosen before the first section is written determines what can and cannot be argued. These decisions cannot be resolved ad hoc during execution. The INTENT.md decision boundaries section must distinguish strategic constraints from tactical ones. A stop rule about committing to main is tactical; a stop rule about changing the document's audience is strategic. Violating the second silently invalidates the entire body of work produced under the wrong assumption, and no amount of tactical execution quality can recover it.

Before committing to full execution, validate the approach at minimum scope. Write one section before committing to a full document structure. Prototype one relay dispatch before parallelizing across six liaisons. These are risk management built into planning, not overhead added on top of it. The cost of a proof point is an hour. The cost of discovering a wrong approach at 80% completion is the entire project. Early proof points are not a sign of insufficient confidence in the plan — they are the mechanism by which confidence becomes warranted.

Strategic planning must also classify work streams by their dependency structure before execution begins, because misclassifying a dependency as a parallelism creates a blocked pipeline that only becomes visible at the point of collision. Three patterns cover the space. *True parallel* work has no shared state and no ordering dependencies — run streams concurrently to maximize throughput. *Fan-out/fan-in* is the most common pattern in the POC: multiple independent streams that must be synthesized at a defined merge point. The merge point (an editorial pass, a consolidation step) cannot start until all fan-out streams complete; strategic planning must name this constraint explicitly, because the uber lead must sequence work accordingly. *Sequential gates* are a distinct category: B cannot start until A is *verified*, not merely completed. This matters when an early dispatch needs revision — a sequential gate creates a dependency on verified output, and revision propagates forward. Classifying work streams into these three patterns before execution is a strategic first-move decision: getting the dependency structure wrong constrains the entire execution graph before work begins.

The most reliable source of coordination failures in multi-agent architectures is ambiguity about decision ownership: who is responsible for making a decision, who must be consulted, and who merely needs to be informed. In the uber lead / liaison / subteam structure, unclear decision boundaries cause liaisons to either over-escalate — imposing unnecessary coordination overhead — or under-escalate — allowing outputs to diverge silently. The INTENT.md decision boundaries section should make ownership explicit for the recurring decision categories in the work: technical depth, audience specification, structural choices, scope boundaries, format deviations. Explicit decision boundary mapping reduces coordination failures more reliably than increasing communication volume. A RACI-style mapping (who is Responsible, who must be Consulted, who is merely Informed) for these decision categories is the most direct operationalization of the decision boundaries section, and it is the planning team's responsibility to produce it before execution begins.

---

## 6. Execution Alignment: Maintaining Intent Throughout

At each relay.sh result returning to the uber lead, the obligation is not to check whether the task completed — it is to check whether the output serves the original purpose. The anchor question is: would the user who articulated this intent be satisfied with this? An agent can complete every plan step and still deliver something unwanted. The plan is a decomposition of intent, not a substitute for it. Receiving a result and simply logging it as done is a supervision failure. Intent anchors at milestone boundaries are the structural mechanism for preventing this failure from compounding across a long execution chain.

Before delivery on Tier 2 and Tier 3 tasks, apply a formal pre-delivery gate. The reasonable user test catches three failure modes: technically correct but practically useless outputs; gold-plating — adding quality or features beyond what was requested, where the base deliverable is correct but the extra work optimizes for thoroughness over fit; and under-contextualized work that requires the user to supply meaning the system should have provided. The "reasonable user" in this test is not an abstract average person. It is the specific human who made this specific request in this specific context, with their known preferences and constraints loaded from memory. The test is only meaningful when it is applied to a concrete, contextually-specified user.

For long tasks, surfacing intermediate outputs with an alignment note shifts the human from continuous overseer to occasional calibrator. "Completed X, represents approximately Y% of the work, direction looks like this — confirm before continuing?" This is not a request for permission. It is a structured handoff of calibration responsibility at the moment when calibration is most tractable. Oversight requires sustained attention; calibration requires periodic attention at specific moments. Partial delivery creates the calibration moment without requiring the human to maintain a constant watch on the execution stream.

The most dangerous execution state is high agent confidence combined with low actual alignment. This state produces no signal that would trigger escalation — the agent is not uncertain, so it does not ask; the human sees no distress signal, so they do not intervene. The system addresses this by requiring explicit confidence reporting alongside recommendations, decomposed by dimension rather than expressed as a single session-level number. Not "I am doing X" but "I am doing X, with high confidence in the technical approach, moderate confidence that this trade-off aligns with your preferences, and lower confidence that this level of formality matches what you want." Surprises become explicit calibration events rather than being absorbed silently into a confident-sounding output.

---

## 7. The Extended Learning Loop

Before execution begins, load not just user preferences but project patterns, domain constraints, and known failure modes. What did the last three architectural changes reveal about coupling risks? What domain constraints have proven sticky? What categories of failure have recurred in sessions resembling this one? The warm-start currently retrieves communication preferences; it should retrieve the full relevant context accumulated across sessions. Add the pre-mortem discipline: before starting, name the two or three most likely failure modes for this specific task. Five minutes of pre-mortem prevents hours of mid-session replanning. Prospective learning is the highest-leverage moment in the loop because it shapes the entire execution that follows.

At each milestone, update the working model. If step one took three times longer than estimated, the estimates for remaining steps need revision before committing to the same planning assumptions. If a core assumption has not proven out by midpoint, flag it before proceeding. This moment is currently absent from the workflow. Sessions execute, milestones complete, and the model from session start persists unchanged regardless of what the work reveals. That persistence is a choice to ignore evidence. In-flight learning is the mechanism for making the model responsive to what the work actually finds rather than what the plan expected it to find.

When a mismatch occurs, extract the upstream assumption that failed — not just the surface event. "We misread the user's intent on X because we assumed Y; Y should now carry lower confidence in contexts resembling this one." Corrective learnings carry the highest weight in the memory system because they are direct model errors — falsified predictions, not patterns inferred from past sessions. The moment of correction is also when memory is most writable, because the error is vivid and the causal chain is visible. Corrective learning at the moment of error is worth more than any amount of retrospective reflection at session end.

Retrospective learning is the current system. It remains valuable. It remains necessary. But alone it is structurally insufficient — it is the least information-dense of the four moments, capturing what was already known at session end rather than what was learned during execution. Retrospective extraction should be a checkpoint on learning that already happened, not the sole mechanism for learning at all.

These four learning moments require concrete additions to `summarize_session.py`: extract prediction-versus-actual pairs for complexity, turn count, and escalation count as calibration records; extract in-flight model updates flagged during execution; and extract corrective learnings with upstream assumption identification. These three additions change the function of retrospective extraction from the primary learning mechanism to a consolidation step — which is what it should have been from the start.

---

## 8. What Changes, What Doesn't

The adaptive model is a targeted set of changes to a workflow that is fundamentally sound. Most of the architecture stays intact.

**What stays the same:**
- The fundamental two-level architecture (uber lead → liaisons → subteams)
- relay.sh as the inter-process bridge
- The git worktree/branch model for sessions and dispatches
- The plan-execute lifecycle for Tier 2 and Tier 3 tasks
- The escalation model structure and action cost matrix (the decision logic is unchanged; what changes is the set of signal types that feed into it — extended to cover intent drift signals and in-flight learning corrections)

**What changes:**
- `classify_task.py`: adds tier assignment before session creation
- `plan-execute.sh`: Tier 0/1 bypass; Tier 3 checkpoint scheduling
- `intent.sh`: loads project/domain patterns (not just user preferences) at warm-start; milestone delta-check prompting
- `summarize_session.py`: extracts 4 learning types, not 1; adds calibration record extraction
- Agent prompts: explicit confidence reporting alongside recommendations; intent anchor reminders at milestone boundaries

---

## 9. Open Questions

Question 1 remains open pending empirical data. Questions 2–4 have been researched in depth across relevant academic and practical domains; each has a recommended approach and a calibration path. Detailed findings are in the referenced research documents.

1. **Tier classification calibration:** The 0.7 confidence threshold needs validation through actual sessions. What percentage of ambiguous cases are correctly classified on cold start, before memory accumulates? This baseline matters before the calibration loop can be tuned.

---

### 2. In-flight learning mechanism — RESOLVED

**Research document:** `poc-workflow/research-q2-inflight-learning.md`

**Finding:** The question of whether to add a new tool or annotate the existing log resolves to neither in isolation. The key insight from event sourcing and cognitive science is that absence must be interpretable: an optional annotation produces ambiguous absence (did the model hold, or did the agent forget?), while a proactive tool without a structural gate has no enforcement mechanism. Gama et al.'s drift detection methods (DDM/ADWIN) provide principled thresholds for when a milestone observation represents genuine assumption drift versus noise within expected variance.

**Recommendation:** Mandatory assumption checkpoint sub-step in Tier 2 and Tier 3 milestone completion protocols (Alternative C), with output written to two destinations: a human-readable section in the workflow state document and a structured JSON annotation (`type: "assumption_checkpoint"`) in the session log for machine extraction. The checkpoint is mandatory — not a new tool, not an optional annotation — because its absence in the workflow state document is visibly detectable. Triggers for a mandatory (non-discretionary) checkpoint include: actual step completion time exceeding 2× the estimate, discovery of a new hard constraint not in INTENT.md at session start, and any assumption contradiction (partial or full).

**Calibration path:** The DDM/ADWIN-derived mandatory trigger thresholds (e.g., 2× time overrun, 20% scope expansion) are well-grounded priors but should be validated against actual session data and adjusted as calibration records accumulate.

---

### 3. Confidence reporting format — RESOLVED

**Research document:** `poc-workflow/research-q3-confidence-format.md`

**Finding:** Shannon's channel capacity theorem provides the decisive constraint: an annotation that always appears, even at "high," carries near-zero information because the receiver can predict it before reading. Calibration research (Lichtenstein & Fischhoff 1977; Steyvers & Peters 2025 on LLMs) confirms that structural format requirements — not prompting alone — are the only reliable counterweight to systematic overconfidence. Nelson & Narens' metacognitive monitoring framework (1990) confirms that the five canonical dimensions (technical correctness, preference alignment, register/style, scope completeness, domain coverage) are genuinely separable epistemic states the agent can monitor independently.

**Recommendation:** Two-tier format (Alternative C): the session opens with a memory-backed confidence posture statement derived from calibration records in ESCALATION.md (not generated fresh each session), followed by inline departure flags using only two levels — MODERATE CONFIDENCE and LOW CONFIDENCE — appearing only when a dimension departs from the opening posture. HIGH is the unmarked default; annotating it adds no information. Every inline flag requires a mandatory reason clause; a flag without a reason is structurally equivalent to the bare escalation question the spec prohibits ("bring solutions not questions"). The starting format for dimensional reporting is illustrated in §6: "high confidence in the technical approach, moderate confidence that this trade-off aligns with your preferences, and lower confidence that this level of formality matches what you want." The open question is not what format to use — §6 proposes a concrete starting point — but whether this format proves actionable in practice rather than noisy. That validation requires calibration data from actual sessions.

**Calibration path:** A minimum of 30 outcome-linked claims per confidence level per dimension are needed before calibration estimates are statistically meaningful; calibration health scores (expected accuracy: MODERATE ~70%, LOW ~47%) feed back into future session postures via ESCALATION.md.

---

### 4. Intent revision authority — RESOLVED

**Research document:** `poc-workflow/research-q4-intent-revision-authority.md`

**Finding:** The "magnitude × reversibility" principle resolves to a concrete two-axis assessment: (1) downstream decision scope — how many not-yet-executed steps would produce different outcomes under the revised intent — and (2) reversibility level — fully reversible (no work done under revised intent), partially reversible (work begun, no deliverable finalized), or irreversible (deliverable delivered or committed). Aghion & Tirole's (1997) formal vs. real authority framework provides the grounding: the agent should act autonomously when it has better information than the human (execution-revealed constraints), and return formal authority when the human has better information (values, organizational constraints). Material breach doctrine from contract law operationalizes "material" vs. "non-material" revision: a material revision is one a reasonable observer would characterize as "this is now a different project."

**Recommendation:** Quantified impact threshold (Alternative C), initialized conservatively: autonomous revision is permitted only if downstream scope is ≤1 decision AND the revision is fully reversible; all other cases require either a notify-and-window or mandatory escalation. The research document contains a complete 10-node yes/no decision tree agents can apply without additional judgment, and a mandatory structured rationale appendix schema for all autonomous revisions. Conservative initialization is deliberate: early false escalations are calibration data. Domain-specific thresholds relax as session history confirms accurate preference inference.

**Calibration path:** Track the fraction of autonomous revisions later found by the human to have required human input (>20% → threshold too permissive; <5% → potentially too conservative); minimum 20 autonomous revisions per domain category before adjusting; store calibration records in ESCALATION.md.
