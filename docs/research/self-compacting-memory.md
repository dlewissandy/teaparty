# Self-Compacting Agent Memory: Research Foundations

This document synthesizes research across five areas directly applicable to an LLM agent that must
manage its own context window by deciding what to keep verbatim, what to summarize, and what to
drop entirely. The organizing question: **how does a rational system forget?**

---

## 1. ACT-R Base-Level Activation Decay

ACT-R is the primary cognitive architecture for modeling human forgetting. Its base-level activation
mechanism has been validated against hundreds of memory experiments and provides a mathematically
precise account of how recency and frequency combine to determine memory accessibility.

### 1.1 The Formula

See `docs/research/act-r.md` for the full derivation and worked examples. The key equation:

```
B = ln( sum over all accesses i:  t_i ^ (-d) )
```

Where:
- `t_i` is elapsed time since the i-th access (seconds)
- `d` is the decay parameter, standardly **0.5**
- The sum is over every prior access (creation, retrieval, reinforcement)
- `ln` is the natural logarithm

**What the formula encodes.** Each access leaves a trace. Each trace decays as a power function of
elapsed time. Traces accumulate: a chunk accessed 50 times decays far more slowly than one accessed
once. The logarithm compresses the range, meaning you need exponentially more accesses to get linear
activation gains.

**The empirical basis for d=0.5.** Anderson & Schooler (1991) analyzed newspaper headlines,
child-directed speech, and email archives and found that real-world information relevance follows a
power-law decay with exponent approximately 0.5. The memory system is literally calibrated to match
how fast information becomes irrelevant in the environment. Forgetting is not a defect; it is a
rational response to environmental statistics.

### 1.2 Retrieval Threshold

A chunk is retrieved only if its activation exceeds the retrieval threshold tau (τ):

```
Retrieved if B > tau
```

ACT-R default: tau = 0. Tutorial models use tau = 0 to -2 depending on task demands. The probability
of retrieval follows a soft threshold (logistic function):

```
P(retrieve) = 1 / (1 + exp(-(B - tau) / s))
```

Where `s` is the noise parameter (logistic scale, typically 0.2-0.5 when enabled).

**What happens to sub-threshold chunks.** Critically: they remain in storage but are inaccessible
for retrieval. They are not deleted. This has a specific consequence: a forgotten chunk that receives
a new access adds a fresh trace and can pop back above threshold. Old traces still contribute weakly,
so re-exposure to familiar context recovers memories. This is the "oh, I remember that!" phenomenon.

### 1.3 Implications for TeaParty

The ACT-R model maps directly onto a TeaParty agent's context management problem:

- **Activation score = retention priority.** A memory item's retention score can be computed as
  `B = ln(sum of t_i^(-d))` where t_i tracks each time the item was retrieved or referenced. Items
  that were accessed recently and often stay accessible; items that have not been touched since
  creation decay away.

- **Threshold = compaction trigger.** When a memory item's B falls below tau, it is a candidate for
  summarization or eviction. The threshold is not a hard delete; it is a signal that the item should
  be compressed into a higher-level summary rather than kept verbatim.

- **Noise = soft boundary.** The logistic retrieval probability means there is no sharp cut-off. An
  agent implementing a soft variant would probabilistically retain items near the threshold rather
  than hard-deleting them, which avoids the "rare but critical instruction" problem identified in
  the memory surveys (see Section 5).

- **The approximation matters computationally.** Petrov (2006) and van Rijn et al. (2018) derive
  efficient approximations for the BLA equation. The exact formula requires recomputing all traces;
  the approximation (tracking only n accesses and time-of-creation) is O(1) per update. Applicable
  directly to scoring memory items at compaction time.

### 1.4 Key References

**Anderson, J.R. & Schooler, L.J.** (1991). Reflections of the environment in memory. *Psychological
Science*, 2(6), 396-408. Empirical foundation: power-law decay is calibrated to environmental
statistics, not arbitrary. URL: (no open access; widely cited in ACT-R literature)

**Anderson, J.R. & Lebiere, C.** (1998). *The Atomic Components of Thought.* Lawrence Erlbaum
Associates. Definitive derivation of the activation equations and retrieval threshold. The retrieval
probability formula (P = logistic) appears in Chapter 4.

