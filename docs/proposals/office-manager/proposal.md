[Milestone 3: Human Interaction Layer](../milestone-3.md) >

# Office Manager

A team lead for organization-level thinking. It coordinates across projects, dispatches work, synthesizes status, and transmits the human's intent through the hierarchy.

---

## What It Is

A `claude -p` agent. Same runtime substrate as every other agent: invoked via the CLI, stream-json output, tools for reading files and inspecting state. It is the lead of the management team, whose members include:

- **The human proxy** (implicit) -- handles escalations and gates across all projects, reducing escalation spam by autonomously resolving those it is confident about
- **Liaisons for each project team** -- lightweight representatives that answer status queries and spawn instances when execution is needed
- **The Configuration workgroup liaison** -- represents the team that creates and modifies agents, skills, hooks, and other Claude Code artifacts

Multiagent plan-and-execute: the office manager plans and coordinates, liaisons dispatch work to their project teams, and the proxy filters escalations so only the ones it cannot handle reach the human. Communication between members happens via `Send` and `Reply`.

---

## The Conversation

From the dashboard's Sessions card, the human opens a free-form conversation with the office manager. No protocol drives it.

Typical interaction patterns (inquiry, steering, action) are in [examples/conversation-patterns.md](examples/conversation-patterns.md).

---

## Two Kinds of Influence

**Memory-based steering** records durable preferences that influence all future work. "Focus on security." "We're switching to Postgres next quarter." These propagate indirectly through the shared memory pool, surfacing in any agent's retrieval when the context matches. For directives that should remain influential over weeks, the memory system could use a pinned activation floor -- analogous to ACT-R's `set-base-levels` / `fixedActivation` mechanism, which sets a minimum base-level activation for tagged chunks. The tradeoff: pinned chunks occupy retrieval slots that contextually relevant but unpinned chunks would otherwise fill, potentially crowding out useful information. Whether this is worth the cost depends on how quickly steering directives decay under standard dynamics, which is an empirical question for the POC.

**Direct intervention** acts immediately on a specific session. "Stop that session." "Withdraw that dispatch." The orchestrator provides MCP tools that the office manager calls during its turn: `WithdrawSession(session_id)`, `PauseDispatch(dispatch_id)`, `ResumeDispatch(dispatch_id)`, `ReprioritizeDispatch(dispatch_id, priority)`. The orchestrator handles these like any other tool call in the stream. This is the same pattern as any agent tool -- no new infrastructure beyond the tool definitions.

---

## Authority and Conflict Resolution

The office manager's directives represent the decider's current explicit intent. The proxy's decisions are based on learned patterns. When they conflict, the most recent direct statement wins.

Two kinds of authority must be distinguished. **Gate authority** means participating as a CfA role holder (reviewer, approver) within a session's state machine. **Team-lead authority** means controlling the dispatch that contains the session: pausing, withdrawing, reprioritizing. The office manager exercises only team-lead authority. It never approves gates directly; it records preferences so the proxy is likely to retrieve them at the next gate, depending on activation and context match.

This boundary is load-bearing. The proxy's autonomy model depends on being the sole gate decision-maker with accuracy tracking.

---

## Memory

Same ACT-R memory infrastructure as the proxy, sharing `.proxy-memory.db`. Chunk types, the shared memory pool, and recording mechanics are in [references/memory-model.md](references/memory-model.md).

---

## Session Lifecycle

Invocation, multi-turn interaction, and between-session persistence are described in [references/session-lifecycle.md](references/session-lifecycle.md).

---

## Relationship to the Proxy

Both agents serve the same decider through different channels. The proxy learns gate behavior (what the human approves, corrects, attends to). The office manager learns coordination behavior (what they ask about, prioritize, intervene on). Because they share a memory database, what the human says in one conversation becomes context available in the other.

- In an **office manager session**, the human says "I'm worried about the database migration." The office manager records a `steering` chunk. Later, in a **separate project gate**, the proxy retrieves that chunk and gives the migration plan closer scrutiny.
- In a **project gate**, the human corrects a plan. The proxy records a `gate_outcome` chunk. Later, in an **office manager session**, the human asks "how are things going?" The office manager retrieves that chunk and reports the concern.

The message threads are separate. Learning crosses between them because both agents read and write the same memory database, and activation-based retrieval surfaces chunks when the context matches. (Neither agent retains its context window between invocations -- the agent session is ephemeral, rebuilt from prompt and memory each time. The message history persists; the agent context does not.)

---

## Relationship to Other Proposals

- [chat-experience](../chat-experience/proposal.md) -- the office manager conversation is Pattern 1
- [team-configuration](../team-configuration/proposal.md) -- the management team YAML defines the office manager's team, including D-A-I human roles
- [dashboard-ui](../dashboard-ui/proposal.md) -- Sessions card is the entry point
- [cfa-extensions](../cfa-extensions/proposal.md) -- INTERVENE and WITHDRAW mechanics
- [proxy-review](../proxy-review/proposal.md) -- the proxy review session is a separate channel to the proxy, not through the office manager
