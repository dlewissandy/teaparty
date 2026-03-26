# ACT-R Proxy Mapping: Chunks, Traces, and Retrieval

This document maps ACT-R's declarative memory concepts to concrete proxy agent structures. For the theory and equations, see [act-r.md](act-r.md). For the motivation and migration plan, see [proxy-memory-motivation.md](proxy-memory-motivation.md). For two-pass prediction and learned attention, see [proxy-prediction-and-attention.md](proxy-prediction-and-attention.md).

---

## What Are the Chunks?

Each chunk represents a **memory of an interaction** between the proxy and the human. A chunk is created whenever the proxy observes or participates in a decision. The chunk is a structured tuple. Field ordering matters.

```python
{
    # Structural fields (SQL-filtered, exact match)
    "type": "gate_outcome",          # or "dialog_turn", "discovery_response"
    "state": "PLAN_ASSERT",          # CfA state where interaction occurred
    "task_type": "security",         # project/task category
    "outcome": "correct",            # approve, correct, dismiss, promote, discuss
    "lens": "",                      # for discovery mode: which lens produced this

    # Two-pass prediction results (see proxy-prediction-and-attention.md)
    "prior_prediction": "approve",   # Pass 1: prediction without artifact
    "prior_confidence": 0.8,
    "posterior_prediction": "correct",  # Pass 2: prediction with artifact
    "posterior_confidence": 0.85,
    "prediction_delta": "Missing rollback section changed prediction",
    "salient_percepts": ["no rollback strategy", "database migration risk"],

    # Content fields
    "human_response": "Add a rollback strategy for the migration",
    "delta": "",                     # what the proxy got wrong vs human response
    "content": "...",                # full text of the interaction

    # Memory dynamics
    "traces": [42, 47],              # interaction sequence numbers when accessed

    # Independent embeddings per percept dimension
    "embedding_situation": [...],    # state + task type
    "embedding_artifact": [...],     # the artifact content at review time
    "embedding_stimulus": [...],     # the question or observation
    "embedding_response": [...],     # the human's response
    "embedding_salience": [...],     # the prediction delta (what surprised the proxy)
}
```

The chunk has three layers.

**Structural fields** (type, state, task_type, outcome, lens) are categorical. They are queried by exact match via SQL. They preserve the relational structure of the interaction: who did what at which gate with what result. Embeddings cannot capture this ordering reliably.

**Two-pass prediction fields** capture the prior (before seeing the artifact), the posterior (after), and the delta between them. The delta is the salience signal. It identifies what in the artifact changed the proxy's mind. See [proxy-prediction-and-attention.md](proxy-prediction-and-attention.md) for the full design.

**Independent embeddings** represent each percept dimension as a separate vector. At retrieval time, matching across multiple dimensions produces specific, selective associations. A chunk that scores high on situation AND artifact AND salience is a strong association. A chunk that scores high on only one dimension is a weak one.

| Embedding | What it captures | Retrieval use |
|-----------|-----------------|---------------|
| **Situation** | CfA state plus task type | "What happened at PLAN_ASSERT for security?" |
| **Artifact** | The artifact under review | "What happened when the plan had gaps?" |
| **Stimulus** | The question or observation | "What happened when the proxy asked this?" |
| **Response** | The human's actual response | "Has the human given this kind of feedback before?" |
| **Salience** | The prediction delta | "When has the proxy been surprised by this pattern?" |

This replaces the single content embedding with a multi-dimensional representation that separates what the proxy sensed from what happened. It enables retrieval by any dimension or intersection of dimensions.

**Note on multi-dimensional retrieval.** Using 5 independent embeddings per chunk and aggregating cosine similarities at retrieval time is a novel design choice without published validation. The closest precedent is Park, J.S., et al.'s (2023) generative agents, which combine separate recency, importance, and relevance scores. Those are different signal types, not faceted semantic embeddings. Phase 1 should include an explicit ablation comparing multi-dimensional retrieval against a single blended embedding to determine whether the added complexity and 5x embedding cost earn their keep.

