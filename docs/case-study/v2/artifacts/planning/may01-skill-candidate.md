---
task: I would like a book on the universal nature of humor. There are certain types of humor that transcend time, culture and language (e.g. comedy wildlife photos, physical humor, affiliative humor, etc). This is a 5-7 chapter book, targeting armchair enthusiasts, and should explore this phenomena across cultural, temporal, language, belief, and technological boundaries. Thesis: Humor is what unites us.
session_id: job-20260501-053328-911918--i-would-like-a-book-on-the-uni
timestamp: 2026-05-01T08:11:25
status: pending
---

# PLAN

A working plan to produce the manuscript described in `INTENT.md`. Every section serves a constraint or success criterion already named in the intent — this document does not introduce new goals.

## Decisions to confirm

These are choices the intent leaves to the team. The plan below assumes them; the human can redirect any of them at ASSERT.

1. **Era spine for ch2–6 is media-driven, not century-driven.**
   - Ch2: Oral / pre-text antiquity (through ~500 CE)
   - Ch3: Manuscript era (~500–1500)
   - Ch4: Print era (~1500–1900)
   - Ch5: Broadcast era (~1900–2000)
   - Ch6: Algorithmic / information age (2000–present) — the chapter the intent fixes
   Rationale: media transitions make the universality claim *demonstrable* rather than asserted. A pratfall surviving oral → manuscript → print → broadcast → algorithm is the book's central trick, and the spine has to set it up. Time-driven splits (ancient/medieval/early-modern/modern) lose this leverage.
2. **Drafting cadence is sequential, ch1 → ch7.** Narrator-as-discoverer and the escalating-argument architecture both depend on the writer remembering what the reader has just been shown. Parallel chapter drafts produce voice drift and redundant cases; the time saved is repaid in line-edit and flow passes.
3. **Voice is calibrated on ch1 before ch2–7 commit.** The David Shapiro × Mary Roach target is specific enough to miss. A first-person-singular voice bible falls out of drafting ch1 and is then enforced as a reference in line edit.
4. **Pass sequence (after full draft):** structural/thesis → fact / intellectual honesty → flow → reader-experience audit (1st pass — funny-test + absorption) → line edit/voice → AI smell → reader-experience audit (2nd pass — confirms no regressions) → copyedit. Rationale: do load-bearing changes first, polish last; run the funny-test early enough that injecting humor is still cheap, and again at the end to guard regressions.

## Phase 0 — Architecture

Deliverable: `manuscript/architecture.md`. One document, ~2000–3000 words, that fixes the load-bearing decisions before any chapter is drafted.

Contents:

- **Thesis arc.** A paragraph per chapter naming what each chapter contributes to the argument *that the previous chapter could not*. Ch7 is included — its job is to stress-test, not to summarize.
- **Era spine.** The five era chapters (2–6) with the date ranges from "Decisions to confirm" above, and a one-line statement of what each era's *medium* makes possible or constrains for comedy.
- **Case slate.** 2–4 cases per chapter, vetted-source-only. Each entry: the case, what it demonstrates, primary source(s), and which boundary axes (cultural/temporal/linguistic/belief/technological) it crosses. This is the master list the no-synthetic-anecdotes gate is checked against. A case is *eligible* only when at least one named primary or scholarly source is on file.
- **Impact moments.** 3–5 designed set-pieces, located by chapter and approximate position. Each entry: the scene, why it lands, what it earns for the argument. These are the moments the manuscript is *engineered* around — the rest of the prose connects them.
- **Counterexample slate (ch7).** The divisive-humor cases and genuinely-not-universal cases the book commits to engaging with. Same source-vetting rule.
- **Word budget.** A target word count per chapter summing to ~80K (mid of the 70–90K band). The intent leaves distribution to the team; this document fixes it. Chapters can over- or undershoot by ~15% before the budget is renegotiated.
- **Voice probe.** Two paragraphs of sample prose in the target voice, used as a reference object during ch1 drafting and for line-edit calibration thereafter.

Phase 0 ends when `architecture.md` is approved by the human. The case slate is the single largest checkpoint here — once it is approved, drafting commits to those cases and changing them is treated as scope renegotiation.

## Phase 1 — Per-chapter drafting

Sequential, ch1 → ch7. Each chapter runs through the same loop:

1. **Research pass.** For each case in the chapter's slate, pull primary or scholarly sources into `research/ch{n}/`. Notes capture the specific anecdote, dates, attributions, and quotation if any. This is the substrate the no-synthetic-anecdotes gate is checked against later.
2. **Outline.** A scene-by-scene outline for the chapter, showing how cases are sequenced, where the analysis seasoning sits (target ~80/20 story-to-analysis), and where any impact moment for this chapter lands. Outline is reviewed against the architecture's thesis arc — does this chapter sharpen the argument the way Phase 0 said it would?
3. **Draft.** Single first-person-singular voice. No `***` section breaks doing structural work — connective tissue is prose. Word count tracked against the chapter's budget.
4. **Per-chapter self-review checklist.** Before declaring the chapter done, the author walks the chapter against this list. Failure on any item reopens the chapter:
   - **No-synthetic-anecdotes gate.** Every anecdote in this chapter traces to a real, cited source in `research/ch{n}/`. Composites — even clearly framed — fail. *(Intent-pinned ownership.)*
   - **Thesis contribution.** This chapter sharpens or stress-tests the thesis from the previous one. It does not just survey.
   - **Case depth.** Cases are developed in depth, not enumerated. If a case appears only as a name-drop, it is cut or grown.
   - **Voice match.** Spot-check against the voice probe from Phase 0. First-person-singular, narrator-as-discoverer, dry-and-warm balance.
   - **Boundary-axis coverage.** The chapter's cases cross at least two of the five boundary axes between them (the book as a whole crosses all five; not every chapter has to).
   - **No structural typography.** No `***` breaks carrying argumentative weight. If a transition is missing, write it.
   - **Word budget.** Chapter is within ~15% of the Phase 0 target.

