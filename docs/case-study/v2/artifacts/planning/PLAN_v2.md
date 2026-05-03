# PLAN

A working plan to produce the manuscript described in `INTENT.md`. Every section serves a constraint or success criterion already named in the intent — this document does not introduce new goals.

## Decisions to confirm

The intent leaves a small set of choices to the team. The plan below assumes them; the human can redirect any of them as part of approving the plan.

1. **Era spine for Ch2–5 is media-driven, not century-driven.**
   - Ch2: Oral / pre-text antiquity (through ~500 CE)
   - Ch3: Manuscript era (~500–1500)
   - Ch4: Print era (~1500–1900)
   - Ch5: Broadcast era (~1900–2000)
   - Ch6: Algorithmic / information age (intent-pinned)
   Rationale: the intent names *technological* as one of the five boundaries the case slate must cross, and the universality claim is most demonstrable when each chapter's medium constrains what comedy can survive. A pratfall surviving oral → manuscript → print → broadcast → algorithm is the book's central trick; a century-driven split (ancient/medieval/early-modern/modern) loses that leverage.

2. **Drafting cadence is parallel — Ch1 first as the voice anchor, then Ch2–Ch7 drafted concurrently.** Calendar pressure makes parallelism the working choice. Voice drift, case overlap, and asynchronous callback planting are the known costs of parallelism; they are managed by the disciplines named in Phase 1 below (voice anchor before parallel commit, mid-flight voice spot-checks, case-slate-as-lock, callback contract). Voice drift is treated as the dominant Phase-2 risk and the editorial passes are designed against it.

3. **Voice is calibrated on Ch1 before Ch2–7 commit.** The David Shapiro × Mary Roach target is specific enough to miss. A voice probe is fixed in Phase 0 against named source passages; Ch1 drafts first to tune it in the working manuscript; *only after the tuned probe is in* do Ch2–7 launch in parallel, each calibrating against the tuned probe.

4. **Editorial-pass order (after full draft):** Structural → Fact / intellectual honesty → Flow → Reader-experience audit → Line edit / voice → AI-smell → Final copyedit. Rationale: load-bearing changes first (structure, then truth), then how-it-moves (flow), then the airport-reader sanity check while injecting humor is still cheap (reader-experience), then sentence-level polish (line edit, AI-smell), then mechanical (copyedit). All seven INTENT-specified passes are present, run as distinct goals, in this order.

## Phase 0 — Architecture

**Deliverable:** `manuscript/architecture.md`. One document that fixes the load-bearing decisions before any chapter is drafted. Backed by `research/architecture/case-slate.md` and `research/architecture/counterexample-slate.md` — the source-of-truth documents the architecture references.

Contents (one section per item):