---

## When Are Traces Created?

A trace is added to a chunk (incrementing the global interaction counter) when:

1. **The chunk is created.** The proxy observes a gate outcome, a dialog exchange, or a discovery response. This is the first trace.
2. **The chunk is retrieved.** When the proxy retrieves this chunk while making a decision, the retrieval itself reinforces the memory. Memories that are useful stay active; memories that are never retrieved decay.

These two rules match our adaptation of ACT-R's reinforcement model. See [act-r.md](act-r.md) §Reinforcement Model. Loading chunks into the prompt prefix does not constitute retrieval-and-use.

---

## How Does an Interaction Become a Chunk?

Every gate interaction produces a chunk. Chunks always include structural fields, prediction fields, and outcome. The salience fields (`prediction_delta`, `salient_percepts`, `embedding_salience`) are populated only when surprise occurs. The prior and posterior actions differ, or the confidence delta exceeds the surprise threshold. See [proxy-prediction-and-attention.md](proxy-prediction-and-attention.md). Non-surprise chunks have empty salience fields but are still stored and contribute to the memory through their other dimensions.

### Gate Mode (During Sessions)

1. The proxy is consulted at a CfA gate (e.g., PLAN_ASSERT)
2. The proxy generates a prediction (approve/correct/escalate)
3. The human responds (or the proxy acts autonomously if confident)
4. A chunk is created with:
   - `state` = the CfA state
   - `task_type` = the project slug
   - `outcome` = what actually happened (approve, correct, etc.)
   - `delta` = if the proxy predicted wrong, what was the difference
   - `content` = the artifact summary plus human response text
5. The chunk is embedded (content fields only) and stored with its first trace at the current interaction count

### Discovery Mode (Between Sessions)

1. The proxy (in collaborator mode) surfaces an observation
2. The human responds: promote, dismiss, or discuss
3. A chunk is created with:
   - `state` = `DISCOVERY_{lens}` (e.g., `DISCOVERY_SPEC_ALIGNMENT`)
   - `outcome` = promote, dismiss, or discuss
   - `lens` = which review lens produced the observation
   - `delta` = the dismissal reason (if dismissed) or the discussion content
   - `content` = the observation text plus human response

### Dialog Turns (Within Discussions)

Each conversational exchange in a discussion creates its own chunk:
- `type` = `dialog_turn`
- `content` = the exchange (human question plus agent response)
- These chunks capture how the human reasons and what they chose to emphasize

---

## Retrieval: Structural Filtering + Semantic Ranking

We replace ACT-R's symbolic spreading activation with **vector embeddings** for context sensitivity (see [act-r.md](act-r.md) §Context Sensitivity via Embeddings for the rationale). Each chunk's content is embedded via the same infrastructure used by the learning system (`memory_indexer.py`). Semantic similarity between the current context and stored memories is computed directly via cosine similarity.

Retrieval operates in two stages.

**Stage 1: Activation filtering.** Compute raw base-level activation B for each chunk (see [research/act-r.md](../research/act-r.md) §Base-Level Activation). Discard chunks with B below tau (-0.5). See [act-r.md](act-r.md) §Parameter Choices for why tau differs from the ACT-R default.

**Stage 2: Composite scoring and ranking.** For survivors of the activation filter, compute a composite score for ranking:

```
composite = activation_weight * normalize(B)  +  semantic_weight * cosine_avg  +  noise
```

Where:
- `B` is the base-level activation (recency and frequency via ACT-R)
- `normalize(B)` maps B to [0, 1] via min-max scaling over the candidate set, so that activation and similarity contribute on comparable scales
- `cosine_avg` is the average cosine similarity across all 5 embedding dimensions (see below)
- `noise` is logistic noise (see [act-r.md](act-r.md))
- `activation_weight` and `semantic_weight` control the balance (starting point: 0.5 / 0.5)

