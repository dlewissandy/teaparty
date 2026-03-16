# End-to-End Walkthrough

!!! note "Live session"
    Project **humor-book**, session **20260315-171017**, March 15–16, 2026.

A single natural-language prompt — four sentences about humor, universality, and armchair enthusiasts — entered the TeaParty orchestrator and emerged as a ~55,000-word manuscript: a prologue, seven chapters, two independent editorial reports, two verification reports, and five title alternatives.

> *I would like a book on the universal nature of humor. There are certain types of humor that transcend time, culture and language (e.g. comedy wildlife photos, physical humor, affiliative humor, etc). This is a 5-7 chapter book, targeting armchair enthusiasts, and should explore this phenomena across cultural, temporal, language, belief, and technological boundaries. Thesis: Humor is what unites us.*

The system executed the full CfA lifecycle autonomously: intent capture (2 questions, 5 minutes), planning (4 questions, 16 minutes), and five phases of hierarchical dispatch — research, specification, production, editorial, and verification — with the human proxy handling all sub-team approval gates.

![TUI workspace showing eight parallel research dispatches running](e2e-raw-files/e2e workspace.png)

This is the TUI during the research phase — the human's only view of the session while it runs. The top pane shows the original prompt and the CfA state history. The middle pane streams the uber team's execution: dispatching research tracks, confirming proxy approvals, advancing phases. The status bar at the bottom shows eight active dispatches. From the human's side, the experience after the initial six dialog turns was: watch the stream, wait, and review the final manuscript when the session completed.

---

## The Story in Five Parts

**[Intent & Planning](e2e/dialog.md)** — Two agents, six questions, 21 minutes. The dialog transcripts show how a four-sentence prompt became a complete intent document and a five-phase execution plan — with the agents bringing proposals, not open-ended questions.

**[Execution](e2e/execution.md)** — Eight parallel research tracks, eight spec agents, seven chapter drafts, two editorial passes, two verification passes — all dispatched hierarchically into isolated worktrees. How the uber team coordinated five phases without becoming a bottleneck.

**[The Manuscript](e2e/results.md)** — What the session actually produced: a complete popular non-fiction book with links to every chapter draft, from initial to final.

**[Obstacles](e2e/obstacles.md)** — Watchdog timeouts, token limits, rate-limit collisions, a prologue that refused to persist, and agents that couldn't figure out where they were in the worktree hierarchy. What went wrong and how the system adapted.

**[Learnings](e2e/learnings.md)** — The learning system's self-assessment: alignment observations, the proxy confidence model, and the "frustration misinterpretation" where the proxy read timeouts as human annoyance.

**[Key Takeaways](e2e/takeaways.md)** — What the session demonstrates about the four pillars, where the opportunities lie, and the overall assessment.

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
