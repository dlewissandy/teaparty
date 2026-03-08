# Research Q2: In-Flight Learning and the Milestone Model-Update Mechanism

**Document status:** Research synthesis — resolves Open Question 2 from `workflow-detailed-design.md` Section 9
**Date:** 2026-03-01
**Scope:** Tier 2 and Tier 3 session execution, four-moment learning loop

---

## 1. Problem Statement

### 1.1 The Open Question

From `workflow-detailed-design.md`, Section 9, Open Question 2:

> "The spec has no current mechanism for flagging milestone model-updates into the session stream. Does this require a new tool, or can it be encoded as a structured annotation in the existing session log format?"

### 1.2 What Working Assumptions Are

A working assumption is a component of the agent's task model constructed at session start. When a Tier 2 or Tier 3 session opens, the agent builds a model of the work from the available evidence: INTENT.md, prior session memory, and the plan produced during the intent-capture phase. This model has at least four components:

1. **Complexity estimate.** How many steps, how much depth, how long each milestone will take. This estimate drives sequencing, parallelism decisions, and escalation thresholds.

2. **Approach viability assessment.** The judgment that the chosen decomposition — which liaisons to dispatch, which tools to use, which sequence to follow — is fit for the task as understood. This is the most consequential assumption because it shapes every downstream step.

3. **User preference model.** The working representation of what the user wants: their communication style, depth expectations, scope boundaries, and tolerance for agent autonomy. This is loaded from warm-start memory and refined through intake questioning, but it remains a prediction at session open.

4. **Constraint set.** The boundary conditions under which the work must be done: stop rules from INTENT.md, hard technical constraints, time constraints, scope limits. The assumption is that the constraint set as enumerated in INTENT.md at session start is complete, or complete enough for planning.

Each of these is a hypothesis, not a fact. Each may be confirmed, partially contradicted, or fully contradicted by evidence that emerges during execution. A milestone is the natural observation point at which that confirmation or contradiction becomes legible.

### 1.3 The Operational Cost of Missing Records

When a session is interrupted — by a handoff to a new agent instance, by a multi-day gap in execution, by a relay dispatch that returns after the parent context has shifted — the resuming agent reconstructs its task model from the session log. If the session log contains no record of mid-session assumption changes, the resuming agent faces two bad options:

**Re-derive the model from scratch.** The agent reads all prior execution records and attempts to infer the current state of each assumption. This is expensive — it requires reading all prior work, applying interpretation to ambiguous intermediate outputs, and producing a working model that may still be wrong if the relevant signal is embedded in narrative text rather than in a structurally distinct record. For long Tier 3 sessions, re-derivation may require reading hundreds of lines of execution history.

**Operate on the stale model.** The agent proceeds on the assumption that the model from session start still holds, since there is no record contradicting it. If an assumption was partially contradicted at milestone 2, the Tier 3 work following milestone 3 may proceed on a wrong model without any visible signal that this is happening. The stale model is the more dangerous outcome because it produces no error signal — the agent is confident and wrong.

Both outcomes carry real operational cost: token consumption for re-derivation, or compounding drift for stale-model execution. Neither is recoverable through retrospective extraction because by then the downstream effects have propagated through the entire execution chain.

### 1.4 Why This Matters for the Four-Moment Learning Loop

The `learning-evolution.md` document identifies four distinct learning moments: prospective (before execution), in-flight (at milestones), corrective (at mismatch discovery), and retrospective (after completion). The current workflow captures the retrospective moment via `summarize_session.py`. Prospective learning is served by warm-start memory retrieval in `intent.sh`. Corrective learning is partially served by the escalation calibration mechanism.

In-flight learning is currently unrecorded. There is no session log event type, no workflow state update, and no prompt instruction that produces a canonical record of a mid-session assumption change. As `learning-evolution.md` states: "Sessions execute, milestones complete, and the model that was constructed at the start of the session persists unchanged regardless of what the work reveals." This is not a gap at the edge of the learning loop — it is the gap at the moment when learning is cheapest to act on and most worth capturing.

### 1.5 The Altmann-Byrne Prospective Memory Connection

Altmann and Byrne's prospective memory model (activation-based, developed across publications from approximately 2000 to 2016) describes the conditions under which humans successfully complete deferred intentions — intentions to do something at a future moment contingent on recognizing that the moment has arrived. Their central finding is that retrieval of deferred intentions is mediated by activation levels that decay over time and are restored by environmental cues at the moment of execution.

The session log is a functional analog to prospective memory. It records commitments about future steps alongside the state of current execution. When an in-flight assumption changes, the session log must be updated to serve two distinct functions: recording what happened (the retrospective record) and signaling what the prior agent expected to happen next (the prospective commitment). An assumption-change event affects both: it changes what has happened AND it changes the expected state of downstream work.

Altmann and Byrne's research identifies interruptions as most costly when the interrupted task's subgoal state is ambiguous — when it is unclear which subgoal the interrupted person had been pursuing and whether it had been completed. This is precisely the condition created by a session log with no canonical place for assumption status. A resuming agent does not know whether the prior agent's model was confirmed, partially revised, or invalidated. The ambiguity forces re-derivation — the same costly reorientation that Altmann and Byrne measure in human interrupted-task studies.

The design implication is structural: the session log needs a predictably located, syntactically distinct record of assumption state at each milestone. Not narrative text that encodes assumption status implicitly, but a record type that a resuming agent can retrieve directly without parsing the entire execution history.

---

## 2. Research Findings by Domain

### 2.1 Cognitive Science — Prospective Memory and Interrupted-Task Management

**The Altmann-Byrne model.** Erik Altmann and Robert Byrne developed an activation-based model of prospective memory across a series of publications from approximately 2000 through 2016 (principal theoretical statement in Altmann and Byrne, 2002, "The Strategic Use of Memory for Frequency and Recency," Psychological Review). In this model, deferred intentions are stored memory structures with activation values that decay over time. The moment of intended execution is recognized when environmental cues trigger retrieval of the stored intention. Retrieval fails when activation has decayed below threshold before the cue occurs, or when the cue is ambiguous and does not sufficiently re-activate the stored intention.

Applied to the session log: each milestone in a Tier 2 or Tier 3 session is a deferred execution point. The session log is the storage medium for commitments about those execution points. When an assumption about a downstream milestone changes mid-session, the commitment stored in the session log becomes stale — it still predicts the milestone will proceed under the original model, but the evidence now contradicts that prediction. If the update is not written back to the session log, the stored commitment and the current model diverge, and any subsequent retrieval of the commitment will recover the stale version.

**Subgoal loss under interruption.** Altmann and Byrne specifically document the cost of subgoal loss — the condition where an interrupted task's intermediate state is ambiguous at resumption. In their experimental paradigm, subjects performing multi-step tasks under interruption made more errors at the step immediately following the interruption point, particularly when they could not directly observe which subgoal had been active before interruption. The error rate was substantially higher when subgoal state was ambiguous versus when it was externally represented.

The session log can externally represent subgoal state — that is precisely what it is for. But it can only do this reliably if assumption state is a first-class element of that external representation. If assumption state is embedded in narrative execution records, resuming agents face the same ambiguity that produces subgoal-loss errors in Altmann and Byrne's human subjects.

