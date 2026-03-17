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

## The Activation Equation

Every chunk in memory has a total activation `A`:

```
A = B + S + noise
```

Where:
- `B` is the **base-level activation** (learning and forgetting)
- `S` is the **spreading activation** (context sensitivity)
- `noise` is a random component (captures the inherent variability of memory)

### Base-Level Activation (B)

Base-level activation reflects how often and how recently a chunk has been accessed:

```
B = ln( sum over all accesses i:  t_i ^ (-d) )
```

Where:
- `t_i` is the time (in seconds) since the i-th access of this chunk
- `d` is the **decay parameter**, standardly set to **0.5**
- `ln` is the natural logarithm
- The sum is over every time this chunk was accessed (created, retrieved, reinforced)

**How it works.** Each time a chunk is accessed, it gets a **trace**. Each trace decays as a power function of time: `t^(-0.5)`. The sum of all decaying traces, passed through a logarithm, gives the base-level activation.

**Worked example.** A chunk was accessed 3 times: 10 seconds ago, 100 seconds ago, and 10,000 seconds ago.

```
B = ln( 10^(-0.5) + 100^(-0.5) + 10000^(-0.5) )
  = ln( 0.316 + 0.100 + 0.010 )
  = ln( 0.426 )
  = -0.853
```

Now suppose the chunk is accessed again (right now, t=0... well, t=1 second to avoid division by zero):

```
B = ln( 1^(-0.5) + 11^(-0.5) + 101^(-0.5) + 10001^(-0.5) )
  = ln( 1.000 + 0.302 + 0.100 + 0.010 )
  = ln( 1.412 )
  = 0.345
```

The activation jumped from -0.853 to 0.345 — the chunk went from hard to retrieve to easy to retrieve, because it was just accessed.

**Key properties:**
- Recent accesses contribute much more than old ones (power-law decay)
- Many accesses accumulate — a chunk accessed 50 times decays much slower than one accessed once
- The logarithm compresses the range — you need exponentially more accesses to get linear activation gains
- At `d = 0.5`, a single trace loses half its contribution when the elapsed time quadruples

### Why d = 0.5?

Anderson and Schooler (1991) showed that this value isn't arbitrary — it matches the statistical structure of the real world. They analyzed newspaper headlines, child-directed speech, and email archives. In all three domains, the probability that a word encountered in the past would be relevant now followed a power function with an exponent near 0.5. The memory system's decay rate matches the environment's relevance rate. Forgetting is not a bug — it is a rational response to the statistics of the world.

### Spreading Activation (S)

Spreading activation captures context: chunks related to what you're currently thinking about receive a boost.

```
S = sum over all sources j:  W_j * S_ji
```

Where:
- `j` ranges over the **sources of activation** — the chunks currently in the agent's focus (e.g., the current CfA state, the current task, the current lens)
- `W_j` is the **attentional weight** of source j. The total attention is a fixed budget (standardly `W = 1.0`) divided among the sources: if there are 3 sources, each gets `W_j = 1/3`
- `S_ji` is the **associative strength** from source j to chunk i

The associative strength `S_ji` reflects how strongly j and i are connected:

```
S_ji = S_max - ln(fan_j)
```

Where:
- `S_max` is the maximum associative strength (standardly **1.5**)
- `fan_j` is the number of chunks associated with source j

**The fan effect.** A source connected to many chunks spreads its activation thinly — each association is weaker. A source connected to few chunks concentrates its activation — each association is stronger. This is why specific contexts produce better retrieval than vague ones: "proxy at PLAN_ASSERT for security task" activates fewer, more relevant chunks than "proxy at any gate for any task."

**Worked example.** The agent is currently focused on two things: the CfA state `PLAN_ASSERT` (associated with 8 chunks in memory) and the task type `security` (associated with 3 chunks in memory). The attention budget W = 1.0 is split evenly: W_j = 0.5 each.

For a chunk that is associated with both sources:
```
S = 0.5 * (1.5 - ln(8)) + 0.5 * (1.5 - ln(3))
  = 0.5 * (1.5 - 2.08) + 0.5 * (1.5 - 1.10)
  = 0.5 * (-0.58) + 0.5 * (0.40)
  = -0.29 + 0.20
  = -0.09
```

For a chunk associated only with PLAN_ASSERT (not security):
```
S = 0.5 * (1.5 - ln(8)) + 0
  = -0.29
```

The chunk associated with both the state and the task type gets more spreading activation than one associated with only the state. Context narrows retrieval.

