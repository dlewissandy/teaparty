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

The current design retrieves memory chunks as text, inserts them into the LLM prompt, and lets the LLM reprocess them from tokens on every call. This works but it misses a deeper alignment between ACT-R's cognitive architecture and the LLM's.

### The Insight

The LLM already has a cognitive architecture: attention (spreading activation), the context window (working memory), pattern recognition, inference. ACT-R gives us the principled memory dynamics — what to load, when to forget. The LLM gives us the processing that ACT-R had to build from scratch with production rules. We are not reimplementing ACT-R. We are using ACT-R's memory theory to govern the interface between long-term storage and the LLM's native cognition.

When the LLM processes a memory chunk, the KV cache entries it produces are far richer than any embedding vector. They capture the model's full understanding of that chunk in context — all the associations and implications inferred during processing. An embedding is a lossy compression into a single vector. The KV cache is the model's actual internal state.

### The Architecture

```
Long-term storage (disk, SQLite, chunks with activation traces)
        │
        │  ACT-R activation: which chunks are most active?
        ▼
KV cache (working memory, loaded at session start)
        │
        │  Gate arrives → Pass 1 (prior from cache)
        │  Artifact loads → Pass 2 (posterior from cache + artifact)
        │  Delta = Bayesian surprise
        ▼
New chunk written to long-term storage
(content = the surprise, not the raw interaction)
```

**ACT-R activation selects what enters working memory.** At session start, the retrieval runs: which memories are most active? Those chunks get loaded into the prompt, creating KV cache entries. Low-activation chunks never make it in. This is the attention bottleneck — the cache has a size limit, just like working memory.

**The KV cache IS spreading activation.** When the LLM processes memory chunk A, the attention mechanism creates internal representations that influence how it processes everything that follows. "Thinking about proxy learning" primes the model for "backtrack patterns" — not because we computed an association score, but because the transformer's own attention made the connection. We don't need to build spreading activation. We need to get the right chunks into the cache and the LLM's attention does the rest.

**Bayesian surprise determines what gets stored.** The two-pass prediction runs. The prior comes from the cached context. The artifact arrives, extending the cache. The posterior is computed. The delta — the surprise — is the processed percept that gets written to long-term storage. Not the raw artifact. Not the full interaction. The part that changed the proxy's mind. This is analogous to how ACT-R perceptual modules work: they don't store the raw sensory input, they store the processed percept that reached declarative memory.

**The cache persists within a session.** The retrieved memories, once loaded, stay in the cache across all gates in the session. The proxy doesn't re-read its memories at every gate — it already "has them in mind." Each gate only processes the new content (artifact, question). This is where prompt caching via the Anthropic API would provide concrete savings: the memory prefix is processed once, and subsequent gates reuse the cached KV state.

### Why This Is Future Work

The proxy currently invokes Claude via `claude -p` (CLI subprocess). The CLI does not expose cache control parameters. To use explicit KV cache management, the proxy would need to switch to direct Anthropic API calls. The proxy is a good candidate for this — it doesn't need tools, worktrees, or team sessions. It just needs to reason over context and produce a prediction. But the migration from CLI to API is a separate effort.

Additionally, persistent KV cache (saving cache state to disk and reloading across sessions) is not currently available in the Anthropic API. The cache is ephemeral within a TTL window. True cross-session working memory — where the proxy loads its KV state from the previous session rather than reprocessing from text — would require either API support for persistent caches or a local inference setup.

### What This Means for the Current Design

The current design (ACT-R activation → text retrieval → embedding-based ranking → LLM prompt) is the implementable version. It works today with the CLI. The KV cache architecture is the version that fully aligns ACT-R's memory theory with the LLM's native cognition — but it requires API-level control that we don't currently have.

The designs are compatible. The transition from text retrieval to KV cache retrieval doesn't change what gets stored (chunks with activation traces) or how forgetting works (power-law decay on interaction counts). It changes how stored memories reach the LLM's processing — from re-reading text to loading pre-computed state. The memory theory is the same. The delivery mechanism improves.

---

## References

**Anderson, J. R., & Lebiere, C.** (1998). *The Atomic Components of Thought.* Lawrence Erlbaum Associates. — The definitive ACT-R reference. Chapter 4 covers declarative memory in full.

**Anderson, J. R., & Schooler, L. J.** (1991). Reflections of the environment in memory. *Psychological Science*, 2(6), 396-408. — Empirical basis for the power-law decay parameter. Read this first for intuition about why the math works.

**ACT-R Tutorial, Unit 4: Activation of Chunks and Base-Level Learning.** Carnegie Mellon University. http://act-r.psy.cmu.edu/wordpress/wp-content/themes/ACT-R/tutorials/unit4.htm — Step-by-step tutorial with worked examples and code. The best starting point for implementation.
