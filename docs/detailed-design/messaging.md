# Messaging System

Detailed design for the persistent message bus, event listener, stream processing,
and WebSocket broadcast pipeline.

Source files:

- `teaparty/messaging/conversations.py` -- SqliteMessageBus, conversation types and state
- `teaparty/messaging/bus.py` -- EventBus (in-process async pub/sub)
- `teaparty/messaging/listener.py` -- BusEventListener (Unix socket IPC for Send/Reply)
- `teaparty/teams/stream.py` -- Stream event classification and live relay
- `teaparty/bridge/message_relay.py` -- MessageRelay (WebSocket broadcast to dashboard)

---

## SqliteMessageBus

`SqliteMessageBus` is the persistence layer for human-agent and agent-agent
conversations.  Each agent has its own SQLite database at
`{teaparty_home}/management/agents/{agent-name}/{agent-name}-messages.db`,
located by the `agent_bus_path()` helper.

### Schema

Two primary tables:

**messages** -- `(id TEXT PK, conversation TEXT, sender TEXT, content TEXT, timestamp REAL)`.
Indexed on `(conversation, timestamp)` for efficient range queries.

**conversations** -- `(id TEXT PK, type TEXT, state TEXT, created_at REAL, awaiting_input INTEGER)`.
Tracks conversation lifecycle and input-request flags.

