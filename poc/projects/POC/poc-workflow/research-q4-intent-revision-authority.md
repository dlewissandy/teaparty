# Research Q4: Intent Revision Authority — When Should an Agent Revise INTENT.md Autonomously vs. Escalate?

**Status:** Research document resolving Open Question 4 from workflow-detailed-design.md Section 9
**Date:** 2026-03-01
**Session:** session/20260301-131335

---

## 1. Problem Statement

### The Open Question

From workflow-detailed-design.md, Section 9, Open Question 4:

> "When should an agent revise INTENT.md mid-session versus escalate for human confirmation? The magnitude-times-reversibility criteria is directionally right but needs operationalization — concrete thresholds, not just a principle, so agents can apply it consistently across sessions and task types."

### What Operationalization Means

A principle without thresholds fails in a specific and predictable way: agents will apply their own implicit thresholds, and those thresholds will vary across sessions, agents, and task types. The result is not random error — it is systematic inconsistency that produces two distinct failure modes simultaneously.

**False escalation** occurs when an agent stops execution to seek human confirmation for a revision that a well-calibrated system would handle autonomously. The cost is real and measurable: approximately 15 minutes of interruption for the human (context-switch cost plus response time plus agent re-orientation), plus flow loss for the session itself. Across a complex project with many minor tactical revisions, false escalation can consume more human attention than the oversight the system was designed to reduce. The human begins to treat escalations as noise, which degrades their response quality to the escalations that genuinely matter.

**False autonomy** occurs when an agent revises INTENT.md without escalating when it should have. The costs here are asymmetric and tier-dependent. In Tier 2 sessions, a false-autonomy revision typically costs 30–60 minutes of rework plus moderate trust damage. In Tier 3 sessions, it can cost hours of downstream rework, significant trust damage, and in severe cases a project restart. The asymmetry between false escalation cost (~15 minutes) and false autonomy cost (30 minutes to project restart) is the governing fact that determines where calibration should begin.

The magnitude-times-reversibility principle from living-intent.md ("magnitude of divergence multiplied by reversibility of the current path") is correct as a principle. The problem is that it does not specify what counts as large versus small magnitude, what counts as reversible versus irreversible, or how to combine the two when they point in different directions. Two agents applying this principle in good faith to the same revision will make different calls. That inconsistency is what this research resolves.

### The Divergence Taxonomy (from living-intent.md)

Living-intent.md identifies three divergence types that the intent delta check must catch. Each presents different authority challenges:

**Scope drift** (doing more or less than intended) tends to be the most visible and often the most recoverable. The agent can usually detect scope drift by comparing current work scope to the deliverable specified in INTENT.md's objective section. Authority challenge: scope reduction may look like efficiency but may actually mean the agent is dropping something the user considered essential. Scope expansion is the more common pattern and directly corresponds to the "scope creep" failure mode described in execution-alignment.md. Both directions require attention, but scope expansion carries higher autonomous-revision risk.

**Approach drift** (pursuing the right goal through a means the user would not sanction) requires an authority determination that depends heavily on whether the alternative approach is execution-revealed (the original approach hit a technical obstacle) or preference-inferred (the agent simply concluded a different approach would be better). The former may authorize autonomous revision; the latter requires more caution. Execution-alignment.md's "low-cost, reversible improvisation that serves intent" framing applies here: the reversibility and cost of the approach change determine the authority threshold.

**Purpose drift** (the work is no longer serving the original reason it was requested at all) is the most dangerous type because it is hardest to detect mid-execution and most expensive to correct late. Living-intent.md is explicit: purpose drift requires a revision to INTENT.md itself, not just a tactical adjustment. This is the one divergence type that almost always requires human confirmation, because the agent cannot reliably determine by itself whether the purpose has genuinely shifted or whether it is merely experiencing a local perspective on an intact global purpose.

### The Two Costs to Balance

| Cost Type | Tier 2 | Tier 3 |
|-----------|--------|--------|
| False escalation (escalated when autonomous was correct) | ~15 min interruption + context switch + minor flow loss | ~20 min interruption + larger context switch (complex session state) |
| False autonomy (autonomous when escalation was correct) | ~30–60 min rework + moderate trust damage | Potentially hours of rework + significant trust damage + possible project restart |

The asymmetry is highest in Tier 3. This asymmetry justifies conservative initialization of thresholds and a deliberate calibration mechanism that relaxes thresholds only as evidence accumulates.

---

## 2. Research Findings by Domain

### 2.1 Decision Theory — Minimax Regret

**Source:** Savage, L.J. (1951). "The Theory of Statistical Decision." *Journal of the American Statistical Association*, 46(253), 55–67.

**Core concept:** Minimax regret is a decision criterion that minimizes the maximum regret the decision-maker could experience across possible outcomes. Rather than maximizing expected value (which requires probability estimates the decision-maker may not reliably have), minimax regret identifies the choice that limits worst-case exposure. Regret is defined as the difference between the payoff of the chosen action and the payoff of the best available action in hindsight.

**Why minimax regret is the right framework for intent revision authority:**

An agent considering whether to revise INTENT.md autonomously does not know which decision is correct. It has a model of what the revision means and whether it would be sanctioned, but that model is precisely what is in question. Expected-value maximization fails here because the agent cannot reliably estimate the probability that its autonomous revision is correct — if it could, the revision authority question would not be difficult. What the agent can estimate is the bounds on regret:

- If it acts autonomously and the revision was correct: regret = 0
- If it acts autonomously and the revision was wrong: regret = rework cost + trust damage (large, tier-dependent)
- If it escalates and escalation was correct: regret = 0
- If it escalates and escalation was unnecessary: regret = interruption cost (~15 min equivalent)

The minimax move is the one that minimizes the worst of these regrets. When the rework cost of false autonomy exceeds the interruption cost of false escalation — which is true for any non-trivial revision — minimax regret favors escalation as the default. The only case where minimax regret favors autonomous action is when the worst-case regret of escalating (interruption cost) exceeds the worst-case regret of acting (rework cost), which occurs only for very small, very reversible revisions.

**The reversibility-and-organizational-impact matrix:**

The two-by-two matrix in task-tiers.md (reversibility x organizational impact) is a simplified regret matrix. It captures the two dimensions that most directly determine worst-case regret: reversibility governs recovery cost if the autonomous decision is wrong; organizational impact governs how broadly the wrong decision propagates before it is caught. The matrix's practical prescription — "irreversible action combined with external or cross-team impact maps to 'always escalate'" — is the minimax regret solution to the worst-cell combination.

**Calibration of cost estimates before empirical data accumulates:**

Before session data accumulates, the system must use normative cost estimates as priors. The following are recommended starting priors based on the workflow design context:

- Interruption cost (false escalation): 15 minutes of human time equivalent
- Minor rework cost (false autonomy, Tier 2, small downstream scope): 30 minutes
- Major rework cost (false autonomy, Tier 2, large downstream scope): 90 minutes
- Minor rework cost (false autonomy, Tier 3, small downstream scope): 60 minutes
- Major rework cost (false autonomy, Tier 3, large downstream scope): 4+ hours

These priors should be updated as session data accumulates. The calibration protocol in Section 10 specifies the update mechanism.

**Regret matrix for Tier 2 vs. Tier 3:**

| Scenario | Action | Tier 2 Regret | Tier 3 Regret |
|----------|--------|---------------|---------------|
| Revision correct, agent acts autonomously | Autonomous | 0 | 0 |
| Revision correct, agent escalates | Escalate | 15 min | 20 min |
| Revision wrong, agent acts autonomously | Autonomous | 30–90 min + trust | 60 min–4h+ + trust |
| Revision wrong, agent escalates | Escalate | 0 (human catches it) | 0 (human catches it) |

The maximum regret of autonomous action in Tier 3 (4h+ rework + significant trust damage) dominates all other cells. This is the decisive fact for Tier 3 conservative initialization. In Tier 2, the maximum regret ratio (autonomous wrong: 90 min vs. escalate unnecessary: 15 min) is 6:1, still favoring conservative thresholds.

### 2.2 Organizational Theory — Authority Delegation

**Source 1:** Aghion, P. & Tirole, J. (1997). "Formal and Real Authority in Organizations." *Journal of Political Economy*, 105(1), 1–29.

**Core concepts:** Formal authority is the right to make a decision — conferred by role, contract, or organizational structure. Real authority is the effective power to make a decision well — determined by who has the information necessary to make a good decision. These often diverge. A principal (human) may hold formal authority over a decision while an agent (AI or employee) holds real authority because the agent has direct access to the relevant information.