**The dual record requirement.** When an in-flight assumption changes, the agent must update two distinct records: the retrospective record of what has happened, and the prospective commitment about what comes next. These are not the same update. A milestone that confirms an assumption produces a retrospective record (confirmation of what was predicted) but does not require a change to the prospective commitment. A milestone that contradicts an assumption produces a retrospective record (evidence of contradiction) AND requires revision of the prospective commitment about downstream work. Conflating these two update types in a single narrative record — "milestone 2 complete, some challenges encountered" — loses the prospective update entirely.

**Design implication.** The session log needs a structurally distinct, predictably located record of assumption state that serves as the external representation of the agent's current task model. This record must be recoverable without parsing narrative execution history. It must be updated at each milestone where assumption state changes — not as an optional narrative observation, but as a mandatory structured record that a resuming agent can retrieve directly.

### 2.2 Distributed Systems — Event Sourcing

**The event sourcing pattern.** Greg Young introduced the event sourcing pattern in the context of CQRS (Command Query Responsibility Segregation) design, documented in influential presentations and writings from approximately 2010 onward. The central insight is a distinction between two types of data artifacts: event records (immutable, timestamped records of what happened) and projections (derived views computed from the event stream). In an event-sourced system, the event log is the source of truth; all other data structures — including the current state — are derived from it.

Applied to the session log: each milestone completion is an event. Each model update is also an event. The question is whether a model-update is a new event type with its own timestamp and schema, or a mutation of derived state inferred from execution event records.

Martin Fowler's documentation of event sourcing (martinfowler.com, "Event Sourcing," updated through approximately 2019) frames the core distinction precisely: an event record captures what happened at a specific time, with all the information needed to reconstruct the state at that time; a derived state projection computes the current model from the sequence of events. In Fowler's framing, the choice to represent a state change as an event versus a derived-state mutation has significant consequences for retrospective analysis: if model updates are events, the event stream contains a complete audit trail of how the task model evolved; if they are derived-state mutations, that audit trail must be reconstructed by re-processing the entire event sequence.

**Pat Helland's immutability analysis.** Pat Helland's "Immutability Changes Everything" (CIDR 2015) argues that the choice to treat records as immutable events rather than mutable state has systemic consequences: immutable event records are trivially replicable, trivially auditable, and support correct temporal reasoning about system state at any past point. Mutable state projections require synchronization, version tracking, and careful reasoning about the current-versus-historical distinction.

Applied to in-flight learning: if a model-update is encoded as a new event in the session log (a structurally typed record with its own schema and timestamp), then:
- Retrospective extraction is a simple query: return all events of type `assumption_checkpoint`
- The absence of such an event at a milestone is unambiguous: no assumption changed
- The evolution of the task model over the session is directly readable from the event sequence
- A resuming agent can retrieve the most recent `assumption_checkpoint` event to recover the current model state without reading all prior execution records

If a model-update is encoded as an annotation on the execution record (a text block embedded in the milestone completion log entry), then:
- Retrospective extraction requires parsing all milestone completion records and detecting the presence or absence of the annotation block
- Absence of the annotation is ambiguous: it could mean no assumption changed, or it could mean the agent forgot to annotate
- The evolution of the task model requires reading the entire narrative history
- A resuming agent cannot directly retrieve the current model state without parsing all prior records

**Consequences for session log design.** Event sourcing analysis strongly favors typed events over embedded annotations for model-update records. The clean separation of event types eliminates the ambiguity-of-absence problem. However, the session log in the poc-workflow system is not a pure event store — it is a human-readable document that serves both machine-queryability and human review functions. The design must balance event-sourcing's clarity with the readability requirements of the human-review use case.

### 2.3 Machine Learning — Online Learning and Concept Drift Detection

**The concept drift problem.** A session's working model — the agent's current hypothesis about task complexity, approach viability, user preferences, and constraints — is a classifier that makes predictions about the task. Each milestone produces an observation that either confirms or contradicts the model's predictions. The question of when a model-update is warranted is formally equivalent to the concept drift problem in online learning: when has the distribution of observations changed enough that the current model is no longer an accurate predictor?

**Gama et al. DDM (Drift Detection Method, 2004).** Joao Gama, Pedro Medas, Gladys Castillo, and Pedro Rodrigues (2004, "Learning with Drift Detection," SBIA — Brazilian Symposium on Artificial Intelligence) proposed the Drift Detection Method as a principled statistical test for concept drift in online learning scenarios. DDM tracks the error rate of the current model and maintains a running estimate of the minimum error rate observed. Two thresholds are defined:

- **Warning level:** when the current error rate exceeds the minimum by a statistically significant margin (approximately 2 standard deviations in Gama et al.'s parameterization), the model is flagged as potentially drifting. Observations are retained in a buffer for potential retraining.
- **Drift level:** when the current error rate exceeds the minimum by a larger margin (approximately 3 standard deviations), concept drift is confirmed and the model is retrained on the buffered observations.

Applied to in-flight learning: the "error rate" is the discrepancy between predicted and actual milestone behavior. If actual step completion time is 1.5x the estimate (warning level — within elevated but non-alarming range), this is within the noise band: elevated, worth noting, but not a confirmed assumption change. If actual step completion time is 2x or more the estimate (drift level), the model's complexity assumption is confirmed to be wrong: this is a mandatory checkpoint.

**Bifet and Gavalda ADWIN (Adaptive Windowing, 2007).** Albert Bifet and Ricard Gavalda (2007, "Learning from Time-Changing Data with Adaptive Windowing," SIAM International Conference on Data Mining) proposed ADWIN as an improvement on fixed-window drift detection methods. ADWIN maintains a sliding window of recent observations and continuously tests whether any two sub-windows of that window have statistically different means. When a statistically significant difference is detected, the older sub-window is dropped and the model is updated to reflect only the recent distribution.

The ADWIN insight relevant to in-flight learning is the sliding window: ADWIN does not require a fixed number of observations before triggering a drift detection event. It detects drift based on the statistical significance of the observed divergence regardless of window size. Applied to session execution, this means a mandatory checkpoint annotation should be triggered not by a fixed count of anomalous observations, but by the statistical magnitude of the observed discrepancy from the model's predictions.

**Translating DDM/ADWIN to a concrete rule.** For the poc-workflow system, the following mapping applies:

| DDM/ADWIN concept | Session execution analog |
|-------------------|--------------------------|
| Model error rate | Discrepancy between predicted and actual milestone behavior |
| Warning threshold (~2 standard deviations) | 1.5x estimated time; minor soft constraint discovered |
| Drift threshold (~3 standard deviations) | 2x estimated time; hard constraint discovered; assumption contradicted |
| Model retraining | Mandatory checkpoint annotation + downstream step revision |
| Noise band | Variance within 1.5x estimate; assumption confirmed at different confidence than expected |

The rule is: a checkpoint annotation is mandatory when the drift threshold is met; it is discretionary (agent exercises judgment) when only the warning threshold is met.

**Why this framing matters.** Without DDM/ADWIN logic, the mandatory-versus-discretionary distinction is purely subjective. Different agents will make different judgments about whether an observation is "significant enough" to warrant a checkpoint annotation. The DDM/ADWIN framework provides an objective criterion grounded in statistical significance of divergence from the model — not in the agent's subjective assessment of importance. This produces consistent behavior across agents and sessions, and enables retrospective calibration of the threshold parameters based on accumulated session data.

### 2.4 Observability Engineering — Structured Logging

**OpenTelemetry structured log record specification.** The OpenTelemetry project (Cloud Native Computing Foundation, specification developed from 2019, with the log signal reaching stable status in 2023) defines a structured log record format that distinguishes between the log body (human-readable narrative text), attributes (structured key-value pairs that are machine-queryable), and the resource and instrumentation context. The core design principle is that structured fields are queryable; narrative text is not.

The OpenTelemetry Logs Data Model specification defines required fields (`TimeUnixNano`, `SeverityText`, `Body`) and optional attributes that can be attached to any log record as typed key-value pairs. These attributes are indexed and queryable by log processing systems (such as Elasticsearch or OpenSearch), while the Body field is treated as human-readable content.

Applied to the session log: if model-update information is embedded in the Body of a log record (narrative text), it is not queryable by retrospective extraction tools without text parsing. If model-update information is encoded in structured attributes with defined field names and types, it is directly queryable: `SELECT * FROM session_log WHERE type = 'assumption_checkpoint' AND assumption_status = 'contradicted'`.

**Cindy Sridharan on distributed systems observability.** Cindy Sridharan's "Distributed Systems Observability" (O'Reilly, 2018) establishes the canonical three-pillar framework: metrics (aggregated measurements), traces (execution path records), and logs (event records with context). Sridharan's key observation about logs is that their value is proportional to the queryability of their contents: unstructured log text is searchable by keyword but not aggregable or correlatable; structured log records with defined field schemas support aggregation, correlation, and retrospective analysis.

