# Proxy & ACT-R Memory

Six escalations to the proxy during this session. All under `when_unsure` policy. The escalation skill picked between answering autonomously and consulting the human at each one. The breakdown:

| Conv id (suffix) | Caller's question | Human turns | Terminal | Mode |
|---|---|---|---|---|
| `13edd7d7…` | INTENT review | 0 | RESPONSE: "NOT APPROVED" | **Autonomous** |
| `5fe9f71d…` | revised INTENT review | 3 | RESPONSE: "NOT APPROVED. Two changes required." | Collaborative |
| `b348d13c…` | revised INTENT review | 2 | RESPONSE: "NOT APPROVED — two targeted revisions required." | Collaborative |
| `ac1ea7b0…` | INTENT ratification | 1 | RESPONSE: "Both revisions are confirmed on disk." | Collaborative |
| `27d47559…` | PLAN review | 1 | RESPONSE: "Approve the plan with one redirect." | Collaborative |
| `3cb9ff07…` | WORK ratification | 2 | RESPONSE: "Ratified — proceed to APPROVED_WORK." | Collaborative |

This is the [§7 escalation model](../../cfa-engineering.md#7-the-escalation-model) operating end to end: one molecule (`Proxy(t, x, π=when_unsure, h)`) per call, the proxy non-deterministically choosing between `[respond]` and `[escalate]`, every escalation eventually reaching `[respond]`.

---

## The autonomous escalation in detail

Of the six, the first one (INTENT review) is the cleanest demonstration of the autonomous path. The proxy ran a multi-step diligence pass without ever opening a dialog with the human:

1. Loaded the `escalation` skill with argument `when_unsure`.
2. Read `collaborate.md` (the per-policy escalation rail, since `when_unsure` routes there).
3. Walked the worktree (which is a clone of the caller's worktree, per [§7's "the proxy is a real agent"](../../cfa-engineering.md#7-the-escalation-model)).
4. Read `INTENT.md`, `IDEA.md`, `manuscript/architecture.md`, and the per-chapter research artifacts that the prior session left behind.
5. Read `proxy.md` — its own ACT-R memory bank.
6. Decided, verbatim: **"I'll respond from memory."**
7. Issued one `RESPONSE` JSON: "NOT APPROVED. Direct answers to your three questions..."

Zero dialog turns with the human. The decision to answer autonomously was the proxy's own — exercising the `when_unsure` policy's grant of judgment.

The proxy's reply was substantive: it identified that the INTENT under review "is not approvable as-is — it is missing the specific learnings from the prior attempt that was withdrawn at Pass 7 for executing the wrong intent." That specificity comes from the proxy having read both the current INTENT and the prior session's residual architecture artifacts. The §7 spec consequence — "an answer under `never` [or any policy where the proxy answers autonomously] is not a fiction; the proxy genuinely has the data and the memory to answer" — is observable here in the trace.

---

## ACT-R memory in active use

The project's proxy memory at `joke-book/proxy.md` accumulated across sessions:

- **17 ACT-R chunks** existed before this session (earliest: 2026-04-23, latest pre-session: 2026-05-01).
- Each chunk has structured frontmatter: `id`, `type` (procedural / institutional), `domain` (task / team), `importance` (0.5–0.95), `reinforcement_count`, `last_reinforced`.
- A representative chunk:

  ```
  ## [2026-04-23] Observation
  Category: Preferences
  Signal: "Don't over think this."
  Implication: When the human gives straightforward, direct instructions, execute
  them without unnecessary analysis, elaboration, or suggestions for complexity.
  Avoid over-design and premature consideration of edge cases or alternatives
  when the task is clear and simple.
  ```

This is the [Human Proxy system's](../../systems/human-proxy/index.md) ACT-R declarative memory adapted for gate decisions: structured chunks with activation-relevant metadata. The proxy reads these at every escalation as part of its diligence rail.

### The consolidation log

This session's worktree contains `.proxy-consolidation-log.jsonl` recording 45 consolidation decisions:

| Decision | Count | Meaning |
|---|---|---|
| ADD | 38 | New observation written as a fresh chunk |
| SKIP | 7 | Candidate observation merged into an existing chunk (or rejected) |

The consolidation pass runs over candidate observations from the session and decides, for each pair, whether to ADD a new chunk or SKIP (because an equivalent chunk exists, or the observation is below threshold). This is the [contradiction detection / consolidation pass](../../systems/learning/index.md#temporal-decay-and-retirement) that keeps the memory bank from drowning in duplicates.

38 new chunks added during one session is significant. The memory bank materially grew during this run — the proxy that runs the *next* session on this project starts from a richer memory than the proxy that started this one.

---

## Escalation as a structural primitive

The six escalations weren't ad-hoc. Each was triggered by an `AskQuestion` from the joke-book-lead during its skill execution:

- INTENT skill's ASSERT step (3 escalations to converge on approval, with revision rounds in between)
- PLAN skill's ASSERT step (1 escalation; approved with one redirect)
- EXECUTE skill's ASSERT step at end (2 escalations: one for an interim ratification, one for final WORK ratification)

The `Proxy(t, x, when_unsure, h)` molecule's behavior matched §7 across all six. Five of six routed through `[escalate]` at least once before terminating with `[respond]`. The autonomous case fired `[respond]` directly without ever entering `[escalate]`.

The consolidated answers from the human's dialog in collaborative escalations were not just relayed — they were rewritten into the proxy's voice with ACT-R-grounded context. From the WORK ratification (verbatim from the bus): *"Ratified — proceed to APPROVED_WORK and close. Darrell reviewed and signed off. Verbatim: 'it looks good.' Context on the ratification path: I walked the worktree, read Ch1 and Ch7 in full, sampled the reader-experience…"*

The proxy carried both the human's literal approval *and* its own grounded confirmation that the work matched what was being approved. That second half is the ACT-R memory and the worktree-clone diligence rail composed.
