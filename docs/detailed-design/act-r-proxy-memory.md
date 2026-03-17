# ACT-R Memory Model for the Human Proxy

This document describes how to replace the proxy agent's current confidence model (EMA + Laplace estimates) with an activation-based memory system derived from the ACT-R cognitive architecture.

For the theory and equations, see [act-r.md](act-r.md).
For the concrete proxy mapping, see [act-r-proxy-mapping.md](act-r-proxy-mapping.md).
For the two-pass prediction model and learned attention, see [act-r-proxy-sensorium.md](act-r-proxy-sensorium.md).

---

## Why Replace the Current Model

The proxy currently tracks confidence as a single scalar per (state, task_type) pair — an exponential moving average of approval rates plus a Laplace smoothed estimate. This works for the narrow question "should I auto-approve at this gate?" but fails in several ways:

**No forgetting toward baseline.** EMA decays toward the running average. If the human dismissed 10 observations during a spec rewrite, EMA drives confidence to zero for that category. When the spec stabilizes, the proxy won't recover without new positive signal. It has "learned" that spec alignment doesn't matter — permanently.

**No context sensitivity.** The proxy at PLAN_ASSERT retrieves the same confidence whether the human is reviewing a plan for a security feature or a documentation update. The current model has no mechanism for context to influence retrieval.

**No distinction between habitual and episodic patterns.** "This human always cares about containment" (reinforced across 20 sessions) and "this human rejected the last plan" (one event) are stored with the same machinery. The model can't distinguish stable preferences from one-off reactions.

**No connection between gate mode and discovery mode.** The proxy operates in two modes — staffing approval gates during sessions and reviewing the codebase between sessions (see [autodiscovery.md](../autodiscovery.md)). Both modes need the same memory of the human, but the current scalar model can't represent the richer interactions that discovery mode produces.

ACT-R's declarative memory model solves all four problems with a single mechanism.

---

## The Approach

Replace the scalar confidence model with **activation-weighted embedding retrieval**:

- **Base-level activation** from ACT-R handles forgetting. Each memory has traces that decay as a power function of interactions elapsed. Frequently reinforced memories stay active; one-off events fade. The equation is `B = ln(Σ t_i^(-d))` with `d = 0.5`. See [act-r.md](act-r.md) for the full derivation.

- **Vector embeddings** handle context sensitivity. Each memory chunk's content is embedded; retrieval uses cosine similarity to find semantically relevant memories. This replaces ACT-R's symbolic spreading activation with a mechanism that is both simpler and more powerful.

- **Structural filtering** handles the relational structure. The chunk is a tuple (state, outcome, task_type, ...) where field ordering matters. SQL queries on structural fields narrow the candidate set; semantic ranking orders within the filtered set. See [act-r-proxy-mapping.md](act-r-proxy-mapping.md) for the chunk schema.

- **Interaction-based time** replaces wall-clock seconds. The decay equation uses interaction counts (gate decisions, dialog turns, discovery responses), not seconds. Between sessions, the counter doesn't advance — memories don't decay while the system is idle. This is faithful to Anderson & Schooler's (1991) event-based empirical analysis.

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

## Future Direction: KV Cache as Working Memory

The current design retrieves memory chunks as text, inserts them into the LLM prompt, and reprocesses them from tokens on every call. This works but misses a deeper alignment between ACT-R's cognitive architecture and the LLM's native machinery. This section specifies what a KV-cache-based architecture would look like concretely.

### Roles of the Three Systems

**ACT-R** provides the memory selection policy. It answers: which memories are active enough to load? It does not process the memories — it ranks them.

**The KV cache** is working memory. It holds the LLM's processed understanding of the loaded memories. Once a memory is in the cache, the LLM doesn't re-read it — the processed state is already there. The cache persists within a session (across gates) and is populated at session start.

**The LLM's transformer attention** is spreading activation. When the LLM processes chunk A, its attention mechanism creates internal representations that prime processing of subsequent chunks. Associations emerge from the LLM's own reasoning over the cached content, not from precomputed scores.

**Bayesian surprise** is the perceptual filter. The two-pass prediction (prior without artifact, posterior with) identifies what in the artifact changed the proxy's mind. The surprise — the processed percept — is what gets stored as a new chunk. Raw artifacts and raw interactions do not enter long-term memory.

