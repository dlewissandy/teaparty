# Factcheck Review: Issue #200

## Scope

**Design doc:** The issue references `docs/proposals/messaging.md` but that file does not exist. The issue body itself is the only specification. All checks below are against the issue body requirements.

**Changed files checked:**
- `projects/POC/orchestrator/messaging.py` (new)
- `projects/POC/orchestrator/session.py` (modified)
- `projects/POC/orchestrator/tui_bridge.py` (modified)
- `projects/POC/tui/ipc.py` (modified)
- `projects/POC/tui/screens/drilldown.py` (modified)
- `projects/POC/tui/screens/launch.py` (modified)
- `projects/POC/orchestrator/tests/test_issue_200.py` (new)

## Findings

### 1. Missing Textual chat panel
**Severity:** high
**Code location:** `projects/POC/tui/screens/` (no chat panel exists)
**Doc location:** Issue body, "POC implementation" section
**Doc says:** "Textual chat panel alongside the existing dashboard"
**Code does:** No chat panel widget was created. The existing `TextArea` input widget in `drilldown.py` was rewired to use the message bus for transport, but this is the same modal input widget, not a chat panel alongside the dashboard.
**Gap:** The issue specifies a dedicated chat panel as part of the POC implementation. The diff only changes the transport layer for the existing modal input widget. There is no persistent, visible chat UI showing conversation history.

### 2. Subteam conversations not wired
**Severity:** medium
**Code location:** `projects/POC/orchestrator/messaging.py:49` (ConversationType.SUBTEAM defined), `projects/POC/orchestrator/dispatch_cli.py` (not modified)
**Doc location:** Issue body, "Three conversation types" section
**Doc says:** "Subteam conversation (one per dispatch, proxy participates)"
**Code does:** `ConversationType.SUBTEAM` is defined with prefix `team:`, and `make_conversation_id` can generate subteam IDs. However, no code creates subteam conversations. `dispatch_cli.py` and `dispatch_listener.py` are unmodified.
**Gap:** The subteam conversation type is defined but never instantiated or used at runtime. No dispatch creates a subteam conversation, and the proxy does not participate in one.

### 3. Office manager conversation not wired
**Severity:** medium
**Code location:** `projects/POC/orchestrator/messaging.py:47` (ConversationType.OFFICE_MANAGER defined)
**Doc location:** Issue body, "Three conversation types" section
**Doc says:** "Office manager conversation (one per human, persistent across sessions)"
**Code does:** `ConversationType.OFFICE_MANAGER` is defined with prefix `om:`. No code creates an office manager conversation. The context notes `docs/proposals/office-manager.md` does not exist either.
**Gap:** The office manager conversation type is defined but never instantiated. This may be intentionally deferred since the office manager feature itself does not exist yet, but the issue lists it as one of the three conversation types to implement.

### 4. Design doc referenced but never created
**Severity:** medium
**Code location:** N/A
**Doc location:** Issue body, References section: "docs/proposals/messaging.md -- full proposal"
**Doc says:** The issue references `docs/proposals/messaging.md` as the full proposal.
**Code does:** This file was never created. The implementation was done from the issue body alone.
**Gap:** The referenced design doc does not exist. The issue body served as the de facto spec, which means there is no canonical design document for future reference or cross-issue linking.

## Verified Consistent

1. **Core abstraction matches spec.** The three adapter methods `send(conversation_id, sender, content) -> message_id`, `receive(conversation_id, since_timestamp) -> list[message]`, and `conversations() -> list[conversation_id]` are implemented exactly as specified in the `MessageBusAdapter` protocol (`messaging.py:68-83`).

2. **SQLite storage schema matches spec.** Single table with columns `id, conversation, sender, content, timestamp` (`messaging.py:97-103`). WAL mode enabled for concurrent read safety.

3. **Project session conversation type works end-to-end.** `Session.run()` creates `SqliteMessageBus` in `infra_dir/messages.db`, generates a `session:` prefixed conversation ID, wraps it in `MessageBusInputProvider`, and wires it as the effective input provider to the `Orchestrator` (`session.py:152-164, 245`). Same for `Session.resume_from_disk()` (`session.py:604-616, 669`).

4. **Migration path from FIFO implemented correctly.** The orchestrator now uses `MessageBusInputProvider` which polls the message bus instead of blocking on FIFO. The `effective_input = self._bus_input_provider or self.input_provider` pattern (`session.py:245, 669`) correctly falls back to the original provider when no bus is available. The TUI's `drilldown.py` checks the message bus first, then falls back to TUIInputProvider, then to FIFO -- maintaining backward compatibility.

5. **Messages are plain text with sender attribution.** The `Message` dataclass has `sender` and `content` fields, no message types or threading. Consistent with spec.

6. **Adapter interface is auth-agnostic.** The `MessageBusAdapter` protocol has no authentication parameters. Consistent with spec.

7. **Audit trail preserved.** `MessageBusInputProvider.__call__` records both the orchestrator's question and the human's response in the bus (`messaging.py:187-199`). All messages persist in SQLite for audit.

8. **SESSION_STARTED event includes bus info.** Both `Session.run()` and `Session.resume_from_disk()` publish `message_bus_path` and `conversation_id` in the SESSION_STARTED event data (`session.py:189-190, 634-635`). The TUI captures these in `launch.py:137-138` and `drilldown.py:575-576`.

9. **TUI IPC extended with bus transport.** `ipc.py` adds `check_message_bus_request()` and `send_message_bus_response()` that correctly detect pending orchestrator questions and submit human responses via the bus.

10. **Polling semantics match spec.** The issue acknowledges "polling adds latency" as a POC tradeoff. `MessageBusInputProvider` uses `asyncio.sleep(poll_interval)` polling (default 0.1s), which is the expected mechanism change from blocking FIFO to polled bus.

## Verdict

**PARTIAL**

The core messaging bus abstraction, SQLite implementation, adapter protocol, and project session conversation type are fully implemented and correctly wired. The FIFO-to-bus migration for the orchestrator's input path is complete.

Unmet spec requirements:
- **Textual chat panel** -- the issue specifies "Textual chat panel alongside the existing dashboard" but no chat panel was created; only the transport layer behind the existing modal input widget was changed.
- **Subteam conversations** -- defined but never instantiated or used by any dispatch/proxy code.
- **Office manager conversations** -- defined but never instantiated (may be intentionally deferred pending the office manager feature).
- **Design doc** -- `docs/proposals/messaging.md` referenced by the issue was never created.
