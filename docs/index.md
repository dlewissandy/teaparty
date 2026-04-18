# TeaParty

TeaParty is a research platform for durable, scalable agent coordination — the problem of keeping multi-agent systems aligned with human intent as work grows in complexity, duration, and organizational scope. We are building toward a future where teams of humans and AI agents work together on increasingly difficult projects: not agents as tools wielded by humans, and not agents as autonomous replacements, but genuine mixed teams where each member contributes what they do best.

## The Problem

**Intent gap.** The human's request is treated as a specification. It isn't — it's the start of a conversation. The gap between what was said and what was meant contains organizational values, unstated tradeoffs, and contextual knowledge the human has internalized to the point of invisibility. Agents that treat the initial request as complete input build what they want to build, not what was asked for.

**Human escalation failure.** The plan-execute model treats human oversight as a dial: escalate more or escalate less. But it's a two-sided failure. Too much escalation and the human starts rubber-stamping — approvals become reflexive, not considered, and oversight loses meaning. Too little and intent diverges — the agent drifts from what was actually wanted, accumulating small misalignments into large ones. Neither extreme works. Oversight must be calibrated: earned through demonstrated alignment, not configured upfront.

**Backtracking.** The plan-execute model assumes execution moves forward. In practice, errors discovered mid-execution sometimes require going back not one step but all the way to the beginning — rethinking intent, not just revising the plan. Agents without a first-class backtrack mechanism compound errors rather than reset. The ability to return to origin is not a failure mode; it's a required capability.

**Context rot and scoping.** Without structural boundaries, agents see everything and nothing clearly. Even within a well-scoped context, signal degrades as conversations grow — the twentieth revision of a plan buries the original intent. Hierarchical teams address both: each agent sees only what is relevant to its role (scoping), and limiting what each agent works on slows degradation (rot). But scoping without retrieval creates its own drift: scoped agents lose access to the organizational knowledge that should inform every decision.

## Our Contributions

TeaParty addresses these failures through four research pillars, each targeting a distinct structural gap.

### Conversation for Action

*Addresses: intent gap, backtracking*

Winograd and Flores (*Understanding Computers and Cognition*, 1986) recognized that conversations follow structured patterns of request, commitment, and fulfillment, and modeled human coordination as a state machine of speech acts. But they designed for human-to-human coordination, where participants share an ocean of unspoken context — organizational norms, shared history, cultural assumptions, professional conventions. Mixed agent-human teams have no such shared substrate. What humans leave implicit, agents cannot infer.

TeaParty adapts their Conversation for Action framework for this reality. A three-phase protocol — Intent, Planning, Execution — is formalized as a state machine with explicit transitions and cross-phase backtracks. Each phase produces artifacts that make implicit context explicit: what to optimize for, what to protect, and what tradeoffs are acceptable. Approval gates between phases are not just checkpoints — they are learning opportunities where the system observes human corrections and preferences, feeding the memory and proxy systems described below. The result is intent engineering — agents operating from a shared specification of purpose, not an ambiguous request.

[CfA Orchestration →](systems/cfa-orchestration/index.md) · [Intent Engineering →](systems/cfa-orchestration/intent-engineering.md) · [Strategic Planning →](systems/cfa-orchestration/planning.md)

### Hierarchical Memory and Learning

*Addresses: context rot, scoping*

Learning is not a storage problem. It is a retrieval problem — getting the right knowledge to the right agent at the right moment. And it requires differentiation by purpose, because not all knowledge serves the same function:

- **Organizational learning** — learn the organization's values. Institutional norms, conventions, and working agreements that should govern all work within scope.
- **Task learning** — learn the most effective way to perform tasks. Procedural knowledge — rules, procedures, skills, and causal abstractions — that improves with each task outcome.
- **Proxy learning** — solve the autonomy/oversight dilemma. Learn the human's preferences, risk tolerance, and domain-specific decision patterns so the system can act as an accurate stand-in for low-risk decisions.

A promotion chain moves validated learnings up through the organizational hierarchy — from team sessions through projects to global scope. Four learning moments (prospective, in-flight, corrective, retrospective) capture knowledge at the points where it matters most. Fuzzy retrieval injects relevant knowledge into each agent's scoped context, bridging the gap that context scoping creates.

[Learning & Memory →](systems/learning/index.md) · [Research Index →](research/INDEX.md)

### Hierarchical Teams

*Addresses: context rot, scoping*

Context isolation via process boundaries is the key structural insight: each team level runs as an independent process with its own context window, so agents cannot be overwhelmed by information irrelevant to their role.

Complex work requires complex team structures. A single flat team trying to plan a project and write every file hits context limits and loses coherence. The fix is structural: separate strategic coordination from tactical execution.

TeaParty organizes agent teams in a hierarchy that mirrors how real organizations operate — an office manager coordinates across projects, project leads coordinate within projects, workgroup agents execute. Every agent is an independent `claude -p` process with its own context window; coordination happens exclusively through a persistent message bus. When a lead dispatches work via `Send`, it composes the recipient's context at the boundary — that is where compression happens. No intermediary agent reformulates messages; the sender's composition is the contract. The office manager never sees raw file content; workgroup agents never see cross-team coordination. Each hop through the hierarchy narrows context to what the next level needs.

