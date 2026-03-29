[UI Redesign](../proposal.md) >

# Bridge API Specification

The bridge is an aiohttp server that exposes TeaParty's existing data through REST endpoints and a WebSocket. It imports existing modules directly — `SqliteMessageBus`, `StateReader`, `config_reader`, `heartbeat`, `cfa_state`.

`StateReader` is imported from `projects.POC.orchestrator.state_reader`, not from the TUI package. Session discovery logic and heartbeat liveness classification live in the orchestrator so the bridge has no dependency on the TUI it supersedes (issue #280).

---

## Startup

```python
bridge = TeaPartyBridge(
    teaparty_home='~/.teaparty',
    projects_dir='/path/to/projects',
    static_dir='docs/proposals/ui-redesign/mockup',
)
bridge.run(port=8081)
```

1. Initialize `StateReader(poc_root, projects_dir)` for filesystem polling
2. Open `SqliteMessageBus` per active session (`{infra_dir}/messages.db`)
3. Load config via `load_management_team()` + `discover_projects()`
4. Start 1-second polling loop (same cadence as the TUI)
5. Serve static files at `/` and API routes at `/api/`

---

## REST Endpoints

### State

| Method | Path | Returns | Source |
|--------|------|---------|--------|
| GET | `/api/state` | All projects with sessions, dispatches, liveness | `StateReader.reload()` |
| GET | `/api/state/{project}` | Single project's sessions | `StateReader.find_project(slug)` |
| GET | `/api/cfa/{session_id}` | CfA state (phase, state, actor, history, backtrack count) | `load_state(infra_dir/.cfa-state.json)` |
| GET | `/api/heartbeat/{session_id}` | Liveness: alive, stale, or dead | `_heartbeat_three_state()` from `orchestrator.state_reader` (30s/300s thresholds) |

`StateReader` scans `{project}/.sessions/*/` directories. Each session has `.cfa-state.json` (state), `.heartbeat` (liveness), and `messages.db` (conversations). The bridge opens a `SqliteMessageBus` connection per active session. Connections close when sessions complete.

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
| GET | `/api/conversations?type=TYPE` | Active conversations, filterable | `bus.active_conversations(type)` |
| GET | `/api/conversations/{id}?since=TS` | Messages since timestamp | `bus.receive(id, since)` |
| POST | `/api/conversations/{id}` | Send human message (interjection or response) | `bus.send(id, 'human', content)` |

Conversation types: `office_manager`, `project_session`, `subteam`, `job`, `task`, `proxy_review`, `liaison`.

Conversation ID format:
- `om:{human}` — office manager (persistent)
- `job:{project}:{job_id}` — job conversation
- `task:{project}:{job_id}:{task_id}` — task conversation (three-part qualifier)
- `proxy:{decider}` — proxy review
- `session:{timestamp}` — project session
- `team:{slug}` — subteam
- `liaison:{requester}:{target}` — liaison

### Artifacts

| Method | Path | Returns | Source |
|--------|------|---------|--------|
| GET | `/api/artifacts/{project}` | Entry file parsed into sections | Parse `project.md` headings |
| GET | `/api/file?path=PATH` | Raw file content from worktree | Read file, return as text |

For org-level, project=`org` returns `organization.md`.

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
A message with `ack_status = 'pending'` exists in this conversation. The chat page should highlight it. Detected by querying `WHERE ack_status = 'pending'` — no content inspection.

```json
{"type": "message", "conversation_id": "...", "sender": "...", "content": "...", "timestamp": 0.0}
```
New message in any active conversation. The bridge polls each conversation's `bus.receive(id, since=last_ts)`.

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

---

## Human Input Flow

The bridge does NOT implement `InputProvider`. It writes to the same SQLite message bus that `MessageBusInputProvider` already polls.

```
1. Orchestrator's MessageBusInputProvider posts question
   → inserts message with ack_status = 'pending'

2. Bridge poll queries WHERE ack_status = 'pending'
   → pushes {"type": "input_requested", ...} via WebSocket

3. Chat page shows the question (it's a message in the conversation)

4. Human types response, hits Enter

5. Chat page POSTs to /api/conversations/{id}
   → bridge inserts human reply with reply_to = <question message id>
   → bridge updates question message ack_status = 'acknowledged' (same transaction)

6. Orchestrator's MessageBusInputProvider poll picks up the response
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
projects/POC/bridge/
├── server.py          # aiohttp app, route definitions, static file serving
├── poller.py          # StateReader polling loop, state diffing, WebSocket event push
└── message_relay.py   # Per-session SqliteMessageBus polling, message event push
```

### What the bridge does NOT do
- Run Claude agents (that's the orchestrator)
- Implement InputProvider (it writes to the message bus instead)
- Connect to MCP sockets (escalations flow through the orchestrator)
- Manage worktrees (that's the orchestrator)
- Parse or execute CfA transitions (it reads state, doesn't drive it)

The bridge is read-heavy, write-light. It reads state files, config, heartbeats, and messages. It writes only human messages to the message bus and withdrawal requests to the intervention socket.