- **Thesis arc.** A paragraph per chapter naming what each chapter contributes to the argument *that the previous chapter could not*. Ch7 is included — its job is to stress-test, not to summarize. Argument escalates; chapters do not run in parallel.
- **Era spine.** The five era chapters (2–6) with date ranges, and a one-line statement of what each era's medium makes possible or constrains for comedy.
- **Case slate.** Source-of-truth in `research/architecture/case-slate.md`. Per chapter: 4 primary cases plus 1 backup. Each entry: the case, what it demonstrates, primary or scholarly source, and which boundary axes (cultural, temporal, linguistic, belief, technological) it crosses. This is the master list the no-synthetic-anecdotes hard stop is checked against. A case is *eligible* only when at least one named primary or scholarly source is on file. **Non-Western coverage is required across the slate as a whole** (intent-level requirement, not stylistic) — the slate documents which traditions are cleared.
- **Callback design.** 3–5 callbacks the manuscript is engineered around — recurring comic moves or characters that plant in early chapters and fire later. Each callback: source case, intermediate plants if any, return point, and the recognition shock the reader is meant to feel at the return.
- **Impact moments.** 3–5 designed set-pieces (per intent), located by chapter and approximate position. Each entry: scene, why it lands, what it earns for the argument. These are the moments the manuscript is engineered around — connective prose connects them.
- **Counterexample slate (Ch7).** Source-of-truth in `research/architecture/counterexample-slate.md`. The divisive-humor cases, linguistic/cultural-lock cases, belief-line cases, and medium-locked cases the chapter commits to engaging. Each case labeled *holds* / *qualifies* / *breaks locally* relative to the thesis. Same source-vetting rule as the primary slate. Includes the Ch7 resolution path (the order in which counterexamples are walked and how the chapter lands).
- **Voice probe.** Two paragraphs of sample prose at the David Shapiro × Mary Roach target — drawn from a real Phase-0 case so it doubles as scaffolding for Ch1. Annotated to show all five voice moves named in INTENT (observational comparison, dry precision, deadpan understatement, callbacks across chapters, surprise via specificity). The probe is the calibration object for Ch1 drafting and for the line-edit / voice pass.
- **Closing-emotion blueprint.** A specification for the last 500–1,000 words of Ch7: shape (the emotion the close should leave the reader holding), explicit anti-criteria (no sentimentality, no swelling-strings vibes, no abstract humanity-uplift, no tour-guide rhetoric, no "throughout history" closer, *humanity* does no argumentative work in the last 1,000 words, no closing on the thesis sentence), and a structural sketch of what the final scene does without restating the thesis.
- **Word budget.** Per-chapter targets summing to ~80K (mid of the 70–90K band). Tolerance: ±15% per chapter before the budget is renegotiated. Documented in a table that the per-chapter gate references.
- **Page-level cadence reference.** Definition of one beat (per intent: roughly one quotable line, callback, observational aside, or earned small smile per page). Three concrete labelled beats drawn from the voice probe so the per-chapter cadence gate has fixed targets to sample against.

## Phase 1 — Per-chapter drafting

**Cadence.** Ch1 drafts first as the live voice anchor. Once Ch1's draft is in and the Phase-0 voice probe is tuned against the actual prose, Ch2–Ch7 launch and draft in parallel, each calibrating against the tuned probe. The disciplines below carry the load that sequencing would otherwise carry: voice spot-checks fire mid-flight (not just at the per-chapter checklist); the case slate is treated as a lock to prevent overlap and improvised swaps; callbacks are written to a fixed contract so the planting and firing chapters can be drafted without back-channel coordination. After all seven first drafts land, an end-to-end conceptual-flow read-through (Phase 1.5 below) verifies the parallel drafts cohere as a single book before Phase 2 begins.

Each chapter — including Ch1 — runs through the same loop:

1. **Research pass.** For each case in the chapter's slate, pull primary or scholarly sources into `research/ch{n}/`. Notes capture the specific anecdote, dates, attributions, and any quotation. This is the substrate the no-synthetic-anecdotes gate is checked against later. If a case fails research (source unobtainable, attribution can't be confirmed, anecdote turns out apocryphal), it is replaced from the chapter's backup or from a fresh search; the slate is updated to record the substitution.

2. **Outline.** A scene-by-scene outline showing how cases are sequenced, where the analysis seasoning sits (target ~80/20 story-to-analysis), where the chapter's impact moment lands, and which callbacks plant or fire. The outline is checked against the architecture's thesis arc — does this chapter sharpen the argument the way Phase 0 said it would?

3. **Draft.** Single first-person voice. Sections connected by prose, not `***` breaks doing structural work. Word count tracked against the chapter's budget. Designed impact moment(s) and callback fires hit their planned beats.

4. **Mid-flight voice check (parallel chapters only).** When a parallel-drafting chapter clears its first scene (~25% of chapter target), a short cross-chapter voice spot-check fires: pull the just-drafted opening alongside the tuned voice probe and an in-progress sample from at least one other parallel chapter; flag drift before the chapter bakes it in for another 75%. This is a lightweight gate, not a blocking review — drift is corrected at the sentence level if possible, escalated to a re-tune of the probe if multiple chapters are drifting in the same direction.