**Cosine averaging.** The semantic score is computed by summing cosine similarities across all matched dimensions and dividing by the total number of dimensions (5), not just the number of populated ones. This means a chunk with high similarity on 2 populated dimensions out of 5 gets `(sim1 + sim2 + 0 + 0 + 0) / 5`, while a chunk with moderate similarity across all 5 gets `(sim1 + sim2 + sim3 + sim4 + sim5) / 5`. This rewards breadth of matching: chunks that match across more dimensions score higher than chunks that match narrowly on fewer dimensions, all else being equal.

**Why normalization is needed.** B is unbounded (can range from negative values to ~3+ for heavily-accessed chunks), while cosine similarity is bounded [-1, 1]. Without normalization, heavily-accessed chunks would dominate retrieval regardless of semantic relevance. Min-max normalization over the candidate set ensures both signals contribute proportionally. This follows the approach of Park, J.S., et al. (2023), who normalize all retrieval components to [0, 1] before combining. The normalization range should be refined during Phase 1 when real activation distributions are observed.

Note that because normalization is computed over the candidate set, the effective influence of the activation_weight / semantic_weight balance varies by query. When all candidates have similar activation, semantic relevance dominates. That is the correct behavior. When activation varies widely, it has strong discriminating power. The 0.5 / 0.5 starting point is a design parameter whose effective behavior is query-dependent.

| Parameter | Starting Value | Role | Source |
|-----------|---------------|------|--------|
| Activation weight | 0.5 | Weight of normalized base-level activation in composite | Design parameter; calibrate empirically |
| Semantic weight | 0.5 | Weight of cosine similarity in composite | Design parameter; calibrate empirically |

---

## How Does the Proxy Use Retrieved Chunks?

When the proxy needs to act (what question to ask at a gate, what observation to surface, how to respond in a discussion):

1. **Filter by activation.** Compute raw B for all chunks matching structural criteria (state, task_type). Discard chunks with B below tau (-0.5).
2. **Score.** For each survivor, compute the composite score (normalized activation plus semantic similarity plus noise).
3. **Retrieve top-k.** Return the highest-scoring chunks.
4. **Serialize and embed.** Convert retrieved chunks to text for the proxy's LLM prompt. The serialization includes structural fields (state, task_type, outcome), prediction fields (prior/posterior), and content. Embeddings are not included (they are binary noise). Each chunk occupies approximately 400-600 tokens (~500 average), so the chunk context is limited to a budget (e.g., 10 chunks at 5000 tokens). The serialization format uses Markdown for readability: heading for each chunk ID, subheadings for each field type, prose content inline.
5. **Reason.** The proxy's LLM prompt receives the serialized chunks as context: "Here are your relevant memories of working with this human..." The LLM reasons over them to produce a prediction, an observation, or a response.
6. **Record.** After the human responds, a new chunk is created (or an existing chunk is reinforced with a new trace). The cycle continues.

---

## Cold Start Behavior

With zero chunks in memory, retrieval returns nothing. The proxy's LLM receives no memories and must reason from the system prompt and artifact alone. This is equivalent to the proxy escalating every gate to the human. The correct cold-start behavior is: when you know nothing about the human, you ask them.

The current system's Laplace prior serves the same function (start uncertain, converge toward confidence). The difference is mechanical. The new system's cold start produces dialog (the proxy asks questions because it has no memories to draw on), while the current system's cold start produces escalation (the proxy punts because the scalar is below threshold). Both are conservative. The new system generates richer interaction data per gate (questions, responses, reasoning, structured chunks with embeddings) compared to a single binary outcome update. Whether this richer data translates to faster convergence toward useful retrieval is an empirical question for the Phase 1 ablations.

---

## Replacing the Current Confidence Model

The current model asks: "What is my confidence that this human will approve?" A scalar gates a binary decision. The ACT-R model asks: "What would this human say right now?" A set of retrieved memories that the proxy reasons over generates the questions, concerns, and dialog the human would produce.

