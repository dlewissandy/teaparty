# UI Redesign: HTML Dashboard

Supersedes: [dashboard-ui](../dashboard-ui/proposal.md)

Replace the ~7,000-line Textual TUI with HTML/JS pages served by a Python bridge over SQLite. No servers wrapping Claude. No Anthropic TOS concerns. Claude can build and verify these with browser dev tools.

Interactive mockup (normative for navigation and controls): [mockup/index.html](mockup/index.html)

---

## Why

The TUI is the single largest maintenance burden in the project. Three problems:

1. **Claude can't modify it.** Textual's TCSS is close enough to CSS that Claude confuses them, and it can't run the TUI to verify changes. Every iteration burns tokens with no convergence.

2. **It does too many things.** Configuration, monitoring, messaging, statistics, and five levels of hierarchical navigation are tangled into one ~7,000-line app. Changes in one area break others.

3. **It doesn't advance the research.** The TUI is infrastructure tax. Every hour spent on it is an hour not spent on the CfA protocol, proxy learning, or hierarchical teams.

HTML solves all three. Claude knows HTML/CSS/JS cold. Browser dev tools work. Separate pages enforce separation of concerns. And because the orchestrator already has a SQLite message bus, the bridge wraps existing infrastructure — it adds no business logic, though it is a new server component with its own implementation scope (see Bridge Server below).

---

## Pages

The mockup defines five pages. Each opens in its own browser tab.

| Page | File | Purpose | Reference |
|------|------|---------|-----------|
| Home | `index.html` | Project cards with job workflow bars, escalation triage | [references/home.md](references/home.md) |
| Config | `config.html?project=ID` | Org catalog and project assembly | [references/config.md](references/config.md) |
| Artifacts | `artifacts.html?project=ID` | Browsable docs, gate review | [references/artifacts.md](references/artifacts.md) |
| Stats | `stats.html` | Charts and metrics | [references/stats.md](references/stats.md) |
| Chat | `chat.html?conv=ID` | Job chat + participant chat | [references/chat.md](references/chat.md) |

The mockup is normative for navigation flows and visual design. The reference docs describe user stories and interaction details.

---

## Key Design Decisions

### The home page IS the status dashboard
The home page shows every project, every active job with workflow progress bars, and every pending escalation. Clicking a job opens its chat. This eliminated three separate dashboard levels (management, project, job status) because the home card contains everything the human needs to decide where to go.

### Config uses a catalog/assembly model
Global config defines an org catalog of workgroups, agents, and skills. Projects assemble from the catalog, tagged `shared`/`local`/`generated`, with per-project overrides. Like git's global/local config — one source of truth per definition. This avoids deep-copy drift and makes project setup a conversation with the office manager ("use Editorial, Writing, and Research workgroups") rather than manual YAML editing.

### Artifacts viewer for gate reviews
At approval gates, the human clicks "Review" in the chat header and the artifact opens in a markdown viewer. All gate artifacts (INTENT, PLAN, WORK_ASSERT) use progressive disclosure — summary first, then links to deeper content (diffs, files, tests). The human never needs to find a worktree path.

### Two chat variants, same page
Job chats navigate by tasks (sidebar lists task sub-conversations). Participant chats navigate by history (sidebar lists past sessions with that person). Same rendering engine, different sidebar content. Chat renders markdown natively because agents produce it.

### Proxy is directly queryable
The proxy appears as a clickable participant at project and job scope. The human can query its learning, challenge assumptions, or give job-specific instructions before gates happen — not just react to escalations.

---

## Bridge Server

The bridge is a new async Python server (aiohttp) that wraps existing TeaParty infrastructure. It adds no business logic — CfA transitions, orchestration, and agent execution remain in the orchestrator — but it is a meaningful new server component: an aiohttp app with static file serving, seven REST endpoint groups, a WebSocket with five event types, a 1-second polling loop with state diffing, per-session message bus lifecycle management, conversation routing across multiple databases, and a workgroup scanner (no existing backing function in `config_reader`). A 300–500 line implementation is the realistic floor.

Three structural gaps bear on implementation planning: StateReader coupling (#280), the withdrawal path (#278), and the missing workgroup scanner. These are tracked separately but any sprint sizing must account for them.

It imports existing TeaParty modules directly — `SqliteMessageBus`, `StateReader`, `config_reader`, `heartbeat`, `cfa_state` — rather than reimplementing them.

**Why aiohttp:** Async needed for WebSocket push. Lightweight. No framework opinions.

**Why not a new protocol:** The orchestrator's `MessageBusInputProvider` already polls the message bus for human responses. The bridge writes to the same database. Human types in chat → bridge writes to SQLite → orchestrator picks it up. No new IPC.

**Why polling (not event subscription):** The TUI already polls `StateReader` at 1-second intervals. The bridge does the same. This avoids coupling the bridge to the orchestrator's in-process `EventBus`, which would require running in the same process. The bridge is a separate process by design.

See [references/bridge-api.md](references/bridge-api.md) for the complete REST and WebSocket API specification.

---

## Relationship to Other Proposals

- [dashboard-ui](../dashboard-ui/proposal.md) — Superseded entirely
- [chat-experience](../chat-experience/proposal.md) — Chat page implements its interaction model
- [messaging](../messaging/proposal.md) — Bridge reads/writes its SQLite message bus via `SqliteMessageBus`
- [office-manager](../office-manager/proposal.md) — Config and home delegate to it
