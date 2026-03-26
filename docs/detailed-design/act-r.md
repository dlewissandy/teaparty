# ACT-R Adaptations for TeaParty

How TeaParty's proxy memory system adapts ACT-R declarative memory for agent gate decisions. This document covers only where we depart from vanilla ACT-R. For the theory, equations, and standard parameter values, see [research/act-r.md](../research/act-r.md).

Related:
- [proxy-memory-motivation.md](proxy-memory-motivation.md) — motivation and migration plan
- [proxy-chunks-and-retrieval.md](proxy-chunks-and-retrieval.md) — chunks, traces, retrieval implementation
- [proxy-prediction-and-attention.md](proxy-prediction-and-attention.md) — two-pass prediction and learned attention
- [../conceptual-design/human-proxies.md](../conceptual-design/human-proxies.md) — conceptual design

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
| Noise (s) | NIL (disabled) | **0.25** | Low enough for mostly-deterministic retrieval, high enough for occasional exploration. Needs empirical calibration. |
| Retrieval threshold (tau) | 0 | **-0.5** | Admits chunks with slightly negative activation. Desirable in a low-interaction system (50-200 lifetime interactions) where useful chunks may hover near zero. Needs empirical calibration. |

**Caveat on d = 0.5.** Anderson & Schooler's corpora are high-volume streams (thousands of observations). Proxy gate interactions are sparse — perhaps 50-200 total lifetime interactions. The power-law form is the right functional shape, and d = 0.5 produces moderate decay. But whether 0.5 is optimal for this interaction regime is an open empirical question.

---

## Context Sensitivity via Embeddings

ACT-R uses symbolic spreading activation for context sensitivity (see [research/act-r.md](../research/act-r.md)). We replace this with **vector embeddings and cosine similarity**. Each chunk has up to 5 independent embedding dimensions (situation, artifact, stimulus, response, salience). At retrieval, cosine similarity between query embeddings and chunk embeddings provides the context-sensitivity signal.

This is a fundamental departure. We lose the ability to reason about structural relationships between chunks, but gain the ability to match on semantic meaning without manually defining associative links.

---

## Two-Stage Retrieval

ACT-R retrieves the single chunk with highest activation above threshold (see [research/act-r.md](../research/act-r.md) §Retrieval). We retrieve a **ranked set** using a two-stage process:

1. **Activation filter**: all chunks with B > tau survive (standard ACT-R)
2. **Composite ranking**: survivors are scored by `activation_weight * normalized_B + semantic_weight * cosine_sim + noise` and the top-k are returned

The composite score mixes ACT-R activation with semantic similarity. This is not ACT-R — it is a hybrid that uses ACT-R's activation as one signal among two. The design doc for this is [proxy-chunks-and-retrieval.md](proxy-chunks-and-retrieval.md).

Normalization is min-max over the candidate set. This makes the effective weight of activation relative to the current query, not absolute. See issue #192 for known limitations.

---

## Reinforcement Model

In vanilla ACT-R, a chunk is reinforced every time it participates in a production rule firing (see [research/act-r.md](../research/act-r.md) §Base-Level Activation). In our system, reinforcement happens at two points:

1. **On chunk creation** — the initial trace
2. **On explicit reinforcement** — after the proxy has consumed retrieved memories and produced a response, the caller explicitly reinforces the chunks that were used via `reinforce_retrieved()`

Retrieval itself does not add traces (see issue #191). This departs from some ACT-R implementations where retrieval automatically reinforces, but aligns with the ACT-R specification that reinforcement occurs when a chunk is "specifically retrieved for a task and actively referenced by a production rule."

---

## What We Don't Use

Several ACT-R mechanisms are not implemented (see [research/act-r.md](../research/act-r.md) for descriptions of each):

- **Spreading activation** — replaced by embedding similarity (see above)
- **Partial matching** — replaced by cosine similarity, which provides a continuous match score
- **Production compilation** — not applicable to our system
- **Utility learning** — not applicable; we have a separate confidence calibration mechanism
- **Soft-threshold retrieval probability** — we use a hard threshold (B > tau) for stage 1 filtering. The soft threshold could replace this for future consideration.