For the session log, this has a direct implication: if retrospective extraction needs to find all model-update events across multiple sessions to identify patterns of assumption failure, those events must have a shared, stable field schema. Narrative text descriptions of assumption changes are not retrospectively extractable in any scalable way; structured annotation records with a stable schema are.

**Elasticsearch/Logstash structured logging conventions.** Elastic Common Schema (ECS, from Elasticsearch, updated through 2024) defines field naming conventions for machine-queryable log records: `event.type`, `event.category`, `event.outcome`, with application-specific fields in a namespaced prefix. Applied to the session log: model-update records should follow a consistent field naming convention with a stable type field that enables direct query-by-type.

**The readability-queryability tension.** The core challenge for session log design is that the human reader and the machine query have different needs. The human reader needs narrative context — why did the assumption change, what does it mean for the work ahead, what should a resuming agent do differently. The machine query needs structured fields — what type of event is this, what was the before/after state, what session and milestone does it belong to. These two requirements pull toward different formats: narrative text for humans, structured fields for machines.

The observability engineering resolution to this tension is the two-field pattern: a Body or `summary` field that carries human-readable narrative, paired with structured attributes or a JSON annotation block that carries machine-queryable fields. The human reads the Body; the machine queries the attributes. Both are present in the same record. This is the pattern that should be applied to milestone model-update notes.

### 2.5 HCI — Notification Design and Progressive Disclosure

**Gloria Mark's interruption and attentional cost research.** Gloria Mark's research on interruption cost (Mark, Gudith, and Klocke, 2008, "The Cost of Interrupted Work: More Speed and Stress," ACM CHI; and earlier work from 2005) documented that recovery time after interruption is 23 minutes on average for complex knowledge work, that interrupted tasks produce higher error rates and higher stress, and that the cost is significantly modulated by the information state at the point of interruption: interruptions at natural breakpoints (analogous to milestone boundaries) are substantially cheaper to recover from than interruptions mid-subtask.

A related finding from Mark's later work (2016, 2018) is that undifferentiated information signals in high-volume streams are effectively ignored — users develop attentional filters that screen out signals that are not structurally distinct from the ambient flow. Applied to the session log: if model-update notes are not visually and structurally distinct from execution records, readers will fail to process them at higher rates than expected. The signal will be present but invisible.

**Progressive disclosure in mobile notification systems.** iOS and Android notification design (Apple Human Interface Guidelines, updated through 2024; Google Material Design notification guidelines, updated through 2024) employ priority stratification to maintain signal-to-noise ratio in high-volume information streams. Notifications are classified by urgency and structured to surface the most important information at each disclosure level: a title in the collapsed view, a summary in the first expansion, full detail in the expanded view. Empirical A/B testing data from mobile platform developers (summarized in multiple product engineering analyses from Apple and Google, 2018–2022) consistently shows that priority-stratified, structurally distinct notifications have significantly higher engagement rates than flat, undifferentiated streams.

Applied to the session log: model-update notes should be structurally distinct at two levels — visually distinct within the session log document (so a human reader scanning the log can immediately identify model-update entries without reading every line), and syntactically distinct (so a machine query can retrieve model-update records without parsing narrative text). Both distinctions are necessary; neither alone is sufficient.

**Progressive disclosure applied to workflow state.** The workflow state document (the file tracking execution progress across milestones) is the primary human-readable artifact consulted by a resuming agent or a reviewing human. If model-update information is present only in the session log (a secondary document consulted for audit purposes), it will be discovered only by readers who know to look for it. If model-update information is co-located with execution progress in the workflow state document, it is encountered in the natural reading flow. Co-location with execution records in the human-readable document is the progressive disclosure principle applied to workflow state: the reader sees the execution progress AND the assumption state together, at the point where the execution progress is being read.

This is the design argument for the two-destination pattern: model-update records should appear in BOTH the session log (structured, machine-queryable) AND the workflow state document (narrative, human-readable, co-located with execution progress). The two destinations serve different readers without requiring either reader to consult a secondary document.

---

## 3. In-Flight Learning Event Taxonomy

Five event types may warrant a model-update note at a milestone boundary. Each is defined with a trigger condition, a specification of what should be recorded, and a mandatory-versus-discretionary classification derived from the DDM/ADWIN drift-detection framework.

---

### Type 1: Assumption Confirmation

**Definition.** A working assumption held at session start is confirmed by evidence produced during milestone execution. The model's prediction was correct; the observation matches the prediction within the noise band.

**Trigger.** The milestone produces output consistent with the complexity estimate, approach viability assessment, user preference model, or constraint set as encoded in the session model. No significant discrepancy between predicted and actual behavior.

**What the agent should record.** Which assumption was tested and confirmed; the confidence level before and after (confirmation may increase confidence above the prior level); a one-sentence summary noting which observation provided confirmation.

**Mandatory vs. Discretionary.** DISCRETIONARY. An assumption confirmation is within the noise band by definition — it is an observation consistent with the model's prediction. DDM/ADWIN logic does not trigger at the warning or drift threshold when error rate (model discrepancy) is zero or near-zero. The agent may record a confirmation to maintain a continuous assumption audit trail, but is not required to do so.

**Rationale for discretionary status.** The value of recording confirmations is calibration: a prior confidence of "moderate" confirmed three times in a row should increase to "high." However, the absence of a confirmation record at a given milestone does not create the ambiguity-of-absence problem that motivates mandatory annotation — there is no risk of downstream drift from a silent confirmation.

---

### Type 2: Assumption Partial Contradiction

**Definition.** A working assumption held at session start is partially contradicted by evidence produced during milestone execution. The assumption was correct in some respects but wrong in others; the downstream effect is bounded — it affects some but not all subsequent steps.

**Trigger.** The milestone produces output that requires revision of a portion of the session model, but the overall approach remains viable. Examples: a technical approach is more complex than estimated in one specific integration point but works as expected elsewhere; a user preference is revealed to be stronger or more conditional than the prior model predicted; a constraint turns out to be softer than encoded in INTENT.md (or harder, but only in a bounded scope).

