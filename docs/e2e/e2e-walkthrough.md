# End-to-End Walkthrough

!!! note "Live session"
    Project **humor-book**, session **20260315-171017**, March 15–16, 2026.

A single natural-language prompt — four sentences about humor, universality, and armchair enthusiasts — entered the TeaParty orchestrator and emerged as a ~55,000-word manuscript: a prologue, seven chapters, two independent editorial reports, two verification reports, and five title alternatives.

> *I would like a book on the universal nature of humor. There are certain types of humor that transcend time, culture and language (e.g. comedy wildlife photos, physical humor, affiliative humor, etc). This is a 5-7 chapter book, targeting armchair enthusiasts, and should explore this phenomena across cultural, temporal, language, belief, and technological boundaries. Thesis: Humor is what unites us.*

The system executed the full CfA lifecycle autonomously: intent capture (2 questions, 5 minutes), planning (4 questions, 16 minutes), and five phases of hierarchical dispatch — research, specification, production, editorial, and verification — with the human proxy handling all sub-team approval gates.

---

## User Experience

The entire interaction — from the initial prompt through intent capture, planning, and all five execution phases — occurred within the TeaParty interactive console. The human typed the four-sentence prompt, answered six questions across two brief dialogs, and then watched.

![TUI workspace showing eight parallel research dispatches running](e2e-raw-files/e2e workspace.png)

This is the TUI during the research phase. The top pane shows the original prompt and the CfA state history — each transition from IDEA through PLAN visible as it happened. The middle pane streams the uber team's execution in real time: dispatching research tracks into worktrees, confirming proxy approvals at sub-team gates, advancing phases as deliverables land on disk. The status bar at the bottom shows eight active dispatches running concurrently.

From the human's side, the experience after the initial dialog was: watch the stream and review artifacts as they arrived. The console didn't just show progress — it provided direct links to the generated artifacts in their worktrees, making it easy to open a research brief, read a chapter draft, or inspect an editorial report without hunting through the file system. At approval gates, the human could click through to the relevant artifacts, review them, and approve or correct — all without leaving the console.

There was no context-switching between tools, no manual file management, no copy-paste between agents. The orchestrator handled phase transitions, worktree creation, artifact routing, and quality gates autonomously. The human's role reduced to the six consequential decisions at the start and a handful of gate approvals at the end.

---

## The Story in Five Parts

**[Intent & Planning](dialog.md)** — Two agents, six questions, 21 minutes. The dialog transcripts show how a four-sentence prompt became a complete intent document and a five-phase execution plan — with the agents bringing proposals, not open-ended questions.

**[Execution](execution.md)** — Eight parallel research tracks, eight spec agents, seven chapter drafts, two editorial passes, two verification passes — all dispatched hierarchically into isolated worktrees. How the uber team coordinated five phases without becoming a bottleneck.

**[The Manuscript](results.md)** — What the session actually produced: a complete popular non-fiction book with links to every chapter draft, from initial to final.

**[Obstacles](obstacles.md)** — Watchdog timeouts, token limits, rate-limit collisions, a prologue that refused to persist, and agents that couldn't figure out where they were in the worktree hierarchy. What went wrong and how the system adapted.

**[Learnings](learnings.md)** — The learning system's self-assessment: alignment observations, the proxy confidence model, and the "frustration misinterpretation" where the proxy read timeouts as human annoyance.

**[Key Takeaways](takeaways.md)** — What the session demonstrates about the four pillars, where the opportunities lie, and the overall assessment.

---

## By the Numbers

| Metric | Value |
|--------|-------|
| Prompt length | 4 sentences |
| Human dialog turns | 6 (intent) + 4 (planning) + ~6 gate approvals |
| Phases executed | 5 (Research → Spec → Production → Editorial → Verification) |
| Parallel dispatches per phase | 8 |
| Total artifacts produced | 8 briefs, 8 specs, 8 drafts, 2 editorial reports, 2 verification reports, 5 title alternatives |
| Total manuscript length | ~55,000 words |
| Session restarts required | Multiple (watchdog timeouts + token limits) |

---

## CfA State Machine Trace

| Time (UTC) | State | Action | Actor |
|---|---|---|---|
| 00:10:17 | IDEA | propose | human |
| 00:14:56 | PROPOSAL | assert | intent_team |
| 00:15:54 | INTENT_ASSERT | approve | proxy |
| 00:15:59 | INTENT | plan | planning_team |
| 00:29:27 | DRAFT | assert | planning_team |
| 00:31:51 | PLAN_ASSERT | approve | proxy |
| 00:31:51 | PLAN | delegate | uber_team |
| 00:32–05:35 | TASK | execute | uber_team (5 phases) |
| 05:35:21 | TASK_ASSERT | correct | proxy (3 revision notes) |
| 05:40–05:56 | TASK_ASSERT | correct ×6 | proxy (confirmation loop) |
| 05:56:10 | TASK_ASSERT | approve | proxy |
| 13:16:34 | WORK_ASSERT | approve | proxy |
