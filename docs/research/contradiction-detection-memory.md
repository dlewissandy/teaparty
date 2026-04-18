# Contradiction Detection in Agent Memory Systems

Research on detecting, classifying, and resolving conflicting information in persistent agent memory — with particular focus on LLM agent systems that accumulate episodic memories of a specific human's decisions and preferences.

This file was created to support the TeaParty proxy agent's "contradictory retrieval" signal (described in `docs/systems/human-proxy/index.md` §"Knowing When to Ask"): when retrieved memories point in conflicting directions, the proxy must recognize the conflict, classify its cause, and decide whether to act, merge, or escalate.

---

## Why This Is Hard

Contradiction detection in natural language memory is harder than it sounds. Two conditions must both hold:

1. **Semantic relationship detection**: two statements must be recognized as being about the same thing (coreference, entity linking) and asserting incompatible values or stances.
2. **Context sensitivity**: what looks like a contradiction may be context-dependent ("avoid meetings" vs. "schedule a weekly sync" are not contradictory if the human is talking about different contexts). The detector must distinguish genuine inconsistency from domain-scoping.

In preference memory specifically, there is a third complication:

3. **Temporal ordering**: a newer preference may supersede an older one — this is preference drift, not contradiction. The system must distinguish between "these two are inconsistent and I need to ask" versus "this one is more recent and therefore supersedes the older one."

The literature has converged on a basic taxonomy of why retrieved memories conflict:
- **Preference drift**: the human changed their mind; the newer signal is the ground truth.
- **Context sensitivity**: both are correct, in different contexts (domain, stakes, urgency).
- **Genuine inconsistency**: the human has not resolved a real tension in their own preferences; surfacing this is the right response.
- **Retrieval noise**: the memories are not actually about the same thing; apparent conflict is an artifact of fuzzy matching.

---

## Techniques: What the Field Actually Uses

### 1. LLM-as-Judge: The Dominant Approach

The most common mechanism in deployed systems (2024-2026) is to present the candidate set of retrieved memories to an LLM and ask it to classify each pair as entailing, contradicting, or neutral — and if contradicting, to resolve or flag. This is sometimes called "LLM-as-judge" for memory consistency.

**Why it dominates:** LLMs understand context sensitivity naturally. They can distinguish "I prefer fast solutions" (context: prototyping) from "I prefer careful solutions" (context: production) without being told these are different scopes. Symbolic NLI models cannot do this without extensive feature engineering.

**Typical operation sequence (from Mem0 and similar systems):**
1. A new memory candidate arrives (from an interaction).
2. Candidate memories from the store are retrieved by semantic similarity.
3. An LLM is prompted with the candidates and the new item: for each pair, classify the relationship and produce one of: **ADD** (no conflict), **UPDATE** (complement existing), **DELETE** (new supersedes old), **SKIP** (already represented).
4. The decision is applied to the store.

This is also how Hindsight (2025) and EgoMem (2025) operate. EgoMem calls this a "Memory Update Agent" — an LLM component specifically tasked with identifying conflicts and updating structured profiles. Hindsight uses confidence-scoring: contradicting evidence triggers a larger confidence adjustment than merely weakening evidence, following the formula `max(c - 2α, 0.0)`.

**Limitation:** LLM-as-judge is expensive to run at write time for large memory stores. The cost scales with the number of candidate memories retrieved for comparison. Systems manage this by retrieving only semantically close candidates (top-k by embedding similarity), not the entire store.

### 2. Recency-Based Resolution (Temporal Priority)

The simplest non-trivial strategy: when two memories conflict, prefer the more recent one. This is implemented in Memoria (2025) via an exponential decay weighting function — newer triplets receive higher weights and effectively override older ones during retrieval and response generation.

**When it works:** For preference drift (the human changed their mind), recency is usually the right tiebreaker. If a human recently said "I want daily status updates" and an older memory says "I prefer weekly summaries," the recent one is almost certainly correct.

