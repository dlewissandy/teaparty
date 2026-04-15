# TeaParty UX Design

A delightful user experience for a platform where teams of humans and AI agents co-author files and collaborate in chat.

---

## Design Philosophy

**The user should feel like a CEO walking through a building full of brilliant departments.**
They don't micromanage -- they set direction, drop in on conversations, review work, and let their organization run. The UI should make this feel natural, effortless, and -- above all -- *alive*.

### Principles

1. **Alive, not static.** Agents are working even when you're not looking. The UI should breathe -- subtle activity pulses, live status, gentle notifications. You should *feel* the organization humming.
2. **Progressive disclosure.** Home shows the forest. Click to see trees. Click again to see leaves. Never overwhelm.
3. **Chat is the workspace.** Every meaningful interaction happens through conversation. Files, status, and settings are *context* for conversation, not separate destinations.
4. **Agents are people.** Give them avatars, voices, personalities. Show their thinking. Let them surprise you. Never reduce them to spinners or loading bars.
5. **Minimal chrome, maximum content.** Every pixel of UI that isn't content is debt. Borders, labels, and buttons should fade into the background until needed.

---

## Information Architecture

```
Home
 |
 +-- Organization A
 |     |
 |     +-- [Engagement: "Build mobile app"]     <- cross-org work
 |     |
 |     +-- [Project: "Q1 Launch"]               <- cross-workgroup
 |     |     +-- Job: "Design landing page"
 |     |     +-- Job: "Implement checkout"
 |     |
 |     +-- Workgroup: Engineering
 |     |     +-- Job: "Fix login bug"
 |     |     +-- Job: "Add search"
 |     |     +-- Agents: implementer, reviewer
 |     |     +-- Files: src/, docs/, workflows/
 |     |
 |     +-- Workgroup: Design
 |     |     +-- Job: "Redesign dashboard"
 |     |     +-- Agents: designer, researcher
 |     |
 |     +-- Partnerships: A <-> B
 |
 +-- Organization B
       +-- ...
```

---

## Layout Model

Three-panel responsive layout with a hierarchical blade on the left, a conversation in the center, and a contextual file browser on the right.

```
+----------------------------------------------------------------------+
|  [TP]  TeaParty          wg:3  th:12  msg:847         [?] [DK] [ME]  |
+----------+---+------------------------------------------+-----------+
|          | | |                                           |           |
|  TREE    |R| |            CONVERSATION                   |   FILES   |
|  BLADE   |E| |                                           |   PANEL   |
|          |S| |  +--------------------------------------+ |           |
| Breadcrumb|I| |  |  Message from Agent                  | | Directory |
| --------- |Z| |  |  with avatar, name, timestamp       | | --------- |
| Section 1 |E| |  +--------------------------------------+ | file.md   |
|  - item   | | |                                           | config/   |
|  - item   | | |  +--------------------------------------+ |  app.json |
| Section 2 | | |  |  Message from User                   | |           |
|  - item   | | |  |  "Can you add tests?"                | | --------- |
|  - item   | | |  +--------------------------------------+ | Viewer    |
|  - item   | | |                                           | --------- |
|           | | |  +--------------------------------------+ | # README  |
|           | | |  |  Agent is thinking...        [pulse] | | Content   |
|           | | |  +--------------------------------------+ | here...   |
|           | | |                                           |           |
|           | | |  +--------------------------------------+ |           |
|           | | |  | [file: README.md]  |  Type message   | |           |
|           | | |  +--------------------------------------+ |           |
+----------+---+------------------------------------------+-----------+
```

### Panel Behavior

| Panel | Default Width | Min | Max | Collapsible |
|-------|-------------|-----|-----|-------------|
| Tree Blade | 330px | 200px | 50% viewport | No -- always visible |
| Resize Handle | 5px | -- | -- | -- |
| Chat Panel | Fills remaining | 400px | -- | No |
| File Panel | 380px | 280px | 600px | Yes -- toggle via header icon |

### Mobile (< 980px)

Panels stack vertically. The tree collapses to a slide-out drawer triggered by a hamburger icon. The file panel becomes a slide-up sheet.

---

## Screen-by-Screen Design

### Screen 1: Home (Level 1)

The user's command center. Shows all organizations at a glance with live activity indicators.

```
+----------+-------------------------------------------------------+
| TREE     |                    CONVERSATION                        |
|          |                                                       |
| [HOME]   |  Home Agent                                           |
| --------- |  --------------------------------------------------- |
|           |                                                       |
| ORGS      |  [bot]  Welcome back, Primus. Here's what's         |
| --------- |         happening across your organizations:          |
|           |                                                       |
|  Acme Corp|         Acme Corp                                     |
|   [3 active jobs]|    - 3 active jobs across Engineering          |
|   [*] 2 need you |    - 2 items need your attention               |
|           |         - The login page is ready for review          |
|  Widget Co|                                                       |
|   [1 engagement] |  Widget Co                                     |
|           |         - New engagement from PartnerOrg              |
|           |         - Consulting workgroup idle                   |
| INVITES   |                                                       |
| --------- |  --------------------------------------------------- |
|  None     |                                                       |
|           |  [bot]  What would you like to focus on?              |
| MEMBERS   |                                                       |
| --------- |  --------------------------------------------------- |
|  Primus  |                                                       |
|  [home]   |  +--------------------------------------------------+|
|           |  | Type a message to your home agent...        [Send] ||
|           |  +--------------------------------------------------+|
+----------+-------------------------------------------------------+
```

**Key Design Decisions:**

- The home agent greets you with a *live summary*, not a static dashboard. It knows what changed since you last visited.
- Organizations show activity badges: active job count, items needing attention.
- The home agent's conversation *is* the dashboard. Ask it to create orgs, propose partnerships, or just catch you up.

**Activity Indicators on Org Cards:**

```
  +--------------------------------------------+
  |  [A]  Acme Corp                            |
  |                                            |
  |  Engineering    3 active    [*][*][ ]      |
  |  Design         1 active    [*]            |
  |  Admin          idle                       |
  |                                            |
  |  [2 need your input]              [Enter>] |
  +--------------------------------------------+
```

Each `[*]` is a small colored dot: green = progressing, amber = waiting on you, gray = idle.

---

### Screen 2: Organization View (Level 2)

Drill into an organization. See its workgroups, engagements, partnerships, and members.

