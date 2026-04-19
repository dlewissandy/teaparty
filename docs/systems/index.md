# Architecture

TeaParty's runtime is composed of six systems. Four of them realize the research contributions described on the [home page](../index.md); two are enabling infrastructure that the others depend on. The [organizational model](../overview.md) — the OM / Project Lead / workgroup hierarchy — is the *shape* that these systems produce when composed; it is not itself one of them.

## The six systems

| System | Role | Code |
|---|---|---|
| [CfA Orchestration](cfa-orchestration/index.md) | State-machine engine driving every session through Intent → Planning → Execution with approval gates and backtracks. | `teaparty/cfa/` |
| [Human Proxy](human-proxy/index.md) | Learned agent that stands in for the human at approval gates and escalations. | `teaparty/proxy/` |
| [Learning & Memory](learning/index.md) | Hierarchical memory (episodic / procedural / research) with a promotion chain, temporal decay, and continuous skill refinement. | `teaparty/learning/` |
| [Messaging](messaging/index.md) | Two buses — an async event bus (orchestrator ↔ bridge) and a SQLite-backed conversation bus (inter-agent Send; reply is the recipient's turn-end output). | `teaparty/messaging/` |
| [Workspace](workspace/index.md) | Git worktree isolation, job and task lifecycle, and the unified agent launcher. Session = worktree = branch, unconditionally. | `teaparty/workspace/` |
| [Bridge (Dashboard)](bridge/index.md) | HTML dashboard + bridge server. Human-facing reflection and interaction surface at `localhost:8081`. | `teaparty/bridge/` |

## How they compose

```
                        ┌─────────────────────────────┐
                        │       CfA Orchestration     │
                        │  (state machine, gates)     │
                        └──────────────┬──────────────┘
                                       │ drives
            ┌──────────────┬───────────┴──────────┬──────────────┐
            ▼              ▼                      ▼              ▼
     ┌────────────┐  ┌────────────┐        ┌────────────┐  ┌────────────┐
     │ Human Proxy│  │ Learning   │        │ Workspace  │  │ Messaging  │
     │ (gates,    │◄─┤ (retrieval,│        │ (worktrees,│  │ (Send +    │
     │  presence) │  │ promotion) │        │  jobs)     │  │  event bus)│
     └────────────┘  └────────────┘        └────────────┘  └────────────┘
            ▲              ▲                      │              │
            │              │                      │              │
            └───feedback───┘                      └──reflected──►┤
                                                                 ▼
                                                          ┌────────────┐
                                                          │ Bridge/UI  │
                                                          │ (dashboard)│
                                                          └────────────┘
```

CfA Orchestration is the main loop. It decides what state a session is in, invokes the right actor, and advances on completion. When it reaches an approval gate it asks the Human Proxy. Proxy decisions are learned from corrections; those corrections feed Learning, and Learning's retrievals in turn inform Proxy prediction — a bidirectional coupling.

Work that spans agents is dispatched through Messaging. Each dispatched unit gets isolated storage through Workspace. Bridge observes everything via the event bus and the conversation store; it is a reflection layer, not an orchestrator.

## Pillars vs. infrastructure

The [home page](../index.md) frames TeaParty as four research pillars — Conversation for Action, Hierarchical Memory and Learning, Hierarchical Teams, and Human Proxy Agents. Three pillars map 1:1 to a system (CfA Orchestration, Learning & Memory, Human Proxy). The fourth pillar — Hierarchical Teams — is an **emergent property** of composing Messaging, Workspace, and the team-configuration tree in `.teaparty/`. There is no single "hierarchical teams" module in the code; hierarchy comes from the *shape* of Send routing (the recipient's turn-end is the reply), worktree nesting, and roster scoping applied at each level. The mechanisms are operational; the multi-tier OM → project-lead → workgroup-agent dispatch *pattern* has not yet been cleanly demonstrated end-to-end (see the [case study scope statement](../case-study/index.md#scope-of-what-this-session-demonstrates) and the [recursive-dispatch proposal](../proposals/recursive-dispatch/proposal.md)). See the [organizational model](../overview.md) for the conceptual story.

Messaging, Workspace, and Bridge are infrastructure. They exist because the pillars need them, not because they make independent research claims.

## Supporting layers

Several packages sit underneath the six systems but are not themselves "systems" in this sense:

- `teaparty/runners/` — Claude CLI, Ollama, and deterministic execution backends. The runtime substrate for any agent invocation.
- `teaparty/mcp/` — MCP tool surface exposed to agents: config CRUD, escalation, messaging, intervention. A tool registry, not a coordinator.
- `teaparty/config/` — Reads `.teaparty/` (agents, workgroups, projects). Read-only parser; not an active system.
- `teaparty/scheduling/` — Cron-based recurring agent execution.

These are documented in [reference/](../reference/) where reference material exists.

## Proof of life

Every system's status section is grounded in the code as it exists today. For a narrative end-to-end demonstration of the six composed — from a four-sentence prompt to a 55,000-word manuscript — see the [Humor Book case study](../case-study/index.md).