**What the agent should record.** Which assumption was partially contradicted; the specific respect in which it was wrong; which downstream steps are affected and which are not; the revised confidence level; a one-to-two sentence summary of what needs to change.

**Mandatory vs. Discretionary.** MANDATORY. A partial contradiction meets the drift threshold under DDM logic — the model's prediction was wrong in a domain-relevant direction. The downstream effect is bounded but non-zero: at least some steps must proceed differently than planned. Leaving this unrecorded creates the stale-model risk for resuming agents. The `assumption_status` field must be set to `partially-holding`.

---

### Type 3: Assumption Full Contradiction

**Definition.** A working assumption held at session start is completely contradicted by evidence produced during milestone execution. The assumption was wrong in a way that requires replanning the approach, not merely adjusting parameters.

**Trigger.** The milestone produces output that invalidates a core component of the session model: the chosen decomposition is intractable, the approach is not viable for the task as it has actually presented, the user preference model was wrong in a fundamental direction, or the constraint set is substantially different from what INTENT.md encoded. Full contradiction requires stopping, reassessing, and producing a revised plan before proceeding.

**What the agent should record.** Which assumption was contradicted; the evidence that contradicted it; the specific scope of replanning required; whether human escalation is required (if the contradiction involves a stop rule or a large irreversible action); the revised confidence level for related assumptions; a one-to-two sentence description of the required replanning.

**Mandatory vs. Discretionary.** MANDATORY. A full contradiction is a confirmed drift event under both DDM and ADWIN frameworks — the model has broken down and cannot guide correct execution until it is revised. This is the highest-priority checkpoint event. The `assumption_status` field must be set to `contradicted`, and the `downstream_affected_steps` field must carry an estimate of the replanning scope.

---

### Type 4: Complexity Delta

**Definition.** The actual complexity of the work (measured by time, step count, or depth of analysis required) differs significantly from the estimate embedded in the session model at start.

**Trigger.** Actual step completion time exceeds estimated time by more than 2x (mandatory), or by between 1.5x and 2x (discretionary). Alternatively, the actual step count required to achieve a milestone outcome is more than 20% above or below the plan's estimate.

**What the agent should record.** The estimated complexity; the actual complexity; the ratio of actual to estimated; which remaining steps are affected by the revised complexity estimate; a one-sentence explanation of what drove the complexity change.

**Mandatory vs. Discretionary.** MANDATORY when actual completion time exceeds 2x estimated (DDM drift threshold); DISCRETIONARY when actual completion time is 1.5x–2x estimated (DDM warning level). The 2x threshold is derived from DDM's drift detection criterion: a doubling of the expected time implies the estimating model is wrong in a statistically significant direction, not merely imprecise. A 1.5x overrun may be within the noise band of any single estimate; a 2x overrun is not.

**Note.** Complexity delta is worth recording even when the direction is "smaller than estimated" (the work is easier than planned), because the downstream effect on remaining step estimates is directionally significant. Completing a milestone in half the estimated time may allow schedule compression or scope expansion — both of which benefit from an explicit note.

---

### Type 5: New Constraint Discovered

**Definition.** A hard constraint on the work, not present in INTENT.md at session start, is discovered during milestone execution. The constraint limits what subsequent steps may do in a way that was not anticipated in the original plan.

**Trigger.** Any of: a technical dependency is discovered that prevents or limits the chosen approach; a user-stated boundary is revealed during execution that was not captured in intake; a legal, organizational, or systemic constraint is encountered that modifies the scope or method of the work; an INTENT.md stop rule turns out to apply to a broader scope than originally understood.

**What the agent should record.** The specific constraint discovered; the evidence source (where in the work was the constraint revealed); which downstream steps are affected; whether the constraint requires human confirmation before proceeding; a one-to-two sentence description of the constraint and its scope.

**Mandatory vs. Discretionary.** MANDATORY. Any new hard constraint not present in INTENT.md at session start is by definition a drift event — the constraint set the model was operating with is wrong. DDM logic applies: the model's prediction (that the constraint set was complete) is falsified by the observation. The absence of this record risks downstream steps proceeding under the wrong constraint set, which can produce irreversible errors.

---

## 4. Three Alternatives

### Alternative A: Structured Annotation Block Embedded in Existing Milestone Log Entry

**Description.** Each milestone log entry is extended with an optional structured block. The block is syntactically delimited (e.g., by a YAML front-matter-style delimiter or a distinct heading prefix) and carries a defined set of fields: `assumption_status` (holding, partially-holding, or contradicted), `summary` (maximum two sentences), `prior_confidence`, and `updated_confidence`. The session log remains a single stream. The block is present when an assumption event occurred at the milestone and absent when no assumption change occurred (or, optionally, present with status `holding` for explicit confirmations).

**Structural form:**

```
## Milestone: [Name] — [timestamp]

[narrative execution record]

---assumption-checkpoint---
assumption_status: partially-holding
summary: Technical approach viable but integration requires an additional preprocessing step not anticipated in plan.
prior_confidence: high
updated_confidence: moderate
---end-checkpoint---
```

**Advantages:**
- Low implementation cost: no new tools, no new file types, no changes to tool interfaces
- Single stream: humans and machines read the same document; no synchronization required
- Human-readable in context: the checkpoint block appears immediately below the execution record it annotates, so the narrative context is co-located
- No new agent behavior required beyond inserting the structured block in the log entry

**Disadvantages and Risks:**

*False-negative rate: High.* The absence of an annotation block is structurally ambiguous. It may mean no assumption changed at this milestone, or it may mean the agent forgot to annotate. There is no structural mechanism to distinguish these two cases. A retrospective extraction tool cannot determine from the absence of a block whether the assumption held or the record was omitted. This is the "no news is good news" problem: silence is not interpretable as a signal. For Tier 3 sessions spanning many milestones, the proportion of silently omitted annotations can be substantial, and there is no detection mechanism.

*Retrospective extraction compatibility: Partial.* Extraction requires parsing all milestone records and detecting the presence or absence of the delimiter. Extraction tools must handle variable formatting (agents may vary delimiter syntax slightly), and the absence of a block must be treated as ambiguous rather than informative. Cross-session extraction — finding all partially-contradicted assumptions across multiple sessions — requires parsing every log record in every session, not a targeted type query.

*Discipline mechanism: None.* The annotation is optional by design. There is no structural consequence for omitting it. Discipline depends entirely on agent prompt compliance, which is known to be imperfect across session boundaries and agent instances.

*False-positive rate: Low.* When an annotation block is present, it is a reliable signal that the agent made an assumption observation. The false-positive rate (annotations that do not reflect actual assumption events) is low because the structured format constrains the agent to report specific fields rather than general narrative.

**Assessment summary:** Alternative A is low-cost and human-readable, but its high false-negative rate and ambiguous absence interpretation make it inadequate for the retrospective extraction use case and for the resuming-agent disambiguation use case. It is most useful as a component of a larger mechanism, not as the sole mechanism.

---

### Alternative B: Dedicated Tool Call — `flag_model_update(assumption, status, direction)`

**Description.** A new tool is added to the agent interface: `flag_model_update`. The tool accepts structured arguments (assumption identifier, status code, direction of change) and produces a typed event in the session event stream — structurally distinct from execution records and typed as `model_update_event`. Calling the tool is how the agent records an in-flight assumption change. The tool's output is machine-queryable by type.

**Tool signature (conceptual):**

