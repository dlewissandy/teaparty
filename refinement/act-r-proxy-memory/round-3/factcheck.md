# Fact Check — Round 3

Scope: Verify corrected cost calculation and formula attribution in draft-2.

---

## Cost Calculation (act-r-proxy-memory.md, lines 307-315)

### Changed Claim
Draft-1 claimed two-pass with caching costs ~$0.47 per session, making it "roughly 35% more expensive."
Draft-2 corrects this to ~$0.33 per session, making it "roughly 6% cheaper."

### Verification

**Parameters given (Sonnet pricing):**
- Input: $3/MTok
- Cached read: $0.30/MTok
- Output: $15/MTok
- Cache-write premium: 1.25x
- 10 gates per session

**Current design (no caching):**
- 10 gates × 9,000 input tokens = 90,000 input @ $3/MTok
  - Cost: 90,000 / 1,000,000 × $3 = $0.27
- 10 gates × 500 output tokens = 5,000 output @ $15/MTok
  - Cost: 5,000 / 1,000,000 × $15 = $0.075
- **Total: $0.345 ≈ $0.35** ✓ CORRECT

**Two-pass with caching (draft-2 formula):**

Cache write (first call):
- (P + M) = 2,000 + 5,000 = 7,000 tokens
- Cost: 7,000 / 1,000,000 × $3 × 1.25 = $0.02625 ✓ CORRECT
  (Draft-1 error: $26.25 results from treating $3 as $3,000,000/MTok conversion)

Cached reads (remaining calls):
- 2G - 1 = 2(10) - 1 = 19 reads
- Cost: 19 × 7,000 / 1,000,000 × $0.30 = $0.0399 ✓ CORRECT
  (Draft-1 error: $39.90 from same unit mistake)

New gate content (per-pass):
- 2G × 2,000 = 20 × 2,000 = 40,000 tokens @ full price
- Cost: 40,000 / 1,000,000 × $3 = $0.12 ✓ CORRECT

Surprise extraction (20% rate):
- 2 gates × 500 tokens @ output rate
- Cost: 2 × 500 / 1,000,000 × $15 = $0.015 ✓ CORRECT

Output (20 passes):
- 20 × 500 = 10,000 tokens @ $15/MTok
- Cost: 10,000 / 1,000,000 × $15 = $0.15 ✓ CORRECT

**Draft-2 total: $0.02625 + $0.0399 + $0.12 + $0.015 + $0.15 = $0.33115 ≈ $0.33** ✓ CORRECT

### Assessment
The cost calculation is correct. The unit conversion error in draft-1 was catastrophic (treating MTok as thousands instead of millions). The corrected calculation reverses the economic framing as claimed in the changelog: two-pass caching is now cost-equivalent (~6% cheaper), not more expensive.

---

## Formula Attribution (act-r-proxy-mapping.md, lines 198 & act-r.md, lines 29, 173-175)

### Changed Claim
Draft-1 cited Anderson & Lebiere (1998) p. 124 for the base-level approximation.
Draft-2 updates this to:
- Anderson & Lebiere (1998, Chapter 4) for the base formula B = ln(Σ t_i^(-d))
- Petrov (2006) for the hybrid approximation combining the formula with direct computation for recent traces

### Verification

**Base formula source:**
The equation B = ln(Σ t_i^(-d)) is definitional to ACT-R's base-level activation. Anderson & Lebiere (1998) *The Atomic Components of Thought*, Chapter 4, develops and justifies this equation as the core of ACT-R's declarative memory system. ✓ CORRECT

**Petrov (2006) attribution:**
The draft-2 documents reference "Petrov (2006)" generically without a full citation. The claim that Petrov developed a "hybrid approximation" is theoretically sound — it is an established approach in ACT-R modeling to combine the exact formula for recent data with approximations for older data — but the specific reference cannot be verified from the draft without seeing the full citation.

**Assessment for present task:** The key claim changed is the tracing equation source. The shift from "p. 124" (a specific page) to "Chapter 4" (a section) is more accurate, as the derivation spans the chapter, not a single page. The Petrov attribution cannot be verified without a full citation in the documents, but the conceptual claim (hybrid approximation combining exact + approximate computation) is methodologically sound. This is a low-priority issue for a fact check focused on calculations and verifiable citations. If Petrov's work needs formal citation, it should be added to the References sections with a full publication record.

---

## Minor Prose Changes

EMA coupling (act-r-proxy-memory.md, line 204-205): The draft-2 clarification ("EMA and the memory system operate on separate data paths...") accurately restates the relationship without making false claims of independence. ✓ CORRECT

---

## Summary

**Cost calculation:** Corrected and verified to be accurate. The unit conversion error was caught and fixed. The new economic framing is sound.

**Formula attribution:** Base formula correctly attributed to Anderson & Lebiere (1998, Chapter 4). Petrov (2006) reference is mentioned but lacks a full citation entry — should be added to References sections if presented as a formal source.

**Verdict:** All factual claims changed between draft-1 and draft-2 are correct or defensible. No errors detected in the corrected cost model.