**When it fails:** For context-sensitive preferences, recency is the wrong criterion. Both the old and new preferences may be valid in different circumstances. Treating the newer one as overriding discards information that is still valid in its original context.

**TeaParty implication:** Recency weighting should be applied as a default tiebreaker when the proxy classifies a conflict as likely preference drift (i.e., when the two memories are in the same context domain and the newer one is more specific). It should not be applied when the proxy suspects context sensitivity.

### 3. Embedding Clustering + LLM Resolution (O-Mem Approach)

O-Mem (2025) uses a two-stage approach for persona memory specifically:
1. **LLM-augmented nearest-neighbor clustering**: new attributes are clustered with existing ones by semantic similarity.
2. **LLM consolidation within clusters**: when a cluster contains potentially conflicting attributes, an LLM analyzes the cluster and synthesizes a coherent representation.

This is more sophisticated than pure recency but also more expensive. It treats memory as an active curation task rather than a passive accumulation task. The key insight: rather than preserving all raw observations and resolving conflicts at retrieval time, O-Mem resolves them at write time, keeping the store itself coherent.

**TeaParty implication:** This "write-time consolidation" approach is architecturally similar to what the TeaParty learning system calls "compaction." The proxy's `proxy.md` preferential store is a natural candidate for this pattern: when new preference observations arrive, a compaction pass could cluster them and consolidate conflicting entries rather than appending them.

### 4. Structured Memory with Confidence Scores (Hindsight Approach)

Hindsight (arXiv:2512.12818, 2025) separates agent memory into distinct networks: objective facts, personal experiences, and opinions. Only opinions carry confidence scores and update via the conflict mechanism. The update rule:
- Reinforcing evidence: small confidence increase
- Weakening evidence: small confidence decrease
- Contradicting evidence: `max(c - 2α, 0.0)` — a larger, asymmetric decrease

The asymmetry here is intentional and principled: a single contradicting example should destabilize a belief more than a single supporting example should reinforce it, because false beliefs are more dangerous than missed reinforcements. This is structurally similar to TeaParty's 3x asymmetric regret weighting on corrections (see `human-proxy-agent-design.md` §2).

When confidence falls below a threshold, the opinion text itself can be revised or removed. This avoids the proliferation of low-confidence stale beliefs that would otherwise accumulate.

### 5. NLI-Based Detection (Dialogue Systems Heritage)

Natural Language Inference (NLI) classifies sentence pairs as entailment, contradiction, or neutral. Dialogue NLI (Welleck et al., 2019, ACL 2019) applied this to chatbot persona consistency: an NLI model detected when a bot's new utterance contradicted an earlier persona statement, enabling utterance re-ranking to reduce contradictions.

**Why NLI has fallen out of favor for memory systems:** Modern LLM-based agents are already running an LLM; adding a separate NLI model adds infrastructure without adding capability the LLM does not already provide. LLM-as-judge subsumes NLI. The NLI literature is still relevant for understanding what the classification problem is, and for offline evaluation, but deployed systems have largely moved to LLM-as-judge.

**Where NLI-based approaches still apply:** Benchmarking and evaluation. MemBench (2025, ACL Findings) uses NLI-like pair classification to evaluate whether memory systems preserve consistency. MemoryRewardBench (2025) evaluates reward models trained to score memory quality including consistency.

---

## Benchmark Landscape: What Gets Evaluated

**MemBench (Tan et al., 2025 — ACL Findings)**
- URL: https://arxiv.org/abs/2506.21605 / https://aclanthology.org/2025.findings-acl.989/
- Tests: information extraction, multi-hop reasoning, knowledge updating, preference following, temporal reasoning.
- Knowledge updating directly tests whether agents handle contradictory information (when a prior fact is overridden by a new one in context).
- Finding: existing systems including Mem0 and MemoryOS show significant weakness on knowledge updating tasks — most systems are better at retrieval than at update/revision.

