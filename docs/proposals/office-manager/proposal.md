[Milestone 3: Human Interaction Layer](../milestone-3.md) >

# Office Manager

The office manager is the human's teammate for organization-level thinking. It is a team lead that coordinates across projects — dispatching work, synthesizing status, and transmitting the human's intent through the hierarchy.

---

## What It Is

A `claude -p` agent. Same runtime substrate as every other agent: invoked via the CLI, stream-json output, tools for reading files and inspecting state. It is the lead of the management team, whose members include:

- **The human proxy** (implicit) — handles escalations and gates across all projects, reducing escalation spam by autonomously resolving those it's confident about
- **Liaisons for each project team** — lightweight representatives that answer status queries and spawn instances when execution is needed
- **The Configuration workgroup liaison** — represents the team that creates and modifies agents, skills, hooks, and other Claude Code artifacts

The management team uses multiagent plan-and-execute. The office manager plans and coordinates. Liaisons dispatch work to their project teams. The proxy filters escalations so only the ones it can't handle reach the human. The office manager talks to its members via `AskTeam`.

---

## The Conversation

The human talks to the office manager from the dashboard (Sessions card). The conversation is free-form — no protocol drives it.

See [examples/conversation-patterns.md](examples/conversation-patterns.md) for typical interaction patterns: inquiry, steering, and action.

---

## Two Kinds of Influence

**Memory-based steering** — durable preferences that influence all future work. "Focus on security." "We're switching to Postgres next quarter." Recorded as memory chunks. They propagate indirectly, surfacing in any agent's retrieval when the context matches. For directives that should remain influential over weeks, the memory system may need a "pinned" activation floor that resists normal ACT-R decay.

**Direct intervention** — urgent action on a specific session. "Stop that session." "Withdraw that dispatch." The office manager exercises team-lead authority over its dispatches. No new infrastructure needed.

---

## Authority and Conflict Resolution

The office manager's directives represent the decider's current explicit intent. The proxy's decisions are based on learned patterns. When they conflict, the most recent direct statement wins. Recency and explicitness are the arbiters.

The boundary between office manager and proxy is load-bearing. The proxy's autonomy model depends on being the sole gate decision-maker with accuracy tracking. The office manager never approves gates directly — it records preferences so the proxy handles them at the next gate.

---

## Memory

The office manager uses the same ACT-R memory infrastructure as the proxy, sharing the same `.proxy-memory.db`. See [references/memory-model.md](references/memory-model.md) for chunk types, shared memory pool, and recording.

---

## Session Lifecycle

See [references/session-lifecycle.md](references/session-lifecycle.md) for invocation, multi-turn interaction, and between-conversation persistence.

---

## Relationship to the Proxy

The proxy and the office manager serve the same decider through different channels. The proxy learns gate behavior (what the human approves, corrects, attends to). The office manager learns coordination behavior (what they ask about, prioritize, intervene on). They share memory — what the human says in one conversation becomes context available in the other:

- In an **office manager session**, the human says "I'm worried about the database migration." The office manager records a `steering` chunk. Later, in a **separate project gate**, the proxy retrieves that chunk and gives the migration plan closer scrutiny. The proxy wasn't in the office manager conversation — it learned from the shared memory pool.
- In a **project gate**, the human corrects a plan: "this needs better error handling." The proxy records a `gate_outcome` chunk. Later, in an **office manager session**, the human asks "how are things going?" The office manager retrieves that chunk and reports error handling as a recurring concern. The office manager wasn't at the gate — it learned from the shared memory pool.

The conversations are separate. The learning crosses between them because both agents read and write the same memory database, and activation-based retrieval surfaces chunks when the context matches.

---

## Relationship to Other Proposals

- [chat-experience](../chat-experience/proposal.md) — the office manager conversation is Pattern 1
- [team-configuration](../team-configuration/proposal.md) — the management team YAML defines the office manager's team, including D-A-I human roles
- [dashboard-ui](../dashboard-ui/proposal.md) — Sessions card is the entry point
- [cfa-extensions](../cfa-extensions/proposal.md) — INTERVENE and WITHDRAW mechanics
- [proxy-review](../proxy-review/proposal.md) — the proxy review session is a separate channel to the proxy, not through the office manager