```python
flag_model_update(
    assumption: str,          # which assumption is being updated
    status: Literal["holding", "partially-holding", "contradicted"],
    direction: str,           # brief description of direction of change
    prior_confidence: Literal["high", "moderate", "low"],
    updated_confidence: Literal["high", "moderate", "low"],
    downstream_affected_steps: int | str   # count or "none"
)
```

**Advantages:**
- Clean event stream: model-update events are structurally distinct from execution records; retrospective extraction queries one event type without parsing narrative text
- Unambiguous absence: if `flag_model_update` was not called at a milestone, no assumption changed by definition (assuming the agent followed the protocol). The absence is interpretable.
- False-negative rate: Low (conditional on agent compliance). The tool's explicit invocation requirement creates a clear record-or-not-record distinction.
- Retrospective extraction compatibility: Full. All `model_update_event` records are directly queryable.

**Disadvantages and Risks:**

*Discipline mechanism: None.* This is the critical weakness of Alternative B. `advance_workflow` is called because it GATES the next step — the workflow cannot proceed to milestone N+1 without calling it. `flag_model_update` gates nothing. Its omission has no immediate structural consequence. An agent can proceed to the next milestone without calling `flag_model_update` at the current one, and the workflow will not detect this. The discipline mechanism is entirely prompt-level: the agent must remember to call the tool, must judge correctly whether an assumption event occurred, and must invoke the tool with correct arguments. All three of these requirements can fail silently.

Compared to `advance_workflow`: the gating function of `advance_workflow` provides a structural enforcement mechanism. `flag_model_update` is a proactive tool — the agent calls it when it judges it should, not because the workflow requires it. Proactive tools without structural gates are known to have lower compliance rates than gated tools, particularly in long sessions where attentional resources are consumed by the primary task.

*Interface growth.* Adding a new tool to the agent interface increases cognitive load at tool selection time. Agents must correctly choose between calling `flag_model_update` (for assumption events) and not calling it (for non-assumption events). In practice, agents may err toward under-calling (omitting in ambiguous cases) or over-calling (annotating events that do not meet the threshold).

*Human readability: Poor.* Tool call metadata is not human-readable in the session log without a viewer that renders structured event records. A human reviewing the log to understand mid-session assumption changes must either consult a rendered view or interpret raw tool call records.

*False-positive rate: Low.* When `flag_model_update` is called, it is a reliable signal.

**Assessment summary:** Alternative B has the cleanest machine-queryable record and the most unambiguous absence interpretation, but its fundamental weakness is that it lacks any structural enforcement mechanism. It relies entirely on agent prompt compliance for a proactive judgment — the exact condition where compliance is least reliable. Its human readability is also the lowest of the three alternatives.

---

### Alternative C: Mandatory Assumption Checkpoint Sub-Step in Tier 2 and Tier 3 Milestone Completion Protocol

**Description.** Each milestone completion in Tier 2 and Tier 3 workflows includes a mandatory checkpoint sub-step, encoded in the workflow definition itself — not in tool specifications or log format alone. The checkpoint text is embedded in the milestone completion instructions and specifies exactly what the agent must produce before the milestone is marked complete. The output goes to two destinations: (a) a new `## Assumption Checkpoint` section in the workflow state document (human-readable, co-located with execution progress), and (b) a structured annotation in the session log entry (machine-queryable). The two-destination pattern separates readability (workflow state document) from queryability (session log annotation) while maintaining both.

**The workflow structure enforcement.** The workflow state document's `## Assumption Checkpoint` section serves a structural function: its ABSENCE is detectable. A reviewer or resuming agent reading the workflow state document can observe that the checkpoint section was not filled for a given milestone — not merely that it might have been forgotten, but that it is structurally missing in a document whose milestone format includes a checkpoint section. This transforms the absence from ambiguous to detectable.

**Advantages:**
- Discipline via workflow structure: the checkpoint section is a defined component of the milestone format; its absence is visible to any reader of the workflow state document, not just to extraction tools
- Human readability: Excellent. The checkpoint section appears in the workflow state document co-located with execution progress; it is encountered in the natural reading flow by humans and resuming agents alike
- Machine queryability: the structured annotation in the session log is machine-queryable, providing the retrospective extraction value of Alternative B without requiring a new tool
- Two-destination pattern: separates human readability (workflow state document) from machine queryability (session log), which is the core observability engineering insight — different readers need different formats from the same event
- Low implementation cost: no new tools required; changes are to workflow definitions and agent prompts

**Disadvantages and Risks:**

*Cognitive load at milestone completion.* Each milestone completion requires the agent to produce two outputs: the execution record and the checkpoint annotation. For routine milestones where the assumption held exactly as expected, this adds overhead that produces a "routine checkpoint — no change" annotation rather than useful new information. This overhead is real but bounded; the fixed cost per milestone is small relative to the value of the mandatory record.

*Automatic availability for retrospective extraction.* The checkpoint output in the workflow state file is not automatically available for retrospective extraction without integration. `summarize_session.py` must know to read checkpoint sections from the workflow state document, or the structured annotation in the session log must be the extraction target. If extraction relies on the session log annotation and the workflow state checkpoint is only for human readability, the two-destination pattern requires consistent annotation in both destinations — which requires agent compliance for the session log annotation specifically.

*False-negative rate: Low (but not zero).* The visible absence of the checkpoint section in the workflow state document is a strong structural mechanism, but an agent could fill the section with a placeholder without completing the analysis. This is a lower risk than Alternative A's silent omission (the section is present but nominal) but is not zero.

*False-positive rate: Low.* Same as Alternatives A and B.

**Assessment summary:** Alternative C has the strongest discipline mechanism of the three alternatives — the visible absence of a structural section — and the best human readability by the co-location of checkpoint data with execution progress. Its retrospective extraction compatibility is full when the session log annotation is used as the extraction target. The overhead of the mandatory checkpoint is real but justified by the value of the consistent record.

---

## 5. Comparative Analysis Table

| Dimension | Alt A (Log Annotation) | Alt B (Tool Call) | Alt C (Checkpoint Protocol) |
|-----------|----------------------|------------------|---------------------------|
| Implementation cost | Low | Medium | Low |
| False-negative rate | High (absence ambiguous) | Low (absence = no change, conditional on compliance) | Low (absence visible in workflow state doc) |
| False-positive rate | Low | Low | Low |
| Retrospective extraction | Partial (parsing required; absence ambiguous) | Full (typed events; direct query) | Full (structured annotation in session log; typed) |
| Human readability | Good (in-context, same doc) | Poor (tool call metadata; requires rendering) | Excellent (co-located in workflow state doc; natural reading flow) |
| Discipline mechanism | None (prompt-only; silent omission undetectable) | None (proactive, no gate; omission undetectable) | Workflow structure (section absence is detectable by any reader) |
| Absence interpretation | Ambiguous (omission vs. no event) | Unambiguous (no change, conditional on compliance) | Detectable (section missing vs. section present) |
| Overhead per milestone | Minimal (when done) | Minimal (when done) | Fixed cost per milestone regardless of event type |
| Resuming agent utility | Low (must parse narrative) | Moderate (typed event, but tool-log not primary doc) | High (checkpoint section in primary workflow state doc) |
| Cross-session aggregation | Poor (no stable schema) | Excellent (stable type field) | Excellent (stable JSON schema in session log annotation) |

---

## 6. Recommendation

**Recommended approach: Alternative C (mandatory checkpoint sub-step) with Alternative A's structured log annotation embedded within the mandatory checkpoint flow.**

