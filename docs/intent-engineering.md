# Intent: Automated Intent Engineering Experience

## Why This Exists

AI agent systems operate on a plan-execute model: the human provides a request, the agent plans how to fulfill it, then executes. This model fails in proportion to the gap between what the human said and what the human meant. That gap contains organizational values, unstated tradeoffs, decision boundaries, domain constraints, and quality expectations that the human has internalized to the point of invisibility.

Prompt engineering tells agents what to do. Context engineering tells agents what to know. Intent engineering tells agents what to want — what to optimize for, what to protect, and what tradeoffs are acceptable. Without it, agents optimize for what they can measure and destroy what they cannot.

This project builds an AI-assisted dialog experience, constrained to under 15 minutes, that produces an intent.md file. That file becomes the governing document for all downstream planning and execution — not a suggestion, but a specification of purpose.

A core behavioral principle applies across all phases of this system: the agent brings solutions, not questions. During intent gathering, it researches the problem space and presents alternatives rather than asking open-ended questions. During planning, it investigates open questions and presents well-reasoned options for the human to choose between. During execution, escalation means presenting the situation, a recommended course of action, and the reasoning behind it — never a bare question. The agent's value is in doing the preparatory work so the human makes decisions, not does research.

Three principles govern the quality of all artifacts this system produces, including the intent.md itself:

**Every sentence must earn its place.** If removing a sentence would not change the reader's ability to understand the intent, remove it. This applies to the intent.md, to plans, and to all agent-generated output.

**Would a reasonable person find this sufficient?** Read every artifact as someone who wasn't in the room. If they cannot proceed with what they've been given, the document is incomplete.

**Bring solutions, not questions.** Never present a problem without researched alternatives and a recommendation. This applies to the agent during intent gathering, during planning, during escalation, and in every open question it surfaces.

## What The System Produces

Through collaborative conversation, the agent and human co-construct an intent.md that captures:

**The objective** — what outcome the human wants and why it matters. Not the task, but the purpose the task serves.

**Success criteria** — both quantifiable (measurable thresholds) and qualitative (values, feel, style). Qualitative criteria are first-class. They are a different kind of signal, not a lesser version of quantitative criteria.

**Decision boundaries and escalation posture** — where the agent should use its own judgment, where it should stop and consult the human, and what it must never do. This is not a static checklist. It is a narrative that captures the human's risk tolerance for this specific project, informed by the learned escalation model described below.

**Constraints** — technical, organizational, temporal, and resource boundaries the solution must satisfy.

**Open questions** — ambiguities and design decisions that cannot be resolved during intent gathering. These are not a parking lot. The planning phase must actively research each open question, develop well-reasoned alternatives, and present them to the human for decision before execution begins.

The intent.md is a prose document written in natural language, not a form with fields to fill in. Its structure should follow the shape of the problem, not a fixed template. Some projects will need extensive escalation guidance and minimal constraints. Others will be constraint-heavy with obvious objectives. The document must capture what matters, not check boxes.

## CfA State Machine

The Conversation for Action protocol is formalized as a three-phase state machine — Intent, Planning, Execution — with explicit backtrack transitions between phases. Each phase has a synthesis loop that refines artifacts through iteration, and escalation paths for human involvement. See [CfA State Machine](cfa-state-machine.md) for the complete state diagrams and transition definitions.

## Least-Regret Escalation

Every autonomous agent faces a continuous choice: act or ask. Both options carry risk. Acting when the human wanted to be consulted causes wrong work, eroded trust, and violated values. Escalating when the agent could have handled it wastes the human's time and fails to deliver on the promise of autonomy.

These failure modes are not symmetric. Their relative costs vary by organization, individual, domain, and specific decision. The agent must choose the option with the least expected regret. This requires three capabilities:

**A model of the human's risk tolerance.** This is learned by observing the human's reactions over time. When the agent acts autonomously and gets corrected, that indicates the escalation threshold was set too low. When the agent escalates and the human responds with "you should have just done that," the threshold was set too high. Both signals calibrate the model.

**A model of action cost.** Before choosing to act or ask, the agent estimates two properties of the decision: how reversible it is, and how much organizational impact it carries. High-reversibility, low-impact decisions default toward autonomy. Low-reversibility, high-impact decisions default toward escalation. What the organization considers "high-impact" is itself a learned property, not a universal constant.

**A default posture that shifts over time.** At cold start, with no observational history, the agent defaults to escalation. As it accumulates data, the threshold shifts toward autonomy in domains where the human has demonstrated consistent preferences. The agent earns autonomy through demonstrated alignment, not through configuration.

The escalation model is one of the highest-value things the institutional memory system stores (see "Relationship to Institutional Memory" below). It encodes not just what a person values but how much latitude they grant, and how that varies by domain and risk level.

## How The Conversation Works

### Cold Start (No Prior Context)

When the system has no history with this human or organization, the human is the sole source of intent. The agent:

- Conducts a responsive dialog that surfaces implicit assumptions, not a scripted questionnaire.
- Researches the solution space in real time. When the human names a technology, domain, or constraint, the agent uses web search and file access to understand what that means concretely, what its boundaries are, and what adjacent constraints the human may not have mentioned.
- Pushes back when stated intent is internally contradictory or when success criteria conflict.
- Identifies gaps: missing rationale, unspecified failure modes, absent qualitative expectations.
- Surfaces escalation preferences: "Where do you want me to use my judgment and where do you want me to stop and check?"
- Accepts documents, links, and prior conversations from the human as context sources.

### Warm Start (Accumulated Context)