**van Rijn, H., van Maanen, L., & van Woudenberg, M.** (2018). A Comparison of Approximations for
Base-Level Activation in ACT-R. *Computational Brain & Behavior*, 1(3-4), 218-232.
URL: https://link.springer.com/article/10.1007/s42113-018-0015-3

**ACT-R Tutorial, Unit 4: Activation of Chunks and Base-Level Learning.** Carnegie Mellon University.
URL: http://act-r.psy.cmu.edu/wordpress/wp-content/themes/ACT-R/tutorials/unit4.htm

**ACT-R Tutorial, Unit 5: Activation and Probability of Recall.** Carnegie Mellon University.
URL: http://act-r.psy.cmu.edu/wordpress/wp-content/themes/ACT-R/tutorials/unit5.htm

---

## 2. Memory Consolidation in Cognitive Science

Biological memory consolidation during sleep provides a second theoretical lens: not just decay, but
active, selective restructuring. The key insight is that consolidation is not about time passing; it
is about distinguishing signal from noise.

### 2.1 The Synaptic Homeostasis Hypothesis (SHY)

**Tononi & Cirelli (Sleep and the Price of Plasticity, PMC3921176, 2014)** is the canonical
computational account of sleep-dependent forgetting. The core claim:

During waking, all learning increases synaptic strength indiscriminately, which saturates capacity
and increases metabolic cost. Sleep performs global synaptic downscaling: most synapses are weakened
(non-Hebbian homeostatic plasticity). But engram-associated synapses — those involved in strongly
encoded memories — are **spared from downscaling or further potentiated**.

The result: signal-to-noise ratio increases. Memories that were encoded strongly survive the
downscaling and become more distinguishable from background noise. Memories that were encoded weakly
(single occurrence, low arousal, low reinforcement) fall below threshold.

**What determines survival in SHY:**
1. **Encoding strength at acquisition** — strongly encoded items survive global downscaling
2. **Consolidation tagging** — items tagged during wakefulness (via emotional salience, repetition,
   active rehearsal) are flagged for protection
3. **Reactivation during slow-wave sleep** — hippocampal replay strengthens selected memories via
   repeated reactivation, which effectively adds new access traces (exactly like ACT-R's trace
   accumulation)

### 2.2 The Dual Role: Forgetting Enables Consolidation

**Krause et al. (Frontiers in Cellular Neuroscience, 2019)** make the counterintuitive point explicit:
forgetting is not a side effect of consolidation — it is a necessary component. Without active
forgetting of irrelevant material, the signal-to-noise ratio cannot improve. The brain does not just
select what to keep; it actively suppresses what not to keep.

This has a direct computational implication: an agent that never forgets will experience *context
poisoning* — irrelevant old material competes with relevant current material for attention, degrading
performance. Proactive forgetting is not just about saving space; it is about maintaining retrieval
quality.

### 2.3 Selective Synaptic Plasticity: Homer1a and Arc

**Seibt & Frank (PMC9826981, 2022)** identify molecular mechanisms of selectivity during sleep:
scaling factors Homer1a and Arc are expressed selectively at synapses that should be downscaled, and
are absent at engram-tagged synapses. The mechanism is content-dependent, not purely time-dependent.

Computational translation: the decision of what to forget should be based on **content properties**
(importance, relevance, distinctiveness), not purely on age. Time-based eviction is necessary but
insufficient.

### 2.4 Systems Consolidation: Hippocampus to Neocortex

**Langille & Brown (Nature Neuroscience review, 2018)** describe systems-level consolidation: the
hippocampus initially holds episodic memories as high-fidelity traces, then replays them during sleep
to transfer gist-level abstractions to neocortex. The hippocampal episodic record eventually fades;
the neocortical semantic representation persists.

This maps directly onto a hierarchical summarization strategy:
1. **Episodic (verbatim)** — recent context stored exactly, in working memory / context window
2. **Semantic (gist)** — consolidated summaries stored in longer-term memory
3. **Procedural (schemas)** — highly-practiced patterns compressed into compact representations

### 2.5 Key References

**Tononi, G. & Cirelli, C.** (2014). Sleep and the Price of Plasticity: From Synaptic and Cellular
Homeostasis to Memory Consolidation and Integration. *Neuron*, 81(1), 12-34.
PMC: https://pmc.ncbi.nlm.nih.gov/articles/PMC3921176/