This is not a combination of two independent mechanisms. Alternative A's structured annotation is adopted as the machine-queryable output of Alternative C's mandatory checkpoint. The annotation does not exist as an optional add-on; it is one of the two mandatory outputs of the checkpoint step. The result is a two-destination mandatory checkpoint: one output to the workflow state document (human-readable section), one output to the session log (structured JSON annotation).

### 6.1 Why Mandatory Checkpoint Over Proactive Tool

Alternative B's failure mode is that it lacks a structural gate. The `advance_workflow` tool gates milestone progression — you cannot proceed without calling it. `flag_model_update` gates nothing. The entire discipline mechanism depends on prompt compliance for a proactive judgment in the middle of task execution, where attentional resources are consumed by the primary task. This is the worst possible condition for reliable prompt compliance.

Alternative C's mandatory checkpoint is enforced differently: it is embedded in the milestone completion instructions as a required step, not a recommended one. The output appears in the workflow state document as a structurally defined section. If the section is absent, any reader of the workflow state document can observe its absence — not through extraction tooling, but through direct observation. This is a significantly stronger enforcement mechanism than a proactive tool call without consequences for omission.

The structural gate is not perfect — an agent could fill the checkpoint section nominally — but the visibility of the section to human reviewers and resuming agents creates an accountability mechanism that a silent tool-call omission does not.

### 6.2 Why Two Destinations

The observability engineering literature establishes clearly that the human reader and the machine query have different needs. The workflow state document is the primary document consulted by humans and resuming agents reading execution progress; if assumption state is only in the session log, it is available for extraction but not for casual review. The session log structured annotation is the primary artifact for retrospective extraction; if assumption state is only in the workflow state document's narrative section, it is human-readable but not cross-session queryable.

The two-destination pattern serves both readers from a single agent action: write the checkpoint, produce two outputs. The human-readable output goes to the workflow state document; the machine-queryable output goes to the session log. Neither destination requires the reader to consult the other.

### 6.3 Why the Structured Annotation Must Be Within the Mandatory Flow

If the structured session log annotation is optional — produced by the agent if it chooses to, in addition to the mandatory workflow state checkpoint — its false-negative rate reverts to Alternative A's high level. The annotation must be a required output of the mandatory checkpoint step, not an encouraged addition. The checkpoint prompt (see Section 7) specifies both outputs as required.

### 6.4 Separation of Readability from Queryability

This is the core observability engineering insight applied to workflow design. A single record format cannot optimally serve both human narrative comprehension and machine query efficiency. A system that attempts to serve both with a single format produces records that are too structured for easy human reading and too narrative for reliable machine querying. The two-destination pattern solves this by allowing each destination to optimize for its reader. The cost is a second output from the checkpoint step; the benefit is that both readers get the format they need from the same agent action.

---

## 7. Mandatory Checkpoint Prompt Specification

### 7.1 Checkpoint Step Text

The following text is to be embedded verbatim in the milestone completion instructions for all Tier 2 and Tier 3 workflow definitions. It should appear as the final sub-step of every milestone completion block, before the milestone is marked complete.

---

**ASSUMPTION CHECKPOINT (required before marking this milestone complete)**

Before recording this milestone as complete, perform the following two-step checkpoint:

**Step 1 — Workflow state document update.** Add the following section to the workflow state document immediately below the current milestone's completion record:

```
## Assumption Checkpoint — [Milestone Name]
### Assumption Status: [holding | partially-holding | contradicted]
### Summary: [1-2 sentences: what changed, or confirmation that no change occurred]
### Prior Confidence: [high | moderate | low]
### Updated Confidence: [high | moderate | low]
### Trigger: [what observation prompted this update, or "routine checkpoint — no change"]
```

If the primary working assumptions from session start are holding exactly as modeled, write `holding` for status and `routine checkpoint — no change` for trigger. Do not omit this section because no change occurred — a holding confirmation is a valid checkpoint entry.

**Step 2 — Session log structured annotation.** Append the following JSON annotation to the session log entry for this milestone:

```json
{
  "type": "assumption_checkpoint",
  "milestone_id": "[milestone identifier]",
  "assumption_status": "[holding|partially-holding|contradicted]",
  "summary": "[max 2 sentences]",
  "prior_confidence": "[high|moderate|low]",
  "updated_confidence": "[high|moderate|low]",
  "trigger": "[description of observation or 'routine-no-change']",
  "downstream_affected_steps": "[estimated count or 'none']"
}
```

Both outputs are required. A milestone is not complete until both the workflow state checkpoint section and the session log annotation have been written.

---

### 7.2 Workflow State Document Section Format

```
## Assumption Checkpoint — [Milestone Name]
### Assumption Status: [holding | partially-holding | contradicted]
### Summary: [1-2 sentences describing what changed or confirming no change]
### Prior Confidence: [high | moderate | low]
### Updated Confidence: [high | moderate | low]
### Trigger: [what observation prompted this update, or "routine checkpoint — no change"]
```

**Field definitions:**

- `Assumption Status`: The overall status of the session's primary working assumptions after this milestone. `holding` means the model held as constructed at session start. `partially-holding` means the model was correct in its broad direction but wrong in specific respects that affect some downstream steps. `contradicted` means a core component of the model was wrong in a way requiring replanning.

- `Summary`: One to two sentences. For `holding` status: which specific assumption was most directly tested by this milestone's work and how it was confirmed. For `partially-holding`: which assumption was partially wrong and which downstream steps are affected. For `contradicted`: which assumption was wrong and what replanning is required.

- `Prior Confidence`: The confidence level in the relevant assumptions before this milestone's work began. Assess as `high` (strong prior evidence and consistent with session model), `moderate` (reasonable prior evidence but with acknowledged uncertainty), or `low` (weak prior evidence; assumption made by default or under constraint).

- `Updated Confidence`: The confidence level after this milestone's observations. May increase (if assumption was confirmed strongly), decrease (if partially contradicted), or reach the lowest meaningful level (if fully contradicted, in which case the field should read `low` and status should be `contradicted`).

- `Trigger`: The specific observation at this milestone that prompted the assumption assessment. For `holding` with no change: `routine checkpoint — no change`. For all other statuses: a one-sentence description of the specific evidence (what output, what behavior, what discovery) that drove the assessment.

### 7.3 Session Log Structured Annotation Format

The machine-queryable version of the checkpoint, appended to the session log entry for the milestone. Delimited by triple-backtick fences with the `json` language tag to support human scanning while remaining machine-parseable.

```json
{
  "type": "assumption_checkpoint",
  "milestone_id": "[milestone identifier — e.g., 'milestone-2-schema-design']",
  "assumption_status": "[holding|partially-holding|contradicted]",
  "summary": "[max 2 sentences matching the workflow state Summary field]",
  "prior_confidence": "[high|moderate|low]",
  "updated_confidence": "[high|moderate|low]",
  "trigger": "[description of observation or 'routine-no-change']",
  "downstream_affected_steps": "[estimated count of affected downstream steps or 'none']"
}
```

**Field definitions (machine-queryability notes):**

- `type`: Always `assumption_checkpoint`. This is the query key for retrospective extraction. `summarize_session.py` should extract all records where `type == "assumption_checkpoint"` and compute the proportion of `holding`, `partially-holding`, and `contradicted` events per session as a calibration metric.

- `milestone_id`: A stable identifier for the milestone, consistent with the milestone identifiers used in the plan and workflow state document. Use the milestone name in kebab-case with a numeric prefix matching its position in the plan sequence.

