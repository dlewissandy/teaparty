# Fact Check — Round 1

Sources checked: `act-r-proxy-memory.md`, `act-r.md`, `act-r-proxy-mapping.md`, `act-r-proxy-sensorium.md`

---

## Verified

- **Anderson, J. R., & Schooler, L. J. (1991). "Reflections of the environment in memory." Psychological Science, 2(6), 396-408.** — confirmed: paper exists, correct journal, volume, issue, and page range. [Sage abstract](https://journals.sagepub.com/doi/abs/10.1111/j.1467-9280.1991.tb00174.x); [PDF](https://users.cs.northwestern.edu/~paritosh/papers/KIP/AndersonSchooler1991ReflectionsOfEnvironmentOnMemory.pdf)

- **Anderson & Schooler (1991) data sources: New York Times headlines, child-directed speech, email** — confirmed: the paper analyzed three databases: word occurrences in NYT headlines, child-directed speech (CHILDES database, Hall & Tirre 1979 transcripts), and email message distribution. All three sources match the description in the documents.

- **Anderson, J. R., & Lebiere, C. (1998). The Atomic Components of Thought. Lawrence Erlbaum Associates.** — confirmed: book exists, correct publisher, Chapter 4 covers declarative memory. [Semantic Scholar](https://www.semanticscholar.org/paper/The-Atomic-Components-of-Thought-Anderson-Lebiere/084da26797ebaa448bab831eddabf50a96f4fe59)

- **Decay parameter d = 0.5 is the ACT-R standard** — confirmed: the :bll (base-level learning) parameter is "almost always set to 0.5" per ACT-R documentation; d = 0.5 is the empirically validated standard value across hundreds of ACT-R models. [ACT-R Unit 4 tutorial](http://act-r.psy.cmu.edu/wordpress/wp-content/themes/ACT-R/tutorials/unit4.htm)

- **Base-level activation equation B = ln(Σ t_i^(-d))** — confirmed: this is the standard ACT-R base-level learning equation. Multiple sources confirm that each access adds a trace that decays as t^(-d), and the log of the sum gives activation.

- **Latency parameters F = 1.0 and f = 1.0 as standard values** — confirmed: the latency factor (LF) defaults to 1.0 in ACT-R. The latency exponent was standardly 1.0 but has been deprecated since ACT-R 5. The document correctly notes these are "not needed for agents."

- **Prompt cache hits at 0.1x base input price (90% discount)** — confirmed: Anthropic pricing page states cache read (hit) costs 0.1× base input price, i.e., 10% of standard rate. [Anthropic Pricing](https://platform.claude.com/docs/en/about-claude/pricing)

- **Cache hit example: "0.30/MTok instead of 3.00/MTok for Sonnet"** — confirmed: Claude Sonnet base input = $3.00/MTok; cache hit = $0.30/MTok. The example is arithmetically correct.

- **5-minute default cache TTL** — confirmed: Anthropic's 5-minute cache write is 1.25× base input price, and is documented as a 5-minute duration. [Anthropic Pricing](https://platform.claude.com/docs/en/about-claude/pricing)

- **ACT-R retrieval noise follows a logistic distribution** — confirmed: noise in ACT-R is generated from a logistic distribution characterized by parameter s, per Anderson & Lebiere (1998) and the official tutorials.

- **Property: "at d = 0.5, a single trace loses half its contribution when the interaction count quadruples"** — confirmed by algebra: (4T)^(-0.5) = T^(-0.5) × (1/2). The claim is correct.

- **Anderson & Schooler (1991) analysis is "event-based"** — partially confirmed: the paper analyzed word occurrences by temporal proximity (days, not seconds), and is consistently described in secondary literature as demonstrating a power-law in event recency. The connection between the empirical data analysis and the "event-based" framing of the interaction counter is a reasonable interpretation, though the paper's primary unit is days for the NYT/email analysis, not discrete events.

- **Allen AI AutoDiscovery uses Bayesian surprise** — confirmed: "AutoDiscovery: Open-ended Scientific Discovery via Bayesian Surprise" is a real paper from Allen AI (AI2), presented at NeurIPS 2025. [arXiv](https://arxiv.org/abs/2507.00310); [GitHub](https://github.com/allenai/autodiscovery). The document's description is accurate: it uses Bayesian surprise (KL divergence between prior and posterior) to rank discoveries.

- **Worked example 1, first pass:** B = ln(2^(-0.5) + 10^(-0.5) + 50^(-0.5)) = ln(0.707 + 0.316 + 0.141) = ln(1.164) = 0.152 — confirmed correct.

- **G=5 two-pass with cache total = 34,300** — confirmed correct by the formula:
  - First prefix: 7,000
  - 9 × 0.1 × 7,000 = 6,300
  - 10 × 2,000 = 20,000
  - 0.2 × 5 × 2 × 500 = 1,000
  - Total = 34,300 ✓

- **G=3 two-pass with cache total = 23,100; savings = 14%** — confirmed:
  - 7,000 + 5×700 + 12,000 + 600 = 23,100 ✓; vs. current 27,000 → 14.4% ≈ 14% ✓

- **Current (no two-pass): G=5 → 45,000; G=10 → 90,000; G=20 → 180,000** — all confirmed: G × 9,000.

- **Two-pass no cache: G=5 → 90,000** — confirmed: 10 × 9,000 = 90,000.

---

## Incorrect

- **"Noise parameter s standardly set to 0.25"** (act-r.md, Standard Parameter Values table) — the ACT-R `:ans` (activation noise) parameter has no universal standard numeric value; its default is NIL (disabled). When enabled in tutorial examples, the value used is 0.5, not 0.25. The document's claim of 0.25 as the "standard value" is not supported by ACT-R documentation. The 0.25 value is used in some models, but there is no single standard, and the most commonly demonstrated tutorial value is 0.5. Source: [ACT-R Unit 4 tutorial](http://act-r.psy.cmu.edu/wordpress/wp-content/themes/ACT-R/tutorials/unit4.htm); [ACT-R reference manual](http://act-r.psy.cmu.edu/actr7.x/reference-manual.pdf)

- **"Retrieval threshold τ standardly set to -0.5"** (act-r.md, Standard Parameter Values table) — the `:rt` parameter default in ACT-R is NIL (disabled), not -0.5. When tutorials enable it, the demonstrated value is typically 0, not -0.5. The -0.5 value appears in some model-fitting contexts but is not the canonical "standard value." Source: ACT-R Unit 4 tutorial (search result summary): "the retrieval threshold (the :rt parameter) is set to its default value of 0" in tutorial demonstrations.

- **G=10 two-pass with cache total: document states 62,600** — computed value is 62,300:
  - First prefix: 7,000
  - (2×10 − 1) × 0.1 × 7,000 = 19 × 700 = 13,300
  - 2×10 × 2,000 = 40,000
  - 0.2 × 10 × 2 × 500 = 2,000
  - Actual total = 62,300, not 62,600 (error of 300)

- **G=20 two-pass with cache total: document states 119,200** — computed value is 118,300:
  - First prefix: 7,000
  - (2×20 − 1) × 0.1 × 7,000 = 39 × 700 = 27,300
  - 2×20 × 2,000 = 80,000
  - 0.2 × 20 × 2 × 500 = 4,000
  - Actual total = 118,300, not 119,200 (error of 900)

- **G=10 savings: document states 30%** — with corrected total 62,300 vs. current 90,000: savings = (90,000 − 62,300) / 90,000 = 30.8% ≈ 31%. The documented figure of 30% is approximately correct but mildly inconsistent with the stated total of 62,600, which would give (90,000 − 62,600)/90,000 = 30.4%. Either way the savings figure rounds to ~30-31%; this is a minor rounding inconsistency flowing from the incorrect total.

- **G=20 savings: document states 34%** — with corrected total 118,300 vs. current 180,000: savings = (180,000 − 118,300)/180,000 = 34.3% ≈ 34%. With the document's stated total of 119,200: (180,000 − 119,200)/180,000 = 33.8% ≈ 34%. The savings percentage rounds to 34% under both totals; the stated percentage is correct despite the incorrect total.

---

## Unverifiable

- **"Activation-weighted embedding retrieval is the pattern underlying modern AI memory systems, including Claude's own persistent memory."** (act-r-proxy-mapping.md) — reason: no public documentation describes Claude's internal persistent memory architecture as using activation-weighted embedding retrieval. Claude's memory tool (when used) stores text; the internal retrieval mechanism is not publicly specified. The claim may be aspirational or an inference from general AI memory system design, but cannot be verified from public sources.

- **"The approach is deployed at scale."** (act-r-proxy-mapping.md, same passage) — reason: no citation or source is provided, and the claim that this specific hybrid (ACT-R activation + embedding cosine) approach is in production at scale cannot be verified.

- **Prompt cache "matching is account-level, not session-level — two separate API calls with the same prefix hit the cache, even from different processes"** (act-r-proxy-memory.md) — partially verified: Anthropic documentation confirms that caches are shared within the same workspace/organization, and that identical prefixes across separate requests do hit the cache. However, the claim that `claude -p` subprocess calls with identical system prompts will produce cache hits against each other is not documented. The CLI may add per-call variation (timestamps, session IDs) that breaks prefix matching. The document itself acknowledges this in the "Verification Needed" section, which is appropriate.

- **"At ~500 tokens per chunk and a 200K context window, the theoretical max is ~376 chunks."** (act-r-proxy-memory.md) — reason: 200,000 / 500 = 400, not 376. The arithmetic does not match with the stated assumptions. If the document is accounting for system prompt overhead (e.g., ~12,000 tokens for system prompt leaving ~188,000 for chunks: 188,000/500 = 376), that accounting is plausible but the basis is unstated.

- **"This is the same principle that Allen AI's AutoDiscovery uses for hypothesis ranking"** (act-r-proxy-sensorium.md) — reason: AutoDiscovery uses Bayesian surprise for hypothesis *prioritization* during open-ended scientific discovery, not "hypothesis ranking" in the sense of ordering a fixed set. The analogy to the proxy's prior-posterior shift is structurally sound (both use KL divergence / prediction change as a salience signal), but the characterization "hypothesis ranking" does not precisely match AutoDiscovery's use of Bayesian surprise for exploration policy. Verified the paper exists and uses Bayesian surprise; the description is an approximation rather than a precise claim.

- **Standard noise value s = 0.25 claim attribution to Anderson & Lebiere (1998)** — reason: the book is not freely available for text search; cannot confirm or deny whether 0.25 appears specifically in that text. What is confirmed is that the ACT-R implementation's default is NIL and tutorial demonstrations use 0.5. Whether 0.25 appears in the 1998 book as a recommended value cannot be verified from accessible sources.

---

## Numerical Checks

- **B = ln(2^(-0.5) + 10^(-0.5) + 50^(-0.5)) = ln(0.707 + 0.316 + 0.141) = ln(1.164) = 0.152** — correct: 2^(-0.5) = 0.70711, 10^(-0.5) = 0.31623, 50^(-0.5) = 0.14142, sum = 1.16476, ln(1.16476) = 0.1524.

- **B = ln(1^(-0.5) + 3^(-0.5) + 11^(-0.5) + 51^(-0.5)) = ln(1.000 + 0.577 + 0.302 + 0.140) = ln(2.019) = 0.703** — correct within rounding: 1^(-0.5) = 1.0, 3^(-0.5) = 0.57735, 11^(-0.5) = 0.30151, 51^(-0.5) = 0.14003, sum = 2.01889, ln(2.01889) = 0.70175. The document states 0.703; actual is 0.702 (rounding difference at third decimal; negligible).

- **Cost model, G=5, two-pass with cache = 34,300** — correct. Formula verified above.

- **Cost model, G=3, two-pass with cache = 23,100; savings = 14%** — correct.

- **Cost model, G=10, two-pass with cache: document states 62,600** — incorrect: correct value is 62,300. The formula with the stated parameters yields 7,000 + 13,300 + 40,000 + 2,000 = 62,300.

- **Cost model, G=20, two-pass with cache: document states 119,200** — incorrect: correct value is 118,300. The formula yields 7,000 + 27,300 + 80,000 + 4,000 = 118,300.

- **"~376 chunks" at 500 tokens/chunk in 200K context** — incorrect by the stated assumptions: 200,000 / 500 = 400, not 376. A value of 376 is consistent with a usable context of ~188,000 tokens (reserving ~12,000 for system prompt and gate content), but that accounting is not stated.

- **"d = 0.5: a single trace loses half its contribution when the interaction count quadruples"** — correct: (4T)^(-0.5) = 2^(-1) × T^(-0.5) = T^(-0.5) / 2.