5. **Per-chapter self-review checklist.** Before declaring the chapter done, the author walks the chapter against this list. Failure on any item reopens the chapter:
   - **No-synthetic-anecdotes gate.** Every anecdote in this chapter traces to a real, cited source in `research/ch{n}/`. Composites fail, even when clearly framed.
   - **No invented quotes or attributions.** Where the evidence is shaky, the prose hedges or cuts.
   - **Thesis contribution.** This chapter sharpens or stress-tests the thesis from the previous one. It does not just survey.
   - **Case depth.** Cases are developed in depth, not enumerated. A case appearing only as a name-drop is cut or grown.
   - **Voice match.** Spot-check against the voice probe. First-person, dry-when-the-fact-is-funny-enough, playful-when-the-subject-rewards-it; never winking at the camera, never lecturing.
   - **Reader-stance match.** Narrator-as-discoverer, not reporter. Reader walks the find with the writer; reader is allowed to notice things first.
   - **Boundary-axis coverage.** The chapter's cases cross at least two of the five boundary axes between them (the book as a whole crosses all five; not every chapter has to).
   - **Page-level cadence.** Sample five random pages: at least four show one of the named beat-types from Phase 0 §10.
   - **Tone management for dark material.** Where the chapter touches death, suffering, taboo, or cross-cultural sensitivity, the laughter reads as honoring the gravity of the material — not deflecting from it. Flippancy and clinical distance are both failures.
   - **No structural typography.** No `***` carrying argumentative weight. If a transition is missing, write it.
   - **Word budget.** Chapter is within ±15% of the Phase 0 target.

**Disciplines that make parallelism work.** These are the load-bearing constraints that replace the protection sequential drafting would have given for free.

- **Voice anchor before parallel commit.** Ch1 drafts to completion (or at minimum to a stable, post-self-review draft) *before* Ch2–7 launch. The Phase-0 voice probe is then tuned against the actual Ch1 prose. The tuned probe is the reference object for every parallel chapter. Launching Ch2–7 against the *un-tuned* Phase-0 probe is the failure mode.
- **Case slate as lock.** With chapters drafting concurrently, the architecture's case slate is the contract. No case appears in more than one chapter without architecture-level approval. Backups are pre-cleared substitutions, not improvised replacements; if two parallel chapters reach for the same backup, the lead arbitrates rather than each chapter solving locally. A swap that goes through the lead is a slate update; a swap that doesn't is a defect the structural pass will catch.
- **Callback contract.** §4 of the architecture (callback design) is the contract that lets the planting chapter and the firing chapter be written at the same time. Each callback's source case, intermediate plants, return point, and the recognition shock the reader is meant to feel are fixed in Phase 0; the planting-chapter author writes to the contract; the firing-chapter author writes to the contract; neither needs back-channel coordination with the other to keep the callback intact.
- **Mid-flight voice spot-check.** Step 4 of the per-chapter loop above. Catches voice drift at ~25% rather than at the per-chapter checklist (~100%), where it is much more expensive to fix.

Special cases inside Phase 1:

- **Ch1.** Drafts first; doubles as the live voice anchor. Establishes the question and installs the narrator. After Ch1 draft is in, the voice probe in `architecture.md` is updated to reflect what the prose actually became; Ch2–7 then launch in parallel and calibrate against the tuned probe.
- **Ch7.** Engages divisive humor and the genuinely-not-universal as material to examine, not to celebrate or amplify. Does not flinch at the cases that qualify or break locally. The thesis resolves, sharpened by the stress test. Finishes with the closing-emotion turn from Phase 0's blueprint.

## Phase 1.5 — Conceptual-flow reconciliation

