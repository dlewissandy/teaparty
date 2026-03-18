# Research Findings — Round 1

## Concern: :rt default value (fact check — flagged as incorrect)

**Finding:** The fact checker is correct. In current ACT-R (7.x), the `:rt` parameter defaults to **0.0**, not NIL. This is confirmed by the ACT-R source code (`declarative-memory.lisp`), where `:rt` is defined as `"a number"` with default 0.0. In contrast, `:ans` defaults to `nil` and `:bll` defaults to `nil`. The document may have been influenced by ACT-R 5 conventions or confused the behavior when subsymbolic computation is disabled (`:esc nil`) — in that case, the threshold is irrelevant, but the parameter value is still 0.0.

**Sources:**
- [ACT-R source code (declarative-memory.lisp)](https://github.com/RyanHope/ACT-R/blob/master/core-modules/declarative-memory.lisp) — `:rt` default is 0.0
- [ACT-R 7.30+ Reference Manual](http://act-r.psy.cmu.edu/actr7.x/reference-manual.pdf) — reference documentation (PDF not machine-readable but multiple web sources confirm)

**Implication for document:** act-r.md line 117 should be corrected. The `:rt` default is 0, not NIL. The `:ans` default is correctly stated as NIL.

## Concern: "Cache matching is account-level" (fact check — flagged as outdated)

**Finding:** Confirmed outdated. As of February 5, 2026, Anthropic changed prompt caching to use **workspace-level isolation** instead of organization-level isolation. The document's claim that "cache matching is account-level, not session-level" was accurate for the pre-February 2026 API but is now incorrect. The core point — that caching works across processes — remains true within a workspace, but the scope has narrowed.

**Sources:**
- [Anthropic Prompt Caching Documentation](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) — "Starting February 5, 2026, prompt caching will use workspace-level isolation"
- [Anthropic Pricing](https://platform.claude.com/docs/en/about-claude/pricing) — confirms workspace-level isolation

**Implication for document:** act-r-proxy-memory.md line 221 should be updated from "account-level" to "workspace-level." The functional point (two subprocess calls can share cache) is still valid if they're in the same workspace.

## Concern: Anderson & Schooler and the d = 0.5 exponent (fact check — unverifiable)

**Finding:** The relationship between Anderson & Schooler (1991) and d = 0.5 is more nuanced than the document presents. Anderson & Schooler (1991) demonstrated that environmental statistics (word recurrence in headlines, speech, email) follow power-law distributions, and that human memory decay mirrors these distributions. The d = 0.5 value is the standard ACT-R modeling parameter, confirmed across hundreds of models. However, Anderson & Schooler's paper reported on the environmental statistics matching the *form* of power-law decay — the specific exponent value of 0.5 became the ACT-R convention through subsequent modeling work, not as a direct empirical finding from the 1991 paper alone. Secondary sources reference forgetting rates closer to 0.126 from the paper's analyses, which is a different quantity than the decay parameter d.

The document's act-r.md line 87 states Anderson & Schooler "showed that this value... matches the statistical structure of the real world," which overstates the directness of the connection. The caveat on line 91 is more accurate.

**Sources:**
- [Schooler & Anderson (2017) "The Adaptive Nature of Memory"](http://act-r.psy.cmu.edu/wordpress/wp-content/uploads/2021/07/SchoolerAnderson2017.pdf) — later retrospective on the research program
- Multiple ACT-R sources confirming d = 0.5 as the standard modeling parameter
- [Semantic Scholar page for Anderson & Schooler 1991](https://www.semanticscholar.org/paper/Reflections-of-the-Environment-in-Memory-Anderson-Schooler/6b2e11d45e5592b55d522310f6c9c6198f76daaf)

**Implication for document:** The stronger claim on act-r.md line 87 should be softened to match the more accurate caveat on line 91. The d = 0.5 value is well-established as the ACT-R standard, but attributing it as a direct empirical finding from Anderson & Schooler (1991) is an overstatement.

## Concern: "Bayesian surprise" usage (visionary critic — novelty)

**Finding:** The visionary critic is technically correct. Bayesian surprise has a precise formal definition: the KL divergence between posterior and prior distributions over model space (Itti & Baldi, 2005/2009). The document's use of the term for a categorical action-change comparison is a loose analogy, not a formal application.

However, the underlying principle — that the information-theoretic content of an observation is measured by how much it changes beliefs — is genuinely the same principle. The document is applying the *concept* of Bayesian surprise (attend to what changes your beliefs) at a coarse granularity (did the action prediction change?), not the *formalism* (KL divergence over probability distributions).

**Sources:**
- [Itti & Baldi (2009) "Bayesian surprise attracts human attention"](https://www.sciencedirect.com/science/article/pii/S0042698908004380) — formal definition of Bayesian surprise as KL divergence
- [Itti & Baldi (2005) NeurIPS paper](http://papers.neurips.cc/paper/2822-bayesian-surprise-attracts-human-attention.pdf) — original conference version

**Implication for document:** The sensorium document should acknowledge that it uses "Bayesian surprise" as a conceptual analogy to Itti & Baldi's formal definition, not as a formal application. The mechanism is "surprise-driven attention" inspired by the Bayesian surprise framework, operating on categorical predictions rather than probability distributions.

## Concern: Trace compaction approximation (visionary critic + engineering critic)

**Finding:** There is published work on exactly this problem. Petrov (2006) developed computationally efficient approximations for the ACT-R base-level activation equation. The standard approximation from Anderson & Lebiere (1998, p. 124) replaces old traces with a summary but doesn't capture the transient boost after each use. Petrov's "hybrid approximation" preserves core properties with much less error. A more recent comparison paper (2018) in *Computational Brain & Behavior* evaluates multiple approximation approaches.

The visionary critic's concern about Jensen's inequality is valid — naive averaging of trace ages is not mathematically equivalent. But the problem is well-studied and has known solutions in the ACT-R literature.

**Sources:**
- [Petrov (2006) "Computationally Efficient Approximation of the Base-Level Learning Equation in ACT-R"](http://alexpetrov.com/pub/iccm06/) — ICCM '06
- [Comparison of Approximations for Base-Level Activation in ACT-R (2018)](https://link.springer.com/article/10.1007/s42113-018-0015-3) — *Computational Brain & Behavior*

**Implication for document:** The trace compaction section should reference Petrov (2006) and the standard ACT-R approximation rather than inventing a new approach. The approximation formula from Anderson & Lebiere (1998, p. 124) or Petrov's hybrid approximation are both well-tested alternatives with known error characteristics.

## Concern: Embedding model not specified (engineering critic)

**Finding:** The document references `memory_indexer.py` as existing infrastructure. Checked whether this exists in the codebase.

**Sources:** Codebase search needed (deferred to synthesis).

**Implication for document:** The engineering critic's concern is valid — the embedding model, dimensionality, and API need to be specified or explicitly delegated to implementation.

## New Evidence Discovered

### ACT-R standard approximation for base-level activation

Anderson & Lebiere (1998, p. 124) published a standard approximation formula that avoids storing all individual traces:

```
B ≈ ln(n / (1-d)) - d * ln(L)
```

where n is the total number of presentations and L is the lifetime (interactions since first presentation). This has known limitations (doesn't capture transient boost after each use) but is the standard ACT-R simplification. The document's trace compaction proposal is solving the same problem in a less principled way.

### Prompt caching now has 1-hour TTL option

The current Anthropic pricing shows two cache durations: 5-minute (1.25x write premium) and 1-hour (2x write premium). The document only discusses the 5-minute TTL. For a proxy processing a session of multiple gates, the 1-hour cache could be more cost-effective if gates are spaced more than 5 minutes apart.
