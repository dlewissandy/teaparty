# Hiring Manager Review -- Round 3

## Status: Ready to fund Phase 1

The round 2 fixes landed cleanly. The REINFORCE broadcast removal, tau semantics separation, cosine averaging correction, salient_percepts schema fix, fabricated citation corrections, and evaluation go/no-go criteria all address the concerns they were meant to address. The documents are now internally consistent, honest about what is established vs. novel, and have a concrete evaluation plan with decision rules.

I have one new concern and two minor observations. None block funding.

---

## New Concern

### 1. The retrieval function computes activation twice per chunk
[feasibility] The `retrieve()` function in act-r-proxy-mapping.md computes `base_level_activation()` in Stage 1 (filtering by tau) and then `composite_score()` calls `base_level_activation()` again in Stage 2 (ranking). For a candidate set of N chunks, this is 2N activation computations instead of N. The Stage 1 loop already has the B values -- the `survivors` list stores `(b, c)` tuples -- but `composite_score()` recomputes B from scratch instead of accepting the precomputed value. This is not a design problem; it is a minor implementation inefficiency in the sketch. Mention it so the implementer passes the precomputed B into the scoring function rather than rediscovering it during implementation.

---

## Minor Observations

### 2. The cost model in the KV cache section still presents specific numbers
[evaluation] The cost model (act-r-proxy-memory.md, "Cost Model") now appropriately caveats that it focuses on input token-equivalents and omits output tokens. However, the G=5 worked example and the savings table (14% at 3 gates, 24% at 5, 30% at 10, 34% at 20) still present as concrete projections despite being built on three unverified assumptions (CLI cache compatibility, cache TTL survival, no per-call prompt variation). The "Verification Needed" section flags these assumptions explicitly, which is good -- but a reader skimming the savings table without reading the verification section will take the numbers as reliable. Consider adding a one-line caveat to the table itself, or moving the table below the verification section so readers encounter the caveats first. This is a presentation issue, not a factual one.

### 3. The soft-threshold probability equation has an ambiguous role
[missing] The act-r.md retrieval section now says the soft-threshold equation `P(retrieve) = 1 / (1 + exp(-(B - tau) / s))` "can serve as the gating function on raw B, providing probabilistic filtering before ranking." The word "can" leaves it ambiguous whether the implementation should use this probabilistic gate or the hard threshold `B > tau` that the `retrieve()` function actually implements. Both are defensible choices -- hard threshold is simpler, soft threshold is more faithful to ACT-R. But the theory document presents the soft threshold as the model and the implementation uses a hard threshold, with "can serve as" bridging the gap without resolving it. The implementer will need to choose. A one-sentence recommendation in the mapping document (e.g., "Phase 1 uses the hard threshold for simplicity; the soft threshold is available for Phase 2 if probabilistic retrieval proves useful") would close this.

---

## What Improved Since Round 2

The fabricated citations are corrected with full author names, DOIs, and accurate descriptions of what each paper actually contributes. The Meghdadi et al. description now honestly notes its psycholinguistics focus and scopes the relevance to the methodological pattern. The REINFORCE removal is clean -- the pseudocode, the trace rules, and the explanatory note all agree that loading into the prompt prefix is not retrieval-and-use. The tau two-stage separation (filter on raw B, rank on composite) resolves a real bug that would have surfaced during implementation. The cosine averaging fix (divide by 5 always) produces the breadth-rewarding behavior the prose describes. The go/no-go criteria (70% action match, 95% ablation thresholds, 50-interaction minimum, ambiguity extension to 100) are concrete enough for someone other than the designer to run the evaluation.

## Bottom Line

Fund Phase 1. The design is sound, the evaluation plan is concrete, the epistemic claims are honest, and the remaining issues are implementation details that belong in a code review, not a design review. The two-stage migration (shadow mode with ablations, then dialog mode) is the right approach -- it lets the system prove itself before taking over decisions. The ablation plan will resolve the open questions about whether multi-dimensional embeddings and ACT-R decay earn their complexity. Ship it.
