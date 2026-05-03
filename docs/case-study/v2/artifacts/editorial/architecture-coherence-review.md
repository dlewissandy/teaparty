# Architecture coherence review — `manuscript/architecture.md`

Internal-coherence review before human ASSERT. Phase 0 deliverable. Reviewed against `INTENT.md`, `PLAN.md`, `research/architecture/case-slate.md`, and `research/architecture/counterexample-slate.md`.

---

## Top-line verdict

**PASS WITH FIXES.**

The architecture is structurally sound and faithful to its substrate. Cross-references resolve cleanly across §3, §4, §5, §6, §7, and §10. The word budget arithmetic is exact. The Keaton overlap resolution is faithful to the slate's own recommendation. The voice probe in §7 hits its 60/40 Roach-Shapiro target and lands at least one screenshot beat per paragraph. The closing-emotion blueprint names the anti-criteria explicitly. The thesis arc escalates rather than parallels.

Two **fix-before-ASSERT** items prevent a clean PASS:

1. **§3 framing does not name the non-Western-jokes gate at architecture level.** The slate clears the gate (5 distinct traditions); the architecture inherits the clearance silently. If §3 is ever trimmed under revision pressure, the gate evaporates without anyone noticing.
2. **§7 annotation block numbers Move 4 and Move 5 in the opposite order from `INTENT.md`.** Annotation-only fix; the prose itself is fine. But this is the calibration object ch1 will draft against, and the numbering should match the spec it calibrates to.

Neither fix is load-bearing for downstream drafting; both are cheap to apply before the human approves.

A handful of nice-to-have polish items are noted per-section. No blockers.

---

## Per-section findings

### §1 — Thesis arc

✓ — escalation is real, chapter-by-chapter.

Each chapter paragraph names a contribution the previous chapter could not have made: Ch2 establishes that humor was already polished pre-text; Ch3 establishes *structural convergence* (independent re-emergence in unrelated literate cultures); Ch4 establishes *verbatim survival* (transmission as artefact, not just type); Ch5 establishes *embodied portability* (the comic body crossing borders); Ch6 establishes *structure without body* (the joke decoupled from speaker, language, country); Ch7 stress-tests. The argument advances at every step. No two adjacent chapters duplicate work.

The Ch1 paragraph plays the slightly different role of *installing the question rather than advancing it* — that is correct for a Ch1 framing.

No findings.

---

### §2 — Era spine

✓ — clean.

Five era chapters, date ranges that match `PLAN.md`'s "Decisions to confirm" item 1, one-line descriptor each that names what the medium makes possible or constrains. No drift.

No findings.

---

### §3 — Case slate reference

**Finding (fix-before-ASSERT): §3 does not name the non-Western-jokes requirement at architecture level.** The opening framing reads:

> Source-of-truth: `research/architecture/case-slate.md`. Per chapter: 4 primaries + 1 backup. `[axes: …]` shorthand: c = cultural, t = temporal, l = linguistic, b = belief, x = technological.

`INTENT.md` calls non-Western coverage a hard requirement ("Non-Western jokes are required; the universality thesis cannot be argued from a Western-only sample"). `PLAN.md`'s Phase-0 contents calls non-Western jokes "intent gate." The slate's slate-wide summary documents the count (5 distinct traditions cleared with one to spare). But the architecture's own §3 framing is silent. The gate is currently implicit-by-roster; trimming or a forced swap could erode it without flagging.

*Suggested correction:* one additional line in §3's opening framing, e.g., "Non-Western coverage is required across the slate as a whole (INTENT-level gate); the slate's slate-wide summary documents 5 distinct traditions cleared." That preserves the gate at architecture level so it cannot be trimmed silently.

Otherwise §3 is clean. The fact-checker's exhaustive walk confirmed every primary and backup case named in §3 (Ch2–Ch6) appears in `case-slate.md` for the correct chapter, with matching era-attribution. The 4 primaries + 1 backup convention is honored throughout. The `[axes]` shorthand resolves consistently.

