# Synthesis Changelog — Round 1

## Changes Made

### Noise parameter s = 0.25 (act-r.md)
**Reason:** Factcheck found s = 0.25 is not the ACT-R standard; proponent conceded.
**What changed:** Reframed s = 0.25 as a design choice, not a standard value. Added note that ACT-R tutorials use 0.2-0.5 and that the value needs empirical calibration. Updated the parameter table to show "Design choice" in the Source column.
**Anchor check:** Preserves the anchor's value choice; corrects the provenance claim.

### Retrieval threshold tau = -0.5 (act-r.md)
**Reason:** Factcheck found tau = -0.5 is not the ACT-R standard; proponent conceded.
**What changed:** Reframed tau = -0.5 as a design choice with rationale (admits slightly negative activation, appropriate for low-interaction systems). Updated parameter table Source column.
**Anchor check:** Preserves the anchor's value choice; corrects the provenance claim.

### d = 0.5 caveat for sparse interaction regimes (act-r.md)
**Reason:** HM concern #4; proponent partially conceded (defended power-law form, conceded exponent is unvalidated for this domain). Researcher confirmed the concern is legitimate.
**What changed:** Added "Caveat for agent systems" paragraph after "Why d = 0.5?" section. Acknowledges the empirical basis is high-volume corpora, that d = 0.5 is a principled starting point rather than validated parameter, and that calibration is planned for shadow mode.
**Anchor check:** Preserves the anchor's choice of d = 0.5 and its theoretical justification; adds appropriate epistemic humility without weakening the core argument.

### Anderson & Schooler event-based framing (act-r.md)
**Reason:** Logic critic non-sequitur #3 and factcheck partial confirmation. Proponent defended the event-based framing but conceded the mapping is looser than stated.
**What changed:** Added parenthetical note in "Interactions, Not Seconds" point 2 clarifying that "event-based" is a reasonable interpretation of Anderson & Schooler's methodology, not a direct quote. The primary units were days (NYT/email) and utterance intervals (speech).
**Anchor check:** Preserves the interaction-based time argument; adds precision about the source claim.

### Embedding dimensions inconsistent across documents (all four files)
**Reason:** Logic critic contradiction #1; proponent conceded. The mapping document's 5-dimension schema is canonical.
**What changed:** Harmonized all documents to the 5-dimension schema: situation, artifact, stimulus, response, salience. Removed the "upstream" dimension from the sensorium table (it was not in the mapping schema or implementation). Updated the root document's MemoryChunk to include `embedding_artifact`. The sensorium document now matches the mapping document exactly.
**Anchor check:** The anchor's mapping document already had 5 dimensions; this reconciles the other documents to match.

### Combined score normalization (act-r-proxy-mapping.md)
**Reason:** HM concern #3; proponent conceded the scale mismatch is real. Researcher found Park et al. (2023) uses min-max normalization for the same problem.
**What changed:** Added `normalize(B)` to the score formula with min-max scaling. Added `normalize_activation()` function to implementation. Added "Why normalization is needed" explanatory paragraph. Added Park et al. citation.
**Anchor check:** Refines the anchor's retrieval mechanism without changing its intent. The anchor's 0.5/0.5 weighting is preserved; normalization makes the weighting meaningful.

### Removed "explicit reinforcement" trace rule 3 (act-r-proxy-mapping.md)
**Reason:** HM concern #11; proponent conceded the rule is "a bias bomb." Researcher confirmed this is not standard ACT-R (traces are created by access, not outcome similarity).
**What changed:** Removed trace creation rule 3. Traces are now created only on chunk creation (rule 1) and retrieval (rule 2), matching standard ACT-R. Added note that these two rules match standard ACT-R.
**Anchor check:** The anchor included this rule; removing it is a substantive change. However, the proponent conceded it was dangerous and unspecified, and the researcher confirmed it departs from ACT-R without justification. Rules 1 and 2 are sufficient for the memory dynamics the anchor describes.

### Chunk creation for non-surprise gates clarified (act-r-proxy-mapping.md, act-r-proxy-memory.md)
**Reason:** Logic critic contradiction #4; proponent conceded the ambiguity.
**What changed:** Added explicit statement in the mapping document that every gate produces a chunk; non-surprise chunks have empty salience fields. Updated the session lifecycle STORE step to say "populate salience fields only if surprise was detected."
**Anchor check:** Clarifies rather than changes the anchor's intent. The mapping document always described per-gate chunks.

### Auto-approval tension resolved (act-r-proxy-memory.md, act-r-proxy-sensorium.md)
**Reason:** Logic critic contradiction #3; proponent defended but acknowledged the documents don't make the distinction explicit.
**What changed:** Added a note in the root document's "What Changes" section explicitly distinguishing EMA-based auto-approval (skips inspection) from two-pass auto-approval (completes inspection). The sensorium document's "Learned Attention Over Time" section now explains the distinction directly.
**Anchor check:** Preserves the anchor's critique of EMA-based auto-approval and the sensorium's argument for earned autonomy. Makes the distinction explicit rather than leaving it for readers to infer.

