# ACT-R Memory Model for the Human Proxy

This document describes the proxy agent's memory architecture: an activation-based memory system derived from ACT-R that models what the human would retrieve and attend to, combined with EMA as a system health monitor.

For the theory and equations, see [overview.md](overview.md).
For the concrete proxy mapping, see [mapping.md](mapping.md).
For the two-pass prediction model and learned attention, see [sensorium.md](sensorium.md).

---

## The Proxy's Job

The proxy's job is not to approve or reject. It is to **proxy the behavior of the human** — ask the questions the human would ask, probe the reasoning the human would probe, raise the concerns the human would raise, and reach a decision only after the kind of dialog the human would have conducted. Approval or rejection is the final act of a rich conversation, not a binary gate.

This requires modeling what the human would retrieve and attend to in a given context. The LLM then reasons over those retrieved memories to generate contextually appropriate questions and concerns. ACT-R models memory accessibility, not thinking. What the proxy retrieves shapes what the LLM reasons about. This selection mechanism is how past interactions influence current behavior.

The dimensions that matter for retrieval are: which memories activate above the retrieval threshold; what their content describes; how the current situation connects to them through semantic similarity and structural match.

## Two Systems, Two Roles

**ACT-R activation memory** models memory accessibility. It stores memories of past interactions (the questions the human asked, the concerns they raised, the reasoning they applied, the corrections they made) and surfaces the memories most relevant to the current context. The LLM then uses these retrieved memories as raw material to simulate the human's conversational behavior. This is the core of the proxy's cognitive capability.

**EMA** monitors system health. It tracks approval rates per (state, task_type) over time, not to decide whether to approve but to detect trends. When approval rate drops from 0.8 to 0.4 over 10 sessions, the planning agent is producing worse plans and the proxy is catching it. EMA is a diagnostic signal about how well the upstream agents are performing, not a decision mechanism for the proxy.

The current system conflates these roles. EMA drives the approve/escalate decision. The new design separates them: ACT-R memory drives the proxy's behavior (what questions to ask, what to attend to, what the human would say). EMA observes the outcomes and reports on system health.

## What Changed from the Original Model

The original model used EMA as a decision gate: confidence above threshold yielded auto-approval, below yielded escalation. This failed for several reasons.

It skips inspection. A high EMA means the proxy auto-approves without reading the artifact. The human would have read it, probed the details, challenged assumptions, verified completeness, even when ultimately approving. Quality requires artifact inspection. EMA skips inspection entirely. Two-pass prediction ensures inspection through explicit prior-posterior comparison.

It has no context sensitivity. The same EMA applies whether the human is reviewing a security plan or a documentation update. The proxy cannot ask different questions for different artifacts.

It cannot distinguish habitual from episodic patterns. A human's stable preference ("always asks about rollback plans") is invisible to a scalar, as is their recent shift ("rejected the last two migration plans").

It has no connection to discovery mode. The proxy's between-session reviews produce richer interactions than a scalar can represent. See [autodiscovery.md](../../../reference/autodiscovery.md) for details.

