# ACT-R Proxy Mapping: Chunks, Traces, and Retrieval

This document maps ACT-R's declarative memory concepts to concrete proxy agent structures. For the theory and equations, see [act-r-primer.md](act-r-primer.md). For the motivation and migration plan, see [act-r-proxy-memory.md](act-r-proxy-memory.md).

---

## What Are the Chunks?

Each chunk represents a **memory of an interaction** between the proxy and the human. A chunk is created whenever the proxy observes or participates in a decision. The chunk is a structured tuple — the field ordering matters:

```python
{
    "type": "gate_outcome",          # or "dialog_turn", "discovery_response"
    "state": "PLAN_ASSERT",          # CfA state where interaction occurred
    "task_type": "security",         # project/task category
    "outcome": "approve",            # approve, correct, dismiss, promote, discuss
    "lens": "",                      # for discovery mode: which lens produced this
    "delta": "",                     # what the proxy got wrong (prediction vs reality)
    "content": "...",                # full text of the interaction
    "traces": [42, 47],              # interaction sequence numbers when accessed
    "embedding": [0.12, -0.34, ...]  # vector embedding of the content field only
}
```

The **structural fields** (type, state, task_type, outcome, lens) are categorical — queried by exact match via SQL. They preserve the relational structure of the interaction: who did what at which gate with what result. Embeddings cannot capture this ordering reliably.

The **content fields** (delta, content) are free text — ranked by semantic similarity via cosine on the embedding. "Missing rollback plan" should match "no recovery strategy" even though the words differ.

The **embedding covers only the content fields**, not the structural fields. This separation ensures that structural queries are exact and semantic queries are meaningful.

---

## When Are Traces Created?

A trace is added to a chunk (incrementing the global interaction counter) when:

1. **The chunk is created.** The proxy observes a gate outcome, a dialog exchange, or a discovery response. This is the first trace.
2. **The chunk is retrieved.** When the proxy retrieves this chunk while making a decision, the retrieval itself reinforces the memory. Memories that are useful stay active; memories that are never retrieved decay.
3. **The chunk is explicitly reinforced.** When a new interaction produces a similar outcome to a past one — the human approves at PLAN_ASSERT again — the matching chunk gets an additional trace even if it wasn't explicitly retrieved.

---

## How Does an Interaction Become a Chunk?

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

In ACT-R, context sensitivity is handled by **spreading activation** — a tag-based mechanism where chunks associated with the current focus receive an activation boost. ACT-R uses this because it operates on symbolic representations that have no notion of semantic similarity.

We have something better: **vector embeddings**. Each chunk's content is embedded via the same infrastructure used by the learning system (`memory_indexer.py`). Semantic similarity between the current context and stored memories is computed directly via cosine similarity.

This is not a novel combination. Activation-weighted embedding retrieval is the pattern underlying modern AI memory systems, including Claude's own persistent memory. The approach is deployed at scale.

Retrieval operates in two layers:

**Structural filtering** narrows the search space using the chunk's categorical fields. "Show me memories from PLAN_ASSERT gates on security tasks" is a SQL query on `state` and `task_type`. This is fast, exact, and captures the relational structure that embeddings miss — the ordering of the tuple is preserved in the schema, not in the embedding.

**Semantic ranking** orders the filtered results by meaning. Within the set of PLAN_ASSERT memories, "missing rollback plan" should rank near "no recovery strategy" even though the words differ. Cosine similarity on the embedded content handles this.

The combined retrieval score:

```
score = activation_weight * B  +  semantic_weight * cosine(chunk_embedding, context_embedding)  +  noise
```

Where:
- `B` is the base-level activation (recency and frequency via ACT-R)
- `cosine(...)` is the semantic similarity between the chunk and the current context
- `noise` is logistic noise (see [act-r-primer.md](act-r-primer.md))
- `activation_weight` and `semantic_weight` control the balance (starting point: 0.5 / 0.5)

| Parameter | Starting Value | Role | Source |
|-----------|---------------|------|--------|
| Activation weight | 0.5 | Weight of base-level activation in score | Design parameter; calibrate empirically |
| Semantic weight | 0.5 | Weight of cosine similarity in score | Design parameter; calibrate empirically |

---

## How Does the Proxy Use Retrieved Chunks?

When the proxy needs to make a decision — whether to auto-approve at a gate, what observation to surface, how to respond in a discussion:

1. **Filter structurally.** SQL query on state, task_type to narrow candidates.
2. **Score.** For each candidate, compute base-level activation + semantic similarity + noise.
3. **Threshold.** Discard chunks with score below `tau` (-0.5).
4. **Retrieve top-k.** Return the highest-scoring chunks.
5. **Reason.** The proxy's LLM prompt receives the retrieved chunks as context: "Here are your relevant memories of working with this human..." The LLM reasons over them to produce a prediction, an observation, or a response.
6. **Record.** After the human responds, a new chunk is created (or an existing chunk is reinforced with a new trace). The cycle continues.

