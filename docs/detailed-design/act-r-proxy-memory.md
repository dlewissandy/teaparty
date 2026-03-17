# ACT-R Memory Model for the Human Proxy

This document describes how to replace the proxy agent's current confidence model (EMA + Laplace estimates) with an activation-based memory system derived from the ACT-R cognitive architecture. It is written for an engineer who has never used ACT-R and covers the complete theory, all formulas, and the concrete mapping to TeaParty's proxy agent.

---

## Why Replace the Current Model

The proxy currently tracks confidence as a single scalar per (state, task_type) pair — an exponential moving average of approval rates plus a Laplace smoothed estimate. This works for the narrow question "should I auto-approve at this gate?" but fails in several ways:

**No forgetting toward baseline.** EMA decays toward the running average. If the human dismissed 10 observations during a spec rewrite, EMA drives confidence to zero for that category. When the spec stabilizes, the proxy won't recover without new positive signal. It has "learned" that spec alignment doesn't matter — permanently.

**No context sensitivity.** The proxy at PLAN_ASSERT retrieves the same confidence whether the human is reviewing a plan for a security feature or a documentation update. The current model has no mechanism for context to influence retrieval.

**No distinction between habitual and episodic patterns.** "This human always cares about containment" (reinforced across 20 sessions) and "this human rejected the last plan" (one event) are stored with the same machinery. The model can't distinguish stable preferences from one-off reactions.

**No connection between gate mode and discovery mode.** The proxy operates in two modes — staffing approval gates during sessions and reviewing the codebase between sessions (see [autodiscovery.md](../autodiscovery.md)). Both modes need the same memory of the human, but the current scalar model can't represent the richer interactions that discovery mode produces.

ACT-R's declarative memory model solves all four problems with a single mechanism.

---

## ACT-R in 500 Words

ACT-R (Adaptive Control of Thought — Rational) is a cognitive architecture developed by John Anderson at Carnegie Mellon University. It is a computational model of human cognition — not a metaphor or a framework, but a running system that reproduces human performance data across hundreds of experiments on memory, learning, and decision-making.

ACT-R's central claim about memory: **the probability of retrieving a memory reflects the statistical patterns of the environment.** Things you encountered recently and frequently are more likely to be relevant now. The memory system is rational — it forgets at the rate that makes its retrievals most useful given the actual patterns of the world.

Memory in ACT-R is organized as **chunks** — structured units of knowledge. Each chunk has an **activation level** that determines how accessible it is. High-activation chunks are retrieved quickly and reliably. Low-activation chunks are effectively forgotten — still stored, but below the retrieval threshold.

Activation is not a fixed property. It changes continuously based on two factors:

1. **Base-level activation** — how often and how recently this chunk has been accessed. This is the learning-and-forgetting component.
2. **Spreading activation** — how related this chunk is to what you're currently thinking about. This is the context component.

The mathematical model for these two factors, combined with a noise term and a retrieval threshold, produces all of the memory phenomena relevant to the proxy: learning from experience, forgetting without reinforcement, context-sensitive retrieval, and graceful cold start.

---

## The Retrieval Model

Every chunk in memory has a retrieval score that combines three signals:

```
score = activation_weight * B  +  semantic_weight * cosine(chunk, context)  +  noise
```

Where:
- `B` is the **base-level activation** from ACT-R (learning and forgetting via power-law decay)
- `cosine(chunk, context)` is the **semantic similarity** between the chunk's embedding and the current context embedding (replaces ACT-R's symbolic spreading activation)
- `noise` is a random component (captures the inherent variability of memory)

Structural filtering (SQL queries on state, outcome, task_type) narrows the candidate set before scoring. The score ranks within the filtered set.

### Base-Level Activation (B)

Base-level activation reflects how often and how recently a chunk has been accessed:

```
B = ln( sum over all accesses i:  t_i ^ (-d) )
```

Where:
- `t_i` is the number of **interactions** since the i-th access of this chunk (not wall-clock time — see below)
- `d` is the **decay parameter**, standardly set to **0.5**
- `ln` is the natural logarithm
- The sum is over every time this chunk was accessed (created, retrieved, reinforced)

**How it works.** Each time a chunk is accessed, it gets a **trace**. Each trace decays as a power function of interactions elapsed: `t^(-0.5)`. The sum of all decaying traces, passed through a logarithm, gives the base-level activation.

