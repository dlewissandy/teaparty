# ACT-R Proxy Mapping: Chunks, Traces, and Retrieval

ACT-R's declarative memory concepts mapped to the proxy agent's concrete structures. For the theory and equations, see [overview.md](overview.md). For the motivation and migration plan, see [memory.md](memory.md). For two-pass prediction and learned attention, see [sensorium.md](sensorium.md).

---

## What Are the Chunks?

Each chunk represents a **memory of an interaction** between the proxy and the human. A chunk is created whenever the proxy observes or participates in a decision. The chunk is a structured tuple.

```python
{
    # Identity / metadata (carried for audit and prompt serialization;
    # not used as retrieval filters)
    "type": "gate_outcome",          # or "dialog_turn", "review_correction", "steering", "withdrawal"
    "state": "PLAN",                 # CfA state where the interaction occurred (or "" for non-CfA)
    "task_type": "security",         # task category — analytics only
    "outcome": "correct",            # approve, correct, dismiss, promote, discuss
    "lens": "",                      # discovery lens, if applicable

    # Content
    "human_response": "Add a rollback strategy for the migration",
    "delta": "",                     # what the proxy got wrong vs human response
    "content": "...",                # full text of the interaction (rendered into the prompt)

    # Memory dynamics
    "traces": [42, 47],              # interaction sequence numbers when accessed

    # Three-dim retrieval embeddings (issue #432)
    "embedding_conversation": [...], # the thread's conversation through this stimulus
    "embedding_job": [...],          # the job's PROMPT.txt (the human's request)
    "embedding_project": [...],      # the project description (project.yaml)

    # Salience embedding — independent retrieval path (sensorium.md)
    "embedding_salience": [...],     # the prediction delta (what surprised the proxy)
}
```

