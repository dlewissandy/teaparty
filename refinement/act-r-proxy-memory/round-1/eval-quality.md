# Quality Evaluation — Round 1

## Verdict: PASS

## Concerns Addressed

- **Noise parameter s = 0.25 claimed as ACT-R standard** (factcheck) — addressed: reframed as design choice in act-r.md, parameter table updated with "Design choice; ACT-R tutorials use 0.2-0.5" in Source column, calibration flagged.
- **Retrieval threshold tau = -0.5 claimed as ACT-R standard** (factcheck) — addressed: reframed as design choice with rationale for negative threshold, parameter table updated.
- **Cost model arithmetic errors G=10 and G=20** (factcheck) — addressed: incorrect rows removed from summary table rather than corrected in place; the formula remains for readers to verify. Acceptable resolution.
- **Embedding dimensions inconsistent across documents** (logic #1) — addressed: all four documents now use the 5-dimension schema from the mapping document. The sensorium's "upstream" dimension was removed; the root document's MemoryChunk gained `embedding_artifact`.
- **Combined score mixes incompatible scales** (HM #3) — addressed: `normalize(B)` added to score formula, `normalize_activation()` function added to implementation sketch, explanatory paragraph added, Park et al. citation for precedent.
- **"Explicit reinforcement" trace rule 3 is vague and dangerous** (HM #11) — addressed: rule removed entirely. Traces now created only on creation and retrieval, matching standard ACT-R.
- **Chunk creation ambiguity for non-surprise gates** (logic #4) — addressed: explicit statement added that every gate produces a chunk; non-surprise chunks have empty salience fields. Session lifecycle STORE step updated.
- **Auto-approval tension between root and sensorium documents** (logic #3) — addressed: root document now includes a note distinguishing EMA-based auto-approval (skips inspection) from two-pass auto-approval (completes inspection). Sensorium expanded to make the distinction explicit.
- **Surprise is binary but should be graded** (HM #7) — addressed: surprise now triggers on action change (strong) OR confidence delta > 0.3 (moderate). SurpriseDelta.magnitude updated. Session lifecycle pseudocode updated.
- **No evaluation criteria or success metrics** (HM #1) — addressed: concrete metrics added (action match rate, prior calibration, surprise calibration, retrieval relevance) plus an ablation plan isolating each design component.
- **Embedding cost buried** (HM #8) — addressed: noted in sensorium Implementation section and added to cost model variable list.
- **No memory maintenance or garbage collection** (HM #10) — addressed: new "Memory Maintenance" section in mapping document with trace compaction, chunk pruning, and database maintenance.
- **Cold start unaddressed** (HM #5) — addressed: new "Cold Start Behavior" section in mapping document making explicit that zero chunks = escalate everything.
- **"Deployed at scale" and Claude memory claims unverifiable** (factcheck) — addressed: removed and replaced with specific published citations (Park et al. 2023, Nuxoll & West HAI 2024, Bhatia et al. Frontiers 2026).
- **"Low-fan spreading activation" analogy overstated** (logic non-sequitur #4) — addressed: phrasing removed, replaced with direct description of the intersection effect. Note added that multi-dimensional retrieval is a novel design choice needing ablation.
- **d = 0.5 justification doesn't transfer cleanly** (HM #4, logic non-sequitur #3) — addressed: caveat paragraph added acknowledging the regime difference, framing d = 0.5 as principled starting point rather than validated parameter.
- **Two-pass delta noise unacknowledged** (HM #6) — addressed: "A note on signal quality" paragraph added to sensorium document.
- **Cost model omits output tokens and cache-write premium** (logic non-sequitur #2) — addressed: output tokens (O), cache-write premium (w), and embedding cost (E) added to variables. Explicit note that the model focuses on input token-equivalents.
- **376-chunk arithmetic unexplained** (factcheck) — addressed: explicit assumption stated (reserving ~12,000 tokens for system prompt and gate content).
- **Anderson & Schooler "event-based" framing overstated** (logic non-sequitur #3) — addressed: parenthetical clarification added that "event-based" is a reasonable interpretation, not a direct quote, with primary units noted.
- **AutoDiscovery "hypothesis ranking" imprecise** (factcheck) — addressed: changed to "guiding hypothesis exploration."
- **EMA/ACT-R separation too rigid** (logic unstated assumption #5) — addressed: note added about indirect information flow and operational actions.
- **Cross-task learning may contaminate** (logic unstated assumption #3) — addressed: sentence added noting structural filtering mitigates contamination.
- **KV cache section framing blurs core vs. future economics** (HM #9) — addressed: framing sentence added separating the core design from the future direction.

## Concerns Correctly Rejected

- **"Corrections are more informative" is a non sequitur** (logic non-sequitur #1) — defended: the proponent's argument that error-describing text is inherently more specific than success-confirming text held. Phrasing tightened from "richer" to "more specific associations" without abandoning the claim.
- **LLM may not produce meaningfully different Pass 1 vs Pass 2 outputs** (logic unstated assumption #1) — defended: conditioning on presence/absence of a multi-page artifact is a substantive input difference. The concern is reasonable as a monitoring item but not a design flaw.
- **Cosine similarity is not spreading activation** (logic unstated assumption #2) — defended: the documents explicitly state this is a replacement, not a replication. The "low-fan" analogy was softened (a concession), but the substitution itself stands.
- **Activation threshold may not be self-regulating** (logic unstated assumption #4) — defended: directionally correct that a fixed threshold on a decaying function limits loading. Note added about tau adjustment, but no heavyweight analysis added — appropriately deferred to shadow mode.
- **Multi-dimensional embeddings need validation** (HM #2) — defended: the architecture is preserved with an ablation plan committed. The question is empirical, not structural.
- **KV cache section should be removed** (HM #9) — defended: section preserved with adjusted framing. It demonstrates architectural continuity and is clearly labeled future work.

## Concerns Missed

- **The KV cache section's cost model still presents specific G=3 and G=5 numbers as though the input-only comparison tells the full story.** The synthesis added disclaimers about output tokens and cache-write premium, but the remaining summary table (G=3, G=5) still shows the input-only "token-equivalents" comparison with a "vs. Current" column that says "-24%". A reader skimming the table gets the old misleading conclusion. The table should either include output costs or carry a footnote at the table itself (not just in surrounding prose).
- **The sensorium document's "Upstream" dimension was removed from the table but the prose at line 14 of draft-0 still listed "upstream context" as a percept the proxy has access to.** The draft-1 sensorium still lists upstream context in the Problem section's bullet list (line 14) but there is no corresponding embedding dimension for it. This is a minor coherence gap: the proxy senses upstream context but has no dedicated retrieval pathway for it. The synthesis changelog says upstream was removed because it wasn't in the mapping schema, but did not address how upstream context enters retrieval at all — presumably it folds into the artifact or stimulus embedding, but this is unstated.

## Regressions

- **The cost summary table lost information.** Draft-0 had a table showing G=3, 5, 10, 20 with specific numbers and savings percentages. Draft-1 removed G=10 and G=20 rows to fix arithmetic errors but did not replace them with corrected values. This makes the scaling argument weaker — the reader can no longer see at a glance that savings improve with more gates.
- **The "Corrections are more informative" passage in the mapping document changed from "richer associations" to "more specific associations" but then added a hedging sentence ("Whether this specificity translates to better retrieval precision is an empirical question to validate during shadow mode"). The hedge is appropriate for epistemic honesty but weakens a claim the proponent successfully defended.** This is a minor regression — the claim is still present but reads as less confident than the defense warranted.

## Coherence

The revised document set reads as a unified whole — the embedding schema is consistent, cross-references are accurate, the auto-approval tension is resolved, and the tone is uniform across all four documents.

## Overall

Draft-1 is substantially better than draft-0. Every factual error the fact-checker identified has been corrected or removed. Every concern the proponent conceded has been addressed. The defended claims remain intact. The documents gained three new sections (cold start, memory maintenance, evaluation metrics) that fill genuine gaps. The epistemic calibration improved significantly: the draft now distinguishes clearly between what is established ACT-R theory, what is a design choice for this system, and what is novel and unvalidated. The cost model is more honest about its scope. The only regressions are minor (truncated cost table, slightly over-hedged correction claim). The synthesis was well-executed.
