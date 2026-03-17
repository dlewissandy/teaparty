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

### Session Lifecycle — Pseudocode

```python
def run_session(session):
    """Full session lifecycle with KV cache as working memory."""

    # ── Session start: load working memory ──────────────────────
    counter = get_interaction_counter()
    all_chunks = get_all_chunks()

    # ACT-R activation ranks every chunk in long-term storage.
    # B = ln(Σ t_i^(-d)) for each chunk, where t_i is interactions
    # since the i-th access of that chunk.
    ranked = []
    for chunk in all_chunks:
        b = base_level_activation(chunk.traces, counter, d=0.5)
        ranked.append((b, chunk))
    ranked.sort(key=lambda x: -x[0])

    # Select top-k chunks that fit the context window budget.
    # W = context window size (tokens).
    # Reserve space for system prompt, gate content, and generation.
    budget = W - SYSTEM_PROMPT_TOKENS - GATE_RESERVE_TOKENS
    loaded_chunks = []
    tokens_used = 0
    for activation, chunk in ranked:
        if activation < tau:
            break  # below retrieval threshold, stop loading
        chunk_tokens = token_count(chunk.content)
        if tokens_used + chunk_tokens > budget:
            break  # working memory is full
        loaded_chunks.append(chunk)
        tokens_used += chunk_tokens

    # Build the cached prefix: system prompt + loaded memories.
    # This prefix is processed ONCE into KV cache entries.
    # All subsequent gates reuse this cache.
    prefix = build_prefix(
        system_prompt=PROXY_SYSTEM_PROMPT,
        memories=loaded_chunks,
    )
    cache = create_kv_cache(prefix)  # one LLM forward pass

    # ── Per-gate loop ───────────────────────────────────────────
    for gate in session.gates:
        counter = increment_interaction_counter()

        # Pass 1: Prior (from cache, no artifact)
        # The LLM reasons over its cached memories + the gate context.
        # It has NOT seen the artifact.
        prior = llm_generate(
            cache=cache,                    # reused, not reprocessed
            suffix=format_gate_context(
                state=gate.state,
                task_type=gate.task_type,
                session_history=gate.history,
                instruction="Predict what the human would say. "
                            "You have not seen the artifact.",
            ),
            temperature=0,                  # deterministic prior
        )
        # prior = {action: "approve", confidence: 0.8, reasoning: "..."}

        # Pass 2: Posterior (cache + artifact)
        # Same cache, extended with the artifact content.
        posterior = llm_generate(
            cache=cache,                    # same cached prefix
            suffix=format_gate_context(
                state=gate.state,
                task_type=gate.task_type,
                session_history=gate.history,
                artifact=gate.artifact_content,
                prior_prediction=prior,
                instruction="You previously predicted: {prior}. "
                            "Now read the artifact and revise.",
            ),
            temperature=0,                  # deterministic posterior
        )
        # posterior = {action: "correct", confidence: 0.85, reasoning: "..."}

        # ── Bayesian surprise ───────────────────────────────────
        # The surprise is the delta between prior and posterior.
        # This is the processed percept — what the artifact revealed
        # that the proxy's model didn't predict.
        if prior.action != posterior.action:
            # Strong surprise: the artifact changed the decision.
            surprise = SurpriseDelta(
                magnitude=abs(posterior.confidence - prior.confidence),
                direction="positive" if posterior.confidence > prior.confidence else "negative",
                prior_action=prior.action,
                posterior_action=posterior.action,
                description=extract_what_changed(prior.reasoning, posterior.reasoning),
                salient_percepts=extract_salient_features(prior.reasoning, posterior.reasoning),
            )
        else:
            # Weak or no surprise: artifact confirmed expectations.
            surprise = SurpriseDelta(
                magnitude=abs(posterior.confidence - prior.confidence),
                direction="confirmed",
                prior_action=prior.action,
                posterior_action=posterior.action,
                description="",
                salient_percepts=[],
            )

        # ── Use the posterior for the actual decision ───────────
        decision = posterior  # this is what the proxy acts on

        # ... gate executes (auto-approve, escalate, etc.) ...
        # ... human responds (if escalated) ...

        human_response = gate.execute(decision)

        # ── Store the processed percept ─────────────────────────
        # What gets stored is NOT the raw artifact or the full
        # interaction. It is the surprise — what the proxy learned.
        new_chunk = MemoryChunk(
            id=generate_id(),
            type="gate_outcome",
            state=gate.state,
            task_type=gate.task_type,
            outcome=human_response.action,
            prior_prediction=prior.action,
            prior_confidence=prior.confidence,
            posterior_prediction=posterior.action,
            posterior_confidence=posterior.confidence,
            prediction_delta=surprise.description,
            salient_percepts=surprise.salient_percepts,
            human_response=human_response.text,
            delta=compute_proxy_error(posterior, human_response),
            content=build_chunk_content(
                surprise=surprise,
                human_response=human_response,
                gate_context=gate,
            ),
            traces=[counter],
            # Embeddings per percept dimension (see act-r-proxy-mapping.md)
            embedding_situation=embed(f"{gate.state} {gate.task_type}"),
            embedding_stimulus=embed(surprise.description) if surprise.description else None,
            embedding_response=embed(human_response.text) if human_response.text else None,
            embedding_salience=embed(
                " ".join(surprise.salient_percepts)
            ) if surprise.salient_percepts else None,
            # NOTE: no artifact embedding. The artifact is referenced,
            # not embedded. If this chunk is retrieved in a future session,
            # the LLM reads the original artifact via file tools.
        )
        store_chunk(new_chunk)

        # Mark loaded chunks as retrieved (adds a trace to each,
        # reinforcing memories that were in working memory during
        # this interaction).
        for chunk in loaded_chunks:
            add_trace(chunk.id, counter)

    # ── Session end ─────────────────────────────────────────────
    # Cache is discarded. Next session starts fresh with a new
    # ACT-R retrieval and a new cache. The chunks in long-term
    # storage have updated traces from this session's interactions.
    discard_cache(cache)
```

