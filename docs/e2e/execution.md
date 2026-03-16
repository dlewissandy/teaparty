# Execution

With the plan approved, the state machine transitioned to PLAN → TASK via `delegate`, triggering hierarchical dispatch. The uber team decomposed Phase 1 (Research) into eight parallel research tracks — one per chapter including the prologue — and dispatched each to its own worktree.

---

## How Dispatches Worked

Each research dispatch:

- Created an isolated git worktree for its work
- Ran its own CfA cycle (intent → plan → execute) within that worktree
- Used the proxy for all assert gates (`never_escalate=True`) — no human involvement
- Received a scoped task brief from the uber team (context compression at the hierarchy boundary)

The screenshot below shows the TUI workspace during the execution phase. The top pane displays the original prompt and the session's CfA state history. The middle pane shows the uber team dispatching eight parallel research tracks. The status bar at the bottom shows the session in the TASK state with eight active dispatches.

![TUI workspace showing eight parallel research dispatches running](../e2e-raw-files/e2e workspace.png)

---

## Phase 1: Research

| Dispatch | Chapter | Brief | Task |
|---|---|---|---|
| 20260315-173223 | Prologue | [prologue_brief.md](../e2e-raw-files/research/prologue_brief.md) | Cognitive mechanisms, cross-cultural examples, opening joke candidates |
| 20260315-173232 | Ch 1: Born Laughing | [ch1_brief.md](../e2e-raw-files/research/ch1_brief.md) | Biology of laughter, infant laughter, Panksepp rat experiments |
| 20260315-173240 | Ch 2: The Oldest Joke | [ch2_brief.md](../e2e-raw-files/research/ch2_brief.md) | Archaeology of humor, Sumerian to Roman |
| 20260315-173257 | Ch 3: Banana Peels and Power | [ch3_brief.md](../e2e-raw-files/research/ch3_brief.md) | Slapstick, status reversal |
| 20260315-173303 | Ch 4: You Had to Be There | [ch4_brief.md](../e2e-raw-files/research/ch4_brief.md) | Affiliative humor, in-group bonding |
| 20260315-173318 | Ch 5: The Last Laugh | [ch5_brief.md](../e2e-raw-files/research/ch5_brief.md) | Gallows humor, comedy from disaster |
| 20260315-173351 | Ch 6: Silence Is Funny | [ch6_brief.md](../e2e-raw-files/research/ch6_brief.md) | Visual humor, wordless comedy |
| 20260315-173433 | Ch 7: Spam Spam Spam | [ch7_brief.md](../e2e-raw-files/research/ch7_brief.md) | Absurdism, nonsense traditions |

Each track delivered a brief with the structure defined in the plan: key mechanism, 8–12 sourced examples (with cultural/temporal spread noted), a proposed throughline argument, and a flagged counterexample. The [Ch1 brief](../e2e-raw-files/research/ch1_brief.md) is representative — it runs to 360 lines and includes:

- The two-pathway model of laughter (Wild et al., 2003) — involuntary laughter routing through ancient subcortical structures, voluntary laughter through the motor cortex
- 12 sourced examples spanning Panksepp's rats (1990s–2003), Darwin's baby diary (1839), the Yanomami five-month genealogical joke (1964), Davila Ross's ape-laughter phylogeny (2009), and the 2023 cross-species PAG confirmation
- Confidence flags on every citation (HIGH/MEDIUM/LOW) with a verification table for claims needing primary-source confirmation
- A dedicated counterexample cluster: Barrett's constructed emotion theory, Aristophanes' *The Clouds*, flyting, the *Philogelos* scholastikos jokes
- Three proposed narrative hooks, ranked by opening impact

All eight briefs were delivered to disk. The prologue brief was the most unreliable — it failed to persist across multiple dispatch attempts (see [Obstacles](obstacles.md)) — but was eventually completed.

---

## Phases 2–5

The uber team advanced through the remaining phases with the same parallel-dispatch pattern:

**Phase 2 (Specification):** Eight spec agents, one per chapter, each reading all research briefs and producing a per-chapter spec with throughline argument, opening hook, narrative arc, counterexample placement, and register notes. Title alternatives developed in parallel.

**Phase 3 (Production):** Seven chapter drafts plus prologue produced in parallel. Ch7 was sequenced last within its track so its synthesis could reference the other six drafts.

**Phase 4 (Editorial):** Two independent editorial reports produced — each reading the full manuscript as a single document and auditing voice consistency, thesis coherence, boundary coverage, and per-chapter invariants.

**Phase 5 (Verification):** Two independent verification reports auditing the manuscript against every success criterion in INTENT.md, every invariant in PLAN.md, and additional criteria (no thesis-statement openings, emotional landing in Ch7, Camus substitution).
