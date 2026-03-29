# UI Redesign: HTML Dashboard

Supersedes: [dashboard-ui](../dashboard-ui/proposal.md)

Replace the 65k-line Textual TUI with five HTML/JS pages served by a thin Python bridge over SQLite. No servers wrapping Claude. No Anthropic TOS concerns. Claude can build and verify these with browser dev tools.

Interactive mockup: [mockup/index.html](mockup/index.html)

---

## Pages

| Page | Purpose | Entry |
|------|---------|-------|
| [Home](#home) | Project dashboard, escalation triage | `index.html` |
| [Config](#config-manager) | Org catalog + project assembly | `config.html` |
| [Artifacts](#artifacts) | Browsable docs, gate review | `artifacts.html` |
| [Stats](#stats) | Charts and metrics | `stats.html` |
| [Chat](#chat) | Async messaging, interjections | `chat.html` |

---

## Home

The landing page. One card per project showing jobs with [workflow progress bars](#workflow-progress-bars), escalation indicators, and action buttons.

**Org row:** Global Config, Statistics, Org Knowledge, Office Manager, escalation count badge.

**Project cards:**
- Status badge, description, stats (active jobs, escalations, workgroups)
- Active jobs with workflow bars — click any job to open its [Job Chat](#job-chat)
- Action buttons: Config, Artifacts, Manager
- "+ New Project" opens Office Manager chat

This page eliminated three separate dashboard levels (management, project, job status).

---

## Config Manager

Two levels: global catalog and project assembly.

### Global Config

The org catalog. Defines workgroups, agents, and skills that projects can pull in.

- **Workgroup Catalog, Agent Catalog, Skill Catalog** — org-level definitions
- **Participants** — Office Manager + humans (D-A-I roles)
- **Artifacts** — links to [organization.md](#org-artifacts)
- **Hooks, Scheduled Tasks** — org-level

### Project Config

Projects assemble from the catalog. Each item is tagged by source:

| Tag | Meaning |
|-----|---------|
| `shared` | From org catalog, possibly with overrides |
| `local` | Defined only in this project |
| `generated` | Project lead, created from template |

Override indicators show where a project diverges from the org definition (e.g., "norms overridden" on a shared workgroup).

"+ New" creates locally. "+ Catalog" pulls from the org catalog. Breadcrumb links back to Global Config.

See [Assembly Model](#assembly-model) for details.

---

## Artifacts

Browsable project documentation. Each project has a `project.md` entry file; the org has `organization.md`.

**Layout:** Sidebar navigator (sections from entry file) + main pane (rendered markdown or index).

**Content:** Architecture, design docs, implementation, active job artifacts (INTENT/PLAN/WORK_ASSERT from running jobs), learnings.

**Gate review:** At any approval gate, the [Job Chat](#job-chat) header shows a "Review" button that opens the relevant artifact here. All gate artifacts use progressive disclosure — summary, then links to diffs, files, tests, research. The human never needs to find a worktree path.

See [Gate Review Flow](#gate-review-flow) for details.

### Org Artifacts

`organization.md` — rolled-up organizational memory: institutional learnings, procedural skills, proxy knowledge, strategic decisions. Accessible from the Global Config artifacts card and the Home org row.

---

## Stats

Summary metrics + charts: tasks completed over time, token usage, proxy accuracy trend, escalations by phase. All derived from SQLite queries.

---

## Chat

One browser tab per conversation. Two variants sharing the same page.

### Job Chat

For job-scoped work. Sidebar navigator shows **tasks**:
- Job conversation (with project lead)
- Each task sub-conversation (with assigned agent)
- Red dots on conversations with escalations

**Header:** Participant name, scope, gate "Review" button (at gates, see [Gate Review Flow](#gate-review-flow)), "Withdraw" button (with [confirmation modal](#withdraw-confirmation)).

### Participant Chat

For 1:1 conversations. Sidebar navigator shows **conversation history**:
- All sessions with that participant, sorted by date
- Used for: Office Manager, Manager, Proxy, Humans

### Shared Features

- **Markdown rendering** — bold, lists, links, images, code blocks, blockquotes, tables. Agents produce markdown naturally.
- **Filters** — toggleable: agent, human, thinking, tools, system
- **Multiline input** — shift+enter for newlines, auto-grows up to 10 rows, then scrollbar
- **Interjections** — human can type into any conversation at any time

---

## Design Details

### Participant Model

| Scope | Agents | Proxy | Humans |
|-------|--------|-------|--------|
| Org (home) | Office Manager | -- | -- |
| Project (config/home) | Manager | Proxy (project learning) | Decider, Advisors |
| Job (chat) | Project Lead | Proxy (job instructions) | Decider, Advisors |

Every scope has the same three categories. What changes is the conversation scope.

### Assembly Model

Projects are assembled, not constructed:

1. Pick workgroups from the org catalog
2. Pick agents from the org catalog
3. Project lead generated from template
4. Assign participants (humans with D-A-I roles)
5. Customize — override norms, agent settings, bring in skills

Like git's global/local config. Global defines, project references and overrides. No copying — one source of truth per definition, with per-project deltas.

### Workflow Progress Bars

Phases render as bars (work), circles (gates):
```
━━━━━━━●━━━━━━━●━━━━━━━●━━━━━━
INTENT      PLAN      WORK      DONE
         ^         ^         ^
      INTENT_   PLAN_    WORK_
      ASSERT    ASSERT   ASSERT
```

- **Bars:** green (complete), yellow (in progress), dim (not reached)
- **Circles:** green (passed), red + pulse (at this gate), dim (not reached)

Task escalations during a work phase: bar is yellow, escalation dot is red. Gate escalations: preceding bar is green, gate circle is red.

### Gate Review Flow

At any approval gate (INTENT_ASSERT, PLAN_ASSERT, WORK_ASSERT):

1. Proxy escalates in the [Job Chat](#job-chat)
2. Chat header shows green "Review INTENT/PLAN/WORK" button
3. Button opens [Artifacts](#artifacts) viewer with the gate document
4. Gate document uses progressive disclosure — summary first, then links to deeper content
5. Human reviews, returns to chat, responds to the escalation

The human never needs to find a worktree path.

### Withdraw Confirmation

The "Withdraw" button on job chats opens a modal: "This will cancel the job and all running tasks. Completed work will be preserved in the worktree but not merged. This action cannot be undone." Cancel or Withdraw.

---

## Technical Implementation

### Page Structure

Separate HTML files, each in its own browser tab:

| File | Query Params | Purpose |
|------|-------------|---------|
| `index.html` | — | Home dashboard |
| `config.html` | `?project=ID` (optional) | Global config or project config |
| `artifacts.html` | `?project=ID` (`org` for org-level) | Artifacts viewer |
| `stats.html` | — | Statistics |
| `chat.html` | `?conv=ID` | Job chat (task navigator) |
| `chat.html` | `?conv=ID&task=TASK_ID` | Job chat, deep-link to task |
| `chat.html` | `?conv=office-manager` | Participant chat (session navigator) |

Cross-app navigation uses `window.open()` with query params. The mockup is normative for all navigation flows and control behavior.

### Python Bridge

An async Python server (aiohttp) that bridges the HTML pages to TeaParty's existing infrastructure. No Claude involvement. No Anthropic API calls. Reuses existing modules directly via import.

#### Dependencies

- `aiohttp` — HTTP server + WebSocket
- Existing TeaParty modules imported directly:
  - `orchestrator.messaging.SqliteMessageBus`
  - `orchestrator.config_reader.*`
  - `orchestrator.heartbeat.*`
  - `tui.state_reader.StateReader`
  - `scripts.cfa_state.*`

#### Startup

```python
bridge = TeaPartyBridge(
    teaparty_home='~/.teaparty',
    projects_dir='/path/to/projects',
    static_dir='docs/proposals/ui-redesign/mockup',
)
bridge.run(port=8081)
```

On startup:
1. Initialize `StateReader(poc_root, projects_dir)` for filesystem polling
2. Open `SqliteMessageBus` connections per active session (`{infra_dir}/messages.db`)
3. Load config via `load_management_team()` and `discover_projects()`
4. Start 1-second polling loop (same cadence as the TUI's `set_interval`)
5. Serve static files + API routes

#### REST API

**State & Status**

| Method | Path | Returns | Source |
|--------|------|---------|--------|
| GET | `/api/state` | All projects, sessions, dispatches | `StateReader.reload()` |
| GET | `/api/state/{project}` | Single project sessions | `StateReader.find_project(slug)` |
| GET | `/api/cfa/{session_id}` | CfA state for session | `load_state(infra_dir/.cfa-state.json)` |
| GET | `/api/heartbeat/{session_id}` | Liveness: alive/stale/dead | `read_heartbeat()` |

**Config**

| Method | Path | Returns | Source |
|--------|------|---------|--------|
| GET | `/api/config` | Management team + project list | `load_management_team()` + `discover_projects()` |
| GET | `/api/config/{project}` | Project team + resolved workgroups | `load_project_team()` + `resolve_workgroups()` |
| GET | `/api/workgroups` | Org-level workgroup catalog | Scan `{teaparty_home}/workgroups/*.yaml` |

**Messages**

| Method | Path | Returns | Source |
|--------|------|---------|--------|
| GET | `/api/conversations` | Conversations, filterable by type | `bus.active_conversations(type)` |
| GET | `/api/conversations/{id}?since=TS` | Messages since timestamp | `bus.receive(id, since)` |
| POST | `/api/conversations/{id}` | Send human message | `bus.send(id, 'human', content)` |

**Artifacts**

| Method | Path | Returns | Source |
|--------|------|---------|--------|
| GET | `/api/artifacts/{project}` | Entry file sections | Parse `project.md` headings |
| GET | `/api/file?path=...` | Raw file content | Read from worktree |

**Actions**

| Method | Path | Effect | Source |
|--------|------|--------|--------|
| POST | `/api/withdraw/{session_id}` | Withdraw a job | Write to `INTERVENTION_SOCKET` |

#### WebSocket

Single endpoint: `ws://localhost:8081/ws`

The bridge polls `StateReader` every second. On change, it pushes to connected clients:

```json
{"type": "state_changed", "session_id": "...", "phase": "...", "state": "..."}
{"type": "input_requested", "session_id": "...", "conversation_id": "...", "question": "..."}
{"type": "message", "conversation_id": "...", "sender": "...", "content": "..."}
{"type": "heartbeat", "session_id": "...", "status": "alive|stale|dead"}
{"type": "session_completed", "session_id": "...", "terminal_state": "..."}
```

Polling diffs previous state against current. Only changes produce events. For messages, the bridge polls each active conversation's `bus.receive(id, since=last_ts)` and pushes new messages immediately.

#### Human Input Flow

The bridge does not implement `InputProvider`. It writes to the same SQLite message bus that the orchestrator's `MessageBusInputProvider` already polls.

1. Orchestrator's `MessageBusInputProvider` posts question as `orchestrator` sender
2. Bridge poll detects new message, pushes `input_requested` via WebSocket
3. Chat page shows the question (it's a message in the conversation)
4. Human types response in chat textarea
5. Chat page POSTs to `/api/conversations/{id}` with `sender: human`
6. Bridge calls `bus.send(id, 'human', content)`
7. Orchestrator's `MessageBusInputProvider` poll picks up the response
8. Orchestrator continues

No new protocol. The bridge reads and writes the same database the orchestrator uses.

#### Escalation Routing

Agent escalations (via `AskQuestion` MCP tool) flow through the existing path: escalation listener → proxy → message bus. The bridge reads the result from the message bus. No socket integration needed for reading — escalations appear as messages.

The bridge only needs socket integration for **interventions** (withdraw) which write to `INTERVENTION_SOCKET`.

#### Session Discovery

Same as the TUI:

1. `StateReader.reload()` scans `{project}/.sessions/*/` directories
2. Each session has `.cfa-state.json`, `.heartbeat`, `messages.db`
3. Bridge opens `SqliteMessageBus` per active session's `messages.db`
4. When sessions complete, bridge closes the connection

#### File Structure

```
projects/POC/bridge/
├── __init__.py
├── server.py          # aiohttp app, routes, WebSocket handler
├── poller.py          # StateReader polling loop, diff detection, event push
└── message_relay.py   # Per-session message bus polling, WebSocket push
```

Imports from existing modules — no reimplementation.

---

## Relationship to Other Proposals

- [dashboard-ui](../dashboard-ui/proposal.md) — Superseded entirely
- [chat-experience](../chat-experience/proposal.md) — Chat page implements its interaction model
- [messaging](../messaging/proposal.md) — All pages read/write its SQLite message bus; bridge uses `SqliteMessageBus` directly
- [office-manager](../office-manager/proposal.md) — Config and home delegate to it
