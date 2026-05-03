# Dispatch Tree

The May 2 session put 78 dispatches on the bus. Counted from the conversation table:

| Agent role | Count | Parent role |
|---|---|---|
| joke-book-lead | 1 | (top of tree, child of human chat) |
| writing-lead | 8 | joke-book-lead |
| editorial-lead | 10 | joke-book-lead |
| proxy | 6 | joke-book-lead (escalation threads) |
| markdown-writer | 13 | writing-lead (1–3 per parent) |
| voice-editor | 23 | editorial-lead (across 3 voice passes) |
| fact-checker | 8 | editorial-lead (one parallel fact-check pass) |
| copy-editor | 8 | editorial-lead (across copy passes) |
| style-reviewer | 2 | editorial-lead |

Three levels deep, every child gets its own `dispatch:<id>` thread, its own git worktree, its own claude session.

Below: three UML sequence diagrams. The first compresses the whole session into the major message-passing patterns. The next two zoom into specific windows where the **per-parent cap of 3 concurrent children** ([§13](../../cfa-engineering.md#13-configuration-surface)) is observable in the timing data.

---

## Diagram 1 — Macro session flow

The whole-session flow with one representative child per role. Reads top-to-bottom in time.

```mermaid
sequenceDiagram
    autonumber
    participant H as Human
    participant L as joke-book-lead
    participant P as proxy
    participant W as writing-lead
    participant M as markdown-writer
    participant E as editorial-lead
    participant S as specialists

    H ->> L: chat (prompt)

    Note over L,P: INTENT phase — 4 escalations
    L ->>+ P: AskQuestion (INTENT review)
    P -->>- L: RESPONSE NOT APPROVED (autonomous, 0 human turns)
    L ->>+ P: AskQuestion (revised INTENT)
    P ->> H: dialog
    H -->> P: reply
    P -->>- L: RESPONSE NOT APPROVED (2 changes required)
    L ->>+ P: AskQuestion (re-revised)
    P ->> H: dialog
    H -->> P: reply
    P -->>- L: RESPONSE NOT APPROVED (2 targeted revisions)
    L ->>+ P: AskQuestion (ratify)
    P ->> H: dialog
    H -->> P: reply
    P -->>- L: RESPONSE APPROVED

    Note over L,P: PLAN phase
    L ->>+ P: AskQuestion (PLAN review)
    P ->> H: dialog
    H -->> P: reply
    P -->>- L: RESPONSE APPROVE with redirect

    Note over L,S: EXECUTE phase — writing (8 writing-leads, 13 markdown-writers)
    L ->>+ W: Delegate (Ch1 anchor)
    W ->>+ M: Send (markdown)
    M -->>- W: Reply
    W -->>- L: Reply
    L ->>+ W: Delegate (Ch2..7 in batches of 3)
    W ->>+ M: Send (markdown)
    M -->>- W: Reply
    W -->>- L: Reply

    Note over L,S: EXECUTE phase — editorial (10 editorial-leads)
    L ->>+ E: Delegate (structural / fact / flow / voice / copy pass)
    E ->>+ S: Send (specialists, in batches of 3)
    S -->>- E: Reply
    E -->>- L: Reply

    Note over L,P: WORK ratification
    L ->>+ P: AskQuestion (WORK ratify)
    P ->> H: dialog
    H -->> P: reply
    P -->>- L: RESPONSE Ratified

    L -->> H: DONE
```

The shaded blocks group the CfA phases. AskQuestion calls flow to the proxy; some terminate autonomously (the first one), the rest go through human dialog before the proxy's RESPONSE returns to the caller. Delegate calls open dispatch threads to workgroup-leads; Send calls fan out from the workgroup-leads to specialists. Reply edges go back up the same channel — the thread is bidirectional.

---

## Diagram 2 — Writing-phase concurrency, joke-book-lead's view

**Eight writing-leads dispatched, never more than three concurrent.** Times below are seconds from session start (t=0 = 05:53:34 UTC).

```mermaid
sequenceDiagram
    autonumber
    participant L as joke-book-lead
    participant W1 as writing-lead<br/>:7a51 (Ch1 anchor)
    participant W2 as writing-lead<br/>:130e
    participant W3 as writing-lead<br/>:1d7d
    participant W4 as writing-lead<br/>:908a
    participant W5 as writing-lead<br/>:283d
    participant W6 as writing-lead<br/>:07d3
    participant W7 as writing-lead<br/>:d5c7
    participant W8 as writing-lead<br/>:e2b8

    Note over L: t=0 — Ch1 anchor first<br/>(serialized, voice probe)
    L ->>+ W1: Delegate (Ch1)
    W1 -->>- L: Reply (t=2623)

    Note over L,W4: t=2805–5136 — first fan-out batch (max 3 concurrent)
    L ->>+ W2: Delegate (t=2805)
    L ->>+ W3: Delegate (t=2859)
    L ->>+ W4: Delegate (t=2920)
    Note over L,W4: 3 active children
    W3 -->>- L: Reply (t=4803)
    W2 -->>- L: Reply (t=4868)
    W4 -->>- L: Reply (t=5136)

    Note over L,W7: t=5243–7023 — second fan-out batch (max 3 concurrent)
    L ->>+ W5: Delegate (t=5243)
    L ->>+ W6: Delegate (t=5421)
    L ->>+ W7: Delegate (t=5497)
    Note over L,W7: 3 active children — cap hit, no 4th opens
    W5 -->>- L: Reply (t=6928)
    W7 -->>- L: Reply (t=7023)
    W6 -->>- L: Reply (t=8369)

    Note over L,W8: t=25160 — late drafting pass after editorials
    L ->>+ W8: Delegate (t=25160)
    W8 -->>- L: Reply (t=26282)
```

Reading: the lead opened the Ch1 anchor first (sequential — Ch1 is the voice probe per the plan), then opened the next three Delegate threads in a 115-second burst (W2 → W3 → W4), waited for them all to settle, opened the next three (W5 → W6 → W7), waited again, then a single late W8. **At no point did the joke-book-lead have more than three writing-lead children active simultaneously.** The cap from §13 is observable in the activation pattern.

---

## Diagram 3 — Voice-pass fan-out, editorial-lead's view

**The same cap holds at the editorial-lead level.** This editorial-lead (`dispatch:44aba47d9149`, voice pass) dispatched 8 voice-editors. They ran in **three batches: 3, 3, 2.**

```mermaid
sequenceDiagram
    autonumber
    participant E as editorial-lead<br/>:44ab (voice pass)
    participant V1 as voice-editor<br/>:25ef
    participant V2 as voice-editor<br/>:bc67
    participant V3 as voice-editor<br/>:b005
    participant V4 as voice-editor<br/>:e778
    participant V5 as voice-editor<br/>:9b4d
    participant V6 as voice-editor<br/>:f0cc
    participant V7 as voice-editor<br/>:1866
    participant V8 as voice-editor<br/>:8099

    Note over E,V3: Batch 1 — t=16880–17416 (3 active)
    E ->>+ V1: Send (chapter)
    E ->>+ V2: Send (chapter)
    E ->>+ V3: Send (chapter)
    V3 -->>- E: Reply (t=17214)
    V2 -->>- E: Reply (t=17344)
    V1 -->>- E: Reply (t=17416)

    Note over E,V6: Batch 2 — t=17462–17964 (3 active)
    E ->>+ V4: Send
    E ->>+ V5: Send
    E ->>+ V6: Send
    V6 -->>- E: Reply (t=17719)
    V4 -->>- E: Reply (t=17876)
    V5 -->>- E: Reply (t=17964)

    Note over E,V8: Batch 3 — t=18027–18413 (2 active)
    E ->>+ V7: Send
    E ->>+ V8: Send
    V7 -->>- E: Reply (t=18387)
    V8 -->>- E: Reply (t=18413)
```

The pattern repeats across all three voice passes (3+3+2, 3+3+1, 3+3+2 = 23 voice-editors total). The fact-check pass at `dispatch:2404788a7008` showed the same shape — 8 fact-checkers in 3+3+2 batches.

The per-parent cap of 3 from §13 is enforced everywhere — at the project-lead level (writing-leads, editorial-leads) and at the workgroup-lead level (voice-editors, fact-checkers). A fan-out target of 8 reduces to three batches of (3, 3, 2); the concurrent count never exceeds 3. This is the close-before-spark-more discipline from [§13](../../cfa-engineering.md#13-configuration-surface).

---

## Closure is the lead's discretion

Two writing-leads (`283d258761f4`, `d5c742adab3d`) remained `active` on the bus when the session reached `DONE`. That's not a defect: closing a dispatch conversation is optional in CfA — the lead can close (which merges immediately) or leave the conversation open and rely on end-of-phase merge. Both writing-leads' work landed in the parent's worktree the same way through end-of-phase. 70 of 72 dispatches were explicitly closed; the other 2 were merged-without-close at phase boundary.
