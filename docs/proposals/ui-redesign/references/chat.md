[UI Redesign](../proposal.md) >

# Chat Page

The primary human interaction surface. Async, bidirectional, multi-channel messaging. One browser tab per conversation.

Mockup: [mockup/chat.html](../mockup/chat.html)

---

## Two Variants

The same page (`chat.html`) renders two different layouts depending on the conversation type. The difference is in the sidebar navigator.

### Job Chat (`chat.html?conv=JOB_ID`)

For job-scoped work. The sidebar lists **tasks** within the job.

**User stories:**
- "I want to see what the team is doing on this job." → The job conversation shows messages from the Project Lead, developers, and proxy. Task sub-conversations show individual agent work.
- "A task has an escalation." → Red dot on the task in the sidebar. Click to see the agent's question. Type a response.
- "I want to interject mid-work." → Select the task conversation, type into it. The agent picks up the interjection from the message bus on its next poll.
- "I want to review the gate artifact." → Green "Review INTENT/PLAN/WORK" button in the header. Opens the [Artifacts viewer](artifacts.md) with the relevant document.
- "I want to cancel this job." → Red "Withdraw" button in the header. Confirmation modal: "This will cancel the job and all running tasks. Completed work will be preserved in the worktree but not merged." Cancel or Withdraw.

**Deep linking:** `chat.html?conv=job:poc:job-001&task=t2` opens the job chat with task t2 selected in the sidebar. Used by escalation clicks on the home page.

**Sidebar contents:**
- "Job conversation" entry (the main thread with the project lead)
- One entry per task, showing task name (truncated) and red dot if escalation pending
- Selected entry highlighted in green

**Header:**
- Participant name and scope
- "Review" button (green, only shown at gates — INTENT_ASSERT, PLAN_ASSERT, WORK_ASSERT)
- "Withdraw" button (red, always shown)

### Participant Chat (`chat.html?conv=om:darrell`)

For 1:1 conversations with a specific participant. The sidebar lists **conversation history** with that participant.

**User stories:**
- "I want to talk to the office manager about restructuring." → Click Office Manager on the home page. Chat opens showing past sessions in the sidebar. Click "+ New" or just start typing.
- "I want to review what I discussed with the proxy last week." → Open proxy chat. Sidebar shows sessions by date. Click the older session.
- "I want to give the proxy job-specific instructions." → From the job board on the home page, click the proxy participant. Chat opens with that job as the conversational context — the proxy is the same global agent, but the conversation is framed around the current work.

**Sidebar contents:**
- "CONVERSATIONS" header
- One entry per historical session, showing label and date
- Most recent session selected by default

**Header:**
- Participant name
- Session label as scope

---

## Markdown Rendering

Chat messages render as markdown because agents naturally produce it. This enables:

- **Rich text** — bold, italic, lists, headings, blockquotes for structured responses
- **Links to files** — `[retrieval.py](projects/POC/orchestrator/retrieval.py)` becomes a clickable link. In the production build, clicking opens the file in the Artifacts viewer.
- **Code blocks** — syntax-highlighted code in agent responses
- **Images** — agents can reference generated diagrams or screenshots
- **Tables** — structured data (status summaries, comparison matrices)

The human's input is also rendered as markdown, so they can use formatting when writing detailed responses.

---

## Message Filters

Toggleable buttons above the message stream control what's visible:

| Filter | Default | Content |
|--------|---------|---------|
| agent | ON | Agent response text |
| human | ON | Human messages |
| thinking | OFF | Agent reasoning/chain-of-thought |
| tools | OFF | Tool use calls |
| system | OFF | Session init, config, state transitions |

Filters let the human focus on the conversation without noise from tool calls and system events, but can turn them on when debugging or understanding what an agent did.

---

## Input

**Multiline textarea** — not a single-line input.
- Enter sends the message
- Shift+Enter inserts a newline
- Auto-grows up to 10 rows, then shows a scrollbar
- Human input is rendered as markdown (so formatting is preserved)

---

## Real-Time Updates

The chat page subscribes to the bridge's WebSocket. When new messages arrive for the current conversation, they appear immediately without polling. The sidebar updates escalation indicators in real time.

If the human has multiple chat tabs open (e.g., one per active job), each tab receives only the messages for its conversation. Filtering is client-side.

---

## Controls

| Control | Action |
|---------|--------|
| Click sidebar entry | Switch to that task/session conversation |
| Click "Review" button | Opens Artifacts viewer with gate document |
| Click "Withdraw" button | Opens confirmation modal |
| Confirm withdrawal | Posts withdrawal to bridge API, system message appears in chat |
| Toggle filter button | Show/hide that message type |
| Enter in textarea | Send message to conversation via bridge API |
| Shift+Enter in textarea | Insert newline |
| Click link in rendered markdown | Opens target (file in Artifacts viewer, or external URL) |