### Interactions, Not Seconds

In the ACT-R literature, `t` is measured in seconds — laboratory experiments use wall-clock time. For the proxy, we measure `t` in **interactions**: gate decisions, dialog turns, discovery responses. Each interaction advances the clock by 1.

This is a better fit than wall-clock time for three reasons:

1. **Between sessions, nothing happens.** If the proxy handles 5 gates on Monday and none until Thursday, wall-clock decay would erode Monday's memories over 3 idle days. Interaction-based decay doesn't advance — no interactions means no decay, which is correct because nothing happened to make the memories less relevant.

2. **Anderson & Schooler's empirical basis is event-based.** Their 1991 analysis measured word *occurrences* in newspaper headlines, child-directed speech, and email. The power-law pattern they found was in events (how many headlines ago did this word last appear?), not in seconds. The environment's statistical structure is event-based; so should the memory system's.

3. **Experience scales with activity, not calendar time.** A proxy that handled 100 interactions over a busy week has far more trace accumulation than one that handled 5 over the same calendar period. The memory should reflect *experience*, not elapsed time.

**Worked example.** A chunk was accessed 3 times: 2 interactions ago, 10 interactions ago, and 50 interactions ago.

```
B = ln( 2^(-0.5) + 10^(-0.5) + 50^(-0.5) )
  = ln( 0.707 + 0.316 + 0.141 )
  = ln( 1.164 )
  = 0.152
```

Now the proxy has another interaction (the chunk is accessed again, t=1):

```
B = ln( 1^(-0.5) + 3^(-0.5) + 11^(-0.5) + 51^(-0.5) )
  = ln( 1.000 + 0.577 + 0.302 + 0.140 )
  = ln( 2.019 )
  = 0.703
```

The activation jumped from 0.152 to 0.703 — the chunk went from moderately accessible to highly accessible, because it was just accessed.

**Key properties:**
- Recent accesses contribute much more than old ones (power-law decay)
- Many accesses accumulate — a chunk accessed 50 times decays much slower than one accessed once
- The logarithm compresses the range — you need exponentially more accesses to get linear activation gains
- At `d = 0.5`, a single trace loses half its contribution when the interaction count quadruples
- Between sessions, the interaction counter doesn't advance — memories don't decay while the system is idle

### Why d = 0.5?

Anderson and Schooler (1991) showed that this value isn't arbitrary — it matches the statistical structure of the real world. They analyzed newspaper headlines, child-directed speech, and email archives. In all three domains, the probability that an item encountered in the past would be relevant now followed a power function with an exponent near 0.5. Crucially, their analysis was event-based — they measured relevance as a function of how many *events* ago something last appeared, not how many seconds. This is why interaction-based `t` is the natural unit: the empirical basis for `d = 0.5` was always about event intervals, not clock intervals.

The memory system's decay rate matches the environment's relevance rate. Forgetting is not a bug — it is a rational response to the statistics of the world.

### Context Sensitivity: Structural Filtering + Semantic Retrieval

In ACT-R, context sensitivity is handled by **spreading activation** — a tag-based mechanism where chunks associated with the current focus receive an activation boost. ACT-R uses this because it operates on symbolic representations that have no notion of semantic similarity.

We have something better: **vector embeddings**. Each chunk's free-text content (the delta, the conversation, the observation) is embedded into a dense vector via the same embedding infrastructure used by the learning system (`memory_indexer.py`). Semantic similarity between the current context and stored memories is computed directly via cosine similarity, rather than indirectly via shared tags and fan effects.

This is not a novel combination. Activation-weighted embedding retrieval is the pattern underlying modern AI memory systems, including Claude's own persistent memory. The approach is deployed at scale.

The proxy's context sensitivity operates in two layers:

**Structural filtering** narrows the search space using the chunk's categorical fields. "Show me memories from PLAN_ASSERT gates on security tasks" is a SQL query on `state` and `task_type`. This is fast, exact, and captures the relational structure that embeddings miss — the ordering of the tuple (who did what to whom at which gate) is preserved in the schema, not in the embedding.

**Semantic ranking** orders the filtered results by meaning. Within the set of PLAN_ASSERT memories, "missing rollback plan" should rank near "no recovery strategy" even though the words differ. Cosine similarity on the embedded content handles this.

