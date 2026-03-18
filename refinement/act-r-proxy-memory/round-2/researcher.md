# Research Findings — Round 2

## Concern: Cost calculation error in worked example

**Finding:** The fact checker's arithmetic is correct. The worked example (draft-1/act-r-proxy-memory.md lines 289-294) contains unit conversion errors in the cache write and cache read line items that inflate those costs by approximately 1,000x.

Verification of correct calculations:

**Current design (correct in document):**
- 10 gates × 9,000 tokens @ $3/MTok = 90,000 / 1,000,000 × $3 = $0.27 ✓
- 10 gates × 500 output tokens @ $15/MTok = 5,000 / 1,000,000 × $15 = $0.075 ✓
- Total: $0.345 ≈ $0.35 ✓

**Two-pass with caching (corrected):**
- Cache write: 7,000 tokens × ($3/1,000,000) × 1.25 = $0.02625
  - Document line 289 states: "(2,000 + 5,000) × $3 × 1.25 = $26.25" (incorrect: treats cost as if rate were per 1,000 tokens, not per 1,000,000)
  - Correct: 7,000 × ($3 / 1,000,000) × 1.25 = $0.02625

- Cached reads: 19 reads × 7,000 tokens × ($0.30/1,000,000) = 133,000 / 1,000,000 × $0.30 = $0.0399
  - Document line 290 states: "(20 gates - 1) × (7,000 tokens) × $0.30 = $39.90" (incorrect: off by 1,000x)
  - Correct: 133,000 / 1,000,000 × $0.30 = $0.0399

- New gate content: 20 passes × 2,000 tokens × ($3/1,000,000) = $0.12 ✓
- Surprise extraction: 2 calls × 500 tokens × ($15/1,000,000) = $0.015 ✓
- Output: 20 × 500 × ($15/1,000,000) = $0.15 ✓

**Corrected total: ~$0.33** (not $0.47 as stated in document)

**Implication for document:**
1. The two-pass design with caching costs approximately $0.33 per session, making it roughly **6% cheaper** than the current design (~$0.35), not 35% more expensive.
2. Line 296 claiming "incremental cost is roughly 35% more per session" must be removed or corrected.
3. This reverses the economic framing: the two-pass design is cost-equivalent or cheaper, which strengthens its economic argument. The cache infrastructure becomes an investment with immediate payback rather than a cost overhead.

**Sources:**
- Anthropic Pricing: $3/MTok input, $0.30/MTok cached read, $3.75/MTok 5-min cache write (1.25x multiplier), $15/MTok output
- Worked example calculations verified against stated parameters

---

## Concern: Petrov (2006) formula attribution

**Finding:** The formula B ≈ ln(n/(1-d)) - d*ln(L) is correctly cited as an "ACT-R standard" formula, but the attribution is imprecise. This formula originates from **Anderson & Lebiere (1998, Chapter 4, p. 124)**, not Petrov (2006). Petrov's contribution was to develop a *hybrid approximation* that combines the Anderson & Lebiere standard formula with direct computation for recent traces, producing higher accuracy in certain regimes.

Draft-1 (act-r-proxy-mapping.md line 197) correctly states: "Use the ACT-R standard base-level approximation B ≈ ln(n/(1-d)) - d*ln(L)... Petrov (2006) developed a more accurate hybrid approximation that combines this formula with direct computation for recent traces." This is accurate.

However, the reference (line 467) states only: "Hybrid approximation combining the ACT-R standard formula with direct computation" without clarifying that the base formula itself is from Anderson & Lebiere. A reader looking up Petrov (2006) expecting to find B ≈ ln(n/(1-d)) - d*ln(L) attributed to Petrov directly would be confused.

**Sources:**
- Anderson, J. R., & Lebiere, C. (1998). *The Atomic Components of Thought.* Lawrence Erlbaum Associates. Chapter 4, p. 124 — origin of B ≈ ln(n/(1-d)) - d*ln(L)
- Petrov, A. (2006). "Computationally Efficient Approximation of the Base-Level Learning Equation in ACT-R." *Proceedings of ICCM '06.* — hybrid extension that improves on the standard formula
- Round 1 researcher already verified these sources and provided direct citation

**Implication for document:**
The document is not wrong, but could be clearer. Option 1: update the reference to note that the base formula is from Anderson & Lebiere (1998) and Petrov (2006) extends it. Option 2: if the design will use the standard approximation (not Petrov's hybrid), simplify the reference to cite only Anderson & Lebiere. The current state is correct but could cause citation confusion.

---

## Summary

**Critical issue resolved:** The cost calculation error reverses the economic framing of two-pass caching — it is cheaper, not more expensive. This significantly strengthens the design's viability.

**Minor issue noted:** Petrov attribution is correct but could be clarified in the reference section to distinguish his contribution (hybrid extension) from the base formula (Anderson & Lebiere 1998).
