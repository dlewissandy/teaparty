[UI Redesign](../proposal.md) >

# Bridge API Specification

The bridge is a new aiohttp server that wraps TeaParty's existing infrastructure. It adds no business logic — that stays in the orchestrator — but it is a new server component with meaningful implementation scope.

**What the bridge implements as new code:**
- aiohttp app with static file serving and route definitions
- 1-second polling loop with state diffing to detect CfA transitions, input requests, heartbeat changes, and session completions
- Per-session `SqliteMessageBus` connection lifecycle (open on first poll of a non-terminal session, close on terminal state detection)
- WebSocket endpoint with five push-event types and broadcast-all dispatch
- Conversation routing across multiple databases (OM database vs per-session databases)
- Workgroup scanner (`GET /api/workgroups`) — no existing backing function in `config_reader`

**What the bridge delegates to existing infrastructure:**
- `SqliteMessageBus` — message storage and retrieval
- `StateReader` — filesystem polling and session discovery (#280)
- `config_reader` — project and management team configuration
- `heartbeat` / `cfa_state` — liveness classification and CfA state loading
- `MessageBusInputProvider` — orchestrator polls the same database the bridge writes to

Two structural gaps require separate implementation work: the withdrawal path needs a stable socket contract (#278), and the workgroup scanner has no existing backing function. StateReader extraction (#280) is complete. Implementers planning from this spec must account for the two remaining gaps.

`StateReader` is imported from `orchestrator.state_reader`. Session discovery logic and heartbeat liveness classification live in the orchestrator so the bridge has no dependency on the TUI it supersedes.

---

## Startup

```python
bridge = TeaPartyBridge(
    teaparty_home='~/.teaparty',
    static_dir='bridge/static',
)
bridge.run(port=8081)
```

1. Construct a single `StateReader(repo_root, teaparty_home=teaparty_home)` instance stored on the bridge. Projects are discovered from the registry in `teaparty_home/teaparty.yaml`. This single instance is shared by the polling loop and all REST state handlers (`/api/state`, `/api/state/{project}`) — not recreated per request.
2. Open a `SqliteMessageBus` for the office manager at `{teaparty_home}/management/agents/office-manager/om-messages.db` (persistent, not session-scoped — see [Message routing](#message-routing) below)
3. Load config via `load_management_team()` + `discover_projects()`
4. Start 1-second polling loop (same cadence as the TUI)
5. Serve static files at `/` and API routes at `/api/`

**Per-session connection lifecycle (managed by the polling loop):**

- **Open:** On the first poll that encounters a session not in a terminal state, the poller opens a `SqliteMessageBus` connection at `{infra_dir}/messages.db` via a `bus_factory` callable. One connection per session; subsequent polls reuse it.
- **Close:** When the poller detects a session has transitioned to a terminal CfA state (`COMPLETED_WORK` or `WITHDRAWN`), it calls `bus.close()` and removes the connection from its registry. The close is triggered by the poller's state diff, not by the session process itself.
- **Terminal sessions on first poll:** A session already in a terminal state when the bridge starts is never opened — the poller skips `bus_factory` for sessions that are terminal on first encounter.

---

## REST Endpoints

### State

| Method | Path | Returns | Source |
|--------|------|---------|--------|
| GET | `/api/state` | All projects with sessions, dispatches, liveness | `StateReader.reload()` |
| GET | `/api/state/{project}` | Single project's sessions | `StateReader.find_project(slug)` |
| GET | `/api/cfa/{session_id}` | CfA state (phase, state, actor, history, backtrack count) | `load_state(infra_dir/.cfa-state.json)` |
| GET | `/api/heartbeat/{session_id}` | Liveness: alive, stale, or dead | `_heartbeat_three_state()` from `orchestrator.heartbeat` (30s/300s thresholds) |

`StateReader` scans `{project}/.sessions/*/` directories. Each session has `.cfa-state.json` (state), `.heartbeat` (liveness), and `messages.db` (conversations). Per-session `SqliteMessageBus` connections are managed by the polling loop — see **Per-session connection lifecycle** in [Startup](#startup).

### Config

| Method | Path | Returns | Source |
|--------|------|---------|--------|
| GET | `/api/config` | Management team + project list | `load_management_team()` + `discover_projects()` |
| GET | `/api/config/{project}` | Project team with resolved workgroups | `load_project_team()` + `resolve_workgroups()` |
| GET | `/api/workgroups` | Org-level workgroup catalog | Scan `{teaparty_home}/workgroups/*.yaml` |

Config resolution follows existing precedence: org < workgroup < project. Norms replace by category. Budgets merge by key.

### Messages

| Method | Path | Returns | Source |
|--------|------|---------|--------|
| GET | `/api/conversations?type=TYPE` | Active conversations, filterable | `bus.active_conversations(ConversationType[type.upper()])` |
| GET | `/api/conversations/{id}?since=TS` | Messages since timestamp | `bus.receive(id, since_timestamp=float(TS))` |
| POST | `/api/conversations/{id}` | Send human message (interjection or response) | `bus.send(id, 'human', content)` |

Conversation types: `office_manager`, `project_session`, `subteam`, `job`, `task`, `proxy_review`, `liaison`.

`active_conversations` takes a `ConversationType` enum member, not a string. The `?type=` query parameter is a string; the bridge must convert it before calling the bus: `ConversationType[type.upper()]`. A raw string will not match any enum member and the call returns an empty list with no error — a silent failure that makes every conversation list appear empty. `receive` uses `since_timestamp` as the keyword argument name (not `since`); passing it by keyword with the wrong name raises `TypeError`.

#### Message routing

The bridge maintains three distinct database connections:

| Type | Database path | Scope |
|------|--------------|-------|
| `office_manager` | `{teaparty_home}/management/agents/office-manager/om-messages.db` | Persistent — survives sessions, one per installation |
| `proxy_review` | `{teaparty_home}/management/agents/proxy-review/proxy-messages.db` | Persistent — survives sessions, one per installation |
| All other types | `{infra_dir}/messages.db` | Session-scoped — one per active session |

`?type=office_manager` queries the persistent OM database. `?type=proxy_review` queries the persistent proxy database. All other `?type=` values aggregate across active session databases. Querying a persistent-type against a session bus always returns an empty list.

Conversation IDs encode their routing target via prefix:
- `om:{human}` — office manager (routes to OM database)
- `proxy:{decider}` — proxy review (routes to proxy database)
- `session:{timestamp}` — project session
- `job:{project}:{job_id}` — job conversation
- `task:{project}:{job_id}:{task_id}` — task conversation (three-part qualifier)
- `team:{slug}` — subteam
- `liaison:{requester}:{target}` — liaison

`GET /api/conversations/{id}` and `POST /api/conversations/{id}` use the prefix to route to the correct database without a type lookup. The canonical database paths are provided by `om_bus_path(teaparty_home)` in `orchestrator.office_manager` and `proxy_bus_path(teaparty_home)` in `orchestrator.proxy_review`.

### Artifacts

| Method | Path | Returns | Source |
|--------|------|---------|--------|
| GET | `/api/artifacts/{project}` | Entry file parsed into sections | Parse `project.md` headings |
| GET | `/api/file?path=PATH` | Raw file content from worktree | Read file, return as text |

For org-level, project=`org` returns `organization.md`.

### Filesystem Navigation

| Method | Path | Returns | Source |
|--------|------|---------|--------|
| GET | `/api/fs/list?path=PATH` | `{entries: [{name, path, is_dir}]}` — directory listing | `_list_directory(path)` |

`PATH` is expanded via `os.path.expanduser` so `~` works. Returns 400 if `path` is missing, 404 if the path does not exist or is not a directory. Used by the OM agent to navigate the filesystem during project onboarding.

### Project Management

| Method | Path | Body | Returns | Source |
|--------|------|------|---------|--------|
| POST | `/api/projects/add` | `{name, path, description?, lead?, decider?, agents?, humans?, workgroups?, skills?}` | `{ok: true, management_team}` | `add_project()` |
| POST | `/api/projects/create` | `{name, path, description?, lead?, decider?, agents?, humans?, workgroups?, skills?}` | `{ok: true, management_team}` | `create_project()` |

`/api/projects/add` registers an existing directory and creates `.teaparty.local/project.yaml` with the provided frontmatter. No `.git/` or `.claude/` prerequisites. Returns 409 if the name conflicts or the path does not exist.

`/api/projects/create` scaffolds a new project directory (`mkdir`, `git init`, `.claude/`), writes `.teaparty.local/project.yaml`, and adds to `teams:`. Returns 409 if the directory already exists or the name conflicts.

### Actions

| Method | Path | Effect | Source |
|--------|------|--------|--------|
| POST | `/api/withdraw/{session_id}` | Withdraw a job | Write `InterventionRequest` to `~/.teaparty/sockets/{session_id}.sock` |

The bridge locates a session's intervention channel via a stable, predictable Unix socket path:
`~/.teaparty/sockets/{session_id}.sock`. The bridge constructs this path from the session ID alone —
no file read or registry lookup required. Socket file presence is the readiness signal: if the file
does not appear within N seconds of session start, the bridge marks intervention as unavailable and
surfaces that to the UI. The shared serialization type is `InterventionRequest` (defined in
`intervention_listener.py`), imported by both the bridge and the MCP server.

The bridge is read-heavy, write-light. It reads state files, config, heartbeats, and messages. It
writes only human messages to the message bus and withdrawal requests to the intervention socket.

> **Decision record:** See [#278](https://github.com/dlewissandy/teaparty/issues/278) — Option B
> chosen (stable socket path) over Option A (sentinel file). Uniform failure mode, no staleness
> ambiguity, consistent with infra dir conventions. Socket capped to `~/.teaparty/sockets/` rather
> than `{infra_dir}` to keep path length provably bounded.

---

## WebSocket

Single endpoint: `ws://localhost:8081/ws`

### Push Events

The bridge polls `StateReader` every second and diffs against previous state. Changes produce events:

```json
{"type": "state_changed", "session_id": "...", "phase": "...", "state": "..."}
```
CfA state transition detected.

```json
{"type": "input_requested", "session_id": "...", "conversation_id": "...", "question": "..."}
```
Orchestrator is waiting for human input. The chat page should highlight this conversation.

Source: `conversations.awaiting_input = 1` in the session's `messages.db`. `MessageBusInputProvider` sets this flag when posting a question and clears it when a human response is received. The bridge detects the event by polling `bus.conversations_awaiting_input()` — no message content inspection required (issue #288).

```json
{"type": "message", "id": "...", "conversation_id": "...", "sender": "...", "content": "...", "timestamp": 0.0}
```
New message in any active conversation. The bridge polls each conversation's `bus.receive(id, since_timestamp=last_ts)`. The `id` field is the message's database ID, used by the chat page to filter echo events (see **Duplicate-message suppression** below).

```json
{"type": "heartbeat", "session_id": "...", "status": "alive|stale|dead"}
```
Heartbeat status changed (transitions only, not every poll).

```json
{"type": "session_completed", "session_id": "...", "terminal_state": "COMPLETED_WORK|WITHDRAWN"}
```
Session reached a terminal state.

### Client Subscription

Clients receive all events. Filtering is client-side (e.g., a chat page only cares about messages for its conversation). This keeps the server simple — no subscription management.

**Scale assumption:** This broadcast-all design is appropriate for a single user with a handful of concurrent sessions. It does not scale to multi-user deployments where clients should not see each other's messages. If TeaParty ever becomes multi-user, per-client subscription management or per-session WebSocket channels would be required.

**Duplicate-message suppression (correlation ID scheme):** The chat page uses optimistic UI — it renders a message immediately when the human hits Enter, before the round-trip to the bridge. The bridge then polls the database, detects the new message, and broadcasts a `message` event to all clients including the sender. Without suppression, the sending tab would render the message twice.

The fix is a client-side correlation ID set:
1. The chat page POSTs the message to `POST /api/conversations/{id}` and receives `{"id": "<msg_id>"}` in the response.
2. It stores `msg_id` in a local `sentIds` set.
3. When a `message` WebSocket event arrives, if `event.id` is in `sentIds`, the event is an echo — skip it and remove the ID from the set.

The server-side contract: every `message` event must include the `id` field (the message's database ID). The chat page relies on this to identify echoes.

**Sticky escalation badges:** The home page tracks pending escalations in `escalationConvMap` (session_id → conversation_id). This map is the sticky source of truth: entries are added by `input_requested` WebSocket events and by REST data on page load, but are only removed when the human explicitly responds (sends a human message to the escalation conversation). `fetchAll()` merges new REST entries but never clears existing map entries — this prevents badge loss during page re-renders triggered by `session_completed` or `state_changed` events.

---

## Human Input Flow

The bridge does NOT implement `InputProvider`. It writes to the same SQLite message bus that `MessageBusInputProvider` already polls.

```
1. Orchestrator's MessageBusInputProvider posts question
   → bus.send(conv_id, 'orchestrator', question)
   → bus.set_awaiting_input(conv_id, True)

2. Bridge poll calls bus.conversations_awaiting_input()
   → detects conv_id has awaiting_input=1
   → pushes {"type": "input_requested", ...} via WebSocket

3. Chat page shows the question (it's a message in the conversation)

4. Human types response, hits Enter

5. Chat page POSTs to /api/conversations/{id}
   → bridge calls bus.send(conv_id, 'human', response)

6. Orchestrator's MessageBusInputProvider poll picks up the response
   → clears awaiting_input flag via bus.set_awaiting_input(conv_id, False)
   → orchestrator continues
```

No new protocol. The bridge and the orchestrator share a database.

---

## Escalation Routing

Agent escalations (via `AskQuestion` MCP tool) flow through the existing path:

```
Agent calls AskQuestion → MCP server → ASK_QUESTION_SOCKET
→ EscalationListener → proxy agent → confidence check
→ if confident: return proxy answer (no human involvement)
→ if not confident: post to message bus → human answers via bridge
```

The bridge only sees the message bus side. It never connects to `ASK_QUESTION_SOCKET` or `ASK_TEAM_SOCKET`. Those are orchestrator-internal.

---

## Implementation Notes

### Dependencies
- `aiohttp` (only new dependency)
- All other imports from existing TeaParty modules

### File Structure
```
bridge/
├── server.py          # aiohttp app, route definitions, static file serving
├── poller.py          # StateReader polling loop, state diffing, WebSocket event push
└── message_relay.py   # Per-session SqliteMessageBus polling, message event push
```

### I/O model and scale assumption

`SqliteMessageBus` wraps a synchronous `sqlite3.Connection`. Every read in the polling loop — `receive()`, `conversations_awaiting_input()`, `conversations()` — is a blocking I/O call. Because aiohttp runs a single-threaded event loop, each blocking call stalls the loop for its duration. All WebSocket clients are unresponsive until the call returns.

At current research scale this is acceptable: local disk, WAL mode, a handful of concurrent sessions, and each poll completes in under a millisecond. The 1-second polling cadence means the event loop is blocked for a tiny fraction of each cycle.

**Scale assumption:** This design is bounded to local-disk SQLite, WAL mode, single-user deployments with fewer than ~10 concurrent sessions. If any of these change — remote filesystem, many concurrent sessions, or observed WebSocket latency under load — the correct fix is `loop.run_in_executor()` to offload the blocking calls to a thread pool, or a migration to `aiosqlite`. The bridge makes no attempt to hide this constraint: it is a deliberate trade-off for implementation simplicity at research scale.

### What the bridge does NOT do
- Implement InputProvider (it writes to the message bus instead)
- Connect to MCP sockets (escalations flow through the orchestrator)
- Manage worktrees (that's the orchestrator)
- Parse or execute CfA transitions (it reads state, doesn't drive it)

The bridge is primarily read-heavy, write-light. It reads state files, config, heartbeats, and messages. It writes human messages to the message bus and withdrawal requests to the intervention socket.

**Exception: OM agent invocation.** The bridge invokes the office manager agent (`claude -p --agent office-manager`) directly when a human posts to an `om:` conversation thread (issue #322). This is the only agent execution the bridge performs; all CfA-phase orchestration and worktree dispatch remain in the orchestrator. The OM invocation fires as a fire-and-forget `asyncio.create_task` — the response arrives on the OM bus and is broadcast to WebSocket clients by `MessageRelay`.
