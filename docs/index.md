# TeaParty

TeaParty is a research platform for durable, scalable agent coordination — the problem of keeping multi-agent systems aligned with human intent as work grows in complexity, duration, and organizational scope. The core thesis: current agent systems fail not because models lack capability, but because the systems around them lack structure for coordination, memory, trust calibration, and human oversight.

## The Problem

**Intent gap.** The human's request is treated as a specification. It isn't — it's the start of a conversation. The gap between what was said and what was meant contains organizational values, unstated tradeoffs, and contextual knowledge the human has internalized to the point of invisibility. Agents that treat the initial request as complete input build what they want to build, not what was asked for.

**Human escalation failure.** The plan-execute model treats human oversight as a dial: escalate more or escalate less. But it's a two-sided failure. Too much escalation and the human starts rubber-stamping — approvals become reflexive, not considered, and oversight loses meaning. Too little and intent diverges — the agent drifts from what was actually wanted, accumulating small misalignments into large ones. Neither extreme works. Oversight must be calibrated: earned through demonstrated alignment, not configured upfront.

**Backtracking.** The plan-execute model assumes execution moves forward. In practice, errors discovered mid-execution sometimes require going back not one step but all the way to the beginning — rethinking intent, not just revising the plan. Agents without a first-class backtrack mechanism compound errors rather than reset. The ability to return to origin is not a failure mode; it's a required capability.

**Context rot and scoping.** Without structural boundaries, agents see everything and nothing clearly. Even within a well-scoped context, signal degrades as conversations grow — the twentieth revision of a plan buries the original intent. Hierarchical teams address both: each agent sees only what is relevant to its role (scoping), and limiting what each agent works on slows degradation (rot). But scoping without retrieval creates its own drift: scoped agents lose access to the organizational knowledge that should inform every decision.

## Four Pillars

TeaParty addresses these failures through four research pillars, each targeting a distinct structural gap.

### Conversation for Action

*Addresses: intent gap, backtracking*

Prompt engineering tells agents what to do. Context engineering tells agents what to know. **Intent engineering tells agents what to want** — what to optimize for, what to protect, and what tradeoffs are acceptable.

TeaParty implements a three-phase Conversation for Action (CfA) protocol — Intent, Planning, Execution — formalized as a state machine with explicit transitions and cross-phase backtracks. Each phase produces artifacts that constrain downstream work. The result: agents operate from a shared specification of purpose, not an ambiguous request.

[Intent Engineering →](intent-engineering.md) · [CfA State Machine →](cfa-state-machine.md)

### Hierarchical Memory and Learning

*Addresses: context rot, scoping*

Learning is not a storage problem. It is a retrieval problem — getting the right knowledge to the right agent at the right moment. And it requires differentiation by purpose, because not all knowledge serves the same function:

- **Organizational learning** — learn the organization's values. Institutional norms, conventions, and working agreements that should govern all work within scope.
- **Task learning** — learn the most effective way to perform tasks. Procedural knowledge — rules, procedures, skills, and causal abstractions — that improves with each task outcome.
- **Proxy learning** — solve the autonomy/oversight dilemma. Learn the human's preferences, risk tolerance, and domain-specific decision patterns so the system can act as an accurate stand-in for low-risk decisions.

A promotion chain moves validated learnings up through the organizational hierarchy — from team sessions through projects to global scope. Four learning moments (prospective, in-flight, corrective, retrospective) capture knowledge at the points where it matters most. Fuzzy retrieval injects relevant knowledge into each agent's scoped context, bridging the gap that context scoping creates.

[Learning System →](learning-system.md) · [Research Foundations →](cognitive-architecture.md)

### Hierarchical Teams

*Addresses: context rot, scoping*

Context isolation via process boundaries is the key structural insight: each team level runs as an independent process with its own context window, so agents cannot be overwhelmed by information irrelevant to their role.

Complex work requires complex team structures. A single flat team trying to plan a project and write every file hits context limits and loses coherence. The fix is structural: separate strategic coordination from tactical execution.

TeaParty organizes agent teams in a hierarchy that mirrors how real organizations operate. An uber team (the strategic coordinator) manages strategy while subteams execute tactics. Each level runs as a separate process with its own context window. Liaison agents — lightweight teammates in the upper team whose sole function is communication relay — bridge levels, relaying tasks downward and results upward, compressing context at each boundary. The uber lead never sees raw file content; subteam workers never see cross-team coordination.

Agents serve as context boundaries. The hierarchy provides scoping — each agent sees only what is relevant to its role and level. Reducing the scope of what each agent works on mitigates context rot within each scoped conversation.

[Hierarchical Teams →](hierarchical-teams.md) · [POC Architecture →](poc-architecture.md)

### Human Proxy Agents

*Addresses: human escalation failure*

Every autonomous agent faces a continuous choice: act or ask. Both carry risk. Acting when the human wanted to be consulted causes wrong work and eroded trust. Escalating when the agent could have handled it wastes time and fails to deliver on the promise of autonomy. Neither pure autonomy nor constant oversight works.

TeaParty implements a confidence-based proxy model that learns when to auto-approve and when to escalate. The model observes human reactions over time — corrections indicate the threshold was too low, rubber-stamps indicate it was too high. Asymmetric regret weighting ensures false approvals cost more than false escalations. The agent earns autonomy through demonstrated alignment, not configuration.

[Human Proxy Agents →](human-proxies.md) · [Least-Regret Escalation →](intent-engineering.md#least-regret-escalation)

The full research bibliography is in [Research Library →](research/INDEX.md).
