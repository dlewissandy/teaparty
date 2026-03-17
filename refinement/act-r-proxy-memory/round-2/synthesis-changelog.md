# Synthesis Changelog — Round 2

## Changes Made

### Fabricated citations replaced with verified citations (all documents with references)
**Reason:** Factcheck found "Nuxoll & West (2024)" and "Bhatia et al. (2026)" are fabricated author names. Researcher confirmed correct citations with DOIs. Proponent conceded this is indefensible.
**What changed:**
- "Nuxoll, A., & West, R. (2024). HAI '24" replaced with "Honda, Y., Fujita, Y., Zempo, K., & Fukushima, S. (2025). HAI '25. DOI: 10.1145/3765766.3765803" in all documents.
- "Bhatia, S., et al. (2026). Frontiers" replaced with "Meghdadi, M., Duff, J., & Demberg, V. (2026). Frontiers in Language Sciences, 5. DOI: 10.3389/flang.2026.1721326" in all documents.
- Meghdadi et al. description revised to accurately note its psycholinguistics focus (associative priming in the Lexical Decision Task) and that the relevance is the LM-embedding-as-ACT-R-association-metric methodological pattern, not agent memory per se.
- "Park, S." corrected to "Park, J.S." in all documents.
**Anchor check:** The anchor did not include these citations. The corrected citations support the same claims the draft-1 citations were intended to support. No change to the anchor's argument.

### REINFORCE broadcast step removed from session lifecycle (act-r-proxy-memory.md)
**Reason:** Both critics and the researcher independently confirmed this is not standard ACT-R. In ACT-R, a chunk is reinforced only when specifically retrieved for a task and actively referenced by a production rule (ACT-R Tutorial Unit 4; Anderson & Lebiere 1998 Ch. 4). Loading chunks into the prompt prefix is not retrieval-and-use. The broadcast REINFORCE creates a rich-get-richer feedback loop that undermines the "drifting interests" behavior the design claims to produce.
**What changed:**
- Removed "REINFORCE: add trace N to each loaded chunk" from the session lifecycle pseudocode.
- Added explanatory note after the pseudocode documenting why the step was removed and citing the ACT-R standard.
- Updated the trace creation rules in act-r-proxy-mapping.md to explicitly state that loading into prompt prefix is not retrieval-and-use, with ACT-R Tutorial Unit 4 citation.
**Anchor check:** The anchor's pseudocode included the REINFORCE step. This is a substantive removal, but it is well-justified: the step departs from ACT-R without justification and creates feedback dynamics that undermine the anchor's own design goals. Creation and retrieval traces (rules 1 and 2) are sufficient.

### Tau semantics fixed: threshold on raw B, composite for ranking only (act-r.md, act-r-proxy-mapping.md)
**Reason:** Both critics identified independently that tau was applied to the composite score (normalized B + cosine + noise) rather than to raw activation B. The theory document defines tau as an activation threshold; the implementation used it as a composite-score threshold. These are different quantities on different scales. Proponent conceded.
**What changed:**
- act-r.md: Retrieval section now explicitly states "tau is a threshold on raw B" and explains the two-stage design (filter by activation, then rank by composite).
- act-r-proxy-mapping.md: Retrieval rewritten as two stages: Stage 1 filters by raw B > tau; Stage 2 computes composite score for ranking over survivors only. The `retrieve()` function implementation reflects this separation.
- The soft-threshold retrieval probability equation (`P(retrieve) = 1 / (1 + exp(-(B - tau) / s))`) is now referenced as the gating function on raw B, resolving the logic critic's concern that it was presented but never implemented.
**Anchor check:** The anchor applied tau to the composite score (an implementation detail, not an intentional design choice). The fix aligns the implementation with ACT-R's theoretical semantics while preserving the anchor's intent of filtering low-activation chunks before ranking.

