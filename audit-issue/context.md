# Audit Context: Issue #200

## Issue Text

**Title:** Messaging bus with adapter interface replacing FIFO IPC

### Problem

The human's only communication channel with agents is a blocking FIFO IPC (`.input-request.json` + `.input-response.fifo`). This is synchronous, single-conversation, and tied to the TUI's modal input widget. It cannot support:

- Concurrent conversations (office manager + project session)
- Async human participation (respond when available, not when blocked)
- External adapters (Slack, Teams) for future deployment
- Audit trail of human-agent interaction

### Proposal

Implement the messaging system described in docs/proposals/messaging.md.

**Core abstraction:** A message bus with three adapter methods:

```
send(conversation_id, sender, content) → message_id
receive(conversation_id, since_timestamp) → list[message]
conversations() → list[conversation_id]
```

**POC implementation:**
- SQLite storage (single table: id, conversation, sender, content, timestamp)
- Textual chat panel alongside the existing dashboard
- Orchestrator reads from message bus instead of blocking on FIFO

**Three conversation types:**
- Office manager conversation (one per human, persistent across sessions)
- Project session conversation (one per active session, closed on completion)
- Subteam conversation (one per dispatch, proxy participates)

**Migration path:** Replace FIFO IPC with message bus reads. Where the orchestrator blocks on `.input-response.fifo`, it polls the conversation instead. Semantics are identical; mechanism changes from blocking FIFO to polled message bus.

### Key design decisions documented in proposal

- Messages are plain text with sender attribution, no types or threading
- Adapter interface is auth-agnostic
- Polling vs push tradeoff for POC (FIFO was instant; polling adds latency)

### References

- docs/proposals/messaging.md — full proposal (DOES NOT EXIST in codebase)
- docs/proposals/office-manager.md — the office manager depends on this
- projects/POC/orchestrator/ipc.py — current FIFO IPC to be replaced (actually at projects/POC/tui/ipc.py)

## Design Docs

**docs/proposals/messaging.md** — DOES NOT EXIST. The issue references this as the full proposal but the file was never created. The issue body itself is the only specification.

**docs/proposals/office-manager.md** — DOES NOT EXIST. Referenced as depending on messaging.

## Diff Summary

7 files changed:
- `projects/POC/orchestrator/messaging.py` — NEW FILE (203 lines). Core abstraction: Message, ConversationType, MessageBusAdapter protocol, SqliteMessageBus, MessageBusInputProvider.
- `projects/POC/orchestrator/session.py` — MODIFIED. Creates SqliteMessageBus in infra_dir, wires MessageBusInputProvider as orchestrator input. Also includes unrelated changes from other issues (#10, #149, #197).
- `projects/POC/orchestrator/tests/test_issue_200.py` — NEW FILE (457 lines). 28 tests.
- `projects/POC/orchestrator/tui_bridge.py` — MODIFIED (+2 lines). Added message_bus_path and conversation_id to InProcessSession.
- `projects/POC/tui/ipc.py` — MODIFIED (+64 lines). Added check_message_bus_request() and send_message_bus_response().
- `projects/POC/tui/screens/drilldown.py` — MODIFIED. Replaced Future/FIFO with message bus for input submission and detection.
- `projects/POC/tui/screens/launch.py` — MODIFIED (+4 lines). Captures bus info from SESSION_STARTED event.

## Key Files to Read

- `/Users/darrell/git/teaparty/projects/POC/orchestrator/messaging.py`
- `/Users/darrell/git/teaparty/projects/POC/orchestrator/session.py`
- `/Users/darrell/git/teaparty/projects/POC/orchestrator/tui_bridge.py`
- `/Users/darrell/git/teaparty/projects/POC/orchestrator/tests/test_issue_200.py`
- `/Users/darrell/git/teaparty/projects/POC/tui/ipc.py`
- `/Users/darrell/git/teaparty/projects/POC/tui/screens/drilldown.py`
- `/Users/darrell/git/teaparty/projects/POC/tui/screens/launch.py`
- `/Users/darrell/git/teaparty/projects/POC/orchestrator/escalation_listener.py` (NOT modified — still uses Unix sockets, not message bus)
- `/Users/darrell/git/teaparty/projects/POC/orchestrator/dispatch_listener.py` (NOT modified — still uses Unix sockets)
