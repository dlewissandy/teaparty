# ACT-R Proxy Mapping: Chunks, Traces, and Retrieval

This document maps ACT-R's declarative memory concepts to concrete proxy agent structures. For the theory and equations, see [act-r.md](act-r.md). For the motivation and migration plan, see [act-r-proxy-memory.md](act-r-proxy-memory.md).

---

## What Are the Chunks?

Each chunk represents a **memory of an interaction** between the proxy and the human. A chunk is created whenever the proxy observes or participates in a decision. The chunk is a structured tuple — the field ordering matters:

```python
{
    # Structural fields (SQL-filtered, exact match)
    "type": "gate_outcome",          # or "dialog_turn", "discovery_response"
    "state": "PLAN_ASSERT",          # CfA state where interaction occurred
    "task_type": "security",         # project/task category
    "outcome": "correct",            # approve, correct, dismiss, promote, discuss
    "lens": "",                      # for discovery mode: which lens produced this

    # Two-pass prediction results (see act-r-proxy-sensorium.md)
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

The chunk has three layers:

**Structural fields** (type, state, task_type, outcome, lens) are categorical — queried by exact match via SQL. They preserve the relational structure of the interaction: who did what at which gate with what result. Embeddings cannot capture this ordering reliably.

**Two-pass prediction fields** capture the prior (before seeing the artifact), the posterior (after), and the delta between them. The delta is the salience signal — what in the artifact changed the proxy's mind. See [act-r-proxy-sensorium.md](act-r-proxy-sensorium.md) for the full design.

**Independent embeddings** represent each percept dimension as a separate vector. At retrieval time, matching across multiple dimensions produces specific, selective associations. A chunk that scores high on situation AND artifact AND salience is a strong association. A chunk that scores high on only one dimension is a weak one.

| Embedding | What it captures | Retrieval use |
|-----------|-----------------|---------------|
| **Situation** | CfA state + task type | "What happened at PLAN_ASSERT for security?" |
| **Artifact** | The artifact under review | "What happened when the plan had gaps?" |
| **Stimulus** | The question or observation | "What happened when the proxy asked this?" |
| **Response** | The human's actual response | "Has the human given this kind of feedback before?" |
| **Salience** | The prediction delta | "When has the proxy been surprised by this pattern?" |

This replaces the single content embedding with a multi-dimensional representation that separates what the proxy sensed from what happened — enabling retrieval by any dimension or intersection of dimensions.

**Note on multi-dimensional retrieval.** Using 5 independent embeddings per chunk and aggregating cosine similarities at retrieval time is a novel design choice without published validation. The closest precedent is Park et al.'s (2023) generative agents, which combine separate recency, importance, and relevance scores — but those are different signal types, not faceted semantic embeddings. The Phase 1 shadow mode should include an explicit ablation comparing multi-dimensional retrieval against a single blended embedding to determine whether the added complexity and 5x embedding cost earn their keep.

---

## When Are Traces Created?

A trace is added to a chunk (incrementing the global interaction counter) when:

1. **The chunk is created.** The proxy observes a gate outcome, a dialog exchange, or a discovery response. This is the first trace.
2. **The chunk is retrieved.** When the proxy retrieves this chunk while making a decision, the retrieval itself reinforces the memory. Memories that are useful stay active; memories that are never retrieved decay.

These two rules match standard ACT-R, where traces are created by access (creation and retrieval).

---

## How Does an Interaction Become a Chunk?

Every gate interaction produces a chunk. Chunks always include structural fields, prediction fields, and outcome. The salience fields (`prediction_delta`, `salient_percepts`, `embedding_salience`) are populated only when surprise occurs (the prior and posterior actions differ, or the confidence delta exceeds the surprise threshold — see [act-r-proxy-sensorium.md](act-r-proxy-sensorium.md)). Non-surprise chunks have empty salience fields but are still stored and contribute to the memory through their other dimensions.

### Gate Mode (During Sessions)

1. The proxy is consulted at a CfA gate (e.g., PLAN_ASSERT)
2. The proxy generates a prediction (approve/correct/escalate)
3. The human responds (or the proxy acts autonomously if confident)
4. A chunk is created with:
   - `state` = the CfA state
   - `task_type` = the project slug
   - `outcome` = what actually happened (approve, correct, etc.)
   - `delta` = if the proxy predicted wrong, what was the difference
   - `content` = the artifact summary + human response text
5. The chunk is embedded (content fields only) and stored with its first trace at the current interaction count

### Discovery Mode (Between Sessions)

1. The proxy (in collaborator mode) surfaces an observation
2. The human responds: promote, dismiss, or discuss
3. A chunk is created with:
   - `state` = `DISCOVERY_{lens}` (e.g., `DISCOVERY_SPEC_ALIGNMENT`)
   - `outcome` = promote, dismiss, or discuss
   - `lens` = which review lens produced the observation
   - `delta` = the dismissal reason (if dismissed) or the discussion content
   - `content` = the observation text + human response

### Dialog Turns (Within Discussions)

Each conversational exchange in a discussion creates its own chunk:
- `type` = `dialog_turn`
- `content` = the exchange (human question + agent response)
- These chunks capture *how* the human reasons, not just *what* they decided

---

## Retrieval: Structural Filtering + Semantic Ranking

In ACT-R, context sensitivity is handled by **spreading activation** — a graph-based mechanism where chunks associated with the current focus receive an activation boost. ACT-R uses this because it operates on symbolic representations with typed associations between chunks.

We replace spreading activation with **vector embeddings**. Each chunk's content is embedded via the same infrastructure used by the learning system (`memory_indexer.py`). Semantic similarity between the current context and stored memories is computed directly via cosine similarity. This substitution provides context-sensitive retrieval without requiring a pre-built associative graph, which is an advantage for a system where associations are learned from unstructured text. However, it is a different mechanism with different properties — embeddings capture semantic overlap in text, not structural associations between concepts.

This combination of activation-based decay with embedding similarity has direct precedent in the research literature. Nuxoll & West (HAI 2024) combine ACT-R base-level activation with cosine similarity for LLM agent memory. Bhatia et al. (Frontiers, 2026) integrate language model embeddings into the ACT-R framework directly. Park et al.'s (2023) generative agents use a structurally similar weighted combination of recency, importance, and relevance — establishing the pattern of hybrid retrieval for agent memory.

Retrieval operates in two layers:

**Structural filtering** narrows the search space using the chunk's categorical fields. "Show me memories from PLAN_ASSERT gates on security tasks" is a SQL query on `state` and `task_type`. This is fast, exact, and captures the relational structure that embeddings miss — the ordering of the tuple is preserved in the schema, not in the embedding.

**Semantic ranking** orders the filtered results by meaning. Within the set of PLAN_ASSERT memories, "missing rollback plan" should rank near "no recovery strategy" even though the words differ. Cosine similarity on the embedded content handles this.

The combined retrieval score (TeaParty design — not an ACT-R equation; replaces ACT-R's spreading activation with embedding similarity):

```
score = activation_weight * normalize(B)  +  semantic_weight * cosine(chunk_embedding, context_embedding)  +  noise
```

Where:
- `B` is the base-level activation (recency and frequency via ACT-R)
- `normalize(B)` maps B to [0, 1] via min-max scaling over the candidate set, so that activation and similarity contribute on comparable scales
- `cosine(...)` is the semantic similarity between the chunk and the current context (already bounded [-1, 1])
- `noise` is logistic noise (see [act-r.md](act-r.md))
- `activation_weight` and `semantic_weight` control the balance (starting point: 0.5 / 0.5)

**Why normalization is needed.** B is unbounded (can range from negative values to ~3+ for heavily-accessed chunks), while cosine similarity is bounded [-1, 1]. Without normalization, heavily-accessed chunks would dominate retrieval regardless of semantic relevance. Min-max normalization over the candidate set ensures both signals contribute proportionally. This follows the approach of Park et al. (2023), who normalize all retrieval components to [0, 1] before combining. The normalization range should be refined during shadow mode when real activation distributions are observed.

| Parameter | Starting Value | Role | Source |
|-----------|---------------|------|--------|
| Activation weight | 0.5 | Weight of normalized base-level activation in score | Design parameter; calibrate empirically |
| Semantic weight | 0.5 | Weight of cosine similarity in score | Design parameter; calibrate empirically |

---

## How Does the Proxy Use Retrieved Chunks?

When the proxy needs to act — what question to ask at a gate, what observation to surface, how to respond in a discussion:

1. **Filter structurally.** SQL query on state, task_type to narrow candidates.
2. **Score.** For each candidate, compute normalized base-level activation + semantic similarity + noise.
3. **Threshold.** Discard chunks with score below `tau` (-0.5).
4. **Retrieve top-k.** Return the highest-scoring chunks.
5. **Reason.** The proxy's LLM prompt receives the retrieved chunks as context: "Here are your relevant memories of working with this human..." The LLM reasons over them to produce a prediction, an observation, or a response.
6. **Record.** After the human responds, a new chunk is created (or an existing chunk is reinforced with a new trace). The cycle continues.

---

## Cold Start Behavior

With zero chunks in memory, retrieval returns nothing. The proxy's LLM receives no memories and must reason from the system prompt and artifact alone. This is equivalent to the proxy escalating every gate to the human — the correct cold-start behavior, because when you know nothing about the human, you ask them.

The current system's Laplace prior serves the same function (start uncertain, converge toward confidence). The difference is that the new system's cold start produces dialog (the proxy asks questions because it has no memories to draw on), while the current system's cold start produces escalation (the proxy punts because the scalar is below threshold). Both are conservative; the new system's conservatism is more informative because it generates interaction data that builds the memory from the first session onward.

---

## Replacing the Current Confidence Model

The current model asks: "what is my confidence that this human will approve?" — a scalar that gates a binary decision. The ACT-R model asks: "what would this human say right now?" — a set of retrieved memories that the proxy reasons over to generate the questions, concerns, and dialog the human would produce.

The proxy doesn't transition from "always escalate" to "auto-approve." It transitions from "I don't know this human, so I must ask them everything" to "I know what this human would ask, so I can ask it on their behalf." The decision emerges from the dialog, not from a threshold.

EMA remains as a system health monitor — tracking approval rates per (state, task_type) over time. A declining EMA signals that upstream agents are producing worse artifacts, not that the proxy should change its behavior. Note that EMA trend information does flow into the proxy's decisions indirectly: if upstream quality degrades, the proxy encounters more corrections and surprises, producing correction chunks with richer salience deltas. The memory system naturally becomes more skeptical as corrections accumulate. EMA may also trigger operational actions (alerting the team, adjusting dispatch configuration) even though it does not directly alter per-gate decisions.

---

## The Three Outcome Types

**Approve / Promote** — the proxy was right (or the human agreed with the observation). The chunk records a positive outcome. When retrieved in future decisions, it biases toward confidence.

**Correct / Dismiss** — the proxy was wrong (or the human found the observation unhelpful). The chunk records a negative outcome AND a delta (what was wrong, why it was dismissed). The delta makes the chunk more distinctive — more specific content produces a more specific embedding — which means it is retrieved more precisely in similar future situations. Corrections carry more specific associations than approvals because error-describing text ("missing rollback strategy for database migration") is inherently more targeted than success-confirming text ("approved"). Whether this specificity translates to better retrieval precision is an empirical question to validate during shadow mode.

**Discuss** — the human engaged but didn't decide. The chunk records the exchange. It contributes to the proxy's understanding of how the human reasons but doesn't directly bias toward confidence or caution. Dialog chunks build the episodic memory that informs the proxy's conversational style, not its gate decisions.

---

## Memory Maintenance

The traces list grows as chunks are retrieved and reinforced across sessions. Without maintenance, long-lived chunks could accumulate thousands of traces. The design needs a compaction strategy:

- **Trace compaction.** Traces older than a configurable horizon (e.g., 500 interactions) are replaced with a summary: a count and an average interval. The base-level activation formula uses the summary for old traces (contributing a precomputed constant) and individual traces for recent ones. This bounds the traces list without losing the activation signal from historical access patterns.
- **Chunk pruning.** Chunks that have been below threshold tau for N consecutive sessions (e.g., N = 10) are archived to cold storage. They can be restored if a future retrieval query specifically targets their structural fields, but they do not participate in routine scoring.
- **Database maintenance.** SQLite VACUUM runs periodically (e.g., at session start if the database exceeds a size threshold).

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
    prior_prediction: str            # Pass 1 prediction (without artifact)
    prior_confidence: float          # Pass 1 confidence
    posterior_prediction: str        # Pass 2 prediction (with artifact)
    posterior_confidence: float      # Pass 2 confidence
    prediction_delta: str            # what changed between passes (salience)
    human_response: str              # what the human actually did
    delta: str                       # proxy error vs human response
    content: str                     # full text of the interaction
    traces: list[int]                # list of interaction sequence numbers
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
    prior_prediction TEXT DEFAULT '',
    prior_confidence REAL DEFAULT 0,
    posterior_prediction TEXT DEFAULT '',
    posterior_confidence REAL DEFAULT 0,
    prediction_delta TEXT DEFAULT '',
    human_response TEXT DEFAULT '',
    delta TEXT DEFAULT '',
    content TEXT NOT NULL,
    traces TEXT NOT NULL,              -- JSON array of interaction sequence numbers
    embedding_situation TEXT,          -- JSON array of floats
    embedding_artifact TEXT,
    embedding_stimulus TEXT,
    embedding_response TEXT,
    embedding_salience TEXT
);

-- Global interaction counter (monotonically increasing)
CREATE TABLE proxy_state (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
INSERT OR IGNORE INTO proxy_state (key, value) VALUES ('interaction_counter', 0);
```

