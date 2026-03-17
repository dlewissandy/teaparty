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

## References

**Anderson, J. R., & Lebiere, C.** (1998). *The Atomic Components of Thought.* Lawrence Erlbaum Associates. — The definitive ACT-R reference. Chapter 4 covers declarative memory in full.

**Anderson, J. R., & Schooler, L. J.** (1991). Reflections of the environment in memory. *Psychological Science*, 2(6), 396-408. — Empirical basis for the power-law decay parameter. Read this first for intuition about why the math works.

**ACT-R Tutorial, Unit 4: Activation of Chunks and Base-Level Learning.** Carnegie Mellon University. http://act-r.psy.cmu.edu/wordpress/wp-content/themes/ACT-R/tutorials/unit4.htm — Step-by-step tutorial with worked examples and code. The best starting point for implementation.
