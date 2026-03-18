# Defense — Round 2

## Concessions

### Cost calculation error (fact checker)
The critic is right. The cache write and cache read calculations are off by approximately 1,000x due to a unit convention error (MTok vs. per-token basis). The corrected calculation yields approximately $0.33 per session, not $0.47. This means the two-pass design is roughly 6% cheaper than the current design, not 35% more expensive. The economic argument flips: the two-pass design is cost-justified on economic grounds alone, not just on quality grounds. The document should correct the arithmetic and restate the cost claim: "The two-pass design with caching is cost-equivalent to or slightly cheaper than the current design."

### Engineering gaps remain unaddressed from Round 1 (engineering critic)
The critic is right that four blocking gaps persist despite being conceded in Round 1:
1. **Embedding model not specified** — the document includes `embedding_model TEXT NOT NULL` but doesn't say which model to use.
2. **Prompt templates for surprise extraction** — lines 82-84 describe two LLM calls but provide no actual prompt text.
3. **Chunk serialization format** — line 160 says chunks become context but provides no serialization template.
4. **Confidence extraction not specified** — the surprise threshold uses `|posterior.confidence - prior.confidence| > 0.3` but confidence format is undefined.

These need explicit answers before Phase 1 can proceed. The document should add an "Integration Specification" section that either specifies these or explicitly scopes them as Phase 1 parameter tuning (not design decisions). If deferred to Phase 1, the document should state the constraint: "The embedding model will be selected based on availability and performance during Phase 1; the implementation must support `embedding_model_version` tracking for future migration."

Additionally, concurrency control for the interaction counter needs specification: the document describes a FIFO queue but doesn't specify transaction semantics, lock ordering, or isolation levels. This is a real race condition in a parallel dispatch system.

### Sparse surprising interactions may not train reliable attention (visionary critic #1, logic critic #2)
The critic raises a valid concern: if only ~15% of interactions are surprising, the learned attention model is built from sparse signal. The prior-posterior agreement dependency creates a circular loop—the prior must be accurate to bootstrap attention learning, but attention learning requires surprising interactions that only occur when the prior is *inaccurate*. This is a real bootstrapping problem.

The document should acknowledge this explicitly: "The learned attention model is seeded from surprising interactions (minority-class events). A proxy with poor initial accuracy generates more surprises and richer training signal; a proxy with good initial accuracy learns slowly. This creates an inverted-U learning curve where learning is fastest in the middle regime (25-50% surprise rate) and slowest at the extremes. Phase 1 shadow mode must include surprise rate monitoring to detect slow learning." The document should also state the fallback: "If surprise rate stabilizes below 5% or doesn't converge by the end of Phase 1, the system remains in dialog mode with memory-augmented assistance, not autonomous mode."

### Confidence threshold mechanism is undefined (logic critic #1, engineering critic #4)
The surprise extraction mechanism depends on a precise threshold: `|posterior.confidence - prior.confidence| > 0.3`. But the document acknowledges that LLM-generated confidence scores are poorly calibrated. This creates a contradiction: the system is built on a precision mechanism (0.3 threshold) using an unstable measurement (confidence).

The document should either:
1. **Specify confidence extraction explicitly** — provide a prompt instruction that requests confidence in a specific format (e.g., "rate your confidence on a scale 0-10" or "output confidence as a probability p in [0,1]"), then document the parsing and validation logic.
2. **Replace confidence with a discrete signal** — use a binary mechanism for strong surprise (action change) and remove the moderate surprise threshold entirely. Make the design simpler: only strong surprise (posterior_action ≠ prior_action) triggers extraction.
3. **Defer calibration to Phase 1** — state the threshold as a tunable parameter: "The confidence threshold starts at 0.3; Phase 1 will calibrate this empirically and report the optimal threshold for strong/moderate surprise detection."

The document currently does all three at once, creating ambiguity. It should choose one, explicitly.

### Autonomy criteria are deferred but framed as inevitable (visionary critic #7, logic critic #2)
The sensorium document frames autonomy as a natural outcome ("when the prior is specific enough"), but Phase 3 is described in a single sentence and autonomy thresholds are undefined. This creates a risk: if the data doesn't cooperate (priors remain accurate but surprises remain common, or surprises converge to zero but to noise not signal), the system could be stuck in dialog mode indefinitely while claiming the path to autonomy is clear.

