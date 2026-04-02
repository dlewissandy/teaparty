[Milestone 3: Human Interaction Layer](../milestone-3.md) >

# Messaging

The messaging system lets humans and agents have conversations that persist, can be resumed, and work across different interfaces.

---

## Messages

A message carries:
- **sender**: who sent it (human, proxy, office-manager, project-lead, ...)
- **conversation**: which conversation it belongs to
- **timestamp**: when
- **type**: what kind (message, escalation, intervention, system)
- **content**: text

See [examples/message-schema.md](examples/message-schema.md) for the full structure.

The `type` field distinguishes messages that sibling proposals already need to handle differently: escalations require dashboard badges, interventions trigger CfA processing, system messages carry state transitions.

Conversations are identified by what they represent: an office manager session, a project session, a dispatch. Each has a stable ID tied to the thing it represents.

---

## Conversations

Three kinds, mapping to the hierarchy.

**Office manager conversation.** One per human. Always available. Persists across sessions.

**Project session conversation.** One per active session. Gate questions, corrections, dialog. Closes when the session ends.

**Subteam conversation.** One per dispatch. The proxy participates on behalf of the human. The human can read these and drop in.

Multiple conversations can be active simultaneously.

---

## How Messages Flow

**Human to Agent.** The human types in the chat. The message is delivered to the agent's `claude -p` session via `--resume` at the next turn boundary. A running `claude -p` process cannot receive input mid-turn; delivery is eventually consistent, bounded by the current turn's duration. This replaces the FIFO IPC; see [references/migration.md](references/migration.md).

**Agent to Human.** Agent output from stream-json is parsed. Every event type is written to the bus with a typed sender — not just conversational text. A single agent turn produces multiple messages: thinking blocks (`sender: thinking`), tool invocations (`sender: tool_use`), tool results (`sender: tool_result`), and the final text response (`sender: <agent-role>`). System events (`sender: system`) carry session init and state transitions. Stream filtering (see [dashboard-ui chat-windows](../dashboard-ui/references/chat-windows.md)) determines what the human sees by default; all event types are stored and available.

**Agent to Agent.** Through the message bus, using the write-then-exit-then-resume model. An agent posts a message to a teammate via the `Send` MCP tool; the bus creates a conversation context, TeaParty spins up the receiving agent, and re-invokes the caller when a `Reply` arrives. The caller's process exits after posting — it does not run concurrently with the recipient. See [agent-dispatch/proposal.md](../agent-dispatch/proposal.md) for the full execution model.

---

## Adapter Interface

The adapter is the boundary between the message bus and whatever renders the conversation. See [references/adapter-interface.md](references/adapter-interface.md) for the three-method contract.

The adapter does not transform message content. It may add presentation formatting for the target platform (Slack markdown, card layouts), but the semantic content passes through unchanged.

---

## POC Implementation

SQLite storage, Textual chat panel, message bus replacing the FIFO IPC. See [examples/poc-implementation.md](examples/poc-implementation.md) for details.

---

## What This Enables

Messages wait for the human; no need to be watching when a gate fires. Every human-agent interaction is a stored, searchable audit trail. The adapter interface means future integrations (different UIs, notification systems) are an adapter swap with no orchestrator changes.

---

## Constraints

External adapters (Slack, Teams, cross-machine proxy) require API key authentication under Commercial Terms. See [references/compliance.md](references/compliance.md).
