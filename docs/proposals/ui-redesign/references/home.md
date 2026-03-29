[UI Redesign](../proposal.md) >

# Home Page

The landing page. Answers "what needs my attention?" and "where do I want to go?" in one screen.

Mockup: [mockup/index.html](../mockup/index.html)

---

## User Stories

### "I just opened TeaParty. What's happening?"
The home page shows every project with active job counts, escalation counts, and workflow progress bars. At a glance: POC has 3 jobs (two at gates, one planning), Joke-book has 2 jobs (one working, one reviewing). Red pulsing dots mark jobs with escalations.

### "Something needs my attention."
The org row shows a red escalation badge with total count across all projects. Each project card shows escalations inline — phase, summary, age. Click any escalation to open the job chat with the relevant task conversation selected.

### "I want to respond to an escalation."
Click the job row (or the escalation within the card). A new browser tab opens with `chat.html?conv=j1&task=t2`. The chat shows the conversation, the sidebar highlights the task, and the human types a response. The orchestrator picks it up from the message bus.

### "I want to start a new job."
Click "Manager" on the project card. A participant chat opens with the project manager. The human describes the work. The manager creates the job.

### "I want to create a new project."
Click "+ New Project" (right-aligned on the PROJECTS header). An Office Manager chat opens. The human describes the project. The office manager assembles it from the org catalog.

### "I want to check org-level config or knowledge."
The org row has cards for Global Config, Statistics, Org Knowledge (organization.md), and Office Manager. Each opens the relevant page in a new tab.

---

## Layout

**Org row:** Horizontal cards — Global Config, Statistics, Org Knowledge, Office Manager. Plus a red escalation badge when escalations exist.

**Project cards:** Grid layout, one card per project. Each card contains:
1. Header: project name + status badge (ACTIVE/IDLE)
2. Description (one line, italic)
3. Stats row: active jobs | escalations | workgroups
4. Job rows: each shows job name (truncated), workflow progress bar, status badge, red dot if escalation
5. Action buttons: Config | Artifacts | Manager

---

## Workflow Progress Bars

Jobs display inline workflow bars using the bar-circle-bar pattern:

```
━━━━━━━●━━━━━━━●━━━━━━━●━━━━━━
INTENT      PLAN      WORK      DONE
```

Bars represent work phases. Circles represent approval gates (INTENT_ASSERT, PLAN_ASSERT, WORK_ASSERT).

| Element | Complete | In Progress | At Gate | Not Reached |
|---------|----------|-------------|---------|-------------|
| Bar | Green | Yellow | — | Dim |
| Circle | Green | — | Red (pulsing) | Dim |

Task escalations during a work phase: the work bar is yellow, the escalation dot on the job row is red. Gate escalations: the preceding bar is green (work done), the gate circle is red (awaiting review).

---

## Controls

| Control | Action |
|---------|--------|
| Click org card | Opens corresponding page in new tab |
| Click project job row | Opens job chat (`chat.html?conv=JOB_ID`) |
| Click escalation within card | Opens job chat at the escalated task (`chat.html?conv=JOB_ID&task=TASK_ID`) |
| Click "Config" button | Opens project config (`config.html?project=ID`) |
| Click "Artifacts" button | Opens project artifacts (`artifacts.html?project=ID`) |
| Click "Manager" button | Opens manager chat (`chat.html?conv=poc-manager`) |
| Click "+ New Project" | Opens office manager chat (`chat.html?conv=office-manager`) |