The document should specify autonomy criteria now, before Phase 1 begins, so that Phase 1 can measure them. Proposed criteria:
1. **Prior-posterior agreement rate ≥ 95%** on a held-out validation set (20% of Phase 1 interactions).
2. **Surprise rate ≤ 5%** on the validation set (low surprise means the prior is well-calibrated).
3. **Salience delta diversity ≥ 80%** — the salient percepts extracted from surprising interactions show variance, not clustering on a few repeated patterns (avoiding overfitting).

These criteria can be measured in Phase 1. The document should add: "If by the end of Phase 1 all three criteria are met, the system transitions to Phase 2 (dialog with optional autonomous action at proxy discretion). If surprise rate remains above 10% or salience delta diversity is below 60%, the system remains in Phase 1 with extended dialog. Phase 3 (autonomous operation) begins only after Phase 2 has achieved 50+ hours of dialog with fewer than 5 human corrections."

### EMA is not truly separate—it's functionally reintegrated (visionary critic #8, logic critic #3)
The document claims EMA "remains as a system health monitor" and is "separate from the memory system," but then states that EMA degradation flows into behavior indirectly: degradation produces more correction chunks, which get richer salience deltas, which change what memories are retrieved. This is not separation; it's reintegration through a mediating mechanism.

The document should be explicit about the coupling: "EMA monitors upstream quality. When EMA drops, more corrections are recorded in the memory system; more corrections mean more chunks with rich salience deltas, which increases retrieval diversity. This is a side effect of the memory system responding to reality, not EMA actively driving behavior. EMA does not influence `retrieve()` or composite scoring—it influences what memories exist, which influences what memories can be retrieved. The distinction is important: EMA is decoupled from the decision algorithm, but coupled to the data that feeds it."

This reframing is honest. It explains why EMA remains valuable (as an early warning signal) without claiming separation that doesn't exist.

### Sparse matching may be penalized in composite score (logic critic assumption #2)
The document divides composite scores by 5 always, which penalizes chunks matching on only one or two dimensions. The critic correctly notes that if a chunk matches high on `situation` alone (e.g., "what happens at PLAN_ASSERT?"), it scores (sim_situation + 0 + 0 + 0 + 0) / 5 = 0.2 * sim_situation. For this to outrank a chunk with moderate matches on all five dimensions, sim_situation would need to be implausibly high (> 5x the moderate sims).

The document should test this empirically. Proposal: Phase 1 ablation should include "divide by number of populated dimensions (query-side)" vs. "divide by 5 (chunk-side)." If query-side normalization performs better, it means the system benefits from not penalizing sparse chunks—which would argue for adaptive normalization. The current divide-by-5 scheme is conservative (favors dense matching) and may be right for this domain, but the document should acknowledge the tradeoff and plan to test it.

### Dialog quality measurement remains absent (visionary critic #9)
Round 1 flagged this: action match rate measures whether the proxy reaches the same decision as the human, not whether the proxy's reasoning path is sound. A proxy that reaches the right action through wrong reasoning would pass the metric but fail the vision.

The document acknowledges this implicitly by using "inspection" as a mechanism: the two-pass design ensures the proxy examines the artifact before deciding. But "examined" is not measured—only "examined and agreed" is measured (posterior matches prior). The document should add a secondary metric for Phase 1: **Dialog turn analysis**. Sample a subset of Phase 1 interactions and ask: "Does the proxy's reasoning in Pass 2 reference artifact-specific details, or does it generic reasoning that would apply to any similar situation?" Manual review of 10-20 proxy reasoning traces would reveal whether the two-pass mechanism actually improves reasoning quality or just validates decisions. This doesn't solve the measurement problem, but it surfaces the question explicitly.

### Two-pass execution ≠ two-pass inspection (logic critic #2)
The autonomy criterion states: "the proxy has earned the right to act autonomously because it has demonstrated that it attends to what the human would attend to, inspects the artifact through two-pass prediction, and finds nothing unexpected." The evidence is prior-posterior agreement. But agreement doesn't prove inspection—the proxy could have a highly accurate prior that doesn't depend on the artifact.