**Key finding:** The Aghion-Tirole framework establishes that formal authority should track real authority to the extent the principal can tolerate. When an agent has better information than the principal (higher real authority), delegating formal authority to the agent produces better decisions. When the principal has better information (higher real authority), retaining formal authority is correct. Misalignment between formal and real authority produces systematic errors: a principal exercising formal authority without real authority over-centralizes and makes poor decisions; an agent exercising real authority without formal authority under-reports information and acts without accountability.

**Application to INTENT.md revision:**

For each category of INTENT.md revision, the authority delegation decision reduces to an information-access assessment: who has better information for this decision?

**Agent has better information (real authority favors agent):**
- Execution-revealed technical constraints: the agent has just encountered a constraint that did not exist or was not visible at session start. The human cannot reliably evaluate this constraint without the agent's explanation of it, and the explanation itself will often be sufficient for the human to confirm the agent's proposed revision. In these cases, the agent's real authority is high — it has direct observational evidence the human lacks.
- Discovered technical limitations: a planned approach has proven infeasible due to technical factors the agent discovered during execution. The agent is in the best position to know what it discovered and to assess the range of alternatives.

**Human has better information (real authority favors human):**
- Value tradeoffs: decisions that depend on the human's preferences, values, or organizational constraints the agent cannot infer from the session history alone. The human holds this information internally and has not made it accessible to the agent.
- Unstated organizational constraints: rules, policies, or relationship considerations that affect what the "right" revision would be but that are not captured in INTENT.md or accessible from session context.
- Risk tolerance calibration: the human's actual tolerance for downstream risk from a revision cannot be reliably inferred by the agent, especially in early sessions before calibration history accumulates.

**Practical implication:** Before deciding on autonomous revision authority, the agent should explicitly ask: "Is the relevant information for this revision more accessible to me or to the human?" This assessment is not just a step in the decision process — it is the authorization logic itself. If the agent has decisively better information, autonomous revision with notification is justified. If the human has better information (or the information access is uncertain), escalation is correct.

**Source 2:** Simon, H.A. (1947). *Administrative Behavior: A Study of Decision-Making Processes in Administrative Organization.* Macmillan.

**Core concepts:** Simon's administrative behavior model introduces bounded rationality — decision-makers do not optimize; they satisfice within cognitive and informational limits. Administrative authority, in Simon's framework, is accepted by subordinates not because they are compelled but because they recognize the decision-making advantages of following a coordinated authority structure. Subordinates defer to authority when they lack the information or capacity to decide better themselves.

**Application:** Simon's bounded rationality principle implies that agents should default to escalation when their information for a decision is bounded or uncertain. The cognitive load of assessing "do I have sufficient information to make this revision correctly?" is itself bounded — the agent cannot fully assess its own informational limits. This provides a structural reason for conservative initialization: the agent's confidence in its own information access may be higher than is warranted, particularly before calibration history accumulates. The conservative initialization in the recommendation section compensates for this systematic over-confidence risk.

### 2.3 Software Engineering — Change Impact Analysis

**Source 1:** Lehnert, M. (2002). "A Review of Software Change Impact Analysis." Weimar, Germany: Technical Report.

**Core concepts:** Change impact analysis distinguishes direct impact (components immediately affected by a change) from indirect or downstream impact (components not immediately affected but reached through dependency chains). The key insight is that small, localized changes can have large downstream footprints when dependency chains are long. Magnitude of a change cannot be assessed from the size of the change itself — it must be assessed from the breadth of downstream decisions the change governs.

**Application to INTENT.md revision:** A one-sentence revision to INTENT.md can have downstream impact across the entire remaining workflow if that sentence governs a quality criterion applied at every execution step. Conversely, a paragraph-length revision that is self-contained and affects only one optional deliverable may have minimal downstream impact despite its size. Agents assessing revision magnitude must evaluate downstream decision scope, not text change volume.

This directly informs the operationalized definition of magnitude in Section 4.3: magnitude is measured in downstream decisions governed, not in words changed.

**Source 2:** Baldwin, C.Y. & Clark, K.B. (2000). *Design Rules: The Power of Modularity.* MIT Press.

**Core concepts:** Baldwin and Clark distinguish architecturally load-bearing design elements from non-load-bearing elements. Load-bearing elements are those that govern or constrain downstream decisions throughout the system — changing them requires propagating changes through everything that depends on them. Non-load-bearing elements are local; changing them affects only their immediate context.

**Application to INTENT.md sections:**

The sections of INTENT.md have different architectural weights:

- **Objective section:** Architecturally load-bearing. Every execution decision implicitly derives from the objective. If the objective changes, every quality judgment throughout the remaining workflow changes, because "good" is defined relative to the objective.
- **Success criteria section:** Architecturally load-bearing. Success criteria govern every quality assessment throughout execution — they are the evaluation standard applied at every milestone and delivery gate. A revision to success criteria changes what "acceptable" means for all subsequent outputs.
- **Decision boundaries section:** Partially load-bearing. Decision boundaries constrain the agent's authority throughout execution. Expansion of decision boundaries (agent authorized to decide more) is load-bearing upward — it enables autonomous action that would otherwise require escalation. Narrowing is load-bearing downward — it constrains authority that was previously assumed.
- **Constraints section:** Variably load-bearing. Hard constraints (budget, technology, scope limits) are load-bearing because they govern feasibility assessments throughout execution. Soft constraints (preferences, stylistic guidance) are less load-bearing because they affect individual outputs without governing the overall feasibility structure.
- **Open questions section:** Non-load-bearing. Marking an open question as resolved is a local action that closes an uncertainty rather than opening new ones.

This architectural weight analysis produces the authority classification in Section 3.

### 2.4 Law — Material Breach Doctrine

**Source:** Common law contract doctrine, developed across centuries of English and American case law. Key formulations include the Restatement (Second) of Contracts section 241 (1981) and Cardozo's analysis in *Jacob & Youngs v. Kent* (1921).

**Core concepts:** The material breach doctrine distinguishes material breach from non-material (partial) breach. A material breach "goes to the root of the contract" — it defeats the fundamental purpose the parties intended when entering the agreement, and it justifies the non-breaching party in treating the contract as discharged. A non-material breach causes some harm or deviation but does not defeat the fundamental purpose — it entitles the non-breaching party to damages but does not justify treating the contract as discharged.

**Why this doctrine is the right analogy:** The material breach doctrine was developed specifically to solve the operationalization problem the open question addresses: when does a deviation require the other party's consent? The doctrine's answer has been refined by centuries of application to contested cases. It provides both a principle (root of the contract) and an application framework (what "root" means concretely for different contract types and deviations).

**Applied to INTENT.md revision:**

A material INTENT.md revision is one where a reasonable observer would say: "This is now a different project." Specifically, a revision is material when it changes:
- The primary deliverable (what is being produced)
- The purpose the deliverable serves (why it is being produced)
- The primary decision authority structure (who can sanction what)

A non-material INTENT.md revision adjusts implementation details while preserving the fundamental purpose. The test: would the human who articulated the original intent recognize the post-revision INTENT.md as pursuing the same goal through adjusted means? If yes, non-material. If the human would say "this is not what I asked for," material.

**Analysis of INTENT.md sections through the material breach lens:**

- **Objective section:** Any revision risks materiality. The objective is the "root" of the intent contract. A reasonable observer test for objective revisions: does the revised objective pursue the same fundamental purpose as the original? Even modest objective changes can be material if they redirect the fundamental purpose.
- **Success criteria section:** Redefinition of primary success criteria is material (it changes what "done" means); clarification of how existing criteria are measured is non-material (it adjusts implementation without changing the standard). The line: would the original success criteria still be satisfied by the output if the revision had not been made?
- **Decision boundaries section:** Expansion of agent authority is material (the human granted less than is now being taken); contraction is non-material (the agent is taking on less than the human authorized, not more). The asymmetry reflects the underlying asymmetry in the authority relationship.
- **Constraints section:** Addition of a new hard constraint that rules out an approach the human already sanctioned is material. Refinement of how an existing constraint is implemented is non-material.
- **Open questions section:** Resolution is never material — it closes an uncertainty in a direction the human explicitly left open for resolution.

### 2.5 Cognitive Science — Threshold Perception

**Source 1:** Weber, E.H. (1834). *De Pulsu, Resorptione, Auditu et Tactu.* Koehler; Fechner, G.T. (1860). *Elemente der Psychophysik.* Breitkopf und Hartel.

**Core concepts:** The Weber-Fechner Law establishes that the just-noticeable difference (JND) between stimuli is a constant proportion of the existing stimulus magnitude, not an absolute value. A 1-gram difference is detectable when holding a 10-gram weight but not when holding a 100-gram weight. Perception of change is proportional to baseline, not absolute.