### Noise

```
noise ~ Logistic(0, s)
```

Where `s` is the **noise parameter**, standardly set to **0.25**. This adds randomness to retrieval — sometimes you remember something unexpected, sometimes you fail to retrieve something you should. The noise ensures the system doesn't become deterministic, which would prevent exploration of its own memory.

For implementation: sample from a logistic distribution with location 0 and scale `s`. In Python: `random.random()` transformed via `s * log(p / (1 - p))` where p is uniform on (0, 1).

### Retrieval

A chunk is retrieved if its total activation `A = B + S + noise` exceeds the **retrieval threshold** `tau`:

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

| Parameter | Symbol | Standard Value | Role |
|-----------|--------|---------------|------|
| Decay | d | 0.5 | Power-law decay exponent for traces |
| Noise | s | 0.25 | Scale of retrieval noise (logistic) |
| Retrieval threshold | tau | -0.5 | Minimum activation for retrieval |
| Max associative strength | S_max | 1.5 | Ceiling on source-to-chunk association |
| Total attention | W | 1.0 | Budget split among spreading activation sources |
| Latency factor | F | 1.0 | Scales retrieval time (not needed for proxy) |
| Latency exponent | f | 1.0 | Scales retrieval time (not needed for proxy) |

These values are empirically validated across hundreds of ACT-R models. For the proxy implementation, start with the standard values and adjust only if calibration against real session data warrants it.

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
    "traces": [                      # list of (timestamp, access_type) pairs
        (1710600000, "created"),
        (1710686400, "retrieved"),
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
    traces: list[float]              # list of timestamps (epoch seconds)
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
    context_tags TEXT NOT NULL,      -- JSON array
    traces TEXT NOT NULL,            -- JSON array of epoch timestamps
    embedding TEXT                   -- JSON array of floats
);
```

### Core Functions

```python
def base_level_activation(traces: list[float], now: float, d: float = 0.5) -> float:
    """Compute B = ln(sum t_i^(-d)) for a chunk's trace history."""
    total = 0.0
    for t in traces:
        age = max(now - t, 1.0)  # avoid division by zero
        total += age ** (-d)
    if total <= 0:
        return -float('inf')  # effectively forgotten
    return math.log(total)

def spreading_activation(
    chunk_tags: list[str],
    source_tags: list[str],
    s_max: float = 1.5,
) -> float:
    """Compute S = sum W_j * S_ji for context-based boosting."""
    if not source_tags:
        return 0.0
    w_j = 1.0 / len(source_tags)
    # Precompute fan for each source tag (number of chunks associated with it)
    # In practice, fan counts are cached and updated on chunk creation
    total = 0.0
    for tag in source_tags:
        if tag in chunk_tags:
            fan = get_fan_count(tag)  # how many chunks have this tag
            s_ji = s_max - math.log(max(fan, 1))
            total += w_j * s_ji
    return total

def retrieve(
    context_tags: list[str],
    now: float,
    tau: float = -0.5,
    s: float = 0.25,
    top_k: int = 10,
) -> list[MemoryChunk]:
    """Retrieve the top-k chunks above threshold, ordered by activation."""
    results = []
    for chunk in all_chunks():
        b = base_level_activation(chunk.traces, now)
        sp = spreading_activation(chunk.context_tags, context_tags)
        noise = logistic_noise(s)
        a = b + sp + noise
        if a > tau:
            results.append((a, chunk))
    results.sort(key=lambda x: -x[0])
    return [chunk for _, chunk in results[:top_k]]
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

## References

**Anderson, J. R., & Lebiere, C.** (1998). *The Atomic Components of Thought.* Lawrence Erlbaum Associates. — The definitive ACT-R reference. Complete derivation of the activation equations, spreading activation, retrieval dynamics, and parameter values. Chapter 4 covers declarative memory in full.

**Anderson, J. R., & Schooler, L. J.** (1991). Reflections of the environment in memory. *Psychological Science*, 2(6), 396-408. — Empirical basis for the power-law decay parameter (d = 0.5). Demonstrates that human forgetting curves match the statistical structure of real-world information relevance. Read this first for intuition about why the math works.

**ACT-R Tutorial, Unit 4: Activation of Chunks and Base-Level Learning.** Carnegie Mellon University. http://act-r.psy.cmu.edu/wordpress/wp-content/themes/ACT-R/tutorials/unit4.htm — Step-by-step tutorial with worked examples and code. The best starting point for implementation.
