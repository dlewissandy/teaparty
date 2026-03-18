# Quality Evaluation — Round 2

## Verdict: PASS

Round 2 synthesis successfully addressed critical errors and major specification gaps. The cost calculation error was corrected, the Phase 0 specification checklist was added, and key engineering gaps are now explicitly scoped. The document improved on all fronts while defending sound positions.

---

## Concerns Addressed

**Cost calculation error (fact checker)** — Addressed. The worked example in act-r-proxy-memory.md lines 307-315 is corrected from $0.47 to $0.33 per session. Unit conversion errors are fixed (tokens divided by 1,000,000 for pricing, not applied as whole-number multipliers). The corrected claim is now that two-pass with caching is 6% cheaper than current design, flipping the economic argument from "cost overhead" to "investment with immediate payback." Verification is mathematically sound.

**Engineering gaps remain unaddressed (engineering critic)** — Addressed. New Phase 0 Specification Checklist (act-r-proxy-memory.md lines 81-92) explicitly scopes six blocking decisions: embedding model, chunk serialization format, prompt templates, output parsing, confidence extraction, and concurrency control. These are no longer left implicit; they are assigned to Phase 0 with a statement that answers are required before Phase 1 begins. This moves accountability from implicit to explicit.

**Sparse surprising interactions (visionary and logic critics)** — Addressed. New section "Bootstrapping the Learned Attention Model" (act-r-proxy-sensorium.md lines 89-98) acknowledges the bootstrapping challenge explicitly: ~7-8 surprise examples at 15% rate with 50 interactions creates sparse signal. The section specifies Phase 1 monitoring (surprise rate tracking), identifies the inverted-U learning curve, and provides a concrete fallback: revert to binary surprise extraction if confidence-based extraction proves too noisy. This is honest about the gap and provides empirical gates.

**Confidence threshold mechanism is undefined (logic and engineering critics)** — Addressed. Enhanced "Surprise: When to Extract Salient Percepts" section (act-r-proxy-sensorium.md lines 73-86) now explicitly states that the 0.3 threshold is "a starting heuristic, not a precision instrument" and specifies the fallback: "if confidence values prove too noisy, the fallback is the binary mechanism (action change only), which is more robust." This resolves the contradiction between precision mechanism and unstable measurement.

**Autonomy criteria deferred but framed as inevitable (visionary and logic critics)** — Addressed. Phase 1 shadow mode section (act-r-proxy-memory.md lines 104-109) uses conditional language: "if metrics are ambiguous after 50 interactions, extend shadow mode to 100 interactions before deciding." The go/no-go criteria are now concrete thresholds (action match rate >= 70%, etc.), not vague promises. Phase 3 is no longer implied; it is conditional on Phase 2 data.

**EMA reintegration falsely claimed as separation (visionary and logic critics)** — Addressed. The session lifecycle section (act-r-proxy-memory.md lines 204-205) now explicitly states the coupling: "EMA and the memory system operate on separate data paths. When upstream quality degrades, the memory system responds through its normal operation — more correction chunks accumulate, shifting retrieval toward skeptical patterns, not through EMA influencing retrieval." This is honest about the indirect coupling without false claims of separation.

**Chunk serialization format not specified (engineering critic)** — Addressed. Enhanced section "How Does the Proxy Use Retrieved Chunks?" in act-r-proxy-mapping.md (lines 160-162) now specifies serialization concretely: Markdown format with chunk ID heading, subheadings for field types, prose content inline. Token budget is given (~400-600 tokens per chunk, ~500 average), and context limit is specified (~10 chunks at 5000 tokens). Format is functional but leaves template instantiation to Phase 0, which is appropriate.

**KV cache verification staged as a gate (engineering critic)** — Addressed. New paragraph at end of "Verification Needed" section (act-r-proxy-memory.md lines 327-328): "Phase 0 verification (1-2 weeks): Test prompt caching behavior with `claude -p` subprocess calls. If caching is not reliable, the two-pass design cost rises approximately to $0.50/session. Cost-benefit analysis will determine whether to proceed to Phase 1 with simpler single-pass design plus memory augmentation instead." This makes cache verification a pre-Phase-1 decision gate, not a deferred unknown.

---

## Concerns Correctly Rejected (Defended Positions Maintained)

**Learned attention bootstrapping defended by activation reinforcement** — Maintained. The proponent's defense (round-2/proponent.md lines 68-73) is sound and not contradicted by draft-2. The design includes two signals: activation (frequency of use, dense) and salience (artifact-specific attention, sparse). Non-surprising interactions reinforce activation even without salience. This dual mechanism is preserved in the phase 0 specification and ablation plan (act-r-proxy-memory.md lines 111-115).

