[Milestone 3: Human Interaction Layer](../milestone-3.md) >

# Agent Dispatch

Agents are not subprocesses inside a lead's context. Each agent is an independent `claude -p` invocation with its own working environment, its own skill set, and its own conversation thread on the message bus. The lead coordinates by posting messages, not by holding its team in memory.

---

## Single-Agent Invocations

Every agent — lead or worker — runs as a standalone `claude -p` process. Each agent is spawned independently with its own agent definition file (`--agent`, singular). TeaParty uses `--agents` (plural) for roster composition, not for native in-process spawning — each entry defines a communication partner the agent can reach via `Send`, with a description that guides routing decisions and a prompt field that carries the recipient's `agent_id` for bus routing.

This changes the lead's role: it decomposes work, sends requests to named roster members, and synthesizes responses. It no longer needs to hold the whole team in context simultaneously.

The worktree composition step, roster composition, skill isolation via `--bare`, and MCP scoping via `--settings` are detailed in the [invocation model](references/invocation-model.md).

---

## Agent-to-Agent Messaging

Agent-to-agent communication goes through the message bus — the same bus that carries human-agent conversations. This supersedes the current messaging proposal's statement that agent-to-agent communication is "via MCP tools and dispatch, not through the message bus."

When an agent posts a message to a teammate via the `AskTeam` MCP tool, the bus creates a conversation context. TeaParty spins up the receiving agent with that context. The exchange is multi-turn: the receiving agent can ask a follow-up, the caller can respond, all on the same context ID.

Every agent runs in an isolated context window with no visibility into any other agent's conversation history. Messages crossing a process boundary must carry enough context for the recipient to act. Two tools handle all inter-agent communication:

- **`Send(member, message)`** — delivers a message to a named roster member, opening or continuing a thread. Before posting, the orchestrator flushes the current state to the job's scratch file (`{worktree}/.context/scratch.md`). The tool assembles a composite message: the agent's message as the Task section, the scratch file contents as the Context section. The recipient gets a current, self-contained brief structured for progressive disclosure — task first, job state below, pointers to detail files for anything that needs deeper reading.
- **`Reply(message)`** — responds to whoever opened the current thread and closes it. No context injection — the context is already established.

The calling agent writes naturally; the tool constructs the envelope. The scratch file is the prior: a distilled snapshot of decisions, human input, dead ends, and current state, maintained by the orchestrator from the stream. The flush-before-send ensures the snapshot includes everything up to and including the current turn.

The execution model is write-then-exit-then-resume. A lead that sends three parallel requests records all three outstanding threads in its conversation history before exiting its current turn. It is not running concurrently with its workers. When workers call `Reply`, TeaParty tracks completions via the `pending_count` field in the bus context record; the lead is re-invoked when all threads close. The lead's state lives on the bus, not in process memory — this is what makes it durable across restarts and partial failures.

The bus must be a durable store, not just a message queue. Conversation context records persist across process restarts so that re-invocation can retrieve session IDs and pending state. This durability is a hard requirement placed on the Messaging proposal.

> **Implementation status.** This is the target model. The current `AskTeam` delivery path is a synchronous Unix domain socket RPC to `DispatchListener`; no message bus involvement exists. Implementing this model requires replacing that RPC with bus-mediated tools and re-invocation plumbing. See the [conversation model](references/conversation-model.md) for the full implementation requirements.

The [conversation model](references/conversation-model.md) covers context identity, multi-turn mechanics, the navigator hierarchy, and escalation routing.

---

## Routing and Boundaries

Bus routing determines which agents can initiate conversations with which others. Routing policy is derived from workgroup membership — a coding worker does not have a direct bus route to a config specialist. Cross-team requests within a project go through the project lead.

Cross-project communication is always mediated by the office manager. Project-scoped agents have no direct bus routes to other projects. The OM holds cross-project context and translates between them.

