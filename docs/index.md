# TeaParty

TeaParty is a research platform for durable, scalable agent coordination — the problem of keeping multi-agent systems aligned with human intent as work grows in complexity, duration, and organizational scope. The core thesis: current agent systems fail not because models lack capability, but because the systems around them lack structure for coordination, memory, trust calibration, and human oversight.

## The Problem

AI agent systems operate on a plan-execute model: the human provides a request, the agent plans, then executes. This model breaks in proportion to the gap between what the human said and what the human meant. That gap contains organizational values, unstated tradeoffs, decision boundaries, and quality expectations that the human has internalized to the point of invisibility.

As tasks grow in complexity, two structural failures emerge:

**Context scoping.** Without structural boundaries, every agent sees everything and nothing clearly. A strategic coordinator drowning in raw file diffs cannot maintain clarity about project direction. A code writer buried in cross-team negotiations cannot focus on implementation. Agents need context boundaries — each agent should see only what is relevant to its level and role.

**Context rot.** Even within a properly scoped agent, signal degrades as conversations grow. Every additional message dilutes what matters. The twentieth revision of a plan buries the original intent. Context rot — the degradation of earlier instructions in long multi-step tasks, where the model begins optimizing for recent context at the expense of the original intent — is not a failure of scoping. It is what happens inside a well-scoped context that runs too long or accumulates too much state.

Hierarchical teams address both: agents serve as context boundaries (scoping), and reducing what each agent works on limits how fast its context degrades (rot).

But scoping alone creates a new problem. **Context scoping without learning and retrieval is a recipe for misalignment.** Scoped agents lose access to organizational context — the values, conventions, and accumulated knowledge that should inform every decision. Without a learning system that injects relevant knowledge into each agent's scoped context at the right moment, agents drift. They optimize locally and violate globally.

## Four Pillars

TeaParty addresses these failures through four research pillars, each targeting a distinct structural gap.

### Conversation for Action

Prompt engineering tells agents what to do. Context engineering tells agents what to know. **Intent engineering tells agents what to want** — what to optimize for, what to protect, and what tradeoffs are acceptable.

TeaParty implements a three-phase Conversation for Action (CfA) protocol — Intent, Planning, Execution — formalized as a state machine with explicit transitions and cross-phase backtracks. Each phase produces artifacts that constrain downstream work. The result: agents operate from a shared specification of purpose, not an ambiguous request.

[Intent Engineering →](intent-engineering.md) · [CfA State Machine →](cfa-state-machine.md)

### Hierarchical Memory and Learning

Learning is not a storage problem. It is a retrieval problem — getting the right knowledge to the right agent at the right moment. And it requires differentiation by purpose, because not all knowledge serves the same function:

- **Organizational learning** — learn the organization's values. Institutional norms, conventions, and working agreements that should govern all work within scope.
- **Task learning** — learn the most effective way to perform tasks. Procedural knowledge — rules, procedures, skills, and causal abstractions — that improves with each task outcome.
- **Proxy learning** — solve the autonomy/oversight dilemma. Learn the human's preferences, risk tolerance, and domain-specific decision patterns so the system can act as an accurate stand-in for low-risk decisions.

A promotion chain moves validated learnings up through the organizational hierarchy — from team sessions through projects to global scope. Four learning moments (prospective, in-flight, corrective, retrospective) capture knowledge at the points where it matters most. Fuzzy retrieval injects relevant knowledge into each agent's scoped context, bridging the gap that context scoping creates.

[Learning System →](learning-system.md) · [Research Foundations →](cognitive-architecture.md)

### Hierarchical Teams

Context isolation via process boundaries is the key structural insight: each team level runs as an independent process with its own context window, so agents cannot be overwhelmed by information irrelevant to their role.

Complex work requires complex team structures. A single flat team trying to plan a project and write every file hits context limits and loses coherence. The fix is structural: separate strategic coordination from tactical execution.

TeaParty organizes agent teams in a hierarchy that mirrors how real organizations operate. An uber team (the strategic coordinator) manages strategy while subteams execute tactics. Each level runs as a separate process with its own context window. Liaison agents — lightweight teammates in the upper team whose sole function is communication relay — bridge levels, relaying tasks downward and results upward, compressing context at each boundary. The uber lead never sees raw file content; subteam workers never see cross-team coordination.

Agents serve as context boundaries. The hierarchy provides scoping — each agent sees only what is relevant to its role and level. Reducing the scope of what each agent works on mitigates context rot within each scoped conversation.

[Hierarchical Teams →](hierarchical-teams.md) · [POC Architecture →](poc-architecture.md)

### Human Proxy Agents

