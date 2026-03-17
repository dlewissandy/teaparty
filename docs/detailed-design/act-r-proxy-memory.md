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

## What's Established vs. What's Novel

This design combines components with very different levels of empirical support. An engineer should know which parts are solid ground and which require experimentation.

### Established

**ACT-R base-level activation** — the power-law decay equation with `d = 0.5`. Validated across hundreds of published cognitive models. The most empirically grounded component of this design. Source: Anderson & Lebiere 1998; Anderson & Schooler 1991.

**Interaction-based time units** — Anderson & Schooler's 1991 analysis measured relevance as a function of event intervals, not clock time. Using interaction counts as `t` is faithful to the original empirical basis.

**Embedding retrieval for semantic similarity** — dense vector embeddings with cosine similarity. Widely deployed, well-understood. We already use this in `memory_indexer.py`.

**Activation-weighted embedding retrieval** — combining recency/frequency weighting with semantic similarity. This is the pattern underlying modern AI memory systems (including Claude's persistent memory). Deployed at scale.

**LLM reasoning over retrieved memories to predict human behavior** — Park et al. (2024) built generative agent simulations of 1,052 real people from interview transcripts, achieving 85% accuracy using LLM in-context reasoning over retrieved personal data.

### Design Parameters Requiring Calibration

**Activation/semantic weight balance** (starting at 0.5 / 0.5) — how much to weight recency/frequency vs. semantic similarity. Calibrate against real session data.

**Retrieval threshold** (tau = -0.5) — the ACT-R standard was calibrated for human lab experiments. The right threshold for proxy memory retrieval may differ. Shadow mode (Phase 1) will reveal the right value.

**Chunk granularity** — what constitutes one chunk is a design decision, not an empirical finding. See [act-r-proxy-mapping.md](act-r-proxy-mapping.md) for the current choices.

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

### Structured Output Format

Both passes produce `ACTION<TAB>PROSE` — the same format used by the existing `classify_review.py`. Parsing extracts the first line, splits on tab, lowercases the action. The structured format makes prior/posterior comparison deterministic on the action and semantic on the prose.

### Surprise Extraction

Only runs when the action changed (strong surprise). Confirmed predictions (no surprise) cost 2 LLM calls. Surprises cost 4. Since most gate interactions should be unsurprising (the proxy's prior is usually right), the average cost approaches 2 calls, not 4.

**Extract what changed**: LLM receives both prose traces, returns one sentence describing what the artifact revealed.

**Extract salient features**: LLM receives both prose traces, returns a list of short feature descriptions (e.g., "no rollback strategy", "migration risk").

Both extraction calls are short-context (~200 tokens each) and cheap relative to the full-context passes.

### Cost Per Gate

| Scenario | LLM Calls | When |
|----------|-----------|------|
| No surprise (action unchanged) | 2 | Prior + posterior. Most common case. |
| Strong surprise (action changed) | 4 | Prior + posterior + delta extraction + feature extraction. |

The delta extraction calls are short-context (just the two prose strings, ~200 tokens each). They're cheap relative to the full-context passes.

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

The context window imposes a hard limit on working memory — how many chunks can be loaded into the cache. This mirrors ACT-R's buffer capacity constraint.

```python
# Working memory budget calculation
W = 200_000                          # context window (tokens)
SYSTEM_PROMPT_TOKENS = 2_000         # proxy instructions
GATE_RESERVE_TOKENS = 10_000         # artifact + question + generation
MEMORY_BUDGET = W - SYSTEM_PROMPT_TOKENS - GATE_RESERVE_TOKENS
                                     # = 188,000 tokens for memories

# Average chunk size: ~500 tokens (a gate interaction summary)
MAX_CHUNKS = MEMORY_BUDGET // 500    # ≈ 376 chunks

# In practice, load far fewer — diminishing returns after ~50 chunks.
# The ACT-R activation threshold (tau) naturally limits the set to
# chunks with meaningful activation.
PRACTICAL_LIMIT = 50
```

The activation threshold `tau` is the natural limiter. Only chunks above threshold are loaded. On cold start, few chunks exist and most are loaded. As memory accumulates across sessions, the threshold selects the most active subset. The working memory capacity is self-regulating through the activation equation.

### Why This Is Future Work

The proxy currently invokes Claude via `claude -p` (CLI subprocess). The CLI does not expose cache control parameters. To use explicit KV cache management, the proxy would need to switch to direct Anthropic API calls with `cache_control` message blocks. The proxy is a good candidate for this — it doesn't need tools, worktrees, or team sessions. It just needs to reason over context and produce a prediction. But the migration from CLI to API is a separate effort.

Additionally, persistent KV cache (saving cache state to disk and reloading across sessions) is not currently available in the Anthropic API. The cache is ephemeral within a TTL window. True cross-session working memory would require either API support for persistent caches or a local inference setup.

### Compatibility with the Current Design

The current design (ACT-R activation → text retrieval → embedding ranking → LLM prompt via CLI) and this future design (ACT-R activation → KV cache loading → API calls) are compatible:

- Same long-term storage (SQLite, chunks with traces)
- Same activation equation for selection (`B = ln(Σ t_i^(-d))`)
- Same interaction-based time units
- Same two-pass prediction model
- Same surprise-based chunk creation

The transition changes *how* selected memories reach the LLM (re-reading text vs. loading cached state) without changing *which* memories are selected or *what* gets stored afterward.

---

## References

**Anderson, J. R., & Lebiere, C.** (1998). *The Atomic Components of Thought.* Lawrence Erlbaum Associates. — The definitive ACT-R reference. Chapter 4 covers declarative memory in full.

**Anderson, J. R., & Schooler, L. J.** (1991). Reflections of the environment in memory. *Psychological Science*, 2(6), 396-408. — Empirical basis for the power-law decay parameter. Read this first for intuition about why the math works.

**ACT-R Tutorial, Unit 4: Activation of Chunks and Base-Level Learning.** Carnegie Mellon University. http://act-r.psy.cmu.edu/wordpress/wp-content/themes/ACT-R/tutorials/unit4.htm — Step-by-step tutorial with worked examples and code. The best starting point for implementation.
