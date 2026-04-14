# Detailed Design

This section maps the conceptual design to the actual implementation. It describes what exists in code today, how the components integrate, and where the implementation diverges from or has not yet reached the conceptual design. Gaps are called out honestly with references to the GitHub issues that track them.

The conceptual design is spread across the documents in the parent folder -- [overview.md](../overview.md), [conceptual-design/cfa-state-machine.md](../conceptual-design/cfa-state-machine.md), [conceptual-design/human-proxies.md](../conceptual-design/human-proxies.md), [conceptual-design/learning-system.md](../conceptual-design/learning-system.md), [conceptual-design/intent-engineering.md](../conceptual-design/intent-engineering.md), [conceptual-design/strategic-planning.md](../conceptual-design/strategic-planning.md), [conceptual-design/hierarchical-teams.md](../conceptual-design/hierarchical-teams.md), [conceptual-design/messaging.md](../conceptual-design/messaging.md), [conceptual-design/team-configuration.md](../conceptual-design/team-configuration.md), and [reference/folder-structure.md](../reference/folder-structure.md). These detailed design documents do not repeat the conceptual rationale. They specify how the concepts are (or are not) realized in the codebase.

---

## Scope

These documents describe the **teaparty runtime** -- the `teaparty/` package that drives the CfA state machine, launches agents, coordinates teams via the message bus, reads configuration, serves the dashboard, and manages the learning and proxy subsystems. The scope covers: CfA engine (`teaparty/cfa/`), agent launcher and runners (`teaparty/runners/`), message bus (`teaparty/messaging/`), config reader (`teaparty/config/`), bridge/dashboard (`teaparty/bridge/`), proxy system (`teaparty/proxy/`), learning system (`teaparty/learning/`), team coordination (`teaparty/teams/`), and workspace management (`teaparty/workspace/`).

These documents do not describe the engagement orchestration layer (org lead negotiation, decomposition into projects, feedback bubble-up), which is upstream and addressed in the conceptual design documents. See [conceptual-design/hierarchical-teams.md](../conceptual-design/hierarchical-teams.md) for the full conceptual model.

---

## Documents

- [Agent Runtime](agent-runtime.md) -- CLI invocation design, unified agent launcher, hierarchical dispatch
- [Unified Agent Launch](unified-agent-launch.md) -- One-shot launch with `--resume`, prompt assembly, worktree lifecycle
- [CfA State Machine](cfa-state-machine.md) -- State representation, transition table, INTERVENE/WITHDRAW events
- [Approval Gate](approval-gate.md) -- Proxy decision model, confidence computation, design choices
- [Learning System](learning-system.md) -- Memory hierarchy, extraction pipeline, design choices
- [Team Configuration](team-configuration.md) -- `.teaparty/` config tree, catalog merging, MCP CRUD tools
- [Project Onboarding](project-onboarding.md) -- Step-by-step: directory, git, `.claude/`, `.teaparty/`, lead scaffolding
- Messaging *(forthcoming)* -- Bus-mediated Send/Reply, conversation lifecycle, streaming
- Context Budget *(forthcoming)* -- Token budget allocation, context injection, partial implementation status
- Dashboard *(forthcoming)* -- HTML dashboard reference: chat blade, config screens, filters, navigation

---

## Gap Summary

### Pillar Status

The conceptual design rests on seven pillars. Here is an honest assessment of each.

#### Conversation for Action (CfA)

