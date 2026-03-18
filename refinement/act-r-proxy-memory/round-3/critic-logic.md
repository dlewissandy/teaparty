# Logical Review — Round 3

## New Issues

### 1. Cosine-divide-by-5 penalty contradicts documented retrieval patterns

Act-r-proxy-mapping.md (lines 140-141) scores chunks by averaging cosine similarity across all 5 dimensions, dividing by 5 regardless of how many dimensions are populated. This means a chunk matching strongly on situation alone (sim=0.9) scores (0.9 + 0 + 0 + 0 + 0) / 5 = 0.18. A chunk matching weakly on all five dimensions (each sim=0.4) scores 0.4. The system mathematically heavily penalizes sparse matching.

Yet act-r-proxy-sensorium.md (line 155) lists "Situation alone: What happens at PLAN_ASSERT?" as a valid retrieval pattern. The design permits the query but the scoring function penalizes its results. The document states this "rewards breadth of matching," but does not acknowledge that breadth-weighting makes situation-only retrieval nearly impossible to win. Either situation-only retrieval is intended (and the cosine division should be by populated dimensions only, not by 5) or it is not intended (and sensorium.md should remove it from the valid patterns list). The contradiction is unresolved.

### 2. Activation threshold tau = -0.5 inverts ACT-R semantics

Act-r.md (line 119) uses tau = -0.5, justified as "desirable in a low-interaction system where useful chunks may hover near zero activation." This admits chunks with negative activation — below the retrieval threshold in standard ACT-R.

In ACT-R, the retrieval threshold (default tau = 0) is where activation transitions from "below threshold, effectively forgotten" to "above threshold, accessible." The document adapts this downward to tau = -0.5, expanding the accessible range to include "effectively forgotten" chunks.

This is a defensible design choice for low-volume systems. The rationale is sound. But it creates a semantic mismatch: the proxy's "active memory" (chunks above -0.5) includes chunks that ACT-R would classify as "effectively forgotten" (chunks below 0). The proxy's memory accessibility model no longer aligns with the theory it claims to implement.

The chunk retention policy (act-r-proxy-mapping.md, line 200) archives chunks that have been below tau for N consecutive sessions. If tau = -0.5 admits "effectively forgotten" chunks into retrieval, the archival threshold should reflect this divergence from ACT-R semantics. The document does not specify how N interacts with the inverted threshold. Is a chunk below -0.5 considered "below threshold" for archival purposes? If so, archival contradicts retrieval (retrieval includes negative B, archival excludes it). If not, the distinction between archival and retrieval becomes semantic only.

### 3. Embedding model migration lacks policy

Act-r-proxy-mapping.md (line 273) notes the embedding_model column exists "enabling re-embedding migration when the model changes." But the document never specifies the migration policy. If the embedding model is upgraded (e.g., from text-embedding-3-small to text-embedding-3-large), what happens to existing chunks?

Option A: Re-embed all chunks with the new model (expensive, e.g., 1000 chunks × 5 dimensions = 5000 embedding calls). Option B: Keep old chunks with old embeddings, only use new model for new chunks (semantic inconsistency in retrieval). Option C: Defer re-embedding until chunks are retrieved (performance unpredictable, mixing old and new embeddings in same query).

The retrieval function (act-r-proxy-mapping.md, line 333) assumes context_embeddings are generated with the same model as chunk embeddings: `cosine_similarity(chunk_vec, context_vec)`. Mixing embedding models produces meaningless cosine similarities. This is not a theoretical problem; it is a data quality issue that must have an explicit policy before production use.

### 4. Interaction counter race condition in concurrent dispatch

Act-r-proxy-memory.md (line 149) states "The proxy does not split into parallel instances. It is one brain with one memory and one interaction counter." The design uses a FIFO queue to serialize gate processing.

But act-r-proxy-memory.md (line 90) lists "Concurrency control for interaction counter" as a Phase 0 design decision requiring specification. The current implementation (act-r-proxy-mapping.md, lines 418-420) shows `record_interaction()` calling `increment_interaction_counter()`. In a multi-process or multi-thread environment, reading the counter, incrementing, and writing back is a race condition unless wrapped in a database transaction with proper isolation.

The document acknowledges this gap ("specify transaction semantics and isolation levels") but defers it without guidance. If concurrent gates fire before the counter increment from gate A is committed, gate B and gate A could both read counter = N, both increment to N+1, and both write N+1 back. Traces would have the same age despite being created at different times, breaking the temporal ordering assumption in the decay formula.