**Application to magnitude thresholds:**

A 10% scope change is much more noticeable — and more disruptive — when the project has 5 remaining steps than when it has 50 remaining steps. Absolute thresholds for autonomous revision authority will systematically over-escalate on large projects (where small absolute changes are proportionally minor) and under-escalate on small projects (where small absolute changes are proportionally large). Magnitude thresholds must be proportional to current project scope.

This is the theoretical basis for the proportional threshold specification in Section 4.3: "large" revision is defined as more than 30% of remaining workflow steps governed by the revision, not as more than N steps in absolute terms.

The Weber-Fechner insight also implies that threshold calibration should be domain- and scale-specific. A threshold calibrated on large Tier 3 projects may be systematically too permissive when applied to Tier 2 projects. The calibration protocol (Section 10) should track project scope alongside revision data.

**Source 2:** Kahneman, D. (2011). *Thinking, Fast and Slow.* Farrar, Straus and Giroux.

**Core concepts:** Kahneman's dual-process theory distinguishes System 1 processing (fast, automatic, intuitive, heuristic-based) from System 2 processing (slow, deliberate, effortful, rule-following). Humans automatically apply one or the other depending on the cognitive demands of the stimulus.

**Application to INTENT.md section authority:**

Changes to different INTENT.md sections make different cognitive demands on the human reviewing them:

- **Objective section:** Changes here require System 2 processing to recognize as significant. The connection between an objective-level revision and its downstream implications is non-obvious and non-automatic. Humans cannot evaluate objective changes by intuition alone — the implications only emerge with deliberate analysis. This is a structural reason why objective section revisions must always be surfaced to the human: even if the human could confirm quickly, they cannot confirm correctly without deliberate attention that the system cannot guarantee they will apply to an asynchronous notification.

- **Constraints section:** Changes to hard constraints also require System 2 processing — the implications of adding or removing a constraint may not be immediately visible. Soft constraint changes may be evaluable through System 1 if presented with clear framing ("I adjusted the tone constraint from X to Y based on discovered platform standard").

- **Open questions section:** Resolution of open questions involves local, bounded information that is System-1 processable by the human if the resolution context is presented clearly. The human can confirm "yes, that's the right call" without requiring deliberate analysis.

This cognitive processing distinction provides a second, independent basis for the authority matrix in Section 3, consistent with but separate from the architectural weight analysis.

### 2.6 Risk Management — Probability-Impact Matrices

**Source:** Project Management Institute (2017). *A Guide to the Project Management Body of Knowledge (PMBOK Guide), 6th Edition.* Project Management Institute.

**Core concepts:** The PMBOK probability-impact matrix is a risk assessment tool that classifies risks by their probability of occurrence and their impact if they occur. It produces a risk score used to prioritize risk responses. The framework distinguishes risk appetite (the general attitude toward taking risks, which can vary by category), risk tolerance (the acceptable level of variation in a specific risk category, calibratable over time), and risk threshold (the specific level at which a risk must be formally escalated, regardless of appetite — a non-negotiable hard limit).

**Application to intent revision authority:**

The agent, within the revision authority framework, has:

- **Risk appetite:** The agent's general posture toward autonomous revision. Conservative initialization (as recommended) means low risk appetite — the agent will accept some false escalation costs to avoid false autonomy costs. As calibration history accumulates and the agent demonstrates reliable judgment, risk appetite can expand in specific domains where the evidence supports it.

- **Risk tolerance (domain-specific, calibratable):** Within the conservative posture, different revision categories have different tolerance levels. Open question resolution has high tolerance (autonomous action almost always correct). Objective section revision has essentially zero tolerance (autonomous action almost never appropriate). The domain calibration records in ESCALATION.md track how tolerance should shift per domain as session data accumulates.

- **Risk threshold (non-negotiable hard limit):** The hard threshold above which execution stops regardless of confidence or risk appetite. This applies to: objective section changes (always), irreversible revisions with downstream scope greater than 2 decisions (always), and any revision where the material breach test is clearly satisfied. These are the cases where the asymmetry of false-autonomy cost is so extreme that no confidence level justifies autonomous action.

The PMBOK distinction between tolerance (calibratable) and threshold (non-negotiable) maps directly onto the two-tier structure of the decision tree in Section 8: the threshold generates the mandatory escalation branches; the tolerance calibration generates the boundary between autonomous and notify+window.

---

## 3. INTENT.md Section Authority Analysis

For each section, this analysis applies four lenses from the research synthesis:
1. Architectural weight (Baldwin & Clark): load-bearing vs. non-load-bearing
2. Information access (Aghion & Tirole): agent or human has better information?
3. Material breach threshold: what revision would be material?
4. Cognitive processing (Kahneman): System 1 or System 2 required to evaluate?

### 3.1 Objective Section

**Architectural weight:** Fully load-bearing. The objective governs every quality judgment throughout execution. Every decision about what to include, what depth to pursue, what tradeoffs to accept, implicitly derives from the objective. A changed objective changes the implicit governing standard for all prior and subsequent work.

**Information access:** Human has decisively better information. The objective encodes the human's fundamental purpose — why they made this request at all. The agent can observe what the objective says, but only the human knows whether a proposed revision still serves the underlying need. The agent cannot reliably infer from execution-revealed evidence what the human's underlying purpose is; they stated it at session start, and any revision to it requires their input to verify it still serves what they actually need.

**Material breach threshold:** Almost any revision to the objective is material. Even modest restatements can change what counts as success in ways that defeat the original purpose. The only non-material objective change is purely stylistic restatement of identical content (same goal, same scope, clearer language). This is a correction, not a revision, and requires no authority escalation.

**Cognitive processing required:** System 2. The downstream implications of objective changes are not intuitively apparent without deliberate analysis.

**Authority classification: MANDATORY ESCALATION for any substantive change.** Exception: purely stylistic restatement that preserves identical scope and goal is autonomous (no content change occurred).

### 3.2 Success Criteria Section

**Architectural weight:** Fully load-bearing. Success criteria are the evaluation standard applied at every milestone and delivery gate. Every intermediate quality judgment — is this draft good enough to proceed? does this output meet the bar? — is made against the success criteria. Revising them changes what "acceptable" means for all subsequent outputs.

**Information access:** Mixed. For clarification of how to measure existing criteria (e.g., "word count limit" is ambiguous — does it mean words, characters, or sentences?), the agent's execution context may provide better information than the human's recollection at session start. For redefinition of what the criteria are, the human has better information — they know whether the revised criteria still capture what they actually care about.

**Material breach threshold:** Redefinition of criteria (changing what is evaluated) is material. Clarification of how criteria are measured (making the evaluation method more precise without changing the standard) is non-material. Test: would outputs that satisfied the original criteria automatically satisfy the revised criteria? If yes, non-material (the bar has not moved). If no, material (the bar has changed).

**Cognitive processing required:** System 2 for redefinition; System 1 may be sufficient for minor clarification if presented with clear framing showing before/after.

**Authority classification: MANDATORY ESCALATION for redefinition; AUTONOMOUS (with rationale appendix) for minor clarification where scope change is at or below 25% of the criterion's measurement range.** The 25% threshold is the conservative starting prior for this section's tolerance zone; it should be calibrated per domain. Example: "success criterion specifies maximum 1,000 words" — autonomous clarification to 1,200 words (20% increase) if execution reveals the content requires it and the agent can document the execution-revealed constraint. Mandatory escalation to redefine criterion from "accuracy-optimized" to "engagement-optimized."

### 3.3 Decision Boundaries Section

**Architectural weight:** Partially load-bearing. Decision boundaries constrain authority throughout execution — they determine what the agent can do without returning to the human. Changes have asymmetric architectural weight: expansion (agent takes on more authority) is highly load-bearing because it enables autonomous action the human has not explicitly sanctioned; contraction (agent takes on less authority) is minimally load-bearing because it restricts the agent's own scope.

**Information access:** Asymmetric by direction. For contraction (narrowing agent authority): agent has better information — the agent has discovered that an element of its authorized scope exceeds its competence or creates unacceptable risks. For expansion (widening agent authority): human has better information — whether additional autonomous authority is appropriate depends on trust calibration and organizational constraints the human holds.

**Material breach threshold:** Expansion of agent authority is material (the human granted less than the agent is now claiming). Contraction is non-material (the agent is restricting itself, which is conservative). The asymmetry is fundamental to the authority relationship.

**Cognitive processing required:** System 2 for expansion review; System 1 for contraction notification.