A sanity check between Phase 1 and Phase 2, not a new editorial pass. After all seven first drafts have cleared their per-chapter self-review, the manuscript is read end-to-end as a single artifact for thematic continuity — does it read as one book, or as seven chapters from different books? This step catches the structural cost of parallel drafting: chapters that each pass their own checklist but together don't cohere on tone, narrator stance, vocabulary register, or argumentative pitch.

Deliverable: a short reconciliation report (`editorial/conceptual-flow-reconciliation.md`) listing any continuity defects — voice register shifts, terminology drift, tone-management inconsistencies on dark material, callback-contract slips, narrator-stance breaks. Defects are repaired in the relevant chapters before Phase 2 begins. If the report is empty (or only nice-to-haves), Phase 2 starts with no rework.

This step is *load-bearing* in a parallel-drafting plan. The structural pass at the top of Phase 2 assumes a coherent draft; if the draft is incoherent at the seams between chapters, the structural pass will mis-diagnose and recommend the wrong surgery.

## Phase 2 — Manuscript-level editorial passes

Run on the full manuscript in this order. Each pass produces a list of revisions; revisions are applied before the next pass starts (or in-place during the pass, where the pass owner can fix without leaving their lane). Each pass corresponds 1:1 to an INTENT-required pass. They are run as distinct goals — never collapsed into a single "editing pass."

1. **Structural / thesis-advancement pass.** Does the argument escalate Ch1 → Ch7? Does each chapter advance the case the previous chapter could not? Does Ch7 stress-test rather than summarize? Are there chapters or sections that can be cut or merged without losing the spine? This pass has license to recommend chapter-level surgery.
2. **Fact and intellectual-honesty pass.** Every cited source is checked. Every anecdote checked against `research/ch{n}/`. Counter-evidence is treated honestly — if a case is stronger as a partial example than as a clean win, it is rewritten as a partial example. The book is checked against overclaim on boundary axes the case slate does not actually cross. The hard stops (no synthetic anecdotes, no invented quotes, no contact with living researchers) are re-verified at manuscript scale.
3. **Flow audit.** Connective tissue between sections and chapters. No `***` breaks doing structural work. Reads as continuous prose, not stitched fragments. Transitions carry argument and image, not topic announcement.
4. **Reader-experience audit.** Outside-in read from the airport-buyer's seat. Two checks, both run on the full draft (absorption is a whole-book property; the funny-test is best caught while injection is still cheap):
   - **Funny-test.** Does the prose itself produce laugh-or-grin moments at airport-book frequency? The book is *funny*, not merely about funny things. If the answer is no in stretches, this pass blocks until the affected sections are revised or the line-edit pass is staged to inject humor where it should have been.
   - **Absorption.** Does the manuscript hold a cold reader chapter to chapter? Where it sags, the flow pass and case-depth get re-opened. End-state criteria from INTENT (surprise repeated, anticipation builds, narrator trusted, belief revised, closing warmth earned, terminal impulse to recommend or quote, "reader misses their boarding call") are the gates.
5. **Line edit / voice consistency pass.** Sentence-level voice consistency against the (post-Ch1-tuned) voice probe. First-person, dry-and-warm, narrator-as-discoverer. Dialect and rhythm normalized across chapters. The pass also injects humor where the reader-experience audit flagged sag, where injection can be done at sentence level.
6. **AI-smell audit.** Hunt and remove residual machine-y patterns: over-hedged sentences, telegraphed transitions ("In this chapter we will…"), tricolons-of-three-where-two-would-do, em-dash overgrowth, structurally identical paragraph openers, generic adjectives where a specific noun would do. Read aloud where in doubt.
7. **Final copyedit.** Mechanical: spelling, punctuation, citation format in endnotes, hyphenation, capitalization conventions. Last pass because earlier passes invalidate it.

A pass *blocks* if it finds a defect it cannot fix in place. The pass owner records the defect, the manuscript loops back to the appropriate earlier phase, and passes resume from where the loop returns.

## Phase 3 — Endnotes and final compile

