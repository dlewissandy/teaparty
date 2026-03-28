# Intent Review: Issue #200

## Intent Statement
Replace the blocking FIFO IPC between humans and agents with a persistent, conversation-based message bus backed by an adapter interface. This enables concurrent conversations, async human participation, an audit trail of all human-agent interaction, and a future path to external adapters (Slack, Teams). The POC implementation uses SQLite storage, and the orchestrator reads from the message bus instead of blocking on the FIFO.

## Findings

### 1. No chat panel alongside the dashboard
**Type:** partial-implementation
**What the issue asks for:** "Textual chat panel alongside the existing dashboard" -- a visible chat UI where the human can see conversation history and interact with the message bus.
**What the diff delivers:** The existing TextArea input widget in the drilldown screen was rewired to submit via the message bus instead of FIFO. There is no new chat panel. The drilldown screen's input area is a transient prompt that appears/disappears, not a persistent conversational view.
**The gap:** The issue explicitly calls for a "Textual chat panel alongside the existing dashboard." What was delivered is a transport-layer swap under the existing modal input widget. The human still sees the same ephemeral input prompt -- they cannot scroll back through conversation history, see their own prior messages alongside agent messages, or interact with the bus as a conversation. This is the difference between replacing the plumbing (done) and delivering the experience (not done).

### 2. Office manager and subteam conversation types are defined but never used
**Type:** scaffolding
**What the issue asks for:** Three conversation types: office manager (persistent across sessions), project session (one per session), and subteam (one per dispatch, proxy participates).
**What the diff delivers:** `ConversationType` enum with all three types, `make_conversation_id()` that generates prefixed IDs for each. But only `PROJECT_SESSION` is ever instantiated. No code creates an office manager or subteam conversation. The dispatch system (`dispatch_cli.py`, `dispatch_listener.py`) does not reference the message bus at all.
**The gap:** Two of the three conversation types are dead code. The subteam conversation was supposed to replace the proxy's communication channel during dispatch -- nothing in the dispatch path uses the bus. The office manager conversation has no caller anywhere.

### 3. Dispatch and escalation listeners not migrated
**Type:** missing-integration
**What the issue asks for:** The migration path is "where the orchestrator blocks on `.input-response.fifo`, it polls the conversation instead." The dispatch_listener and escalation_listener use Unix sockets for IPC with dispatched subteams.
**What the diff delivers:** Only the top-level session's input provider was migrated. `dispatch_cli.py`, `dispatch_listener.py`, and `escalation_listener.py` have zero references to the message bus.
**The gap:** The FIFO IPC replacement is incomplete -- it only covers the main session's human-agent input path. Subteam and escalation communication still uses the old mechanisms. The issue describes subteam conversations as a core part of the design ("one per dispatch, proxy participates"), and this is entirely absent.

### 4. FIFO IPC retained as active fallback, not deprecated
**Type:** intent-drift
**What the issue asks for:** "Replace FIFO IPC with message bus reads." The migration path is described as a replacement: "semantics are identical; mechanism changes from blocking FIFO to polled message bus."
**What the diff delivers:** The drilldown screen's `_submit_input()` has a three-tier fallback: try message bus from InProcessSession, then try message bus from infra_dir, then fall back to FIFO. The `_update_input_area()` similarly falls back to TUIInputProvider.is_waiting. The old FIFO functions remain fully intact in `ipc.py`.
**The gap:** This is additive rather than a replacement. The FIFO path is still alive and active as a fallback. The issue says "replace," and while retaining backward compatibility is reasonable, the old path should be marked as deprecated or there should be a clear statement that the bus is now the primary path. The code treats both as equally valid alternatives.

## Verdict
PARTIAL

The core abstraction (MessageBusAdapter protocol, SqliteMessageBus, MessageBusInputProvider) is well-implemented and the main session input path successfully uses the message bus with a full audit trail. However:

1. **The chat panel UI is missing entirely.** The issue asks for a "Textual chat panel alongside the existing dashboard" and no such panel exists.
2. **Two of three conversation types are scaffolding** -- office manager and subteam conversations are defined but never instantiated or used.
3. **Dispatch/escalation communication is untouched** -- the subteam conversation type exists in name only.

What remains: a persistent chat panel in the TUI that shows conversation history, activation of subteam conversations in the dispatch path, and either implementing or explicitly deferring the office manager conversation.
