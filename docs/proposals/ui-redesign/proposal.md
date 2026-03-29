# UI Redesign: HTML Dashboard

Supersedes: [dashboard-ui](../dashboard-ui/proposal.md)

---

## Problem

The current TUI is a 65k+ line Textual monolith that does too many things: configuration management, operational monitoring, multi-channel messaging, statistics, and hierarchical navigation. Claude cannot reliably modify it (confuses Textual TCSS with web CSS, fails to run it to verify changes). The result is a high-maintenance UI that detracts from the research goals.

## Solution

Replace the TUI with separate HTML/JS pages served by a thin Python bridge over the existing SQLite message bus. No servers wrapping Claude. No Anthropic TOS concerns. Claude knows HTML/CSS/JS well and can use browser dev tools to verify changes.

### Architecture

```
claude -p agents ──write──> SQLite <──read── Python bridge ──serve──> Browser
                            (message bus,     (no Claude,              (HTML/CSS/JS,
                             state files)      just SQL queries)        browser tabs)
```

The Python bridge (~100-200 lines) serves static files, exposes REST endpoints for SQLite queries, and provides WebSocket for real-time updates. It has no relationship to Claude or Anthropic's stack.

---

## Pages

### 1. Home (`index.html`)

**Purpose:** Project-centric dashboard. The landing page. Answers "what needs my attention?" and "where do I want to go?"

**Layout:**
- **Org row:** Quick-access cards for Global Config, Statistics, Org Knowledge (`organization.md`), Office Manager chat, and an escalation count badge (red, pulsing when escalations exist)
- **Projects section:** One card per project, each showing:
  - Name, status badge, description
  - Stats row: active jobs, escalation count, workgroup count
  - Active jobs with workflow progress bars (bars for work phases, circles for gates -- green if passed, yellow if in progress, red if at a gate with an escalation, dim if not reached)
  - Action buttons: Config, Artifacts, Manager
- **"+ New Project" button** opens an Office Manager chat

**Navigation:** Clicking a job row opens the Job Chat. Clicking an action button opens the corresponding page scoped to that project.

**What it replaces:** The management dashboard, the project dashboard, the job dashboard, the status manager. All operational awareness is on this single page.

### 2. Config Manager (`config.html`)

**Purpose:** Organizational hierarchy management via office manager conversations.

**Two levels:**

**Global Config** (org catalog):
- Projects (click to drill into project config)
- Workgroup Catalog, Agent Catalog, Skill Catalog (org-level definitions available to all projects)
- Participants (Office Manager + humans with D-A-I roles)
- Artifacts card (links to `organization.md` in the Artifacts viewer)
- Hooks, Scheduled Tasks (org-level)
- All "+ New" buttons open Office Manager chat

**Project Config** (assembled from catalog):
- Workgroups: each tagged `shared` (from org catalog) or `local` (project-specific), with override indicators
- Agents: tagged `generated` (project lead from template), `shared` (from catalog), or `local` (bespoke)
- Participants: Manager, Proxy, Humans (D-A-I roles)
- Artifacts card (links to `project.md` in the Artifacts viewer)
- Skills, Hooks, Scheduled Tasks: each tagged `shared` or `local`
- "+ New" creates locally, "+ Catalog" pulls from org catalog
- Breadcrumb links back to Global Config

**Assembly model:** Projects are assembled by picking workgroups and agents from the org catalog, getting a generated project lead from a template, then customizing with local overrides. Like git's global/local config -- global defines, project references and overrides.

**What it replaces:** The management dashboard config cards, the workgroup deep-copy flow, the agent config modal, all "+ New" flows.

### 3. Stats (`stats.html`)

**Purpose:** Interactive statistical visualizations.

**Content:**
- Summary stats: jobs done, tasks done, active, backtracks, withdrawals, escalations, proxy accuracy, tokens, skills learned
- Charts: tasks completed over time, token usage over time, proxy accuracy trend, escalations by phase
- All derived from SQLite queries against state and message bus tables

**What it replaces:** The stats bars on every dashboard level.

### 4. Artifacts (`artifacts.html?project=ID`)

**Purpose:** Browsable documentation and project memory. Each project has a `project.md` entry file; the org has `organization.md`.

**Layout:**
- Sidebar navigator: project name as H1 with entry file subtitle, sections from the entry file, items within each section
- Main pane: selected artifact rendered as markdown, or project overview (index of all sections and items)
- Job artifacts link back to job chat via "View job conversation" button

**Content organized by project entry file:**
- Architecture, Design Docs, Implementation (links to specs and code)
- Active Job Artifacts (INTENT.md, PLAN.md, WORK_ASSERT.md from running jobs)
- Learnings (institutional, task-based, proxy patterns)

**Gate review flow:** At any approval gate, the job chat header shows a "Review INTENT/PLAN/WORK" button that opens the relevant artifact in this viewer. All gate artifacts use progressive disclosure -- summary first, then links to deeper content (diffs, changed files, test results, research, dependencies).

**Org-level artifacts** (`organization.md`): rolled-up organizational memory -- institutional learnings, procedural skills, proxy knowledge, strategic decisions.

**What it replaces:** No prior equivalent. Previously, reviewing artifacts meant finding the worktree path manually.

### 5. Chat (`chat.html?conv=ID`)

**Purpose:** Async, bidirectional, multi-channel messaging. The primary human interaction surface.