**Authority classification: MANDATORY ESCALATION for expansion; AUTONOMOUS (with rationale appendix) for contraction.** Rationale: the material breach test is cleanly satisfied by expansion (the agent is taking authority it was not granted) and cleanly not satisfied by contraction (the agent is giving up authority it was granted, which cannot violate the intent of the original grant).

### 3.4 Constraints Section

**Architectural weight:** Variable. Hard constraints (budget, technology selection, scope limits, compliance requirements) are architecturally load-bearing because they govern feasibility assessments throughout execution. Soft constraints (tonal preferences, stylistic guidance, formatting preferences) are non-load-bearing because they affect individual outputs without governing the overall structure.

**Information access:** Context-dependent. For execution-revealed constraints (the agent discovered a constraint not known at session start — e.g., a dependency limitation, a platform restriction), the agent has better information. For preference-inferred constraints (the agent is estimating that the human would want a constraint added based on partial signals), the human has better information.

**Material breach threshold:** Adding a new hard constraint is material if it rules out an approach the human already sanctioned (the plan was built around an approach that the new constraint forecloses). Adjusting how an existing soft constraint is implemented is non-material.

**Cognitive processing required:** System 2 for hard constraint changes; System 1 for soft constraint adjustments if framing is clear.

**Authority classification:**
- Hard constraint addition: MANDATORY ESCALATION if it forecloses a sanctioned approach; NOTIFY+WINDOW if it is additive (creates new restriction without foreclosing existing plan)
- Hard constraint removal: NOTIFY+WINDOW (removes a restriction the human set — may be appropriate given execution context but requires awareness)
- Soft constraint adjustment: AUTONOMOUS (with rationale appendix) if execution-revealed; NOTIFY+WINDOW if preference-inferred

### 3.5 Open Questions Section

**Architectural weight:** Non-load-bearing. Open questions are explicitly flagged as unresolved at session start — their resolution closes uncertainty rather than opening new dependencies. The human placed them in INTENT.md precisely because they expected them to be resolved during execution.

**Information access:** Agent typically has better information. Open questions are often resolved through execution-revealed evidence (the approach that the open question was about has now been attempted and the answer is clear). The agent has direct observational access to this evidence.

**Material breach threshold:** Resolution of an open question is almost never material — it closes a known uncertainty in a direction the human explicitly left open. The only exception: if an open question resolution effectively redefines the objective or primary success criteria (rare, but possible if the open question was about fundamental scope or purpose).

**Cognitive processing required:** System 1 if resolution is presented with clear before/after framing.

**Authority classification: AUTONOMOUS (with rationale appendix) for resolution.** Exception: if resolution effectively changes the objective or success criteria, apply the authority rule for that section instead.

### Authority Summary Table

| Section | Load-Bearing? | Better Info: Agent or Human? | Material Breach Trigger | Authority Classification |
|---------|--------------|------------------------------|------------------------|-------------------------|
| Objective | Fully | Human (always) | Almost any substantive change | MANDATORY ESCALATION |
| Success criteria | Fully | Mixed (depends on revision type) | Redefinition (standard changes) | ESCALATE for redefinition; AUTONOMOUS for minor clarification (at or below 25% measurement range) |
| Decision boundaries | Partially | Asymmetric by direction | Expansion of agent authority | ESCALATE for expansion; AUTONOMOUS for contraction |
| Constraints (hard) | Fully | Context-dependent | New constraint forecloses sanctioned approach | ESCALATE if forecloses plan; NOTIFY+WINDOW if additive; NOTIFY+WINDOW for removal |
| Constraints (soft) | Non | Agent if execution-revealed; human if inferred | Rarely | AUTONOMOUS if execution-revealed; NOTIFY+WINDOW if inferred |
| Open questions | Non | Agent (typically) | Rarely (only if implies objective change) | AUTONOMOUS (with rationale) |

---

## 4. Operationalizing Key Concepts

### 4.1 Reversibility — Three Levels

Reversibility for INTENT.md revisions is defined by whether work completed under the prior intent would need to be redone if the revision is found to be incorrect. This is distinct from reversibility of the revision itself (which is trivially reversible — text can always be changed back). The relevant question is: what is the cost to the session if this revision turns out to be wrong?

**Fully reversible:** No work has been completed under the revised intent yet. The revision changes the governing standard before any work is done against it. If the revision is later found incorrect, execution simply proceeds against the corrected standard with no rework cost.

Examples:
1. The agent is about to begin the first major execution step of the session and realizes the success criteria need clarification — no work has been done against the current criteria yet.
2. A constraint revision is identified at the start of a sub-task before any sub-task execution has begun.

Authority implications: Fully reversible revisions are the safest category for autonomous action. The worst-case outcome of a wrong autonomous revision is that execution proceeds briefly before the error is caught — no completed work is discarded.

**Partially reversible:** Work has begun under the revised intent but no deliverable has been finalized or handed off to the human or committed to the session log as complete. Rollback is possible but requires rework of in-progress work.

Examples:
1. The agent has drafted three of five sections of a document under the revised success criteria; the draft sections are still in progress and have not been surfaced to the human.
2. An approach revision has been made mid-execution; several tactical decisions have been made under the revised approach, but no output has been delivered.

Authority implications: Partially reversible revisions carry moderate risk. Wrong autonomous revision costs the rework of in-progress (not yet finalized) work. Escalation is more conservative but appropriate for any revision with non-trivial downstream scope.

**Irreversible:** A deliverable based on the revised intent has been delivered to the human or committed to the session log as complete. Rollback requires a human decision and potentially a session restart or significant rework of finalized outputs.

Examples:
1. The agent revised the success criteria, produced outputs under the new criteria, delivered them to the human, and the human is now acting on them — discovering the revision was wrong means the delivered outputs are based on wrong criteria.
2. A scope revision was made, sub-tasks were completed and committed as done under the revised scope, and the session has moved on — the committed work cannot be silently rolled back.

Authority implications: Irreversible revisions require the most conservative authority thresholds. The cost of a wrong autonomous revision is highest here because finalized work must be re-examined and potentially re-done with human involvement.

### 4.2 Downstream Decision Scope — Operational Definition

**Definition:** A remaining workflow step is "governed by" a revision if:
(a) the step has not yet been executed AND
(b) the outcome of that step would differ depending on whether the revision is in effect

**Criteria for (b):** A step's outcome differs under the revision if the step's quality criterion, approach selection, or scope is determined by the revised element. Steps that are fully self-contained and derive their quality standard from domain norms rather than from the INTENT.md element being revised are not downstream-governed.

**Worked examples:**

**Example 1 — Success Criteria Revision (Accuracy to Shareability):**
Session involves curating and scoring 20 research items to produce a ranked list. The agent is considering revising the success criteria from "optimize for accuracy" to "optimize for shareability." The agent has completed 5 items. 15 items remain.

Downstream-governed steps: All 15 remaining items involve a quality judgment (score and rank). Each judgment would produce a different outcome depending on whether accuracy or shareability is the criterion. Downstream decision scope = 15.

Additionally, a final compilation and ranking step will produce different output depending on which criterion governed the individual scores. Downstream decision scope = 16.

This revision governs more than 10 remaining decisions — under the conservative initialization, this requires at minimum NOTIFY+WINDOW and likely MANDATORY ESCALATION given the fundamental nature of the criteria change (redefinition, not clarification).

**Example 2 — Approach Revision (Document Structure):**
Session involves writing a technical report. The agent has completed the introduction and is about to begin body sections. The agent is considering revising the approach from a problem-solution structure to a chronological narrative structure. The report has 8 remaining sections.

Downstream-governed steps: All 8 remaining sections would be drafted differently depending on which structure is in effect. Additionally, the introduction already written would require revision for consistency. Downstream decision scope = 8 remaining sections + 1 revision = 9.

This is an approach drift revision. The downstream scope (9) exceeds the fully-reversible autonomous threshold (at or below 10) but only barely, and it is partially reversible (introduction was completed but not delivered). Under conservative initialization, this is NOTIFY+WINDOW territory.

**Example 3 — Constraint Clarification (Soft Constraint):**
Session involves producing a social media content calendar. The constraints section specifies "maintain brand voice." The agent is mid-execution and has discovered that the client's style guide defines brand voice specifically as "direct and concise, avoiding hedging language." The agent is considering adding this specificity as a clarification to the constraints section. 12 posts remain to be written.

Downstream-governed steps: All 12 remaining posts would apply this specific guidance. However, the constraint was not changed (brand voice is still required); only the implementation definition was clarified. This is an execution-revealed constraint (agent discovered the style guide existed and defines the term specifically) not a preference inference.

