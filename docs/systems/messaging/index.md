# Messaging

Messaging is the inter-agent communication backbone of TeaParty. Every agent is an independent `claude -p` process with its own context window — no shared memory, no shared process boundary. All coordination happens by passing messages through two buses that sit at the center of the system: an **event bus** for in-process orchestrator-to-bridge signalling, and a **conversation bus** for durable, persistent communication between agents and humans.

The two buses serve different purposes and have different lifetimes. Readers often conflate them; keeping them distinct is essential to understanding how work flows through the system.

## Why it exists

Agents are one-shot processes. A lead dispatches work to a worker, then exits. The worker runs, replies, then exits. Neither process is alive when the other needs to send or receive. Communication must therefore be **durable** — messages persist across process restarts, and an agent re-invoked via `--resume` finds its conversation history intact. This is what makes the write-then-exit-then-resume execution model viable: agent state lives on the bus, not in process memory.

Durability is only one reason the messaging layer is load-bearing. The others:

- **Scoping.** Each conversation has a stable identity tied to what it represents — office manager, project session, agent dispatch, proxy review. Routing policy is derived from workgroup membership, so a coding worker has no direct route to a config specialist in a different workgroup.
- **Context isolation.** Every process boundary is a hard context barrier. A project lead cannot see its workers' internal reasoning; workers cannot see the project lead's planning history. Each `Send` compresses — the sender decides what the recipient needs.
- **Send/Reply over liaison agents.** There are no intermediary agents whose job is to reformulate messages between levels. The sender at each boundary composes the context directly. This avoids a class of telephone-game failures and keeps the dispatch chain narrow.

## How it works

**The event bus** (`teaparty/messaging/bus.py`) is an in-process async pub/sub channel. The orchestrator publishes lifecycle events — `SESSION_STARTED`, `DISPATCH_COMPLETED`, `STREAM_DATA`, `INPUT_REQUESTED`, `STATE_CHANGED`, cost/context warnings, and others — and the bridge subscribes to relay them to the dashboard over WebSocket. It is transient, runs only while the orchestrator is alive, and does not persist.

**The conversation bus** (`teaparty/messaging/conversations.py`) is a per-agent SQLite store at `{teaparty_home}/management/agents/{agent-name}/{agent-name}-messages.db`. It holds three tables: `messages` (the full conversation record), `conversations` (lifecycle state — `ACTIVE` or `CLOSED`, plus an `awaiting_input` flag), and `agent_contexts` (parent/child dispatch records with a `pending_count` for fan-in). All databases use WAL mode. This is the persistent backbone.

**Send/Reply routing** (`teaparty/messaging/listener.py`, `teaparty/messaging/dispatcher.py`) runs over Unix domain sockets. When an agent calls `Send(member, message)` via MCP, the listener creates a sub-context, launches the recipient as a background task, and returns `{status: queued}` immediately — the caller is not blocked. When the recipient process exits, `trigger_reply` closes the child context, decrements the parent's `pending_count`, injects the reply into the parent's history, and re-invokes the parent when fan-in reaches zero. A per-agent asyncio lock serializes `--resume` calls so a single agent never runs in two contexts at once.

**Conversation kinds** are enumerated in `ConversationType`: office manager, project manager, project session, subteam, job, task, proxy review, liaison, config lead, project lead. Each has a distinct ID prefix and lifetime. Agent dispatch contexts use `agent:{initiator}:{recipient}:{uuid}` — the UUID suffix guarantees parallel Sends to the same recipient get distinct contexts.

## Status

Messaging is **fully operational** and is the most mature subsystem in TeaParty. Both buses are in production use: the event bus drives every dashboard update, and the conversation bus carries every human-to-agent and agent-to-agent exchange. Fan-out/fan-in via `agent_contexts` is exercised in real sessions; routing enforcement, per-agent `--resume` serialization, and WAL-mode concurrency have all stabilized.

Remaining design surface is narrow and mostly concerns integration with adjacent systems rather than the bus itself: chat delivery atomicity is documented as a separate topic (see below), and cross-project mediation through the office manager is an operational pattern more than a code-level gap. There is no active redesign of the core bus.

## Deeper topics

- [bus-and-conversations](bus-and-conversations.md) — implementation of the event bus, conversation bus, stream processing, and the WebSocket broadcast pipeline.
- [dispatch](dispatch.md) — Send/Reply semantics, the dispatch chain, routing rules, and context compression at each hop.
- [chat-delivery](chat-delivery.md) — atomicity guarantees for chat delivery across the two buses.

Related systems: [bridge](../bridge/index.md) consumes the event bus and renders the conversation bus in the dashboard; [workspace](../workspace/index.md) launches the agent processes that read and write messages. The [execution](../../case-study/execution.md) case study traces a full session through the messaging layer end-to-end.
