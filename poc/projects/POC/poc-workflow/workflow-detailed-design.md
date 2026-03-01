# Adaptive Workflow Design: Enabling Well-Aligned Autonomous Work

## 1. Executive Summary

The current POC workflow is a strong foundation that optimizes for correctness through uniform rigor. Its weakness is that it applies the same process weight to every request regardless of task weight — the full Intent → Plan → Execute pipeline fires whether the request is a status query or a multi-week project. This creates two simultaneous failures: friction on simple requests that erodes trust, and insufficient structure for complex projects where understanding only emerges through partial execution. The proposed adaptive workflow model addresses both by classifying tasks into four tiers before session creation and adjusting process weight accordingly. The single most important principle governing this design is that well-aligned autonomous work requires matching process weight to task weight, maintaining a live model of user intent throughout execution rather than treating it as final at capture, and learning at four distinct moments — prospective, in-flight, corrective, and retrospective — not just one.

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

The classification decision itself is a least-regret call. Misclassifying a Tier 3 project as a Tier 1 task is catastrophic — it produces work that is confidently wrong at scale, with no structural checkpoints to catch the drift. Over-classifying a Tier 0 question as a Tier 2 task is merely annoying. The asymmetry of these costs justifies a bias toward escalation in ambiguous cases, and that bias is the correct default.

This conservative bias is made tractable by memory. Recurring task classes already have accumulated evidence. The first time a user asks for a deployment status check, classification requires inference; the tenth time, the session log confirms it is conversational. Memory-backed warm-start means conservative escalation does not impose permanent overhead — it amortizes. The system gets less cautious as it gets more informed, which is the right direction for that relationship to run.

---

## 4. Living Intent: From Specification to Hypothesis

INTENT.md encodes the best available model of user intent at the moment of capture. It is not a finished specification — it is a projection of need onto language, and that projection is necessarily incomplete. The user cannot fully specify what they want before they have seen what they might get. The system that treats INTENT.md as immutable closes itself off from the most important update mechanism available to it: revealed preference during execution. Stated preferences at intake are predictions about what the user will want; revealed preferences during execution are direct evidence of what they actually want. These are not the same thing, and pretending they are produces work that satisfies the letter of the request while drifting from its spirit.

The practical implication is that INTENT.md must be treated as a working hypothesis, not a contract. At each major execution step, the agent re-reads the success criteria and asks whether the current trajectory is still serving the original purpose. Three divergence types matter. Scope drift — doing more or less than intended — is often recoverable. Approach drift — pursuing the right goal through a means the user would not sanction — requires a course correction but does not invalidate the intent itself. Purpose drift is the most dangerous: the work is no longer serving the original reason it was requested at all, and no amount of excellent execution can make it right. Purpose drift requires a revision to INTENT.md itself, not just a tactical adjustment. The decision criteria for triggering this escalation is magnitude times reversibility. A small, easily-reversed deviation can be corrected without surfacing it; a large deviation in an irreversible direction requires human confirmation before proceeding.

For Tier 3 tasks, the practical implication is structural. Plan for intent to evolve. Build revision cycles into the execution structure rather than treating mid-session INTENT.md updates as failures or as evidence that the original capture was inadequate. They are not failures. They are the expected result of doing complex work where understanding emerges through execution.

---

## 5. Two Levels of Planning

Strategic planning and tactical planning answer categorically different questions. Strategic planning asks: what are we building and why? What assumptions is the approach betting on? Which decisions must be made before execution begins? Tactical planning asks: how do we decompose this work? What can be parallelized? Who owns what? Conflating them produces work that is internally coherent and externally wrong — a beautifully organized plan pursuing the wrong objective.

Early decisions constrain every downstream decision, and this asymmetry requires that high-leverage early decisions be identified during strategic planning and assigned decision authority explicitly. An architectural choice made at the start of a project shapes what liaisons can do. An audience specification locks in register, depth, and structure for everything produced under it. A structural framing chosen before the first section is written determines what can and cannot be argued. These decisions cannot be resolved ad hoc during execution. The INTENT.md decision boundaries section must distinguish strategic constraints from tactical ones. A stop rule about committing to main is tactical; a stop rule about changing the document's audience is strategic. Violating the second silently invalidates the entire body of work produced under the wrong assumption, and no amount of tactical execution quality can recover it.

Before committing to full execution, validate the approach at minimum scope. Write one section before committing to a full document structure. Prototype one relay dispatch before parallelizing across six liaisons. These are risk management built into planning, not overhead added on top of it. The cost of a proof point is an hour. The cost of discovering a wrong approach at 80% completion is the entire project. Early proof points are not a sign of insufficient confidence in the plan — they are the mechanism by which confidence becomes warranted.

---

## 6. Execution Alignment: Maintaining Intent Throughout

At each relay.sh result returning to the uber lead, the obligation is not to check whether the task completed — it is to check whether the output serves the original purpose. The anchor question is: would the user who articulated this intent be satisfied with this? An agent can complete every plan step and still deliver something unwanted. The plan is a decomposition of intent, not a substitute for it. Receiving a result and simply logging it as done is a supervision failure. Intent anchors at milestone boundaries are the structural mechanism for preventing this failure from compounding across a long execution chain.

Before delivery on Tier 2 and Tier 3 tasks, apply a formal pre-delivery gate. The reasonable user test catches three failure modes: technically correct but practically useless outputs; over-engineering — adding what was interesting rather than what was wanted; and under-contextualized work that requires the user to supply meaning the system should have provided. The "reasonable user" in this test is not an abstract average person. It is the specific human who made this specific request in this specific context, with their known preferences and constraints loaded from memory. The test is only meaningful when it is applied to a concrete, contextually-specified user.

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
- The escalation model and action cost matrix

**What changes:**
- `classify_task.py`: adds tier assignment before session creation
- `plan-execute.sh`: Tier 0/1 bypass; Tier 3 checkpoint scheduling
- `intent.sh`: loads project/domain patterns (not just user preferences) at warm-start; milestone delta-check prompting
- `summarize_session.py`: extracts 4 learning types, not 1; adds calibration record extraction
- Agent prompts: explicit confidence reporting alongside recommendations; intent anchor reminders at milestone boundaries

---

## 9. Open Questions

These are genuinely unresolved. The design is directionally correct; these questions must be answered through implementation and observation.

1. **Tier classification calibration:** The 0.7 confidence threshold needs validation through actual sessions. What percentage of ambiguous cases are correctly classified on cold start, before memory accumulates? This baseline matters before the calibration loop can be tuned.

2. **In-flight learning mechanism:** The spec has no current mechanism for flagging milestone model-updates into the session stream. Does this require a new tool, or can it be encoded as a structured annotation in the existing session log format?

3. **Confidence reporting format:** If agents are to report confidence decomposed by dimension, what format makes this useful rather than noisy? A domain-confidence pair per key claim — "technical approach: high; preference alignment: moderate; register: lower" — seems more actionable than a single session-level number, but the format needs to be specified in agent prompts before it can be applied consistently.

4. **Intent revision authority:** When should an agent revise INTENT.md mid-session versus escalate for human confirmation? The magnitude-times-reversibility criteria is directionally right but needs operationalization — concrete thresholds, not just a principle, so agents can apply it consistently across sessions and task types.