Special cases inside Phase 1:

- **Ch1.** First chapter drafted, also the voice bible. Ch1 establishes thesis framing and earns reader curiosity (intent's success criterion). After ch1 draft is in, the voice probe in `architecture.md` is updated to reflect what the prose actually became, so ch2–7 calibrate against the real voice.
- **Ch7.** Engages divisive humor and the genuinely-not-universal as material to examine. The chapter does not celebrate or amplify exclusionary humor (intent's out-of-scope clause). The thesis resolves, doesn't dissolve — ch7 finishes with what *is* universal, sharpened by the stress test.

Phase 1 ends when all seven chapters have passed their per-chapter self-review.

## Phase 2 — Manuscript-level passes

Run on the full manuscript in this order. Each pass produces a list of revisions; revisions are applied before the next pass starts (or the pass that finds them, if it can fix in place).

1. **Structural / thesis pass.** Does the argument escalate ch1 → ch7? Does ch7 actually stress-test, not summarize? Are there chapters that can be cut or merged without losing the spine? This is the pass with license to recommend chapter-level surgery.
2. **Fact / intellectual honesty pass.** Every cited source is checked. Every anecdote is checked against `research/ch{n}/`. Counter-evidence is treated honestly — if a case is stronger as a partial example than as a clean win, it is rewritten as a partial example. The pass also checks that the book does not overclaim against the boundary axes it has not actually crossed.
3. **Flow pass.** Connective tissue between sections and chapters. No `***` doing structural work. Reads as continuous prose, not stitched fragments. Transitions carry argument and image, not just topic.
4. **Reader-experience audit (1st pass).** *(Intent-pinned ownership of the funny-test.)* Two checks:
   - **Funny-test.** Does the prose itself produce laugh-or-grin moments at airport-book frequency? A leisure reader should notice. If the answer is no, this pass blocks until line edit injects humor where it should have been.
   - **Absorption.** Does the manuscript hold a cold reader chapter-to-chapter? Where it sags, the flow pass and case-depth get re-opened.
   This pass is run on the full draft, not chapter-by-chapter, because absorption is a whole-book property.
5. **Line edit / voice pass.** Sentence-level voice consistency against the (updated post-ch1) voice probe. First-person singular, dry-and-warm, narrator-as-discoverer. Dialect and rhythm normalized across chapters.
6. **AI smell pass.** Hunt and remove residual machine-y patterns: over-hedged sentences, telegraphed transitions ("In this chapter we will…"), tricolons-of-three-where-two-would-do, em-dash overgrowth, structurally identical paragraph openers. Read aloud where in doubt.
7. **Reader-experience audit (2nd pass).** Re-runs funny-test and absorption check after line edit and AI-smell. Catches regressions where polishing flattened a joke.
8. **Copyedit pass.** Mechanical: spelling, punctuation, citation format, hyphenation, capitalization conventions. Last pass because earlier passes invalidate it.

A pass *blocks* if it finds a defect it cannot fix in place. The pass owner records the defect, the manuscript loops back to the appropriate earlier phase, and passes resume from where the loop returns.

## Phase 3 — Notes section and final compile

- **Notes section.** All citations consolidated into a notes section at the back. Inline references in the prose are minimized — the prose carries voice; rigor lives in the notes (intent's "rigor without footnote clutter" constraint).
- **Final word count.** Confirm the manuscript falls within 70–90K. If it lands materially below 70K, the structural pass is reopened — the book is too thin and needs to grow, not be padded.
- **Definition-of-done check.** Walk the manuscript against the five DoD bullets in INTENT.md. Each must be defensible against a specific stretch of text.
- **Deliverable.** A single-file or multi-file manuscript at `manuscript/` (final form) plus `manuscript/notes.md`. Text-only — no visuals this phase, per intent.

## Out of scope (this plan)

- Visuals, photos, layout, cover, jacket copy. Intent defers these.
- A taxonomy of humor or a comprehensive history. Intent rules these out.
- Marketing, agent submission, publication logistics. Manuscript only.

## Risks to watch

- **Voice drift across chapters.** Mitigation: ch1 voice bible, line-edit pass, two reader-experience audits.
- **Case slate erosion.** Cases that looked good in Phase 0 may not survive research. Mitigation: source-vetting *before* slate is closed; if a case fails research, replace from a backup pool sized at +1 per chapter.
- **Funny-test failure late.** Mitigation: first reader-experience audit is run *before* the polish passes, so injection is still cheap. Author also writes ch1 with the funny-test explicitly in mind, not as a downstream verification.
- **Word count drift.** Mitigation: per-chapter budget, ±15% tolerance, manuscript-level reconciliation in Phase 3.