The proxy does not transition from "always escalate" to "auto-approve." It transitions from "I do not know this human, so I must ask them everything" to "I know what this human would ask, so I can ask it on their behalf." The decision emerges from the dialog, not from a threshold.

EMA remains as a system health monitor. It tracks approval rates per (state, task_type) over time. A declining EMA signals that upstream agents are producing worse artifacts, not that the proxy should change its behavior. EMA and the memory system operate on separate data paths. EMA tracks approval rates over time and produces trend reports. The memory system records interactions as chunks. The two systems do not share state. When upstream quality degrades, the memory system responds to the degradation through its normal operation. More correction chunks accumulate, shifting retrieval toward skeptical patterns, not through EMA influencing retrieval.

---

## The Three Outcome Types

**Approve / Promote** — the proxy was right (or the human agreed with the observation). The chunk records a positive outcome. When retrieved in future decisions, it biases toward confidence.

**Correct / Dismiss** — the proxy was wrong (or the human found the observation unhelpful). The chunk records a negative outcome AND a delta (what was wrong, why it was dismissed). The delta makes the chunk more distinctive. More specific content produces a more specific embedding, which means it is retrieved more precisely in similar future situations. Corrections carry more specific associations than approvals because error-describing text ("missing rollback strategy for database migration") is inherently more targeted than success-confirming text ("approved"). Whether this specificity translates to better retrieval precision is an empirical question to validate during Phase 1.

**Discuss** — the human engaged but did not decide. The chunk records the exchange. It contributes to the proxy's understanding of how the human reasons but does not directly bias toward confidence or caution. Dialog chunks build the episodic memory that informs the proxy's conversational style, not its gate decisions.

---

## Contradiction Detection

