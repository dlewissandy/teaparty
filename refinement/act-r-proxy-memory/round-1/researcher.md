# Research Findings — Round 1

## Concern: Noise parameter s = 0.25 claimed as standard (fact-check: incorrect)

**Finding:** The ACT-R `:ans` (activation noise) parameter has a default of NIL (disabled). When enabled in the Unit 4 tutorial's paired-associate model, the value used is **0.5**, not 0.25. The tutorial explicitly sets `:ans 0.5` alongside `:rt -2`, `:lf 0.35`, and `:bll 0.5`. The value 0.25 does appear in some published ACT-R models (e.g., the Julia ACTRModels package documentation shows `s=0.20`), so it is within the range of values used in practice — but calling it "the standard value" is incorrect. There is no single standard; the most prominent tutorial example uses 0.5.

**Sources:**
- [ACT-R Unit 4 Tutorial](http://act-r.psy.cmu.edu/wordpress/wp-content/themes/ACT-R/tutorials/unit4.htm) — uses `:ans 0.5`
- [ACT-R 7.30+ Reference Manual](http://act-r.psy.cmu.edu/actr7.x/reference-manual.pdf) — default is NIL
- [ACTRModels.jl documentation](https://docs.juliahub.com/General/ACTRModels/stable/) — uses `s=0.20` in example

**Implication for document:** The act-r.md table should not claim s = 0.25 as the "standard value." Options: (a) state that s has no universal default and is model-dependent, with 0.25-0.5 being the typical range; (b) use 0.5 to match the most widely cited tutorial; or (c) note that the proxy design uses s = 0.25 as a design choice, not an ACT-R standard. The prose should also drop "standardly set to 0.25."

---

## Concern: Retrieval threshold tau = -0.5 claimed as standard (fact-check: incorrect)

**Finding:** The ACT-R `:rt` parameter default is NIL (disabled). When enabled in tutorials, the demonstrated values vary: the Unit 4 paired-associate model uses `:rt -2`; teaching notes from George Mason University reference `:rt 0` as a common starting point, "often set to -1." The value -0.5 appears in some model-fitting contexts but is not a canonical standard. No single "standard value" exists — the threshold is always model-dependent.

**Sources:**
- [ACT-R Unit 4 Tutorial](http://act-r.psy.cmu.edu/wordpress/wp-content/themes/ACT-R/tutorials/unit4.htm) — uses `:rt -2`
- [Notes on teaching ACT-R modeling, Bill Kennedy, George Mason University](http://act-r.psy.cmu.edu/wordpress/wp-content/uploads/2012/12/1006notesfortutorial.pdf) — references `:rt 0`, "often -1"
- [ACT-R 7.30+ Reference Manual](http://act-r.psy.cmu.edu/actr7.x/reference-manual.pdf) — default is NIL

**Implication for document:** The act-r.md table should not present tau = -0.5 as a standard value validated across hundreds of models. The document should acknowledge that tau is a design parameter chosen for the proxy system, not an ACT-R standard. The value -0.5 is a reasonable choice but is the document authors' choice.

---

## Concern: d = 0.5 may not transfer to sparse interaction regimes (HM concern #4)

**Finding:** The hiring manager's concern is legitimate and the document partially overstates the case. Anderson & Schooler (1991) analyzed three corpora: New York Times headlines, child-directed speech (CHILDES), and email. These are high-volume natural language corpora with thousands to tens of thousands of observations. The power-law with exponent near 0.5 was validated at that scale. Whether the same exponent produces useful forgetting curves with 50-200 total lifetime interactions is genuinely an open empirical question.

However, two points soften the concern: (1) The ACT-R decay equation with d = 0.5 has been used successfully in cognitive models of tasks with relatively few trials (paired-associate learning tasks in the Unit 4 tutorial involve tens of trials, not thousands). The equation's behavior at low trace counts is mathematically well-defined and produces reasonable activation curves — a chunk with 3 traces at recent intervals has activation ~0.7, which is clearly above any reasonable threshold. (2) The interaction-based time substitution means the relevant question is not "does d = 0.5 work with few events" but "does the power-law decay pattern hold for this kind of event." The document does not cite evidence that proxy gate interactions follow the same statistical patterns as word occurrences in newspapers.

The document treats d = 0.5 as settled. It is not settled for this use case — it is a principled starting point.

**Sources:**
- [Anderson & Schooler (1991)](https://journals.sagepub.com/doi/abs/10.1111/j.1467-9280.1991.tb00174.x) — original corpora analysis
- [ACT-R Unit 4 Tutorial](http://act-r.psy.cmu.edu/wordpress/wp-content/themes/ACT-R/tutorials/unit4.htm) — paired-associate model with d = 0.5 and modest trial counts
- [Schooler & Anderson (2017), "The Adaptive Nature of Memory"](http://act-r.psy.cmu.edu/wordpress/wp-content/uploads/2021/07/SchoolerAnderson2017.pdf) — subsequent validation work

**Implication for document:** The "Why d = 0.5?" section should acknowledge that the empirical basis comes from high-volume natural language corpora and that proxy interactions are a different statistical regime. The value is a principled default, not a validated parameter for this domain. The migration plan should include empirical calibration of d.

---

## Concern: Combined score mixes incompatible scales (HM concern #3)

**Finding:** The concern is technically correct and well-established in the information retrieval literature. Base-level activation B is unbounded (can range from negative infinity to positive infinity in theory; in practice, a chunk with 20 traces at recent intervals could have B around 2-3). Cosine similarity is bounded [-1, 1]. A naive weighted sum with equal weights will be dominated by whichever component has larger magnitude.

The generative agents paper (Park et al., 2023) — which uses a structurally similar weighted combination of recency, importance, and relevance — explicitly addresses this by normalizing all components to [0, 1] via min-max scaling before combining. This is the standard approach in hybrid retrieval systems.

ACT-R itself avoids this problem because spreading activation and base-level activation are on the same scale (both measured in log-odds of retrieval). The document's substitution of cosine similarity for spreading activation introduces the scale mismatch that ACT-R's original design does not have.

**Sources:**
- [Park et al. (2023), "Generative Agents: Interactive Simulacra of Human Behavior"](https://dl.acm.org/doi/fullHtml/10.1145/3586183.3606763) — normalizes recency, importance, relevance to [0,1] before combining
- [Result fusion and ranking strategies in hybrid search](https://apxml.com/courses/advanced-vector-search-llms/chapter-3-hybrid-search-approaches/result-fusion-ranking-strategies) — standard practice of normalizing scores to common scale
- [Normalizing cosine similarity for scoring](https://medium.com/@kswastik29/normalizing-cosine-similarity-for-scoring-a-practical-approach-8df5e3d41876)

**Implication for document:** The combined score formula needs a normalization step. Either: (a) normalize B to [0, 1] via min-max or sigmoid before combining, (b) use a learned weighting (as in recent Mix-of-Experts approaches), or (c) use rank-based fusion (RRF) instead of score-based combination. The document should acknowledge this is a known issue in hybrid retrieval and specify the normalization approach.

---

## Concern: Multi-dimensional embedding retrieval is underspecified (HM concern #2)

**Finding:** The approach of using multiple independent embeddings per chunk and averaging cosine similarities is not standard practice in the RAG/retrieval literature. The literature on multi-representation embeddings (e.g., BGE-M3) focuses on different *types* of representations (dense, sparse, multi-vector) for the same content, not independent embeddings of different semantic facets.

The closest precedent is the generative agents work (Park et al., 2023), which uses separate scores for recency, importance, and relevance — but these are fundamentally different signals (temporal, categorical, semantic), not multiple semantic embeddings of different content facets.

The document's claim that averaging cosine similarities across 5 dimensions is "the equivalent of low-fan spreading activation" is an analogy, not a demonstrated equivalence. In ACT-R, spreading activation is governed by the fan effect (Sj = S / n, where n is the number of associations), which produces mathematically specific behavior: chunks associated with fewer cues receive stronger activation. Averaging 5 cosine similarities does not produce the fan effect — a chunk that matches on 5 dimensions scores the same average as a chunk matching on 1, as long as the average similarity is equal. The intersection effect the document describes (matching on more dimensions = stronger) would require a product or minimum operation, not an average.

No published evaluation was found comparing 5 independent faceted embeddings against a single blended embedding for memory retrieval.

**Sources:**
- [BGE-M3 / Milvus blog on embedding selection](https://milvus.io/blog/how-to-choose-the-right-embedding-model-for-rag.md) — multi-representation approaches use dense+sparse+multi-vector, not faceted semantic dimensions
- [Park et al. (2023)](https://dl.acm.org/doi/fullHtml/10.1145/3586183.3606763) — separate signals, not faceted embeddings
- [Anderson & Lebiere (1998)](https://www.semanticscholar.org/paper/The-Atomic-Components-of-Thought-Anderson-Lebiere/084da26797ebaa448bab831eddabf50a96f4fe59) — fan effect in spreading activation (Sj = S/n)

**Implication for document:** The document should: (1) drop the claim that averaging cosine similarities is equivalent to low-fan spreading activation — it is not, mathematically; (2) acknowledge that 5-facet embedding retrieval is a novel design choice without published validation; (3) propose an explicit ablation comparing single-embedding vs. multi-embedding retrieval; (4) consider whether the aggregation function should be something other than average (e.g., weighted product, minimum, or sum) to produce the intersection behavior the design intends.

---

## Concern: "Activation-weighted embedding retrieval ... including Claude's own persistent memory" (fact-check: unverifiable)

**Finding:** Claude's persistent memory (as of March 2026) uses a file-based architecture: CLAUDE.md files loaded into context at conversation start, plus an auto-memory system that stores notes as text files. Memory retrieval uses the model's context window to find relevant information within pre-loaded text, or active search through conversation history. There is no public documentation describing activation-weighted embedding retrieval as Claude's memory mechanism. The architecture is described by Anthropic and community documentation as "transparent, file-based" and explicitly contrasted with "automated, black-box RAG systems."

The broader claim that activation-weighted embedding retrieval is "the pattern underlying modern AI memory systems" has some support. The Park et al. (2023) generative agents use a weighted combination of recency (exponential decay), importance, and relevance (cosine similarity). A 2024 HAI paper ("Human-Like Remembering and Forgetting in LLM Agents") explicitly combines ACT-R base-level activation with cosine similarity for LLM memory retrieval. A Frontiers paper integrates LLM embeddings into the ACT-R framework directly. So the pattern exists in the research literature — but calling it "the pattern underlying modern AI memory systems" overstates its prevalence, and attributing it to Claude is incorrect.

**Sources:**
- [Claude Code Memory Documentation](https://code.claude.com/docs/en/memory) — file-based CLAUDE.md architecture
- [Anthropic Memory Tool Documentation](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool) — text file storage in /memories directory
- [Park et al. (2023)](https://dl.acm.org/doi/fullHtml/10.1145/3586183.3606763) — weighted recency + importance + relevance
- [Human-Like Remembering and Forgetting in LLM Agents (HAI 2024)](https://dl.acm.org/doi/10.1145/3765766.3765803) — ACT-R activation + cosine similarity for LLM agents
- [Integrating language model embeddings into ACT-R (Frontiers 2026)](https://www.frontiersin.org/journals/language-sciences/articles/10.3389/flang.2026.1721326/full) — embedding integration into ACT-R

**Implication for document:** Remove the claim about Claude's persistent memory. The sentence can be revised to cite the actual precedents: Park et al.'s generative agents and the 2024 HAI paper on ACT-R-inspired LLM memory. Also soften "the pattern underlying modern AI memory systems" to something like "a pattern with growing adoption in AI memory research."

---

## Concern: "The approach is deployed at scale" (fact-check: unverifiable)

**Finding:** No evidence was found of a production deployment using the specific hybrid of ACT-R activation + embedding cosine similarity at scale. Park et al.'s generative agents are a research demo (25 agents in a sandbox), not a production system. The HAI 2024 paper is a research architecture. The Frontiers 2026 paper is academic. The claim is not supported by any public source.

**Sources:** Same as above.

**Implication for document:** Remove or qualify. If the intent is to say "the components (embedding retrieval, decay-based recency) are individually deployed at scale," that is defensible — but the specific combination described in the document is not demonstrated at production scale in any public system.

---

## Concern: LLM temperature 0 non-determinism contaminates two-pass delta (HM concern #6)

**Finding:** The hiring manager's concern is well-supported by extensive evidence. Temperature 0 does NOT guarantee deterministic LLM outputs. Sources of non-determinism include:

1. **Floating-point precision:** GPU parallel operations use finite-precision arithmetic where operation order affects rounding, and rounding errors cascade through transformer layers.
2. **GPU parallelism:** Race conditions in parallel computation cause different operation ordering across runs.
3. **Batch effects:** In mixture-of-experts models, other sequences in the same batch influence routing decisions.
4. **Provider-side variation:** No major LLM provider currently guarantees fully deterministic outputs.

Multiple dedicated analyses confirm this: a 2024 arXiv paper ("Non-Determinism of 'Deterministic' LLM Settings," arXiv:2408.04667) directly studies this phenomenon. Multiple engineering blog posts document reproducible variation at temperature 0.

This means the two-pass delta (prior vs. posterior) will contain noise from prompt sensitivity and non-determinism that is unrelated to the artifact's influence. The signal-to-noise ratio of the delta is an empirical question that the document does not address.

**Sources:**
- [Non-Determinism of "Deterministic" LLM Settings (arXiv:2408.04667)](https://arxiv.org/html/2408.04667v5)
- [Does Temperature 0 Guarantee Deterministic LLM Outputs?](https://www.vincentschmalbach.com/does-temperature-0-guarantee-deterministic-llm-outputs/)
- [Zero Temperature Randomness in LLMs](https://martynassubonis.substack.com/p/zero-temperature-randomness-in-llms)
- [Why Temperature=0 Doesn't Guarantee Determinism in LLMs](https://mbrenndoerfer.com/writing/why-llms-are-not-deterministic)

**Implication for document:** The document should acknowledge that the prior-posterior delta is a noisy signal. At minimum, note that (a) temperature 0 does not guarantee deterministic outputs, (b) prompt structure differences between Pass 1 and Pass 2 are a confound, and (c) the delta should be interpreted as an approximate salience signal, not a precise measurement. Consider whether the binary surprise trigger (action changed vs. didn't) is more robust than continuous delta measures, precisely because it thresholds away small noise-driven variations.

---

## Concern: Surprise is binary but attention is not (HM concern #7)

**Finding:** The concern is architecturally valid. The surprise mechanism only triggers when `prior.action != posterior.action`. This means high-confidence-to-low-confidence shifts (same action, different certainty) produce no surprise signal — no salient percepts are extracted, no salience embedding is stored. The document stores confidence values but never uses them in the surprise calculation.

However, there is a counterargument from the Bayesian surprise literature. Itti & Baldi (2009, "Bayesian Surprise Attracts Human Attention") define surprise as KL divergence between prior and posterior distributions, which is continuous and captures shifts in confidence, not just categorical changes. The document's binary surprise is a simplification that discards information. The AutoDiscovery system (Allen AI, NeurIPS 2025) also uses continuous KL divergence, not binary category change.

The document's own two-pass design already produces the data needed for continuous surprise (prior confidence, posterior confidence, prior action, posterior action). Implementing continuous surprise using these fields would be straightforward and would capture the information the binary mechanism misses.

**Sources:**
- [Itti & Baldi (2009), "Bayesian surprise attracts human attention"](https://pubmed.ncbi.nlm.nih.gov/18834898/) — continuous KL-divergence surprise
- [AutoDiscovery (Allen AI, NeurIPS 2025)](https://arxiv.org/html/2507.00310v2) — continuous Bayesian surprise for hypothesis exploration
- [Of Bits and Wows: A Bayesian Theory of Surprise (Baldi & Itti, 2010)](https://pmc.ncbi.nlm.nih.gov/articles/PMC2860069/) — formal theory

**Implication for document:** The document should either: (a) implement continuous surprise magnitude (e.g., based on confidence delta + action change), triggering percept extraction at different levels of detail based on magnitude; or (b) explicitly acknowledge the information loss from binary surprise and justify why the simplification is acceptable for this use case (e.g., robustness to noise from concern #6 — binary thresholding filters out noise-driven small shifts).

---

## Concern: AutoDiscovery uses Bayesian surprise for "hypothesis ranking" (fact-check: approximate)

**Finding:** The fact-checker flagged this as an approximation rather than an error. AutoDiscovery uses Bayesian surprise (KL divergence between posterior and prior Beta distributions) as a scoring signal within a Monte Carlo Tree Search (MCTS) procedure to balance exploration and exploitation in the hypothesis search space. The system *prioritizes* which hypotheses to explore next, not *ranks* a fixed set. However, within MCTS, surprise scores do rank candidate hypotheses for selection, so "ranking" is not wrong — it is imprecise. The structural analogy (both systems use prior-posterior divergence as a salience signal) is sound.

**Sources:**
- [AutoDiscovery (arXiv:2507.00310)](https://arxiv.org/html/2507.00310v2) — MCTS with Bayesian surprise for exploration policy
- [AutoDiscovery GitHub](https://github.com/allenai/autodiscovery) — official implementation

**Implication for document:** Minor wording fix. Change "hypothesis ranking" to "hypothesis prioritization" or "guiding hypothesis exploration." The analogy itself is valid.

---

## Concern: Cost model arithmetic errors (fact-check: G=10 and G=20 totals incorrect)

**Finding:** The fact-checker's arithmetic is correct. Using the document's own formula:

**G=10:** 7,000 + (19 x 700) + (20 x 2,000) + (0.2 x 10 x 2 x 500) = 7,000 + 13,300 + 40,000 + 2,000 = **62,300** (document states 62,600; error of 300)

**G=20:** 7,000 + (39 x 700) + (40 x 2,000) + (0.2 x 20 x 2 x 500) = 7,000 + 27,300 + 80,000 + 4,000 = **118,300** (document states 119,200; error of 900)

The savings percentages are approximately correct under either total (30-31% for G=10, 34% for G=20).

**Sources:** Verified by direct computation from the document's own formula and parameters.

**Implication for document:** Correct the G=10 total to 62,300 and the G=20 total to 118,300. The savings percentages can remain as stated (30% and 34% are reasonable roundings).

---

## Concern: "~376 chunks" at 500 tokens/chunk in 200K context (fact-check: arithmetic unclear)

**Finding:** 200,000 / 500 = 400, not 376. The value 376 is consistent with reserving ~12,000 tokens for system prompt and gate content (188,000 / 500 = 376), which is a reasonable assumption given the document's own cost model uses P = 2,000 for system prompt and C = 2,000 for gate content, plus overhead. But the basis for 376 is unstated.

**Sources:** Verified by direct computation.

**Implication for document:** Either state the assumption explicitly ("reserving ~12,000 tokens for system prompt and gate content, the practical capacity is ~376 chunks") or round to the simpler "~400 chunks" with a note that actual capacity depends on prompt overhead.

---

## Concern: Prompt cache cross-process sharing via `claude -p` (fact-check: partially verified)

**Finding:** Anthropic's prompt caching documentation confirms that caches are shared at the organization level and that identical prefixes across separate API calls do hit the cache. However, the specific behavior of the `claude -p` CLI is not documented with respect to caching. The CLI may add per-call metadata (timestamps, session identifiers, tool definitions) that break prefix matching. The document already acknowledges this in its "Verification Needed" section, which is appropriate. No additional evidence was found to resolve the uncertainty.

**Sources:**
- [Anthropic Prompt Caching Documentation](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) — organization-level sharing, 100% identical prefix required for cache hit
- [Anthropic Pricing](https://platform.claude.com/docs/en/about-claude/pricing) — 0.1x rate for cache reads confirmed

**Implication for document:** The "Verification Needed" section is already correctly scoped. No change needed beyond what the document already acknowledges.

---

## Concern: "Explicit reinforcement" is vague and dangerous (HM concern #11)

**Finding:** No research was needed — this is a design specification question, not a factual claim. However, the concern is well-formulated. Trace creation rule 3 says chunks get reinforced when "a new interaction produces a similar outcome to a past one." The similarity criterion is unspecified. If implemented as exact match on (state, outcome) — e.g., every PLAN_ASSERT approval reinforces all prior PLAN_ASSERT approval chunks — the result would be runaway reinforcement of the most common interaction pattern.

In ACT-R proper, reinforcement only occurs through explicit retrieval (the chunk must be actively recalled to get a trace). There is no "implicit reinforcement by outcome similarity" in the standard ACT-R model. Rule 3 is a design extension, not an ACT-R mechanism, and it introduces a feedback loop that ACT-R's original design avoids.

**Sources:**
- [Anderson & Lebiere (1998)](https://www.semanticscholar.org/paper/The-Atomic-Components-of-Thought-Anderson-Lebiere/084da26797ebaa448bab831eddabf50a96f4fe59) — traces created by access (creation, retrieval), not by outcome similarity
- [ACT-R Unit 4 Tutorial](http://act-r.psy.cmu.edu/wordpress/wp-content/themes/ACT-R/tutorials/unit4.htm) — base-level learning via access traces

**Implication for document:** Rule 3 should either be removed (rely on rules 1 and 2, which match standard ACT-R), or the similarity criterion must be fully specified with analysis of the feedback dynamics. If kept, the document should explicitly note this is a departure from ACT-R and explain why the feedback loop is desirable.

---

## New Evidence Discovered

### 1. Direct precedent: ACT-R + embedding for LLM agents

Two recent papers directly implement the pattern the document proposes — combining ACT-R base-level activation with embedding cosine similarity for LLM agent memory:

- **"Human-Like Remembering and Forgetting in LLM Agents: An ACT-R-Inspired Memory Architecture"** (HAI 2024). Stores utterances as memory chunks, computes total activation as base-level activation + cosine similarity, uses this for context-sensitive temporally dynamic retrieval. Published at the 13th International Conference on Human-Agent Interaction.
  - Source: [ACM Digital Library](https://dl.acm.org/doi/10.1145/3765766.3765803)

- **"Integrating language model embeddings into the ACT-R cognitive modeling framework"** (Frontiers in Language Sciences, 2026). Replaces hand-coded associations with cosine similarity from Word2Vec and BERT embeddings while retaining ACT-R's interpretability.
  - Source: [Frontiers](https://www.frontiersin.org/journals/language-sciences/articles/10.3389/flang.2026.1721326/full)

- **"Enhancing memory retrieval in generative agents through LLM-trained cross attention networks"** (Frontiers in Psychology, 2025). Proposes improvements to the Park et al. generative agents memory using learned retrieval weights.
  - Source: [Frontiers](https://www.frontiersin.org/journals/psychology/articles/10.3389/fpsyg.2025.1591618/full)

These are direct precedents the document should cite. The HAI 2024 paper in particular validates the core architectural pattern (ACT-R activation + cosine similarity) and would strengthen the document's case while replacing the unverifiable claims about Claude's memory.

### 2. Park et al. (2023) normalization approach

The generative agents paper (Park et al., 2023) faces the same score combination problem (recency, importance, relevance on different scales) and solves it with min-max normalization to [0, 1] before weighted combination. This is the most directly applicable precedent for the document's combined retrieval score and provides a ready-made solution for concern #3.

### 3. ActMem: Bridging Memory Retrieval and Reasoning (2026)

A March 2026 paper "ActMem: Bridging the Gap Between Memory Retrieval and Reasoning in LLM Agents" was found during search. This appears to be very recent work at the intersection of activation-based memory and LLM reasoning, though detailed content was not accessible.
  - Source: [arXiv](https://arxiv.org/html/2603.00026)