### Cosine averaging fixed: divide by total dimensions, not populated dimensions (act-r-proxy-mapping.md)
**Reason:** Both critics identified that averaging over populated dimensions only does not produce the claimed intersection effect. A chunk matching well on 2/2 dimensions (avg 0.85) outscores one matching moderately on 5/5 (avg 0.30). Proponent conceded and recommended dividing by total dimensions (5) always.
**What changed:**
- `retrieval_score()` renamed to `composite_score()` for clarity, now divides by `TOTAL_EMBEDDING_DIMENSIONS` (5) instead of `len(similarities)`.
- Module-level constant `TOTAL_EMBEDDING_DIMENSIONS = 5` added.
- Docstring corrected: removed false "intersection effect" claim from the old formulation. Now accurately states that dividing by total dimensions rewards breadth of matching.
- Prose in the retrieval section updated to describe the corrected aggregation.
- Sensorium document updated to reference the corrected aggregation.
**Anchor check:** The anchor's prose described the intersection effect but the implementation (averaging over populated dimensions) did not produce it. The fix makes the implementation match the anchor's stated intent.

### salient_percepts added to dataclass, SQL schema, and record_interaction (act-r-proxy-mapping.md)
**Reason:** Logic critic found that `salient_percepts` appears in prose examples and the sensorium document but was absent from the MemoryChunk dataclass, SQL schema, and `record_interaction()` function. Proponent conceded this is a consistency bug.
**What changed:**
- Added `salient_percepts: list[str]` to the MemoryChunk dataclass.
- Added `salient_percepts TEXT DEFAULT '[]'` column (JSON array of strings) to the SQL schema.
- Added `salient_percepts: list[str] | None = None` parameter to `record_interaction()`.
- Field is populated only when surprise is detected (strong or moderate), consistent with the graded surprise mechanism.
**Anchor check:** The anchor's chunk examples included `salient_percepts`. This fix adds the missing implementation for a field the anchor intended to be present.

### Evaluation go/no-go criteria with thresholds and sample sizes added (act-r-proxy-memory.md)
**Reason:** HM concern that evaluation metrics have no success thresholds or sample size requirements. Without go/no-go criteria, shadow mode produces data nobody knows how to interpret. With 50-200 lifetime interactions, statistical power is a real constraint. Proponent conceded.
**What changed:**
- Added "Go/no-go criteria for Phase 2 transition" subsection under shadow mode evaluation:
  - Minimum sample: 50 gate interactions spanning 3+ task types and 4+ CfA states.
  - Timeline estimate: ~3-5 weeks at 5-10 gates/session, 2-3 sessions/week.
  - Action match rate threshold: >= 70% for go, < 60% for rethink, 60-70% for investigation.
  - Multi-dimensional vs. single-embedding: if single achieves >= 95% of multi-dimensional match rate, simplify.
  - ACT-R decay vs. simple recency: same 95% threshold.
  - Ambiguity rule: extend to 100 interactions if ambiguous at 50; default to simpler configuration if still ambiguous.
**Anchor check:** The anchor's migration path had no evaluation criteria. This addition fills a gap without changing the phased approach.

### Upstream context retrieval pathway documented (act-r-proxy-sensorium.md)
**Reason:** HM concern that upstream context is listed as a percept the proxy senses but has no retrieval pathway after the "upstream" embedding dimension was removed in draft-1. Proponent clarified it enters through artifact and stimulus embeddings but this was unstated.
**What changed:**
- Added "Note on upstream context" paragraph in the sensorium's Problem section, explaining that upstream context is passed as raw text in Pass 2, enters memory through the artifact and stimulus embeddings, and that a dedicated dimension was considered but removed because it overlapped without adding discriminating power.
**Anchor check:** The anchor's sensorium had 6 dimensions including upstream; the mapping document had 5. Draft-1 harmonized to 5 but left the gap undocumented. This addition makes the design decision explicit.

