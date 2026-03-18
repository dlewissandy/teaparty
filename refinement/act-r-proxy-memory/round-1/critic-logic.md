# Logical Review — Round 1

## Contradictions

### 1. Retrieval-as-reinforcement creates a self-fulfilling retrieval loop that the document claims to prevent

The document explicitly removes the REINFORCE step to prevent "the rich-get-richer feedback loop where already-active chunks accumulate traces from every gate regardless of relevance" (act-r-proxy-memory.md, line 181). Yet act-r-proxy-mapping.md (line 72) states: "When the proxy retrieves this chunk while making a decision, the retrieval itself reinforces the memory." The top-k retrieved chunks at each gate receive traces, boosting their activation for the next gate. Chunks that are retrieved once gain activation advantage, making them more likely to be retrieved again, which gives them another trace, and so on. This is the same rich-get-richer dynamic the REINFORCE removal was designed to prevent — it just operates through the retrieval path instead of the working-memory path. The document acknowledges and blocks one reinforcement channel while leaving an identical one open.

### 2. "Dialog is how quality is maintained" vs. autonomous action without dialog

The root document (act-r-proxy-memory.md, line 29) asserts: "The dialog is how quality is maintained. Skipping it because the trend is positive is rubber-stamping." This is stated as a categorical claim about the necessity of dialog for quality. Yet the same document (line 39) permits "autonomous proxy action (without escalation to the human) when the proxy has demonstrably inspected the artifact." The sensorium document (act-r-proxy-sensorium.md, line 165-167) elaborates that "the proxy has earned the right to act autonomously" when the prior is specific enough that "the posterior rarely diverges."

The document's defense is that "the dialog happened inside the proxy's reasoning" (sensorium, line 167). But this redefines "dialog" from its meaning on line 29 (a conversation between proxy and human where the human's participation maintains quality) to something that happens entirely within the proxy's internal process. If internal-only reasoning counts as "dialog," then the EMA-based system also has "dialog" — the proxy internally checked its confidence. The distinction the document draws between the two systems depends on "dialog" meaning different things in the critique and the defense.

### 3. EMA "does not directly alter per-gate decisions" vs. EMA trend information "does flow into the proxy's decisions"

In act-r-proxy-mapping.md (line 179), two claims appear in adjacent sentences: "EMA trend information does flow into the proxy's decisions indirectly" and "EMA may also trigger operational actions... even though it does not directly alter per-gate decisions." The first claim establishes that EMA affects decisions (through the indirect mechanism of producing correction chunks). The second claims it does not. The qualifier "directly" is doing all the work, but the document never defines the boundary between direct and indirect influence. If correction chunks produced by EMA-detected degradation bias the proxy toward skepticism, EMA is influencing per-gate decisions — the indirection doesn't change the causal relationship.

### 4. Noise is both retrieval exploration and composite ranking noise

In act-r.md (line 103), noise is described as enabling "occasional exploration of less-active memories." In act-r-proxy-mapping.md (line 131, 137), noise appears in the composite score formula: `composite = activation_weight * normalize(B) + semantic_weight * cosine_avg + noise`. The noise term is added to the composite (which includes both activation and semantic components), not to activation alone. But the ACT-R motivation for noise is about activation-level stochasticity in retrieval — the probability that a chunk near threshold gets retrieved despite low activation. Adding noise to a composite score that includes semantic similarity changes the semantics: it now randomly perturbs the relevance ranking, not just the accessibility filter. The document uses ACT-R's justification for noise (activation-level exploration) while applying it to a different quantity (composite ranking).

## Non Sequiturs

### 1. "Corrections carry more specific associations than approvals" does not follow from text specificity

Act-r-proxy-mapping.md (line 187) argues: "Corrections carry more specific associations than approvals because error-describing text ('missing rollback strategy for database migration') is inherently more targeted than success-confirming text ('approved')." The conclusion is about embedding specificity (retrieval precision), but the premise is about text length and descriptiveness. More descriptive text does not necessarily produce more discriminating embeddings — long, detailed text can produce embeddings that are close to the centroid of many topics, while short specific text can produce highly distinctive embeddings. The relationship between text specificity and embedding discriminability is an empirical property of the embedding model, not a logical entailment.

### 2. Prior-posterior agreement as evidence of "genuine understanding"

