# TeaParty

TeaParty is a research platform exploring how humans and AI agents collaborate on complex, multi-step work. The core thesis: current agent systems fail not because models lack capability, but because the systems around them lack structure for coordination, memory, trust calibration, and human oversight.

## The Problem

AI agent systems today operate on a plan-execute model: the human provides a request, the agent plans, then executes. This model breaks in proportion to the gap between what the human said and what the human meant. That gap contains organizational values, unstated tradeoffs, decision boundaries, and quality expectations that the human has internalized to the point of invisibility.

As tasks grow in complexity, additional failure modes compound:

- **Context rot.** Flat multi-agent conversations balloon with competing details. No agent can maintain clarity about what matters at their level.
- **No persistent learning.** Agents reset every session. Lessons from yesterday's failure don't inform today's approach.
- **The autonomy-oversight dilemma.** Pure autonomy misses human values. Constant human oversight defeats the point of automation. Neither extreme works.
- **Coordination without structure.** Multiple agents working together without clear hierarchy produce inconsistent, conflicting output.

## Four Pillars

TeaParty addresses these failures through four research pillars, each targeting a distinct structural gap in current agent systems.

### Conversation for Action (CfA)

Prompt engineering tells agents what to do. Context engineering tells agents what to know. **Intent engineering tells agents what to want** — what to optimize for, what to protect, and what tradeoffs are acceptable.

TeaParty implements a three-phase state machine — Intent, Planning, Execution — governed by a formal CfA protocol. Each phase produces artifacts that constrain downstream work. Backtracking across phases is explicit and tracked. The result: agents operate from a shared specification of purpose, not an ambiguous request.

[Read more: Intent Engineering](intent-engineering.md)

### Hierarchical Memory and Learning

Claude Code's built-in memory (MEMORY.md) treats learning as a storage problem. It is actually a retrieval problem. Storing things is easy. Getting the right thing at the right moment and having it actually influence behavior — that is the hard part.

TeaParty distinguishes three learning types — institutional, task-based, and proxy — each with different scope, storage, retrieval, and rate of change. A promotion chain moves validated learnings from team sessions up through project and global scope. Four learning moments (prospective, in-flight, corrective, retrospective) capture knowledge at the points where it matters most.

[Read more: Learning System](learning-system.md) | [Research Foundations: Cognitive Architecture](cognitive-architecture.md)

### Hierarchical Teams

A single flat team trying to plan a project AND write every file hits context limits and loses coherence as the conversation grows. The fix is structural: separate strategic coordination from tactical execution.

TeaParty organizes agent teams in levels — an uber team coordinates strategy while subteams execute tactics. Each level runs as a separate process with its own context window. Liaison agents bridge levels, relaying tasks downward and results upward, compressing context at each boundary. The uber lead never sees raw file content; subteam workers never see cross-team coordination.

[Read more: Hierarchical Teams](hierarchical-teams.md) | [POC Architecture](poc-architecture.md)

### Human Proxy Agents

Every autonomous agent faces a continuous choice: act or ask. Both carry risk. Acting when the human wanted to be consulted causes wrong work and eroded trust. Escalating when the agent could have handled it wastes time and fails to deliver on the promise of autonomy.

TeaParty implements a confidence-based proxy model that learns when to auto-approve and when to escalate. The model observes human reactions over time — corrections indicate the threshold was too low, rubber-stamps indicate it was too high. Asymmetric regret weighting ensures false approvals (rubber-stamping bad work) cost more than false escalations. The agent earns autonomy through demonstrated alignment, not configuration.

[Read more: Intent Engineering — Least-Regret Escalation](intent-engineering.md#least-regret-escalation)

## Implementation

TeaParty is implemented as a Python orchestrator that drives Claude Code CLI processes. The system uses:

- **CfA state machine** with hierarchical parent-child linking for sub-team delegation
- **Async orchestrator engine** with actor-based phases (agent runner, approval gate, dispatch runner)
- **Git worktree isolation** for concurrent sessions
- **TUI dashboard** for monitoring and human interaction
- **Event-driven architecture** connecting orchestrator, TUI, and agent processes

The [POC architecture](poc-architecture.md) document describes the concrete two-level team implementation.