- `assumption_status`: Enumerated to three values only. Extractors should treat any value outside this set as a data quality error.

- `downstream_affected_steps`: Integer count of steps in the remainder of the plan that must change due to this assumption event, or `"none"` if no downstream steps are affected. For `holding` status this is always `"none"`. For `contradicted` status this should reflect the full replanning scope.

**Annotation placement in session log.** The JSON annotation block should appear at the end of the milestone's session log entry, after the narrative execution record, delimited by triple-backtick code fences with the `json` language tag. This placement allows human readers to read the narrative first and encounter the structured annotation at the end, consistent with progressive disclosure principles.

### 7.4 Worked Example: Assumption Partially Contradicted

**Scenario.** A Tier 3 session is implementing a new data processing pipeline. The session model at start estimated that the schema validation step (Milestone 2) would be straightforward — the schema was expected to be stable and well-documented based on prior session memory. During Milestone 2's work, the agent discovers that one data source has an undocumented optional field that creates validation ambiguity. The primary approach (strict schema enforcement) is still viable, but requires an additional preprocessing step to normalize the optional field before validation. Full replanning is not required, but the subsequent milestone (Milestone 3: integration testing) will take longer than estimated because the preprocessing step must be implemented and tested first.

**Workflow state document checkpoint section:**

```
## Assumption Checkpoint — Milestone 2: Schema Validation

### Assumption Status: partially-holding

### Summary: Schema validation approach is viable, but an undocumented optional field
in the events data source requires a preprocessing normalization step before strict
validation can run. Milestone 3 (integration testing) will require additional time
to implement and test this step.

### Prior Confidence: high

### Updated Confidence: moderate

### Trigger: Discovery during Milestone 2 that `events.metadata.source_region` is an
optional field not present in the documented schema; strict validation rejects records
where this field is absent, requiring a pre-pass to inject a default value.
```

**Session log structured annotation:**

```json
{
  "type": "assumption_checkpoint",
  "milestone_id": "milestone-2-schema-validation",
  "assumption_status": "partially-holding",
  "summary": "Schema validation approach viable but requires additional preprocessing step for undocumented optional field. Milestone 3 scope expands by approximately one additional implementation step.",
  "prior_confidence": "high",
  "updated_confidence": "moderate",
  "trigger": "events.metadata.source_region is optional and absent in ~12% of records; strict validation rejects these records; normalization pre-pass required",
  "downstream_affected_steps": "1"
}
```

**Notes on this example:**

- `assumption_status` is `partially-holding` because the primary approach (strict schema validation) is retained; the approach is not wrong, it is more complex than expected in one specific respect.
- `downstream_affected_steps` is `"1"` because Milestone 3 is the only downstream milestone directly affected; the additional preprocessing step is contained within the Milestone 3 scope.
- `prior_confidence` is `"high"` because the session model was built on strong prior evidence (documented schema, prior session memory of stable data sources). The partial contradiction reduces confidence to `"moderate"` — the approach is still right but the environment is less predictable than modeled.
- The trigger is specific and evidence-grounded: a specific field name, a specific prevalence rate, and a specific consequence. This level of specificity is required for the trigger field to be useful in retrospective analysis.
- The checkpoint is MANDATORY under the taxonomy (Type 2: Assumption Partial Contradiction) and under the DDM/ADWIN rule (the assumption was contradicted — a confirmed drift event regardless of the magnitude of its downstream effect).

---

## 8. DDM/ADWIN Mandatory vs. Discretionary Threshold

### 8.1 Proposed Rule

A checkpoint annotation is MANDATORY (the agent must complete the full two-step checkpoint process before marking the milestone complete) when ANY of the following conditions are met:

**Condition 1 — Complexity delta (drift threshold).** Actual step completion time exceeds estimated time by more than 2x, OR actual step count required to achieve the milestone outcome exceeds the plan's estimate by more than 20%.

*DDM/ADWIN rationale.* Under DDM, a 2x overrun corresponds to approximately 3 standard deviations of divergence from the model's expectation given typical estimation variance. This is the confirmed drift level, not the warning level. At 2x, the probability that the overrun is within normal noise is less than the DDM drift threshold probability, meaning the model's complexity estimate is wrong with high statistical confidence. A 20% step count overrun is similarly beyond the noise band for scope estimation — within-scope variance typically runs under 10–15% for well-specified Tier 2 and Tier 3 tasks.