Every autonomous agent faces a continuous choice: act or ask. Both carry risk. Acting when the human wanted to be consulted causes wrong work and eroded trust. Escalating when the agent could have handled it wastes time and fails to deliver on the promise of autonomy. Neither pure autonomy nor constant oversight works.

TeaParty implements a confidence-based proxy model that learns when to auto-approve and when to escalate. The model observes human reactions over time — corrections indicate the threshold was too low, rubber-stamps indicate it was too high. Asymmetric regret weighting ensures false approvals cost more than false escalations. The agent earns autonomy through demonstrated alignment, not configuration.

[Human Proxy Agents →](human-proxies.md) · [Least-Regret Escalation →](intent-engineering.md#least-regret-escalation)

## What's Been Demonstrated

The POC is operational. The uber/subteam hierarchy has run against real tasks — this documentation was produced by the same uber/subteam structure it describes, using live dispatches in isolated worktrees. Learning extraction is automated: agents do not write memory files; a post-session runner (`scripts/summarize_session.py`) reads the conversation stream and promotes durable learnings to the appropriate scope in the hierarchy. The CfA state machine is running — approval gates, backtrack transitions (Execution → Planning → Intent), and proxy-gated planning are all operational. Git worktree isolation is working: concurrent subteam dispatches run in separate branches and merge back without conflict.

The dogfooding story is worth noting: the POC is actively building its own documentation using the same orchestration it documents, which provides a continuous integration test of the coordination model.

### Measurement Targets

These are the signals that will indicate the system is working:

- **Learning quality**: does the proxy model calibrate faster with accumulated learnings vs. cold start? The signal is escalation rate over time — a warming proxy should escalate less on tasks that resemble prior sessions.
- **Context isolation**: does splitting uber/sub contexts reduce mid-task goal drift? The signal is output consistency across parallel dispatches — drift would appear as divergence between what the uber team directed and what subteams produced.
- **Escalation convergence**: does the escalation rate decrease over sessions as the proxy model accumulates observations? A flat or rising escalation rate after N sessions indicates the proxy is not learning from outcomes.
- **Session coherence**: does the CfA structure reduce intent drift — the plan diverging from `intent.md`? The signal is how often backtrack transitions are triggered; a well-calibrated system should require fewer backtracks as teams accumulate task learnings.

---

## Research Positioning

TeaParty builds on established multi-agent coordination research (CoALA, Generative Agents, multi-agent collaboration surveys), context window and memory augmentation work (MemGPT/Letta, Mem0, A-MEM), and human-AI oversight literature (metacognition, trust calibration, uncertainty communication). The prior work establishes that hierarchical teams outperform flat teams, that structured memory augmentation improves long-horizon performance, and that human oversight is necessary but costly.

What TeaParty adds is the combination of four things that have not been demonstrated together: (1) explicit context scoping via process boundaries — each team level is a separate OS process with its own context window, not just a logical role assignment; (2) a formal state machine for structured task delegation with cross-phase backtrack transitions; (3) automated learning extraction scoped by hierarchy level, with a promotion chain that filters aggressively before generalizing; and (4) a calibratable proxy model for human oversight that learns from act/ask outcomes rather than requiring upfront configuration.

The full bibliography is in [Research Library →](research/INDEX.md). The research sections of individual doc files cite specific papers against specific design decisions.

---

## Folder Structure

TeaParty's folder structure mirrors its organizational model. The top-level directory is the organization. Projects live in `projects/` as separate git repositories.

```
teaparty/                           # the organization
├── .claude/agents/                 # agent role definitions
├── docs/                           # organization-level documentation
├── projects/                       # one git repo per project
│   ├── MEMORY.md                   # global learnings
│   ├── POC/                        # proof-of-concept project
│   │   ├── agents/                 # team definitions (uber, coding, writing, ...)
│   │   ├── orchestrator/           # CfA engine, actors, session lifecycle
│   │   ├── scripts/                # CfA state machine, proxy model, learning
│   │   ├── tui/                    # terminal UI dashboard
│   │   └── .sessions/             # session history + worktrees
│   ├── hierarchical-memory-paper/  # research paper project
│   ├── agentic-cfa-publication/    # research paper project
│   └── ...
└── teaparty_app/                   # the platform itself
```

TeaParty eats its own dogfood. The POC orchestrator drives Claude Code CLI processes that modify the TeaParty codebase itself via git worktrees. The `.claude/agents/` directory defines 11 agent roles — architect, backend-engineer, researcher, doc-writer, and others. The uber team coordinates strategic decisions; subteams (coding, writing, art, research, editorial) execute tactical work. Each session gets an isolated git worktree; completed work merges back to the parent repository.

This is the intended production pattern: organizations define agent roles, projects are separate repositories, and the platform orchestrates work across the hierarchy.

[Folder Structure →](folder-structure.md) · [POC Architecture →](poc-architecture.md)