```
+----------+-------------------------------------------------------+
| TREE     |                    CONVERSATION                        |
|          |                                                       |
| [HOME] > Acme Corp  [gear]                                      |
| --------- |                                                       |
|           |  This is Acme Corp's org-level view.                  |
| WORKGROUPS|  Select a workgroup, engagement, or DM the org lead.  |
| --------- |                                                       |
|  Engineering  [3]|                                                |
|  Design       [1]|  +------------------------------------------+ |
|  QA           [ ]|  |  Recent Activity                          | |
|                  |  |  ---------------------------------------- | |
| ENGAGEMENTS  |  |  [eng] "Mobile app" with PartnerOrg          | |
| --------- |  |       Status: in_progress  [3 jobs]             | |
|  Mobile app   |  |                                              | |
|   in_progress |  |  [eng] Internal: "Q1 marketing site"        | |
|  Q1 site      |  |       Status: negotiating                   | |
|   negotiating |  |                                              | |
|               |  +------------------------------------------+   |
| PARTNERSHIPS  |                                                  |
| --------- |                                                       |
|  PartnerOrg   |                                                   |
|   [active ->] |  DM the Org Lead:                                |
|  VendorInc    |  +--------------------------------------------------+
|   [active <-] |  | Ask the org lead anything...            [Send] |
|               |  +--------------------------------------------------+
| MEMBERS       |                                                   |
| --------- |                                                       |
|  Primus [owner]|                                                 |
|  org-lead [agent]|                                                |
+----------+-------------------------------------------------------+
```

**Key Design Decisions:**

- Clicking an org in the tree drills down. Breadcrumb updates: `Home > Acme Corp`.
- The center panel shows a *summary view* with recent activity cards -- not a blank screen.
- Engagements are first-class navigation items alongside workgroups.
- Partnership direction shown with arrows: `->` means "we can engage them", `<-` means "they can engage us", `<->` means mutual.
- The org lead DM is always available at the bottom -- this is the human's primary interaction point.

---

### Screen 3: Workgroup View (Level 3)

Inside a workgroup. Jobs, agents, files, and the admin conversation.

```
+----------+-------------------------------------------------------+
| TREE     |                    CONVERSATION                        |
|          |                                                       |
| [HOME] > [Acme] > Engineering  [gear]                           |
| --------- |                                                       |
|           |  +--------------------------------------------------+|
| ADMIN     |  |  Admin Conversation                               ||
| --------- |  |  (workgroup management)                           ||
|  [Admin]  |  +--------------------------------------------------+|
|           |                                                       |
| JOBS      |  Selecting a job or agent below opens its             |
| --------- |  conversation in this panel.                          |
|  Fix login bug                                                    |
|   [active] [eng: Mobile app]                                      |
|  Add search                                                       |
|   [active]                                                        |
|  Refactor auth                                                    |
|   [completed]                                                     |
|           |                                                       |
| AGENTS    |                                                       |
| --------- |                                                       |
|  [bot] implementer  [lead]                                        |
|  [bot] reviewer                                                   |
|           |                                                       |
| FILES     |                                                       |
| --------- |                                                       |
|  workflows/                                                       |
|    code-review.md                                                 |
|    feature-build.md                                               |
|  README.md                                                        |
+----------+-------------------------------------------------------+
```

**Key Design Decisions:**

- Jobs are the primary content. Each shows status badge and optional engagement/project link.
- Agents listed with lead designation and custom avatars.
- Clicking a job opens its conversation. Clicking an agent opens a DM (if permitted).
- Files section shows the workgroup's shared files (not job-specific files).

---

### Screen 4: Job Conversation (The Core Experience)

Where work actually happens. This is the screen users spend 80% of their time on.

