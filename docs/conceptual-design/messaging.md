# Messaging

The message bus is the universal transport for all agent communication in TeaParty.

---

## Why a Bus

Agents are independent one-shot processes. A lead dispatches work to a worker, then exits. The worker runs, produces a result, then exits. Neither process is alive when the other needs to deliver a message.

This means message delivery must be durable -- messages are written to persistent storage and survive process boundaries. The bus provides this. It is the single transport layer for human-to-agent, agent-to-human, and agent-to-agent communication. Every message flows through the same infrastructure regardless of who sent it or who receives it.

---

## Message Model

A message carries five fields:

- **sender** -- who sent it (a human name, agent role, or system identifier)
- **conversation** -- which conversation it belongs to (a stable conversation ID)
- **timestamp** -- when the message was created
- **type** -- what kind: `message`, `escalation`, `intervention`, or `system`
- **content** -- the text payload

The `type` field drives downstream behavior. Escalations surface dashboard badges. Interventions trigger CfA processing (see [cfa-state-machine.md](cfa-state-machine.md)). System messages carry state transitions and lifecycle events. Ordinary messages are conversational text.

Messages are stored in SQLite. Each agent has its own persistent message database at a canonical path under the TeaParty home directory. Storage is append-only within a conversation -- messages are never modified after creation.

---

## Conversation Lifecycle

Conversations have explicit state: **active** or **closed**.

The originator owns the lifecycle. Only the participant who opened a conversation can close it. A worker that receives a task via `Send` cannot close the conversation -- it can only `Reply`, which closes its own session but leaves the conversation open for the originator to continue or close.

Conversations are identified by what they represent. The ID scheme encodes the conversation kind and its structural position:

| Kind | ID scheme | Lifecycle |
|---|---|---|
| Office manager | `om:{qualifier}` | Persistent across sessions |
| Job/session | `job:{project}:{session_id}` | Closes when session ends |
| Agent exchange | `agent:{initiator}:{recipient}:{uuid}` | Closes when exchange resolves |

The UUID suffix on agent exchanges ensures uniqueness when the same initiator sends multiple parallel tasks to the same recipient. Two simultaneous `Send` calls produce distinct context IDs.

---

## Send and Reply

Two operations handle all inter-agent communication.

**Send(member, message)** delivers a message to a named roster member. Before posting, the orchestrator flushes the agent's current state to its scratch file. The tool assembles a composite message: the agent's message as the Task section, the scratch file contents as the Context section. The recipient gets a self-contained brief -- task first, job state below, file pointers for deeper reading.

`Send` opens a new conversation thread by default. To continue an existing exchange, the caller supplies the prior context ID explicitly. There is no automatic lookup by initiator/recipient pair -- that would be ambiguous in the parallel-send case.

**Reply(message)** responds to whoever opened the current thread. Reply closes the agent's session (the process exits) but does not close the conversation. The originator retains ownership and can continue or close it.

Roster membership determines who an agent can reach via `Send`. The roster is derived from [team configuration](team-configuration.md) -- a coding worker does not have a direct route to a config specialist. Cross-team requests within a project go through the project lead.

---

## Conversation Kinds

**Office manager.** One per human. Always available, persistent across days and weeks. The human's standing channel to the office manager agent.

**Project manager.** One per project per human. Persistent. Carries project-level coordination, gate questions, and corrections.

**Proxy.** One per human. The proxy agent's dedicated channel for human interaction -- review decisions, escalation handling, dialog.

**Agent dispatch.** One per Send/Reply exchange between agents. Created by `Send`, resolved by `Reply`. Multiple dispatch conversations can be active simultaneously -- a lead managing three parallel workers holds three open context IDs. See [agent-dispatch.md](agent-dispatch.md) for the full execution model.

**Config lead.** Scoped to an entity (agent, workgroup, project). The chat blade in the dashboard holds the conversation ID and routes through the bus. Persistent as long as the entity exists.

---

## Human-to-Agent Delivery

Human messages arrive at turn boundaries. A running `claude -p` process cannot receive input mid-turn -- delivery is eventually consistent, bounded by the current turn's duration.

The delivery path:

1. Human types in the chat blade. The blade holds a `conversation_id` identifying the target conversation.
2. The message is written to the bus on that conversation ID.
3. At the next turn boundary, the agent is resumed via `--resume` with the new message injected into its conversation history.

The chat blade routes through the bus -- it does not communicate with agents directly. This means the same delivery mechanism works regardless of which dashboard view initiated the message.

---

## Agent-to-Agent Delivery

Agent-to-agent delivery follows the write-then-exit-then-resume model. No two agents in an exchange run concurrently.

The sequence:

1. Agent A calls `Send(member, message)`. The orchestrator flushes state, assembles the composite, writes it to the bus. Agent A's process exits.
2. The bus event listener detects the new message. It spawns Agent B via `claude -p` with the conversation history, including the composite message and the parent context ID.
3. Agent B does its work. When done, it calls `Reply(message)`. The reply is written to the bus on the same context ID. Agent B's process exits.
4. The bus event listener detects the reply. It appends the reply to Agent A's conversation history and re-invokes Agent A via `--resume`.
5. Agent A reads the reply and continues.

For parallel dispatch (fan-out), the lead sends to multiple workers before exiting. Each `Send` creates a distinct context ID. The bus tracks a `pending_count` on the parent context. Each `Reply` decrements it. The lead is re-invoked when `pending_count` reaches zero -- after all workers have replied.

Mid-task clarification is a separate pattern. A worker can `Send` back to the lead to ask a question, opening a new clarification thread. The lead is re-invoked in that thread, answers, and calls `Reply`. The clarification thread closes independently -- the worker's task thread and its fan-in counter are unaffected. See [agent-dispatch.md](agent-dispatch.md) for serialization mechanics.

---

## Concurrency

Each agent has a limit of three open conversations. The conversation map in the agent's `metadata.json` tracks active slots. A fourth `Send` blocks until a slot frees.

This bound exists because each open conversation represents context the agent must maintain across re-invocations. Unbounded conversations would exhaust the agent's ability to track state meaningfully. Three is enough for parallel fan-out to a small team while preventing runaway context accumulation.

The bus event listener enforces a per-agent re-invocation lock: only one `--resume` call for a given agent can be active at a time. A second re-invocation request queues until the first completes and the process exits. This ensures an agent is never running in two contexts simultaneously.

---

## Durability

The bus is a persistent store, not a transient message queue. Conversation records survive process restarts. Re-invocation can retrieve session IDs and pending state from the bus after an orchestrator crash. This durability is what makes the write-then-exit-then-resume model viable -- agent state lives on the bus, not in process memory.

At-least-once delivery is the guarantee. Duplicate delivery is acceptable; message loss is not. Recovery after interruption re-spawns any workers that had not replied and re-invokes the lead when the reconstituted fan-in completes.
