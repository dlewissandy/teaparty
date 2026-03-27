[Milestone 3: Human Interaction Layer](../milestone-3.md) >

# Messaging

The messaging system lets humans and agents have conversations that persist, can be resumed, and work across different interfaces — from the local TUI today to Slack or Teams in the future.

---

## Messages

A message carries:
- **sender**: who sent it (human, proxy, office-manager, project-lead, ...)
- **conversation**: which conversation it belongs to
- **timestamp**: when
- **content**: text

See [examples/message-schema.md](examples/message-schema.md) for the full structure.

Conversations are identified by what they're about — an office manager session, a project session, a dispatch. Each has a stable ID tied to the thing it represents.

---

## Conversations

Three kinds, mapping to the hierarchy:

**Office manager conversation.** One per human. Always available. Persists across sessions.

**Project session conversation.** One per active session. Gate questions, corrections, dialog. Closes when the session ends.

**Subteam conversation.** One per dispatch. The proxy participates on behalf of the human. The human can read these and drop in.

Multiple conversations can be active simultaneously.

---

## How Messages Flow

**Human → Agent.** The human types in the chat. The message is delivered to the agent's `claude -p` session via `--resume`. This replaces the FIFO IPC — see [references/migration.md](references/migration.md).

**Agent → Human.** Agent output from stream-json is parsed. Conversational content becomes messages. Stream filtering (see [dashboard-ui chat-windows](../dashboard-ui/references/chat-windows.md)) determines what the human sees.

**Agent → Agent.** Via MCP tools (AskQuestion, AskTeam) and dispatch — not through the message bus.

---

## Adapter Interface

The adapter is the boundary between the message bus and whatever renders the conversation. See [references/adapter-interface.md](references/adapter-interface.md) for the three-method contract.

The adapter is auth-agnostic and does not transform content.

---

## POC Implementation

SQLite storage, Textual chat panel, message bus replacing the FIFO IPC. See [examples/poc-implementation.md](examples/poc-implementation.md) for details.

---

## What This Enables

- **Slack/Teams integration** — adapter swap, no orchestrator changes
- **Mobile access** — respond to gates from a phone via external adapter
- **Audit trail** — every human-agent interaction is a stored message
- **Async participation** — messages wait for the human; no need to be watching when a gate fires

---

## Constraints

External adapters (Slack, Teams, cross-machine proxy) require API key authentication under Commercial Terms. See [references/compliance.md](references/compliance.md).
