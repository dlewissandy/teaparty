# ACT-R Proxy Mapping: Chunks, Traces, and Retrieval

ACT-R's declarative memory concepts mapped to the proxy agent's concrete structures. For the theory and equations, see [overview.md](overview.md). For the motivation and migration plan, see [memory.md](memory.md). For two-pass prediction and learned attention, see [sensorium.md](sensorium.md).

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

    # Two-pass prediction results (see sensorium.md)
    "prior_confidence": 0.8,          # Pass 1: confidence without artifact
    "posterior_confidence": 0.85,     # Pass 2: confidence after reading artifact
    "prediction_delta": "Missing rollback section changed prediction",
    "salient_percepts": ["no rollback strategy", "database migration risk"],

    # Categorical prior/posterior prediction fields exist in the schema
    # (prior_prediction, posterior_prediction) but are no longer populated.
    # The conversational-prompts migration moved categorical action
    # classification downstream to `_classify_review` in
    # teaparty/cfa/actors.py, which runs on the final human/proxy response
    # rather than per-pass.  Historical rows written before the migration
    # may still have values.

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

**Two-pass prediction fields** capture the prior (before seeing the artifact), the posterior (after), and the delta between them. The delta is the salience signal. It identifies what in the artifact changed the proxy's mind. See [sensorium.md](sensorium.md) for the full design.

**Independent embeddings** represent each percept dimension as a separate vector. At retrieval time, matching across multiple dimensions produces specific, selective associations. A chunk that scores high on situation AND artifact AND salience is a strong association. A chunk that scores high on only one dimension is a weak one.

| Embedding | What it captures | Retrieval use |
|-----------|-----------------|---------------|
| **Situation** | CfA state plus task type | "What happened at PLAN_ASSERT for security?" |
| **Artifact** | The artifact under review | "What happened when the plan had gaps?" |
| **Stimulus** | The question or observation | "What happened when the proxy asked this?" |
| **Response** | The human's actual response | "Has the human given this kind of feedback before?" |
| **Salience** | The prediction delta | "When has the proxy been surprised by this pattern?" |

This replaces the single content embedding with a multi-dimensional representation that separates what the proxy sensed from what happened. It enables retrieval by any dimension or intersection of dimensions.

**Note on multi-dimensional retrieval.** Using independent embeddings per chunk and aggregating cosine similarities at retrieval time is a novel design choice without published validation. The closest precedent is Park, J.S., et al.'s (2023) generative agents, which combine separate recency, importance, and relevance scores. Those are different signal types, not faceted semantic embeddings. Phase 1 should include an explicit ablation comparing 4-dimensional experience retrieval against a single blended embedding to determine whether the added complexity and embedding cost earn their keep. Salience retrieval should be evaluated separately: does providing attention-model context improve posterior accuracy? This is a cleaner ablation because it isolates the experience question from the attention question.

---

## When Are Traces Created?

A trace is added to a chunk (incrementing the global interaction counter) when:

1. **The chunk is created.** The proxy observes a gate outcome, a dialog exchange, or a discovery response. This is the first trace.
2. **The chunk is retrieved.** When the proxy retrieves this chunk while making a decision, the retrieval itself reinforces the memory. Memories that are useful stay active; memories that are never retrieved decay.

These two rules match standard ACT-R. Chunks are reinforced only when specifically retrieved for a task and actively referenced by a production rule, not merely when present in working memory. See ACT-R Tutorial Unit 4. Loading chunks into the prompt prefix for context is analogous to having chunks in declarative memory above threshold; it does not constitute retrieval-and-use.

---

## How Does an Interaction Become a Chunk?

Every gate interaction produces a chunk. Chunks always include structural fields, prediction fields, and outcome. The salience fields (`prediction_delta`, `salient_percepts`, `embedding_salience`) are populated only when surprise occurs (the confidence delta between Pass 1 and Pass 2 exceeds the surprise threshold of 0.3). See [sensorium.md](sensorium.md). Non-surprise chunks have empty salience fields but are still stored and contribute to the memory through their other dimensions.

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