Routing and context translation are handled by bus rules and OM mediation, without a dedicated liaison role. This replaces Chat Experience Pattern 4 (Liaison Chat).

The [routing reference](references/routing.md) covers the full routing rule structure, agent identity, the routing table format, the OM's cross-project gateway role, the bus dispatcher location, and the disposition of #332.

---

## Relationship to Native Agent Teams

Claude Code's native agent teams feature (experimental, `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) provides inter-agent messaging and shared task coordination. TeaParty uses `--agents` for roster composition but not for native in-process spawning. The distinction matters:

- **`--agents` in TeaParty** defines who an agent can communicate with and what they do. The `prompt` field carries the bus routing key. Actual communication goes through the bus — not through Claude's internal agent spawning mechanism. Each agent remains an independent `claude -p` process.
- **Native agent teams** spawn sub-agents inside the coordinating agent's session. Those agents share in-process state and exist only for the duration of the parent session. They cannot be resumed after restart.

TeaParty's bus model is architecturally distinct on the dimensions that matter for durable coordination:

- **Durable conversation history across restarts.** The bus is a persistent store. The native agent teams model uses in-memory coordination; `/resume` and `/rewind` do not restore in-process teammates.
- **Project-scoped routing with access control.** Roster composition drives the routing table; the bus dispatcher enforces it at the transport layer. Native agent teams have no equivalent routing boundary.
- **OM-mediated cross-project routing.** The OM is a first-class coordination participant. Native agent teams have no cross-project gateway concept.
- **CfA-based escalation into the human coordination protocol.** Escalation threads through the bus conversation hierarchy into existing CfA gates. Native agent teams have no equivalent.

These differences are not incidental. They are what "durable, scalable agent coordination" requires that the platform's native primitives do not yet provide.

---

## Skill Isolation

Each agent invocation gets a worktree with a composed `.claude/skills/` directory. Skill composition layers common skills, role-specific skills, and project-scoped skills. Project skills win on name collision. The orchestrator performs this composition at spawn time — it already knows the agent's role and project context.

`--bare` suppresses all auto-discovery, so the agent sees exactly the composed set and nothing else. TeaParty's own orchestration skills are never in the composition unless the agent's role explicitly includes them.

---

## Supersedes

- [messaging/proposal.md](../messaging/proposal.md) — "Agent to Agent" section: agent-to-agent now goes through the bus
- [chat-experience/proposal.md](../chat-experience/proposal.md) — Pattern 4 (Liaison Chat): replaced by bus routing rules and OM mediation
- #332 — OM chat invocation missing liaisons: the liaison agent definitions in `orchestrator/office_manager.py` are superseded by bus routing rules; the routing function moves to the bus dispatcher and OM mediation

---

## Prerequisites

- [Messaging](../messaging/proposal.md) — bus transport, conversation identity, adapter interface. The bus must be a durable persistent store; this is a hard requirement, not an optional capability.
- [Office Manager](../office-manager/proposal.md) — OM as cross-project gateway. Cross-project routing requires the OM to expose an agent-addressable context. The OM proposal's on-demand invocation model must be extended to support a persistent listener mode — the OM must be addressable by project leads without a human-initiated conversation as the carrier. This work is in scope for this proposal's implementation; cross-project agent routing cannot be delivered without it.

---

## Relationship to Other Proposals

- [Team Configuration](../team-configuration/proposal.md) — workgroup membership is the input to routing rule derivation
- [CfA Extensions](../cfa-extensions/proposal.md) — escalation events bubble up the conversation chain using the INTERVENE/WITHDRAW mechanics. Every agent spawn must inject the job-level context ID so that INTERVENE can propagate from sub-conversation contexts to the job-level conversation. CfA Extensions must also define the receptive state precondition — what the job-level conversation must be doing when INTERVENE arrives.
- [Context Budget](../context-budget/proposal.md) — each agent invocation has its own context; the budget applies per-invocation