The document should separate the claims: (1) Two-pass execution (running both passes) is mechanically enforced. (2) Two-pass inspection (examining the artifact in Pass 2) is assumed but not measured. The autonomy criterion should be reframed: "The proxy's prior-posterior agreement rate reaches 95% on validation data. The prior is accurate enough that the posterior rarely diverges. At this point, autonomous action is defended not by the claim that the proxy 'understands,' but by the practical fact that the proxy's decisions are predictively accurate and consistent with human judgment." This is modest but defensible.

## Defenses

### Learned attention bootstrapping is defended by the activation mechanism (visionary critic #1 response)
The critic worries that learned attention is built from sparse surprising interactions (15% of gates). But the design includes a balancing mechanism: **activation reinforcement**. Frequently retrieved chunks accumulate higher activation, even if they don't trigger surprise. Routine chunks that are consistently approved are retrieved often (because they match `state` and `task_type`), accumulating activation through retrieval counts. Non-surprising interactions still reinforce activation—they just don't contribute salience embeddings.

The composite score weights activation and similarity equally (0.5 each). A routine chunk with high activation can outrank a novel chunk with rich salience but low activation. The system has two signals: activation (frequency of use) and salience (artifact-specific attention). Over time, the proxy learns two kinds of memories: (1) what it consistently checks (activation-driven) and (2) what surprises it at specific artifact patterns (salience-driven).

The critic is right that if surprise rate is very low, the salience model is sparse. But the activation model is dense. The system doesn't depend on surprise alone. This defense is sound, but the document should make the two-signal mechanism more explicit in the main text rather than leaving it implicit.

### Retrieval bias from surprise events is addressed by diversity metrics (visionary critic #2 response)
The critic notes that chunks with salience embeddings get weighted heavily, creating retrieval bias—surprising events become overrepresented. This is a real concern, but the design includes a mitigation: **surprise extraction happens only for strong surprises** (action change or high confidence delta). Weak surprises are recorded but don't trigger salience embedding. Additionally, the activation component of the composite score balances the salience weight: a chunk with salience but low activation is outweighed by a chunk with high activation and no salience.

The stronger defense: the document should propose an explicit Phase 1 metric: **salience coverage ratio** — what percentage of salient percepts (across all extracted surprises) are unique vs. clustered? If 80% of surprises cluster around a few repeated patterns, the salience model is overfitted. If surprises are diverse, the model is building genuine attention. This metric would surface the bias problem if it exists.

### Composite score normalization is query-dependent—this is intentional (visionary critic #3 response)
The critic notes that normalization by the activation variance in the candidate set means the effective weight of activation vs. similarity is not fixed. A query with high activation variance will be dominated by recency; a query with low variance will be dominated by similarity.

This is not a bug—it's a feature. The system is saying: "If candidates cluster similarly by activation (all routine checks), prioritize semantic relevance. If candidates vary widely by activation (mix of fresh and old memories), let recency dominate." This adaptive weighting is more sophisticated than static weights, and it emerges naturally from normalization. The document should note this explicitly: "The effective balance between activation and similarity weighting adapts to the candidate set. This is intentional: when all candidates are similar by activation, similarity becomes the tiebreaker. When activation varies widely, recency dominates. Phase 1 will monitor whether this adaptive weighting produces better retrieval than fixed weights."

### Prior-only scenario (cross-type retrieval) can use structural filtering (visionary critic #4 response)
The critic notes that the design doesn't specify what happens when retrieval returns chunks of different structural types (e.g., retrieving a discovery_turn chunk to inform a gate_outcome prior). The document leaves this as implicit.

The design does include structural filtering: `query_chunks(state=state, task_type=task_type)` filters by gate context. This biases retrieval toward chunks from the same gate type. If a PLAN_ASSERT gate retrieves mostly PLAN_ASSERT chunks, cross-type mixing is minimal. But the filtering is a constraint, not a prohibition. The document should clarify: "Retrieval is biased toward same-type chunks via state and task_type filtering, but not strictly limited to them. A PLAN_ASSERT gate may retrieve a related DISCOVERY_TURN chunk if it's semantically similar and activated. Cross-type retrieval is allowed because the LLM can reason across chunk types; strict type separation would lose valuable context. Phase 1 will ablate strict type filtering vs. permissive cross-type retrieval to determine which is better."