---

## Replacing the Current Confidence Model

The current model answers one question: "what is my confidence that this human will approve at this gate?" It answers with a scalar: the EMA approval rate.

The ACT-R model answers a richer question: "what do I know about how this human has responded in situations similar to this one?" It answers with a set of retrieved memories — specific past interactions, weighted by recency, frequency, and contextual relevance.

| Current Model | ACT-R Replacement |
|---|---|
| EMA approval rate per (state, task_type) | Retrieved chunks from similar contexts |
| Cold start threshold (< 5 observations) | Low base-level activation (few traces) → chunks below retrieval threshold |
| Staleness guard (7-day timeout) | Power-law decay — unused chunks naturally fall below threshold |
| Asymmetric regret (3x penalty for corrections) | Correction chunks are more distinctive (higher delta) → more retrievable |
| Exploration rate (15% random escalation) | Retrieval noise — sometimes unexpected chunks surface, changing the decision |

The cold start behavior emerges naturally. With zero chunks, there's nothing to retrieve — the proxy has no basis for prediction and must escalate. As chunks accumulate, the retrieval set grows. The transition from "always escalate" to "sometimes auto-approve" to "usually auto-approve" happens without explicit thresholds — it's driven by the activation levels of the accumulated memories.

---

## The Three Outcome Types

**Approve / Promote** — the proxy was right (or the human agreed with the observation). The chunk records a positive outcome. When retrieved in future decisions, it biases toward confidence.

**Correct / Dismiss** — the proxy was wrong (or the human found the observation unhelpful). The chunk records a negative outcome AND a delta (what was wrong, why it was dismissed). The delta makes the chunk more distinctive — richer content, more specific embedding — which means it is retrieved more precisely in similar future situations. Corrections are more informative than approvals, and the memory system naturally captures this because informative memories have richer associations.

**Discuss** — the human engaged but didn't decide. The chunk records the exchange. It contributes to the proxy's understanding of how the human reasons but doesn't directly bias toward confidence or caution. Dialog chunks build the episodic memory that informs the proxy's conversational style, not its gate decisions.

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
    delta: str                       # what was wrong / dismissal reason
    content: str                     # full text of the interaction
    traces: list[int]                # list of interaction sequence numbers
    embedding: list[float] | None    # vector embedding for semantic retrieval
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
    delta TEXT DEFAULT '',
    content TEXT NOT NULL,
    traces TEXT NOT NULL,            -- JSON array of interaction sequence numbers
    embedding TEXT                   -- JSON array of floats
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


def retrieval_score(
    chunk: MemoryChunk,
    context_embedding: list[float],
    current_interaction: int,
    activation_weight: float = 0.5,
    semantic_weight: float = 0.5,
    d: float = 0.5,
    s: float = 0.25,
) -> float:
    """Combined retrieval score: ACT-R activation + semantic similarity + noise."""
    b = base_level_activation(chunk.traces, current_interaction, d)
    sem = cosine_similarity(chunk.embedding, context_embedding) if chunk.embedding else 0.0
    noise = logistic_noise(s)
    return activation_weight * b + semantic_weight * sem + noise


def retrieve(
    state: str = '',
    task_type: str = '',
    context_text: str = '',
    current_interaction: int = 0,
    tau: float = -0.5,
    top_k: int = 10,
) -> list[MemoryChunk]:
    """Retrieve top-k chunks above threshold."""
    candidates = query_chunks(state=state, task_type=task_type)
    context_embedding = embed(context_text)
    scored = []
    for chunk in candidates:
        score = retrieval_score(chunk, context_embedding, current_interaction)
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
) -> MemoryChunk:
    """Record an interaction as a memory chunk.
    If chunk_id matches existing chunk, adds a trace (reinforcement).
    Otherwise creates a new chunk. Increments global interaction counter.
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
        delta=delta,
        content=content,
        traces=[current],
        embedding=embed(content),
    )
    store_chunk(chunk)
    return chunk
```

### Integration Points

1. **`consult_proxy()` in `proxy_agent.py`** — replace `.proxy-confidence.json` load + Laplace/EMA with: retrieve chunks for the current context, pass to the proxy agent prompt.

2. **`record_outcome()` in `scripts/approval_gate.py`** — replace EMA/Laplace update with: create a new chunk (or reinforce an existing one).

3. **`_calibrate_confidence()` in `proxy_agent.py`** — replace scalar confidence computation with: the retrieval set IS the confidence signal. The LLM reads the memories and calibrates itself.

4. **Discovery mode** in the Code Collaborator — same `retrieve()` function with discovery-specific state keys.