The SQLite implementation (act-r-proxy-mapping.md, lines 266-270) uses a single proxy_state table with interaction_counter as a row. SQLite's default transaction isolation is sufficient for simple single-row increments if each process wraps the read-increment-write in a transaction. But the document does not specify this. Implementation code must use `BEGIN IMMEDIATE` or similar to prevent dirty reads.

### 5. Autonomy criterion conflates prediction accuracy with inspection (persists from Round 2)

Act-r-proxy-sensorium.md (line 175-179) grants autonomy when "the prior is specific enough that the posterior rarely diverges." The document claims the proxy "has demonstrated that it attends to what the human would attend to, inspects the artifact through two-pass prediction."

But posterior agreement with prior is evidence of prediction accuracy, not evidence of this-decision inspection. A system with a perfectly accurate prior (learned from previous decisions) will produce posteriors that agree with the prior by definition. The posterior agrees because the prior is accurate, not because the proxy inspected and confirmed.

The sensorium document acknowledges this distinction (line 212): "A proxy that auto-approves because its prior correctly anticipated the artifact would have no issues, and the posterior confirmed it, has demonstrated accurate prediction through systematic inspection." But the autonomy criterion (posterior agreement) does not distinguish "the proxy correctly predicted because it examined the artifact features" from "the proxy correctly predicted because its learned prior is accurate and needs no artifact revision."

A fallback mitigation would be to require that posterior reasoning cite specific artifact features. But the current design does not enforce this. The posterior is free-text LLM output. The proxy could generate output like "I predicted approve before reading the artifact, and the artifact does not change this prediction" without examining the artifact at all.

This is a known limitation of the design. It is explicitly acknowledged in the document. But it remains a logical gap: the autonomy criterion (posterior agreement) is insufficient to establish the inspection property it claims to measure.

## Previously Raised Issues Still Unresolved

### EMA reintegration through indirection (Round 2)

Act-r-proxy-mapping.md (line 180) states EMA and memory operate on "separate data paths." But act-r-proxy-memory.md (line 204) describes the causal path: "When upstream quality degrades, the memory system responds through its normal operation. More correction chunks accumulate, shifting retrieval toward skeptical patterns."

This is integration by indirection. EMA detects degradation → more correction chunks are created → retrieval favors skepticism. The two systems do not share state, but their behavior outcomes are coupled. The document frames this as separation ("they operate on separate data paths") while describing integration ("EMA trends flow into decisions through the memory system").

The contradiction between "separated" and "functionally integrated" is asserted but not resolved. Acceptable resolutions would be: (a) acknowledge they are integrated and describe the coupling explicitly, or (b) show that the coupling is weak enough to be negligible. The document does neither. It claims separation while describing integration.

## Convergence Assessment

**Overall coherence: HIGH.** The document set is logically sound across most dimensions. The major contradictions from Rounds 1-2 have been resolved or properly scoped:

- REINFORCE removal is explicit.
- Dialog equivocation is acknowledged as a design choice, not a logical error.
- Confidence measurement is flagged as unstable but included in Phase 1 validation.
- Sparse signal training is acknowledged and measured in shadow mode.
- EMA integration is described in terms of causal flow (though still framed as separation).

**Remaining issues: IMPLEMENTATION AND EDGE CASE LEVEL.** The new issues (Round 3) are not fundamental contradictions but design decisions that lack explicit specification:

- Cosine-divide-by-5 vs. situation-only retrieval: minor, addressable by clarifying intent.
- Tau = -0.5 semantic mismatch: minor, aligns with the stated reason (low-volume systems). The design trades off semantic alignment with ACT-R for practical feasibility.
- Embedding model migration: important for production, but specification is deferred to implementation, which is acceptable.
- Interaction counter race condition: important for correctness, but specification is deferred to Phase 0, which is correct.
- Autonomy criterion logically insufficient: acknowledged limitation, not a flaw.

**Diminishing returns:** Further critique would target design assumptions that the document explicitly marks for empirical validation: whether confidence thresholds are calibrable, whether d=0.5 is optimal for sparse time series, whether multi-dimensional embedding adds enough value to justify the cost. These are empirical questions, not logical ones. Logical critique of a design that acknowledges its empirical assumptions is diminishing returns.

**Recommendation:** The document is ready for Phase 0 specification. All open design decisions are properly identified. The remaining logical coherence improvements require empirical data from shadow mode, not further theoretical critique.
