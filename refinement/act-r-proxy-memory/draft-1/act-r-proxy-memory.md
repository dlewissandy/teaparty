# ACT-R Memory Model for the Human Proxy

This document describes the proxy agent's memory architecture: an activation-based memory system derived from ACT-R for modeling how the human thinks, combined with EMA as a system health monitor.

For the theory and equations, see [act-r.md](act-r.md).
For the concrete proxy mapping, see [act-r-proxy-mapping.md](act-r-proxy-mapping.md).
For the two-pass prediction model and learned attention, see [act-r-proxy-sensorium.md](act-r-proxy-sensorium.md).

---

## The Proxy's Job

The proxy's job is not to approve or reject. It is to **proxy the behavior of the human** — ask the questions the human would ask, probe the reasoning the human would probe, raise the concerns the human would raise, and reach a decision only after the kind of dialog the human would have conducted. Approval or rejection is the final act of a rich conversation, not a binary gate.

This means the proxy needs to model how the human *thinks*, not just what they *decide*. What do they attend to? What questions do they ask? What concerns recur? How do they reason about tradeoffs? None of this is a scalar.

## Two Systems, Two Roles

**ACT-R activation memory** models the human's thinking. It stores memories of past interactions — the questions the human asked, the concerns they raised, the reasoning they applied, the corrections they made. Retrieval surfaces the memories most relevant to the current context, giving the proxy the raw material to simulate the human's conversational behavior. This is the core of the proxy's cognitive capability.

**EMA** monitors system health. It tracks approval rates per (state, task_type) over time — not to decide whether to approve, but to detect trends. "The approval rate at PLAN_ASSERT dropped from 0.8 to 0.4 over 10 sessions" doesn't mean "escalate more." It means "the planning agent is producing worse plans and the proxy is catching it." EMA is a diagnostic signal about how well the upstream agents are performing, not a decision mechanism for the proxy.

The current system conflates these roles — EMA drives the approve/escalate decision. The new design separates them: ACT-R memory drives the proxy's behavior (what questions to ask, what to attend to, what the human would say). EMA observes the outcomes and reports on system health.

## What Changes in the Current Model

The current model uses EMA as a decision gate: confidence above threshold -> auto-approve, below -> escalate. This fails because:

**It skips the dialog.** A high EMA means the proxy auto-approves without asking any questions. The human would have asked questions — probed the artifact, challenged assumptions, verified completeness — even when they ultimately approve. The dialog is how quality is maintained. Skipping it because the trend is positive is rubber-stamping.

**It has no context sensitivity.** The same EMA applies whether the human is reviewing a security plan or a documentation update. The proxy can't ask different questions for different artifacts.

**It can't distinguish habitual from episodic patterns.** "This human always asks about rollback plans" (stable) and "this human rejected the last plan" (one-off) are invisible to a scalar.

**It has no connection to discovery mode.** The proxy's between-session reviews (see [autodiscovery.md](../autodiscovery.md)) produce richer interactions than a scalar can represent.

ACT-R activation memory solves these problems. EMA stays, reframed as monitoring.

Note: the new design does permit autonomous proxy action (without escalation to the human) when the proxy has demonstrably inspected the artifact via two-pass prediction and its prior-posterior agreement reflects genuine understanding — not pattern-matching on a scalar. See [act-r-proxy-sensorium.md](act-r-proxy-sensorium.md) for how this differs from EMA-based auto-approval.

---

## The Approach

Replace the scalar confidence model with **activation-weighted embedding retrieval**:

- **Base-level activation** from ACT-R handles forgetting. Each memory has traces that decay as a power function of interactions elapsed. Frequently reinforced memories stay active; one-off events fade. The equation is `B = ln(Sigma t_i^(-d))` with `d = 0.5`. See [act-r.md](act-r.md) for the full derivation.

- **Vector embeddings** handle context sensitivity. Each memory chunk's content is embedded; retrieval uses cosine similarity to find semantically relevant memories. This replaces ACT-R's symbolic spreading activation with a mechanism that serves the same role (context-sensitive retrieval) via a different mechanism (semantic overlap in embedding space rather than structural graph associations).

- **Structural filtering** handles the relational structure. The chunk is a tuple (state, outcome, task_type, ...) where field ordering matters. SQL queries on structural fields narrow the candidate set; semantic ranking orders within the filtered set. See [act-r-proxy-mapping.md](act-r-proxy-mapping.md) for the chunk schema.

