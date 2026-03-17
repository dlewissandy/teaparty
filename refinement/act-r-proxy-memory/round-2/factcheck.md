# Fact Check — Round 2

Sources checked: `draft-1/act-r.md`, `draft-1/act-r-proxy-mapping.md`, `draft-1/act-r-proxy-sensorium.md`, `draft-1/act-r-proxy-memory.md`
Round 1 corrections based on: `round-1/factcheck.md`, `round-1/synthesis-changelog.md`

---

## Round 1 Corrections Applied

- **s = 0.25 reframed as design choice (act-r.md)** — fixed correctly. The parameter table now reads "Design choice; ACT-R tutorials use 0.2-0.5" in the Source column. The prose says "we use s = 0.25 as a design choice" and notes it needs empirical calibration. The provenance claim is gone.

- **tau = -0.5 reframed as design choice (act-r.md)** — fixed correctly. The table reads "Design choice; ACT-R tutorials use 0 to -2." The prose says "a design choice that admits chunks with slightly negative activation" and notes calibration is needed. Provenance claim removed.

- **d = 0.5 caveat added (act-r.md)** — fixed correctly. The "Caveat for agent systems" paragraph is present and acknowledges that Anderson & Schooler's corpora were high-volume, that 50-200 proxy interactions are sparse by comparison, and that d = 0.5 is a principled starting point to be calibrated in shadow mode. Epistemic humility is appropriate.

- **Anderson & Schooler event-based framing (act-r.md)** — fixed correctly. Point 2 in "Interactions, Not Seconds" now includes: "(Note: their primary unit of analysis was days for NYT/email and utterance intervals for speech — the 'event-based' framing is a reasonable interpretation of their methodology, not a direct quote from the paper.)" This matches the required correction from round 1.

- **Embedding dimensions harmonized to 5 (all files)** — fixed correctly. All four documents consistently use the five-dimension schema: situation, artifact, stimulus, response, salience. The "upstream" dimension is absent from the sensorium table. The mapping document, sensorium document, and memory document MemoryChunk dataclass all match.

- **normalize(B) added to combined score (act-r-proxy-mapping.md)** — fixed correctly. The formula now reads `activation_weight * normalize(B) + semantic_weight * cosine(...) + noise`. The `normalize_activation()` function is present in the implementation sketch. The "Why normalization is needed" paragraph is present and cites Park et al. (2023).

- **Explicit reinforcement trace rule 3 removed (act-r-proxy-mapping.md)** — fixed correctly. The "When Are Traces Created?" section now lists only two rules: creation and retrieval. The note "These two rules match standard ACT-R" is present.

- **Chunk creation for non-surprise gates clarified (act-r-proxy-mapping.md)** — fixed correctly. The "How Does an Interaction Become a Chunk?" section now explicitly states that every gate produces a chunk, and "salience fields are populated only when surprise occurs... Non-surprise chunks have empty salience fields but are still stored."

- **Auto-approval distinction made explicit (act-r-proxy-memory.md, act-r-proxy-sensorium.md)** — fixed correctly. The root document's "What Changes" section includes a note distinguishing EMA-based auto-approval (skips inspection) from two-pass auto-approval (completes inspection). The sensorium document's "Learned Attention Over Time" section restates this distinction explicitly.

- **Surprise mechanism expanded to graded (act-r-proxy-sensorium.md, act-r-proxy-memory.md)** — fixed correctly. The "Surprise" section now describes three levels: action changed (strong, 2 LLM calls), confidence delta > 0.3 (moderate, 1 LLM call), neither (no surprise, no calls). SurpriseDelta.magnitude values 1.0/0.5/0.0 are present in the data structures section. The session lifecycle pseudocode reflects this three-way branch.

- **Two-pass delta noise acknowledged (act-r-proxy-sensorium.md)** — fixed correctly. The "A note on signal quality" paragraph is present after "The Delta" section. It acknowledges temperature 0 non-determinism and characterizes the binary surprise trigger as partly a robustness choice.