| Maturity Level | Status | Notes |
|---|---|---|
| **Operational** | Fully implemented | State machine in `teaparty/cfa/` with correct states, transitions, and validation. Three-phase protocol (Intent, Planning, Execution) with backtrack transitions. INTERVENE and WITHDRAW events implemented for human override and session cancellation. |
| **Integrated** | Yes | One-shot launch with `--resume` replaces persistent sessions. The launcher assembles the prompt, invokes the runner, and the CfA engine manages state transitions. Session lifecycle is tied to the worktree (session=worktree 1:1:1). |
| **Full Design** | Not yet | [#92](https://github.com/dlewissandy/teaparty/issues/92) tracks replacing bespoke state management with `python-statemachine` for formal guard conditions and visualization. |

#### Hierarchical Teams

| Maturity Level | Status | Notes |
|---|---|---|
| **Operational** | Three-level hierarchy works | Office Manager, Project Manager, Project Lead, and workgroups are operational. OM dispatches to PMs, PMs to PLs, PLs to workgroup agents. Process boundaries provide context isolation via worktrees. |
| **Integrated** | Yes | Bus-mediated Send/Reply replaces liaison agents. Session=worktree 1:1:1 mapping. Squash-merge on completion. Team coordination in `teaparty/teams/`. |
| **Full Design** | Not yet | Engagement orchestration (org lead negotiation, decomposition, feedback bubble-up) is not yet agent-driven end-to-end. See [hierarchical-teams.md](../conceptual-design/hierarchical-teams.md). |

#### Learning System

| Maturity Level | Status | Notes |
|---|---|---|
| **Operational** | Yes | Post-session learning extraction, memory indexing, session summarization, reinforcement tracking, and memory compaction are all wired. Promotion chain implements session, project, and global gates with recurrence detection and proxy exclusion ([#217](https://github.com/dlewissandy/teaparty/issues/217)). Continuous skill refinement detects execution friction, refines skill templates via LLM, and suppresses degraded skills ([#229](https://github.com/dlewissandy/teaparty/issues/229)). Temporal decay with 90-day half-life and decay floor ([#218](https://github.com/dlewissandy/teaparty/issues/218)). No online learning during execution. |
| **Integrated** | Yes | Reinforcement tracking wired ([#91](https://github.com/dlewissandy/teaparty/issues/91)). Scope multipliers integrated into retrieval. Type-aware budget allocation implemented ([#197](https://github.com/dlewissandy/teaparty/issues/197)). Proxy learning integration complete -- bidirectional feedback between proxy corrections and agent learnings ([#198](https://github.com/dlewissandy/teaparty/issues/198)). Memory context injection works. |
| **Full Design** | Not yet | In-flight and prospective extraction are design targets. Skill crystallization (automatic generalization of repeated plans) is not yet implemented. |

#### Human Proxy

| Maturity Level | Status | Notes |
|---|---|---|
| **Operational** | Yes | Three-tier proxy path: flat patterns, interaction history, and ACT-R memory retrieval with two-pass prediction (prior/posterior). Cold-start gating via ACT-R memory depth ([#220](https://github.com/dlewissandy/teaparty/issues/220)). Contradiction detection and resolution with LLM-as-judge classification ([#228](https://github.com/dlewissandy/teaparty/issues/228)). Per-context prediction accuracy tracking per (state, task_type) pair ([#226](https://github.com/dlewissandy/teaparty/issues/226)). Asymmetric confidence decay following Hindsight (arXiv:2512.12818). Proxy review sessions via the dashboard chat blade. |
| **Integrated** | Yes | Proxy learning integrated with main learning system -- bidirectional feedback ([#198](https://github.com/dlewissandy/teaparty/issues/198)). ACT-R memory retrieval feeds into proxy context. Salience index separated from chunk embeddings ([#227](https://github.com/dlewissandy/teaparty/issues/227)). Unified launcher integration -- proxy participates in the same launch pipeline as agent sessions. |
| **Full Design** | Not yet | Intake dialog Phases 2-3, text derivative learning, behavioral rituals, and gap-detection questioning are design targets. Actual proxy accuracy on real escalations is unmeasured. |

#### Messaging / Dispatch

| Maturity Level | Status | Notes |
|---|---|---|
| **Operational** | Yes | Bus-mediated Send/Reply in `teaparty/messaging/`. Conversation lifecycle management. Real-time streaming to the dashboard via the bridge server. Event routing between agents, teams, and the dashboard. |
| **Integrated** | Yes | Replaces liaison agents for inter-level communication. The bus is the backbone for team coordination -- OM/PM/PL communicate via Send/Reply rather than direct subprocess calls. IPC between worktree-isolated sessions. |
| **Full Design** | Not yet | Conceptual design in [messaging.md](../conceptual-design/messaging.md) describes full conversation threading and routing patterns. Reference doc forthcoming. |

#### Team Configuration

| Maturity Level | Status | Notes |
|---|---|---|
| **Operational** | Yes | `.teaparty/` config tree: agent definitions, workgroup rosters, project settings, skill catalogs. Catalog merging across management and project levels. Config reader in `teaparty/config/`. MCP server provides config CRUD via `teaparty/mcp/`. |
| **Integrated** | Yes | The unified launcher reads config to assemble agent prompts, select runners, and scope tool access. Dashboard config screens expose the config tree for editing. |
| **Full Design** | Not yet | Conceptual design in [team-configuration.md](../conceptual-design/team-configuration.md). Reference doc forthcoming. |

#### Dashboard

| Maturity Level | Status | Notes |
|---|---|---|
| **Operational** | Yes | HTML dashboard served by `teaparty/bridge/`. Chat blade for real-time session interaction and proxy review. Config screens for agents, workgroups, projects, skills. Session filters and navigation. Heartbeat and status display via `teaparty/bridge/state/`. |
| **Integrated** | Yes | Consumes the message bus for real-time streaming. Drives proxy review sessions. Config edits propagate through the config reader. |
| **Full Design** | Not yet | Reference doc forthcoming. |

### Key Dependencies and Preconditions

**Learning as foundation.** The human proxy's retrieval-backed prediction depends on the learning system's scoped retrieval. The intake dialog depends on having proxy learnings to predict from. The planning warm start depends on procedural learning (skills). These dependencies mean the learning system is a prerequisite for the other pillars to reach their full conceptual design. With promotion chain, type-aware retrieval, proxy-learning integration, and continuous skill refinement now operational, the remaining gaps are in-flight/prospective extraction and automatic skill crystallization.

---

## Remaining Gaps

**Engagement orchestration.** The conceptual design describes a full engagement lifecycle (proposed, accepted, in_progress, completed, reviewed) with partnerships (directional trust, cycle prevention) and org lead orchestration (negotiation, decomposition into projects/jobs, feedback bubble-up). The runtime implements three-level dispatch but not the full engagement orchestration loop.

**Context budget.** Token budget allocation is partially implemented. Type-aware budget allocation works for learning retrieval. Full context budget management across prompt assembly -- balancing system prompt, learnings, conversation history, and tool results within model limits -- is not yet complete.

**Session directory consolidation.** Session artifacts (logs, state, learnings) are written to worktree roots. A unified session directory structure for discovery and cleanup across worktrees is not yet implemented.

---

## Experimental Results

Ablative experiments designed to validate each pillar's architectural claims are documented in [Experimental Results](../experimental-results/index.md).