Under the authority matrix: soft constraint, execution-revealed — AUTONOMOUS. The downstream scope (12) is large, but the nature of the revision (clarification, not redefinition; execution-revealed, not inferred) keeps it in the autonomous zone under the constraints section authority rule. The rationale appendix must document: the style guide discovery, the specific language found, and the downstream posts affected.

### 4.3 Magnitude — Proportional Threshold (Weber-Fechner Applied)

Magnitude thresholds are proportional to remaining workflow scope, not absolute.

**Large revision:** The revision changes the governing rule for more than 30% of remaining workflow steps.

Example: 20 steps remain; the revision governs more than 6 of them. The 30% threshold is the conservative starting prior — empirical calibration may adjust it per domain.

**Small revision:** The revision changes the governing rule for fewer than 10% of remaining steps.

Example: 20 steps remain; the revision governs fewer than 2 of them.

**Boundary zone (10 to 30%):** Apply the section-based authority matrix from Section 3 as the tiebreaker. If the affected section's authority classification is AUTONOMOUS, boundary-zone revisions proceed autonomously with rationale appendix. If the section is NOTIFY+WINDOW, boundary-zone revisions use NOTIFY+WINDOW. If the section is MANDATORY ESCALATION, boundary-zone revisions escalate.

**Calibration note:** These percentage thresholds (30% / 10%) are starting priors derived from the Weber-Fechner proportionality principle. They should be updated using the calibration protocol in Section 10 as session data accumulates. Domain-specific calibration is expected — the right threshold for content-production sessions may differ from the right threshold for technical implementation sessions.

**Minimum step floor:** To prevent the proportional threshold from generating perverse results when remaining steps are very small (e.g., 1 remaining step where 30% = 0.3 steps), the following floor applies: if fewer than 5 steps remain, treat "large" as any revision governing 2 or more steps and "small" as governing 0 steps. This floor prevents the Weber-Fechner scaling from producing zero-threshold situations.

---

## 5. Three Alternatives

### Alternative A: Section-Based Authority Matrix

**Description:** Map each INTENT.md section to a fixed authority level. Agents consult a lookup table without exercising additional judgment. The authority level is determined entirely by which section is being revised.

**Section authority rules:**
- Objective: MANDATORY ESCALATION for any revision
- Success criteria: MANDATORY ESCALATION for redefinition; AUTONOMOUS for minor clarification (at or below 25% measurement range change)
- Decision boundaries: MANDATORY ESCALATION for expansion; AUTONOMOUS for contraction
- Constraints (hard): MANDATORY ESCALATION if forecloses sanctioned approach; NOTIFY+WINDOW otherwise
- Constraints (soft): AUTONOMOUS (execution-revealed) or NOTIFY+WINDOW (inferred)
- Open questions: AUTONOMOUS (resolution only)

**Advantages:**
- Highly consistent: the same revision to the same section always gets the same authority classification regardless of context.
- Low cognitive load: no judgment required beyond identifying which section is affected.
- Fully auditable: every authority decision can be traced to a section-rule mapping.
- Resistant to motivated reasoning: no room to rationalize a preferred autonomous action.

**Disadvantages:**
- Within-section variation is not captured. A minor clarification of success criteria (adjusting word count limit by 5%) gets the same treatment as a fundamental redefinition (changing from accuracy optimization to shareability optimization). The clarification note above ("at or below 25%") is itself a judgment call that re-introduces the within-section problem.
- Rigid: the authority level for a section does not adjust based on how much of the session remains, how much work has been done, or how reversible the revision is.
- False escalation risk is high for load-bearing sections: any success criteria revision triggers at minimum NOTIFY+WINDOW regardless of its actual downstream impact.

**Failure mode:** Frequent false escalations for minor within-section clarifications. In sessions with many small, execution-revealed clarifications (common in Tier 3 iterative work), this produces excessive interruption overhead.

### Alternative B: Causal Attribution Rule

**Description:** Authority decision is based entirely on the cause of the revision. The same revision may be handled differently depending on whether the agent identifies it as execution-revealed, preference-inferred, or externally triggered.

**Causal categories:**
- Execution-revealed constraint (agent discovered technical limitation not known at session start) — AUTONOMOUS
- Preference inference (agent updating intent model based on estimated user reaction) — MANDATORY ESCALATION
- External information (dependency changed, constraint lifted by external event) — NOTIFY+WINDOW (brief confirmation window)

**Rationale:** Directly applies the Aghion-Tirole real authority principle. The agent acts autonomously when it has demonstrably better information (execution discovery); escalates when the human has better information (value/preference judgments).

**Advantages:**
- Captures the real authority intuition directly: authority follows information access.
- Distinguishes the genuinely important difference between discovery (agent has evidence) and inference (agent is guessing).
- Theoretically coherent: maps cleanly to the research foundation.

**Disadvantages:**
- Causal attribution itself can be uncertain. The agent may misidentify a preference inference as a technical discovery. The rationalization risk is significant: "I discovered that the user would prefer X" blurs the line between discovery and inference.
- Hard to audit: causal categories are inherently interpretive; two auditors reviewing the same revision record may classify it differently.
- No quantifiable threshold: produces binary (autonomous vs. escalate) classifications without a middle tier that would accommodate partially reversible, moderate-scope revisions.

**Failure mode:** Systematic misattribution of preference inferences as execution-revealed discoveries. Because preference inferences feel experientially similar to discoveries (both involve the agent updating its model), the agent may consistently classify inferences as discoveries and proceed autonomously when it should escalate. This failure mode is particularly hard to detect retrospectively because the rationale records will accurately describe the agent's (incorrect) causal attribution.

### Alternative C: Quantified Impact Threshold with Mandatory Rationale

**Description:** Revisions are assessed on two axes simultaneously — downstream decision scope and reversibility level. Authority classification follows from the combination of these two measurements, with specific numeric thresholds.

**Proposed thresholds:**

| Reversibility | Downstream Scope at or below 2 | Downstream Scope 3 to 5 | Downstream Scope above 5 |
|--------------|------------------------------|------------------------|------------------------|
| Fully reversible | AUTONOMOUS | AUTONOMOUS | NOTIFY+WINDOW |
| Partially reversible | AUTONOMOUS | NOTIFY+WINDOW | MANDATORY ESCALATION |
| Irreversible | NOTIFY+WINDOW | MANDATORY ESCALATION | MANDATORY ESCALATION |

All AUTONOMOUS revisions MUST append a structured revision record (the rationale appendix defined in Section 9) before proceeding. All NOTIFY+WINDOW revisions append a note to the session log and allow 30 minutes for human response before proceeding.

**Advantages:**
- Quantifiable thresholds that produce measurable data for calibration.
- Calibratable over time: the numeric thresholds (2, 5) can be adjusted per domain as session data accumulates.
- Handles within-section variation: the same section can receive different authority classifications depending on the specific revision's actual downstream scope.
- Auditable: downstream scope estimate and reversibility level are explicit and reviewable.
- Full three-tier output: produces autonomous, notify, and escalate classifications rather than a binary.

**Disadvantages:**
- Agents must estimate downstream decision scope, which is not trivial for complex sessions with long dependency chains. The estimate itself introduces error.
- Thresholds may need tuning before they are well-calibrated, and the tuning process requires sufficient data (20 or more revisions per domain per Section 10 before adjustment is statistically reliable).
- Does not directly encode the section-based authority matrix, which captures important information about whether the human or agent has better information for the revision category.

---

## 6. Comparative Analysis Table

| Dimension | Alt A (Section Matrix) | Alt B (Causal Attribution) | Alt C (Impact Threshold) |
|-----------|----------------------|--------------------------|------------------------|
| Consistency | High — same section, same rule | Low — depends on agent's causal interpretation | Medium — same axes, but scope estimates vary |
| Auditable | High — traceable to section rule | Low — causal categories are interpretive | High — numeric thresholds, explicit estimates |
| Cognitive load | Low — lookup table | Medium — requires causal analysis | Medium — requires scope estimation |
| Handles within-section variation | No — all revisions to a section treated equally | Yes — cause determines authority regardless of section | Yes — scope and reversibility cut across sections |
| Calibratable over time | No — section rules are fixed | Partially — causal taxonomy can be refined, but attribution remains subjective | Yes — numeric thresholds directly calibratable from revision outcome data |
| False escalation risk | High (rigid) — minor clarifications trigger same rule as redefinitions | Low — execution discoveries always get autonomous treatment | Medium-Low — conservative initialization produces some false escalations that calibration reduces |
| False autonomy risk | Low — section rules are conservative | Medium — systematic misattribution risk is non-trivial | Low — conservative initialization, hard irreversibility thresholds |
| Implementation complexity | Low | Low-Medium | Medium |
| Produces calibration data | No | No | Yes |

