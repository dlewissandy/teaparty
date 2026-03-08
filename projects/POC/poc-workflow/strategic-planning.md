# Strategic Planning: Two Levels That Must Not Collapse Into One

## Two Levels of Planning

Strategic planning and tactical planning are not points on a continuum — they are categorically different activities, and conflating them is the most reliable way to produce work that is internally coherent and externally wrong.

Strategic questions are: What are we building, and why? What key decisions must be made before work begins? What assumptions is this entire approach betting on, and what would invalidate them? Tactical questions are different in kind: How do we decompose the work? What can be parallelized? What are the dependencies, and who owns each piece?

The conflation failure mode is a plan that is tactically coherent but strategically wrong. Every task gets done. The outcome misses the point. This failure is harder to detect than simple failure and considerably more expensive to correct, because partial credit thinking makes it resistant to acknowledgment. When a team executes cleanly against the wrong objective, the natural response is to defend the execution rather than question the direction. The work was good. The plan was followed. The problem is upstream, and upstream is where no one is looking.

In the POC architecture, the uber lead's role is inherently strategic. The uber lead delegates; it does not produce deliverables. Liaisons bridge to subteams via relay.sh. This two-level hierarchy — strategic coordination at the uber level, tactical execution at the subteam level — is not a performance preference. It is a structural guarantee that someone is always holding the strategic frame while the tactical work proceeds. When the uber lead starts making tactical decisions — which specific sections to include in a chapter, how exactly to format an output — something has gone wrong in the delegation model. The hierarchy has collapsed, and with it the guarantee.

## The First-Move Problem

Early autonomous decisions shape the entire trajectory of complex work. Architectural choices, naming conventions, structural decisions made in the first hour constrain every decision afterward in ways that are rarely visible at the time and expensive to undo later. This is why strategic planning cannot be skipped or rushed — not because planning is virtuous in the abstract, but because the cost of a first-move error compounds through every subsequent decision that assumes it.

Strategic planning should explicitly identify high-leverage decision points and assign decision authority for each before execution begins. The three-tier model — autonomous, notify, escalate — provides the right vocabulary. Autonomous means the agent decides based on the existing spec. Notify means the agent decides and surfaces the choice in its result so it can be reviewed without blocking execution. Escalate means the work stops until a human decides. The assignment of decisions to tiers is itself a strategic act, and it should happen at planning time, not execution time.

The INTENT.md decision boundaries section is the right place to encode this, but it needs to distinguish strategic decisions from tactical ones. A stop rule about never committing directly to main is a tactical boundary — violating it causes a recoverable local problem. A stop rule about not changing the document's intended audience from developers to executives without consultation is strategic — violating it silently invalidates the entire body of work produced under the wrong assumption. These are not the same category of constraint, and treating them identically either over-escalates tactical decisions or under-escalates strategic ones.

The decision matrix from the detailed design makes this operational: irreversible decisions with organizational impact always escalate. First-move architectural decisions often fall into exactly this cell. The reversibility axis is the key test. If the decision can be corrected cheaply later, it can be made autonomously now. If correcting it requires redoing substantial downstream work, the decision cost has been misassigned.

## Early Proof Points

Before committing to full execution, identify the smallest possible validation that confirms the approach is correct. This is not a delay tactic — it is a risk management decision with a clear expected value calculation. If the proof point fails, the cost of redirection is minimal. If it passes, confidence in the plan increases substantially and subsequent decisions can be made with more autonomy. The alternative is discovering the assumption failure at delivery.

In the POC architecture, this principle has concrete expressions. Write one section before committing to a full document structure — this verifies the audience, tone, and depth assumptions before eight more sections are produced in the wrong register. Prototype one relay dispatch before parallelizing across six liaisons — this verifies that the subteam task description is clear enough before multiplying any error in it. Verify data availability before building the analysis pipeline — irreversible time spent in construction is the cost of skipping this check.

The proof point discipline is risk management built into the planning phase, not added overhead on top of it. Plans that skip proof points are not leaner — they have simply deferred the validation cost to the most expensive possible moment, which is when delivery is expected and course correction requires rewinding completed work.

