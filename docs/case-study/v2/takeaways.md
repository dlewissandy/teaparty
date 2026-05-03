# Takeaways

What v2 closes that v1 left open, and what the two runs together say about the four research pillars.

---

## What v2 closes

**Hierarchical Teams — now demonstrated.** v1's [scope statement](../v1/index.md#scope-of-what-this-session-demonstrates) was honest that hierarchical dispatch was *not* cleanly demonstrated: "the substantive work for each phase was driven primarily by the project lead rather than by independent sub-agents running their own CfA cycles in isolated worktrees." v2 closes this. 78 dispatches across a three-level tree, with concrete worktrees and concrete claude sessions per child. The dispatch model from [§6 of the engineering spec](../../cfa-engineering.md#6-the-dispatch-model) is observable on the bus.

**Proxy with structured memory — now demonstrated.** v1 showed the proxy participating at gates and producing revision notes. v2 shows the structured ACT-R memory underneath: 17 chunks accumulated across prior sessions, 38 new chunks written during this run, the proxy reading `proxy.md` directly during escalation diligence. The [Human Proxy system's](../../systems/human-proxy/index.md) declarative memory layer is operating in production.

**Both escalation modes — now demonstrated.** v1's escalations were predominantly approve-on-behalf, with the proxy acting under modest confidence. v2 shows the full spread: one autonomous response (proxy answered from memory + worktree diligence, zero human turns) and five collaborative responses (1–3 human turns each). Both modes from [§7](../../cfa-engineering.md#7-the-escalation-model) demonstrated within one session under one policy (`when_unsure`).

**Cross-run knowledge reuse — now demonstrated.** v1 was a from-scratch run. v2 read May 1's prior humor-book attempt as a `skill-candidates/*.md` file during the planning phase. The May 2 PLAN.md is structurally adapted from May 1's. Knowledge persists across runs and is consulted when relevant — the [planning skill's SELECT/APPLY path](../../cfa-engineering.md#4-the-skill-contract) materialized in a real session.

---

## What's next

**Skill promotion.** The May 2 planner consulted the May 1 humor-book attempt as a skill candidate during DRAFT — that consultation is logged on the bus and visible in the planning agent's stream. What's missing today is the mechanism to *promote* a candidate file into a registered skill. Once that mechanism lands (scheduled for the next milestone), future planners can hit the SELECT/APPLY path against a registered skill and write `.active-skill.json` formally — turning today's read-during-DRAFT into tomorrow's structured skill reuse with a contract artifact.

---

## v1 vs v2 — what each is for

| Question you'd ask the case study | Read |
|---|---|
| "Does the system satisfy the intent end-to-end?" | [v1](../v1/index.md) — INTENT.md → PLAN.md → manuscript with editorial and verification passes; proxy ratified each gate. |
| "Does the dispatch hierarchy actually work?" | [v2](dispatch.md) — 78 dispatches, 3 levels deep, 9 distinct agent types. |
| "Does the proxy's memory do anything?" | [v2](proxy-and-memory.md) — 17 inherited chunks consulted, 38 new chunks written, autonomous response trace. |
| "What does an escalation look like under each policy mode?" | [v2](proxy-and-memory.md) — 6 escalations under `when_unsure`, with one autonomous and five collaborative. |
| "Do skills carry knowledge across runs?" | v2 — May 1's plan was consulted by May 2's planner. (Promotion mechanism scheduled for the next milestone — see "What's next" above.) |

The two runs together cover the four pillars. v1 carries the end-to-end intent-satisfaction story (CfA + Proxy + single-session Learning); v2 carries the architectural story (Hierarchical Teams + Proxy memory + cross-run skill reuse).

Neither run is a controlled ablation. The case the documentation makes is *demonstration*, not measurement. The [planned validation](../../experimental-results/index.md) section is where the ablative measurement work lives.
