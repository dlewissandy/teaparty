[Milestone 3: Human Interaction Layer](../milestone-3.md) >

# Agent Dispatch

Agents are not subprocesses inside a lead's context. Each agent is an independent `claude -p` invocation with its own working environment, its own skill set, and its own conversation thread on the message bus. The lead coordinates by posting messages, not by holding its team in memory.

---

## Single-Agent Invocations

Every agent — lead or worker — runs as a standalone `claude -p` process. Each agent is spawned independently with its own agent definition file (`--agent`, singular). TeaParty uses `--agents` (plural) for roster composition, not for native in-process spawning. Each roster entry defines a communication partner the agent can reach via `Send`, with a description that guides routing decisions and a field carrying the recipient's `agent_id` for bus routing.

The lead decomposes work, sends requests to named roster members, and synthesizes responses. It no longer needs to hold the whole team in context simultaneously.

The worktree composition step, roster composition, skill isolation via `--bare`, and MCP scoping via `--settings` are detailed in the [invocation model](references/invocation-model.md).

---

## Agent-to-Agent Messaging

Agent-to-agent communication goes through the message bus — the same bus that carries human-agent conversations. This supersedes the current messaging proposal's statement that agent-to-agent communication is "via MCP tools and dispatch, not through the message bus."

When an agent posts a message to a teammate via `Send`, the bus creates a conversation context. TeaParty spins up the receiving agent with that context. The exchange is multi-turn: the receiving agent can ask a follow-up, the caller can respond, all on the same context ID.

Every agent runs in an isolated context window with no visibility into any other agent's conversation history. Messages crossing a process boundary must carry enough context for the recipient to act. Two tools handle all inter-agent communication:

- **`Send(member, message)`** — delivers a message to a named roster member, opening a new thread by default. Before posting, the orchestrator flushes the current state to the job's scratch file (`{worktree}/.context/scratch.md`). The tool assembles a composite message: the agent's message as the Task section, the scratch file contents as the Context section. The recipient gets a current, self-contained brief structured for progressive disclosure — task first, job state below, pointers to detail files for anything that needs deeper reading.
- **`Reply(message)`** — responds to whoever opened the current thread and closes it. No context injection — the context is already established.

The calling agent writes naturally; the tool constructs the envelope. The scratch file is the prior: a distilled snapshot of decisions, human input, dead ends, and current state, maintained by the orchestrator from the stream. The flush-before-send ensures the snapshot reflects everything up to and including the current turn.

The execution model is write-then-exit-then-resume. A lead that sends three parallel requests records all three outstanding threads in its conversation history before exiting its current turn. It does not run concurrently with its workers. When workers call `Reply`, TeaParty tracks completions via the `pending_count` field in the bus context record; the lead is re-invoked when all threads close. The lead's state lives on the bus, not in process memory — durability across restarts and partial failures follows from that.

The bus must be a durable store, not just a message queue. Conversation context records persist across process restarts so that re-invocation can retrieve session IDs and pending state. This durability is a hard requirement placed on the Messaging proposal.

> **Implementation status.** This is the target model. The current `AskTeam` delivery path is a synchronous Unix domain socket RPC to `DispatchListener`; no message bus involvement exists. `Send` and `Reply` are the target tools; `AskTeam` is the current implementation. Implementing this model requires replacing that RPC with bus-mediated tools and re-invocation plumbing. See the [conversation model](references/conversation-model.md) for the full implementation requirements.

The [conversation model](references/conversation-model.md) covers context identity, multi-turn mechanics, the navigator hierarchy, and escalation routing.

---

## Routing and Boundaries

Bus routing determines which agents can initiate conversations with which others. Routing policy is derived from workgroup membership — a coding worker does not have a direct bus route to a config specialist. Cross-team requests within a project go through the project lead.

Cross-project communication is always mediated by the office manager. Project-scoped agents have no direct bus routes to other projects. The OM holds cross-project context and translates between them.

Routing and context translation are handled by bus rules and OM mediation, without a dedicated liaison role. This replaces Chat Experience Pattern 4 (Liaison Chat).

The [routing reference](references/routing.md) covers the full routing rule structure, agent identity, the routing table format, the OM's cross-project gateway role, the bus dispatcher location, and the disposition of #332.

---

## Relationship to Native Agent Teams

Claude Code's agent teams feature provides inter-agent messaging and shared task coordination. TeaParty uses `--agents` for roster composition but not for native in-process spawning. The distinction matters:

- **`--agents` in TeaParty** defines who an agent can communicate with and what they do. Actual communication goes through the bus — not through Claude's internal agent spawning mechanism. Each agent remains an independent `claude -p` process.
- **Native agent teams** spawn sub-agents inside the coordinating agent's session. Those agents share in-process state and exist only for the duration of the parent session. They cannot be resumed after restart.

TeaParty's bus model is architecturally distinct on the dimensions that matter for durable coordination:

- **Durable conversation history across restarts.** The bus is a persistent store. The native agent teams model uses in-memory coordination; `/resume` and `/rewind` do not restore in-process teammates.
- **Project-scoped routing with access control.** Roster composition drives the routing table; the bus dispatcher enforces it at the transport layer. Native agent teams have no equivalent routing boundary.
- **OM-mediated cross-project routing.** The OM is a first-class coordination participant. Native agent teams have no cross-project gateway concept.
- **CfA-based escalation into the human coordination protocol.** Escalation threads through the bus conversation hierarchy into existing CfA gates. Native agent teams have no equivalent.

These four distinctions are the design intent. None of the enforcement mechanisms exist in code yet — see the Implementation Status section of the [routing reference](references/routing.md). The comparison is forward-looking by design, not a claim about current behavior.

**Positioning note: Temporal.io.** The write-then-exit-then-resume execution pattern, durable state on an external store, and `pending_count`-driven fan-in re-invocation are structurally similar to Temporal.io's workflow execution model — workflow workers write decisions to a persistent event history, exit, and are re-invoked when activities complete. The similarity is not coincidental; both designs solve the same durability problem. The key difference is the state carrier. Temporal's state is a deterministic, replayable event log — workflow logic must be deterministic so the engine can reconstruct execution state by replaying events. TeaParty's state carrier is LLM conversation history, which is not deterministic and cannot be replayed. An LLM inference call is not a deterministic function of its inputs; re-running it with the same history produces different output. This is why Temporal cannot be directly applied here: Temporal's replay guarantee is undefined for non-deterministic workers. TeaParty applies the same durable execution infrastructure to agents that maintain state as language rather than as code, and whose continuation is re-invocation with restored context rather than deterministic replay.

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

- [Messaging](../messaging/proposal.md) — bus transport, conversation identity, adapter interface. The bus must be a durable persistent store; this is a hard requirement, not an optional capability. The Agent Dispatch proposal places the following requirements on the bus: two-record atomicity for sub-context creation (writing a new sub-context record and incrementing the parent's `pending_count` must succeed or fail together — a single-field CAS is not sufficient), durable writes keyed by `context_id`, and key-value lookup by both `context_id` and `agent_id`. The Messaging proposal must confirm these properties before re-invocation and fan-in can be implemented.
- [Office Manager](../office-manager/proposal.md) — OM as cross-project gateway. Cross-project routing requires the OM to expose an agent-addressable context. The OM proposal's on-demand invocation model must be extended to support a persistent listener mode. The minimal design for this mode: the OM maintains a stable session ID registered at TeaParty session start; project leads address it by the hardcoded `om` agent ID; TeaParty holds an open `--resume`-capable session for the OM independent of any human conversation. The session identity problem (who creates the initial conversation and what is its initial history) and the exit condition are open design questions that must be resolved in the OM proposal before cross-project routing can be delivered.

---

## Relationship to Other Proposals

- [Team Configuration](../team-configuration/proposal.md) — workgroup membership is the input to routing rule derivation
- [CfA Extensions](../cfa-extensions/proposal.md) — escalation events bubble up the conversation chain using the INTERVENE/WITHDRAW mechanics. Every agent spawn must inject both the immediate parent context ID and the job-level context ID so that INTERVENE can propagate from any depth in the hierarchy to the job-level conversation. CfA Extensions must define the field names for both injections and the receptive state precondition — what the job-level conversation must be doing when INTERVENE arrives.
- [Context Budget](../context-budget/proposal.md) — each agent invocation has its own context; the budget applies per-invocation. The maximum tokens injected into a freshly spawned worker (scratch file contents plus task message) is the primary constraint Agent Dispatch places on the Context Budget proposal. That ceiling must be specified before dispatch feasibility can be fully evaluated.

---

## Acceptance Criteria

The durability claim is validated when the following hold empirically:

- A session interrupted mid-fan-out (orchestrator killed while workers are active) recovers on restart: all in-flight context IDs are resumed, workers that had not replied are re-spawned, and the lead is re-invoked when the reconstituted fan-in completes.
- Message delivery is at-least-once for all `Send` and `Reply` calls within a session. Duplicate delivery is acceptable; message loss is not.
- A recovered lead's output on re-invocation is evaluated by interrupting a session at a defined checkpoint (after the lead has sent all `Send` calls and before any `Reply` arrives), recovering, and comparing the lead's final output against a control run (same session, no interruption). Equivalence is assessed by the engineer running the test against a checklist of required output properties specified before the run. The sample size for the first integration milestone is three interrupted sessions; the pass criterion is stated before the runs begin, not after.
- The maximum tested parallelism is stated explicitly at the time of the first integration test run.

These are the minimum conditions under which the durability claim is considered validated at the smoke-test milestone level — they confirm the mechanism functions, not that it reliably functions at scale. Full experimental design is out of scope for this proposal but must exist before the milestone is closed.