**Two variants based on conversation type:**

**Job Chat** (navigator shows tasks):
- Sidebar: "TASKS" header, job conversation entry, one entry per task sub-conversation
- Red dots on conversations with pending escalations
- Clicking a task shows that task's conversation stream
- Header: participant name, scope, "Review ARTIFACT" button (at gates), "Withdraw" button (with confirmation modal)

**Participant Chat** (navigator shows conversation history):
- Sidebar: "CONVERSATIONS" header, one entry per historical session with that participant, sorted by date
- Clicking a session shows that session's messages
- Used for: Office Manager, Manager, Proxy, Humans

**Shared features:**
- Markdown rendering in messages (bold, lists, links, images, code blocks, blockquotes, tables)
- Toggleable filters: agent, human, thinking, tools, system
- Multiline input: shift+enter for newlines, auto-grows up to 10 rows, then scrollbar
- Human can type into any conversation at any time (interjections)

**What it replaces:** The chat popup windows, the escalation-in-chat flow, the task chat.

---

## Participant Model

| Scope | Agents | Proxy | Humans |
|-------|--------|-------|--------|
| Org (home) | Office Manager | -- | -- |
| Project (config/home) | Manager | Proxy (project learning) | Decider, Advisors |
| Job (chat) | Project Lead | Proxy (job instructions) | Decider, Advisors |

Every scope has the same three categories of participants. What changes is the scope of the conversation.

---

## Key Design Decisions

### Home page IS the status dashboard
No separate status screens. The home page shows all projects, all jobs, all escalations, with workflow progress bars. Click any job to go straight to its chat. This eliminated three dashboard levels (management, project, job status).

### Config uses catalog/assembly model
Global config is the org catalog. Projects assemble from it. Items are tagged `shared`, `local`, or `generated`. Overrides are visible. Like git global/local config.

### Artifacts viewer for gate reviews
At approval gates, the human clicks "Review" in the chat header and the artifact opens in the viewer. No worktree paths to find. All artifacts use progressive disclosure markdown -- summary first, links to deeper content.

### Two chat variants, same page
Job chats navigate by tasks. Participant chats navigate by conversation history. Same rendering, different sidebar content based on conversation type.

### Proxy is directly queryable
The proxy appears as a participant at project and job scope. The human can proactively query its learning, challenge assumptions, or give job-specific instructions before gates happen.

### Office manager learns
The office manager accumulates institutional knowledge about how the human structures teams, workgroups, norms, and budgets. Same learning infrastructure as the proxy.

### Markdown in chat messages
Agents naturally produce markdown. Chat renders it -- links to files for review, images, code blocks, tables. The human's input is also rendered as markdown.

---

## Technical Implementation

### Python Bridge

A small Python process (~100-200 lines) that:
1. Serves the HTML/CSS/JS as static files
2. Exposes REST endpoints for reading SQLite (message bus, state)
3. Provides WebSocket for real-time push (new escalations, state changes, messages)
4. Exposes REST endpoints for writing to message bus (human interjections, responses)

No Claude involvement. No Anthropic API calls. Just a database bridge.

### Data Sources

| Data | Source | Access |
|------|--------|--------|
| Messages | SQLite message bus (`messaging.py`) | REST + WebSocket |
| CfA state | `.cfa-state.json` files | REST (file read) |
| Config | `teaparty.yaml`, `project.yaml`, workgroup YAML | REST (file read) |
| Heartbeats | `.heartbeat` files | REST (file stat) |
| Stats | Derived from message bus + state files | REST (SQL aggregate) |
| Escalations | Message bus (filtered by type) | REST + WebSocket |
| Artifacts | Markdown files on disk | REST (file read + render) |

### Page Structure

Each page is a separate HTML file that opens in its own browser tab:
- `index.html` -- Home dashboard (landing page)
- `config.html?project=ID` -- Config manager (global or project level)
- `stats.html` -- Statistics
- `artifacts.html?project=ID` -- Artifacts viewer (per-project or org)
- `chat.html?conv=ID&task=TASK_ID` -- Chat (one browser tab per conversation)

Cross-app navigation uses `window.open()` with query params. The browser's native tab management handles the rest.

### Workflow Progress Bars

Phases render as bars (work phases) and circles (approval gates):
```
━━━━━━━●━━━━━━━●━━━━━━━●━━━━━━
INTENT      PLAN      WORK      DONE
         ^         ^         ^
      INTENT_   PLAN_    WORK_
      ASSERT    ASSERT   ASSERT
```

Colors: bars are green (complete), yellow (in progress), dim (not reached). Circles are green (passed), red (at this gate), dim (not reached).

---

## Relationship to Other Proposals

- [dashboard-ui](../dashboard-ui/proposal.md) -- Superseded entirely.
- [chat-experience](../chat-experience/proposal.md) -- Chat page implements the interaction model defined there.
- [messaging](../messaging/proposal.md) -- All pages read/write the SQLite message bus defined there.
- [office-manager](../office-manager/proposal.md) -- Config manager and home page delegate to the office manager agent.

---

## Interactive Mockup

[mockup/index.html](mockup/index.html) -- Demonstrates the complete UI with mock data. All content uses lorem ipsum to distinguish illustrative from normative. The normative content is the page structure, navigation flow, information at each level, the participant model, the catalog/assembly pattern, and the gate review flow.