### Session Lifecycle

The session lifecycle has three phases: loading working memory at session start, a per-gate prediction loop, and storage of processed percepts. Working memory is populated once and reused across all gates via the KV cache. Each gate runs the two-pass prediction (prior without artifact, posterior with), computes surprise from the structured action delta, and stores only the surprise — not the raw interaction — as a new memory chunk. Loaded memories are reinforced on each gate interaction, keeping active memories above the retrieval threshold for future sessions.

```
SESSION START
    read interaction counter N from storage
    for each chunk in long-term storage:
        compute B = ln(Σ (N − trace_i)^(−0.5))
    sort chunks by B descending
    load top chunks into prompt prefix while B > τ and budget remains
    process prefix into KV cache

    for each gate in session:
        increment N

        PASS 1 — PRIOR
            generate from cached prefix + gate context, no artifact
            output: ACTION <tab> PROSE, temperature 0
            parse → prior.action, prior.prose

        PASS 2 — POSTERIOR
            generate from cached prefix + gate context + artifact + prior
            output: ACTION <tab> PROSE, temperature 0
            parse → posterior.action, posterior.prose

        SURPRISE
            if prior.action ≠ posterior.action:
                extract what changed → one-sentence description (LLM call)
                extract salient features → list of percept phrases (LLM call)
            else:
                no surprise, no additional calls

        DECISION
            execute gate using posterior
            receive human response if escalated

        STORE
            create chunk from surprise + human response + proxy error
            embed situation, stimulus, response, salience independently
            store with first trace = N

        REINFORCE
            add trace N to each loaded chunk

SESSION END
    discard cache
```

### Data Structures

```
StructuredPrediction
    action    : one of {approve, correct, escalate, withdraw}
    prose     : free-text reasoning

SurpriseDelta
    magnitude       : 1.0 (action changed) or 0.0 (confirmed)
    prior action    : action before artifact
    prior prose     : reasoning before artifact
    posterior action : action after artifact
    posterior prose  : reasoning after artifact
    description     : what changed (only on strong surprise)
    salient percepts : list of artifact features that caused the shift

MemoryChunk
    id, type, state, task_type, outcome              — structural (SQL-filtered)
    prior action, prior prose                         — Pass 1 result
    posterior action, posterior prose                  — Pass 2 result
    surprise description, salient percepts            — processed percept
    human response, proxy error                       — ground truth
    traces                                            — list of interaction numbers
    embedding_situation, _stimulus, _response, _salience — independent vectors
```

Both passes produce `ACTION<TAB>PROSE` — the same structured format used by the existing `classify_review.py`. Surprise extraction (2 additional short-context LLM calls) only runs when the action changed. Most gates produce no surprise: 2 calls. Surprises cost 4.

### Cache Economics

The two-pass prediction model doubles the proxy's LLM calls per gate. Without cost mitigation, this is prohibitive. Prompt caching — reusing the processed KV state for a shared prompt prefix across calls — is the mitigation.

#### How Anthropic Prompt Caching Works

The Anthropic Messages API supports prompt caching via `cache_control` blocks. When a message prefix is marked cacheable:

- **First call**: full price to process the prefix (input tokens at standard rate)
- **Subsequent calls with the same prefix** (within 5-minute TTL): cached prefix tokens at ~10% of standard rate (e.g., 0.30/MTok instead of 3.00/MTok for Sonnet)
- **Cache matching is account-level**, not session-level — two separate API calls with the same prefix hit the cache, even from different processes

This last point is critical. The proxy invokes Claude as a subprocess (`subprocess.run(['claude', '-p', ...])`) — one process per pass. There is no shared state between processes. But prompt caching operates at the API backend, not the client. If the system prompt + memories are identical across calls, the second call gets the cache hit regardless of process isolation.

#### Prompt Structure for Caching

Every proxy call shares a common prefix:

```
┌─────────────────────────────────────────┐
│ System prompt (proxy instructions)       │ ← cacheable
│ Retrieved memories (top-k chunks)        │ ← cacheable
├─────────────────────────────────────────┤
│ Gate context (state, task, history)       │ ← varies per gate
│ Artifact (Pass 2 only)                   │ ← varies per gate
│ Instruction (prior vs posterior prompt)   │ ← varies per pass
└─────────────────────────────────────────┘
```

