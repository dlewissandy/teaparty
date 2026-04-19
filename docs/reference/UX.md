# TeaParty UX Design

The user experience for a platform where humans and AI agent teams collaborate on coordinated work.

Design principles, information architecture, and component patterns for the TeaParty dashboard. Implementation lives in `teaparty/bridge/static/`; see [bridge architecture](../systems/bridge/index.md) and [navigation](../systems/bridge/navigation.md) for behavior reference.

---

## Design Philosophy

**The user should feel like a manager walking through a building full of capable teams.** They don't micromanage. They set direction, drop in on conversations, review work, and let the organization run. The UI should make this feel natural, effortless, and *alive*.

### Principles

1. **Alive, not static.** Agents are working even when you're not looking. The UI breathes: subtle activity pulses, live status, gentle notifications. You should *feel* the work humming.
2. **Progressive disclosure.** Home shows the management overview. Click into a project to see its workgroups and jobs. Click into a job to see its conversation and artifacts. Never overwhelm.
3. **Chat is the workspace.** Every meaningful interaction happens through conversation. Files, status, and configuration are *context* for conversation, not separate destinations.
4. **Agents are people.** Give them avatars, voices, personalities. Show their thinking. Never reduce them to spinners or loading bars.
5. **Minimal chrome, maximum content.** Every pixel of UI that isn't content is debt. Borders, labels, and buttons fade into the background until needed.

---

## Information Architecture

The user's mental model is a three-level hierarchy that mirrors the [organizational model](../overview.md):

```
Management (home)
 ├── Office Manager (chat)
 ├── Configuration Team
 └── Project A
       ├── Project Lead (chat)
       ├── Workgroup: Engineering
       │     └── Agents: implementer, reviewer, …
       ├── Workgroup: Research
       │     └── Agents: literature-researcher, …
       └── Jobs
             └── Job: "Fix login bug"
                   ├── Tasks (per-agent worktrees)
                   └── Artifacts (INTENT.md, PLAN.md, deliverables)
```

The two scopes correspond directly to the on-disk configuration tree (`~/.teaparty/management/` and `{project}/.teaparty/project/`); see [folder structure](folder-structure.md).

---

## Layout Model

Two-panel layout with a hierarchical content area on the left and a slide-out chat blade on the right.

```
+----------------------------------------------------------------------+
|  [TP]  TeaParty       jobs:3   conv:5   $0.42         [?] [DK] [ME]  |
+--------------------------------------------------------+-+-----------+
|                                                         | |           |
|                       MAIN CONTENT                      |T|   CHAT    |
|                                                         |A|   BLADE   |
|  +-------------------------+ +-------------------------+|B| (collapsi-|
|  |  Project A              | |  Project B              ||| ble — opens|
|  |  3 active jobs          | |  idle                   ||| a chat with|
|  |  [open >]               | |  [open >]               ||| the agent  |
|  +-------------------------+ +-------------------------+|| scoped to  |
|                                                         || the page  |
|  Active jobs                                            ||           |
|  --------------------------------------------------------|+-----------+
|  • Fix login bug — implementer (active)                 |
|  • Add search — designer (waiting on you)               |
+----------------------------------------------------------------------+
```

The chat blade mounts on every page that uses the `blade-layout` container (index, config, and artifacts pages). See [chat-ux](../systems/bridge/chat-ux.md) for the routing table that determines which conversation the blade opens.

### Panel behavior

| Element | Default | Min | Max | Collapsible |
|---|---|---|---|---|
| Main content | Fills viewport | — | — | No |
| Chat blade | 33vw when open | 320px | 50vw | Yes — chevron tab toggles |
| Top status bar | 48px height | — | — | No |

### Mobile (< 760px)