The combined retrieval score:

```
score = activation_weight * B  +  semantic_weight * cosine(chunk_embedding, context_embedding)
```

Where:
- `B` is the base-level activation (recency and frequency)
- `cosine(...)` is the semantic similarity between the chunk and the current context
- `activation_weight` and `semantic_weight` control the balance (starting point: 0.5 / 0.5)

This replaces ACT-R's spreading activation equation (`S = Σ W_j * S_ji`) with a mechanism that is both simpler and more powerful:
- No tag maintenance or fan-count bookkeeping
- Semantic similarity captures relationships that no tag vocabulary could enumerate
- Structural filtering preserves the tuple ordering that embeddings would lose
- The base-level activation component is unchanged from ACT-R

### Noise

```
noise ~ Logistic(0, s)
```

Where `s` is the **noise parameter**, standardly set to **0.25**. This adds randomness to retrieval — sometimes you remember something unexpected, sometimes you fail to retrieve something you should. The noise ensures the system doesn't become deterministic, which would prevent exploration of its own memory.

For implementation: sample from a logistic distribution with location 0 and scale `s`. In Python: `random.random()` transformed via `s * log(p / (1 - p))` where p is uniform on (0, 1).

### Retrieval

A chunk is retrieved if its total score (combining activation, semantic similarity, and noise) exceeds the **retrieval threshold** `tau`:

```
Retrieved if A > tau
```

The standard value is `tau = -0.5`. Chunks with activation below this threshold are effectively forgotten — they exist in memory but cannot be accessed.

The **probability of retrieval** follows a soft threshold (not a hard cutoff):

```
P(retrieve) = 1 / (1 + exp(-(A - tau) / s))
```

This is a logistic function centered at the threshold. Chunks well above threshold are almost certainly retrieved. Chunks well below are almost certainly not. Chunks near the threshold are retrieved probabilistically — sometimes yes, sometimes no.

**Retrieval latency** also follows from activation:

```
latency = F * exp(-f * A)
```

Where `F` and `f` are scaling parameters (standardly `F = 1.0`, `f = 1.0`). High-activation chunks are retrieved faster. This isn't directly relevant to the proxy implementation but explains why the model predicts human reaction times so accurately.

---

## Standard Parameter Values

| Parameter | Symbol | Starting Value | Role | Source |
|-----------|--------|---------------|------|--------|
| Decay | d | 0.5 | Power-law decay exponent for traces | ACT-R standard; Anderson & Schooler 1991 |
| Noise | s | 0.25 | Scale of retrieval noise (logistic) | ACT-R standard |
| Retrieval threshold | tau | -0.5 | Minimum score for retrieval | ACT-R standard |
| Activation weight | — | 0.5 | Weight of base-level activation in score | Design parameter; calibrate empirically |
| Semantic weight | — | 0.5 | Weight of cosine similarity in score | Design parameter; calibrate empirically |

The ACT-R parameters (d, s, tau) are empirically validated across hundreds of cognitive models. The activation/semantic weights are design parameters for the hybrid retrieval — start at equal weighting and adjust based on retrieval quality in real sessions.

Note: ACT-R's spreading activation parameters (S_max, W, fan counts) are not used. Semantic similarity via embeddings replaces that mechanism entirely.

---

## Mapping to the Proxy Agent

### What Are the Chunks?

Each chunk represents a **memory of an interaction** between the proxy and the human. A chunk is created whenever the proxy observes or participates in a decision. The chunk's content is a structured record:

```python
{
    "type": "gate_outcome",          # or "dialog_turn", "discovery_response"
    "state": "PLAN_ASSERT",          # CfA state where interaction occurred
    "task_type": "security",         # project/task category
    "outcome": "approve",            # approve, correct, dismiss, promote, discuss
    "lens": "",                      # for discovery mode: which lens produced this
    "delta": "",                     # what the proxy got wrong (prediction vs reality)
    "context_tags": ["proxy", "plan", "security"],  # for spreading activation
    "traces": [                      # list of interaction sequence numbers
        42,                          # created at interaction #42
        47,                          # retrieved at interaction #47
    ]
}
```

### When Are Traces Created?

A trace is added to a chunk when:

1. **The chunk is created.** The proxy observes a gate outcome, a dialog exchange, or a discovery response. This is the first trace.
2. **The chunk is retrieved.** When the proxy retrieves this chunk while making a decision (via spreading activation from the current context), the retrieval itself reinforces the memory. Memories that are useful stay active; memories that are never retrieved decay.
3. **The chunk is explicitly reinforced.** When a new interaction produces a similar outcome to a past one — the human approves at PLAN_ASSERT again — the matching chunk gets an additional trace even if it wasn't explicitly retrieved.

### How Does an Interaction Become a Chunk?

**Gate mode (during sessions):**

1. The proxy is consulted at a CfA gate (e.g., PLAN_ASSERT)
2. The proxy generates a prediction (approve/correct/escalate)
3. The human responds (or the proxy acts autonomously if confident)
4. A chunk is created with:
   - `state` = the CfA state
   - `task_type` = the project slug
   - `outcome` = what actually happened (approve, correct, etc.)
   - `delta` = if the proxy predicted wrong, what was the difference
   - `context_tags` = derived from the state, task, and artifact content
5. The chunk is embedded (for vector retrieval) and stored with its first trace timestamped to now

**Discovery mode (between sessions):**

1. The proxy (in collaborator mode) surfaces an observation
2. The human responds: promote, dismiss, or discuss
3. A chunk is created with:
   - `state` = `DISCOVERY_{lens}` (e.g., `DISCOVERY_SPEC_ALIGNMENT`)
   - `outcome` = promote, dismiss, or discuss
   - `lens` = which review lens produced the observation
   - `delta` = the dismissal reason (if dismissed) or the discussion content
   - `context_tags` = derived from the lens, code area, and observation topic

**Dialog turns (within discussions):**

Each conversational exchange in a discussion creates its own chunk:
   - `type` = `dialog_turn`
   - Content = the exchange (human question + agent response)
   - `context_tags` = derived from the topic and related concepts
   - These chunks capture *how* the human reasons, not just *what* they decided

### How Does the Proxy Use Activation for Decisions?

When the proxy needs to make a decision — whether to auto-approve at a gate, what observation to surface, how to respond in a discussion — it retrieves relevant chunks from memory:

1. **Set the spreading activation sources.** The current context (CfA state, task type, lens, topic keywords) becomes the set of sources `j` in the spreading activation equation.

2. **Compute activation for all chunks.** For each chunk in memory, compute `A = B + S + noise`. Base-level activation reflects how often and recently each chunk was accessed. Spreading activation boosts chunks related to the current context. Noise adds variability.

3. **Retrieve chunks above threshold.** Chunks with `A > tau` are retrieved. These are the memories the proxy "has in mind" when making its decision.

4. **Reason over retrieved chunks.** The proxy's LLM prompt receives the retrieved chunks as context: "Here are your relevant memories of working with this human..." The LLM reasons over them to produce a prediction, an observation, or a response.

5. **Record the outcome.** After the human responds, a new chunk is created (or an existing chunk is reinforced with a new trace). The cycle continues.

### Replacing the Current Confidence Model

The current model answers one question: "what is my confidence that this human will approve at this gate?" It answers with a scalar: the EMA approval rate.

The ACT-R model answers a richer question: "what do I know about how this human has responded in situations similar to this one?" It answers with a set of retrieved memories — specific past interactions, weighted by recency, frequency, and contextual relevance.

The mapping:

| Current Model | ACT-R Replacement |
|---|---|
| EMA approval rate per (state, task_type) | Retrieved chunks from similar contexts |
| Cold start threshold (< 5 observations) | Low base-level activation (few traces) → chunks below retrieval threshold |
| Staleness guard (7-day timeout) | Power-law decay — unused chunks naturally fall below threshold |
| Asymmetric regret (3x penalty for corrections) | Correction chunks are more distinctive (higher delta) → more retrievable |
| Exploration rate (15% random escalation) | Retrieval noise — sometimes unexpected chunks surface, changing the decision |

The cold start behavior emerges naturally. With zero chunks, there's nothing to retrieve — the proxy has no basis for prediction and must escalate. As chunks accumulate, the retrieval set grows. The transition from "always escalate" to "sometimes auto-approve" to "usually auto-approve" happens without explicit thresholds — it's driven by the activation levels of the accumulated memories.