The prefix (system prompt + memories) is stable across all calls in a session. The suffix (gate context, artifact, instruction) varies per call.

#### Cost Model

Let:
- P = system prompt tokens (~2,000)
- M = memory tokens (~5,000 for 10 chunks)
- C = gate content tokens per pass (~2,000)
- D = delta extraction tokens (~500, only on surprise)
- G = number of gates per session
- r = cache discount rate (0.1 = 90% discount)

**Current design (no two-pass, no caching):**
```
Cost = G × (P + M + C)
     = G × 9,000 tokens at full price
```

**Two-pass without caching:**
```
Cost = G × 2 × (P + M + C)
     = G × 18,000 tokens at full price    ← 2x the current cost
```

**Two-pass with prompt caching:**
```
Cost = (P + M)                             # first call: full price
     + (2G - 1) × r × (P + M)             # remaining calls: cached prefix
     + 2G × C                              # per-pass: gate content at full price
     + surprise_rate × G × 2 × D           # delta extraction (surprise only)

For G=5, surprise_rate=0.2 (20% of gates produce surprise):
     = 7,000                               # first prefix
     + 9 × 0.1 × 7,000                    # cached prefixes = 6,300
     + 10 × 2,000                          # gate content = 20,000
     + 0.2 × 5 × 2 × 500                  # delta extraction = 1,000
     = 34,300 token-equivalents

vs. current (no two-pass): 5 × 9,000 = 45,000
vs. two-pass without caching: 10 × 9,000 = 90,000
```

**Summary for G=5 gates:**

| Configuration | Token-equivalents | vs. Current |
|---------------|-------------------|-------------|
| Current (1 pass, no cache) | 45,000 | baseline |
| Two-pass, no cache | 90,000 | +100% |
| Two-pass, with cache | 34,300 | **-24%** |

The two-pass model with prompt caching is **cheaper than the current single-pass model** because the cache discount on repeated prefix processing more than compensates for the extra pass. The savings increase with more gates per session:

| Gates | Current | Two-pass + cache | Savings |
|-------|---------|------------------|---------|
| 3 | 27,000 | 23,100 | 14% |
| 5 | 45,000 | 34,300 | 24% |
| 10 | 90,000 | 62,600 | 30% |
| 20 | 180,000 | 119,200 | 34% |

#### Verification Needed

This analysis assumes the `claude -p` CLI produces API calls whose prefixes match for cache purposes. This needs empirical verification:

1. Do two sequential `claude -p` subprocess calls with the same system prompt hit the Anthropic prompt cache?
2. Does the CLI add any per-call variation to the prompt (timestamps, session IDs) that would break prefix matching?
3. What is the actual cache TTL, and does it survive the time between gates in a real session?

If the CLI breaks caching, the proxy should be migrated to direct API calls. The proxy is a good candidate — it doesn't need tools, worktrees, or team sessions.

### Working Memory Capacity

The context window limits how many chunks can be loaded. At ~500 tokens per chunk and a 200K context window, the theoretical max is ~376 chunks. In practice, the activation threshold τ limits loading to the 20-50 most active chunks — self-regulating as memory accumulates.

### Why This Is Future Work

The proxy invokes Claude via `claude -p` (subprocess). The CLI doesn't expose cache control. Explicit KV management requires direct API calls. The proxy is a good candidate for migration — it doesn't need tools, worktrees, or team sessions. But that migration is a separate effort. The current text-retrieval design and this KV cache design share the same memory theory; only the delivery mechanism differs.

---

## References

**Anderson, J. R., & Lebiere, C.** (1998). *The Atomic Components of Thought.* Lawrence Erlbaum Associates. — The definitive ACT-R reference. Chapter 4 covers declarative memory in full.

**Anderson, J. R., & Schooler, L. J.** (1991). Reflections of the environment in memory. *Psychological Science*, 2(6), 396-408. — Empirical basis for the power-law decay parameter. Read this first for intuition about why the math works.

**ACT-R Tutorial, Unit 4: Activation of Chunks and Base-Level Learning.** Carnegie Mellon University. http://act-r.psy.cmu.edu/wordpress/wp-content/themes/ACT-R/tutorials/unit4.htm — Step-by-step tutorial with worked examples and code. The best starting point for implementation.