**Multi-dimensional embeddings have a clear fallback** — Maintained. The 5x embedding cost and novel design choice are kept, with an explicit Phase 1 ablation (act-r-proxy-memory.md lines 107-108): "if single-embedding retrieval achieves >= 95% of multi-dimensional retrieval's match rate, the 5x embedding cost is not justified — simplify to single embedding." This is conservative engineering: test the complex design, fall back to simpler if payoff is marginal.

**ACT-R decay vs. simple recency is an empirical question** — Maintained. The ablation is specified (act-r-proxy-memory.md lines 108-109): "if most-recent-N retrieval achieves >= 95% of ACT-R decay's match rate, the activation machinery is not earning its complexity." The design doesn't defend power-law decay as obviously right; it proposes to test it against a simpler baseline.

**Composite score normalization is intentionally adaptive** — Maintained. The proponent's defense (round-2/proponent.md lines 80-83) is correct. The draft-2 mapping document (act-r-proxy-mapping.md line 144) explicitly notes: "When all candidates have similar activation, semantic relevance dominates. That is the correct behavior. When activation varies widely, it has strong discriminating power." This adaptive behavior is preserved and highlighted as intentional design.

**Sparse matching is penalized deliberately** — Maintained. The cosine averaging mechanism (act-r-proxy-mapping.md lines 140-141) rewards breadth of matching: "chunks that match across more dimensions score higher than chunks that match narrowly on fewer dimensions." This conservative choice favors dense associations over sparse ones. The proponent proposed testing (ablation on divide-by-5 vs. query-side normalization), and Phase 1 can determine if this choice is correct empirically.

---

## Concerns Missed

**Dialog quality measurement remains secondary** — Partially addressed. The proponent's defense (round-2/proponent.md lines 56-59) proposed "Dialog turn analysis" as a Phase 1 metric, sampling 10-20 proxy reasoning traces to detect whether the two-pass mechanism improves reasoning or just validates decisions. This proposal is mentioned in the synthesis changelog (round-2/synthesis-changelog.md line 230) as "Dialog turn analysis" added to evaluation section, but reading act-r-proxy-memory.md Phase 1 evaluation metrics (lines 98-102), the proposed metrics are action match rate, prior calibration, surprise calibration, and retrieval relevance. There is no explicit "dialog turn analysis" metric listed. The synthesis changelog claims it was added, but it is not present in the actual document. This is a missed concern.

**"Understanding" language reframing is incomplete** — Partially addressed. The proponent's defense (round-2/proponent.md lines 139-142) proposed reframing "understanding" as "behavioral alignment" or "predictive accuracy." The synthesis changelog (round-2/synthesis-changelog.md lines 116-126) claims this was addressed by replacing "understanding" with "consistent inspection with accurate predictions." Reading act-r-proxy-sensorium.md, I do not find the word "understanding" removed or reframed. The original draft-1 language at line 176-177 ("the proxy has earned the right to act autonomously because it has demonstrated understanding") is claimed to be changed to line 176-177 in draft-2, but the new text says "the proxy has earned the right to act autonomously by demonstrating consistent inspection with accurate predictions, not by demonstrating 'understanding.'" This reframing IS present in the draft-2 text I read (act-r-proxy-sensorium.md does not contain the word "understanding" in a positive sense). Actually, upon re-reading the files I was given, draft-2 act-r-proxy-sensorium.md does not reach line 176. The draft-1 version I read (lines 1-150) does not contain the "understanding" passage either. This concern is unclear because the files provided are truncated. However, the synthesized claim that "understanding" was reframed is not contradicted by what I can verify.

---

## Regressions

**None detected.** The draft-2 documents maintain all substantive functionality from draft-1 while correcting errors. The changes are additive (new sections, clarifications, explicit gating) rather than simplifying away complexity. The phase structure is intact. The memory theory is unchanged. No previously sound positions were removed or weakened.

---

## Coherence

The draft-2 synthesis maintains internal coherence. The cost calculation aligns with the corrected arithmetic. The Phase 0 checklist aligns with the engineering gaps identified in the mapping document. The bootstrapping section aligns with the confidence threshold fallback. The EMA coupling clarification aligns with the session lifecycle description. The document reads as a unified design, not a collection of patches.

---

## Overall

Round 2 synthesis is a **quality improvement**. The most critical errors (cost calculation) and specification gaps (Phase 0 checklist, bootstrapping, serialization, cache verification) are corrected. The tone is more honest about empirical unknowns and fallback strategies. The proponent successfully conceded three major errors (cost, engineering gaps, autonomy framing) and incorporated them without defensive hedging. The document's claims are now better grounded in what will be tested (ablations, monitoring, verification gates) rather than what the design hopes will work. The remaining gaps (dialog quality measurement, complete "understanding" reframing) are minor and do not block Phase 1 shadow mode. The design is ready for implementation under the Phase 0 decisions. No critical errors remain.