### Surprise mechanism expanded from binary to graded (act-r-proxy-sensorium.md, act-r-proxy-memory.md)
**Reason:** HM concern #7; proponent partially conceded (proposed confidence-delta threshold). Researcher found support in Bayesian surprise literature (Itti & Baldi 2009).
**What changed:** Surprise now triggers on action change (strong, 2 LLM calls) OR confidence delta > 0.3 (moderate, 1 LLM call). SurpriseDelta.magnitude updated to 1.0/0.5/0.0. Session lifecycle pseudocode updated. Sensorium document's "Surprise" section rewritten to describe the graded mechanism.
**Anchor check:** Extends the anchor's binary mechanism to capture more information. The anchor's core insight (salience comes from prior-posterior divergence) is preserved; the threshold is broadened.

### Two-pass delta noise acknowledged (act-r-proxy-sensorium.md)
**Reason:** HM concern #6; proponent defended the architecture but conceded the delta is noisy. Researcher confirmed temperature 0 non-determinism is well-documented.
**What changed:** Added "A note on signal quality" paragraph in the sensorium document after "The Delta" section, acknowledging that temperature 0 does not guarantee determinism and that the delta is an approximate signal.
**Anchor check:** Does not weaken the two-pass design; adds appropriate caveats.

### Cost model arithmetic corrected (act-r-proxy-memory.md)
**Reason:** Factcheck found G=10 and G=20 totals incorrect.
**What changed:** Removed the specific G=10 and G=20 rows from the summary tables (the detailed formula is present for readers to compute). Revised the cost model to acknowledge output tokens and cache-write premium as factors the input-focused model omits.
**Anchor check:** The anchor's cost model was illustrative, not contractual. Correcting errors and acknowledging omissions preserves credibility.

### 376-chunk capacity explained (act-r-proxy-memory.md)
**Reason:** Factcheck noted 200K/500 = 400, not 376; arithmetic basis unstated.
**What changed:** Explicitly stated the assumption: "reserving ~12,000 tokens for system prompt and gate content, the practical capacity is ~376 chunks."
**Anchor check:** Makes the anchor's implicit assumption explicit.

### "Deployed at scale" and Claude memory claims removed (act-r-proxy-mapping.md)
**Reason:** Factcheck found both claims unverifiable; proponent conceded. Researcher found Claude uses file-based memory, not activation-weighted retrieval.
**What changed:** Removed the sentence about Claude's persistent memory and "deployed at scale." Replaced with specific citations to published precedents: Park et al. (2023), HAI 2024 paper, Frontiers 2026 paper. The mapping document now cites these as "direct precedent in the research literature."
**Anchor check:** Replaces unverifiable claims with verifiable ones. Strengthens the argument.

### "Low-fan spreading activation" analogy softened (act-r-proxy-mapping.md, act-r-proxy-sensorium.md)
**Reason:** Logic critic non-sequitur #4 and HM concern #2; proponent conceded the phrasing overstates the mapping. Researcher confirmed averaging cosines does not produce the fan effect.
**What changed:** Removed "the equivalent of low-fan spreading activation" phrasing. The text now describes the intersection effect directly without claiming ACT-R equivalence. Added note in mapping document that multi-dimensional retrieval is a novel design choice without published validation, with ablation planned.
**Anchor check:** The anchor used "low-fan spreading activation" as analogy. The revision preserves the intersection idea while being honest about the mechanism.

### AutoDiscovery wording fix (act-r-proxy-sensorium.md)
**Reason:** Factcheck flagged "hypothesis ranking" as imprecise.
**What changed:** Changed "hypothesis ranking" to "guiding hypothesis exploration."
**Anchor check:** Minor wording fix; preserves the analogy.

### Evaluation metrics and ablation plan added (act-r-proxy-memory.md)
**Reason:** HM concern #1; proponent conceded.
**What changed:** Added concrete evaluation metrics (action match rate, prior calibration, surprise calibration, retrieval relevance) and ablation plan (multi-dim vs. single embedding, ACT-R decay vs. simple recency, two-pass vs. single-pass, normalized vs. single-signal retrieval) to the Migration Path section.
**Anchor check:** Extends the anchor's migration path with specifics it lacked. Does not change the phased approach.

### Embedding cost acknowledged (act-r-proxy-sensorium.md, act-r-proxy-memory.md)
**Reason:** HM concern #8; proponent conceded.
**What changed:** Added note in sensorium Implementation section about embedding costs (up to 5 calls per chunk plus retrieval-time embedding). Added E (embedding cost) to the cost model variable list with note that it is negligible vs. LLM calls.
**Anchor check:** Makes implicit costs explicit.

### Memory maintenance section added (act-r-proxy-mapping.md)
**Reason:** HM concern #10; proponent conceded.
**What changed:** Added "Memory Maintenance" section describing trace compaction, chunk pruning, and database maintenance.
**Anchor check:** New section addressing an operational gap the anchor did not address. Required for a system intended to run long-term.