**Condition 2 — New hard constraint discovered.** A constraint on the work not present in INTENT.md at session start is discovered during milestone execution. "Hard constraint" means a constraint that binds: it prevents or requires a specific action regardless of agent judgment (a technical dependency that forces a specific implementation approach, a user-stated boundary that limits scope, a systemic requirement that changes the deliverable's form).

*DDM/ADWIN rationale.* A new hard constraint is a point event — a single observation that falsifies the model's assumption of constraint completeness. Under ADWIN, a single point event with definitive impact does not require a window of observations to trigger drift detection; the impact is immediate and bounded. The constraint set changing is not a noisy signal requiring statistical smoothing; it is an unambiguous change in the environment.

**Condition 3 — Assumption contradicted (partially or fully).** The milestone's work produces evidence that a working assumption is wrong in any direction — whether the approach is less viable than expected, the complexity is materially different, the user preference model is wrong, or the constraint set is different.

*DDM/ADWIN rationale.* A contradiction event is definitionally a drift event — the model's prediction was falsified by observation. DDM would classify this as confirmed drift regardless of the magnitude, because the nature of the event (assumption falsification) is qualitatively different from mere variance around the prediction.

**Condition 4 — Scope expansion beyond 20% of original task count.** The number of tasks required to complete the session's objective has expanded by more than 20% relative to the original plan.

*DDM/ADWIN rationale.* A 20% scope expansion is the point at which the original plan's sequencing and resource allocations are no longer valid guides for the remaining work. Below 20%, scope growth is within the noise band of plan estimation; above 20%, the plan needs active revision. This threshold is consistent with DDM's warning-to-drift transition: warning at 10–15% (elevated but not confirmed drift), confirmed drift at 20% and above.

### 8.2 Within Noise Band — Discretionary

The following conditions are within the noise band of normal execution variance. A checkpoint annotation is DISCRETIONARY — the agent should exercise judgment about whether an annotation adds meaningful information:

- **Actual time is 1.5x–2x estimated.** This is the DDM warning level: elevated discrepancy that may indicate early-stage drift, but is not statistically confirmed drift. The agent should note the elevated discrepancy in the narrative record. A structured checkpoint annotation is recommended if the agent judges the overrun is likely to continue into subsequent milestones.

- **Minor soft constraint adjustments discovered.** A soft constraint (a preference or guideline, not a binding requirement) turns out to apply more narrowly or more broadly than modeled. If the adjustment affects no downstream steps and requires no replanning, annotation is discretionary.

- **Assumption confirmed at different confidence than expected.** The assumption held, but the evidence was weaker than expected (confirmation at moderate confidence when high confidence was anticipated). This is a calibration signal worth recording if the agent has a basis for believing the lower confidence is likely to persist.

### 8.3 Threshold Summary Table

| Condition | Threshold | Classification | DDM/ADWIN Analog |
|-----------|-----------|----------------|------------------|
| Completion time overrun | Greater than 2x estimated | MANDATORY | Confirmed drift (>3 standard deviations) |
| Completion time overrun | 1.5x–2x estimated | DISCRETIONARY | Warning level (2–3 standard deviations) |
| Step count overrun | Greater than 20% of plan | MANDATORY | Confirmed drift |
| New hard constraint | Any discovery | MANDATORY | Point event; constraint set falsified |
| New soft constraint | Any discovery | DISCRETIONARY | May be noise |
| Assumption contradiction | Any contradiction | MANDATORY | Falsification event |
| Scope expansion | Greater than 20% original task count | MANDATORY | Confirmed drift |
| Assumption confirmation | Any confirmation | DISCRETIONARY | Within noise band (model correct) |
| Confidence level change only | Without status change | DISCRETIONARY | Warning level; calibration signal |

---

## 9. Cross-References

### 9.1 Calibration Linkage — research-q3-confidence-format.md

Each checkpoint annotation carries `prior_confidence` and `updated_confidence` fields. These two fields are the per-milestone data inputs for the confidence calibration system described in `research-q3-confidence-format.md`.

The calibration measurement question that `research-q3-confidence-format.md` must address is: does the agent's prior confidence at each milestone accurately predict the probability of assumption confirmation? A session with consistently `high` prior confidence that produces frequent `partially-holding` or `contradicted` events is a session where the confidence format is miscalibrated — the agent was overconfident. Aggregating `prior_confidence` and `assumption_status` pairs across checkpoints and sessions produces the calibration data needed to answer this question.

The two documents define complementary halves of the confidence tracking system: this document defines when and how to record confidence changes (the checkpoint mechanism); `research-q3-confidence-format.md` defines how to represent and aggregate those confidence values in a format useful for calibration measurement.

**Implementation note.** The `summarize_session.py` retrospective extraction step should extract all `assumption_checkpoint` records from the session log and compute: (a) the proportion of `high`/`moderate`/`low` prior confidence entries that resulted in `holding` versus `partially-holding`/`contradicted` outcomes, and (b) the mean confidence shift per checkpoint. These two metrics are the per-session inputs to the calibration record described in `learning-evolution.md`'s calibration section.

### 9.2 Alignment with Autonomous Revision Records — research-q4-intent-revision-authority.md

The checkpoint annotation's schema (assumption, trigger, downstream scope, reversibility-adjacent fields) should be designed to align with the autonomous revision record schema described in `research-q4-intent-revision-authority.md`. Both are instances of a "model-state-change record" type: the checkpoint records a change in the agent's task model; the autonomous revision record records a change in the authoritative intent document.

The shared vocabulary that enables joint retrospective analysis includes:
- `trigger`: both record types should use the same trigger field semantics (the specific observation that prompted the model change)
- `downstream_affected_steps`: the checkpoint record and the revision record should use compatible representations of downstream scope, so that joint queries can identify sessions where both model changes and intent revisions occurred within the same execution window
- Confidence fields: both record types should use the same `high/moderate/low` vocabulary

**Implication for schema design.** When `research-q4-intent-revision-authority.md` defines its autonomous revision record schema, it should treat the `assumption_checkpoint` schema in this document as the reference. Fields that appear in both records should have identical names and value vocabularies to support joint retrospective queries of the form: "find all sessions where an assumption was contradicted AND an intent revision was made, ordered by the time gap between the two events."

---

## 10. Provenance and Sources

This section lists all named theories, researchers, frameworks, and publications cited in this document. Sources are categorized by type: established research (peer-reviewed or widely validated), practitioner documentation (industry specifications, engineering documentation), and design synthesis (conclusions drawn by this document from the research).

### 10.1 Established Research

**Altmann, E. G. and Byrne, M. D.** Multiple publications, approximately 2000–2016. Activation-based prospective memory model. Principal theoretical statement: Altmann and Byrne (2002), "The Strategic Use of Memory for Frequency and Recency." Psychological Review. Cited in Sections 1.5, 2.1.

**Gama, J., Medas, P., Castillo, G., and Rodrigues, P.** (2004). "Learning with Drift Detection." SBIA — Brazilian Symposium on Artificial Intelligence. Cited in Sections 2.3, 3, 8.

**Bifet, A. and Gavalda, R.** (2007). "Learning from Time-Changing Data with Adaptive Windowing." SIAM International Conference on Data Mining. Cited in Sections 2.3, 3, 8.

**Mark, G., Gudith, D., and Klocke, U.** (2008). "The Cost of Interrupted Work: More Speed and Stress." ACM CHI Conference on Human Factors in Computing Systems. Cited in Section 2.5.

**Mark, G.** (2005, 2016, 2018). Multiple publications on interruption cost, attentional recovery, and notification response rates. Cited in Section 2.5.

**Helland, P.** (2015). "Immutability Changes Everything." CIDR — Conference on Innovative Data Systems Research. Cited in Section 2.2.

### 10.2 Practitioner Documentation

**Young, G.** Event sourcing and CQRS patterns, approximately 2010–present. Distributed in presentations, blog posts, and conference talks. Not a single paper; attributed as the originating practitioner of the event sourcing pattern. Cited in Section 2.2.

**Fowler, M.** "Event Sourcing." martinfowler.com, published approximately 2005, updated through approximately 2019. Cited in Section 2.2.

**OpenTelemetry Logs Data Model.** Cloud Native Computing Foundation (CNCF). Specification developed from 2019; log signal reached stable status 2023. Available at opentelemetry.io/docs/specs/otel/logs/data-model/. Cited in Section 2.4.

**Sridharan, C.** (2018). "Distributed Systems Observability." O'Reilly Media. Cited in Section 2.4.

**Elastic Common Schema (ECS).** Elasticsearch / Elastic NV. Field naming convention for structured log records. Updated through 2024. Available at elastic.co/guide/en/ecs/current/. Cited in Section 2.4.

**Apple Human Interface Guidelines — Notifications.** Apple, Inc. Updated through 2024. Cited in Section 2.5.

**Google Material Design — Notification guidelines.** Google, LLC. Updated through 2024. Cited in Section 2.5.

### 10.3 Design Synthesis

The following conclusions are design synthesis by this document — derived from but not directly stated in the cited research. They represent the application of research findings to the specific design problem of the poc-workflow in-flight learning mechanism.

**The 2x completion time threshold as the mandatory checkpoint trigger.** Derived from DDM's drift detection criterion (approximately 3 standard deviations of divergence from model expectation), translated to a concrete ratio applicable to session execution time estimates. The 2x figure is this document's translation; DDM's original parameterization is in terms of classification error rates, not time ratios. (Sections 8.1, Condition 1)

**The 20% scope expansion threshold.** Derived by analogy from DDM's warning-to-drift transition applied to step count variance. The specific 20% figure is this document's operationalization. (Section 8.1, Condition 4)

**The two-destination pattern (workflow state document and session log annotation) as the implementation recommendation.** Derived from OpenTelemetry's readability-queryability separation and from progressive disclosure principles in HCI notification design. The specific two-file implementation is design synthesis. (Sections 6, 7)

**The "absence is detectable" framing for Alternative C.** Derived from structural enforcement principles in workflow design; the visible-absence mechanism is a design synthesis from the comparison of gated versus proactive tool invocations in the poc-workflow architecture. (Sections 4, 6.1)

**The prospective memory framing of the session log as deferred-intention storage.** The connection between Altmann-Byrne prospective memory and session log design is design synthesis; Altmann and Byrne do not discuss session logs or AI agent systems. (Section 1.5)
