# Quality Evaluation — Round 1

## Verdict: PASS

## Concerns Addressed

- **:rt default value (fact check)** — addressed: act-r.md line 119 now reads "The ACT-R default for `:rt` is 0 (zero)" with clear separation from `:ans` which defaults to NIL. Correct.
- **Cache matching scope (fact check)** — addressed: act-r-proxy-memory.md line 226 now reads "workspace-level (as of February 2026; previously organization-level)". Correct.
- **Anderson & Schooler d=0.5 overstatement (fact check + researcher)** — addressed: act-r.md lines 87-89 now distinguish the environmental power-law finding from the specific exponent value. The existing caveat (line 93) is preserved. Good balance.
- **"Bayesian surprise" misnamed (visionary #2 + researcher)** — addressed: renamed to "prediction-change salience" across all files with Itti & Baldi cited as conceptual inspiration. Consistent across documents.
- **Trace compaction (visionary #5 + engineering #6 + researcher)** — addressed: act-r-proxy-mapping.md line 197 now references the standard ACT-R approximation and Petrov (2006). Jensen's inequality violation noted. Petrov added to references.
- **Embedding drift (visionary #6)** — addressed: `embedding_model TEXT NOT NULL` added to SQL schema at line 254. Field present in dataclass.
- **Cost model needs absolute numbers (visionary #7)** — addressed: worked example with Sonnet pricing at lines 279-296, showing ~$0.35 current vs ~$0.47 two-pass per session. Concrete and useful.
- **1-hour TTL option (researcher)** — addressed: line 225 adds the 1-hour TTL at 2x write premium.
- **Dialog equivocation (logic #2)** — addressed: act-r-proxy-memory.md line 31 now frames the argument around inspection rather than dialog. "Quality requires artifact inspection."
- **"Genuine understanding" (logic non-sequitur #2)** — addressed: act-r-proxy-memory.md line 41 and act-r-proxy-sensorium.md line 169 now use "consistent inspection with accurate predictions" rather than "genuine understanding."
- **Cold start "populates faster" (logic non-sequitur #3)** — addressed: act-r-proxy-mapping.md line 169 now hedges: "Whether this richer data translates to faster convergence toward useful retrieval is an empirical question."
- **EMA direct/indirect equivocation (logic #3)** — addressed: act-r-proxy-mapping.md line 179 and act-r-proxy-memory.md line 179 now state the separation mechanism clearly.
- **Noise placement departure (logic #4)** — addressed: act-r-proxy-mapping.md lines 337-341 acknowledge the departure from ACT-R semantics in a code comment.
- **delta_from_posterior naming (engineering #9)** — addressed: act-r-proxy-sensorium.md line 115 now uses `"delta"` matching the canonical schema.
- **Autonomy criterion underspecified (visionary #4)** — addressed: act-r-proxy-sensorium.md lines 167 adds explicit acknowledgment that autonomy criteria are a design gap requiring operational specification before Phase 3.
- **ACT-R framing (visionary #1)** — addressed: act-r-proxy-memory.md lines 15-17 and 21 now explicitly state the division of labor (ACT-R models memory accessibility; LLM reasons over retrieved memories).
- **AI writing patterns** — partially addressed: em dashes reduced, "This is" patterns varied, some "not X but Y" patterns reworked. Improvement visible but not transformative.

## Concerns Correctly Rejected

- **"ACT-R is just an index" / recharacterize as RAG** — defended: the document now states ACT-R's role explicitly while maintaining the claim that retrieval shapes reasoning. The proponent's argument held.
- **Retrieval-reinforcement loop identical to REINFORCE** — defended: the distinction between selective (retrieval) and blanket (REINFORCE) reinforcement is maintained. The proponent's argument held.
- **Five embeddings should be removed** — defended: the existing ablation plan is sufficient. The activation counterbalance argument is reasonable.
- **Dialog claim untestable** — defended: action match rate as pragmatic proxy is acknowledged.
- **Embedding cosine similarity assumption** — defended: scope correctly delegated to parent document.

## Concerns Missed

- **Engineering #1 (embedding model not specified)** — the `embedding_model` column was added to the schema, but the actual model choice (which API, what dimensionality) is still unspecified. The changelog lists this as "explicitly scoped out as implementation decisions" but neither the changelog nor the document says this explicitly. The document should note that the embedding model is an implementation choice with constraints (must be deterministic, must support re-embedding).
- **Engineering #7 (concurrency control for interaction counter)** — not addressed. The FIFO queue is described in the future KV cache section but the current design has no concurrency specification. This concern was conceded in the proponent's "engineering gaps" section but not incorporated.
- **Engineering #10 (chunk serialization format for LLM prompt)** — not addressed. The proponent conceded this as a blocking gap but the synthesis didn't add a serialization specification.
- **Engineering #2, #3, #4 (prompt templates, output parsing, confidence format)** — not addressed. These were conceded as real gaps but the synthesis noted they should be "explicitly scoped out." The document doesn't do this explicitly.

## Regressions

- **EMA section in act-r-proxy-mapping.md (line 179)** has minor redundancy: "EMA remains as a system health monitor — tracking approval rates per (state, task_type) over time. A declining EMA signals that upstream agents are producing worse artifacts, not that the proxy should change its behavior." is followed immediately by "EMA and the memory system operate on separate data paths. EMA tracks approval rates over time and produces trend reports." The approval-rate tracking is stated twice in adjacent sentences. Should be tightened.
- No other regressions detected. All equations, worked examples, code, schemas, and references from draft-0 are preserved in draft-1.

## Coherence

The documents read as a unified set with consistent terminology; the "prediction-change salience" rename and "inspection" reframe are applied consistently across all four files.

## Overall

Draft-1 is meaningfully better than draft-0. The factual corrections (:rt default, cache scope, d=0.5 attribution) are clean. The conceptual tightenings (inspection vs. dialog, retrieval vs. thinking, prediction accuracy vs. understanding) make the document more honest without losing its ambition. The new content (cost example, 1-hour TTL, embedding_model column, Petrov citation, autonomy gap acknowledgment) addresses real gaps. The missed engineering concerns (embedding model choice, chunk serialization, concurrency, prompt templates) are the main weakness — four conceded gaps that weren't incorporated. These don't make draft-1 worse than draft-0 (they were absent in draft-0 too), but they represent missed opportunities for improvement. A second round should address them.