**Krause, A.J. et al.** (2019). Remembering to Forget: A Dual Role for Sleep Oscillations in Memory
Consolidation and Forgetting. *Frontiers in Cellular Neuroscience*, 13, 71.
URL: https://www.frontiersin.org/journals/cellular-neuroscience/articles/10.3389/fncel.2019.00071/full

**Seibt, J. & Frank, M.G.** (2022). Remembering and forgetting in sleep: Selective synaptic
plasticity during sleep driven by scaling factors Homer1a and Arc.
PMC: https://pmc.ncbi.nlm.nih.gov/articles/PMC9826981/

**Langille, J.J. & Brown, R.E.** (2018). Mechanisms of systems memory consolidation during sleep.
*Nature Neuroscience*. URL: https://www.nature.com/articles/s41593-019-0467-3

**Computational models of memory consolidation during sleep** (PubMed review, 2018).
URL: https://pubmed.ncbi.nlm.nih.gov/30321652/

---

## 3. Selective Forgetting in AI Systems

### 3.1 The Problem: Context Poisoning and Retrieval Degradation

**Park et al., Memory for Autonomous LLM Agents Survey (arXiv:2603.07670, 2026)** document the
central failure mode: agents that never forget accumulate irrelevant material that competes with
current relevant content for attention. The survey identifies two specific failure patterns:

1. **Context poisoning** — old, outdated facts persist and contradict current state
2. **Context distraction** — irrelevant historical content dilutes the signal of current relevant
   content, causing the model to attend to the wrong information

Neither problem is solved by simply expanding context windows. The paper reports that models scoring
near-perfect on long-context recall benchmarks "plummet to 40-60%" on multi-session agentic tasks
requiring decision-relevant memory integration. Retrieval is not the bottleneck — selective use is.

**Crucially:** the survey notes that selective forgetting is severely underdeveloped as a research
area. Current systems default to time-based expiration or storage-limit eviction — mechanisms that
cannot distinguish outdated information from safety-critical knowledge.

### 3.2 MemGPT: Hierarchical Tiered Memory

**Packer et al., MemGPT: Towards LLMs as Operating Systems (arXiv:2310.08560, NeurIPS 2023)** is
the foundational LLM agent paper for self-directed memory management.

Architecture:
- **Main context (in-context)** — the LLM's active working memory; fixed-size context window
- **Recall storage** — searchable database of all past interactions; retrieved by the agent on demand
- **Archival storage** — vector-indexed cold store for older material

The critical design choice: the LLM itself decides what moves between tiers. Memory operations
(write, read, search, evict, summarize) are exposed as tools. The agent controls its own memory
hierarchy the way an OS process controls virtual memory via system calls.

**Eviction policy:** MemGPT does not implement ACT-R-style decay. Eviction is triggered when main
context approaches capacity. The agent decides what to summarize and what to archive. This is
self-directed but not activation-driven.

**Implication for TeaParty:** MemGPT establishes the architectural pattern (tiered memory, agent
as memory controller). What it leaves unspecified is the decision criterion for eviction priority.
This is exactly where ACT-R base-level activation fills the gap.

### 3.3 SleepGate: Proactive Interference Resolution

**SleepGate (arXiv:2603.14517, 2026)** directly addresses the problem of outdated information
in the KV cache competing with current information — biologically called proactive interference (PI).

The paper demonstrates that PI causes retrieval accuracy to decline log-linearly toward chance as
stale associations accumulate, regardless of context length. The mechanism:

1. **Conflict-Aware Temporal Tagger** — detects when new entries semantically supersede old ones
2. **Forgetting Gate** — assigns retention scores to cache entries; applies soft attention biasing
   (log-based penalties to attention weights) rather than hard deletion
3. **Consolidation Module** — compresses semantically similar entries into summaries preserving the
   most recent value

Results: 99.5% retrieval accuracy at proactive interference depth 5, versus under 18% for all
baselines. Effective interference horizon reduced from O(n) to O(log n).

**Key design principle:** SleepGate uses **content-dependent forgetting** (learned via a small
neural network) rather than time-based or position-based eviction. The system learns what kinds of
content supersede other kinds, rather than applying uniform decay.

**Implication for TeaParty:** The forgetting gate design — applying soft penalties rather than hard
deletion — is directly implementable as a scoring function on context items. Rather than delete
sub-threshold items, down-weight their attention contribution or compress them into summaries.