- **Endnotes.** All citations consolidated as endnotes per INTENT (no other front- or back-matter is in scope). Inline references in the prose are minimized — the prose carries voice; rigor lives in the notes.
- **Final word count.** Confirm the manuscript falls within 70–90K. If it lands materially below 70K, the structural pass is reopened — the book is too thin and needs to grow, not be padded.
- **Definition-of-done check.** Walk the manuscript against the DoD bullets in `INTENT.md`. Each must be defensible against a specific stretch of text:
  - 70–90K across seven chapters per the structure.
  - Five boundaries crossed; non-Western jokes distributed across the case slate.
  - Reader experience delivered (page-by-page texture and staged arc); end-state criteria cleared.
  - Voice holds (David Shapiro × Mary Roach target).
  - All seven editorial passes have been run as distinct goals.
  - Hard stops honored (no synthetic anecdotes, no invented quotes, no contact with living researchers).
- **Deliverable.** Manuscript files at `manuscript/` plus `manuscript/endnotes.md` (or equivalent endnotes file). Text-only — no visuals, per intent.

## Out of scope (this plan)

Mirror of `INTENT.md`'s out-of-scope list, retained here so dispatched workers don't drift into it:

- Heavy academic apparatus beyond endnotes (no extensive lit review, no peer-review-grade footnoting).
- Original empirical research or new experiments.
- Contact with living researchers, subjects, or rights-holders.
- Illustrations, photographs, or rights-cleared image inserts.
- Translation into other languages.
- Cover design, marketing, publishing, or distribution.
- Front- or back-matter beyond endnotes (no dedication, acknowledgements, foreword, prologue, or epilogue).

## Risks to watch

- **Voice drift across chapters (dominant Phase-2 risk under parallel drafting).** With Ch2–7 drafting concurrently, drift is the failure mode the plan is most exposed to. Mitigations stack: (a) Ch1 anchors and the voice probe is tuned against the actual Ch1 prose before parallel commit; (b) mid-flight voice spot-check at ~25% of each parallel chapter catches drift before it bakes in; (c) the per-chapter self-review checklist gates on voice match; (d) Phase 1.5 conceptual-flow reconciliation reads the seven drafts as one artifact and surfaces drift at the seams; (e) the line-edit / voice consistency pass runs on the full manuscript with the tuned probe as the reference object.
- **Case-slate erosion / overlap under parallel drafting.** Cases that look good in Phase 0 may not survive research; with parallel chapters, two authors may also reach for the same backup. Mitigations: source-vetting *before* the slate is closed; per-chapter backups documented as pre-approved substitutions, not improvised replacements; the slate is the lock — any swap routes through the lead, who arbitrates conflicts and updates the slate. Improvised swaps are defects the structural pass is designed to catch.
- **Callback contract slips (parallel-drafting risk).** A callback's planting and firing chapters are written at the same time. If the planting chapter omits the plant, or the firing chapter mis-recognizes the return, the recognition shock the architecture engineered for is lost. Mitigation: §4 of the architecture is the contract; both ends of each callback hold to that contract without back-channel coordination; Phase 1.5's read-through verifies callbacks fire as designed.
- **Funny-test failure late.** Mitigation: reader-experience audit runs *before* line-edit and AI-smell passes, so injection is still cheap. Authors also draft with the funny-test in mind, not as a downstream verification.
- **Tone failure on dark material.** Mitigation: per-chapter checklist names tone management for dark material as a gated item; Phase 1.5 reconciliation checks for inconsistency across chapters; reader-experience audit re-checks at manuscript level.
- **Word-count drift.** Mitigation: per-chapter budget, ±15% tolerance, manuscript-level reconciliation in Phase 3.
- **Counterexample chapter softens the thesis instead of sharpening it.** Mitigation: Ch7's slate-and-resolution path is fixed in Phase 0 (`counterexample-slate.md`), not invented during drafting; the structural pass re-verifies that Ch7 stress-tests rather than summarizes.