As the proxy accumulates episodic memories across sessions, retrieved memory sets may contain conflicting evidence — one chunk says the human prefers aggressive parallelization, another says they insist on sequential verification. Without explicit detection, the LLM receives contradictory evidence and silently resolves it (or doesn't), with no visibility into what happened. Contradictory retrieval is one of the three signals that should trigger escalation (alongside no retrieval hits and novel concerns in agent output), per the conceptual design.

The detection mechanism operates at two points in the lifecycle.

**Retrieval-time flagging.** After `retrieve_chunks()` returns the top-k set for a gate decision, a brief LLM call scans the result set for conflicting pairs and classifies each conflict by cause:

- **Preference drift** (recency gap, same domain) — prefer the newer memory; schedule the older for demotion at next compaction
- **Context sensitivity** (different domains) — preserve both with scope annotations; both are valid in their respective contexts
- **Genuine tension** (recent, same domain, high confidence both) — escalate to the human; this cannot be resolved from memory alone
- **Retrieval noise** (low semantic similarity despite co-retrieval) — discard the weaker match

When conflicts are found, the classification is injected into the proxy's prompt alongside the memories, making the conflict visible to the proxy's reasoning rather than leaving it implicit. Most gates will have no conflicts — the classification call is skipped entirely when retrieved memories agree.

When the cause is ambiguous, the default is context sensitivity (preserve both) rather than preference drift (discard the older). Falsely discarding valid context-specific knowledge is harder to recover from than preserving a possibly-outdated entry.

**Write-time consolidation.** During the post-session pipeline, a compaction pass on `proxy.md` (the always-loaded preferential store) clusters recent observations with existing entries by semantic similarity, presents conflicting pairs to an LLM, and applies a four-way decision taxonomy: ADD (no conflict), UPDATE (complement existing), DELETE (new supersedes old), SKIP (already represented). Contradicting evidence reduces a memory's weight more than supporting evidence increases it, consistent with the proxy's existing 3x correction asymmetry from regret theory.

For the research basis, see `docs/research/contradiction-detection-memory.md`.

---

## Salience Separation (Design Target)

The current design includes salience (the prediction delta — what changed between prior and posterior) as a fifth embedding dimension in the composite score, averaged alongside situation, artifact, stimulus, and response. This conflates two questions: "what happened in similar situations?" and "what has surprised me in similar situations?"

The proposed refinement separates these into independent retrieval paths.

**Experience retrieval** uses four dimensions (situation, artifact, stimulus, response) and answers "what happened before in similar contexts?" Chunks without salience are no longer penalized by the breadth-rewarding divisor — the denominator becomes 4 instead of 5. Since most interactions produce no surprise, this eliminates a structural penalty on the majority of chunks.

**Attention retrieval** uses salience embeddings only and answers "when has the proxy been surprised in ways relevant to this situation?" Only chunks with populated salience fields participate. The result set is smaller but highly specific — these are the memories that build the learned attention model.

The two result sets are injected into the proxy's prompt as separate sections ("your relevant experience" and "what has surprised you"), priming the LLM to reason about expectation and vigilance as distinct concerns. This separation also produces a cleaner ablation for Phase 1: experience retrieval can be evaluated independently of the attention model.

---

## Memory Maintenance

The traces list grows as chunks are retrieved and reinforced across sessions. Without maintenance, long-lived chunks could accumulate thousands of traces. The design needs a compaction strategy.

**Trace compaction.** Use the ACT-R standard base-level approximation B ≈ ln(n/(1-d)) - d*ln(L), where n = total presentations and L = lifetime in interactions. Petrov (2006) developed a more accurate hybrid approximation that combines this formula with direct computation for recent traces. Both are well-studied alternatives with known error bounds, unlike the naive averaging approach which violates Jensen's inequality for the concave t^(-d) function.

**Chunk pruning.** Chunks that have been below threshold tau for N consecutive sessions (e.g., N = 10) are archived to cold storage. They can be restored if a future retrieval query specifically targets their structural fields, but they do not participate in routine scoring.

**Database maintenance.** SQLite VACUUM runs periodically (e.g., at session start if the database exceeds a size threshold).

---

## Implementation

The design above is implemented in `projects/POC/orchestrator/proxy_memory.py` (chunk storage, activation, retrieval, scoring) and `projects/POC/orchestrator/proxy_agent.py` (two-pass prediction, surprise extraction, confidence calibration). Gate outcomes are recorded as chunks in `projects/POC/orchestrator/actors.py`.

---

## References

**Park, J.S., et al.** (2023). Generative Agents: Interactive Simulacra of Human Behavior. *UIST '23*. — Weighted combination of recency, importance, and relevance with min-max normalization. Direct precedent for hybrid retrieval scoring.

**Honda, Y., Fujita, Y., Zempo, K., & Fukushima, S.** (2025). Human-Like Remembering and Forgetting in LLM Agents: An ACT-R-Inspired Memory Architecture. In *Proceedings of the 13th International Conference on Human-Agent Interaction* (HAI '25), pp. 229-237. ACM. DOI: 10.1145/3765766.3765803 — ACT-R base-level activation plus cosine similarity for LLM agent memory retrieval. Best Paper Award, HAI 2025.

**Meghdadi, M., Duff, J., & Demberg, V.** (2026). Integrating language model embeddings into the ACT-R cognitive modeling framework. *Frontiers in Language Sciences*, 5. DOI: 10.3389/flang.2026.1721326 — Demonstrates that LM embedding cosine similarity is a valid substitute for hand-coded association strengths within the ACT-R framework. The paper's domain is psycholinguistic modeling (associative priming in the Lexical Decision Task); the relevance here is the methodological pattern of using LM embeddings where ACT-R uses symbolic associations.

**Petrov, A.** (2006). Computationally Efficient Approximation of the Base-Level Learning Equation in ACT-R. In *Proceedings of the Seventh International Conference on Cognitive Modeling* (ICCM '06). — Hybrid approximation combining the ACT-R standard formula with direct computation, providing more accurate activation estimates than naive averaging.