### 3.4 AgeMem: Learned Memory Control via RL

**AgeMem (arXiv:2601.01885, 2026)** trains the memory management policy end-to-end via
reinforcement learning, exposing six memory tools to the agent:

- **LTM:** Add, Update, Delete
- **STM:** Retrieve, Summary, Filter

The agent learns when to invoke each operation from task outcomes. Three-stage progressive RL
training (store salient info → manage distractors → integrated task execution) with GRPO for
long-range credit assignment.

Results: 4.8-8.6 percentage points over non-trained baselines on five benchmarks; 3.1-5.1% prompt
token reduction while maintaining performance; memory quality scores of 0.533-0.605.

**Important caveat:** this is a preprint; the RL training approach has not yet been peer-reviewed.
The benchmark improvements are plausible but should be verified against independent evaluation.

**Implication for TeaParty:** The tool-based approach (memory operations as explicit agent actions)
aligns with TeaParty's agent-as-agent philosophy. However, the RL training requirement is not
immediately applicable. The six-tool taxonomy (Add/Update/Delete for LTM; Retrieve/Summary/Filter
for STM) is a useful target interface for a self-compacting memory system.

### 3.5 A-Mem: Zettelkasten-Style Linked Memory

**A-Mem (arXiv:2502.12110, 2025)** implements memory as a linked note graph inspired by the
Zettelkasten method. Each memory item is enriched with keywords, tags, semantic embeddings, and
explicit links to related memories. When new memories arrive, the system uses an LLM to identify
connections to existing memories and updates both the new and existing nodes' contextual
representations.

This is not primarily a forgetting system — A-Mem focuses on organization and retrieval. But it
demonstrates a key complementary principle: **memory compaction should preserve relationships, not
just content.** A flat summary that discards which items were connected loses navigational structure.

### 3.6 Key References

**Packer, C. et al.** (2023). MemGPT: Towards LLMs as Operating Systems. arXiv:2310.08560.
(NeurIPS 2023 workshop) URL: https://arxiv.org/abs/2310.08560

**SleepGate: Learning to Forget — Sleep-Inspired Memory Consolidation for Resolving Proactive
Interference in Large Language Models.** (2026) arXiv:2603.14517.
URL: https://arxiv.org/html/2603.14517

**AgeMem: Agentic Memory — Learning Unified Long-Term and Short-Term Memory Management for Large
Language Model Agents.** (2026) arXiv:2601.01885.
URL: https://arxiv.org/abs/2601.01885

**A-Mem: Agentic Memory for LLM Agents.** (2025) arXiv:2502.12110.
URL: https://arxiv.org/html/2502.12110v1

**Memory for Autonomous LLM Agents: Mechanisms, Evaluation, and Emerging Frontiers (Survey).** (2026)
arXiv:2603.07670. URL: https://arxiv.org/html/2603.07670

---

## 4. Progressive Summarization and Hierarchical Compression

### 4.1 The Summarization Drift Problem

The memory survey (arXiv:2603.07670) identifies the critical failure mode of rolling summarization:
**summarization drift**. When summaries are compressed repeatedly, low-frequency details are
progressively dropped. The system ends up with a sanitized, generic version of history that sounds
plausible but has lost specific constraints.

The canonical example: "A rare but critical instruction from day one — 'never call the production
database directly' — may survive the first compression but is exactly the kind of low-frequency,
high-importance detail that tends to vanish by the third pass."

This is exactly the ACT-R sub-threshold problem in another form: an item with high importance but low
access frequency will have low activation (B) and be dropped by pure decay-based eviction. The fix
requires separating **importance** from **access frequency** as distinct axes.

### 4.2 Generative Agents: Three-Factor Retrieval with Explicit Importance Scoring

**Park et al., Generative Agents: Interactive Simulacra of Human Behavior (UIST 2023, ACM)**
is the closest peer-reviewed system to what TeaParty needs. The memory retrieval score combines
three independent factors:

```
score = α * recency + β * importance + γ * relevance
```

Where:
- **Recency** — exponential decay since last access (t^-d analog)
- **Importance** — LLM-assigned score (1-10 scale) at encoding time, based on how "poignant" the
  event is. Mundane events score 1-3; significant events score 7-10.
- **Relevance** — cosine similarity between the memory's embedding and the current query embedding

