# The Office Manager: Human-Initiated Conversation and Cross-Project Coordination

The current system is asymmetric. Agents talk to humans when *they* need something: at approval gates, during escalations, when the proxy is uncertain. Humans wait. This is unlike any real team, where people walk in at any time, ask what's going on, redirect priorities, or tell everyone to stop.

The office manager fixes this by giving humans a seat at the coordination level.

---

## Position in the Hierarchy

The office manager is a team lead, one level above projects. It sits in the corporate hierarchy the same way the org lead sits above workgroups in [overview.md](../overview.md).

```
    Office Manager (team lead)
    ├── Human(s) — team members with direct access
    │
    ├── AskTeam → POC Project (subteam)
    ├── AskTeam → Joke-book Project (subteam)
    └── AskTeam → ... (subteam)
```

Humans are members of the office manager's team. They have a seat at the table. They can speak at any time because they are participants, not external observers being consulted. The office manager coordinates across projects, dispatches work to project-level teams via the existing `AskTeam` infrastructure, and reports back.

This is the same hierarchical team pattern used everywhere in TeaParty. The office manager doesn't need special interruption infrastructure. Team leads already control their dispatches. Pause, withdraw, reprioritize — these are things a team lead does.

## Human Participation at All Levels

The office manager does not gate access to projects. Humans retain direct participation at every level of the hierarchy:

- **Office manager team** — coordination, cross-project visibility, steering. Humans talk to the office manager here.
- **Project team** — CfA sessions, hands-on work. Humans can drop directly into any project session and participate. This is where sessions live today.
- **Subteams** — the proxy stands in for humans at this level (humans can't attend every meeting), but a human could drop in if they wanted to.

The office manager is a coordination layer, not a gatekeeper. The human's hands are always on the wheel. The TUI dashboard is the human's view across all levels. From it they can talk to the office manager for the cross-cutting view, enter a project session directly for hands-on work, or review what's happening at any level.

---

## Multiple Humans, One Decider

Teams can have multiple human members. Different humans may participate at different levels with different roles. One human might be the strategic lead working with the office manager. Another might be a domain expert who drops into specific project sessions. Another might only review final deliverables.

Every project has a **decider** — the human whose approval matters at gates. Others can inform or advise, but the proxy models the decider specifically. The proxy's prediction target is always: "what would the decider say?"

At the office manager level, the team also has a decider — the human who owns the portfolio. Other humans contribute context, ask questions, provide domain knowledge. Their inputs are valuable (stored as memory chunks, attributed to their source) but the office manager's coordination priorities come from the decider.

This keeps the proxy clean: one proxy per decider per level. Other humans' inputs are context, not prediction targets.

---

## What the Office Manager Is

The office manager is a `claude -p` agent. Same runtime substrate as every other agent: invoked via the CLI, stream-json output, tools for reading files and inspecting state. It is a team lead that happens to coordinate across projects rather than executing CfA phases within one.

It is the human's teammate for organization-level thinking. When the human wants to know what's happening across projects, they talk to the office manager. When they want to redirect priorities or inject context that crosses project boundaries, they tell it. When they have a thought that doesn't fit into any single project's workflow, the office manager is where it goes.

## What the Office Manager Is Not

It is not the proxy. The proxy is a full Claude agent that stands in for the decider at gates, reasoning about artifacts with tools and ACT-R memory. The office manager doesn't make gate decisions. It coordinates.

It is not an orchestrator. It does not run CfA phases or manage session state machines. It dispatches to project teams via `AskTeam`, the same way any team lead dispatches to subteams. The project orchestrators execute independently.

It is not a dashboard. The TUI dashboard shows state. The office manager interprets state and takes action on it.

---

## Relationship to the CfA Protocol

The office manager operates above the CfA protocol, not within it. It is a team lead whose subteams run CfA sessions. It does not occupy a role in the state machine (proposer, reviewer, approver).

When the office manager pauses or withdraws a project session, it is exercising team-lead authority over a dispatch, not making a CfA state transition as a protocol participant. This is analogous to a manager canceling a meeting. The manager is not a meeting participant, but the meeting still ends.

The CfA state machine has defined roles and legal transitions. The office manager is not bound by those roles. It acts with the decider's authority, relayed through the existing team hierarchy.

---

## The Conversation

Humans on the office manager's team can talk to it at any time from the TUI dashboard. The office manager is invoked via `claude -p` with its team agent definition, tools (Read/Glob/Grep/Bash), ACT-R memory chunks, and MCP tools for dispatching to project teams.

The conversation is free-form.

### Inquiry

> "What's going on with the POC project?"

The office manager reads session state files, git logs, dispatch results, CfA state JSONs. It synthesizes a narrative: what's running, what's blocked, what completed recently, what looks unusual.

> "Why did the planning phase backtrack?"

It reads the CfA state history and the backtrack feedback, explains the chain of events.

### Steering

> "Focus on security aspects first for all active sessions."

The office manager records this as a priority directive in shared memory. When the proxy next retrieves memories at a gate, this high-activation chunk surfaces and influences the review. Steering propagates through memory, not by modifying prompts in active sessions.

The human needs to know whether their steering took effect. On the next conversation, the office manager can inspect recent proxy gate decisions and their retrieval context to report whether the steering chunk was retrieved and influential.

> "That approach to the database migration won't work because we're switching to Postgres next quarter."

Context that exists only in the human's head. The office manager records it as a memory chunk. When agents next work on database-related tasks, this context is retrievable.

### Action

> "Can you make sure all my projects are committed and pushed?"

The office manager uses its tools to check git status across all project worktrees, commits and pushes where needed, reports what it did.

> "Withdraw the current session on the POC project."

The office manager exercises its team-lead authority over the dispatch, setting the CfA state to WITHDRAWN.

> "Hold the presses — stop all active dispatches."

The office manager pauses all active dispatches. No new phases launch; work already in progress completes.

---

## Two Kinds of Influence

The office manager transmits the human's intent through two mechanisms. The boundary between them is scope and urgency.

**Memory-based steering** is for durable preferences that should influence all future work. "Focus on security." "We're switching to Postgres next quarter." Recorded as memory chunks. They propagate indirectly, surfacing in any agent's retrieval when the context matches. Broad, ongoing, eventually consistent. For directives that should remain influential over weeks, the memory system may need a "pinned" activation floor that resists normal ACT-R decay.

**Direct intervention** is for urgent action on a specific session. "Stop that session." "Withdraw that dispatch." The office manager exercises team-lead authority over its dispatches — the same authority any team lead has over subteam work in the existing hierarchy. No new infrastructure needed beyond what the dispatch system already provides.

---

## Authority and Conflict Resolution

The office manager's directives represent the decider's current explicit intent. The proxy's decisions are based on learned patterns from prior gate interactions. When they conflict, the office manager's directives take precedence.

This is consistent with how the proxy already works. Gate corrections override proxy predictions. A steering chunk from the office manager is the same thing: the decider speaking directly about what they want. The proxy's learned pattern ("this decider usually approves plans without rollback strategies") yields to the explicit directive ("I want rollback strategies in every plan").

The precedence is temporal and explicit. The most recent direct statement wins. If the decider told the office manager "focus on security" yesterday and then approves a non-security plan at a gate today, the gate approval is the most recent signal. Recency and explicitness are the arbiters.

When multiple humans contribute, their inputs are attributed. The decider's directives take precedence. An advisor's context injection is valuable information, not a binding directive.

---

## Memory

The office manager uses the same ACT-R memory infrastructure as the proxy. Same `MemoryChunk` dataclass, same activation dynamics, same SQLite storage. Different chunk types.

### Chunk Types

| Type | What it captures | Example |
|------|-----------------|---------|
| `inquiry` | What a human asked about | "Asked about POC project status" |
| `steering` | Priority or preference directive | "Decider wants security focus across all sessions" |
| `action_request` | What a human asked the office manager to do | "Requested commit and push for all projects" |
| `context_injection` | Domain knowledge a human volunteered | "Advisor: switching to Postgres next quarter" |

Chunks are attributed to the human who produced them. The decider's steering chunks and an advisor's context injections are both stored but carry different weight — the decider's chunks are prediction targets for the proxy, the advisor's are informational context.

### Shared Memory Pool

The office manager and the proxy serve the same decider. Both read and write to the same `.proxy-memory.db`. Chunk type discriminates reads: the proxy queries for `gate_outcome` chunks, the office manager queries for `inquiry` and `steering` chunks. Either can query across types when the structural filters match. The proxy retrieving a `steering` chunk ("decider said focus on security") while reviewing a security plan is the right behavior.

SQLite in WAL mode handles concurrent access. The write pattern (infrequent chunk insertions) makes contention negligible.

### Recording Chunks from Conversation

The office manager itself decides what to record. At conversation end, a final prompt turn asks the office manager to summarize what the humans cared about and produce memory chunks. This is consistent with how agents work in this system: they are autonomous, not scripted. The recording is an agent judgment, not a mechanical extraction.

---

## Session Lifecycle

The office manager's conversation is a `claude -p` session. Unlike single-turn agent invocations within CfA phases, the office manager conversation may be multi-turn. The runtime substrate is the same; the usage pattern differs.

### Invocation

A human presses a key in the TUI. The TUI invokes `claude -p` with the office manager's team agent definition, tools, ACT-R memory, and a platform state summary.

### Multi-Turn

The first invocation returns a session ID. Subsequent messages use `--resume <session_id>`. The office manager retains context across turns within a conversation. Operational concerns (context window limits, session persistence) belong in detailed design.

### Between Conversations

The office manager is not persistent between conversations. Each starts fresh from `claude -p`. ACT-R memory carries forward what the agent judged worth remembering. A fresh agent with persistent memory avoids unbounded state, context pressure, and drift.

---

## Relationship to the Proxy

The proxy and the office manager serve the same decider through different channels.

The proxy is the decider's shadow inside the CfA protocol. It appears at gates, reasons about artifacts, and earns autonomy through accurate prediction. Its memory is tuned for gate decisions.

The office manager is the decider's voice above the CfA protocol. It appears when a human initiates conversation, coordinates across projects, and earns trust by being useful. Its memory is tuned for priorities and cross-cutting context.

They share memory because they serve the same decider. The shared pool makes cross-pollination automatic. A steering directive given to the office manager influences the proxy's next gate review without explicit forwarding.

The boundary between them is load-bearing. The proxy's autonomy model depends on being the sole gate decision-maker, with accuracy tracking. If the office manager could also approve gates, the proxy's metrics would lose meaning. When a human asks the office manager to approve something, the right response is to record their preference so the proxy handles it at the next gate.

---

## Open Questions

1. **How is the conversation triggered from the TUI?** A dedicated keystroke? A persistent chat panel? An overlay?

2. **Should the office manager proactively surface information?** "I noticed the POC session has been in planning for an hour." This is proactive conversation from agent to human — the reverse of the pattern this document describes. A future extension.

3. **How do multiple humans interact in the same conversation?** Turn-taking? Separate sessions? The office manager models a team with multiple human members, but the conversation mechanics need design.

4. **What are the evaluation criteria?** The proxy has gate prediction accuracy. The office manager's equivalent likely centers on conversation utility. To be defined during detailed design.
