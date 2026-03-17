# Drift Evaluation — Round 1

## Verdict: PASS

## Drift Flags

### The Proxy's Job (act-r-proxy-memory.md)
**Anchor says:** The proxy's job is to proxy the behavior of the human — dialog first, decision last.
**Draft says:** Identical text, plus an added note that the design "does permit autonomous proxy action (without escalation to the human) when the proxy has demonstrably inspected the artifact via two-pass prediction."
**Assessment:** Preserved. The addition makes an implicit consequence of the sensorium design explicit rather than contradicting the anchor's position.
**Justified:** Yes — the logic critic identified a real tension between "dialog is essential" and the sensorium's earned-autonomy argument. The note resolves rather than undermines.

### Two Systems, Two Roles (act-r-proxy-memory.md)
**Anchor says:** ACT-R is the cognitive core; EMA is a health monitor only.
**Draft says:** Same claim, with a nuance added in the mapping document that EMA trends flow indirectly into decisions via the memory (more corrections produce more correction chunks) and may trigger operational actions.
**Assessment:** Preserved. The nuance is honest without collapsing the separation.
**Justified:** Yes — the logic critic's point about information leakage was legitimate.

### Embeddings replace spreading activation — "both simpler and more powerful" (act-r-proxy-memory.md, act-r-proxy-mapping.md)
**Anchor says:** Vector embeddings replace spreading activation with a mechanism "both simpler and more powerful."
**Draft says:** Replaces with "serves the same role (context-sensitive retrieval) via a different mechanism (semantic overlap in embedding space rather than structural graph associations)."
**Assessment:** Weakened. The anchor's "simpler and more powerful" is a confident claim. The draft retreats to neutral phrasing.
**Justified:** Yes — the logic critic correctly identified that embeddings and spreading activation have genuinely different properties (embeddings capture text overlap, not structural associations). The anchor was overclaiming. The draft still uses embeddings; it just stops claiming superiority over a mechanism it is not replicating.

### "Deployed at scale" / Claude memory claim (act-r-proxy-mapping.md)
**Anchor says:** "Activation-weighted embedding retrieval is the pattern underlying modern AI memory systems, including Claude's own persistent memory. The approach is deployed at scale."
**Draft says:** Removes both claims. Replaces with specific citations (Park et al. 2023, Nuxoll & West 2024, Bhatia et al. 2026).
**Assessment:** Recharacterized. The anchor's rhetorical move was "this is mainstream, even Claude does it." The draft's move is "here are published papers that validate the pattern."
**Justified:** Yes — the factcheck found the Claude memory claim was unverifiable. The replacement is stronger evidence for the same conclusion.

### "Low-fan spreading activation" analogy (act-r-proxy-mapping.md, act-r-proxy-sensorium.md)
**Anchor says:** Multi-dimensional embedding intersection is "the equivalent of low-fan spreading activation."
**Draft says:** Describes the intersection effect directly ("specific, selective associations") without claiming ACT-R equivalence.
**Assessment:** Weakened. The anchor used ACT-R's fan-effect language to ground the design in cognitive theory.
**Justified:** Yes — averaging cosine similarities does not produce the fan effect. The critic was right; the analogy was misleading. The functional description is preserved.

### Interaction-based time and Anderson & Schooler (act-r.md)
**Anchor says:** Anderson & Schooler's analysis "was in events (how many headlines ago did this word last appear?), not in seconds. The environment's statistical structure is event-based."
**Draft says:** Adds parenthetical: "the 'event-based' framing is a reasonable interpretation of their methodology, not a direct quote from the paper. The primary units were days (NYT/email) and utterance intervals (speech)."
**Assessment:** Preserved with added precision. The anchor's argument for interaction-based time is fully intact; the source attribution is corrected.
**Justified:** Yes — the factcheck found the original phrasing overstated the directness of the mapping.

### d = 0.5 (act-r.md)
**Anchor says:** d = 0.5 matches the statistical structure of the real world. "These values are empirically validated across hundreds of ACT-R models."
**Draft says:** Preserves the theoretical argument in full. Adds a "Caveat for agent systems" paragraph acknowledging that Anderson & Schooler's corpora are high-volume while proxy interactions are sparse, and calls d = 0.5 "a principled starting point" to be calibrated in shadow mode. The parameter table now distinguishes "ACT-R standard" (d) from "Design choice" (s, tau).
**Assessment:** Preserved with epistemic honesty added. The anchor's theoretical case is intact. The caveat is additive.
**Justified:** Yes — the concern about sparse vs. dense interaction regimes is legitimate and the anchor was silent on it.

### Noise s = 0.25 and threshold tau = -0.5 (act-r.md)
**Anchor says:** "standardly set to 0.25" and "standard value is tau = -0.5."
**Draft says:** Reframed as design choices, not ACT-R standards. Adds ACT-R default info (NIL/disabled) and tutorial ranges.
**Assessment:** Preserved (values unchanged). Provenance corrected.
**Justified:** Yes — the factcheck was right that these are not ACT-R standards.

