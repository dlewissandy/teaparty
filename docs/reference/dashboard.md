# Dashboard Architecture

The TeaParty dashboard is a single-page-style browser UI served by an aiohttp
bridge server on localhost:8081. All screens are static HTML files that share a
common stylesheet and communicate with the backend over REST endpoints and a
single WebSocket connection.

## Screen Hierarchy

```
index.html          Main dashboard — session list, system health, nav to projects
  config.html       Configuration — management / project / workgroup / agent
  chat.html         Chat window — conversation viewer for a specific session
  artifacts.html    Artifact browser — pinned files and project artifacts
  stats.html        Statistics — cost, token, and timing breakdowns
```

Every screen except `chat.html` includes the chat blade (see below), so
lightweight conversation is available without leaving the current context.

## Static Files

All UI assets live in `teaparty/bridge/static/`:

| File             | Purpose                                      |
|------------------|----------------------------------------------|
| `index.html`     | Main dashboard, session list, navigation     |
| `config.html`    | Four-level config editor with blade layout   |
| `chat.html`      | Full-screen conversation viewer              |
| `artifacts.html` | Artifact browser and pin management          |
| `stats.html`     | Cost and performance statistics              |
| `styles.css`     | Shared stylesheet (dark theme, monospace)    |

`styles.css` defines a dark-mode palette under `:root` using CSS custom
properties (`--bg`, `--surface`, `--green`, `--red`, etc.) and sets a monospace
font stack (`SF Mono`, `Fira Code`, `Cascadia Code`). All screens inherit this
baseline.

## Chat Blade

The blade is a slide-out side panel embedded in pages that use the
`blade-layout` container (`config.html`, `index.html`, `artifacts.html`). Its
key characteristics:

- **Width**: 33vw when open, collapsed to a thin clickable tab when closed.
- **Structure**: A `.blade-tab` toggle, a `.blade-body` containing a header with
  close button, and an `<iframe>` that loads `chat.html` with appropriate query
  parameters.
- **Per-entity conversations**: The blade sets a `convId` derived from the
  current context (e.g. `om:<management-team>` on the index page,
  `config-lead:<project>` on config screens). Conversations are persisted via
  `localStorage` keyed by this ID.
- **Context routing**: On the index page the blade connects to the Office
  Manager. On config and artifact screens it connects to the appropriate config
  lead for the entity being viewed.

State variables (`omConvId`, `bladeConvId`, `bladeContext`, `_bladeOpen`) track
which conversation is loaded and whether the panel is visible.

## Config Screens

`config.html` renders four hierarchical levels, selected via URL parameters and
breadcrumb navigation:

1. **Management** — top-level team roster and settings.
2. **Project** — per-project configuration (agents, workgroups, hooks, skills).
3. **Workgroup** — workgroup roster and artifact pins within a project.
4. **Agent** — individual agent definition (model, tools, maxTurns, role).

Each level displays the full catalog of available items (agents, skills, hooks)
with active/assigned items highlighted. Toggle switches control membership — for
example, toggling an agent into or out of a workgroup roster. An edit mode
(activated by the Edit button in the page header) enables mutation controls that
are hidden during read-only browsing.

A file browser modal supports artifact pinning: selecting files from the project
tree and attaching them to a workgroup or project configuration.

Mutable rendering state (`_agentCtx`, `_currentWgName`, `_currentProjectSlug`,
etc.) allows the UI to re-render panels after toggle operations without
re-fetching the full config from the server.

## Chat Window

`chat.html` is the full-screen conversation viewer, opened either directly or
inside the blade iframe. It accepts URL query parameters:

- `conv` — conversation ID to display.
- `name` — human-readable project/session name for the header.
- `task` / `session` — pre-select a specific subtask or session.
- `seed` — initial message to send on load.
- `context` — entity context string for routing.

### Filter Bar

A filter bar exposes 9 message type toggles:

| Filter     | Content                                      |
|------------|----------------------------------------------|
| `agent`    | Agent-authored messages                      |
| `human`    | Human / proxy messages                       |
| `thinking` | Extended thinking blocks                     |
| `tools`    | Tool use invocations                         |
| `results`  | Tool results                                 |
| `system`   | System-level messages                        |
| `state`    | CfA state transitions                        |
| `cost`     | Token cost annotations                       |
| `log`      | Diagnostic log entries                       |

### Subtask Navigation

The chat window renders a recursive subtask tree for sessions that spawn child
tasks. Clicking a subtask node navigates into that conversation while
maintaining the parent breadcrumb trail.

### Message Rendering

Messages are rendered as styled HTML with full Markdown support (headings,
code blocks, tables, images, blockquotes) via inline CSS rules scoped to
`.msg-text`. A withdraw modal allows cancelling a running job from the chat
view.

## WebSocket Protocol

The bridge server (`teaparty/bridge/server.py`) is an aiohttp application that
serves static files, REST endpoints, and a WebSocket at `/ws`. All connected
clients share a single broadcast channel.

### MessageRelay

`teaparty/bridge/message_relay.py` defines the `MessageRelay` class, which
polls per-session `SqliteMessageBus` instances for new messages and
conversations with `awaiting_input=1`. It emits two event types over the
WebSocket:

- **`message`** — a new message appeared in a conversation.
- **`input_requested`** — a conversation has set `awaiting_input=1`, signaling
  that the frontend should prompt the user.

The relay receives a shared `bus_registry` dict (`{session_id:
SqliteMessageBus}`) managed by the `StatePoller`, which handles bus lifecycle
(opening and closing buses as sessions start and stop).

### StatePoller

The `StatePoller` (in `teaparty/bridge/state/`) monitors session state changes
(heartbeat, active participants, CfA state transitions) and broadcasts
`state_update` events so the dashboard can reflect live status without polling
REST endpoints.

### Event Flow

```
SqliteMessageBus  ──>  MessageRelay  ──>  broadcast()  ──>  WebSocket  ──>  browser
Session state     ──>  StatePoller   ──>  broadcast()  ──>  WebSocket  ──>  browser
```

The bridge server maintains a set of connected WebSocket clients and fans out
every event dict as a JSON frame to all of them.

## Bridge Server

`TeaPartyBridge` (`teaparty/bridge/server.py`) is the entry point. It accepts a
`teaparty_home` path and a `static_dir`, wires up the aiohttp app with REST
routes and the WebSocket handler, and starts the `MessageRelay` and
`StatePoller` as background tasks. Default port is 8081.

Key dependencies injected at construction:

- `StateReader` — reads session and config state from disk.
- `SqliteMessageBus` / `agent_bus_path` — per-agent conversation storage.
- `AgentSession` — live session metadata.
- Config readers (`load_management_team`, `load_project_team`,
  `discover_projects`, `discover_agents`, etc.) — config CRUD backing the
  REST endpoints that `config.html` calls.
