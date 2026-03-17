# Quality Evaluation — Round 2

## Verdict: PASS

## Concerns Addressed

- **Fabricated citations (factcheck)** — addressed: Honda et al. (2025) replaces "Nuxoll & West (2024)" with correct authors, year, and DOI. Meghdadi et al. (2026) replaces "Bhatia et al. (2026)" with correct first author and DOI. Meghdadi et al. description honestly notes its psycholinguistics focus and that relevance is the methodological pattern, not agent memory per se. Park corrected from "Park, S." to "Park, J.S." All references sections across all four documents are consistent.

- **Tau semantics mismatch (HM #2, logic #1)** — addressed: Retrieval rewritten as two-stage pipeline. Stage 1 filters on raw B > tau (ACT-R semantics preserved). Stage 2 computes composite score for ranking over survivors only. The act-r.md retrieval section now explicitly states tau is a threshold on raw B and references the soft-threshold equation as the gating function. The `retrieve()` implementation matches. This was the most important structural fix.

- **REINFORCE broadcast bias (HM #5, logic non-sequitur #2)** — addressed: The per-gate blanket reinforcement step is removed from the session lifecycle pseudocode. An explanatory note documents why, citing ACT-R Tutorial Unit 4. The trace creation rules in act-r-proxy-mapping.md now explicitly state that loading into prompt prefix is not retrieval-and-use. This eliminates the rich-get-richer feedback loop that would have ossified early memories.

- **Multi-dimensional cosine average does not produce intersection effect (HM #3, logic non-sequitur #1)** — addressed: `composite_score()` now divides by `TOTAL_EMBEDDING_DIMENSIONS` (5) instead of `len(similarities)`. Module-level constant added. Docstring corrected. Prose in both mapping and sensorium documents updated. The arithmetic now matches the claim: a chunk matching on 2/5 dimensions is penalized relative to one matching on 5/5.

- **salient_percepts missing from data model (logic #3)** — addressed: Field added to MemoryChunk dataclass (`salient_percepts: list[str]`), SQL schema (`salient_percepts TEXT DEFAULT '[]'`), and `record_interaction()` function. Examples, dataclass, schema, and function signature are now consistent.

- **Evaluation go/no-go criteria (HM #1)** — addressed: Concrete thresholds added. Minimum sample of 50 interactions spanning 3+ task types and 4+ CfA states. Action match rate >= 70% for go, < 60% for rethink. Multi-dimensional vs. single embedding: simplify if single achieves >= 95% of multi-dimensional match rate. Ambiguity rule: extend to 100 interactions, default to simpler configuration. Timeline estimate of 3-5 weeks included.

- **Shadow mode timeline (HM #4)** — addressed: Timeline estimate of 3-5 weeks at 5-10 gates/session with 2-3 sessions/week, tied to the 50-interaction minimum sample. Interaction-count-based rather than calendar-based, consistent with the document's own design philosophy.

- **Upstream context retrieval pathway (HM #6)** — addressed: New "Note on upstream context" paragraph in the sensorium's Problem section explains that upstream context is passed as raw text in Pass 2, enters memory through artifact and stimulus embeddings, and that a dedicated dimension was considered but removed due to overlap.

## Concerns Correctly Rejected

- **Min-max normalization is query-dependent (logic unstated assumption #1)** — defended: Query-dependent normalization answers the right question ("how does this chunk compare to other candidates for this query?"), follows the Park et al. approach, and produces correct behavior when candidates have similar activation (semantic relevance dominates). A documentation note was added instead of a design change. Sound reasoning.

- **LLM may override retrieved memories (logic unstated assumption #2)** — defended: LLMs condition strongly on in-context examples; this is the empirical basis of few-shot prompting and RAG. Specific episodic examples override general pretrained dispositions. The sparse-memory edge case is the cold-start problem, already addressed. Reasonable defense.

- **Short text fragments may not produce useful embeddings (logic unstated assumption #3)** — defended: Modern embedding models are trained and evaluated on short text pairs (STS, MTEB benchmarks). The weakest case (situation embedding) is also covered by structural filtering. The dimensions where embedding quality matters most (artifact, response, salience) contain natural language. Adequate defense.

- **Confidence threshold 0.3 may be unreliable (logic unstated assumption #4)** — defended with appropriate hedging: acknowledged as a starting heuristic, not a precision instrument. Caveat about LLM confidence calibration added. Binary fallback explicitly noted. The mechanism is retained with honest uncertainty. This is the right call — removing it would lose real information; keeping it with caveats preserves optionality.

- **Cold-start argument circularity (logic non-sequitur #3)** — defended and tightened: The revised cold-start section focuses on the mechanical difference (dialog producing structured chunks with embeddings vs. single binary outcome) without claiming the broader contested conclusion. The narrower claim is mechanically true.

## Concerns Missed

None. All six HM concerns and all seven logic critic findings (3 contradictions, 3 non-sequiturs, 4 unstated assumptions) received explicit treatment in the synthesis — either as fixes or as defended rejections. The factcheck's citation corrections were applied in full.

## Regressions

None observed. The core architecture is preserved. No sections were removed. The voice and argumentation quality are maintained or improved. The two-stage retrieval pipeline is cleaner than the conflated single-stage design it replaced. The session lifecycle pseudocode is shorter and more correct without the REINFORCE step.

## Coherence

The four documents are internally consistent: tau semantics, embedding dimensions, trace rules, data model fields, retrieval pipeline stages, and citation attributions all match across documents.

## Overall

Draft-2 resolves every critical concern from round 2 without introducing new problems. The six conceded fixes (citations, REINFORCE removal, tau semantics, cosine averaging, salient_percepts, go/no-go criteria) are all substantive and correctly implemented. The five defended rejections are well-reasoned and appropriately documented with caveats where uncertainty remains. The document set has moved from "plausible engineering proposal with known bugs" to "implementable specification with honest uncertainty about empirical parameters." The remaining open questions (confidence threshold calibration, embedding quality for short fragments, actual shadow mode outcomes) are correctly deferred to empirical validation rather than resolved by assertion. This is ready for Phase 1 implementation.