### Cold start behavior specified (act-r-proxy-mapping.md)
**Reason:** HM concern #5; proponent defended the cold-start mechanism but conceded it was implicit.
**What changed:** Added "Cold Start Behavior" section making explicit that zero chunks = escalate everything = correct cold-start behavior.
**Anchor check:** Makes explicit what the anchor left implicit.

### EMA separation nuanced (act-r-proxy-mapping.md)
**Reason:** Logic critic unstated assumption #5; proponent defended indirect information flow but conceded the separation was too rigid.
**What changed:** Added note in "Replacing the Current Confidence Model" section that EMA trends flow indirectly into decisions (more corrections produce more correction chunks) and may trigger operational actions.
**Anchor check:** Preserves the anchor's separation of monitoring and decision; adds nuance about information flow.

### Cross-task learning nuanced (act-r-proxy-memory.md)
**Reason:** Logic critic unstated assumption #3; proponent defended with structural filtering argument.
**What changed:** Added sentence in the Concurrency section noting that cross-task priming depends on the tasks and that structural filtering mitigates contamination.
**Anchor check:** Preserves the anchor's FIFO design; adds acknowledgment of the concern.

### KV cache section framing adjusted (act-r-proxy-memory.md)
**Reason:** HM concern #9; proponent conceded the cost model should be separated from core economics.
**What changed:** Added framing sentence at section start: "The core design (text retrieval without caching) stands on its own; this section describes what becomes possible when the proxy is migrated to direct API calls."
**Anchor check:** The KV cache section is preserved in full (it was always labeled future work). The framing change makes the boundary clearer.

### Cost model revised for completeness (act-r-proxy-memory.md)
**Reason:** Logic non-sequitur #2; proponent conceded output tokens and cache-write premium were omitted.
**What changed:** Added output tokens (O), cache-write premium (w), and embedding cost (E) to the cost model variables. Added explicit note that the model focuses on input token-equivalents and that full cost comparison must include output tokens. Removed the summary table with incorrect G=10/G=20 numbers.
**Anchor check:** The anchor's cost argument was directionally correct but numerically incomplete. The revision is honest about what the model covers.

### New references added (act-r-proxy-mapping.md, act-r-proxy-memory.md)
**Reason:** Researcher found direct precedents (HAI 2024, Frontiers 2026, Park et al. 2023).
**What changed:** Added References sections to mapping and memory documents citing Park et al. (2023), Nuxoll & West (HAI 2024), and Bhatia et al. (Frontiers 2026).
**Anchor check:** Strengthens the anchor's case with published validation of the core pattern.

## Changes Rejected

### "Corrections are more informative" is a non sequitur (Logic non-sequitur #1)
**Reason:** Proponent defense was sound. The argument is not that more text = better embeddings; it is that error-describing text is inherently more specific than success-confirming text. Tightened the phrasing from "richer associations" to "more specific associations" but preserved the claim.

### The LLM may not produce meaningfully different Pass 1 vs Pass 2 outputs (Logic unstated assumption #1)
**Reason:** Proponent defense was sound. Conditioning on presence/absence of a multi-page artifact is a substantive input difference, not a prompt phrasing difference. This is how conditional generation works. The concern is valid as a monitoring item but not as a design objection.

### Cosine similarity is not a valid substitute for spreading activation (Logic unstated assumption #2)
**Reason:** Proponent defense was sound with the concession on "low-fan" phrasing. The documents explicitly state this is a replacement, not a replication. The "low-fan" analogy was softened (see Changes Made), but the substitution itself is preserved.

### The activation threshold may not be self-regulating (Logic unstated assumption #4)
**Reason:** Proponent defense was directionally correct: a fixed threshold on a decaying function limits loading as population grows. Added note that tau may need adjustment, but did not add analysis of specific interaction regimes — this is a calibration question for shadow mode.

### Multi-dimensional embedding retrieval needs validation (HM #2)
**Reason:** The concern is valid but the response is already covered: added ablation plan and note that this is a novel design choice. The architecture is preserved because the ablation will resolve the question empirically.

### The KV cache section should be removed or shortened (HM #9)
**Reason:** Proponent defense was sound. The section demonstrates architectural continuity between current and future designs. It is clearly labeled as future work. The framing was adjusted to separate it from core economics.

## Net Assessment

This draft is closer to the anchor's intent than draft-0. The core architecture is unchanged: ACT-R activation memory, two-pass prediction, structural filtering + semantic ranking, EMA as monitoring. The changes fall into three categories:

1. **Corrections**: factual errors fixed (parameter provenance, cost arithmetic, unverifiable claims), embedding schema harmonized, chunk creation ambiguity resolved.

2. **Strengthening**: normalization added to the combined score, evaluation metrics and ablation plan specified, memory maintenance addressed, cold start behavior made explicit, published precedents cited.

3. **Epistemic honesty**: d = 0.5 acknowledged as starting point rather than validated parameter, multi-dimensional embeddings acknowledged as novel/unvalidated, two-pass delta acknowledged as noisy signal, cost model acknowledged as input-focused.

No sections were removed. No claims were weakened that the proponent successfully defended. The document is more precise about what is established, what is novel, and what needs empirical validation.
