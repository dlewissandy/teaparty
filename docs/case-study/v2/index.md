# v2 — Hierarchical Dispatch

!!! note "Live session"
    Project **joke-book**, session **20260502-055334-470510**, May 2, 2026.

The same four-sentence prompt that drove the [v1 run](../v1/index.md) — a book on the universal nature of humor — entered the orchestrator again two months later, on a project that had accumulated a memory bank, a skill candidate from a prior attempt, and an installed agent roster. Where v1 satisfied its INTENT end-to-end with the project lead carrying most of the substantive work, v2 is the dispatch-and-memory demonstration: 78 dispatches across a three-level tree, six proxy escalations exercising both modes from §7, and the May 1 attempt's plan consulted as material for May 2's plan.

> *I would like a book on the universal nature of humor. There are certain types of humor that transcend time, culture and language (e.g. comedy wildlife photos, physical humor, affiliative humor, etc). This is a 5-7 chapter book, targeting armchair enthusiasts, and should explore this phenomena across cultural, temporal, language, belief, and technological boundaries. Thesis: Humor is what unites us.*

The session ran ~10.5 hours wall-clock (05:53 → 16:34 UTC, May 2). It traversed the full CfA lifecycle (INTENT → PLAN → EXECUTE → DONE).

---

## What this run demonstrates

**[Hierarchical dispatch](dispatch.md).** The dispatch tree is real and three deep: the project lead delegated to 8 writing-leads and 10 editorial-leads; those leads in turn dispatched 13 markdown-writers, 23 voice-editors, 8 fact-checkers, 8 copy-editors, and 2 style-reviewers. 78 dispatches in total. Each child ran in its own git worktree with its own claude session, and the per-parent cap of 3 concurrent children from [§13](../../cfa-engineering.md#13-configuration-surface) is observable end-to-end in the timing data — wide fan-outs ran as serialized batches of 3.

**[Proxy with ACT-R memory](proxy-and-memory.md).** The project's proxy memory — `proxy.md`, 17 ACT-R chunks accumulated since April 23 — was actively consulted during this session. The consolidation log records 38 ADD and 7 SKIP decisions during the run, meaning 38 new memory entries were written and 7 candidate entries were merged into existing ones. This is the [memory layer from the human-proxy system](../../systems/human-proxy/index.md) operating in production.

**Both escalation modes from §7.** Six escalations to the proxy, all under `when_unsure` policy. One was answered autonomously: the proxy read the worktree, consulted `proxy.md`, said verbatim "I'll respond from memory.", and issued a clean RESPONSE without ever opening a human dialog. The other five involved 1–3 human turns before the proxy issued its consolidated response. Both modes from [the escalation model](../../cfa-engineering.md#7-the-escalation-model) demonstrated in one session.

**Skill-candidate reuse across runs.** The May 2 planning agent read `skill-candidates/job-20260501-053328-911918--i-would-like-a-book-on-the-uni.md` — the prior humor-book attempt's plan, captured as a skill candidate at the end of that run. May 2's PLAN.md is structurally adapted from May 1's: same phase structure, same deliverable shape, refined details. This is the planning skill's [SELECT/APPLY](../../cfa-engineering.md#4-the-skill-contract) path realized in practice — though the formal `.active-skill.json` artifact wasn't written this run, the consultation itself is on the bus and on disk.

**Multiple checkpoints and deliverables.** Phase 0 produced `manuscript/architecture.md` as an explicit pre-drafting checkpoint. Then five chapter drafts (`manuscript/ch{1..5}.md`), per-chapter research directories under `research/`, and a structural editorial pass (`editorial/architecture-coherence-review.md`). The editorial-leads ran six independent passes (style, fact, copy, voice × 3) and the proxy gated three CfA assert points.

---

## By the numbers

| Metric | Value |
|---|---|
| Wall-clock duration | ~10h 41m (05:53 → 16:34 UTC, May 2) |
| Dispatches (total) | 78 |
| Dispatch tree depth | 3 levels |
| Distinct agent types | 9 (joke-book-lead, writing-lead, editorial-lead, markdown-writer, voice-editor, fact-checker, copy-editor, style-reviewer, proxy) |
| Proxy escalations | 6 (1 autonomous, 5 collaborative) |
| ACT-R memory chunks (pre-existing) | 17 |
| Consolidation decisions during run | 45 (38 ADD, 7 SKIP) |
| Phase artifacts | architecture.md + 5 chapter drafts + editorial review + per-chapter research |
| Final state | DONE |

---

## CfA state machine trace

Read directly from the session log:

| Time (UTC) | Event |
|---|---|
| 05:53:34 | SESSION started — prompt accepted |
| 05:53:34 | INTENT phase started |
| 06:45:22 | INTENT phase completed |
| 06:45:22 | INTENT → PLAN |
| 06:45:35 | PLAN phase started |
| 06:58:50 | PLAN phase completed |
| 06:58:50 | PLAN → EXECUTE |
| 06:58:50 | EXECUTE phase started |
| 16:31:18 | EXECUTE phase completed |
| 16:31:18 | EXECUTE → DONE |
| 16:34:45 | SESSION completed — DONE |

Six proxy escalations fired during the lifecycle: at INTENT review, at PLAN review (multiple revision rounds), and at WORK ratification. Details in [Proxy & ACT-R](proxy-and-memory.md).

---

## Where to read next

- **[Dispatch Tree](dispatch.md)** — the complete dispatch interaction diagram with per-agent counts, plus a spotlight on parallel fan-out under one editorial-lead.
- **[Proxy & ACT-R Memory](proxy-and-memory.md)** — the six escalations broken down by mode, what the proxy read at each one, and the consolidation log from this run.
- **[Artifacts](results.md)** — every file the session produced, organized by phase: planning, architecture, research, manuscript drafts, editorial review, and the proxy's memory bank.
- **[Takeaways](takeaways.md)** — what v2 closes that v1 left open, and what's still open.