### Query-dependent normalization behavior documented (act-r-proxy-mapping.md)
**Reason:** Logic critic identified that min-max normalization over the candidate set makes the activation/similarity balance query-dependent. Proponent defended this as correct behavior but agreed it should be documented.
**What changed:**
- Added paragraph after the normalization explanation noting that the effective influence of the 0.5/0.5 weights varies by query, explaining when semantic relevance vs. activation dominates, and characterizing this as a feature (when candidates have similar activation, relevance should dominate).
**Anchor check:** Additive documentation of an existing mechanism. No design change.

### Cold start argument tightened (act-r-proxy-mapping.md)
**Reason:** Logic critic argued the cold-start section uses its own conclusion as evidence. Proponent defended that the claim is narrower than the critic reads it — about mechanical behavior, not the contested broader conclusion.
**What changed:**
- Revised the cold-start comparison to focus on the mechanical difference (dialog producing structured chunks with embeddings vs. single binary outcome) without claiming the broader conclusion about chunks being "better."
**Anchor check:** The anchor's cold start behavior was implicit. The revision makes it explicit with tighter argumentation.

## Changes Rejected

### Remove the confidence-delta surprise trigger (logic critic unstated assumption #4)
**Reason:** The logic critic questions whether LLM confidence values are calibrated enough to threshold on. The proponent's defense is sound: the threshold is a starting heuristic to be calibrated in shadow mode, and the fallback to binary-only is explicitly available. The sensorium document now carries the appropriate caveat about calibration. The graded mechanism captures real information (large confidence shifts without action changes) that the binary mechanism would lose. Keeping it with the caveat is better than removing it.

### Remove the "more informative" cold-start claim entirely (logic critic non-sequitur #3)
**Reason:** The logic critic's point about circularity was addressed by tightening the argument to focus on mechanical differences rather than the contested broader conclusion. The narrower claim (richer interaction data per gate) is mechanically true and does not depend on the overall ACT-R-vs-EMA conclusion.

### Make normalization absolute rather than query-dependent (logic critic unstated assumption #1)
**Reason:** Proponent's defense was sound. Query-dependent normalization answers the right question (how does this chunk compare to other candidates for this query?) and Park et al. (2023) use the same approach. The behavior when candidates have similar activation (semantic relevance dominates) is correct. Documented as a note rather than changed.

### The LLM may override retrieved memories with pretrained priors (logic critic unstated assumption #2)
**Reason:** Proponent's defense was sound. LLMs condition strongly on in-context examples — this is the basis of few-shot prompting and RAG. Specific episodic examples consistently override general pretrained dispositions. The edge case of sparse/contradictory memories is the cold-start problem, which is already addressed. This is a monitoring concern, not a design flaw.

### Short text fragments may not produce useful embeddings (logic critic unstated assumption #3)
**Reason:** Proponent's defense was sound. Modern embedding models are specifically trained and evaluated on short text pairs (STS benchmark, MTEB). The situation embedding ("PLAN_ASSERT security") is the weakest case, but it is also covered by structural filtering (exact SQL match). The dimensions where embedding quality matters most (artifact, response, salience) contain natural language sentences or paragraphs.

## Net Assessment

This draft addresses the six critical fixes identified for round 2:

1. **Fabricated citations** — replaced with verified citations (Honda et al. 2025, Meghdadi et al. 2026, Park J.S. et al. 2023).
2. **REINFORCE broadcast** — removed from session lifecycle; chunks get traces only on creation and retrieval, matching standard ACT-R.
3. **Tau semantics** — threshold on raw B for filtering; composite score for ranking only.
4. **Cosine averaging** — divide by total dimensions (5), not populated dimensions.
5. **salient_percepts** — added to dataclass, SQL schema, and record_interaction.
6. **Evaluation go/no-go** — concrete thresholds, sample sizes, and decision rules added.

Additional changes address the remaining HM and logic critic concerns (upstream context pathway, query-dependent normalization documentation, cold-start argument tightening). The core architecture remains unchanged: ACT-R activation memory, two-pass prediction, structural filtering + semantic ranking, EMA as monitoring. No sections were removed. The voice and structure are preserved.