---

## 7. Recommendation

**Recommend Alternative C (Quantified Impact Threshold) initialized conservatively, with the section-based authority matrix applied as an override for load-bearing sections.**

The quantified approach is recommended over the alternatives for three reasons: it produces calibration data that enables the system to improve over time (neither A nor B does this); it handles within-section variation that the section matrix cannot capture; and the mandatory rationale appendix creates a shared vocabulary with the Q2 model-update annotation schema (enabling joint retrospective analysis as specified in Section 12).

**Specific implementation recommendations:**

**1. Conservative initialization.** First implementation sets the autonomous threshold at at or below 1 downstream decision AND fully reversible (more conservative than the standard at or below 2 from Alternative C). The standard threshold table from Alternative C becomes the operational target after calibration history accumulates. This conservative initialization is correct for two reasons:

First, the asymmetry of false-autonomy costs (Tier 3: hours of rework + project restart risk) versus false-escalation costs (~15 min) justifies bearing the extra escalation overhead during the calibration period. Extra false escalations in early sessions generate calibration data about where thresholds should be — when the human consistently says "you should have just done that," that domain's threshold relaxes. The conservative initialization structures the calibration process so that the agent learns toward autonomy rather than being initialized permissively and learning toward caution after damage.

Second, the Dunning-Kruger risk identified in human-dynamics.md — high agent confidence combined with low actual alignment — is most severe in early sessions before calibration history accumulates. Conservative initialization acts as a structural correction for systematic overconfidence.

**Conservative initialization threshold table:**

| Reversibility | Downstream Scope = 0 to 1 | Downstream Scope 2 to 3 | Downstream Scope above 3 |
|--------------|------------------------|------------------------|------------------------|
| Fully reversible | AUTONOMOUS | NOTIFY+WINDOW | MANDATORY ESCALATION |
| Partially reversible | NOTIFY+WINDOW | MANDATORY ESCALATION | MANDATORY ESCALATION |
| Irreversible | MANDATORY ESCALATION | MANDATORY ESCALATION | MANDATORY ESCALATION |

**Standard threshold table (operational target after calibration):**

| Reversibility | Downstream Scope at or below 2 | Downstream Scope 3 to 5 | Downstream Scope above 5 |
|--------------|------------------------------|------------------------|------------------------|
| Fully reversible | AUTONOMOUS | AUTONOMOUS | NOTIFY+WINDOW |
| Partially reversible | AUTONOMOUS | NOTIFY+WINDOW | MANDATORY ESCALATION |
| Irreversible | NOTIFY+WINDOW | MANDATORY ESCALATION | MANDATORY ESCALATION |

Transition from conservative to standard initialization requires: 20 autonomous revisions in the domain category with fewer than 20% found by human to have required human input (see Section 10 calibration protocol).

**2. Section override for load-bearing sections.** Apply the section-based authority matrix (Section 3) as an override — it can only make the classification more conservative, never less conservative. If the quantified threshold produces AUTONOMOUS but the section rule produces MANDATORY ESCALATION (e.g., an objective section revision with very small downstream scope estimate), the mandatory escalation applies. This combines the calibration advantages of Alternative C with the information-access insight of Alternative A.

Overrides:
- Objective section: any revision — override to MANDATORY ESCALATION regardless of scope/reversibility
- Success criteria section redefinition: override to MANDATORY ESCALATION
- Decision boundary expansion: override to MANDATORY ESCALATION

**3. Dynamic threshold calibration (Aghion-Tirole applied dynamically).** As session history accumulates evidence that preference inferences are accurate in a given domain (the human consistently confirms autonomous revisions without modification), the threshold for that domain relaxes toward the standard table. As the system encounters cases where autonomous revision produced downstream damage, the threshold tightens (may return to the conservative initialization or below it). This mirrors the asymmetric weight applied to escalation calibration generally: positive confirmation signals adjust the threshold by one calibration increment; negative (damage) signals adjust it by two calibration increments.

**4. Mandatory rationale appendix.** All autonomous revisions append a structured record using the schema in Section 9 before proceeding. The rationale appendix is not optional — it is the mechanism by which the calibration data in Section 10 is generated, and it is the accountability structure that justifies granting autonomous revision authority. An autonomous revision without a rationale appendix is unauthorized.

---

## 8. Decision Tree for Agent Use

The following decision tree can be applied directly without additional judgment. Every node is a specific yes/no question with explicit decision outcomes.

```
[Agent considering a revision to INTENT.md]
  |
  v
Q1: Does this revision change the Objective section (the fundamental purpose of what
    is being produced)?
  YES -> MANDATORY ESCALATION (stop execution, await human response, do not proceed)
  NO -> continue to Q2

Q2: Does this revision redefine the Success Criteria (change what "success" means,
    not just clarify how it is measured)?
  YES -> MANDATORY ESCALATION
  NO -> continue to Q3

Q3: Does this revision expand the Decision Boundaries (agent claiming authority it
    was not explicitly granted)?
  YES -> MANDATORY ESCALATION
  NO -> continue to Q4

Q4: Has any deliverable been finalized or handed off to the human, or committed to
    the session log as complete, under the CURRENT intent (before this revision)?
  YES (irreversible) -> Q5
  NO -> continue to Q6

Q5 [Irreversible]: How many remaining workflow steps would produce different outcomes
   under the revised intent?
  > 2 (or > 1 under conservative initialization) -> MANDATORY ESCALATION
  <= 2 (<= 1 conservative) -> NOTIFY+WINDOW
      (append revision record to session log, allow 30 min for human response,
       proceed only after window closes without response or after confirmation)

Q6: Has any work begun under the current intent (started but not finalized)?
  YES (partially reversible) -> Q7
  NO (fully reversible) -> Q8

Q7 [Partially reversible]: How many remaining workflow steps would produce different
   outcomes under the revised intent?
  > 5 (or > 3 conservative) -> MANDATORY ESCALATION
  3-5 (2-3 conservative) -> NOTIFY+WINDOW
  <= 2 (<= 1 conservative) -> Q9 (section override check)

Q8 [Fully reversible]: How many remaining workflow steps would produce different
   outcomes under the revised intent?
  > 10 (or > 3 conservative) -> NOTIFY+WINDOW
  <= 10 (<= 3 conservative) -> Q9 (section override check)

Q9 [Section override check -- applies only to revisions that reached AUTONOMOUS from Q7 or Q8]:
  Does this revision affect the Success Criteria section (even for clarification)?
    YES -> Apply one tier stricter: AUTONOMOUS -> NOTIFY+WINDOW
    NO -> continue to Q10
  Does this revision affect the Constraints (Hard) section?
    YES -> Does it foreclose or significantly restrict a previously sanctioned approach?
      YES -> MANDATORY ESCALATION
      NO -> NOTIFY+WINDOW
    NO -> continue to Q10

Q10: Is the cause of this revision a preference inference (agent estimating user
     preference rather than responding to execution-revealed evidence)?
  YES -> Apply one tier stricter (AUTONOMOUS -> NOTIFY+WINDOW;
         NOTIFY+WINDOW -> MANDATORY ESCALATION)
  NO (execution-revealed or new external information) -> AUTONOMOUS

[All AUTONOMOUS outcomes: append structured revision record (Section 9 schema)
 before proceeding. This step is not optional.]

[All NOTIFY+WINDOW outcomes: append revision note to session log specifying revision
 content, rationale, and 30-minute window. If human responds within window: follow
 human direction. If window closes without response: proceed with revision, append
 outcome note.]

[All MANDATORY ESCALATION outcomes: stop execution. Present revision proposal to
 human with: current INTENT.md text, proposed revision, cause of revision,
 downstream scope assessment, and agent recommendation. Do not proceed until human
 responds.]
```

**Decision tree refinements based on section authority analysis:**

- **Success criteria clarification (not redefinition):** The tree routes through Q2 (redefinition check). If Q2 is NO (clarification only), the quantified threshold applies. However, Q9 applies a one-tier-stricter rule for any success criteria change that passes Q2. This ensures success criteria clarifications are at minimum NOTIFY+WINDOW rather than AUTONOMOUS, consistent with the fully-load-bearing architectural status of this section.

- **Contraction of decision boundaries:** The tree routes through Q3 (expansion check). If Q3 is NO (contraction), the quantified threshold applies normally. Contraction gets no override because the section authority analysis establishes it as non-material.