**MemoryBench (Ai et al., 2025 — arXiv:2510.17281)**
- URL: https://arxiv.org/abs/2510.17281
- Tests: continual learning from feedback, multi-domain.
- Finding: A-Mem, Mem0, and MemoryOS "cannot consistently outperform RAG baselines" on continual learning — systems that simply retrieve rather than maintain coherent memory are competitive, which suggests current update/consolidation mechanisms are not adding much value yet.

**BEAM (Tavakoli, Salemi et al., ICLR 2026 — arXiv:2510.27246)**
- URL: https://arxiv.org/pdf/2510.27246
- Tests: long-term memory retention over very long contexts (beyond 1M tokens).
- Includes contradiction resolution, event ordering, instruction following.
- Finding: all current LLMs degrade significantly on memory tasks as context length increases; explicit memory management is necessary.

---

## Key Systems and Their Contradiction-Handling Mechanisms

### Mem0 (Chhikara et al., 2025)
- URL: https://arxiv.org/abs/2504.19413
- Mechanism: LLM-as-judge at write time. When adding a new memory, the system retrieves semantically similar existing memories and prompts an LLM to classify each relationship as: ADD, UPDATE, DELETE, or SKIP. "The latest truth wins" when a contradiction is detected; the old memory is deleted or overwritten.
- Mem0g (graph variant) adds a Conflict Detector and LLM-powered Update Resolver that flags overlapping or contradictory nodes/edges before committing.
- Evidence: 26% accuracy improvement over OpenAI Memory on LOCOMO benchmark; 91% lower p95 latency vs. full-context.
- **Directly relevant:** This is the most production-validated contradiction-handling mechanism in the literature. The ADD/UPDATE/DELETE/SKIP classification maps naturally onto operations the TeaParty proxy's memory store could perform.

### Hindsight (arXiv:2512.12818, 2025)
- URL: https://arxiv.org/html/2512.12818v1
- Mechanism: Structured separation of facts, experiences, and opinions. Opinions carry confidence scores. Contradicting evidence decreases confidence asymmetrically (`max(c - 2α, 0.0)`). When confidence falls below threshold, belief is revised or removed.
- Conflict resolution in biographical facts: LLM-powered merging that "resolves direct conflicts in favor of new information when appropriate" while appending non-conflicting details.
- **Directly relevant:** The asymmetric confidence update rule for contradictions is a principled and inexpensive mechanism TeaParty could adapt for preference memories. Contradicting evidence destabilizes beliefs more than supporting evidence reinforces them — this matches the 3x regret asymmetry already in the proxy design.

### EgoMem (arXiv:2509.11914, 2025)
- URL: https://arxiv.org/html/2509.11914
- Mechanism: Memory Update Agent — an external LLM that receives new extracted information plus the existing user profile and is prompted to identify conflicts and update accordingly. Conflict detection is delegated entirely to LLM reasoning, not a separate classification model.
- Results: 87%+ fact-consistency in personalized dialogs; >98% F1 on episodic trigger evaluation.
- **Relevant:** Confirms that LLM-as-judge for memory updates achieves high factual consistency in practice. The architecture — separate update agent, asynchronous to main dialog — is compatible with TeaParty's post-session learning pipeline.

### O-Mem (arXiv:2511.13593, 2025)
- URL: https://arxiv.org/html/2511.13593v1
- Mechanism: LLM-augmented nearest-neighbor clustering for persona attributes. New attributes are grouped with existing ones; clusters are consolidated by an LLM that synthesizes the cluster into a coherent profile. Decision: ADD, IGNORE, or UPDATE.
- **Relevant:** The clustering-before-consolidation pattern prevents redundant or near-duplicate memories from accumulating without doing a full cross-product comparison.