- **Cost model G=10 and G=20 rows removed (act-r-proxy-memory.md)** — fixed correctly. The summary table with specific G=10 and G=20 figures (which were incorrect in round 0) is absent. The cost model now presents a general formula with variables and a note that the full cost comparison must include output tokens.

- **376-chunk capacity basis stated (act-r-proxy-memory.md)** — fixed correctly. The text now reads: "reserving ~12,000 tokens for system prompt and gate content, the practical capacity is ~376 chunks." The arithmetic basis is explicit: (200,000 - 12,000) / 500 = 376. This is consistent with the correction requested.

- **"Deployed at scale" and Claude memory claims removed (act-r-proxy-mapping.md)** — fixed: the original unverifiable sentences are gone. Replaced with citations to Park et al. (2023), Nuxoll & West (HAI 2024), and Bhatia et al. (Frontiers 2026). However, the replacement citations introduce new errors — see "New Claims Verified" below.

- **"Low-fan spreading activation" phrasing removed (act-r-proxy-mapping.md, act-r-proxy-sensorium.md)** — fixed correctly. Neither document uses the phrase "low-fan spreading activation." The mapping document now explicitly notes that multi-dimensional retrieval is a novel design choice without published validation and that an ablation is planned.

- **AutoDiscovery wording (act-r-proxy-sensorium.md)** — fixed correctly. The text now reads "guiding hypothesis exploration" rather than "hypothesis ranking." The AutoDiscovery paper (Allen AI, NeurIPS 2025) is correctly described.

- **Memory Maintenance section added (act-r-proxy-mapping.md)** — present. Describes trace compaction, chunk pruning, and SQLite VACUUM. New content not verified against round-1 factcheck (introduced by synthesis), but the section is internally consistent and makes no specific external claims that require source verification.

- **Cold Start Behavior section added (act-r-proxy-mapping.md)** — present and coherent. No external claims.

- **Evaluation metrics and ablation plan added (act-r-proxy-memory.md)** — present. Four evaluation metrics and four ablations listed. No external claims.

---

## New Claims Verified

### HAI 2024 citation: "Nuxoll, A., & West, R. (2024). Human-Like Remembering and Forgetting in LLM Agents. HAI '24."

**Incorrect on author names; incorrect on conference year.**

The paper exists and is real. The correct citation is:

> Honda, Y., Fujita, Y., Zempo, K., & Fukushima, S. (2025). Human-Like Remembering and Forgetting in LLM Agents: An ACT-R-Inspired Memory Architecture. In *Proceedings of the 13th International Conference on Human-Agent Interaction* (HAI '25). ACM. DOI: 10.1145/3765766.3765803

- The authors "Nuxoll" and "West" do not appear in this paper. The actual authors are Honda, Fujita, Zempo, and Fukushima, affiliated with Japanese universities. "Nuxoll, A." and "West, R." are fabricated names — they do not correspond to this paper.
- The conference edition is HAI '25 (13th conference, held November 2025 in Yokohama, proceedings published January 2026), not "HAI '24" (which was the 12th conference).
- The paper did win Best Paper Award at HAI 2025, confirming its quality.
- The description in the document ("ACT-R base-level activation + cosine similarity for LLM agent memory retrieval") is directionally accurate for the paper's content. The paper does integrate ACT-R activation into LLM memory recall. The subject matter is right; the attribution is wrong.

**Severity: citation is unfixable as written. Both the author names and the conference year must be corrected.**

Source: https://dl.acm.org/doi/10.1145/3765766.3765803

### Frontiers 2026 citation: "Bhatia, S., et al. (2026). Integrating language model embeddings into the ACT-R cognitive modeling framework. Frontiers in Language Sciences."

**Incorrect on author names. Title and venue are correct. Content description is misleading.**

The paper exists. The correct citation is:

> Meghdadi, M., Duff, J., & Demberg, V. (2026). Integrating language model embeddings into the ACT-R cognitive modeling framework. *Frontiers in Language Sciences*, 5. DOI: 10.3389/flang.2026.1721326

- "Bhatia, S." is not an author on this paper. The first author is Meghdadi (Maryam Meghdadi, Saarland University). "Bhatia, S." is a fabricated first author.
- The title and venue are correct: the paper exists at Frontiers in Language Sciences, published February 23, 2026.
- The document's description says "Embedding-based replacement for hand-coded ACT-R associations." The actual paper is a psycholinguistics study about associative priming in the Lexical Decision Task — it uses LM embeddings to provide association metrics within the ACT-R framework for modeling how humans read and respond to word pairs. It is not about agent memory architecture or replacing hand-coded associations in an agent context. The paper's contribution is to psycholinguistic cognitive modeling, not to AI agent design. The description in the document overstates the relevance to TeaParty's use case and mischaracterizes the paper's purpose.

**Severity: citation is unfixable as written. The first author name must be corrected. The description should be revised to accurately reflect the paper's psycholinguistics focus, with a note that the relevance is the LM-embedding-as-ACT-R-association-metric pattern — not agent memory per se.**

Source: https://www.frontiersin.org/journals/language-sciences/articles/10.3389/flang.2026.1721326/full

### Park et al. (2023) citation: "Generative Agents: Interactive Simulacra of Human Behavior. UIST '23."

**Confirmed correct on authors, title, and venue.**

- Authors: Joon Sung Park, Joseph O'Brien, Carrie Jun Cai, Meredith Ringel Morris, Percy Liang, Michael S. Bernstein. The document uses "Park, S., et al." — the first author's surname is Park, given name Joon Sung. "Park, S." is incorrect (the S is not a surname initial; the given name is Joon Sung, surname Park). This is a minor formatting error, not a fabrication.
- Venue: UIST '23 (36th Annual ACM Symposium on User Interface Software and Technology). Confirmed.
- The document's description: "Weighted combination of recency, importance, and relevance with min-max normalization. Direct precedent for hybrid retrieval scoring." — confirmed accurate. Park et al. compute a retrieval score as a weighted sum of recency (exponential decay), importance (LLM-rated), and relevance (cosine similarity), with all three components normalized to [0, 1] via min-max scaling before combining. The normalization claim is specifically verified.
- The document also says Park et al. use "min-max normalization for the same problem" (scale mismatch between different signal types). This is confirmed: Park normalizes all three components to [0, 1] before weighting.

**Confirmed correct (minor author formatting issue: "Park, S." should be "Park, J.S." but this is conventional shorthand and not a factual error).**

Source: https://dl.acm.org/doi/10.1145/3586183.3606763

---

## Numerical Checks

No new numerical computations were introduced in the draft-1 revision. The G=10 and G=20 rows (which were incorrect in draft-0) were removed rather than corrected. The remaining cost model is expressed as a formula with variables — no specific row values to check. No new calculations appear in the other documents.

The 376-chunk capacity computation is now explicit: (200,000 - 12,000) / 500 = 376. This is arithmetically correct.

---

## Summary

The round-1 corrections were applied correctly across all four documents. The substantive design changes (graded surprise, normalization, trace rules, auto-approval distinction, embedding harmonization, cost model, etc.) all land as described in the changelog.

The two new citations introduced to replace the unverifiable claims have critical errors:

| Citation as written | Problem |
|---|---|
| Nuxoll & West (2024), HAI '24 | Authors fabricated; year wrong. Real paper: Honda et al. (2025), HAI '25. |
| Bhatia et al. (2026), Frontiers | First author fabricated. Real first author: Meghdadi. Paper is about psycholinguistics, not agent memory architecture. |

The Park et al. (2023) citation is correct on venue, title, and content. The author formatting "Park, S." is a minor issue.

The replacement citations were introduced specifically to address the round-1 finding that the "deployed at scale" and "Claude memory" claims were unverifiable. Replacing unverifiable claims with fabricated citations is a regression, not a fix. The citation issue must be corrected before these documents are published or shared externally.