- **Open questions resolution:** The tree does not route through Q1 to Q3 for open question resolution (it does not change the objective, redefine success criteria, or expand decision boundaries). It proceeds through Q4 to Q9, and typically reaches Q10 as execution-revealed — AUTONOMOUS. The rationale appendix documents the resolution.

---

## 9. Autonomous Revision Record Schema

All AUTONOMOUS revisions must append this record to INTENT.md before proceeding. NOTIFY+WINDOW revisions append the same record when proceeding after the window closes (with an added field for human response or absence thereof).

**Format:** Append as a dated section at the end of INTENT.md.

```markdown
## Autonomous Revision -- [YYYY-MM-DD HH:MM UTC]

**Changed:** [Exact section name + brief description of change; for short text,
             include before -> after verbatim; for longer text, describe the delta]

**Cause:** [Select one: execution-revealed-constraint | new-external-information |
            preference-inference]
           Note: preference-inference causes should rarely reach this record --
           they should trigger escalation at Q10. If this field is
           preference-inference, document why escalation was not triggered.

**Cause detail:** [One sentence: the specific trigger event.
                  Example: "Discovered that the target platform enforces a 280-character
                  limit on posts, making the current 400-character constraint unachievable."]

**Reversibility:** [Select one: fully | partially | irreversible]
                  Fully: no work completed under prior intent
                  Partially: work begun but not finalized or delivered
                  Irreversible: deliverable finalized or handed off

**Downstream decisions governed:** [Integer count + brief list of affected remaining steps.
                                   Example: "4 decisions -- sections 3, 4, 5 of the report
                                   and final compilation step"]

**Reversal procedure:** [What would need to be done if this revision is found to be wrong.
                        Who must confirm the reversal.
                        Example: "Sections 3-5 would need to be re-drafted against original
                        criteria. Human must confirm reversal and new direction before
                        re-execution."]

**Prior assumption:** [What the agent believed about this element of INTENT.md before
                      this revision. Example: "Posts can be up to 400 characters per
                      platform standard."]

**Updated assumption:** [What the agent believes now, post-revision.
                        Example: "Posts must be at or below 280 characters; this is a platform
                        hard limit discovered during execution of Step 3."]

**Conservative initialization active:** [yes | no -- whether this session is
                                         operating under conservative or standard thresholds]
```

**Mandatory record completeness check:** Before appending the record and proceeding, confirm all fields are populated with specific content. A field containing only "N/A" or "[none]" is a record completeness failure — if a field is not applicable, explain why in the field rather than leaving it blank.

**Notify+Window supplement** (append below the standard record when NOTIFY+WINDOW applies):

```markdown
**Notification sent:** [YYYY-MM-DD HH:MM UTC]
**Window closes:** [YYYY-MM-DD HH:MM UTC -- 30 minutes after notification]
**Human response:** [confirmed | modified (describe modification) | rejected (describe
                    alternative direction) | no-response (window closed without reply)]
**Action taken:** [proceeded as revised | proceeded as modified | reverted to prior
                  intent | awaiting further clarification]
```

---

## 10. Calibration Protocol

### Data to Capture Per Revision

For each INTENT.md revision occurring in a session, the calibration record must capture:

| Field | Values | Notes |
|-------|--------|-------|
| session_id | string | Links to full session record |
| session_tier | 0, 1, 2, 3 | Task tier at session start |
| revision_timestamp | ISO 8601 | When the revision was considered |
| revision_section | objective, success_criteria, decision_boundaries, constraints_hard, constraints_soft, open_questions | Which INTENT.md section |
| revision_type | clarification, redefinition, expansion, contraction, resolution, new_constraint, removal | Nature of the change |
| cause_category | execution_revealed, new_external_information, preference_inference | From decision tree Q10 |
| reversibility_level | fully, partially, irreversible | At time of revision |
| downstream_scope_estimated | integer | Agent's count at decision time |
| authority_path_taken | autonomous, notify_window, mandatory_escalation | Decision tree outcome |
| conservative_init_active | boolean | Whether conservative thresholds were in effect |
| human_response | confirmed, modified, rejected, no_response, n_a | If escalated or notified |
| human_response_latency_min | integer | Minutes from notification to response |
| downstream_damage_found | boolean | Whether damage was discovered downstream |
| downstream_damage_description | string | If damage found: what and when it was discovered |
| actual_downstream_scope | integer | After session: actual affected steps (for calibration of estimates) |

### Statistical Analysis for Threshold Adjustment

**Primary calibration metric:** "What fraction of autonomous revisions were later found by the human to have required human input?" (Measured as: count of human_response = rejected divided by count of authority_path_taken = autonomous, across sessions in the domain category.)

- If rate above 20%: threshold too permissive — tighten by one calibration increment (shift one column left in the threshold table for this domain category)
- If rate below 5%: potentially too conservative — review in context. Do not automatically relax; check whether the low rate reflects genuine good calibration or a domain where human input is rarely needed regardless of threshold. If the human also frequently says "you should have just done that" (false escalation feedback), relax by one increment.
- Target zone: 5 to 20% human-correction rate on autonomous revisions indicates thresholds are producing useful calibration without excessive false autonomy.

**Secondary calibration metric:** "What fraction of escalations are confirmed without modification by the human?" (Measured as: count of human_response = confirmed divided by count of authority_path_taken = mandatory_escalation.)

- If rate above 80%: escalation threshold may be too conservative for this domain — consider relaxing by one increment
- If rate below 40%: escalation threshold is well-calibrated (human is frequently modifying or redirecting)

**Downstream damage rate:** "What fraction of autonomous revisions produced detectable downstream damage?" (Measured as: count of downstream_damage_found = true divided by count of authority_path_taken = autonomous.)

- Any non-zero rate triggers immediate threshold review regardless of statistical minimums
- A damage rate above 5% triggers automatic tightening to conservative initialization levels for the affected domain

**Minimum sample size before threshold adjustment:** 20 autonomous revisions in a given domain category (defined by revision_section x session_tier). Smaller samples do not provide sufficient statistical power for reliable threshold adjustment. During the calibration accumulation period, operate at conservative initialization.

**Calibration increment definition:** One calibration increment = shifting one cell in the threshold table. Example: relaxing the fully-reversible row from "downstream scope at or below 1 = AUTONOMOUS" to "downstream scope at or below 2 = AUTONOMOUS." Multiple increments require multiple minimum-sample cycles.

### Storage of Calibration Data

Append calibration records to `ESCALATION.md` under a section titled `## Intent Revision Authority -- Domain Calibration Records`. Use the same format as Q3 confidence calibration records (consistent storage enables joint retrospective analysis across both systems as specified in Section 12).

Each calibration record entry:

```
[YYYY-MM-DD] | domain: [section x tier] | path: [autonomous|notify|escalate] |
  cause: [category] | scope_est: [N] | scope_actual: [N] | reversibility: [level] |
  outcome: [confirmed|modified|rejected|no_response|n_a] | damage: [yes|no]
```

**Calibration summary update:** After every 20 records in a domain category, compute the primary and secondary calibration metrics and append a summary entry:

```
## Calibration Summary -- [domain] -- [YYYY-MM-DD]
Records analyzed: [N]
Autonomous correction rate: [X%] -> threshold action: [none | tighten | relax]
Escalation confirmation rate: [X%] -> threshold action: [none | tighten | relax]
Damage rate: [X%] -> threshold action: [none | immediate review]
Current threshold table: [conservative_init | standard | adjusted: describe]
Next review at: [N + 20] records
```

---

## 11. Regret Matrix (Savage Minimax Applied)

### Full Regret Matrix for Tier 2 and Tier 3 Sessions

**Decision states and regret values:**

| Decision | Revision was correct (human would have confirmed) | Revision was wrong (human would have modified/rejected) |
|----------|---------------------------------------------------|--------------------------------------------------------|
| **Tier 2: Acted autonomously** | Regret = 0 (best outcome) | Regret = 30 to 90 min rework + moderate trust damage (~0.5 to 1.5 hr equivalent) |
| **Tier 2: Escalated** | Regret = 15 min interruption + flow loss | Regret = 0 (human catches it, redirects correctly) |
| **Tier 3: Acted autonomously** | Regret = 0 (best outcome) | Regret = 1 to 4+ hr rework + significant trust damage + possible project restart (1 to 8+ hr equivalent) |
| **Tier 3: Escalated** | Regret = 20 min interruption + larger context switch (~0.3 to 0.5 hr equivalent) | Regret = 0 (human catches it, redirects correctly) |

**Minimax regret analysis:**

For Tier 2: Max regret of autonomous action = 90 min. Max regret of escalation = 15 min. Minimax regret favors escalation by a 6:1 factor. Conservative initialization is justified until empirical data adjusts the cost estimates.