**agent_contexts** -- `(context_id TEXT PK, initiator_agent_id, recipient_agent_id,
parent_context_id, session_id, status, pending_count INTEGER, created_at,
conversation_status, agent_worktree_path)`.  Tracks agent-to-agent dispatch
contexts for fan-out/fan-in coordination (issue #351).

All databases use WAL mode for concurrent read safety.

### Conversation types

The `ConversationType` enum defines ten conversation scopes:

| Type | Prefix | Persistence | Scope |
|------|--------|-------------|-------|
| `OFFICE_MANAGER` | `om:` | Indefinite | One per human |
| `PROJECT_MANAGER` | `pm:` | Indefinite | One per project+human |
| `PROJECT_SESSION` | `session:` | Session | Closes when session ends |
| `SUBTEAM` | `team:` | Dispatch | One per dispatch |
| `JOB` | `job:` | Job | One per project+job |
| `TASK` | `task:` | Task | One per project+job+task |
| `PROXY_REVIEW` | `proxy:` | Indefinite | One per decider |
| `LIAISON` | `liaison:` | Session | Requester+target |
| `CONFIG_LEAD` | `config:` | Indefinite | One per entity-scope |
| `PROJECT_LEAD` | `lead:` | Indefinite | One per project lead |

Conversation IDs are namespaced: `make_conversation_id(type, qualifier)` produces
e.g. `om:primus` or `session:20260327-143000`.

### Conversation state

`ConversationState` is either `ACTIVE` or `CLOSED`.  The bus rejects writes to
closed conversations with a `ValueError`.  The `awaiting_input` flag signals that
the orchestrator is waiting for human input; the bridge polls this to surface
input-requested events.

### Agent contexts and fan-in

The `agent_contexts` table tracks agent-to-agent dispatch.  When an agent fans out
to N workers, each child context is created atomically with `create_sub_context()`,
which increments the parent's `pending_count` in the same transaction.  As each
worker replies, `decrement_pending_count()` decrements the counter.  When it
reaches zero the fan-in is complete and the caller is re-invoked.

---

## EventBus (in-process pub/sub)

`EventBus` in `bus.py` is a lightweight async pub/sub for orchestrator-to-bridge
communication within the same process.  It defines 18 event types:

- Session lifecycle: `SESSION_STARTED`, `SESSION_COMPLETED`
- Dispatch lifecycle: `DISPATCH_STARTED`, `DISPATCH_COMPLETED`
- Phase lifecycle: `PHASE_STARTED`, `PHASE_COMPLETED`
- State: `STATE_CHANGED`
- Streaming: `STREAM_DATA`, `STREAM_ERROR`
- Input: `INPUT_REQUESTED`, `INPUT_RECEIVED`
- Control: `WITHDRAW`, `INTERVENE`
- Health: `FAILURE`, `LOG`, `API_OVERLOADED`
- Cost: `COST_WARNING`, `COST_LIMIT`, `CONTEXT_WARNING`, `TURN_COST`

Each `Event` carries `type`, `data` dict, `session_id`, and `timestamp`.
Subscribers are async callbacks; failures are logged but do not propagate.

The `InputRequest` dataclass describes what the orchestrator needs: `type`
(approval, prompt, dialog, failure), CfA `state`, optional `artifact` path,
`bridge_text` summary, and human-readable `options`.

---

## BusEventListener (Unix socket IPC)

`BusEventListener` bridges MCP tool calls (Send, Reply, CloseConversation) to
bus operations via Unix domain sockets.  The orchestrator starts four sockets
before launching Claude Code:

| Socket | Purpose |
|--------|---------|
| `send.sock` | Receives Send(member, composite, context_id) calls |
| `reply.sock` | Receives Reply(message) calls |
| `close.sock` | Receives CloseConversation calls |
| `interject.sock` | Receives bridge-triggered interjections (--resume) |

### Send flow

1. Agent calls Send via MCP; the MCP server connects to `send.sock`.
2. Listener receives `{type: "send", member, composite, context_id}`.
3. If `context_id` refers to an existing open conversation, the recipient's
   prior session is resumed (not spawned fresh).
4. If the conversation is closed, an error is returned immediately.
5. For new conversations, a context record is created synchronously in the bus.
6. `spawn_fn(member, composite, context_id)` runs as a background task.
7. `{status: "queued", context_id}` is returned immediately -- non-blocking.

Context IDs follow the format `agent:{initiator}:{recipient}:{uuid4}`.  The UUID
suffix ensures parallel Send calls to the same recipient produce distinct contexts.

### Reply flow and fan-in

1. Agent calls Reply; listener closes the current agent context record.
2. `reply_fn(context_id, session_id, message)` injects the result into the
   caller's conversation history.
3. The parent's `pending_count` is decremented.  When it reaches zero,
   `reinvoke_fn` triggers the caller's re-invocation.
4. Per-agent `asyncio.Lock` instances serialize concurrent `--resume` calls
   for the same agent, preventing race conditions in fan-in scenarios.

---

## Stream processing

`teaparty/teams/stream.py` provides two key functions for real-time event handling.

### _classify_event

Maps raw stream-json event dicts to `(sender, content)` pairs:

- `assistant` events: iterates content blocks -- `thinking` blocks yield
  `('thinking', text)`, `text` blocks yield `(agent_role, text)`, `tool_use`
  blocks yield `('tool_use', JSON)`.
- `tool_use` / `tool_result` events: yield their respective sender labels.
- `user` events: extracts `tool_result` blocks from content.
- `system` events: yield `('system', JSON)`.
- `result` events: yield `('cost', JSON)` with token/cost stats.

Deduplication: `tool_use` and `tool_result` events are tracked by ID in
`seen_tool_use` and `seen_tool_result` sets, preventing duplicate entries
when the same tool call appears in both `assistant` and standalone events.

`NON_CONVERSATIONAL_SENDERS` (thinking, tool_use, tool_result, system,
orchestrator, state, cost, log) filters internal trace from conversational history.

### _make_live_stream_relay

Returns `(callback, events)` for real-time streaming to the message bus.
The callback processes each stream-json event synchronously: for every
`(sender, content)` pair from `_classify_event`, it writes immediately to
the bus via `bus.send(conv_id, sender, content)` and appends to the events list
for post-processing.

---

## WebSocket broadcast: MessageRelay

`MessageRelay` in `teaparty/bridge/message_relay.py` polls per-session message
buses and pushes events to the dashboard via WebSocket.

### Architecture

- Holds a shared `bus_registry: dict[session_id, SqliteMessageBus]` (managed
  by the StatePoller).
- Tracks `_last_ts: dict[conversation_id, float]` for incremental polling.
- Tracks `_awaiting: set[conversation_id]` to avoid redundant input_requested events.

### Poll cycle

`poll_once()` iterates all active buses:

1. For each conversation, fetches messages since `_last_ts[cid]`.
2. Broadcasts each new message as `{type: "message", id, conversation_id, sender,
   content, timestamp}`.
3. Queries `conversations_awaiting_input()` for flag changes.
4. For newly-awaiting conversations, fetches the latest orchestrator message as
   the question text and broadcasts `{type: "input_requested", session_id,
   conversation_id, question}`.

`run()` loops `poll_once()` at a configurable interval (default 1 second).

### Event types emitted

| Event type | Payload | Trigger |
|------------|---------|---------|
| `message` | id, conversation_id, sender, content, timestamp | New message in any conversation |
| `input_requested` | session_id, conversation_id, question | `awaiting_input` flag set on a conversation |