## Decision Tree Mapping

Strategic planning should map the decisions that will arise during execution before execution begins. The output is not a general principle about escalation posture — it is a specific answer to specific questions that will otherwise be resolved inconsistently by different agents acting on different interpretations of the same spec.

This operationalizes the INTENT.md decision boundaries section into something executable. The decision about how much technical depth to include in a section, for example, arises in every writing dispatch in the POC. Is this autonomous — the writer decides based on the audience spec? Notify — the writer decides and surfaces the choice in the result? Or escalate — the writer pauses and confirms? The plan should answer this once, before execution begins, rather than leaving it to each writer to interpret independently. Unmapped decisions create execution-time escalations that could have been resolved at planning time. These are the most expensive escalations because they interrupt flow at the moment it is most costly to interrupt it.

| Decision | Likely Values | Escalation Threshold | Authority |
|---|---|---|---|
| Technical depth in a section | Light overview / moderate depth / deep reference | Audience spec is ambiguous or contradicted by content | Writer decides autonomously based on spec; notify if departing from it |
| Audience shift mid-document | Developers / technical leads / executives | Any shift from the specified audience | Escalate to uber lead |
| Section restructuring during drafting | Add section / merge sections / reorder / remove | Structural changes affecting downstream sections or other dispatches | Notify; escalate if cross-dispatch impact |
| Format deviation from template | Prose / bullets / tables / code blocks | Deviations that change how editorial processes the output | Notify |
| Scope expansion beyond original dispatch | Additional examples / extended analysis / new sub-topic | Any expansion changing word count or time estimate by more than 20% | Escalate |

## Parallelization Strategy

The POC's relay.sh dispatch model enables genuine parallelism, but strategic planning must identify which work streams are actually parallel before execution begins. The distinction matters because misclassifying a dependency as a parallelism creates a blocked pipeline that only becomes visible at the point of collision.

True parallel work has no shared state and no ordering dependencies — maximize throughput. In the POC, art and writing dispatches for different chapters are often truly parallel. Neither depends on the other's output, and running them concurrently costs nothing.

Fan-out/fan-in is the most common pattern in the POC: multiple independent streams that must be synthesized at a defined merge point. Multiple writing dispatches produce chapters that editorial must then review together. The fan-in — editorial review — cannot start until all fan-out streams complete. Strategic planning should name this constraint explicitly, because the uber lead autonomously sequences dependent work — writing first, then art, then editorial review — without being prompted to do so. That sequencing should be encoded in the plan, not rediscovered at runtime.

Sequential gates are a different category: B cannot start until A is verified. In the POC, a writing dispatch must complete before an art dispatch can reference its content. The gate is not just ordering — it is a dependency on verified output, not merely completed output. The distinction matters when an early dispatch produces something that needs revision. Strategic planning that identifies sequential gates also identifies which revision cycles block downstream work.

## Plan Revision Cycles

Plans are working hypotheses. They should be revised when new information invalidates a key assumption — not when execution turns out to be harder than expected. The distinction is between genuinely new information and the normal difficulty of doing the work.

Legitimate triggers for mid-execution plan revision are: discovery of a constraint that invalidates a key assumption, a proof point failing, or a scope change from the user. Each of these changes what the plan was predicting. Legitimate triggers for runtime improvisation without plan revision are: local optimizations that do not change the overall structure, and filling in tactical details not specified in the plan. These are expected during execution, not deviations from it.

The distinction matters because plan revision at the strategic level requires re-confirming intent with the human. Runtime improvisation does not. Agents that revise the strategic plan autonomously — changing the document's audience, restructuring the overall architecture, dropping a planned work stream — have exceeded their decision authority regardless of whether the revision was locally sensible. Agents that escalate tactical details to the human are wasting coordination bandwidth on decisions they were already authorized to make. The open questions surfaced during intent gathering are an active handoff to the planning phase precisely because the planning phase is where decision authority gets assigned. Once assigned, it should be exercised.
