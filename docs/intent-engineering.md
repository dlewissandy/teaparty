# Intent: Automated Intent Engineering Experience

Intent engineering is the first pillar of TeaParty's four-pillar framework: it establishes what an agent should want before any planning or execution begins. Prompt engineering tells agents what to do. Context engineering tells agents what to know. Intent engineering tells agents what to want — what to optimize for, what to protect, and what tradeoffs are acceptable. Without it, agents optimize for what they can measure and destroy what they cannot.

## Why This Exists

AI agent systems operate on a plan-execute model: the human provides a request, the agent plans how to fulfill it, then executes. This model fails in proportion to the gap between what the human said and what the human meant. That gap contains organizational values, unstated tradeoffs, decision boundaries, domain constraints, and quality expectations that the human has internalized to the point of invisibility.

The intent engineering system is an AI-assisted dialog experience, constrained to under 15 minutes, that produces an `intent.md` file. That file becomes the governing document for all downstream planning and execution — not a suggestion, but a specification of purpose.

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

Every autonomous agent faces a continuous choice: act or ask. Both carry risk. The agent must choose the option with the least expected regret — weighted by this human's risk tolerance, the reversibility of the action, and its organizational impact. At cold start the agent defaults to escalation; autonomy is earned through demonstrated alignment, not configured in advance.

The escalation model is one of the highest-value things the institutional memory system stores. It encodes not just what a person values but how much latitude they grant, and how that varies by domain and risk level. See [Human Proxies — Least-Regret Escalation](human-proxies.md#least-regret-escalation) for the full treatment.

## How The Conversation Works

### Cold Start (No Prior Context)

When the system has no history with this human or organization, the human is the sole source of intent. The agent conducts a responsive dialog — not a scripted questionnaire — that surfaces implicit assumptions, researches the solution space in real time, pushes back on contradictions, identifies gaps, and surfaces escalation preferences. Documents, links, and prior conversations are accepted as context sources.

### Warm Start (Accumulated Context)

Over time, the system observes how the human responds to completed work: what they correct, what they praise, what they silently accept, and what they reject. These observations accumulate into institutional memory. In warm-start mode, the agent pre-populates intent elements and escalation posture inferred from prior interactions — presented for confirmation, not silently assumed. Corrections to pre-populated intent are high-value signal that the model has diverged from reality. See [Learning System](learning-system.md) for how this memory is stored and retrieved.

## Relationship to Institutional Memory

The intent engineering system is the first consumer of proxy learnings from the [learning system](learning-system.md). The relationship is bidirectional: accumulated observations flow into intent gathering as priors that reduce burden on the human, and every intent gathering session produces new signal about what the organization values. Escalation outcomes — every autonomous action accepted or corrected, every escalation warranted or unnecessary — are calibration data points for the escalation model.

Institutional memory operates at three scopes: individual (preferences and risk tolerance), team (shared conventions), and organization (universal policies). Intent gathered from an individual may conflict with team or organizational priors. The system must surface these conflicts rather than silently resolving them.

## Success Criteria

The governing metric is alignment over time: the system's ability to produce work that reflects what the human actually wanted improves with each interaction. This is not directly measurable as a single number. It manifests as a constellation of observable properties including reduction in rework, reduction in escalation errors, increased productivity, increased human satisfaction with output quality, and reduction in catastrophic negative outcomes. No single proxy captures alignment fully, and the relevant proxies will vary by organization and domain. The system is succeeding when the trend across these indicators is positive and no individual indicator is degrading.

The intent gathering conversation itself has two specific constraints: it must complete in under 15 minutes for moderate-complexity projects, and it must feel like working with a sharp colleague rather than filling out a form. The agent must demonstrate understanding of the problem space by bringing relevant research into the dialog, not just asking questions. The resulting intent.md must read as a document the human would have written themselves if they had the time and discipline to make all their implicit knowledge explicit.

## Open Questions

Open research questions for this area are collected in [Research Directions](research-directions.md).

## References

- Nate B. Jones, ["Klarna saved $60 million and broke its company"](https://natesnewsletter.substack.com/p/klarna-saved-60-million-and-broke) (Substack, Feb 24 2026) — the prompt-to-context-to-intent engineering progression, and the case study of an AI that optimized for the wrong objective
- Nate B. Jones, [AI News and Strategy Daily](https://www.youtube.com/@naborjones) (YouTube) — videos on intent engineering and context engineering