### Memoria (arXiv:2512.12686, 2025)
- URL: https://arxiv.org/html/2512.12686v1
- Mechanism: Knowledge graph with exponential decay weighting. Conflict resolution is implicit: newer triplets receive higher weights through temporal decay, so contradictions are resolved by recency at retrieval time rather than by cleanup at write time.
- **Relevant as a contrast:** This approach avoids the cost of write-time conflict detection but produces a store that is coherent only in the soft sense (recent memories dominate) rather than the hard sense (conflicting memories are removed). For TeaParty's use case, where the proxy must reason about retrieved memories as evidence, soft-coherent stores create ambiguity: both old and new preferences are present, and the proxy cannot tell whether the old one was superseded or is still valid in some context.

---

## The Contradictory Retrieval Signal for TeaParty

The proxy's design (in `human-proxies.md`) already names "contradictory retrieval" as one of the three signals that trigger questioning. The research above gives concrete substance to what this means and how to implement it.

**What contradictory retrieval looks like in practice:**

The proxy retrieves memories relevant to the current decision context. Contradiction detection runs on the retrieved set — not the entire store (which would be expensive), just what was surfaced as relevant. This is the key constraint: detection runs at retrieval time, on a bounded candidate set (top-k), not as a global consistency check.

**Classification of the conflict (what to do with it):**

Following the taxonomy from the literature, when two retrieved memories conflict, the proxy should classify the cause:

1. **Recency gap + same context domain** → likely preference drift; prefer newer, note the superseded belief for compaction.
2. **Different context domains** → likely context sensitivity; retrieve both in the response, note the domain scope of each; no contradiction.
3. **Recent, same context domain, high confidence both** → likely genuine unresolved tension; escalate to the human.
4. **Low semantic similarity despite co-retrieval** → likely retrieval noise; discard the weaker match.

This classification does not require a separate ML model. A brief LLM prompt on the retrieved candidate pair can perform it reliably — this is exactly the LLM-as-judge pattern.

**The asymmetric confidence update:**

Following Hindsight's finding and consistent with TeaParty's existing asymmetric regret (3x correction weight), confirmed contradictions should decrease a belief's weight more than confirming evidence increases it. A preference that is contradicted by a newer observation should be demoted more aggressively than it was built up.

**Write-time vs. retrieval-time:**

The literature offers two architectural options:
- Write-time (Mem0, EgoMem, O-Mem): detect and resolve contradictions when new memories are written; the store stays coherent.
- Retrieval-time (Memoria): soft-resolve by recency weighting when memories are retrieved; the store accumulates all observations.

For TeaParty, write-time resolution is preferable for `proxy.md` (preferential, always-loaded store) because that store is small and coherence is critical — it directly shapes the proxy's behavior. Retrieval-time soft resolution may be acceptable for `proxy-tasks/` (task-based episodic memories) where domain-scoping is more important than eliminating old entries.

---

## Papers Cataloged

### Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory (Chhikara et al., 2025)
- **Venue:** arXiv:2504.19413 (preprint)
- **URL:** https://arxiv.org/abs/2504.19413
- **Key findings:**
  - Explicit contradiction-handling at write time: ADD, UPDATE, DELETE, SKIP classification by LLM.
  - Mem0g (graph variant) adds a dedicated Conflict Detector + LLM Update Resolver for graph memory.
  - "Latest truth wins" when a contradiction is detected.
  - 26% accuracy improvement over OpenAI Memory on LOCOMO; 91% lower latency vs. full-context.
- **Implications for TeaParty:** The ADD/UPDATE/DELETE/SKIP taxonomy is directly adoptable for proxy memory operations. The graph variant's separate Conflict Detector pattern is the right architecture for `proxy.md` compaction: detect → classify → resolve, not detect-and-ignore.