Each dimension is normalized to [0,1] before combining. The α, β, γ weights are equal (1/3 each)
in the original paper.

**The reflection mechanism** is the critical ingredient for gist extraction. Periodically, the agent
scans its recent memory stream, asks itself "What are the 5 most important insights about my recent
experiences?", and writes reflection nodes that summarize patterns. These reflection nodes are higher-
level semantic memories that reference multiple episodic memories. Over time, episodic memories decay
by recency; reflection nodes persist because they capture recurring patterns.

This is a computational implementation of hippocampus-to-neocortex systems consolidation: episodic
detail fades, semantic gist persists.

**Implication for TeaParty:** The three-factor formula directly addresses the summarization drift
problem. Items with high importance but low recency are not dropped by recency-only scoring. An
agent compacting its context should compute importance at encoding time (not just at eviction time)
and use it to veto eviction of critical-but-infrequent items.

### 4.3 HiAgent: Subgoal-Based Hierarchical Chunking

**HiAgent (arXiv:2408.09559, ACL 2025)** implements a specific form of progressive summarization
that is architecturally clean for LLM agents: **subgoal completion as a compression trigger**.

The mechanism:
- Each task is decomposed into subgoals before execution begins
- While executing a subgoal, the full action-observation trajectory is kept verbatim
- When a subgoal completes, the trajectory is replaced with a summary
- Only the summary and the current subgoal's trajectory remain in working memory

Results across five long-horizon tasks: 2x improvement in success rate, 35% reduction in context
length, 19% reduction in wall-clock run time.

**What gets kept verbatim vs. compressed:**
- Current subgoal's action-observation pairs: verbatim (needed for immediate decision-making)
- Completed subgoal trajectories: compressed to summary (needed only as outcome reference)
- Earlier summaries: remain as compressed reference throughout the task

This is a principled answer to the verbatim vs. summarize decision: **recency within the current
task phase determines verbatim retention**. The boundary between verbatim and summarized is the
subgoal boundary, not a sliding window or an activation threshold.

**Implication for TeaParty:** CfA phases are natural compression boundaries. The action-observation
history within the current phase stays verbatim; the outcome of completed phases is compressed to
a summary. The sub-task / sub-agent boundary is the chunking unit.

### 4.4 ProMem: Proactive Memory Extraction

**ProMem: Beyond Static Summarization — Proactive Memory Extraction for LLM Agents (arXiv:2601.04463,
2026)** addresses the precision/recall tradeoff in extraction. Rather than summarizing everything,
ProMem operates in three stages:

1. **Initial extraction** — rapid scan to identify key facts (41-43% completeness at baseline)
2. **Memory completion** — semantic matching aligns extracted items to source dialogue, identifying
   gaps via embedding similarity (threshold 0.6)
3. **Verification loop** — self-questioning probes the original text to recover missed details and
   eliminate hallucinations

Result: 73.80% memory integrity versus 41-43% for static summarization baselines.

The key design choice: prioritize **recall over precision** (accepts slightly lower precision for
substantially higher completeness), and ground every extracted fact in a specific source passage
with a similarity score above 0.6. Facts that cannot be grounded are dropped as hallucinations.

**Implication for TeaParty:** Extraction fidelity is a first-class concern. A compaction step that
generates plausible-sounding summaries without verifying them against source content introduces
hallucinations into the agent's long-term memory — a hard-to-detect failure mode. The ProMem
pipeline (extract → verify → deduplicate) is the right structure for any summarization step.

### 4.5 Key References

**Park, J.S. et al.** (2023). Generative Agents: Interactive Simulacra of Human Behavior. UIST 2023.
ACM DL: https://dl.acm.org/doi/fullHtml/10.1145/3586183.3606763
arXiv: https://arxiv.org/abs/2304.03442

**Hierarchical Working Memory Management for Solving Long-Horizon Agent Tasks (HiAgent).** (2024)
arXiv:2408.09559. ACL 2025. URL: https://arxiv.org/abs/2408.09559

**Beyond Static Summarization: Proactive Memory Extraction for LLM Agents (ProMem).** (2026)
arXiv:2601.04463. URL: https://arxiv.org/html/2601.04463v1

---

## 5. Synthesis: A Decision Framework for Self-Compacting Context

Drawing these five research strands together, here is a principled decision framework for an LLM
agent managing its own context window.

