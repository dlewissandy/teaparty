# Fact Check — Round 3

Sources checked: all four files in `draft-2/`
Prior findings: `round-2/factcheck.md`, `round-2/synthesis-changelog.md`

---

## Part 1: Fabricated Citations from Draft-1 — Were They Correctly Replaced?

The round-2 factcheck found two fabricated citations and one minor formatting error. The changelog confirms all three were addressed. Verification below.

### Honda et al. (2025) — formerly "Nuxoll & West (2024), HAI '24"

**Status: Correctly replaced. Citation is real and accurate.**

The draft-2 reference appears in `act-r-proxy-mapping.md` (References section) and `act-r-proxy-memory.md` (References section):

> Honda, Y., Fujita, Y., Zempo, K., & Fukushima, S. (2025). Human-Like Remembering and Forgetting in LLM Agents: An ACT-R-Inspired Memory Architecture. In *Proceedings of the 13th International Conference on Human-Agent Interaction* (HAI '25), pp. 229-237. ACM. DOI: 10.1145/3765766.3765803 — ACT-R base-level activation + cosine similarity for LLM agent memory retrieval. Best Paper Award, HAI 2025.

Verified:
- Authors (Honda, Fujita, Zempo, Fukushima): confirmed via ACM Digital Library and ResearchGate.
- Conference: 13th International Conference on Human-Agent Interaction (HAI '25): confirmed.
- DOI 10.1145/3765766.3765803: confirmed live.
- Best Paper Award at HAI 2025: confirmed (XperLab blog post from Tsukuba, November 2025).
- Content description ("ACT-R base-level activation + cosine similarity for LLM agent memory retrieval"): confirmed directionally accurate per round-2 verification.

**Page numbers pp. 229-237: not independently confirmed.** These page numbers appear in `round-2/researcher.md` (the source of the corrected citation) and were carried forward into draft-2. They cannot be verified without direct ACM Digital Library access. They are plausible (a 9-page paper in a proceedings volume is normal) but should be treated as unconfirmed. If the documents are published or shared externally, the page numbers should be verified against the ACM proceedings directly. This is a low-severity caveat, not an error.

**The fabricated "Nuxoll & West" attribution is gone and replaced with the correct authors. This correction is complete.**

Source: https://dl.acm.org/doi/10.1145/3765766.3765803

---

### Meghdadi et al. (2026) — formerly "Bhatia et al. (2026), Frontiers"

**Status: Correctly replaced. Citation is real and accurate. Description accurately revised.**

The draft-2 reference appears in `act-r-proxy-mapping.md` (both in prose on line 121 and in the References section):

> Meghdadi, M., Duff, J., & Demberg, V. (2026). Integrating language model embeddings into the ACT-R cognitive modeling framework. *Frontiers in Language Sciences*, 5. DOI: 10.3389/flang.2026.1721326 — Demonstrates that LM embedding cosine similarity is a valid substitute for hand-coded association strengths within the ACT-R framework. The paper's domain is psycholinguistic modeling (associative priming in the Lexical Decision Task); the relevance here is the methodological pattern of using LM embeddings where ACT-R uses symbolic associations.

Verified:
- Authors (Meghdadi, Duff, Demberg): confirmed. Maryam Meghdadi (Saarland University), John Duff (UCLA), Vera Demberg (Saarland University).
- Title: confirmed exactly.
- Journal: *Frontiers in Language Sciences*, Volume 5: confirmed.
- DOI: confirmed live at Frontiers.
- Published February 23, 2026: confirmed.
- Paper's domain (psycholinguistic modeling, associative priming, Lexical Decision Task): confirmed per Frontiers abstract.
- Description of relevance ("methodological pattern of using LM embeddings where ACT-R uses symbolic associations"): accurate and appropriately scoped.

**The fabricated "Bhatia, S." first author is gone, replaced with the correct first author Meghdadi. The misleading description ("embedding-based replacement for hand-coded ACT-R associations" applied to agent memory) has been corrected to accurately scope the relevance to the methodological pattern only. This correction is complete.**

Source: https://www.frontiersin.org/journals/language-sciences/articles/10.3389/flang.2026.1721326/full

---

### Park, J.S. et al. (2023) — minor formatting error "Park, S." in draft-1

**Status: Correctly fixed. "Park, J.S." now appears consistently.**

Confirmed in both `act-r-proxy-mapping.md` and `act-r-proxy-memory.md` references. The full author list (Park, O'Brien, Cai, Morris, Liang, Bernstein) is confirmed via ACM Digital Library. The description ("Weighted combination of recency, importance, and relevance with min-max normalization. Direct precedent for hybrid retrieval scoring.") is confirmed accurate — the paper explicitly normalizes all three retrieval components to [0, 1] via min-max scaling before combining.

**This correction is complete.**

Source: https://dl.acm.org/doi/10.1145/3586183.3606763

---

## Part 2: Remaining Factual Errors

No new factual errors were found in the claims that were verified. Specific checks below.

### ACT-R parameter values and equations

- Base-level activation formula `B = ln(sum t_i^(-d))`: confirmed standard ACT-R (Anderson & Lebiere, 1998, Ch. 4).
- d = 0.5 empirical basis (Anderson & Schooler, 1991): confirmed.
- Soft-threshold retrieval probability `P = 1 / (1 + exp(-(B - tau) / s))`: confirmed as ACT-R equation 4.4 form (Anderson & Lebiere, 1998).
- Tau as threshold on raw B (not composite): now correctly stated and implemented. Stage 1 filters by raw B; Stage 2 ranks by composite. This was the round-2 Tau semantics fix. Verified as applied correctly in `act-r-proxy-mapping.md` `retrieve()` function.
- REINFORCE step removed from session lifecycle: confirmed absent in `act-r-proxy-memory.md` pseudocode. The explanatory note is present: "In standard ACT-R, chunks are reinforced only when specifically retrieved for a task and actively referenced by a production rule — not merely by being present in working memory (ACT-R Tutorial Unit 4; Anderson & Lebiere, 1998, Chapter 4)."

### Cosine averaging denominator

- Verified: `composite_score()` divides `sim_sum` by `TOTAL_EMBEDDING_DIMENSIONS` (the constant 5), not by `len(similarities)`. Module-level constant `TOTAL_EMBEDDING_DIMENSIONS = 5` is present. This was the round-2 fix. Applied correctly.

### Anthropic prompt caching figures

- "First call: cache-write premium 1.25x": consistent with Anthropic's documented caching pricing as of mid-2025.
- "Subsequent calls: cached prefix at ~10% of standard rate (e.g., 0.30/MTok instead of 3.00/MTok for Sonnet)": the specific dollar figures ($0.30/MTok cached, $3.00/MTok uncached) correspond to Claude 3.5 Sonnet pricing as of mid-2025. These figures may not reflect current pricing for claude-sonnet-4-6 (the model running this project). The document does not specify which Sonnet model, making the specific dollar figures potentially stale. This is a minor caveat, not a fabrication — the relative claim (cached prefix at ~10% of standard rate) is accurate as a structural property of Anthropic's caching scheme, even if the absolute figures vary by model.
- Cache TTL "within 5-minute TTL": Anthropic's documented cache TTL is 5 minutes for standard caching. This is confirmed correct as of mid-2025.
- "Cache matching is account-level, not session-level": confirmed as accurate for Anthropic prompt caching.

### Working memory capacity computation

- "(200,000 - 12,000) / 500 = 376": arithmetic is correct: 188,000 / 500 = 376. Verified.

### Anderson & Schooler (1991) citation

- Title: "Reflections of the environment in memory"
- Journal: *Psychological Science*, 2(6), 396-408
- This matches the standard citation for this paper. Confirmed.

### salient_percepts field consistency

- Present in `MemoryChunk` dataclass (`salient_percepts: list[str]`): confirmed.
- Present in SQL schema (`salient_percepts TEXT DEFAULT '[]'`): confirmed.
- Present in `record_interaction()` signature (`salient_percepts: list[str] | None = None`): confirmed.
- Populated only when surprise detected: confirmed in session lifecycle pseudocode and `record_interaction()` body (`salient_percepts=salient_percepts or []`).

---

## Part 3: New Claims Introduced in Draft-2

The changelog lists six substantive changes. The following new claims are introduced and should be checked:

### Tau two-stage retrieval (new in draft-2)

**Claim:** "tau is a threshold on raw B — it filters for memory accessibility. The filtered candidates are then ranked by a composite score."

This is a design decision, not an external factual claim. However, the characterization of tau as a threshold on raw activation B (not on a composite score) is consistent with ACT-R's formal definition. Anderson & Lebiere (1998, Ch. 4) define the retrieval condition as `B > tau` where B is base-level activation. No issue.

### "Loading chunks into the prompt prefix is analogous to having chunks in declarative memory above threshold; it does not constitute retrieval-and-use" (new in draft-2)

**Claim citing:** "ACT-R Tutorial Unit 4; Anderson & Lebiere, 1998, Chapter 4"

This is an accurate characterization of standard ACT-R. In ACT-R, spreading activation and chunk retrieval occur when a production rule specifically fires and requests a declarative memory retrieval (the "harvest" step). Passive presence in working memory does not count as a retrieval event. The characterization is accurate and the sources cited are appropriate. No issue.

### Evaluation go/no-go thresholds (new in draft-2)

The 70%/60%/95% thresholds and sample size requirements (50 interactions, 3+ task types, 4+ CfA states, 3-5 weeks estimate) are design choices, not external factual claims. They make no citations and are internally consistent. No issue.

### AutoDiscovery reference in `act-r-proxy-sensorium.md`

**Claim:** "The same principle that Allen AI's AutoDiscovery uses for guiding hypothesis exploration — but applied to what the proxy pays attention to..."

The round-2 factcheck (round-1 correction) confirmed this description was fixed from "hypothesis ranking" to "guiding hypothesis exploration." The phrasing is present in draft-2 as written. The AutoDiscovery reference is descriptive but does not cite a specific paper inline at this location, so no citation to verify. The framing is appropriate.

---

## Summary Table

| Item | Status |
|---|---|
| Honda et al. (2025) — authors, venue, DOI, description | Correct |
| Honda et al. (2025) — page numbers pp. 229-237 | Unconfirmed (plausible; cannot verify without direct ACM access) |
| Meghdadi et al. (2026) — authors, title, venue, DOI, description | Correct |
| Park, J.S. et al. (2023) — formatting, venue, content description | Correct |
| ACT-R equations and parameter characterizations | Correct |
| REINFORCE step removal | Correctly applied |
| Tau two-stage retrieval | Correctly applied |
| Cosine averaging denominator fix | Correctly applied |
| salient_percepts field consistency | Correctly applied |
| 376-chunk capacity arithmetic | Correct |
| Prompt caching structure (10% rate, account-level, 5-min TTL) | Correct |
| Prompt caching dollar figures (0.30/3.00 for Sonnet) | Model-version caveat; accurate as structural ratio, may be stale for specific model |

---

## Net Assessment

The round-2 critical fixes were applied correctly across all four documents. The two fabricated citations (Nuxoll & West; Bhatia) are replaced with verified citations (Honda et al., Meghdadi et al.). The Meghdadi description is accurately scoped to the methodological relevance, not overstated. Park is formatted correctly as "J.S."

One minor open item: the page numbers "pp. 229-237" for Honda et al. were sourced from the round-2 researcher's corrected citation and cannot be independently confirmed without direct ACM Digital Library access. This is a low-severity issue — the DOI is correct and resolves live, so the page numbers are redundant for reference purposes. If these documents are published externally, verify pages at https://dl.acm.org/doi/10.1145/3765766.3765803.

The prompt caching dollar figures ($0.30/MTok, $3.00/MTok) are consistent with mid-2025 Claude 3.5 Sonnet pricing but the document does not specify which Sonnet model. This is a minor version-specificity gap, not a factual error.

No fabrications, no new unverifiable claims, no arithmetic errors. The documents are factually clean.