This is also why hierarchical teams are not a single module in the code — the shape emerges from three pieces composed together: the message bus (persistent Send/Reply, scoped routing), the workspace layer (each session gets its own git worktree branched from its parent), and the team-configuration tree in `.teaparty/` (who can reach whom). See the [organizational model](overview.md) for how the pieces compose into the team hierarchy.

[Organizational Model →](overview.md) · [Messaging →](systems/messaging/index.md) · [Workspace →](systems/workspace/index.md)

### Human Proxy Agents

*Addresses: human escalation failure*

As agent teams grow, the human becomes a bottleneck. Other agents escalate questions about preferences, constraints, and tradeoffs. Plans need approval. Ambiguous situations need judgment calls. The human cannot be in every conversation, but their intent must be represented in all of them.

The human proxy agent's single job is to learn to stand in for the human. It answers clarifying questions from other agents, responds to escalations, engages in dialog about the human's preferences, and approves or rejects plans — all based on an evolving model of what the human would decide. Over time it observes human reactions: corrections indicate the model was wrong, rubber-stamps indicate it was right. Asymmetric regret weighting ensures false approvals cost more than false escalations. The proxy earns autonomy through demonstrated alignment, reducing the burden on the human without removing them from the loop.

[Human Proxy →](systems/human-proxy/index.md) · [Approval Gate →](systems/human-proxy/approval-gate.md)

## Proof of Concept

TeaParty eats its own dogfood. The platform's documentation, design artifacts, and implementation are produced by hierarchical agent teams running the TeaParty POC — the same coordination patterns we're researching are the ones we use to build.

The platform runs on Claude Code CLI: a persistent message bus for inter-process communication, a CfA state machine that drives each session through Intent → Planning → Execution with approval gates and backtracks, git worktree isolation per session so concurrent dispatches cannot race each other, a team-configuration tree that scopes which agents can reach which others, and post-session learning extraction that feeds validated insights into the scoped memory hierarchy. The *mechanisms* that make multi-tier, multi-agent orchestration possible are in place. Getting the composed system to exercise those mechanisms cleanly in a single end-to-end run — multiple independent workgroup agents collaborating under an office manager across a recursive dispatch chain — is on the list of next validations.

This is bootstrapping in progress. Every page in this documentation, every architectural decision, and every line of application code has been produced or reviewed by agent teams operating under the protocols described above. The result is a tight feedback loop: the system we're building is also the system we're testing, and the failures we encounter are the failures we're designing solutions for.

### See it run

The [**Humor Book case study**](case-study/index.md) walks through a complete end-to-end session: a four-sentence prompt becomes a 55,000-word manuscript — a prologue, seven chapters, two editorial passes, two verification passes — produced autonomously by hierarchical agent teams with proxy-managed approval gates. It includes the intent and planning dialogs, execution traces across five phases and eight parallel research tracks, the obstacles encountered, and the learning system's self-assessment.

Every artifact the session produced — drafts, specs, proxy-interaction logs, worktree layouts, dashboard screenshot — is preserved in [`case-study/artifacts/`](case-study/artifacts/).

### Project History

{{ project_count }} projects, {{ total_sessions }} sessions to date.

| Category | Projects | Sessions |
|----------|----------|----------|
{% for category, projects in project_categories.items() %}{% if projects %}| {{ category }} | {{ projects | length }} | {{ projects | sum(attribute=1) }} |
{% endif %}{% endfor %}

The full research bibliography is in [Research Library →](research/INDEX.md).

## Architecture

The six systems that realize the four pillars above are documented in [**Architecture**](systems/index.md) — one system per folder, with a landing page that describes what, why, how, and current status. The [organizational model](overview.md) describes the team hierarchy (office manager → project lead → workgroup) that emerges when those systems compose.

## Validation

The architectural claims above need two kinds of evidence: demonstrations that the system composed works at all, and ablations that isolate the contribution of each design choice.

**What we have today.** The [Humor Book case study](case-study/index.md) is the current end-to-end demonstration. A four-sentence prompt was lifted through intent and planning dialogs, carried through five execution phases, and produced a complete manuscript with preserved artifacts — proxy-interaction logs, drafts, specs, editorial reports, verification reports. This shows the composed system producing substantive output under the CfA protocol, with real proxy participation at gates and real learning signal captured. It is not itself a controlled ablation.

**What's planned but not yet run.** The [Planned Validation](experimental-results/index.md) section specifies seven ablative experiments — one per pillar claim — with methodology, evaluation criteria, and task corpus. The harness and instrumentation infrastructure are in place. The experiments have not been executed yet; individual experiment pages currently carry their design, not their results. That gap is the honest statement of where the research is: claims are specified and testable, one end-to-end demonstration exists, ablative measurement is the next step.

## Contributing

See [CONTRIBUTING.md](contributing.md) for development workflows, coding standards, and how to use TeaParty to build TeaParty.