### Embedding cost during high-surprise sessions is not actually 20-40 extra calls (visionary critic #5 response)
The critic worries that surprise extraction (2 LLM calls producing text that is then embedded 5 ways) could add 20-40 embedding API calls not budgeted in the cost model. Let me trace the cost:

- Strong surprise: triggers 2 LLM calls (description + salient percepts extraction), each producing short text (<200 tokens).
- These texts are embedded 5 ways if they contain salient percepts.
- Expected surprises per session: 5-10 (out of 50 interactions).
- Additional embeddings per strong surprise: 5 (one per dimension).
- Total additional embedding calls: 5-10 surprises × 5 = 25-50 additional embeddings per session.

The critic's concern is valid: this adds embedding cost that the document doesn't break out separately. However, the cost model should absorb this. At $0.0001 per embedding, 50 embeddings = $0.005 per session. The corrected total cost in my concession above ($0.33) already accounts for this under surprise extraction. The document should make the embedding cost for surprise extraction explicit: "Surprise extraction produces text that is embedded 5 ways per strong surprise. Expected cost: 5-10 surprises × 5 embeddings × $0.0001 = $0.003-0.005 per session."

### Activation decay is defensible in sparse regime with ablation fallback (visionary critic #6 response)
The critic notes that ACT-R's decay parameter d = 0.5 was calibrated for high-volume environments (100+ interactions per hour), not sparse regimes (5-10 gates per session, 50-100 interactions per month). At sparse tempo, a chunk accessed 50 interactions ago has activation B ≈ 50^(-0.5) ≈ 0.14, which compresses retrieval candidates heavily.

The document's response is correct: include an ablation comparing ACT-R vs. simple recency (timestamp-based). If simple recency achieves ≥ 95% of ACT-R's retrieval performance, the power-law decay is unnecessary overhead. The document explicitly plans this ablation, which is the right approach. The critic's question—does power-law decay fit sparse regime?—is empirical and will be answered in Phase 1.

### KV cache verification is necessary but staged appropriately (visionary critic #10 response, engineering critic #8 response)
The critic notes that the cost model depends on KV cache working and identifies three unknowns: CLI cache behavior, CLI prompt variation, and cache TTL. These are real questions.

The document appropriately stages this: verification is planned before Phase 1 cost budgeting (act-r-proxy-memory.md line 304). The engineering decision is: test `claude -p` caching with a simple script (two identical passes, same prompt, measure whether cache is hit) before committing to the two-pass design cost estimate. If caching fails, the two-pass design costs ~35% more and needs economic justification on quality grounds alone, or a fallback strategy (lower model, hybrid single-pass + memory).

The document should add: "Phase 0 verification (1-2 weeks): Test prompt caching behavior with `claude -p` subprocess calls. If caching is not reliable, the two-pass design cost rises to $0.50/session; cost-benefit analysis will determine whether to proceed to Phase 1 with simpler single-pass design + memory augmentation instead."

### Multi-dimensional embeddings have clear fallback (engineering critic #9 response)
The critic notes that 5-dimensional embedding is novel and adds 5x embedding cost, with unknown payoff. The design defers validation to Phase 1 ablation.

This is sound. The document already has a clear fallback: single-embedding blended system (situation + artifact + stimulus + response + salience averaged into one vector). The ablation criterion is explicit (≥ 95% parity). The engineering comment is correct: the simpler design is ready to implement today; the multi-dimensional design is an optional enhancement with a clear go/no-go gate. This is good engineering practice.

## Clarifications

### Dialog chunks building episodic memory is a distinct mechanism (visionary critic misreading)
The critic characterizes the three outcome types (gate_outcome, discovery_turn, correction) as overlapping or redundant. The document now distinguishes them more clearly:

- **gate_outcome:** captures the decision and the context (state, task_type, action). Used for action prediction.
- **discovery_turn:** captures dialog that reveals *how* the human reasons. Used for dialog generation and quality assessment.
- **correction:** captures where the proxy was wrong and what the human said instead. Used for error analysis and attentional saliency.

These are not three ways to record the same thing. They're three different memories for three different purposes. The document should make this more explicit in the main text.