**Retrieval is purely vector-based** (issue #432). Identity columns like `state`, `task_type`, and `lens` are recorded for audit and prompt context but do not partition the candidate set. Discrimination at retrieval time comes from cosine similarity over the three rich embeddings:

| Embedding | What it captures | Source text at recording |
|-----------|------------------|--------------------------|
| **Conversation** | the dialog leading to the chunk's stimulus | thread history through the latest turn |
| **Job** | the larger intent the proxy is serving | `.teaparty/jobs/{job-id}/PROMPT.txt` |
| **Project** | the codebase and conventions | `description:` from `.teaparty/project/project.yaml` |

The proxy is general — it can be asked about a codebase, a movie, a personal decision. There is no guaranteed artifact, no guaranteed CfA state, no guaranteed task category at retrieval. Only the three above are universally available. Conversation carries the bulk of contextual signal; job and project add the surrounding intent and the codebase identity. Activation (recency × frequency) handles the temporal layer; cosine on the three embeddings handles the contextual layer.

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

## Retrieval: Activation Filter + Weighted-Cosine Ranking

In ACT-R, context sensitivity is handled by **spreading activation** — a graph-based mechanism routing activation from the current focus to associated chunks via typed symbolic associations.

We replace spreading activation with **cosine similarity over text embeddings**. The chunk's three rich embeddings (conversation, job, project) are compared at retrieval time against query embeddings built from the proxy's current context using the same embedding model. Cosine on rich text discriminates; the structural fields are recorded but not used for filtering (issue #432).

This combination of activation-based decay with embedding similarity has direct precedent in the research literature. Honda, Fujita, Zempo, & Fukushima (HAI '25) combine ACT-R base-level activation with cosine similarity for LLM agent memory retrieval. Meghdadi, Duff, & Demberg (Frontiers in Language Sciences, 2026) demonstrate that language model embedding cosine similarity is a valid substitute for hand-coded association strengths within the ACT-R framework. Park, J.S., et al.'s (2023) generative agents use a structurally similar weighted combination of recency, importance, and relevance.

Retrieval operates in two stages.

**Stage 1: Activation filtering.** Compute raw base-level activation B for each chunk. Discard chunks with B below tau (-0.5). This is the ACT-R retrieval threshold. Chunks below threshold are effectively forgotten.

**Stage 2: Composite scoring and ranking.** For survivors, compute the composite score:

```
cosine = w_conv · cos(chunk.conversation, ctx.conversation)
       + w_job  · cos(chunk.job,          ctx.job)
       + w_proj · cos(chunk.project,      ctx.project)

composite = activation_weight · tanh(B − τ)
          + semantic_weight   · cosine
          + noise
```

Where:
- `B` is the base-level activation (recency × frequency via ACT-R)
- `tanh(B − τ)` maps B to (-1, 1) with a zero crossing at τ (issue #416)
- `w_conv = 0.9`, `w_job = 0.05`, `w_proj = 0.05` — conversation carries the bulk of contextual signal at retrieval time
- A missing chunk- or query-side embedding on a dimension contributes zero (no renormalization), so chunks with sparser embeddings degrade gracefully toward activation-only ranking
- `noise` is logistic noise (see [overview.md](overview.md))
- `activation_weight` and `semantic_weight` default to 0.5 each

**Why these weights.** Conversation captures what is being said and what has just been said — the moment-to-moment context that most strongly determines relevance. Job and project add the surrounding intent and the codebase's identity, but the same job often spans many distinguishable conversations, and the same project spans many jobs. Conversation is the dominant signal; job and project are tiebreakers.

**Why no `/N` averaging.** The weights sum to 1.0 explicitly. A chunk that perfectly matches the current context on all three dimensions reaches `cosine = 1.0`. The old `/4` averaging capped reachable cosine at 0.75 even on a perfect three-of-four match because `response` could never be queried.

| Parameter | Starting Value | Role |
|-----------|---------------|------|
| Activation weight | 0.5 | Weight of `tanh(B − τ)` |
| Semantic weight | 0.5 | Weight of the weighted-cosine term |
| `w_conv` | 0.9 | Conversation cosine weight |
| `w_job` | 0.05 | Job cosine weight |
| `w_proj` | 0.05 | Project cosine weight |
| Noise scale (s) | 0.08 | Logistic noise (std dev ≈ πs/√3 ≈ 0.145) |

---

## How Does the Proxy Use Retrieved Chunks?

When the proxy needs to act (what question to ask at a gate, what observation to surface, how to respond in a discussion):

1. **Filter by activation.** Compute raw B for every non-deleted chunk. Discard chunks with B below tau (-0.5).
2. **Score.** For each survivor, compute the composite score (`tanh(B − τ)` activation contribution plus weighted-cosine semantic similarity plus noise).
3. **Retrieve top-k.** Return the highest-scoring chunks.
4. **Serialize and embed.** Convert retrieved chunks to text for the proxy's LLM prompt. The serialization includes the chunk's metadata (state, task_type, outcome) and content. Embeddings are not included (they are binary noise). Each chunk occupies approximately 400-600 tokens; the chunk context is limited to a budget (e.g., 10 chunks at 5000 tokens).
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
    id: str                              # unique identifier
    type: str                            # gate_outcome, dialog_turn, review_correction, steering, withdrawal
    state: str                           # CfA state at recording time (or '' for non-CfA)
    task_type: str                       # task category — analytics only
    outcome: str                         # approve, correct, dismiss, promote, discuss
    lens: str                            # discovery lens, if applicable
    human_response: str                  # what the human actually said
    delta: str                           # proxy error vs human response
    content: str                         # full text of the interaction (for prompt serialization)
    traces: list[int]                    # interaction sequence numbers
    embedding_model: str                 # which embedding model produced the vectors
    embedding_conversation: list[float] | None
    embedding_job: list[float] | None
    embedding_project: list[float] | None
    embedding_salience: list[float] | None
    # Two-pass prediction fields (sensorium.md)
    prior_confidence: float
    posterior_confidence: float
    prediction_delta: str
    salient_percepts: list[str]
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
    prior_confidence REAL DEFAULT 0,
    posterior_confidence REAL DEFAULT 0,
    prediction_delta TEXT DEFAULT '',
    salient_percepts TEXT DEFAULT '[]', -- JSON array of strings
    human_response TEXT DEFAULT '',
    delta TEXT DEFAULT '',
    content TEXT NOT NULL,
    traces TEXT NOT NULL,              -- JSON array of interaction sequence numbers
    embedding_model TEXT DEFAULT '',
    embedding_conversation TEXT,       -- JSON array of floats
    embedding_job TEXT,
    embedding_project TEXT,
    embedding_salience TEXT,
    deleted_at INTEGER DEFAULT NULL    -- soft-delete timestamp
);

CREATE TABLE proxy_state (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
INSERT OR IGNORE INTO proxy_state (key, value) VALUES ('interaction_counter', 0);
```

### Core Functions

```python
SEMANTIC_DIMS = ('conversation', 'job', 'project')
COSINE_WEIGHT_CONVERSATION = 0.9
COSINE_WEIGHT_JOB = 0.05
COSINE_WEIGHT_PROJECT = 0.05


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
    d: float = 0.5, s: float = 0.08, tau: float = -0.5,
) -> float:
    """tanh(B − τ) activation + weighted three-dim cosine + noise.

    Missing chunk- or query-side embeddings on a dimension contribute
    zero (no renormalization).
    """
    b = base_level_activation(chunk.traces, current_interaction, d)
    b_norm = math.tanh(b - tau)

    weights = {
        'conversation': COSINE_WEIGHT_CONVERSATION,
        'job':          COSINE_WEIGHT_JOB,
        'project':      COSINE_WEIGHT_PROJECT,
    }
    chunk_vecs = {
        'conversation': chunk.embedding_conversation,
        'job':          chunk.embedding_job,
        'project':      chunk.embedding_project,
    }
    sem = 0.0
    for dim, w in weights.items():
        cv = chunk_vecs[dim]
        qv = context_embeddings.get(dim)
        if cv and qv:
            sem += w * cosine_similarity(cv, qv)

    return activation_weight * b_norm + semantic_weight * sem + logistic_noise(s)


def retrieve(
    context_embeddings: dict[str, list[float]] | None = None,
    current_interaction: int = 0,
    tau: float = -0.5, top_k: int = 10,
) -> list[MemoryChunk]:
    """Two-stage retrieval: activation filter, then composite ranking."""
    context_embeddings = context_embeddings or {}
    candidates = query_chunks()  # all non-deleted chunks
    survivors = [c for c in candidates
                 if base_level_activation(c.traces, current_interaction) > tau]
    scored = [(composite_score(c, context_embeddings, current_interaction, tau=tau), c)
              for c in survivors]
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:top_k]]


def record_interaction(
    *, conversation_text: str, job_text: str, project_text: str,
    type: str, state: str, task_type: str, outcome: str, content: str,
    human_response: str = '', prediction_delta: str = '',
    embedding_model: str = '',
) -> MemoryChunk:
    """Record an interaction with the three-dim retrieval embeddings populated."""
    current = increment_interaction_counter()
    chunk = MemoryChunk(
        id=generate_id(),
        type=type, state=state, task_type=task_type, outcome=outcome,
        content=content, human_response=human_response,
        prediction_delta=prediction_delta,
        traces=[current],
        embedding_model=embedding_model,
        embedding_conversation=embed(conversation_text) if conversation_text else None,
        embedding_job=embed(job_text) if job_text else None,
        embedding_project=embed(project_text) if project_text else None,
        embedding_salience=embed(prediction_delta) if prediction_delta else None,
    )
    store_chunk(chunk)
    return chunk
```

### Integration Points

1. **`proxy_build_prompt` in `teaparty/proxy/hooks.py`** — composes conversation/job/project context, embeds it, and passes as `context_embeddings` to `retrieve_chunks`.
2. **`record_escalation_chunk` in `teaparty/proxy/hooks.py`** — fires after `AskQuestionRunner.run` completes (the §7 [ask] / [respond] cycle). The conversation embedding holds the question+answer dialog. This is the routine recording site; the proxy's memory grows from every escalation.
3. **`proxy_post_invoke` in `teaparty/proxy/hooks.py`** — populates `embedding_conversation`/`embedding_job`/`embedding_project` on review-correction chunks (`[CORRECTION:...]` marker).
4. **`_record_withdrawal_memory_chunk` in `teaparty/workspace/withdraw.py`** — same population path on withdrawal chunks.
5. **`record_steering_chunk` in `teaparty/proxy/memory.py`** — embeds the steering directive itself as the conversation vector so it surfaces broadly via cosine.

The text sources are read once per session: `conversation` from the session's message log; `job` from `.teaparty/jobs/{job-id}/PROMPT.txt`; `project` from `description:` in `.teaparty/project/project.yaml`.

---

## References

**Park, J.S., et al.** (2023). Generative Agents: Interactive Simulacra of Human Behavior. *UIST '23*. — Weighted combination of recency, importance, and relevance with min-max normalization. Direct precedent for hybrid retrieval scoring.

**Honda, Y., Fujita, Y., Zempo, K., & Fukushima, S.** (2025). Human-Like Remembering and Forgetting in LLM Agents: An ACT-R-Inspired Memory Architecture. In *Proceedings of the 13th International Conference on Human-Agent Interaction* (HAI '25), pp. 229-237. ACM. DOI: 10.1145/3765766.3765803 — ACT-R base-level activation plus cosine similarity for LLM agent memory retrieval. Best Paper Award, HAI 2025.

**Meghdadi, M., Duff, J., & Demberg, V.** (2026). Integrating language model embeddings into the ACT-R cognitive modeling framework. *Frontiers in Language Sciences*, 5. DOI: 10.3389/flang.2026.1721326 — Demonstrates that LM embedding cosine similarity is a valid substitute for hand-coded association strengths within the ACT-R framework. The paper's domain is psycholinguistic modeling (associative priming in the Lexical Decision Task); the relevance here is the methodological pattern of using LM embeddings where ACT-R uses symbolic associations.

**Petrov, A.** (2006). Computationally Efficient Approximation of the Base-Level Learning Equation in ACT-R. In *Proceedings of the Seventh International Conference on Cognitive Modeling* (ICCM '06). — Hybrid approximation combining the ACT-R standard formula with direct computation, providing more accurate activation estimates than naive averaging.