Main content stacks vertically; the blade becomes a slide-up sheet triggered by a chat icon in the bottom nav. See [Responsive Breakpoints](#responsive-breakpoints).

---

## Screens

### Home: Management Dashboard

Where the user lands. Shows the management team, projects, active jobs, and overall system health.

```
+----------------------------------------------------------------------+
|  TeaParty   jobs:3   conv:5   $0.42                                  |
+--------------------------------------------------------+-------------+
|                                                         | Office     |
|  Management Team                                        | Manager    |
|  ----------------------------------------------------- | (chat)     |
|  [bot] office-manager (lead)                           |             |
|  [bot] configuration-lead                              | "Hey, the   |
|  [you] Primus (decider)                                | research    |
|                                                         | team just   |
|  Projects                                               | landed the  |
|  ----------------------------------------------------- | Sumerian    |
|  [icon] humor-book              3 active jobs   [>]    | brief…"     |
|  [icon] teaparty                idle             [>]    |             |
|                                                         |             |
|  Active jobs                                            | [filters]   |
|  ----------------------------------------------------- | agent       |
|  • humor-book / "Write Ch7"  — writing-lead (active)   | human       |
|  • humor-book / "Verify…"    — quality-control (idle)  | thinking    |
|                                                         | tools       |
|  Escalation queue (2)                                   | results     |
|  ----------------------------------------------------- | ...         |
|  • [PLAN_ASSERT] humor-book — proxy needs you          |             |
+--------------------------------------------------------+-------------+
```

**Key decisions:**

- **The OM chat blade is the user's coordination surface.** Cross-project questions ("what's going on right now") and unscoped intent ("take this and put it somewhere sensible") go here.
- **Project cards show live activity.** A status dot indicates whether the project has running jobs, idle workgroups, or pending escalations.
- **The escalation queue surfaces gates that need a human decision.** Clicking an item opens the relevant project chat with the gate question in context.

### Project Page

Shows one project's workgroups, agents, jobs, and configuration.

```
+----------------------------------------------------------------------+
|  TeaParty > humor-book                            [+ New Job] [Edit] |
+--------------------------------------------------------+-------------+
|  Project Lead                                           | Project    |
|  [bot] humor-book-lead                                 | Lead chat   |
|                                                         |             |
|  Workgroups                                             | "Working on |
|  ----------------------------------------------------- | Ch7 now —   |
|  [icon] writing      lead: writing-lead    [3 agents]  | reviewing   |
|  [icon] research     lead: research-lead   [2 agents]  | the         |
|  [icon] editorial    lead: editorial-lead  [1 agent]   | absurdism   |
|  [icon] verification lead: qc-lead         [2 agents]  | brief.      |
|                                                         | Want me to  |
|  Active jobs                                            | flag the    |
|  ----------------------------------------------------- | Camus       |
|  • Write Ch7 — writing-lead (active)         [>]       | substitution|
|  • Verify manuscript — qc-lead (waiting)     [>]       | early?"     |
|                                                         |             |
|  Configuration  [agents] [skills] [hooks] [pins]       |             |
+--------------------------------------------------------+-------------+
```

**Key decisions:**

- **The project lead chat blade is scoped to this project.** Steering, status, and project-level questions go here.
- **Workgroups list focus + roster.** Drilling into a workgroup shows its agents, skills, and assigned work.
- **Configuration tabs** route through the configuration lead. The user describes what they want in chat; the lead's specialists apply the change. See [configuring teams](../guides/configuring-teams.md).

### Job Page

The core experience. One job, its conversation, its artifacts, and the workflow state.

```
+----------------------------------------------------------------------+
|  Fix login bug                                       [Withdraw]      |
|  humor-book > job-20260315-171017               State: TASK          |
+--------------------------------------------------------+-------------+
|  Phase Stepper                                          | Project    |
|  [✓] Intent  [✓] Planning  [▶] Execution  [ ] Done    | Lead chat   |
|                                                         |             |
|  Conversation                                           | (project    |
|  ----------------------------------------------------- | lead in     |
|  [bot] writing-lead                  10:30 AM           | this thread)|
|  Drafting Ch7. Following the absurdism brief — Spam     |             |
|  sketch is the opening, Camus close is the landing.     |             |
|                                                         |             |
|  [bot] writing-lead                  10:42 AM           |             |
|  First pass complete. ch7.md committed to the worktree. |             |
|                                                         |             |
|  [you] Primus                        10:51 AM           |             |
|  Looks good. Watch for the Gottfried/Aristocrats        |             |
|  duplication with Ch5.                                  |             |
|                                                         |             |
|  Artifacts (in worktree)                                |             |
|  ----------------------------------------------------- |             |
|  INTENT.md     PLAN.md     ch7.md     research/        |             |
+--------------------------------------------------------+-------------+
```

**Key decisions:**

- **Phase stepper** shows current CfA state (Intent / Planning / Execution / Done) with backtracks visible if any occurred.
- **Conversation is the primary content.** Agent messages, human messages, system events all interleave in time order.
- **Artifacts row** lists files in the job's worktree. Clicking opens the file viewer with the chat blade still scoped to the project lead. See [artifact-page](../systems/bridge/artifact-page.md).

### Configuration Screens

The configuration tree (management → project → workgroup → agent) is browsable but read-mostly. Mutation goes through the configuration lead conversation. See [configuring teams](../guides/configuring-teams.md) for the full workflow.

### Chat Window (full-screen)

The blade can also open as a full-screen window for long conversations. URL parameters control conversation selection, filters, and pre-seeded messages; see [chat-ux](../systems/bridge/chat-ux.md).

---

## Component Design

### Agent avatars

Each agent gets a generated avatar derived from its name hash. The avatar communicates personality at a glance.

```
Bot avatar (32×32):              Human avatar (32×32):
+--------+                       +--------+
|  .--.  |                       | /    \ |
| (o  o) |                       ||  **  ||
|  \--/  |                       | \ -- / |
| [====] |                       |  \  /  |
+--------+                       +--------+

Color from name hash:
  office-manager  -> gold
  project-lead    -> blue
  implementer     -> teal
  reviewer        -> purple
  designer        -> amber
  researcher      -> green
```

### Message bubbles

```
Agent message:
+--+---------------------------------------------+
|  |  [implementer]               10:30 AM        |
|AV|                                               |
|  |  Message content with **markdown** support    |
|  |  and `code blocks` rendered properly.         |
|  |                                               |
|  |  > Thinking: Analyzing the token expiry…      |
|  |  (collapsed by default; expand to see)        |
+--+---------------------------------------------+
    Left accent bar: warm tan (#c28f2e)

User message:
+---------------------------------------------+--+
|  Primus                        10:31 AM     |  |
|                                              |AV|
|  Message content here.                       |  |
+---------------------------------------------+--+
    Right accent bar: blue (#2d66d6)

System message:
+--------------------------------------------------+
|  [SYS]  CfA state: PLANNING → PLAN_ASSERT        |
+--------------------------------------------------+
    Centered, muted styling, no accent bar
```

### Status badges

```
Job status:
  [active]     -> blue background
  [waiting]    -> amber background (gate or escalation)
  [completed]  -> green background
  [withdrawn]  -> gray background

CfA state:
  [INTENT]        [PROPOSAL]      [INTENT_ASSERT]
  [PLANNING]      [DRAFT]         [PLAN_ASSERT]
  [TASK]          [TASK_ASSERT]   [WORK_ASSERT]
  [WITHDRAWN]     [COMPLETED_WORK]

Agent activity:
  [thinking]   -> pulsing amber dot + "Analyzing..."
  [working]    -> pulsing green dot + "Writing code..."
  [waiting]    -> gray dot
  [idle]       -> no indicator
```

### Phase stepper

Compact, shown above the job conversation:

```
Compact (default):
  [✓] Intent  [✓] Planning  [▶] Execution  [ ] Done

Expanded (click to toggle):
  +--------------------------------------------------+
  |  CfA Phase Trace                                  |
  |                                                   |
  |  [✓] Intent     IDEA → PROPOSAL → INTENT_ASSERT   |
  |       INTENT.md approved by proxy at 09:14         |
  |                                                   |
  |  [✓] Planning   INTENT → DRAFT → PLAN_ASSERT      |
  |       PLAN.md approved by proxy at 09:33           |
  |                                                   |
  |  [▶] Execution  TASK → TASK_ASSERT (in progress)  |
  |       3 tasks dispatched, 1 completed              |
  |                                                   |
  |  [ ] Done       WORK_ASSERT pending                |
  +--------------------------------------------------+
```

Backtracks render as visible loops (e.g. `[↺ TASK → PLANNING]`) so rework is never hidden in the UI.

### Context-remaining indicator

A thin bar at the bottom of the conversation showing how much LLM context remains:

```
Full context:
  [========================================] 100%

Half used:
  [====================                    ]  50%

Getting low (turns amber):
  [======                                  ]  15%

Critical (turns red):
  [==                                      ]   5%
```

Mirrors the per-session context budget tracked in [context-budget](../systems/cfa-orchestration/context-budget.md).

### Artifacts row

Below the conversation, a row of pinned files for the job:

```
+------------------------------------------+
|  Artifacts                                |
+------------------------------------------+
|  [INTENT.md]  [PLAN.md]  [ch7.md]  [...] |
+------------------------------------------+
```

Clicking opens the file viewer in the artifact page; the chat blade follows along, still scoped to the project lead. Pinning is configured per workgroup or project; see [team configuration](team-configuration.md).

### Withdraw and Pause controls

Two destructive controls, separated visually:

- **Withdraw**: kills the job; cascades through dispatch hierarchy. Lives in the page header behind a confirmation modal.
- **Pause**: halts new dispatches; in-flight work completes. Resumable. Lives in a less prominent position to discourage accidental use.

See [steering sessions](../guides/steering-sessions.md).

---

## Color System

```
LIGHT MODE                          DARK MODE
==========                          =========

Primary:     #2d66d6  (blue)        #6da3ff  (lighter blue)
Agent:       #8b5b00  (warm tan)    #d4a44a  (golden)
Success:     #1a7a3a  (green)       #4ade80  (bright green)
Warning:     #b45309  (amber)       #fbbf24  (bright amber)
Danger:      #9b2a1f  (red)         #f87171  (bright red)

Background:  #eef2f7  (cool gray)   #0c1420  (deep navy)
Panel:       #ffffff  (white)       #111b2a  (dark navy)
Tree bg:     #f7f9fc  (ice blue)    #0e1825  (darker navy)

Text:        #1f2d3a  (near-black)  #e2e8f0  (near-white)
Muted:       #5e6f80  (gray)        #8899aa  (lighter gray)
Border:      #d7e0ea  (light)       #1e2d3f  (dark border)
```

The current dashboard ships dark mode by default. CSS custom properties under `:root` (`--bg`, `--surface`, `--green`, `--red`, etc.) make a light-mode swap a one-line change.

---

## Typography

```
Font: Manrope (Google Fonts)
Fallback: "Segoe UI", system-ui, sans-serif

Scale:
  Page title (h1):     1.5rem   / 700 weight
  Section title (h2):  1.1rem   / 600 weight
  Body text:           0.95rem  / 400 weight
  Meta / labels:       0.84rem  / 500 weight
  Small / badges:      0.75rem  / 600 weight

Code: "JetBrains Mono", "Fira Code", monospace
  Inline code:         0.88rem  / 400 weight
  Code block:          0.85rem  / 400 weight
```

---

## Animation

### Agent thinking

When an agent is working, show *what* it's doing rather than that it's loading.

```
Phase 1: "Reading session.py…"          (file icon pulse)
Phase 2: "Analyzing token validation…"  (brain icon pulse)
Phase 3: "Writing fix…"                 (pencil icon pulse)
Phase 4: "Running tests…"               (test tube icon pulse)
```

The thinking indicator replaces a generic "typing…" with contextual status. This makes the agent feel like a real collaborator, not a black box.

### Notification toasts

```
+------------------------------------------+
|  [bot] writing-lead finished a job        |
|  "Write Ch7" → completed                  |
|                                  [View >] |
+------------------------------------------+
    Slides in from bottom-right; auto-dismiss 5s

+------------------------------------------+
|  [!] Proxy needs your input               |
|  PLAN_ASSERT — humor-book                 |
|                                  [View >] |
+------------------------------------------+
    Amber background; persists until dismissed
```

### Smooth transitions

- **Blade open/close:** slides from right (250ms ease-out).
- **Page navigation:** content cross-fades (150ms) when drilling in/out.
- **New messages:** slide in from bottom with subtle fade (200ms).
- **Status badge changes:** color morphs (300ms).

### Micro-interactions

- **Unread dot:** gently pulses twice when a new message arrives, then holds steady.
- **Agent avatar:** subtle glow when the agent is currently active.
- **Send button:** brief scale pulse (1.05×) on click.
- **Tree item hover:** background fades in (100ms), not instant.

---

## Responsive Breakpoints

```
Desktop (> 1280px):
  Two-panel layout, generous whitespace
  Main: flex | Chat blade: 33vw (resizable 320px-50vw)

Laptop (980-1280px):
  Two panels, narrower blade
  Main: flex | Chat blade: 380px

Tablet (760-980px):
  Two panels, blade hidden by default
  Main: full width | Blade: slide-out sheet

Mobile (< 760px):
  Single panel, bottom nav
  Main: full width
  Chat: slide-up sheet from bottom
  Compact message layout (smaller avatars, tighter spacing)
```

---

## Accessibility

- **All interactive elements** have visible focus rings (blue outline, 2px offset).
- **Keyboard navigation:** Tab through nav items, Enter to select, Escape to close blades.
- **Screen readers:** ARIA labels on all buttons; live regions for new messages; `role="log"` on message lists.
- **Color contrast:** All text meets WCAG AA (4.5:1 for normal text, 3:1 for large text).
- **Reduced motion:** Respects `prefers-reduced-motion`; disables all animations; transitions snap instantly.
- **Font scaling:** All sizes in `rem`; layout flexes with browser font size up to 200%.

---

## Implementation Reference

| Concern | Source of truth |
|---|---|
| Layout, panel behavior | `teaparty/bridge/static/styles.css` |
| Chat blade mount + routing | `teaparty/bridge/static/accordion-chat.js` ([chat-ux](../systems/bridge/chat-ux.md)) |
| Page navigation | [navigation](../systems/bridge/navigation.md) |
| Stats bar | [stats-bar](../systems/bridge/stats-bar.md) |
| Artifact viewer | [artifact-page](../systems/bridge/artifact-page.md) |
| WebSocket event flow | [bridge index](../systems/bridge/index.md) |

This page specifies *what the experience should feel like*. The bridge architecture docs above specify *how it's implemented*. When the two diverge, the implementation docs are authoritative for behavior; this one is authoritative for principles.

---

## Summary

The TeaParty UX is built on a simple insight: **the best management tool is a conversation.** Instead of dashboards full of charts and forms, users talk to intelligent agents who handle complexity behind the scenes. The UI's job is to make those conversations feel natural, keep the organizational context visible without being overwhelming, and let the user feel the *life* of their AI-powered teams.

Every screen flows from conversation. Every action starts with a message. The human is always in control, but they control by *directing* rather than by clicking through forms.