### Activation filtering and composite scoring maintain separate concerns (clarity on logic #4)
The critic noted confusion about noise placement in composite score. The document includes activation filtering (tau threshold, line 345) before composite scoring. This separation is clean: activation decides whether a chunk is eligible; composite score ranks eligibles.

Adding noise to the composite (rather than to activation directly) changes the semantics slightly, but it simplifies the implementation: one noise term instead of separate activation-level and ranking-level noise. The document should note: "Noise placement at the composite level is a practical simplification that differs from pure ACT-R semantics. In pure ACT-R, noise is applied at activation-level stochasticity. Here, noise is applied to the weighted composite score. This affects ranking in borderline cases but not systematically. Phase 1 ablation will compare the two approaches if retrieval performance suggests noise-level tuning is necessary."

### "Sparse interaction regime" explains the challenge the design addresses (visionary context)
The critic frames sparse interaction regime (5-10 gates per session) as a challenge for learned attention. This is not a misreading—it's the central design challenge. The document is building a memory system for an agent that operates in a sparse, high-stakes environment (each gate is consequential, not a high-volume stream). The sparse regime is not a bug; it's why the design is needed.

The document should emphasize this: "The proxy operates in a sparse regime: 5-10 gates per session, 2-3 sessions per week. This is fundamentally different from ACT-R's original environments (high-volume information streams). In sparse regimes, every interaction is significant, and the decay schedule is different. The design adapts ACT-R's principles (base-level activation, surprise-driven attention) to sparse, high-stakes decision-making. Phase 1 will validate whether these adaptations work."

### "Understanding" language is defended as proxy for predictive alignment (logic clarity)
The critic flags language like "the proxy has earned the right to act autonomously because it has demonstrated understanding." This is not a technical claim about sentience or comprehension. It's a claim about predictive alignment: the proxy's behavior reliably matches the human's behavior, which is operationally sufficient for autonomy (even if it's not "understanding" in a philosophical sense).

The document should reframe the language: "The proxy demonstrates understanding operationally when it produces predictions that align with human behavior on held-out validation data. This is not a claim about internal experience or consciousness; it's a claim about predictive accuracy. We use 'understanding' as shorthand for 'behavioral alignment' throughout this document."

### High-confidence assertions are hedged in verification section (tone clarity)
The critic notes that some statements ("the system has earned autonomy") sound inevitable rather than conditional. The document does include a verification section (act-r-proxy-memory.md lines 298-306) that flags unknowns. The tension is intentional: the forward path is clear if the empirical assumptions hold, and the document states what would change if they don't.

The document should resolve this by using more conditional language in the main text: "If the proxy achieves 95% prior-posterior agreement on validation data, the system is positioned to transition to Phase 2 dialog mode with optional autonomous action. This transition is not guaranteed—it depends on surprise rate stabilizing below 5% and salience delta diversity showing that the learned attention model is not brittle."

## Acknowledgments of Persistent Gaps

The design has five persistent gaps that Round 1 conceded and Round 2 resurfaces. The document should acknowledge these upfront and assign ownership:

1. **Embedding model choice** — defer to Phase 0 decision (week 1).
2. **Prompt templates (Pass 1, Pass 2, extraction)** — provide draft templates or defer to Phase 0 specification.
3. **Output parsing (ACTION/PROSE, confidence extraction)** — specify error handling or defer to Phase 0.
4. **Chunk serialization format** — provide template or defer to Phase 0.
5. **Concurrency control** — specify transaction semantics or defer to Phase 0.

The document should add a "Phase 0 Specification Checklist" that makes clear what must be decided before Phase 1 begins, and assign these as pre-implementation tasks, not design decisions.

## Summary

Round 2 surfaced two critical errors that need correction: the cost calculation (reverses the economic argument) and the autonomy criteria (should be defined before Phase 1, not after). These are genuine concessions that change the document's claims.

The bulk of Round 2 concerns are about specification gaps (engineering) and measurement gaps (evaluation). These are important but not design flaws—they're questions of what gets specified in Phase 0 vs. Phase 1 vs. Phase 2. The document should be explicit about this framing rather than leaving gaps implicit.

The visionary and logic concerns are real tensions that the document should acknowledge more clearly. The design is defensible, but the defenses depend on empirical validation during Phase 1. The document should be honest about these dependencies and explicit about the fallback strategies if the data doesn't cooperate.