```
+----------+------------------------------------------+-----------+
| TREE     |        Fix login bug                      |  FILES   |
|          |  Engineering  |  [workflow] [files] [...]  |          |
| [HOME] > [Acme] > Engineering  [gear]               |          |
| --------- |                                          | src/     |
|           |                                          |  auth/   |
| ...       |  +--------------------------------------+|   login  |
|           |  | [bot] implementer         10:30 AM   ||   .tsx   |
| JOBS      |  |                                      ||  comp/   |
| --------- |  | I've analyzed the login bug. The     ||   Button |
|  > Fix    |  | issue is in `auth/session.py` line   ||   Input  |
|    login  |  | 47 -- the token expiry check uses    || test/    |
|  Add      |  | UTC but the stored timestamp is      ||   login  |
|    search |  | local time.                          ||   .test  |
|  Refactor |  |                                      ||          |
|    auth   |  | I'll fix this by normalizing both    || -------- |
|           |  | to UTC. Here's my plan:              ||          |
|           |  |                                      || # login  |
|           |  | 1. Update `validate_session()`       || .tsx     |
|           |  | 2. Add timezone-aware comparison     ||          |
|           |  | 3. Add regression test               || ```tsx   |
|           |  +--------------------------------------+|| import   |
|           |                                          || React    |
|           |  +--------------------------------------+|| from ... |
|           |  | [you] Primus              10:31 AM  ||          |
|           |  |                                      || export   |
|           |  | Looks good. Also check the refresh   || function |
|           |  | token path -- same bug might exist   || Login()  |
|           |  | there too.                           || {        |
|           |  +--------------------------------------+||  ...     |
|           |                                          ||          |
|           |  +--------------------------------------+||          |
|           |  | [bot] implementer                    ||          |
|           |  |                          [thinking]  ||          |
|           |  | Analyzing refresh token path...      ||          |
|           |  +--------------------------------------+||          |
|           |                                          ||          |
|           |  Usage: 45s | $0.12 | 8.4k tok | 23%   ||          |
|           |  +--------------------------------------+||          |
|           |  | [file: auth/session.py]              ||          |
|           |  | Type a message...            [Send]  ||          |
|           |  +--------------------------------------+||          |
+----------+------------------------------------------+-----------+
```

**Key Design Decisions:**

- **Chat header** shows job name, parent workgroup, and quick-action icons (workflow state, files toggle, settings).
- **Messages** show agent avatar, name, timestamp. Agent messages have a warm tan accent. User messages are clean blue.
- **Thinking indicator** is a gentle pulse, not a spinner. Shows what the agent is *doing*, not just "loading".
- **File context bar** in composer shows which file is attached. Click to change or remove.
- **Usage bar** is subtle -- shows elapsed time, cost, token count, and context remaining as a thin progress bar.
- **File panel** on the right shows the job's workspace. Click a file to view it. Click a file + "attach" to add it as context to your next message.

---

### Screen 5: Engagement View

Cross-org collaboration. Two org leads negotiate and track work.

```
+----------+-------------------------------------------------------+
| TREE     |        Mobile App Engagement                           |
|          |  Acme Corp <-> PartnerOrg  |  Status: in_progress      |
| [HOME] > [Acme] > Engagements                                    |
| --------- |                                                       |
|           |  +--------------------------------------------------+|
| ENGAGEMENTS| | [bot] org-lead (Acme)              Yesterday      ||
| --------- | |                                                    ||
|  > Mobile | | We've broken this into three workstreams:          ||
|    app    | |                                                    ||
|  Q1 site  | | 1. Design (UI/UX) -- dispatched to Design WG      ||
|           | | 2. Implementation -- dispatched to Engineering     ||
|           | | 3. QA -- will start after implementation           ||
|           | |                                                    ||
|           | | Current status:                                    ||
|           | | - Design: Job "Mobile UI" -- 60% complete          ||
|           | | - Engineering: Job "Mobile API" -- in progress     ||
|           | | - QA: Not yet started                              ||
|           | +--------------------------------------------------+||
|           |                                                       |
|           |  +--------------------------------------------------+|
|           |  | [bot] org-lead (PartnerOrg)          Today        ||
|           |  |                                                   ||
|           |  | Thanks for the update. The client wants to        ||
|           |  | prioritize the checkout flow -- can Engineering   ||
|           |  | focus there first?                                ||
|           |  +--------------------------------------------------+|
|           |                                                       |
| DISPATCHED|  +--------------------------------------------------+|
| WORK      |  | [you] Primus                        Just now     ||
| --------- |  |                                                   ||
|  Design   |  | @org-lead Yes, reprioritize checkout. And let's   ||
|   Mobile UI  | add Apple Pay to the scope.                       ||
|   [60%]   |  +--------------------------------------------------+|
|  Engin.   |                                                       |
|   Mobile API |  +--------------------------------------------------+
|   [active]|  | Type a message...                          [Send] |
|  QA       |  +--------------------------------------------------+
|   [pending]|                                                      |
+----------+-------------------------------------------------------+
```

**Key Design Decisions:**

- Engagement conversation is the *negotiation and tracking* channel.
- Left panel shows dispatched work with progress indicators.
- Both org leads appear with their org affiliation shown.
- Humans can participate -- they see the conversation and can direct the org lead.
- Status bar at top: engagement status, participating orgs, direction.

---

### Screen 6: Multi-Agent Job (Team Session)

When multiple agents collaborate in a job conversation.

```
+----------+------------------------------------------+-----------+
| TREE     |        Redesign Dashboard                 |  FILES   |
|          |  Design  |  Team: designer, researcher    |          |
|          |  Workflow: feature-build (Step 2 of 5)    |          |
| --------- |                                          |          |
|           |  +--------------------------------------+| mockups/ |
|           |  | [bot] designer (lead)       2:15 PM  ||  v1.svg  |
|           |  |                                      ||  v2.svg  |
|           |  | I've reviewed the current dashboard  || research/|
|           |  | and identified three pain points:    ||  compet  |
|           |  |                                      ||  itor-   |
|           |  | 1. Information density too high      ||  analys  |
|           |  | 2. No clear visual hierarchy         ||  is.md   |
|           |  | 3. Navigation buried in menus        || -------- |
|           |  |                                      ||          |
|           |  | @researcher Can you pull competitor  || [v1.svg] |
|           |  | analyses for dashboard patterns?     ||          |
|           |  +--------------------------------------+|| (render) |
|           |                                          ||          |
|           |  +--------------------------------------+||          |
|           |  | [bot] researcher            2:16 PM  ||          |
|           |  |                                      ||          |
|           |  | On it. I'll look at Linear, Notion,  ||          |
|           |  | and Figma dashboards. Creating       ||          |
|           |  | research/competitor-analysis.md now.  ||          |
|           |  +--------------------------------------+||          |
|           |                                          ||          |
|           |  +--------------------------------------+||          |
|           |  | [you] Primus               2:20 PM  ||          |
|           |  |                                      ||          |
|           |  | Love the direction. Make sure we     ||          |
|           |  | keep the quick-stats row -- users    ||          |
|           |  | told us they check that daily.       ||          |
|           |  +--------------------------------------+||          |
|           |                                          ||          |
|           |  Workflow: Feature Build                  ||          |
|           |  [x] 1. Clarify Requirements             ||          |
|           |  [>] 2. Research & Analysis              ||          |
|           |  [ ] 3. Design Iteration                 ||          |
|           |  [ ] 4. Review & Feedback                ||          |
|           |  [ ] 5. Finalize                         ||          |
|           |                                          ||          |
|           |  +--------------------------------------+||          |
|           |  | Type a message...            [Send]  ||          |
|           |  +--------------------------------------+||          |
+----------+------------------------------------------+-----------+
```

**Key Design Decisions:**

- **Team roster** in the header shows all participating agents.
- **Workflow progress** shown as a compact stepper at the bottom of the message area (above composer). Clickable to see step details.
- Agents mention each other naturally with `@name` -- the conversation reads like a real team discussion.
- The human drops in, gives direction, and leaves. The agents keep working.

---

### Screen 7: Feedback Bubble-Up (Notification Flow)

When an agent deep in a job needs human input, the request bubbles up through the hierarchy.

```
NOTIFICATION FLOW
=================

                     +-------------------------------------------+
                     |  [!] 2 items need your attention           |
                     |                                            |
                     |  [bot] org-lead (Acme)                     |
                     |  "The Engineering team needs your          |
                     |   approval on the auth approach --         |
                     |   they're choosing between JWT and         |
                     |   session tokens."                         |
                     |                                   [View >] |
                     |                                            |
                     |  [bot] org-lead (Acme)                     |
                     |  "Design team wants to know if the         |
                     |   brand colors are final."                 |
                     |                                   [View >] |
                     +-------------------------------------------+

BEHIND THE SCENES (invisible to user):
======================================

  Job Agent (implementer)
       |  "Need human decision: JWT vs session tokens"
       v
  Workgroup Lead (eng-lead)
       |  Summarizes and escalates
       v
  Org Lead (org-lead)
       |  Contextualizes for the human
       v
  Human sees notification in org lead DM
       |
       |  "Go with JWT -- we need stateless auth for mobile"
       v
  Response flows back down:
  Org Lead -> Workgroup Lead -> Job Agent
```

**Key Design Decisions:**

- The human sees a **notification badge** on the org in the tree (amber dot = needs attention).
- Clicking it opens the org lead DM where the org lead has *already summarized* the request in human-friendly language.
- The human responds in natural language. The org lead routes the answer back down.
- The human never sees the raw internal escalation chain -- just the org lead's curated summary.
- `[View >]` links take the human to the relevant job conversation if they want more detail.

---

### Screen 8: Partnership Management

Establishing trust links between organizations.

```
+----------+-------------------------------------------------------+
| TREE     |        Partnerships                                    |
|          |  Acme Corp  |  Settings > Partnerships                 |
| [HOME] > [Acme]  [gear]                                          |
| --------- |                                                       |
|           |  ACTIVE PARTNERSHIPS                                  |
| ...       |  +--------------------------------------------------+|
|           |  |  PartnerOrg                                       ||
|           |  |  Direction: Mutual  [<->]                         ||
|           |  |  Since: Jan 15, 2026                              ||
|           |  |  Active engagements: 1                            ||
|           |  |                              [Revoke]  [Engage >] ||
|           |  +--------------------------------------------------+|
|           |                                                       |
|           |  +--------------------------------------------------+|
|           |  |  VendorInc                                        ||
|           |  |  Direction: They can engage us  [<-]              ||
|           |  |  Since: Feb 1, 2026                               ||
|           |  |  Active engagements: 0                            ||
|           |  |                              [Revoke]             ||
|           |  +--------------------------------------------------+|
|           |                                                       |
|           |  PENDING                                              |
|           |  +--------------------------------------------------+|
|           |  |  StartupXYZ                                       ||
|           |  |  Direction: We want to engage them  [->]          ||
|           |  |  Proposed: Feb 18, 2026                           ||
|           |  |                                       [Withdraw]  ||
|           |  +--------------------------------------------------+|
|           |                                                       |
|           |  INBOUND REQUESTS                                     |
|           |  +--------------------------------------------------+|
|           |  |  AgencyCo wants to be able to engage you          ||
|           |  |  Direction: They want to engage us  [<-]          ||
|           |  |                         [Accept]  [Decline]       ||
|           |  +--------------------------------------------------+|
|           |                                                       |
|           |  +--------------------------------------------------+|
|           |  | [+ Propose Partnership]                           ||
|           |  +--------------------------------------------------+|
+----------+-------------------------------------------------------+
```

---

### Screen 9: Internal Engagement Creation

A human asks their org to do something -- the simplest workflow in the system.

```
FLOW: Human creates an internal engagement
=============================================

Step 1: User clicks [+ New Engagement] in org view
       or simply tells the org lead what they need

+--------------------------------------------------+
|  Org Lead DM                                      |
|                                                   |
|  [you]  I need a marketing site for the Q1        |
|         product launch. Landing page, pricing     |
|         page, and a signup form.                  |
|                                                   |
|  [bot]  I'll set that up as an internal           |
|         engagement. Let me scope it out:          |
|                                                   |
|         Title: Q1 Marketing Site                  |
|         Workgroups: Design + Engineering           |
|         Timeline: 2 weeks                         |
|                                                   |
|         I'll create a project, dispatch design    |
|         first (wireframes + brand), then          |
|         engineering (implementation). Sound good?  |
|                                                   |
|  [you]  Perfect. Keep me posted.                  |
|                                                   |
|  [bot]  Done. I've created:                       |
|         - Engagement: "Q1 Marketing Site"         |
|         - Project with Design + Engineering       |
|         - Job: "Marketing site wireframes"        |
|           (dispatched to Design)                  |
|                                                   |
|         I'll check in with the teams and update   |
|         you here. You can also track progress     |
|         in the Engagements section.               |
+--------------------------------------------------+
```

**Key Design Decision:** The human never fills out a form. They just *tell the org lead what they want* in natural language. The org lead handles decomposition, dispatch, and tracking. This is the magic moment -- it should feel like having a brilliant chief of staff.

---

## Component Design

### Agent Avatars

Each agent gets a unique, generated avatar. The avatar communicates personality at a glance.

```
Bot Avatar (32x32):              Human Avatar (32x32):
+--------+                       +--------+
|  .--.  |                       | /    \ |
| (o  o) |                       ||  **  ||
|  \--/  |                       | \ -- / |
| [====] |                       |  \  /  |
| |    | |                       |   \/   |
+--------+                       +--------+

Colors derived from agent name hash:
  implementer -> warm blue
  reviewer    -> teal
  designer    -> purple
  researcher  -> amber
  org-lead    -> gold
```

### Message Bubbles

```
Agent message:
+--+---------------------------------------------+
|  |  [implementer]               10:30 AM        |
|AV|                                               |
|  |  Message content with **markdown** support    |
|  |  and `code blocks` rendered properly.         |
|  |                                               |
|  |  > Thinking: Analyzing the token expiry...    |
|  |  (collapsed by default, expand to see)        |
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
|  [SYS]  Job "Fix login bug" created              |
|         Workflow: code-review auto-selected       |
+--------------------------------------------------+
    Centered, muted styling, no accent bar
```

### Status Badges

```
Job Status:
  [active]     -> blue bg, white text
  [completed]  -> green bg, white text
  [cancelled]  -> gray bg, white text

Engagement Status:
  [proposed]     -> light purple
  [negotiating]  -> amber
  [in_progress]  -> blue
  [completed]    -> green
  [reviewed]     -> green + checkmark
  [declined]     -> red
  [cancelled]    -> gray

Agent Activity:
  [thinking]   -> pulsing amber dot + "Analyzing..."
  [working]    -> pulsing green dot  + "Writing code..."
  [idle]       -> gray dot (no text)

Partnership Direction:
  [->]   -> "We can engage them"
  [<-]   -> "They can engage us"
  [<->]  -> "Mutual" (both directions)
```

### Workflow Stepper

Shown in job conversations when a workflow is active.

```
Compact (default, shown above composer):
  [x] 1. Scope  [x] 2. Analyze  [>] 3. Implement  [ ] 4. Review  [ ] 5. Ship

Expanded (click to toggle):
  +--------------------------------------------------+
  |  Workflow: Code Review                            |
  |                                                   |
  |  [x] 1. Acknowledge and Scope                    |
  |       Completed by reviewer at 10:15 AM           |
  |                                                   |
  |  [x] 2. Structural Analysis                      |
  |       Completed by reviewer at 10:22 AM           |
  |       Output: review-notes.md                     |
  |                                                   |
  |  [>] 3. Implementation Review   <-- current       |
  |       Agent: implementer                          |
  |       In progress since 10:25 AM                  |
  |                                                   |
  |  [ ] 4. Synthesize Feedback                       |
  |       Agent: reviewer                             |
  |       Loop: 0/3 iterations                        |
  |                                                   |
  |  [ ] 5. Present Results                           |
  |       Completes workflow                          |
  +--------------------------------------------------+
```

### Context Remaining Indicator

A thin bar showing how much LLM context remains for the conversation.

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

### File Panel

```
+------------------------------------------+
|  Files: Engineering (job workspace)  [X]  |
+------------------------------------------+
|  src / auth /                    [+ New]  |
|  ----------------------------------------|
|  [>] components/                          |
|  [>] utils/                               |
|  [ ] session.py              2.1 KB       |
|  [ ] login.tsx               1.8 KB       |
|  [ ] login.test.tsx          3.2 KB       |
|  ----------------------------------------|
|                                           |
|  session.py                 [Raw] [Edit]  |
|  ----------------------------------------|
|  import datetime                          |
|  from typing import Optional              |
|                                           |
|  def validate_session(token: str):        |
|      """Validate a session token."""      |
|      expiry = get_token_expiry(token)     |
|      now = datetime.utcnow()             |
|      return now < expiry                  |
|                                           |
+------------------------------------------+
```

---

## Interaction Workflows

### Workflow 1: First-Time User Onboarding

```
START
  |
  v
Login (Google OAuth)
  |
  v
Home created automatically
Home agent greets user
  |
  v
"Welcome to TeaParty! I'm your home agent.
 I help you manage organizations and partnerships.
 Would you like to create your first organization?"
  |
  +-- User says "Yes" or describes what they want
  |     |
  |     v
  |   "What kind of organization? I have templates:
  |    - Software Development (Engineering + Design + QA)
  |    - Consulting (Research + Writing + Analysis)
  |    - Creative Agency (Design + Content + Strategy)
  |    - Custom (I'll help you build it)"
  |     |
  |     v
  |   User picks template
  |     |
  |     v
  |   Org created with workgroups, agents, workflows
  |   User redirected to org view
  |     |
  |     v
  |   Org lead greets user:
  |   "I'm the org lead for [OrgName]. I manage work
  |    across your teams. Tell me what you need, or
  |    explore the workgroups to see who's here."
  |
  +-- User says "No" or "Later"
        |
        v
      Home agent waits, user explores
```

### Workflow 2: Requesting Work (Internal Engagement)

```
Human tells org lead what they need
  |
  v
Org lead creates engagement (internal)
  |
  v
Org lead decomposes into projects/jobs
  |
  +-- Single workgroup needed?
  |     |
  |     v
  |   Dispatch job directly to workgroup
  |
  +-- Multiple workgroups needed?
        |
        v
      Create project
      Dispatch jobs to each workgroup
        |
        v
      Workgroup leads coordinate in project conversation
        |
        v
      Jobs execute (agents follow workflows)
        |
        +-- Agent needs human input?
        |     |
        |     v
        |   Feedback bubbles up:
        |   Agent -> WG Lead -> Org Lead -> Human
        |   Human responds
        |   Response flows back down
        |
        v
      Jobs complete, merge deliverables
        |
        v
      Org lead assembles results
        |
        v
      Org lead notifies human: "Done! Here's what we built."
        |
        v
      Human reviews deliverables
```

### Workflow 3: Cross-Org Engagement

```
Org A's lead proposes engagement to Org B
  |
  v
Engagement conversation created
Both org leads can see it
  |
  v
NEGOTIATION PHASE
  Org leads discuss scope, terms, timeline
  Humans from either side can participate
  agreement.md is drafted
  |
  v
Org B's lead accepts
  |
  v
IN PROGRESS
  Org B decomposes into internal projects/jobs
  Org B's workgroups execute
  Org A's lead can check status via engagement conversation
  |
  +-- Org B needs something from Org C?
  |     |
  |     v
  |   Sub-engagement: B -> C
  |   Cycle check: Is C already in chain [A, B]? No -> proceed
  |   C executes, delivers back to B
  |
  v
COMPLETED
  Org B places deliverables in deliverables/ folder
  Org A's lead reviews
  |
  v
REVIEWED
  Satisfaction rating
  Engagement archived
```

### Workflow 4: File Collaboration in a Job

```
User opens job conversation
  |
  v
File panel shows job workspace
  |
  +-- Browse files
  |     Click file -> view in panel
  |     Click [Edit] -> inline editor
  |     Click [Attach] -> adds file context to composer
  |
  +-- Agent creates files during conversation
  |     File appears in panel in real-time
  |     User can click to view
  |
  +-- User attaches file to message
  |     File content sent as context
  |     Agent can read and modify it
  |
  +-- For workspace-enabled workgroups (git):
        |
        v
      Job has its own branch
      Agents commit changes
      User can see git diff in file panel
        |
        v
      Job completes -> Merge to main
      Conflict? -> Shown in UI, agent or human resolves
```

---

## Animation and Delight

### Agent Thinking

When an agent is composing a response, show *what* it's doing, not just that it's loading.

```
Phase 1: "Reading session.py..."        (file icon pulse)
Phase 2: "Analyzing token validation..."  (brain icon pulse)
Phase 3: "Writing fix..."              (pencil icon pulse)
Phase 4: "Running tests..."            (test tube icon pulse)
```

The thinking indicator replaces the generic "typing..." with contextual status. This makes the agent feel like a real collaborator, not a black box.

### Notification Toasts

```
+------------------------------------------+
|  [bot] implementer finished a job         |
|  "Fix login bug" -> completed             |
|                                  [View >] |
+------------------------------------------+
    Slides in from bottom-right, auto-dismiss 5s

+------------------------------------------+
|  [!] Org lead needs your input            |
|  "Choose between JWT and session tokens"  |
|                                  [View >] |
+------------------------------------------+
    Amber background, persists until dismissed
```

### Smooth Transitions

- **Panel resize**: CSS transition on width (200ms ease).
- **Blade navigation**: Content cross-fades (150ms) when drilling in/out.
- **New messages**: Slide in from bottom with subtle fade (200ms).
- **File panel open/close**: Slides from right (250ms ease-out).
- **Status badge changes**: Color morphs (300ms).

### Micro-Interactions

- **Unread dot**: Gently pulses twice when a new message arrives, then holds steady.
- **Agent avatar**: Subtle glow when the agent is currently active.
- **Send button**: Brief scale pulse (1.05x) on click.
- **Breadcrumb hover**: Underline slides in from left.
- **Tree item hover**: Background fades in (100ms), not instant.

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

## Responsive Breakpoints

```
Desktop (> 1280px):
  Full three-panel layout
  Tree: 330px | Chat: flex | Files: 380px

Laptop (980-1280px):
  Three panels, narrower tree
  Tree: 260px | Chat: flex | Files: 320px

Tablet (760-980px):
  Two panels, file panel hidden by default
  Tree: slide-out drawer | Chat: full width

Mobile (< 760px):
  Single panel, bottom nav
  Swipe between tree / chat / files
  Compact message layout (smaller avatars, tighter spacing)
```

---

## Key Screens as SVG Wireframes

### Home Screen

```svg
<svg viewBox="0 0 900 500" xmlns="http://www.w3.org/2000/svg" font-family="sans-serif">
  <!-- Topbar -->
  <rect x="0" y="0" width="900" height="48" fill="#2d66d6" rx="0"/>
  <text x="16" y="32" fill="white" font-weight="700" font-size="18">TP</text>
  <text x="50" y="32" fill="rgba(255,255,255,0.8)" font-size="14">TeaParty</text>
  <circle cx="860" cy="24" r="14" fill="rgba(255,255,255,0.2)"/>
  <text x="854" y="29" fill="white" font-size="12">DL</text>

  <!-- Tree Blade -->
  <rect x="0" y="48" width="240" height="452" fill="#f7f9fc"/>
  <rect x="0" y="48" width="240" height="452" fill="none" stroke="#d7e0ea"/>

  <!-- Breadcrumb -->
  <rect x="8" y="56" width="224" height="32" fill="none"/>
  <rect x="12" y="62" width="20" height="20" fill="#2d66d6" rx="4"/>
  <text x="40" y="76" fill="#2d66d6" font-size="11" font-weight="600">HOME</text>

  <!-- Orgs Section -->
  <text x="12" y="110" fill="#5e6f80" font-size="10" font-weight="600">ORGANIZATIONS</text>

  <rect x="8" y="118" width="224" height="40" fill="#e8efff" rx="6"/>
  <circle cx="24" cy="138" r="10" fill="#2d66d6"/>
  <text x="20" y="142" fill="white" font-size="9" font-weight="700">A</text>
  <text x="40" y="134" fill="#1f2d3a" font-size="12" font-weight="600">Acme Corp</text>
  <text x="40" y="146" fill="#5e6f80" font-size="10">3 active jobs</text>
  <circle cx="218" cy="132" r="5" fill="#b45309"/>
  <text x="215" y="135" fill="white" font-size="7" font-weight="700">2</text>

  <rect x="8" y="164" width="224" height="40" fill="white" rx="6" stroke="#d7e0ea"/>
  <circle cx="24" cy="184" r="10" fill="#6b21a8"/>
  <text x="20" y="188" fill="white" font-size="9" font-weight="700">W</text>
  <text x="40" y="180" fill="#1f2d3a" font-size="12" font-weight="600">Widget Co</text>
  <text x="40" y="192" fill="#5e6f80" font-size="10">1 engagement</text>

  <!-- Members Section -->
  <text x="12" y="230" fill="#5e6f80" font-size="10" font-weight="600">MEMBERS</text>
  <rect x="8" y="238" width="224" height="28" fill="white" rx="4" stroke="#d7e0ea"/>
  <text x="16" y="256" fill="#1f2d3a" font-size="11">Primus</text>

  <!-- Chat Panel -->
  <rect x="244" y="48" width="656" height="452" fill="white"/>
  <rect x="244" y="48" width="656" height="452" fill="none" stroke="#d7e0ea"/>

  <!-- Chat Header -->
  <rect x="244" y="48" width="656" height="36" fill="#fafbfc"/>
  <text x="260" y="72" fill="#1f2d3a" font-size="13" font-weight="600">Home</text>

  <!-- Messages -->
  <rect x="260" y="100" width="24" height="24" fill="#d4a44a" rx="4"/>
  <text x="265" y="117" fill="white" font-size="9" font-weight="700">HA</text>
  <text x="292" y="112" fill="#8b5b00" font-size="11" font-weight="600">home-agent</text>
  <text x="440" y="112" fill="#5e6f80" font-size="10">Just now</text>

  <rect x="292" y="120" width="560" height="80" fill="#fdf8f0" rx="6"/>
  <text x="304" y="138" fill="#1f2d3a" font-size="11">Welcome back, Primus. Here's what's happening:</text>
  <text x="304" y="156" fill="#1f2d3a" font-size="11" font-weight="600">Acme Corp</text>
  <text x="304" y="170" fill="#5e6f80" font-size="10">3 active jobs - 2 need your input</text>
  <text x="304" y="186" fill="#1f2d3a" font-size="11" font-weight="600">Widget Co</text>
  <text x="304" y="200" fill="#5e6f80" font-size="10">New engagement from PartnerOrg</text>

  <!-- Composer -->
  <rect x="260" y="460" width="600" height="32" fill="white" rx="6" stroke="#d7e0ea"/>
  <text x="272" y="480" fill="#5e6f80" font-size="11">Talk to your home agent...</text>
  <rect x="820" y="462" width="52" height="28" fill="#2d66d6" rx="4"/>
  <text x="833" y="480" fill="white" font-size="11" font-weight="600">Send</text>
</svg>
```

### Job Conversation Screen

```svg
<svg viewBox="0 0 1100 600" xmlns="http://www.w3.org/2000/svg" font-family="sans-serif">
  <!-- Topbar -->
  <rect x="0" y="0" width="1100" height="48" fill="#2d66d6" rx="0"/>
  <text x="16" y="32" fill="white" font-weight="700" font-size="18">TP</text>
  <text x="50" y="32" fill="rgba(255,255,255,0.8)" font-size="14">TeaParty</text>

  <!-- Tree Blade -->
  <rect x="0" y="48" width="220" height="552" fill="#f7f9fc"/>
  <rect x="0" y="48" width="220" height="552" fill="none" stroke="#d7e0ea"/>

  <!-- Breadcrumb -->
  <rect x="8" y="56" width="204" height="28" fill="none"/>
  <rect x="10" y="60" width="16" height="16" fill="#2d66d6" rx="3"/>
  <text x="32" y="72" fill="#5e6f80" font-size="9">Acme</text>
  <text x="56" y="72" fill="#5e6f80" font-size="9">></text>
  <text x="64" y="72" fill="#1f2d3a" font-size="9" font-weight="600">Engineering</text>

  <!-- Jobs Section -->
  <text x="10" y="102" fill="#5e6f80" font-size="9" font-weight="600">JOBS</text>

  <rect x="6" y="108" width="208" height="32" fill="#e8efff" rx="4"/>
  <text x="14" y="128" fill="#1f2d3a" font-size="11" font-weight="500">Fix login bug</text>
  <rect x="152" y="114" width="50" height="18" fill="#2d66d6" rx="9"/>
  <text x="160" y="127" fill="white" font-size="8" font-weight="600">active</text>

  <rect x="6" y="144" width="208" height="32" fill="white" rx="4" stroke="#d7e0ea"/>
  <text x="14" y="164" fill="#1f2d3a" font-size="11">Add search</text>
  <rect x="152" y="150" width="50" height="18" fill="#2d66d6" rx="9"/>
  <text x="160" y="163" fill="white" font-size="8" font-weight="600">active</text>

  <rect x="6" y="180" width="208" height="32" fill="white" rx="4" stroke="#d7e0ea"/>
  <text x="14" y="200" fill="#5e6f80" font-size="11">Refactor auth</text>
  <rect x="132" y="186" width="70" height="18" fill="#1a7a3a" rx="9"/>
  <text x="140" y="199" fill="white" font-size="8" font-weight="600">completed</text>

  <!-- Agents Section -->
  <text x="10" y="236" fill="#5e6f80" font-size="9" font-weight="600">AGENTS</text>

  <rect x="6" y="242" width="208" height="28" fill="white" rx="4" stroke="#d7e0ea"/>
  <rect x="12" y="248" width="16" height="16" fill="#4a90d9" rx="3"/>
  <text x="34" y="260" fill="#1f2d3a" font-size="10">implementer</text>
  <rect x="164" y="248" width="36" height="16" fill="#e8efff" rx="8"/>
  <text x="170" y="260" fill="#2d66d6" font-size="8" font-weight="600">lead</text>

  <rect x="6" y="274" width="208" height="28" fill="white" rx="4" stroke="#d7e0ea"/>
  <rect x="12" y="280" width="16" height="16" fill="#0d9488" rx="3"/>
  <text x="34" y="292" fill="#1f2d3a" font-size="10">reviewer</text>

  <!-- Chat Panel -->
  <rect x="224" y="48" width="536" height="552" fill="white"/>
  <rect x="224" y="48" width="536" height="552" fill="none" stroke="#d7e0ea"/>

  <!-- Chat Header -->
  <rect x="224" y="48" width="536" height="40" fill="#fafbfc" stroke="#d7e0ea"/>
  <text x="240" y="74" fill="#1f2d3a" font-size="14" font-weight="600">Fix login bug</text>
  <text x="370" y="74" fill="#5e6f80" font-size="10">Engineering</text>

  <!-- Workflow stepper -->
  <rect x="224" y="88" width="536" height="24" fill="#f0f4ff"/>
  <circle cx="260" cy="100" r="6" fill="#1a7a3a"/>
  <text x="256" y="103" fill="white" font-size="7">1</text>
  <text x="272" y="104" fill="#1a7a3a" font-size="9">Scope</text>
  <line x1="300" y1="100" x2="328" y2="100" stroke="#d7e0ea" stroke-width="1"/>
  <circle cx="340" cy="100" r="6" fill="#1a7a3a"/>
  <text x="336" y="103" fill="white" font-size="7">2</text>
  <text x="352" y="104" fill="#1a7a3a" font-size="9">Analyze</text>
  <line x1="390" y1="100" x2="418" y2="100" stroke="#d7e0ea" stroke-width="1"/>
  <circle cx="430" cy="100" r="6" fill="#2d66d6"/>
  <text x="426" y="103" fill="white" font-size="7">3</text>
  <text x="442" y="104" fill="#2d66d6" font-size="9" font-weight="600">Implement</text>
  <line x1="498" y1="100" x2="526" y2="100" stroke="#d7e0ea" stroke-width="1"/>
  <circle cx="538" cy="100" r="6" fill="none" stroke="#d7e0ea"/>
  <text x="534" y="103" fill="#5e6f80" font-size="7">4</text>
  <text x="550" y="104" fill="#5e6f80" font-size="9">Review</text>
  <line x1="586" y1="100" x2="614" y2="100" stroke="#d7e0ea" stroke-width="1"/>
  <circle cx="626" cy="100" r="6" fill="none" stroke="#d7e0ea"/>
  <text x="622" y="103" fill="#5e6f80" font-size="7">5</text>
  <text x="638" y="104" fill="#5e6f80" font-size="9">Ship</text>

  <!-- Agent message 1 -->
  <rect x="240" y="122" width="20" height="20" fill="#4a90d9" rx="4"/>
  <text x="244" y="136" fill="white" font-size="7" font-weight="700">IM</text>
  <text x="268" y="134" fill="#8b5b00" font-size="10" font-weight="600">implementer</text>
  <text x="480" y="134" fill="#5e6f80" font-size="9">10:30 AM</text>

  <rect x="240" y="140" width="504" height="90" fill="#fdf8f0" rx="6"/>
  <line x1="240" y1="140" x2="240" y2="230" stroke="#c28f2e" stroke-width="3"/>
  <text x="252" y="158" fill="#1f2d3a" font-size="10">I've analyzed the login bug. The issue is in</text>
  <text x="252" y="172" fill="#1f2d3a" font-size="10" font-family="monospace" font-weight="600">auth/session.py</text>
  <text x="365" y="172" fill="#1f2d3a" font-size="10">line 47 -- the token</text>
  <text x="252" y="186" fill="#1f2d3a" font-size="10">expiry check uses UTC but the stored timestamp</text>
  <text x="252" y="200" fill="#1f2d3a" font-size="10">is local time.</text>
  <text x="252" y="220" fill="#1f2d3a" font-size="10">I'll fix this by normalizing both to UTC.</text>

  <!-- User message -->
  <rect x="700" y="248" width="20" height="20" fill="#2d66d6" rx="10"/>
  <text x="704" y="262" fill="white" font-size="7" font-weight="700">DL</text>
  <text x="268" y="260" fill="#1f2d3a" font-size="10" font-weight="600">Primus</text>
  <text x="480" y="260" fill="#5e6f80" font-size="9">10:31 AM</text>

  <rect x="240" y="268" width="504" height="48" fill="#f0f4ff" rx="6"/>
  <line x1="744" y1="268" x2="744" y2="316" stroke="#2d66d6" stroke-width="3"/>
  <text x="252" y="288" fill="#1f2d3a" font-size="10">Looks good. Also check the refresh token path --</text>
  <text x="252" y="304" fill="#1f2d3a" font-size="10">same bug might exist there too.</text>

  <!-- Agent thinking -->
  <rect x="240" y="330" width="20" height="20" fill="#4a90d9" rx="4"/>
  <text x="268" y="342" fill="#8b5b00" font-size="10" font-weight="600">implementer</text>
  <rect x="240" y="352" width="504" height="32" fill="#fdf8f0" rx="6"/>
  <line x1="240" y1="352" x2="240" y2="384" stroke="#c28f2e" stroke-width="3"/>
  <circle cx="262" cy="368" r="4" fill="#b45309" opacity="0.6"/>
  <text x="274" y="372" fill="#8b5b00" font-size="10" font-style="italic">Analyzing refresh token path...</text>

  <!-- Usage bar -->
  <rect x="240" y="540" width="504" height="16" fill="#fafbfc"/>
  <text x="252" y="552" fill="#5e6f80" font-size="8">45s</text>
  <text x="282" y="552" fill="#5e6f80" font-size="8">$0.12</text>
  <text x="318" y="552" fill="#5e6f80" font-size="8">8.4k tokens</text>
  <rect x="400" y="546" width="120" height="4" fill="#e5e7eb" rx="2"/>
  <rect x="400" y="546" width="92" height="4" fill="#2d66d6" rx="2"/>
  <text x="526" y="552" fill="#5e6f80" font-size="8">23% context</text>

  <!-- Composer -->
  <rect x="240" y="560" width="504" height="32" fill="white" rx="6" stroke="#d7e0ea"/>
  <rect x="244" y="564" width="100" height="24" fill="#e8efff" rx="4"/>
  <text x="252" y="580" fill="#2d66d6" font-size="8">auth/session.py</text>
  <text x="360" y="580" fill="#5e6f80" font-size="10">Type a message...</text>
  <rect x="696" y="564" width="44" height="24" fill="#2d66d6" rx="4"/>
  <text x="706" y="580" fill="white" font-size="10" font-weight="600">Send</text>

  <!-- File Panel -->
  <rect x="764" y="48" width="336" height="552" fill="white"/>
  <rect x="764" y="48" width="336" height="552" fill="none" stroke="#d7e0ea"/>

  <!-- File Header -->
  <rect x="764" y="48" width="336" height="36" fill="#fafbfc" stroke="#d7e0ea"/>
  <text x="780" y="72" fill="#1f2d3a" font-size="12" font-weight="600">Files</text>
  <text x="820" y="72" fill="#5e6f80" font-size="10">Job workspace</text>

  <!-- File tree -->
  <text x="780" y="102" fill="#5e6f80" font-size="9" font-weight="600">src / auth /</text>

  <rect x="776" y="110" width="316" height="24" fill="white" rx="3" stroke="#d7e0ea"/>
  <text x="792" y="126" fill="#c28f2e" font-size="10">components/</text>

  <rect x="776" y="138" width="316" height="24" fill="#e8efff" rx="3"/>
  <text x="792" y="154" fill="#1f2d3a" font-size="10" font-weight="500">session.py</text>
  <text x="1060" y="154" fill="#5e6f80" font-size="9">2.1 KB</text>

  <rect x="776" y="166" width="316" height="24" fill="white" rx="3" stroke="#d7e0ea"/>
  <text x="792" y="182" fill="#1f2d3a" font-size="10">login.tsx</text>
  <text x="1060" y="182" fill="#5e6f80" font-size="9">1.8 KB</text>

  <!-- Divider -->
  <line x1="776" y1="210" x2="1088" y2="210" stroke="#d7e0ea"/>

  <!-- File viewer -->
  <text x="780" y="228" fill="#1f2d3a" font-size="11" font-weight="600">session.py</text>
  <rect x="1020" y="216" width="32" height="18" fill="#f0f4ff" rx="3"/>
  <text x="1026" y="229" fill="#2d66d6" font-size="8">Raw</text>
  <rect x="1056" y="216" width="32" height="18" fill="#2d66d6" rx="3"/>
  <text x="1062" y="229" fill="white" font-size="8">Edit</text>

  <text x="780" y="252" fill="#5e6f80" font-size="9" font-family="monospace">import datetime</text>
  <text x="780" y="266" fill="#5e6f80" font-size="9" font-family="monospace">from typing import Optional</text>
  <text x="780" y="286" fill="#5e6f80" font-size="9" font-family="monospace">def validate_session(token):</text>
  <text x="780" y="300" fill="#5e6f80" font-size="9" font-family="monospace">    """Validate session."""</text>
  <text x="780" y="314" fill="#5e6f80" font-size="9" font-family="monospace">    expiry = get_expiry(token)</text>
  <text x="780" y="328" fill="#5e6f80" font-size="9" font-family="monospace">    now = datetime.utcnow()</text>
  <text x="780" y="342" fill="#5e6f80" font-size="9" font-family="monospace">    return now &lt; expiry</text>
</svg>
```

---

## Navigation State Machine

```
                    +----------+
                    |   HOME   |  Level 1
                    | (root)   |
                    +----+-----+
                         |
              +----------+-----------+
              |                      |
        +-----v------+        +-----v------+
        |  ORG VIEW  |        |  ORG VIEW  |  Level 2
        |  (Acme)    |        |  (Widget)  |
        +-----+------+        +------------+
              |
    +---------+----------+-----------+
    |         |          |           |
+---v---+ +--v---+ +----v----+ +----v------+
| WORK  | | WORK | | ENGAGE  | | PARTNER   |  Level 3
| GROUP | | GROUP| | MENT    | | SHIPS     |
| (Eng) | | (Des)| | (view)  | | (manage)  |
+---+---+ +------+ +---------+ +-----------+
    |
    +--------+---------+
    |        |         |
+---v--+ +--v---+ +---v---+
| JOB  | | JOB  | | AGENT |  Level 3.5
| conv | | conv | | DM    |  (opens in
+------+ +------+ +-------+   chat panel)
```

Each level is a "blade" in the left tree. Clicking deeper replaces the tree content
and updates the breadcrumb. The chat panel shows the selected conversation or a
summary view. The file panel shows contextual files.

---

## Accessibility

- **All interactive elements** have visible focus rings (blue outline, 2px offset).
- **Keyboard navigation**: Tab through tree items, Enter to select, Escape to go up a level.
- **Screen readers**: ARIA labels on all buttons, live regions for new messages, role="log" on message list.
- **Color contrast**: All text meets WCAG AA (4.5:1 for normal text, 3:1 for large text).
- **Reduced motion**: Respects `prefers-reduced-motion` -- disables all animations, transitions snap instantly.
- **Font scaling**: All sizes in rem, layout flexes with browser font size up to 200%.

---

## Summary

The TeaParty UX is built on a simple insight: **the best management tool is a conversation.** Instead of dashboards full of charts and forms, users talk to intelligent agents who handle complexity behind the scenes. The UI's job is to make those conversations feel natural, keep the organizational context visible without being overwhelming, and let the user feel the *life* of their AI-powered organization.

Every screen flows from conversation. Every action starts with a message. The human is always in control -- but they control by *directing*, not by clicking through forms. That's the delight.