- **Interaction-based time** replaces wall-clock seconds. The decay equation uses interaction counts (gate decisions, dialog turns, discovery responses), not seconds. Between sessions, the counter doesn't advance — memories don't decay while the system is idle. The choice of event-based time is well-motivated: Anderson & Schooler's (1991) empirical analysis was event-based, and wall-clock decay during idle periods would be clearly wrong for an agent system. The specific decay exponent (d = 0.5) is a principled starting point from ACT-R's empirical tradition, to be calibrated during shadow mode.

---

## What Changes, What Stays

**Changes:**
- EMA role: from decision gate (approve/escalate) to system health monitor (are upstream agents improving?)
- Memory: from scalar per state-task pair to chunk-based activation memory (`proxy_memory.db`)
- Decision process: from threshold check to simulated dialog (proxy asks the questions the human would ask, then decides)
- `consult_proxy()`: from confidence lookup to retrieval + LLM reasoning over past interactions

**Stays:**
- `.proxy-confidence.json` — still tracks EMA per state-task pair, now as a monitoring signal
- The proxy agent prompt structure (receives context, generates prediction)
- The proxy agent's tools (file read, dialog)
- The delta-based learning signal (prediction vs. reality)
- The intake dialog flow
- The discovery mode concept and discussion lifecycle

---

## Migration Path

The transition can be incremental:

1. **Phase 1: Shadow mode.** Run ACT-R retrieval alongside the existing model. The proxy generates dialog from retrieved memories but the existing EMA gate still controls the actual decision. Log the proxy's dialog and compare against what the human actually said.

   **Evaluation metrics for shadow mode:**
   - Action match rate: did the proxy's posterior action match the human's actual decision?
   - Prior calibration: how often did the prior match the posterior? (measures how well the proxy predicts before seeing the artifact)
   - Surprise calibration: when surprise was detected, did the human's response confirm that the salient percepts were relevant?
   - Retrieval relevance: human spot-checks of retrieved memory sets for qualitative assessment

   **Ablations to run during shadow mode:**
   - Multi-dimensional embeddings (5 vectors) vs. single blended embedding
   - ACT-R decay vs. simple recency (most-recent-N)
   - Two-pass prediction vs. single-pass (posterior only)
   - Normalized combined score vs. activation-only and similarity-only retrieval

2. **Phase 2: Dialog mode.** The proxy's retrieved memories drive the full dialog — questions, follow-ups, reasoning — before reaching a decision. EMA continues to track outcomes as a health monitor.

3. **Phase 3: Integrated.** ACT-R memory, two-pass prediction, and EMA monitoring are unified. The proxy conducts the dialog the human would have conducted. EMA surfaces trends in system performance.

Phase 1 can start immediately — it requires only the chunk storage and retrieval functions.

---

## Future Direction: KV Cache as Working Memory

The current design retrieves memory chunks as text, inserts them into the LLM prompt, and reprocesses them from tokens on every call. This works but misses a deeper alignment between ACT-R's cognitive architecture and the LLM's native machinery. This section specifies what a KV-cache-based architecture would look like concretely. The core design (text retrieval without caching) stands on its own; this section describes what becomes possible when the proxy is migrated to direct API calls.

### Roles of the Three Systems

**ACT-R** provides the memory selection policy. It answers: which memories are active enough to load? It does not process the memories — it ranks them.

**The KV cache** is working memory. It holds the LLM's processed understanding of the loaded memories. Once a memory is in the cache, the LLM doesn't re-read it — the processed state is already there. The cache persists within a session (across gates) and is populated at session start.

**The LLM's transformer attention** provides context sensitivity. When the LLM processes chunk A, its attention mechanism creates internal representations that prime processing of subsequent chunks. Associations emerge from the LLM's own reasoning over the cached content, not from precomputed scores.

**Bayesian surprise** is the perceptual filter. The two-pass prediction (prior without artifact, posterior with) identifies what in the artifact changed the proxy's mind. The surprise — the processed percept — is what gets stored as a new chunk. Raw artifacts and raw interactions do not enter long-term memory.

### Session Lifecycle

The session lifecycle has three phases: loading working memory at session start, a per-gate prediction loop, and storage of processed percepts. Working memory is populated once and reused across all gates via the KV cache. Each gate runs the two-pass prediction (prior without artifact, posterior with), computes surprise from the structured action delta, and stores only the surprise — not the raw interaction — as a new memory chunk. Loaded memories are reinforced on each gate interaction, keeping active memories above the retrieval threshold for future sessions.

### Concurrency

Dispatches run in parallel. Multiple gates may arrive concurrently from different subteams. The proxy does not split into parallel instances — it is one brain with one memory and one interaction counter.

