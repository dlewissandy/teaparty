# Drift Evaluation — Round 2

## Verdict: PASS

## Drift Flags

### Anderson & Schooler "event-based" framing (act-r.md)
**Anchor says:** "their analysis was event-based — they measured relevance as a function of how many *events* ago something last appeared, not how many seconds"
**Draft says:** adds parenthetical caveat: "their primary unit of analysis was days for NYT/email and utterance intervals for speech — the 'event-based' framing is a reasonable interpretation of their methodology, not a direct quote from the paper"
**Assessment:** Preserved with qualification
**Justified:** Yes. The anchor's claim was slightly overstated; the caveat is honest without retreating from the core argument that interaction-based time is well-motivated.

### d = 0.5 empirical status (act-r.md)
**Anchor says:** "These values are empirically validated across hundreds of ACT-R models" — presented as a settled fact.
**Draft says:** adds a full "Caveat for agent systems" paragraph noting sparse interaction counts (50-200 vs. thousands), calls d = 0.5 "a principled starting point informed by ACT-R's empirical tradition, not a validated parameter for agent gate decisions."
**Assessment:** Weakened
**Justified:** Yes. The anchor's claim was about ACT-R models of human cognition in lab settings. The draft correctly notes the regime is different. The core claim (d = 0.5 is the right starting point because the power-law form is established) is preserved. The addition of "calibrate during shadow mode" is honest engineering, not capitulation.

### Noise parameter s = 0.25 (act-r.md)
**Anchor says:** "standardly set to **0.25**" — presented as a standard value.
**Draft says:** "The ACT-R default for `:ans` is NIL (disabled); when enabled, tutorial examples use values ranging from 0.2 to 0.5. For this system, we use **s = 0.25** as a design choice"
**Assessment:** Recharacterized (from "standard" to "design choice")
**Justified:** Yes. The anchor overstated this as a standard value when ACT-R actually defaults to noise disabled. The draft is more accurate without changing the chosen value or its rationale.

### Tau = -0.5 (act-r.md)
**Anchor says:** "The standard value is `tau = -0.5`"
**Draft says:** "The ACT-R default for `:rt` is NIL (disabled); when enabled, tutorial values range from 0 to -2 depending on the model. For this system, we use **tau = -0.5** — a design choice"
**Assessment:** Recharacterized (from "standard" to "design choice")
**Justified:** Yes. Same logic as noise — the anchor presented a design choice as a standard. The value and its role are unchanged.

### "We have something better: vector embeddings" (act-r-proxy-mapping.md)
**Anchor says:** "We have something better: **vector embeddings**" — a confident, assertive claim of superiority over ACT-R's symbolic spreading activation.
**Draft says:** "We replace spreading activation with **vector embeddings**... This substitution provides context-sensitive retrieval without requiring a pre-built associative graph... However, it is a different mechanism with different properties — embeddings capture semantic overlap in text, not structural associations between concepts."
**Assessment:** Weakened
**Justified:** Borderline. The anchor's "something better" was rhetorically strong but defensible — embeddings genuinely are more powerful for unstructured text contexts. The draft hedges into "different mechanism with different properties" which is technically more accurate but loses the anchor's conviction that this substitution is an improvement, not merely a trade. The core design choice (use embeddings) is preserved. The added citations (Honda et al., Meghdadi et al.) actually strengthen the case by providing external validation. Net: acceptable.

### Multi-dimensional embeddings as "low-fan spreading activation" (act-r-proxy-mapping.md)
**Anchor says:** "the equivalent of low-fan spreading activation" — a direct analogy claim.
**Draft says:** removes that phrase, adds a caveat note calling multi-dimensional retrieval "a novel design choice without published validation" and recommending ablation in shadow mode.
**Assessment:** Weakened
**Justified:** Yes. The anchor's analogy was evocative but the mechanism (averaging independent cosine similarities) is not actually equivalent to low-fan spreading activation in ACT-R's sense (graph-based association through shared chunk slots). The draft preserves the design and the intuition while being honest that it needs empirical validation.

### REINFORCE step in session lifecycle (act-r-proxy-memory.md)
**Anchor says:** Pseudocode includes "REINFORCE: add trace N to each loaded chunk" after every gate.
**Draft says:** Removed entirely, with explanatory note citing ACT-R standards.
**Assessment:** Removed
**Justified:** Yes. This was the most substantive removal and it is well-defended. The anchor's REINFORCE step departs from standard ACT-R (where chunks are reinforced only on retrieval-and-use, not passive presence in working memory) and creates a rich-get-richer dynamic that undermines the anchor's own claimed behavior of drifting interests. The removal is an improvement to the anchor's design, not a retreat from it.

### Retrieval equation: tau applied to composite vs. raw B (act-r-proxy-mapping.md)
**Anchor says:** `score = activation_weight * B + semantic_weight * cosine(...) + noise` with threshold check `if score > tau`.
**Draft says:** Two-stage: filter by raw B > tau first, then rank by composite score with normalized B.
**Assessment:** Recharacterized (implementation changed)
**Justified:** Yes. The anchor's design had tau gating on a mixed score where tau's ACT-R semantics (activation threshold) no longer applied. The draft separates filtering (on activation, as ACT-R intends) from ranking (on composite). This fixes an inconsistency in the anchor rather than weakening it.