### The Surprise Computation — Detail

The surprise between prior and posterior is not a simple diff. It requires extracting *what specifically changed* in the proxy's reasoning.

```python
@dataclass
class SurpriseDelta:
    magnitude: float        # |posterior.confidence - prior.confidence|
    direction: str          # "positive", "negative", or "confirmed"
    prior_action: str       # what the proxy predicted before the artifact
    posterior_action: str   # what the proxy predicted after the artifact
    description: str        # natural language: what changed and why
    salient_percepts: list  # specific artifact features that caused the shift

def extract_what_changed(prior_reasoning: str, posterior_reasoning: str) -> str:
    """Extract the specific change between prior and posterior reasoning.

    This is an LLM call — we ask the model to compare its own two
    reasoning traces and identify what the artifact revealed.

    Returns a concise description: 'Missing rollback section in
    database migration plan changed prediction from approve to correct.'
    """
    return llm_generate(
        prompt=f"""Compare these two predictions and identify what changed:

PRIOR (before seeing artifact): {prior_reasoning}
POSTERIOR (after seeing artifact): {posterior_reasoning}

In one sentence, state what the artifact revealed that changed
the prediction. If nothing changed, say 'confirmed'.""",
        temperature=0,
    )

def extract_salient_features(prior_reasoning: str, posterior_reasoning: str) -> list[str]:
    """Extract the specific artifact features that caused the surprise.

    Returns a list of short feature descriptions:
    ['no rollback strategy', 'database migration risk']
    """
    return llm_generate(
        prompt=f"""What specific features of the artifact caused this
prediction change?

PRIOR: {prior_reasoning}
POSTERIOR: {posterior_reasoning}

List each feature as a short phrase, one per line.""",
        temperature=0,
    ).strip().split('\n')
```

Note: `extract_what_changed` and `extract_salient_features` are additional LLM calls. This means each gate interaction costs 4 LLM calls total: Pass 1 (prior), Pass 2 (posterior), delta extraction, feature extraction. The last two are short-context calls (just the two reasoning traces) and are cheap relative to the full-context passes.

### Cache Economics

The cost model for one session with G gates:

**Without KV caching (current design):**
```
Cost = G × process(system_prompt + memories + gate_content)
     = G × process(P + M + C)
```

Every gate reprocesses the full prompt. For a session with 5 gates and 10 retrieved memories, that's 5 full processing passes over the same memory content.

**With KV caching:**
```
Cost = process(P + M)                           # once at session start
     + G × process(C)                           # per gate: only new content
     + G × 2 × process(delta_extraction)        # per gate: surprise analysis
```

The memory prefix (P + M) is processed once. Each gate processes only the gate-specific content (C) against the cached prefix. The delta extraction calls are short-context.

For a session with 5 gates, 10 memories totaling 5000 tokens, and gate content averaging 2000 tokens:

```
Without caching: 5 × (5000 + 2000) = 35,000 tokens processed
With caching:    5000 + 5 × 2000 + 5 × 2 × 500 = 20,000 tokens processed
Savings:         ~43%
```

The savings increase with more gates per session and more loaded memories. A session with 10 gates saves ~55%.

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
