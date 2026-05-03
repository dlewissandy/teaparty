# Case Study

Two end-to-end runs on the *humor book* prompt, two months apart. Same four-sentence input. Different demonstrations.

| Run | When | Demonstrates | Pages |
|---|---|---|---|
| **[v2 — Hierarchical Dispatch](v2/index.md)** | May 2026 | Multi-level dispatch tree (78 dispatches across 3 levels), ACT-R memory in active use, both escalation modes from §7, skill-candidate reuse from a prior run | [Overview](v2/index.md) · [Dispatch Tree](v2/dispatch.md) · [Proxy & ACT-R](v2/proxy-and-memory.md) · [Artifacts](v2/results.md) · [Takeaways](v2/takeaways.md) |
| **[v1 — End-to-End Manuscript](v1/index.md)** | March 2026 | The CfA state machine driving Intent → Planning → Execution end-to-end, proxy participation at gates, a complete 55,000-word manuscript | [Overview](v1/index.md) · [Intent & Planning](v1/dialog.md) · [Execution](v1/execution.md) · [Manuscript](v1/results.md) · [Obstacles](v1/obstacles.md) · [Learnings](v1/learnings.md) · [Takeaways](v1/takeaways.md) |

**Why two.** v1 was the first end-to-end run that produced a real manuscript. Its [scope statement](v1/index.md#scope-of-what-this-session-demonstrates) was honest about what it did *not* cleanly demonstrate — most prominently the Hierarchical Teams pillar, where execution was driven primarily by the project lead rather than by independent sub-agents running their own CfA cycles in isolated worktrees. v2, run two months later on the same prompt, closes that gap: 78 dispatches across a 3-level tree, with concrete evidence of memory, skill reuse, and both escalation modes. v1 is preserved as the end-to-end intent-satisfaction baseline; v2 is where the architectural claims now ground.

**What's the same.** Same prompt (a four-sentence ask for a book on universal humor), same project lead role, same proxy concept, same CfA state machine. The protocol didn't change between runs.

**What's different.** What the system did *with* that protocol. v2's run is the one to read for evidence of the four pillars composed.
