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

### Python Bridge

A small Python process (~100-200 lines):
1. Serves HTML/CSS/JS as static files
2. REST endpoints for reading SQLite (message bus, state)
3. WebSocket for real-time push (escalations, state changes, messages)
4. REST endpoints for writing to message bus (interjections, responses)

No Claude involvement. No Anthropic API calls. Just a database bridge.

### Data Sources

| Data | Source | Access |
|------|--------|--------|
| Messages | SQLite message bus | REST + WebSocket |
| CfA state | `.cfa-state.json` files | REST (file read) |
| Config | `teaparty.yaml`, `project.yaml`, workgroup YAML | REST (file read) |
| Heartbeats | `.heartbeat` files | REST (file stat) |
| Stats | Derived from message bus + state | REST (SQL aggregate) |
| Escalations | Message bus (filtered) | REST + WebSocket |
| Artifacts | Markdown files on disk | REST (file read + render) |

### Page Structure

Separate HTML files, each in its own browser tab:
- `index.html` — Home dashboard
- `config.html?project=ID` — Config (global or project level)
- `artifacts.html?project=ID` — Artifacts viewer
- `stats.html` — Statistics
- `chat.html?conv=ID&task=TASK_ID` — Chat

Cross-app navigation uses `window.open()` with query params. Browser tab management handles the rest.

---

## Relationship to Other Proposals

- [dashboard-ui](../dashboard-ui/proposal.md) — Superseded entirely
- [chat-experience](../chat-experience/proposal.md) — Chat page implements its interaction model
- [messaging](../messaging/proposal.md) — All pages read/write its SQLite message bus
- [office-manager](../office-manager/proposal.md) — Config and home delegate to it
