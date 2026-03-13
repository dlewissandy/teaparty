# TeaParty

TeaParty is a research platform exploring how humans and AI agents collaborate on complex, multi-step work. The core thesis: current agent systems fail not because models lack capability, but because the systems around them lack structure for coordination, memory, trust calibration, and human oversight.

## The Problem

AI agent systems operate on a plan-execute model: the human provides a request, the agent plans, then executes. This model breaks in proportion to the gap between what the human said and what the human meant. That gap contains organizational values, unstated tradeoffs, decision boundaries, and quality expectations that the human has internalized to the point of invisibility.

As tasks grow in complexity, two structural failures emerge:

**Context scoping.** Without structural boundaries, every agent sees everything and nothing clearly. A strategic coordinator drowning in raw file diffs cannot maintain clarity about project direction. A code writer buried in cross-team negotiations cannot focus on implementation. Agents need context boundaries — each agent should see only what is relevant to its level and role.

**Context rot.** Even within a properly scoped agent, signal degrades as conversations grow. Every additional message dilutes what matters. The twentieth revision of a plan buries the original intent. Context rot is not a failure of scoping — it is what happens inside a well-scoped context that runs too long or accumulates too much state.

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

Complex work requires complex team structures. A single flat team trying to plan a project and write every file hits context limits and loses coherence. The fix is structural: separate strategic coordination from tactical execution.

TeaParty organizes agent teams in a hierarchy that mirrors how real organizations operate. An uber team coordinates strategy while subteams execute tactics. Each level runs as a separate process with its own context window. Liaison agents bridge levels, relaying tasks downward and results upward, compressing context at each boundary. The uber lead never sees raw file content; subteam workers never see cross-team coordination.

Agents serve as context boundaries. The hierarchy provides scoping — each agent sees only what is relevant to its role and level. Reducing the scope of what each agent works on mitigates context rot within each scoped conversation.

[Hierarchical Teams →](hierarchical-teams.md) · [POC Architecture →](poc-architecture.md)

### Human Proxy Agents

Every autonomous agent faces a continuous choice: act or ask. Both carry risk. Acting when the human wanted to be consulted causes wrong work and eroded trust. Escalating when the agent could have handled it wastes time and fails to deliver on the promise of autonomy. Neither pure autonomy nor constant oversight works.

TeaParty implements a confidence-based proxy model that learns when to auto-approve and when to escalate. The model observes human reactions over time — corrections indicate the threshold was too low, rubber-stamps indicate it was too high. Asymmetric regret weighting ensures false approvals cost more than false escalations. The agent earns autonomy through demonstrated alignment, not configuration.

[Human Proxy Agents →](human-proxies.md) · [Least-Regret Escalation →](intent-engineering.md#least-regret-escalation)

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