Gates enter a **FIFO queue** and the proxy processes them one at a time. This is how a human works: concurrent tasks compete for attention, but attention is serial. The queue ordering means that what the proxy learns from dispatch A's gate is available when it processes dispatch B's gate — cross-task learning happens naturally through the sequential processing of concurrently-produced work. Whether cross-task priming is beneficial or contaminating depends on the tasks: cross-cutting patterns ("this human always asks about test coverage") generalize usefully, while domain-specific patterns do not. The structural filtering in retrieval mitigates contamination — when processing a documentation gate, security-specific chunks are not surfaced unless the semantic match is strong.

At WORK_ASSERT (the rollup), the proxy doesn't need a special aggregation step. It has already processed each dispatch gate individually, storing surprises and building understanding throughout the session. WORK_ASSERT is just another gate where the proxy reasons over its accumulated memories — which now include the fresh chunks from all the dispatch gates it processed during this session.

```
SESSION START
    read interaction counter N from storage
    for each chunk in long-term storage:
        compute B = ln(Sigma (N - trace_i)^(-0.5))
    sort chunks by B descending
    load top chunks into prompt prefix while B > tau and budget remains
    process prefix into KV cache
    initialize gate queue (FIFO)

    as gates arrive from dispatches, enqueue them
    for each gate dequeued:
        increment N

        PASS 1 -- PRIOR
            generate from cached prefix + gate context, no artifact
            output: ACTION <tab> PROSE, temperature 0
            parse -> prior.action, prior.prose

        PASS 2 -- POSTERIOR
            generate from cached prefix + gate context + artifact + prior
            output: ACTION <tab> PROSE, temperature 0
            parse -> posterior.action, posterior.prose

        SURPRISE
            if prior.action != posterior.action:
                strong surprise: extract description + salient percepts (2 LLM calls)
            else if |posterior.confidence - prior.confidence| > 0.3:
                moderate surprise: extract salient percepts (1 LLM call)
            else:
                no surprise, no additional calls

        DECISION
            execute gate using posterior
            receive human response if escalated

        STORE
            create chunk from prediction results + human response + proxy error
            populate salience fields only if surprise was detected
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
    magnitude       : 1.0 (action changed), 0.5 (confidence shifted), or 0.0 (confirmed)
    prior action    : action before artifact
    prior prose     : reasoning before artifact
    posterior action : action after artifact
    posterior prose  : reasoning after artifact
    description     : what changed (only on strong surprise)
    salient percepts : list of artifact features that caused the shift

MemoryChunk
    id, type, state, task_type, outcome              -- structural (SQL-filtered)
    prior action, prior prose                         -- Pass 1 result
    posterior action, posterior prose                  -- Pass 2 result
    surprise description, salient percepts            -- processed percept (empty if no surprise)
    human response, proxy error                       -- ground truth
    traces                                            -- list of interaction numbers
    embedding_situation, _artifact, _stimulus, _response, _salience -- independent vectors
```

Both passes produce `ACTION<TAB>PROSE` — the same structured format used by the existing `classify_review.py`. Surprise extraction only runs when the action changed (2 additional short-context LLM calls) or confidence shifted significantly (1 call). Most gates produce no surprise: 2 calls. Strong surprises cost 4; moderate surprises cost 3.

### Cache Economics

The two-pass prediction model doubles the proxy's LLM calls per gate. Without cost mitigation, this is prohibitive. Prompt caching — reusing the processed KV state for a shared prompt prefix across calls — is the mitigation.

#### How Anthropic Prompt Caching Works

The Anthropic Messages API supports prompt caching via `cache_control` blocks. When a message prefix is marked cacheable:

- **First call**: full price to process the prefix (input tokens at standard rate), plus a 1.25x cache-write premium
- **Subsequent calls with the same prefix** (within 5-minute TTL): cached prefix tokens at ~10% of standard rate (e.g., 0.30/MTok instead of 3.00/MTok for Sonnet)
- **Cache matching is account-level**, not session-level — two separate API calls with the same prefix hit the cache, even from different processes

This last point is critical. The proxy invokes Claude as a subprocess (`subprocess.run(['claude', '-p', ...])`) — one process per pass. There is no shared state between processes. But prompt caching operates at the API backend, not the client. If the system prompt + memories are identical across calls, the second call gets the cache hit regardless of process isolation.

#### Prompt Structure for Caching

Every proxy call shares a common prefix:

```
+------------------------------------------+
| System prompt (proxy instructions)       | <- cacheable
| Retrieved memories (top-k chunks)        | <- cacheable
+------------------------------------------+
| Gate context (state, task, history)       | <- varies per gate
| Artifact (Pass 2 only)                   | <- varies per gate
| Instruction (prior vs posterior prompt)   | <- varies per pass
+------------------------------------------+
```

The prefix (system prompt + memories) is stable across all calls in a session. The suffix (gate context, artifact, instruction) varies per call.

#### Cost Model

Let:
- P = system prompt tokens (~2,000)
- M = memory tokens (~5,000 for 10 chunks)
- C = gate content tokens per pass (~2,000)
- O = output tokens per pass (~500)
- D = delta extraction tokens (~500, only on surprise)
- G = number of gates per session
- r = cache discount rate (0.1 = 90% discount)
- w = cache-write premium (1.25)
- E = embedding cost per chunk (~5 calls at ~$0.0001 each, negligible vs. LLM calls)

**Current design (no two-pass, no caching):**
```
Input cost  = G x (P + M + C) = G x 9,000 tokens at full price
Output cost = G x O = G x 500 tokens
```

**Two-pass with prompt caching (input tokens only, for comparison):**
```
Input cost = w x (P + M)                      # first call: cache write premium
           + (2G - 1) x r x (P + M)           # remaining calls: cached prefix
           + 2G x C                            # per-pass: gate content at full price
           + surprise_rate x G x 2 x D         # delta extraction (surprise only)

Output cost = 2G x O                           # doubles with two passes
            + surprise_rate x G x 2 x 200      # delta extraction output
```

The cost model above focuses on input token-equivalents for the prefix reuse argument. The full cost comparison must include output tokens (which double) and the cache-write premium (1.25x on the first call). The savings from prefix caching are substantial for the input side; whether the total cost (input + output) is lower than single-pass depends on the ratio of prefix tokens to gate-specific tokens. For sessions with many gates and a large memory prefix, the cached design is cheaper overall. For sessions with few gates, the savings are smaller.

#### Verification Needed

This analysis assumes the `claude -p` CLI produces API calls whose prefixes match for cache purposes. This needs empirical verification:

1. Do two sequential `claude -p` subprocess calls with the same system prompt hit the Anthropic prompt cache?
2. Does the CLI add any per-call variation to the prompt (timestamps, session IDs) that would break prefix matching?
3. What is the actual cache TTL, and does it survive the time between gates in a real session?

If the CLI breaks caching, the proxy should be migrated to direct API calls. The proxy is a good candidate — it doesn't need tools, worktrees, or team sessions.

### Working Memory Capacity

The context window limits how many chunks can be loaded. At ~500 tokens per chunk and a 200K context window, reserving ~12,000 tokens for system prompt and gate content, the practical capacity is ~376 chunks. In practice, the activation threshold tau limits loading to a smaller set — self-regulating as memory accumulates. The actual loading count depends on interaction tempo and reinforcement patterns; tau may need adjustment based on observed activation distributions in shadow mode.

### Why This Is Future Work

The proxy invokes Claude via `claude -p` (subprocess). The CLI doesn't expose cache control. Explicit KV management requires direct API calls. The proxy is a good candidate for migration — it doesn't need tools, worktrees, or team sessions. But that migration is a separate effort. The current text-retrieval design and this KV cache design share the same memory theory; only the delivery mechanism differs.

---

## References

**Anderson, J. R., & Lebiere, C.** (1998). *The Atomic Components of Thought.* Lawrence Erlbaum Associates. — The definitive ACT-R reference. Chapter 4 covers declarative memory in full.

**Anderson, J. R., & Schooler, L. J.** (1991). Reflections of the environment in memory. *Psychological Science*, 2(6), 396-408. — Empirical basis for the power-law decay parameter. Read this first for intuition about why the math works.

**Park, S., et al.** (2023). Generative Agents: Interactive Simulacra of Human Behavior. *UIST '23*. — Weighted combination of recency, importance, and relevance with min-max normalization. Direct precedent for hybrid retrieval scoring.

**Nuxoll, A., & West, R.** (2024). Human-Like Remembering and Forgetting in LLM Agents. *HAI '24*. — ACT-R base-level activation + cosine similarity for LLM agent memory retrieval.

**ACT-R Tutorial, Unit 4: Activation of Chunks and Base-Level Learning.** Carnegie Mellon University. http://act-r.psy.cmu.edu/wordpress/wp-content/themes/ACT-R/tutorials/unit4.htm — Step-by-step tutorial with worked examples and code. The best starting point for implementation.