Over time, the system observes how the human responds to completed work: what they correct, what they praise, what they silently accept, and what they reject. These observations accumulate into institutional memory. In warm-start mode, the agent:

- Pre-populates intent elements and escalation posture inferred from prior interactions. These are presented for confirmation, not silently assumed.
- Reduces the burden on the human, making the 15-minute constraint easier to meet as the system matures.
- Treats corrections to pre-populated intent as high-value signal that the model has diverged from reality.

## Relationship to Institutional Memory

Institutional memory, as used in this document, means the persistent store of learned organizational knowledge that accumulates across interactions. It includes observed values, decision patterns, escalation tolerance, domain constraints, and working-style preferences. This is the knowledge layer being designed in the companion project "OpenClaw Memory Architecture Research," which investigates how agentic memory systems store, index, query, and expire knowledge.

The intent engineering system is the first consumer of this memory architecture. The planning phase must account for this dependency — the memory architecture's design will constrain how intent gathering stores and retrieves learned context. The relationship is bidirectional:

**Memory informs intent.** Accumulated observations flow into the intent gathering conversation as priors that reduce the burden on the human.

**Intent informs memory.** Every intent gathering session produces new signal about what the organization values. Corrections to pre-populated intent are especially valuable because they indicate where the model has drifted.

**Escalation outcomes inform memory.** Every autonomous action that is accepted or corrected, and every escalation that proves warranted or unnecessary, becomes a calibration data point for the escalation model.

Institutional memory must operate at three scopes: individual (one person's preferences and risk tolerance), team (shared conventions and decision patterns), and organization (policies and values that apply universally). Intent gathered from an individual may conflict with team or organizational priors. The system must surface these conflicts rather than silently resolving them.

## Success Criteria

The governing metric is alignment over time: the system's ability to produce work that reflects what the human actually wanted improves with each interaction. This is not directly measurable as a single number. It manifests as a constellation of observable properties including reduction in rework, reduction in escalation errors, increased productivity, increased human satisfaction with output quality, and reduction in catastrophic negative outcomes. No single proxy captures alignment fully, and the relevant proxies will vary by organization and domain. The system is succeeding when the trend across these indicators is positive and no individual indicator is degrading.

The intent gathering conversation itself has two specific constraints: it must complete in under 15 minutes for moderate-complexity projects, and it must feel like working with a sharp colleague rather than filling out a form. The agent must demonstrate understanding of the problem space by bringing relevant research into the dialog, not just asking questions. The resulting intent.md must read as a document the human would have written themselves if they had the time and discipline to make all their implicit knowledge explicit.

## Open Questions

**Learning from downstream outcomes.** The system must learn whether completed work actually satisfied the intent, without requiring the human to fill out a survey. Passive observation of corrections is necessary but not sufficient — the human may accept mediocre work out of time pressure. Three approaches worth evaluating:
- Instrument output delivery points (file acceptance, edits, rejections, rollbacks) and treat the edit-to-acceptance ratio as a proxy signal.
- Compare intent.md success criteria against observable outcomes where possible (tests pass, deploy succeeds, no rework within a time window).
- Use lightweight periodic check-ins at natural breakpoints ("this phase is complete — does the direction still feel right?") rather than per-task surveys.
These are not mutually exclusive. The recommendation is to start with delivery-point instrumentation because it requires no human effort and produces signal immediately.

**Divergence between stated and revealed preferences.** The human may say they want X but consistently correct toward Y. Three approaches:
- Surface the contradiction explicitly during the next intent gathering session: "You've stated X in three prior intents but corrected toward Y five times. Should I update my model?"
- Weight revealed preferences more heavily than stated ones automatically, on the principle that actions are more reliable than words.
- Track both and present the divergence without auto-resolving, letting the human decide.
The recommendation is the first option. Silent auto-correction is paternalistic and risks masking a real change in organizational direction. Explicit surfacing treats the human as the authority while still bringing the observation to the table.

**Minimum viable memory architecture for warm-start.** The full institutional memory system is a large project. Three scoping options for an MVP:
- Start with the escalation model only. It has the highest value density, clear signal sources (act/ask outcomes), and a well-defined feedback loop.
- Start with per-user key-value observations ("prefers X over Y") stored in markdown alongside the escalation model. Low infrastructure cost, immediately useful for pre-populating intent.
- Start with the full OpenClaw-style hybrid search architecture from day one, accepting longer time-to-value in exchange for not having to migrate later.
The recommendation is the second option. The escalation model alone is too narrow to demonstrate warm-start value in intent gathering, but full hybrid search is premature before the observation corpus is large enough to need it.

**Domain segmentation for escalation.** The escalation model must be domain-indexed — a human may grant broad autonomy for coding but narrow autonomy for communications. Three approaches:
- Let domains emerge from observation by clustering decisions by topic and tracking tolerance per cluster.
- Pre-define domains during intent gathering by asking the human to identify areas with different risk tolerances.
- Use the intent.md project categorization as the domain index, inheriting segmentation from the work itself.
The recommendation is to start with the third option and evolve toward the first. Project-level categorization is immediately available and requires no upfront taxonomy, while emergent clustering can refine the model as data accumulates.

## References

- Nate B. Jones, ["Klarna saved $60 million and broke its company"](https://natesnewsletter.substack.com/p/klarna-saved-60-million-and-broke) (Substack, Feb 24 2026) — the prompt-to-context-to-intent engineering progression, and the case study of an AI that optimized for the wrong objective
- Nate B. Jones, [AI News and Strategy Daily](https://www.youtube.com/@naborjones) (YouTube) — videos on intent engineering and context engineering