Act-r-proxy-memory.md (line 39) claims the proxy's "prior-posterior agreement reflects genuine understanding — not pattern-matching on a scalar." But prior-posterior agreement means the proxy predicted the same action before and after seeing the artifact. This is evidence of prediction accuracy, not understanding. A lookup table that memorizes (state, task_type) -> action would also show prior-posterior agreement with zero understanding. The document conflates predictive accuracy with cognitive fidelity. The sensorium document makes the stronger argument that two-pass prediction demonstrates the proxy "was looking at the right things," but this is about the mechanism (did the proxy examine the artifact?), not about agreement (did the prediction change?). Agreement is the *absence* of the signal that demonstrates inspection.

### 3. Cold start produces "richer interaction data" therefore "memory populates faster"

Act-r-proxy-mapping.md (line 169) argues: "The new system generates richer interaction data per gate (questions, responses, reasoning, structured chunks with embeddings) compared to a single binary outcome update, which means the memory populates faster in terms of information per interaction." The premise is about data richness per interaction. The conclusion is about population speed. But richer data per chunk doesn't mean the memory becomes useful faster — it means each chunk is larger. Whether the proxy reaches useful retrieval quality in fewer interactions depends on whether the additional data dimensions actually improve retrieval, which is the very thing the ablations are designed to test. The conclusion assumes the answer to an open question.

## Unstated Assumptions

### 1. The LLM's reasoning over retrieved chunks produces behavior that approximates the human's behavior

The entire architecture assumes that if you give an LLM the right memories (selected by ACT-R), it will generate dialog that resembles what the human would say. This is never argued for — it's the foundational assumption. The memory system selects *what* the LLM sees; the LLM determines *what it does* with that input. If the LLM's reasoning over memories doesn't approximate human reasoning over the same memories, the entire system fails regardless of retrieval quality. The document optimizes the retrieval pipeline exhaustively while taking the reasoning step on faith.

### 2. The proxy's predictions and the human's decisions occupy the same action space

The chunk schema uses a shared vocabulary: {approve, correct, escalate, withdraw} for proxy predictions and human responses. The evaluation metrics compare them directly (action match rate). This assumes the human's actual decision-making maps cleanly onto these categories. If the human sometimes does things that don't fit — partial approval with caveats, corrections that are really questions, escalations that are really deferrals — the match rate becomes a measure of categorical fit, not predictive accuracy.

### 3. Embedding cosine similarity is a valid proxy for the semantic relationships that matter for retrieval

The substitution of vector embeddings for ACT-R's symbolic spreading activation is justified by citing Honda et al. (2025) and Meghdadi et al. (2026). But those works validate embeddings as substitutes for *association strength* in specific tasks (agent memory retrieval and lexical decision). Whether embedding similarity captures the specific associations that matter for *predicting a particular human's gate decisions* — which is a much narrower and more idiosyncratic task — is assumed, not established.

### 4. The interaction counter is a valid unit of subjective time for ACT-R decay

The document argues that interaction-based time is better than wall-clock time for agent systems (act-r.md, "Interactions, Not Seconds"). The argument is sound for the specific case of idle-time decay. But it assumes all interactions are equivalent units of subjective time: a brief "approve" interaction and a 20-turn discussion both advance the counter by 1. In ACT-R's original formulation with seconds, a longer interaction naturally occupies more time, producing more realistic decay patterns for temporally extended events. The interaction counter flattens temporal extent — a 5-second approval and a 30-minute discussion are the same "distance" from the next interaction. Whether this matters depends on whether temporal extent correlates with memory relevance in this domain, which is neither argued nor tested.

## Assessment

The document set is logically coherent in its broad structure — the motivation is sound, the ACT-R adaptation is reasonable, and the separation of concerns (memory vs. monitoring) is clean. The logical weaknesses are concentrated in three areas:

1. **Equivocation on "dialog."** The document's central argument (dialog is essential for quality) is undermined by its own autonomy mechanism (the proxy can skip dialog when confident). The defense depends on redefining dialog to include internal-only reasoning, which collapses the distinction the document draws between the new and old systems.

2. **Conflation of prediction accuracy with cognitive fidelity.** Multiple arguments treat "the proxy predicted correctly" as evidence of "the proxy understands the human." These are different claims, and the gap between them is exactly where the system could fail silently.

3. **Retrieval-reinforcement loop.** The document carefully argues against one reinforcement path (working-memory presence) while leaving an identical one open (retrieval). This isn't a minor oversight — it's a contradiction between the stated design principle and the implemented mechanism.

The document is structurally sound but has load-bearing equivocations.