### Core Functions

```python
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


def normalize_activation(b: float, b_min: float, b_max: float) -> float:
    """Normalize base-level activation to [0, 1] via min-max scaling."""
    if b_max == b_min:
        return 0.5
    return max(0.0, min(1.0, (b - b_min) / (b_max - b_min)))


def retrieval_score(
    chunk: MemoryChunk,
    context_embeddings: dict[str, list[float]],
    current_interaction: int,
    b_min: float,
    b_max: float,
    activation_weight: float = 0.5,
    semantic_weight: float = 0.5,
    d: float = 0.5,
    s: float = 0.25,
) -> float:
    """Combined retrieval score: normalized ACT-R activation +
    multi-dimensional semantic similarity + noise.

    context_embeddings: dict mapping dimension names to embedding vectors.
    Only dimensions present in both the context and the chunk contribute.
    The semantic score is the average cosine across matched dimensions —
    chunks matching on more dimensions score higher (intersection effect).
    """
    b = base_level_activation(chunk.traces, current_interaction, d)
    b_norm = normalize_activation(b, b_min, b_max)

    # Multi-dimensional semantic similarity
    dim_map = {
        'situation': chunk.embedding_situation,
        'artifact': chunk.embedding_artifact,
        'stimulus': chunk.embedding_stimulus,
        'response': chunk.embedding_response,
        'salience': chunk.embedding_salience,
    }
    similarities = []
    for dim, context_vec in context_embeddings.items():
        chunk_vec = dim_map.get(dim)
        if chunk_vec and context_vec:
            similarities.append(cosine_similarity(chunk_vec, context_vec))
    sem = sum(similarities) / len(similarities) if similarities else 0.0

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
    """Retrieve top-k chunks above threshold.

    1. Structural filter on state, task_type
    2. Compute activation range for normalization
    3. Multi-dimensional semantic scoring
    4. Threshold and rank
    """
    candidates = query_chunks(state=state, task_type=task_type)
    context_embeddings = context_embeddings or {}

    # Compute activation range for normalization
    activations = [
        base_level_activation(c.traces, current_interaction)
        for c in candidates
    ]
    b_min = min(activations) if activations else 0.0
    b_max = max(activations) if activations else 0.0

    scored = []
    for chunk in candidates:
        score = retrieval_score(
            chunk, context_embeddings, current_interaction,
            b_min, b_max,
        )
        if score > tau:
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
    delta: str = '',
    lens: str = '',
    prior_prediction: str = '',
    prior_confidence: float = 0.0,
    posterior_prediction: str = '',
    posterior_confidence: float = 0.0,
    prediction_delta: str = '',
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
        human_response=human_response,
        delta=delta,
        content=content,
        traces=[current],
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

1. **`consult_proxy()` in `proxy_agent.py`** — add ACT-R memory retrieval: load relevant chunks into the proxy agent prompt so it can generate the dialog the human would produce. EMA continues to update as a monitoring signal.

2. **`record_outcome()` in `scripts/approval_gate.py`** — add chunk creation alongside the existing EMA update. Both systems record the outcome; they serve different purposes.

3. **`_calibrate_confidence()` in `proxy_agent.py`** — replace scalar confidence computation with: the retrieval set IS the confidence signal. The LLM reads the memories and calibrates itself.

4. **Discovery mode** in the Code Collaborator — same `retrieve()` function with discovery-specific state keys.

---

## References

**Park, S., et al.** (2023). Generative Agents: Interactive Simulacra of Human Behavior. *UIST '23*. — Weighted combination of recency, importance, and relevance with min-max normalization. Direct precedent for hybrid retrieval scoring.

**Nuxoll, A., & West, R.** (2024). Human-Like Remembering and Forgetting in LLM Agents. *HAI '24*. — ACT-R base-level activation + cosine similarity for LLM agent memory retrieval.

**Bhatia, S., et al.** (2026). Integrating language model embeddings into the ACT-R cognitive modeling framework. *Frontiers in Language Sciences*. — Embedding-based replacement for hand-coded ACT-R associations.