### Cosine averaging: populated dimensions vs. total dimensions (act-r-proxy-mapping.md)
**Anchor says:** "average cosine across matched dimensions" (divides by number of populated dimensions).
**Draft says:** divides by total dimensions (5), not populated ones.
**Assessment:** Recharacterized (implementation changed)
**Justified:** Yes. The anchor claimed an "intersection effect" but the implementation (averaging over populated dimensions) actually rewarded narrow matches. The draft fixes the implementation to match the anchor's stated intent.

### EMA as purely non-decision-making (act-r-proxy-memory.md)
**Anchor says:** EMA is reframed strictly as monitoring: "not a decision mechanism for the proxy."
**Draft says:** Preserves this, but adds: "EMA trend information does flow into the proxy's decisions indirectly: if upstream quality degrades, the proxy encounters more corrections... The memory system naturally becomes more skeptical as corrections accumulate. EMA may also trigger operational actions..."
**Assessment:** Preserved with nuance
**Justified:** Yes. The anchor's sharp separation was slightly too clean. The draft acknowledges the indirect pathway without reverting EMA to a decision gate.

### Proxy autonomy / auto-approval (act-r-proxy-memory.md, act-r-proxy-sensorium.md)
**Anchor says:** "The proxy doesn't transition from 'always escalate' to 'auto-approve.'" Implies the proxy always produces dialog, never skips the human.
**Draft says:** Adds a note that the proxy *can* act autonomously when "its prior-posterior agreement reflects genuine understanding — not pattern-matching on a scalar." The sensorium document elaborates: "the proxy has earned the right to act autonomously because it has demonstrated that it attends to what the human would attend to."
**Assessment:** Preserved with clarification
**Justified:** Yes. The anchor was ambiguous — it said the proxy doesn't auto-approve based on a scalar, but never explicitly addressed what happens when the proxy's model becomes highly accurate. The draft resolves this ambiguity in the direction the anchor's logic points: autonomy is earned through demonstrated understanding (two-pass prediction), not through scalar accumulation.

### Surprise mechanism: binary vs. graded (act-r-proxy-sensorium.md)
**Anchor says:** Binary surprise only: "if prior.action != posterior.action" triggers extraction; otherwise no surprise.
**Draft says:** Graded surprise with confidence-delta threshold (|confidence delta| > 0.3 as moderate surprise), plus explicit caveat that the threshold needs calibration and the binary fallback is available.
**Assessment:** Extended (new mechanism added)
**Justified:** Yes. This is additive, not subtractive. The binary mechanism is preserved as the "strong surprise" case. The confidence-delta case captures real information the anchor's binary mechanism would miss (large confidence shifts without action changes). The caveat about calibration is appropriate.

### Voice and register
**Anchor says:** Direct, confident, first-person-plural engineering voice. Statements like "This is a better fit," "We have something better," "One equation, many behaviors."
**Draft says:** Mostly preserved. The confident assertions remain. Qualifications are added as separate paragraphs or notes rather than hedging the original sentences. "We have something better" became "We replace spreading activation with vector embeddings" — the only notable voice change.
**Assessment:** Mostly preserved
**Justified:** The few places where confidence was softened correspond to places where the anchor overstated (parameter values presented as "standard" when they're design choices, "something better" for a different-not-strictly-better mechanism). The draft does not descend into committee prose.

### Cache economics cost model (act-r-proxy-memory.md)
**Anchor says:** Claims two-pass with caching is "cheaper than the current single-pass model" with a clean cost table.
**Draft says:** Adds cache-write premium (1.25x), output token doubling, and embedding costs. Notes savings are "substantial for the input side" but total cost depends on ratio of prefix to gate-specific tokens.
**Assessment:** Weakened
**Justified:** Yes. The anchor's cost model omitted real costs (cache-write premium, output tokens). The draft is more honest without abandoning the argument that caching makes the two-pass model economically viable.

## Overall

Draft-2 preserves the anchor's core architecture (ACT-R activation memory replacing EMA-as-decision-gate, two-pass prediction, structural filtering + semantic ranking, interaction-based time, Bayesian surprise), its structure (four documents with clear roles), and its ambition (a proxy that earns autonomy through demonstrated understanding, not scalar accumulation). The changes fall into three categories: (1) corrections where the anchor's implementation contradicted its own stated intent (cosine averaging, tau semantics, REINFORCE step), (2) honest recharacterizations where the anchor overstated certainty (parameter values called "standard" that are actually design choices, "something better" softened to "different mechanism"), and (3) additive precision where the anchor was silent (cold-start behavior, evaluation criteria, upstream context pathway, graded surprise). No novel claims were argued away. No sections were removed. The voice remains direct and confident where the claims support it, with qualifications added as separate notes rather than hedged inline. The critics improved the design's internal consistency without diluting its ambition.