ACT-R activation memory solves these problems. EMA stays, reframed as monitoring. This transition is complete — EMA is decoupled from confidence scoring ([#220](https://github.com/dlewissandy/teaparty/issues/220)) and ACT-R memory drives retrieval and prediction.

Note: the design does permit autonomous proxy action (without escalation to the human) when the proxy has demonstrably inspected the artifact via two-pass prediction and its predictions consistently match the human's patterns. This is earned through consistent inspection, not inferred from a scalar. See [sensorium.md](sensorium.md) for how this differs from EMA-based auto-approval.

---

## The Approach

Replace the scalar confidence model with **activation-weighted embedding retrieval**.

**Base-level activation** from ACT-R handles forgetting. Each memory has traces that decay as a power function of interactions elapsed. Frequently reinforced memories stay active; one-off events fade. The equation is `B = ln(Sigma t_i^(-d))` with `d = 0.5`. See [overview.md](overview.md) for the full derivation.

**Vector embeddings** handle context sensitivity. Each memory chunk's content is embedded; retrieval uses cosine similarity to find semantically relevant memories. This replaces ACT-R's symbolic spreading activation with semantic overlap in embedding space, achieving context-sensitive retrieval through a different mechanism than structural graph associations.

**Structural filtering** handles the relational structure. The chunk is a tuple (state, outcome, task_type, ...) where field ordering matters. SQL queries on structural fields narrow the candidate set; semantic ranking orders within the filtered set. See [mapping.md](mapping.md) for the chunk schema.

**Interaction-based time** replaces wall-clock seconds. The decay equation uses interaction counts (gate decisions, dialog turns, discovery responses), not seconds. Between sessions, the counter does not advance; memories do not decay while the system is idle. Event-based time is well-motivated: Anderson & Schooler's (1991) empirical analysis was event-based. Wall-clock decay during idle periods would be inappropriate for an agent system. The specific decay exponent (d = 0.5) is a principled starting point from ACT-R's empirical tradition, to be calibrated during Phase 1.

---

## What Changed, What Stayed

**Changed (all operational):**
- EMA role: from decision gate (approve/escalate) to system health monitor (are upstream agents improving?) ([#220](https://github.com/dlewissandy/teaparty/issues/220))
- Memory: from scalar per state-task pair to chunk-based activation memory (`proxy_memory.db`)
- Decision process: from threshold check to simulated dialog (proxy asks the questions the human would ask, then decides)
- `consult_proxy()`: from confidence lookup to retrieval plus LLM reasoning over past interactions

**Stayed:**
- `.proxy-confidence.json` — still tracks EMA per state-task pair, now as a monitoring signal
- The proxy agent prompt structure (receives context, generates prediction)
- The proxy agent's tools (file read, dialog)
- The delta-based learning signal (prediction vs. reality)
- The intake dialog flow
- The discovery mode concept and discussion lifecycle

---

## Migration Path

The transition can be incremental.

### Phase 0: Specification Checklist — Complete

Phase 0 design decisions have been resolved:

1. **Embedding model:** OpenAI `text-embedding-3-small` (primary), Gemini `embedding-001` (fallback). Configured in `memory_indexer.py`.
2. **Chunk serialization:** `blended_text_from_fields()` in `proxy_memory.py` concatenates state, task_type, content, human_response, and prediction_delta into a single string for blended embedding.
3. **Prompt templates:** Two-pass prediction prompts implemented in `proxy_agent.py` — prior (without artifact), posterior (with artifact + prior).
4. **Output parsing:** ACTION and CONFIDENCE parsed from final lines of LLM output via regex. Parse failures default to confidence 0.0.
5. **Confidence:** 0.0–1.0 probability scale. Post-hoc calibration via `_calibrate_confidence()` caps at 0.5 when ACT-R memory depth is below threshold.
6. **Concurrency:** SQLite with WAL mode for multi-process access to `proxy_memory.db`.

### Phase 1: Integration — Complete

ACT-R memory system and two-pass prediction are operational on the develop branch. EMA is decoupled from the decision gate ([#220](https://github.com/dlewissandy/teaparty/issues/220)) and serves as a system health monitor only.

**Evaluation metrics** — implemented in `evaluate_proxy.py` and `proxy_metrics.py` ([#221](https://github.com/dlewissandy/teaparty/issues/221)):
- Action match rate: did the proxy's posterior action match the human's actual decision?
- Prior calibration: how often did the prior match the posterior?
- Surprise calibration: when surprise was detected, did the human's response confirm that the salient percepts were relevant?
- Retrieval relevance: human spot-checks of retrieved memory sets for qualitative assessment

**Go/no-go criteria for Phase 2 transition:**
- Minimum sample: 50 gate interactions spanning at least 3 task types and 4 CfA states before any evaluation is meaningful.
- Action match rate: >= 70% agreement between proxy posterior action and human actual decision.
- Multi-dimensional embedding ablation: if single-embedding retrieval achieves >= 95% of multi-dimensional retrieval's match rate, simplify to single embedding.
- ACT-R decay vs. simple recency ablation: if most-recent-N retrieval achieves >= 95% of ACT-R decay's match rate, the activation machinery is not earning its complexity.

**Ablations — implemented** in `proxy_ablation.py`:
- Multi-dimensional embeddings (5 vectors) vs. single blended embedding ([#222](https://github.com/dlewissandy/teaparty/issues/222)) — scoring is swappable via `retrieve_chunks()` mode parameter
- ACT-R decay vs. simple recency (most-recent-N) ([#223](https://github.com/dlewissandy/teaparty/issues/223))
- Composite score vs. activation-only and similarity-only retrieval ([#225](https://github.com/dlewissandy/teaparty/issues/225)) — leave-one-out ablation with action match rate metric
- Two-pass prediction vs. single-pass (posterior only) — built into the two-pass architecture

Additional Phase 1 capabilities implemented:
- Salience index separated from chunk embeddings ([#227](https://github.com/dlewissandy/teaparty/issues/227))
- Contradiction detection and LLM-as-judge classification ([#228](https://github.com/dlewissandy/teaparty/issues/228))
- Per-context prediction accuracy tracking ([#226](https://github.com/dlewissandy/teaparty/issues/226))
- Asymmetric confidence decay following Hindsight (arXiv:2512.12818) ([#228](https://github.com/dlewissandy/teaparty/issues/228))
- Post-session proxy memory consolidation with Mem0-style ADD/UPDATE/DELETE/SKIP taxonomy ([#228](https://github.com/dlewissandy/teaparty/issues/228))

**Status:** Phase 1 is feature-complete. Go/no-go evaluation requires accumulating sufficient gate interactions from real sessions.

### Phase 2: Learned Attention

ACT-R memory, two-pass prediction, and EMA monitoring are unified. The proxy conducts the dialog the human would have conducted. The accumulated prior-posterior deltas build a learned attention model. EMA surfaces trends in system performance.

Phase 2 requires Phase 1 go/no-go evaluation data from real sessions.

---

## Future Direction: KV Cache as Working Memory

The current design retrieves memory chunks as text, inserts them into the LLM prompt, and reprocesses them from tokens on every call. This works but misses a deeper alignment between ACT-R's cognitive architecture and the LLM's native machinery. This section specifies what a KV-cache-based architecture would look like concretely. The core design (text retrieval without caching) stands on its own; this section describes what becomes possible when the proxy is migrated to direct API calls.

### Roles of the Three Systems

**ACT-R** provides the memory selection policy. It answers which memories are active enough to load, not how they are processed.

**The KV cache** is working memory. It holds the LLM's processed understanding of the loaded memories. Once a memory is in the cache, the LLM does not re-read it. The processed state is already there. The cache persists within a session (across gates) and is populated at session start.

**The LLM's transformer attention** provides context sensitivity. When the LLM processes chunk A, its attention mechanism creates internal representations that prime processing of subsequent chunks. Associations emerge from the LLM's own reasoning over the cached content, not from precomputed scores.

**Prediction-change salience** is the perceptual filter. Inspired by Itti & Baldi's Bayesian surprise framework but operating on categorical predictions, the two-pass prediction identifies what in the artifact changed the proxy's mind. The surprise (the processed percept) is what gets stored as a new chunk. Raw artifacts and raw interactions do not enter long-term memory.

### Session Lifecycle

The session lifecycle has three phases: loading working memory at session start, a per-gate prediction loop, and storage of processed percepts. Working memory is populated once and reused across all gates via the KV cache. Each gate runs the two-pass prediction (prior without artifact, posterior with), computes surprise from the structured action delta, and stores only the surprise as a new memory chunk.

### Concurrency

Dispatches run in parallel. Multiple gates may arrive concurrently from different subteams. The proxy does not split into parallel instances. It is one brain with one memory and one interaction counter.

Gates enter a **FIFO queue** and the proxy processes them one at a time. This is how a human works: concurrent tasks compete for attention, but attention is serial. The queue ordering means that what the proxy learns from dispatch A's gate is available when it processes dispatch B's gate. Cross-task learning happens naturally through the sequential processing of concurrently-produced work. Whether cross-task priming is beneficial or contaminating depends on the tasks. Cross-cutting patterns ("this human always asks about test coverage") generalize usefully, while domain-specific patterns do not. The structural filtering in retrieval mitigates contamination. When processing a documentation gate, security-specific chunks are not surfaced unless the semantic match is strong.

At WORK_ASSERT (the rollup), the proxy does not need a special aggregation step. It has already processed each dispatch gate individually, storing surprises and building understanding throughout the session. WORK_ASSERT is just another gate where the proxy reasons over its accumulated memories (which now include fresh chunks from all the dispatch gates it processed during this session).

```
SESSION START
    read interaction counter N from storage
    for each chunk in long-term storage:
        compute B = ln(Sigma (N - trace_i)^(-0.5))
    filter chunks where B > tau
    sort survivors by B descending
    load top chunks into prompt prefix while budget remains
    process prefix into KV cache
    initialize gate queue (FIFO)

    as gates arrive from dispatches, enqueue them
    for each gate dequeued:
        increment N

        PASS 1 -- PRIOR
            generate from cached prefix + gate context, no artifact
            output: free human-voice text + CONFIDENCE: <float> on final line
            parse -> prior.prose, prior.confidence

        PASS 2 -- POSTERIOR
            generate from cached prefix + gate context + artifact + prior
            output: free human-voice text + CONFIDENCE: <float> on final line
            parse -> posterior.prose, posterior.confidence

        SURPRISE
            if |posterior.confidence - prior.confidence| > 0.3:
                surprise: extract description + salient percepts (1 LLM call)
            else:
                no surprise, no additional calls

            (Pre-583cccd8, an additional `prior.action != posterior.action`
             branch triggered a heavier 2-call extraction.  Categorical
             per-pass actions were retired in that migration; classification
             now runs downstream on the final response via _classify_review.)

        DECISION
            execute gate using posterior
            receive human response if escalated

        STORE
            create chunk from prediction results + human response + proxy error
            populate salience fields only if surprise was detected
            embed situation, stimulus, response, salience independently
            store with first trace = N

SESSION END
    discard cache
```

Note: the REINFORCE step present in earlier drafts has been removed. In standard ACT-R, chunks are reinforced only when specifically retrieved for a task and actively referenced by a production rule, not merely by being present in working memory. Loading chunks into the prompt prefix is analogous to having chunks in declarative memory above threshold; it does not constitute retrieval-and-use. Chunks earn traces through creation (rule 1) and retrieval (rule 2) only. This prevents the rich-get-richer feedback loop where already-active chunks accumulate traces from every gate regardless of relevance.

EMA and the memory system operate on separate data paths. EMA tracks approval rates per (state, task_type); the memory system records interaction chunks. When upstream quality degrades, the memory system responds through its normal operation. More correction chunks accumulate, shifting retrieval toward skeptical patterns, not through EMA influencing retrieval.

### Data Structures

```
PassResult
    prose      : free human-voice text
    confidence : 0.0–1.0 float

SurpriseDelta
    magnitude        : 0.5 (confidence shifted > 0.3), or 0.0 (confirmed)
    prior prose      : reasoning before artifact
    prior confidence : confidence before artifact
    posterior prose  : reasoning after artifact
    posterior confidence : confidence after artifact
    description      : what in the artifact caused the shift
    salient percepts : list of artifact features that caused the shift

MemoryChunk
    id, type, state, task_type, outcome              -- structural (SQL-filtered)
    prior confidence, posterior confidence           -- two-pass trajectory
    surprise description, salient percepts            -- processed percept (empty if no surprise)
    human response                                   -- ground truth (classified via _classify_review)
    traces                                            -- list of interaction numbers
    embedding_situation, _artifact, _stimulus, _response, _salience -- independent vectors
```

Both passes produce free human-voice text followed by `CONFIDENCE: <float>` on the final line. Surprise extraction runs when confidence shifted significantly (1 additional LLM call). Most gates produce no surprise: 2 calls. Surprises cost 3. Categorical action — which drives learning from human corrections — is classified downstream from the final human/proxy response by `_classify_review` in `teaparty/cfa/actors.py`, not per-pass at the proxy; that split dates to commit 583cccd8 (2026-04-16).

### Cache Economics

The two-pass prediction model doubles the proxy's LLM calls per gate. Without cost mitigation, this is prohibitive. Prompt caching (reusing the processed KV state for a shared prompt prefix across calls) is the mitigation.

#### How Anthropic Prompt Caching Works

The Anthropic Messages API supports prompt caching via `cache_control` blocks. When a message prefix is marked cacheable:

- **First call**: full price to process the prefix (input tokens at standard rate), plus a 1.25x cache-write premium
- **Subsequent calls with the same prefix** (within 5-minute TTL): cached prefix tokens at ~10% of standard rate (e.g., 0.30/MTok instead of 3.00/MTok for Sonnet)
- **1-hour TTL option**: Anthropic also offers a 1-hour TTL at 2x write premium, which may be more cost-effective for sessions where gates are spaced more than 5 minutes apart
- **Cache matching is workspace-level** (as of February 2026; previously organization-level), not session-level. Two separate API calls with the same prefix hit the cache, even from different processes.

This last point is critical. The proxy invokes Claude as a subprocess (`subprocess.run(['claude', '-p', ...])`) — one process per pass. There is no shared state between processes. But prompt caching operates at the API backend, not the client. If the system prompt plus memories are identical across calls, the second call gets the cache hit regardless of process isolation.

#### Prompt Structure for Caching

Every proxy call shares a common prefix:

```
+------------------------------------------+
| System prompt (proxy instructions)       | <- cacheable
| Retrieved memories (top-k chunks)        | <- cacheable
+------------------------------------------+
| Gate context (state, task, history)      | <- varies per gate
| Artifact (Pass 2 only)                   | <- varies per gate
| Instruction (prior vs posterior prompt)  | <- varies per pass
+------------------------------------------+
```

The prefix (system prompt plus memories) is stable across all calls in a session. The suffix (gate context, artifact, instruction) varies per call.

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

The cost model above focuses on input token-equivalents for the prefix reuse argument. The full cost comparison must include output tokens (which double) and the cache-write premium (1.25x on the first call). The savings from prefix caching are substantial for the input side; whether the total cost (input plus output) is lower than single-pass depends on the ratio of prefix tokens to gate-specific tokens. For sessions with many gates and a large memory prefix, the cached design is cheaper overall. For sessions with few gates, the savings are smaller.

#### Worked Example

For a 10-gate session using Sonnet ($3/MTok input, $0.30/MTok cached read, $15/MTok output):

**Current design:**
- 10 gates × 9,000 input tokens (prompt + memory + content) = 90,000 input tokens @ $3/MTok = $0.27
- 10 gates × 500 output tokens = 5,000 output tokens @ $15/MTok = $0.075
- Total: ~$0.35

**Two-pass with caching (corrected):**
- Cache write: 7,000 tokens × ($3/1,000,000) × 1.25 = $0.02625
- Cached reads: 19 reads × 7,000 tokens × ($0.30/1,000,000) = $0.0399
- New gate content: 20 passes × 2,000 tokens × ($3/1,000,000) = $0.12
- Surprise extraction (20% rate): 2 gates × 500 tokens × ($15/1,000,000) = $0.015
- Output (20 passes): 20 × 500 tokens × ($15/1,000,000) = $0.15
- **Total: ~$0.33**

The two-pass design with caching costs approximately $0.33 per session, making it roughly 6% cheaper than the current design (~$0.35). This is cost-equivalent or slightly cheaper thanks to prefix caching, which strengthens the economic argument. The cache infrastructure becomes an investment with immediate payback rather than a cost overhead.

#### Verification Needed

This analysis assumes the `claude -p` CLI produces API calls whose prefixes match for cache purposes. This needs empirical verification:

1. Do two sequential `claude -p` subprocess calls with the same system prompt hit the Anthropic prompt cache?
2. Does the CLI add any per-call variation to the prompt (timestamps, session IDs) that would break prefix matching?
3. What is the actual cache TTL, and does it survive the time between gates in a real session?

If the CLI breaks caching, the proxy should be migrated to direct API calls. The proxy is a good candidate. It does not need tools, worktrees, or team sessions.

Phase 0 verification (1-2 weeks): Test prompt caching behavior with `claude -p` subprocess calls. If caching is not reliable, the two-pass design cost rises approximately to $0.50/session. Cost-benefit analysis will determine whether to proceed to Phase 1 with simpler single-pass design plus memory augmentation instead.

### Working Memory Capacity

The context window limits how many chunks can be loaded. At ~500 tokens per chunk and a 200K context window, reserving ~12,000 tokens for system prompt and gate content, the practical capacity is ~376 chunks. In practice, the activation threshold tau limits loading to a smaller set, self-regulating as memory accumulates. The actual loading count depends on interaction tempo and reinforcement patterns; tau may need adjustment based on observed activation distributions during Phase 1.

### Why This Is Future Work

The proxy invokes Claude via `claude -p` (subprocess). The CLI does not expose cache control. Explicit KV management requires direct API calls. The proxy is a good candidate for migration. It does not need tools, worktrees, or team sessions. But that migration is a separate effort. The current text-retrieval design and this KV cache design share the same memory theory; only the delivery mechanism differs.

---

## References

**Anderson, J. R., & Lebiere, C.** (1998). *The Atomic Components of Thought.* Lawrence Erlbaum Associates. — The definitive ACT-R reference. Chapter 4 covers declarative memory in full.

**Anderson, J. R., & Schooler, L. J.** (1991). Reflections of the environment in memory. *Psychological Science*, 2(6), 396-408. — Empirical basis for the power-law decay parameter. Read this first for intuition about why the math works.

**Park, J.S., et al.** (2023). Generative Agents: Interactive Simulacra of Human Behavior. *UIST '23*. — Weighted combination of recency, importance, and relevance with min-max normalization. Direct precedent for hybrid retrieval scoring.

**Honda, Y., Fujita, Y., Zempo, K., & Fukushima, S.** (2025). Human-Like Remembering and Forgetting in LLM Agents: An ACT-R-Inspired Memory Architecture. In *Proceedings of the 13th International Conference on Human-Agent Interaction* (HAI '25), pp. 229-237. ACM. DOI: 10.1145/3765766.3765803 — ACT-R base-level activation plus cosine similarity for LLM agent memory retrieval. Best Paper Award, HAI 2025.

**ACT-R Tutorial, Unit 4: Activation of Chunks and Base-Level Learning.** Carnegie Mellon University. http://act-r.psy.cmu.edu/wordpress/wp-content/themes/ACT-R/tutorials/unit4.htm — Step-by-step tutorial with worked examples and code. The best starting point for implementation.