**Nice-to-have:** the Keaton overlap notice (the paragraph between the framing and Ch2's primaries) cross-references §4 Callback 2 for the Dead Parrot deadpan-callback claim. A second cross-reference to the slate's own reserve-list provenance for Dead Parrot ("documented as Ch5 substitution candidate in `case-slate.md`'s reserve list") would harden the swap's audit trail. Optional.

---

### §4 — Callback design

✓ — all four callbacks resolve cleanly to §3 cases.

The fact-checker walked each callback's source case, intermediate plants (where named), and return point against §3, confirming chapter-and-position alignment for all of:

- Callback 1 — You Meng (Ch2) → Cantinflas (Ch5) → meme circulation (Ch6).
- Callback 2 — *Philogelos* slave-seller (Ch2) → Joe Miller #99 (Ch4 early) + Twain quail-shot (Ch4 late) → Dead Parrot (Ch5 backup) + KC Green (Ch6).
- Callback 3 — Cervantes windmills (Ch4 backup, planted) → Chaplin + Lucy (Ch5).
- Callback 4 — Hou Bai (Ch3) → Caonima (Ch6).

The "recognition shock" descriptions for each callback are concrete (the dog in flames *is* the indignant slave-seller; the children's chorus *is* Hou Bai's pun-cover). They specify what the callback should feel like at the point of recognition, which is exactly what `PLAN.md` Phase-0 contents require for callback design.

**Nice-to-have:** Callback 2's return-point clause "Ch5 backup if used (Dead Parrot's 'He's just resting' *is* the *Philogelos* shopkeeper…)" reads as conditional, but the §3 swap *already commits* to Dead Parrot as the Ch5 backup. The "if used" is a pre-commitment hedge that the swap retired. Suggest: "Ch5 (Dead Parrot's 'He's just resting' *is* the *Philogelos* shopkeeper…)". Optional.

---

### §5 — Impact moments

✓ — clean.

Four moments, located by chapter and approximate page; each names scene + why-it-lands + what-it-earns in the format `PLAN.md` Phase-0 contents specifies. The fact-checker confirmed each moment maps to a §3 case at the chapter claimed (Westcar opening Ch2; Twain late Ch4; Lucy mid-Ch5; *Song of the Grass Mud Horse* late Ch6). Verbatim quoted detail ("Speed it up a little!"; "Why blame my cats") matches the slate's primary-source text.

The architecture commits to four moments rather than three or five; that lands inside `INTENT.md`'s "3–5 designed impact moments" range. Two of the four (Impact 2 and Impact 4) are explicitly engineered to fire callbacks at the same time, which is consistent with §4 and reinforces the connective-tissue function callbacks are supposed to play.

No findings.

---

### §6 — Counterexample slate (Ch7) and resolution path

✓ on substance — clean.

The fact-checker confirmed all eight cases named in the resolution path exist in `counterexample-slate.md` with matching thesis-status labels (holds / qualifies / qualifies hard / breaks locally), and in the staged order the architecture claims (Soviet train → *Futon* → Apollinaire → Keaton → *Life of Brian* → Jyllands-Posten → Jim Crow → RTLM/Habimana). Categories (divisive / linguistic-cultural / belief / medium-locked) are 2-2-2-2 as the counterexample slate prescribes.

The resolution path's logic is intact: ramp from low-resistance qualifies, hold the Jyllands-Posten concession explicitly without softening the pivot, close on the hardest material with the chapter's reframing — *the question we leave the reader with is what we point this at*. The pivot from §6 step 5 to §8 (closing-emotion turn) is named cleanly.

**Nice-to-have:** §6 step 2's middle sentence reads "Same move in the technological axis." That is faintly explanatory in a register §6 otherwise keeps terse-and-imperative. *Suggested correction:* "Then medium-lock — Apollinaire and Keaton, this time on the technological axis. Keaton is the hinge…". Optional polish.

---

### §7 — Voice probe

**Finding (fix-before-ASSERT): annotation block numbers Move 4 and Move 5 in the opposite order from `INTENT.md`.** `INTENT.md`'s "Voice mechanism" section orders the moves as: 1. Observational comparison, 2. Dry precision, 3. Deadpan understatement, 4. Callbacks across chapters, 5. Surprise via specificity. §7's annotation block has callbacks at Move 5 and surprise-via-specificity at Move 4 — swapped.

The numbering will become the per-chapter gate's reference object. If chapters self-review against the architecture's ordering and the structural pass references INTENT's, the moves can be miscounted at the seam.

*Suggested correction:* swap the annotation block's Move 4 and Move 5 labels (no prose change required) so the architecture's numbering tracks INTENT's. If the architecture's ordering is the deliberate one, that decision needs to be made explicit, and INTENT updated in turn — but the simpler and safer move is to align the architecture to INTENT.

✓ on the prose itself. The voice-editor's verdict: the §7 probe hits 60/40 Roach-Shapiro, errs (correctly) toward Roach, lands at least one screenshot beat per paragraph ("not stopped Sneferu from being a guy" in ¶1; the fishnets-stalled tableau in ¶2), demonstrates all four required moves visibly (callbacks excepted, as the annotation block correctly notes), and shows no Shapiro-pole drift of the kind the prior cycle's loss-of-nerve produced.

**Nice-to-have:** the Move 4 annotation cites "*ebony* doing work an adjective can't" — *ebony* is itself an adjective in that clause ("ebony oars"). The intended point is that the *concrete particular* (ebony, not just "wooden") does work that a generic adjective can't. Wording is wonky in a way that pulls a thoughtful reader up short. *Suggested correction:* rephrase to something like "*ebony* doing work a generic adjective can't" or "the specificity of *ebony* doing the work" — preserves the point without the self-undercut.

**Nice-to-have:** ¶2's "small turquoise fish-shaped pendant" is a strong specificity beat that the annotation block does not cite under Move 4. Consider adding it to the Move 4 line-refs.

---

### §8 — Closing-emotion blueprint

✓ — comprehensive and explicit.

All seven anti-criteria named in the task spec are explicitly named in §8 (not merely implied):

1. ✓ "No sentimentality."
2. ✓ "No swelling-strings vibes."
3. ✓ "No abstract humanity-uplift ('we are all one' / 'across the ages we are joined' / similar)."
4. ✓ "No tour-guide rhetoric ('now we have come to the end of our journey,' 'as we have seen throughout,' 'let us close by remembering')."
5. ✓ "No 'throughout history' closer."
6. ✓ "The word *humanity* does no argumentative work in the last 1,000 words. (It can appear in a quotation; it cannot carry a sentence.)" — note the explicit quotation-vs-load-bearing distinction is itself useful spec.
7. ✓ "No closing on the thesis sentence. The thesis is what the book demonstrated; the close is what the demonstration leaves the reader holding."

The structural sketch of the last 500 words is concrete: narrows from the Ch7 argumentative resolution to the Westcar scribe at his desk in the Second Intermediate Period. The image does the argument's work without restating it. The named-other shape is preserved ("not 'the world,' not 'everyone,' one person").

The §8 sketch is consistent with §1's Ch7 paragraph and with §6 step 5 (which hands off cleanly to §8). All three pointers point at the same closing scene without contradiction.

No findings.

---

### §9 — Word budget

✓ — arithmetic exact.

Per-chapter targets sum to exactly 80,000 (10K + 12K × 5 + 10K). ±15% bands computed correctly per chapter (10K → 8,500–11,500; 12K → 10,200–13,800). Manuscript range (70K–90K) matches `INTENT.md`. The closing line — "A chapter outside its ±15% band reopens the budget conversation; it does not silently auto-pad or auto-cut" — is operational guidance that downstream chapters can act on.

No findings.

---

### §10 — Page-level cadence reference

✓ — operational.

Definition of one beat is named (per `INTENT.md`). Three concrete examples are drawn from the §7 voice probe, each labeled by type (quotable line; deadpan understatement; observational aside / surprise via specificity). The voice-editor confirmed all three beats appear verbatim in §7's prose. Per-chapter gate is named: "samples five random pages: at least four must show a beat" — fixed target the per-chapter self-review can act against.

This section is the operational reflection of `INTENT.md`'s late-added page-level cadence requirement. It is present, concrete, and gated. No drift.

No findings.

---

## Cross-section findings

- **§3 ↔ §4 ↔ §5 ↔ §6 cross-references — clean.** Fact-checker's exhaustive walk: every case named in §4 callbacks, §5 impact moments, and §6 resolution path resolves to a case in §3 (for case-slate cases) or in `counterexample-slate.md` (for Ch7 cases) at the chapter and approximate position claimed.
- **§7 ↔ §10 beat consistency — clean.** All three §10 beats appear verbatim in §7's prose.
- **§1 Ch7 ↔ §6 step 5 ↔ §8 closing-scene consistency — clean.** All three pointers target the same closing turn (the Ch7 reframing, then the §8 narrowing-to-Westcar-scribe image).
- **Keaton overlap resolution — faithful.** The architecture's swap (Ch5 backup → Dead Parrot; Ch7 keeps Keaton) reflects exactly the recommendation `case-slate.md`'s Note (lines 742–747) makes for the overlap, with the verbatim phrase "the counterexample function is the more singular use" preserved. Dead Parrot is documented in `case-slate.md`'s reserve list as a Ch5 substitution candidate. The justification (Dead Parrot adds British TV sketch tradition; deadpan callback to *Philogelos*) is supported by the slate.

No cross-section findings flagged. The architecture's internal references are coherent.

---

## Gate-by-gate report

- **No-synthetic-anecdotes gate (spot-check ≥3 cases at random).** ✓ — fact-checker verified three randomly-selected cases from §3/§6 against the relevant slate; each has at least one named primary or scholarly source on file.
- **All five voice moves visibly demonstrated in §7 (callbacks excepted).** ✓ on prose; **fix-before-ASSERT** on annotation numbering (Move 4/5 swap relative to INTENT). The four required moves (observational comparison, dry precision, deadpan understatement, surprise via specificity) are each present in the prose and exemplified by lines the annotation correctly identifies — the only defect is the move-number labels.
- **All five failure modes checked against in spirit (architecture's own register).** ✓ — style-reviewer found no drift of the architecture itself toward comparative-anthropology, thesis-pre-explanation, defensive meta-commentary, parallel-survey-by-hard-break, or tour-guide register. The §6 step 2 finding noted above is faintly explanatory but stays inside spec voice.
- **Non-Western coverage preserved.** ✓ on count (5 traditions: Chinese, Arabic, Japanese, Mexican/Latin American, Indian — all visibly in §3); **fix-before-ASSERT** on §3 framing not naming the gate. The coverage is real; the architecture-level commitment is implicit-by-roster rather than named-as-gate.
- **Closing-emotion blueprint anti-criteria named explicitly.** ✓ — all seven items present and explicit (not implied) in §8.

---

## Summary of fixes before ASSERT

Two fix-before-ASSERT items, applied as small targeted edits to the architecture (downstream dispatch — this review does not edit the document):

1. **§3** — add one line to the opening framing naming the non-Western-jokes gate as an architecture-level commitment.
2. **§7** — swap the annotation block's Move 4 and Move 5 labels so they track `INTENT.md`'s ordering (callbacks = Move 4; surprise via specificity = Move 5).

Three nice-to-have polish items, optional:

- **§3 Keaton-overlap notice** — add a cross-reference to the slate's reserve-list provenance for Dead Parrot.
- **§4 Callback 2** — strike "if used" from the Ch5 return clause; the swap committed to Dead Parrot as Ch5 backup.
- **§6 step 2** — tighten "Same move in the technological axis." to "this time on the technological axis."
- **§7 Move 4 annotation** — rephrase "*ebony* doing work an adjective can't" to clear the self-undercut, and consider adding the "small turquoise fish-shaped pendant" beat to the Move 4 line-refs.

After the two fix-before-ASSERT items are applied, the architecture is ready for human ASSERT.