In ACT-R, context sensitivity is handled by **spreading activation**. A graph-based mechanism routes activation from the current focus to associated chunks. ACT-R uses this because it operates on symbolic representations with typed associations between chunks.

We replace spreading activation with **vector embeddings**. Each chunk's content is embedded via the same infrastructure used by the learning system (`memory_indexer.py`). Semantic similarity between the current context and stored memories is computed directly via cosine similarity. This substitution provides context-sensitive retrieval without requiring a pre-built associative graph, which is an advantage for a system where associations are learned from unstructured text. However, it is a different mechanism with different properties. Embeddings capture semantic overlap in text, not structural associations between concepts.

This combination of activation-based decay with embedding similarity has direct precedent in the research literature. Honda, Fujita, Zempo, & Fukushima (HAI '25) combine ACT-R base-level activation with cosine similarity for LLM agent memory retrieval. Meghdadi, Duff, & Demberg (Frontiers in Language Sciences, 2026) demonstrate that language model embedding cosine similarity is a valid substitute for hand-coded association strengths within the ACT-R framework. Their work is in psycholinguistic modeling (associative priming in the Lexical Decision Task), but the methodological pattern of using LM embeddings where ACT-R uses symbolic associations transfers to our context. Park, J.S., et al.'s (2023) generative agents use a structurally similar weighted combination of recency, importance, and relevance. This establishes the pattern of hybrid retrieval for agent memory.

Retrieval operates in two stages.

**Stage 1: Activation filtering.** Compute raw base-level activation B for each chunk. Discard chunks with B below tau (-0.5). This is the ACT-R retrieval threshold. It filters for memory accessibility. Chunks below threshold are effectively forgotten. This keeps tau's semantics aligned with ACT-R: it gates on activation, not on a mixed score.

**Stage 2: Composite scoring and ranking.** For survivors of the activation filter, compute a composite score for ranking:

```
composite = activation_weight * tanh(B - τ)  +  semantic_weight * cosine_avg  +  noise
```

Where:
- `B` is the base-level activation (recency and frequency via ACT-R)
- `tanh(B - τ)` maps B to (-1, 1) with a principled zero crossing at the retrieval threshold τ
- `cosine_avg` is the average cosine similarity across the 4 experience embedding dimensions (situation, artifact, stimulus, response — salience is retrieved independently, see below)
- `noise` is logistic noise (see [overview.md](overview.md))
- `activation_weight` and `semantic_weight` control the balance (starting point: 0.5 / 0.5)

**Why tanh(B - τ).** Cosine similarity already lives on a natural scale: 0 = orthogonal (no contribution), +1 = perfect match, -1 = antithesis. No normalization needed. Raw activation B is on a log scale with no natural upper bound. To make the two components commensurable, we need a monotonic map from ℝ → (-1, 1). Shifting by τ grounds the zero point: a chunk at exactly the retrieval threshold contributes nothing to the composite, mirroring the cosine semantics. The tradeoff between recency and frequency in B is ACT-R's design; `tanh` is a monotonic transform and preserves it exactly.

**Cosine averaging.** The semantic score is computed by summing cosine similarities across the 4 experience dimensions (situation, artifact, stimulus, response) and dividing by 4, not just the number of populated ones. This means a chunk with high similarity on 2 populated dimensions out of 4 gets `(sim1 + sim2 + 0 + 0) / 4`, while a chunk with moderate similarity across all 4 gets `(sim1 + sim2 + sim3 + sim4) / 4`. This rewards breadth of matching: chunks that match across more dimensions score higher than chunks that match narrowly on fewer dimensions, all else being equal. Salience is excluded from composite scoring and retrieved independently via `retrieve_salience()`.

Both components are on (-1, 1) with a principled zero crossing. The 0.5 / 0.5 weight split has unambiguous meaning: at exactly the threshold and orthogonal context, composite = 0 + 0 + noise.

| Parameter | Starting Value | Role | Source |
|-----------|---------------|------|--------|
| Activation weight | 0.5 | Weight of `tanh(B − τ)` activation contribution in composite | Design parameter; calibrate empirically |
| Semantic weight | 0.5 | Weight of cosine similarity in composite | Design parameter; calibrate empirically |
| Noise scale (s) | 0.08 | Logistic noise scale; std dev ≈ πs/√3 ≈ 0.145 | Calibrated so noise perturbs ranking without dominating signal |

---

## How Does the Proxy Use Retrieved Chunks?

When the proxy needs to act (what question to ask at a gate, what observation to surface, how to respond in a discussion):

1. **Filter by activation.** Compute raw B for all chunks matching structural criteria (state, task_type). Discard chunks with B below tau (-0.5).
2. **Score.** For each survivor, compute the composite score (`tanh(B − τ)` activation contribution plus semantic similarity plus noise).
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

## Memory Maintenance

The traces list grows as chunks are retrieved and reinforced across sessions. Without maintenance, long-lived chunks could accumulate thousands of traces. The design needs a compaction strategy.

**Trace compaction.** Use the ACT-R standard base-level approximation B ≈ ln(n/(1-d)) - d*ln(L), where n = total presentations and L = lifetime in interactions. Petrov (2006) developed a more accurate hybrid approximation that combines this formula with direct computation for recent traces. Both are well-studied alternatives with known error bounds, unlike the naive averaging approach which violates Jensen's inequality for the concave t^(-d) function.

**Chunk pruning.** Chunks that have been below threshold tau for N consecutive sessions (e.g., N = 10) are archived to cold storage. They can be restored if a future retrieval query specifically targets their structural fields, but they do not participate in routine scoring.

**Database maintenance.** SQLite VACUUM runs periodically (e.g., at session start if the database exceeds a size threshold).

---

## Implementation Sketch

### Data Structure

```python
@dataclass
class MemoryChunk:
    id: str                          # unique identifier
    type: str                        # gate_outcome, dialog_turn, discovery_response
    state: str                       # CfA state or DISCOVERY_{lens}
    task_type: str                   # project slug or empty
    outcome: str                     # approve, correct, dismiss, promote, discuss
    lens: str                        # discovery lens (empty for gate mode)
    prior_prediction: str            # Pass 1 prediction (deprecated; empty
                                     # on new chunks; classification now
                                     # runs downstream)
    prior_confidence: float          # Pass 1 confidence
    posterior_prediction: str        # Pass 2 prediction (deprecated — see
                                     # prior_prediction note)
    posterior_confidence: float      # Pass 2 confidence
    prediction_delta: str            # what changed between passes (salience)
    salient_percepts: list[str]      # artifact features that caused the shift
    human_response: str              # what the human actually did
    delta: str                       # proxy error vs human response
    content: str                     # full text of the interaction
    traces: list[int]                # list of interaction sequence numbers
    embedding_model: str             # which model produced the vectors
    embedding_situation: list[float] | None
    embedding_artifact: list[float] | None
    embedding_stimulus: list[float] | None
    embedding_response: list[float] | None
    embedding_salience: list[float] | None
```

### Storage

```sql
CREATE TABLE proxy_chunks (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    state TEXT NOT NULL,
    task_type TEXT DEFAULT '',
    outcome TEXT NOT NULL,
    lens TEXT DEFAULT '',
    prior_prediction TEXT DEFAULT '',   -- deprecated; empty on new chunks
    prior_confidence REAL DEFAULT 0,
    posterior_prediction TEXT DEFAULT '', -- deprecated; empty on new chunks
    posterior_confidence REAL DEFAULT 0,
    prediction_delta TEXT DEFAULT '',
    salient_percepts TEXT DEFAULT '[]', -- JSON array of strings
    human_response TEXT DEFAULT '',
    delta TEXT DEFAULT '',
    content TEXT NOT NULL,
    traces TEXT NOT NULL,              -- JSON array of interaction sequence numbers
    embedding_model TEXT DEFAULT '',   -- which model produced the vectors (determined internally)
    embedding_situation TEXT,          -- JSON array of floats
    embedding_artifact TEXT,
    embedding_stimulus TEXT,
    embedding_response TEXT,
    embedding_salience TEXT,
    embedding_blended TEXT,            -- single blended embedding (ablation: Configuration B)
    deleted_at INTEGER DEFAULT NULL    -- soft-delete timestamp; memory_depth filters WHERE deleted_at IS NULL
);

-- Global interaction counter (monotonically increasing)
CREATE TABLE proxy_state (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
INSERT OR IGNORE INTO proxy_state (key, value) VALUES ('interaction_counter', 0);
```

The embedding_model column records which model produced the vectors, enabling re-embedding migration when the model changes.

### Core Functions

```python
EXPERIENCE_EMBEDDING_DIMENSIONS = 4  # situation, artifact, stimulus, response
# Salience is retrieved independently via retrieve_salience()


def base_level_activation(
    traces: list[int], current_interaction: int, d: float = 0.5,
) -> float:
    """Compute B = ln(sum t_i^(-d)) for a chunk's trace history."""
    total = 0.0
    for trace in traces:
        age = max(current_interaction - trace, 1)
        total += age ** (-d)
    if total <= 0:
        return -float('inf')
    return math.log(total)


def composite_score(
    chunk: MemoryChunk,
    context_embeddings: dict[str, list[float]],
    current_interaction: int,
    activation_weight: float = 0.5,
    semantic_weight: float = 0.5,
    d: float = 0.5,
    s: float = 0.08,
    tau: float = -0.5,
) -> float:
    """Composite ranking score: tanh-normalised ACT-R activation +
    multi-dimensional semantic similarity + noise.

    composite = activation_weight * tanh(B - τ)
              + semantic_weight * cosine_avg
              + noise

    tanh(B - τ) maps B to (-1, 1) with a zero crossing at the retrieval
    threshold τ. No min-max range is needed: tanh has no degenerate case.

    context_embeddings: dict mapping dimension names to embedding vectors.
    The semantic score sums cosine similarities across the 4 experience
    dimensions and divides by EXPERIENCE_EMBEDDING_DIMENSIONS (4), not
    the number of populated dimensions. Salience is excluded from
    composite scoring and retrieved independently.
    """
    b = base_level_activation(chunk.traces, current_interaction, d)
    b_norm = math.tanh(b - tau)

    # Experience dimensions only — salience retrieved independently
    dim_map = {
        'situation': chunk.embedding_situation,
        'artifact': chunk.embedding_artifact,
        'stimulus': chunk.embedding_stimulus,
        'response': chunk.embedding_response,
    }
    sim_sum = 0.0
    for dim, context_vec in context_embeddings.items():
        chunk_vec = dim_map.get(dim)
        if chunk_vec and context_vec:
            sim_sum += cosine_similarity(chunk_vec, context_vec)
    sem = sim_sum / EXPERIENCE_EMBEDDING_DIMENSIONS

    noise = logistic_noise(s)
    return activation_weight * b_norm + semantic_weight * sem + noise


def retrieve(
    state: str = '',
    task_type: str = '',
    context_embeddings: dict[str, list[float]] | None = None,
    current_interaction: int = 0,
    tau: float = -0.5,
    top_k: int = 10,
) -> list[MemoryChunk]:
    """Retrieve top-k chunks above activation threshold.

    1. Structural filter on state, task_type
    2. Activation filter: discard chunks with raw B below tau
    3. Composite scoring and ranking (tanh normalization — no range needed)
    """
    candidates = query_chunks(state=state, task_type=task_type)
    context_embeddings = context_embeddings or {}

    # Stage 1: filter by raw activation (tau on B, not on composite)
    survivors = []
    for c in candidates:
        b = base_level_activation(c.traces, current_interaction)
        if b > tau:
            survivors.append(c)

    if not survivors:
        return []

    # Stage 2: composite scoring for ranking
    scored = []
    for chunk in survivors:
        score = composite_score(
            chunk, context_embeddings, current_interaction, tau=tau,
        )
        scored.append((score, chunk))
    scored.sort(key=lambda x: -x[0])
    return [chunk for _, chunk in scored[:top_k]]


def record_interaction(
    chunk_id: str | None,
    interaction_type: str,
    state: str,
    task_type: str,
    outcome: str,
    content: str,
    embedding_model: str,
    delta: str = '',
    lens: str = '',
    prior_prediction: str = '',
    prior_confidence: float = 0.0,
    posterior_prediction: str = '',
    posterior_confidence: float = 0.0,
    prediction_delta: str = '',
    salient_percepts: list[str] | None = None,
    human_response: str = '',
    artifact_text: str = '',
    stimulus_text: str = '',
) -> MemoryChunk:
    """Record an interaction as a memory chunk.
    If chunk_id matches existing chunk, adds a trace (reinforcement).
    Otherwise creates a new chunk with independent per-dimension embeddings.
    Increments global interaction counter.
    """
    current = increment_interaction_counter()
    if chunk_id and chunk_exists(chunk_id):
        add_trace(chunk_id, current)
        return get_chunk(chunk_id)
    chunk = MemoryChunk(
        id=generate_id(),
        type=interaction_type,
        state=state,
        task_type=task_type,
        outcome=outcome,
        lens=lens,
        prior_prediction=prior_prediction,
        prior_confidence=prior_confidence,
        posterior_prediction=posterior_prediction,
        posterior_confidence=posterior_confidence,
        prediction_delta=prediction_delta,
        salient_percepts=salient_percepts or [],
        human_response=human_response,
        delta=delta,
        content=content,
        traces=[current],
        embedding_model=embedding_model,
        embedding_situation=embed(f'{state} {task_type}'),
        embedding_artifact=embed(artifact_text) if artifact_text else None,
        embedding_stimulus=embed(stimulus_text) if stimulus_text else None,
        embedding_response=embed(human_response) if human_response else None,
        embedding_salience=embed(prediction_delta) if prediction_delta else None,
    )
    store_chunk(chunk)
    return chunk
```

### Integration Points

1. **`consult_proxy()` in `proxy_agent.py`** — add ACT-R memory retrieval. Load relevant chunks into the proxy agent prompt so it can generate the dialog the human would produce. EMA continues to update as a monitoring signal.

2. **`record_outcome()` in `scripts/approval_gate.py`** — add chunk creation alongside the existing EMA update. Both systems record the outcome; they serve different purposes.

3. **`_calibrate_confidence()` in `proxy_agent.py`** — replace scalar confidence computation with: the retrieval set IS the confidence signal. The LLM reads the memories and calibrates itself.

4. **Discovery mode** in the Code Collaborator — same `retrieve()` function with discovery-specific state keys.

---

## References

**Park, J.S., et al.** (2023). Generative Agents: Interactive Simulacra of Human Behavior. *UIST '23*. — Weighted combination of recency, importance, and relevance with min-max normalization. Direct precedent for hybrid retrieval scoring.

**Honda, Y., Fujita, Y., Zempo, K., & Fukushima, S.** (2025). Human-Like Remembering and Forgetting in LLM Agents: An ACT-R-Inspired Memory Architecture. In *Proceedings of the 13th International Conference on Human-Agent Interaction* (HAI '25), pp. 229-237. ACM. DOI: 10.1145/3765766.3765803 — ACT-R base-level activation plus cosine similarity for LLM agent memory retrieval. Best Paper Award, HAI 2025.

**Meghdadi, M., Duff, J., & Demberg, V.** (2026). Integrating language model embeddings into the ACT-R cognitive modeling framework. *Frontiers in Language Sciences*, 5. DOI: 10.3389/flang.2026.1721326 — Demonstrates that LM embedding cosine similarity is a valid substitute for hand-coded association strengths within the ACT-R framework. The paper's domain is psycholinguistic modeling (associative priming in the Lexical Decision Task); the relevance here is the methodological pattern of using LM embeddings where ACT-R uses symbolic associations.

**Petrov, A.** (2006). Computationally Efficient Approximation of the Base-Level Learning Equation in ACT-R. In *Proceedings of the Seventh International Conference on Cognitive Modeling* (ICCM '06). — Hybrid approximation combining the ACT-R standard formula with direct computation, providing more accurate activation estimates than naive averaging.