### 5.1 Three Axes of Retention Priority

Every memory item should be scored on three independent axes before the compaction decision:

| Axis | Source | How to compute | Why it matters |
|------|--------|---------------|----------------|
| **Recency/frequency** (B) | ACT-R | `ln(sum of t_i^-d)`, d=0.5 | Frequently-accessed items are more likely to be needed again |
| **Importance** (I) | Generative Agents | LLM-assigned score (1-10) at encoding time | Rare but critical instructions must survive low recency |
| **Relevance** (R) | Generative Agents | Cosine similarity to current task embedding | Items relevant to current phase have priority regardless of age |

Combine as: `retention_score = α*B_normalized + β*I_normalized + γ*R_normalized`

The Park et al. (2023) paper uses α=β=γ=1/3 as a starting point. Weights can be tuned based on
task properties (long-horizon tasks may benefit from higher β to prevent summarization drift on
critical constraints).

### 5.2 Three Retention Decisions

Based on retention score and content type:

| Decision | Condition | Mechanism |
|----------|-----------|-----------|
| **Keep verbatim** | High B + high R (actively needed now) | No compression; stays in context window |
| **Summarize to gist** | Low-to-medium B, moderate I (not current, but not trivial) | Extract key facts via ProMem-style verification; compress to 1-3 sentences |
| **Drop** | Low B + low I + low R (not recent, not important, not relevant) | Evict from context; may retain in archival tier |

The SHY model provides the biological justification: items with high importance (strongly encoded)
survive global downscaling; items with low encoding strength do not.

### 5.3 The Sub-Threshold Problem and Its Fix

ACT-R's sub-threshold chunks are not deleted — they remain in storage and can be retrieved if
re-exposed. The agent memory equivalent: items below the eviction threshold should be **compressed,
not deleted**. They move to a summarized tier where their gist is preserved but their verbatim form
is released from the context window.

This is not just a storage optimization. The memory survey (arXiv:2603.07670) establishes that
the primary risk of aggressive compaction is loss of rare but critical constraints. The fix: never
hard-delete items that scored high on importance (I ≥ 7) at encoding time, regardless of their
current recency score. Archive them verbatim to a cold store rather than dropping them.

### 5.4 Compression Boundaries

HiAgent's insight is that subgoal completion is a principled compression trigger, not a sliding
window or a token count threshold. For TeaParty:

- **CfA phase completion** is the natural compression boundary
- Within the current phase: keep verbatim
- On phase completion: summarize the phase outcome (ProMem-style: extract, verify, deduplicate)
- Phase summaries: retain indefinitely at reduced fidelity

### 5.5 Proactive Interference Prevention

SleepGate establishes that stale information actively competes with current information (proactive
interference), reducing retrieval quality beyond what context length alone would predict. The fix
is not just eviction — it is identifying and down-weighting items that have been **superseded**
by later information.

For a TeaParty agent: when a new memory item contradicts or supersedes an existing item, the old
item's retention score should be penalized, not just aged out. The `docs/research/contradiction-
detection-memory.md` file covers the NLI / belief revision mechanisms for detecting supersession.

---

## 6. Research Gaps

These are the open questions most relevant to TeaParty's compaction design:

1. **Importance scoring at encoding time** — Park et al. use an LLM prompt ("how poignant is this?
   1-10"). This is expensive and potentially inconsistent. No peer-reviewed work has established a
   reliable, cheap importance estimator for agent context items.

2. **Evaluation benchmarks** — the memory survey notes that MemoryAgentBench (ICLR 2026) is the
   only benchmark that explicitly tests selective forgetting. All other benchmarks evaluate retrieval
   accuracy without testing whether forgotten items should have been forgotten. Evaluation remains
   immature.

3. **Optimal alpha/beta/gamma weights** — Park et al. use equal weights. No systematic study has
   optimized these weights for agentic settings with long-horizon constraints.

4. **Verification cost vs. fidelity tradeoff** — ProMem's three-stage pipeline achieves 73.8%
   integrity vs. 43% for static summarization, but at higher computational cost. No work has
   characterized the cost-fidelity Pareto frontier for different task types.

---

## Tags

`#memory` `#forgetting` `#working-memory` `#episodic` `#semantic` `#self-evolving`
`#context-injection` `#retrieval` `#teaparty-direct`