### The Three Outcome Types

The current model treats outcomes as binary: approve or reject. Discovery mode adds a third: discuss. How do these map to chunks?

**Approve / Promote** — the proxy was right (or the human agreed with the observation). The chunk records a positive outcome. When retrieved in future decisions, it biases toward confidence.

**Correct / Dismiss** — the proxy was wrong (or the human found the observation unhelpful). The chunk records a negative outcome AND a delta (what was wrong, why it was dismissed). The delta makes the chunk more distinctive — more specific context tags, richer content — which means it is retrieved more precisely in similar future situations. Corrections are more informative than approvals, and the memory system naturally captures this because informative memories have richer associations.

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
    context_tags: list[str]          # for spreading activation fan computation
    traces: list[int]                # list of interaction sequence numbers
    embedding: list[float] | None    # vector embedding for hybrid retrieval
```

### Storage

Chunks are stored in a SQLite database (extending the existing `.memory.db` pattern):

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
    """Compute B = ln(sum t_i^(-d)) for a chunk's trace history.

    traces: list of interaction sequence numbers when this chunk was accessed.
    current_interaction: the global interaction counter right now.
    d: decay parameter (standard: 0.5).
    """
    total = 0.0
    for trace in traces:
        age = max(current_interaction - trace, 1)  # interactions since this access
        total += age ** (-d)
    if total <= 0:
        return -float('inf')  # effectively forgotten
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
    """Compute the combined retrieval score for a chunk.

    Combines ACT-R base-level activation (recency/frequency) with
    semantic similarity (embedding cosine distance) plus noise.
    """
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
    """Retrieve the top-k chunks above threshold.

    1. Structural filter: SQL query on state, task_type (exact match)
    2. Semantic ranking: score by activation + embedding similarity
    3. Threshold: discard chunks below tau
    4. Return top-k by score
    """
    # Step 1: structural filter
    candidates = query_chunks(state=state, task_type=task_type)

    # Step 2: embed the current context
    context_embedding = embed(context_text)

    # Step 3: score and filter
    scored = []
    for chunk in candidates:
        score = retrieval_score(chunk, context_embedding, current_interaction)
        if score > tau:
            scored.append((score, chunk))

    # Step 4: top-k
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

    If chunk_id matches an existing chunk (reinforcement), adds a trace.
    Otherwise creates a new chunk with its first trace.
    Increments the global interaction counter.
    """
    current = increment_interaction_counter()

    if chunk_id and chunk_exists(chunk_id):
        # Reinforcement: add a trace to existing chunk
        add_trace(chunk_id, current)
        return get_chunk(chunk_id)

    # New chunk
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

The ACT-R memory replaces the current confidence model at these call sites:

1. **`consult_proxy()` in `proxy_agent.py`** — currently loads the `.proxy-confidence.json` model and computes Laplace/EMA confidence. Replace with: retrieve chunks for the current (state, task_type) context, pass retrieved memories to the proxy agent prompt, let the LLM reason over them.

2. **`record_outcome()` in `scripts/approval_gate.py`** — currently updates EMA and Laplace counts. Replace with: create a new chunk (or add a trace to a matching existing chunk) in the proxy memory database.

3. **`_calibrate_confidence()` in `proxy_agent.py`** — currently computes a scalar confidence from statistical history. Replace with: the retrieval set itself IS the confidence signal. Many retrieved approval chunks → high confidence. Retrieved correction chunks with similar context → low confidence. The LLM reads the memories and calibrates itself.

4. **Discovery mode** in the Code Collaborator — uses the same `retrieve()` function with discovery-specific context tags. The proxy's memory spans both modes seamlessly.

---

## What Changes, What Stays

**Changes:**
- `.proxy-confidence.json` (scalar EMA/Laplace per state-task pair) → `proxy_memory.db` (chunk-based activation memory)
- `compute_confidence()` → `retrieve()` + LLM reasoning over retrieved chunks
- `record_outcome()` → chunk creation with traces
- Cold start threshold (hardcoded 5 observations) → emergent from low activation
- Staleness guard (hardcoded 7 days) → emergent from power-law decay
- Exploration rate (hardcoded 15%) → emergent from retrieval noise

**Stays:**
- The proxy agent prompt structure (receives context, generates prediction)
- The proxy agent's tools (file read, dialog)
- The escalation decision point (confident → act, not confident → ask)
- The delta-based learning signal (prediction vs. reality)
- The intake dialog flow
- The discovery mode concept and discussion lifecycle

The architectural change is in *how the proxy knows what it knows* — not in what it does with that knowledge.

---

## Migration Path

The transition can be incremental:

1. **Phase 1: Shadow mode.** Run ACT-R retrieval alongside the existing EMA model. Log both decisions. Compare. Don't change behavior yet.
2. **Phase 2: Hybrid.** Use ACT-R retrieval to enrich the proxy agent's prompt (pass retrieved memories as context) while still using EMA for the auto-approve/escalate decision.
3. **Phase 3: Full replacement.** Remove EMA. The proxy's confidence comes entirely from what it retrieves and the LLM's reasoning over those memories.

Phase 1 can start immediately — it requires only the chunk storage and retrieval functions, no changes to the proxy's decision path.

---

## What's Established vs. What's Novel

This design combines components with very different levels of empirical support. An engineer should know which parts are solid ground and which require experimentation.

### Established

**ACT-R base-level activation** — the power-law decay equation (`B = ln(Σ t_i^(-d))`) with `d = 0.5`. Validated across hundreds of published cognitive models reproducing human memory performance (reaction times, error rates, forgetting curves). The most empirically grounded component of this design. Source: Anderson & Lebiere 1998; Anderson & Schooler 1991.

**Interaction-based time units** — Anderson & Schooler's 1991 analysis measured relevance as a function of event intervals (how many headlines ago, how many emails ago), not clock time. Using interaction counts as `t` is faithful to the original empirical basis, not a deviation from it.

**Embedding retrieval for semantic similarity** — dense vector embeddings with cosine similarity for document retrieval. Widely deployed, well-understood. We already use this in `memory_indexer.py`.

**Activation-weighted embedding retrieval** — combining recency/frequency weighting with semantic similarity for memory retrieval. This is the pattern underlying modern AI memory systems (including Claude's persistent memory). Deployed at scale, not experimental.

**LLM reasoning over retrieved memories to predict human behavior** — Park et al. (2024) built generative agent simulations of 1,052 real people from interview transcripts. The agents replicated survey responses with 85% accuracy using LLM in-context reasoning over retrieved personal data. This validates the premise that conversational history, retrieved by relevance, is sufficient context for an LLM to predict individual human behavior.

### Design Parameters Requiring Calibration

**Activation/semantic weight balance** (starting at 0.5 / 0.5) — how much to weight recency/frequency vs. semantic similarity. This balance likely varies by use case: gate decisions may favor activation (recent similar gates are most relevant), while discovery mode may favor semantics (topically related observations matter more than recent ones). Calibrate against real session data.

**Retrieval threshold** (tau = -0.5) — the ACT-R standard was calibrated for human lab experiments. The right threshold for proxy memory retrieval may differ. Too low: noisy retrieval. Too high: useful memories missed. Shadow mode (Phase 1) will reveal the right value.

**Chunk granularity** — what constitutes one chunk (a gate decision? a dialog turn? an observation + response?) is a design decision, not an empirical finding. The choices in this document are reasonable starting points but may need revision based on retrieval quality.

---

## References

**Anderson, J. R., & Lebiere, C.** (1998). *The Atomic Components of Thought.* Lawrence Erlbaum Associates. — The definitive ACT-R reference. Complete derivation of the activation equations, spreading activation, retrieval dynamics, and parameter values. Chapter 4 covers declarative memory in full.

**Anderson, J. R., & Schooler, L. J.** (1991). Reflections of the environment in memory. *Psychological Science*, 2(6), 396-408. — Empirical basis for the power-law decay parameter (d = 0.5). Demonstrates that human forgetting curves match the statistical structure of real-world information relevance. Read this first for intuition about why the math works.

**ACT-R Tutorial, Unit 4: Activation of Chunks and Base-Level Learning.** Carnegie Mellon University. http://act-r.psy.cmu.edu/wordpress/wp-content/themes/ACT-R/tutorials/unit4.htm — Step-by-step tutorial with worked examples and code. The best starting point for implementation.
