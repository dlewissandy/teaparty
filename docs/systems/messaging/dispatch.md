# Agent Dispatch

How TeaParty routes messages between agents and humans, launches agent processes, and maintains session continuity across restarts.

All communication flows through the message bus. Every agent is an independent process with its own context window. No agent shares memory, state, or a process boundary with any other agent. Coordination happens through messages, not through shared sessions.

---

## The Bus as Universal Transport

The message bus is the single transport layer for all communication in TeaParty. Human-to-agent messages, agent-to-agent messages, escalations, and system events all travel through the same bus. There is no secondary channel — no stdin pipe, no in-process delegation, no shared context.

This uniformity means every interaction is stored, routable, and visible. The bus is a durable persistent store, not a transient message queue. Conversation records survive process restarts. An agent that exits and is later re-invoked finds its conversation history intact.

See [messaging.md](index.md) (forthcoming) for the bus storage model and adapter interface.

---

## Send and Reply

Two operations handle all inter-agent communication.

**Send(member, message)** delivers a message to a named roster member, opening a new conversation thread. The caller decides what context to include in the message — task description, relevant state, pointers to files. Context compression happens at the Send boundary: the caller distills what the recipient needs to know into the message body. No intermediate agent reformulates or relays the content.

**Reply(message)** responds to whoever opened the current thread and closes it. The conversation context is already established from the opening Send.

Each conversation thread has an open/close lifecycle owned by the originator. The originator opens the thread with Send; the recipient closes it with Reply. A single agent can have multiple threads open simultaneously — a lead that sends three parallel requests has three open threads tracked in its conversation history.

---

## One-Shot Launch with Resume

Every agent — office manager, project lead, workgroup agent — runs as an independent `claude -p` process. There are no persistent agent processes. Each invocation receives the agent's definition file, its workspace, and its conversation history via `--resume`.

The execution model is **write-then-exit-then-resume**:

1. An agent is invoked with a message (from a human, from another agent, or from the system).
2. The agent processes the message, produces output, and may Send messages to other agents.
3. The agent's process exits.
4. When replies arrive or new messages are delivered, the agent is re-invoked with `--resume` against the same session, picking up where it left off.

The agent's state lives on the bus, not in process memory. An agent that sends three parallel requests records all three outstanding threads before exiting. When workers Reply, the bus tracks completions; the caller is re-invoked only when all pending threads close. Durability across restarts and partial failures follows from this — there is no in-memory state to lose.

---

## Routing Rules

Bus routing determines which agents can communicate with which others. Routing policy is derived from workgroup membership as defined in [team-configuration.md](../../reference/team-configuration.md).

An agent's roster — the set of members it can reach via Send — is composed at launch time from the workgroup definition. A coding agent does not have a route to a config specialist in another workgroup. Cross-workgroup requests within a project go through the project lead.

Cross-project communication is always mediated by the office manager. Project-scoped agents have no direct bus routes to agents in other projects. The office manager holds cross-project context and translates between project boundaries.

---

## Conversation Kinds

Different conversations serve different coordination functions. Each kind has a stable identity tied to what it represents.

**Office manager conversation.** One per human. The entry point for all human interaction with TeaParty. Always available, persists across sessions.

**Project manager conversation.** One per active project session. Gate questions, corrections, project-level coordination. Closes when the session ends.

**Proxy conversation.** The human proxy participates on behalf of the human in agent-level work. The human can observe and intervene.

**Agent dispatch conversation.** Created when one agent Sends to another. Scoped to the task being delegated. Closes when the recipient Replies.

**Config lead conversation.** Configuration management interactions — agent definitions, workgroup structure, project setup.

---

## The Dispatch Chain

Work flows down through a chain of independent processes, each with its own context window:

```
Office Manager
  └── Project Manager (per project)
        └── Project Lead
              └── Workgroup Agents
```

The office manager receives human requests and routes them to the appropriate project. The project manager coordinates cross-workgroup planning. The project lead decomposes work into tasks for workgroup agents. Each level communicates with the level below via Send/Reply on the bus.

Every level is a separate `claude -p` process. The office manager does not hold the project lead's context. The project lead does not hold its workers' reasoning. Each process boundary is a hard context isolation guarantee — not a prompt instruction that might be forgotten, but a physical separation that cannot be breached.

Context compression happens naturally at each boundary. When a project lead sends a task to a worker, it includes only what the worker needs. When the worker replies, it summarizes its result. The office manager sees project-level outcomes, not agent-level deliberation. This is the structural solution to context rot described in [hierarchical-teams.md](../../overview.md).

---

## Real-Time Event Streaming

All agents stream events to the bus as they execute. Every event type is stored: thinking blocks, tool invocations, tool results, and final text responses. System events carry session initialization and state transitions.

Events relay from the bus to WebSocket connections for dashboard visibility. The dashboard receives a live stream of all agent activity across all active conversations. Stream filtering determines what the human sees by default; all event types are stored and available for inspection.

---

## Concurrency

The system enforces a ceiling of **10 concurrent agent processes**. This is a system-wide limit — across all projects, all workgroups, all conversation kinds.

Each agent may have at most **3 open conversations** tracked in its `metadata.json`. An agent that has sent three requests and is awaiting replies cannot open a fourth until one closes. This per-agent limit prevents any single lead from monopolizing the concurrency pool.

The combination of the two limits bounds total system resource consumption while allowing meaningful parallelism within a project.

---

## Context Compression

There are no dedicated intermediary agents that exist solely to reformulate or relay messages between levels. Context compression is the responsibility of the sender at each boundary.

When an agent composes a Send, it decides what context to include. A project lead sending a task to a worker includes a scoped task description, relevant file pointers, and whatever job state the worker needs — not the full project planning history. A worker replying to its lead summarizes its result — not its internal reasoning chain.

Each hop compresses. The further down the chain, the more specific and narrow the context becomes. The further up, the more summarized. This cascading compression keeps every agent's context window focused on what is relevant to its role.

---

## Relationship to Other Designs

- [messaging.md](index.md) (forthcoming) — bus storage, conversation identity, adapter interface, durability guarantees
- [hierarchical-teams.md](../../overview.md) — the structural rationale for process-isolated teams and context compression at boundaries
- [team-configuration.md](../../reference/team-configuration.md) — workgroup membership definitions that drive roster composition and routing rules
