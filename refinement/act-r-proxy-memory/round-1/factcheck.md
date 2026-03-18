# Fact Check — Round 1

## Verified

- **Anderson & Schooler (1991) citation** — confirmed: "Reflections of the environment in memory," *Psychological Science*, 2(6), 396-408 is correct. The paper analyzes statistical patterns in environmental sources (New York Times headlines, child-directed speech, email) and shows they match human memory patterns. Source: [SAGE Journals](https://journals.sagepub.com/doi/abs/10.1111/j.1467-9280.1991.tb00174.x), [Northwestern PDF](https://users.cs.northwestern.edu/~paritosh/papers/KIP/AndersonSchooler1991ReflectionsOfEnvironmentOnMemory.pdf)

- **d = 0.5 as ACT-R standard** — confirmed: 0.5 is the standard value for the base-level learning decay parameter across ACT-R models. Multiple sources confirm "0.5 the standard value" used across a large range of applications. Source: ACT-R Tutorial Unit 4, ACT-R Reference Manual, Wikipedia ACT-R article

- **:ans default is NIL** — confirmed: the default for the noise parameter `:ans` is NIL (disabled). When enabled, the subsymbolic computation system uses it. Source: ACT-R Reference Manual

- **:rt default** — the document claims ":rt is NIL (disabled)." The ACT-R Reference Manual indicates the default value for `:rt` is 0 (zero), not NIL. The document's claim that the default is NIL appears to be **incorrect** — see "Incorrect" section below.

- **Park et al. (2023) citation** — confirmed: "Generative Agents: Interactive Simulacra of Human Behavior" was published at UIST '23. Authors: Joon Sung Park, Joseph C. O'Brien, Carrie J. Cai, Meredith Ringel Morris, Percy Liang, Michael S. Bernstein. Source: [ACM DL](https://dl.acm.org/doi/fullHtml/10.1145/3586183.3606763)

- **Park et al. use recency, importance, relevance with min-max normalization** — confirmed: the paper normalizes all three scores to [0,1] using min-max scaling and combines them with equal weights (alpha = 1 for all three). The formula is `score = α_recency * recency + α_importance * importance + α_relevance * relevance`. Relevance uses cosine similarity on embeddings. Source: [arXiv version](https://ar5iv.labs.arxiv.org/html/2304.03442)

- **Honda et al. (2025) citation** — confirmed: "Human-Like Remembering and Forgetting in LLM Agents: An ACT-R-Inspired Memory Architecture" published in HAI '25 proceedings. DOI 10.1145/3765766.3765803 resolves to the ACM Digital Library. Best Paper Award confirmed via [XperLab announcement](https://www.xpercept.aclab.esys.tsukuba.ac.jp/index.php/2025/11/17/hai2025-best-paper/). Source: [ACM DL](https://dl.acm.org/doi/10.1145/3765766.3765803)

- **Meghdadi, Duff, & Demberg (2026) citation** — confirmed: "Integrating language model embeddings into the ACT-R cognitive modeling framework" published in *Frontiers in Language Sciences*, 5. DOI 10.3389/flang.2026.1721326. Authors and affiliations match. Source: [Frontiers](https://www.frontiersin.org/journals/language-sciences/articles/10.3389/flang.2026.1721326/full)

- **Anthropic prompt caching: 1.25x cache write premium (5-minute TTL)** — confirmed: 5-minute cache writes are 1.25x base input price. Source: [Anthropic Pricing](https://platform.claude.com/docs/en/about-claude/pricing)

- **Anthropic prompt caching: 10% cache read rate** — confirmed: cache reads are 0.1x base input price (10% of standard). For Sonnet: $0.30/MTok vs $3.00/MTok standard. Source: [Anthropic Pricing](https://platform.claude.com/docs/en/about-claude/pricing)

- **Anthropic prompt caching: 5-minute default TTL** — confirmed. Source: [Anthropic Pricing](https://platform.claude.com/docs/en/about-claude/pricing)

- **Anderson & Lebiere (1998) citation** — confirmed: *The Atomic Components of Thought*, Lawrence Erlbaum Associates. This is the standard ACT-R reference. Source: widely cited across ACT-R literature

- **Base-level activation equation B = ln(sum t_i^(-d))** — confirmed: this is the standard ACT-R base-level learning equation from Anderson & Lebiere (1998) Chapter 4 and the ACT-R tutorials. Source: ACT-R Tutorial Unit 4

- **Retrieval probability equation P = 1/(1+exp(-(B-tau)/s))** — confirmed: this is the standard ACT-R soft retrieval threshold (logistic function). The document cites it as "Anderson & Lebiere, 1998, eq. 4.4." Source: ACT-R literature and tutorials

## Incorrect

- **":rt default is NIL"** (act-r.md, line 117) — The document states: "The ACT-R default for `:rt` is NIL (disabled)." The ACT-R Reference Manual indicates the default for `:rt` is **0** (zero), not NIL. The retrieval threshold defaults to 0 when subsymbolic computation is enabled (`:esc t`). It is effectively irrelevant when subsymbolic computation is disabled (the default), but the parameter itself defaults to 0, not NIL. This conflates "subsymbolic computation is disabled by default" with ":rt defaults to NIL." The :ans parameter does default to NIL, but :rt does not.

- **"Cache matching is account-level"** (act-r-proxy-memory.md, line 221) — The document states: "Cache matching is account-level, not session-level." As of February 5, 2026, Anthropic changed prompt caching to use **workspace-level isolation** instead of organization-level isolation. The document's claim was accurate for earlier versions but is now outdated. Source: [Anthropic Pricing](https://platform.claude.com/docs/en/about-claude/pricing) — "Starting February 5, 2026, prompt caching will use workspace-level isolation instead of organization-level isolation."

## Unverifiable

- **Anderson & Schooler's decay exponent value** — The document claims Anderson & Schooler (1991) found a power-law exponent "near 0.5." The PDF was not machine-readable via web fetch. Secondary sources reference a "forgetting rate" of 0.126 from the paper, which is not 0.5. The d = 0.5 value is the ACT-R standard parameter validated across models (confirmed above), but attributing it specifically to Anderson & Schooler (1991) as an empirical finding (as opposed to an ACT-R modeling convention) requires direct access to the paper. The document's caveat in act-r.md (line 91) that d = 0.5 is "a principled starting point" partially hedges this, but the earlier stronger claim (act-r.md, line 87) that Anderson & Schooler "showed that this value... matches the statistical structure of the real world" may overstate what the 1991 paper actually demonstrated.

- **Honda et al. page numbers (pp. 229-237)** — the DOI resolves but ACM DL returned 403 on fetch. The page range could not be independently verified. The conference proceedings, DOI, and Best Paper Award are all confirmed from other sources.

- **"ACT-R Tutorial Unit 4" reinforcement rules** — The document cites specific claims about when chunks are reinforced ("only when specifically retrieved for a task and actively referenced by a production rule — not merely by being present in working memory"). The tutorial page at the cited URL did not return readable content (it's an index page directing to downloaded materials). The claim is consistent with standard ACT-R descriptions but could not be verified against the specific cited source.

- **Allen AI AutoDiscovery** (act-r-proxy-sensorium.md, line 58) — The document references "the same principle that Allen AI's AutoDiscovery uses for guiding hypothesis exploration." No verification was attempted as this is a tangential comparison, not a load-bearing claim.

## Numerical Checks

- **Worked example 1** (act-r.md, lines 57-64):
  ```
  B = ln(2^(-0.5) + 10^(-0.5) + 50^(-0.5))
    = ln(0.7071 + 0.3162 + 0.1414)
    = ln(1.1647)
    = 0.1526
  ```
  Document says 0.152. **Correct** (rounding to 3 decimal places).

- **Worked example 2** (act-r.md, lines 66-73):
  ```
  B = ln(1^(-0.5) + 3^(-0.5) + 11^(-0.5) + 51^(-0.5))
    = ln(1.0000 + 0.5774 + 0.3015 + 0.1400)
    = ln(2.0189)
    = 0.7023
  ```
  Document says 0.703. **Correct** (rounding to 3 decimal places).

- **"At d = 0.5, a single trace loses half its contribution when the interaction count quadruples"** (act-r.md, line 82):
  ```
  At t=1: 1^(-0.5) = 1.000
  At t=4: 4^(-0.5) = 0.500
  ```
  1.000 → 0.500 is exactly half. **Correct**.

- **Working memory capacity calculation** (act-r-proxy-memory.md, line 286):
  ```
  (200,000 - 12,000) / 500 = 376 chunks
  ```
  **Correct**.

- **Cost model token estimates** (act-r-proxy-memory.md, lines 255-258):
  ```
  Current design input: G × (P + M + C) = G × (2000 + 5000 + 2000) = G × 9,000
  ```
  **Correct**.