### Hindsight: Building Agent Memory that Retains, Recalls, and Reflects (2025)
- **Venue:** arXiv:2512.12818
- **URL:** https://arxiv.org/html/2512.12818v1
- **Key findings:**
  - Separates objective facts, personal experiences, and opinions into distinct networks.
  - Opinions carry confidence scores with asymmetric update: supporting evidence `+α`, weakening `-α`, contradicting `-2α`.
  - Repeated contradictions reduce both confidence and eventually the belief text itself.
  - LLM-powered merging for biographical fact conflicts: newer wins, non-conflicting details appended.
- **Implications for TeaParty:** The confidence-decay-under-contradiction rule is directly applicable to the proxy's preference memory. Proxy memories that are contradicted multiple times should lose weight faster than they were gained — this is the memory-system analog of the 3x correction asymmetry in the confidence model.

### EgoMem: Lifelong Memory Agent for Full-Duplex Omnimodal Models (2025)
- **Venue:** arXiv:2509.11914
- **URL:** https://arxiv.org/html/2509.11914
- **Key findings:**
  - Memory Update Agent: an external LLM component prompted to identify conflicts and update structured user profiles.
  - Achieves 87%+ fact-consistency in personalized dialogs; >98% F1 on episodic trigger evaluation.
  - Conflict resolution via periodic online or offline memory consolidation (not only at write time).
  - Asynchronous to main dialog — memory updates run in background.
- **Implications for TeaParty:** The asynchronous update architecture is well-suited to TeaParty's post-session pipeline. Conflict consolidation does not need to run during the proxy's active dialog — it can run as a post-session compaction step, consistent with how TeaParty already handles `_try_compact()` after institutional writes.

### O-Mem: Omni Memory System for Personalized, Long-Horizon, Self-Evolving Agents (2025)
- **Venue:** arXiv:2511.13593
- **URL:** https://arxiv.org/html/2511.13593v1
- **Key findings:**
  - LLM-augmented nearest-neighbor clustering for persona attributes.
  - Within-cluster LLM consolidation synthesizes conflicting attributes into coherent profiles.
  - Decision taxonomy for new attributes: ADD, IGNORE, UPDATE.
  - Prevents redundant/conflicting accumulation without requiring full cross-product comparison.
- **Implications for TeaParty:** The clustering-before-consolidation pattern is more efficient than comparing every new memory to every existing one. For the proxy's `proxy-tasks/` store (potentially large), clustering related memories before consolidating them is the right architecture.

### Memoria: A Scalable Agentic Memory Framework for Personalized Conversational AI (2025)
- **Venue:** arXiv:2512.12686
- **URL:** https://arxiv.org/html/2512.12686v1
- **Key findings:**
  - Knowledge graph with exponential decay weighting; conflict resolution is implicit via recency priority.
  - Newer triplets receive higher weights; conflicting preferences are resolved at retrieval time, not write time.
  - Effective for preference drift scenarios; less effective when old preferences are still valid in their original context.
- **Implications for TeaParty:** A contrast to explicit write-time resolution. Useful for task-based episodic stores where the cost of write-time consolidation would be high, but not suitable for `proxy.md` where the proxy must reason about specific preferences rather than blending them.

### MemBench: Towards More Comprehensive Evaluation on the Memory of LLM-Based Agents (Tan et al., 2025)
- **Venue:** ACL Findings 2025 / arXiv:2506.21605
- **URL:** https://arxiv.org/abs/2506.21605 / https://aclanthology.org/2025.findings-acl.989/
- **Key findings:**
  - Evaluates: information extraction, multi-hop reasoning, knowledge updating, preference following, temporal reasoning.
  - Knowledge updating tests whether agents handle contradictory information when a prior fact is overridden.
  - Most memory systems show significant weakness on knowledge updating tasks; retrieval is better-developed than update.
  - Preference following tests higher-order inference from accumulated observations, not just verbatim recall.
