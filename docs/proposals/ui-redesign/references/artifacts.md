[UI Redesign](../proposal.md) >

# Artifacts Viewer

Browsable project documentation and the primary surface for gate reviews. Each project has a `project.md` entry file; the org has `organization.md`.

Mockup: [mockup/artifacts.html](../mockup/artifacts.html)

---

## User Stories

### "I'm at a gate review and need to see what was produced."
The job chat header shows a green "Review PLAN" button (or INTENT/WORK depending on the gate). Click it. The Artifacts viewer opens with the gate document rendered as markdown. The document uses progressive disclosure — summary first, then links to deeper content. For WORK_ASSERT, those links point to diffs, changed files, and test results. The human reads, decides, returns to the chat to respond.

### "I want to browse the project's design docs."
From the home page, click "Artifacts" on a project card. The viewer shows the project's `project.md` entry file as an index — Architecture, Design Docs, Implementation, Active Job Artifacts, Learnings. Click any item in the sidebar to read it.

### "I want to see what a job produced."
In the Artifacts viewer, the "Active Job Artifacts" section lists INTENT.md, PLAN.md, and WORK_ASSERT.md for running jobs. Each shows the job name. Click one to read it. A "View job conversation" link opens the job chat for context.

### "I want to see what the org has learned."
From the home page, click "Org Knowledge" in the org row. The Artifacts viewer opens with `organization.md` — institutional learnings, procedural skills, proxy knowledge, strategic decisions. This is the rolled-up organizational memory.

### "I want to review a specific file from a worktree."
Links within gate documents point to files in the worktree (changed source files, test output, etc.). Clicking a link opens that file in the viewer. The human never needs to know the worktree path — all navigation is through markdown links.

---

## Layout

**Sidebar navigator:**
- Project name as H1, entry file name as subtitle (`project.md` or `organization.md`)
- Sections from the entry file (Architecture, Design Docs, etc.)
- Items within each section, clickable

**Main pane:**
- When no item selected: project overview (index of all sections with summaries)
- When item selected: rendered markdown content, file path shown, "View job conversation" link for job artifacts

---

## Gate Review Integration

At approval gates, the chat page provides a direct link to the relevant artifact:

| Gate | Review Button | Opens |
|------|---------------|-------|
| INTENT_ASSERT | "Review INTENT" | `artifacts.html?project=ID&file=.sessions/JOB/INTENT.md` |
| PLAN_ASSERT | "Review PLAN" | `artifacts.html?project=ID&file=.sessions/JOB/PLAN.md` |
| WORK_ASSERT | "Review WORK" | `artifacts.html?project=ID&file=.sessions/JOB/WORK_ASSERT.md` |

All gate documents use the same progressive disclosure structure:
1. **Summary** — what was accomplished or proposed
2. **Details** — links to supporting content (research, task breakdowns, diffs)
3. **Links** — clickable paths to files in the worktree, rendered in the viewer

The human reads at whatever depth they need, then returns to the chat to approve, correct, or escalate.

---

## Entry Files

### project.md
Each project's consolidated memory and documentation index. Frontmatter describes the project (name, description, decider, lead). Body organizes links by section. This file is both machine-readable (agents read the frontmatter) and human-browsable (the Artifacts viewer renders it).

### organization.md
The org-level equivalent. Contains rolled-up institutional learnings, procedural skills (crystallized from successful work), proxy knowledge (behavioral patterns, rituals), and strategic decisions. Updated by the learning promotion chain.

---

## Controls

| Control | Action |
|---------|--------|
| Click sidebar item | Show artifact in main pane |
| Click "View job conversation" | Opens job chat (`chat.html?conv=JOB_ID`) |
| Click link within rendered markdown | Opens target file in the viewer |