### Binary surprise mechanism (act-r-proxy-sensorium.md, act-r-proxy-memory.md)
**Anchor says:** Surprise is binary: "if prior.action != posterior.action" triggers extraction; otherwise no surprise.
**Draft says:** Surprise is graded: action change = strong surprise (2 calls), confidence delta > 0.3 = moderate surprise (1 call), neither = no surprise.
**Assessment:** Extended. The anchor's binary mechanism is a strict subset of the draft's graded mechanism. No anchor behavior is removed.
**Justified:** Yes — the HM concern about losing information from large confidence shifts without action changes was compelling. The proponent partially conceded.

### Explicit reinforcement trace rule (act-r-proxy-mapping.md)
**Anchor says:** Rule 3: "When a new interaction produces a similar outcome to a past one — the human approves at PLAN_ASSERT again — the matching chunk gets an additional trace even if it wasn't explicitly retrieved."
**Draft says:** Rule 3 removed. Traces created only on creation and retrieval.
**Assessment:** Removed.
**Justified:** Yes — the proponent conceded this was "a bias bomb." The researcher confirmed it departs from ACT-R without justification. Rules 1 and 2 are sufficient for the memory dynamics the anchor describes. This is one of the few substantive removals and it is well-justified.

### Two-pass prediction design (act-r-proxy-sensorium.md)
**Anchor says:** The two-pass architecture (prior without artifact, posterior with) is the core mechanism for learned attention.
**Draft says:** Identical architecture preserved in full. Adds a "note on signal quality" acknowledging that temperature 0 does not guarantee determinism and the delta is approximate.
**Assessment:** Preserved. The caveat is honest without undermining the design.
**Justified:** Yes — acknowledging LLM non-determinism is responsible engineering.

### KV cache as working memory (act-r-proxy-memory.md)
**Anchor says:** Detailed future-direction section with session lifecycle, concurrency model, pseudocode, data structures, and cost model.
**Draft says:** All content preserved. Adds framing sentence ("The core design stands on its own; this section describes what becomes possible..."), adds cache-write premium to cost model, removes incorrect G=10/G=20 arithmetic, adds nuance to cross-task learning.
**Assessment:** Preserved. Framing clarified, arithmetic corrected.
**Justified:** Yes — the corrections are factual.

### Cost model (act-r-proxy-memory.md)
**Anchor says:** Detailed token-equivalent analysis showing two-pass with caching is 24% cheaper than single-pass for G=5. Includes G=10 and G=20 projections.
**Draft says:** Preserves the G=5 analysis. Removes G=10/G=20 rows (factcheck found arithmetic errors). Adds output tokens and cache-write premium as acknowledged omissions. Adds caveat that total savings depend on prefix-to-gate-content ratio.
**Assessment:** Weakened numerically but preserved directionally. The anchor's "cheaper than single-pass" claim survives for G=5 but the broader projections are removed.
**Justified:** Yes — publishing wrong numbers is worse than publishing fewer numbers. The formula remains for readers to compute.

### Sensorium embedding dimensions (act-r-proxy-sensorium.md)
**Anchor says:** 6-dimension table including "Upstream."
**Draft says:** 5-dimension table; "Upstream" removed to match the mapping document's canonical schema.
**Assessment:** Preserved (reconciled). The anchor's mapping document always had 5 dimensions; the sensorium's 6th was an inconsistency.
**Justified:** Yes — the mapping document is the implementation-facing schema and was already at 5 dimensions.

### Voice and prose style
**Anchor says:** Direct, opinionated, first-person-plural. "This fails because." "It is worth it." "Forgetting is not a bug."
**Draft says:** Same voice throughout. The additions (caveats, evaluation metrics, maintenance) are written in the same register. No committee-speak detected.
**Assessment:** Preserved.
**Justified:** N/A.

### Structure and organization
**Anchor says:** Four documents with clear separation: theory (act-r.md), motivation/migration (act-r-proxy-memory.md), implementation mapping (act-r-proxy-mapping.md), attention mechanism (act-r-proxy-sensorium.md).
**Draft says:** Same four documents, same section structure. New sections added (Cold Start Behavior, Memory Maintenance, evaluation metrics in Migration Path) but no sections moved or removed.
**Assessment:** Preserved. Additive only.
**Justified:** N/A.

## Overall

This draft preserves the anchor's intent. The core architecture is unchanged: ACT-R activation memory replaces EMA as the decision driver, two-pass prediction provides learned attention, structural filtering plus semantic ranking handles retrieval, and EMA is reframed as monitoring. No sections were removed. No novel claims were argued away by critics. The most substantive removal (explicit reinforcement trace rule 3) was conceded by the proponent as dangerous and confirmed by the researcher as non-standard ACT-R. The rhetorical adjustments ("simpler and more powerful" softened, "deployed at scale" replaced with citations, parameter provenance corrected) make the document more honest without making it less ambitious. The additions (normalization, evaluation metrics, memory maintenance, cold start) fill operational gaps the anchor left unaddressed. The voice is intact. This is refinement, not drift.