- **Implications for TeaParty:** If TeaParty's proxy memory is ever benchmarked, MemBench's knowledge-updating and preference-following tasks are the right tests. The finding that knowledge updating is the weak link in current systems is consistent with the absence of explicit contradiction detection in early LLM memory implementations — this is an unsolved problem, not a solved one.

### Memory Management and Contextual Consistency for Long-Running Low-Code Agents (Xu, 2025)
- **Venue:** arXiv:2509.25250
- **URL:** https://arxiv.org/abs/2509.25250
- **Key findings:**
  - Proposes hybrid memory with active contradiction detection running during memory accumulation.
  - Demonstrates that unmanaged memory growth causes systematic performance degradation over time.
  - Active contradiction detection improves task completion rates compared to passive approaches.
  - Human-inspired selective forgetting strategies balance context freshness with historical accuracy.
- **Implications for TeaParty:** Direct empirical support for why contradiction detection must be active rather than passive. Passive accumulation (just retrieve and let the LLM sort it out) degrades performance as the store grows.

### Dialogue Natural Language Inference (Welleck et al., ACL 2019)
- **Venue:** ACL 2019 / arXiv:1811.00671
- **URL:** https://ar5iv.labs.arxiv.org/html/1811.00671
- **Key findings:**
  - NLI applied to dialogue persona consistency: an NLI model detects when a new utterance contradicts an established persona statement.
  - Re-ranking utterances using NLI contradiction scores reduces persona inconsistencies in deployed chatbots.
  - Created the Dialogue NLI dataset (DNLI) for this task — premise/hypothesis pairs from persona-based dialogue.
- **Implications for TeaParty:** This is the foundational paper for using NLI as a consistency mechanism. While LLM-as-judge has superseded dedicated NLI models in deployed systems, the framing — treating memory entries as "persona premises" and new observations as "hypotheses" to be checked against them — is directly applicable to proxy preference memory.

---

## Summary: What TeaParty Should Do

The literature supports a two-stage contradiction handling design for the proxy:

**Stage 1: Retrieval-time flagging.** When the proxy retrieves memories for a decision, run a brief LLM prompt over the retrieved candidate set (top-k, typically 5-10 entries) to classify any pairs as conflicting. This is inexpensive because it runs on a small retrieved set, not the full store. The output is a flag: "no conflict," "suspected preference drift," "suspected context sensitivity," or "confirmed unresolved tension."

- No conflict → proceed.
- Suspected preference drift → apply recency tiebreaker; schedule the superseded memory for soft-deletion or demotion at next compaction.
- Suspected context sensitivity → annotate both memories with their inferred scope; use both in proxy response.
- Confirmed unresolved tension → escalate to human; this is one of the three known conditions that warrant questioning.

**Stage 2: Write-time consolidation (post-session).** After each session, run a compaction pass on `proxy.md` (preferential store) using the O-Mem/Mem0 pattern: cluster recent observations with existing entries, present conflicting pairs to an LLM, apply ADD/UPDATE/DELETE/SKIP. This keeps the always-loaded `proxy.md` coherent and compact. For `proxy-tasks/` (retrieved on demand, larger), use softer recency weighting (Memoria pattern) rather than explicit consolidation, except when a retrieval-time flag identifies a conflict that warrants explicit resolution.

The asymmetric confidence rule from Hindsight (contradictions reduce confidence by `2α`, support increases by `α`) is the right decay rule for both stages. It is consistent with the proxy's existing 3x correction asymmetry and has theoretical grounding in both Hindsight's implementation and the regret asymmetry literature.

**What remains unsolved:** No paper in this review provides a method for reliably distinguishing preference drift from context sensitivity without asking the human. The distinction requires knowing whether the two contexts (old and new) are the same or different, which requires domain knowledge the system may not have. The safest default when the proxy cannot classify a conflict type is to treat it as "suspected context sensitivity" (preserve both with scope annotations) rather than preference drift (discard the older), because falsely discarding valid context-specific knowledge is harder to recover from than preserving a possibly-outdated entry.
