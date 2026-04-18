# ACT-R Adaptations for TeaParty

How TeaParty's proxy memory system adapts ACT-R declarative memory for agent gate decisions. This document covers only where we depart from vanilla ACT-R. For the theory, equations, and standard parameter values, see [research/act-r.md](../../../research/act-r.md).

Related:
- [memory.md](memory.md) — motivation and migration plan
- [mapping.md](mapping.md) — chunks, traces, retrieval implementation
- [sensorium.md](sensorium.md) — two-pass prediction and learned attention
- [../index.md](../index.md) — conceptual design

---

## Interactions, Not Seconds

In ACT-R, `t` in the base-level activation equation is measured in seconds. We measure `t` in **interactions**: gate decisions, dialog turns, observations. Each interaction advances the clock by 1.

**Between sessions, nothing happens.** If the agent handles 5 decisions on Monday and none until Thursday, wall-clock decay would erode Monday's memories over 3 idle days. Interaction-based decay does not advance. No interactions means no decay, which is correct because nothing happened to make the memories less relevant.

**Anderson & Schooler's empirical basis is event-based.** Their 1991 analysis measured word *occurrences* in newspaper headlines, child-directed speech, and email. The power-law pattern they found was in events (how many headlines ago did this word last appear?), not in seconds. The environment's statistical structure is event-based. So should the memory system's. (Note: their primary unit of analysis was days for NYT/email and utterance intervals for speech. The "event-based" framing is a reasonable interpretation of their methodology, not a direct quote from the paper.)

**Experience scales with activity, not calendar time.** An agent that handled 100 interactions over a busy week has far more trace accumulation than one that handled 5 over the same calendar period. The memory should reflect *experience*, not elapsed time.

---

## Parameter Choices

We depart from ACT-R defaults for noise and retrieval threshold.

| Parameter | ACT-R Default | Our Value | Rationale |
|-----------|---------------|-----------|-----------|
| Decay (d) | 0.5 | **0.5** | No departure. Empirically validated. |
| Noise (s) | NIL (disabled) | **0.08** | Calibrated so noise std dev (~0.145) stays below typical signal differences (~0.3). Perturbs ranking without dominating it. Validated via noise-scale sensitivity analysis in the ablation harness. |
| Retrieval threshold (tau) | 0 | **-0.5** | Admits chunks with slightly negative activation. Desirable in a low-interaction system (50-200 lifetime interactions) where useful chunks may hover near zero. Needs empirical calibration. |

**Caveat on d = 0.5.** Anderson & Schooler's corpora are high-volume streams (thousands of observations). Proxy gate interactions are sparse — perhaps 50-200 total lifetime interactions. The power-law form is the right functional shape, and d = 0.5 produces moderate decay. But whether 0.5 is optimal for this interaction regime is an open empirical question.

---

## Context Sensitivity via Embeddings

ACT-R uses **symbolic spreading activation** for context sensitivity: activation spreads from the current goal through associative links between chunks. The spread depends on fan (how many chunks share an association) and source activation.

We replace this with **vector embeddings and cosine similarity**. Each chunk has up to 5 independent embedding dimensions (situation, artifact, stimulus, response, salience). At retrieval, cosine similarity between query embeddings and chunk embeddings provides the context-sensitivity signal.

This is a fundamental departure. ACT-R's spreading activation is symbolic, discrete, and structure-aware. Cosine similarity over embeddings is continuous, learned, and structure-blind. The trade-off: we lose the ability to reason about structural relationships between chunks, but we gain the ability to match on semantic meaning without manually defining associative links.

---

## Two-Stage Retrieval

ACT-R retrieves the single chunk with highest activation above threshold. We retrieve a **ranked set** using a two-stage process:

1. **Activation filter**: all chunks with B > tau survive (standard ACT-R)
2. **Composite ranking**: survivors are scored by `activation_weight * normalized_B + semantic_weight * cosine_sim + noise` and the top-k are returned

The composite score mixes ACT-R activation with semantic similarity. This is not ACT-R — it is a hybrid that uses ACT-R's activation as one signal among two. The design doc for this is [mapping.md](mapping.md).

Normalization is min-max over the candidate set. This makes the effective weight of activation relative to the current query, not absolute.

---

## Reinforcement Model

In ACT-R, a chunk is reinforced (gets a new trace) every time it participates in a production rule firing. In our system, reinforcement happens at two points:

1. **On chunk creation** — the initial trace
2. **On explicit reinforcement** — after the proxy has consumed retrieved memories and produced a response, the caller explicitly reinforces the chunks that were used via `reinforce_retrieved()`

Retrieval itself does not add traces. This departs from some ACT-R implementations where retrieval automatically reinforces, but aligns with the ACT-R specification that reinforcement occurs when a chunk is "specifically retrieved for a task and actively referenced by a production rule."

---

## What We Don't Use

Several ACT-R mechanisms are not implemented:

- **Spreading activation** — replaced by embedding similarity (see above)
- **Partial matching** — ACT-R can retrieve chunks that partially match a query, with a penalty. We use cosine similarity instead, which provides a continuous match score.
- **Production compilation** — ACT-R's procedural learning mechanism (combining two production rules into one). Not applicable to our system.
- **Utility learning** — ACT-R learns which production rules to prefer via reward. Not applicable; we have a separate confidence calibration mechanism.
- **Soft-threshold retrieval probability** — the logistic P(retrieve) function from ACT-R eq. 4.4. We use a hard threshold (B > tau) for stage 1 filtering. The soft threshold could replace this; it's documented in [research/act-r.md](../../../research/act-r.md) for future consideration.
