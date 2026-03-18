# Fact Check — Round 2

## Verified

- **:rt default is 0 (zero)** — confirmed as corrected from Round 1. Draft-1 act-r.md line 119 now correctly states: "The ACT-R default for `:rt` is 0 (zero). When `:rt` is explicitly set in tutorial examples, values range from 0 to -2 depending on the model." The Round 1 correction has been applied.

- **Cache write premium 1.25x** — confirmed from Round 1: Anthropic prompt caching has a 1.25x cache-write premium. Source: [Anthropic Pricing](https://platform.claude.com/docs/en/about-claude/pricing)

- **Cache read rate 10% (0.30/MTok vs 3.00/MTok)** — confirmed from Round 1: cache reads are 0.1x base input price. Source: [Anthropic Pricing](https://platform.claude.com/docs/en/about-claude/pricing)

- **Workspace-level cache isolation (as of February 2026)** — confirmed from Round 1: prompt caching switched from organization-level to workspace-level isolation on February 5, 2026. Draft-1 act-r-proxy-memory.md line 226 correctly states this.

- **Working memory capacity calculation (376 chunks)** — confirmed from Round 1: (200,000 - 12,000) / 500 = 376 chunks. Calculation is correct.

- **Dialog mode captures "how the human reasons"** — draft-1 act-r-proxy-mapping.md line 111 states "These chunks capture *how* the human reasons, not just *what* they decided" — this statement is aspirational but reasonable; no factual error.

- **Two-pass prediction logic** — the structure and motivation for prior/posterior comparison are sound and match cognitive modeling principles (inspection before decision).

## Incorrect

- **Cost calculation numbers ($0.35 current, $0.47 two-pass)** — The arithmetic in the worked example (draft-1 act-r-proxy-memory.md lines 289-294) does not check out. Recalculation:

  **Current design verification (correct):**
  - 10 gates × 9,000 tokens @ $3/MTok = $0.27 ✓
  - 10 × 500 output tokens @ $15/MTok = $0.075 ✓
  - Total: $0.345 ≈ $0.35 ✓

  **Two-pass with caching (incorrect):**
  - Cache write: (2,000 + 5,000) tokens × $3/MTok × 1.25 = 7,000 × ($3/1,000,000) × 1.25 = $0.02625 (document claims $26.25 — off by 1,000x)
  - Cached reads: (20 - 1) × 7,000 × $0.30/MTok = 133,000 × ($0.30/1,000,000) = $0.0399 (document claims $39.90 — off by 1,000x)
  - New gate content: 20 × 2,000 × $3/MTok = $0.12 ✓
  - Surprise extraction: 2 × 500 × $15/MTok = $0.015 ✓
  - Output: 20 × 500 × $15/MTok = $0.15 ✓
  - **Correct total: ~$0.33** (not $0.47)

  **Root cause:** The cache write and cache read lines appear to use a different unit convention (treating costs as if rates are per 1,000 tokens rather than per 1,000,000 tokens), inflating those line items by approximately 1,000x. The final sum of $0.47 is therefore incorrect. The actual total cost should be approximately $0.33, making the two-pass design roughly **equivalent to or slightly cheaper than** the current design (not 35% more expensive as claimed).

- **Claim: "incremental cost is roughly 35% more per session"** — This corollary claim (act-r-proxy-memory.md line 296) is incorrect. The corrected cost calculation shows the two-pass design at ~$0.33 per session vs. ~$0.35 for current, making it approximately **6% cheaper**, not 35% more expensive.

## Unverifiable

- **Petrov, A. (2006) citation and approximation formula B ≈ ln(n/(1-d)) - d*ln(L)** — The document cites: "Petrov, A. (2006). Computationally Efficient Approximation of the Base-Level Learning Equation in ACT-R. In *Proceedings of the Seventh International Conference on Cognitive Modeling* (ICCM '06)." The ICCM conference exists and 2006 is a plausible year. The approximation formula (using total presentations n and lifetime L) is consistent with ACT-R literature patterns for trace compaction. However, the exact formula attribution to Petrov (2006) and its precise form cannot be independently verified without access to the actual paper. The formula structure is mathematically reasonable as an approximation to the base-level learning equation, but attribution requires the source document.

  **Recommendation:** If citing a specific paper for a specific formula, either (a) verify direct access to the source, or (b) cite only the general methodology (e.g., "ACT-R standard approximation formulas") without attribution. The current citation is specific enough that readers might try to look up Petrov (2006) and find the formula doesn't match, creating loss of trust.

- **Meghdadi, Duff, & Demberg (2026) contribution re: LM embeddings as ACT-R association strengths** — Confirmed in Round 1. Present in draft-1 act-r-proxy-mapping.md and unchanged from draft-0.

## Numerical Checks

- **Base-level activation worked examples (act-r.md lines 57-73)** — Carry forward from Round 1, unchanged in draft-1. Both are correct (rounding to 3 decimals).

- **Working memory capacity: (200,000 - 12,000) / 500 = 376 chunks** — Confirmed in Round 1, unchanged in draft-1. Correct.

- **Cold start behavior description** — Draft-1 act-r-proxy-mapping.md line 169 adds: "The new system generates richer interaction data per gate (questions, responses, reasoning, structured chunks with embeddings) compared to a single binary outcome update, which means the memory populates faster in terms of information per interaction." This is qualitative reasoning, not a numerical claim, and is reasonable.

## Summary

**Critical issue:** The cost model worked example contains calculation errors that systematically understate the cost-effectiveness of the two-pass design. The two-pass approach appears to be cost-equivalent or slightly cheaper than the current design, not 35% more expensive. This reverses the economic framing in the document.

**Minor issue:** The Petrov (2006) citation is specific enough that readers may expect to verify it. If the paper is not readily accessible or if the formula attribution is uncertain, the citation should either be verified or generalized (cite the methodology without specific attribution).

**Confirmed:** The :rt default correction from Round 1 has been correctly applied in draft-1.
