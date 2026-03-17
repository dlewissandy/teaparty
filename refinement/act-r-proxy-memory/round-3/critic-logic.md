# Logical Review -- Round 3

## Status of Prior Concerns

All contradictions, non sequiturs, and unstated assumptions raised in rounds 1 and 2 have been resolved or explicitly documented. Specifically:

- Embedding schema: harmonized to 5 dimensions across all documents.
- Auto-approval tension: resolved with explicit distinction between EMA-based (skips inspection) and two-pass (completes inspection).
- Tau semantics: corrected to threshold on raw B, composite for ranking only.
- Cosine averaging: corrected to divide by total dimensions (5), not populated dimensions.
- REINFORCE broadcast: removed; traces created only on creation and retrieval.
- salient_percepts: added to dataclass, SQL schema, and record_interaction.
- Chunk creation for non-surprise gates: explicitly documented.
- Cost model scope: acknowledged as input-token-focused.
- Parameter provenance: design choices distinguished from ACT-R standards.
- Cold start argument: tightened to mechanical comparison.

## New Issues

### 1. The soft-threshold equation is offered as a gating function but the implementation uses a hard threshold

The act-r.md retrieval section (lines 119-127) presents the soft-threshold probability equation `P(retrieve) = 1 / (1 + exp(-(B - tau) / s))` and states: "This soft-threshold equation can serve as the gating function on raw B, providing probabilistic filtering before ranking."

The mapping document's `retrieve()` function (lines 354-359) applies a hard threshold: `if b > tau: survivors.append(...)`. This is a deterministic cutoff, not a probabilistic one. A chunk with B = -0.51 is always excluded; a chunk with B = -0.49 is always included.

The round 2 changelog states: "The soft-threshold retrieval probability equation is now referenced as the gating function on raw B, resolving the logic critic's concern that it was presented but never implemented." But the implementation still uses a hard threshold. The prose says "can serve as"; the code says `if b > tau`. This is a weaker version of the round 2 contradiction (where tau was applied to the wrong quantity). The quantity is now correct, but the mechanism (hard vs. soft) is still inconsistent between theory and implementation.

This is a minor consistency issue. The hedge "can serve as" acknowledges optionality, and either mechanism is defensible. But the round 2 changelog claims this was resolved, and it was not fully resolved -- it was shifted from "wrong quantity" to "wrong mechanism."

### 2. Noise is added to the composite score, but the theory says noise controls retrieval probability

The act-r.md noise section (lines 96-106) describes noise as governing retrieval via the logistic soft threshold. The composite_score function (mapping document, line 333) adds noise as a random offset to the ranking score: `return activation_weight * b_norm + semantic_weight * sem + noise`. These are different roles. In the theory, noise determines whether a near-threshold chunk is retrieved at all (via the sigmoid). In the implementation, noise perturbs the ranking order among already-admitted chunks.

Both roles are reasonable. But the document presents one theory of noise and implements another. The noise parameter s = 0.25 was chosen as a design value for retrieval-probability noise (act-r.md line 103: "low enough to keep retrieval mostly deterministic while allowing occasional exploration"). When the same s = 0.25 is used as additive ranking noise, its effect is different: on a composite score where activation and similarity each contribute roughly [0, 0.5], a logistic noise sample with scale 0.25 can produce values up to ~1.5 (rare) or commonly ~0.3, which is large enough to dominate the ranking signal. The parameter value was justified for one role and deployed in another.

This is not a contradiction in the logical sense -- the design works either way -- but it is a mismatch between the stated justification for s = 0.25 and its actual effect in the implementation.

## Assessment

The document set is logically coherent. The core argument holds: ACT-R base-level activation provides the forgetting curve, vector embeddings provide context sensitivity as a replacement for spreading activation, two-pass prediction provides the salience signal, and the three components combine into a retrieval system that serves the proxy's needs. The migration path is concrete, the evaluation criteria are specified, and the epistemic claims are appropriately scoped.

The two issues above are consistency gaps between the theory document's description of noise and the retrieval threshold, and the implementation's use of both. They are implementation-level details that would be resolved naturally during coding (choose hard or soft threshold; choose where noise enters the pipeline). Neither affects the soundness of the design.

No new contradictions, non sequiturs, or unstated assumptions.