For Tier 3: Max regret of autonomous action = 8+ hours. Max regret of escalation = 0.5 hours. Minimax regret favors escalation by a 16:1 factor. The dominance here is so strong that even generous estimates of autonomous decision accuracy cannot close the gap without substantial calibration history demonstrating consistent accuracy.

### Sensitivity Analysis

**Cells most sensitive to empirical calibration (should be updated first as session data accumulates):**

1. **Tier 2 false autonomy cost (rework):** The 30 to 90 minute range is wide. Empirical data from actual sessions with revision damage will narrow this. If actual Tier 2 rework averages 30 minutes, the minimax ratio drops from 6:1 to 2:1, which may justify faster relaxation of Tier 2 thresholds.

2. **Tier 3 false autonomy cost (rework + damage):** The 1 to 8+ hour range reflects genuine uncertainty about the severity of downstream damage in Tier 3 sessions. Empirical damage records (Section 10: downstream_damage_description) will narrow this range significantly. Initial conservatism is non-negotiable until this cell has at least 5 data points.

3. **Interruption cost (both tiers):** The 15 to 20 minute estimate for false escalation cost assumes the human is available and responsive. In practice, escalation to an unavailable human may create session blocking for hours. If the actual escalation latency in observed sessions is materially higher than 20 minutes, the minimax ratio shifts toward autonomous action in some domains.

**Asymmetry justification for conservative initialization:**

The regret matrix makes the conservative initialization justification explicit: the maximum regret of false autonomy in Tier 3 (8+ hours) dominates all other cells. No plausible calibration of interruption costs (which are bounded by the 30-minute human notification window in the NOTIFY+WINDOW path) can close a ratio of this magnitude. Therefore, conservative initialization is not merely prudent — it is the minimax optimal strategy for Tier 3 sessions until session data produces significantly lower empirical estimates of false-autonomy costs.

The asymmetric weighting already established in the system (negative signals weighted at -0.10, positive signals at +0.05 in the escalation calibration model) applies here: false autonomy damage adjustments to the threshold carry twice the weight of confirmations that the threshold could have been more permissive.

---

## 12. Cross-References

### Shared Vocabulary with Q2 Checkpoint Annotations

The autonomous revision record schema (Section 9) uses the same structural vocabulary as Q2 checkpoint model-update notes:

| Field | Revision Record | Q2 Annotation |
|-------|----------------|---------------|
| Prior state | Prior assumption | Model state at checkpoint entry |
| Update trigger | Cause detail | Trigger event |
| Updated state | Updated assumption | Model state at checkpoint exit |
| Downstream scope | Downstream decisions governed | Downstream steps affected |
| Reversibility | Reversibility | Reversibility of current path |

This shared vocabulary is deliberate. Both records are model-state-change events: the revision record documents a change to the external intent specification; the Q2 annotation documents a change to the agent's internal confidence model. Both are learning events. Using consistent field names and value vocabularies enables joint retrospective analysis: a session debrief can examine both types of model updates together, identifying whether intent revisions and confidence updates were causally related, whether the sequence of revisions follows a pattern, and whether the calibration protocol should treat them as linked data rather than independent records.

The cause_category field (execution-revealed / new-external-information / preference-inference) should use exactly these three values in both schemas. Shared taxonomy enables cross-system analysis without normalization.

### Integration with Q3 Confidence Calibration Records in ESCALATION.md

Domain-level calibration of revision authority thresholds (Section 10) is stored in ESCALATION.md using the same tabular format as Q3 confidence calibration records. Both systems calibrate agent judgment thresholds using session outcome data; consistent storage format enables:

1. **Joint retrospective analysis:** Sessions where both confidence calibration and revision authority calibration events occurred can be analyzed together to identify correlations — e.g., do sessions with high confidence drift also show more revision authority miscalibration?

2. **Unified calibration review cadence:** A single periodic review of ESCALATION.md can assess both systems simultaneously, rather than requiring separate review processes.

3. **Cross-system threshold alignment:** If Q3 confidence calibration finds that the system is systematically overconfident in a domain, the revision authority calibration for that domain should be tightened in concert — overconfidence in execution extends to overconfidence in revision authority judgments.

The ESCALATION.md section for revision authority calibration (as specified in Section 10) should follow immediately after the Q3 confidence calibration records section to reinforce their analytical relationship.

---

## 13. Provenance and Sources

### Established Research (citations to original work)

| Source | Year | Key Contribution Applied |
|--------|------|-------------------------|
| Weber, E.H. *De Pulsu, Resorptione, Auditu et Tactu* | 1834 | Just-noticeable difference proportionality — basis for proportional magnitude thresholds in Section 4.3 |
| Simon, H.A. *Administrative Behavior* | 1947 | Bounded rationality and administrative authority — supports conservative initialization under informational uncertainty (Section 7) |
| Savage, L.J. "The Theory of Statistical Decision." *Journal of the American Statistical Association* | 1951 | Minimax regret framework — basis for the regret matrix in Section 11 and the conservative initialization justification |
| Fechner, G.T. *Elemente der Psychophysik* | 1860 | Weber-Fechner law formalization — supports proportional threshold specification in Section 4.3 |
| Aghion, P. & Tirole, J. "Formal and Real Authority in Organizations." *Journal of Political Economy* | 1997 | Formal vs. real authority — basis for information-access authority assessment in Sections 2.2 and 3, and dynamic calibration mechanism in Section 7 |
| Restatement (Second) of Contracts, section 241 | 1981 | Material breach doctrine formalization — basis for material/non-material revision distinction in Section 2.4 |
| *Jacob & Youngs, Inc. v. Kent*, 230 N.Y. 239 | 1921 | Material breach doctrine application — key case illustrating "root of the contract" standard |
| Kahneman, D. *Thinking, Fast and Slow* | 2011 | System 1 / System 2 dual-process theory — basis for cognitive processing requirements per INTENT.md section in Section 2.5 |
| Lehnert, M. "A Review of Software Change Impact Analysis" | 2002 | Direct vs. downstream impact analysis — basis for "magnitude = downstream decision scope, not text volume" in Section 2.3 |
| Baldwin, C.Y. & Clark, K.B. *Design Rules: The Power of Modularity* | 2000 | Architecturally load-bearing vs. non-load-bearing elements — basis for section architectural weight analysis in Sections 2.3 and 3 |
| Project Management Institute. *PMBOK Guide, 6th Edition* | 2017 | Risk appetite vs. risk tolerance vs. risk threshold distinction — basis for hard threshold vs. calibratable tolerance structure in Section 2.6 |

### Design Synthesis (our application of research to this system — not established prior art)

The following are design decisions derived from applying the research above to the specific constraints of the poc-workflow system. They represent architectural choices, not empirical findings:

- **Three-level reversibility taxonomy** (Section 4.1): The specific definitions of "fully / partially / irreversible" in terms of finalized deliverables and session log commits are design choices, not research findings. The general principle of using reversibility as an authority signal derives from the system's existing escalation model and execution-alignment.md.

- **Conservative initialization thresholds** (downstream scope at or below 1 for fully-reversible autonomous): The specific threshold values are normative starting priors. The conservative initialization logic derives from Savage minimax regret and the asymmetric cost structure, but the specific numbers are calibration targets, not empirically derived.

- **30-minute NOTIFY+WINDOW duration**: Derived from the ~15-minute interruption cost estimate (human needs time to re-orient and respond) plus a buffer. Not empirically validated.

- **20-revision minimum sample size for threshold adjustment**: Chosen to provide minimal statistical reliability (at a 20% correction rate, 20 samples gives approximately plus-or-minus 9% margin of error). Not derived from prior calibration research.

- **Section override rules** (Q9 in decision tree): The specific overrides for success criteria and hard constraints are design choices derived from the architectural weight analysis (Section 3), which is itself an application of Baldwin & Clark's framework to INTENT.md structure.

- **Threshold calibration increments**: The "one column shift per calibration cycle" mechanic is a design choice for gradual, controllable threshold adjustment. The asymmetric weighting (negative signals at 2x weight) is derived from the system's existing -0.10/+0.05 escalation calibration model, extended by analogy.

- **25% measurement range clarification threshold for success criteria**: A design prior for the threshold below which success criteria clarification is autonomous. Not empirically derived; should be the first threshold updated as calibration data accumulates.

- **The causal attribution taxonomy** (execution-revealed / new-external-information / preference-inference): Derived from Aghion-Tirole's information-access framework, but the specific three-category breakdown is a design synthesis choice, not a direct citation.
